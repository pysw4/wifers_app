"""
Signal Strength Prediction Model Training
信号强度预测模型训练脚本

训练一个回归模型，基于建筑物、楼层、时间段和频段特征
预测真实的 Wi-Fi 信号强度（dBm 单位）。

数据来源：
  - clientes_processed.csv: 客户端的实际信号强度测量值 (signal_db)
  - aps_geolocalizados_wgs84.geojson: AP 的地理位置信息（建筑物、楼层）
"""
import pandas as pd
import numpy as np
import json
import os
import joblib
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import LabelEncoder

# =====================================================================
# 全局配置 (Global Configuration)
# =====================================================================
RANDOM_SEED = 0          # 随机种子，确保实验可重复性
MODEL_DIR = "models"     # 模型保存目录
CLIENTS_FILE = "clientes_processed.csv"                              # 客户端测量数据文件
GEOJSON_FILE = "geolocation_package/data/aps_geolocalizados_wgs84.geojson"  # AP 地理信息文件

print("=" * 60)
print("Training REAL Signal Strength (dBm) Prediction Model")
print("=" * 60)

# =====================================================================
# 第一步：从 GeoJSON 加载 AP 的建筑物/楼层映射
# Step 1: Load AP building/floor mapping from GeoJSON
# - 遍历 GeoJSON 中的所有 feature
# - 提取每个 AP 的名称、所属建筑物、楼层信息
# - 存入字典 ap_building_map，供后续匹配使用
# =====================================================================
print("\n[1] Loading AP location data from GeoJSON...")
with open(GEOJSON_FILE) as f:
    geojson_data = json.load(f)

ap_building_map = {}
for feature in geojson_data['features']:
    props = feature['properties']
    ap_name = props.get('USER_NOM_A')        # AP 名称
    building = props.get('USER_EDIFI', 'Unknown')   # 所属建筑物
    floor = props.get('Num_Planta', 0)              # 所在楼层
    if ap_name:
        ap_building_map[ap_name] = {
            'building': building,
            'floor': floor
        }

print(f"  Loaded {len(ap_building_map)} AP locations")
uniq_buildings = set(v['building'] for v in ap_building_map.values())
print(f"  Unique buildings: {len(uniq_buildings)}")

# =====================================================================
# 第二步：加载客户端信号强度数据
# Step 2: Load client signal data
# - clientes_processed.csv 包含实际的信号强度测量值 (signal_db)
# - 使用 nrows 限制读取行数，避免大文件导致内存不足
# =====================================================================
print("\n[2] Loading client signal data...")
cli = pd.read_csv(CLIENTS_FILE, nrows=500000)  # 采样 50 万行用于训练
print(f"  Loaded {len(cli)} client samples")

# =====================================================================
# 第三步：将 AP 名称映射为建筑物和楼层
# Step 3: Map AP names to building/floor
# - 根据客户端连接到的 AP (associated_device_name) 查找其地理位置
# - 如果精确匹配失败，尝试部分匹配（AP 名称可能包含子串匹配）
# =====================================================================
print("\n[3] Mapping AP names to buildings...")


def get_ap_location(ap_name):
    """
    根据 AP 名称获取其所在建筑物和楼层信息。
    如果精确匹配失败，会尝试部分匹配（AP 名称中可能包含关键字）。
    
    参数:
        ap_name (str): AP 名称（可能为空）
    返回:
        pd.Series: {'building': 建筑物名, 'floor': 楼层号}
    """
    if pd.isna(ap_name):
        return pd.Series({'building': 'Unknown', 'floor': 0})
    info = ap_building_map.get(ap_name, None)
    if info:
        return pd.Series(info)
    # 尝试部分匹配：遍历所有已知 AP，检查名称是否包含或被包含
    for key, val in ap_building_map.items():
        if key in ap_name or ap_name in key:
            return pd.Series(val)
    return pd.Series({'building': 'Unknown', 'floor': 0})


# 为每条客户端记录映射 AP 位置
location_info = cli['associated_device_name'].apply(get_ap_location)
cli['building'] = location_info['building']
cli['floor'] = location_info['floor']

