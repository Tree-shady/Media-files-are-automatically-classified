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
import math
from collections import deque

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


# 进度条类
class ProgressBar:
    def __init__(self, total, desc="处理中", bar_length=50, unit='文件'):
        self.total = total
        self.desc = desc
        self.bar_length = bar_length
        self.unit = unit
        self.lock = threading.Lock()
        self.start_time = time.time()
        self.completed = 0
        self.last_update = 0
        self.speed_history = deque(maxlen=10)  # 速度历史（平滑显示）

        # 初始显示
        if total > 0:
            self._print()

    def update(self, num=1):
        """更新进度"""
        with self.lock:
            self.completed += num
            current_time = time.time()
            elapsed = current_time - self.last_update

            # 每0.2秒或当完成时更新一次，避免刷新太频繁
            if elapsed >= 0.1 or self.completed >= self.total:
                self._print()
                self.last_update = current_time

    def increment(self):
        """增加一个完成项（简化方法）"""
        self.update(1)

    def _format_speed(self):
        """计算并格式化处理速度"""
        total_elapsed = time.time() - self.start_time
        if total_elapsed > 0:
            items_per_sec = self.completed / total_elapsed
            self.speed_history.append(items_per_sec)
            avg_speed = sum(self.speed_history) / len(self.speed_history)

            # 根据速度大小选择适当的单位
            if avg_speed > 100:
                return f"{avg_speed:.0f} {self.unit}/秒"
            elif avg_speed > 0.1:
                return f"{avg_speed:.1f} {self.unit}/秒"
            else:
                return f"{avg_speed:.2f} {self.unit}/秒"
        return ""

    def _print(self):
        """打印当前进度条"""
        if self.total == 0:
            return

        progress = min(1.0, self.completed / self.total)
        filled_length = int(round(self.bar_length * progress))

        # 创建进度条字符串
        bar = '▓' * filled_length + '░' * (self.bar_length - filled_length)
        percent = min(100.0, progress * 100.0)

        ratio_str = f"{self.completed}/{self.total}"
        speed_str = self._format_speed()
        time_remaining = self._calc_remaining() if progress > 0 else "计算中..."

        # 构建完整输出行
        line = f"\r{self.desc}: {percent:5.1f}% |{bar}| {ratio_str} {speed_str} (剩余: {time_remaining})"

        # 确保行尾清除其他字符
        clear_length = max(80, self.bar_length + 80)
        spaces = " " * clear_length
        print(f"\r{spaces}\r{line}", end='', flush=True)

        # 当完成时换行
        if self.completed >= self.total:
            print()

    def _calc_remaining(self):
        """计算预计剩余时间"""
        elapsed = time.time() - self.start_time
        if self.completed > 0 and elapsed > 0:
            time_per = elapsed / self.completed
            remaining = time_per * (self.total - self.completed)

            # 格式化剩余时间为用户友好的格式
            if remaining < 60:  # 秒级
                return f"{remaining:.0f}秒"
            elif remaining < 3600:  # 分钟级
                return f"{remaining / 60:.1f}分钟"
            else:  # 小时级
                return f"{remaining / 3600:.1f}小时"
        return ""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.total > 0 and self.completed < self.total:
            self._print()  # 确保即使未完成也显示最后状态
        return False


# 优化常量
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.heic', '.tiff', '.nef', '.cr2', '.arw', '.dng')
VIDEO_EXTENSIONS = ('.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.3gp', '.m4v', '.mts', '.mpg', '.mpeg')
ALL_EXTENSIONS = IMAGE_EXTENSIONS + VIDEO_EXTENSIONS

# 扩展名字典用于快速查找
EXT_MAP = {ext: 1 for ext in ALL_EXTENSIONS}


