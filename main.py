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
        
        # 2. Load signal strength model
        try:
            load_signal_model()
            logger.info("Signal strength model loaded successfully")
        except Exception as e:
            logger.warning(f"Signal strength model not loaded: {e}")
        
        # 3. Load graph (heavy, may time out - but we catch errors gracefully)
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
# Predicts REAL signal strength (dBm) based on building, floor, hour, and band
# Trained on actual signal_db values from clientes_processed.csv

SIGNAL_MODEL_PATH = BASE_DIR / 'models' / 'signal_strength_model.joblib'
SIGNAL_META_PATH = BASE_DIR / 'models' / 'signal_strength_meta.joblib'
BUILDING_ENCODER_PATH = BASE_DIR / 'models' / 'building_encoder.joblib'
_signal_model = None
_signal_feature_names = None
_building_encoder = None
_buildings_list = None


def load_signal_model(force: bool = False):
    """Load the signal strength regression model (lazy-loaded)."""
    global _signal_model, _signal_feature_names, _building_encoder, _buildings_list
    if _signal_model is not None and not force:
        return _signal_model, _signal_feature_names, _building_encoder, _buildings_list

    if not SIGNAL_MODEL_PATH.exists():
        logger.warning("Signal strength model not found at %s", SIGNAL_MODEL_PATH)
        return None, None, None, None

    try:
        _signal_model = joblib.load(SIGNAL_MODEL_PATH)
        if SIGNAL_META_PATH.exists():
            meta = joblib.load(SIGNAL_META_PATH)
            _signal_feature_names = meta.get('feature_names', ['building_code', 'floor', 'hour', 'band'])
            _buildings_list = meta.get('buildings', [])
        if BUILDING_ENCODER_PATH.exists():
            _building_encoder = joblib.load(BUILDING_ENCODER_PATH)
        logger.info("Loaded signal strength model from %s", SIGNAL_MODEL_PATH)
        logger.info(f"  Buildings: {len(_buildings_list) if _buildings_list else 0}")
        return _signal_model, _signal_feature_names, _building_encoder, _buildings_list
    except Exception as e:
        logger.error("Failed to load signal strength model: %s", e)
        return None, None, None, None


def _build_signal_features(features: dict) -> pd.DataFrame:
    """
    Build feature vector for signal strength prediction.
    
    Input features:
    - building: str (building name, e.g. 'ETSE', 'FAC.DRET', 'BIBLIOTECA HUMANITATS')
    - floor: int/float (floor number, e.g. 0, 1, 2, -1)
    - hour: int/float (hour of day, 0-23)
    - band: int/float (5 for 5GHz, 2.4 for 2.4GHz, default: 5)
    """
    global _building_encoder, _buildings_list
    
    building_name = str(features.get('building', 'Unknown'))
    floor = float(features.get('floor', 0) or 0)
    hour = float(features.get('hour', 12) or 12)
    band = float(features.get('band', 5.0) or 5.0)
    
    # Encode building name
    building_code = 0  # default fallback
    if _building_encoder is not None:
        if building_name in _building_encoder.classes_:
            building_code = int(_building_encoder.transform([building_name])[0])
        elif _buildings_list:
            # Try to find closest match
            for i, b in enumerate(_buildings_list):
                if building_name.lower() in b.lower() or b.lower() in building_name.lower():
                    building_code = i
                    break
    
    signal_features = {
        'building_code': building_code,
        'floor': floor,
        'hour': hour,
        'band': band,
    }
    
    df = pd.DataFrame([signal_features])
    return df


def _dbm_to_quality_text(dbm: float) -> dict:
    """Convert dBm value to quality description."""
    if dbm >= -50:
        return {"quality": "Excellent", "color": "green", "bars": 5}
    elif dbm >= -60:
        return {"quality": "Good", "color": "yellow", "bars": 4}
    elif dbm >= -70:
        return {"quality": "Fair", "color": "orange", "bars": 3}
    elif dbm >= -80:
        return {"quality": "Weak", "color": "red", "bars": 2}
    else:
        return {"quality": "Very Poor", "color": "darkred", "bars": 1}


