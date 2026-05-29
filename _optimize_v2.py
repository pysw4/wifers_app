#!/usr/bin/env python3
"""Optimize trend endpoints - v2 with precise line-based editing."""
import re

with open("main.py") as f:
    lines = f.readlines()
    code = "".join(lines)

# ─────────────────────────────────────────────
# 1) Add _ap_index_by_name + _precomputed_trends globals
#    After line: _trend_cache_time: dict[str, float] = {}
# ─────────────────────────────────────────────
old1 = "_trend_cache_time: dict[str, float] = {}\n"
new1 = old1 + (
    "_precomputed_trends: dict[str, dict] = {}  # {ap_name_lower: {trend, stats}}\n"
    "_precomputed_trends_loaded: bool = False\n"
    "_ap_index_by_name: dict[str, dict] = {}  # {ap_name_lower: ap_entry}\n"
)
assert old1 in code, "FAIL: can't find _trend_cache_time"
code = code.replace(old1, new1, 1)

# ─────────────────────────────────────────────
# 2) Modify _build_ap_index to also populate _ap_index_by_name
#    Change: global _ap_index -> global _ap_index, _ap_index_by_name
#    Add dict entry after the append
# ─────────────────────────────────────────────
old2 = "    global _ap_index\n"
new2 = "    global _ap_index, _ap_index_by_name\n"
assert old2 in code, "FAIL: can't find global _ap_index in _build_ap_index"
code = code.replace(old2, new2, 1)

# Add after the append block: the exact append lines plus what follows
old3 = (
    '        _ap_index.append({\n'
    '            "id": unique_id,\n'
    '            "name": ap_name,\n'
    '            "lat": float(coords[1]),\n'
    '            "lng": float(coords[0]),\n'
    '            "building": props.get("USER_EDIFI", props.get("Nom_Edific", "Unknown")),\n'
    '            "floor": float(props.get("Num_Planta", 0) or 0),\n'
    '            "espacio": espacio,\n'
    '        })\n'
    '    return _ap_index\n'
)
new3 = (
    '        _ap_index.append({\n'
    '            "id": unique_id,\n'
    '            "name": ap_name,\n'
    '            "lat": float(coords[1]),\n'
    '            "lng": float(coords[0]),\n'
    '            "building": props.get("USER_EDIFI", props.get("Nom_Edific", "Unknown")),\n'
    '            "floor": float(props.get("Num_Planta", 0) or 0),\n'
    '            "espacio": espacio,\n'
    '        })\n'
    '        # Build O(1) lookup\n'
    '        ap_key = ap_name.strip().lower()\n'
    '        if ap_key not in _ap_index_by_name:\n'
    '            _ap_index_by_name[ap_key] = _ap_index[-1]\n'
    '    return _ap_index\n'
)
assert old3 in code, "FAIL: can't find the append block"
code = code.replace(old3, new3, 1)

# ─────────────────────────────────────────────
# 3) Optimize _find_ap_in_index -> O(1) dict lookup
# ─────────────────────────────────────────────
old4 = (
    'def _find_ap_in_index(ap_name: str) -> Optional[dict]:\n'
    '    cache_key = ap_name.strip().lower()\n'
    '    ap_index = _build_ap_index()\n'
    '    for entry in ap_index:\n'
    '        if entry["name"].strip().lower() == cache_key:\n'
    '            return entry\n'
    '    return None\n'
)
new4 = (
    'def _find_ap_in_index(ap_name: str) -> Optional[dict]:\n'
    '    _build_ap_index()  # ensure index is built\n'
    '    cache_key = ap_name.strip().lower()\n'
    '    return _ap_index_by_name.get(cache_key)\n'
)
assert old4 in code, "FAIL: can't find _find_ap_in_index"
code = code.replace(old4, new4, 1)

