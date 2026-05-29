#!/usr/bin/env python3
"""Precise line-by-line edits using exact known line numbers."""
import ast

with open("main.py") as f:
    lines = f.readlines()

# 1) After line 72 (idx 71), add globals
lines.insert(72, "_precomputed_trends: dict[str, dict] = {}\n")
lines.insert(73, "_precomputed_trends_loaded: bool = False\n")
lines.insert(74, "_ap_index_by_name: dict[str, dict] = {}\n")

# 2) Line 294 (idx 293): change global
assert "    global _ap_index" in lines[293], f"Expected global at 293, got: {lines[293]}"
lines[293] = "    global _ap_index, _ap_index_by_name\n"

# 3) After line 297 (idx 296): add _ap_index_by_name = {}
#    (line numbers shifted by +3 from globals insertion)
assert "    _ap_index = []" in lines[296], f"Expected _ap_index = [] at 296, got: {lines[296]}"
lines[297:297] = ["    _ap_index_by_name = {}\n"]

# 4) After `        })` (line 319, idx 318) before `    return _ap_index` (line 320, idx 319)
#    Insert dict entry lines
append_close_idx = 318  # line with `        })`
assert lines[append_close_idx].strip() == '})', f"Expected ')}}' at {append_close_idx}, got: {lines[append_close_idx]}"
assert lines[append_close_idx+1].strip() == 'return _ap_index', f"Expected return at {append_close_idx+1}, got: {lines[append_close_idx+1]}"

lines[319:319] = [
    '        # Build O(1) lookup\n',
    '        ap_key = ap_name.strip().lower()\n',
    '        if ap_key not in _ap_index_by_name:\n',
    '            _ap_index_by_name[ap_key] = _ap_index[-1]\n',
]

# 5) Replace _find_ap_in_index body (lines 462-468, idx 461-467)
#    Line numbers shifted by +8 so far: 3+1+4 = 8
#    Original: 459-465. New: 467-473
find_start = None
for i, line in enumerate(lines):
    if 'def _find_ap_in_index(ap_name: str) -> Optional[dict]:' in line:
        find_start = i
        break
assert find_start is not None, "Can't find _find_ap_in_index"

# Replace body: original was 5 lines (cache_key, ap_index, for, if, return None)
# Replace with 3 lines (_build_ap_index, cache_key, return)
new_find_body = [
    '    _build_ap_index()\n',
    '    cache_key = ap_name.strip().lower()\n',
    '    return _ap_index_by_name.get(cache_key)\n',
]
# Delete old body: find_start+1 through find_start+5 (4 lines)
del lines[find_start+1:find_start+6]
# Insert new body
lines[find_start+1:find_start+1] = new_find_body

# 6) Replace prediction block in get_ap_daily_trend
#    Find the block by looking for `day_type = "weekend"` followed by prediction code
trend_start = None
for i, line in enumerate(lines):
    if 'day_type = "weekend" if is_weekend else "weekday"' in line:
        trend_start = i
        break
assert trend_start is not None, "Can't find get_ap_daily_trend block"

# Collect the prediction block (starts at trend_start + 2: ap_name_code = ...)
# But wait - after our edits, the line numbers have changed.
# Let's find the pattern differently - search for ap_name_code = ... near trend_start
pred_start = None
for i in range(trend_start, trend_start + 5):
    if 'ap_name_code = _encode_ap_name(ap_entry["name"])' in lines[i]:
        pred_start = i
        break
assert pred_start is not None, f"Can't find pred start near {trend_start}"

# Find end of prediction block: `worst_hour = ...`
pred_end = None
for i in range(pred_start, pred_start + 25):
    if 'worst_hour = signal_values.index(min_db) if signal_values else 0' in lines[i]:
        pred_end = i
        break
assert pred_end is not None, f"Can't find pred end after {pred_start}"

