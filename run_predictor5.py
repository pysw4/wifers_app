"""Predictor5_0 — 通用 AP 信号强度 LSTM 预测器
─────────────────────────────────────────────
训练：使用全部 AP 数据 + AP 名称编码 + 时间特征 → 单一通用模型
预测：predict(ap_name, start_datetime, horizon_hours) → 未来 signal_score
"""
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from sklearn.preprocessing import MinMaxScaler, LabelEncoder
from sklearn.model_selection import train_test_split
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset
from tqdm import tqdm
import warnings, os, joblib
warnings.filterwarnings('ignore')

# ─────────────────────────────────────────────
#  配置参数
# ─────────────────────────────────────────────
DEVICE = torch.device('mps' if torch.backends.mps.is_available() else 'cpu')
print(f'  🔥 使用设备: {DEVICE}')

DRY_RUN         = False    # True = 仅取前10个AP+2个epoch，快速验证流程
WINDOW_SIZE     = 24       # 输入：过去 24 小时
FORECAST_HORIZON = 12      # 输出：未来 12 小时
TARGET_COLUMN   = 'signal_score'
BATCH_SIZE      = 256      # GPU 可以用更大 batch
EPOCHS          = 2 if DRY_RUN else 30
PATIENCE        = 5
MODEL_DIR       = 'predictor5_model'
os.makedirs(MODEL_DIR, exist_ok=True)

# ─────────────────────────────────────────────
#  特征定义
# ─────────────────────────────────────────────
NUMERIC_FEATURES = [
    'signal_score', 'signal_strength', 'signal_db', 'snr',
    'cpu_utilization', 'mem_usage', 'client_count', 'health',
    'speed', 'maxspeed'
]
ALL_FEATURES = NUMERIC_FEATURES + ['ap_code', 'hour_sin', 'hour_cos', 'day_sin', 'day_cos']
# idx = [0..9] numeric, 10=ap_code, 11=hour_sin, 12=hour_cos, 13=day_sin, 14=day_cos
TARGET_IDX = NUMERIC_FEATURES.index(TARGET_COLUMN)  # 0

print('=' * 60)
print('  Predictor5_0 — 通用多 AP LSTM 预测器')
print('=' * 60)

# ═════════════════════════════════════════════
#  1. 加载数据
# ═════════════════════════════════════════════
print('\n[1/7] 加载数据...')

if DRY_RUN:
    # DRY RUN: 先快速获取 top AP 再只读这些 AP 的数据（避免读完整 37M 行）
    import pyarrow.parquet as pq
    pf = pq.ParquetFile('meme_clean.parquet')
    # 只读 ap_name 列来排序取 top
    ap_names = pf.read(columns=['associated_device_name', 'signal_score']).to_pandas()
    ap_names['associated_device_name'] = ap_names['associated_device_name'].str.strip()
    top_aps = ap_names['associated_device_name'].value_counts().head(10).index.tolist()
    del ap_names
    # 用 pyarrow 的 row group filter 读
    table = pq.read_table('meme_clean.parquet', filters=[('associated_device_name', 'in', top_aps)])
    df = table.to_pandas()
    # 再 strip 一次确保一致性
    df['associated_device_name'] = df['associated_device_name'].str.strip()
    # 只保留这些 AP 的数据
    df = df[df['associated_device_name'].isin(top_aps)].copy()
    print(f'  Shape: {df.shape}')
    print(f'  🔬 DRY RUN: 仅用前 {len(top_aps)} 个 AP')
else:
    df = pd.read_parquet('meme_clean.parquet')
    print(f'  Shape: {df.shape}')

df = df.dropna(subset=NUMERIC_FEATURES).copy()
print(f'  去空后: {df.shape}')

df['timestamp'] = pd.to_datetime(df['timestamp'])

df = df.sort_values(['associated_device_name', 'timestamp']).reset_index(drop=True)
all_aps = df['associated_device_name'].unique()
print(f'  总 AP: {len(all_aps)}')

# ═════════════════════════════════════════════
#  2. 特征工程
# ═════════════════════════════════════════════
print('\n[2/7] 特征工程: AP 编码 + 时间特征...')

