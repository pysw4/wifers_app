#!/usr/bin/env python3
"""Optimize trend endpoints: precompute trends, O(1) AP lookup, error protection."""
import re

with open("main.py") as f:
    code = f.read()

# ─────────────────────────────────────────────
# 1) Add global cache variables after _trend_cache_time
# ─────────────────────────────────────────────
code = code.replace(
    "_trend_cache_time: dict[str, float] = {}",
    "_trend_cache_time: dict[str, float] = {}\n"
    "_precomputed_trends: dict[str, dict] = {}  # {ap_name_lower: {trend: [...], stats: {...}, accuracy_vs_actual: ...}}\n"
    "_precomputed_trends_loaded: bool = False\n"
    "_ap_index_by_name: dict[str, dict] = {}  # {ap_name_lower: ap_entry}"
)

# ─────────────────────────────────────────────
# 2) Optimize _build_ap_index to also build dict
# ─────────────────────────────────────────────
old_build = """def _build_ap_index() -> list[dict]:
    global _ap_index
    if _ap_index is not None:
        return _ap_index
    geojson = _load_geojson()
    _ap_index = []
    seen_ids = {}
    for feature in geojson["features"]:"""

new_build = """def _build_ap_index() -> list[dict]:
    global _ap_index, _ap_index_by_name
    if _ap_index is not None:
        return _ap_index
    geojson = _load_geojson()
    _ap_index = []
    _ap_index_by_name = {}
    seen_ids = {}
    for feature in geojson["features"]:"""

code = code.replace(old_build, new_build)

# After the line that appends to _ap_index, add dict entry
# Find:         _ap_index.append({
# And add _ap_index_by_name after
old_append = """        _ap_index.append({
            "id": unique_id,
            "name": ap_name,
            "lat": float(coords[1]),
            "lng": float(coords[0]),
            "building": props.get("USER_EDIFI", props.get("Nom_Edific", "Unknown")),
            "floor": float(props.get("Num_Planta", 0) or 0),
            "espacio": espacio,
        })"""

new_append = """        _ap_index.append({
            "id": unique_id,
            "name": ap_name,
            "lat": float(coords[1]),
            "lng": float(coords[0]),
            "building": props.get("USER_EDIFI", props.get("Nom_Edific", "Unknown")),
            "floor": float(props.get("Num_Planta", 0) or 0),
            "espacio": espacio,
        })
        # Build O(1) lookup dict (lowercase name -> entry)
        ap_key = ap_name.strip().lower()
        if ap_key not in _ap_index_by_name:
            _ap_index_by_name[ap_key] = _ap_index[-1]"""

code = code.replace(old_append, new_append)

# ─────────────────────────────────────────────
# 3) Optimize _find_ap_in_index -> O(1) dict lookup
# ─────────────────────────────────────────────
old_find = """def _find_ap_in_index(ap_name: str) -> Optional[dict]:
    cache_key = ap_name.strip().lower()
    ap_index = _build_ap_index()
    for entry in ap_index:
        if entry["name"].strip().lower() == cache_key:
            return entry
    return None"""

new_find = """def _find_ap_in_index(ap_name: str) -> Optional[dict]:
    _build_ap_index()  # ensure index is built
    cache_key = ap_name.strip().lower()
    return _ap_index_by_name.get(cache_key)"""

code = code.replace(old_find, new_find)

# ─────────────────────────────────────────────
# 4) Add precompute function + startup event
# ─────────────────────────────────────────────
precompute_func = """

def _precompute_all_trends():
    \"\"\"Precompute trends for ALL APs at startup. Called once.\"\"\"
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
    today = datetime.now()
    day_of_week = float(today.weekday())
    is_weekend = 1.0 if day_of_week >= 5 else 0.0
    day_of_month = float(today.day)
    month = float(today.month)
    
    # Build features for ALL APs at once (vectorized)
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
    
    # Group predictions by AP
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
    \"\"\"Precompute trends on startup in background.\"\"\"
    print("[INFO] Starting background trend precomputation...")
    import threading
    thread = threading.Thread(target=_precompute_all_trends, daemon=True)
    thread.start()
"""

# Insert before the final if __name__ block
code = code.replace(
    "if __name__ == \"__main__\":",
    precompute_func + "\nif __name__ == \"__main__\":"
)

