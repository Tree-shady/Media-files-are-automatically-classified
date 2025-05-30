import os
import shutil
from PIL import Image
from PIL.ExifTags import TAGS
import datetime
import subprocess
import concurrent.futures
import logging
import time
from functools import lru_cache
import sys
import hashlib
import threading
from collections import defaultdict

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# 优化常量
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.heic', '.tiff', '.nef', '.cr2', '.arw', '.dng')
VIDEO_EXTENSIONS = ('.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.3gp', '.m4v', '.mts')
ALL_EXTENSIONS = IMAGE_EXTENSIONS + VIDEO_EXTENSIONS

# 线程安全的统计对象
class ProcessingStats:
    def __init__(self):
        self.lock = threading.Lock()
        self.files_moved = 0
        self.files_skipped = 0
        self.files_failed = 0
        self.files_processed = 0
        self.start_time = time.time()
        
    def moved(self):
        with self.lock:
            self.files_moved += 1
            self.files_processed += 1
            
    def skipped(self):
        with self.lock:
            self.files_skipped += 1
            self.files_processed += 1
            
    def failed(self):
        with self.lock:
            self.files_failed += 1
            self.files_processed += 1
            
    def get_stats(self):
        with self.lock:
            elapsed = time.time() - self.start_time
            return {
                'moved': self.files_moved,
                'skipped': self.files_skipped,
                'failed': self.files_failed,
                'processed': self.files_processed,
                'elapsed': elapsed
            }

def setup_logging(verbose=False):
    """配置日志级别"""
    log_level = logging.DEBUG if verbose else logging.INFO
    logger.setLevel(log_level)

@lru_cache(maxsize=4096)
def get_cached_file_timestamp(filepath):
    """带缓存的文件修改时间获取（性能优化）"""
    try:
        return os.path.getmtime(filepath)
    except Exception:
        return time.time()

@lru_cache(maxsize=4096)
def get_image_exif_date(image_path):
    """从图片EXIF获取日期（带缓存）"""
    try:
        with Image.open(image_path) as img:
            exif_data = img.getexif()
            
            if not exif_data:
                return None
            
            # 预定义的日期标签ID列表（避免每次循环所有标签）
            date_tag_ids = {
                36867: "DateTimeOriginal",  # EXIF日期时间原始值
                36868: "DateTimeDigitized",  # EXIF数字化日期时间
                
                # 添加更多常见图片格式的特殊日期标签
                306: "DateTime",            # TIFF/EP 标准日期时间
                32943: "DateTimeOriginal",  # Olympus RAW
            }
            
            for tag_id, tag_name in date_tag_ids.items():
                value = exif_data.get(tag_id)
                if value:
                    try:
                        # 清理可能的控制字符并标准化日期格式
                        clean_value = value.strip().replace(':', '-', 2)
                        # 提取日期部分（忽略时间）
                        date_str = clean_value.split()[0]
                        return datetime.datetime.strptime(date_str[:10], "%Y-%m-%d").date()
                    except (ValueError, TypeError):
                        continue
    except Exception as e:
        logger.debug(f"EXIF读取错误 {os.path.basename(image_path)}: {str(e)}")
    return None

