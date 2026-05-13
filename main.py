from fastapi import FastAPI
from find_paths import *
from helper_script import *
import networkx as nx
import pandas as pd
import numpy as np
import joblib
import os

app = FastAPI()

UAB_bbox = 2.09491, 41.50736, 2.11543, 41.49505
G = ox.graph_from_bbox(UAB_bbox, network_type="walk")
aps = add_aps_to_graph(G,path="geolocation_package/data/aps_geolocalizados_wgs84.geojson",bbox=UAB_bbox)
# print(G.nodes[aps[0]].keys())       #   aps node :'x' 'y' 'node_type' 'height', 'building' 'espacio' etc.key
# print(G.nodes[1493656218].keys()) # normal road point keys : only 'x' 'y' 'street_count'

# Load the trained ML model
model_path = os.path.join(os.path.dirname(__file__), 'models', 'decision_tree.joblib')
ml_model = joblib.load(model_path) if os.path.exists(model_path) else None

@app.get("/")
def root():
    return {"message": "API is working"}

@app.get("/candidates/{lat}/{lng}/{radius}")
def candidates(lng: float, lat: float, radius: int):
    nearest_node = ox.distance.nearest_nodes(G, lng, lat)
    candidates = find_qualified_in_range(G=G, original_target=nearest_node, acceptable_range=radius)
    aps_near_candidates_pairs = find_ap_near_candidates(G = G,candidates = candidates,aps = aps, amount = 5,c_floor = 1)
    candi_info = []
    for pair in aps_near_candidates_pairs:
        for ap in pair[1]:
            candi_info.append({
                "lng": G.nodes[ap]['x'],
                "lat": G.nodes[ap]['y'],
                "building": G.nodes[ap]['building'],
                "height": G.nodes[ap]['height'],
                "espacio": G.nodes[ap]['espacio']
    })
            # candidates_information.append([x,y,building,height,espacio])
    return {"candidates":candi_info}

@app.get("/recommend/{lat}/{lng}/{radius}/{min_range}/{max_range}")
def recommend(lng:float,lat:float,radius:int,min_range:float,max_range:float):
    """
    Recommend best APs based on weighted scoring.
    Scoring factors: proximity to user, AP status prediction confidence, distance within range.
    Returns ranked list of APs with scores.
    """
    try:
        source_node = ox.distance.nearest_nodes(G, lng, lat)
        source_coords = (G.nodes[source_node]['y'], G.nodes[source_node]['x'])
        
        # Get candidates from /candidates endpoint
        _candidates = candidates(lng, lat, radius)
        candi_info = _candidates["candidates"]
        
        if not candi_info:
            return {"recommended_aps": [], "message": "No candidates found in radius"}
        
        # Calculate scores for each AP based on:
        # - Distance from user (normalized, prefer closer)
        # - ML model prediction confidence (prefer "Up" with high confidence)
        # - Distance constraints (must be within min_range and max_range)
        ap_scores = []
        
        for ap in candi_info:
            ap_coords = (ap['lat'], ap['lng'])
            
            # Haversine distance approximation (in meters, simplified)
            lat_diff = (ap_coords[0] - source_coords[0]) * 111000
            lng_diff = (ap_coords[1] - source_coords[1]) * 111000 * np.cos(np.radians(source_coords[0]))
            distance = np.sqrt(lat_diff**2 + lng_diff**2)
            
            # Check if within range constraints
            if distance < min_range or distance > max_range:
                continue
            
            # Predict AP status using ML model
            try:
                # Use default/mock features for prediction if not available in geojson
                # In production, these should come from real AP metadata
                features = {
                    'client_count': 5,  # mock value
                    'cpu_utilization': 50.0,
                    'mem_free': 2048,
                    'mem_total': 8192,
                    'last_modified': 1234567890,
                    'hour': 14,
                    'mem_usage': 4096,
                    'overloaded': 0
                }
                
                if ml_model:
                    X = pd.DataFrame([list(features.values())], columns=list(features.keys()))
                    pred = ml_model.predict(X)[0]
                    proba = ml_model.predict_proba(X)[0]
                    status_confidence = float(max(proba))
                    status = 'Up' if pred == 1 else 'Down'
                else:
                    status = 'Unknown'
                    status_confidence = 0.5
            except:
                status = 'Unknown'
                status_confidence = 0.5
            
            # Weighted scoring:
            # - Proximity score (normalized, 0-1, inverse distance)
            # - Status confidence (0-1, prefer "Up")
            # - Building/location quality (0-1, prefer descriptive metadata)
            proximity_score = max(0, 1 - (distance / max_range))
            building_quality = 1.0 if len(str(ap.get('building', ''))) >= 3 else 0.5
            espacio_quality = 1.0 if len(str(ap.get('espacio', ''))) >= 3 else 0.5
            
            # Weighted combination (adjust weights as needed)
            weights = {
                'proximity': 0.4,
                'status_confidence': 0.35,
                'location_quality': 0.25
            }
            
            location_quality = (building_quality + espacio_quality) / 2
            total_score = (
                weights['proximity'] * proximity_score +
                weights['status_confidence'] * status_confidence +
                weights['location_quality'] * location_quality
            )
            
            ap_scores.append({
                'lng': ap['lng'],
                'lat': ap['lat'],
                'building': ap['building'],
                'height': ap['height'],
                'espacio': ap['espacio'],
                'distance_meters': round(distance, 2),
                'ap_status': status,
                'status_confidence': round(status_confidence, 3),
                'total_score': round(total_score, 3)
            })
        
        # Sort by total score descending
        ap_scores.sort(key=lambda x: x['total_score'], reverse=True)
        
        return {
            "recommended_aps": ap_scores,
            "count": len(ap_scores),
            "user_location": {"lat": lat, "lng": lng},
            "range_constraints": {"min": min_range, "max": max_range}
        }
    
    except Exception as e:
        return {"error": str(e)}

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

@app.post("/predict")
def predict_ap_status(features: dict):
    """
    Predict AP status using the trained Decision Tree ML model.
    Required features: client_count, cpu_utilization, mem_free, mem_total, 
                       last_modified, hour, mem_usage, overloaded
    """
    try:
        if ml_model is None:
            return {"error": "ML model not loaded. Please ensure models/decision_tree.joblib exists."}
        
        # Extract required features
        required_features = ['client_count', 'cpu_utilization', 'mem_free', 'mem_total',
                           'last_modified', 'hour', 'mem_usage', 'overloaded']
        
        feature_values = []
        for feat in required_features:
            value = features.get(feat)
            if value is None:
                return {"error": f"Missing required feature: {feat}"}
            feature_values.append(float(value))
        
        # Make prediction
        X = pd.DataFrame([feature_values], columns=required_features)
        prediction = ml_model.predict(X)[0]
        prediction_proba = ml_model.predict_proba(X)[0]
        
        # Map prediction to string
        pred_label = 'Up' if prediction == 1 else 'Down'
        confidence = float(max(prediction_proba))
        
        return {
            "prediction": pred_label,
            "confidence": round(confidence, 3),
            "model": "Decision Tree",
            "features_used": dict(zip(required_features, feature_values))
        }
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

