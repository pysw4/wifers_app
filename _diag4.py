import json, joblib, pandas as pd
model = joblib.load('models/signal_strength_model.joblib')
building_encoder = joblib.load('models/building_encoder.joblib')
with open('precomputed/actual_signal_averages.json') as f: actual_data = json.load(f)

# Use ap-llet39 directly - it has 1344 measurements
target = "ap-llet39"
actual = actual_data.get(target, {})
hourly = actual.get('hourly', {})

print(f"AP: {target}")
print(f"Total measurements: {actual.get('total_measurements', 0)}")
print(f"Hours with data: {sorted(hourly.keys(), key=int)}")
print()

# We need building_code. Let's find it from the geojson
with open('geolocation_package/data/aps_geolocalizados_wgs84.geojson') as f:
    geojson = json.load(f)

for feat in geojson['features']:
    props = feat['properties']
    name = str(props.get('USER_NOM_A', '')).strip().lower()
    if name == target:
        building = props.get('USER_EDIFI', props.get('Nom_Edific', 'Unknown'))
        floor = float(props.get('Num_Planta', 0) or 0)
        bc = int(building_encoder.transform([building])[0])
        print(f"Found in geojson: building={building}, floor={floor}, bc={bc}")
        
        rows = []
        for h in range(24):
            rows.append({'building_code': bc, 'floor': floor, 'hour': float(h), 'band': 5.0,
                         'day_of_week': 2.0, 'is_weekend': 0.0, 'day_of_month': 15.0, 'month': 4.0, 'ap_name_code': 0})
        preds = model.predict(pd.DataFrame(rows))
        
        print(f"\n{'Hour':>4} | {'Predicted':>8} | {'Actual':>8} | {'Samples':>7} | {'Diff':>6}")
        print("-" * 50)
        for h in range(24):
            pred = preds[h]
            h_str = str(h)
            if h_str in hourly:
                am = hourly[h_str]['actual_mean']
                sam = hourly[h_str]['samples']
                diff = abs(pred - am)
                print(f"{h:4d} | {pred:>7.1f} | {am:>7.1f} | {sam:>6d} | {diff:>5.1f}")
            else:
                print(f"{h:4d} | {pred:>7.1f} | {'N/A':>8} | {'N/A':>7} | {'N/A':>6}")
        break
