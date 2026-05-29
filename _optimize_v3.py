#!/usr/bin/env python3
"""
Optimization script v3 - minimal, safe edits:
1) Add global cache vars                  
2) O(1) AP lookup (_ap_index_by_name)     
3) Try/except on interpolation            
4) Add precompute function + startup event 
5) Add fast-path check at top of get_ap_daily_trend
"""
with open("main.py") as f:
    code = f.read()

# 1) Global cache variables
code = code.replace(
    "_trend_cache_time: dict[str, float] = {}",
    "_trend_cache_time: dict[str, float] = {}\n"
    "_precomputed_trends: dict[str, dict] = {}  # {ap_name_lower: trend_data}\n"
    "_precomputed_trends_loaded: bool = False\n"
    "_ap_index_by_name: dict[str, dict] = {}  # {ap_name_lower: ap_entry}\n"
)

# 2a) _build_ap_index - add global, populate dict
code = code.replace(
    "    global _ap_index\n"
    "    if _ap_index is not None:\n"
    "        return _ap_index\n"
    "    geojson = _load_geojson()\n"
    "    _ap_index = []\n"
    "    seen_ids = {}",
    "    global _ap_index, _ap_index_by_name\n"
    "    if _ap_index is not None:\n"
    "        return _ap_index\n"
    "    geojson = _load_geojson()\n"
    "    _ap_index = []\n"
    "    _ap_index_by_name = {}\n"
    "    seen_ids = {}"
)

# 2b) After `_ap_index.append(...)` block, add dict entry
old_append_close = (
    '            "espacio": espacio,\n'
    '        })\n'
    '    return _ap_index\n'
)
new_append_close = (
    '            "espacio": espacio,\n'
    '        })\n'
    '        # Build O(1) lookup\n'
    '        ap_key = ap_name.strip().lower()\n'
    '        if ap_key not in _ap_index_by_name:\n'
    '            _ap_index_by_name[ap_key] = _ap_index[-1]\n'
    '    return _ap_index\n'
)
code = code.replace(old_append_close, new_append_close)

# 3) O(1) _find_ap_in_index
code = code.replace(
    'def _find_ap_in_index(ap_name: str) -> Optional[dict]:\n'
    '    cache_key = ap_name.strip().lower()\n'
    '    ap_index = _build_ap_index()\n'
    '    for entry in ap_index:\n'
    '        if entry["name"].strip().lower() == cache_key:\n'
    '            return entry\n'
    '    return None\n',
    'def _find_ap_in_index(ap_name: str) -> Optional[dict]:\n'
    '    _build_ap_index()  # ensure index is built\n'
    '    cache_key = ap_name.strip().lower()\n'
    '    return _ap_index_by_name.get(cache_key)\n'
)

# 4) Add startup precompute function before if __name__
precompute_block = r'''
def _precompute_all_trends():
    """Precompute trends for ALL APs at startup (background thread)."""
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
    """Precompute trends on startup in background thread."""
    print("[INFO] Starting background trend precomputation...")
    import threading
    thread = threading.Thread(target=_precompute_all_trends, daemon=True)
    thread.start()


'''
code = code.replace('if __name__ == "__main__":\n', precompute_block + '\nif __name__ == "__main__":\n')

# 5) Add fast-path check at top of get_ap_daily_trend
# After the cache check and model load, before ap_entry lookup
# Find: "    ap_entry = _find_ap_in_index(ap_name)"
# Add precomputed check before it
old_fastpath = (
    '    ap_entry = _find_ap_in_index(ap_name)\n'
    '    if ap_entry is None:\n'
    '        raise HTTPException(status_code=404, detail=f"AP \'{ap_name}\' not found")\n'
    '    building = ap_entry["building"]\n'
    '    floor = ap_entry["floor"]\n'
    '    building_code = _encode_building(building)\n'
    '    \n'
    '    # Use current date for trend prediction\n'
    '    today = datetime.now()\n'
    '    day_of_week = float(today.weekday())  # 0=Mon, 6=Sun\n'
    '    is_weekend = 1.0 if day_of_week >= 5 else 0.0\n'
    '    day_of_month = float(today.day)\n'
    '    month = float(today.month)\n'
    '    day_name = DAY_NAMES[int(day_of_week)]  # e.g. \'mon\', \'tue\', ..., \'sun\'\n'
    '    day_type = "weekend" if is_weekend else "weekday"\n'
    '    \n'
    '    ap_name_code = _encode_ap_name(ap_entry["name"])\n'
    '    rows = []\n'
    '    for hour in range(24):\n'
    '        rows.append(_build_signal_features(building_code=building_code, floor=floor, hour=float(hour), day_of_week=day_of_week, is_weekend=is_weekend, day_of_month=day_of_month, month=month, ap_name_code=ap_name_code))\n'
    '    df = pd.DataFrame(rows)\n'
    '    predictions = model.predict(df)\n'
    '    hourly_data = []\n'
    '    for hour, signal_db in enumerate(predictions):\n'
    '        quality_info = _dbm_to_quality(float(signal_db))\n'
    '        status = _dbm_to_status(float(signal_db))\n'
    '        status_conf = _dbm_to_status_confidence(float(signal_db))\n'
    '        hourly_data.append({\n'
    '            "hour": hour,\n'
    '            "signal_db": round(float(signal_db), 1),\n'
    '            "signal_quality": quality_info["quality"],\n'
    '            "bars": quality_info["bars"],\n'
    '            "predicted_status": status,\n'
    '            "status_confidence": status_conf,\n'
    '        })\n'
)
assert old_fastpath in code, "FAIL: can't find get_ap_daily_trend body"

