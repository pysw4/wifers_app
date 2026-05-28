"""
AP Up/Down Classifier Retraining Script (v3 - only inference-available features)
========================================
v3 improvements:
1. Removed client_count, cpu_utilization, mem_free, mem_total, last_modified, mem_usage, overloaded
   - These features are not available at inference time; previously filled with hardcoded defaults,
     leading to unreliable predictions
2. New features: building_code, floor, lat, lng, predicted_signal_db
   - building_code/floor/lat/lng obtained statically from GeoJSON
   - predicted_signal_db from signal strength model prediction (model cascade)
3. Retained features: hour, day_of_week, is_weekend, month, day_of_month
   - These features can be obtained from system time
"""

import pandas as pd
import numpy as np
import os
import joblib
import json
import time
import warnings
warnings.filterwarnings('ignore')

from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    accuracy_score, f1_score, precision_score, recall_score,
    confusion_matrix
)
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.tree import DecisionTreeClassifier
from sklearn.preprocessing import StandardScaler

RANDOM_SEED = 42
MODEL_DIR = "models"
RESULT_DIR = "results"
os.makedirs(MODEL_DIR, exist_ok=True)
os.makedirs(RESULT_DIR, exist_ok=True)

print("=" * 70)
print("AP Up/Down Classifier Retraining v3")
print("Only using features available at inference time")
print("Removed: client_count, cpu_utilization, mem_free, mem_total, last_modified, mem_usage, overloaded")
print("Added: building_code, floor, lat, lng, predicted_signal_db")
print("=" * 70)

# ============================================================
# 1. Load data
# ============================================================
print("\n[1/7] Loading data...")
t0 = time.time()

use_cols = ['swarm_name', 'client_count', 'cpu_utilization', 'mem_free', 'mem_total',
            'last_modified', 'hour', 'mem_usage', 'overloaded', 'status', 'date']
df = pd.read_csv('aps_processed.csv', usecols=use_cols, engine='python', on_bad_lines='skip')
print(f"  Loaded: {len(df)} rows, {time.time()-t0:.1f}s")

# ============================================================
# 2. Load GeoJSON and build AP lookup
# ============================================================
print("\n[2/7] Loading GeoJSON AP data...")

with open('geolocation_package/data/aps_geolocalizados_wgs84.geojson') as f:
    geojson = json.load(f)

# Build AP lookup: swarm_name -> {building, floor, lat, lng}
ap_lookup = {}
for feat in geojson['features']:
    props = feat['properties']
    name = props.get('USER_NOM_A', '')
    if not name:
        continue
    coords = feat['geometry']['coordinates']
    ap_lookup[name] = {
        'building': props.get('USER_EDIFI', 'Unknown'),
        'floor': float(props.get('Num_Planta', 0) or 0),
        'lat': float(coords[1]),
        'lng': float(coords[0]),
    }

print(f"  GeoJSON APs: {len(ap_lookup)}")

# ============================================================
# 3. Load signal strength model for cascade prediction
# ============================================================
print("\n[3/7] Loading signal strength model...")

signal_model = joblib.load('models/signal_strength_model.joblib')
signal_meta = joblib.load('models/signal_strength_meta.joblib')
building_encoder = joblib.load('models/building_encoder.joblib')

print(f"  Signal model loaded: {signal_meta['model_type']}")
print(f"  Buildings: {signal_meta['n_buildings']}")

# ============================================================
# 4. Merge AP data with GeoJSON and compute signal predictions
# ============================================================
print("\n[4/7] Merging AP data with GeoJSON and computing signal predictions...")

def encode_building(building_name):
    """Encode building name to integer."""
    if building_name in building_encoder.classes_:
        return int(building_encoder.transform([building_name])[0])
    # Fuzzy fallback
    for i, b in enumerate(building_encoder.classes_):
        if building_name.lower() in b.lower() or b.lower() in building_name.lower():
            return i
    return 0

# Merge: for each row in df, look up AP in GeoJSON
matched_count = 0
unmatched_count = 0

building_codes = []
floors = []
lats = []
lngs = []

