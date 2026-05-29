#!/usr/bin/env python3
"""Diagnose: simulate what the backend returns for a specific AP and check the hourly data."""
import json
import joblib
import numpy as np
import pandas as pd

# Load model and encoders
model = joblib.load('models/signal_strength_model.joblib')
building_encoder = joblib.load('models/building_encoder.joblib')

# Load actual averages
with open('precomputed/actual_signal_averages.json') as f:
    actual_data = json.load(f)

# Load AP index
with open('geolocation_package/data/aps_geolocalizados_wgs84.geojson') as f:
    geojson = json.load(f)

# Pick a specific AP that has lots of actual data
# From earlier: ap-llet39 has 1344 measurements
target_ap = "ap-llet39"

# Find it in geojson
for feat in geojson['features']:
    props = feat['properties']
    name = str(props.get('USER_NOM_A', '')).strip().lower()
    if name == target_ap:
        building = props.get('USER_EDIFI', props.get('Nom_Edific', 'Unknown'))
        floor = props.get('Num_Planta', 0)
        if isinstance(floor, str):
            try: floor = int(floor)
            except: floor = 0
        coords = feat['geometry']['coordinates']
        
        building_code = int(building_encoder.transform([building])[0])
        
        print(f"AP: {target_ap}")
        print(f"Building: {building} (code: {building_code})")
        print(f"Floor: {floor}")
        print(f"Location: {coords[1]}, {coords[0]}")
        print()
        
        # Predict 24 hours
        rows = []
        for hour in range(24):
            rows.append({
                'building_code': building_code, 'floor': float(floor), 'hour': float(hour),
                'band': 5.0, 'day_of_week': 2.0, 'is_weekend': 0.0,
                'day_of_month': 15.0, 'month': 4.0, 'ap_name_code': 0
            })
        df = pd.DataFrame(rows)
        preds = model.predict(df)
        
        # Get actual data
        actual = actual_data.get(target_ap, {})
        hourly_actual = actual.get('hourly', {})
        
        print(f"{'Hour':>5} | {'Predicted':>10} | {'Actual Mean':>12} | {'Samples':>8}")
        print("-" * 45)
        
        for h in range(24):
            pred = preds[h]
            h_str = str(h)
            if h_str in hourly_actual:
                actual_mean = hourly_actual[h_str]['actual_mean']
                samples = hourly_actual[h_str]['samples']
                print(f"{h:5d} | {pred:>8.1f} dBm | {actual_mean:>8.1f} dBm | {samples:>8d}")
            else:
                print(f"{h:5d} | {pred:>8.1f} dBm | {'N/A':>12} | {'N/A':>8}")
        
        print()
        print("=== Key observation ===")
        print("Both predicted and actual are negative dBm values.")
        print("The chart Y-axis goes from most negative (bottom) to least negative (top).")
        print("So -90 dBm is at the bottom, -30 dBm is at the top.")
        print()
        print("If the green line (actual average) appears 'inverted' relative to the blue line (predicted),")
        print("it means the actual values trend opposite to predicted values.")
        print("This is a MODEL ACCURACY issue, not a sign issue.")
        break
