#!/usr/bin/env python3
"""
Pre-compute heatmap data script (supports all 7 days of the week)
Generates 168 heatmap files (7 days × 24 hours) in one go,
saves as static JSON files for millisecond API response.

Usage:
    python precompute_heatmaps.py

Output:
    precomputed/
        mon/  heatmap_h0.json  ~  heatmap_h23.json   (24 files)
        tue/  heatmap_h0.json  ~  heatmap_h23.json   (24 files)
        wed/  heatmap_h0.json  ~  heatmap_h23.json   (24 files)
        thu/  heatmap_h0.json  ~  heatmap_h23.json   (24 files)
        fri/  heatmap_h0.json  ~  heatmap_h23.json   (24 files)
        sat/  heatmap_h0.json  ~  heatmap_h23.json   (24 files)
        sun/  heatmap_h0.json  ~  heatmap_h23.json   (24 files)
"""

import json
import os
import time
from pathlib import Path
from math import radians, cos, sin, asin, sqrt

import joblib
import pandas as pd
import numpy as np

# =====================================================================
# Configuration
# =====================================================================
BASE_DIR = Path(__file__).resolve().parent
GEOJSON_PATH = BASE_DIR / 'geolocation_package' / 'data' / 'aps_geolocalizados_wgs84.geojson'
SIGNAL_MODEL_PATH = BASE_DIR / 'models' / 'signal_strength_model.joblib'
SIGNAL_META_PATH = BASE_DIR / 'models' / 'signal_strength_meta.joblib'
BUILDING_ENCODER_PATH = BASE_DIR / 'models' / 'building_encoder.joblib'
OUTPUT_DIR = BASE_DIR / 'precomputed'

UAB_bbox = 41.50736, 41.49505, 2.11543, 2.09491  # north, south, east, west

# Day-of-week mapping: 0=Mon, 6=Sun
DAY_NAMES = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
DAY_FULL_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

# =====================================================================
# Load model and encoder
# =====================================================================
print("=" * 60)
print("Pre-computing heatmap data for all 7 days × 24 hours")
print("=" * 60)

print("\n[1] Loading signal strength model...")
signal_model = joblib.load(SIGNAL_MODEL_PATH)
print(f"  Model loaded from {SIGNAL_MODEL_PATH}")

building_encoder = None
buildings_list = None
if BUILDING_ENCODER_PATH.exists():
    building_encoder = joblib.load(BUILDING_ENCODER_PATH)
    print(f"  Building encoder loaded from {BUILDING_ENCODER_PATH}")
if SIGNAL_META_PATH.exists():
    meta = joblib.load(SIGNAL_META_PATH)
    buildings_list = meta.get('buildings', [])
    print(f"  Buildings list: {len(buildings_list)} buildings")

# =====================================================================
# Load GeoJSON
# =====================================================================
print("\n[2] Loading GeoJSON data...")
with open(GEOJSON_PATH) as f:
    geojson_data = json.load(f)

features = geojson_data['features']
print(f"  Loaded {len(features)} AP features from GeoJSON")

# =====================================================================
# Build building encoding function
# =====================================================================
def encode_building(building_name: str) -> int:
    """Encode building name to integer"""
    if building_encoder is not None:
        if building_name in building_encoder.classes_:
            return int(building_encoder.transform([building_name])[0])
        if buildings_list:
            for i, b in enumerate(buildings_list):
                if building_name.lower() in b.lower() or b.lower() in building_name.lower():
                    return i
    return 0

# =====================================================================
# Build AP point list
# =====================================================================
print("\n[3] Computing signal strength for all APs × 7 days × 24 hours...")

# First extract basic info for all APs
ap_points_base = []
for feature in features:
    props = feature['properties']
    coords = feature['geometry']['coordinates']
    
    building = props.get('USER_EDIFI', 'Unknown')
    if building == 'Unknown' or not building:
        continue
    
    ap_points_base.append({
        'lat': float(coords[1]),
        'lng': float(coords[0]),
        'building': building,
        'floor': float(props.get('Num_Planta', 0) or 0),
        'ap_name': props.get('USER_NOM_A', 'Unknown'),
    })

print(f"  Total APs with valid building: {len(ap_points_base)}")

# Pre-compute building_code to avoid repeated encoding
for ap in ap_points_base:
    ap['building_code'] = encode_building(ap['building'])

# Batch predict all APs × 24 hours × 7 days
all_hours = list(range(24))
total_predictions = len(ap_points_base) * len(all_hours) * len(DAY_NAMES)

print(f"  Total predictions needed: {total_predictions}")
print(f"  Predicting...")

start_time = time.time()

# Build feature matrix for each hour + day of week
# Must match the 8 features the model was trained on:
#   building_code, floor, hour, band, day_of_week, is_weekend, day_of_month, month
for dow_idx, day_name in enumerate(DAY_NAMES):
    for hour in all_hours:
        rows = []
        for ap in ap_points_base:
            rows.append({
                'building_code': ap['building_code'],
                'floor': ap['floor'],
                'hour': float(hour),
                'band': 5.0,  # Fixed to use 5GHz as total signal strength
                'day_of_week': float(dow_idx),
                'is_weekend': 1.0 if dow_idx >= 5 else 0.0,
                'day_of_month': 15.0,  # 使用月中值作为默认
                'month': 4.0,  # 使用4月（数据集中最常见的月份）
            })
        
        df = pd.DataFrame(rows)
        predictions = signal_model.predict(df)

        
        # Write predictions back to ap_points_base
        key = f'{day_name}_h{hour}'
        for i, ap in enumerate(ap_points_base):
            if 'signal_by_hour' not in ap:
                ap['signal_by_hour'] = {}
            ap['signal_by_hour'][key] = float(predictions[i])