# 2a. AP LabelEncoder — 用全部 AP 拟合
le_ap = LabelEncoder()
le_ap.fit(df['associated_device_name'])
df['ap_code'] = le_ap.transform(df['associated_device_name'])

# 2b. 时间特征（hour + day_of_week，用 sin/cos 编码）
hours   = df['timestamp'].dt.hour
dow     = df['timestamp'].dt.dayofweek
df['hour_sin'] = np.sin(2 * np.pi * hours / 24)
df['hour_cos'] = np.cos(2 * np.pi * hours / 24)
df['day_sin']  = np.sin(2 * np.pi * dow / 7)
df['day_cos']  = np.cos(2 * np.pi * dow / 7)

print(f'  最终 Shape: {df.shape}, AP 数: {df["associated_device_name"].nunique()}')

# ═════════════════════════════════════════════
#  3. 前向填充 + 重采样
# ═════════════════════════════════════════════
print('[3/7] 前向填充 & 按小时重采样...')

# 先 forward fill 缺失值
for ap in tqdm(all_aps, desc='  前向填充'):
    mask = df['associated_device_name'] == ap
    df.loc[mask, NUMERIC_FEATURES] = df.loc[mask, NUMERIC_FEATURES].ffill().bfill()

# 按小时均值重采样（保留 ap_code 和 时间特征的一致性）
hourly_parts = []
for ap in tqdm(all_aps, desc='  重采样'):
    sub = df[df['associated_device_name'] == ap].copy()
    sub = sub.set_index('timestamp')
    # 数值按小时取均值
    numeric_resampled = sub[NUMERIC_FEATURES].resample('1h').mean()
    # AP 编码和时间特征取第一个（同一小时内不变）
    const_cols = ['ap_code']
    const_resampled = sub[const_cols].resample('1h').first()
    # 时间特征从 index 重新生成
    resampled = numeric_resampled.join(const_resampled).ffill().bfill()
    # 重新生成时间特征（基于新 index 的时间）
    resampled['hour_sin'] = np.sin(2 * np.pi * resampled.index.hour / 24)
    resampled['hour_cos'] = np.cos(2 * np.pi * resampled.index.hour / 24)
    resampled['day_sin']  = np.sin(2 * np.pi * resampled.index.dayofweek / 7)
    resampled['day_cos']  = np.cos(2 * np.pi * resampled.index.dayofweek / 7)
    resampled['associated_device_name'] = ap
    resampled = resampled.reset_index()
    hourly_parts.append(resampled)

hourly_df = pd.concat(hourly_parts, ignore_index=True)
print(f'  重采样后: {hourly_df.shape}')
del df  # 释放内存

# ═════════════════════════════════════════════
#  4. 归一化（拟合全部数据）
# ═════════════════════════════════════════════
print('[4/7] 归一化...')

# 在归一化前清理 inf / NaN
hourly_df[ALL_FEATURES] = hourly_df[ALL_FEATURES].replace([np.inf, -np.inf], np.nan)
hourly_df[ALL_FEATURES] = hourly_df[ALL_FEATURES].fillna(hourly_df[ALL_FEATURES].median())

scaler = MinMaxScaler()
scaled_values = scaler.fit_transform(hourly_df[ALL_FEATURES])
print(f'  归一化 Shape: {scaled_values.shape}')

# ═════════════════════════════════════════════
#  5. 为每个 AP 生成序列 → 合并
# ═════════════════════════════════════════════
print('[5/7] 生成训练序列...')

def create_sequences_for_ap(data_2d, window, horizon, target_idx):
    """为单个 AP 的数据生成 (X, y) 序列"""
    X, y = [], []
    total = len(data_2d) - window - horizon
    if total <= 0:
        return None, None
    for i in range(total):
        X.append(data_2d[i:i + window])
        y.append(data_2d[i + window:i + window + horizon, target_idx])
    return np.array(X, dtype=np.float32), np.array(y, dtype=np.float32)

all_X, all_y = [], []
ap_seq_counts = {}

