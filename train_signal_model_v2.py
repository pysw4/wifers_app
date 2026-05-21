"""
Signal Strength Prediction Model Training v2
信号强度预测模型训练脚本 v2

使用更丰富的特征来预测 Wi-Fi 信号强度 (dBm)：
  - client_count: AP 连接的客户端数量
  - cpu_utilization: AP 的 CPU 使用率
  - tx_power: AP 的发射功率 (dBm)，按频段匹配
  - utilization: AP 对应频段的信道利用率 (%)
  - hour: 小时 (0-23)
  - hour_sin / hour_cos: 小时的周期性编码
  - day_of_week: 星期几 (0-6)
  - is_weekend: 是否周末
  - is_business_hours: 是否上课/工作时间
  - month: 月份
  - day_of_month: 日
  - mem_usage: AP 的内存使用率 (%)

数据来源：
  - clientes_processed.csv: 客户端的实际信号强度测量值 (signal_db)
  - aps_processed.csv: AP 的运行指标
  两个表通过 AP 名称 (associated_device_name = swarm_name) 和日期关联

缓存机制：
  - cache/aps_agg_v2.csv: 按 (AP, date, hour) 聚合后的 AP 指标
  - cache/merged_v2.csv: clientes + aps_agg 关联后的数据
  如果缓存存在则跳过对应环节，加速后续训练
"""
import pandas as pd
import numpy as np
import json
import os
import joblib
from tqdm import tqdm
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

# =====================================================================
# 全局配置
# =====================================================================
RANDOM_SEED = 0
MODEL_DIR = "models"
CACHE_DIR = "cache"
CLIENTS_FILE = "clientes_processed.csv"
APS_FILE = "aps_processed.csv"
APS_AGG_CACHE = os.path.join(CACHE_DIR, "aps_agg_v2.csv")
MERGED_CACHE = os.path.join(CACHE_DIR, "merged_v2.csv")

os.makedirs(CACHE_DIR, exist_ok=True)

print("=" * 60)
print("Training v2 Signal Strength (dBm) Prediction Model")
print("Using features: client_count, cpu_utilization, tx_power, utilization,")
print("                 hour, hour_sin, hour_cos, day_of_week, is_weekend,")
print("                 is_business_hours, month, day_of_month, mem_usage")
print("=" * 60)


def extract_radio_metrics(radios_str, target_band):
    """
    从 radios JSON 中提取指定频段的指标。
    
    radios 格式: [{'band': 0/1, 'tx_power': ..., 'utilization': ..., ...}, ...]
    band=0 → 2.4GHz, band=1 → 5GHz
    
    返回:
        (tx_power, utilization) 或 (None, None)
    """
    if pd.isna(radios_str):
        return None, None
    try:
        radios = json.loads(radios_str.replace("'", '"'))
        target_band_int = 1 if target_band >= 5.0 else 0
        for radio in radios:
            if radio.get('band') == target_band_int:
                return (float(radio.get('tx_power', 0)), 
                        float(radio.get('utilization', 0)))
        # 没找到匹配频段，返回第一个可用的
        if radios:
            return (float(radios[0].get('tx_power', 0)),
                    float(radios[0].get('utilization', 0)))
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    return None, None


# =====================================================================
# 第一步：加载/构建 AP 聚合数据
# =====================================================================
if os.path.exists(APS_AGG_CACHE):
    print(f"\n[1] Loading cached AP aggregation from {APS_AGG_CACHE}...")
    aps_agg = pd.read_csv(APS_AGG_CACHE)
    print(f"  Loaded {len(aps_agg)} AP+date+hour combinations")
else:
    print("\n[1] Building AP aggregation from aps_processed.csv...")
    
    ap_cols = ['swarm_name', 'client_count', 'cpu_utilization', 'mem_usage', 
               'date', 'hour', 'radios']
    aps_df = pd.read_csv(APS_FILE, usecols=ap_cols)
    print(f"  Loaded {len(aps_df)} AP metric rows")
    
    # 提取 radio 指标（带进度条）
    print("  Extracting radio metrics from AP radios...")
    tx_powers = []
    utilizations = []
    for _, row in tqdm(aps_df.iterrows(), total=len(aps_df), desc="  Parsing radios"):
        tx, util = extract_radio_metrics(row['radios'], 5.0)
        tx_powers.append(tx)
        utilizations.append(util)
    
    aps_df['tx_power'] = tx_powers
    aps_df['utilization'] = utilizations
    aps_df = aps_df.drop(columns=['radios'])
    
    # 聚合
    print("  Aggregating AP metrics by AP+date+hour...")
    aps_agg = aps_df.groupby(['swarm_name', 'date', 'hour'], as_index=False).agg({
        'client_count': 'mean',
        'cpu_utilization': 'mean',
        'mem_usage': 'mean',
        'tx_power': 'mean',
        'utilization': 'mean',
    })
    print(f"  Aggregated to {len(aps_agg)} AP+date+hour combinations")
    
    # 保存缓存
    aps_agg.to_csv(APS_AGG_CACHE, index=False)
    print(f"  Cached to {APS_AGG_CACHE}")

