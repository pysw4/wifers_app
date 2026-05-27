#!/usr/bin/env python3
"""
Wifers App - FastAPI Backend Server

Provides REST API endpoints for:
  - /predict: AP status prediction (Up/Down) - v3 model (真实可用特征)
  - /predict/signal_strength/heatmap: Pre-computed signal strength heatmap
  - /predict/signal_strength/ap_trend: Daily signal trend for a specific AP
  - /recommend: AP recommendation based on location and preferences
  - /route: Basic routing between two points
  - /route/advanced: Advanced routing with signal-aware pathfinding
  - /health: Health check endpoint
  - /status: Detailed server status
  - /cache/status: Cache statistics

Pre-computed heatmap files are served from precomputed/{day}/heatmap_h{hour}.json.
"""

import json
import math
import os
import time
from pathlib import Path
from typing import Any, Optional

import joblib
import pandas as pd
import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "models"
PRECOMPUTED_DIR = BASE_DIR / "precomputed"
GEOJSON_PATH = BASE_DIR / "geolocation_package" / "data" / "aps_geolocalizados_wgs84.geojson"

DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_FULL_NAMES = {
    "monday": "mon", "tuesday": "tue", "wednesday": "wed",
    "thursday": "thu", "friday": "fri", "saturday": "sat", "sunday": "sun",
}
NIGHT_REPRESENTATIVE_HOUR = 3
HEATMAP_CACHE_TTL = 3600
TREND_CACHE_TTL = 1800

app = FastAPI(title="Wifers App API", description="Backend API for Wi-Fi signal prediction and recommendation", version="3.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

_decision_tree_v3: Any = None
_decision_tree_v3_meta: Optional[dict] = None
_building_encoder: Any = None
_signal_strength_model: Any = None
_signal_strength_meta: Any = None
_geojson_data: Optional[dict] = None
_ap_index: Optional[list[dict]] = None
_buildings_list: Optional[list[str]] = None
_heatmap_cache: dict[str, dict] = {}
_heatmap_cache_time: dict[str, float] = {}
_trend_cache: dict[str, dict] = {}
_trend_cache_time: dict[str, float] = {}


def _load_decision_tree_v3():
    global _decision_tree_v3, _decision_tree_v3_meta
    if _decision_tree_v3 is None:
        path = MODELS_DIR / "decision_tree_v3.joblib"
        if not path.exists():
            path = MODELS_DIR / "decision_tree.joblib"
            if not path.exists():
                raise FileNotFoundError("No decision tree model found")
        _decision_tree_v3 = joblib.load(path)
        meta_path = MODELS_DIR / "decision_tree_meta_v3.json"
        if meta_path.exists():
            with open(meta_path) as f:
                _decision_tree_v3_meta = json.load(f)
        else:
            _decision_tree_v3_meta = {}
    return _decision_tree_v3


def _load_building_encoder():
    global _building_encoder
    if _building_encoder is None:
        path = MODELS_DIR / "building_encoder.joblib"
        if path.exists():
            _building_encoder = joblib.load(path)
    return _building_encoder


def _load_signal_strength_model():
    global _signal_strength_model
    if _signal_strength_model is None:
        path = MODELS_DIR / "signal_strength_model.joblib"
        if not path.exists():
            raise FileNotFoundError(f"Signal strength model not found: {path}")
        _signal_strength_model = joblib.load(path)
    return _signal_strength_model


def _load_signal_strength_meta():
    global _signal_strength_meta
    if _signal_strength_meta is None:
        path = MODELS_DIR / "signal_strength_meta.joblib"
        if path.exists():
            _signal_strength_meta = joblib.load(path)
    return _signal_strength_meta or {}


def _load_geojson() -> dict:
    global _geojson_data
    if _geojson_data is None:
        if not GEOJSON_PATH.exists():
            raise FileNotFoundError(f"GeoJSON file not found: {GEOJSON_PATH}")
        with open(GEOJSON_PATH) as f:
            _geojson_data = json.load(f)
    return _geojson_data


def _build_ap_index() -> list[dict]:
    global _ap_index
    if _ap_index is not None:
        return _ap_index
    geojson = _load_geojson()
    _ap_index = []
    for feature in geojson["features"]:
        props = feature["properties"]
        coords = feature["geometry"]["coordinates"]
        _ap_index.append({
            "id": props.get("USER_ID", props.get("USER_NOM_A", "")),
            "name": props.get("USER_NOM_A", "Unknown"),
            "lat": float(coords[1]),
            "lng": float(coords[0]),
            "building": props.get("USER_EDIFI", "Unknown"),
            "floor": float(props.get("Num_Planta", 0) or 0),
            "espacio": props.get("USER_Espai", ""),
        })
    return _ap_index


def _get_buildings_list() -> list[str]:
    global _buildings_list
    if _buildings_list is not None:
        return _buildings_list
    index = _build_ap_index()
    buildings = sorted({ap["building"] for ap in index if ap["building"] != "Unknown"})
    _buildings_list = buildings
    return _buildings_list


def _validate_day(day: str) -> str:
    day_lower = day.strip().lower()
    if day_lower in DAY_NAMES:
        return day_lower
    if day_lower in DAY_FULL_NAMES:
        return DAY_FULL_NAMES[day_lower]
    raise HTTPException(status_code=400, detail=f"Invalid day: '{day}'. Must be one of {DAY_NAMES}")


def _validate_hour(hour: int) -> int:
    if not isinstance(hour, int) or hour < 0 or hour > 23:
        raise HTTPException(status_code=400, detail=f"Invalid hour: {hour}. Must be an integer between 0 and 23.")
    return hour


def _get_heatmap_filepath(day: str, hour: int) -> Path:
    effective_hour = NIGHT_REPRESENTATIVE_HOUR if hour < 7 else hour
    return PRECOMPUTED_DIR / day / f"heatmap_h{effective_hour}.json"


def _load_heatmap_file(day: str, hour: int) -> dict:
    cache_key = f"{day}_h{hour}"
    now = time.time()
    if cache_key in _heatmap_cache:
        if now - _heatmap_cache_time.get(cache_key, 0) < HEATMAP_CACHE_TTL:
            data = _heatmap_cache[cache_key]
            data["hour"] = hour
            return data
    filepath = _get_heatmap_filepath(day, hour)
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"Heatmap not found for {day} hour {hour}")
    with open(filepath) as f:
        data = json.load(f)
    _heatmap_cache[cache_key] = data
    _heatmap_cache_time[cache_key] = now
    data["hour"] = hour
    return data


