"""Compare predicted vs actual trends for ap-llet39."""
import json, joblib, pandas as pd, numpy as np

model = joblib.load('models/signal_strength_model.joblib')
building_encoder = joblib.load('models/building_encoder.joblib')
with open('precomputed/actual_signal_averages.json') as f: actual_data = json.load(f)
with open('geolocation_package/data/aps_geolocalizados_wgs84.geojson') as f: geojson = json.load(f)

target = 'ap-llet39'
actual = actual_data.get(target, {}).get('hourly', {})

for feat in geojson['features']:
    name = str(feat['properties'].get('USER_NOM_A', '')).strip().lower()
    if name == target:
        building = feat['properties'].get('USER_EDIFI', 'Unknown')
        floor = float(feat['properties'].get('Num_Planta', 0) or 0)
        bc = int(building_encoder.transform([building])[0])
        
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
                        vb = actual[str(hb)]['actual_mean']
                        va = actual[str(ha)]['actual_mean']
                        ratio = (h - hb) / (ha - hb)
                        full_actual[h] = round(vb + (va - vb) * ratio, 1)
                    elif before:
                        full_actual[h] = actual[str(before[-1])]['actual_mean']
                    elif after:
                        full_actual[h] = actual[str(after[0])]['actual_mean']
        
        print(f"{'Hour':>4} | {'Predicted':>8} | {'Actual':>8} | {'Pred Dir':>8} | {'Actual Dir':>10}")
        print("-" * 50)
        for h in range(24):
            act_str = f"{full_actual.get(h, 0):>7.1f}" if h in full_actual else "    N/A"
            if h > 0 and h in full_actual and (h-1) in full_actual:
                pd_ = 'up' if preds[h] > preds[h-1] else 'down'
                ad_ = 'up' if full_actual[h] > full_actual[h-1] else 'down'
            else:
                pd_ = '-'
                ad_ = '-'
            print(f"{h:4d} | {preds[h]:>7.1f} | {act_str} | {pd_:>8} | {ad_:>10}")
        
        # Count same/opposite
        same = 0
        opposite = 0
        for h in range(1, 24):
            if h in full_actual and (h-1) in full_actual:
                pd_ = preds[h] > preds[h-1]
                ad_ = full_actual[h] > full_actual[h-1]
                if pd_ == ad_:
                    same += 1
                else:
                    opposite += 1
        print(f"\nSame direction: {same}, Opposite direction: {opposite}")
        break