# Build replacement
repl = [
    '    # Use precomputed trend if available (fast path - no model inference)\n',
    '    precomputed = _precomputed_trends.get(cache_key)\n',
    '    if precomputed is not None:\n',
    '        hourly_data = precomputed["trend"]\n',
    '        signal_values = [h["signal_db"] for h in hourly_data]\n',
    '        avg_db = precomputed["stats"]["avg_db"]\n',
    '        max_db = precomputed["stats"]["max_db"]\n',
    '        min_db = precomputed["stats"]["min_db"]\n',
    '        best_hour = precomputed["stats"]["best_hour"]\n',
    '        worst_hour = precomputed["stats"]["worst_hour"]\n',
    '    else:\n',
    '        # On-demand inference (fallback until precompute finishes)\n',
    '        ap_name_code = _encode_ap_name(ap_entry["name"])\n',
    '        rows = []\n',
    '        for hour in range(24):\n',
    '            rows.append(_build_signal_features(building_code=building_code, floor=floor, hour=float(hour), day_of_week=day_of_week, is_weekend=is_weekend, day_of_month=day_of_month, month=month, ap_name_code=ap_name_code))\n',
    '        df = pd.DataFrame(rows)\n',
    '        predictions = model.predict(df)\n',
    '        hourly_data = []\n',
    '        signal_values = []\n',
    '        for hour, signal_db in enumerate(predictions):\n',
    '            quality_info = _dbm_to_quality(float(signal_db))\n',
    '            status = _dbm_to_status(float(signal_db))\n',
    '            status_conf = _dbm_to_status_confidence(float(signal_db))\n',
    '            hourly_data.append({\n',
    '                "hour": hour,\n',
    '                "signal_db": round(float(signal_db), 1),\n',
    '                "signal_quality": quality_info["quality"],\n',
    '                "bars": quality_info["bars"],\n',
    '                "predicted_status": status,\n',
    '                "status_confidence": status_conf,\n',
    '            })\n',
    '            signal_values.append(round(float(signal_db), 1))\n',
    '        avg_db = sum(signal_values) / len(signal_values) if signal_values else 0\n',
    '        max_db = max(signal_values) if signal_values else 0\n',
    '        min_db = min(signal_values) if signal_values else 0\n',
    '        best_hour = signal_values.index(max_db) if signal_values else 0\n',
    '        worst_hour = signal_values.index(min_db) if signal_values else 0\n',
    '\n',
]
# Delete old lines pred_start..pred_end+1 (inclusive)
del lines[pred_start:pred_end+2]
# Insert new lines
lines[pred_start:pred_start] = repl

# 7) Wrap interpolation body in try/except
#    Find the `if len(actual_hours) >= 2:` block and `for h in range(24):` 
interp_if_idx = None
for i, line in enumerate(lines):
    if line.strip() == 'if len(actual_hours) >= 2:':
        interp_if_idx = i
        break
assert interp_if_idx is not None, "Can't find interpolation block"

# Find `for h in range(24):` right after it
for_h_idx = None
for i in range(interp_if_idx, interp_if_idx + 5):
    if lines[i].strip() == 'for h in range(24):':
        for_h_idx = i
        break
assert for_h_idx is not None, "Can't find for h in interpolation"

# Insert `try:` after `for h in range(24):`
lines.insert(for_h_idx + 1, '                try:\n')

# Find `elif len(actual_hours) == 1:` after the for body - this is the close point
elif_idx = None
for i in range(for_h_idx, for_h_idx + 50):
    if lines[i].strip() == 'elif len(actual_hours) == 1:':
        elif_idx = i
        break
assert elif_idx is not None, "Can't find elif after interpolation"

# Insert `except:` and `pass` before the elif
lines.insert(elif_idx, '                except Exception:\n')
lines.insert(elif_idx + 1, '                    pass\n')

# 8) Add precompute function before if __name__ == "__main__":
main_start = None
for i, line in enumerate(lines):
    if line.strip() == 'if __name__ == "__main__":':
        main_start = i
        break
assert main_start is not None, "Can't find if __name__"