def _encode_building(building_name: str) -> int:
    encoder = _load_building_encoder()
    meta = _load_signal_strength_meta()
    buildings_list = meta.get("buildings", [])
    if encoder is not None and building_name in encoder.classes_:
        return int(encoder.transform([building_name])[0])
    for i, b in enumerate(buildings_list):
        if building_name.lower() in b.lower() or b.lower() in building_name.lower():
            return i
    return 0


def _dbm_to_quality(dbm: float) -> dict:
    if dbm >= -50:
        return {"quality": "Excellent", "bars": 5}
    elif dbm >= -60:
        return {"quality": "Good", "bars": 4}
    elif dbm >= -70:
        return {"quality": "Fair", "bars": 3}
    elif dbm >= -80:
        return {"quality": "Weak", "bars": 2}
    else:
        return {"quality": "Very Poor", "bars": 1}


def _haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2)
    c = 2 * math.asin(math.sqrt(a))
    return R * c


def _approximate_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    lat_diff = (lat2 - lat1) * 111_320
    lng_diff = (lng2 - lng1) * 111_320 * abs(math.cos(math.radians((lat1 + lat2) / 2)))
    return math.sqrt(lat_diff ** 2 + lng_diff ** 2)


def _build_signal_features(building_code: int, floor: float, hour: float, day_of_week: float, is_weekend: float, day_of_month: float, month: float) -> dict:
    return {"building_code": building_code, "floor": floor, "hour": hour, "band": 5.0, "day_of_week": day_of_week, "is_weekend": is_weekend, "day_of_month": day_of_month, "month": month}


def _build_v3_decision_features(hour: float, day_of_week: float, is_weekend: float, day_of_month: float, month: float, building_code: int, floor: float, lat: float, lng: float, predicted_signal_db: float) -> list[list[float]]:
    return [[hour, day_of_week, is_weekend, month, day_of_month, building_code, floor, lat, lng, predicted_signal_db]]


def _find_ap_in_index(ap_name: str) -> Optional[dict]:
    cache_key = ap_name.strip().lower()
    ap_index = _build_ap_index()
    for entry in ap_index:
        if entry["name"].strip().lower() == cache_key:
            return entry
    return None


def _predict_signal_for_ap(ap_entry: dict, hour: float, day_of_week: float, is_weekend: float, day_of_month: float, month: float) -> float:
    model = _load_signal_strength_model()
    building_code = _encode_building(ap_entry["building"])
    features = _build_signal_features(building_code=building_code, floor=ap_entry["floor"], hour=hour, day_of_week=day_of_week, is_weekend=is_weekend, day_of_month=day_of_month, month=month)
    df = pd.DataFrame([features])
    return float(model.predict(df)[0])