# 线程安全的统计对象
class ProcessingStats:
    def __init__(self, total_files):
        self.lock = threading.Lock()
        self.files_moved = 0
        self.files_skipped = 0
        self.files_failed = 0
        self.files_processed = 0
        self.total_files = total_files
        self.start_time = time.time()
        self.last_log_time = self.start_time
        self.last_count = 0

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
                'elapsed': elapsed,
                'total': self.total_files
            }

    def log_progress(self, force=False):
        """记录进度（每分钟或当强制时）"""
        current_time = time.time()
        with self.lock:
            if force or (current_time - self.last_log_time > 60 or self.files_processed == self.total_files):
                percent = (self.files_processed / self.total_files) * 100
                speed = (self.files_processed - self.last_count) / max(1, current_time - self.last_log_time)

                logger.info(
                    f"进度: {percent:.1f}% ({self.files_processed}/{self.total_files}) | "
                    f"速度: {speed:.1f}文件/秒 | "
                    f"成功: {self.files_moved} | "
                    f"跳过: {self.files_skipped} | "
                    f"失败: {self.files_failed}"
                )

                self.last_log_time = current_time
                self.last_count = self.files_processed


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

            # 预定义的日期标签ID列表
            date_tag_ids = {
                36867: "DateTimeOriginal",  # EXIF日期时间原始值
                36868: "DateTimeDigitized",  # EXIF数字化日期时间
                306: "DateTime",  # TIFF/EP 标准日期时间

                # 相机特定标签
                50934: "OlympusDate",  # Olympus日期时间
                50937: "OlympusDateTime",  # Olympus日期时间(长格式)
                32781: "DateTimeCreated",  # 创建日期时间(某些相机)
            }

            for tag_id, tag_name in date_tag_ids.items():
                value = exif_data.get(tag_id)
                if value:
                    try:
                        # 清理可能的问题字符
                        clean_value = ''.join(c for c in value.strip() if c.isprintable())
                        # 尝试分割日期部分
                        date_part = clean_value.split()[0]
                        return datetime.datetime.strptime(date_part[:10], "%Y-%m-%d").date()
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
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

        if result.returncode == 0:
            # 尝试解析输出中的日期值
            for date_str in result.stdout.splitlines():
                date_str = date_str.strip()
                if not date_str:
                    continue

                # 尝试所有可能的日期格式
                formats = [
                    "%Y-%m-%dT%H:%M:%S",  # ISO格式 (GoPro/iPhone)
                    "%Y%m%d",  # 紧凑格式 (Sony相机)
                    "%Y/%m/%d %H:%M:%S",  # 目录/时间格式
                    "%d-%b-%Y",  # Nikon格式 (01-JAN-2023)
                    "%Y:%m:%d %H:%M:%S"  # EXIF格式的视频
                ]

                for fmt in formats:
                    try:
                        # 清理不规则字符
                        clean_date = ''.join(c for c in date_str if c.isprintable())
                        # 处理时区/微秒部分
                        date_parts = clean_date.split('.')[0].split('+')
                        dt_str = date_parts[0].replace('T', ' ')
                        dt = datetime.datetime.strptime(dt_str, fmt)
                        return dt.date()
                    except ValueError:
                        continue

        # 尝试从文件名解析日期（常见于数码相机）
        basename = os.path.basename(video_path)
        if len(basename) >= 8 and basename[:8].isdigit():
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

        # 尝试从文件名解析日期
        basename = os.path.basename(media_path)

        # 常见文件名模式（20230105_123456.jpg）
        for pattern in ["%Y%m%d", "%Y-%m-%d", "%Y_%m_%d"]:
            if len(basename) >= 10:
                for start in range(0, max(1, len(basename) - 10)):
                    date_str = basename[start:start + 8]
                    if len(date_str) < 8:
                        continue

                    if pattern == "%Y_%m_%d" and date_str[4] == '_' and date_str[7] == '_':
                        date_str = date_str[:4] + date_str[5:7] + date_str[8:10]

                    if pattern == "%Y-%m-%d" and date_str[4] == '-' and date_str[7] == '-':
                        date_str = date_str[:4] + date_str[5:7] + date_str[8:10]

                    # 验证可能的日期格式
                    if date_str.isdigit() and len(date_str) == 8:
                        year = int(date_str[0:4])
                        month = int(date_str[4:6])
                        day = int(date_str[6:8])

                        # 验证日期有效性（非严格验证）
                        if 1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31:
                            return datetime.date(year, month, day)

        # 最后使用缓存的文件修改时间
        timestamp = get_cached_file_timestamp(media_path)
        return datetime.datetime.fromtimestamp(timestamp).date()
    except Exception as e:
        logger.debug(f"日期获取错误 {os.path.basename(media_path)}: {str(e)}")
        return datetime.date(1970, 1, 1)  # 回退到epoch时间


def generate_unique_filename(target_dir, base_name, extension):
    """生成唯一文件名（解决冲突）"""
    counter = 1
    base, orig_ext = os.path.splitext(base_name)
    if not extension:
        extension = orig_ext

    # 首选原始文件名
    new_filename = base_name

    while os.path.exists(os.path.join(target_dir, new_filename)):
        # 尝试计数器
        new_filename = f"{base}_{counter}{extension}"
        counter += 1

        # 如果冲突严重，添加短哈希
        if counter > 10:  # 防止无限循环
            file_hash = hashlib.md5(f"{base}{time.time()}{counter}".encode()).hexdigest()[:6]
            new_filename = f"{base}_{file_hash}{extension}"

        # 最终保护
        if counter > 100:
            new_filename = f"{base}_{int(time.time())}{extension}"

    return os.path.join(target_dir, new_filename)


