"""
WiFers API - FastAPI backend for AP recommendation, routing, and signal strength prediction.

Optimized version: consolidated imports, type hints, functools LRU cache,
vectorized ML predictions, and reduced Dijkstra recomputation.
"""

# ---------------------------------------------------------------------------
# Standard library
# ---------------------------------------------------------------------------
import json
import logging
import traceback
from contextlib import asynccontextmanager
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

# ---------------------------------------------------------------------------
# Third-party
# ---------------------------------------------------------------------------
import joblib
import networkx as nx
import numpy as np
import osmnx as ox
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from scipy.spatial import KDTree

# ---------------------------------------------------------------------------
# Local
# ---------------------------------------------------------------------------
from helper_script import add_aps_to_graph, find_paths_to_candidates, find_qualified_in_range

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger("wifers")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
PRECOMPUTED_DIR = BASE_DIR / "precomputed"
PRIMARY_MODEL_PATH = BASE_DIR / "models" / "decision_tree.joblib"
FALLBACK_MODEL_PATH = Path.cwd() / "models" / "decision_tree.joblib"

UAB_BBOX: tuple[float, float, float, float] = (41.50736, 41.49505, 2.11543, 2.09491)

MODEL_FEATURES: list[str] = [
    "client_count",
    "cpu_utilization",
    "mem_free",
    "mem_total",
    "last_modified",
    "hour",
    "mem_usage",
    "overloaded",
    "day_of_week",
    "is_weekend",
    "month",
    "day_of_month",
]

DAY_NAMES: list[str] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
NIGHT_HOURS: set[int] = {0, 1, 2, 3, 4, 5, 6}
NIGHT_REPRESENTATIVE: int = 3

# ---------------------------------------------------------------------------
# Global application state  (lazily initialised during lifespan)
# ---------------------------------------------------------------------------
G: Optional[nx.MultiDiGraph] = None
G_AP_nodes: Optional[list] = None
G_road: Optional[nx.MultiDiGraph] = None
ml_model = None
model_path: Optional[Path] = None
_initialized: bool = False

# AP spatial index
_ap_coords: Optional[list] = None
_ap_kdtree: Optional[KDTree] = None
_ap_name_to_data: Optional[dict] = None


# ===================================================================
#  Lifespan  (startup / shutdown)
# ===================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise graph, ML model, and preload current-hour heatmap."""
    global _initialized
    print("=" * 60)
    print("[BOOT] WiFers API starting up …")
    print(f"[BOOT] BASE_DIR = {BASE_DIR}")
    print(f"[BOOT] PRECOMPUTED_DIR = {PRECOMPUTED_DIR}")
    print(f"[BOOT] PRECOMPUTED_DIR exists = {PRECOMPUTED_DIR.exists()}")
    if PRECOMPUTED_DIR.exists():
        print(f"[BOOT] precomputed subdirs: {[p.name for p in PRECOMPUTED_DIR.iterdir()]}")
    print(f"[BOOT] PRIMARY_MODEL_PATH exists = {PRIMARY_MODEL_PATH.exists()}")
    print(f"[BOOT] FALLBACK_MODEL_PATH exists = {FALLBACK_MODEL_PATH.exists()}")
    print("=" * 60)
    try:
        logger.info("Initializing application resources …")
        load_ml_model()
        logger.info("ML model loaded")

        try:
            init_graph()
            _initialized = True
        except Exception as exc:
            logger.error("Failed to load graph: %s", exc)
            print(f"[BOOT] ❌ Graph load FAILED: {exc}")
            traceback.print_exc()
            logger.warning("Graph routing will be unavailable until the graph is loaded")
            _initialized = False

        try:
            now = datetime.now()
            print(f"[BOOT] Preloading heatmap for hour={now.hour}, day={_current_day_name()}")
            _get_hourly_data(now.hour)  # pre-warm cache via _get_hourly_data
            logger.info("Preloaded heatmap for current hour")
        except Exception as exc:
            logger.warning("Failed to preload heatmap: %s", exc)
            print(f"[BOOT] ⚠️ Heatmap preload FAILED: {exc}")
            traceback.print_exc()

    except Exception as exc:
        logger.error("Startup initialisation failed: %s", exc)
        print(f"[BOOT] ❌ Startup FAILED: {exc}")
        traceback.print_exc()
        _initialized = False

    print(f"[BOOT] ✅ Startup complete. _initialized={_initialized}")
    print("=" * 60)
    yield  # app running
    logger.info("Shutting down …")