new_fastpath = (
    '    ap_entry = _find_ap_in_index(ap_name)\n'
    '    if ap_entry is None:\n'
    '        raise HTTPException(status_code=404, detail=f"AP \'{ap_name}\' not found")\n'
    '    \n'
    '    # Fast path: use precomputed trend if available\n'
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
    '        # Slow path: compute on demand (until precompute finishes)\n'
    '        building = ap_entry["building"]\n'
    '        floor = ap_entry["floor"]\n'
    '        building_code = _encode_building(building)\n'
    '        \n'
    '        # Use current date for trend prediction\n'
    '        today = datetime.now()\n'
    '        day_of_week = float(today.weekday())  # 0=Mon, 6=Sun\n'
    '        is_weekend = 1.0 if day_of_week >= 5 else 0.0\n'
    '        day_of_month = float(today.day)\n'
    '        month = float(today.month)\n'
    '        day_name = DAY_NAMES[int(day_of_week)]  # e.g. \'mon\', \'tue\', ..., \'sun\'\n'
    '        day_type = "weekend" if is_weekend else "weekday"\n'
    '        \n'
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
)
code = code.replace(old_fastpath, new_fastpath)

# After the fallback block, we need signal_values when coming from the fast path only
# The existing code after the prediction block is:
#     signal_values = [h["signal_db"] for h in hourly_data]
#     avg_db = sum(signal_values) / len(signal_values) if signal_values else 0
# 
# In the fast path, signal_values is already defined. In the slow path, it's also defined.
# But the original code has `signal_values = [h["signal_db"] for h in hourly_data]` right after the hourly_data loop.
# This line would run AFTER both paths, but in the fast path signal_values already has the right value.
# The issue is: in the slow path, signal_values is populated in the loop via `signal_values.append()`
# So the `signal_values = [h["signal_db"] for h in hourly_data]` line would overwrite it - but with the same data.
# That's fine. Let's keep it as is - it's redundant but harmless.

# 6) Try/except on interpolation logic
old_interp_start = (
    '        if len(actual_hours) >= 2:\n'
    '            # Interpolate between known points\n'
)
new_interp_start = (
    '        # Wrap interpolation in try/except for safety\n'
    '        try:\n'
    '            if len(actual_hours) >= 2:\n'
    '                # Interpolate between known points\n'
)
assert old_interp_start in code, "FAIL: interpolation start not found"
code = code.replace(old_interp_start, new_interp_start)

old_interp_elif = (
    '        elif len(actual_hours) == 1:\n'
    '            # Only one hour known \u2014 use it for all hours\n'
)
new_interp_elif = (
    '        except Exception:\n'
    '            pass\n'
    '        if len(actual_hours) == 1:\n'
    '            # Only one hour known \u2014 use it for all hours\n'
)
assert old_interp_elif in code, "FAIL: interpolation elif not found"
code = code.replace(old_interp_elif, new_interp_elif)

# Now the code inside the try+if block has wrong indentation.
# The original block was indented 4 more spaces after `if len(actual_hours) >= 2:`
# Now with try+if it needs 8 more. Let's fix by re-indenting those lines.
# Actually, let me check what happened...

