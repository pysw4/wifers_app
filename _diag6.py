"""Compare predicted vs actual trend shapes for ap-llet39."""
import json, joblib, pandas as pd, numpy as np

model = joblib.load('models/signal_strength_model.joblib')
building_encoder = joblib.load('models/building_encoder.joblib')
with open('precomputed/actual_signal_averages.json') as f: actual_data = json.load(f)

# Use ap-llet39
target = "ap-llet39"
actual = actual_data.get(target, {}).get('hourly', {})

# We need to find the building for this AP
# From earlier diagnostic, ap-llet39 has hours 5-18 with data
# Let's try different building codes to see which gives reasonable predictions
# First, let's check what buildings exist
print("Available buildings (first 20):")
buildings = list(building_encoder.classes_)
for i, b in enumerate(buildings[:20]):
    print(f"  {i}: {b}")

# Try a few building codes and see which predictions match actual data best
print("\nTrying different building codes for ap-llet39...")
print("Actual data for ap-llet39:")
for h_str in sorted(actual.keys(), key=int):
    print(f"  h{h_str}: {actual[h_str]['actual_mean']} dBm ({actual[h_str]['samples']} samples)")

# The actual values range from -76.1 to -52.0
# Let's see what predictions look like with different building codes
for bc in range(min(5, len(buildings))):
    rows = []
    for h in range(24):
        rows.append({'building_code': bc, 'floor': 0.0, 'hour': float(h), 'band': 5.0,
                     'day_of_week': 2.0, 'is_weekend': 0.0, 'day_of_month': 15.0, 'month': 4.0, 'ap_name_code': 0})
    preds = model.predict(pd.DataFrame(rows))
    print(f"\nBuilding code {bc} ({buildings[bc]}):")
    print(f"  Predicted range: {preds.min():.1f} to {preds.max():.1f}")
    # Check if trend is similar to actual
    # Actual: h5=-61, h6=-58.3, h7=-55.3 (rising), h14=-76.1 (sharp drop)
    # Check if predicted also drops at h14
    print(f"  h5={preds[5]:.1f}, h6={preds[6]:.1f}, h7={preds[7]:.1f}, h14={preds[14]:.1f}")