class PredictRequestV3(BaseModel):
    model_config = {"extra": "ignore"}
    ap_name: str = Field(default="", description="AP name (e.g. AP-FTI02)")
    hour: float = Field(default=12, description="Hour of day (0-23)")
    day_of_week: float = Field(default=0, description="Day of week (0=Mon, 6=Sun)")
    is_weekend: float = Field(default=0, description="Is weekend (0 or 1)")
    month: float = Field(default=4, description="Month (1-12)")
    day_of_month: float = Field(default=15, description="Day of month")


class RecommendRequest(BaseModel):
    lat: float
    lng: float
    radius: int = Field(default=500, ge=50, le=2000)
    mode: str = Field(default="balanced", pattern="^(distance|signal|balanced)$")
    building: str = Field(default="")
    prefer_stable: bool = Field(default=True)


@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": time.time(), "precomputed_days": len(DAY_NAMES), "precomputed_hours": 24, "model_version": "v3"}


@app.get("/status")
async def server_status():
    models_loaded = {
        "decision_tree_v3": _decision_tree_v3 is not None,
        "building_encoder": _building_encoder is not None,
        "signal_strength_model": _signal_strength_model is not None,
        "geojson": _geojson_data is not None,
        "ap_index": _ap_index is not None,
    }
    return {"status": "ok", "timestamp": time.time(), "model_version": "v3", "models": models_loaded, "cache": {"heatmap_entries": len(_heatmap_cache), "trend_entries": len(_trend_cache)}, "precomputed": {"days": DAY_NAMES, "hours": list(range(24)), "night_representative_hour": NIGHT_REPRESENTATIVE_HOUR}}


@app.post("/predict")
async def predict_ap_status(request: PredictRequestV3):
    """
    v3 模型 - 只使用推理时可获得的特征
    请求只需 ap_name + 时间特征，其余自动从 GeoJSON 和信号模型获取
    """
    try:
        model = _load_decision_tree_v3()
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

    ap_entry = _find_ap_in_index(request.ap_name)
    if ap_entry is None:
        raise HTTPException(status_code=404, detail=f"AP '{request.ap_name}' not found in GeoJSON database.")

    building_code = _encode_building(ap_entry["building"])
    floor = ap_entry["floor"]
    lat = ap_entry["lat"]
    lng = ap_entry["lng"]

    try:
        predicted_signal_db = _predict_signal_for_ap(ap_entry=ap_entry, hour=request.hour, day_of_week=request.day_of_week, is_weekend=request.is_weekend, day_of_month=request.day_of_month, month=request.month)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Signal prediction failed: {str(e)}")

    features = _build_v3_decision_features(hour=request.hour, day_of_week=request.day_of_week, is_weekend=request.is_weekend, day_of_month=request.day_of_month, month=request.month, building_code=building_code, floor=floor, lat=lat, lng=lng, predicted_signal_db=predicted_signal_db)

    prediction = model.predict(features)[0]
    probability = model.predict_proba(features)[0].tolist()
    confidence = max(probability)

    return {
        "prediction": "Up" if prediction == 1 else "Down",
        "confidence": round(confidence, 3),
        "probability": probability,
        "model_version": "v3",
        "ap_info": {"name": request.ap_name, "building": ap_entry["building"], "floor": int(floor), "lat": lat, "lng": lng},
        "features_used": {
            "time": {"hour": request.hour, "day_of_week": request.day_of_week, "is_weekend": request.is_weekend, "month": request.month, "day_of_month": request.day_of_month},
            "ap_static": {"building_code": building_code, "floor": floor, "lat": lat, "lng": lng},
            "cascade": {"predicted_signal_db": round(predicted_signal_db, 1)},
        },
    }