# =====================================================================
# 第四步：过滤有效数据
# Step 4: Filter valid rows
# - 删除信号强度、建筑物、时间段为空的数据
# - 删除建筑物为 'Unknown' 的数据（无法用于训练）
# - 删除楼层为空的数据
# =====================================================================
valid = cli.dropna(subset=['signal_db', 'building', 'hour'])
valid = valid[valid['building'] != 'Unknown']
valid = valid[valid['floor'].notna()]
print(f"  Valid samples with location: {len(valid)}")

# =====================================================================
# 第五步：准备特征工程 (Feature Engineering)
# Step 5: Prepare features
# - 将建筑物名称通过 LabelEncoder 编码为整数
# - 特征包含：建筑物编码、楼层、时间段（小时）、频段
# - 目标变量：信号强度 (signal_db)
# =====================================================================
print("\n[4] Preparing features...")

# 将建筑物名称编码为整数（Label Encoding）
le_building = LabelEncoder()
valid['building_code'] = le_building.fit_transform(valid['building'])

# 特征列：building_code(建筑物编码), floor(楼层), hour(小时), band(频段)
feature_cols = ['building_code', 'floor', 'hour', 'band']
X = valid[feature_cols].copy()
y = valid['signal_db'].values

print(f"  Samples: {len(X)}")
print(f"  Feature columns: {feature_cols}")
print(f"  Signal dB range: {y.min():.0f} to {y.max():.0f} dBm")
print(f"  Signal dB mean: {y.mean():.1f} dBm")
print(f"  Buildings encoded: {len(le_building.classes_)}")

# =====================================================================
# 第六步：训练随机森林回归模型
# Step 6: Train Random Forest model
# - 按 80%:20% 划分训练集和测试集
# - 使用 RandomForestRegressor，配置：
#   - n_estimators=150: 150 棵决策树
#   - max_depth=20: 每棵树最大深度，防止过拟合
#   - min_samples_leaf=5: 叶子节点最少样本数
#   - n_jobs=-1: 使用全部 CPU 核心加速训练
# =====================================================================
print("\n[5] Training Random Forest model...")
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=RANDOM_SEED
)

# 训练随机森林回归器
model = RandomForestRegressor(
    n_estimators=150,
    max_depth=20,
    min_samples_leaf=5,
    random_state=RANDOM_SEED,
    n_jobs=-1
)

model.fit(X_train, y_train)
print(f"  Model trained on {len(X_train)} samples")

# =====================================================================
# 第七步：模型评估 (Model Evaluation)
# Step 7: Evaluate the model
# - MAE (Mean Absolute Error): 平均绝对误差，单位 dBm
# - RMSE (Root Mean Squared Error): 均方根误差，对大误差更敏感
# - R² (R-squared): 决定系数，衡量模型对数据变异的解释能力
# =====================================================================
y_pred = model.predict(X_test)
mae = mean_absolute_error(y_test, y_pred)
rmse = np.sqrt(mean_squared_error(y_test, y_pred))
r2 = r2_score(y_test, y_pred)

print(f"\n[6] Evaluation Results:")
print(f"  MAE:  {mae:.2f} dBm")
print(f"  RMSE: {rmse:.2f} dBm")
print(f"  R²:   {r2:.3f}")
print(f"  Avg error: {mae:.1f} dBm")

# =====================================================================
# 第八步：分析特征重要性 (Feature Importance)
# Step 8: Feature importance analysis
# - 随机森林可以输出各特征对预测结果的贡献度
# - 按重要性从高到低排序输出
# =====================================================================
print("\n[7] Feature Importances:")
importances = pd.DataFrame({
    'feature': feature_cols,
    'importance': model.feature_importances_
}).sort_values('importance', ascending=False)
for i, (_, row) in enumerate(importances.iterrows()):
    print(f"  {i+1}. {row['feature']}: {row['importance']:.3f}")

# =====================================================================
# 第九步：示例预测展示
# Step 9: Example predictions
# - 从测试集中抽取 5 条样本进行预测
# - 展示预测值与真实值的对比
# =====================================================================
print("\n[8] Example predictions:")
test_samples = X_test.head(5)
preds = model.predict(test_samples)
for i, (_, sample) in enumerate(test_samples.iterrows()):
    building_name = le_building.inverse_transform([int(sample['building_code'])])[0]
    print(f"  {building_name}, Floor {int(sample['floor'])}, Hour {int(sample['hour'])}, {sample['band']}GHz")
    print(f"    → Predicted: {preds[i]:.1f} dBm (Actual: {y_test[i]:.1f} dBm)")

