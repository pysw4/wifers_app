# -*- coding: utf-8 -*-
"""Predictor2_0.ipynb

从 Google Colab 自动生成的预测模型训练脚本。
本节使用以下算法训练 AP 状态（Up/Down）分类模型：
  - Logistic Regression (逻辑回归)
  - Naïve Bayes (朴素贝叶斯)
  - K-Neighbors (K 近邻)
  - SVM Linear (线性支持向量机)
  - SVM RBF (径向基核支持向量机)
  - Decision Tree (决策树)
  - Decision Tree with GridSearch (网格搜索优化的决策树)

Original file is located at
    https://colab.research.google.com/drive/1755hyUBrCC0nlu2TarjTAnYnchNzW5Zi
"""

# =====================================================================
# 导入所需库
# Imports: 加载所有必要的机器学习、数据处理和可视化工具
# =====================================================================
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.neighbors import KNeighborsRegressor
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.svm import SVR
from sklearn.tree import DecisionTreeRegressor
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.naive_bayes import GaussianNB
from sklearn.neighbors import KNeighborsClassifier
from sklearn.kernel_approximation import Nystroem
from sklearn.svm import LinearSVC
from sklearn.pipeline import Pipeline
from sklearn.tree import DecisionTreeClassifier
from sklearn.metrics import accuracy_score
from sklearn import tree
from sklearn.model_selection import GridSearchCV
import ast
import os
import joblib

RANDOM_SEED = 0  # 全局随机种子，确保实验可重复

# =====================================================================
# 数据预处理 (Data Preprocessing)
# Step 0: 加载原始数据，清理无关列，展开 radios 嵌套结构
# =====================================================================

# 读取 "aps_processed.csv" 原始数据集
d_aps = pd.read_csv(
    "aps_processed.csv",
    engine="python",
    on_bad_lines="error"
)

# 丢弃对预测无用的列：
# - timestamp: 时间戳，信息已拆分为其他列
# - swarm_name: 组名，不作为预测特征
# - firmware_version: 固件版本，不作为预测特征
# - macaddr: MAC 地址，标识符而非特征
# - date: 日期，信息已拆分为其他列
d_aps.drop(columns=["timestamp", "swarm_name", "firmware_version", "macaddr", "date"], inplace=True)

# 基于内存和训练速度考虑，对数据进行采样（完整数据集可能过大）
d_aps = d_aps.sample(n=1000, random_state=RANDOM_SEED)

d_aps.info()

# =====================================================================
# 分离目标变量和特征 (Separate Target and Features)
# - y_status: 目标变量，AP 状态（"Up" 或 "Down"）
# - features_aps: 特征矩阵（除去 status 列）
# =====================================================================
y_status = d_aps["status"]
features_aps = d_aps.drop(columns=["status"], inplace=False)
print(features_aps.info())

# 1. 单独提取 radios 列（嵌套结构：每个 AP 可能有多个无线电接口的列表）
radios_col = features_aps["radios"].copy()
print(radios_col.info())

# 2. 如果行是字符串，使用 ast.literal_eval 安全地转换为 Python 对象
radios_col = radios_col.apply(
    lambda x: ast.literal_eval(x) if isinstance(x, str) else x
)

# 3. 将列表形式的无线电记录展开为行（每行对应一个无线电接口）
radios_df = radios_col.explode()
print(radios_df.info())

# 4. 删除缺失或无效的无线电记录
radios_df = radios_df.dropna()

# 5. 将字典转换为 DataFram 列（规范化处理）
radios_df = pd.json_normalize(radios_df)

radios_df.head()

# 从特征矩阵中移除原始的 radios 列（已被展开处理）
d_aps_wr = features_aps.drop(columns=["radios"], inplace=True)

# =====================================================================
# 划分训练集/验证集/测试集 (Train/Validation/Test Split)
# - 随机抽取 10% 作为测试集（最终评估用）
# - 剩余 90% 中，再按 67%:33% 划分为训练集和验证集
# =====================================================================

# 抽取测试集：随机 10% 的样本
X_test_ap = features_aps.sample(frac=0.1, replace=False, random_state=RANDOM_SEED, axis=None, ignore_index=False)

