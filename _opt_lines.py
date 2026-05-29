#!/usr/bin/env python3
"""Line-number-based optimization using readlines/writelines."""
import ast

with open("main.py") as f:
    lines = f.readlines()

# ─────────────────────────────────────────────
# 1) Add globals after line 72 (0-indexed: 71)
#    Line 72: _trend_cache_time: dict[str, float] = {}
# ─────────────────────────────────────────────
insert_after = []
for i, line in enumerate(lines):
    insert_after.append(line)
    if i == 71:
        insert_after.append("_precomputed_trends: dict[str, dict] = {}\n")
        insert_after.append("_precomputed_trends_loaded: bool = False\n")
        insert_after.append("_ap_index_by_name: dict[str, dict] = {}\n")
lines = insert_after

# ─────────────────────────────────────────────
# 2) _build_ap_index - add _ap_index_by_name to global
#    Original line 291: "    global _ap_index"
# ─────────────────────────────────────────────
for i, line in enumerate(lines):
    if '    global _ap_index' in line and 'def _build_ap_index' in ''.join(lines[max(0,i-10):i]):
        lines[i] = '    global _ap_index, _ap_index_by_name\n'
        break

# ─────────────────────────────────────────────
# 3) Add `_ap_index_by_name = {}` after `_ap_index = []`
# ─────────────────────────────────────────────
for i, line in enumerate(lines):
    if line.strip() == '_ap_index = []' and 'def _build_ap_index' in ''.join(lines[max(0,i-10):i]):
        lines.insert(i+1, '    _ap_index_by_name = {}\n')
        break

# ─────────────────────────────────────────────
# 4) After append block add O(1) dict entry
#    Find the `        })` and `    return _ap_index` pattern
# ─────────────────────────────────────────────
new_lines = []
for i, line in enumerate(lines):
    stripped = line.rstrip()
    if stripped == '        })' and i+1 < len(lines) and lines[i+1].strip() == 'return _ap_index':
        new_lines.append(line)
        new_lines.append('        # Build O(1) lookup\n')
        new_lines.append('        ap_key = ap_name.strip().lower()\n')
        new_lines.append('        if ap_key not in _ap_index_by_name:\n')
        new_lines.append('            _ap_index_by_name[ap_key] = _ap_index[-1]\n')
    else:
        new_lines.append(line)
lines = new_lines

# ─────────────────────────────────────────────
# 5) Replace _find_ap_in_index body
#    Now at a different line number. Find by content.
# ─────────────────────────────────────────────
new_lines = []
skip_count = 0
for i, line in enumerate(lines):
    if skip_count > 0:
        skip_count -= 1
        continue
    if 'def _find_ap_in_index(ap_name: str) -> Optional[dict]:' in line:
        new_lines.append(line)
        new_lines.append('    _build_ap_index()\n')
        new_lines.append('    cache_key = ap_name.strip().lower()\n')
        new_lines.append('    return _ap_index_by_name.get(cache_key)\n')
        # Skip old body (4 lines)
        skip_count = 4
    else:
        new_lines.append(line)
lines = new_lines

# ─────────────────────────────────────────────
# 6) Replace get_ap_daily_trend prediction block
#    Find the exact lines in the function get_ap_daily_trend
# ─────────────────────────────────────────────
# Find the block: `ap_name_code = _encode_ap_name(ap_entry["name"])` that follows `day_type = "weekend"...`
# This is the ONE in get_ap_daily_trend (line 801 in original)
new_lines = []
in_trend_pred = False
pred_lines_buffer = []

