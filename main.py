from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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

# Use lifespan context manager instead of deprecated @app.on_event("startup")
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
        
        # 3. Preload current hour's heatmap (lightweight, ~1-2MB)
        try:
            from datetime import datetime
            current_hour = datetime.now().hour
            _load_hourly_file(current_hour)
            logger.info(f"Preloaded heatmap for hour {current_hour}")
        except Exception as e:
            logger.warning(f"Failed to preload heatmap: {e}")

    except Exception as e:
        logger.error(f"Startup initialization failed: {e}")
        _initialized = False
    
    yield  # Application running
    
    # Cleanup on shutdown
    logger.info("Shutting down application...")


app = FastAPI(lifespan=lifespan)

# CORS middleware — allow Flutter Web frontend to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://wifers-app-web.onrender.com",
        "http://localhost:3000",
        "http://localhost:5000",
        "http://localhost:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global variables for lazy-loaded resources
G = None
G_AP_nodes = None
G_road = None  # Subgraph containing only road nodes (integer nodes), used for nearest_nodes queries
ml_model = None
model_path = None
_initialized = False

# AP spatial index for fast nearest-AP lookup
_ap_coords = None  # list of (ap_name, lat, lng)
_ap_kdtree = None  # scipy.spatial.KDTree
_ap_name_to_data = None  # {ap_name: {building, floor, lat, lng}}

UAB_bbox = 41.50736, 41.49505, 2.11543, 2.09491
MODEL_FEATURES = [
    'client_count',
    'cpu_utilization',
    'mem_free',
    'mem_total',
    'last_modified',
    'hour',
    'mem_usage',
    'overloaded',
    'day_of_week',
    'is_weekend',
    'month',
    'day_of_month'
]


MODEL_FILE_NAME = 'decision_tree.joblib'
BASE_DIR = Path(__file__).resolve().parent
PRIMARY_MODEL_PATH = BASE_DIR / 'models' / MODEL_FILE_NAME
FALLBACK_MODEL_PATH = Path.cwd() / 'models' / MODEL_FILE_NAME


def init_graph(force: bool = False):
    """Initialize the OSM graph and AP nodes (lazy-loaded)."""
    global G, G_AP_nodes, G_road, _ap_coords, _ap_kdtree, _ap_name_to_data
    if G is not None and not force:
        return G, G_AP_nodes

    logger.info("Loading OSM graph for UAB area...")
    # bbox format: (left, bottom, right, top) = (west, south, east, north)
    osm_bbox = (UAB_bbox[3], UAB_bbox[1], UAB_bbox[2], UAB_bbox[0])
    G = ox.graph_from_bbox(bbox=osm_bbox, network_type="walk")
    
    # Create subgraph containing only road nodes (integer nodes) for nearest_nodes queries
    # This ensures ox.distance.nearest_nodes never returns AP string nodes
    road_nodes = [n for n in G.nodes() if not isinstance(n, str)]
    G_road = G.subgraph(road_nodes).copy()
    logger.info(f"Created road subgraph with {len(G_road.nodes())} nodes")


    
    logger.info("Adding AP nodes to graph...")
    G_AP_nodes = add_aps_to_graph(G, bbox=[UAB_bbox[3], UAB_bbox[0], UAB_bbox[2], UAB_bbox[1]])
    logger.info(f"Loaded graph with {len(G.nodes())} total nodes, {len(G_AP_nodes)} AP nodes added")
    
    # Build AP spatial index (KD-Tree) for O(log N) nearest-AP lookup
    _build_ap_spatial_index()
    
    return G, G_AP_nodes


