import os
import shutil
from PIL import Image
from PIL.ExifTags import TAGS
import datetime

def get_image_date(image_path):
    """获取图片的拍摄日期，若无法获取则使用文件创建日期"""
    try:
        img = Image.open(image_path)
        exif_data = img.getexif()
        
        if not exif_data:
            raise AttributeError("No EXIF data found")
        
        # 查找拍摄日期标签(306对应DateTimeOriginal)
        date_str = None
        for tag_id, value in exif_data.items():
            tag_name = TAGS.get(tag_id, tag_id)
            if tag_name == 'DateTimeOriginal' and value:
                date_str = value
                break
            
        if not date_str:
            # 如果找不到原始拍摄日期，尝试其他日期标签
            for tag_id, value in exif_data.items():
                tag_name = TAGS.get(tag_id, tag_id)
                if isinstance(tag_name, str) and 'Date' in tag_name and value:
                    date_str = value
                    break
        
        if date_str:
            # 清理日期字符串中的空字符
            date_str = ''.join(filter(lambda x: ord(x) > 31, date_str))
            return datetime.datetime.strptime(date_str.split()[0].replace(":", "-"), "%Y-%m-%d").date()
    
    except Exception:
        pass
    
    # 所有EXIF方法都失败时使用文件修改日期
    timestamp = os.path.getmtime(image_path)
    return datetime.datetime.fromtimestamp(timestamp).date()

def organize_images(source_dir, target_base_dir=None):
    """主函数：按日期整理图片"""
    if target_base_dir is None:
        target_base_dir = source_dir
    
    # 支持的图片格式
    valid_extensions = ('.jpg', '.jpeg', '.png', '.heic', '.tiff', '.nef', '.cr2', '.arw', '.dng')
    
    # 统计处理结果
    files_processed = 0
    files_skipped = 0
    files_error = 0
    
    # 遍历所有文件
    for filename in os.listdir(source_dir):
        filepath = os.path.join(source_dir, filename)
        
        # 跳过目录
        if os.path.isdir(filepath):
            continue
        
        # 检查扩展名
        if filename.lower().endswith(valid_extensions):
            try:
                # 获取图片日期
                img_date = get_image_date(filepath)
                date_folder = img_date.strftime("%Y-%m-%d")  # 这里是固定修复的部分！
                
                # 创建目标文件夹
                target_dir = os.path.join(target_base_dir, date_folder)
                os.makedirs(target_dir, exist_ok=True)
                
                # 生成目标路径
                new_path = os.path.join(target_dir, filename)
                
                # 处理文件名冲突
                counter = 1
                while os.path.exists(new_path) and os.path.samefile(filepath, new_path) is False:
                    base, ext = os.path.splitext(filename)
                    new_filename = f"{base}_{counter}{ext}"
                    new_path = os.path.join(target_dir, new_filename)
                    counter += 1
                
                # 移动文件
                shutil.move(filepath, new_path)
                files_processed += 1
                print(f"✓ Moved: {filename} -> {date_folder}/{os.path.basename(new_path)}")
                
            except Exception as e:
                files_error += 1
                print(f"✗ Error processing {filename}: {str(e)}")
        else:
            files_skipped += 1
    
    # 打印总结报告
    print("\n" + "=" * 50)
    print(f"整理完成! 总文件: {files_processed + files_skipped + files_error}")
    print(f"✅ 成功处理: {files_processed} 张图片")
    print(f"⚠️ 跳过非图片: {files_skipped} 个文件")
    print(f"❌ 处理失败: {files_error} 张图片")
    print("=" * 50)
    print("注: 按日期分类后的文件夹可在以下位置找到:")
    print(os.path.abspath(target_base_dir))

# 使用示例
if __name__ == "__main__":
    # 设置源图片目录（当前目录）
    source_directory = os.getcwd()
    
    # 设置目标根目录（可选，默认为源目录）
    # target_directory = "/path/to/sorted/photos"
    
    # 组织图片
    organize_images(source_directory)
    # 使用自定义目标目录： organize_images(source_directory, target_directory)