app = FastAPI(title="WiFers API", lifespan=lifespan)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Model-loading helpers
# ---------------------------------------------------------------------------
def load_ml_model(force: bool = False):
    """Load the Decision Tree model (idempotent).

    Only loads ``decision_tree.joblib`` — other ``.joblib`` files
    (signal_strength_model, building_encoder) are ignored.
    """
    global ml_model, model_path
    if ml_model is not None and not force:
        return ml_model, model_path

    candidates: list[Path] = [PRIMARY_MODEL_PATH, FALLBACK_MODEL_PATH]

    for candidate in candidates:
        if candidate.exists():
            try:
                ml_model = joblib.load(candidate)
                model_path = candidate
                logger.info("Loaded ML model from %s", candidate)
                return ml_model, model_path
            except Exception as exc:
                logger.warning("Failed to load ML model from %s: %s", candidate, exc)

    model_path = PRIMARY_MODEL_PATH
    err = f"ML model not found. Tried: {', '.join(str(p) for p in candidates)}"
    logger.error(err)
    raise RuntimeError(err)


# ===================================================================
#  Graph loading  (OSM + APs + KD-Tree)
# ===================================================================
def init_graph(force: bool = False):
    """Lazy-load the OSM walk graph, add AP nodes, and build the KD-Tree."""
    global G, G_AP_nodes, G_road, _ap_coords, _ap_kdtree, _ap_name_to_data
    if G is not None and not force:
        return G, G_AP_nodes

    logger.info("Loading OSM walk graph for UAB area …")
    # bbox → (west, south, east, north)
    osm_bbox = (UAB_BBOX[3], UAB_BBOX[1], UAB_BBOX[2], UAB_BBOX[0])
    G = ox.graph_from_bbox(bbox=osm_bbox, network_type="walk")

    # Road-only subgraph so that nearest_nodes never returns an AP string node
    road_nodes = [n for n in G.nodes() if not isinstance(n, str)]
    G_road = G.subgraph(road_nodes).copy()
    logger.info("Road subgraph: %d nodes", len(G_road.nodes()))

    logger.info("Adding AP nodes …")
    G_AP_nodes = add_aps_to_graph(G, bbox=[UAB_BBOX[3], UAB_BBOX[0], UAB_BBOX[2], UAB_BBOX[1]])
    logger.info("Graph ready: %d total nodes, %d AP nodes", len(G.nodes()), len(G_AP_nodes))

    _build_ap_spatial_index()
    return G, G_AP_nodes


def _build_ap_spatial_index() -> None:
    """Populate ``_ap_coords``, ``_ap_kdtree``, and ``_ap_name_to_data``."""
    global _ap_coords, _ap_kdtree, _ap_name_to_data
    _ap_coords = []
    _ap_name_to_data = {}

    for ap_name in G_AP_nodes:
        data = G.nodes[ap_name]
        ax, ay = data.get("x"), data.get("y")
        if ax is None or ay is None:
            continue
        _ap_coords.append([ay, ax])  # (lat, lng)
        _ap_name_to_data[ap_name] = {
            "lat": ay,
            "lng": ax,
            "building": data.get("building", "Unknown"),
            "floor": data.get("height", 0),
        }

    if _ap_coords:
        _ap_kdtree = KDTree(_ap_coords)
        logger.info("AP spatial index built: %d APs", len(_ap_coords))
    else:
        logger.warning("No AP coordinates — spatial index is empty")


# ===================================================================
#  Heatmap cache  (hourly files,  LRU via functools.lru_cache)
# ===================================================================
def _resolve_hour(hour: int) -> tuple[int, bool, Optional[int]]:
    """Map *hour* to actual file hour + night-representative metadata."""
    if hour in NIGHT_HOURS:
        return NIGHT_REPRESENTATIVE, True, NIGHT_REPRESENTATIVE
    return hour, False, None


