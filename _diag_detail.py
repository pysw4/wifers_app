"""Detailed comparison for ap-llet39 - check if trend is truly inverted."""
import json, joblib, pandas as pd, numpy as np

model = joblib.load('models/signal_strength_model.joblib')
building_encoder = joblib.load('models/building_encoder.joblib')
with open('precomputed/actual_signal_averages.json') as f: actual_data = json.load(f)
with open('geolocation_package/data/aps_geolocalizados_wgs84.geojson') as f: geojson = json.load(f)
cli = pd.read_csv('clientes_processed.csv', nrows=500000)

target = 'ap-llet39'
target_upper = target.upper()

# Get CSV data
ap_data = cli[cli['associated_device_name'] == target_upper]
csv_hourly = ap_data.groupby('hour')['signal_db'].mean()

# Find building
for feat in geojson['features']:
    props = feat['properties']
    name = str(props.get('USER_NOM_A', '')).strip().lower()
    if name == target:
        building = props.get('USER_EDIFI', props.get('Nom_Edific', 'Unknown'))
        floor = float(props.get('Num_Planta', 0) or 0)
        bc = int(building_encoder.transform([building])[0])
        
        # Predict
        rows = []
        for h in range(24):
            rows.append({'building_code': bc, 'floor': floor, 'hour': float(h), 'band': 5.0,
                         'day_of_week': 2.0, 'is_weekend': 0.0, 'day_of_month': 15.0, 'month': 4.0, 'ap_name_code': 0})
        preds = model.predict(pd.DataFrame(rows))
        
        print(f"AP: {target}")
        print(f"Building: {building} (code: {bc}), Floor: {floor}")
        print()
        print(f"{'Hour':>4} | {'Predicted':>8} | {'CSV Mean':>8} | {'CSV Samples':>11}")
        print("-" * 40)
        
        for h in range(24):
            if h in csv_hourly.index:
                csv_mean = csv_hourly[h]
                samples = len(ap_data[ap_data['hour'] == h])
                print(f"{h:4d} | {preds[h]:>7.1f} | {csv_mean:>7.1f} | {samples:>10d}")
            else:
                print(f"{h:4d} | {preds[h]:>7.1f} | {'N/A':>8} | {'N/A':>11}")
        
        # Check trend direction for consecutive hours
        print(f"\nTrend direction (consecutive hours):")
        print(f"{'Hours':>10} | {'Pred Dir':>8} | {'Actual Dir':>10}")
        print("-" * 35)
        for h in range(5, 16):
            if h in csv_hourly.index and (h+1) in csv_hourly.index:
                pred_dir = 'up' if preds[h+1] > preds[h] else 'down'
                actual_dir = 'up' if csv_hourly[h+1] > csv_hourly[h] else 'down'
                match = 'SAME' if pred_dir == actual_dir else 'OPPOSITE'
                print(f"h{h}-h{h+1}:    | {pred_dir:>8} | {actual_dir:>10} | {match}")
        break