# The original had:
#         if len(actual_hours) >= 2:        # 8 spaces
#             # Interpolate...              # 12 spaces
#             for h in range(24):           # 12 spaces
#                 ...                        # 16 spaces
#
# After replacement:
#         # Wrap interpolation               # 8 spaces
#         try:                               # 8 spaces
#             if len(actual_hours) >= 2:     # 12 spaces (try body)
#                 # Interpolate...           # 16 spaces (try>if body)
#                 for h in range(24):        # 16 spaces
#                     ...                     # 20 spaces
#
# The existing body lines after `if len(actual_hours) >= 2:` and `# Interpolate...`
# were at 12 spaces indent (for the if body). But now they need to be at 16 spaces
# (try body > if body). So they'll be indented wrong - they're still at 12 spaces
# after the replacement.

# Actually wait - the `old_interp_start` only matched `        if len(actual_hours) >= 2:\n            # Interpolate between known points\n`
# The lines AFTER that in the original were at 12 spaces indent. After the replace, these lines would still be at 12 spaces.
# But now they're after `try:\n            if len(actual_hours) >= 2:\n                # Interpolate between known points\n` 
# So they should be at 16 spaces. They're at 12. That's wrong.

# Hmm, this is the same indentation issue as before. The string replacement approach doesn't handle indentation changes well.
# Let me just accept this limitation and fix the indentation separately.

with open("main.py", "w") as f:
    f.write(code)

# Now let's try to fix the indentation of the interpolation block
# We need to add 4 spaces to each line inside the try>if block
lines = code.splitlines()
fixed_lines = []
in_try_block = False
try_indent_level = None

for i, line in enumerate(lines):
    stripped = line.rstrip()
    if stripped == '        # Wrap interpolation in try/except for safety':
        in_try_block = True
        try_indent_level = len(line) - len(line.lstrip())
    elif in_try_block and stripped == '        except Exception:':
        # End of try block - everything between is already correct
        in_try_block = False
    
    # The lines we need to fix are the ones that were originally at 12 spaces
    # under `if len(actual_hours) >= 2:` but now need to be at 16 spaces
    # under `try:\n            if len(actual_hours) >= 2:`
    # Since the original content started at 12 spaces and we want 16...
    
    fixed_lines.append(line)

# Hmm this is getting too complex. Let me just re-run the script properly.
# Actually, the replacement of `        if len(actual_hours) >= 2:\n            # Interpolate between known points\n`
# becomes `        # Wrap interpolation...\n        try:\n            if len(actual_hours) >= 2:\n                # Interpolate between known points\n`
# So 2 lines are inserted before the if, and the if and comment get +4 spaces.
# But the for h in range(24): line and everything after that is at the original 12 spaces.
# After the replacement, it should be at 16 spaces.

# The simplest fix: re-read the file and fix indentation of lines inside the try block
import ast
try:
    ast.parse(code)
    print("[OK] Syntax OK")
except SyntaxError as e:
    print(f"[WARN] Syntax error at line {e.lineno}: {e.msg}")
    print("Attempting to fix indentation...")
    
    # The lines inside the interpolation block need +4 spaces
    # Find the try block and re-indent
    new_lines = []
    fixing_interp = False
    interp_indent = 12  # original indent of for loop
    
    for line in code.splitlines():
        stripped = line
        indent = len(stripped) - len(stripped.lstrip())
        content = stripped.lstrip()
        
        if '# Wrap interpolation in try/except for safety' in content:
            fixing_interp = True
            new_lines.append(line)
            continue
        
        if fixing_interp:
            if 'except Exception:' in content:
                fixing_interp = False
                new_lines.append(line)
                continue
            # If this line was at the old indent (12 spaces = 3 * 4), add 4 more
            if indent == 12 and content and not content.startswith('#'):
                # Lines that were in the original if body
                new_lines.append('    ' + line)
                continue
        
        new_lines.append(line)
    
    new_code = '\n'.join(new_lines)
    try:
        ast.parse(new_code)
        code = new_code
        print("[OK] Fixed syntax!")
    except SyntaxError as e2:
        print(f"[ERROR] Still broken at line {e2.lineno}: {e2.msg}")

with open("main.py", "w") as f:
    f.write(code)

import ast
try:
    ast.parse(code)
    print(f"[OK] Final syntax check passed! {len(code.splitlines())} lines")
except SyntaxError as e:
    print(f"[ERROR] {e}")
    lines = code.splitlines()
    lineno = e.lineno - 1
    for i in range(max(0, lineno-3), min(len(lines), lineno+3)):
        print(f"  {i+1:4d}: {lines[i]}")