@lru_cache(maxsize=3)
def _load_hourly_file(day_name: str, file_hour: int) -> dict:
    """Read a single ``precomputed/{day}/heatmap_h{file_hour}.json``.

    Cached via ``functools.lru_cache`` (max 3 entries) — automatically
    evicts least-recently-used entries.
    """
    filepath = PRECOMPUTED_DIR / day_name / f"heatmap_h{file_hour}.json"
    print(f"[DEBUG] _load_hourly_file: looking for {filepath}")
    if not filepath.exists():
        print(f"[DEBUG] ❌ Heatmap file NOT FOUND: {filepath}")
        print(f"[DEBUG]    PRECOMPUTED_DIR exists: {PRECOMPUTED_DIR.exists()}")
        if PRECOMPUTED_DIR.exists():
            print(f"[DEBUG]    Contents: {[p.name for p in PRECOMPUTED_DIR.iterdir()]}")
        raise FileNotFoundError(f"Heatmap not found: {filepath}")
    logger.info("Loading heatmap: %s", filepath)
    with open(filepath, encoding="utf-8") as fh:
        data = json.load(fh)
    print(f"[DEBUG] ✅ Heatmap loaded: {len(data.get('ap_points', {}).get('points', []))} APs")
    return data


def _get_hourly_data(hour: int, day_name: Optional[str] = None) -> dict:
    """Return heatmap dict for *hour*, enriched with metadata."""
    if day_name is None:
        day_name = _current_day_name()

    file_hour, is_night, rep_hour = _resolve_hour(hour)
    data = _load_hourly_file(day_name, file_hour)
    return {
        **data,
        "hour": hour,
        "is_night_representative": is_night,
        "representative_hour": rep_hour,
    }


def _current_day_name() -> str:
    """Return abbreviated day name for *today*."""
    return DAY_NAMES[datetime.now().weekday()]


# ===================================================================
#  AP daily trend index  (built once per day)
# ===================================================================
_ap_trend_index: dict = {}
_ap_trend_day: Optional[str] = None


def _build_ap_trend_index(day_name: str) -> dict:
    """Aggregate all 24 hourly files into ``{ap_name: {hour: {signal_db, …}}}``."""
    index: dict[str, dict[int, dict]] = {}

    # Night hours (all mapped to NIGHT_REPRESENTATIVE)
    night_file = PRECOMPUTED_DIR / day_name / f"heatmap_h{NIGHT_REPRESENTATIVE}.json"
    if night_file.exists():
        with open(night_file, encoding="utf-8") as fh:
            night_data = json.load(fh)
        for pt in night_data.get("ap_points", {}).get("points", []):
            name = pt.get("ap_name")
            if not name:
                continue
            entry = index.setdefault(name, {})
            for h in NIGHT_HOURS:
                entry[h] = {
                    "signal_db": pt["signal_db"],
                    "signal_quality": pt["signal_quality"],
                    "bars": pt["bars"],
                }

    # Day hours 7–23
    for hour in range(7, 24):
        fp = PRECOMPUTED_DIR / day_name / f"heatmap_h{hour}.json"
        if not fp.exists():
            continue
        with open(fp, encoding="utf-8") as fh:
            hdata = json.load(fh)
        for pt in hdata.get("ap_points", {}).get("points", []):
            name = pt.get("ap_name")
            if not name:
                continue
            entry = index.setdefault(name, {})
            entry[hour] = {
                "signal_db": pt["signal_db"],
                "signal_quality": pt["signal_quality"],
                "bars": pt["bars"],
            }
    return index


def _get_ap_trend_index(day_name: Optional[str] = None) -> dict:
    """Return the in-memory trend index, rebuilding on day change."""
    global _ap_trend_index, _ap_trend_day
    if day_name is None:
        day_name = _current_day_name()

    if not _ap_trend_index or _ap_trend_day != day_name:
        _ap_trend_index = _build_ap_trend_index(day_name)
        _ap_trend_day = day_name
        logger.info("AP trend index built for %s (%d APs)", day_name, len(_ap_trend_index))
    return _ap_trend_index