def file_hash(filepath, block_size=65536):
    """计算文件的快速哈希值（仅文件开头）"""
    hasher = hashlib.md5()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(block_size), b''):
            hasher.update(chunk)
            if hasher.digest_size > 0:  # 只读16K足够识别差异
                break
    return hasher.hexdigest()[:8]  # 短哈希减少比较开销


def calculate_target_path(file_info, target_base_dir, stats, progress_bar=None):
    """计算文件的目标路径，同时更新统计信息"""
    filename, source_path = file_info

    try:
        # 检查源文件是否仍然存在
        if not os.path.exists(source_path):
            logger.warning(f"文件已消失: {filename} (跳过)")
            stats.skipped()
            return None

        # 获取文件大小（用于进度统计）
        file_size = os.path.getsize(source_path)

        # 计算文件日期和目标文件夹
        media_date = get_media_date_fast(source_path)
        date_folder = media_date.strftime("%Y-%m-%d")
        target_dir = os.path.join(target_base_dir, date_folder)
        os.makedirs(target_dir, exist_ok=True)

        # 获取实际扩展名
        base, orig_ext = os.path.splitext(filename)
        ext_lower = orig_ext.lower()
        extension = None

        # 查找实际文件扩展名
        for ext in ALL_EXTENSIONS:
            if filename.lower().endswith(ext):
                extension = ext
                break
        if extension is None:
            extension = orig_ext

        # 初始目标路径
        target_path = os.path.join(target_dir, filename)

        # 检查目标文件是否存在
        if not os.path.exists(target_path):
            return (source_path, target_path, date_folder, file_size)

        # 如果已存在，检查是否是相同文件
        if file_hash(source_path) == file_hash(target_path):
            logger.debug(f"跳过重复文件: {filename}")
            stats.skipped()
            return None

        # 生成唯一文件名
        target_path = generate_unique_filename(target_dir, filename, extension)

        return (source_path, target_path, date_folder, file_size)

    except Exception as e:
        logger.error(f"计算路径失败 {filename}: {str(e)}", exc_info=False)
        stats.failed()
        return None
    finally:
        # 更新进度条（如果有）
        if progress_bar:
            progress_bar.increment()


def process_file(file_task, stats, progress_bar=None):
    """安全地处理单个文件（移动操作），更新统计信息"""
    if file_task is None:
        return False

    source_path, target_path, date_folder, file_size = file_task
    filename = os.path.basename(source_path)

    try:
        # 双重检查源文件
        if not os.path.exists(source_path):
            logger.warning(f"源文件已消失: {filename} (跳过)")
            stats.skipped()
            return False

        # 移动文件
        shutil.move(source_path, target_path)
        new_filename = os.path.basename(target_path)
        logger.info(f"✓ 已移动: {filename} -> {date_folder}/{new_filename}")
        stats.moved()
        return True
    except Exception as e:
        logger.error(f"✗ 移动失败: {filename} - 错误: {str(e)}", exc_info=False)
        stats.failed()
        return False
    finally:
        # 更新进度条（如果有）
        if progress_bar:
            progress_bar.increment()