for ap_name in tqdm(all_aps, desc='  生成序列'):
    mask = hourly_df['associated_device_name'] == ap_name
    group = hourly_df.loc[mask].sort_values('timestamp')
    if len(group) < WINDOW_SIZE + FORECAST_HORIZON + 1:
        continue
    # 找到这个 group 在 scaled_values 中的行索引
    idx_start = group.index[0]
    idx_end   = group.index[-1] + 1
    data_2d = scaled_values[idx_start:idx_end]
    X_ap, y_ap = create_sequences_for_ap(data_2d, WINDOW_SIZE, FORECAST_HORIZON, TARGET_IDX)
    if X_ap is not None and len(X_ap) > 0:
        all_X.append(X_ap)
        all_y.append(y_ap)
        ap_seq_counts[ap_name] = len(X_ap)

X_all = np.concatenate(all_X, axis=0)
y_all = np.concatenate(all_y, axis=0)
del all_X, all_y

n_aps_used = len(ap_seq_counts)
print(f'  实际使用 AP: {n_aps_used}')
print(f'  总样本: {X_all.shape[0]}')
print(f'  序列形状: {X_all.shape[1:]} → {y_all.shape[1]}')

# 统计各 AP 的序列量
seq_counts = pd.Series(ap_seq_counts)
print(f'  中位数序列/AP: {seq_counts.median():.0f}, 范围: {seq_counts.min()}~{seq_counts.max()}')

# ═════════════════════════════════════════════
#  6. 训练模型（PyTorch + MPS GPU）
# ═════════════════════════════════════════════
print('\n[6/7] 训练通用 LSTM（PyTorch + MPS GPU）...')
X_train, X_test, y_train, y_test = train_test_split(X_all, y_all, test_size=0.15, shuffle=False)

# DRY RUN 用小模型加速验证，正式训练用大模型
if DRY_RUN:
    LSTM_UNITS_1 = 16
    LSTM_UNITS_2 = 8
    DENSE_UNITS = 8
else:
    LSTM_UNITS_1 = 80
    LSTM_UNITS_2 = 48
    DENSE_UNITS = 32

N_FEATURES = X_train.shape[2]
N_FEATURES_IN = N_FEATURES

class LSTMPredictor(nn.Module):
    def __init__(self, input_size, hidden1, hidden2, dense_units, output_size):
        super().__init__()
        self.lstm1 = nn.LSTM(input_size, hidden1, batch_first=True)
        self.drop1 = nn.Dropout(0.25)
        self.lstm2 = nn.LSTM(hidden1, hidden2, batch_first=True)
        self.drop2 = nn.Dropout(0.25)
        self.fc1 = nn.Linear(hidden2, dense_units)
        self.relu = nn.ReLU()
        self.fc2 = nn.Linear(dense_units, output_size)

    def forward(self, x):
        x, _ = self.lstm1(x)
        x = self.drop1(x)
        x, _ = self.lstm2(x)
        x = self.drop2(x)
        x = x[:, -1, :]  # take last output
        x = self.relu(self.fc1(x))
        x = self.fc2(x)
        return x

model = LSTMPredictor(N_FEATURES_IN, LSTM_UNITS_1, LSTM_UNITS_2, DENSE_UNITS, FORECAST_HORIZON)
model.to(DEVICE)

# 参数统计
total_params = sum(p.numel() for p in model.parameters())
trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
print(f'  模型参数量: {total_params:,} ({total_params*4/1024:.1f} KB)')
print(f'  可训练参数: {trainable_params:,}')

criterion = nn.MSELoss()
optimizer = optim.Adam(model.parameters())

# 数据加载器
X_train_t = torch.tensor(X_train, dtype=torch.float32)
y_train_t = torch.tensor(y_train, dtype=torch.float32)
X_test_t = torch.tensor(X_test, dtype=torch.float32)
y_test_t = torch.tensor(y_test, dtype=torch.float32)

train_dataset = TensorDataset(X_train_t, y_train_t)
train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True)

# 训练循环
best_val_loss = float('inf')
patience_counter = 0

# 验证集划分（后 15% 的训练数据用于验证）
val_size = int(len(X_train_t) * 0.15)
X_val_t, y_val_t = X_train_t[-val_size:], y_train_t[-val_size:]
X_train_t_sub, y_train_t_sub = X_train_t[:-val_size], y_train_t[:-val_size]