precompute = [
    '\n',
    'def _precompute_all_trends():\n',
    '    """Precompute trends for ALL APs at startup (background thread)."""\n',
    '    global _precomputed_trends, _precomputed_trends_loaded\n',
    '    if _precomputed_trends_loaded:\n',
    '        return\n',
    '    try:\n',
    '        model = _load_signal_strength_model()\n',
    '    except Exception as e:\n',
    '        print(f"[WARN] Cannot precompute trends: {e}")\n',
    '        _precomputed_trends_loaded = True\n',
    '        return\n',
    '    ap_index = _build_ap_index()\n',
    '    from datetime import datetime\n',
    '    today = datetime.now()\n',
    '    day_of_week = float(today.weekday())\n',
    '    is_weekend = 1.0 if day_of_week >= 5 else 0.0\n',
    '    day_of_month = float(today.day)\n',
    '    month = float(today.month)\n',
    '    rows = []\n',
    '    ap_keys = []\n',
    '    for ap in ap_index:\n',
    '        building_code = _encode_building(ap["building"])\n',
    '        ap_name_code = _encode_ap_name(ap["name"])\n',
    '        for hour in range(24):\n',
    '            rows.append(_build_signal_features(\n',
    '                building_code=building_code, floor=ap["floor"],\n',
    '                hour=float(hour), day_of_week=day_of_week,\n',
    '                is_weekend=is_weekend, day_of_month=day_of_month,\n',
    '                month=month, ap_name_code=ap_name_code\n',
    '            ))\n',
    '            ap_keys.append((ap["name"].strip().lower(), hour))\n',
    '    df = pd.DataFrame(rows)\n',
    '    predictions = model.predict(df)\n',
    '    from collections import defaultdict\n',
    '    ap_hourly = defaultdict(list)\n',
    '    for (ap_key, hour), pred in zip(ap_keys, predictions):\n',
    '        ap_hourly[ap_key].append((hour, float(pred)))\n',
    '    for ap_key, hourly_list in ap_hourly.items():\n',
    '        hourly_list.sort(key=lambda x: x[0])\n',
    '        signal_values = [h[1] for h in hourly_list]\n',
    '        hourly_data = []\n',
    '        for hour, signal_db in hourly_list:\n',
    '            quality_info = _dbm_to_quality(signal_db)\n',
    '            status = _dbm_to_status(signal_db)\n',
    '            hourly_data.append({\n',
    '                "hour": hour,\n',
    '                "signal_db": round(signal_db, 1),\n',
    '                "signal_quality": quality_info["quality"],\n',
    '                "bars": quality_info["bars"],\n',
    '                "predicted_status": status,\n',
    '            })\n',
    '        _precomputed_trends[ap_key] = {\n',
    '            "trend": hourly_data,\n',
    '            "stats": {\n',
    '                "avg_db": round(sum(signal_values) / len(signal_values), 1),\n',
    '                "max_db": round(max(signal_values), 1),\n',
    '                "min_db": round(min(signal_values), 1),\n',
    '                "best_hour": signal_values.index(max(signal_values)),\n',
    '                "worst_hour": signal_values.index(min(signal_values)),\n',
    '            },\n',
    '        }\n',
    '    print(f"[INFO] Precomputed trends for {len(_precomputed_trends)} APs")\n',
    '    _precomputed_trends_loaded = True\n',
    '\n',
    '\n',
    '@app.on_event("startup")\n',
    'async def _startup_precompute():\n',
    '    """Precompute trends on startup in background thread."""\n',
    '    print("[INFO] Starting background trend precomputation...")\n',
    '    import threading\n',
    '    thread = threading.Thread(target=_precompute_all_trends, daemon=True)\n',
    '    thread.start()\n',
    '\n',
    '\n',
]

lines[main_start:main_start] = precompute

# Write
with open("main.py", "w") as f:
    f.writelines(lines)

# Verify
with open("main.py") as f:
    code = f.read()

try:
    ast.parse(code)
    print(f"[OK] Syntax OK! {len(code.splitlines())} lines")
except SyntaxError as e:
    print(f"[ERROR] {e}")
    l = code.splitlines()
    lineno = e.lineno - 1
    for i in range(max(0, lineno-3), min(len(l), lineno+3)):
        print(f"  {i+1:4d}: |{l[i]}")
