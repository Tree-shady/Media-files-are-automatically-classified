# organize_v1.0.py 
修复日期格式化问题：  
修复前（错误）： date_folder = img_date.strftime（“%Y-%m-% d”） # 修复后（正确）： date_folder = img_date.strftime（“%Y-%m-%d”） 增强日期提取功能：  
增加了多个日期标签的尝试（不只DateTimeOriginal）  
添加了无效字符过滤和日期格式清理  
更健壮地处理各种EXIF日期格式  
完善文件处理：  

改进文件名冲突处理逻辑  
添加更详细的处理统计和报告  
显示最终的文件夹位置  
支持更多图片格式：  
新增了对 ARW、DNG 等RAW格式的支持  

错误处理增强：  

更好的异常捕获和报告  
避免移动已处理文件的错误  
使用说明不变：  
将代码保存为 organize_photos.py  
安装所需依赖：  

pip install pillow  
把脚本放在图片文件夹中运行：  

python organize_photos.py  
特别说明：  
此代码已在多个平台测试运行，修正了原始代码中的字符串格式问题，并增强了处理多种日期格式文件的能力。新版本提供了更详细的处理报告，让用户清晰了解整理结果。  
  
# organize_v1.2.py  
全面支持图片和视频：  
图片格式：JPG, PNG, HEIC, TIFF, RAW (NEF, CR2, ARW, DNG)  
视频格式：MP4, MOV, AVI, MKV, FLV, WMV, MTS, 3GP, M4V  
增强的日期获取策略：  
图片：优先使用EXIF拍摄日期  
视频：尝试使用FFmpeg获取创建时间元数据  
通用后备：使用文件修改时间作为最后手段  
支持多种日期格式解析，提高兼容性  
添加FFmpeg集成：  
自动检测视频文件的创建日期元数据  
需要先安装FFmpeg（安装方法见下文）  
优雅降级：没有FFmpeg时使用文件修改时间  
更详细的处理日志：  
显示已处理文件的新路径  
区分成功、失败和跳过的文件  
清晰的总结报告  
安装和使用说明：  
安装必要的Python库：  
<BASH>  
pip install pillow  
安装FFmpeg（可选但推荐）：  
Windows: 从 https://ffmpeg.org/ 下载并加入PATH  
macOS: brew install ffmpeg  
Linux: sudo apt install ffmpeg  
运行脚本：  
<BASH>  
python organize_media.py  
自定义操作：  
指定不同的源目录和目标目录：  
<PYTHON>  
在主程序部分修改  
organize_media("/path/to/source", "/path/to/destination")  
添加更多文件格式支持：  
修改 valid_extensions 元组，添加您需要的扩展名  
改变文件处理方式：  
若要复制而非移动文件，将 shutil.move 替换为 shutil.copy2  
注意事项：  
脚本会移动而不是复制文件，操作前建议备份重要数据  
对于HEIC格式，需要安装额外的解码器（macOS原生支持）  
如果无法使用FFmpeg，视频文件将使用文件修改时间作为日期  
文件名冲突会自动通过添加后缀解决（如 photo_1.jpg）  
这个增强版脚本可以处理各种常见媒体文件，提供了多种日期获取策略，并且能够生成详细的操作报告，让您随时了解处理进度和结果。  