def organize_media(source_dir, target_base_dir=None, verbose=False, max_workers=None):
    """主函数：按日期整理媒体文件（图片+视频）"""
    setup_logging(verbose)

    # 设置目标目录
    if target_base_dir is None:
        target_base_dir = source_dir

    if not os.path.exists(target_base_dir):
        os.makedirs(target_base_dir)
        logger.info(f"创建新目标目录: {os.path.abspath(target_base_dir)}")

    logger.info(f"⭐ 开始媒体整理（包含视频） @ {os.path.abspath(source_dir)}")
    logger.info(f"🖥️ 系统信息: Python {sys.version} on {sys.platform}")
    logger.info(f"⚙️ 配置: 目标目录={os.path.abspath(target_base_dir)} | 详细模式={'是' if verbose else '否'}")

    # 1. 扫描媒体文件
    logger.info("🔍 开始扫描媒体文件...")
    start_scan = time.time()
    media_files = []
    total_size = 0
    skipped_dirs = []

    # 用于扫描进度的虚拟进度条
    scan_stats = ProcessingStats(total_files=float('inf'))
    last_log_time = time.time()

    # 递归扫描所有文件
    for root, dirs, files in os.walk(source_dir):
        # 跳过系统目录（以.开头或特殊目录）
        if os.path.basename(root).startswith('.') or os.path.basename(root) == '__MACOSX':
            skipped_dirs.append(root)
            continue

        for file in files:
            # 检查文件扩展名
            file_ext = os.path.splitext(file)[1].lower()
            if file_ext in EXT_MAP:
                file_path = os.path.join(root, file)
                file_size = 0

                try:
                    # 获取文件大小
                    file_size = os.path.getsize(file_path)
                    total_size += file_size
                    # 添加到处理列表
                    media_files.append((file, file_path))
                except OSError:
                    pass  # 跳过无法访问的文件

                # 每隔5秒或每500个文件记录一次进度
                current_time = time.time()
                if current_time - last_log_time > 5 and len(media_files) % 500 == 0:
                    logger.info(
                        f"扫描进度: 已找到 {len(media_files):,}个文件 ({total_size / 1024 / 1024:.1f} MB)"
                    )
                    last_log_time = current_time

    # 扫描完成
    if skipped_dirs:
        logger.debug(f"⚠️ 跳过 {len(skipped_dirs)} 个系统目录")

    scan_time = time.time() - start_scan
    logger.info(
        f"📊 扫描完成! 找到 {len(media_files):,}个媒体文件 ({total_size / 1024 / 1024:.1f} MB) "
        f"耗时: {scan_time:.1f}秒 ({len(media_files) / max(scan_time, 0.01):.1f}文件/秒)"
    )

    # 没有文件时提前返回
    if not media_files:
        logger.info("❗ 没有找到可处理的媒体文件，程序退出")
        return

    # 2. 设置全局统计
    global_stats = ProcessingStats(total_files=len(media_files))

    # 3. 并行处理计算目标路径
    logger.info("🧠 计算目标路径...")
    compute_tasks = []

    # 自动计算合适的线程数
    worker_count = max_workers or min(32, max(4, int(len(media_files) / 100) + 1))
    logger.info(f"🔧 使用 {worker_count} 个线程进行日期计算")

    # 创建计算进度条
    with ProgressBar(total=len(media_files),
                     desc="计算文件日期",
                     unit="文件") as compute_bar:

        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as compute_executor:
            # 提交所有计算任务
            future_to_file = {}
            for file_info in media_files:
                future = compute_executor.submit(
                    calculate_target_path,
                    file_info,
                    target_base_dir,
                    global_stats,
                    compute_bar
                )
                future_to_file[future] = file_info[0]

            # 批量等待结果
            try:
                for future in concurrent.futures.as_completed(future_to_file):
                    filename = future_to_file[future]
                    try:
                        task = future.result()
                        if task:
                            compute_tasks.append(task)
                    except Exception as e:
                        logger.debug(f"路径计算错误 {filename}: {str(e)}")
            except KeyboardInterrupt:
                logger.warning("用户中止计算任务!")
                return

    # 4. 处理无效/跳过的任务
    valid_tasks = [t for t in compute_tasks if t is not None]
    if len(valid_tasks) != len(media_files):
        diff = len(media_files) - len(valid_tasks)
        logger.info(f"⚠️ 跳过 {diff} 个文件（重复或无法处理）")

    if not valid_tasks:
        logger.info("❗ 没有有效的文件需要移动")
        return

    logger.info(f"🚀 开始移动 {len(valid_tasks):,} 个文件...")

    # 5. 并行处理文件移动
    # I/O操作使用较少线程
    io_workers = min(worker_count, 8)

    # 移动进度条
    total_bytes = sum(t[3] for t in valid_tasks)
    desc_text = f"移动文件 ({total_bytes / 1024 / 1024:.1f} MB)"

    with ProgressBar(total=len(valid_tasks), desc=desc_text, unit="文件") as move_bar:

        with concurrent.futures.ThreadPoolExecutor(max_workers=io_workers) as move_executor:
            # 提交所有移动任务
            io_futures = []
            for task in valid_tasks:
                future = move_executor.submit(
                    process_file,
                    task,
                    global_stats,
                    move_bar
                )
                io_futures.append(future)

            # 等待任务完成，同时每分钟记录一次详细状态
            while io_futures:
                # 分批等待10个子任务完成
                batch = []
                for _ in range(min(64, len(io_futures))):
                    if io_futures:
                        batch.append(io_futures.pop(0))

                if batch:
                    _, done = concurrent.futures.wait(
                        batch,
                        timeout=5,
                        return_when=concurrent.futures.FIRST_COMPLETED
                    )

                    # 处理已完成的子任务
                    for future in list(done):
                        try:
                            future.result()  # 触发异常（如果有）
                        except Exception:
                            pass  # 错误已在任务内部处理

                    # 记录详细进度
                    global_stats.log_progress()

    # 6. 最终性能报告
    stats = global_stats.get_stats()
    elapsed = stats['elapsed']

    # 计算各种速率
    file_rate = stats['processed'] / elapsed if elapsed > 0 else 0
    mb_rate = total_bytes / (1024 * 1024) / elapsed if elapsed > 0 else 0

    # 生成最终报告
    summary = [
        "=" * 70,
        "⭐ 整理完成!",
        "=" * 70,
        f"📊 统计数据:",
        f"  总耗时: {elapsed:.1f}秒",
        f"  已处理: {stats['processed']}/{stats['total']} ({stats['processed'] / stats['total'] * 100:.1f}%)",
        f"  成功移动: {stats['moved']}个文件",
        f"  跳过/重复: {stats['skipped']}个文件",
        f"  处理失败: {stats['failed']}个文件",
        "",
        f"⚡ 性能指标:",
        f"  速度: {file_rate:.1f}文件/秒 | {mb_rate:.1f} MB/秒",
        "",
        f"🗂️ 目标位置: {os.path.abspath(target_base_dir)}",
        "=" * 70
    ]

    for line in summary:
        logger.info(line)