for epoch in range(EPOCHS):
    model.train()
    train_loss_total = 0.0
    train_batches = 0

    pbar = tqdm(train_loader, desc=f'  Epoch {epoch+1}/{EPOCHS}', leave=False, ncols=80)
    for batch_X, batch_y in pbar:
        batch_X, batch_y = batch_X.to(DEVICE), batch_y.to(DEVICE)

        optimizer.zero_grad()
        outputs = model(batch_X)
        loss = criterion(outputs, batch_y)
        loss.backward()
        optimizer.step()

        train_loss_total += loss.item()
        train_batches += 1
        pbar.set_postfix(loss=f'{loss.item():.4f}')

    # 验证
    model.eval()
    with torch.no_grad():
        X_val, y_val = X_val_t.to(DEVICE), y_val_t.to(DEVICE)
        val_outputs = model(X_val)
        val_loss = criterion(val_outputs, y_val).item()

    avg_train_loss = train_loss_total / max(train_batches, 1)
    print(f'  Epoch {epoch+1}/{EPOCHS} — loss: {avg_train_loss:.6f} — val_loss: {val_loss:.6f}')

    # Early Stopping
    if val_loss < best_val_loss:
        best_val_loss = val_loss
        patience_counter = 0
        # 保存最佳模型
        torch.save(model.state_dict(), os.path.join(MODEL_DIR, 'best_model.pt'))
    else:
        patience_counter += 1
        if patience_counter >= PATIENCE:
            print(f'  ⏹ Early stopping at epoch {epoch+1}')
            break

# 加载最佳模型
model.load_state_dict(torch.load(os.path.join(MODEL_DIR, 'best_model.pt'), map_location=DEVICE))

# 评估
model.eval()
with torch.no_grad():
    X_test_gpu, y_test_gpu = X_test_t.to(DEVICE), y_test_t.to(DEVICE)
    y_pred = model(X_test_gpu).cpu().numpy()
    test_loss = criterion(model(X_test_gpu), y_test_gpu).item()
    test_mae = nn.L1Loss()(model(X_test_gpu), y_test_gpu).item()

print(f'\n  ✅ 测试 MSE: {test_loss:.6f}, MAE: {test_mae:.6f}')

# ═════════════════════════════════════════════
#  7. 保存模型 + 预处理组件
# ═════════════════════════════════════════════
print('[7/7] 保存模型与组件...')
# 保存完整模型（架构 + 权重）
torch.save(model.state_dict(), os.path.join(MODEL_DIR, 'model_state.pt'))
# 保存模型架构定义
model_scripted = torch.jit.script(model.cpu())
model_scripted.save(os.path.join(MODEL_DIR, 'model_jit.pt'))
model.to(DEVICE)

joblib.dump(scaler,  os.path.join(MODEL_DIR, 'scaler.joblib'))
joblib.dump(le_ap,   os.path.join(MODEL_DIR, 'label_encoder.joblib'))
# 保存特征列表等元信息
meta = {
    'framework': 'pytorch',
    'device': str(DEVICE),
    'window_size': WINDOW_SIZE,
    'forecast_horizon': FORECAST_HORIZON,
    'target_column': TARGET_COLUMN,
    'numeric_features': NUMERIC_FEATURES,
    'all_features': ALL_FEATURES,
    'target_idx': TARGET_IDX,
    'n_aps_total': len(all_aps),
    'n_aps_used': n_aps_used,
    'n_samples': len(X_all),
    'n_features': N_FEATURES_IN,
    'lstm_units_1': LSTM_UNITS_1,
    'lstm_units_2': LSTM_UNITS_2,
    'dense_units': DENSE_UNITS,
    'test_mse': float(test_loss),
    'test_mae': float(test_mae),
}
joblib.dump(meta, os.path.join(MODEL_DIR, 'meta.joblib'))
print(f'  ✅ 模型和组件已保存到 {MODEL_DIR}/')