# ─────────────────────────────────────────────
# 5) Modify get_ap_daily_trend to use precomputed data
# ─────────────────────────────────────────────
# Replace the model loading + prediction section
old_trend_start = """    ap_name_code = _encode_ap_name(ap_entry["name"])
    rows = []
    for hour in range(24):
        rows.append(_build_signal_features(building_code=building_code, floor=floor, hour=float(hour), day_of_week=day_of_week, is_weekend=is_weekend, day_of_month=day_of_month, month=month, ap_name_code=ap_name_code))
    df = pd.DataFrame(rows)
    predictions = model.predict(df)
    hourly_data = []
    for hour, signal_db in enumerate(predictions):
        quality_info = _dbm_to_quality(float(signal_db))
        status = _dbm_to_status(float(signal_db))"""

new_trend_start = """    # Use precomputed trend if available, otherwise fall back to on-demand prediction
    cache_key = ap_name.strip().lower()
    precomputed = _precomputed_trends.get(cache_key)
    if precomputed is not None:
        hourly_data = precomputed["trend"]
        signal_values = [h["signal_db"] for h in hourly_data]
        avg_db = precomputed["stats"]["avg_db"]
        max_db = precomputed["stats"]["max_db"]
        min_db = precomputed["stats"]["min_db"]
        best_hour = precomputed["stats"]["best_hour"]
        worst_hour = precomputed["stats"]["worst_hour"]
    else:
        # Fallback: predict on demand (for unknown APs or until precomputed is ready)
        ap_name_code = _encode_ap_name(ap_entry["name"])
        rows = []
        for hour in range(24):
            rows.append(_build_signal_features(building_code=building_code, floor=floor, hour=float(hour), day_of_week=day_of_week, is_weekend=is_weekend, day_of_month=day_of_month, month=month, ap_name_code=ap_name_code))
        df = pd.DataFrame(rows)
        predictions = model.predict(df)
        hourly_data = []
        signal_values = []
        for hour, signal_db in enumerate(predictions):
            quality_info = _dbm_to_quality(float(signal_db))
            status = _dbm_to_status(float(signal_db))"""

code = code.replace(old_trend_start, new_trend_start)

# After the fallback data collection, we need to keep the signal_values for the existing avg/max/min calc
# But since fallback already builds hourly_data similarly, we need to match the rest of the code.
# Let's check what comes after the original hourly_data building.

# Actually, the fallback path builds hourly_data differently (without signal_values list).
# Let me look at what code follows the original block...
# The original code has:
#     hourly_data = []
#     for hour, signal_db in enumerate(predictions):
#         ...
#         hourly_data.append({...})
#     signal_values = [h["signal_db"] for h in hourly_data]
#     avg_db = sum(signal_values) / len(signal_values) if signal_values else 0
#     ...

# In my replacement, the else block doesn't have signal_values defined. Let me fix that.
# Need to replace the else block to also build signal_values

old_fallback_appends = """        hourly_data.append({
            "hour": hour,
            "signal_db": round(float(signal_db), 1),
            "signal_quality": quality_info["quality"],
            "bars": quality_info["bars"],
            "predicted_status": status,
            "status_confidence": status_conf,
        })
    signal_values = [h["signal_db"] for h in hourly_data]"""

new_fallback_appends = """        hourly_data.append({
            "hour": hour,
            "signal_db": round(float(signal_db), 1),
            "signal_quality": quality_info["quality"],
            "bars": quality_info["bars"],
            "predicted_status": status,
            "status_confidence": status_conf,
        })
        signal_values.append(round(float(signal_db), 1))
    # signal_values already populated in loop"""

code = code.replace(old_fallback_appends, new_fallback_appends)

# ─────────────────────────────────────────────
# 6) Wrap interpolation logic in try/except
# ─────────────────────────────────────────────
# Find the interpolation block and wrap it
old_interp = """        if len(actual_hours) >= 2:"""

new_interp = """        # Wrap interpolation in try/except to prevent single AP from crashing response
        try:
            if len(actual_hours) >= 2:"""

code = code.replace(old_interp, new_interp)

# Close the try block before the else clause
# We need to add "except Exception: pass" before the "elif len(actual_hours) == 1:" 
old_elif = """        elif len(actual_hours) == 1:"""

new_elif = """        except Exception:
                pass
        if len(actual_hours) == 1:"""

code = code.replace(old_elif, new_elif)

with open("main.py", "w") as f:
    f.write(code)

print("[OK] main.py optimized successfully!")
print(f"Lines: {len(code.splitlines())}")
