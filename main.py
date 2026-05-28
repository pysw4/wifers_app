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
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import joblib
from foto2ap_service import recognize_ap
import numpy as np
import pandas as pd
import uvicorn
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator


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
_ap_name_encoder: Any = None
_signal_strength_model: Any = None
_signal_strength_meta: Any = None
_geojson_data: Optional[dict] = None
_ap_index: Optional[list[dict]] = None
_buildings_list: Optional[list[str]] = None
_heatmap_cache: dict[str, dict] = {}
_heatmap_cache_time: dict[str, float] = {}
_trend_cache: dict[str, dict] = {}
_trend_cache_time: dict[str, float] = {}

# --- Booking system (in-memory storage) ---
_bookings: list[dict] = []
_room_lookup: dict[str, dict] = {}
PERF_RANK = {'Very Poor': 0, 'Weak': 1, 'Fair': 2, 'Good': 3,
             'Excellent': 4, 'Excellent+': 5, 'Excellent++': 6}

# --- Prediction feedback / accuracy tracking ---
_prediction_feedback: list[dict] = []  # Stores {ap_name, hour, predicted, actual, timestamp}

# --- Actual signal data from clientes_processed.csv for accuracy comparison ---
_actual_signal_data: dict[str, dict] = {}  # {ap_name_lower: {hourly: {hour: {actual_mean, samples}}, total_measurements}}
_actual_signal_loaded: bool = False

def _load_actual_signal_data():
    """Load precomputed actual signal averages from JSON (not CSV)."""
    global _actual_signal_data, _actual_signal_loaded
    if _actual_signal_loaded:
        return _actual_signal_data
    
    json_path = BASE_DIR / "precomputed" / "actual_signal_averages.json"
    if not json_path.exists():
        print(f"[WARN] Precomputed actual signal averages not found: {json_path}")
        _actual_signal_loaded = True
        return _actual_signal_data
    
    try:
        print(f"[INFO] Loading precomputed actual signal averages from {json_path}...")
        with open(json_path) as f:
            raw = json.load(f)
        
        # Convert string hour keys back to int for consistency
        for ap_key, ap_data in raw.items():
            hourly = ap_data.get("hourly", {})
            converted_hourly = {}
            for h_str, h_data in hourly.items():
                converted_hourly[int(h_str)] = h_data
            _actual_signal_data[ap_key] = {
                "hourly": converted_hourly,
                "total_measurements": ap_data["total_measurements"],
            }
        
        print(f"[INFO] Loaded actual signal averages for {len(_actual_signal_data)} APs")
        _actual_signal_loaded = True
    except Exception as e:
        print(f"[ERROR] Failed to load actual signal averages: {e}")
    
    return _actual_signal_data




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


def _load_ap_name_encoder():
    global _ap_name_encoder
    if _ap_name_encoder is None:
        path = MODELS_DIR / "ap_name_encoder.joblib"
        if path.exists():
            _ap_name_encoder = joblib.load(path)
    return _ap_name_encoder


def _encode_ap_name(ap_name: str) -> int:
    """Encode AP name using the label encoder. Returns 0 if not found."""
    encoder = _load_ap_name_encoder()
    if encoder is None:
        return 0
    # Try exact match first, then stripped
    clean_name = ap_name.strip()
    if clean_name in encoder.classes_:
        return int(encoder.transform([clean_name])[0])
    # Try with leading space (some encoder classes have leading spaces)
    if f" {clean_name}" in encoder.classes_:
        return int(encoder.transform([f" {clean_name}"])[0])
    # Try case-insensitive
    for cls in encoder.classes_:
        if cls.strip().lower() == clean_name.lower():
            return int(encoder.transform([cls])[0])
    return 0


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


def _dbm_to_status(dbm: float) -> str:
    """Convert signal dBm to predicted Up/Down status.
    Signal >= -75 dBm → likely Up (usable connection)
    Signal < -75 dBm → likely Down (too weak for reliable use)
    """
    return "Up" if dbm >= -75 else "Down"


def _dbm_to_status_confidence(dbm: float) -> float:
    """Confidence of the status prediction based on how far from threshold."""
    # -75 dBm threshold, confidence scales with distance from threshold
    diff = dbm - (-75)
    # Clamp confidence between 0.5 and 0.99
    confidence = min(0.99, max(0.5, 0.5 + abs(diff) / 50))
    return round(confidence, 3)


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


