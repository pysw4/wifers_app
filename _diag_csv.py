"""Check if model predictions match CSV signal_db values for a specific AP."""
import json, joblib, pandas as pd, numpy as np

model = joblib.load('models/signal_strength_model.joblib')
building_encoder = joblib.load('models/building_encoder.joblib')
with open('geolocation_package/data/aps_geolocalizados_wgs84.geojson') as f: geojson = json.load(f)

# Load CSV
cli = pd.read_csv('clientes_processed.csv', nrows=500000)

# Pick an AP with lots of data
target = 'ap-llet39'
target_upper = target.upper()
ap_data = cli[cli['associated_device_name'] == target_upper]

print(f"AP: {target} (CSV name: {target_upper})")
print(f"Total CSV samples: {len(ap_data)}")
print(f"signal_db in CSV: min={ap_data['signal_db'].min()}, max={ap_data['signal_db'].max()}, mean={ap_data['signal_db'].mean():.1f}")
print()

# Group by hour
hourly = ap_data.groupby('hour')['signal_db'].agg(['mean', 'count', 'min', 'max'])
print(f"{'Hour':>4} | {'Mean':>7} | {'Count':>5} | {'Min':>7} | {'Max':>7}")
print("-" * 40)
for h, row in hourly.iterrows():
    print(f"{int(h):4d} | {row['mean']:>7.1f} | {int(row['count']):>5d} | {row['min']:>7.1f} | {row['max']:>7.1f}")

# Now predict using model
for feat in geojson['features']:
    props = feat['properties']
    name = str(props.get('USER_NOM_A', '')).strip().lower()
    if name == target:
        building = props.get('USER_EDIFI', props.get('Nom_Edific', 'Unknown'))
        floor = float(props.get('Num_Planta', 0) or 0)
        bc = int(building_encoder.transform([building])[0])
        
        rows = []
        for h in range(24):
            rows.append({'building_code': bc, 'floor': floor, 'hour': float(h), 'band': 5.0,
                         'day_of_week': 2.0, 'is_weekend': 0.0, 'day_of_month': 15.0, 'month': 4.0, 'ap_name_code': 0})
        preds = model.predict(pd.DataFrame(rows))
        
        print(f"\n{'Hour':>4} | {'Predicted':>8} | {'CSV Mean':>8} | {'Diff':>6}")
        print("-" * 35)
        for h in range(24):
            if h in hourly.index:
                csv_mean = hourly.loc[h, 'mean']
                diff = abs(preds[h] - csv_mean)
                print(f"{h:4d} | {preds[h]:>7.1f} | {csv_mean:>7.1f} | {diff:>5.1f}")
            else:
                print(f"{h:4d} | {preds[h]:>7.1f} | {'N/A':>8} | {'N/A':>6}")
        break
