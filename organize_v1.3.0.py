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

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

def setup_logging(verbose=False):
    """配置日志级别"""
    log_level = logging.DEBUG if verbose else logging.INFO
    logger.setLevel(log_level)

def get_cached_file_timestamp(filepath):
    """获取带缓存的文件时间戳（性能优化）"""
    try:
        # 缓存最近访问的文件时间戳（每个路径32个缓存项）
        return get_cached_file_timestamp.cache.get(filepath)
    except KeyError:
        timestamp = os.path.getmtime(filepath)
        get_cached_file_timestamp.cache[filepath] = timestamp
        return timestamp

# 为时间戳函数设置缓存（最多缓存1024个文件的时间戳）
get_cached_file_timestamp.cache = {}
get_cached_file_timestamp.cache = lru_cache(maxsize=1024)(lambda filepath: os.path.getmtime(filepath))

def get_image_exif_date(image_path):
    """从图片EXIF获取日期（单独函数便于重用和优化）"""
    try:
        with Image.open(image_path) as img:
            exif_data = img.getexif()
            
            if not exif_data:
                return None
            
            # 高效查找日期标签
            date_tag_ids = [tag_id for tag_id, tag_name in TAGS.items() 
                          if tag_name in ['DateTimeOriginal', 'DateTimeDigitized', 'DateTime']]
            
            date_str = None
            for tag_id in date_tag_ids:
                value = exif_data.get(tag_id)
                if value:
                    try:
                        # 尝试解析常见日期格式
                        date_str = value.strip()
                        if ':' in date_str:
                            date_part = date_str.split()[0].replace(":", "-")
                            return datetime.datetime.strptime(date_part, "%Y-%m-%d").date()
                    except (ValueError, TypeError):
                        continue
    except Exception as e:
        logger.debug(f"Error reading EXIF from {os.path.basename(image_path)}: {str(e)}")
    return None

