# Wifers App - Project Architecture & Maintenance Guide

## Overview

Wifers is a UAB (Universitat Autònoma de Barcelona) campus WiFi AP (Access Point) management application. It consists of two main components:

1. **Flutter Frontend** (`lib/`) - Cross-platform mobile/desktop app
2. **Python Backend** (`main.py`) - FastAPI REST API server

The app provides real-time AP status prediction, signal strength heatmaps, campus navigation routing, and AP recommendations.

---

## 1. Project Structure

```
wifers_app/
├── lib/                          # Flutter frontend
│   ├── main.dart                 # App entry point
│   ├── models/
│   │   └── ap_info.dart          # AP data model
│   ├── pages/
│   │   ├── my_home_page.dart     # Main navigation shell (bottom tabs)
│   │   ├── map_page.dart         # Interactive campus map with heatmap
│   │   ├── route_page.dart       # Navigation route display
│   │   ├── recommend_page.dart   # AP recommendation engine
│   │   ├── favorites_page.dart   # Saved favorite APs
│   │   ├── predictor_page.dart   # Manual AP status prediction
│   │   ├── setting_page.dart     # App settings
│   │   └── ap_trend_dialog.dart  # 24h signal trend dialog
│   └── services/
│       ├── api_service.dart      # HTTP client for backend API
│       ├── ap_data_service.dart  # GeoJSON data loader
│       ├── cache_service.dart    # Two-layer cache (memory + persistent)
│       ├── heatmap_asset_service.dart # Static heatmap file loader
│       ├── location_service.dart # GPS location & campus detection
│       └── storage_service.dart  # SharedPreferences persistence
├── main.py                       # FastAPI backend server
├── helper_script.py              # Graph routing & AP placement utilities
├── precompute_heatmaps.py        # Pre-compute 168 heatmap JSON files (7 days × 24 hours)
├── retrain_classifier.py         # ML model retraining script
├── predict.py                    # Standalone prediction script
├── models/                       # Trained ML models
│   ├── decision_tree.joblib      # AP Up/Down classifier
│   ├── decision_tree_meta.json   # Model metadata
│   ├── signal_strength_model.joblib  # Signal strength regressor
│   ├── signal_strength_meta.joblib   # Signal model metadata
│   └── building_encoder.joblib   # Building name encoder
├── precomputed/                  # Pre-computed heatmap JSON files (7 days × 24 hours)
│   ├── mon/                      # 24 files (heatmap_h0.json ~ heatmap_h23.json)
│   ├── tue/                      # 24 files
│   ├── wed/                      # 24 files
│   ├── thu/                      # 24 files
│   ├── fri/                      # 24 files
│   ├── sat/                      # 24 files
│   └── sun/                      # 24 files
├── geolocation_package/          # GeoJSON data & documentation
│   └── data/
│       └── aps_geolocalizados_wgs84.geojson  # AP locations
└── pubspec.yaml                  # Flutter dependencies
```

---

## 2. Frontend Architecture (Flutter)

### 2.1 Navigation Flow

```
main.dart
  └── MyApp
       └── MyHomePage (BottomNavigationBar with IndexedStack)
            ├── [0] MapPage          - Interactive campus map
            ├── [1] FavoritesPage    - Saved APs list
            ├── [2] RecommendPage    - AP recommendation engine
            └── [3] SettingPage      - App preferences
```

### 2.2 Page Descriptions

#### MapPage (`lib/pages/map_page.dart`)
- **Purpose**: Main interactive map showing UAB campus with AP markers
- **Features**:
  - Real-time GPS location tracking with campus boundary detection
  - Signal strength heatmap overlay (color-coded AP markers + smooth grid)
  - Hour selector (0-23) to view signal predictions at different times
  - AP detail bottom sheet with Navigate / 24h Trend / Favorite actions
  - Campus gate navigation fallback when user is outside campus
