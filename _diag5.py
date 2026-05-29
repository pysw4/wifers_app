"""Check if the interpolated actual values could cause inverted-looking chart."""
import json

with open('precomputed/actual_signal_averages.json') as f:
    data = json.load(f)

# Pick ap-llet39 (lots of data)
ap = data.get('ap-llet39', {})
hourly = ap.get('hourly', {})
print(f"AP: ap-llet39")
print(f"Total measurements: {ap.get('total_measurements', 0)}")
print(f"Raw hourly data (only hours with actual measurements):")
for h in sorted(hourly.keys(), key=int):
    print(f"  h{h}: mean={hourly[h]['actual_mean']} dBm, samples={hourly[h]['samples']}")

# Now simulate what the backend does: interpolate to fill 0..23
actual_hours = sorted([int(k) for k in hourly.keys()])
print(f"\nActual hours available: {actual_hours}")

# Simulate interpolation
full_actual = {}
if len(actual_hours) >= 2:
    for h in range(24):
        if h in [int(k) for k in hourly.keys()]:
            full_actual[h] = hourly[str(h)]['actual_mean']
        else:
            before = [ah for ah in actual_hours if ah < h]
            after = [ah for ah in actual_hours if ah > h]
            if before and after:
                h_before = before[-1]
                h_after = after[0]
                v_before = hourly[str(h_before)]['actual_mean']
                v_after = hourly[str(h_after)]['actual_mean']
                ratio = (h - h_before) / (h_after - h_before)
                interpolated = v_before + (v_after - v_before) * ratio
                full_actual[h] = round(interpolated, 1)
            elif before and not after:
                full_actual[h] = hourly[str(before[-1])]['actual_mean']
            elif after and not before:
                full_actual[h] = hourly[str(after[0])]['actual_mean']

print(f"\nFull 24h interpolated actual values:")
for h in range(24):
    if h in full_actual:
        marker = " *" if h in [int(k) for k in hourly.keys()] else " i"
        print(f"  h{h:2d}: {full_actual[h]:>6.1f} dBm{marker}")
    else:
        print(f"  h{h:2d}: {'N/A':>6}")

print("\nNote: ' *' = actual measurement, ' i' = interpolated")
print("The green line on the chart uses these interpolated values.")
print("If interpolation creates unrealistic values, the green line may look 'inverted'.")
