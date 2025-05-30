import os
import shutil
from PIL import Image
from PIL.ExifTags import TAGS
import datetime
import subprocess

def get_media_date(media_path):
    """获取媒体文件的日期（图片优先使用EXIF，视频使用元数据）"""
    try:
        # 尝试从EXIF信息获取日期（适用于图片）
        if media_path.lower().endswith(('.jpg', '.jpeg', '.png', '.heic', '.tiff', '.nef', '.cr2', '.arw', '.dng')):
            try:
                img = Image.open(media_path)
                exif_data = img.getexif()
                img.close()  # 及时关闭文件
                
                if not exif_data:
                    raise AttributeError("No EXIF data found")
                
                # 查找拍摄日期标签
                date_str = None
                for tag_id, value in exif_data.items():
                    tag_name = TAGS.get(tag_id, tag_id)
                    if tag_name == 'DateTimeOriginal' and value:
                        date_str = value
                        break
                    
                if not date_str:
                    # 尝试其他日期标签
                    for tag_id, value in exif_data.items():
                        tag_name = TAGS.get(tag_id, tag_id)
                        if isinstance(tag_name, str) and 'Date' in tag_name and value:
                            date_str = value
                            break
                
                if date_str:
                    # 清理日期字符串
                    date_str = ''.join(filter(lambda x: ord(x) > 31, date_str))
                    # 尝试多种日期格式
                    for fmt in ("%Y:%m:%d", "%Y-%m-%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
                        try:
                            return datetime.datetime.strptime(date_str[:10].replace(":", "-"), "%Y-%m-%d").date()
                        except ValueError:
                            continue
            except Exception:
                pass  # EXIF解析失败，尝试其他方法
        
        # 对于视频文件或EXIF失败的图片，尝试使用FFmpeg获取元数据
        try:
            if media_path.lower().endswith(('.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.mts')):
                command = [
                    'ffprobe', '-v', 'error',
                    '-show_entries', 'format_tags=creation_time',
                    '-of', 'default=noprint_wrappers=1:nokey=1',
                    media_path
                ]
                result = subprocess.run(command, capture_output=True, text=True)
                if result.returncode == 0 and result.stdout.strip():
                    date_str = result.stdout.strip()
                    # 尝试解析FFmpeg输出的ISO格式日期
                    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y%m%d"):
                        try:
                            created = datetime.datetime.strptime(date_str.split('.')[0], fmt)
                            return created.date()
                        except ValueError:
                            continue
        
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass  # FFmpeg不可用或解析失败
    
    except Exception:
        pass  # 所有特定方法失败时的通用异常处理
    
    # 最终方法：使用文件修改时间
    timestamp = os.path.getmtime(media_path)
    return datetime.datetime.fromtimestamp(timestamp).date()

def organize_media(source_dir, target_base_dir=None):
    """主函数：按日期整理媒体文件（图片+视频）"""
    if target_base_dir is None:
        target_base_dir = source_dir
    
    # 支持的媒体格式
    valid_extensions = (
        # 图片格式
        '.jpg', '.jpeg', '.png', '.heic', '.tiff', '.nef', '.cr2', '.arw', '.dng',
        # 视频格式
        '.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.3gp', '.m4v', '.mts'
    )
    
    # 统计处理结果
    files_processed = 0
    files_skipped = 0
    files_error = 0
    
    print(f"开始整理媒体文件: {source_dir}")
    print("支持的格式: " + ", ".join(valid_extensions))
    
    # 遍历所有文件
    for filename in os.listdir(source_dir):
        filepath = os.path.join(source_dir, filename)
        
        # 跳过目录
        if os.path.isdir(filepath):
            continue
        
        # 检查扩展名
        if filename.lower().endswith(valid_extensions):
            try:
                # 获取媒体文件日期
                media_date = get_media_date(filepath)
                date_folder = media_date.strftime("%Y-%m-%d")
                
                # 创建目标文件夹
                target_dir = os.path.join(target_base_dir, date_folder)
                os.makedirs(target_dir, exist_ok=True)
                
                # 生成目标路径
                new_path = os.path.join(target_dir, filename)
                
                # 处理文件名冲突
                if os.path.exists(new_path):
                    base, ext = os.path.splitext(filename)
                    counter = 1
                    while True:
                        new_filename = f"{base}_{counter}{ext}"
                        new_path = os.path.join(target_dir, new_filename)
                        if not os.path.exists(new_path):
                            break
                        counter += 1
                
                # 移动文件
                shutil.move(filepath, new_path)
                files_processed += 1
                print(f"✓ 已移动: {filename} -> {date_folder}/{os.path.basename(new_path)}")
                
            except Exception as e:
                files_error += 1
                print(f"✗ 处理失败: {filename} - 错误: {str(e)}")
        else:
            files_skipped += 1
            # 仅当文件不是目录且不是媒体文件时显示跳过消息
            if os.path.isfile(filepath):
                print(f"⊷ 跳过非媒体文件: {filename}")
    
    # 打印总结报告
    print("\n" + "=" * 50)
    print(f"整理完成! 总文件: {files_processed + files_skipped + files_error}")
    print(f"✅ 成功移动: {files_processed} 个媒体文件")
    print(f"⚠️ 跳过文件: {files_skipped} 个（非支持格式）")
    print(f"❌ 处理失败: {files_error} 个文件")
    print("=" * 50)
    print("\n整理后的文件夹位置:")
    print(f"📁 {os.path.abspath(target_base_dir)}")
    print("按日期分类的文件夹已创建完成\n")

# 使用示例
if __name__ == "__main__":
    # 设置源目录（当前目录）
    source_directory = os.getcwd()
    
    # 设置目标根目录（可选，默认为源目录）
    # target_directory = "/path/to/sorted/media"
    
    # 组织媒体文件
    organize_media(source_directory)
    
    # 使用自定义目标目录： 
    # organize_media(source_directory, target_directory)