def _get_ap_trend_data(ap_name: str, day_name: Optional[str] = None) -> list[dict]:
    """24-hour trend list for a single AP (O(1) from the in-memory index)."""
    if day_name is None:
        day_name = _current_day_name()
    ap_hours = _get_ap_trend_index(day_name).get(ap_name, {})
    return [
        {"hour": h, **(ap_hours[h] if h in ap_hours else {"signal_db": None, "signal_quality": None, "bars": None})}
        for h in range(24)
    ]


# ===================================================================
#  ML helpers
# ===================================================================
def _build_feature_df(features: dict) -> pd.DataFrame:
    missing = [f for f in MODEL_FEATURES if f not in features]
    if missing:
        raise HTTPException(422, f"Missing features: {missing}")
    values = [float(int(v) if isinstance(v, bool) else v) for v in features.values() if v is not None]
    return pd.DataFrame([values], columns=MODEL_FEATURES)


def _to_pred_label(prediction) -> str:
    return "Up" if prediction in (1, "Up", "up") else "Down"


def _up_proba(proba: np.ndarray) -> float:
    """Probability of 'Up' class."""
    return float(proba[1]) if proba.shape[-1] == 2 else float(proba[-1])


# ===================================================================
#  Scoring helper
# ===================================================================
def _compute_score(
    distance: float,
    signal_db: float,
    up_probability_pct: float,
    radius: float,
    mode: str,
    prefer_stable: bool,
) -> float:
    """Calculate a composite score for a single AP.

    Scoring is based on distance + signal strength only.
    ML status prediction is not used in scoring.
    """
    distance_score = max(0.0, 1.0 - distance / radius)
    signal_score = max(0.0, min(1.0, (signal_db + 97.0) / 75.0))

    if mode == "distance":
        return distance_score * 0.90 + signal_score * 0.10
    if mode == "signal":
        return signal_score * 0.90 + distance_score * 0.10
    # balanced: equal weight on distance and signal
    return distance_score * 0.50 + signal_score * 0.50


# ===================================================================
#  Endpoints
# ===================================================================
@app.get("/")
def root():
    return {
        "message": "API is working",
        "model_path": str(model_path) if model_path else None,
        "graph_loaded": G is not None,
        "initialized": _initialized,
    }


@app.get("/health")
async def health_check():
    return {"status": "ok", "initialized": _initialized}


@app.get("/status")
async def full_status():
    return {
        "status": "ok",
        "initialized": _initialized,
        "graph_loaded": G is not None,
        "graph_nodes": len(G.nodes()) if G is not None else 0,
        "model_loaded": ml_model is not None,
        "model_path": str(model_path) if model_path else None,
        "ap_nodes_count": len(G_AP_nodes) if G_AP_nodes is not None else 0,
    }