def _build_signal_features(building_code: int, floor: float, hour: float, day_of_week: float, is_weekend: float, day_of_month: float, month: float, ap_name_code: int = 0) -> dict:
    return {"building_code": building_code, "floor": floor, "hour": hour, "band": 5.0, "day_of_week": day_of_week, "is_weekend": is_weekend, "day_of_month": day_of_month, "month": month, "ap_name_code": ap_name_code}


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
    ap_name_code = _encode_ap_name(ap_entry["name"])
    features = _build_signal_features(building_code=building_code, floor=ap_entry["floor"], hour=hour, day_of_week=day_of_week, is_weekend=is_weekend, day_of_month=day_of_month, month=month, ap_name_code=ap_name_code)
    df = pd.DataFrame([features])
    return float(model.predict(df)[0])


# --- Booking helper functions ---

def _build_room_lookup():
    """Build a lookup dict mapping room codes to AP info from GeoJSON."""
    global _room_lookup
    if _room_lookup:
        return _room_lookup
    geojson = _load_geojson()
    for feature in geojson["features"]:
        props = feature["properties"]
        room_code = str(props.get("USER_Espai", "")).strip().upper()
        if room_code:
            _room_lookup[room_code] = {
                "ap_name": str(props.get("USER_NOM_A", "")).strip().upper(),
                "building": props.get("USER_EDIFI", ""),
                "floor": props.get("Num_Planta", 0),
            }
    return _room_lookup


def _get_ap_from_room(room_code: str) -> Optional[dict]:
    lookup = _build_room_lookup()
    return lookup.get(room_code.strip().upper())


def _check_booking_availability(bookings: list, room_code: str, date_str: str, start_hour: int, end_hour: int) -> tuple[bool, Optional[dict]]:
    room_code_upper = room_code.strip().upper()
    for book in bookings:
        if book["room_code"] != room_code_upper or book["date"] != date_str:
            continue
        if not (end_hour <= book["start_hour"] or start_hour >= book["end_hour"]):
            return False, book
    return True, None


def _predict_booking_performance(room_code: str, date_str: str, start_hour: int, end_hour: int, n_students: int) -> dict:
    """Predict performance for a booking slot. Returns dict with performance/warning."""
    booking_dt = datetime.strptime(f"{date_str} {start_hour:02d}:00", "%Y-%m-%d %H:%M")
    hours_until = (booking_dt - datetime.now()).total_seconds() / 3600

    ap_info = _get_ap_from_room(room_code)
    if ap_info is None:
        return {"ap_name": "Unknown", "performance": None, "warning": "Room not found"}

    ap_name = ap_info["ap_name"]
    ap_entry = _find_ap_in_index(ap_name)

    if hours_until < 0:
        return {
            "ap_name": ap_name,
            "performance": None,
            "warning": "Cannot predict for a past time slot"
        }

    if hours_until > 5:
        return {
            "ap_name": ap_name,
            "performance": None,
            "warning": f"Prediction not available — booking is {hours_until:.0f}h away (max 5h)"
        }

    if ap_entry is None:
        return {"ap_name": ap_name, "performance": None, "warning": "AP not found in database"}

    try:
        signal_model = _load_signal_strength_model()
    except FileNotFoundError:
        return {"ap_name": ap_name, "performance": None, "warning": "Signal model not loaded"}

    booking_date = datetime.strptime(date_str, "%Y-%m-%d")
    day_of_week = float(booking_date.weekday())
    is_weekend = 1.0 if day_of_week >= 5 else 0.0
    day_of_month = float(booking_date.day)
    month = float(booking_date.month)

    building_code = _encode_building(ap_entry["building"])
    ap_name_code = _encode_ap_name(ap_entry["name"])
    hours = list(range(start_hour, end_hour))

    predictions = []
    for h in hours:
        features = _build_signal_features(
            building_code=building_code, floor=ap_entry["floor"],
            hour=float(h), day_of_week=day_of_week,
            is_weekend=is_weekend, day_of_month=day_of_month, month=month,
            ap_name_code=ap_name_code
        )
        df = pd.DataFrame([features])
        signal_db = float(signal_model.predict(df)[0])
        quality = _dbm_to_quality(signal_db)["quality"]
        predictions.append((h, quality))

    if not predictions:
        return {"ap_name": ap_name, "performance": None, "warning": "No predictions available"}

    worst = min(predictions, key=lambda x: PERF_RANK.get(x[1], 0))
    return {
        "ap_name": ap_name,
        "performance": worst[1],
        "predictions": predictions,
        "warning": None
    }


