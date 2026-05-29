import json, joblib, pandas as pd
model = joblib.load('models/signal_strength_model.joblib')
building_encoder = joblib.load('models/building_encoder.joblib')
with open('precomputed/actual_signal_averages.json') as f: actual_data = json.load(f)
with open('geolocation_package/data/aps_geolocalizados_wgs84.geojson') as f: geojson = json.load(f)

# Find ap-llet39
for feat in geojson['features']:
    name = str(feat['properties'].get('USER_NOM_A', '')).strip().lower()
    if name == 'ap-llet39':
        building = feat['properties'].get('USER_EDIFI', 'Unknown')
        floor = float(feat['properties'].get('Num_Planta', 0) or 0)
        bc = int(building_encoder.transform([building])[0])
        
        rows = [{'building_code': bc, 'floor': floor, 'hour': float(h), 'band': 5.0,
                 'day_of_week': 2.0, 'is_weekend': 0.0, 'day_of_month': 15.0, 'month': 4.0, 'ap_name_code': 0}
                for h in range(24)]
        preds = model.predict(pd.DataFrame(rows))
        
        actual = actual_data.get('ap-llet39', {}).get('hourly', {})
        
        print("Hour | Predicted | Actual | Samples")
        for h in range(24):
            a = actual.get(str(h), {})
            act_str = f"{a.get('actual_mean','N/A'):>8}" if a else "     N/A"
            sam_str = f"{a.get('samples','N/A'):>5}" if a else "  N/A"
            print(f"{h:4d} | {preds[h]:>8.1f} | {act_str} | {sam_str}")
        break
