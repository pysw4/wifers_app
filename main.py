from fastapi import FastAPI, HTTPException
import networkx as nx
import pandas as pd
import numpy as np
import joblib
from pathlib import Path
import osmnx as ox
from helper_script import add_aps_to_graph, find_paths_to_candidates, find_qualified_in_range

app = FastAPI()

UAB_bbox = 41.50736, 41.49505, 2.11543, 2.09491
# bbox format: (left, bottom, right, top) = (west, south, east, north)
osm_bbox = (UAB_bbox[3], UAB_bbox[1], UAB_bbox[2], UAB_bbox[0])  # (west, south, east, north)
G = ox.graph_from_bbox(bbox=osm_bbox, network_type="walk")
G_AP_nodes = add_aps_to_graph(G, bbox=[UAB_bbox[3], UAB_bbox[0], UAB_bbox[2], UAB_bbox[1]])
print(f"Loaded graph with {len(G.nodes())} total nodes, {len(G_AP_nodes)} AP nodes added")

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

ml_model = None
model_path = None


def load_ml_model():
    global ml_model, model_path
    candidates = [PRIMARY_MODEL_PATH, FALLBACK_MODEL_PATH]
    model_dir = BASE_DIR / 'models'
    if not any(candidate.exists() for candidate in candidates) and model_dir.exists():
        candidates.extend(sorted(model_dir.glob('*.joblib')))

    for candidate in candidates:
        if candidate.exists():
            try:
                ml_model = joblib.load(candidate)
                model_path = candidate
                print(f"Loaded ML model from {candidate}")
                return
            except Exception as e:
                print(f"Failed to load ML model from {candidate}: {e}")

    model_path = PRIMARY_MODEL_PATH
    raise RuntimeError(f"ML model not found. Tried: {', '.join(str(p) for p in candidates)}")


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


load_ml_model()

@app.get("/")
def root():
    return {"message": "API is working", "model_path": str(model_path)}

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.post("/predict/batch")
def predict_ap_status_batch(items: list[dict]):
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
            'signal_strength': round(up_prob * 100, 1),
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
def route(lng: float, lat: float, dest_lat: float, dest_lng: float):
    source_node = ox.distance.nearest_nodes(G, lng, lat)
    dest_node = ox.distance.nearest_nodes(G, dest_lng, dest_lat)
    try:
        path_nodes = nx.shortest_path(G, source=source_node, target=dest_node, weight='length')
    except nx.NetworkXNoPath:
        return {"path": []}
    path_coords = [{"lat": G.nodes[n]['y'], "lng": G.nodes[n]['x']} for n in path_nodes]
    return {"path": path_coords}

@app.get("/route/advanced/{lat}/{lng}/{dest_lat}/{dest_lng}")
def advanced_route(lng: float, lat: float, dest_lat: float, dest_lng: float, acceptable_range: int = 500):
    """
    Advanced routing using find_paths_to_candidates from helper_script.
    Finds multiple candidate paths within an acceptable range of the destination.
    Returns the best path along with alternative options.
    """
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
            try:
                path_nodes = nx.shortest_path(G, source=source_node, target=dest_node, weight='length')
                path_coords = [{"lat": G.nodes[n]['y'], "lng": G.nodes[n]['x']} for n in path_nodes]
                return {
                    "path": path_coords,
                    "alternatives": [],
                    "message": "No candidates found in range, using direct path"
                }
            except nx.NetworkXNoPath:
                return {"path": [], "alternatives": [], "message": "No path found"}
        
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
        
    except Exception as e:
        # Fallback to basic routing on error
        try:
            source_node = ox.distance.nearest_nodes(G, lng, lat)
            dest_node = ox.distance.nearest_nodes(G, dest_lng, dest_lat)
            path_nodes = nx.shortest_path(G, source=source_node, target=dest_node, weight='length')
            path_coords = [{"lat": G.nodes[n]['y'], "lng": G.nodes[n]['x']} for n in path_nodes]
            return {
                "path": path_coords,
                "alternatives": [],
                "message": f"Error in advanced routing, using fallback: {str(e)}"
            }
        except:
            return {"path": [], "alternatives": [], "message": f"Routing failed: {str(e)}"}

@app.post("/predict")
def predict_ap_status(features: dict):
    """
    Predict AP status using the trained Decision Tree ML model.
    Required features: client_count, cpu_utilization, mem_free, mem_total,
                       last_modified, hour, mem_usage, overloaded
    """
    df = _build_feature_dataframe(features)
    prediction = ml_model.predict(df)[0]
    prediction_proba = ml_model.predict_proba(df)[0]
    up_prob = _up_probability_from_proba(prediction_proba)
    pred_label = 'Up' if prediction == 1 else 'Down'
    confidence = float(max(prediction_proba))

    return {
        "prediction": pred_label,
        "confidence": round(confidence, 3),
        "signal_strength": round(up_prob * 100, 1),
        "model": "Decision Tree",
        "features_used": features
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

