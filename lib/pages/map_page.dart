import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:geolocator/geolocator.dart';
import 'package:latlong2/latlong.dart';
import 'package:wifers_app/services/api_service.dart';
import 'package:wifers_app/services/ap_data_service.dart';
import 'package:wifers_app/services/location_service.dart';
import 'package:wifers_app/services/storage_service.dart';
import 'package:wifers_app/services/cache_service.dart';
import 'package:wifers_app/models/ap_info.dart';
import 'package:wifers_app/pages/route_page.dart';
import 'package:wifers_app/pages/favorites_page.dart';
import 'package:wifers_app/pages/predictor_page.dart';

class MapPage extends StatefulWidget {
  const MapPage({super.key});

  @override
  State<MapPage> createState() => _MapPageState();
}

class _MapPageState extends State<MapPage> {
  final ApiService _apiService = ApiService();
  final MapController _mapController = MapController();

  static final LatLng _center = LatLng(41.504, 2.105); // UAB Barcelona center
  LatLng? _currentLocation;
  StreamSubscription<Position>? _positionSubscription;

  double _currentZoom = 15.0; // Track zoom level manually (MapController has no zoom getter)
  
  final List<APInfo> _aps = [];
  

  // Heatmap state (AP point mode)
  bool _showHeatmap = false;
  bool _isLoadingHeatmap = false;
  int _selectedHour = DateTime.now().hour;
  Map<String, dynamic>? _heatmapData;
  final Map<String, Color> _signalColors = {
    'Excellent': const Color(0xFF00E676),  // Bright Green (strongest signal)
    'Good': const Color(0xFF76FF03),       // Light Green
    'Fair': const Color(0xFFFFEA00),       // Yellow
    'Weak': const Color(0xFFFF6D00),       // Orange
    'Very Poor': const Color(0xFFD50000),  // Red (weakest signal)
  };
  
  // Cache heatmap predictions by AP name
  Map<String, Map<String, dynamic>> _heatmapCache = {};
  Timer? _heatmapRefreshTimer;

  // Smooth heatmap state (grid mode) - loaded together with AP heatmap data
  bool _showSmoothHeatmap = false;
  List<Map<String, dynamic>> _smoothHeatmapPoints = [];

  Future<void> _loadAps() async {
    try {
      final loaded = await ApDataService.loadAllAps();
      setState(() {
        _aps.clear();
        _aps.addAll(loaded);
      });
    } catch (e) {
      debugPrint('Failed to load AP geojson: $e');
    }
  }

  /// 根据当前地图缩放级别计算 AP 图标大小
  /// 缩放级别越大（放得越大），图标越大
  double _getMarkerSize({bool isHeatmap = false}) {
    final zoom = _currentZoom;

    if (isHeatmap) {
      if (zoom >= 18) return 36;
      if (zoom >= 16) return 28;
      if (zoom >= 14) return 20;
      if (zoom >= 12) return 14;
      return 10; // zoom < 12，即使热力图也变小
    }
    // 普通模式
    if (zoom >= 18) return 14;
    if (zoom >= 16) return 8;
    if (zoom >= 14) return 5;
    if (zoom >= 12) return 3;
    return 0; // zoom < 12 时隐藏普通蓝点
  }

  /// 热力图模式下数字字体大小
  double _getHeatmapTextSize() {
    final zoom = _currentZoom;

    if (zoom >= 18) return 11;
    if (zoom >= 16) return 8;
    if (zoom >= 14) return 7;
    if (zoom >= 12) return 6;
    return 5;
  }

  /// 热力图模式下是否显示 AP 标记（缩放太小时只显示热力图网格不显示点）
  bool get _shouldShowMarkers {
    if (_showSmoothHeatmap && _currentZoom < 12) return false;
    return true;
  }


