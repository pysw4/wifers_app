# 修复 Heatmap/Trend 500 错误

- [x] 分析问题：_load_merged_heatmap() 要求 7 个合并文件，但实际只有 weekday/weekend 目录
- [ ] 修改 _load_merged_heatmap() 兼容现有 weekday/weekend 目录结构
- [ ] 修改 _get_hourly_data() 从旧文件格式读取
- [ ] 修改 _build_ap_trend_index() 从旧文件格式构建索引
- [ ] 修改 _get_day_name() 为 _get_day_type() 返回 weekday/weekend
