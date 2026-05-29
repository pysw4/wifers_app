# 全面修复任务清单

## 🔴 关键错误修复
- [ ] 1. **foto2ap_service.py**: PaddleOCR 结果解析崩溃 — `result[0].get("rec_texts")` 在 list 上调用 .get() 导致 AttributeError
- [ ] 2. **main.py route/advanced**: 与 /route 完全相同，未提供信号感知路由
- [ ] 3. **main.py**: 响应中缺少 alternatives 字段，前端在 map_page/recommend_page 中尝试访问

## 🟡 后端 (main.py) 修复
- [ ] 4. `_load_actual_signal_data()`: JSON 加载后缺少重置缓存逻辑
- [ ] 5. 预计算趋势线程：需更好的错误处理和重试
- [ ] 6. 改进 `_suggest_best_slot` 死代码 (`pred is None` 永远为 False)
- [ ] 7. 添加 `/route/advanced` 的替代路径和信号感知路由

## 🟠 前端 (Flutter/Dart) 修复
- [ ] 8. **api_service.dart**: `fetchRoute`/`fetchAdvancedRoute` 参数顺序确认与清理
- [ ] 9. **map_page.dart**: Navigation 流程中 alternatives 空安全处理
- [ ] 10. **recommend_page.dart**: Building 模式切换时自动搜索
- [ ] 11. **ap_trend_dialog.dart**: 信号质量与状态显示一致性
- [ ] 12. **predictor_page.dart**: 级联特征显示的 null safety
- [ ] 13. **favorites_page.dart**: 导航流程优化

## 🟢 通用改进
- [ ] 14. `requirements.txt`: 清理不必要的依赖
- [ ] 15. 添加更完善的错误日志
- [ ] 16. 验证所有修改
