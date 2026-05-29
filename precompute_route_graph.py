#!/usr/bin/env python3
"""
Precompute a lightweight route graph for the UAB campus.

Exports the OSM walking network (nodes + edges) as a compact JSON file
that can be loaded by the server without osmnx/networkx dependencies.

Usage:
    python precompute_route_graph.py

Output:
    models/route_graph_light.json    (~200-600 KB, vs ~100MB for the full networkx graph)
"""
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "models"
OUTPUT_PATH = MODELS_DIR / "route_graph_light.json"

# UAB campus bounding box (same as main.py)
UAB_BBOX = (2.092, 41.492, 2.118, 41.514)  # (minx, miny, maxx, maxy)


def main():
    print("[INFO] Importing osmnx (one-time local download)...")
    import osmnx as ox
    import networkx as nx

    # 1. Download/load the road graph
    graph_path = MODELS_DIR / "route_graph.pkl"
    if graph_path.exists():
        print(f"[INFO] Loading cached graph from {graph_path}...")
        import pickle
        with open(graph_path, "rb") as f:
            G = pickle.load(f)
        print(f"[INFO] Loaded {len(G.nodes)} nodes, {len(G.edges)} edges")
    else:
        print("[INFO] Downloading UAB campus road graph from OSM...")
        G = ox.graph_from_bbox(
            bbox=UAB_BBOX,
            network_type="walk",
            simplify=True,
        )
        print(f"[INFO] Downloaded: {len(G.nodes)} nodes, {len(G.edges)} edges")
        # Save cache for future use
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        import pickle
        with open(graph_path, "wb") as f:
            pickle.dump(G, f)
        print(f"[INFO] Cached to {graph_path}")

    # 2. Convert to lightweight JSON format
    print("[INFO] Converting to lightweight JSON format...")

    # Nodes: {node_id_str: {"lat": y, "lng": x}}
    nodes = {}
    for node_id, data in G.nodes(data=True):
        nodes[str(node_id)] = {
            "lat": round(data["y"], 6),
            "lng": round(data["x"], 6),
        }

    # Edges: [[u_str, v_str, length], ...]
    edges = []
    for u, v, data in G.edges(data=True):
        length = data.get("length", 0)
        if length > 0:
            edges.append([str(u), str(v), round(length, 1)])

    # Deduplicate edges (undirected graph, many edges may have both directions)
    seen_edges = set()
    unique_edges = []
    for u, v, length in edges:
        key = (min(u, v), max(u, v))
        if key not in seen_edges:
            seen_edges.add(key)
            unique_edges.append([u, v, length])
        # else skip duplicate

    graph_data = {
        "nodes": nodes,
        "edges": unique_edges,
    }

    # 3. Write output
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(graph_data, f, separators=(",", ":"))

    file_size_mb = os.path.getsize(OUTPUT_PATH) / (1024 * 1024)
    print(f"[INFO] Exported {len(nodes)} nodes, {len(unique_edges)} edges to {OUTPUT_PATH}")
    print(f"[INFO] File size: {file_size_mb:.2f} MB")
    print("[DONE] Precomputation complete!")


if __name__ == "__main__":
    main()