@lru_cache(maxsize=2048)
def get_video_metadata_date(video_path):
    """带缓存的视频元数据日期获取，支持更多格式"""
    try:
        cmd = [
            'ffprobe', '-v', 'error',
            '-show_entries', 'format_tags=creation_time :format_tags=creation_date',
            '-of', 'default=nokey=1:noprint_wrappers=1',
            video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            # 尝试解析输出中的日期值（可能有多个值）
            for date_str in result.stdout.splitlines():
                date_str = date_str.strip()
                if not date_str:
                    continue
                
                # 尝试所有可能的日期格式
                formats = [
                    "%Y-%m-%dT%H:%M:%S",   # ISO格式 (GoPro/iPhone)
                    "%Y%m%d",               # 紧凑格式 (Sony相机)
                    "%Y/%m/%d %H:%M:%S",    # 目录/时间格式
                    "%d-%b-%Y",             # Nikon格式 (01-JAN-2023)
                    "%Y:%m:%d %H:%M:%S",    # EXIF格式的视频（有些APP使用）
                    "%b %d %H:%M:%S %Y"     # 系统日志格式
                ]
                
                for fmt in formats:
                    try:
                        # 清理不规则字符
                        clean_date = ''.join(c for c in date_str if c.isprintable())
                        # 处理可能的时区/微秒部分
                        dt_str = clean_date.split('+')[0].split('.')[0]
                        dt = datetime.datetime.strptime(dt_str, fmt)
                        return dt.date()
                    except ValueError:
                        continue
        
        # 如果上述都没成功，尝试从文件名解析日期（常见于数码相机）
        basename = os.path.basename(video_path)
        if len(basename) >= 8 and basename[:4].isdigit() and basename[4:6].isdigit() and basename[6:8].isdigit():
            try:
                year = int(basename[0:4])
                month = int(basename[4:6])
                day = int(basename[6:8])
                return datetime.date(year, month, day)
            except ValueError:
                pass
                
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
        logger.debug(f"视频日期获取失败 {os.path.basename(video_path)}: {str(e)}")
    return None

def get_media_date_fast(media_path):
    """优化的日期获取策略（带缓存和回退）"""
    try:
        lower_path = media_path.lower()
        ext = os.path.splitext(lower_path)[1].lower()
        
        # 图片文件优先尝试EXIF
        if ext in IMAGE_EXTENSIONS:
            exif_date = get_image_exif_date(media_path)
            if exif_date:
                return exif_date
        
        # 视频文件尝试获取元数据
        if ext in VIDEO_EXTENSIONS:
            video_date = get_video_metadata_date(media_path)
            if video_date:
                return video_date
            
        # 尝试从文件名解析日期（如IMG_20230515_123456.jpg）
        basename = os.path.basename(media_path)
        for pattern in ["%Y%m%d", "%Y-%m-%d", "%Y_%m_%d"]:
            if len(basename) >= 10:
                for i in range(len(basename) - 10):
                    try:
                        dt = datetime.datetime.strptime(basename[i:i+10], pattern).date()
                        logger.debug(f"从文件名解析日期: {basename} -> {dt}")
                        return dt
                    except ValueError:
                        continue
                
        # 最后使用缓存的文件修改时间
        timestamp = get_cached_file_timestamp(media_path)
        return datetime.datetime.fromtimestamp(timestamp).date()
    except Exception as e:
        logger.error(f"日期获取错误 {os.path.basename(media_path)}: {str(e)}")
        return datetime.date.today()

def generate_unique_filename(target_dir, base_name, extension):
    """生成唯一文件名（解决冲突）"""
    counter = 1
    base, ext = os.path.splitext(base_name)
    if not extension:
        extension = ext
    
    while True:
        # 首选没有后缀的新文件名
        new_filename = base + extension
        
        # 如果多次失败，添加短哈希
        if counter > 3:
            file_hash = hashlib.md5(f"{base}{time.time()}".encode()).hexdigest()[:6]
            new_filename = f"{base}_{file_hash}{extension}"
            
        new_path = os.path.join(target_dir, new_filename)
        if not os.path.exists(new_path):
            return new_path
            
        counter += 1
        # 防止无限循环
        if counter > 100:
            raise RuntimeError("无法生成唯一的文件名")

def calculate_target_path(file_info, target_base_dir, stats):
    """计算文件的目标路径，同时更新统计信息"""
    filename, source_path = file_info
    
    try:
        # 首先检查源文件是否仍然存在
        if not os.path.exists(source_path):
            logger.warning(f"文件已消失: {filename}")
            stats.skipped()
            return None
            
        media_date = get_media_date_fast(source_path)
        date_folder = media_date.strftime("%Y-%m-%d")
        target_dir = os.path.join(target_base_dir, date_folder)
        os.makedirs(target_dir, exist_ok=True)
        
        # 获取文件扩展名
        base, orig_ext = os.path.splitext(filename)
        extension = None
        
        # 查找实际文件扩展名（处理双重扩展名如 .jpg.txt）
        if filename.lower().endswith(ALL_EXTENSIONS):
            for ext in ALL_EXTENSIONS:
                if filename.lower().endswith(ext):
                    extension = ext
                    break
        if extension is None:
            extension = orig_ext
        
        new_filename = filename
        
        # 生成唯一路径
        target_path = os.path.join(target_dir, new_filename)
        if os.path.exists(target_path):
            # 检查是否是相同文件（防止移动相同文件）
            if file_content_equal(source_path, target_path):
                logger.warning(f"跳过重复文件: {filename}")
                stats.skipped()
                return None
                
            # 生成唯一文件名
            target_path = generate_unique_filename(target_dir, filename, extension)
        
        return (source_path, target_path, date_folder)
    
    except Exception as e:
        logger.error(f"计算路径失败 {filename}: {str(e)}")
        stats.failed()
        return None

def file_content_equal(file1, file2):
    """比较两个文件内容是否相同（基于文件大小和哈希）"""
    if os.path.getsize(file1) != os.path.getsize(file2):
        return False
        
    try:
        hash1 = file_hash(file1)
        hash2 = file_hash(file2)
        return hash1 == hash2
    except Exception:
        return False

def file_hash(filepath, block_size=65536):
    """计算文件的快速哈希值"""
    hasher = hashlib.md5()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(block_size), b''):
            hasher.update(chunk)
    return hasher.hexdigest()

