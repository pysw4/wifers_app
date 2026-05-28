import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:geolocator/geolocator.dart';
import 'package:latlong2/latlong.dart';
import 'package:wifers_app/services/api_service.dart';
import 'package:wifers_app/services/ap_data_service.dart';
import 'package:wifers_app/services/heatmap_asset_service.dart';
import 'package:wifers_app/services/location_service.dart';
import 'package:wifers_app/services/storage_service.dart';
import 'package:wifers_app/services/cache_service.dart';
import 'package:wifers_app/models/ap_info.dart';
import 'package:wifers_app/pages/route_page.dart';
import 'package:wifers_app/pages/ap_trend_dialog.dart';

class MapPage extends StatefulWidget {
  const MapPage({super.key});

  @override
  State<MapPage> createState() => _MapPageState();
}

class _MapPageState extends State<MapPage> {
  final ApiService _apiService = ApiService();
  final MapController _mapController = MapController();

  // UAB campus core bounds
  static const double _campusMinLat = 41.492;
  static const double _campusMaxLat = 41.514;
  static const double _campusMinLng = 2.092;
  static const double _campusMaxLng = 2.118;
  static final LatLng _center = LatLng(41.503, 2.105); // UAB campus center
  static final LatLngBounds _campusBounds = LatLngBounds(
    LatLng(_campusMinLat, _campusMinLng),
    LatLng(_campusMaxLat, _campusMaxLng),
  );
  static const double _campusRadiusKm = 1.2; // ~1.2km from center
  static const double _defaultZoom = 15.5;
  static const double _minZoom = 14.5;
  static const double _maxZoom = 19.0;
  LatLng? _currentLocation;
  StreamSubscription<Position>? _positionSubscription;

  double _currentZoom = 15.0; // Track zoom level manually (MapController has no zoom getter)

  final List<APInfo> _aps = [];

  // Heatmap state — always on, loaded on init
  bool _isLoadingHeatmap = false;
  int _selectedHour = DateTime.now().hour;

  // Day of week selection: 0=Mon, 6=Sun
  static const List<String> _dayNames = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  static const List<String> _dayApiNames = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
  int _selectedDay = DateTime.now().weekday - 1; // DateTime.monday=1 -> our index 0
  String get _selectedDayApiName => _dayApiNames[_selectedDay];
  final Map<String, Color> _signalColors = {
    'Excellent': const Color(0xFF00E676), // Bright Green (strongest signal)
    'Good': const Color(0xFF76FF03), // Light Green
    'Fair': const Color(0xFFFFEA00), // Yellow
    'Weak': const Color(0xFFFF6D00), // Orange
    'Very Poor': const Color(0xFFD50000), // Red (weakest signal)
  };

  // Cache heatmap predictions by AP name
  Map<String, Map<String, dynamic>> _heatmapCache = {};
  Timer? _heatmapRefreshTimer;