# 对应的真实标签
y_true_status = y_status.sample(frac=0.1, replace=False, random_state=RANDOM_SEED, axis=None, ignore_index=False)

# 从原始数据中移除被划入测试集的样本
index_to_remove = y_true_status.index
features_aps.drop(index_to_remove, inplace=True)
y_status.drop(index_to_remove, inplace=True)

# 将剩余数据按 67%:33% 划分为训练集和验证集
X_train_ap, X_val_ap, y_train_ap, y_val_ap = train_test_split(features_aps, y_status, test_size=0.33, random_state=RANDOM_SEED)

# 计算训练集中 "Up" 类别的占比（用于后续对比基线准确率）
acc = (y_train_ap == "Up").sum() / len(y_train_ap)
print(acc)

# =====================================================================
# 训练分类模型 (Classification Model Training)
# 使用多种算法训练 AP 状态分类器，通过字典 dic_alg_cls_ap 记录结果
# =====================================================================

# 创建一个字典，用于存储各算法的对比结果
dic_alg_cls_ap = {}

# 1. Logistic Regression (逻辑回归)
# =====================================================================
# 使用 L2 正则化，balanced 类别权重（自动调整类别不平衡）
log_clf = LogisticRegression(penalty="l2", dual=False, class_weight='balanced', random_state=RANDOM_SEED).fit(X_train_ap, y_train_ap)

# 验证集准确率
accuracy = log_clf.score(X_val_ap, y_val_ap)

# 加权 F1 分数（适用于多分类或不平衡类别）
f1 = f1_score(y_val_ap, log_clf.predict(X_val_ap), average='weighted')

dic_alg_cls_ap["Logistic Regression"] = {"Call": "log_clf", "Accuracy": accuracy, "F1": f1}


# 2. Naïve Bayes (朴素贝叶斯分类器)
# =====================================================================
# 高斯朴素贝叶斯：假设特征服从高斯分布
gnb = GaussianNB()
gnb.fit(X_train_ap, y_train_ap)
y_pred = gnb.predict(X_val_ap)

# 验证集准确率
accuracy = gnb.score(X_val_ap, y_val_ap)

# 加权 F1 分数
f1 = f1_score(y_val_ap, gnb.predict(X_val_ap), average='weighted')

dic_alg_cls_ap["Naïve Bayes"] = {"Call": "gnb", "Accuracy": accuracy, "F1": f1}


# 3. K-Neighbors (K 近邻分类器)
# =====================================================================
# 通过遍历 k=1..25，选择最佳邻居数量，并绘制准确率曲线图
n = [i for i in range(1, 26)]
accuracy = {}
for i in n:
    neigh = KNeighborsClassifier(n_neighbors=i)
    neigh.fit(X_train_ap, y_train_ap)
    accuracy[i] = neigh.score(X_val_ap, y_val_ap)

# 绘制 "K 值 vs 准确率" 关系图，帮助可视化选择最佳 K
plt.plot(n, accuracy.values())
plt.title("k neighbors Vs Accuracy")
plt.xlabel("# Neighbors")
plt.ylabel("Accuracy")
plot_dir = "results"
os.makedirs(plot_dir, exist_ok=True)
plt.savefig(os.path.join(plot_dir, "knn_accuracy.png"), dpi=150, bbox_inches='tight')
plt.close()

# 选择 k=5 的 KNN 分类器（基于经验选择的较优值）
neigh = KNeighborsClassifier(n_neighbors=5)
neigh.fit(X_train_ap, y_train_ap)

# 验证集准确率
accuracy = neigh.score(X_val_ap, y_val_ap)
# 加权 F1 分数
f1 = f1_score(y_val_ap, neigh.predict(X_val_ap), average='weighted')

dic_alg_cls_ap["5-Neighbors"] = {"Call": "neigh", "Accuracy": accuracy, "F1": f1}


# 4. SVM Linear - Direct (线性支持向量机)
# =====================================================================
# 尝试不同的 C 值（正则化强度的倒数），选择验证集准确率最高的参数
Cs = [0.001, 0.01, 0.1, 0.5, 1, 2, 3, 10]
scores = {}
print("-----------FINDING BEST C (Linear SVM)-----------")
print("Cs to try:", Cs)

