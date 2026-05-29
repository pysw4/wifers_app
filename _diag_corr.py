"""Check correlation between predicted and actual trends for multiple APs."""
import json, joblib, pandas as pd, numpy as np

model = joblib.load('models/signal_strength_model.joblib')
building_encoder = joblib.load('models/building_encoder.joblib')
with open('precomputed/actual_signal_averages.json') as f: actual_data = json.load(f)
with open('geolocation_package/data/aps_geolocalizados_wgs84.geojson') as f: geojson = json.load(f)

# Build AP lookup
ap_lookup = {}
for feat in geojson['features']:
    props = feat['properties']
    name = str(props.get('USER_NOM_A', '')).strip().lower()
    building = props.get('USER_EDIFI', props.get('Nom_Edific', 'Unknown'))
    floor = float(props.get('Num_Planta', 0) or 0)
    ap_lookup[name] = {'building': building, 'floor': floor}

# Check APs with most data
aps_sorted = sorted(actual_data.keys(), key=lambda k: actual_data[k].get('total_measurements', 0), reverse=True)

results = []
for target in aps_sorted[:30]:
    if target not in ap_lookup:
        continue
    info = ap_lookup[target]
    try:
        bc = int(building_encoder.transform([info['building']])[0])
    except:
        continue
    floor = info['floor']
    actual = actual_data[target].get('hourly', {})
    
    rows = []
    for h in range(24):
        rows.append({'building_code': bc, 'floor': floor, 'hour': float(h), 'band': 5.0,
                     'day_of_week': 2.0, 'is_weekend': 0.0, 'day_of_month': 15.0, 'month': 4.0, 'ap_name_code': 0})
    preds = model.predict(pd.DataFrame(rows))
    
    actual_hours = sorted([int(k) for k in actual.keys()])
    full_actual = {}
    if len(actual_hours) >= 2:
        for h in range(24):
            hs = str(h)
            if hs in actual:
                full_actual[h] = actual[hs]['actual_mean']
            else:
                before = [ah for ah in actual_hours if ah < h]
                after = [ah for ah in actual_hours if ah > h]
                if before and after:
                    hb, ha = before[-1], after[0]
                    vb, va = actual[str(hb)]['actual_mean'], actual[str(ha)]['actual_mean']
                    ratio = (h - hb) / (ha - hb)
                    full_actual[h] = round(vb + (va - vb) * ratio, 1)
                elif before:
                    full_actual[h] = actual[str(before[-1])]['actual_mean']
                elif after:
                    full_actual[h] = actual[str(after[0])]['actual_mean']
    
    valid_h = [h for h in range(24) if h in full_actual and not np.isnan(full_actual[h])]
    if len(valid_h) >= 4:
        pv = [preds[h] for h in valid_h]
        av = [full_actual[h] for h in valid_h]
        corr = np.corrcoef(pv, av)[0, 1]
        direction = 'INVERTED' if corr < 0 else 'aligned'
        results.append((target, corr, direction, len(valid_h), 
                        actual_data[target].get('total_measurements', 0),
                        min(av), max(av), min(pv), max(pv)))

print(f"{'AP':<20} | {'Corr':>6} | {'Direction':>10} | {'Hours':>5} | {'Samples':>7} | {'Actual Range':>14} | {'Pred Range':>14}")
print("=" * 90)
for r in results:
    print(f"{r[0]:<20} | {r[1]:>6.3f} | {r[2]:>10} | {r[3]:>5d} | {r[4]:>7d} | [{r[5]:>6.1f}, {r[6]:>5.1f}] | [{r[7]:>6.1f}, {r[8]:>5.1f}]")

inverted = [r for r in results if r[1] < 0]
aligned = [r for r in results if r[1] >= 0]
print(f"\nSummary: {len(inverted)} inverted, {len(aligned)} aligned out of {len(results)}")
if inverted:
    print(f"Inverted APs: {[r[0] for r in inverted]}")