def get_video_metadata_date(video_path):
    """获取视频文件的日期元数据"""
    try:
        cmd = [
            'ffprobe', '-v', 'error',
            '-show_entries', 'format_tags=creation_time',
            '-of', 'default=nw=1:nk=1',
            video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            date_str = result.stdout.strip()
            if date_str:
                # 尝试多种常用日期格式
                for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
                    try:
                        # 分割可能存在的毫秒部分
                        clean_date = date_str.split('.')[0]
                        dt = datetime.datetime.strptime(clean_date, fmt)
                        return dt.date()
                    except ValueError:
                        continue
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        logger.debug(f"视频元数据获取失败（{os.path.basename(video_path)}）：{str(e)}")
    return None

def get_media_date(media_path):
    """优化后的媒体日期获取函数"""
    # 图片文件优先尝试EXIF
    lower_path = media_path.lower()
    
    if any(ext in lower_path for ext in ('.jpg', '.jpeg', '.png', '.heic', '.tiff', '.nef', '.cr2', '.arw', '.dng')):
        exif_date = get_image_exif_date(media_path)
        if exif_date:
            return exif_date
        
    # 视频文件尝试获取元数据
    if any(ext in lower_path for ext in ('.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.3gp', '.m4v', '.mts')):
        video_date = get_video_metadata_date(media_path)
        if video_date:
            return video_date
    
    # 最后使用缓存的文件修改时间
    timestamp = get_cached_file_timestamp(media_path)
    return datetime.datetime.fromtimestamp(timestamp).date()

def calculate_target_path(file_info, target_base_dir):
    """计算文件的目标路径（避免重复处理）"""
    filename, source_path = file_info
    media_date = get_media_date(source_path)
    date_folder = media_date.strftime("%Y-%m-%d")
    target_dir = os.path.join(target_base_dir, date_folder)
    
    # 创建目标目录（如果不存在）
    os.makedirs(target_dir, exist_ok=True)
    
    # 处理文件名冲突
    new_path = os.path.join(target_dir, filename)
    if os.path.exists(new_path):
        base, ext = os.path.splitext(filename)
        counter = 1
        while True:
            new_filename = f"{base}_{counter}{ext}"
            new_path = os.path.join(target_dir, new_filename)
            if not os.path.exists(new_path):
                break
            counter += 1
    
    return (source_path, new_path, date_folder)

def process_file(file_task):
    """处理单个文件（移动操作）"""
    source_path, new_path, date_folder = file_task
    filename = os.path.basename(source_path)
    
    try:
        shutil.move(source_path, new_path)
        new_filename = os.path.basename(new_path)
        logger.info(f"✓ 已移动: {filename} -> {date_folder}/{new_filename}")
        return True
    except Exception as e:
        logger.error(f"✗ 移动失败: {filename} - 错误: {str(e)}")
        return False

def organize_media(source_dir, target_base_dir=None, verbose=False, max_workers=None):
    """主函数：按日期整理媒体文件（图片+视频）"""
    setup_logging(verbose)
    start_time = time.time()
    
    if target_base_dir is None:
        target_base_dir = source_dir
    
    # 支持的媒体格式（使用元组提高查找效率）
    valid_extensions = (
        # 图片格式
        '.jpg', '.jpeg', '.png', '.heic', '.tiff', '.nef', '.cr2', '.arw', '.dng',
        # 视频格式
        '.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.3gp', '.m4v', '.mts'
    )
    
    # 收集媒体文件列表（预过滤）
    media_files = []
    skipped_files = []
    
    logger.info(f"开始扫描目录: {os.path.abspath(source_dir)}")
    file_counter = 0
    for filename in os.listdir(source_dir):
        file_counter += 1
        filepath = os.path.join(source_dir, filename)
        
        if os.path.isdir(filepath):
            continue
        
        if filename.lower().endswith(valid_extensions):
            media_files.append((filename, filepath))
        else:
            skipped_files.append(filepath)
    
    # 多线程处理任务
    worker_count = max_workers or max(2, os.cpu_count() * 2)  # 默认CPU核心数×2
    logger.info(f"共找到 {len(media_files)} 个媒体文件，使用 {worker_count} 个并行任务")
    
    # 第一步：批量计算目标路径
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(worker_count, 12)) as executor:
        process_tasks = list(executor.map(
            lambda f: calculate_target_path(f, target_base_dir), 
            media_files
        ))
    
    # 第二步：执行文件移动（I/O密集型，适当减少线程数）
    moved_files = 0
    skipped_count = len(skipped_files)
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(worker_count, 6)) as executor:
        results = executor.map(process_file, process_tasks)
        moved_files = sum(1 for result in results if result)
    
    # 统计结果
    processed_count = len(media_files)
    error_count = processed_count - moved_files
    total_files = file_counter
    
    # 性能分析
    elapsed = time.time() - start_time
    file_rate = processed_count / elapsed if elapsed > 0 else 0
    
    # 打印总结
    logger.info("\n" + "=" * 70)
    logger.info(f"整理完成! 耗时: {elapsed:.2f}秒 ({file_rate:.1f}个文件/秒)")
    logger.info(f"总文件数: {total_files}")
    logger.info(f"✅ 媒体处理: {processed_count} (成功移动: {moved_files})")
    logger.info(f"⚠️ 跳过文件: {skipped_count} (非媒体格式)")
    logger.info(f"❌ 失败处理: {error_count}")
    logger.info("=" * 70)
    logger.info(f"目标位置: {os.path.abspath(target_base_dir)}")

def run_cli():
    """命令行入口函数"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="媒体整理工具 - 按日期分类照片和视频",
        epilog="示例: python organizer.py --source photos/ --target sorted/ --verbose"
    )
    parser.add_argument("--source", default=os.getcwd(), 
                        help="源目录（默认为当前目录）")
    parser.add_argument("--target", default=None, 
                        help="目标目录（默认为源目录）")
    parser.add_argument("--verbose", action="store_true", 
                        help="显示详细日志（调试用）")
    parser.add_argument("--workers", type=int, default=None,
                        help="并行工作线程数（默认自动设置）")
    
    args = parser.parse_args()
    
    print(f"\n📷📹媒体整理工具 v2.0 - 开始处理...")
    print(f"源目录: {os.path.abspath(args.source)}")
    if args.target:
        print(f"目标目录: {os.path.abspath(args.target)}")
    
    try:
        organize_media(
            source_dir=args.source,
            target_base_dir=args.target,
            verbose=args.verbose,
            max_workers=args.workers
        )
    except Exception as e:
        logger.error(f"程序发生错误: {str(e)}")
        import traceback
        if args.verbose:
            logger.debug(traceback.format_exc())

if __name__ == "__main__":
    run_cli()