def _build_ap_spatial_index():
    """Build a KD-Tree spatial index for fast nearest-AP lookup.
    
    This replaces the O(N × M) nested loop in recommend_aps with O(N log M).
    """
    global _ap_coords, _ap_kdtree, _ap_name_to_data
    from scipy.spatial import KDTree
    
    _ap_coords = []
    _ap_name_to_data = {}
    
    for ap_name in G_AP_nodes:
        ap_data = G.nodes[ap_name]
        ax = ap_data.get("x")
        ay = ap_data.get("y")
        if ax is None or ay is None:
            continue
        # Use (lat, lng) as coordinates for KD-Tree
        _ap_coords.append([ay, ax])
        _ap_name_to_data[ap_name] = {
            "lat": ay,
            "lng": ax,
            "building": ap_data.get("building", "Unknown"),
            "floor": ap_data.get("height", 0),
        }
    
    if _ap_coords:
        _ap_kdtree = KDTree(_ap_coords)
        logger.info(f"Built AP spatial index with {len(_ap_coords)} APs")
    else:
        logger.warning("No AP coordinates available for spatial index")


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
    """Convert model prediction to 'Up' / 'Down' string.
    
    Compatible with both cases:
    - Old model: classes_ = ['Down', 'Up'], predict returns string
    - New model: classes_ = [0, 1], predict returns integer
    """
    if prediction == 'Up' or prediction == 1:
        return 'Up'
    return 'Down'


def _up_probability_from_proba(proba: np.ndarray) -> float:
    """Estimate AP signal strength from predicted Up probability."""
    if hasattr(ml_model, 'classes_'):
        try:
            classes = list(ml_model.classes_)
            # Compatible with integer labels [0, 1] and string labels ['Down', 'Up']
            for up_label in [1, 'Up', 'up']:
                if up_label in classes:
                    return float(proba[classes.index(up_label)])
        except Exception:
            pass
    if proba.shape[-1] == 2:
            # Use the probability of the positive class when class labels are unknown.
        # proba[1] is typically the positive class probability
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