def process_file(file_task, stats):
    """安全地处理单个文件（移动操作），更新统计信息"""
    if file_task is None:
        return False
        
    source_path, target_path, date_folder = file_task
    filename = os.path.basename(source_path)
    
    try:
        # 双重检查源文件
        if not os.path.exists(source_path):
            logger.warning(f"源文件已消失: {filename}")
            stats.skipped()
            return False
            
        # 移动文件
        shutil.move(source_path, target_path)
        new_filename = os.path.basename(target_path)
        logger.info(f"✓ 已移动: {filename} -> {date_folder}/{new_filename}")
        stats.moved()
        return True
    except Exception as e:
        logger.error(f"✗ 移动失败: {filename} - 错误: {str(e)}")
        stats.failed()
        return False

def organize_media(source_dir, target_base_dir=None, verbose=False, max_workers=None):
    """主函数：按日期整理媒体文件（图片+视频）"""
    setup_logging(verbose)
    global_stats = ProcessingStats()
    
    if target_base_dir is None:
        target_base_dir = source_dir
    
    logger.info(f"🔍 开始整理媒体文件 @ {os.path.abspath(source_dir)}")
    
    # 1. 扫描媒体文件
    media_files = []
    total_size = 0
    skipped_dirs = []
    
    start_scan = time.time()
    for root, dirs, files in os.walk(source_dir):
        # 跳过系统目录
        if os.path.basename(root).startswith('.') or os.path.basename(root) == '@eaDir':
            skipped_dirs.append(root)
            continue
            
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext in ALL_EXTENSIONS:
                file_path = os.path.join(root, file)
                media_files.append((file, file_path))
                try:
                    total_size += os.path.getsize(file_path)
                except:
                    # 文件访问问题，跳过
                    continue
                    
    if skipped_dirs:
        logger.debug(f"跳过 {len(skipped_dirs)} 个系统目录")
    
    # 没有文件时提前返回
    if not media_files:
        logger.info("没有找到可处理的媒体文件，程序退出")
        return
        
    scan_time = time.time() - start_scan
    logger.info(f"📊 扫描完成! 找到 {len(media_files)} 个媒体文件 ({total_size/1024/1024:.1f} MB) 耗时: {scan_time:.1f}秒")
    
    # 2. 并行处理计算目标路径
    compute_tasks = []
    
    # 自动计算合适的线程数
    worker_count = max_workers or min(24, max(4, int(len(media_files) / 100)))
    logger.info(f"🚀 启动计算引擎 ({worker_count} 线程)")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as compute_executor:
        # 提交所有计算任务
        future_to_file = {}
        for file_info in media_files:
            future = compute_executor.submit(calculate_target_path, file_info, target_base_dir, global_stats)
            future_to_file[future] = file_info[0]
        
        # 批量获取结果（带进度显示）
        processed = 0
        last_report = time.time()
        
        for future in concurrent.futures.as_completed(future_to_file):
            filename = future_to_file[future]
            try:
                task = future.result()
                compute_tasks.append(task)
            except Exception as e:
                logger.error(f"路径计算错误 {filename}: {str(e)}")
                global_stats.failed()
                
            processed += 1
            
            # 每5秒显示一次进度
            current_time = time.time()
            if current_time - last_report > 5 or processed == len(media_files):
                last_report = current_time
                percent = processed / len(media_files) * 100
                logger.info(f"进度: 计算目标路径 {processed}/{len(media_files)} ({percent:.1f}%)")
    
    # 3. 并行处理文件移动
    # 过滤无效任务
    valid_tasks = [t for t in compute_tasks if t is not None]
    if len(valid_tasks) != len(media_files):
        diff = len(media_files) - len(valid_tasks)
        logger.warning(f"⚠️ 跳过 {diff} 个无法计算目标位置的文件")
    
    if not valid_tasks:
        logger.info("没有有效的文件需要移动")
        return
        
    logger.info(f"🔄 开始移动 {len(valid_tasks)} 个文件...")
    
    # I/O操作使用较少线程
    io_workers = min(worker_count, 8)
    logger.info(f"🚚 启动文件转移 ({io_workers} 线程)")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=io_workers) as move_executor:
        io_futures = []
        for task in valid_tasks:
            future = move_executor.submit(process_file, task, global_stats)
            io_futures.append(future)
            
        # 等待所有操作完成（简单方式）
        for future in concurrent.futures.as_completed(io_futures):
            # 结果处理在submit回调中完成
            pass
    
    # 生成最终报告
    stats = global_stats.get_stats()
    elapsed = stats['elapsed']
    file_rate = stats['processed'] / elapsed if elapsed > 0 else 0
    mb_rate = total_size / (1024 * 1024) / elapsed if elapsed > 0 else 0
    
    logger.info("\n" + "=" * 60)
    logger.info(f"⭐ 整理完成! 总耗时: {elapsed:.1f}秒")
    logger.info(f"📊 性能: {file_rate:.1f} 文件/秒, {mb_rate:.1f} MB/秒")
    logger.info(f"✅ 成功移动: {stats['moved']} 个文件")
    logger.info(f"⚠️ 跳过文件: {stats['skipped']} 个")
    if stats['failed'] > 0:
        logger.info(f"❌ 处理失败: {stats['failed']} 个文件")
    logger.info("=" * 60)
    logger.info(f"🏁 目标位置: {os.path.abspath(target_base_dir)}")

