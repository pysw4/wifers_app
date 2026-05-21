from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
import networkx as nx
import pandas as pd
import numpy as np
import joblib
from pathlib import Path
import osmnx as ox
from helper_script import add_aps_to_graph, find_paths_to_candidates, find_qualified_in_range
import os
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 使用 lifespan 上下文管理器替代已弃用的 @app.on_event("startup")
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup application resources."""
    global _initialized
    try:
        logger.info("Initializing application resources...")
        
        # 1. Load ML model (lightweight, should succeed)
        load_ml_model()
        logger.info("ML model loaded successfully")
        
        # 2. Load graph (heavy, may time out - but we catch errors gracefully)
        try:
            init_graph()
            _initialized = True
        except Exception as e:
            logger.error(f"Failed to load graph: {e}")
            logger.warning("Graph routing will be unavailable until graph is loaded")
            _initialized = False
    except Exception as e:
        logger.error(f"Startup initialization failed: {e}")
        _initialized = False
    
    yield  # 应用运行中
    
    # 关闭时的清理工作
    logger.info("Shutting down application...")


app = FastAPI(lifespan=lifespan)

# Global variables for lazy-loaded resources
G = None
G_AP_nodes = None
ml_model = None
model_path = None
_initialized = False

UAB_bbox = 41.50736, 41.49505, 2.11543, 2.09491
MODEL_FEATURES = [
    'client_count',
    'cpu_utilization',
    'mem_free',
    'mem_total',
    'last_modified',
    'hour',
    'mem_usage',
    'overloaded'
]

MODEL_FILE_NAME = 'decision_tree.joblib'
BASE_DIR = Path(__file__).resolve().parent
PRIMARY_MODEL_PATH = BASE_DIR / 'models' / MODEL_FILE_NAME
FALLBACK_MODEL_PATH = Path.cwd() / 'models' / MODEL_FILE_NAME


def init_graph(force: bool = False):
    """Initialize the OSM graph and AP nodes (lazy-loaded)."""
    global G, G_AP_nodes
    if G is not None and not force:
        return G, G_AP_nodes

    logger.info("Loading OSM graph for UAB area...")
    # bbox format: (left, bottom, right, top) = (west, south, east, north)
    osm_bbox = (UAB_bbox[3], UAB_bbox[1], UAB_bbox[2], UAB_bbox[0])
    G = ox.graph_from_bbox(bbox=osm_bbox, network_type="walk")
    
    logger.info("Adding AP nodes to graph...")
    G_AP_nodes = add_aps_to_graph(G, bbox=[UAB_bbox[3], UAB_bbox[0], UAB_bbox[2], UAB_bbox[1]])
    logger.info(f"Loaded graph with {len(G.nodes())} total nodes, {len(G_AP_nodes)} AP nodes added")
    return G, G_AP_nodes


def load_ml_model(force: bool = False):
    """Load the ML model (lazy-loaded)."""
    global ml_model, model_path
    if ml_model is not None and not force:
        return ml_model, model_path

    candidates = [PRIMARY_MODEL_PATH, FALLBACK_MODEL_PATH]
    model_dir = BASE_DIR / 'models'
    if not any(candidate.exists() for candidate in candidates) and model_dir.exists():
        candidates.extend(sorted(model_dir.glob('*.joblib')))

    for candidate in candidates:
        if candidate.exists():
            try:
                ml_model = joblib.load(candidate)
                model_path = candidate
                logger.info(f"Loaded ML model from {candidate}")
                return ml_model, model_path
            except Exception as e:
                logger.warning(f"Failed to load ML model from {candidate}: {e}")

    model_path = PRIMARY_MODEL_PATH
    error_msg = f"ML model not found. Tried: {', '.join(str(p) for p in candidates)}"
    logger.error(error_msg)
    raise RuntimeError(error_msg)


def _build_feature_dataframe(features: dict) -> pd.DataFrame:
    missing_features = [feat for feat in MODEL_FEATURES if feat not in features]
    if missing_features:
        raise HTTPException(status_code=422, detail=f"Missing required feature(s): {', '.join(missing_features)}")

    converted = []
    for feat in MODEL_FEATURES:
        value = features[feat]
        if isinstance(value, bool):
            converted.append(int(value))
            continue
        if isinstance(value, (int, float)):
            converted.append(float(value))
            continue
        if isinstance(value, str):
            try:
                converted.append(float(value))
                continue
            except ValueError:
                raise HTTPException(status_code=422, detail=f"Invalid feature value for '{feat}': cannot convert '{value}' to float")
        raise HTTPException(status_code=422, detail=f"Invalid feature type for '{feat}': {type(value).__name__}")

    return pd.DataFrame([converted], columns=MODEL_FEATURES)


def _to_prediction_label(prediction) -> str:
    """将模型预测结果统一转换为 'Up' / 'Down' 字符串。
    
    兼容两种情况：
    - 旧模型: classes_ = ['Down', 'Up']，predict 返回字符串
    - 新模型: classes_ = [0, 1]，predict 返回整数
    """
    if prediction == 'Up' or prediction == 1:
        return 'Up'
    return 'Down'


def _up_probability_from_proba(proba: np.ndarray) -> float:
    """Estimate AP signal strength from predicted Up probability."""
    if hasattr(ml_model, 'classes_'):
        try:
            classes = list(ml_model.classes_)
            # 兼容整数类标 [0, 1] 和字符串类标 ['Down', 'Up']
            for up_label in [1, 'Up', 'up']:
                if up_label in classes:
                    return float(proba[classes.index(up_label)])
        except Exception:
            pass
    if proba.shape[-1] == 2:
        # Use the probability of the positive class when class labels are unknown.
        # proba[1] 通常是正类概率
        return float(proba[1])
    return float(proba[-1])


@app.get("/")
def root():
    return {
        "message": "API is working",
        "model_path": str(model_path),
        "graph_loaded": G is not None,
        "initialized": _initialized
    }


@app.get("/health")
async def health_check():
    """Health check endpoint for Render."""
    return {"status": "ok", "initialized": _initialized}


@app.get("/status")
async def full_status():
    """Detailed status endpoint for debugging."""
    return {
        "status": "ok",
        "initialized": _initialized,
        "graph_loaded": G is not None,
        "graph_nodes": len(G.nodes()) if G is not None else 0,
        "model_loaded": ml_model is not None,
        "model_path": str(model_path) if model_path else None,
        "ap_nodes_count": len(G_AP_nodes) if G_AP_nodes is not None else 0,
    }


@app.post("/predict/batch")
def predict_ap_status_batch(items: list[dict]):
    if not ml_model:
        raise HTTPException(status_code=503, detail="ML model not loaded yet")
    if not items:
        raise HTTPException(status_code=422, detail="No candidate items provided for batch prediction.")

    predictions = []
    for item in items:
        features = item.get('features') if isinstance(item, dict) and 'features' in item else item
        df = _build_feature_dataframe(features)
        prediction = ml_model.predict(df)[0]
        probability = ml_model.predict_proba(df)[0]
        up_prob = _up_probability_from_proba(probability)
        predictions.append({
            'input': features,
            'prediction': _to_prediction_label(prediction),
            'confidence': round(float(max(probability)), 3),
            'up_probability': round(up_prob * 100, 1),
            'score': round(float(np.max(probability)), 3)
        })

    return {'predictions': predictions, 'count': len(predictions)}


@app.get("/recommend/{lat}/{lng}/{radius}/{min_range}/{max_range}")
def recommend(lng: float, lat: float, radius: int, min_range: float, max_range: float):
    return {
        "message": "Historical AP candidate recommendation is disabled. Use /predict or /predict/batch with current AP feature vectors.",
        "current_location": {"lat": lat, "lng": lng},
        "radius": radius,
        "range": {"min": min_range, "max": max_range}
    }


@app.get("/route/{lat}/{lng}/{dest_lat}/{dest_lng}")
def route(lat: float, lng: float, dest_lat: float, dest_lng: float):
    if G is None:
        raise HTTPException(status_code=503, detail="Graph not loaded yet. Try again in a few seconds.")
    
    logger.info(f"Route request: from ({lat}, {lng}) to ({dest_lat}, {dest_lng})")
    try:
        source_node = ox.distance.nearest_nodes(G, lng, lat)
        dest_node = ox.distance.nearest_nodes(G, dest_lng, dest_lat)
        logger.info(f"Nearest nodes: source={source_node}, dest={dest_node}")
        
        # 解析 AP 节点（字符串）为路网节点（整数）
        dest_node = _resolve_to_road_node(G, dest_node, lat=dest_lat, lng=dest_lng)
        source_node = _resolve_to_road_node(G, source_node, lat=lat, lng=lng)
        
        # 确保 source 和 dest 都是整数，否则无法路由
        if isinstance(source_node, str) or isinstance(dest_node, str):
            logger.warning(f"Cannot route with string nodes: source={source_node}, dest={dest_node}")
            return {"path": []}
        
        try:
            path_nodes = nx.shortest_path(G, source=source_node, target=dest_node, weight='length')
        except nx.NetworkXNoPath:
            logger.warning(f"No path found between {source_node} and {dest_node}")
            return {"path": []}
        
        path_coords = [{"lat": G.nodes[n]['y'], "lng": G.nodes[n]['x']} for n in path_nodes]
        return {"path": path_coords}
    except Exception as e:
        logger.error(f"Route error: {e}", exc_info=True)
        return {"path": [], "message": f"Routing error: {str(e)}"}


def _resolve_to_road_node(G, node_id, lat=None, lng=None):
    """
    如果 node_id 是 AP 节点（字符串类型），找到它最近的 OSM 路网节点。
    OSM 路网节点是整数类型。
    
    使用欧几里得距离手动找最近的路网节点，避免 ox.distance.nearest_nodes 的兼容性问题。
    """
    # 如果节点已经是整数（OSM 路网节点），直接返回
    # 兼容 numpy 整数类型（numpy.int64, numpy.int32 等）
    if isinstance(node_id, (int, np.integer)):
        return int(node_id)
    
    # 如果是字符串节点（AP 或室内节点），找最近的 OSM 路网节点
    logger.info(f"Node '{node_id}' is a string node, finding nearest road node")
    
    # 获取该节点的坐标
    if node_id in G:
        node_lat = G.nodes[node_id].get('y', lat)
        node_lng = G.nodes[node_id].get('x', lng)
    else:
        node_lat = lat
        node_lng = lng
    
    if node_lat is None or node_lng is None:
        logger.warning(f"Node '{node_id}' has no coordinates, cannot resolve")
        return node_id
    
    # 收集所有路网节点
    # 注意：OSM 节点 ID 可能是 numpy.int64 类型，也可能是 Python int 类型
    # 使用更宽松的检查：排除字符串类型的就是路网节点
    road_nodes = []
    for n in G.nodes():
        if isinstance(n, str):
            continue  # 跳过 AP 节点和室内节点
        try:
            int(n)  # 如果能转为 int，就是路网节点
            road_nodes.append(n)
        except (ValueError, TypeError):
            continue
    
    if not road_nodes:
        logger.warning(f"No road nodes found in graph! Total nodes: {len(G.nodes())}")
        # 调试：打印前10个节点的类型
        for i, n in enumerate(G.nodes()):
            if i >= 10:
                break
            logger.warning(f"  Node sample: {n} (type={type(n).__name__})")
        return node_id
    
    logger.info(f"Searching among {len(road_nodes)} road nodes for nearest to ({node_lat}, {node_lng})")
    
    # 手动计算欧几里得距离找最近的路网节点
    try:
        import math
        best_node = None
        best_dist = float('inf')
        for rn in road_nodes:
            try:
                rn_lat = G.nodes[rn].get('y', None)
                rn_lng = G.nodes[rn].get('x', None)
                if rn_lat is None or rn_lng is None:
                    continue
                dist = (rn_lat - node_lat)**2 + (rn_lng - node_lng)**2
                if dist < best_dist:
                    best_dist = dist
                    best_node = rn
            except Exception:
                continue
        if best_node is not None:
            best_node = int(best_node)
            logger.info(f"Resolved '{node_id}' -> road node {best_node} (euclidean dist={math.sqrt(best_dist):.6f})")
            return best_node
    except Exception as e:
        logger.warning(f"Manual road node search failed: {e}")
    
    logger.warning(f"Failed to resolve '{node_id}' to any road node")
    return node_id


@app.get("/route/advanced/{lat}/{lng}/{dest_lat}/{dest_lng}")
def advanced_route(lat: float, lng: float, dest_lat: float, dest_lng: float, acceptable_range: int = 500):
    """
    Advanced routing using find_paths_to_candidates from helper_script.
    Finds multiple candidate paths within an acceptable range of the destination.
    Returns the best path along with alternative options.
    """
    if G is None:
        raise HTTPException(status_code=503, detail="Graph not loaded yet. Try again in a few seconds.")
    
    error_msg = ""  # Store error for fallback message
    
    try:
        source_node = ox.distance.nearest_nodes(G, lng, lat)
        dest_node = ox.distance.nearest_nodes(G, dest_lng, dest_lat)
        
        # 如果 dest_node 是 AP 节点（字符串），解析为路网节点
        dest_node = _resolve_to_road_node(G, dest_node, lat=dest_lat, lng=dest_lng)
        source_node = _resolve_to_road_node(G, source_node, lat=lat, lng=lng)
        
        # 确保 source 和 dest 都是整数（路网节点），否则后续 shortest_path 会失败
        if isinstance(source_node, str) or isinstance(dest_node, str):
            logger.warning(f"Cannot route with string nodes: source={source_node}, dest={dest_node}")
            return {"path": [], "alternatives": [], "message": "Cannot resolve nodes to road network"}
        
        # Find qualified nodes within acceptable range of destination
        qualified_candidates = find_qualified_in_range(
            G=G, 
            original_target=dest_node, 
            acceptable_range=acceptable_range
        )
        
        if not qualified_candidates:
            # Fallback to basic routing
            path_nodes = nx.shortest_path(G, source=source_node, target=dest_node, weight='length')
            path_coords = [{"lat": G.nodes[n]['y'], "lng": G.nodes[n]['x']} for n in path_nodes]
            return {
                "path": path_coords,
                "alternatives": [],
                "message": "No candidates found in range, using direct path"
            }
        
        # Find paths to all candidates
        candidate_paths = find_paths_to_candidates(
            G=G,
            source=source_node,
            target_neighbours=qualified_candidates
        )
        
        if not candidate_paths:
            return {"path": [], "alternatives": [], "message": "No paths found to candidates"}
        
        # Sort candidates by cost (distance) and filter out unreachable (inf cost)
        # This prevents JSON serialization failure from float('inf') values
        sorted_candidates = sorted(
            ((c, (cost, path)) for c, (cost, path) in candidate_paths.items() if cost != float('inf')),
            key=lambda x: x[1][0]
        )
        
        if not sorted_candidates:
            # All candidates are unreachable, fallback to basic shortest path routing
            path_nodes = nx.shortest_path(G, source=source_node, target=dest_node, weight='length')
            path_coords = [{"lat": G.nodes[n]['y'], "lng": G.nodes[n]['x']} for n in path_nodes]
            return {
                "path": path_coords,
                "alternatives": [],
                "message": "All candidates unreachable, using direct path"
            }
        
        # Best path (shortest)
        best_candidate, (best_cost, best_path) = sorted_candidates[0]
        best_path_coords = [{"lat": G.nodes[n]['y'], "lng": G.nodes[n]['x']} for n in best_path]
        
        # Alternative paths (up to 3)
        alternatives = []
        for candidate, (cost, path) in sorted_candidates[1:4]:
            if len(path) > 1:  # Valid path
                path_coords = [{"lat": G.nodes[n]['y'], "lng": G.nodes[n]['x']} for n in path]
                alternatives.append({
                    "path": path_coords,
                    "distance": round(cost, 2),
                    "endpoint": {
                        "lat": G.nodes[candidate]['y'],
                        "lng": G.nodes[candidate]['x']
                    }
                })
        
        return {
            "path": best_path_coords,
            "alternatives": alternatives,
            "distance": round(best_cost, 2),
            "message": "Route calculated with alternatives"
        }
        
    except nx.NetworkXNoPath:
        return {"path": [], "alternatives": [], "message": "No path found"}
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Advanced routing error: {e}", exc_info=True)
        # Fallback to basic routing
        try:
            source_node = ox.distance.nearest_nodes(G, lng, lat)
            dest_node = ox.distance.nearest_nodes(G, dest_lng, dest_lat)
            # 同样解析 AP 节点
            dest_node = _resolve_to_road_node(G, dest_node, lat=dest_lat, lng=dest_lng)
            source_node = _resolve_to_road_node(G, source_node, lat=lat, lng=lng)
            
            # 确保 source 和 dest 都是整数（路网节点），否则 shortest_path 会失败
            if isinstance(source_node, str) or isinstance(dest_node, str):
                logger.warning(f"Cannot use shortest_path with string nodes: source={source_node}, dest={dest_node}")
                return {"path": [], "alternatives": [], "message": f"Routing failed: cannot resolve nodes to road network. {error_msg}"}
            
            path_nodes = nx.shortest_path(G, source=source_node, target=dest_node, weight='length')
            path_coords = [{"lat": G.nodes[n]['y'], "lng": G.nodes[n]['x']} for n in path_nodes]
            return {
                "path": path_coords,
                "alternatives": [],
                "message": f"Advanced routing failed, using fallback: {error_msg}"
            }
        except nx.NetworkXNoPath:
            return {"path": [], "alternatives": [], "message": "No path found in fallback"}
        except Exception as fallback_err:
            return {"path": [], "alternatives": [], "message": f"Routing failed: {error_msg} | Fallback: {str(fallback_err)}"}


@app.post("/predict")
def predict_ap_status(features: dict):
    """
    Predict AP status using the trained Decision Tree ML model.
    Required features: client_count, cpu_utilization, mem_free, mem_total,
                       last_modified, hour, mem_usage, overloaded
    """
    if not ml_model:
        raise HTTPException(status_code=503, detail="ML model not loaded yet")
    
    df = _build_feature_dataframe(features)
    prediction = ml_model.predict(df)[0]
    prediction_proba = ml_model.predict_proba(df)[0]
    up_prob = _up_probability_from_proba(prediction_proba)
    pred_label = _to_prediction_label(prediction)
    confidence = float(max(prediction_proba))

    return {
        "prediction": pred_label,
        "confidence": round(confidence, 3),
        "up_probability": round(up_prob * 100, 1),
        "model": "Decision Tree",
        "features_used": features
    }


# ---- Signal Strength Prediction Endpoints ----
# Predicts REAL signal strength (dBm) based on building, floor, and hour
# Uses precomputed heatmap files for instant response

PRECOMPUTED_DIR = BASE_DIR / 'precomputed'

# In-memory cache for precomputed heatmap data
_heatmap_cache: dict = {}


def _get_day_type() -> str:
    """根据当前日期返回 'weekday' 或 'weekend'"""
    from datetime import datetime
    today = datetime.now()
    return 'weekend' if today.weekday() >= 5 else 'weekday'


def _load_precomputed_heatmap(hour: int) -> dict:
    """从预计算文件加载 heatmap 数据（自动区分 weekday/weekend）"""
    day_type = _get_day_type()
    cache_key = f'{day_type}_{hour}'
    
    if cache_key not in _heatmap_cache:
        filepath = PRECOMPUTED_DIR / day_type / f'heatmap_h{hour}.json'
        if not filepath.exists():
            raise HTTPException(status_code=500, detail=f"Precomputed heatmap not found for {day_type}/hour {hour}")
        with open(filepath) as f:
            import json
            _heatmap_cache[cache_key] = json.load(f)
    return _heatmap_cache[cache_key]


@app.get("/predict/signal_strength/heatmap")
def get_signal_heatmap(hour: int = -1):
    """
    获取热力图数据（从预计算文件读取，毫秒级响应）
    
    自动根据当前日期区分 weekday/weekend，返回对应的热力图数据。
    返回包含两种数据：
    - ap_points: 每个 AP 点的信号强度预测
    - smooth_grid: IDW 插值的平滑网格
    
    参数:
        hour (int, 默认当前时间): 小时 (0-23)
    """
    if hour < 0 or hour > 23:
        from datetime import datetime
        hour = datetime.now().hour
    
    return _load_precomputed_heatmap(hour)


@app.get("/predict/signal_strength/buildings")
def list_available_buildings():
    """列出所有可用的建筑（从预计算数据中提取）"""
    data = _load_precomputed_heatmap(0)
    ap_points = data.get("ap_points", {})
    return {
        "buildings": ap_points.get("buildings", []),
        "count": ap_points.get("buildings_count", 0),
    }


# 趋势数据缓存：{ap_name: {day_type: {hour: data}}}
_trend_cache: dict = {}
TREND_CACHE_TTL = 300  # 5分钟缓存


def _build_ap_index() -> dict:
    """构建 AP 名称到所有小时数据的索引，加速趋势查询"""
    index: dict = {}
    for hour in range(24):
        try:
            data = _load_precomputed_heatmap(hour)
            ap_points = data.get("ap_points", {})
            points = ap_points.get("points", [])
            for point in points:
                ap_name = point.get("ap_name")
                if ap_name:
                    if ap_name not in index:
                        index[ap_name] = {}
                    index[ap_name][hour] = {
                        "signal_db": point["signal_db"],
                        "signal_quality": point["signal_quality"],
                        "bars": point["bars"],
                    }
        except Exception:
            pass
    return index


_ap_index_cache: dict = {}
_ap_index_timestamp: float = 0


def _get_ap_index() -> dict:
    """获取 AP 索引（带缓存）"""
    global _ap_index_cache, _ap_index_timestamp
    now = __import__('time').time()
    if not _ap_index_cache or (now - _ap_index_timestamp) > TREND_CACHE_TTL:
        _ap_index_cache = _build_ap_index()
        _ap_index_timestamp = now
        logger.info(f"Built AP index with {len(_ap_index_cache)} APs")
    return _ap_index_cache


@app.get("/predict/signal_strength/ap_trend/{ap_name}")
def get_ap_daily_trend(ap_name: str):
    """
    获取指定AP在24小时内的信号强度变化趋势。
    
    使用预构建的 AP 索引快速查询，支持 weekday/weekend 切换。
    返回24个数据点（每小时一个），包含 signal_db、signal_quality 和 bars。
    """
    from urllib.parse import unquote
    ap_name = unquote(ap_name)
    
    index = _get_ap_index()
    ap_data = index.get(ap_name, {})
    
    trend_data = []
    for hour in range(24):
        if hour in ap_data:
            trend_data.append({
                "hour": hour,
                **ap_data[hour],
            })
        else:
            trend_data.append({
                "hour": hour,
                "signal_db": None,
                "signal_quality": None,
                "bars": None,
            })
    
    # 计算统计信息
    valid_signals = [d["signal_db"] for d in trend_data if d["signal_db"] is not None]
    stats = {}
    if valid_signals:
        stats = {
            "avg_db": round(sum(valid_signals) / len(valid_signals), 1),
            "max_db": max(valid_signals),
            "min_db": min(valid_signals),
            "best_hour": trend_data[valid_signals.index(max(valid_signals))]["hour"],
            "worst_hour": trend_data[valid_signals.index(min(valid_signals))]["hour"],
        }
    
    return {
        "ap_name": ap_name,
        "day_type": _get_day_type(),
        "trend": trend_data,
        "total_hours": len(trend_data),
        "stats": stats,
    }


@app.get("/predict/signal_strength/ap_trend/{ap_name}/compare")
def get_ap_trend_compare(ap_name: str):
    """
    对比指定AP在 weekday 和 weekend 的信号强度趋势。
    """
    from urllib.parse import unquote
    ap_name = unquote(ap_name)
    
    # 临时切换 day_type 来加载 weekend 数据
    global _heatmap_cache
    original_cache = dict(_heatmap_cache)
    
    results = {}
    for day_type in ['weekday', 'weekend']:
        # 清除缓存强制重新加载
        _heatmap_cache = {k: v for k, v in original_cache.items() if k.startswith(day_type)}
        
        index = _get_ap_index()
        ap_data = index.get(ap_name, {})
        
        trend = []
        for hour in range(24):
            if hour in ap_data:
                trend.append({
                    "hour": hour,
                    **ap_data[hour],
                })
            else:
                trend.append({
                    "hour": hour,
                    "signal_db": None,
                    "signal_quality": None,
                    "bars": None,
                })
        
        valid_signals = [d["signal_db"] for d in trend if d["signal_db"] is not None]
        stats = {}
        if valid_signals:
            stats = {
                "avg_db": round(sum(valid_signals) / len(valid_signals), 1),
                "max_db": max(valid_signals),
                "min_db": min(valid_signals),
            }
        
        results[day_type] = {
            "trend": trend,
            "stats": stats,
        }
    
    # 恢复缓存
    _heatmap_cache = original_cache
    
    return {
        "ap_name": ap_name,
        "weekday": results["weekday"],
        "weekend": results["weekend"],
    }


@app.get("/cache/status")
def cache_status():
    """查看缓存状态"""
    return {
        "heatmap_cache": {
            "size": len(_heatmap_cache),
            "hours_loaded": sorted(_heatmap_cache.keys()),
        },
        "precomputed_files": {
            "total_hours": 24,
            "directory": str(PRECOMPUTED_DIR),
        }
    }


if __name__ == "__main__":
    import uvicorn
    # Run with more workers for production
    uvicorn.run(app, host="0.0.0.0", port=8000)