for ap_name in df['swarm_name']:
    ap_name_clean = ap_name.strip()
    if ap_name_clean in ap_lookup:
        info = ap_lookup[ap_name_clean]
        building_codes.append(encode_building(info['building']))
        floors.append(info['floor'])
        lats.append(info['lat'])
        lngs.append(info['lng'])
        matched_count += 1
    else:
        building_codes.append(0)
        floors.append(0.0)
        lats.append(41.5)  # Default: center of UAB campus
        lngs.append(2.1)
        unmatched_count += 1

df['building_code'] = building_codes
df['floor'] = floors
df['lat'] = lats
df['lng'] = lngs

print(f"  Matched: {matched_count}, Unmatched (using defaults): {unmatched_count}")

# Parse date features
print("  Parsing date features...")
df['date_parsed'] = pd.to_datetime(df['date'], errors='coerce')
df['day_of_week'] = df['date_parsed'].dt.dayofweek
df['is_weekend'] = (df['day_of_week'] >= 5).astype(int)
df['month'] = df['date_parsed'].dt.month
df['day_of_month'] = df['date_parsed'].dt.day

# Predict signal strength for each row (cascade)
print("  Predicting signal strength for all rows (this may take a while)...")
t_signal = time.time()

# Build signal features
signal_features = pd.DataFrame({
    'building_code': df['building_code'],
    'floor': df['floor'],
    'hour': df['hour'],
    'band': 5.0,  # Default to 5GHz band
    'day_of_week': df['day_of_week'],
    'is_weekend': df['is_weekend'],
    'day_of_month': df['day_of_month'],
    'month': df['month'],
})

# Predict in batches to manage memory
batch_size = 50000
n_rows = len(signal_features)
predicted_signals = np.zeros(n_rows)

for start in range(0, n_rows, batch_size):
    end = min(start + batch_size, n_rows)
    batch = signal_features.iloc[start:end]
    predicted_signals[start:end] = signal_model.predict(batch)
    if (start // batch_size) % 5 == 0:
        print(f"    Predicted {end}/{n_rows} rows...")

df['predicted_signal_db'] = predicted_signals
print(f"  Signal prediction done: {time.time()-t_signal:.1f}s")

# ============================================================
# 5. Feature engineering & split
# ============================================================
print("\n[5/7] Preparing features...")

y = (df['status'] == 'Up').astype(int).values

# v3: only use features available at inference time
feature_cols = [
    'hour',           # System time
    'day_of_week',    # System time
    'is_weekend',     # System time
    'month',          # System time
    'day_of_month',   # System time
    'building_code',  # GeoJSON static data
    'floor',          # GeoJSON static data
    'lat',            # GeoJSON static data
    'lng',            # GeoJSON static data
    'predicted_signal_db',  # Signal strength model cascade prediction
]

X = df[feature_cols].copy()

# Ensure all feature columns are numeric
for col in feature_cols:
    X[col] = pd.to_numeric(X[col], errors='coerce')

null_count = X.isnull().sum().sum()
if null_count > 0:
    print(f"  Found {null_count} missing/non-numeric values, filling with median")
    X = X.fillna(X.median())

# Replace infinite values
X = X.replace([np.inf, -np.inf], np.nan).fillna(X.median())
print(f"  After cleaning: {len(X)} rows")

print(f"  Features ({len(feature_cols)}): {feature_cols}")
print(f"  Samples: {len(X)}")

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=RANDOM_SEED, stratify=y
)
print(f"  Training set: {len(X_train)}, Test set: {len(X_test)}")
print(f"  Training set Down ratio: {(1-y_train.mean())*100:.2f}%")
print(f"  Test set Down ratio: {(1-y_test.mean())*100:.2f}%")

scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train)
X_test_scaled = scaler.transform(X_test)

# ============================================================
# 6. Train multiple models
# ============================================================
print("\n[6/7] Training models (class_weight='balanced')...")

models = {
    "Logistic Regression": LogisticRegression(
        class_weight='balanced', max_iter=1000, random_state=RANDOM_SEED, n_jobs=-1
    ),
    "Decision Tree": DecisionTreeClassifier(
        class_weight='balanced', max_depth=20, random_state=RANDOM_SEED
    ),
    "Random Forest (100)": RandomForestClassifier(
        class_weight='balanced', n_estimators=100, max_depth=20,
        random_state=RANDOM_SEED, n_jobs=-1, verbose=0
    ),
    "Random Forest (200)": RandomForestClassifier(
        class_weight='balanced', n_estimators=200, max_depth=25,
        random_state=RANDOM_SEED, n_jobs=-1, verbose=0
    ),
}