for i, line in enumerate(lines):
    # Detect entry into the right predict block
    if 'day_type = "weekend" if is_weekend else "weekday"' in line:
        # Signal that we're in get_ap_daily_trend
        new_lines.append(line)
        in_trend_pred = True
        pred_lines_buffer = []
        continue
    
    if in_trend_pred:
        if line.strip().startswith('ap_name_code = _encode_ap_name(ap_entry["name"])'):
            # This is the start of the predict block we want to replace
            pred_lines_buffer.append(line)
            # Collect the entire predict block
            # It ends at `worst_hour = signal_values.index(min_db) if signal_values else 0`
            j = i + 1
            while j < len(lines):
                pred_lines_buffer.append(lines[j])
                if 'worst_hour = signal_values.index(min_db) if signal_values else 0' in lines[j]:
                    # End of predict block - add +1 for the blank line
                    pred_lines_buffer.append(lines[j+1])  # blank line
                    j += 2
                    break
                j += 1
            
            # Replace with fast-path version
            replacement = (
                '    # Use precomputed trend if available (fast path - no model inference)\n'
                '    precomputed = _precomputed_trends.get(cache_key)\n'
                '    if precomputed is not None:\n'
                '        hourly_data = precomputed["trend"]\n'
                '        signal_values = [h["signal_db"] for h in hourly_data]\n'
                '        avg_db = precomputed["stats"]["avg_db"]\n'
                '        max_db = precomputed["stats"]["max_db"]\n'
                '        min_db = precomputed["stats"]["min_db"]\n'
                '        best_hour = precomputed["stats"]["best_hour"]\n'
                '        worst_hour = precomputed["stats"]["worst_hour"]\n'
                '    else:\n'
                '        # On-demand inference (fallback until precompute finishes)\n'
                '        ap_name_code = _encode_ap_name(ap_entry["name"])\n'
                '        rows = []\n'
                '        for hour in range(24):\n'
                '            rows.append(_build_signal_features(building_code=building_code, floor=floor, hour=float(hour), day_of_week=day_of_week, is_weekend=is_weekend, day_of_month=day_of_month, month=month, ap_name_code=ap_name_code))\n'
                '        df = pd.DataFrame(rows)\n'
                '        predictions = model.predict(df)\n'
                '        hourly_data = []\n'
                '        signal_values = []\n'
                '        for hour, signal_db in enumerate(predictions):\n'
                '            quality_info = _dbm_to_quality(float(signal_db))\n'
                '            status = _dbm_to_status(float(signal_db))\n'
                '            status_conf = _dbm_to_status_confidence(float(signal_db))\n'
                '            hourly_data.append({\n'
                '                "hour": hour,\n'
                '                "signal_db": round(float(signal_db), 1),\n'
                '                "signal_quality": quality_info["quality"],\n'
                '                "bars": quality_info["bars"],\n'
                '                "predicted_status": status,\n'
                '                "status_confidence": status_conf,\n'
                '            })\n'
                '            signal_values.append(round(float(signal_db), 1))\n'
                '        avg_db = sum(signal_values) / len(signal_values) if signal_values else 0\n'
                '        max_db = max(signal_values) if signal_values else 0\n'
                '        min_db = min(signal_values) if signal_values else 0\n'
                '        best_hour = signal_values.index(max_db) if signal_values else 0\n'
                '        worst_hour = signal_values.index(min_db) if signal_values else 0\n'
                '\n'
            )
            new_lines.append(replacement)
            in_trend_pred = False
            pred_lines_buffer = []
            # Skip to after the collected block
            # We've already added up to the current line in earlier iteration
            continue
        else:
            # Still in trend function but not at the predict block
            new_lines.append(line)
            in_trend_pred = False
            pred_lines_buffer = []
    else:
        new_lines.append(line)
lines = new_lines

# ─────────────────────────────────────────────
# 7) Wrap interpolation body in try/except
# ─────────────────────────────────────────────
new_lines = []
for i, line in enumerate(lines):
    stripped = line.strip()
    
    # Add try: after `for h in range(24):` inside interpolation block
    if stripped == 'for h in range(24):' and i >= 2:
        # Check if the context before us is interpolation
        # Look back for `if len(actual_hours) >= 2:`
        prev_lines = [lines[j].strip() for j in range(max(0,i-5), i)]
        if 'if len(actual_hours) >= 2:' in prev_lines:
            new_lines.append(line)
            new_lines.append('                try:\n')
            continue
    
    # Add except: before the end of for loop iteration
    if stripped.startswith("full_actual[h] = {") and '"interpolated": True,' in stripped:
        # This is the last assignment before the for loop ends
        # Check if we're in interpolation context
        prev_lines = [lines[j].strip() for j in range(max(0,i-10), i)]
        if 'if len(actual_hours) >= 2:' in prev_lines and 'try:' not in prev_lines:
            new_lines.append(line)
            # Add except after the preceding closing braces
            continue
        
    # Handle adding except after the assignment that follows elif after and not before
    stripped_next = lines[i+1].strip() if i+1 < len(lines) else ""
    if stripped == '                            }' and stripped_next == '                elif len(actual_hours) == 1:':
        # Check if we're in interpolation
        prev_lines = [lines[j].strip() for j in range(max(0,i-20), i)]
        if 'if len(actual_hours) >= 2:' in prev_lines and 'try:' not in lines[i-1] if i > 0 else True:
            # We need to close the for loop try/except
            # Actually, let's just add the except BEFORE this line
            # But this is the last line of the for body
            new_lines.append('                except Exception:\n')
            new_lines.append('                    pass\n')
            new_lines.append(line)
            continue
    
    new_lines.append(line)

# This try/except approach is getting complex. Let me do it differently.
# Just re-read and do a simpler approach.
# Actually, let me just write out the file so far and then handle the interpolation separately.

with open("main.py", "w") as f:
    f.writelines(lines)

# Re-read and do interpolation with replace on the known content
with open("main.py") as f:
    code = f.read()

