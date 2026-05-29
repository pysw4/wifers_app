"""Final diagnosis: compare model predictions with CSV actual values."""
import json, joblib, pandas as pd, numpy as np

model = joblib.load('models/signal_strength_model.joblib')
building_encoder = joblib.load('models/building_encoder.joblib')
with open('geolocation_package/data/aps_geolocalizados_wgs84.geojson') as f: geojson = json.load(f)
cli = pd.read_csv('clientes_processed.csv', nrows=500000)

# Build AP lookup
ap_lookup = {}
for feat in geojson['features']:
    props = feat['properties']
    name = str(props.get('USER_NOM_A', '')).strip().lower()
    building = props.get('USER_EDIFI', props.get('Nom_Edific', 'Unknown'))
    floor = float(props.get('Num_Planta', 0) or 0)
    ap_lookup[name] = {'building': building, 'floor': floor}

# Check top APs
aps_in_csv = cli['associated_device_name'].value_counts().head(20)
print(f"{'AP':<20} | {'CSV Samples':>11} | {'CSV Mean':>8} | {'Pred Mean':>9} | {'Corr':>6}")
print("=" * 60)

for ap_name, count in aps_in_csv.items():
    ap_key = ap_name.strip().lower()
    if ap_key not in ap_lookup:
        continue
    
    info = ap_lookup[ap_key]
    try:
        bc = int(building_encoder.transform([info['building']])[0])
    except:
        continue
    floor = info['floor']
    
    # Get CSV data
    ap_data = cli[cli['associated_device_name'] == ap_name]
    csv_hourly = ap_data.groupby('hour')['signal_db'].mean()
    
    # Predict
    rows = []
    for h in range(24):
        rows.append({'building_code': bc, 'floor': floor, 'hour': float(h), 'band': 5.0,
                     'day_of_week': 2.0, 'is_weekend': 0.0, 'day_of_month': 15.0, 'month': 4.0, 'ap_name_code': 0})
    preds = model.predict(pd.DataFrame(rows))
    
    # Correlation
    common_hours = [h for h in csv_hourly.index if h in range(24) and not np.isnan(csv_hourly[h])]
    if len(common_hours) >= 4:
        pv = [preds[h] for h in common_hours]
        av = [csv_hourly[h] for h in common_hours]
        corr = np.corrcoef(pv, av)[0, 1]
        pred_mean = np.mean(pv)
        csv_mean_val = np.mean(av)
        direction = 'INVERTED' if corr < 0 else 'aligned'
        print(f"{ap_key:<20} | {int(count):>11d} | {csv_mean_val:>7.1f}  | {pred_mean:>7.1f}  | {corr:>6.3f} ({direction})")