@app.get("/predict/signal_strength/heatmap")
async def get_signal_heatmap(hour: int = Query(default=12, description="Hour of day (0-23)"), day: str = Query(default="mon", description="Day of week (mon/tue/wed/thu/fri/sat/sun)")):
    day_key = _validate_day(day)
    validated_hour = _validate_hour(hour)
    try:
        data = _load_heatmap_file(day_key, validated_hour)
        return JSONResponse(content=data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load heatmap: {str(e)}")


@app.get("/predict/signal_strength/buildings")
async def get_buildings():
    try:
        buildings = _get_buildings_list()
        return {"buildings": buildings, "total": len(buildings)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load buildings: {str(e)}")


@app.get("/predict/signal_strength/ap_trend/{ap_name:path}")
async def get_ap_daily_trend(ap_name: str):
    now = time.time()
    cache_key = ap_name.strip().lower()
    if cache_key in _trend_cache:
        if now - _trend_cache_time.get(cache_key, 0) < TREND_CACHE_TTL:
            return _trend_cache[cache_key]
    try:
        model = _load_signal_strength_model()
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    ap_entry = _find_ap_in_index(ap_name)
    if ap_entry is None:
        raise HTTPException(status_code=404, detail=f"AP '{ap_name}' not found")
    building = ap_entry["building"]
    floor = ap_entry["floor"]
    building_code = _encode_building(building)
    rows = []
    for hour in range(24):
        rows.append(_build_signal_features(building_code=building_code, floor=floor, hour=float(hour), day_of_week=0.0, is_weekend=0.0, day_of_month=15.0, month=4.0))
    df = pd.DataFrame(rows)
    predictions = model.predict(df)
    hourly_data = []
    for hour, signal_db in enumerate(predictions):
        quality_info = _dbm_to_quality(float(signal_db))
        hourly_data.append({"hour": hour, "signal_db": round(float(signal_db), 1), "signal_quality": quality_info["quality"], "bars": quality_info["bars"]})
    signal_values = [h["signal_db"] for h in hourly_data]
    avg_db = sum(signal_values) / len(signal_values) if signal_values else 0
    max_db = max(signal_values) if signal_values else 0
    min_db = min(signal_values) if signal_values else 0
    best_hour = signal_values.index(max_db) if signal_values else 0
    worst_hour = signal_values.index(min_db) if signal_values else 0
    result = {"ap_name": ap_name, "building": building, "floor": int(floor), "lat": ap_entry["lat"], "lng": ap_entry["lng"], "trend": hourly_data, "day_type": "weekday", "stats": {"avg_db": round(avg_db, 1), "max_db": round(max_db, 1), "min_db": round(min_db, 1), "best_hour": best_hour, "worst_hour": worst_hour}}
    _trend_cache[cache_key] = result
    _trend_cache_time[cache_key] = now
    return result


@app.get("/predict/signal_strength/ap_trend/{ap_name:path}/compare")
async def get_ap_trend_compare(ap_name: str):
    try:
        model = _load_signal_strength_model()
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    ap_entry = _find_ap_in_index(ap_name)
    if ap_entry is None:
        raise HTTPException(status_code=404, detail=f"AP '{ap_name}' not found")
    building = ap_entry["building"]
    floor = ap_entry["floor"]
    building_code = _encode_building(building)

    def _predict_for_day(day_of_week: float, is_weekend: float) -> list:
        rows = []
        for hour in range(24):
            rows.append(_build_signal_features(building_code=building_code, floor=floor, hour=float(hour), day_of_week=day_of_week, is_weekend=is_weekend, day_of_month=15.0, month=4.0))
        df = pd.DataFrame(rows)
        predictions = model.predict(df)
        result = []
        for hour, signal_db in enumerate(predictions):
            quality_info = _dbm_to_quality(float(signal_db))
            result.append({"hour": hour, "signal_db": round(float(signal_db), 1), "signal_quality": quality_info["quality"], "bars": quality_info["bars"]})
        return result

    weekday_trend = _predict_for_day(0.0, 0.0)
    weekend_trend = _predict_for_day(5.0, 1.0)
    return {"ap_name": ap_name, "building": building, "weekday": {"label": "Weekday (Mon)", "trend": weekday_trend}, "weekend": {"label": "Weekend (Sat)", "trend": weekend_trend}}


@app.post("/recommend")
async def recommend_aps(request: RecommendRequest):
    try:
        signal_model = _load_signal_strength_model()
        decision_model = _load_decision_tree_v3()
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    current_time = time.localtime()
    current_hour = float(current_time.tm_hour)
    current_day = float(current_time.tm_wday)
    current_day_of_month = float(current_time.tm_mday)
    current_month = float(current_time.tm_mon)
    is_weekend = 1.0 if current_time.tm_wday >= 5 else 0.0
    ap_index = _build_ap_index()
    nearby_aps = []
    for ap in ap_index:
        distance = _approximate_distance(request.lat, request.lng, ap["lat"], ap["lng"])
        if distance > request.radius:
            continue
        if request.building and request.building.lower() not in ap["building"].lower():
            continue
        ap["distance"] = round(distance, 1)
        nearby_aps.append(ap)
    if not nearby_aps:
        return {"recommendations": [], "message": "No APs found in the specified area"}
    signal_rows = []
    for ap in nearby_aps:
        building_code = _encode_building(ap["building"])
        signal_rows.append(_build_signal_features(building_code=building_code, floor=ap["floor"], hour=current_hour, day_of_week=current_day, is_weekend=is_weekend, day_of_month=current_day_of_month, month=current_month))
    signal_df = pd.DataFrame(signal_rows)
    signal_predictions = signal_model.predict(signal_df)
    decision_rows = []
    for i, ap in enumerate(nearby_aps):
        building_code = _encode_building(ap["building"])
        decision_rows.append(_build_v3_decision_features(hour=current_hour, day_of_week=current_day, is_weekend=is_weekend, day_of_month=current_day_of_month, month=current_month, building_code=building_code, floor=ap["floor"], lat=ap["lat"], lng=ap["lng"], predicted_signal_db=float(signal_predictions[i]))[0])
    status_predictions = decision_model.predict(decision_rows)
    status_probabilities = decision_model.predict_proba(decision_rows)
    results = []
    for i, ap in enumerate(nearby_aps):
        signal_db = float(signal_predictions[i])
        quality_info = _dbm_to_quality(signal_db)
        status_pred = int(status_predictions[i])
        status_prob = status_probabilities[i].tolist()
        signal_score = max(0, (signal_db + 100) / 50)
        distance_score = max(0, 1 - ap["distance"] / request.radius)
        if request.mode == "distance":
            score = distance_score * 0.8 + signal_score * 0.2
        elif request.mode == "signal":
            score = signal_score * 0.8 + distance_score * 0.2
        else:
            score = signal_score * 0.5 + distance_score * 0.5
        results.append({"id": ap["id"], "name": ap["name"], "lat": ap["lat"], "lng": ap["lng"], "building": ap["building"], "floor": int(ap["floor"]), "distance": ap["distance"], "signal_db": round(signal_db, 1), "signal_quality": quality_info["quality"], "bars": quality_info["bars"], "prediction": "Up" if status_pred == 1 else "Down", "confidence": round(max(status_prob), 3), "up_probability": round(status_prob[1] if len(status_prob) > 1 else status_prob[0], 3), "score": round(score, 3)})
    results.sort(key=lambda x: x["score"], reverse=True)
    return {"recommendations": results[:20], "total_found": len(results), "mode": request.mode, "radius": request.radius, "model_version": "v3"}


@app.get("/route/{lat}/{lng}/{dest_lat}/{dest_lng}")
async def get_route(lat: float, lng: float, dest_lat: float, dest_lng: float):
    num_points = 20
    path = []
    for i in range(num_points + 1):
        t = i / num_points
        path.append({"lat": round(lat + (dest_lat - lat) * t, 6), "lng": round(lng + (dest_lng - lng) * t, 6)})
    return {"path": path}


@app.get("/route/advanced/{lat}/{lng}/{dest_lat}/{dest_lng}")
async def get_advanced_route(lat: float, lng: float, dest_lat: float, dest_lng: float, acceptable_range: int = Query(default=500, ge=100, le=5000, alias="acceptable_range")):
    try:
        _load_geojson()
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    ap_index = _build_ap_index()
    path_aps = []
    for ap in ap_index:
        dist_to_start = _approximate_distance(lat, lng, ap["lat"], ap["lng"])
        dist_to_dest = _approximate_distance(dest_lat, dest_lng, ap["lat"], ap["lng"])
        if dist_to_start <= acceptable_range or dist_to_dest <= acceptable_range:
            path_aps.append({"lat": ap["lat"], "lng": ap["lng"], "building": ap["building"], "floor": int(ap["floor"]), "ap_name": ap["name"], "distance_to_start": round(dist_to_start, 1), "distance_to_dest": round(dist_to_dest, 1)})
    return {"path": [{"lat": round(lat, 6), "lng": round(lng, 6)}] + [{"lat": round(ap["lat"], 6), "lng": round(ap["lng"], 6)} for ap in path_aps] + [{"lat": round(dest_lat, 6), "lng": round(dest_lng, 6)}], "waypoints": path_aps, "total_waypoints": len(path_aps)}


@app.get("/cache/status")
async def cache_status():
    return {"heatmap_cache": {"entries": len(_heatmap_cache), "keys": list(_heatmap_cache.keys()), "ttl_seconds": HEATMAP_CACHE_TTL}, "trend_cache": {"entries": len(_trend_cache), "keys": list(_trend_cache.keys()), "ttl_seconds": TREND_CACHE_TTL}, "models_loaded": {"decision_tree_v3": _decision_tree_v3 is not None, "building_encoder": _building_encoder is not None, "signal_strength_model": _signal_strength_model is not None}, "ap_index_size": len(_ap_index) if _ap_index else 0, "buildings_count": len(_buildings_list) if _buildings_list else 0}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False, log_level="info")