@app.post("/predict/signal_strength")
def predict_signal_strength(features: dict):
    """
    Predict REAL signal strength (dBm) based on building, floor, hour, and band.
    
    Uses Random Forest regression model trained on 355,522 real client signal measurements.
    
    Input:
    - building (required): Building name (e.g. 'ETSE', 'FAC.DRET', 'BIBLIOTECA HUMANITATS')
    - floor (optional, default: 0): Floor number
    - hour (optional, default: current): Hour of day (0-23)
    - band (optional, default: 5): Frequency band (5 for 5GHz, 2.4 for 2.4GHz)
    
    Returns:
    - signal_db: Predicted signal strength in dBm (-97 to -22 range)
    - quality: Quality description (Excellent/Good/Fair/Weak/Very Poor)
    - bars: Signal bars (1-5)
    """
    model, _, _, buildings = load_signal_model()
    if model is None:
        raise HTTPException(status_code=503, detail="Signal strength model not available")
    
    # Set default hour to current time if not provided
    if 'hour' not in features or features['hour'] is None:
        from datetime import datetime
        features['hour'] = datetime.now().hour
    
    df = _build_signal_features(features)
    predicted_dbm = float(model.predict(df)[0])
    
    quality_info = _dbm_to_quality_text(predicted_dbm)
    
    return {
        "signal_db": round(predicted_dbm, 1),
        "signal_quality": quality_info["quality"],
        "bars": quality_info["bars"],
        "target_unit": "dBm",
        "model": "RandomForestRegressor (trained on real signal data)",
        "n_training_samples": 355522,
        "features_used": {
            "building": str(features.get('building', 'Unknown')),
            "floor": float(features.get('floor', 0) or 0),
            "hour": float(features.get('hour', 12) or 12),
            "band": float(features.get('band', 5.0) or 5.0),
        }
    }


@app.get("/predict/signal_strength/buildings")
def list_available_buildings():
    """List all buildings available for signal strength prediction."""
    _, _, _, buildings = load_signal_model()
    if not buildings:
        raise HTTPException(status_code=503, detail="Signal strength model not available")
    return {
        "buildings": buildings,
        "count": len(buildings),
        "model_path": str(SIGNAL_MODEL_PATH)
    }


@app.get("/predict/signal_strength/heatmap")
def get_signal_heatmap(hour: float = -1, band: float = 5.0):
    """
    Generate heatmap data: predicted signal strength for ALL APs across all buildings.
    Returns GeoJSON-like format with coordinates + predicted signal_db.
    
    This endpoint processes all APs from the GeoJSON file and predicts
    signal strength for each based on its building, floor, and given time.
    
    Use this data to render a color-coded heatmap on the frontend.
    """
    import json as _json
    
    model, _, _, buildings = load_signal_model()
    if model is None:
        raise HTTPException(status_code=503, detail="Signal strength model not available")
    
    # Set default hour
    if hour < 0:
        from datetime import datetime
        hour = float(datetime.now().hour)
    
    # Load GeoJSON
    geojson_path = BASE_DIR / 'geolocation_package' / 'data' / 'aps_geolocalizados_wgs84.geojson'
    if not geojson_path.exists():
        raise HTTPException(status_code=404, detail="GeoJSON file not found")
    
    with open(geojson_path) as f:
        geojson_data = _json.load(f)
    
    heatmap_points = []
    processed_buildings = set()
    
    for feature in geojson_data['features']:
        props = feature['properties']
        coords = feature['geometry']['coordinates']
        
        ap_name = props.get('USER_NOM_A', 'Unknown')
        building = props.get('USER_EDIFI', 'Unknown')
        floor = props.get('Num_Planta', 0)
        
        if building == 'Unknown' or not building:
            continue
        
        # Predict signal for this AP's building/floor
        signal_features = {
            'building': building,
            'floor': float(floor) if floor is not None else 0.0,
            'hour': hour,
            'band': band,
        }
        
        try:
            df = _build_signal_features(signal_features)
            predicted_dbm = float(model.predict(df)[0])
        except Exception:
            continue
        
        quality_info = _dbm_to_quality_text(predicted_dbm)
        
        heatmap_points.append({
            "lat": float(coords[1]),
            "lng": float(coords[0]),
            "signal_db": round(predicted_dbm, 1),
            "signal_quality": quality_info["quality"],
            "bars": quality_info["bars"],
            "ap_name": ap_name,
            "building": building,
            "floor": int(floor) if floor is not None else 0,
        })
        processed_buildings.add(building)
    
    return {
        "type": "heatmap",
        "hour": hour,
        "band": band,
        "total_points": len(heatmap_points),
        "buildings_count": len(processed_buildings),
        "buildings": sorted(list(processed_buildings)),
        "points": heatmap_points,
        "legend": {
            "Excellent": {"min_db": -50, "max_db": 0, "color": "green", "bars": 5},
            "Good": {"min_db": -60, "max_db": -50, "color": "yellow", "bars": 4},
            "Fair": {"min_db": -70, "max_db": -60, "color": "orange", "bars": 3},
            "Weak": {"min_db": -80, "max_db": -70, "color": "red", "bars": 2},
            "Very Poor": {"min_db": -100, "max_db": -80, "color": "darkred", "bars": 1},
        }
    }


