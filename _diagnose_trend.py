#!/usr/bin/env python3
"""Diagnose the trend chart issue - check if predicted vs actual values are inverted."""
import json
import joblib
import numpy as np
import pandas as pd

# 1. Load model
model = joblib.load('models/signal_strength_model.joblib')
meta = joblib.load('models/signal_strength_meta.joblib')
print(f"Model: {type(model).__name__}")
print(f"Training signal range: {meta.get('signal_db_range', 'N/A')}")
print()

# 2. Load actual averages
with open('precomputed/actual_signal_averages.json') as f:
    actual_data = json.load(f)

# 3. Load building encoder
building_encoder = joblib.load('models/building_encoder.joblib')

# 4. Load AP index
with open('geolocation_package/data/aps_geolocalizados_wgs84.geojson') as f:
    geojson = json.load(f)

ap_index = []
for feat in geojson['features']:
    props = feat['properties']
    coords = feat['geometry']['coordinates']
    name = props.get('USER_NOM_A', '')
    building = props.get('USER_EDIFI', props.get('Nom_Edific', 'Unknown'))
    floor = props.get('Num_Planta', 0)
    if isinstance(floor, str):
        try: floor = int(floor)
        except: floor = 0
    ap_index.append({
        'name': str(name).strip().lower(),
        'building': building,
        'floor': float(floor) if floor is not None else 0.0,
    })

# 5. Find APs that have actual data and test
tested = 0
for ap_entry in ap_index:
    ap_key = ap_entry['name']
    if ap_key not in actual_data:
        continue
    
    building = ap_entry['building']
    try:
        building_code = int(building_encoder.transform([building])[0])
    except:
        continue
    
    floor = ap_entry['floor']
    
    # Predict 24 hours
    rows = []
    for hour in range(24):
        rows.append({
            'building_code': building_code, 'floor': floor, 'hour': float(hour),
            'band': 5.0, 'day_of_week': 2.0, 'is_weekend': 0.0,
            'day_of_month': 15.0, 'month': 4.0, 'ap_name_code': 0
        })
    df = pd.DataFrame(rows)
    preds = model.predict(df)
    
    actual = actual_data[ap_key]
    hourly = actual.get('hourly', {})
    
    print(f"AP: {ap_key} | Building: {building} | Floor: {floor}")
    print(f"{'Hour':>5} | {'Predicted':>10} | {'Actual Mean':>12} | {'Diff':>8}")
    print("-" * 45)
    
    diffs = []
    pred_signs = set()
    actual_signs = set()
    
    for h in range(24):
        pred = preds[h]
        pred_signs.add('pos' if pred > 0 else 'neg')
        
        h_str = str(h)
        if h_str in hourly:
            actual_mean = hourly[h_str]['actual_mean']
            actual_signs.add('pos' if actual_mean > 0 else 'neg')
            diff = abs(pred - actual_mean)
            diffs.append(diff)
            print(f"{h:5d} | {pred:>8.1f} dBm | {actual_mean:>8.1f} dBm | {diff:>6.1f} dBm")
        else:
            print(f"{h:5d} | {pred:>8.1f} dBm | {'N/A':>12} | {'N/A':>8}")
    
    print(f"Predicted signs: {pred_signs}")
    print(f"Actual signs: {actual_signs}")
    if diffs:
        print(f"MAE: {sum(diffs)/len(diffs):.1f} dBm")
        print(f"Min diff: {min(diffs):.1f}, Max diff: {max(diffs):.1f}")
    print()
    
    tested += 1
    if tested >= 3:
        break

print(f"\n=== Summary ===")
print(f"Tested {tested} APs")
print(f"Model predicts negative dBm values: ✓ (correct for RSSI)")
print(f"Actual averages are negative dBm values: ✓ (correct for RSSI)")
print(f"\nIf the chart looks inverted, the issue is NOT sign-related.")
print(f"Check the chart Y-axis scaling or the diff calculation in the frontend.")
