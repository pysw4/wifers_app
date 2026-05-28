#!/usr/bin/env python3
"""
Precompute actual signal averages from clientes_processed.csv.

Reads the CSV once, groups by (associated_device_name, hour),
calculates mean signal_db and sample count, and outputs a lightweight JSON
that the backend can load at startup instead of reading the full CSV.

Usage:
    python precompute_actual_averages.py

Output:
    precomputed/actual_signal_averages.json
"""

import json
import os
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "clientes_processed.csv"
OUTPUT_PATH = BASE_DIR / "precomputed" / "actual_signal_averages.json"


def main():
    if not CSV_PATH.exists():
        print(f"[ERROR] CSV not found: {CSV_PATH}")
        return

    print(f"[INFO] Reading {CSV_PATH}...")
    cli = pd.read_csv(CSV_PATH, nrows=500000)
    print(f"[INFO] Loaded {len(cli)} samples, {cli['associated_device_name'].nunique()} unique APs")

    result = {}
    for ap_name in cli['associated_device_name'].unique():
        ap_data = cli[cli['associated_device_name'] == ap_name]
        if len(ap_data) < 5:
            continue  # Skip APs with too few measurements

        hourly = ap_data.groupby('hour')['signal_db'].agg(['mean', 'count'])
        hourly_dict = {}
        for h, row in hourly.iterrows():
            hourly_dict[str(int(h))] = {
                "actual_mean": round(float(row['mean']), 1),
                "samples": int(row['count']),
            }

        result[ap_name.strip().lower()] = {
            "total_measurements": len(ap_data),
            "hourly": hourly_dict,
        }

    # Ensure output directory exists
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_PATH, 'w') as f:
        json.dump(result, f, indent=2)

    print(f"[INFO] Saved averages for {len(result)} APs to {OUTPUT_PATH}")
    print(f"[INFO] File size: {os.path.getsize(OUTPUT_PATH) / 1024:.1f} KB")


if __name__ == "__main__":
    main()
