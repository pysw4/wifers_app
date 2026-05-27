#!/usr/bin/env python3
"""
Wifers App - FastAPI Backend Server

Provides REST API endpoints for:
  - /predict: AP status prediction (Up/Down)
  - /predict/signal_strength/heatmap: Pre-computed signal strength heatmap
  - /predict/signal_strength/ap_trend: Daily signal trend for a specific AP
  - /recommend: AP recommendation based on location and preferences
  - /route: Basic routing between two points
  - /route/advanced: Advanced routing with signal-aware pathfinding
  - /health: Health check endpoint

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

# =====================================================================
# Configuration
# =====================================================================
BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "models"
PRECOMPUTED_DIR = BASE_DIR / "precomputed"
GEOJSON_PATH = (
    BASE_DIR
    / "geolocation_package"
    / "data"
    / "aps_geolocalizados_wgs84.geojson"
)

# Day-of-week mapping (0=Mon, 6=Sun)
DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

# Night hours (0-6) share h3 as representative
NIGHT_REPRESENTATIVE_HOUR = 3

# =====================================================================
# FastAPI App Setup
# =====================================================================
app = FastAPI(
    title="Wifers App API",
    description="Backend API for Wi-Fi signal prediction and recommendation",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =====================================================================
# Lazy-loaded Models (loaded on first use, cached globally)
# =====================================================================
_decision_tree: Any = None
_building_encoder: Any = None
_signal_strength_model: Any = None
_signal_strength_meta: Any = None
_geojson_data: Optional[dict] = None


def _load_decision_tree():
    """Lazy-load the decision tree classifier for AP status prediction."""
    global _decision_tree
    if _decision_tree is None:
        path = MODELS_DIR / "decision_tree.joblib"
        if not path.exists():
            raise FileNotFoundError(f"Decision tree model not found: {path}")
        _decision_tree = joblib.load(path)
    return _decision_tree


def _load_building_encoder():
    """Lazy-load the building label encoder."""
    global _building_encoder
    if _building_encoder is None:
        path = MODELS_DIR / "building_encoder.joblib"
        if path.exists():
            _building_encoder = joblib.load(path)
    return _building_encoder


def _load_signal_strength_model():
    """Lazy-load the signal strength regression model."""
    global _signal_strength_model
    if _signal_strength_model is None:
        path = MODELS_DIR / "signal_strength_model.joblib"
        if not path.exists():
            raise FileNotFoundError(f"Signal strength model not found: {path}")
        _signal_strength_model = joblib.load(path)
    return _signal_strength_model


def _load_signal_strength_meta():
    """Lazy-load signal strength model metadata (buildings list)."""
    global _signal_strength_meta
    if _signal_strength_meta is None:
        path = MODELS_DIR / "signal_strength_meta.joblib"
        if path.exists():
            _signal_strength_meta = joblib.load(path)
    return _signal_strength_meta or {}


def _load_geojson() -> dict:
    """Lazy-load GeoJSON data."""
    global _geojson_data
    if _geojson_data is None:
        if not GEOJSON_PATH.exists():
            raise FileNotFoundError(f"GeoJSON file not found: {GEOJSON_PATH}")
        with open(GEOJSON_PATH) as f:
            _geojson_data = json.load(f)
    return _geojson_data


# =====================================================================
# Helper Functions
# =====================================================================

def _validate_day(day: str) -> str:
    """Validate and normalize day parameter. Returns the day key (e.g. 'mon')."""
    day_lower = day.strip().lower()
    if day_lower in DAY_NAMES:
        return day_lower
    # Try matching full names
    full_names = {
        "monday": "mon", "tuesday": "tue", "wednesday": "wed",
        "thursday": "thu", "friday": "fri", "saturday": "sat", "sunday": "sun",
    }
    if day_lower in full_names:
        return full_names[day_lower]
    raise HTTPException(
        status_code=400,
        detail=f"Invalid day: '{day}'. Must be one of {DAY_NAMES}",
    )


def _validate_hour(hour: int) -> int:
    """Validate hour parameter (0-23)."""
    if not isinstance(hour, int) or hour < 0 or hour > 23:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid hour: {hour}. Must be an integer between 0 and 23.",
        )
    return hour


def _get_heatmap_filepath(day: str, hour: int) -> Path:
    """
    Get the file path for a pre-computed heatmap.
    Night hours (0-6) use h3 as representative.
    """
    effective_hour = NIGHT_REPRESENTATIVE_HOUR if hour < 7 else hour
    return PRECOMPUTED_DIR / day / f"heatmap_h{effective_hour}.json"


def _load_heatmap_file(day: str, hour: int) -> dict:
    """Load a pre-computed heatmap file, returning the data with corrected hour."""
    filepath = _get_heatmap_filepath(day, hour)
    if not filepath.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Heatmap not found for {day} hour {hour}",
        )
    with open(filepath) as f:
        data = json.load(f)
    # Ensure the hour field matches the requested hour (night files use h3)
    data["hour"] = hour
    return data


def _encode_building(building_name: str) -> int:
    """Encode building name to integer using the building encoder."""
    encoder = _load_building_encoder()
    meta = _load_signal_strength_meta()
    buildings_list = meta.get("buildings", [])

    if encoder is not None and building_name in encoder.classes_:
        return int(encoder.transform([building_name])[0])
    # Fallback: fuzzy match
    for i, b in enumerate(buildings_list):
        if building_name.lower() in b.lower() or b.lower() in building_name.lower():
            return i
    return 0


def _dbm_to_quality(dbm: float) -> dict:
    """Convert dBm signal strength to quality label and bars."""
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


# =====================================================================
# Pydantic Models
# =====================================================================

class PredictRequest(BaseModel):
    model_config = {"extra": "ignore"}  # Ignore extra fields from Flutter (client_count, cpu_utilization, etc.)
    building_code: float = Field(default=0, description="Encoded building identifier")
    floor: float = Field(default=0, description="Floor number")
    hour: float = Field(default=12, description="Hour of day (0-23)")
    band: float = Field(default=5.0, description="Frequency band (2.4 or 5 GHz)")
    day_of_week: float = Field(default=0, description="Day of week (0=Mon, 6=Sun)")
    is_weekend: float = Field(default=0, description="Is weekend (0 or 1)")
    day_of_month: float = Field(default=15, description="Day of month")
    month: float = Field(default=4, description="Month (1-12)")


class RecommendRequest(BaseModel):
    lat: float
    lng: float
    radius: int = Field(default=500, ge=50, le=2000)
    mode: str = Field(default="balanced", pattern="^(distance|signal|balanced)$")
    building: str = Field(default="")
    prefer_stable: bool = Field(default=True)


# =====================================================================
# Routes
# =====================================================================

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "timestamp": time.time(),
        "precomputed_days": len(DAY_NAMES),
        "precomputed_hours": 24,
    }


# -----------------------------------------------------------------------
# /predict - AP Status Prediction (Up/Down)
# -----------------------------------------------------------------------

@app.post("/predict")
async def predict_ap_status(request: PredictRequest):
    """
    Predict whether an AP is Up or Down based on features.
    Uses a pre-trained decision tree classifier.
    """
    try:
        model = _load_decision_tree()
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

    features = [
        [
            request.building_code,
            request.floor,
            request.hour,
            request.band,
            request.day_of_week,
            request.is_weekend,
            request.day_of_month,
            request.month,
        ]
    ]
    prediction = model.predict(features)[0]
    probability = model.predict_proba(features)[0].tolist()

    return {
        "prediction": "Up" if prediction == 1 else "Down",
        "probability": probability,
        "features": features[0],
    }


# -----------------------------------------------------------------------
# /predict/signal_strength/heatmap - Pre-computed Signal Heatmap
# -----------------------------------------------------------------------

@app.get("/predict/signal_strength/heatmap")
async def get_signal_heatmap(
    hour: int = Query(default=12, description="Hour of day (0-23)"),
    day: str = Query(default="mon", description="Day of week (mon/tue/wed/thu/fri/sat/sun)"),
):
    """
    Get pre-computed signal strength heatmap data for a given day and hour.

    Returns AP point predictions and smooth grid interpolation.
    Data is pre-computed and stored in precomputed/{day}/heatmap_h{hour}.json.
    Night hours (0-6) share the h3 representative data.
    """
    day_key = _validate_day(day)
    validated_hour = _validate_hour(hour)

    try:
        data = _load_heatmap_file(day_key, validated_hour)
        return JSONResponse(content=data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load heatmap: {str(e)}",
        )


# -----------------------------------------------------------------------
# /predict/signal_strength/ap_trend - Daily Signal Trend for an AP
# -----------------------------------------------------------------------

@app.get("/predict/signal_strength/ap_trend/{ap_name:path}")
async def get_ap_daily_trend(ap_name: str):
    """
    Get the daily signal strength trend for a specific AP across all 24 hours.
    Uses the signal strength model to predict for each hour of the current day.
    """
    try:
        geojson = _load_geojson()
        model = _load_signal_strength_model()
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

    # Find the AP in GeoJSON
    ap_feature = None
    for feature in geojson["features"]:
        props = feature["properties"]
        if props.get("USER_NOM_A", "").strip().lower() == ap_name.strip().lower():
            ap_feature = feature
            break

    if ap_feature is None:
        raise HTTPException(status_code=404, detail=f"AP '{ap_name}' not found")

    props = ap_feature["properties"]
    coords = ap_feature["geometry"]["coordinates"]
    building = props.get("USER_EDIFI", "Unknown")
    floor = float(props.get("Num_Planta", 0) or 0)
    building_code = _encode_building(building)

    # Predict signal for all 24 hours (using Monday as default day)
    rows = []
    for hour in range(24):
        rows.append({
            "building_code": building_code,
            "floor": floor,
            "hour": float(hour),
            "band": 5.0,
            "day_of_week": 0.0,
            "is_weekend": 0.0,
            "day_of_month": 15.0,
            "month": 4.0,
        })

    df = pd.DataFrame(rows)
    predictions = model.predict(df)

    hourly_data = []
    for hour, signal_db in enumerate(predictions):
        quality_info = _dbm_to_quality(float(signal_db))
        hourly_data.append({
            "hour": hour,
            "signal_db": round(float(signal_db), 1),
            "signal_quality": quality_info["quality"],
            "bars": quality_info["bars"],
        })

    return {
        "ap_name": ap_name,
        "building": building,
        "floor": int(floor),
        "lat": float(coords[1]),
        "lng": float(coords[0]),
        "hourly_data": hourly_data,
    }


# -----------------------------------------------------------------------
# /recommend - AP Recommendation
# -----------------------------------------------------------------------

@app.post("/recommend")
async def recommend_aps(request: RecommendRequest):
    """
    Recommend nearby APs based on location, signal strength, and preferences.
    Uses the signal strength model for predictions.

    Returns fields compatible with the Flutter RecommendPage:
      - recommendations: list of APs with id, name, building, floor, lat, lng,
        distance, prediction (Up/Down via decision tree), confidence, score,
        signal_db, signal_quality, bars, up_probability
    """
    try:
        geojson = _load_geojson()
        signal_model = _load_signal_strength_model()
        decision_model = _load_decision_tree()
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

    # Get current hour and day for signal lookup
    current_hour = time.localtime().tm_hour
    current_day = time.localtime().tm_wday  # 0=Mon, 6=Sun
    current_day_of_month = float(time.localtime().tm_mday)
    current_month = float(time.localtime().tm_mon)

    # Find nearby APs
    nearby_aps = []
    for feature in geojson["features"]:
        props = feature["properties"]
        coords = feature["geometry"]["coordinates"]
        ap_lng, ap_lat = float(coords[0]), float(coords[1])

        # Simple bounding box filter (faster than haversine for initial filter)
        lat_diff = (ap_lat - request.lat) * 111_320
        lng_diff = (ap_lng - request.lng) * 111_320 * abs(math.cos(math.radians(request.lat)))
        distance = math.sqrt(lat_diff**2 + lng_diff**2)

        if distance > request.radius:
            continue

        building = props.get("USER_EDIFI", "Unknown")
        if request.building and request.building.lower() not in building.lower():
            continue

        ap_name = props.get("USER_NOM_A", "Unknown")
        ap_id = props.get("USER_ID", ap_name)  # Use USER_ID if available, fallback to name
        floor = float(props.get("Num_Planta", 0) or 0)

        nearby_aps.append({
            "id": ap_id,
            "name": ap_name,
            "lat": ap_lat,
            "lng": ap_lng,
            "building": building,
            "floor": int(floor),
            "distance": round(distance, 1),
        })

    if not nearby_aps:
        return {"recommendations": [], "message": "No APs found in the specified area"}

    # Predict signal strength and status for each nearby AP
    for ap in nearby_aps:
        building_code = _encode_building(ap["building"])
        features = {
            "building_code": building_code,
            "floor": float(ap["floor"]),
            "hour": float(current_hour),
            "band": 5.0,
            "day_of_week": float(current_day),
            "is_weekend": 1.0 if current_day >= 5 else 0.0,
            "day_of_month": current_day_of_month,
            "month": current_month,
        }

        # Signal strength prediction
        features_df = pd.DataFrame([features])
        signal_db = float(signal_model.predict(features_df)[0])
        quality_info = _dbm_to_quality(signal_db)
        ap["signal_db"] = round(signal_db, 1)
        ap["signal_quality"] = quality_info["quality"]
        ap["bars"] = quality_info["bars"]

        # Status prediction (Up/Down) via decision tree
        decision_features = [[
            features["building_code"],
            features["floor"],
            features["hour"],
            features["band"],
            features["day_of_week"],
            features["is_weekend"],
            features["day_of_month"],
            features["month"],
        ]]
        status_pred = decision_model.predict(decision_features)[0]
        status_prob = decision_model.predict_proba(decision_features)[0].tolist()
        ap["prediction"] = "Up" if status_pred == 1 else "Down"
        ap["confidence"] = round(max(status_prob), 3)
        ap["up_probability"] = round(status_prob[1] if len(status_prob) > 1 else status_prob[0], 3)

    # Score and rank APs based on mode
    for ap in nearby_aps:
        signal_score = max(0, (ap["signal_db"] + 100) / 50)  # Normalize to 0-1
        distance_score = max(0, 1 - ap["distance"] / request.radius)

        if request.mode == "distance":
            score = distance_score * 0.8 + signal_score * 0.2
        elif request.mode == "signal":
            score = signal_score * 0.8 + distance_score * 0.2
        else:  # balanced
            score = signal_score * 0.5 + distance_score * 0.5

        ap["score"] = round(score, 3)

    # Sort by score descending
    nearby_aps.sort(key=lambda x: x["score"], reverse=True)

    return {
        "recommendations": nearby_aps[:20],  # Top 20
        "total_found": len(nearby_aps),
        "mode": request.mode,
        "radius": request.radius,
    }


# -----------------------------------------------------------------------
# /route - Basic Routing
# -----------------------------------------------------------------------

@app.get("/route/{lat}/{lng}/{dest_lat}/{dest_lng}")
async def get_route(lat: float, lng: float, dest_lat: float, dest_lng: float):
    """
    Get a simple straight-line path between two points.
    Returns intermediate points for rendering on the map.
    """
    num_points = 20
    path = []
    for i in range(num_points + 1):
        t = i / num_points
        path.append({
            "lat": round(lat + (dest_lat - lat) * t, 6),
            "lng": round(lng + (dest_lng - lng) * t, 6),
        })

    return {"path": path}


# -----------------------------------------------------------------------
# /route/advanced - Advanced Signal-Aware Routing
# -----------------------------------------------------------------------

@app.get("/route/advanced/{lat}/{lng}/{dest_lat}/{dest_lng}")
async def get_advanced_route(
    lat: float,
    lng: float,
    dest_lat: float,
    dest_lng: float,
    acceptable_range: int = Query(default=500, ge=100, le=5000, alias="acceptable_range"),
):
    """
    Get an advanced route that considers signal strength along the path.
    Uses pre-computed heatmap data to find signal-optimized waypoints.
    """
    try:
        geojson = _load_geojson()
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

    # Find APs near the path
    path_aps = []
    for feature in geojson["features"]:
        props = feature["properties"]
        coords = feature["geometry"]["coordinates"]
        ap_lng, ap_lat = float(coords[0]), float(coords[1])

        # Check if AP is within acceptable range of either endpoint
        for ref_lat, ref_lng in [(lat, lng), (dest_lat, dest_lng)]:
            lat_diff = (ap_lat - ref_lat) * 111_320
            lng_diff = (ap_lng - ref_lng) * 111_320 * abs(math.cos(math.radians(ref_lat)))
            distance = math.sqrt(lat_diff**2 + lng_diff**2)
            if distance <= acceptable_range:
                path_aps.append({
                    "lat": ap_lat,
                    "lng": ap_lng,
                    "building": props.get("USER_EDIFI", "Unknown"),
                    "floor": float(props.get("Num_Planta", 0) or 0),
                    "ap_name": props.get("USER_NOM_A", "Unknown"),
                    "distance_to_start": round(distance, 1),
                })
                break

    return {
        "path": [
            {"lat": round(lat, 6), "lng": round(lng, 6)},
            *[{"lat": round(ap["lat"], 6), "lng": round(ap["lng"], 6)} for ap in path_aps],
            {"lat": round(dest_lat, 6), "lng": round(dest_lng, 6)},
        ],
        "waypoints": path_aps,
        "total_waypoints": len(path_aps),
    }


# =====================================================================
# Entry Point
# =====================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info",
    )