elapsed = time.time() - start_time
print(f"  Done in {elapsed:.1f} seconds ({total_predictions/elapsed:.0f} predictions/sec)")

# =====================================================================
# Signal quality conversion function
# =====================================================================
def dbm_to_quality(dbm: float) -> dict:
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
# Generate and save merged heatmap data (one file per hour × day)
# =====================================================================
print("\n[4] Generating merged heatmap data (AP points + smooth grid)...")

# Smooth grid parameters
north, south, east, west = UAB_bbox
margin_lat = (north - south) * 0.02
margin_lng = (east - west) * 0.02
lat_min = south + margin_lat
lat_max = north - margin_lat
lng_min = west + margin_lng
lng_max = east - margin_lng

resolution = 30
lat_grid = [lat_min + (lat_max - lat_min) * i / (resolution - 1) for i in range(resolution)]
lng_grid = [lng_min + (lng_max - lng_min) * i / (resolution - 1) for i in range(resolution)]

def haversine_distance(lat1, lng1, lat2, lng2):
    R = 6371000
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    c = 2 * asin(sqrt(a))
    return R * c

def idw_interpolate(target_lat, target_lng, source_points, power=2, max_dist=300):
    weights = []
    values = []
    total_weight = 0.0
    
    for pt in source_points:
        dist = haversine_distance(target_lat, target_lng, pt['lat'], pt['lng'])
        if dist < 1:
            return pt['signal_db']
        if dist > max_dist:
            continue
        w = 1.0 / (dist ** power)
        weights.append(w)
        values.append(pt['signal_db'])
        total_weight += w
    
    if total_weight == 0:
        return None
    
    weighted_avg = sum(w * v for w, v in zip(weights, values)) / total_weight
    return weighted_avg

legend = {
    "Excellent": {"min_db": -50, "max_db": 0, "color": "green", "bars": 5},
    "Good": {"min_db": -60, "max_db": -50, "color": "yellow", "bars": 4},
    "Fair": {"min_db": -70, "max_db": -60, "color": "orange", "bars": 3},
    "Weak": {"min_db": -80, "max_db": -70, "color": "red", "bars": 2},
    "Very Poor": {"min_db": -100, "max_db": -80, "color": "darkred", "bars": 1},
}

for dow_idx, day_name in enumerate(DAY_NAMES):
    day_dir = OUTPUT_DIR / day_name
    os.makedirs(day_dir, exist_ok=True)
    
    for hour in all_hours:
        key = f'{day_name}_h{hour}'
        
        # --- AP point data ---
        heatmap_points = []
        processed_buildings = set()
        
        for ap in ap_points_base:
            signal_db = ap['signal_by_hour'][key]
            quality_info = dbm_to_quality(signal_db)
            
            heatmap_points.append({
                "lat": ap['lat'],
                "lng": ap['lng'],
                "signal_db": round(signal_db, 1),
                "signal_quality": quality_info["quality"],
                "bars": quality_info["bars"],
                "ap_name": ap['ap_name'],
                "building": ap['building'],
                "floor": int(ap['floor']),
            })
            processed_buildings.add(ap['building'])
        
        # --- Smooth grid data ---
        ap_points_for_idw = []
        for ap in ap_points_base:
            ap_points_for_idw.append({
                'lat': ap['lat'],
                'lng': ap['lng'],
                'signal_db': ap['signal_by_hour'][key],
                'building': ap['building'],
                'floor': int(ap['floor']),
            })
        
        smooth_points = []
        for lat in lat_grid:
            for lng in lng_grid:
                signal = idw_interpolate(lat, lng, ap_points_for_idw, power=2)
                if signal is None:
                    continue
                
                quality_info = dbm_to_quality(signal)
                smooth_points.append({
                    "lat": round(lat, 6),
                    "lng": round(lng, 6),
                    "signal_db": round(signal, 1),
                    "signal_quality": quality_info["quality"],
                    "bars": quality_info["bars"],
                })
        
        # --- Merge output ---
        result = {
            "type": "heatmap",
            "hour": hour,
            "day_name": day_name,
            "day_full_name": DAY_FULL_NAMES[dow_idx],
            "day_of_week": dow_idx,
            "ap_points": {
                "total": len(heatmap_points),
                "buildings_count": len(processed_buildings),
                "buildings": sorted(list(processed_buildings)),
                "points": heatmap_points,
            },
            "smooth_grid": {
                "total": len(smooth_points),
                "grid_size": {"rows": resolution, "cols": resolution},
                "bounds": {
                    "north": lat_max,
                    "south": lat_min,
                    "east": lng_max,
                    "west": lng_min,
                },
                "points": smooth_points,
            },
            "legend": legend,
        }
        
        output_path = day_dir / f'heatmap_h{hour}.json'
        with open(output_path, 'w') as f:
            json.dump(result, f)
        
        print(f"  Saved {day_name}/heatmap_h{hour}.json "
              f"({len(heatmap_points)} AP points + {len(smooth_points)} grid points)")

# =====================================================================
# Done
# =====================================================================
print("\n" + "=" * 60)
print("Done! All heatmap data pre-computed.")
print(f"Output directory: {OUTPUT_DIR}")
print(f"Total files: {len(all_hours) * len(DAY_NAMES)} "
      f"({len(DAY_NAMES)} days × {len(all_hours)} hours)")
print("=" * 60)