def _suggest_best_slot(room_code: str, date_str: str, duration_hours: int, n_students: int) -> Optional[dict]:
    """Find the best available time slot for a given room and duration."""
    results = []
    for start in range(7, 23 - duration_hours):
        end = start + duration_hours
        available, _ = _check_booking_availability(_bookings, room_code, date_str, start, end)
        if not available:
            continue
        pred = _predict_booking_performance(room_code, date_str, start, end, n_students)
        if pred is None or pred["warning"]:
            continue
        results.append((start, end, pred["performance"]))

    if not results:
        return None
    best = max(results, key=lambda x: PERF_RANK.get(x[2], 0))
    return {"start_hour": best[0], "end_hour": best[1], "performance": best[2]}


def _suggest_alternative_rooms(room_code: str, date_str: str, start_hour: int, end_hour: int, n_students: int, min_perf: str) -> list[dict]:
    """Find alternative rooms on the same building/floor with better performance."""
    current = _get_ap_from_room(room_code)
    if current is None:
        return []

    lookup = _build_room_lookup()
    candidates = []
    visited_aps = set()

    for code, info in lookup.items():
        if (info["building"] == current["building"]
                and info["floor"] == current["floor"]
                and code != room_code.strip().upper()):
            ap_name = info["ap_name"]
            if ap_name in visited_aps:
                continue
            available, _ = _check_booking_availability(_bookings, code, date_str, start_hour, end_hour)
            if not available:
                continue
            pred = _predict_booking_performance(code, date_str, start_hour, end_hour, n_students)
            if pred is None or pred["warning"]:
                continue
            if pred["performance"] and PERF_RANK.get(pred["performance"], 0) >= PERF_RANK.get(min_perf, 0):
                candidates.append({"room_code": code, "performance": pred["performance"]})
                visited_aps.add(ap_name)

    return sorted(candidates, key=lambda x: PERF_RANK.get(x["performance"], 0), reverse=True)


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

    @field_validator('lat')
    @classmethod
    def validate_lat(cls, v):
        if v < -90 or v > 90:
            raise ValueError('Latitude must be between -90 and 90')
        return v

    @field_validator('lng')
    @classmethod
    def validate_lng(cls, v):
        if v < -180 or v > 180:
            raise ValueError('Longitude must be between -180 and 180')
        return v

    @field_validator('building')
    @classmethod
    def validate_building(cls, v):
        if len(v) > 100:
            raise ValueError('Building name too long (max 100 characters)')
        return v


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    errors = []
    for error in exc.errors():
        errors.append({
            "field": " -> ".join(str(loc) for loc in error["loc"]),
            "message": error["msg"],
            "type": error["type"],
        })
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Input validation failed",
            "errors": errors,
            "model_version": "v3"
        }
    )


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
        status = _dbm_to_status(float(signal_db))
        status_conf = _dbm_to_status_confidence(float(signal_db))
        hourly_data.append({
            "hour": hour,
            "signal_db": round(float(signal_db), 1),
            "signal_quality": quality_info["quality"],
            "bars": quality_info["bars"],
            "predicted_status": status,
            "status_confidence": status_conf,
        })
    signal_values = [h["signal_db"] for h in hourly_data]
    avg_db = sum(signal_values) / len(signal_values) if signal_values else 0
    max_db = max(signal_values) if signal_values else 0
    min_db = min(signal_values) if signal_values else 0
    best_hour = signal_values.index(max_db) if signal_values else 0
    worst_hour = signal_values.index(min_db) if signal_values else 0

    # Calculate accuracy from feedback data if available
    ap_feedback = [f for f in _prediction_feedback if f["ap_name"].strip().lower() == cache_key]
    accuracy_stats = {}
    if ap_feedback:
        correct = sum(1 for f in ap_feedback if f["predicted"] == f["actual"])
        total = len(ap_feedback)
        accuracy_stats = {
            "total_feedback": total,
            "correct": correct,
            "accuracy": round(correct / total, 3) if total > 0 else 0,
            "up_accuracy": 0,
            "down_accuracy": 0,
        }
        up_feedback = [f for f in ap_feedback if f["actual"] == "Up"]
        down_feedback = [f for f in ap_feedback if f["actual"] == "Down"]
        if up_feedback:
            accuracy_stats["up_accuracy"] = round(
                sum(1 for f in up_feedback if f["predicted"] == "Up") / len(up_feedback), 3
            )
        if down_feedback:
            accuracy_stats["down_accuracy"] = round(
                sum(1 for f in down_feedback if f["predicted"] == "Down") / len(down_feedback), 3
            )

    # Calculate accuracy vs actual measurements from clientes_processed.csv
    actual_data = _load_actual_signal_data().get(cache_key, {})
    accuracy_vs_actual = None
    if actual_data and actual_data.get("hourly"):
        hourly_actual = actual_data["hourly"]
        
        # --- Interpolate missing hours to get a full 24-hour curve ---
        # Build a complete 0..23 array, filling gaps with linear interpolation
        full_actual = {}
        actual_hours = sorted(hourly_actual.keys())
        
        if len(actual_hours) >= 2:
            # Interpolate between known points
            for h in range(24):
                if h in hourly_actual:
                    full_actual[h] = {
                        "actual_mean": hourly_actual[h]["actual_mean"],
                        "samples": hourly_actual[h]["samples"],
                        "interpolated": False,
                    }
                else:
                    # Find nearest known hours before and after
                    before = [ah for ah in actual_hours if ah < h]
                    after = [ah for ah in actual_hours if ah > h]
                    
                    if before and after:
                        h_before = before[-1]
                        h_after = after[0]
                        v_before = hourly_actual[h_before]["actual_mean"]
                        v_after = hourly_actual[h_after]["actual_mean"]
                        # Linear interpolation
                        ratio = (h - h_before) / (h_after - h_before)
                        interpolated = v_before + (v_after - v_before) * ratio
                        full_actual[h] = {
                            "actual_mean": round(interpolated, 1),
                            "samples": 0,
                            "interpolated": True,
                        }
                    elif before and not after:
                        # Extrapolate from last known value (flat)
                        full_actual[h] = {
                            "actual_mean": hourly_actual[before[-1]]["actual_mean"],
                            "samples": 0,
                            "interpolated": True,
                        }
                    elif after and not before:
                        # Extrapolate from first known value (flat)
                        full_actual[h] = {
                            "actual_mean": hourly_actual[after[0]]["actual_mean"],
                            "samples": 0,
                            "interpolated": True,
                        }
        elif len(actual_hours) == 1:
            # Only one hour known — use it for all hours
            single_h = actual_hours[0]
            single_v = hourly_actual[single_h]["actual_mean"]
            for h in range(24):
                full_actual[h] = {
                    "actual_mean": single_v,
                    "samples": hourly_actual[single_h]["samples"] if h == single_h else 0,
                    "interpolated": h != single_h,
                }
        else:
            full_actual = {h: v for h, v in hourly_actual.items()}
        
        # Now build comparison using the full 24-hour actual data
        diffs = []
        actual_hourly_list = []
        for h_data in hourly_data:
            h = h_data["hour"]
            if h in full_actual:
                pred_db = h_data["signal_db"]
                actual_db = full_actual[h]["actual_mean"]
                diff = abs(pred_db - actual_db)
                diffs.append(diff)
                actual_hourly_list.append({
                    "hour": h,
                    "actual_mean": actual_db,
                    "samples": full_actual[h].get("samples", 0),
                    "predicted_db": pred_db,
                    "diff": round(diff, 1),
                    "interpolated": full_actual[h].get("interpolated", False),
                })
        
        if diffs:
            mae = sum(diffs) / len(diffs)
            within_5db = sum(1 for d in diffs if d <= 5)
            within_10db = sum(1 for d in diffs if d <= 10)
            signal_accuracy = within_5db / len(diffs)
            
            # Also compute status accuracy (Up/Down based on -75 threshold)
            status_correct = 0
            status_total = 0
            for h_data in hourly_data:
                h = h_data["hour"]
                if h in full_actual:
                    pred_status = _dbm_to_status(h_data["signal_db"])
                    actual_status = _dbm_to_status(full_actual[h]["actual_mean"])
                    if pred_status == actual_status:
                        status_correct += 1
                    status_total += 1
            
            accuracy_vs_actual = {
                "mae": round(mae, 1),
                "signal_accuracy": round(signal_accuracy, 3),
                "within_5db": within_5db,
                "within_10db": within_10db,
                "compared_hours": len(diffs),
                "total_measurements": actual_data["total_measurements"],
                "status_accuracy": round(status_correct / status_total, 3) if status_total > 0 else None,
                "hourly": actual_hourly_list,
            }

    result = {
        "ap_name": ap_name,
        "building": building,
        "floor": int(floor),
        "lat": ap_entry["lat"],
        "lng": ap_entry["lng"],
        "trend": hourly_data,
        "day_type": "weekday",
        "stats": {
            "avg_db": round(avg_db, 1),
            "max_db": round(max_db, 1),
            "min_db": round(min_db, 1),
            "best_hour": best_hour,
            "worst_hour": worst_hour,
        },
        "accuracy": accuracy_stats,
        "accuracy_vs_actual": accuracy_vs_actual,
    }
    _trend_cache[cache_key] = result
    _trend_cache_time[cache_key] = now
    return result