# 平滑热力图结果缓存：键为 (hour, band)，避免重复计算
_heatmap_smooth_cache: dict = {}

@app.get("/predict/signal_strength/heatmap_smooth")
def get_signal_heatmap_smooth(hour: float = -1, band: float = 5.0, resolution: int = 30):
    """
    平滑热力图端点 (Smooth Heatmap)
    
    在全校园区域生成一个密集的经纬度网格，对每个网格点使用反距离加权插值 (IDW)
    预测信号强度，生成连续渐变的信号热力图。
    
    参数:
        hour (float, 默认当前时间): 预测的小时 (0-23)
        band (float, 默认 5.0): 频段 (5 或 2.4)
        resolution (int, 默认 50): 网格密度（行数=列数=resolution），值越高网格越密
                                   - 50 → ~2500 个点，点间距约 30 米
                                   - 30 → ~900 个点，点间距约 50 米
                                   - 80 → ~6400 个点，点间距约 18 米
    
    返回:
        type: "heatmap_smooth"
        grid_size: 网格尺寸 (rows, cols)
        total_points: 总点数
        bounds: 校园边界坐标
        points: 每个网格点的经纬度 + 预测信号强度 + 质量等级
        legend: 颜色映射图例
    """
    import json as _json
    from math import radians, cos, sin, asin, sqrt

    model, _, _, buildings = load_signal_model()
    if model is None:
        raise HTTPException(status_code=503, detail="Signal strength model not available")

    # 设置默认时间
    if hour < 0:
        from datetime import datetime
        hour = float(datetime.now().hour)

    # 检查缓存：相同 hour + band 的结果直接返回，避免重复计算
    cache_key = (int(hour), float(band))
    if cache_key in _heatmap_smooth_cache:
        logger.info(f"Returning cached smooth heatmap for hour={hour}, band={band}")
        return _heatmap_smooth_cache[cache_key]

    # ================================================================
    # 第一步：加载 GeoJSON 中的所有 AP，预测每个 AP 的信号强度
    #         同时记录每个 AP 的经纬度坐标和预测值
    # ================================================================
    geojson_path = BASE_DIR / 'geolocation_package' / 'data' / 'aps_geolocalizados_wgs84.geojson'
    if not geojson_path.exists():
        raise HTTPException(status_code=404, detail="GeoJSON file not found")

    with open(geojson_path) as f:
        geojson_data = _json.load(f)

    # 存储 AP 点的列表: [(lat, lng, signal_db), ...]
    ap_points = []
    ap_building_map = {}

    for feature in geojson_data['features']:
        props = feature['properties']
        coords = feature['geometry']['coordinates']

        ap_name = props.get('USER_NOM_A', 'Unknown')
        building = props.get('USER_EDIFI', 'Unknown')
        floor = props.get('Num_Planta', 0)

        if building == 'Unknown' or not building:
            continue

        # 预测该 AP 位置的信号强度
        signal_features = {
            'building': building,
            'floor': float(floor) if floor is not None else 0.0,
            'hour': hour,
            'band': band,
        }

        try:
            df = _build_signal_features(signal_features)
            predicted_dbm = float(model.predict(df)[0])
        except Exception:
            continue

        lat = float(coords[1])
        lng = float(coords[0])

        ap_points.append({
            'lat': lat,
            'lng': lng,
            'signal_db': predicted_dbm,
            'building': building,
            'floor': int(floor) if floor is not None else 0,
        })

        # 记录每个建筑物的 AP 列表（用于后续加权）
        if building not in ap_building_map:
            ap_building_map[building] = []
        ap_building_map[building].append({
            'lat': lat,
            'lng': lng,
            'signal_db': predicted_dbm,
        })

    if not ap_points:
        raise HTTPException(status_code=500, detail="No AP data available for heatmap generation")

    # ================================================================
    # 第二步：确定校园边界，生成密集经纬度网格
    # ================================================================
    # UAB 校园边界 (从全局变量 UAB_bbox 获取)
    north, south, east, west = UAB_bbox  # 41.50736, 41.49505, 2.11543, 2.09491

    # 在边界内加一点内缩，避免边缘网格点落在校园外
    margin_lat = (north - south) * 0.02
    margin_lng = (east - west) * 0.02
    lat_min = south + margin_lat
    lat_max = north - margin_lat
    lng_min = west + margin_lng
    lng_max = east - margin_lng

    # 生成网格
    lat_steps = resolution
    lng_steps = resolution
    lat_grid = [lat_min + (lat_max - lat_min) * i / (lat_steps - 1) for i in range(lat_steps)]
    lng_grid = [lng_min + (lng_max - lng_min) * i / (lng_steps - 1) for i in range(lng_steps)]


    def haversine_distance(lat1, lng1, lat2, lng2):
        """计算两点间的大圆距离 (单位: 米)"""
        R = 6371000  # 地球半径 (米)
        dlat = radians(lat2 - lat1)
        dlng = radians(lng2 - lng1)
        a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
        c = 2 * asin(sqrt(a))
        return R * c


    def idw_interpolate(target_lat, target_lng, source_points, power=2, max_dist=300):
        """
        反距离加权插值 (Inverse Distance Weighting)
        
        参数:
            target_lat, target_lng: 待插值点的坐标
            source_points: 源数据点列表，每项为 {'lat': ..., 'lng': ..., 'signal_db': ...}
            power: 距离的幂次（越大则近处点的权重越大），默认 2
            max_dist: 最大有效距离（米），超过此距离的点不考虑
        
        返回:
            插值后的信号强度值 (dBm)
        """
        weights = []
        values = []
        total_weight = 0.0

        for pt in source_points:
            dist = haversine_distance(target_lat, target_lng, pt['lat'], pt['lng'])
            if dist < 1:  # 几乎重合
                return pt['signal_db']
            if dist > max_dist:  # 距离太远，忽略
                continue
            w = 1.0 / (dist ** power)
            weights.append(w)
            values.append(pt['signal_db'])
            total_weight += w

        if total_weight == 0:
            return None  # 没有足够的邻近点

        weighted_avg = sum(w * v for w, v in zip(weights, values)) / total_weight
        return weighted_avg


    # ================================================================
    # 第三步：对每个网格点进行 IDW 插值
    #         用该点附近所有 AP 的预测信号值按距离加权平均
    #         同时考虑建筑物信息：同一建筑物的 AP 权重加成
    # ================================================================
    smooth_points = []
    total = lat_steps * lng_steps
    processed_count = 0

    for lat in lat_grid:
        for lng in lng_grid:
            # 标准 IDW：用所有 AP 点做插值（默认 max_dist=300，仅考虑 300m 内的 AP）
            signal = idw_interpolate(lat, lng, ap_points, power=2)
            
            if signal is None:
                continue  # 该点无有效邻近 AP，跳过

            quality_info = _dbm_to_quality_text(signal)
            
            smooth_points.append({
                "lat": round(lat, 6),
                "lng": round(lng, 6),
                "signal_db": round(signal, 1),
                "signal_quality": quality_info["quality"],
                "bars": quality_info["bars"],
            })
            processed_count += 1

    logger.info(f"Smooth heatmap generated: {processed_count}/{total} grid points with signal estimates")

    result = {
        "type": "heatmap_smooth",
        "hour": hour,
        "band": band,
        "grid_size": {"rows": lat_steps, "cols": lng_steps, "total": total, "estimated": processed_count},
        "bounds": {
            "north": lat_max,
            "south": lat_min,
            "east": lng_max,
            "west": lng_min,
        },
        "total_points": len(smooth_points),
        "points": smooth_points,
        "legend": {
            "Excellent": {"min_db": -50, "max_db": 0, "color": "green", "bars": 5},
            "Good": {"min_db": -60, "max_db": -50, "color": "yellow", "bars": 4},
            "Fair": {"min_db": -70, "max_db": -60, "color": "orange", "bars": 3},
            "Weak": {"min_db": -80, "max_db": -70, "color": "red", "bars": 2},
            "Very Poor": {"min_db": -100, "max_db": -80, "color": "darkred", "bars": 1},
        }
    }
    _heatmap_smooth_cache[cache_key] = result
    return result


@app.get("/predict/signal_strength/predict")
def predict_signal_strength_get(
    building: str,
    floor: float = 0,
    hour: float = -1,
    band: float = 5.0
):
    """
    GET endpoint for signal strength prediction (easier to test in browser).
    """
    if hour < 0:
        from datetime import datetime
        hour = float(datetime.now().hour)
    
    features = {
        'building': building,
        'floor': floor,
        'hour': hour,
        'band': band
    }
    return predict_signal_strength(features)


if __name__ == "__main__":
    import uvicorn
    # Run with more workers for production
    uvicorn.run(app, host="0.0.0.0", port=8000)
