#!/usr/bin/env python3
"""Line-number-based optimization - safe and precise."""

with open("main.py") as f:
    lines = f.readlines()

# ─── 1) Add globals after line 72 (0-indexed: 71) ───
# Line 72: _trend_cache_time: dict[str, float] = {}
insert_after = []
for i, line in enumerate(lines):
    insert_after.append(line)
    if i == 71:  # after line 72 (1-indexed)
        insert_after.append("_precomputed_trends: dict[str, dict] = {}  # {ap_name_lower: trend_data}\n")
        insert_after.append("_precomputed_trends_loaded: bool = False\n")
        insert_after.append("_ap_index_by_name: dict[str, dict] = {}  # {ap_name_lower: ap_entry}\n")
lines = insert_after

# ─── 2) Modify _build_ap_index's global line ───
# Find: "    global _ap_index" -> "    global _ap_index, _ap_index_by_name"
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped == "global _ap_index" and "global _ap_index, _ap_index_by_name" not in line:
        # Check this is inside _build_ap_index
        if i > 5 and "def _build_ap_index" in lines[i-5]:
            lines[i] = "    global _ap_index, _ap_index_by_name\n"
        break

# ─── 3) After `_ap_index.append({...})` add O(1) dict entry ───
# Find the `    return _ap_index\n` that immediately follows the append block in _build_ap_index
new_lines = []
skip_next = False
for i, line in enumerate(lines):
    if skip_next:
        skip_next = False
        continue
    stripped = line.rstrip()
    # Find: `        })\n` followed by `    return _ap_index\n`
    if stripped == '        })' and i + 1 < len(lines) and lines[i + 1].strip() == 'return _ap_index':
        new_lines.append(line)
        new_lines.append(
            '        # Build O(1) lookup\n'
            '        ap_key = ap_name.strip().lower()\n'
            '        if ap_key not in _ap_index_by_name:\n'
            '            _ap_index_by_name[ap_key] = _ap_index[-1]\n'
        )
    else:
        new_lines.append(line)
lines = new_lines

# ─── 4) Replace _find_ap_in_index body ───
new_lines = []
in_find = False
replaced_find = False
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped == "def _find_ap_in_index(ap_name: str) -> Optional[dict]:":
        in_find = True
        replaced_find = False
        new_lines.append(line)
        # Replace the function body
        new_lines.append("    _build_ap_index()  # ensure index is built\n")
        new_lines.append("    cache_key = ap_name.strip().lower()\n")
        new_lines.append("    return _ap_index_by_name.get(cache_key)\n")
        # Skip the old body lines
        continue
    if in_find:
        # Skip lines until we exit the function (dedent or empty line before next def)
        if stripped.startswith("def ") or (stripped == "" and i > 0 and lines[i-1].strip() == ""):
            in_find = False
            new_lines.append(line)
        # else skip old body
        continue
    new_lines.append(line)
lines = new_lines

# ─── 5) Add precompute + startup event before if __name__ == "__main__" ───
precompute_code = """

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

new_lines = []
for i, line in enumerate(lines):
    if line.strip() == 'if __name__ == "__main__":':
        new_lines.append(precompute_code)
        new_lines.append(line)
    else:
        new_lines.append(line)
lines = new_lines

# ─── 6) Add fast-path check in get_ap_daily_trend ───
# Find the block starting at "    ap_name_code = _encode_ap_name(ap_entry["name"])"
# This appears in 5 places. We only want the one in get_ap_daily_trend.
# Let's just find the one that's in that function and has the comment about current date.
# Better: find "ap_name_code = _encode_ap_name(ap_entry["name"])" preceded by
# "day_type = "weekend" if is_weekend else "weekday""

new_lines = []
in_trend_func = False
in_predict_block = False
pending_fast_path = False
prediction_block = []

for i, line in enumerate(lines):
    stripped = line.rstrip()
    
    if "def get_ap_daily_trend(ap_name: str):" in stripped:
        in_trend_func = True
        in_predict_block = False
        new_lines.append(line)
        continue
    
    if in_trend_func:
        # We're looking for the model load + ap_entry followed by predict block
        if stripped == "    ap_entry = _find_ap_in_index(ap_name)":
            pending_fast_path = True
            new_lines.append(line)
            continue
        
        if pending_fast_path:
            if 'raise HTTPException' in stripped:
                new_lines.append(line)
                continue
            
            if building := None:
                pass
            
            stripped_line = stripped
            
            # Check if this line starts the predict block
            if stripped_line == '    building = ap_entry["building"]':
                pending_fast_path = False
                
                # Add the fast-path check here
                new_lines.append('    \n')
                new_lines.append('    # Fast path: use precomputed trend if available\n')
                new_lines.append('    precomputed = _precomputed_trends.get(cache_key)\n')
                new_lines.append('    if precomputed is not None:\n')
                new_lines.append('        hourly_data = precomputed["trend"]\n')
                new_lines.append('        signal_values = [h["signal_db"] for h in hourly_data]\n')
                new_lines.append('        avg_db = precomputed["stats"]["avg_db"]\n')
                new_lines.append('        max_db = precomputed["stats"]["max_db"]\n')
                new_lines.append('        min_db = precomputed["stats"]["min_db"]\n')
                new_lines.append('        best_hour = precomputed["stats"]["best_hour"]\n')
                new_lines.append('        worst_hour = precomputed["stats"]["worst_hour"]\n')
                new_lines.append('    else:\n')
                new_lines.append('        # Slow path: compute on demand\n')
                
                # Collect the original predict block lines (indented 4 more under the else)
                old_block_start = i
                j = i
                original_block_lines = []
                while j < len(lines) and lines[j].strip():
                    original_block_lines.append(lines[j])
                    j += 1
                
                # Add the original block with +4 indent for the else body
                for bl in original_block_lines:
                    if bl.strip():
                        new_lines.append('    ' + bl)  # add 4 spaces
                    else:
                        new_lines.append(bl)
                
                # Skip past the original block in the main loop
                # Set i to j-1 (will be advanced by for loop)
                # We'll handle this differently - collect skip count
                skip_count = j - i - 1  # minus 1 because for loop adds 1
                
                # This is getting too complex. Let me use a different approach.
                # Just save and continue.
                pass
            else:
                new_lines.append(line)
            continue
        
        # Check if we're leaving the function
        if stripped.startswith("def ") or (stripped == "" and "return" in lines[i-1] if i > 0 else False):
            in_trend_func = False
            # fall through to new_lines
        # elif some other condition...
    
    new_lines.append(line)

# Actually this approach is too complex. Let me simplify radically.

print("Wrote line-based changes so far. Doing final polish...")

with open("main.py", "w") as f:
    f.writelines(lines)

import ast
try:
    ast.parse("".join(lines))
    print("[OK] Syntax OK!")
except SyntaxError as e:
    print(f"[ERROR] {e}")