def run_cli():
    """命令行入口函数"""
    import argparse

    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="📸🎥 媒体整理工具 v7.0 - 高级进度条版",
        epilog="""使用示例:
  基本用法: 
    python organizer.py 
  指定源目录: 
    python organizer.py --source ~/Photos
  指定目标目录: 
    python organizer.py --target ~/Sorted_Photos
  高性能模式: 
    python organizer.py --workers 12
  调试模式: 
    python organizer.py --verbose""")

    parser.add_argument("--source", default=os.getcwd(),
                        help="源目录（默认为当前目录）", metavar="PATH")
    parser.add_argument("--target", default=None,
                        help="目标目录（默认在源目录中整理）", metavar="PATH")
    parser.add_argument("--verbose", action="store_true",
                        help="显示详细日志（调试用）")
    parser.add_argument("--workers", type=int, default=8,
                        help="并行工作线程数（默认8）", metavar="N")

    # 添加ASCII艺术欢迎界面
    banner = r"""
███████╗ ██████╗███████╗██████╗  ██████╗ ██████╗ ██╗   ██╗
██╔════╝██╔════╝██╔════╝██╔══██╗██╔═══██╗██╔══██╗╚██╗ ██╔╝
███████╗██║     █████╗  ██████╔╝██║   ██║██████╔╝ ╚████╔╝ 
╚════██║██║     ██╔══╝  ██╔══██╗██║   ██║██╔══██╗  ╚██╔╝  
███████║╚██████╗███████╗██║  ██║╚██████╔╝██║  ██║   ██║   
╚══════╝ ╚═════╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝   ╚═╝   
    """

    args = parser.parse_args()

    print(f"\n\033[96m{banner}\033[0m")
    print(f"\033[96m{'=' * 70}\033[0m")
    print(f"📷📹 媒体整理工具 v7.0 - 专业进度条版")
    print(f"\033[96m{'=' * 70}\033[0m")
    print(f"🔍 源目录  : \033[92m{os.path.abspath(args.source)}\033[0m")
    if args.target:
        print(f"📁 目标目录: \033[92m{os.path.abspath(args.target)}\033[0m")
    else:
        print(f"📁 目标目录: \033[93m源目录内整理\033[0m")
    print(f"⚙️  并行线程: \033[93m{args.workers}\033[0m")
    print(f"🔧 详细模式: \033[93m{'是' if args.verbose else '否'}\033[0m")
    print(f"\033[96m{'=' * 70}\033[0m\n")

    try:
        organize_media(
            source_dir=args.source,
            target_base_dir=args.target,
            verbose=args.verbose,
            max_workers=args.workers
        )
    except KeyboardInterrupt:
        print("\n\033[91m操作被用户中断!\033[0m")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\033[91m程序发生错误: {str(e)}\033[0m")
        if args.verbose:
            logger.debug(f"错误详情: {sys.exc_info()}")
        sys.exit(1)


if __name__ == "__main__":
    run_cli()
