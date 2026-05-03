from fastapi import FastAPI
from find_paths import *
from helper_script import *
import networkx as nx
import pandas as pd
import numpy as np

app = FastAPI()

UAB_bbox = 2.09491, 41.50736, 2.11543, 41.49505
G = ox.graph_from_bbox(UAB_bbox, network_type="walk")
aps = add_aps_to_graph(G,path="geolocation_package/data/aps_geolocalizados_wgs84.geojson",bbox=UAB_bbox)
# print(G.nodes[aps[0]].keys())       #   aps node :'x' 'y' 'node_type' 'height', 'building' 'espacio' etc.key
# print(G.nodes[1493656218].keys()) # normal road point keys : only 'x' 'y' 'street_count'

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
    Aps = []
    source = ox.distance.nearest_nodes(G, lng, lat)
    _candidates = candidates(lng,lat,radius)
    candi_info = _candidates["candidates"]
    for candidate in candi_info:
        Aps.append([candidate['lng'],candidate['lat']])
    min_distance = 10000
    return Aps[1]

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
    Predict AP status based on AP metadata.
    The current dataset does not include real labels in the geojson,
    so we use a rule-based heuristic instead of a random classifier.
    """
    try:
        height = float(features.get('height', 0) or 0)
        building = str(features.get('building', '') or '')
        espacio = str(features.get('espacio', '') or '')
        lng = float(features.get('lng', 0) or 0)
        lat = float(features.get('lat', 0) or 0)

        building_score = 1 if len(building) >= 3 else 0
        espacio_score = 1 if len(espacio) >= 3 else 0
        height_score = 1 if height >= 4 else 0
        location_score = 1 if (UAB_bbox[0] <= lng <= UAB_bbox[2] and UAB_bbox[3] <= lat <= UAB_bbox[1]) else 0

        score = building_score + espacio_score + height_score + location_score
        prediction = 'Up' if score >= 2 else 'Down'
        confidence = 0.65 + 0.1 * min(score, 3)

        return {
            "prediction": prediction,
            "confidence": round(float(min(confidence, 0.99)), 3),
            "features_used": {
                "height": height,
                "building_length": len(building),
                "espacio_length": len(espacio),
                "lng": lng,
                "lat": lat,
                "score": score,
            }
        }
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