class PredictFeedbackRequest(BaseModel):
    ap_name: str = Field(..., description="AP name")
    hour: int = Field(..., ge=0, le=23, description="Hour of prediction")
    predicted: str = Field(..., pattern="^(Up|Down)$", description="What the model predicted")
    actual: str = Field(..., pattern="^(Up|Down)$", description="What actually happened")


@app.post("/predict/feedback")
async def submit_prediction_feedback(request: PredictFeedbackRequest):
    """Submit user feedback on prediction accuracy."""
    feedback = {
        "ap_name": request.ap_name.strip(),
        "hour": request.hour,
        "predicted": request.predicted,
        "actual": request.actual,
        "timestamp": time.time(),
    }
    _prediction_feedback.append(feedback)
    # Keep only last 1000 entries per AP to manage memory
    ap_key = request.ap_name.strip().lower()
    ap_entries = [f for f in _prediction_feedback if f["ap_name"].strip().lower() == ap_key]
    if len(ap_entries) > 1000:
        excess = len(ap_entries) - 1000
        _prediction_feedback[:] = [
            f for f in _prediction_feedback
            if f["ap_name"].strip().lower() != ap_key or f not in ap_entries[:excess]
        ]
    return {
        "success": True,
        "feedback": feedback,
    }


@app.get("/predict/stats/{ap_name:path}")
async def get_prediction_stats(ap_name: str):
    """Get prediction accuracy statistics for a specific AP."""
    cache_key = ap_name.strip().lower()
    ap_feedback = [f for f in _prediction_feedback if f["ap_name"].strip().lower() == cache_key]
    if not ap_feedback:
        return {
            "ap_name": ap_name,
            "total_feedback": 0,
            "accuracy": None,
            "message": "No feedback data available for this AP yet."
        }
    correct = sum(1 for f in ap_feedback if f["predicted"] == f["actual"])
    total = len(ap_feedback)
    up_feedback = [f for f in ap_feedback if f["actual"] == "Up"]
    down_feedback = [f for f in ap_feedback if f["actual"] == "Down"]
    up_correct = sum(1 for f in up_feedback if f["predicted"] == "Up")
    down_correct = sum(1 for f in down_feedback if f["predicted"] == "Down")
    return {
        "ap_name": ap_name,
        "total_feedback": total,
        "correct": correct,
        "accuracy": round(correct / total, 3),
        "up_accuracy": round(up_correct / len(up_feedback), 3) if up_feedback else None,
        "down_accuracy": round(down_correct / len(down_feedback), 3) if down_feedback else None,
        "up_samples": len(up_feedback),
        "down_samples": len(down_feedback),
        "recent_feedback": sorted(ap_feedback, key=lambda x: x["timestamp"], reverse=True)[:10],
    }


