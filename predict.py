# -*- coding: utf-8 -*-
"""
Model Prediction Script
Load the trained best model and make predictions on new data
"""

import os
import joblib
import pandas as pd
import numpy as np
import ast

# Load the best model
model_dir = "models"
model_files = [f for f in os.listdir(model_dir) if f.endswith('.joblib')]

if not model_files:
    print("No model files found in models/ directory")
    exit(1)

model_path = os.path.join(model_dir, model_files[0])
best_model = joblib.load(model_path)
model_name = model_files[0].replace('.joblib', '').replace('_', ' ').title()

print(f"Loaded best model: {model_name}")
print(f"Model path: {model_path}")
print("=" * 50)

# Load the original data to demonstrate predictions
try:
    d_aps = pd.read_csv("aps_processed.csv", engine="python", on_bad_lines="error")
    
    # Preprocess data (same as in training)
    d_aps.drop(columns=["timestamp", "swarm_name", "firmware_version", "macaddr", "date"], inplace=True)
    d_aps = d_aps.sample(n=1000, random_state=0)
    
    # Separate target and features
    y_status = d_aps["status"]
    features = d_aps.drop(columns=["status"], inplace=False)
    
    # Remove 'radios' column to match training data
    if 'radios' in features.columns:
        features = features.drop(columns=['radios'])
    
    print("\nData loaded and preprocessed")
    print(f"Number of samples: {len(features)}")
    print(f"Number of features: {features.shape[1]}")
    print(f"Feature names: {list(features.columns)}")
    print("\n" + "=" * 50)
    
    # Make predictions on first 10 samples
    print("\nMaking predictions on first 10 samples:")
    print("-" * 50)
    
    X_sample = features.iloc[:10]
    predictions = best_model.predict(X_sample)
    probabilities = None
    
    # Try to get prediction probabilities if model supports it
    try:
        probabilities = best_model.predict_proba(X_sample)
    except AttributeError:
        pass
    
    # Display results
    for idx, (pred, true_label) in enumerate(zip(predictions, y_status.iloc[:10])):
        match = "✓" if pred == true_label else "✗"
        print(f"Sample {idx+1}: Predicted={pred}, True={true_label} {match}")
    
    print("\n" + "=" * 50)
    print("\nAccuracy on first 10 samples: {:.2%}".format(
        np.mean(predictions == y_status.iloc[:10].values)
    ))
    
    # Overall accuracy on all samples
    all_predictions = best_model.predict(features)
    overall_accuracy = np.mean(all_predictions == y_status.values)
    print(f"Overall accuracy on all {len(features)} samples: {overall_accuracy:.2%}")
    
    # Save predictions to CSV
    results_df = pd.DataFrame({
        'True_Status': y_status.values,
        'Predicted_Status': all_predictions,
        'Correct': all_predictions == y_status.values
    })
    
    output_path = "results/predictions.csv"
    results_df.to_csv(output_path, index=False)
    print(f"\nPredictions saved to {output_path}")
    
except Exception as e:
    print(f"Error during prediction: {e}")
    import traceback
    traceback.print_exc()
