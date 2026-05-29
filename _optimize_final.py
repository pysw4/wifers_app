#!/usr/bin/env python3
"""
Clean, minimal trend optimization.
Strategy: 
  - #1-#4: Simple string operations (no indentation issues)
  - #5: Use replace_in_file style - replace exact blocks from original file
  - #6: Minimal change to interpolate - just wrap the for h body in try/except
"""
with open("main.py") as f:
    code = f.read()

# ─── 1) Add global cache variables after line 72 ───
code = code.replace(
    "_trend_cache_time: dict[str, float] = {}",
    "_trend_cache_time: dict[str, float] = {}\n"
    "_precomputed_trends: dict[str, dict] = {}\n"
    "_precomputed_trends_loaded: bool = False\n"
    "_ap_index_by_name: dict[str, dict] = {}"
)

# ─── 2) _build_ap_index - add global + init dict ───
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

# ─── 3) After append block, add dict entry ───
code = code.replace(
    '            "espacio": espacio,\n'
    '        })\n'
    '    return _ap_index\n',
    '            "espacio": espacio,\n'
    '        })\n'
    '        # Build O(1) lookup dict\n'
    '        ap_key = ap_name.strip().lower()\n'
    '        if ap_key not in _ap_index_by_name:\n'
    '            _ap_index_by_name[ap_key] = _ap_index[-1]\n'
    '    return _ap_index\n'
)

# ─── 4) O(1) _find_ap_in_index ───
code = code.replace(
    'def _find_ap_in_index(ap_name: str) -> Optional[dict]:\n'
    '    cache_key = ap_name.strip().lower()\n'
    '    ap_index = _build_ap_index()\n'
    '    for entry in ap_index:\n'
    '        if entry["name"].strip().lower() == cache_key:\n'
    '            return entry\n'
    '    return None\n',
    'def _find_ap_in_index(ap_name: str) -> Optional[dict]:\n'
    '    _build_ap_index()\n'
    '    cache_key = ap_name.strip().lower()\n'
    '    return _ap_index_by_name.get(cache_key)\n'
)

# ─── 5) In get_ap_daily_trend: wrap prediction in if/else with precomputed check ───
# Find the exact prediction block in get_ap_daily_trend  
# (the one preceded by day_type = "weekend" ... day_name = ...)
old_predict = (
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
    '    signal_values = [h["signal_db"] for h in hourly_data]\n'
    '    avg_db = sum(signal_values) / len(signal_values) if signal_values else 0\n'
    '    max_db = max(signal_values) if signal_values else 0\n'
    '    min_db = min(signal_values) if signal_values else 0\n'
    '    best_hour = signal_values.index(max(signal_values))\n'
    '    worst_hour = signal_values.index(min(signal_values))\n'
)

new_predict = (
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
    '        best_hour = signal_values.index(max(signal_values))\n'
    '        worst_hour = signal_values.index(min(signal_values))\n'
)

assert old_predict in code, "FAIL: prediction block not found"
code = code.replace(old_predict, new_predict)

# ─── 6) Wrap interpolation body in try/except (minimal change) ───
old_interp = (
    '        if len(actual_hours) >= 2:\n'
    '            # Interpolate between known points\n'
    '            for h in range(24):\n'
    '                if h in hourly_actual:\n'
    '                    full_actual[h] = {\n'
    '                        "actual_mean": hourly_actual[h]["actual_mean"],\n'
    '                        "samples": hourly_actual[h]["samples"],\n'
    '                        "interpolated": False,\n'
    '                    }\n'
    '                else:\n'
    '                    # Find nearest known hours before and after\n'
    '                    before = [ah for ah in actual_hours if ah < h]\n'
    '                    after = [ah for ah in actual_hours if ah > h]\n'
    '                    \n'
    '                    if before and after:\n'
    '                        h_before = before[-1]\n'
    '                        h_after = after[0]\n'
    '                        v_before = hourly_actual[h_before]["actual_mean"]\n'
    '                        v_after = hourly_actual[h_after]["actual_mean"]\n'
    '                        # Linear interpolation\n'
    '                        ratio = (h - h_before) / (h_after - h_before)\n'
    '                        interpolated = v_before + (v_after - v_before) * ratio\n'
    '                        full_actual[h] = {\n'
    '                            "actual_mean": round(interpolated, 1),\n'
    '                            "samples": 0,\n'
    '                            "interpolated": True,\n'
    '                        }\n'
    '                    elif before and not after:\n'
    '                        # Extrapolate from last known value (flat)\n'
    '                        full_actual[h] = {\n'
    '                            "actual_mean": hourly_actual[before[-1]]["actual_mean"],\n'
    '                            "samples": 0,\n'
    '                            "interpolated": True,\n'
    '                        }\n'
    '                    elif after and not before:\n'
    '                        # Extrapolate from first known value (flat)\n'
    '                        full_actual[h] = {\n'
    '                            "actual_mean": hourly_actual[after[0]]["actual_mean"],\n'
    '                            "samples": 0,\n'
    '                            "interpolated": True,\n'
    '                        }\n'
    '        elif len(actual_hours) == 1:\n'
    '            # Only one hour known \u2014 use it for all hours\n'
)

