"""Compare predicted vs actual trend shapes for ap-llet39 with correct building."""
import json, joblib, pandas as pd, numpy as np

model = joblib.load('models/signal_strength_model.joblib')
building_encoder = joblib.load('models/building_encoder.joblib')
ap_name_encoder = joblib.load('models/ap_name_encoder.joblib')
with open('precomputed/actual_signal_averages.json') as f: actual_data = json.load(f)

target = "ap-llet39"
actual = actual_data.get(target, {}).get('hourly', {})

# Find building from geojson
with open('geolocation_package/data/aps_geolocalizados_wgs84.geojson') as f:
    geojson = json.load(f)

for feat in geojson['features']:
    props = feat['properties']
    name = str(props.get('USER_NOM_A', '')).strip().lower()
    if name == target:
        building = props.get('USER_EDIFI', props.get('Nom_Edific', 'Unknown'))
        floor = float(props.get('Num_Planta', 0) or 0)
        bc = int(building_encoder.transform([building])[0])
        
        # Try with ap_name_code
        try:
            ap_code = int(ap_name_encoder.transform([target])[0])
        except:
            ap_code = 0
        
        print(f"AP: {target}")
        print(f"Building: {building} (code: {bc})")
        print(f"Floor: {floor}")
        print(f"AP name code: {ap_code}")
        print()
        
        # Predict with ap_name_code=0 (like trend endpoint does)
        rows0 = []
        for h in range(24):
            rows0.append({'building_code': bc, 'floor': floor, 'hour': float(h), 'band': 5.0,
                         'day_of_week': 2.0, 'is_weekend': 0.0, 'day_of_month': 15.0, 'month': 4.0, 'ap_name_code': 0})
        preds0 = model.predict(pd.DataFrame(rows0))
        
        # Predict with actual ap_name_code
        rows1 = []
        for h in range(24):
            rows1.append({'building_code': bc, 'floor': floor, 'hour': float(h), 'band': 5.0,
                         'day_of_week': 2.0, 'is_weekend': 0.0, 'day_of_month': 15.0, 'month': 4.0, 'ap_name_code': ap_code})
        preds1 = model.predict(pd.DataFrame(rows1))
        
        # Build full 24h actual (interpolated)
        actual_hours = sorted(actual.keys())
        full_actual = {}
        if len(actual_hours) >= 2:
            for h in range(24):
                if h in actual:
                    full_actual[h] = actual[h]['actual_mean']
                else:
                    before = [ah for ah in actual_hours if ah < h]
                    after = [ah for ah in actual_hours if ah > h]
                    if before and after:
                        hb, ha = before[-1], after[0]
                        vb, va = actual[hb]['actual_mean'], actual[ha]['actual_mean']
                        ratio = (h - hb) / (ha - hb)
                        full_actual[h] = round(vb + (va - vb) * ratio, 1)
                    elif before:
                        full_actual[h] = actual[before[-1]]['actual_mean']
                    elif after:
                        full_actual[h] = actual[after[0]]['actual_mean']
        
        print(f"{'Hour':>4} | {'Pred(ap=0)':>10} | {'Pred(real)':>10} | {'Actual':>8} | {'Samples':>7}")
        print("-" * 55)
        for h in range(24):
            a = actual.get(h, {})
            act_str = f"{full_actual.get(h, 'N/A'):>7.1f}" if h in full_actual else "    N/A"
            sam_str = f"{a.get('samples', 0):>5d}" if h in actual else "    0"
            print(f"{h:4d} | {preds0[h]:>8.1f}  | {preds1[h]:>8.1f}  | {act_str} | {sam_str}")
        
        # Check correlation
        valid_h = [h for h in range(24) if h in full_actual and not np.isnan(full_actual[h])]
        if valid_h:
            pred_vals = [preds0[h] for h in valid_h]
            actual_vals = [full_actual[h] for h in valid_h]
            corr = np.corrcoef(pred_vals, actual_vals)[0, 1]
            print(f"\nCorrelation (pred vs actual): {corr:.3f}")
            if corr < 0:
                print("NEGATIVE correlation - trends ARE inverted!")
                print("This means the model predicts the OPPOSITE trend of actual data.")
            else:
                print("POSITIVE correlation - trends are aligned.")
        break
