# -*- coding: utf-8 -*-
"""
模型预测脚本 (Model Prediction Script)
加载训练好的最优模型并对新数据进行预测
"""

import os
import joblib
import pandas as pd
import numpy as np
import ast

# =====================================================================
# 第一步：加载训练好的最优模型
# Step 1: Load the trained best model
# - 遍历 models/ 目录，找到第一个 .joblib 文件
# - 使用 joblib 反序列化加载模型
# - 提取模型名称用于显示
# =====================================================================
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

# =====================================================================
# 第二步：加载并预处理原始数据，用于演示预测
# Step 2: Load and preprocess the original data for prediction demo
# - 读取 aps_processed.csv 原始数据集
# - 丢弃训练时不使用的列（timestamp, swarm_name, firmware_version, macaddr, date）
# - 随机采样 1000 条数据作为预测演示样本
# - 分离特征 (features) 和标签 (y_status)
# - 移除 'radios' 列（该列在训练时已被展开处理）
# =====================================================================
try:
    d_aps = pd.read_csv("aps_processed.csv", engine="python", on_bad_lines="error")
    
    # Preprocess data (same as in training)
    d_aps.drop(columns=["timestamp", "swarm_name", "firmware_version", "macaddr", "date"], inplace=True)
    d_aps = d_aps.sample(n=1000, random_state=0)
    
    # 分离目标变量 (y_status) 和特征 (features)
    y_status = d_aps["status"]
    features = d_aps.drop(columns=["status"], inplace=False)
    
    # 移除 'radios' 列以匹配训练时的特征数量
    if 'radios' in features.columns:
        features = features.drop(columns=['radios'])
    
    print("\nData loaded and preprocessed")
    print(f"Number of samples: {len(features)}")
    print(f"Number of features: {features.shape[1]}")
    print(f"Feature names: {list(features.columns)}")
    print("\n" + "=" * 50)

    # =====================================================================
    # 第三步：对前 10 个样本进行预测并展示结果
    # Step 3: Make predictions on the first 10 samples and display results
    # - 使用 best_model.predict() 进行预测
    # - 尝试获取预测概率（如果模型支持 predict_proba）
    # - 将预测值与真实标签对比，标记正确/错误
    # - 计算前 10 个样本的准确率
    # =====================================================================
    print("\nMaking predictions on first 10 samples:")
    print("-" * 50)
    
    X_sample = features.iloc[:10]
    predictions = best_model.predict(X_sample)
    probabilities = None
    
    # 尝试获取预测概率（部分模型如 SVM 不支持 predict_proba）
    try:
        probabilities = best_model.predict_proba(X_sample)
    except AttributeError:
        pass
    
    # 逐条显示预测结果，用 ✓/✗ 标记预测是否正确
    for idx, (pred, true_label) in enumerate(zip(predictions, y_status.iloc[:10])):
        match = "✓" if pred == true_label else "✗"
        print(f"Sample {idx+1}: Predicted={pred}, True={true_label} {match}")
    
    print("\n" + "=" * 50)
    print("\nAccuracy on first 10 samples: {:.2%}".format(
        np.mean(predictions == y_status.iloc[:10].values)
    ))
    
    # =====================================================================
    # 第四步：在全部样本上计算整体准确率
    # Step 4: Calculate overall accuracy on all samples
    # =====================================================================
    all_predictions = best_model.predict(features)
    overall_accuracy = np.mean(all_predictions == y_status.values)
    print(f"Overall accuracy on all {len(features)} samples: {overall_accuracy:.2%}")
    
    # =====================================================================
    # 第五步：将预测结果保存到 CSV 文件
    # Step 5: Save predictions to CSV
    # - 包含三列：真实状态、预测状态、是否预测正确
    # =====================================================================
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


# =====================================================================
# 使用示例 (Usage Example)
# =====================================================================
if __name__ == "__main__":
    """
    使用示例 / Usage Example:

    # 从命令行运行预测
    $ python predict.py

    # 在代码中导入并使用:
    
    import joblib
    import pandas as pd

    # 加载模型
    model = joblib.load("models/signal_strength_model.joblib")

    # 准备新数据 (DataFrame, 列名需与训练时一致)
    new_data = pd.DataFrame([
        {"building_code": 3, "floor": 1, "hour": 14, "band": 5},
        {"building_code": 7, "floor": 0, "hour": 9,  "band": 2.4},
    ])

    # 进行预测
    predictions = model.predict(new_data)
    print(predictions)   # 输出: [ -58.3  -72.1 ]  (单位: dBm)

    # 若使用分类模型:
    clf = joblib.load("models/logistic_regression.joblib")
    labels = clf.predict(new_data)
    print(labels)        # 输出: ['Up' 'Down']
    """