for c in Cs:
    print("====================================")
    # 使用 LinearSVC: 适用于线性分类的大规模 SVM 实现
    svm_clf_linear = LinearSVC(C=c, max_iter=1000000, random_state=RANDOM_SEED, dual=False)
    svm_clf_linear.fit(X_train_ap, y_train_ap)
    score = svm_clf_linear.score(X_val_ap, y_val_ap)
    scores[score] = c
    print("C =", c)
    print("  --> Score: ", f"{score:.3f}")

print("====================================\n====================================")
# 选出最佳 C 值，并用该值重新训练最终模型
best_c = scores[max(scores.keys())]
print("BEST C: " + str(best_c))

svm_clf_linear = LinearSVC(C=best_c, max_iter=1000000, random_state=RANDOM_SEED, dual=False)
svm_clf_linear.fit(X_train_ap, y_train_ap)

# 验证集准确率
accuracy = svm_clf_linear.score(X_val_ap, y_val_ap)
# 加权 F1 分数
f1 = f1_score(y_val_ap, svm_clf_linear.predict(X_val_ap), average='weighted')

dic_alg_cls_ap["SVC linear"] = {"Call": "svm_clf_linear", "Accuracy": accuracy, "F1": f1}

pipeline_svm_linear = svm_clf_linear


# 5. SVM RBF (径向基核支持向量机)
# =====================================================================
# 尝试不同的 gamma 值（RBF 核宽度参数），选择验证集准确率最高的参数
gammas = [0.001, 0.01, 0.1, 0.5, 1]
scores = {}

print("-----------FINDING BEST GAMMA (RBF SVM)-----------")
print("Gammas to try:", gammas)

from sklearn.svm import SVC

for g in gammas:
    print("====================================")
    # SVC 支持 RBF 核的 SVM 分类器（天然核方法，无需 Nystroem 近似）
    svm_clf_rbf = SVC(kernel='rbf', gamma=g, C=1.0, random_state=RANDOM_SEED)
    svm_clf_rbf.fit(X_train_ap, y_train_ap)
    score = svm_clf_rbf.score(X_val_ap, y_val_ap)
    scores[score] = g
    print("Gamma =", g)
    print("  --> Score: ", f"{score:.3f}")

print("====================================\n====================================")
# 选出最佳 gamma 值，并用该值重新训练最终模型
best_gamma = scores[max(scores.keys())]
print("BEST GAMMA: " + str(best_gamma))

svm_clf_rbf = SVC(kernel='rbf', gamma=best_gamma, C=1.0, random_state=RANDOM_SEED)
svm_clf_rbf.fit(X_train_ap, y_train_ap)

# 验证集准确率
accuracy = svm_clf_rbf.score(X_val_ap, y_val_ap)
# 加权 F1 分数
f1 = f1_score(y_val_ap, svm_clf_rbf.predict(X_val_ap), average='weighted')

dic_alg_cls_ap["SVC rbf"] = {"Call": "svm_clf_rbf", "Accuracy": accuracy, "F1": f1}

pipeline_svm_rbf = svm_clf_rbf


# 6. Decision Trees (决策树)
# =====================================================================
# 按奇数深度值 (1,3,5,...,49) 遍历，寻找最佳树深度
possible_depths = [i for i in range(1, 50, 2)]
for depth in possible_depths:
    # 使用信息熵 (entropy) 作为分裂标准
    stellar_tree = DecisionTreeClassifier(criterion="entropy", max_depth=depth, random_state=RANDOM_SEED).fit(X_train_ap, y_train_ap)
    print("Accuracy_" + str(depth) + ": " + str(accuracy_score(y_val_ap, stellar_tree.predict(X_val_ap))))

# 选择最大深度 49 的决策树（从结果中可见较深树准确率更高）
x = max(possible_depths)
stellar_tree = DecisionTreeClassifier(criterion="entropy", max_depth=x, random_state=RANDOM_SEED).fit(X_train_ap, y_train_ap)