  List<Marker> get _markers {
    final markerSize = _getMarkerSize();
    final heatmapSize = _getMarkerSize(isHeatmap: true);
    final heatmapTextSize = _getHeatmapTextSize();
    final isHeatmapVisible = _showHeatmap && _heatmapCache.isNotEmpty;

    if (!_shouldShowMarkers) return _currentLocationMarker;
    
    if (isHeatmapVisible) {
      // Heatmap mode: color-coded markers
      return _aps.where((ap) => _heatmapCache.containsKey(ap.id ?? ap.name)).map((ap) {
        final key = ap.id ?? ap.name ?? '';
        final prediction = _heatmapCache[key];
        final dbm = prediction?['signal_db'] as num? ?? -70;
        final quality = prediction?['signal_quality'] as String? ?? 'Fair';
        final color = _signalColors[quality] ?? Colors.grey;

        // If marker is too small, only show a dot without text
        final showDetail = heatmapSize >= 14;

        return Marker(
          point: LatLng(ap.lat, ap.lng),
          width: heatmapSize,
          height: heatmapSize,
          child: GestureDetector(
            onTap: () => _showAPOptions(ap, signalDb: dbm.toDouble()),
            child: Container(
              decoration: BoxDecoration(
                color: color.withValues(alpha: showDetail ? 0.6 : 0.4),
                shape: BoxShape.circle,
                border: Border.all(color: Colors.white.withValues(alpha: showDetail ? 0.8 : 0.4), width: showDetail ? 2 : 1),
                boxShadow: showDetail ? [
                  BoxShadow(
                    color: color.withValues(alpha: 0.4),
                    blurRadius: 8,
                    spreadRadius: 2,
                  ),
                ] : null,
              ),
              child: showDetail ? Center(
                child: Text(
                  '${dbm.toInt()}',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: heatmapTextSize,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ) : null,
            ),
          ),
        );
      }).toList()
      ..addAll(_currentLocationMarker);
    }
    
    // Normal mode: small dots (hidden when zoom < 12)
    if (markerSize == 0) return _currentLocationMarker;

    final List<Marker> markers = _aps.map((ap) {
      return Marker(
        point: LatLng(ap.lat, ap.lng),
        width: markerSize + 16,  // more touch area than visible dot
        height: markerSize + 16,
        child: GestureDetector(
          onTap: () => _showAPOptions(ap),
          child: Container(
            width: markerSize,
            height: markerSize,
            decoration: BoxDecoration(
              color: const Color.fromRGBO(33, 150, 243, 0.5),
              shape: BoxShape.circle,
              border: Border.all(color: const Color.fromRGBO(255, 255, 255, 0.8), width: 1),
            ),
          ),
        ),
      );
    }).toList();

    markers.addAll(_currentLocationMarker);
    return markers;
  }

  List<Marker> get _currentLocationMarker {
    if (_currentLocation != null) {
      return [
        Marker(
          point: _currentLocation!,
          width: 36,
          height: 36,
          child: const Icon(
            Icons.person_pin_circle,
            color: Colors.green,
            size: 36,
          ),
        ),
      ];
    }
    return [];
  }

  @override
  void initState() {
    super.initState();
    _startLocationTracking();
    _loadAps();
  }

  @override
  void dispose() {
    _positionSubscription?.cancel();
    _heatmapRefreshTimer?.cancel();
    super.dispose();
  }

  Future<void> _startLocationTracking() async {
    try {
      final position = await LocationService.getCurrentPosition();
      setState(() {
        _currentLocation = LatLng(position.latitude, position.longitude);
      });

      _positionSubscription = Geolocator.getPositionStream(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.best,
          distanceFilter: 10,
        ),
      ).listen((Position position) {
        setState(() {
          _currentLocation = LatLng(position.latitude, position.longitude);
        });
      });
    } catch (e) {
      // Handle location error
    }
  }