# ---------------------------------------------------------------------------
#  /recommend
# ---------------------------------------------------------------------------
@app.post("/recommend")
def recommend_aps(body: dict):
    """Return top-5 recommended APs near the user's location.

    Uses KD-Tree spatial index for O(N log M) nearest-AP lookup and
    reuses pre-computed Dijkstra distances from ``find_qualified_in_range``
    to avoid redundant shortest-path calculations.
    """
    if G is None or G_road is None:
        raise HTTPException(status_code=503, detail="Graph not loaded yet")
    if ml_model is None:
        raise HTTPException(status_code=503, detail="ML model not loaded yet")
    if _ap_kdtree is None:
        raise HTTPException(status_code=503, detail="AP spatial index not built")

    lat = body.get("lat")
    lng = body.get("lng")
    radius: float = float(body.get("radius", 500))
    mode: str = body.get("mode", "balanced")
    building_filter: str = body.get("building", "")
    prefer_stable: bool = body.get("prefer_stable", True)

    if lat is None or lng is None:
        raise HTTPException(status_code=422, detail="lat and lng are required")

    now = datetime.now()
    current_hour = now.hour
    current_day = now.weekday()  # 0 = Mon

    try:
        # 1. Nearest road node
        nearest = ox.distance.nearest_nodes(G_road, lng, lat)
        if nearest is None:
            print(f"[RECOMMEND] 1️⃣ ❌ nearest_nodes returned None (user outside UAB?)")
            return {"recommendations": [], "message": "Location is outside the UAB campus area"}
        source_node = int(nearest)
        print(f"[RECOMMEND] 1️⃣ nearest_nodes → source_node={source_node}")
        logger.info("Recommend: user=(%.5f, %.5f) → source_node=%d", lat, lng, source_node)

        # 2. Single-source Dijkstra: get all reachable nodes + distances in one pass
        distances, paths = nx.single_source_dijkstra(G, source_node, weight="length", cutoff=radius)
        qualified = list(paths.keys())
        print(f"[RECOMMEND] 2️⃣ qualified nodes (single Dijkstra): {len(qualified)}")
        if not qualified:
            return {"recommendations": [], "message": f"No reachable nodes within {radius}m"}

        # ---- collect coordinates & distances ----
        valid_qualified: list = []
        qualified_coords: list = []  # (lat, lng) for KD-Tree
        candidate_distances: dict = {}  # node → walking distance (meters)

        for node in qualified:
            nd = G.nodes[node]
            cx, cy = nd.get("x"), nd.get("y")
            if cx is None or cy is None:
                continue
            valid_qualified.append(node)
            qualified_coords.append([cy, cx])  # KD-Tree uses (lat, lng)
            candidate_distances[node] = distances[node]

        print(f"[RECOMMEND] 2b️⃣ valid_qualified: {len(valid_qualified)}")
        if not valid_qualified:
            return {"recommendations": [], "message": "No reachable nodes with coordinates"}

        # 3. Batch KD-Tree: nearest AP for each qualified node
        kd_distances, kd_indices = _ap_kdtree.query(qualified_coords, k=1)
        ap_name_list = list(_ap_name_to_data.keys())
        print(f"[RECOMMEND] 3️⃣ KD-Tree: {len(kd_indices)} queries, {len(ap_name_list)} APs in index")

        ap_info_map: dict = {}  # {ap_name: {distance, lat, lng, building, floor}}
        for i, candidate in enumerate(valid_qualified):
            ap_idx = int(kd_indices[i])
            ap_name = ap_name_list[ap_idx]
            if ap_name in ap_info_map:
                continue
            info = _ap_name_to_data[ap_name]
            ap_info_map[ap_name] = {
                "distance": candidate_distances.get(candidate, radius),
                "lat": info["lat"],
                "lng": info["lng"],
                "building": info["building"],
                "floor": info["floor"],
            }

        print(f"[RECOMMEND] 3b️⃣ unique APs found: {len(ap_info_map)}")
        if not ap_info_map:
            return {"recommendations": [], "message": "No APs near reachable nodes"}

        # 4. Building filter
        if building_filter:
            ap_info_map = {k: v for k, v in ap_info_map.items() if v["building"] == building_filter}
            print(f"[RECOMMEND] 4️⃣ after building filter '{building_filter}': {len(ap_info_map)} APs")
            if not ap_info_map:
                return {"recommendations": [], "message": f"No APs in building '{building_filter}'"}

        # 5. Signal strength from heatmap cache (in-memory, no disk I/O after first load)
        try:
            heatmap = _get_hourly_data(current_hour)
            signal_map: dict = {}
            for pt in heatmap.get("ap_points", {}).get("points", []):
                name = pt.get("ap_name")
                if name:
                    signal_map[name] = {
                        "signal_db": pt.get("signal_db", -70),
                        "signal_quality": pt.get("signal_quality", "Fair"),
                        "bars": pt.get("bars", 1),
                    }
            print(f"[RECOMMEND] 5️⃣ signal_map: {len(signal_map)} APs from heatmap")
        except Exception as exc:
            print(f"[RECOMMEND] 5️⃣ ❌ heatmap load failed: {exc}")
            traceback.print_exc()
            signal_map = {}

        # 6. Signal strength from heatmap (per-AP, based on current hour/day)
        ap_names = list(ap_info_map.keys())
        n_aps = len(ap_names)

        # 7. Score & rank — based on distance + signal strength
        #    ML prediction is informational only, not used in scoring
        scored: list[dict] = []
        for i, ap_name in enumerate(ap_names):
            info = ap_info_map[ap_name]
            sig = signal_map.get(ap_name, {"signal_db": -70, "signal_quality": "Fair", "bars": 1})

            score = _compute_score(
                distance=info["distance"],
                signal_db=sig["signal_db"],
                up_probability_pct=50.0,  # neutral — not used in scoring
                radius=radius,
                mode=mode,
                prefer_stable=prefer_stable,
            )
            scored.append(
                {
                    "id": ap_name,
                    "name": ap_name,
                    "building": info["building"],
                    "floor": info["floor"],
                    "lat": info["lat"],
                    "lng": info["lng"],
                    "distance": round(info["distance"], 1),
                    "prediction": "N/A",
                    "confidence": 0.0,
                    "up_probability": 0.0,
                    "score": round(score, 4),
                    "signal_db": sig["signal_db"],
                    "signal_quality": sig["signal_quality"],
                    "bars": sig["bars"],
                }
            )

        scored.sort(key=lambda x: x["score"], reverse=True)
        top = scored[:5]

        return {
            "recommendations": top,
            "count": len(top),
            "total_candidates": len(scored),
            "mode": mode,
            "message": f"Top {len(top)} recommendations",
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Recommend error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Recommendation failed: {exc}")


# ---------------------------------------------------------------------------
#  /route  (basic)
# ---------------------------------------------------------------------------
@app.get("/route/{lat}/{lng}/{dest_lat}/{dest_lng}")
def route(lat: float, lng: float, dest_lat: float, dest_lng: float):
    if G is None:
        raise HTTPException(status_code=503, detail="Graph not loaded yet. Try again in a few seconds.")

    logger.info("Route: (%.5f, %.5f) → (%.5f, %.5f)", lat, lng, dest_lat, dest_lng)
    try:
        src = int(ox.distance.nearest_nodes(G_road, lng, lat))
        dst = int(ox.distance.nearest_nodes(G_road, dest_lng, dest_lat))
        logger.info("Nearest road nodes: src=%d, dst=%d", src, dst)

        try:
            path_nodes = nx.shortest_path(G, source=src, target=dst, weight="length")
        except nx.NetworkXNoPath:
            logger.warning("No path between %d and %d", src, dst)
            return {"path": []}

        coords = [{"lat": G.nodes[n]["y"], "lng": G.nodes[n]["x"]} for n in path_nodes]
        return {"path": coords}
    except Exception as exc:
        logger.error("Route error: %s", exc, exc_info=True)
        return {"path": [], "message": str(exc)}


# ---------------------------------------------------------------------------
#  /route/advanced
# ---------------------------------------------------------------------------
@app.get("/route/advanced/{lat}/{lng}/{dest_lat}/{dest_lng}")
def advanced_route(
    lat: float,
    lng: float,
    dest_lat: float,
    dest_lng: float,
    acceptable_range: int = 500,
):
    """Advanced routing with alternative candidate paths."""
    if G is None:
        raise HTTPException(status_code=503, detail="Graph not loaded yet")

    def _coords(path):
        return [{"lat": G.nodes[n]["y"], "lng": G.nodes[n]["x"]} for n in path]

    error_msg = ""
    try:
        src = int(ox.distance.nearest_nodes(G_road, lng, lat))
        dst = int(ox.distance.nearest_nodes(G_road, dest_lng, dest_lat))
        logger.info("Advanced route: src=%d, dst=%d", src, dst)

        candidates = find_qualified_in_range(G, dst, acceptable_range=acceptable_range)
        if not candidates:
            path = nx.shortest_path(G, source=src, target=dst, weight="length")
            return {"path": _coords(path), "alternatives": [], "message": "No candidates in range; using direct path"}

        candidate_paths = find_paths_to_candidates(G, src, candidates)
        if not candidate_paths:
            return {"path": [], "alternatives": [], "message": "No paths to candidates"}

        sorted_cands = sorted(
            ((c, (cost, path)) for c, (cost, path) in candidate_paths.items() if cost != float("inf")),
            key=lambda item: item[1][0],
        )
        if not sorted_cands:
            path = nx.shortest_path(G, source=src, target=dst, weight="length")
            return {"path": _coords(path), "alternatives": [], "message": "All unreachable; using direct path"}

        best_candidate, (best_cost, best_path) = sorted_cands[0]
        alternatives = [
            {
                "path": _coords(p),
                "distance": round(cost, 2),
                "endpoint": {"lat": G.nodes[c]["y"], "lng": G.nodes[c]["x"]},
            }
            for c, (cost, p) in sorted_cands[1:4]
            if len(p) > 1
        ]
        return {
            "path": _coords(best_path),
            "alternatives": alternatives,
            "distance": round(best_cost, 2),
            "message": "Route calculated with alternatives",
        }

    except nx.NetworkXNoPath:
        return {"path": [], "alternatives": [], "message": "No path found"}
    except Exception as exc:
        error_msg = str(exc)
        logger.error("Advanced routing error: %s", exc, exc_info=True)
        try:
            src = int(ox.distance.nearest_nodes(G_road, lng, lat))
            dst = int(ox.distance.nearest_nodes(G_road, dest_lng, dest_lat))
            path = nx.shortest_path(G, source=src, target=dst, weight="length")
            return {"path": _coords(path), "alternatives": [], "message": f"Fallback routing (error: {error_msg})"}
        except nx.NetworkXNoPath:
            return {"path": [], "alternatives": [], "message": "No path in fallback"}
        except Exception as fb_exc:
            return {"path": [], "alternatives": [], "message": f"Routing failed: {error_msg} | {fb_exc}"}


# ---------------------------------------------------------------------------
#  /predict  (ML)
# ---------------------------------------------------------------------------
@app.post("/predict")
def predict_ap_status(features: dict):
    if ml_model is None:
        raise HTTPException(status_code=503, detail="ML model not loaded")

    df = _build_feature_df(features)
    pred = ml_model.predict(df)[0]
    proba = ml_model.predict_proba(df)[0]
    up_pct = _up_proba(proba)

    return {
        "prediction": _to_pred_label(pred),
        "confidence": round(float(max(proba)), 3),
        "up_probability": round(up_pct * 100, 1),
        "model": "Decision Tree",
        "features_used": features,
    }


# ---------------------------------------------------------------------------
#  /predict/signal_strength/heatmap
# ---------------------------------------------------------------------------
@app.get("/predict/signal_strength/heatmap")
def get_signal_heatmap(hour: int = -1, day: Optional[str] = None):
    """Return heatmap for *hour* (defaults to current hour)."""
    if hour < 0 or hour > 23:
        hour = datetime.now().hour
    return _get_hourly_data(hour, day)


# ---------------------------------------------------------------------------
#  /predict/signal_strength/ap_trend/{ap_name}
# ---------------------------------------------------------------------------
@app.get("/predict/signal_strength/ap_trend/{ap_name}")
def get_ap_daily_trend(ap_name: str):
    """24-hour signal-strength trend for a specific AP."""
    ap_name = unquote(ap_name)
    trend_data = _get_ap_trend_data(ap_name)

    valid = [d["signal_db"] for d in trend_data if d["signal_db"] is not None]
    stats: dict = {}
    if valid:
        stats = {
            "avg_db": round(sum(valid) / len(valid), 1),
            "max_db": max(valid),
            "min_db": min(valid),
            "best_hour": trend_data[valid.index(max(valid))]["hour"],
            "worst_hour": trend_data[valid.index(min(valid))]["hour"],
        }

    return {
        "ap_name": ap_name,
        "day_type": _current_day_name(),
        "trend": trend_data,
        "total_hours": len(trend_data),
        "stats": stats,
    }


# ===================================================================
#  Entry-point
# ===================================================================
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)