- **Key Methods**:
  - `_loadHeatmap()` - Loads heatmap from static files (web/heatmaps/) with API fallback
  - `_processHeatmapData()` - Parses AP points + smooth grid from response
  - `_navigateToAP()` - Routes to AP using advanced_route API
  - `_navigateFromGate()` - Routes from campus main entrance
  - `_showAPTrend()` - Opens APTrendDialog for 24h signal trend
  - `_dbmToColor()` - Converts dBm to gradient color (Red→Orange→Yellow→Green)

#### RoutePage (`lib/pages/route_page.dart`)
- **Purpose**: Displays navigation route on map with alternatives
- **Features**:
  - Multiple route selection (best route + alternatives)
  - Real-time GPS tracking with follow mode
  - Distance & estimated time display
  - Alternative route loading via advanced_route API
- **Key Classes**:
  - `RouteAlternative` - Data class for alternative route paths

#### RecommendPage (`lib/pages/recommend_page.dart`)
- **Purpose**: Recommends best APs based on user location and preferences
- **Features**:
  - Three recommendation modes: Distance Priority / Signal Priority / Balanced
  - Building filter dropdown
  - Batch AP status prediction via API
  - Signal strength integration from heatmap data
  - Scoring algorithm combining distance, signal, and predicted status
  - Campus gate fallback for outside-campus users
- **Key Methods**:
  - `_scoreAp()` - Scores AP based on selected mode
  - `_dbmToNormalizedScore()` - Normalizes dBm to [0,1] range
  - `_fetchSignalForAp()` - Gets signal data from heatmap cache

#### FavoritesPage (`lib/pages/favorites_page.dart`)
- **Purpose**: Manages user's saved favorite APs
- **Features**:
  - List of saved APs with building/floor info
  - Navigate to AP (with campus gate fallback)
  - Predict AP status (opens PredictorPage)
  - Remove favorites with confirmation dialog

#### PredictorPage (`lib/pages/predictor_page.dart`)
- **Purpose**: Manual AP status prediction with feature inputs
- **Features**:
  - Auto-filled features when AP is selected
  - Manual form input for all 8 model features
  - Prediction result display with confidence score

#### SettingPage (`lib/pages/setting_page.dart`)
- **Purpose**: App configuration
- **Settings**:
  - Cache prediction results (on/off + duration)
  - Recommendation mode (distance/signal/balanced)
  - Prefer stable APs toggle
  - Recommendation radius (200m-5km)
  - Low-power location mode
  - Notifications toggle
  - Clear cached data / Reset settings

#### APTrendDialog (`lib/pages/ap_trend_dialog.dart`)
- **Purpose**: Shows 24-hour signal strength trend for a specific AP
- **Features**:
  - Line chart and bar chart views
  - Statistics (avg/max/min dBm, best/worst hour)
  - Weekday vs weekend comparison (via compare endpoint)

### 2.3 Services

#### ApiService (`lib/services/api_service.dart`)
- Base URL: `https://wifers-app.onrender.com`
- **Endpoints**:
  - `GET /route/{lat}/{lng}/{dest_lat}/{dest_lng}` - Basic routing
  - `GET /route/advanced/{lat}/{lng}/{dest_lat}/{dest_lng}` - Advanced routing with alternatives
  - `POST /predict` - Single AP status prediction
  - `POST /predict/batch` - Batch AP status prediction
  - `GET /predict/signal_strength/heatmap` - Heatmap data
  - `GET /predict/signal_strength/ap_trend/{ap_name}` - 24h AP trend

#### CacheService (`lib/services/cache_service.dart`)
- Two-layer caching: memory (Map) + persistent (SharedPreferences)
- TTL-based expiration
- Methods: `get`, `set`, `remove`, `clearAll`, `clearExpired`, `has`, `stats`

#### ApDataService (`lib/services/ap_data_service.dart`)
- Loads AP data from bundled GeoJSON asset
- Methods: `loadAllAps()`, `loadBuildings()`, `loadAllApsAsMaps()`

#### HeatmapAssetService (`lib/services/heatmap_asset_service.dart`)
- Loads precomputed heatmap JSON from static web assets
- Methods: `loadHeatmap(day, hour)` - Returns heatmap data for given day/hour
- Fallback: returns null on failure, allowing API fallback in MapPage

