#!/usr/bin/env python3
"""
Precompute Predictor5_0 AP hourly profiles.

Reads meme_clean.parquet and computes per-AP per-hour average numeric features.
Saves to precomputed/predictor5_ap_profiles.json (~1-2 MB) for fast loading
at inference time in main.py.

Usage:  python3 precompute_predictor5_profiles.py
"""

import os, json, warnings
import pandas as pd
import numpy as np
from pathlib import Path

warnings.filterwarnings('ignore')

BASE_DIR = Path(__file__).resolve().parent
PARQUET_PATH = BASE_DIR / "meme_clean.parquet"
OUTPUT_PATH = BASE_DIR / "precomputed" / "predictor5_ap_profiles.json"

NUMERIC_FEATURES = [
    'signal_score', 'signal_strength', 'signal_db', 'snr',
    'cpu_utilization', 'mem_usage', 'client_count', 'health',
    'speed', 'maxspeed'
]

HOUR_FEATURES = ['hour', 'day_of_week'] + NUMERIC_FEATURES


def main():
    print(f"[1/3] 读取 parquet: {PARQUET_PATH}")
    df = pd.read_parquet(str(PARQUET_PATH), columns=['associated_device_name', 'timestamp'] + NUMERIC_FEATURES)
    print(f"      Shape: {df.shape}")

    # 清洗 AP 名称
    df['associated_device_name'] = df['associated_device_name'].str.strip()

    # 丢弃数值列空值
    df = df.dropna(subset=NUMERIC_FEATURES).copy()
    print(f"      去空后: {df.shape}")

    # 解析时间，提取 hour 和 day_of_week
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['hour'] = df['timestamp'].dt.hour
    df['day_of_week'] = df['timestamp'].dt.dayofweek

    print(f"[2/3] 聚合: 每个 AP × 每小时 × 每天均值...")

    # 按 (ap_name, day_of_week, hour) 分组取均值 → 保留昼夜/周末模式
    grouped = df.groupby(['associated_device_name', 'day_of_week', 'hour'])[NUMERIC_FEATURES].mean()
    print(f"      分组 Shape: {grouped.shape}")

    # 转换为嵌套 dict: {ap_name: {day_of_week: {hour: {feat: val, ...}, ...}, ...}}
    profiles = {}
    for (ap_name, dow, hour), row in grouped.iterrows():
        ap_name_str = str(ap_name)
        dow_int = int(dow)
        hour_int = int(hour)
        if ap_name_str not in profiles:
            profiles[ap_name_str] = {}
        if dow_int not in profiles[ap_name_str]:
            profiles[ap_name_str][dow_int] = {}
        profiles[ap_name_str][dow_int][hour_int] = {
            feat: float(round(row[feat], 6))
            for feat in NUMERIC_FEATURES
        }

    # 为缺失的 hour 补默认值（取全局中值）
    print(f"      填充缺失 slot...")
    global_medians = df[NUMERIC_FEATURES].median().to_dict()
    for ap_name in list(profiles.keys()):
        for dow in range(7):
            if dow not in profiles[ap_name]:
                profiles[ap_name][dow] = {}
            for h in range(24):
                if h not in profiles[ap_name][dow]:
                    profiles[ap_name][dow][h] = {
                        feat: float(round(global_medians[feat], 6))
                        for feat in NUMERIC_FEATURES
                    }

    # 保存
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(profiles, f)

    n_aps = len(profiles)
    total_slots = sum(
        1 for ap_data in profiles.values()
        for dow_data in ap_data.values()
        for _ in dow_data
    )
    file_size_mb = os.path.getsize(OUTPUT_PATH) / 1024 / 1024
    print(f"[3/3] ✅ 保存完成: {OUTPUT_PATH}")
    print(f"      AP 数: {n_aps}")
    print(f"      Total slots (AP×dow×hour): {total_slots}")
    print(f"      文件大小: {file_size_mb:.2f} MB")

    # 也保存全局中值和数值范围（用于 scaler fallback）
    scaler_fallback = {
        'medians': {feat: float(round(global_medians[feat], 6)) for feat in NUMERIC_FEATURES},
        'mins': {feat: float(round(float(df[feat].min()), 6)) for feat in NUMERIC_FEATURES},
        'maxs': {feat: float(round(float(df[feat].max()), 6)) for feat in NUMERIC_FEATURES},
    }
    scaler_path = BASE_DIR / "precomputed" / "predictor5_scaler_fallback.json"
    with open(scaler_path, 'w') as f:
        json.dump(scaler_fallback, f)
    print(f"      Scaler fallback 保存: {scaler_path}")


if __name__ == '__main__':
    main()