new_interp = (
    '        if len(actual_hours) >= 2:\n'
    '            # Interpolate between known points\n'
    '            for h in range(24):\n'
    '                try:\n'
    '                    if h in hourly_actual:\n'
    '                        full_actual[h] = {\n'
    '                            "actual_mean": hourly_actual[h]["actual_mean"],\n'
    '                            "samples": hourly_actual[h]["samples"],\n'
    '                            "interpolated": False,\n'
    '                        }\n'
    '                    else:\n'
    '                        # Find nearest known hours before and after\n'
    '                        before = [ah for ah in actual_hours if ah < h]\n'
    '                        after = [ah for ah in actual_hours if ah > h]\n'
    '                        \n'
    '                        if before and after:\n'
    '                            h_before = before[-1]\n'
    '                            h_after = after[0]\n'
    '                            v_before = hourly_actual[h_before]["actual_mean"]\n'
    '                            v_after = hourly_actual[h_after]["actual_mean"]\n'
    '                            # Linear interpolation\n'
    '                            ratio = (h - h_before) / (h_after - h_before)\n'
    '                            interpolated = v_before + (v_after - v_before) * ratio\n'
    '                            full_actual[h] = {\n'
    '                                "actual_mean": round(interpolated, 1),\n'
    '                                "samples": 0,\n'
    '                                "interpolated": True,\n'
    '                            }\n'
    '                        elif before and not after:\n'
    '                            # Extrapolate from last known value (flat)\n'
    '                            full_actual[h] = {\n'
    '                                "actual_mean": hourly_actual[before[-1]]["actual_mean"],\n'
    '                                "samples": 0,\n'
    '                                "interpolated": True,\n'
    '                            }\n'
    '                        elif after and not before:\n'
    '                            # Extrapolate from first known value (flat)\n'
    '                            full_actual[h] = {\n'
    '                                "actual_mean": hourly_actual[after[0]]["actual_mean"],\n'
    '                                "samples": 0,\n'
    '                                "interpolated": True,\n'
    '                            }\n'
    '                except Exception:\n'
    '                    full_actual[h] = {"actual_mean": 0, "samples": 0, "interpolated": True}\n'
    '        elif len(actual_hours) == 1:\n'
    '            # Only one hour known \u2014 use it for all hours\n'
)

assert old_interp in code, "FAIL: interpolation block not found"
code = code.replace(old_interp, new_interp)

with open("main.py", "w") as f:
    f.write(code)

# ─── 7) Append precompute function + startup event before if __name__ ───
# Read back and insert before if __name__
with open("main.py") as f:
    code = f.read()

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
import ast
try:
    ast.parse(code)
    print(f"[OK] ALL OPTIMIZATIONS APPLIED! {len(code.splitlines())} lines, syntax OK")
except SyntaxError as e:
    print(f"[ERROR] {e}")
    lines = code.splitlines()
    lineno = e.lineno - 1
    for i in range(max(0, lineno-3), min(len(lines), lineno+3)):
        print(f"  {i+1:4d}: |{lines[i]}")
