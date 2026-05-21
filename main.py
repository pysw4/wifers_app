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


def _up_probability_from_proba(proba: np.ndarray) -> float:
    """Estimate AP signal strength from predicted Up probability."""
    if hasattr(ml_model, 'classes_'):
        try:
            classes = list(ml_model.classes_)
            if 1 in classes:
                return float(proba[classes.index(1)])
            if 'Up' in classes:
                return float(proba[classes.index('Up')])
        except Exception:
            pass
    if proba.shape[-1] == 2:
        # Use the probability of the positive class when class labels are unknown.
        return float(max(proba))
    return float(max(proba))


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
            'prediction': 'Up' if prediction == 1 else 'Down',
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
        
        try:
            path_nodes = nx.shortest_path(G, source=source_node, target=dest_node, weight='length')
        except nx.NetworkXNoPath:
            logger.warning(f"No path found between {source_node} and {dest_node}")
            return {"path": []}
        
        path_coords = [{"lat": G.nodes[n]['y'], "lng": G.nodes[n]['x']} for n in path_nodes]
        return {"path": path_coords}
    except Exception as e:
        logger.error(f"Route error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Routing error: {str(e)}")


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
        
        # Sort candidates by cost (distance)
        sorted_candidates = sorted(candidate_paths.items(), key=lambda x: x[1][0])
        
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
    pred_label = 'Up' if prediction == 1 else 'Down'
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
