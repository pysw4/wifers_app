"""
AP Up/Down Classifier Retraining Script (v2 - 带周几和日期特征)
========================================
Improvements:
1. Uses all 2.66M data points (previously only 1000)
2. Uses F1 score (instead of accuracy) to select the best model, addressing class imbalance
3. Sets class_weight='balanced' to handle Down being only 5.63%
4. Compares multiple models and outputs confusion matrices
5. 新增特征: day_of_week, is_weekend, month, day_of_month — 考虑周几和日期，更精确
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
print("AP Up/Down Classifier Retraining v2")
print("Using all data points, handling class imbalance")
print("新增特征: day_of_week, is_weekend, month, day_of_month")
print("=" * 70)

# ============================================================
# 1. Load data
# ============================================================
print("\n[1/6] Loading data...")
t0 = time.time()

use_cols = ['client_count', 'cpu_utilization', 'mem_free', 'mem_total',
            'last_modified', 'hour', 'mem_usage', 'overloaded', 'status', 'date']
df = pd.read_csv('aps_processed.csv', usecols=use_cols, engine='python', on_bad_lines='skip')
print(f"  Loaded: {len(df)} rows, {time.time()-t0:.1f}s")

# ============================================================
# 2. Class distribution
# ============================================================
print("\n[2/6] Class distribution:")
counts = df['status'].value_counts()
print(f"  {counts.to_dict()}")
total = len(df)
down_pct = counts.get('Down', 0) / total * 100
print(f"  Down: {counts.get('Down', 0)} ({down_pct:.2f}%)")
print(f"  Up:   {counts.get('Up', 0)} ({100-down_pct:.2f}%)")

# ============================================================
# 3. Feature engineering & split
# ============================================================
print("\n[3/6] Preparing features...")

# 解析日期特征
print("  Parsing date features...")
df['date_parsed'] = pd.to_datetime(df['date'], errors='coerce')
df['day_of_week'] = df['date_parsed'].dt.dayofweek  # 0=Monday, 6=Sunday
df['is_weekend'] = (df['day_of_week'] >= 5).astype(int)
df['month'] = df['date_parsed'].dt.month
df['day_of_month'] = df['date_parsed'].dt.day

y = (df['status'] == 'Up').astype(int).values

feature_cols = [
    'client_count', 'cpu_utilization', 'mem_free', 'mem_total',
    'last_modified', 'hour', 'mem_usage', 'overloaded',
    'day_of_week', 'is_weekend', 'month', 'day_of_month'
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
# 4. Train multiple models
# ============================================================
print("\n[4/6] Training models (class_weight='balanced')...")

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
# 5. Result comparison
# ============================================================
print("\n" + "=" * 70)
print("[5/6] Model comparison (sorted by F1 Down score)")
print("=" * 70)

results_df = pd.DataFrame(results).sort_values('f1_down', ascending=False)
for _, row in results_df.iterrows():
    print(f"  {row['model']:<25s}  F1(Down)={row['f1_down']:.4f}  "
          f"Accuracy={row['accuracy']:.4f}  "
          f"Precision={row['precision_down']:.4f}  "
          f"Recall={row['recall_down']:.4f}")

results_path = os.path.join(RESULT_DIR, "retrain_results_v2.csv")
results_df.to_csv(results_path, index=False)
print(f"\n  Results saved to {results_path}")

# ============================================================
# 6. Save best model
# ============================================================
print("\n" + "=" * 70)
print(f"[6/6] Best model: {best_name} (F1 Down = {best_f1:.4f})")
print("=" * 70)

model_path = os.path.join(MODEL_DIR, 'decision_tree.joblib')
joblib.dump(best_model, model_path)
print(f"  Model saved to {model_path}")

if "Logistic" in best_name:
    scaler_path = os.path.join(MODEL_DIR, 'scaler.joblib')
    joblib.dump(scaler, scaler_path)
    print(f"  Scaler saved to {scaler_path}")

meta = {
    'model_type': type(best_model).__name__,
    'feature_names': feature_cols,
    'n_train_samples': len(X_train),
    'n_test_samples': len(X_test),
    'down_pct': round(down_pct, 2),
    'f1_down': round(float(best_f1), 4),
    'accuracy': round(float(results_df[results_df['model'] == best_name]['accuracy'].values[0]), 4),
    'training_date': time.strftime('%Y-%m-%d %H:%M:%S'),
    'class_balanced': True,
    'selection_metric': 'f1_down',
    'version': 'v2',
    'features_added': ['day_of_week', 'is_weekend', 'month', 'day_of_month'],
    'description': '考虑周几和日期的分类器，更精确',
}
meta_path = os.path.join(MODEL_DIR, 'decision_tree_meta.json')
with open(meta_path, 'w') as f:
    json.dump(meta, f, indent=2)
print(f"  Metadata saved to {meta_path}")

print("\n" + "=" * 70)
print("Retraining complete!")
print(f"Best model: {best_name}")
print(f"F1(Down): {best_f1:.4f}")
print(f"Features: {feature_cols}")
print("=" * 70)
