# -*- coding: utf-8 -*-
"""
Model Prediction Script
Load the trained best model and make predictions on new data
"""

import os
import joblib
import pandas as pd
import numpy as np

# =====================================================================
# Step 1: Load the trained best model
# =====================================================================
model_dir = "models"
MODEL_FILE = "decision_tree.joblib"
model_path = os.path.join(model_dir, MODEL_FILE)

if not os.path.exists(model_path):
    print(f"Model file {model_path} not found!")
    model_files = [f for f in os.listdir(model_dir) if f.endswith('.joblib') and 'decision_tree' in f]
    if not model_files:
        print("No model files found in models/ directory")
        exit(1)
    model_path = os.path.join(model_dir, model_files[0])

best_model = joblib.load(model_path)
model_name = os.path.basename(model_path).replace('.joblib', '').replace('_', ' ').title()

print(f"Loaded best model: {model_name}")
print(f"Model path: {model_path}")
print("=" * 50)

# =====================================================================
# Step 2: Load and preprocess data for prediction demo
# =====================================================================
try:
    d_aps = pd.read_csv("aps_processed.csv", engine="python", on_bad_lines="error")
    
    # Drop columns not used during training
    d_aps.drop(columns=["timestamp", "swarm_name", "firmware_version", "macaddr", "date"], inplace=True)
    d_aps = d_aps.sample(n=1000, random_state=0)
    
    # Separate target variable (y_status) and features
    y_status = d_aps["status"]
    features = d_aps.drop(columns=["status"], inplace=False)
    
    # Remove 'radios' column to match training features
    if 'radios' in features.columns:
        features = features.drop(columns=['radios'])
    
    print("\nData loaded and preprocessed")
    print(f"Number of samples: {len(features)}")
    print(f"Number of features: {features.shape[1]}")
    print(f"Feature names: {list(features.columns)}")
    print("\n" + "=" * 50)

    # =====================================================================
    # Step 3: Predict on first 10 samples and display results
    # =====================================================================
    print("\nMaking predictions on first 10 samples:")
    print("-" * 50)
    
    X_sample = features.iloc[:10]
    predictions = best_model.predict(X_sample)
    
    # Try to get prediction probabilities
    try:
        probabilities = best_model.predict_proba(X_sample)
    except AttributeError:
        probabilities = None
    
    # Convert: model outputs 0=Down, 1=Up → string labels
    pred_labels = ['Up' if p == 1 else 'Down' for p in predictions]
    
    # Display each prediction result, mark ✓/✗ for correctness
    for idx, (pred_label, true_label) in enumerate(zip(pred_labels, y_status.iloc[:10])):
        match = "✓" if pred_label == true_label else "✗"
        print(f"Sample {idx+1}: Predicted={pred_label}, True={true_label} {match}")
    
    # Calculate accuracy on first 10 samples
    true_labels_10 = y_status.iloc[:10].values
    acc_10 = np.mean([p == t for p, t in zip(pred_labels, true_labels_10)])
    print(f"\nAccuracy on first 10 samples: {acc_10:.2%}")
    
    print("\n" + "=" * 50)
    
    # =====================================================================
    # Step 4: Calculate overall accuracy on all samples
    # =====================================================================
    all_predictions_raw = best_model.predict(features)
    all_predictions_labels = ['Up' if p == 1 else 'Down' for p in all_predictions_raw]
    overall_accuracy = np.mean(all_predictions_labels == y_status.values)
    print(f"Overall accuracy on all {len(features)} samples: {overall_accuracy:.2%}")
    
    # =====================================================================
    # Step 5: Save predictions to CSV
    # =====================================================================
    results_df = pd.DataFrame({
        'True_Status': y_status.values,
        'Predicted_Status': all_predictions_labels,
        'Correct': all_predictions_labels == y_status.values
    })
    
    output_path = "results/predictions.csv"
    results_df.to_csv(output_path, index=False)
    print(f"\nPredictions saved to {output_path}")
    
except Exception as e:
    print(f"Error during prediction: {e}")
    import traceback
    traceback.print_exc()