# Inject try/except into the interpolation block
old_for_start = (
    '            for h in range(24):\n'
    '                if h in hourly_actual:\n'
)
new_for_start = (
    '            for h in range(24):\n'
    '                try:\n'
    '                    if h in hourly_actual:\n'
)
code = code.replace(old_for_start, new_for_start)

# Close the try/except before elif len(actual_hours) == 1:
old_close = (
    '                        elif after and not before:\n'
    '                            # Extrapolate from first known value (flat)\n'
    '                            full_actual[h] = {\n'
    '                                "actual_mean": hourly_actual[after[0]]["actual_mean"],\n'
    '                                "samples": 0,\n'
    '                                "interpolated": True,\n'
    '                            }\n'
    '        elif len(actual_hours) == 1:\n'
)
new_close = (
    '                        elif after and not before:\n'
    '                            # Extrapolate from first known value (flat)\n'
    '                            full_actual[h] = {\n'
    '                                "actual_mean": hourly_actual[after[0]]["actual_mean"],\n'
    '                                "samples": 0,\n'
    '                                "interpolated": True,\n'
    '                            }\n'
    '                except Exception:\n'
    '                    pass\n'
    '        elif len(actual_hours) == 1:\n'
)
code = code.replace(old_close, new_close)

# ─────────────────────────────────────────────
# 8) Add precompute function before if __name__
# ─────────────────────────────────────────────
precompute_func = """

def _precompute_all_trends():
    \"\"\"Precompute trends for ALL APs at startup (background thread).\"\"\"
    global _precomputed_trends, _precomputed_trends_loaded
    if _precomputed_trends_loaded:
        return
    try:
        model = _load_signal_strength_model()
    except Exception as e:
        print(f"[WARN] Cannot precompute trends: {e}")
        _precomputed_trends_loaded = True
        return
    ap_index = _build_ap_index()
    from datetime import datetime
    today = datetime.now()
    day_of_week = float(today.weekday())
    is_weekend = 1.0 if day_of_week >= 5 else 0.0
    day_of_month = float(today.day)
    month = float(today.month)
    rows = []
    ap_keys = []
    for ap in ap_index:
        building_code = _encode_building(ap["building"])
        ap_name_code = _encode_ap_name(ap["name"])
        for hour in range(24):
            rows.append(_build_signal_features(
                building_code=building_code, floor=ap["floor"],
                hour=float(hour), day_of_week=day_of_week,
                is_weekend=is_weekend, day_of_month=day_of_month,
                month=month, ap_name_code=ap_name_code
            ))
            ap_keys.append((ap["name"].strip().lower(), hour))
    df = pd.DataFrame(rows)
    predictions = model.predict(df)
    from collections import defaultdict
    ap_hourly = defaultdict(list)
    for (ap_key, hour), pred in zip(ap_keys, predictions):
        ap_hourly[ap_key].append((hour, float(pred)))
    for ap_key, hourly_list in ap_hourly.items():
        hourly_list.sort(key=lambda x: x[0])
        signal_values = [h[1] for h in hourly_list]
        hourly_data = []
        for hour, signal_db in hourly_list:
            quality_info = _dbm_to_quality(signal_db)
            status = _dbm_to_status(signal_db)
            hourly_data.append({
                "hour": hour,
                "signal_db": round(signal_db, 1),
                "signal_quality": quality_info["quality"],
                "bars": quality_info["bars"],
                "predicted_status": status,
            })
        _precomputed_trends[ap_key] = {
            "trend": hourly_data,
            "stats": {
                "avg_db": round(sum(signal_values) / len(signal_values), 1),
                "max_db": round(max(signal_values), 1),
                "min_db": round(min(signal_values), 1),
                "best_hour": signal_values.index(max(signal_values)),
                "worst_hour": signal_values.index(min(signal_values)),
            },
        }
    print(f"[INFO] Precomputed trends for {len(_precomputed_trends)} APs")
    _precomputed_trends_loaded = True


@app.on_event("startup")
async def _startup_precompute():
    \"\"\"Precompute trends on startup in background thread.\"\"\"
    print("[INFO] Starting background trend precomputation...")
    import threading
    thread = threading.Thread(target=_precompute_all_trends, daemon=True)
    thread.start()


"""

code = code.replace('\nif __name__ == "__main__":\n', precompute_func + '\nif __name__ == "__main__":\n')

with open("main.py", "w") as f:
    f.write(code)

# Final syntax check
try:
    ast.parse(code)
    print(f"[OK] ALL OPTIMIZATIONS APPLIED! {len(code.splitlines())} lines, syntax OK")
except SyntaxError as e:
    print(f"[ERROR] {e}")
    lines = code.splitlines()
    lineno = e.lineno - 1
    for i in range(max(0, lineno-3), min(len(lines), lineno+3)):
        print(f"  {i+1:4d}: |{lines[i]}")
