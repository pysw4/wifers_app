# Wifers App

UAB (Universitat Autònoma de Barcelona) campus WiFi AP (Access Point) management application. Provides real-time AP status prediction, signal strength heatmaps, campus navigation routing, and AP recommendations.

## Architecture

The project consists of two main components:

1. **Flutter Frontend** (`lib/`) - Cross-platform mobile/desktop/web app
2. **Python Backend** (`main.py`) - FastAPI REST API server

## Quick Start

### Backend
```bash
pip install -r requirements.txt
python main.py
# Server starts at http://0.0.0.0:8000
```

### Frontend (Flutter)
```bash
flutter pub get
flutter run
```

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check |
| `/status` | GET | Detailed server status |
| `/predict` | POST | AP status prediction (v3 model) |
| `/predict/feedback` | POST | Submit prediction feedback |
| `/predict/stats/{ap_name}` | GET | Prediction accuracy stats |
| `/predict/signal_strength/heatmap` | GET | Signal strength heatmap |
| `/predict/signal_strength/buildings` | GET | List available buildings |
| `/predict/signal_strength/ap_trend/{ap_name}` | GET | 24h AP signal trend |
| `/predict/signal_strength/ap_trend/{ap_name}/compare` | GET | Weekday vs weekend comparison |
| `/predict/signal_strength/accuracy/{ap_name}` | GET | Prediction vs actual accuracy |
| `/recommend` | POST | AP recommendations |
| `/route/{lat}/{lng}/{dest_lat}/{dest_lng}` | GET | Basic routing |
| `/route/advanced/{lat}/{lng}/{dest_lat}/{dest_lng}` | GET | Advanced routing |
| `/foto2ap/recognize` | POST | OCR-based AP recognition |
| `/booking/create` | POST | Create booking |
| `/booking/predict` | POST | Predict booking performance |
| `/booking/cancel` | POST | Cancel booking |
| `/booking/list` | GET | List bookings |
| `/booking/suggest-slot` | POST | Suggest best time slot |
| `/booking/alternatives` | POST | Find alternative rooms |
| `/booking/room-info/{room_code}` | GET | Room AP info |
| `/booking/availability/{room_code}/{date}` | GET | Room availability |
| `/cache/status` | GET | Cache statistics |

## Project Structure

```
wifers_app/
├── lib/                          # Flutter frontend
│   ├── main.dart                 # App entry point
│   ├── models/
│   │   ├── ap_info.dart          # AP data model
│   │   └── booking.dart          # Booking data model
│   ├── pages/
│   │   ├── my_home_page.dart     # Main navigation shell
│   │   ├── map_page.dart         # Interactive campus map
│   │   ├── route_page.dart       # Navigation route display
│   │   ├── recommend_page.dart   # AP recommendation engine
│   │   ├── favorites_page.dart   # Saved favorite APs
│   │   ├── predictor_page.dart   # Manual AP status prediction
│   │   ├── setting_page.dart     # App settings
│   │   ├── booking_page.dart     # Room booking interface
│   │   └── ap_trend_dialog.dart  # 24h signal trend dialog
│   └── services/
│       ├── api_service.dart      # HTTP client for backend API
│       ├── ap_data_service.dart  # GeoJSON data loader
│       ├── cache_service.dart    # Two-layer cache
│       ├── foto2ap_service.dart  # OCR photo recognition
│       ├── heatmap_asset_service.dart # Static heatmap loader
│       ├── location_service.dart # GPS location & campus detection
│       └── storage_service.dart  # SharedPreferences persistence
├── main.py                       # FastAPI backend server
├── helper_script.py              # Graph routing utilities
├── precompute_heatmaps.py        # Pre-compute heatmap JSON files
├── precompute_actual_averages.py # Compute actual signal averages
├── retrain_classifier.py         # ML model retraining
├── retrain_classifier_v3.py      # v3 model retraining
├── train_signal_model.py         # Signal strength model training
├── predict.py                    # Standalone prediction script
├── predictor_lstm.py             # LSTM predictor
├── foto2ap_service.py            # OCR AP recognition service
├── models/                       # Trained ML models
├── precomputed/                  # Pre-computed heatmap JSON files
├── geolocation_package/          # GeoJSON data & documentation
└── pubspec.yaml                  # Flutter dependencies
```

## Deployment

See `render.yaml` for Render Blueprint configuration. The API backend is deployed as a Python web service, and the Flutter web frontend is deployed via Docker with Nginx.

## License

MIT