# 验证集准确率
accuracy = accuracy_score(y_val_ap, stellar_tree.predict(X_val_ap))
# 加权 F1 分数
f1 = f1_score(y_val_ap, stellar_tree.predict(X_val_ap), average='weighted')

dic_alg_cls_ap["Decision Tree"] = {"Call": "stellar_tree", "Accuracy": accuracy, "F1": f1}

from sklearn import tree
import matplotlib.pyplot as plt

# 绘制决策树的可视化图形，便于解释模型决策逻辑
plt.figure(figsize=(12, 8))

tree.plot_tree(
    stellar_tree,
    feature_names=X_train_ap.columns,   # 使用 DataFrame 的列名作为特征名
    class_names=["Up", "Down"],         # 类别名称
    filled=True,
    rounded=True
)

plot_dir = "results"
os.makedirs(plot_dir, exist_ok=True)
plt.savefig(os.path.join(plot_dir, "decision_tree.png"), dpi=150, bbox_inches='tight')
plt.close()


# 7. Grid Search Decision Tree (网格搜索优化的决策树)
# =====================================================================
# 使用 GridSearchCV 在参数网格上搜索最佳决策树参数
params = {'max_leaf_nodes': list(range(2, 100)), 'min_samples_split': [2, 3, 4, 5]}

# 使用 5 折交叉验证搜索最佳参数组合
grid_stellar = GridSearchCV(DecisionTreeClassifier(random_state=RANDOM_SEED), params, verbose=1, cv=5).fit(X_train_ap, y_train_ap)
best_tree_stellar = grid_stellar.best_estimator_


def tree_info(tree_):
    """输出决策树的深度和叶子节点数，用于快速了解树的复杂度"""
    print("depth:", tree_.get_depth(), ", n_leaves:", tree_.get_n_leaves())


tree_info(best_tree_stellar)

# 验证集准确率
accuracy = accuracy_score(y_val_ap, best_tree_stellar.predict(X_val_ap))
# 加权 F1 分数
f1 = f1_score(y_val_ap, best_tree_stellar.predict(X_val_ap), average='weighted')

dic_alg_cls_ap["Decision Tree Grid (depth=2, leaves 3)"] = {"Call": "best_tree_stellar", "Accuracy": accuracy, "F1": f1}


def models_to_dataframe(models):
    """
    将模型对比字典转换为 DataFrame
    输入: models - 形如 {"模型名": {"Call": "变量名", "Accuracy": 0.xx, "F1": 0.xx}, ...} 的字典
    输出: 按准确率降序排列的 DataFrame
    """
    df = pd.DataFrame([
        [k, round(m["Accuracy"], 3), round(m["F1"], 3)]
        for k, m in models.items()
    ], columns=["Model", "Accuracy", "F1"])

    df = df.set_index("Model").sort_values(by="Accuracy", ascending=False)
    return df


# =====================================================================
# 模型对比与保存 (Model Comparison & Saving)
# - 输出所有模型在验证集上的准确率和 F1 分数
# - 将对比结果保存到 CSV 文件
# - 选出验证集准确率最高的模型，保存为 .joblib 文件
# =====================================================================

# 生成模型对比 DataFrame 并输出
results_df = models_to_dataframe(dic_alg_cls_ap)
print(results_df)

# 将结果保存到 CSV 文件
output_dir = "results"
os.makedirs(output_dir, exist_ok=True)
results_path = os.path.join(output_dir, "classification_results.csv")
results_df.to_csv(results_path)
print(f"Saved model results to {results_path}")

# 创建模型保存目录，清理旧模型文件
model_dir = "models"
os.makedirs(model_dir, exist_ok=True)

# 删除旧的模型文件，只保留最后选出的最优模型
for filename in os.listdir(model_dir):
    file_path = os.path.join(model_dir, filename)
    if os.path.isfile(file_path):
        os.remove(file_path)

# 所有训练好的模型对象映射表
model_objects = {
    "Logistic Regression": log_clf,
    "Naïve Bayes": gnb,
    "5-Neighbors": neigh,
    "SVC linear": pipeline_svm_linear,
    "SVC rbf": pipeline_svm_rbf,
    "Decision Tree": stellar_tree,
    "Decision Tree Grid (depth=2, leaves 3)": best_tree_stellar,
}

