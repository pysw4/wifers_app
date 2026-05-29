"""Check if flipping actual values (multiply by -1) makes trends aligned."""
import json, joblib, pandas as pd, numpy as np

model = joblib.load('models/signal_strength_model.joblib')
building_encoder = joblib.load('models/building_encoder.joblib')
with open('precomputed/actual_signal_averages.json') as f: actual_data = json.load(f)
with open('geolocation_package/data/aps_geolocalizados_wgs84.geojson') as f: geojson = json.load(f)

ap_lookup = {}
for feat in geojson['features']:
    props = feat['properties']
    name = str(props.get('USER_NOM_A', '')).strip().lower()
    building = props.get('USER_EDIFI', props.get('Nom_Edific', 'Unknown'))
    floor = float(props.get('Num_Planta', 0) or 0)
    ap_lookup[name] = {'building': building, 'floor': floor}

aps_sorted = sorted(actual_data.keys(), key=lambda k: actual_data[k].get('total_measurements', 0), reverse=True)

print("Testing if flipping actual values (multiply by -1) makes trends aligned...")
print()
print(f"{'AP':<20} | {'Orig Corr':>9} | {'Flipped Corr':>12} | {'Better?':>7}")
print("=" * 55)

flip_better = 0
flip_worse = 0
total = 0

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
        orig_corr = np.corrcoef(pv, av)[0, 1]
        
        # Flip actual values
        av_flipped = [-v for v in av]
        flipped_corr = np.corrcoef(pv, av_flipped)[0, 1]
        
        better = abs(flipped_corr) > abs(orig_corr)
        if better:
            flip_better += 1
        else:
            flip_worse += 1
        total += 1
        
        better_str = 'YES' if better else 'no'
        print(f"{target:<20} | {orig_corr:>8.3f}  | {flipped_corr:>10.3f}  | {better_str:>7}")

print(f"\nSummary: Flipping helps {flip_better}/{total}, hurts {flip_worse}/{total}")
print()
print("If flipping (multiply by -1) makes correlation stronger for most APs,")
print("it means the actual values have the WRONG SIGN.")
print("If not, the model just isn't accurate for those APs.")