@app.post("/recommend")
def recommend_aps(body: dict):
    """
    Fast AP recommendation using graph + heatmap cache + ML model.
    
    Uses KD-Tree spatial index for O(N log M) nearest-AP lookup
    instead of O(N × M) nested loops.
    
    Request body:
    {
        "lat": 41.500,          // User latitude
        "lng": 2.111,           // User longitude
        "radius": 500,          // Search radius in meters
        "mode": "balanced",     // "distance" | "signal" | "balanced"
        "building": "",         // Optional building filter
        "prefer_stable": true   // Prefer stable APs
    }
    
    Returns top 5 recommended APs with scores, signal strength, and predictions.
    """
    if G is None or G_road is None:
        raise HTTPException(status_code=503, detail="Graph not loaded yet")
    if not ml_model:
        raise HTTPException(status_code=503, detail="ML model not loaded yet")
    if _ap_kdtree is None:
        raise HTTPException(status_code=503, detail="AP spatial index not built yet")
    
    lat = body.get("lat")
    lng = body.get("lng")
    radius = body.get("radius", 500)
    mode = body.get("mode", "balanced")
    building_filter = body.get("building", "")
    prefer_stable = body.get("prefer_stable", True)
    
    if lat is None or lng is None:
        raise HTTPException(status_code=422, detail="lat and lng are required")
    
    from datetime import datetime
    now = datetime.now()
    current_hour = now.hour
    current_day = now.weekday()  # 0=Mon
    
    try:
        # 1. Find nearest road node to user
        source_node = int(ox.distance.nearest_nodes(G_road, lng, lat))
        logger.info(f"Recommend: user at ({lat}, {lng}), nearest road node={source_node}")
        
        # 2. Find qualified nodes within radius (uses Dijkstra, unavoidable)
        qualified = find_qualified_in_range(G, source_node, acceptable_range=radius)
        if not qualified:
            return {"recommendations": [], "message": f"No reachable nodes within {radius}m"}
        
        # 3. Use KD-Tree to find nearest AP for each qualified node (O(N log M))
        #    Build a list of (lat, lng) for all qualified nodes
        qualified_coords = []
        valid_qualified = []
        for candidate in qualified:
            candidate_data = G.nodes[candidate]
            cx, cy = candidate_data.get("x"), candidate_data.get("y")
            if cx is None or cy is None:
                continue
            qualified_coords.append([cy, cx])  # (lat, lng)
            valid_qualified.append(candidate)
        
        if not qualified_coords:
            return {"recommendations": [], "message": "No reachable nodes with coordinates"}
        
        # Batch query KD-Tree: find nearest AP for each qualified node
        # Returns (distances, indices) where indices map to _ap_coords
        kd_distances, kd_indices = _ap_kdtree.query(qualified_coords, k=1)
        
        # Build ap_distances dict: {ap_name: {distance, lat, lng, building, floor}}
        ap_distances = {}
        ap_name_list = list(_ap_name_to_data.keys())
        
        for i, candidate in enumerate(valid_qualified):
            ap_idx = kd_indices[i]
            ap_name = ap_name_list[ap_idx]
            
            if ap_name in ap_distances:
                continue  # Already found this AP
            
            ap_info = _ap_name_to_data[ap_name]
            
            # Get walking distance from source to candidate
            try:
                dist = nx.dijkstra_path_length(G, source=source_node, target=candidate, weight='length')
            except (nx.NetworkXNoPath, Exception):
                dist = radius  # fallback
            
            ap_distances[ap_name] = {
                "distance": dist,
                "lat": ap_info["lat"],
                "lng": ap_info["lng"],
                "building": ap_info["building"],
                "floor": ap_info["floor"],
            }
        
        if not ap_distances:
            return {"recommendations": [], "message": "No APs found near reachable nodes"}
        
        # 4. Apply building filter
        if building_filter:
            ap_distances = {k: v for k, v in ap_distances.items() if v["building"] == building_filter}
            if not ap_distances:
                return {"recommendations": [], "message": f"No APs found in building '{building_filter}'"}
        
        # 5. Get signal strength from heatmap cache (memory, no disk I/O)
        try:
            heatmap_data = _get_hourly_data(current_hour)
            ap_points = heatmap_data.get("ap_points", {})
            points = ap_points.get("points", [])
            signal_map = {}  # {ap_name: {signal_db, signal_quality, bars}}
            for point in points:
                name = point.get("ap_name")
                if name:
                    signal_map[name] = {
                        "signal_db": point.get("signal_db", -70),
                        "signal_quality": point.get("signal_quality", "Fair"),
                        "bars": point.get("bars", 1),
                    }
        except Exception:
            signal_map = {}
        
        # 6. Batch predict AP status using ML model (vectorized)
        ap_names = list(ap_distances.keys())
        n_aps = len(ap_names)
        
        # Build feature matrix as numpy array for vectorized prediction
        feature_matrix = np.array([[
            10.0,           # client_count
            50.0,           # cpu_utilization
            1000.0,         # mem_free
            2000.0,         # mem_total
            1640995200.0,   # last_modified
            float(current_hour),
            50.0,           # mem_usage
            0.0 if prefer_stable else 1.0,  # overloaded
            float(current_day),
            1.0 if current_day >= 5 else 0.0,  # is_weekend
            float(now.month),
            float(now.day),
        ]] * n_aps)
        
        feature_df = pd.DataFrame(feature_matrix, columns=MODEL_FEATURES)
        batch_preds = ml_model.predict(feature_df)
        batch_probas = ml_model.predict_proba(feature_df)
        
        predictions = []
        for j in range(n_aps):
            pred = batch_preds[j]
            proba = batch_probas[j]
            up_prob = _up_probability_from_proba(proba)
            predictions.append({
                "prediction": _to_prediction_label(pred),
                "confidence": round(float(max(proba)), 3),
                "up_probability": round(up_prob * 100, 1),
            })
        
        # 7. Score and rank APs
        scored_aps = []
        for i, ap_name in enumerate(ap_names):
            info = ap_distances[ap_name]
            pred_info = predictions[i]
            signal = signal_map.get(ap_name, {"signal_db": -70, "signal_quality": "Fair", "bars": 1})
            
            distance = info["distance"]
            signal_db = signal["signal_db"]
            up_probability = pred_info["up_probability"]
            
            # Calculate scores (same logic as Flutter frontend)
            distance_score = max(0.0, 1.0 - (distance / radius))
            signal_score = max(0.0, min(1.0, (signal_db + 97.0) / 75.0))
            status_score = up_probability / 100.0
            
            if mode == "distance":
                score = distance_score * 0.8 + signal_score * 0.15 + status_score * 0.05
            elif mode == "signal":
                score = signal_score * 0.7 + status_score * 0.2 + distance_score * 0.1
            else:  # balanced
                stability_weight = 0.4 if prefer_stable else 0.25
                score = (status_score * stability_weight +
                        distance_score * (0.5 - stability_weight * 0.3) +
                        signal_score * (0.5 - stability_weight * 0.2))
            
            scored_aps.append({
                "id": ap_name,
                "name": ap_name,
                "building": info["building"],
                "floor": info["floor"],
                "lat": info["lat"],
                "lng": info["lng"],
                "distance": round(distance, 1),
                "prediction": pred_info["prediction"],
                "confidence": pred_info["confidence"],
                "up_probability": pred_info["up_probability"],
                "score": round(score, 4),
                "signal_db": signal_db,
                "signal_quality": signal["signal_quality"],
                "bars": signal["bars"],
            })
        
        # Sort by score descending, return top 5
        scored_aps.sort(key=lambda x: x["score"], reverse=True)
        top_aps = scored_aps[:5]
        
        return {
            "recommendations": top_aps,
            "count": len(top_aps),
            "total_candidates": len(scored_aps),
            "mode": mode,
            "message": f"Top {len(top_aps)} recommendations"
        }
        
    except Exception as e:
        logger.error(f"Recommend error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Recommendation failed: {str(e)}")