# 取验证集准确率最高的模型作为最终模型
best_model_name = results_df.index[0]
best_model = model_objects.get(best_model_name)

if best_model is not None:
    safe_name = best_model_name.lower().replace(" ", "_").replace("(", "").replace(")", "").replace(",", "").replace("/", "_")
    model_path = os.path.join(model_dir, f"{safe_name}.joblib")
    joblib.dump(best_model, model_path)
    print(f"Saved best model object '{best_model_name}' to {model_path}")
else:
    print(f"Warning: no model object mapped for best model '{best_model_name}'")


# =====================================================================
# 使用示例 (Usage Example)
# =====================================================================
#
# 1. 运行完整训练流程:
#   $ python predictor2_0.py
#
# 2. 在代码中加载并使用训练好的最佳分类模型:
#
#   import joblib
#   import pandas as pd
#
#   # 加载最佳模型
#   model = joblib.load("models/decision_tree.joblib")
#
#   # 准备新数据 (DataFrame, 列名需与训练时一致)
#   new_ap_data = pd.DataFrame([
#       {"uptime": 1209600, "adminstatus": "Enable", "sw_ver": "8.5.1"},
#       {"uptime": 86400,   "adminstatus": "Enable", "sw_ver": "8.5.0"},
#   ])
#
#   # 预测 AP 状态
#   predictions = model.predict(new_ap_data)
#   print(predictions)   # 输出: ['Up' 'Down']
#
#   # 预测概率的作用:
#   #   predict_proba() 返回每个样本属于各个类别的概率值 (0~1 之间)。
#   #   相比 predict() 只返回硬分类 ("Up"/"Down")，概率值能反映模型的"置信度"。
#   #
#   # 实际应用场景:
#   #   ① 风险控制 / 阈值调优:
#   #      - 只有当 "Down" 概率 > 0.8 时才标记为"需检修"，否则标记为"需复查"
#   #      - 避免因置信度低时做出错误决策
#   #   ② 结果排名:
#   #      - 按 "Down" 概率从高到低排序，优先处理最可能出问题的 AP
#   #      - 例如: 先处理概率 0.99 的 AP，再处理 0.51 的
#   #   ③ 人工复审队列:
#   #      - 概率在 0.4~0.6 之间的样本 → 自动列入"不确定列表"供人工判断
#   #      - 概率 > 0.9 或 < 0.1 的样本 → 自动处理，无需人工介入
#   #   ④ 集成决策:
#   #      - 结合概率做一些业务规则，如 "Up 概率 < 0.6 则发送告警通知"
#   #
#   try:
#       probs = model.predict_proba(new_ap_data)
#       # probs 是个二维数组，每行 = [属于 "Up" 的概率, 属于 "Down" 的概率]
#       # 例: [[0.92, 0.08], [0.35, 0.65]]
#       # 第一行: 92% 概率为 Up, 8% 概率为 Down
#       # 第二行: 35% 概率为 Up, 65% 概率为 Down → 最终分类为 Down
#       for i, (prob_up, prob_down) in enumerate(probs):
#           status = "Up" if prob_up > prob_down else "Down"
#           confidence = max(prob_up, prob_down)
#           print(f"Sample {i+1}: {status} (confidence: {confidence:.1%})")
#   except AttributeError:
#       print("该模型不支持 predict_proba (如 SVM 默认不输出概率)")
#
# 3. 批量预测并保存结果:
#
#   data = pd.read_csv("new_aps.csv")
#   preds = model.predict(data)
#   data["predicted_status"] = preds
#   data.to_csv("predictions_with_status.csv", index=False)
#   print(f"Predicted {len(preds)} APs, saved to predictions_with_status.csv")
#
# 4. 对比多个训练好的模型:
#
#   models_to_test = ["decision_tree.joblib", "logistic_regression.joblib"]
#   for mfile in models_to_test:
#       m = joblib.load(f"models/{mfile}")
#       acc = m.score(X_val, y_val)
#       print(f"{mfile}: accuracy = {acc:.3f}")
# =====================================================================