@app.get("/predict/signal_strength/accuracy/{ap_name:path}")
async def get_ap_signal_accuracy(ap_name: str):
    """Get detailed prediction vs actual signal accuracy for a specific AP."""
    cache_key = ap_name.strip().lower()
    
    # Load actual data
    actual_data = _load_actual_signal_data().get(cache_key, {})
    if not actual_data or not actual_data.get("hourly"):
        return {
            "ap_name": ap_name,
            "has_data": False,
            "message": "No actual measurement data available for this AP.",
        }
    
    # Get predicted trend
    try:
        model = _load_signal_strength_model()
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    
    ap_entry = _find_ap_in_index(ap_name)
    if ap_entry is None:
        return {
            "ap_name": ap_name,
            "has_data": False,
            "message": "AP not found in GeoJSON database.",
        }
    
    building_code = _encode_building(ap_entry["building"])
    rows = []
    for hour in range(24):
        rows.append(_build_signal_features(
            building_code=building_code, floor=ap_entry["floor"],
            hour=float(hour), day_of_week=0.0, is_weekend=0.0,
            day_of_month=15.0, month=4.0
        ))
    df = pd.DataFrame(rows)
    predictions = model.predict(df)
    
    hourly_actual = actual_data["hourly"]
    comparison = []
    diffs = []
    status_correct = 0
    status_total = 0
    
    for hour in range(24):
        pred_db = round(float(predictions[hour]), 1)
        pred_status = _dbm_to_status(pred_db)
        pred_quality = _dbm_to_quality(pred_db)["quality"]
        
        entry = {
            "hour": hour,
            "predicted_db": pred_db,
            "predicted_status": pred_status,
            "predicted_quality": pred_quality,
        }
        
        if hour in hourly_actual:
            actual_db = hourly_actual[hour]["actual_mean"]
            actual_status = _dbm_to_status(actual_db)
            actual_quality = _dbm_to_quality(actual_db)["quality"]
            diff = abs(pred_db - actual_db)
            diffs.append(diff)
            
            if pred_status == actual_status:
                status_correct += 1
            status_total += 1
            
            entry["actual_db"] = actual_db
            entry["actual_status"] = actual_status
            entry["actual_quality"] = actual_quality
            entry["actual_samples"] = hourly_actual[hour]["samples"]
            entry["diff"] = round(diff, 1)
        else:
            entry["actual_db"] = None
            entry["diff"] = None
        
        comparison.append(entry)
    
    # Calculate metrics
    mae = sum(diffs) / len(diffs) if diffs else None
    within_5db = sum(1 for d in diffs if d <= 5) if diffs else 0
    within_10db = sum(1 for d in diffs if d <= 10) if diffs else 0
    signal_accuracy = within_5db / len(diffs) if diffs else None
    status_accuracy = status_correct / status_total if status_total > 0 else None
    
    return {
        "ap_name": ap_name,
        "building": ap_entry["building"],
        "floor": int(ap_entry["floor"]),
        "has_data": True,
        "total_measurements": actual_data["total_measurements"],
        "compared_hours": len(diffs),
        "metrics": {
            "mae": round(mae, 1) if mae else None,
            "signal_accuracy": round(signal_accuracy, 3) if signal_accuracy else None,
            "within_5db": within_5db,
            "within_10db": within_10db,
            "status_accuracy": round(status_accuracy, 3) if status_accuracy else None,
        },
        "hourly_comparison": comparison,
    }


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
        ap_name_code = _encode_ap_name(ap["name"])
        signal_rows.append(_build_signal_features(building_code=building_code, floor=ap["floor"], hour=current_hour, day_of_week=current_day, is_weekend=is_weekend, day_of_month=current_day_of_month, month=current_month, ap_name_code=ap_name_code))
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