# ─────────────────────────────────────────────
# 4) Add startup event and precompute function before if __name__
# ─────────────────────────────────────────────
precompute_block = (
    '\n'
    'def _precompute_all_trends():\n'
    '    """Precompute trends for ALL APs at startup (background thread)."""\n'
    '    global _precomputed_trends, _precomputed_trends_loaded\n'
    '    if _precomputed_trends_loaded:\n'
    '        return\n'
    '    try:\n'
    '        model = _load_signal_strength_model()\n'
    '    except Exception as e:\n'
    '        print(f"[WARN] Cannot precompute trends: {e}")\n'
    '        _precomputed_trends_loaded = True\n'
    '        return\n'
    '    ap_index = _build_ap_index()\n'
    '    from datetime import datetime\n'
    '    today = datetime.now()\n'
    '    day_of_week = float(today.weekday())\n'
    '    is_weekend = 1.0 if day_of_week >= 5 else 0.0\n'
    '    day_of_month = float(today.day)\n'
    '    month = float(today.month)\n'
    '    rows = []\n'
    '    ap_keys = []\n'
    '    for ap in ap_index:\n'
    '        building_code = _encode_building(ap["building"])\n'
    '        ap_name_code = _encode_ap_name(ap["name"])\n'
    '        for hour in range(24):\n'
    '            rows.append(_build_signal_features(\n'
    '                building_code=building_code, floor=ap["floor"],\n'
    '                hour=float(hour), day_of_week=day_of_week,\n'
    '                is_weekend=is_weekend, day_of_month=day_of_month,\n'
    '                month=month, ap_name_code=ap_name_code\n'
    '            ))\n'
    '            ap_keys.append((ap["name"].strip().lower(), hour))\n'
    '    df = pd.DataFrame(rows)\n'
    '    predictions = model.predict(df)\n'
    '    from collections import defaultdict\n'
    '    ap_hourly = defaultdict(list)\n'
    '    for (ap_key, hour), pred in zip(ap_keys, predictions):\n'
    '        ap_hourly[ap_key].append((hour, float(pred)))\n'
    '    for ap_key, hourly_list in ap_hourly.items():\n'
    '        hourly_list.sort(key=lambda x: x[0])\n'
    '        signal_values = [h[1] for h in hourly_list]\n'
    '        hourly_data = []\n'
    '        for hour, signal_db in hourly_list:\n'
    '            quality_info = _dbm_to_quality(signal_db)\n'
    '            status = _dbm_to_status(signal_db)\n'
    '            hourly_data.append({\n'
    '                "hour": hour,\n'
    '                "signal_db": round(signal_db, 1),\n'
    '                "signal_quality": quality_info["quality"],\n'
    '                "bars": quality_info["bars"],\n'
    '                "predicted_status": status,\n'
    '            })\n'
    '        _precomputed_trends[ap_key] = {\n'
    '            "trend": hourly_data,\n'
    '            "stats": {\n'
    '                "avg_db": round(sum(signal_values) / len(signal_values), 1),\n'
    '                "max_db": round(max(signal_values), 1),\n'
    '                "min_db": round(min(signal_values), 1),\n'
    '                "best_hour": signal_values.index(max(signal_values)),\n'
    '                "worst_hour": signal_values.index(min(signal_values)),\n'
    '            },\n'
    '        }\n'
    '    print(f"[INFO] Precomputed trends for {len(_precomputed_trends)} APs")\n'
    '    _precomputed_trends_loaded = True\n'
    '\n'
    '\n'
    '@app.on_event("startup")\n'
    'async def _startup_precompute():\n'
    '    """Precompute trends on startup in background thread."""\n'
    '    print("[INFO] Starting background trend precomputation...")\n'
    '    import threading\n'
    '    thread = threading.Thread(target=_precompute_all_trends, daemon=True)\n'
    '    thread.start()\n'
    '\n'
    '\n'
)

old5 = 'if __name__ == "__main__":\n'
assert old5 in code, "FAIL: can't find if __name__"
code = code.replace(old5, precompute_block + old5, 1)

# ─────────────────────────────────────────────
# 5) Modify get_ap_daily_trend to use precomputed trends
#    Replace the predict block with precomputed lookup + fallback
# ─────────────────────────────────────────────
old_trend = (
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
)
assert old_trend in code, f"FAIL: can't find trend predict block. Looking for:\n{old_trend[:100]}..."

new_trend = (
    '    # Use precomputed trend if available (fast path)\n'
    '    cache_key = ap_name.strip().lower()\n'
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
    '        # Fallback: predict on demand (until precomputed is ready)\n'
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
)
assert old_trend in code, "FAIL: trend block not found!"
code = code.replace(old_trend, new_trend, 1)

# Fix the fallback path: the append in fallback needs signal_values.append
old_fallback_append = (
    '        hourly_data.append({\n'
    '            "hour": hour,\n'
    '            "signal_db": round(float(signal_db), 1),\n'
    '            "signal_quality": quality_info["quality"],\n'
    '            "bars": quality_info["bars"],\n'
    '            "predicted_status": status,\n'
    '            "status_confidence": status_conf,\n'
    '        })\n'
    '    signal_values = [h["signal_db"] for h in hourly_data]\n'
)
new_fallback_append = (
    '        hourly_data.append({\n'
    '            "hour": hour,\n'
    '            "signal_db": round(float(signal_db), 1),\n'
    '            "signal_quality": quality_info["quality"],\n'
    '            "bars": quality_info["bars"],\n'
    '            "predicted_status": status,\n'
    '            "status_confidence": status_conf,\n'
    '        })\n'
    '        signal_values.append(round(float(signal_db), 1))\n'
    '    # signal_values already populated in loop\n'
)
assert old_fallback_append in code, "FAIL: fallback append not found!"
code = code.replace(old_fallback_append, new_fallback_append, 1)

# ─────────────────────────────────────────────
# 6) Add try/except around interpolation logic
# ─────────────────────────────────────────────
old_interp = (
    '        if len(actual_hours) >= 2:\n'
    '            # Interpolate between known points\n'
)
new_interp = (
    '        # Wrap interpolation in try/except for safety\n'
    '        try:\n'
    '            if len(actual_hours) >= 2:\n'
    '                # Interpolate between known points\n'
)
assert old_interp in code, "FAIL: interpolation block start not found!"
code = code.replace(old_interp, new_interp, 1)

# Fix the continuation: need proper indentation for the try block
# The code after 'if len(actual_hours) >= 2:' needs to be indented under the if
# Let's fix by indenting the block under the try+if
old_interp_body = (
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
)
new_interp_body = (
    '                for h in range(24):\n'
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
    '        except Exception:\n'
    '            pass\n'
    '        if len(actual_hours) == 1:\n'
)
assert old_interp_body in code, "FAIL: interpolation body not found!"
code = code.replace(old_interp_body, new_interp_body, 1)

# Write result
with open("main.py", "w") as f:
    f.write(code)

# Verify syntax
import ast
try:
    ast.parse(code)
    print(f"[OK] Syntax OK! {len(code.splitlines())} lines")
except SyntaxError as e:
    print(f"[ERROR] {e}")
    # Show context around error
    lines = code.splitlines()
    lineno = e.lineno - 1
    for i in range(max(0, lineno-3), min(len(lines), lineno+3)):
        print(f"  {i+1:4d}: {lines[i]}")