# ═════════════════════════════════════════════
#  8. 预测接口
# ═════════════════════════════════════════════
def load_predictor(model_dir=MODEL_DIR):
    """加载训练好的模型和预处理组件"""
    meta = joblib.load(os.path.join(model_dir, 'meta.joblib'))
    scaler = joblib.load(os.path.join(model_dir, 'scaler.joblib'))
    le_ap = joblib.load(os.path.join(model_dir, 'label_encoder.joblib'))

    # 重建模型
    lstm1 = meta.get('lstm_units_1', 80)
    lstm2 = meta.get('lstm_units_2', 48)
    dense_u = meta.get('dense_units', 32)
    n_feats = meta.get('n_features', len(meta['all_features']))
    fh = meta['forecast_horizon']

    device = torch.device('mps' if torch.backends.mps.is_available() else 'cpu')
    model = LSTMPredictor(n_feats, lstm1, lstm2, dense_u, fh)
    model.load_state_dict(torch.load(os.path.join(model_dir, 'model_state.pt'), map_location=device))
    model.to(device)
    model.eval()
    return model, scaler, le_ap, meta

def score2label(score):
    if score >= 0.95: return 'Excellent++'
    elif score >= 0.90: return 'Excellent+'
    elif score >= 0.80: return 'Excellent'
    elif score >= 0.70: return 'Good'
    elif score >= 0.50: return 'Fair'
    else: return 'Poor'

def predict(model, scaler, le_ap, meta, ap_name, start_datetime, horizon_hours=None):
    """预测指定 AP 从 start_datetime 开始的未来 signal_score"""
    W = meta['window_size']
    FH = horizon_hours or meta['forecast_horizon']
    all_feats = meta['all_features']
    TARGET_IDX_LOCAL = meta['target_idx']

    # 编码 AP
    if ap_name not in le_ap.classes_:
        raise ValueError(f"AP '{ap_name}' 不在训练集中。可用的 AP 示例: {le_ap.classes_[:5]}...")
    ap_code = le_ap.transform([ap_name])[0]

    # 构造输入序列
    start = pd.Timestamp(start_datetime)
    window_timestamps = pd.date_range(end=start - pd.Timedelta(hours=1), periods=W, freq='h')

    feat_data = []
    for ts in window_timestamps:
        hour = ts.hour
        dow  = ts.dayofweek
        feat_data.append({
            'ap_code': ap_code,
            'hour_sin': np.sin(2 * np.pi * hour / 24),
            'hour_cos': np.cos(2 * np.pi * hour / 24),
            'day_sin':  np.sin(2 * np.pi * dow / 7),
            'day_cos':  np.cos(2 * np.pi * dow / 7),
        })

    # 数值特征 — 从真实数据获取
    try:
        df_hist = pd.read_parquet('meme_clean.parquet')
        df_hist = df_hist[df_hist['associated_device_name'] == ap_name].copy()
        df_hist['timestamp'] = pd.to_datetime(df_hist['timestamp'])
        df_hist = df_hist.sort_values('timestamp')
        for feat_name in meta['numeric_features']:
            for i, ts in enumerate(window_timestamps):
                nearest = df_hist.iloc[(df_hist['timestamp'] - ts).abs().argsort()[:1]]
                feat_data[i][feat_name] = nearest[feat_name].values[0] if len(nearest) > 0 else 0.5
    except Exception as e:
        print(f'  ⚠ 无法读取历史数据 ({e})，使用默认中值')
        for feat_name in meta['numeric_features']:
            for i in range(W):
                feat_data[i][feat_name] = 0.5

    # 构建 DataFrame 并缩放
    input_df = pd.DataFrame(feat_data)
    input_scaled = scaler.transform(input_df[all_feats])
    X_input = np.expand_dims(input_scaled, axis=0)

    # 预测
    model.eval()
    with torch.no_grad():
        X_tensor = torch.tensor(X_input, dtype=torch.float32).to(next(model.parameters()).device)
        pred_scaled = model(X_tensor).cpu().numpy()[0]

    if len(pred_scaled) < FH:
        pad = np.full(FH - len(pred_scaled), pred_scaled[-1])
        pred_scaled = np.concatenate([pred_scaled, pad])
    pred_scaled = pred_scaled[:FH]

    # 反标准化
    dummy = np.zeros((FH, len(all_feats)))
    dummy[:, TARGET_IDX_LOCAL] = pred_scaled
    pred_original = scaler.inverse_transform(dummy)[:, TARGET_IDX_LOCAL]
    pred_original = np.clip(pred_original, 0, 1)

    # 组装结果
    results_pred = []
    for i in range(FH):
        ts = start + pd.Timedelta(hours=i + 1)
        results_pred.append({
            'offset': i + 1,
            'timestamp': ts,
            'score': float(pred_original[i]),
            'label': score2label(pred_original[i]),
        })
    return results_pred


