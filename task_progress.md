# Foto2AP 功能实现 - 完成

## 新增文件
- **`foto2ap_service.py`** — Python 后端 OCR 服务（从 notebook 提取的 AP 识别逻辑）
- **`lib/services/foto2ap_service.dart`** — Flutter 端 API 封装

## 修改文件
- **`main.py`** — 添加 `POST /foto2ap/recognize` 端点
- **`lib/pages/map_page.dart`** — 添加 Foto2AP 模式（相机 FAB、标记、信息卡片）
- **`pubspec.yaml`** — 添加 `image_picker` 依赖
- **`requirements.txt`** — 添加 `rapidfuzz` 依赖

## 功能流程
1. 点击 📷 相机 FAB → 选择拍照/相册
2. 图片上传后端 → PaddleOCR 识别文本 → 解析 AP 代码 → GeoJSON 查坐标
3. 成功：清除 heatmap → 显示紫色大标记 + 底部信息卡片（AP名、建筑、楼层）
4. 失败：显示错误提示
5. 点击关闭按钮 → 恢复 heatmap 模式