@app.get("/route/{lat}/{lng}/{dest_lat}/{dest_lng}")
def route(lat: float, lng: float, dest_lat: float, dest_lng: float):
    if G is None:
        raise HTTPException(status_code=503, detail="Graph not loaded yet. Try again in a few seconds.")
    
    logger.info(f"Route request: from ({lat}, {lng}) to ({dest_lat}, {dest_lng})")
    try:
        # Use G_road (subgraph containing only road nodes) to find nearest nodes, ensuring no AP string nodes are returned
        source_node = int(ox.distance.nearest_nodes(G_road, lng, lat))
        dest_node = int(ox.distance.nearest_nodes(G_road, dest_lng, dest_lat))
        logger.info(f"Nearest road nodes: source={source_node}, dest={dest_node}")
        
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
    If node_id is an AP node (string type), find its nearest OSM road node.
    OSM road nodes are integer type.
    
    Uses Euclidean distance to manually find the nearest road node,
    avoiding compatibility issues with ox.distance.nearest_nodes.
    """
    # If node is already an integer (OSM road node), return directly
    # Compatible with numpy integer types (numpy.int64, numpy.int32, etc.)
    if isinstance(node_id, (int, np.integer)):
        return int(node_id)
    
    # If it's a string node (AP or indoor node), find nearest OSM road node
    logger.info(f"Node '{node_id}' is a string node, finding nearest road node")
    
    # Get node coordinates
    if node_id in G:
        node_lat = G.nodes[node_id].get('y', lat)
        node_lng = G.nodes[node_id].get('x', lng)
    else:
        node_lat = lat
        node_lng = lng
    
    if node_lat is None or node_lng is None:
        logger.warning(f"Node '{node_id}' has no coordinates, cannot resolve")
        return node_id
    
    # Collect all road nodes
    # Note: OSM node IDs may be numpy.int64 or Python int type
    # Use lenient check: exclude string types to identify road nodes
    road_nodes = []
    for n in G.nodes():
        if isinstance(n, str):
            continue  # Skip AP nodes and indoor nodes
        try:
            int(n)  # If it can be converted to int, it's a road node
            road_nodes.append(n)
        except (ValueError, TypeError):
            continue
    
    if not road_nodes:
        logger.warning(f"No road nodes found in graph! Total nodes: {len(G.nodes())}")
        # Debug: print first 10 node types
        for i, n in enumerate(G.nodes()):
            if i >= 10:
                break
            logger.warning(f"  Node sample: {n} (type={type(n).__name__})")
        return node_id
    
    logger.info(f"Searching among {len(road_nodes)} road nodes for nearest to ({node_lat}, {node_lng})")
    
    # Manually calculate Euclidean distance to find nearest road node
    try:
        import math
        best_node = None
        best_dist = float('inf')
        for rn in road_nodes:
            try:
                # OSM nodes may use 'y'/'x' or 'lat'/'lon' keys
                rn_lat = G.nodes[rn].get('y', G.nodes[rn].get('lat', None))
                rn_lng = G.nodes[rn].get('x', G.nodes[rn].get('lon', None))
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
        # Use G_road (subgraph containing only road nodes) to find nearest nodes, ensuring no AP string nodes are returned
        source_node = int(ox.distance.nearest_nodes(G_road, lng, lat))
        dest_node = int(ox.distance.nearest_nodes(G_road, dest_lng, dest_lat))
        logger.info(f"Advanced route: source={source_node}, dest={dest_node}")
        
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
        # Fallback to basic routing using G_road
        try:
            source_node = int(ox.distance.nearest_nodes(G_road, lng, lat))
            dest_node = int(ox.distance.nearest_nodes(G_road, dest_lng, dest_lat))
            
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
# Predicts REAL signal strength (dBm) based on building, floor, hour, and day of week
# Uses individual precomputed heatmap files (one per hour per day) for instant response
# Night hours (0-6) use h3 as representative to save memory

PRECOMPUTED_DIR = BASE_DIR / 'precomputed'

# Day name mapping: 0=Mon, 6=Sun
DAY_NAMES = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']

# Night hours (0-6): mapped to representative h3
NIGHT_HOURS = list(range(0, 7))
NIGHT_REPRESENTATIVE = 3

# Simple LRU cache: stores the most recently read hourly file
# Each file is ~1-2MB, keeps at most 3 files in memory
_hourly_cache: dict = {}  # {cache_key: data}
_hourly_cache_keys: list = []  # ordered keys for LRU eviction
_HOURLY_CACHE_MAX = 3


def _get_day_name() -> str:
    """Return day name ('mon'/'tue'/.../'sun') based on current date"""
    from datetime import datetime
    today = datetime.now()
    return DAY_NAMES[today.weekday()]


def _load_hourly_file(hour: int, day_name: str = None) -> dict:
    """Load a single hourly heatmap file from precomputed/{day_name}/heatmap_h{hour}.json.
    
    Uses a small LRU cache (max 3 files) to avoid repeated disk I/O.
    Night hours (0-6) are mapped to the representative hour (h3).
    """
    global _hourly_cache, _hourly_cache_keys
    if day_name is None:
        day_name = _get_day_name()
    
    # Night hours use representative h3
    actual_hour = NIGHT_REPRESENTATIVE if hour in NIGHT_HOURS else hour
    
    cache_key = f"{day_name}_{actual_hour}"
    
    # Check cache
    if cache_key in _hourly_cache:
        # Move to end (most recently used)
        _hourly_cache_keys.remove(cache_key)
        _hourly_cache_keys.append(cache_key)
        data = _hourly_cache[cache_key]
        # Tag with requested hour info
        return {
            **data,
            "hour": hour,
            "is_night_representative": hour in NIGHT_HOURS,
            "representative_hour": NIGHT_REPRESENTATIVE if hour in NIGHT_HOURS else None,
        }
    
    # Load from disk
    filepath = PRECOMPUTED_DIR / day_name / f'heatmap_h{actual_hour}.json'
    if not filepath.exists():
        raise HTTPException(status_code=500, detail=f"Precomputed heatmap not found: {filepath}")
    
    with open(filepath) as f:
        data = json.load(f)
    
    # Update cache (LRU eviction)
    _hourly_cache[cache_key] = data
    _hourly_cache_keys.append(cache_key)
    if len(_hourly_cache_keys) > _HOURLY_CACHE_MAX:
        oldest_key = _hourly_cache_keys.pop(0)
        del _hourly_cache[oldest_key]
    
    logger.info(f"Loaded heatmap: {filepath}")
    
    return {
        **data,
        "hour": hour,
        "is_night_representative": hour in NIGHT_HOURS,
        "representative_hour": NIGHT_REPRESENTATIVE if hour in NIGHT_HOURS else None,
    }


def _get_hourly_data(hour: int, day_name: str = None) -> dict:
    """Get heatmap data for a specific hour.
    
    Night hours (0-6) are mapped to the representative hour (h3).
    """
    return _load_hourly_file(hour, day_name)


@app.get("/predict/signal_strength/heatmap")
def get_signal_heatmap(hour: int = -1, day: str = None):
    """
    Get heatmap data (read from individual hourly files, millisecond response)
    
    Automatically detects current day of week.
    Supports all 7 days: mon, tue, wed, thu, fri, sat, sun.
    Night hours (0-6) return representative h3 data.
    Returns two types of data:
    - ap_points: Signal strength prediction for each AP point
    - smooth_grid: IDW interpolated smooth grid
    
    Args:
        hour (int, default current time): Hour (0-23)
        day (str, optional): Day name ('mon'/'tue'/.../'sun'). Default: current day.
    """
    if hour < 0 or hour > 23:
        from datetime import datetime
        hour = datetime.now().hour
    
    return _get_hourly_data(hour, day)


# AP trend index: {ap_name: {hour: {signal_db, signal_quality, bars}}}

# Built once from the individual hourly files, refreshed on day change
_ap_trend_index: dict = {}
_ap_trend_day: str = None


def _build_ap_trend_index(day_name: str = None) -> dict:
    """Build AP trend index from individual hourly heatmap files.
    
    Iterates over all 24 hourly files (night hours use h3 representative)
    and indexes by AP name for O(1) trend queries.
    """
    if day_name is None:
        day_name = _get_day_name()
    
    index = {}
    
    # Night representative (h3)
    night_filepath = PRECOMPUTED_DIR / day_name / f'heatmap_h{NIGHT_REPRESENTATIVE}.json'
    if night_filepath.exists():
        with open(night_filepath) as f:
            night_data = json.load(f)
        night_points = night_data.get("ap_points", {}).get("points", [])
        for point in night_points:
            ap_name = point.get("ap_name")
            if ap_name:
                if ap_name not in index:
                    index[ap_name] = {}
                for h in NIGHT_HOURS:
                    index[ap_name][h] = {
                        "signal_db": point["signal_db"],
                        "signal_quality": point["signal_quality"],
                        "bars": point["bars"],
                    }
    
    # Day hours (7-23)
    for hour in range(7, 24):
        filepath = PRECOMPUTED_DIR / day_name / f'heatmap_h{hour}.json'
        if not filepath.exists():
            continue
        with open(filepath) as f:
            hour_data = json.load(f)
        points = hour_data.get("ap_points", {}).get("points", [])
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
    
    return index


def _get_ap_trend_index(day_name: str = None) -> dict:
    """Get AP trend index, rebuilt on day change."""
    global _ap_trend_index, _ap_trend_day
    if day_name is None:
        day_name = _get_day_name()
    
    if not _ap_trend_index or _ap_trend_day != day_name:
        _ap_trend_index = _build_ap_trend_index(day_name)
        _ap_trend_day = day_name
        logger.info(f"Built AP trend index for {day_name} ({len(_ap_trend_index)} APs)")
    
    return _ap_trend_index


def _get_ap_trend_data(ap_name: str, day_name: str = None) -> list:
    """Get 24-hour trend data for a specific AP from the pre-built index.
    
    O(1) lookup from the in-memory index. Night hours (0-6) use h3 representative data.
    """
    if day_name is None:
        day_name = _get_day_name()
    
    index = _get_ap_trend_index(day_name)
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
    return trend_data




@app.get("/predict/signal_strength/ap_trend/{ap_name}")
def get_ap_daily_trend(ap_name: str):
    """
    Get the 24-hour signal strength trend for a specific AP.
    
    Reads heatmap files on-demand (only current day, 24 files max).
    Returns 24 data points (one per hour), including signal_db, signal_quality, and bars.
    """
    from urllib.parse import unquote
    ap_name = unquote(ap_name)
    
    trend_data = _get_ap_trend_data(ap_name)
    
    # Calculate statistics
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
        "day_type": _get_day_name(),
        "trend": trend_data,
        "total_hours": len(trend_data),
        "stats": stats,
    }


if __name__ == "__main__":

    import uvicorn
    # Run with more workers for production
    uvicorn.run(app, host="0.0.0.0", port=8000)