results = []
best_model = None
best_f1 = -1
best_name = ""

for name, model in models.items():
    print(f"\n  >>> Training {name}...")
    t_start = time.time()

    if "Logistic" in name:
        model.fit(X_train_scaled, y_train)
        y_pred = model.predict(X_test_scaled)
    else:
        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)

    elapsed = time.time() - t_start

    acc = accuracy_score(y_test, y_pred)
    f1 = f1_score(y_test, y_pred, pos_label=0)
    prec = precision_score(y_test, y_pred, pos_label=0)
    rec = recall_score(y_test, y_pred, pos_label=0)
    cm = confusion_matrix(y_test, y_pred)

    print(f"    Time: {elapsed:.1f}s")
    print(f"    Accuracy: {acc:.4f}")
    print(f"    F1(Down): {f1:.4f}")
    print(f"    Precision(Down): {prec:.4f}")
    print(f"    Recall(Down): {rec:.4f}")
    print(f"    Confusion Matrix:")
    print(f"      [{cm[0][0]:>6} {cm[0][1]:>6}] Actual Down")
    print(f"      [{cm[1][0]:>6} {cm[1][1]:>6}] Actual Up")

    results.append({
        "model": name,
        "accuracy": round(acc, 4),
        "f1_down": round(f1, 4),
        "precision_down": round(prec, 4),
        "recall_down": round(rec, 4),
        "training_time_s": round(elapsed, 1),
    })

    if f1 > best_f1:
        best_f1 = f1
        best_model = model
        best_name = name

# ============================================================
# 7. Result comparison & save
# ============================================================
print("\n" + "=" * 70)
print("[7/7] Model comparison (sorted by F1 Down score)")
print("=" * 70)

results_df = pd.DataFrame(results).sort_values('f1_down', ascending=False)
for _, row in results_df.iterrows():
    print(f"  {row['model']:<25s}  F1(Down)={row['f1_down']:.4f}  "
          f"Accuracy={row['accuracy']:.4f}  "
          f"Precision={row['precision_down']:.4f}  "
          f"Recall={row['recall_down']:.4f}")

results_path = os.path.join(RESULT_DIR, "retrain_results_v3.csv")
results_df.to_csv(results_path, index=False)
print(f"\n  Results saved to {results_path}")

# Save best model
print("\n" + "=" * 70)
print(f"Best model: {best_name} (F1 Down = {best_f1:.4f})")
print("=" * 70)

model_path = os.path.join(MODEL_DIR, 'decision_tree_v3.joblib')
joblib.dump(best_model, model_path)
print(f"  Model saved to {model_path}")

if "Logistic" in best_name:
    scaler_path = os.path.join(MODEL_DIR, 'scaler_v3.joblib')
    joblib.dump(scaler, scaler_path)
    print(f"  Scaler saved to {scaler_path}")

meta = {
    'model_type': type(best_model).__name__,
    'feature_names': feature_cols,
    'n_train_samples': len(X_train),
    'n_test_samples': len(X_test),
    'down_pct': round((1 - y.mean()) * 100, 2),
    'f1_down': round(float(best_f1), 4),
    'accuracy': round(float(results_df[results_df['model'] == best_name]['accuracy'].values[0]), 4),
    'training_date': time.strftime('%Y-%m-%d %H:%M:%S'),
    'class_balanced': True,
    'selection_metric': 'f1_down',
    'version': 'v3',
    'features_removed': [
        'client_count', 'cpu_utilization', 'mem_free', 'mem_total',
        'last_modified', 'mem_usage', 'overloaded'
    ],
    'features_added': ['building_code', 'floor', 'lat', 'lng', 'predicted_signal_db'],
    'description': 'Classifier using only inference-available features, removed fake defaults',
}
meta_path = os.path.join(MODEL_DIR, 'decision_tree_meta_v3.json')
with open(meta_path, 'w') as f:
    json.dump(meta, f, indent=2)
print(f"  Metadata saved to {meta_path}")

print("\n" + "=" * 70)
print("Retraining v3 complete!")
print(f"Best model: {best_name}")
print(f"F1(Down): {best_f1:.4f}")
print(f"Features ({len(feature_cols)}): {feature_cols}")
print("=" * 70)
