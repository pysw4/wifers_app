#!/usr/bin/env python3
"""
Precompute Predictor5_0 AP hourly profiles (v2 — per-feature averages).

Per-feature: for each (AP, dow, hour), compute mean of that feature
from whatever rows have it available (instead of requiring all 10 features non-NaN).

Fills missing: neighbor hours → global median.
Saves to precomputed/predictor5_ap_profiles.json for inference in main.py.

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


def _fill_missing_with_neighbors(profiles_raw: dict, global_medians: dict) -> dict:
    """Fill missing AP×dow×hour slots:
    1. Neighbor hours average (same AP, same dow)
    2. Global median fallback
    """
    filled = {}
    for ap_name, dow_data in profiles_raw.items():
        filled[ap_name] = {}
        for dow in range(7):
            filled[ap_name][dow] = {}
            safe = dow_data.get(dow, {})
            for h in range(24):
                if h in safe:
                    filled[ap_name][dow][h] = safe[h]
                else:
                    neighbors = []
                    for nh in [(h - 1) % 24, (h + 1) % 24]:
                        if nh in safe:
                            neighbors.append(safe[nh])
                    if len(neighbors) == 2:
                        merged = {}
                        for feat in NUMERIC_FEATURES:
                            v0 = neighbors[0].get(feat, global_medians[feat])
                            v1 = neighbors[1].get(feat, global_medians[feat])
                            merged[feat] = round((v0 + v1) / 2, 6)
                        filled[ap_name][dow][h] = merged
                    elif len(neighbors) == 1:
                        filled[ap_name][dow][h] = neighbors[0]
                    else:
                        filled[ap_name][dow][h] = {
                            feat: float(round(global_medians[feat], 6))
                            for feat in NUMERIC_FEATURES
                        }
    return filled


def main():
    print(f"[1/3] 读取 parquet: {PARQUET_PATH}")
    df = pd.read_parquet(str(PARQUET_PATH),
                         columns=['associated_device_name', 'timestamp'] + NUMERIC_FEATURES)
    print(f"      Shape: {df.shape}")

    # 清洗
    df['associated_device_name'] = df['associated_device_name'].str.strip()
    df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
    df['hour'] = df['timestamp'].dt.hour
    df['day_of_week'] = df['timestamp'].dt.dayofweek

    # 全局中值（所有可用数据）
    global_medians = {}
    for feat in NUMERIC_FEATURES:
        global_medians[feat] = float(df[feat].median())
    print(f"      全局中值: signal_score={global_medians['signal_score']:.4f}, "
          f"snr={global_medians['snr']:.1f}, cpu={global_medians['cpu_utilization']:.5f}")

    print(f"[2/3] 逐特征聚合: 每个 AP × 每天 × 每小时均值...")

    # 对每个特征独立计算分组均值
    # 只 dropna 该特征，不要求全部特征
    profiles_raw = {}
    for feat in tqdm_me(NUMERIC_FEATURES, desc='  特征'):
        nona = df.dropna(subset=[feat]).copy()
        if len(nona) == 0:
            continue
        grouped = nona.groupby(['associated_device_name', 'day_of_week', 'hour'])[feat].mean()
        for (ap_name, dow, hour), val in grouped.items():
            ap_str, d_int, h_int = str(ap_name), int(dow), int(hour)
            if ap_str not in profiles_raw:
                profiles_raw[ap_str] = {}
            if d_int not in profiles_raw[ap_str]:
                profiles_raw[ap_str][d_int] = {}
            if h_int not in profiles_raw[ap_str][d_int]:
                profiles_raw[ap_str][d_int][h_int] = {}
            profiles_raw[ap_str][d_int][h_int][feat] = round(float(val), 6)

    print(f"      原始 slot 数: {sum(len(d2) for apd in profiles_raw.values() for d in apd.values() for d2 in [d.values()])}")

    # 填充缺失
    print(f"      填充缺失...")
    profiles = _fill_missing_with_neighbors(profiles_raw, global_medians)

    # 统计
    n_aps = len(profiles)
    total_slots = n_aps * 7 * 24
    real_slots = sum(1 for apd in profiles_raw.values()
                     for d in range(7) if d in apd
                     for h in range(24) if h in apd[d])

    neighbor_slots = 0
    median_slots = 0
    for ap_name, apd in profiles.items():
        for d in range(7):
            for h in range(24):
                if not (ap_name in profiles_raw and d in profiles_raw[ap_name] and h in profiles_raw[ap_name][d]):
                    ok = False
                    if ap_name in profiles_raw and d in profiles_raw[ap_name]:
                        for nh in [(h - 1) % 24, (h + 1) % 24]:
                            if nh in profiles_raw[ap_name][d]:
                                ok = True
                                break
                    if ok:
                        neighbor_slots += 1
                    else:
                        median_slots += 1

    print(f"      Slot 来源: {real_slots}/{total_slots} 真实数据 "
          f"({real_slots/total_slots*100:.1f}%), "
          f"{neighbor_slots}/{total_slots} 相邻 ({neighbor_slots/total_slots*100:.1f}%), "
          f"{median_slots}/{total_slots} 中值 ({median_slots/total_slots*100:.1f}%)")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    # 紧凑格式: {ap_name: [v0_0, v0_1, ..., v167_9]} flat array of 168*10=1680 floats
    # 消除特征名重复 → 文件缩小 10x
    print(f"      转换紧凑格式 (flat arrays)...")
    flat_profiles = {}
    for ap_name in profiles:
        arr = []
        for dow in range(7):
            for h in range(24):
                slot = profiles[ap_name][dow][h]
                for feat in NUMERIC_FEATURES:
                    val = slot.get(feat, global_medians[feat])
                    arr.append(round(float(val), 4))
        flat_profiles[ap_name] = arr

    with open(OUTPUT_PATH, 'w') as f:
        json.dump(flat_profiles, f, separators=(',', ':'))

    file_size_mb = os.path.getsize(OUTPUT_PATH) / 1024 / 1024
    print(f"[3/3] ✅ 保存完成: {OUTPUT_PATH}")
    print(f"      AP 数: {n_aps}")
    print(f"      文件大小: {file_size_mb:.2f} MB")

    scaler_path = BASE_DIR / "precomputed" / "predictor5_scaler_fallback.json"
    scaler_fallback = {
        'medians': global_medians,
        'mins': {feat: float(df[feat].min()) for feat in NUMERIC_FEATURES},
        'maxs': {feat: float(df[feat].max()) for feat in NUMERIC_FEATURES},
    }
    with open(scaler_path, 'w') as f:
        json.dump(scaler_fallback, f)
    print(f"      Scaler fallback 保存: {scaler_path}")


try:
    from tqdm import tqdm as tqdm_me
except ImportError:
    def tqdm_me(iterable, **kwargs):
        return iterable


if __name__ == '__main__':
    main()