# =====================================================================
# 第二步：加载客户端信号数据
# =====================================================================
print("\n[2] Loading client signal data from clientes_processed.csv...")

cli_cols = ['associated_device_name', 'band', 'signal_db', 'hour', 'date']
cli = pd.read_csv(CLIENTS_FILE, usecols=cli_cols, nrows=500000)
print(f"  Loaded {len(cli)} client samples")

cli = cli.dropna(subset=['signal_db', 'associated_device_name', 'band', 'hour', 'date'])
print(f"  After dropping NA: {len(cli)} samples")

# =====================================================================
# 第三步：关联两个表
# =====================================================================
if os.path.exists(MERGED_CACHE):
    print(f"\n[3] Loading cached merged data from {MERGED_CACHE}...")
    merged = pd.read_csv(MERGED_CACHE)
    print(f"  Loaded {len(merged)} merged samples")
else:
    print("\n[3] Merging client data with AP metrics...")
    
    merged = cli.merge(
        aps_agg,
        left_on=['associated_device_name', 'date', 'hour'],
        right_on=['swarm_name', 'date', 'hour'],
        how='inner',
    )
    print(f"  Merged samples: {len(merged)}")
    
    if len(merged) == 0:
        print("\n⚠️  WARNING: No matching records found!")
        print("   Sample AP names from clientes:", cli['associated_device_name'].unique()[:10])
        print("   Sample AP names from aps:", aps_agg['swarm_name'].unique()[:10])
        exit(1)
    
    # 保存缓存
    merged.to_csv(MERGED_CACHE, index=False)
    print(f"  Cached to {MERGED_CACHE}")

# =====================================================================
# 第四步：特征工程
# =====================================================================
print("\n[4] Feature engineering...")

# 构建 AP radios 索引字典用于快速查找
# 格式: {(ap_name, date, hour) -> radios_str}
print("  Building AP radios lookup index...")
aps_radios = pd.read_csv(APS_FILE, usecols=['swarm_name', 'date', 'hour', 'radios'])
aps_radios['radios'] = aps_radios['radios'].fillna('[]')
radios_index = {}
for _, row in tqdm(aps_radios.iterrows(), total=len(aps_radios), desc="  Indexing"):
    key = (row['swarm_name'], row['date'], row['hour'])
    if key not in radios_index:
        radios_index[key] = row['radios']

# 根据 clientes 的 band 值重新提取正确的 tx_power 和 utilization
print("  Re-extracting tx_power and utilization with correct band matching...")
corrected_tx = []
corrected_util = []
for _, row in tqdm(merged.iterrows(), total=len(merged), desc="  Matching bands"):
    key = (row['associated_device_name'], row['date'], row['hour'])
    radios_str = radios_index.get(key)
    if radios_str:
        tx, util = extract_radio_metrics(radios_str, row['band'])
        corrected_tx.append(tx if tx is not None else row['tx_power'])
        corrected_util.append(util if util is not None else row['utilization'])
    else:
        corrected_tx.append(row['tx_power'])
        corrected_util.append(row['utilization'])

merged['tx_power'] = corrected_tx
merged['utilization'] = corrected_util

# 日期编码
print("  Encoding temporal features...")
merged['date_parsed'] = pd.to_datetime(merged['date'], errors='coerce')
merged['day_of_week'] = merged['date_parsed'].dt.dayofweek
merged['month'] = merged['date_parsed'].dt.month
merged['day_of_month'] = merged['date_parsed'].dt.day

# 周期性编码小时
merged['hour_rad'] = merged['hour'] * 2 * np.pi / 24
merged['hour_sin'] = np.sin(merged['hour_rad'])
merged['hour_cos'] = np.cos(merged['hour_rad'])

# 时段特征
merged['is_weekend'] = (merged['day_of_week'] >= 5).astype(int)
merged['is_business_hours'] = ((merged['hour'] >= 8) & (merged['hour'] <= 20)).astype(int)