# =====================================================================
# 第十步：保存模型和编码器
# Step 10: Save model and encoders
# - model: 随机森林回归模型 (.joblib)
# - meta: 模型元数据（特征名、模型类型、评估指标等）
# - encoder: 建筑物名称的 LabelEncoder，用于预测时编码
# =====================================================================
os.makedirs(MODEL_DIR, exist_ok=True)

# 保存随机森林模型
model_path = os.path.join(MODEL_DIR, 'signal_strength_model.joblib')
joblib.dump(model, model_path)
print(f"\n[9] Model saved to {model_path}")

# 保存模型元数据（包含特征名称、评估指标、编码的建筑物列表等）
meta = {
    'feature_names': feature_cols,
    'model_type': 'RandomForestRegressor',
    'target': 'signal_db',
    'target_unit': 'dBm',
    'signal_db_range': [float(y.min()), float(y.max())],
    'mae': round(mae, 2),
    'r2': round(r2, 3),
    'buildings': list(le_building.classes_),
    'n_buildings': len(le_building.classes_),
}
meta_path = os.path.join(MODEL_DIR, 'signal_strength_meta.joblib')
joblib.dump(meta, meta_path)

# 保存 LabelEncoder
encoder_path = os.path.join(MODEL_DIR, 'building_encoder.joblib')
joblib.dump(le_building, encoder_path)

print(f"  Metadata saved to {meta_path}")
print(f"  Encoder saved to {encoder_path}")
print(f"\n  Buildings: {list(le_building.classes_)}")
print("\n" + "=" * 60)
print("Training complete!")
print("=" * 60)


# =====================================================================
# 使用示例 (Usage Example)
# =====================================================================
#
# 1. 运行完整训练流程:
#   $ python train_signal_model.py
#
# 2. 在代码中加载并使用训练好的信号强度预测模型:
#
#   import joblib
#   import pandas as pd
#   from sklearn.preprocessing import LabelEncoder
#
#   # 加载模型、元数据和编码器
#   model = joblib.load("models/signal_strength_model.joblib")
#   meta = joblib.load("models/signal_strength_meta.joblib")
#   le_building = joblib.load("models/building_encoder.joblib")
#
#   # 查看元数据
#   print(f"Feature columns: {meta['feature_names']}")
#   print(f"MAE on test set: {meta['mae']} dBm")
#   print(f"Available buildings: {meta['buildings']}")
#
#   # 准备新数据 (DataFrame, 列名必须与训练时一致)
#   new_data = pd.DataFrame([
#       {"building_code": le_building.transform(["Engineering"])[0],
#        "floor": 2, "hour": 14, "band": 5},
#       {"building_code": le_building.transform(["Library"])[0],
#        "floor": 0, "hour": 9,  "band": 2.4},
#   ])
#
#   # 预测信号强度 (单位: dBm)
#   predictions = model.predict(new_data)
#   print(f"Predicted signal strength: {predictions} dBm")
#   # 输出示例: [-58.3 -72.1]
#
# 3. 直接传递建筑物名称 (自动编码):
#
#   building_name = "Main_Building"
#   if building_name in le_building.classes_:
#       building_code = le_building.transform([building_name])[0]
#   else:
#       print(f"Unknown building: {building_name}, using default 0")
#       building_code = 0
#
#   sample = pd.DataFrame([{
#       "building_code": building_code,
#       "floor": 1,
#       "hour": 12,
#       "band": 5,
#   }])
#   signal_dbm = model.predict(sample)[0]
#   print(f"Predicted signal at {building_name} floor 1: {signal_dbm:.1f} dBm")
#
# 4. 批量预测并导出:
#
#   df = pd.read_csv("locations_to_predict.csv")
#   # 确保 df 包含列: building_code, floor, hour, band
#   df["predicted_signal_dbm"] = model.predict(df[meta['feature_names']])
#   df.to_csv("signal_predictions.csv", index=False)
#   print(f"Predicted {len(df)} locations, saved to signal_predictions.csv")
# =====================================================================
