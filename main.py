from fastapi import FastAPI
from find_paths import *
from helper_script import *
app = FastAPI()

UAB_bbox = 2.09491, 41.50736, 2.11543, 41.49505
G = ox.graph_from_bbox(UAB_bbox, network_type="walk")
aps = add_aps_to_graph(G,path="geolocation_package/data/aps_geolocalizados_wgs84.geojson",bbox=UAB_bbox)

@app.get("/")
def root():
    return {"message": "API is working"}

@app.get("/recommend/{user}")
def recommend(user: str):
    return {
        "user": user,
        "recommendations": ["Movie A", "Movie B", "Movie C"]
    }

@app.get("/candidates/{lng}/{lat}/{radius}")
def candidates(lng: float, lat: float, radius: int):
    nearest_node = ox.distance.nearest_nodes(G, lng, lat)
    candidates = find_qualified_in_range(G=G, original_target=nearest_node, acceptable_range=radius)
    coordinates = []
    for candidate in candidates:
        x = G.nodes[candidate]['x']
        y = G.nodes[candidate]['y']
        coordinates.append([x,y])
    return {"candidates":coordinates}
