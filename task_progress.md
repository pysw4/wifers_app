# Booking 问题修复清单

- [x] **Fix 1**: Dart booking_page.dart PERF_RANK 缺少 'Excellent+', 'Excellent++', 'Poor' 标签 — 已添加完整性能等级映射
- [x] **Fix 2**: bookingUI.py 显示 key 错误 — `book['min_perf']` → `book['min_performance']` 已修复
- [x] **Fix 3**: bookingUI.py 数据加载路径为空 — 已添加默认 parquet 和 geojson 路径
- [x] **Fix 4**: bookingUI.py check_availability 使用 ap_name 而非 room_code — 已修复为 room_code，同时修复了 show_availability
- [x] **Fix 5**: 后端未使用 n_students 参数 — 已添加 `_apply_perf_penalty` 函数，超标时性能降级
- [x] **额外**: 添加了 _perfColors 中缺失的 Very Poor/Weak/Poor/Excellent+/Excellent++ 颜色