# 最终特征集
feature_cols = [
    'client_count', 'cpu_utilization', 'tx_power', 'utilization',
    'hour', 'hour_sin', 'hour_cos', 
    'day_of_week', 'is_weekend', 'is_business_hours',
    'month', 'day_of_month', 'mem_usage'
]

# 删除缺失值和无穷值
merged_clean = merged.dropna(subset=feature_cols + ['signal_db'])
# 替换无穷值为 NaN 再删除
merged_clean = merged_clean.replace([np.inf, -np.inf], np.nan).dropna(subset=feature_cols)
print(f"  Samples after cleaning: {len(merged_clean)}")

if len(merged_clean) < 100:
    print("\n⚠️  WARNING: Too few samples after cleaning!")
    exit(1)

X = merged_clean[feature_cols].copy()
y = merged_clean['signal_db'].values

print(f"  Feature columns ({len(feature_cols)}): {feature_cols}")
print(f"  Samples: {len(X)}")
print(f"  Signal dB range: {y.min():.0f} to {y.max():.0f} dBm")
print(f"  Signal dB mean: {y.mean():.1f} dBm")

print("\n  Feature statistics:")
for col in feature_cols:
    print(f"    {col}: mean={X[col].mean():.2f}, std={X[col].std():.2f}, "
          f"min={X[col].min():.2f}, max={X[col].max():.2f}")

# =====================================================================
# 第五步：训练随机森林回归模型
# =====================================================================
print("\n[5] Training Random Forest model...")
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=RANDOM_SEED
)

model = RandomForestRegressor(
    n_estimators=150,
    max_depth=20,
    min_samples_leaf=5,
    random_state=RANDOM_SEED,
    n_jobs=-1,
    verbose=1  # 显示训练进度
)

model.fit(X_train, y_train)
print(f"  Model trained on {len(X_train)} samples")

# =====================================================================
# 第六步：模型评估
# =====================================================================
y_pred = model.predict(X_test)
mae = mean_absolute_error(y_test, y_pred)
rmse = np.sqrt(mean_squared_error(y_test, y_pred))
r2 = r2_score(y_test, y_pred)

print(f"\n[6] Evaluation Results:")
print(f"  MAE:  {mae:.2f} dBm")
print(f"  RMSE: {rmse:.2f} dBm")
print(f"  R²:   {r2:.3f}")

# =====================================================================
# 第七步：特征重要性分析
# =====================================================================
print("\n[7] Feature Importances:")
importances = pd.DataFrame({
    'feature': feature_cols,
    'importance': model.feature_importances_
}).sort_values('importance', ascending=False)
for i, (_, row) in enumerate(importances.iterrows()):
    print(f"  {i+1}. {row['feature']}: {row['importance']:.3f}")

# =====================================================================
# 第八步：示例预测
# =====================================================================
print("\n[8] Example predictions:")
test_samples = X_test.head(5)
preds = model.predict(test_samples)
for i, (_, sample) in enumerate(test_samples.iterrows()):
    print(f"  clients={int(sample['client_count'])}, cpu={sample['cpu_utilization']:.1f}%, "
          f"tx={sample['tx_power']:.0f}dBm, util={sample['utilization']:.1f}%, "
          f"hour={int(sample['hour'])}, weekend={int(sample['is_weekend'])}, "
          f"biz={int(sample['is_business_hours'])}, mem={sample['mem_usage']:.1f}%")
    print(f"    → Predicted: {preds[i]:.1f} dBm (Actual: {y_test[i]:.1f} dBm)")

# =====================================================================
# 第九步：保存模型
# =====================================================================
os.makedirs(MODEL_DIR, exist_ok=True)

model_path = os.path.join(MODEL_DIR, 'signal_strength_model.joblib')
joblib.dump(model, model_path)
print(f"\n[9] Model saved to {model_path}")

meta = {
    'feature_names': feature_cols,
    'model_type': 'RandomForestRegressor',
    'target': 'signal_db',
    'target_unit': 'dBm',
    'signal_db_range': [float(y.min()), float(y.max())],
    'mae': round(mae, 2),
    'rmse': round(rmse, 2),
    'r2': round(r2, 3),
    'n_samples': len(X),
    'n_train_samples': len(X_train),
    'version': 'v2',
    'description': 'Trained with client_count, cpu_utilization, tx_power, utilization, '
                   'hour, hour_sin, hour_cos, day_of_week, is_weekend, '
                   'is_business_hours, month, day_of_month, mem_usage',
}
meta_path = os.path.join(MODEL_DIR, 'signal_strength_meta.joblib')
joblib.dump(meta, meta_path)
print(f"  Metadata saved to {meta_path}")

print("\n" + "=" * 60)
print("Training complete!")
print("=" * 60)