@app.post("/foto2ap/recognize")
async def foto2ap_recognize(file: UploadFile = File(...)):
    """
    Upload a photo of an AP access point and recognise its name + location.

    Uses PaddleOCR to extract text from the image, parses the AP code,
    and looks up its coordinates in the GeoJSON database.

    Returns:
        {
            "success": true,
            "ap_name": "AP-ETSE58",
            "lat": 41.5004,
            "lng": 2.1129,
            "building": "ETSE",
            "floor": 0,
            "espacio": "..."
        }
    """
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    try:
        image_bytes = await file.read()
        if len(image_bytes) == 0:
            raise HTTPException(status_code=400, detail="Empty file")
    except Exception:
        raise HTTPException(status_code=400, detail="Failed to read uploaded file")

    try:
        result = recognize_ap(image_bytes)
    except ImportError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OCR recognition failed: {str(e)}")

    if result is None:
        return JSONResponse(
            status_code=404,
            content={"success": False, "message": "No AP could be recognised in the image. Try a clearer photo of the AP label."}
        )

    return {"success": True, **result}


# --- Booking API endpoints ---


class BookingCreateRequest(BaseModel):
    teacher_id: Optional[str] = Field(default=None, max_length=100)
    room_code: Optional[str] = Field(default=None, max_length=50)
    date: str = Field(description="Date in YYYY-MM-DD format")
    start_hour: int = Field(ge=7, le=22)
    end_hour: int = Field(ge=8, le=23)
    n_students: int = Field(ge=1, le=200)
    min_performance: str = Field(default="Fair", pattern="^(Fair|Good|Excellent)$")


