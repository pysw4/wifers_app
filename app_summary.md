# Wifers — UAB Campus WiFi Intelligence App

## 8 Core Features

---

### 1. Heatmap
Interactive campus map with real-time signal strength visualization. Color-coded AP markers (Green → Yellow → Orange → Red) and smooth IDW grid overlay. Supports hour-by-hour preview (0–23) with 168 precomputed heatmaps (7 days × 24 hours). Signal quality levels: Excellent (≥ -50 dBm), Good (≥ -60 dBm), Fair (≥ -70 dBm), Weak (≥ -80 dBm), Very Poor (< -80 dBm).

### 2. Foto2AP
Snap a photo of any WiFi AP physical label on campus. OCR (EasyOCR) extracts the AP name and auto-locates it on the map. One-tap actions after recognition: view trend, navigate, check prediction.

### 3. Favorites
Save frequently used APs for quick access. View building/floor info, navigate to the AP, predict its status, or remove with confirmation dialog. Persisted via SharedPreferences.

### 4. Recommend
Intelligent AP recommendation engine with 3 modes:
- **Distance Priority** — Score = 1 − (distance / maxDistance)
- **Signal Priority** — Score = normalizedSignal
- **Balanced** — Score = 0.6·signal + 0.4·distance
Supports building filter, search radius (200m–5km), and stable AP preference.

### 5. Navigation
OSMnx-powered pedestrian routing across campus. Returns best path + 2 alternatives. Features real-time GPS follow mode and gate fallback (auto-routes from campus main entrance when user is outside campus).

### 6. Booking
Room booking system with WiFi performance prediction (Fair / Good / Excellent). Hour-by-hour availability grid for any room and date. Smart slot suggestion, alternative room finder, and booking management (create, list, cancel).

### 7. Trend
24-hour signal strength trend for any AP displayed via line chart and bar chart (powered by fl_chart). Shows statistics: average, max, min dBm, best/worst hour. Supports weekday vs weekend comparison.

### 8. Prediction
ML-powered AP status prediction using Decision Tree classifier (8 features: client_count, cpu_utilization, mem_free, mem_total, last_modified, hour, mem_usage, overloaded). Returns Up/Down status with confidence score. Includes feedback loop for continuous learning.

---

*Built with Flutter + FastAPI + scikit-learn | Deployed on Render*