  Future<void> _loadHeatmap() async {
    if (_isLoadingHeatmap) return;
    
    setState(() {
      _isLoadingHeatmap = true;
    });

    try {
      // Build cache key
      final cacheKey = 'heatmap_$_selectedHour';
      const heatmapTtl = Duration(minutes: 30);

      // Try cache first
      final cachedData = await CacheService.get<Map<String, dynamic>>(cacheKey, ttl: heatmapTtl);
      if (cachedData != null) {
        _processHeatmapData(cachedData);
        debugPrint('Loaded heatmap data (cached)');
        return;
      }

      final data = await _apiService.getSignalHeatmap(
        hour: _selectedHour,
      );
      
      // Save to cache
      await CacheService.set(cacheKey, data);
      _processHeatmapData(data);
    } catch (e) {
      setState(() {
        _isLoadingHeatmap = false;
      });
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Failed to load heatmap: $e')),
        );
      }
    }
  }

  void _processHeatmapData(Map<String, dynamic> data) {
    // 解析 AP 点数据
    final apPointsData = data['ap_points'] as Map<String, dynamic>?;
    final points = apPointsData?['points'] as List<dynamic>? ?? [];
    final Map<String, Map<String, dynamic>> cache = {};
    
    for (final point in points) {
      final map = point as Map<String, dynamic>;
      final apName = map['ap_name'] as String;
      cache[apName] = {
        'signal_db': map['signal_db'],
        'signal_quality': map['signal_quality'],
        'bars': map['bars'],
      };
    }

    // 解析平滑网格数据
    final smoothGridData = data['smooth_grid'] as Map<String, dynamic>?;
    final smoothPoints = smoothGridData?['points'] as List<dynamic>? ?? [];
    final parsedSmoothPoints = smoothPoints
        .map<Map<String, dynamic>>((p) => Map<String, dynamic>.from(p as Map))
        .toList();

    setState(() {
      _heatmapCache = cache;
      _heatmapData = data;
      _smoothHeatmapPoints = parsedSmoothPoints;
      _showHeatmap = true;
      _showSmoothHeatmap = true;
      _isLoadingHeatmap = false;
    });

    debugPrint('Loaded ${cache.length} AP points + ${parsedSmoothPoints.length} grid points');
  }

  void _toggleHeatmap() {
    if (_showHeatmap) {
      setState(() {
        _showHeatmap = false;
        _showSmoothHeatmap = false;
        _heatmapCache = {};
        _smoothHeatmapPoints = [];
      });
    } else {
      _loadHeatmap();
    }
  }

  Future<void> _showHourPicker() async {
    final result = await showDialog<int>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Select Time'),
        content: SizedBox(
          width: 300,
          height: 400,
          child: Column(
            children: [
              Text('Current: $_selectedHour:00'),

              const SizedBox(height: 16),
              Expanded(
                child: GridView.builder(
                  gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                    crossAxisCount: 4,
                    childAspectRatio: 1.5,
                  ),
                  itemCount: 24,
                  itemBuilder: (context, index) {
                    final isSelected = index == _selectedHour;
                    return Padding(
                      padding: const EdgeInsets.all(4),
                      child: ElevatedButton(
                        style: ElevatedButton.styleFrom(
                          backgroundColor: isSelected ? Colors.blue : null,
                          foregroundColor: isSelected ? Colors.white : null,
                        ),
                        onPressed: () => Navigator.pop(context, index),
                        child: Text('$index:00'),

                      ),
                    );
                  },
                ),
              ),
            ],
          ),
        ),
      ),
    );

    if (result != null) {
      setState(() {
        _selectedHour = result;
      });
      if (_showHeatmap) {
        _loadHeatmap(); // Refresh with new time (loads both AP points and smooth grid)
      }
    }
  }

  void _showAPOptions(APInfo ap, {double? signalDb}) async {
    String predictedStatus = 'unknown';
    try {
      final features = {
        'client_count': 10,
        'cpu_utilization': 50.0,
        'mem_free': 1000.0,
        'mem_total': 2000.0,
        'last_modified': 1640995200.0,
        'hour': DateTime.now().hour.toDouble(),
        'mem_usage': 50.0,
        'overloaded': 0,
      };
      final result = await _apiService.predictAPStatus(features);
      predictedStatus = result['prediction'] ?? 'unknown';
    } catch (e) {
      predictedStatus = 'error';
    }

    final color = predictedStatus == 'Up' ? Colors.green : predictedStatus == 'Down' ? Colors.red : Colors.orange;

    if (!mounted) return;

    showModalBottomSheet(
      context: context,
      builder: (context) => Container(
        padding: const EdgeInsets.all(16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              ap.name ?? 'AP',
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),
            Text('${ap.building}, Floor ${ap.height ?? 0}'),
            const SizedBox(height: 8),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(Icons.wifi, color: color),
                const SizedBox(width: 8),
                Text(
                  'Status: $predictedStatus',
                  style: TextStyle(color: color, fontWeight: FontWeight.bold),
                ),
              ],
            ),
            if (signalDb != null) ...[
              const SizedBox(height: 8),
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(
                    Icons.signal_wifi_4_bar,
                    color: _dbmToColor(signalDb),
                  ),
                  const SizedBox(width: 8),
                  Text(
                    'Signal: ${signalDb.toStringAsFixed(1)} dBm',
                    style: TextStyle(
                      color: _dbmToColor(signalDb),
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ],
              ),
            ],
            const SizedBox(height: 16),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceEvenly,
              children: [
                ElevatedButton.icon(
                  onPressed: () => _navigateToAP(ap),
                  icon: const Icon(Icons.directions),
                  label: const Text('Navigate'),
                ),
                ElevatedButton.icon(
                  onPressed: () => _predictAP(ap),
                  icon: const Icon(Icons.analytics),
                  label: const Text('Predict'),
                ),
                ElevatedButton.icon(
                  onPressed: () => _favoriteAP(ap),
                  icon: const Icon(Icons.favorite),
                  label: const Text('Favorite'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  /// Convert dBm signal strength to a color using smooth gradient interpolation.
  /// Stronger signal (closer to 0) = Green, Weaker signal (more negative) = Red.
  /// Uses a continuous gradient: Green → Yellow → Orange → Red
  Color _dbmToColor(double dbm) {
    // Clamp dBm to the expected range [-97, -22]
    final clamped = dbm.clamp(-97.0, -22.0);
    // Normalize to 0.0 (weakest) ~ 1.0 (strongest)
    final t = (clamped - (-97.0)) / (-22.0 - (-97.0)); // t in [0, 1]
    
    // Define gradient stops: Red (weak) → Orange → Yellow → Green (strong)
    const stops = [0.0, 0.33, 0.66, 1.0];
    const colors = [
      Color(0xFFD50000),  // Red (very poor)
      Color(0xFFFF6D00),  // Orange (weak)
      Color(0xFFFFEA00),  // Yellow (fair)
      Color(0xFF00E676),  // Green (excellent)
    ];
    
    // Find which segment t falls into and interpolate
    for (int i = 0; i < stops.length - 1; i++) {
      if (t >= stops[i] && t <= stops[i + 1]) {
        final localT = (t - stops[i]) / (stops[i + 1] - stops[i]);
        return Color.lerp(colors[i], colors[i + 1], localT)!;
      }
    }
    return colors.last;
  }

  Future<void> _navigateToAP(APInfo ap) async {
    Navigator.pop(context);
    if (_currentLocation == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Current location not available')),
      );
      return;
    }

    try {
      final routeResult = await _apiService.fetchAdvancedRoute(
        _currentLocation!.longitude,
        _currentLocation!.latitude,
        ap.lng,
        ap.lat,
        acceptableRange: 500,
      );

      final pathData = routeResult['path'] as List<dynamic>;
      final path = pathData.map<LatLng>((item) {
        return LatLng(
          (item['lat'] as num).toDouble(),
          (item['lng'] as num).toDouble(),
        );
      }).toList();

      if (path.isNotEmpty) {
        final alternativesData = routeResult['alternatives'] as List<dynamic>? ?? [];
        final alternatives = <RouteAlternative>[];
        
        for (var altData in alternativesData) {
          final altPathData = altData['path'] as List<dynamic>;
          final altPath = altPathData.map<LatLng>((item) {
            return LatLng(
              (item['lat'] as num).toDouble(),
              (item['lng'] as num).toDouble(),
            );
          }).toList();

          alternatives.add(RouteAlternative(
            path: altPath,
            distance: (altData['distance'] as num).toDouble(),
          ));
        }

        if (!mounted) return;
        Navigator.push(
          context,
          MaterialPageRoute(
            builder: (context) => RoutePage(
              path: path,
              title: 'Navigate to ${ap.name ?? 'AP'}',
              alternatives: alternatives,
              totalDistance: (routeResult['distance'] as num?)?.toDouble(),
            ),
          ),
        );
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Error fetching route: $e')),
      );
    }
  }

  void _predictAP(APInfo ap) {
    Navigator.pop(context);
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (context) => PredictorPage(selectedAp: ap),
      ),
    );
  }

  Future<void> _favoriteAP(APInfo ap) async {
    Navigator.pop(context);
    final apInfo = APInfo(
      id: ap.id,
      name: ap.name,
      lat: ap.lat,
      lng: ap.lng,
      building: ap.building,
      height: ap.height,
      espacio: ap.espacio,
    );

    await StorageService.addFavorite(apInfo);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('${ap.name ?? 'AP'} added to favorites')),
    );
  }

  /// Build smooth heatmap grid polygons from the loaded grid points
  List<Polygon> get _smoothHeatmapPolygons {
    if (_smoothHeatmapPoints.isEmpty) return [];
    
    // Estimate grid cell size from the first two points
    final first = _smoothHeatmapPoints[0];
    final second = _smoothHeatmapPoints.length > 1 ? _smoothHeatmapPoints[1] : null;
    double latStep = 0.0004;  // ~40m default fallback
    double lngStep = 0.0004;
    if (second != null) {
      latStep = ((second['lat'] as num) - (first['lat'] as num)).abs().toDouble();
      lngStep = ((second['lng'] as num) - (first['lng'] as num)).abs().toDouble();
      if (latStep == 0) latStep = 0.0004;
      if (lngStep == 0) lngStep = 0.0004;
    }
    // halve the step so cells tile without gaps
    final halfLat = latStep / 2;
    final halfLng = lngStep / 2;

    return _smoothHeatmapPoints.map((point) {
      final lat = (point['lat'] as num).toDouble();
      final lng = (point['lng'] as num).toDouble();
      final quality = point['signal_quality'] as String? ?? 'Fair';
      final color = _signalColors[quality] ?? Colors.grey;
      
      // Create a small rectangle polygon around each grid point
      return Polygon(
        points: [
          LatLng(lat - halfLat, lng - halfLng),
          LatLng(lat - halfLat, lng + halfLng),
          LatLng(lat + halfLat, lng + halfLng),
          LatLng(lat + halfLat, lng - halfLng),
        ],
        color: color.withValues(alpha: 0.35),
        borderColor: color.withValues(alpha: 0.1),
        borderStrokeWidth: 0.5,
      );
    }).toList();
  }

  Widget _buildHeatmapLegend() {
    // Smooth heatmap legend
    if (_showSmoothHeatmap && _smoothHeatmapPoints.isNotEmpty) {
      return Positioned(
        top: 10,
        right: 10,
        child: Card(
          elevation: 4,
          child: Container(
            padding: const EdgeInsets.all(12),
            width: 160,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Signal Strength',
                  style: TextStyle(fontWeight: FontWeight.bold, fontSize: 13),
                ),
                Text(
                  '$_selectedHour:00 (Smooth)',
                  style: const TextStyle(fontSize: 11, color: Colors.grey),

                ),
                const Divider(height: 8),
                for (final entry in _signalColors.entries)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 2),
                    child: Row(
                      children: [
                        Container(
                          width: 12,
                          height: 12,
                          decoration: BoxDecoration(
                            color: entry.value.withValues(alpha: 0.6),
                            shape: BoxShape.circle,
                          ),
                        ),
                        const SizedBox(width: 6),
                        Expanded(
                          child: Text(
                            entry.key,
                            style: const TextStyle(fontSize: 11),
                          ),
                        ),
                      ],
                    ),
                  ),
                const Divider(height: 8),
                Text(
                  '${_smoothHeatmapPoints.length} grid points',
                  style: const TextStyle(fontSize: 10, color: Colors.grey),
                ),
              ],
            ),
          ),
        ),
      );
    }
    
    // Point heatmap legend
    if (!_showHeatmap || _heatmapData == null) return const SizedBox.shrink();
    
    final legend = _heatmapData!['legend'] as Map<String, dynamic>?;
    if (legend == null) return const SizedBox.shrink();
    
    final apPointsData = _heatmapData!['ap_points'] as Map<String, dynamic>? ?? {};
    final totalPoints = apPointsData['total'] ?? 0;
    final buildingsCount = apPointsData['buildings_count'] ?? 0;
    
    return Positioned(
      top: 10,
      right: 10,
      child: Card(
        elevation: 4,
        child: Container(
          padding: const EdgeInsets.all(12),
          width: 160,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Signal Strength',
                style: TextStyle(fontWeight: FontWeight.bold, fontSize: 13),
              ),
              Text(
                '$_selectedHour:00',

                style: const TextStyle(fontSize: 11, color: Colors.grey),
              ),
              const Divider(height: 8),
              for (final entry in legend.entries)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 2),
                  child: Row(
                    children: [
                      Container(
                        width: 12,
                        height: 12,
                        decoration: BoxDecoration(
                          color: _signalColors[entry.key] ?? Colors.grey,
                          shape: BoxShape.circle,
                        ),
                      ),
                      const SizedBox(width: 6),
                      Expanded(
                        child: Text(
                          entry.key,
                          style: const TextStyle(fontSize: 11),
                        ),
                      ),
                    ],
                  ),
                ),
              const Divider(height: 8),
              Text(
                '$totalPoints APs',
                style: const TextStyle(fontSize: 10, color: Colors.grey),
              ),
              Text(
                '$buildingsCount buildings',
                style: const TextStyle(fontSize: 10, color: Colors.grey),
              ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final displayCenter = _currentLocation ?? _center;

    return Scaffold(
      body: Stack(
        children: [
          FlutterMap(
            mapController: _mapController,
            options: MapOptions(
              initialCenter: displayCenter,
              initialZoom: 15.0,
              minZoom: 13.0,
              maxZoom: 19.0,
              keepAlive: true,
              cameraConstraint: CameraConstraint.contain(
                bounds: LatLngBounds(
                  const LatLng(41.47, 2.07),  // 西南角
                  const LatLng(41.54, 2.14),  // 东北角
                ),
              ),
              onMapEvent: (event) {
                // Track zoom level (MapController has no zoom getter)
                if (event is MapEventMoveEnd || event is MapEventFlingAnimationEnd) {
                  _currentZoom = _mapController.camera.zoom;
                  setState(() {});
                }
              },

            ),
            children: [
              TileLayer(
                urlTemplate: 'https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png',
                userAgentPackageName: 'com.uab.wifers',
              ),
              // Smooth heatmap grid overlay (rendered below markers)
              if (_showSmoothHeatmap)
                PolygonLayer(
                  polygons: _smoothHeatmapPolygons,
                ),
              MarkerLayer(
                markers: _markers,
              ),
            ],
          ),
          // Heatmap legend overlay
          _buildHeatmapLegend(),
        ],
      ),
      floatingActionButton: Column(
        mainAxisAlignment: MainAxisAlignment.end,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          // Heatmap toggle button (loads both AP points and smooth grid)
          FloatingActionButton(
            heroTag: 'heatmap',
            mini: true,
            onPressed: _toggleHeatmap,
            backgroundColor: _showHeatmap ? Colors.blue : null,
            child: _isLoadingHeatmap
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : Icon(
                    Icons.layers,
                    color: _showHeatmap ? Colors.white : null,
                  ),
          ),
          if (_showHeatmap) ...[
            const SizedBox(height: 8),
            // Time picker
            FloatingActionButton(
              heroTag: 'time',
              mini: true,
              onPressed: _showHourPicker,
              child: Text(
                '${_selectedHour}h',
                style: const TextStyle(fontSize: 12),
              ),
            ),
          ],
          const SizedBox(height: 16),
          FloatingActionButton.extended(
            heroTag: 'favorites',
            onPressed: () {
              Navigator.push(
                context,
                MaterialPageRoute(builder: (context) => const FavoritesPage()),
              );
            },
            icon: const Icon(Icons.favorite),
            label: const Text('Favorites'),
          ),
          const SizedBox(height: 16),
          FloatingActionButton.extended(
            heroTag: 'predict',
            onPressed: () {
              Navigator.push(
                context,
                MaterialPageRoute(builder: (context) => const PredictorPage()),
              );
            },
            icon: const Icon(Icons.analytics),
            label: const Text('Predict Hotspot'),
          ),
        ],
      ),
    );
  }
}