class BookingCancelRequest(BaseModel):
    booking_id: str = Field(min_length=1)


class BookingPredictRequest(BaseModel):
    room_code: Optional[str] = Field(default=None, max_length=50)
    date: str = Field(description="Date in YYYY-MM-DD format")
    start_hour: int = Field(ge=7, le=22)
    end_hour: int = Field(ge=8, le=23)
    n_students: int = Field(ge=1, le=200)


class BookingSuggestSlotRequest(BaseModel):
    room_code: Optional[str] = Field(default=None, max_length=50)
    date: str = Field(description="Date in YYYY-MM-DD format")
    duration_hours: int = Field(ge=1, le=6)
    n_students: int = Field(ge=1, le=200)


class BookingAlternativesRequest(BaseModel):
    room_code: Optional[str] = Field(default=None, max_length=50)
    date: str = Field(description="Date in YYYY-MM-DD format")
    start_hour: int = Field(ge=7, le=22)
    end_hour: int = Field(ge=8, le=23)
    n_students: int = Field(ge=1, le=200)
    min_performance: str = Field(default="Fair", pattern="^(Fair|Good|Excellent)$")


@app.post("/booking/create")
async def booking_create(request: BookingCreateRequest):
    """Create a new booking after checking availability and predicting performance."""
    if request.end_hour <= request.start_hour:
        raise HTTPException(status_code=400, detail="End time must be after start time")

    if not request.room_code:
        return {"success": False, "message": "Room code is required", "booking": None}

    ap_info = _get_ap_from_room(request.room_code)
    if ap_info is None:
        raise HTTPException(status_code=404, detail=f"Room '{request.room_code}' not found")

    available, conflict = _check_booking_availability(
        _bookings, request.room_code, request.date,
        request.start_hour, request.end_hour
    )
    if not available:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Room already booked for this time slot",
                "conflict": {
                    "start_hour": conflict["start_hour"],
                    "end_hour": conflict["end_hour"],
                    "booking_id": conflict["booking_id"],
                }
            }
        )

    pred = _predict_booking_performance(
        request.room_code, request.date,
        request.start_hour, request.end_hour, request.n_students
    )

    booking = {
        "booking_id": str(uuid.uuid4())[:8].upper(),
        "teacher_id": request.teacher_id,
        "room_code": request.room_code.strip().upper(),
        "ap_name": ap_info["ap_name"],
        "date": request.date,
        "start_hour": request.start_hour,
        "end_hour": request.end_hour,
        "n_students": request.n_students,
        "min_performance": request.min_performance,
        "predicted_performance": pred.get("performance"),
        "warning": pred.get("warning"),
    }

    _bookings.append(booking)

    return {
        "success": True,
        "booking": booking,
        "prediction": {
            "performance": pred.get("performance"),
            "warning": pred.get("warning"),
        }
    }


@app.post("/booking/predict")
async def booking_predict(request: BookingPredictRequest):
    """Predict performance for a room/time slot without creating a booking."""
    if request.end_hour <= request.start_hour:
        raise HTTPException(status_code=400, detail="End time must be after start time")

    if not request.room_code:
        return {"available": False, "prediction": {"performance": None, "warning": "Room code is required"}}

    ap_info = _get_ap_from_room(request.room_code)
    if ap_info is None:
        raise HTTPException(status_code=404, detail=f"Room '{request.room_code}' not found")

    available, conflict = _check_booking_availability(
        _bookings, request.room_code, request.date,
        request.start_hour, request.end_hour
    )

    pred = _predict_booking_performance(
        request.room_code, request.date,
        request.start_hour, request.end_hour, request.n_students
    )

    return {
        "room_code": request.room_code.strip().upper(),
        "ap_name": ap_info["ap_name"],
        "date": request.date,
        "start_hour": request.start_hour,
        "end_hour": request.end_hour,
        "n_students": request.n_students,
        "available": available,
        "conflict": {
            "start_hour": conflict["start_hour"] if conflict else None,
            "end_hour": conflict["end_hour"] if conflict else None,
            "booking_id": conflict["booking_id"] if conflict else None,
        } if conflict else None,
        "prediction": {
            "performance": pred.get("performance"),
            "warning": pred.get("warning"),
        }
    }


@app.post("/booking/cancel")
async def booking_cancel(request: BookingCancelRequest):
    """Cancel an existing booking by its ID."""
    for i, book in enumerate(_bookings):
        if book["booking_id"] == request.booking_id:
            _bookings.pop(i)
            return {"success": True, "message": "Booking cancelled", "booking_id": request.booking_id}
    raise HTTPException(status_code=404, detail=f"Booking '{request.booking_id}' not found")