# ─────────────────────────────────────────────
#  演示预测
# ─────────────────────────────────────────────
print('\n' + '=' * 60)
print('  🔮 预测演示')
print('=' * 60)

model, scaler, le_ap, meta = load_predictor()
sample_aps = list(ap_seq_counts.keys())[:5]
print(f'\n示例 AP（前 5 个有充足数据的）: {sample_aps}')

for ap_demo in sample_aps:
    ap_data = hourly_df[hourly_df['associated_device_name'] == ap_demo]
    last_ts = ap_data['timestamp'].max()
    start_ts = last_ts
    print(f'\n── {ap_demo} ── 从 {start_ts} 开始预测未来 {FORECAST_HORIZON}h ──')
    try:
        preds = predict(model, scaler, le_ap, meta, ap_demo, start_ts, horizon_hours=FORECAST_HORIZON)
        for p in preds[:6]:
            print(f'  +{p["offset"]:>2d}h  {p["timestamp"]}  →  {p["score"]:.4f}  [{p["label"]}]')
        if len(preds) > 6:
            print(f'  ... 还有 {len(preds) - 6} 个预测')
    except Exception as e:
        print(f'  ✗ 预测失败: {e}')

# ─────────────────────────────────────────────
#  对比图
# ─────────────────────────────────────────────
print('\n[+] 生成测试集对比图...')
model.eval()
with torch.no_grad():
    preds_full = model(X_test_t.to(DEVICE)).cpu().numpy()

fig, axes = plt.subplots(2, 2, figsize=(16, 10))
steps_to_plot = [0, 1, 5, 11]
for idx, step in enumerate(steps_to_plot):
    ax = axes[idx // 2, idx % 2]
    ax.plot(y_test[:, step], label='Real', alpha=0.8)
    ax.plot(preds_full[:, step], label='Predicted', alpha=0.8, linestyle='--')
    ax.set_title(f'Hour +{step+1} — W={WINDOW_SIZE} → FH={FORECAST_HORIZON}')
    ax.set_xlabel('Test Sample')
    ax.set_ylabel('Signal Score (scaled)')
    ax.legend()
    ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig('predictor5_0_comparison.png', dpi=150)
print('  ✅ 对比图已保存: predictor5_0_comparison.png')

# ─────────────────────────────────────────────
#  总结
# ─────────────────────────────────────────────
print('\n' + '=' * 60)
print('  📊 模型训练完成')
print('=' * 60)
print(f'  框架:        PyTorch ({DEVICE})')
print(f'  输入窗口:    {WINDOW_SIZE}h')
print(f'  预测窗口:    {FORECAST_HORIZON}h')
print(f'  特征维度:    {len(ALL_FEATURES)} (10 数值 + 1 AP编码 + 4 时间)')
print(f'  训练 AP 数:  {n_aps_used}/{len(all_aps)}')
print(f'  总样本数:    {len(X_all)}')
print(f'  测试 MSE:    {test_loss:.6f}')
print(f'  测试 MAE:    {test_mae:.6f}')
print(f'  模型保存至:  {MODEL_DIR}/')
print()
print('💡 使用示例:')
print('  from run_predictor5 import load_predictor, predict')
print('  model, scaler, le_ap, meta = load_predictor()')
print('  result = predict(model, scaler, le_ap, meta, "AP-CEDU26", "2025-07-10 18:00:00", 24)')
print('  for r in result: print(r["offset"], r["timestamp"], r["score"], r["label"])')
print('=' * 60)
print('\n✅ Predictor5_0 执行完毕！')