#### LocationService (`lib/services/location_service.dart`)
- UAB campus center: 41.503, 2.105 (radius: 1.2km)
- Campus gate: 41.500182, 2.111848
- Methods: `isNearCampus()`, `getCurrentPosition()`

#### StorageService (`lib/services/storage_service.dart`)
- Persists favorites and settings via SharedPreferences
- Methods: `saveFavorites()`, `loadFavorites()`, `saveSettings()`, `loadSettings()`, `clearCache()`

### 2.4 Data Model

#### APInfo (`lib/models/ap_info.dart`)
```dart
class APInfo {
  String? id;           // AP identifier (USER_NOM_A)
  double lat;           // Latitude
  double lng;           // Longitude
  String building;      // Building name (USER_EDIFI)
  String? name;         // AP name
  int? height;          // Floor number (Num_Planta)
  String? espacio;      // Space identifier (USER_Espai)
  double? signalStrength; // Signal strength in dBm
  String get uniqueKey; // Composite key: id ?? '${lat}_$lng'
}
```

---

## 3. Backend Architecture (Python FastAPI)

### 3.1 Server (`main.py`)

**Startup**: Uses `lifespan` context manager to initialize:
1. Load ML model (Decision Tree classifier)
2. Load OSM graph for UAB campus (with graceful failure)

**Global Resources**:
- `G` - OSMnx graph with AP nodes
- `G_AP_nodes` - AP node data
- `G_road` - Subgraph containing only road nodes (for nearest_nodes queries)
- `ml_model` - Decision Tree classifier (joblib)
- `_heatmap_cache` - In-memory cache for precomputed heatmap JSON

**API Endpoints**:

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Root status check |
| `/health` | GET | Health check for Render |
| `/status` | GET | Detailed status (graph, model, cache) |
| `/predict` | POST | Single AP status prediction |
| `/predict/batch` | POST | Batch AP status prediction |
| `/route/{lat}/{lng}/{dest_lat}/{dest_lng}` | GET | Basic shortest-path routing |
| `/route/advanced/{lat}/{lng}/{dest_lat}/{dest_lng}` | GET | Advanced routing with alternatives |
| `/predict/signal_strength/heatmap` | GET | Heatmap data (by day, mon-sun) |
| `/predict/signal_strength/buildings` | GET | List available buildings |
| `/predict/signal_strength/ap_trend/{ap_name}` | GET | 24h AP signal trend |
| `/predict/signal_strength/ap_trend/{ap_name}/compare` | GET | Weekday vs weekend comparison (via compare endpoint) |
| `/cache/status` | GET | Cache statistics |

**Key Functions**:

- `_resolve_to_road_node()` - Converts string AP nodes to integer OSM road nodes for routing
- `_build_feature_dataframe()` - Validates and converts feature dict to DataFrame
- `_to_prediction_label()` - Converts model output to 'Up'/'Down' string
- `_up_probability_from_proba()` - Extracts Up probability from model prediction
- `_get_day_type()` - Returns day name (mon-sun) based on current date
- `_load_precomputed_heatmap()` - Loads heatmap JSON from cache or disk
- `_build_ap_index()` - Builds AP name → hourly data index for fast trend queries

### 3.2 Graph Routing (`helper_script.py`)

- Uses OSMnx to load UAB campus walking paths
- Adds AP nodes to the graph with spatial coordinates
- `find_qualified_in_range()` - Finds nodes within acceptable range of target
- `find_paths_to_candidates()` - Calculates shortest paths to multiple candidate nodes
- `add_aps_to_graph()` - Adds AP nodes from GeoJSON to OSM graph

### 3.3 ML Models

**Decision Tree Classifier** (`models/decision_tree.joblib`):
- Predicts AP status: **Up** (stable) or **Down** (unstable)
- 8 features: client_count, cpu_utilization, mem_free, mem_total, last_modified, hour, mem_usage, overloaded
- Trained with `class_weight='balanced'` to handle class imbalance (~5.6% Down)
- Selected by F1 score (not accuracy) for better minority class detection

