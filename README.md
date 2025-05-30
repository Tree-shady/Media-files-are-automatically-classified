#v1.0  
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
