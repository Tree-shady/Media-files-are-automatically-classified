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
import platform

# ANSI颜色代码
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    
    # 进度条颜色
    PROGRESS_BAR = '\033[38;5;39m'  # 亮蓝色
    PROGRESS_TEXT = '\033[1;37m'    # 亮白色
    PROGRESS_VALUE = '\033[1;33m'   # 亮黄色
    PROGRESS_REMAINING = '\033[0;36m' # 青色

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# 高级进度条系统（固定位置）
class FixedProgressBar:
    def __init__(self, total, desc="处理中", bar_length=50, unit='文件', position='bottom'):
        """
        固定位置的进度条
        position: 'bottom' 或 'top'
        """
        self.total = total
        self.desc = desc
        self.bar_length = bar_length
        self.unit = unit
        self.position = position
        self.start_time = time.time()
        self.completed = 0
        self.last_update = 0
        self.speed_history = deque(maxlen=10)  # 速度历史（平滑显示）
        self.window_height = 25  # 默认控制台高度
        self.visible = False
        self.last_known_lines = 0
        
        # 获取终端高度
        self._get_terminal_size()
        
        if platform.system() == 'Windows':
            # Windows不支持一些ANSI序列，简化界面
            self.color_prefix = ""
            self.color_suffix = ""
        else:
            self.color_prefix = Colors.PROGRESS_TEXT
            self.color_suffix = Colors.ENDC
        
        if total > 0:
            # 初始化显示
            self._show()
    
    def _get_terminal_size(self):
        """获取终端大小"""
        try:
            from shutil import get_terminal_size
            ts = get_terminal_size()
            self.window_height = ts.lines
            return ts
        except:
            # 如果出错使用默认值
            self.window_height = 25
            return (80, 25)
    
    def update(self, num=1):
        """更新进度"""
        self.completed += num
        current_time = time.time()
        elapsed = current_time - self.last_update
        
        # 每0.1秒或当完成时更新一次
        if elapsed >= 0.1 or self.completed >= self.total:
            self._update_display()
            self.last_update = current_time
    
    def increment(self):
        """增加一个完成项（简化方法）"""
        self.update(1)
    
    def _format_speed(self):
        """计算并格式化处理速度"""
        total_elapsed = time.time() - self.start_time
        if total_elapsed > 0 and self.completed > 0:
            items_per_sec = self.completed / total_elapsed
            self.speed_history.append(items_per_sec)
            if self.speed_history:
                avg_speed = sum(self.speed_history) / len(self.speed_history)
            else:
                avg_speed = items_per_sec
            
            # 根据速度大小选择适当的单位
            if avg_speed > 100:
                return f"{avg_speed:.0f} {self.unit}/秒"
            elif avg_speed > 0.1:
                return f"{avg_speed:.1f} {self.unit}/秒"
            else:
                return f"{avg_speed:.2f} {self.unit}/秒"
        return ""
    
    def _calc_remaining(self):
        """计算预计剩余时间"""
        if self.completed <= 0:
            return ""
        
        elapsed = time.time() - self.start_time
        if elapsed > 0:
            time_per = elapsed / self.completed
            remaining = time_per * (self.total - self.completed)
            
            # 格式化剩余时间为用户友好的格式
            if remaining < 60:  # 秒级
                return f"{remaining:.0f}秒"
            elif remaining < 3600:  # 分钟级
                return f"{remaining/60:.1f}分钟"
            else:  # 小时级
                return f"{remaining/3600:.1f}小时"
        return ""
    
    def _move_to_position(self):
        """移动光标到进度条位置"""
        if self.position == 'top':
            # 移动到顶部
            print("\033[H", end='')
        else:
            # 移动到底部
            self._get_terminal_size()
            print(f"\033[{self.window_height};0H", end='')
    
    def _show(self):
        """首次显示进度条"""
        self.visible = True
        # 保存当前光标位置
        if platform.system() != 'Windows':
            print("\033[s", end='')
        
        # 在底部创建一个空白空间
        if self.position == 'bottom':
            self._get_terminal_size()
            for _ in range(self.window_height - 1):
                print()
        
        # 移动到进度条位置
        self._move_to_position()
        
        # 打印空的进度条以预留空间
        self._update_display()
        
    def _update_display(self):
        """更新进度条显示"""
        if not self.visible:
            return
            
        progress = min(1.0, self.completed / self.total if self.total > 0 else 0)
        filled_length = int(round(self.bar_length * progress))
        bar_length = max(1, self.bar_length)
        
        # 创建进度条
        bar = ('=' * max(0, filled_length - 1)) + '>' + ' ' * max(0, (bar_length - filled_length))
        if filled_length == bar_length:
            bar = '=' * bar_length  # 完整时使用全等号
            
        percent = min(100.0, progress * 100.0)
        
        # 构建完整输出行
        desc = f"{self.desc}:"
        progress_text = f"{percent:5.1f}% [{bar}]"
        stats_text = f"{self.completed}/{self.total}"
        speed_text = self._format_speed()
        remaining_text = self._calc_remaining()
        
        # 组装完整的行
        progress_line = f"{Colors.PROGRESS_TEXT}{desc} {Colors.PROGRESS_VALUE}{progress_text}{Colors.ENDC} "
        stats_line = f"{Colors.PROGRESS_TEXT}已处理: {Colors.PROGRESS_VALUE}{stats_text}{Colors.ENDC}"
        
        if speed_text:
            stats_line += f" | {Colors.PROGRESS_TEXT}速度: {Colors.PROGRESS_VALUE}{speed_text}{Colors.ENDC}"
        if remaining_text:
            stats_line += f" | {Colors.PROGRESS_TEXT}剩余: {Colors.PROGRESS_REMAINING}{remaining_text}{Colors.ENDC}"
        
        # 移动到进度条位置
        self._move_to_position()
        
        # 清除行并打印进度条
        print("\033[K", end='')  # 清除行
        print(progress_line)
        print("\033[K", end='')  # 清除行
        print(stats_line)
        
        # 恢复保存的光标位置（在日志输出位置）
        if platform.system() != 'Windows':
            print("\033[u", end='')
        
        sys.stdout.flush()
        
    def close(self):
        """关闭进度条（在最终位置显示完成信息）"""
        if not self.visible:
            return
            
        self.visible = False
        self._move_to_position()
        
        if self.completed >= self.total:
            # 完成状态
            print("\033[K", end='')  # 清除行
            print(f"{Colors.OKGREEN}✓ {self.desc} 完成! {self.completed}/{self.total}{Colors.ENDC}")
        else:
            # 未完成状态
            print("\033[K", end='')  # 清除行
            print(f"{Colors.WARNING}⚠ {self.desc} 中断! 完成 {self.completed}/{self.total}{Colors.ENDC}")
        
        # 在Windows上需要多打印换行来调整布局
        if platform.system() == 'Windows':
            print("\n")
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if not self.visible:
            return
            
        if exc_type is KeyboardInterrupt:
            self.close()
            return False
            
        # 如果未完成，确保显示进度条
        if self.completed < self.total:
            self._update_display()
        
        # 等待0.5秒后关闭
        time.sleep(0.5)
        self.close()
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
                36867: "DateTimeOriginal",   # EXIF日期时间原始值
                36868: "DateTimeDigitized",  # EXIF数字化日期时间
                306: "DateTime",             # TIFF/EP 标准日期时间
                
                # 相机特定标签
                50934: "OlympusDate",        # Olympus日期时间
                50937: "OlympusDateTime",    # Olympus日期时间(长格式)
                32781: "DateTimeCreated",    # 创建日期时间(某些相机),
                36864: 'ExifVersion',
                36880: 'OffsetTime',
                36881: 'OffsetTimeOriginal',
                36882: 'OffsetTimeDigitized',
                33434: 'ExposureTime',
                33437: 'FNumber',
            }
            
            # 优先检查已知日期标签
            for tag_id, tag_name in date_tag_ids.items():
                value = exif_data.get(tag_id)
                if value and isinstance(value, str):
                    try:
                        # 尝试多种日期格式
                        formats = ["%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"]
                        for fmt in formats:
                            try:
                                dt = datetime.datetime.strptime(value.strip()[:19], fmt)
                                return dt.date()
                            except ValueError:
                                continue
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
            '-show_entries', 'format_tags=creation_time',
            '-show_entries', 'format_tags=creation_date',
            '-show_entries', 'format_tags=com.apple.quicktime.creationdate',
            '-of', 'default=nokey=1:noprint_wrappers=1',
            video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        
        if result.returncode == 0:
            # 尝试解析输出中的日期值
            date_strs = result.stdout.strip().splitlines()
            
            # 尝试所有可能的日期格式
            formats = [
                "%Y-%m-%dT%H:%M:%S",   # ISO格式 (GoPro/iPhone)
                "%Y%m%d",               # 紧凑格式 (Sony相机)
                "%Y/%m/%d %H:%M:%S",    # 目录/时间格式
                "%d-%b-%Y",             # Nikon格式 (01-JAN-2023)
                "%Y:%m:%d %H:%M:%S",     # EXIF格式的视频
                "%Y%m%d%H%M%S",         # 紧凑时间格式
                "%b %d %Y %H:%M:%S"      # 文本月份格式
            ]
            
            for date_str in date_strs:
                date_str = date_str.strip()
                if not date_str:
                    continue
                    
                for fmt in formats:
                    try:
                        # 清理不规则字符
                        clean_date = ''.join(c for c in date_str if c.isprintable()).replace('T', ' ')
                        # 尝试不带时区的部分
                        dt_str = clean_date.split('.')[0].split('+')[0].strip()
                        dt = datetime.datetime.strptime(dt_str, fmt)
                        return dt.date()
                    except ValueError:
                        continue
                        
        # 从文件名提取日期信息
        basename = os.path.basename(video_path)
        name_without_ext = os.path.splitext(basename)[0]
        
        # 常见命名模式: YYYYMMDD_HHMMSS, YYYY-MM-DD HH.MM.SS
        patterns = [
            r'\d{4}-\d{2}-\d{2}',  # YYYY-MM-DD
            r'\d{8}',              # YYYYMMDD
            r'\d{4}\d{2}\d{2}'     # YYYYMMDD
        ]
        
        import re
        for pattern in patterns:
            match = re.search(pattern, name_without_ext)
            if match:
                date_str = match.group(0)
                date_formats = ["%Y-%m-%d", "%Y%m%d", "%Y%m%d"]
                for fmt in date_formats:
                    try:
                        dt = datetime.datetime.strptime(date_str, fmt)
                        return dt.date()
                    except ValueError:
                        continue
                
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
        logger.debug(f"视频日期读取失败 {os.path.basename(video_path)}: {str(e)}")
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
        patterns = [
            r'(\d{4}-\d{2}-\d{2})',       # YYYY-MM-DD
            r'(\d{4}_\d{2}_\d{2})',        # YYYY_MM_DD
            r'(\d{4}\d{2}\d{2})',          # YYYYMMDD
            r'(\d{4}\d{2}\d{2}[_-]\d{6})'  # YYYYMMDD-HHMMSS
        ]
        
        import re
        for pattern in patterns:
            match = re.search(pattern, basename)
            if match:
                date_str = match.group(1)
                date_formats = ["%Y-%m-%d", "%Y_%m_%d", "%Y%m%d", "%Y%m%d-%H%M%S"]
                for fmt in date_formats:
                    if len(date_str) == len(fmt.replace('_', '').replace('-', '')):
                        try:
                            dt = datetime.datetime.strptime(date_str, fmt)
                            return dt.date()
                        except ValueError:
                            continue
                
        # 最后使用缓存的文件修改时间
        timestamp = get_cached_file_timestamp(media_path)
        return datetime.datetime.fromtimestamp(timestamp).date()
    except Exception as e:
        logger.debug(f"日期获取错误 {os.path.basename(media_path)}: {str(e)}")
        # 回退到文件修改时间
        try:
            ts = os.path.getmtime(media_path)
            return datetime.datetime.fromtimestamp(ts).date()
        except:
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
    """计算文件的快速哈希值（仅文件开头提高速度）"""
    hasher = hashlib.md5()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(block_size), b''):
            hasher.update(chunk)
            # 对于大文件，只读取第一部分
            if f.tell() > 1024 * 1024:  # 只读1MB足够
                break
    return hasher.hexdigest()

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
        os.makedirs(
            target_dir, 
            exist_ok=True,
            mode=0o755  # 合理的默认权限
        )
        
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
            # 删除源文件
            try:
                os.remove(source_path)
                logger.debug(f"删除重复文件: {filename}")
            except:
                pass
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
            
        # 如果目标文件存在（可能是并发操作创建的），重新生成唯一路径
        if os.path.exists(target_path):
            target_dir = os.path.dirname(target_path)
            filename = os.path.basename(target_path)
            base, ext = os.path.splitext(filename)
            target_path = generate_unique_filename(target_dir, base, ext)
            
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
    
    # Windows终端支持ANSI转义序列
    if platform.system() == 'Windows':
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass  # 如果失败则忽略，使用基础模式
    
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
        skippable_dirs = ['.', '@eaDir', '__MACOSX', '.DS_Store', 'Thumbs.db']
        if any(skip_name in os.path.basename(root) for skip_name in skippable_dirs):
            skipped_dirs.append(root)
            continue
        
        # 避免进入某些系统目录 (.git, .svn等)
        for d in list(dirs):
            if d.startswith('.') or d in skippable_dirs:
                logger.debug(f"跳过目录: {os.path.join(root, d)}")
                dirs.remove(d)
                skipped_dirs.append(os.path.join(root, d))
            
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
                except OSError as e:
                    logger.warning(f"无法访问文件: {file_path}: {e}")
                
                # 每10秒或每500文件记录一次进度
                current_time = time.time()
                if current_time - last_log_time > 10 or len(media_files) % 500 == 0:
                    logger.info(
                        f"扫描进度: 已找到 {len(media_files):,}个文件 ({total_size/1024/1024:.1f} MB)"
                    )
                    last_log_time = current_time
    
    # 扫描完成
    if skipped_dirs:
        logger.debug(f"⚠️ 跳过 {len(skipped_dirs)} 个系统目录")
    
    scan_time = time.time() - start_scan
    logger.info(
        f"📊 扫描完成! 找到 {len(media_files):,}个媒体文件 ({total_size/1024/1024:.1f} MB) "
        f"耗时: {scan_time:.1f}秒 ({len(media_files)/max(scan_time, 0.01):.1f}文件/秒)"
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
    
    # 创建计算进度条（固定在屏幕底部）
    with FixedProgressBar(total=len(media_files), 
                         desc="分析文件日期", 
                         position='bottom') as compute_bar:
        
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
            finally:
                # 确保进度条更新到最新状态
                compute_bar._update_display()
    
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
    desc_text = f"移动文件 ({total_bytes/1024/1024:.1f} MB)"
    
    with FixedProgressBar(total=len(valid_tasks), 
                         desc=desc_text, 
                         position='bottom') as move_bar:
        
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
            for future in concurrent.futures.as_completed(io_futures):
                try:
                    future.result()  # 触发异常（如果有）
                except Exception:
                    pass
                
                # 每分钟记录一次详细状态
                if time.time() - global_stats.last_log_time >= 60:
                    global_stats.log_progress(force=True)
    
    # 6. 最终性能报告
    stats = global_stats.get_stats()
    elapsed = stats['elapsed']
    
    # 计算各种速率
    file_rate = stats['processed'] / elapsed if elapsed > 0 else 0
    mb_rate = total_bytes / (1024 * 1024) / elapsed if elapsed > 0 else 0
    success_rate = (stats['moved'] / stats['processed']) * 100 if stats['processed'] > 0 else 0
    
    # 生成最终报告
    summary = [
        "=" * 70,
        f"⭐ {Colors.OKGREEN}整理完成!{Colors.ENDC}",
        "=" * 70,
        f"📊 {Colors.PROGRESS_TEXT}统计数据:{Colors.ENDC}",
        f"  总耗时: {Colors.PROGRESS_VALUE}{elapsed:.1f}秒{Colors.ENDC}",
        f"  处理文件: {Colors.PROGRESS_VALUE}{stats['processed']}/{stats['total']}{Colors.ENDC} ({success_rate:.1f}% 成功率)",
        f"  成功移动: {Colors.OKGREEN}{stats['moved']}{Colors.ENDC}个文件",
        f"  跳过/重复: {Colors.WARNING}{stats['skipped']}{Colors.ENDC}个文件",
        f"  处理失败: {Colors.FAIL}{stats['failed']}{Colors.ENDC}个文件",
        "",
        f"⚡ {Colors.PROGRESS_TEXT}性能指标:{Colors.ENDC}",
        f"  速度: {Colors.PROGRESS_VALUE}{file_rate:.1f}文件/秒 | {mb_rate:.1f} MB/秒{Colors.ENDC}",
        "",
        f"🗂️ {Colors.PROGRESS_TEXT}目标位置:{Colors.ENDC} {Colors.PROGRESS_VALUE}{os.path.abspath(target_base_dir)}{Colors.ENDC}",
        "=" * 70
    ]
    
    for line in summary:
        logger.info(line)

def run_cli():
    """命令行入口函数"""
    import argparse
    
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="📸🎥 媒体整理工具 v8.0 - 高级进度条版",
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
██████╗  ██████╗ ██████╗ ███████╗████████╗██████╗ 
██╔══██╗██╔═══██╗██╔══██╗██╔════╝╚══██╔══╝██╔══██╗
██████╔╝██║   ██║██████╔╝█████╗     ██║   ██████╔╝
██╔══██╗██║   ██║██╔══██╗██╔══╝     ██║   ██╔═══╝ 
██║  ██║╚██████╔╝██████╔╝███████╗   ██║   ██║     
╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚══════╝   ╚═╝   ╚═╝     
    """
    
    args = parser.parse_args()
    
    print(f"\n\033[96m{banner}\033[0m")
    print(f"\033[96m{'='*70}\033[0m")
    print(f"{Colors.PROGRESS_TEXT}媒体整理工具 v8.0 - 专业进度条版{Colors.ENDC}")
    print(f"\033[96m{'='*70}\33[0m")
    print(f"{Colors.PROGRESS_TEXT}🔍 源目录  :{Colors.ENDC} \033[92m{os.path.abspath(args.source)}\033[0m")
    if args.target:
        print(f"{Colors.PROGRESS_TEXT}📁 目标目录:{Colors.ENDC} \033[92m{os.path.abspath(args.target)}\033[0m")
    else:
        print(f"{Colors.PROGRESS_TEXT}📁 目标目录:{Colors.ENDC} \033[93m源目录内整理\033[0m")
    print(f"{Colors.PROGRESS_TEXT}⚙️  并行线程:{Colors.ENDC} \033[93m{args.workers}\033[0m")
    print(f"{Colors.PROGRESS_TEXT}🔧 详细模式:{Colors.ENDC} \033[93m{'是' if args.verbose else '否'}\033[0m")
    print(f"\033[96m{'='*70}\033[0m\n")
    
    try:
        organize_media(
            source_dir=args.source,
            target_base_dir=args.target,
            verbose=args.verbose,
            max_workers=args.workers
        )
    except KeyboardInterrupt:
        print(f"\n{Colors.FAIL}操作被用户中断!{Colors.ENDC}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"{Colors.FAIL}程序发生严重错误: {str(e)}{Colors.ENDC}")
        if args.verbose:
            logger.debug(f"错误详情: {sys.exc_info()}")
        sys.exit(1)

if __name__ == "__main__":
    run_cli()