**Signal Strength Model** (`models/signal_strength_model.joblib`):
- Predicts real signal strength in dBm
- Features: building_code, floor, hour, band
- Used by `precompute_heatmaps.py` to generate 168 heatmap files (7 days × 24 hours)

### 3.4 Precomputed Heatmaps (`precompute_heatmaps.py`)

- Generates 168 JSON files (7 days × 24 hours)
- Each file contains:
  - `ap_points`: Signal strength for each AP point
  - `smooth_grid`: IDW-interpolated smooth grid (30×30 resolution)
  - `legend`: Color mapping for signal quality levels
- Signal quality levels: Excellent (≥-50dBm), Good (≥-60dBm), Fair (≥-70dBm), Weak (≥-80dBm), Very Poor (<-80dBm)

---

## 4. Data Flow

### 4.1 Heatmap Display Flow
```
User opens MapPage
  → _loadHeatmap() called in initState
    → Determine current day (mon-sun) and hour (0-23)
    → Try HeatmapAssetService.loadHeatmap(day, hour) first
      → Loads from web/heatmaps/{day}/heatmap_h{hour}.json (static file)
      → Success: process data directly
      → Fail: fallback to API
        → GET /predict/signal_strength/heatmap?hour={h}&day={day}
          → Backend loads from precomputed/{day}/heatmap_h{h}.json
          → Returns AP points + smooth grid
    → Check CacheService for cached heatmap data
      → Cache hit: process cached data
      → Cache miss: process from source
      → Cache result (30 min TTL)
    → _processHeatmapData():
      → Parse AP points into _heatmapCache (Map<ap_name, signal_data>)
      → Parse smooth grid into _smoothHeatmapPoints
    → Render markers with color-coded signal strength
    → Render smooth grid as PolygonLayer
```

### 4.2 Navigation Flow
```
User taps "Navigate" on AP bottom sheet
  → _navigateToAP(ap)
    → Check if user is near campus
      → No: Show dialog → "Start from Gate" → _navigateFromGate(ap)
      → Yes: GET /route/advanced/{lng}/{lat}/{dest_lng}/{dest_lat}
        → Backend: find nearest road nodes → find_paths_to_candidates → return best path + alternatives
    → Parse path coordinates
    → Navigate to RoutePage with path + alternatives
```

### 4.3 Recommendation Flow
```
User taps "Find Best APs" on RecommendPage
  → Get user location (or campus gate fallback)
  → Load all APs from GeoJSON asset
  → Filter by distance (radius) and building
  → Take top 100 nearest APs
  → POST /predict/batch with feature vectors
  → GET /predict/signal_strength/heatmap for signal data
  → Score each AP based on selected mode (distance/signal/balanced)
  → Sort by score, return top 5
  → Cache result
```

---

## 5. Deployment

### 5.1 Render (via render.yaml Blueprint)

The project uses a `render.yaml` Blueprint to define two services:

#### API Backend (`wifers-app-api`)
- **Type**: Web Service (Python)
- **Runtime**: Python 3.11
- **Build**: `pip install -r requirements.txt`
- **Start**: `uvicorn main:app --host 0.0.0.0 --port $PORT --log-level info`
- **Health Check**: `/health`
- **URL**: `https://wifers-app-api.onrender.com`
- Graph loading may time out on cold start; app handles gracefully with `_initialized` flag

#### Flutter Web Frontend (`wifers-app-web`)
- **Type**: Web Service (Docker)
- **Build**: Multi-stage Docker build (`Dockerfile`)
  - Stage 1: Installs Flutter SDK, runs `flutter build web --release`
  - Stage 2: Serves built files via Nginx Alpine
- **URL**: `https://wifers-app-web.onrender.com`
- **Config**: `nginx.conf` handles SPA routing and caching

### 5.2 Local Builds
- Build for Android: `flutter build apk`
- Build for iOS: `flutter build ios`
- Build for Web: `flutter build web`
- Build for macOS: `flutter build macos`