  // Smooth heatmap state (grid mode) - loaded together with AP heatmap data
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
    if (_smoothHeatmapPoints.isNotEmpty && _currentZoom < 12) return false;
    return true;
  }

  List<Marker> get _markers {
    final markerSize = _getMarkerSize();
    final heatmapSize = _getMarkerSize(isHeatmap: true);
    final heatmapTextSize = _getHeatmapTextSize();
    final isHeatmapVisible = _heatmapCache.isNotEmpty;

    final List<Marker> allMarkers = [];

    if (!_shouldShowMarkers) {
      allMarkers.addAll(_currentLocationMarker);
      return allMarkers;
    }

    if (isHeatmapVisible) {
      // Heatmap mode: color-coded markers
      for (final ap in _aps) {
        final key = ap.id ?? ap.name ?? '';
        final prediction = _heatmapCache[key];
        if (prediction == null) continue;
        final dbm = prediction['signal_db'] as num? ?? -70;
        final quality = prediction['signal_quality'] as String? ?? 'Fair';
        final color = _signalColors[quality] ?? Colors.grey;
        final showDetail = heatmapSize >= 14;

        allMarkers.add(
          Marker(
            point: LatLng(ap.lat, ap.lng),
            width: heatmapSize,
            height: heatmapSize,
            child: GestureDetector(
              onTap: () => _showAPOptions(ap, signalDb: dbm.toDouble()),
              child: Container(
                decoration: BoxDecoration(
                  color: color.withValues(alpha: showDetail ? 0.6 : 0.4),
                  shape: BoxShape.circle,
                  border: Border.all(
                    color: Colors.white.withValues(alpha: showDetail ? 0.8 : 0.4),
                    width: showDetail ? 2 : 1,
                  ),
                  boxShadow: showDetail
                      ? [
                          BoxShadow(
                            color: color.withValues(alpha: 0.4),
                            blurRadius: 8,
                            spreadRadius: 2,
                          ),
                        ]
                      : null,
                ),
                child: showDetail
                    ? Center(
                        child: Text(
                          '${dbm.toInt()}',
                          style: TextStyle(
                            color: Colors.white,
                            fontSize: heatmapTextSize,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      )
                    : null,
              ),
            ),
          ),
        );
      }
    } else {
      // Normal mode: small dots (hidden when zoom < 12)
      if (markerSize > 0) {
        for (final ap in _aps) {
          allMarkers.add(
            Marker(
              point: LatLng(ap.lat, ap.lng),
              width: markerSize + 16, // more touch area than visible dot
              height: markerSize + 16,
              child: GestureDetector(
                onTap: () => _showAPOptions(ap),
                child: Container(
                  width: markerSize,
                  height: markerSize,
                  decoration: BoxDecoration(
                    color: const Color.fromRGBO(33, 150, 243, 0.5),
                    shape: BoxShape.circle,
                    border: Border.all(
                      color: const Color.fromRGBO(255, 255, 255, 0.8),
                      width: 1,
                    ),
                  ),
                ),
              ),
            ),
          );
        }
      }
    }

    allMarkers.addAll(_currentLocationMarker);
    return allMarkers;
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
    _loadHeatmap();
  }

  @override
  void dispose() {
    _positionSubscription?.cancel();
    _heatmapRefreshTimer?.cancel();
    super.dispose();
  }

  /// 判断用户是否在校园附近
  bool _isNearCampus(LatLng location) {
    final distance = const Distance().as(
      LengthUnit.Kilometer,
      location,
      _center,
    );
    return distance <= _campusRadiusKm;
  }

  Future<void> _startLocationTracking() async {
    try {
      final position = await LocationService.getCurrentPosition();
      final userLocation = LatLng(position.latitude, position.longitude);
      setState(() {
        _currentLocation = userLocation;
      });

      // 如果用户不在校园附近，地图默认显示校园中心
      if (!_isNearCampus(userLocation)) {
        _mapController.move(_center, _defaultZoom);
      }

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
      // Handle location error - 默认显示校园中心
      _mapController.move(_center, _defaultZoom);
    }
  }

  Future<void> _loadHeatmap() async {
    if (_isLoadingHeatmap) return;

    setState(() {
      _isLoadingHeatmap = true;
    });

    try {
      // Build cache key (include day for 7-day support)
      final cacheKey = 'heatmap_${_selectedDayApiName}_$_selectedHour';
      const heatmapTtl = Duration(minutes: 30);

      // Try cache first
      final cachedData = await CacheService.get<Map<String, dynamic>>(cacheKey, ttl: heatmapTtl);
      if (cachedData != null) {
        _processHeatmapData(cachedData);
        debugPrint('Loaded heatmap data (cached)');
        return;
      }

      // Try loading from static files first (avoids API cold start / quota)
      try {
        final staticData = await HeatmapAssetService.loadHeatmap(
          hour: _selectedHour,
          day: _selectedDayApiName,
        );
        await CacheService.set(cacheKey, staticData);
        _processHeatmapData(staticData);
        debugPrint('Loaded heatmap from static file');
        return;
      } catch (staticError) {
        debugPrint('Static heatmap load failed, falling back to API: $staticError');
      }

      // Fallback: load from API
      final data = await _apiService.getSignalHeatmap(
        hour: _selectedHour,
        day: _selectedDayApiName,
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
      _smoothHeatmapPoints = parsedSmoothPoints;
      _isLoadingHeatmap = false;
    });

    debugPrint('Loaded ${cache.length} AP points + ${parsedSmoothPoints.length} grid points');
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
              Text('Current: $_selectedHour h'),
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
                        child: Text('$index'),
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
      _loadHeatmap(); // Refresh with new time (loads both AP points and smooth grid)
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

    final color = predictedStatus == 'Up'
        ? Colors.green
        : predictedStatus == 'Down'
            ? Colors.red
            : Colors.orange;

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
                _buildActionButton(
                  icon: Icons.directions,
                  label: 'Navigate',
                  color: Colors.blue,
                  onPressed: () => _navigateToAP(ap),
                ),
                _buildActionButton(
                  icon: Icons.trending_up,
                  label: '24h Trend',
                  color: Colors.orange,
                  onPressed: () => _showAPTrend(ap),
                ),
                _buildActionButton(
                  icon: Icons.favorite,
                  label: 'Favorite',
                  color: Colors.red,
                  onPressed: () => _favoriteAP(ap),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  /// 构建底部操作按钮（紧凑样式）
  Widget _buildActionButton({
    required IconData icon,
    required String label,
    required Color color,
    required VoidCallback onPressed,
  }) {
    return SizedBox(
      child: TextButton(
        onPressed: onPressed,
        style: TextButton.styleFrom(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
          minimumSize: Size.zero,
          tapTargetSize: MaterialTapTargetSize.shrinkWrap,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 22, color: color),
            const SizedBox(height: 2),
            Text(label, style: TextStyle(fontSize: 11, color: color)),
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
      Color(0xFFD50000), // Red (very poor)
      Color(0xFFFF6D00), // Orange (weak)
      Color(0xFFFFEA00), // Yellow (fair)
      Color(0xFF00E676), // Green (excellent)
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
    // 先关闭 bottom sheet（使用 rootNavigator 确保只关闭 bottom sheet 不 pop 页面）
    Navigator.of(context, rootNavigator: true).pop();

    if (_currentLocation == null) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Current location not available')),
      );
      return;
    }

    // Check if user is near campus
    if (!LocationService.isNearCampus(_currentLocation!)) {
      if (!mounted) return;
      final startFromGate = await showDialog<bool>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: const Text('Outside Campus Area'),
          content: const Text(
            'You are currently outside the UAB campus area. '
            'Navigation is only available from within the campus.\n\n'
            'Would you like to start navigation from the campus main entrance instead?',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('Cancel'),
            ),
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, true),
              child: const Text('Start from Gate'),
            ),
          ],
        ),
      );
      if (startFromGate != true) return;
      // Navigate from campus gate
      _navigateFromGate(ap);
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

  /// Navigate from the campus main entrance to the target AP.
  /// 直接从校门（campusGate）导航到目标AP，不检查用户当前位置。
  Future<void> _navigateFromGate(APInfo ap) async {
    // 先关闭 bottom sheet
    Navigator.of(context, rootNavigator: true).pop();

    if (!mounted) return;

    try {
      final routeResult = await _apiService.fetchAdvancedRoute(
        LocationService.campusGateLng,
        LocationService.campusGateLat,
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

      if (path.isNotEmpty && mounted) {
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
              title: 'Navigate to ${ap.name ?? 'AP'} (from Gate)',
              alternatives: alternatives,
              totalDistance: (routeResult['distance'] as num?)?.toDouble(),
            ),
          ),
        );
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Error fetching route from gate: $e')),
      );
    }
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

  void _showAPTrend(APInfo ap) {
    // 使用 Navigator.of(context, rootNavigator: true) 确保能正确关闭 bottom sheet
    final navigator = Navigator.of(context);
    navigator.pop(); // 关闭 bottom sheet
    // 使用 rootNavigator 打开 dialog，避免 context 失效问题
    showDialog(
      context: context,
      builder: (dialogContext) => APTrendDialog(
        apName: ap.name ?? ap.id ?? 'Unknown AP',
        building: ap.building,
      ),
    );
  }

  /// Maximum distance (in meters) from the nearest AP for a grid point
  /// to be considered "covered". Points farther than this are hidden.
  static const double _apCoverageRadiusM = 30.0;

  /// Haversine distance in meters between two lat/lng points.
  static double _haversineM(double lat1, double lng1, double lat2, double lng2) {
    const double r = 6371000; // Earth radius in meters
    final dLat = (lat2 - lat1) * math.pi / 180;
    final dLng = (lng2 - lng1) * math.pi / 180;
    final a = math.sin(dLat / 2) * math.sin(dLat / 2) +
        math.cos(lat1 * math.pi / 180) *
            math.cos(lat2 * math.pi / 180) *
            math.sin(dLng / 2) * math.sin(dLng / 2);
    final c = 2 * math.asin(math.sqrt(a));
    return r * c;
  }

  /// Map a signal_db value to a color.
  /// - Strong signal (-50 dBm or better) → green
  /// - Medium (-60 dBm) → yellow
  /// - Weak (-70 dBm or worse) → red
  static Color _signalDbToColor(double signalDb) {
    // Clamp to [-80, -50] range
    final clamped = signalDb.clamp(-80.0, -50.0);
    // Normalize: -80 → 0.0 (worst/red), -50 → 1.0 (best/green)
    final t = (clamped + 80.0) / 30.0;
    // Interpolate: red (0.0) → yellow (0.5) → green (1.0)
    if (t < 0.5) {
      // Red → Yellow
      final u = t / 0.5; // 0.0 → 1.0
      return Color.lerp(
        const Color(0xFFD50000), // Red
        const Color(0xFFFFEA00), // Yellow
        u,
      )!;
    } else {
      // Yellow → Green
      final u = (t - 0.5) / 0.5; // 0.0 → 1.0
      return Color.lerp(
        const Color(0xFFFFEA00), // Yellow
        const Color(0xFF00E676), // Green
        u,
      )!;
    }
  }

  /// Build smooth heatmap grid polygons from the loaded grid points.
  ///
  /// Grid points that are farther than [_apCoverageRadiusM] from the nearest
  /// AP are hidden (transparent). Points near APs are coloured by signal_db:
  /// strong → green, medium → yellow, weak → red.
  List<Polygon> get _smoothHeatmapPolygons {
    if (_smoothHeatmapPoints.isEmpty) return [];

    // Estimate grid cell size from the first two points
    final first = _smoothHeatmapPoints[0];
    final second = _smoothHeatmapPoints.length > 1 ? _smoothHeatmapPoints[1] : null;
    double latStep = 0.0004; // ~40m default fallback
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
      final signalDb = (point['signal_db'] as num?)?.toDouble() ?? -70.0;

      // Find distance to nearest AP
      double minDist = double.infinity;
      for (final ap in _aps) {
        final d = _haversineM(lat, lng, ap.lat, ap.lng);
        if (d < minDist) minDist = d;
      }

      // If no AP is nearby, hide this grid cell
      if (minDist > _apCoverageRadiusM) {
        return Polygon(
          points: [
            LatLng(lat - halfLat, lng - halfLng),
            LatLng(lat - halfLat, lng + halfLng),
            LatLng(lat + halfLat, lng + halfLng),
            LatLng(lat + halfLat, lng - halfLng),
          ],
          color: Colors.transparent,
          borderColor: Colors.transparent,
          borderStrokeWidth: 0,
        );
      }

      final color = _signalDbToColor(signalDb);

      // Create a small rectangle polygon around each grid point
      return Polygon(
        points: [
          LatLng(lat - halfLat, lng - halfLng),
          LatLng(lat - halfLat, lng + halfLng),
          LatLng(lat + halfLat, lng + halfLng),
          LatLng(lat + halfLat, lng - halfLng),
        ],
        color: color.withValues(alpha: 0.45),
        borderColor: color.withValues(alpha: 0.15),
        borderStrokeWidth: 0.5,
      );
    }).toList();
  }

  Widget _buildDaySelector() {
    return Positioned(
      bottom: 80,
      left: 10,
      right: 10,
      child: Center(
        child: Card(
          elevation: 4,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: List.generate(7, (index) {
                final isSelected = index == _selectedDay;
                return Padding(
                  padding: const EdgeInsets.all(2),
                  child: GestureDetector(
                    onTap: () {
                      if (index != _selectedDay) {
                        setState(() {
                          _selectedDay = index;
                        });
                        _loadHeatmap();
                      }
                    },
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
                      decoration: BoxDecoration(
                        color: isSelected ? Colors.blue : Colors.transparent,
                        borderRadius: BorderRadius.circular(16),
                      ),
                      child: Text(
                        _dayNames[index],
                        style: TextStyle(
                          fontSize: 12,
                          fontWeight: isSelected ? FontWeight.bold : FontWeight.normal,
                          color: isSelected ? Colors.white : Colors.black87,
                        ),
                      ),
                    ),
                  ),
                );
              }),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildHeatmapLegend() {
    if (_smoothHeatmapPoints.isNotEmpty) {
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
                  '${_dayNames[_selectedDay]} $_selectedHour:00',
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
    return const SizedBox.shrink();
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
              initialZoom: _defaultZoom,
              minZoom: _minZoom,
              maxZoom: _maxZoom,
              keepAlive: true,
              cameraConstraint: CameraConstraint.contain(
                bounds: _campusBounds,
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
          // Day of week selector
          _buildDaySelector(),
        ],
      ),
      floatingActionButton: FloatingActionButton(
        heroTag: 'time',
        mini: true,
        onPressed: _showHourPicker,
        child: _isLoadingHeatmap
            ? const SizedBox(
                width: 20,
                height: 20,
                child: CircularProgressIndicator(strokeWidth: 2),
              )
            : Text(
                '${_selectedHour}h',
                style: const TextStyle(fontSize: 12),
              ),
      ),
    );
  }
}
