# Task Progress: 预测 vs 实际准确率

- [x] 分析现有代码和数据来源
- [x] 后端 main.py: 添加 `_actual_signal_data` 加载 clientes_processed.csv 实际测量数据
- [x] 后端 main.py: 在 trend API 中计算 MAE 和 signal_accuracy 并附加到响应
- [x] 后端 main.py: 新增 `GET /predict/signal_strength/accuracy/{ap_name}` 端点
- [x] 前端 api_service.dart: 添加 `getAPSignalAccuracy` 方法
- [x] 前端 ap_trend_dialog.dart: 显示准确率卡片 + "Show Actual" 切换按钮 + 双线对比