---

## 6. Maintenance Guide

### 6.1 Retraining the ML Model
```bash
# 1. Ensure aps_processed.csv is in the project root
# 2. Run retraining script
python retrain_classifier.py
# 3. Output: models/decision_tree.joblib + models/decision_tree_meta.json
```

### 6.2 Regenerating Heatmap Data
```bash
# After model retraining or GeoJSON updates:
python precompute_heatmaps.py
# Output: precomputed/{mon..sun}/heatmap_h{0..23}.json (168 files)
```

### 6.3 Updating AP Locations
Edit `geolocation_package/data/aps_geolocalizados_wgs84.geojson`, then:
1. Regenerate heatmaps: `python precompute_heatmaps.py`
2. Rebuild Flutter app to bundle updated GeoJSON

### 6.4 Common Issues & Solutions

**Issue**: Route endpoint returns 500 error
- **Cause**: OSMnx `nearest_nodes` returns string AP nodes instead of integer road nodes
- **Fix**: Use `G_road` subgraph (road nodes only) for `nearest_nodes` queries
- **Protection**: `_resolve_to_road_node()` function converts string nodes to nearest road nodes

**Issue**: Heatmap data not updating
- **Cause**: Backend caches heatmap data in memory (`_heatmap_cache`)
- **Fix**: Call `GET /cache/status` to check cache, or restart the server

**Issue**: Cold start timeout on Render
- **Cause**: OSM graph loading takes >30s on free tier
- **Behavior**: App starts with `_initialized=false`, graph loads asynchronously
- **Workaround**: Retry after a few seconds; `/status` endpoint shows `graph_loaded` status

**Issue**: Location permission denied
- **Cause**: User denied location permission
- **Behavior**: App falls back to campus center or campus gate
- **Fix**: User must enable location in device Settings

### 6.5 Adding New Features

**New API Endpoint**:
1. Add route handler in `main.py`
2. Add corresponding method in `lib/services/api_service.dart`
3. Create/update Flutter page to consume the new endpoint

**New Page**:
1. Create file in `lib/pages/`
2. Add to navigation in `lib/pages/my_home_page.dart`
3. Register route if needed

**New ML Model**:
1. Train model and save to `models/` directory
2. Add loading logic in `main.py` (see `load_ml_model()` pattern)
3. Add prediction endpoint
4. Update Flutter `ApiService` and relevant pages

---

## 7. Dependencies

### Flutter (pubspec.yaml)
- `flutter_map` - Map rendering
- `latlong2` - Coordinate & distance calculations
- `http` - HTTP client
- `geolocator` - GPS location
- `shared_preferences` - Local persistence
- `url_launcher` - External URL handling
- `fl_chart` - Chart rendering (trend dialog)

### Python (requirements inferred)
- `fastapi` - Web framework
- `uvicorn` - ASGI server
- `osmnx` - OpenStreetMap graph
- `networkx` - Graph algorithms
- `pandas` / `numpy` - Data processing
- `scikit-learn` - ML models
- `joblib` - Model serialization
- `geopandas` - GeoJSON processing

---

## 8. Configuration

### UAB Campus Bounds
```python
UAB_bbox = (north=41.50736, south=41.49505, east=2.11543, west=2.09491)
Campus center: 41.503, 2.105
Campus radius: 1.2 km
Campus gate: 41.500182, 2.111848
```

### ML Model Features
```python
MODEL_FEATURES = [
    'client_count', 'cpu_utilization', 'mem_free', 'mem_total',
    'last_modified', 'hour', 'mem_usage', 'overloaded'
]
```

### Signal Quality Thresholds
| Quality | dBm Range | Bars | Color |
|---|---|---|---|
| Excellent | ≥ -50 | 5 | Green |
| Good | -60 to -50 | 4 | Yellow |
| Fair | -70 to -60 | 3 | Orange |
| Weak | -80 to -70 | 2 | Red |
| Very Poor | < -80 | 1 | Dark Red |