@app.get("/booking/list")
async def booking_list(teacher_id: Optional[str] = Query(default=None, description="Filter by teacher ID"),
                       room_code: Optional[str] = Query(default=None, description="Filter by room code"),
                       date: Optional[str] = Query(default=None, description="Filter by date (YYYY-MM-DD)")):
    """List bookings with optional filters."""
    results = _bookings
    if teacher_id:
        results = [b for b in results if b["teacher_id"] == teacher_id]
    if room_code:
        results = [b for b in results if b["room_code"] == room_code.strip().upper()]
    if date:
        results = [b for b in results if b["date"] == date]
    return {"bookings": results, "total": len(results)}


@app.post("/booking/suggest-slot")
async def booking_suggest_slot(request: BookingSuggestSlotRequest):
    """Suggest the best available time slot for a room and duration."""
    if not request.room_code:
        return {"found": False, "message": "Room code is required"}

    ap_info = _get_ap_from_room(request.room_code)
    if ap_info is None:
        raise HTTPException(status_code=404, detail=f"Room '{request.room_code}' not found")

    best = _suggest_best_slot(
        request.room_code, request.date,
        request.duration_hours, request.n_students
    )

    if best is None:
        return {
            "found": False,
            "message": "No available slots with prediction for this room and date"
        }

    return {"found": True, "slot": best}


@app.post("/booking/alternatives")
async def booking_alternatives(request: BookingAlternativesRequest):
    """Find alternative rooms on the same floor with better performance."""
    if request.end_hour <= request.start_hour:
        raise HTTPException(status_code=400, detail="End time must be after start time")

    if not request.room_code:
        return {"room_code": None, "alternatives": [], "total": 0}

    ap_info = _get_ap_from_room(request.room_code)
    if ap_info is None:
        raise HTTPException(status_code=404, detail=f"Room '{request.room_code}' not found")

    alternatives = _suggest_alternative_rooms(
        request.room_code, request.date,
        request.start_hour, request.end_hour,
        request.n_students, request.min_performance
    )

    return {
        "room_code": request.room_code.strip().upper(),
        "alternatives": alternatives,
        "total": len(alternatives)
    }


@app.get("/booking/room-info/{room_code:path}")
async def booking_room_info(room_code: str):
    """Get AP info for a room code."""
    ap_info = _get_ap_from_room(room_code)
    if ap_info is None:
        raise HTTPException(status_code=404, detail=f"Room '{room_code}' not found")
    return {
        "room_code": room_code.strip().upper(),
        "ap_name": ap_info["ap_name"],
        "building": ap_info["building"],
        "floor": ap_info["floor"],
    }


@app.get("/booking/availability/{room_code:path}/{date}")
async def booking_availability(room_code: str, date: str):
    """Get hourly availability for a room on a given date."""
    ap_info = _get_ap_from_room(room_code)
    if ap_info is None:
        raise HTTPException(status_code=404, detail=f"Room '{room_code}' not found")

    room_code_upper = room_code.strip().upper()
    booked_ranges = [
        (b["start_hour"], b["end_hour"])
        for b in _bookings
        if b["room_code"] == room_code_upper and b["date"] == date
    ]

    def is_booked(h):
        return any(s <= h < e for s, e in booked_ranges)

    hours = []
    for h in range(7, 22):
        hours.append({
            "hour": h,
            "available": not is_booked(h),
        })

    return {
        "room_code": room_code_upper,
        "ap_name": ap_info["ap_name"],
        "date": date,
        "hours": hours,
    }


@app.get("/cache/status")

async def cache_status():
    return {"heatmap_cache": {"entries": len(_heatmap_cache), "keys": list(_heatmap_cache.keys()), "ttl_seconds": HEATMAP_CACHE_TTL}, "trend_cache": {"entries": len(_trend_cache), "keys": list(_trend_cache.keys()), "ttl_seconds": TREND_CACHE_TTL}, "models_loaded": {"decision_tree_v3": _decision_tree_v3 is not None, "building_encoder": _building_encoder is not None, "signal_strength_model": _signal_strength_model is not None}, "ap_index_size": len(_ap_index) if _ap_index else 0, "buildings_count": len(_buildings_list) if _buildings_list else 0}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False, log_level="info")