def run_cli():
    """命令行入口函数（带高级选项）"""
    import argparse
    
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="📸🎥 媒体整理工具 v5.0 - 高性能多线程分类引擎",
        epilog="""高级用法:
  批量处理嵌套目录: 
    python media_organizer.py --source archive/
  超大数据集优化:
    python media_organizer.py --source photos/ --workers 16
  网络存储加速:
    python media_organizer.py --source /mnt/nas/photos --target /ssd/temp_sorted
  调试模式:
    python media_organizer.py --source raw_files/ --verbose"""
    )
    parser.add_argument("--source", default=os.getcwd(), 
                        help="源目录（默认为当前目录）", metavar="PATH")
    parser.add_argument("--target", default=None, 
                        help="目标目录（默认在源目录中整理）", metavar="PATH")
    parser.add_argument("--verbose", action="store_true", 
                        help="显示详细日志（调试用）")
    parser.add_argument("--workers", type=int, default=8,
                        help="并行工作线程数（默认8）", metavar="N")
    
    args = parser.parse_args()
    
    print(f"\n{'='*60}")
    print(f"📷📹 媒体整理工具 v5.0 - 高性能分类引擎")
    print(f"{'='*60}")
    print(f"源目录  : {os.path.abspath(args.source)}")
    print(f"目标目录: {os.path.abspath(args.target if args.target else args.source)}")
    print(f"并行线程: {args.workers}")
    print(f"详细模式: {'是' if args.verbose else '否'}")
    print(f"{'='*60}\n")
    
    try:
        organize_media(
            source_dir=args.source,
            target_base_dir=args.target,
            verbose=args.verbose,
            max_workers=args.workers
        )
    except KeyboardInterrupt:
        print("\n操作被用户中断!")
        sys.exit(1)
    except Exception as e:
        logger.error(f"程序发生致命错误: {str(e)}", exc_info=args.verbose)
        sys.exit(1)

if __name__ == "__main__":
    run_cli()
