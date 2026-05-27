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

  // ---------------------------------------------------------------------------
  //  Recommend 模式
  // ---------------------------------------------------------------------------
  bool _isRecommendMode = false;
  bool _isRecommending = false;
  LatLng? _selectedPoint;
  int _recommendRadius = 500;
  String _recommendMode = 'balanced';
  String _recommendBuilding = '';
  List<String> _buildings = [];
  List<Map<String, dynamic>> _recommendResults = [];

  static const Map<String, _ModeDisplay> _modes = {
    'distance': _ModeDisplay('Distance Priority', Icons.near_me, Colors.green),
    'signal': _ModeDisplay('Signal Priority', Icons.signal_wifi_4_bar, Colors.orange),
    'balanced': _ModeDisplay('Balanced', Icons.balance, Colors.blue),
  };

  // ---------------------------------------------------------------------------
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

  Future<void> _loadBuildings() async {
    try {
      final b = await ApDataService.loadBuildings();
      if (mounted) setState(() => _buildings = b);
    } catch (_) {}
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

    // --- 推荐结果标记 (always visible, highest priority) ---
    if (_recommendResults.isNotEmpty && _currentZoom >= 14) {
      for (int i = 0; i < _recommendResults.length; i++) {
        final r = _recommendResults[i];
        final lat = (r['lat'] as num).toDouble();
        final lng = (r['lng'] as num).toDouble();
        final score = (r['score'] as num?)?.toDouble() ?? 0;
        final prediction = r['prediction'] as String? ?? 'Unknown';
        final bgColor = prediction == 'Up' ? Colors.green : Colors.red;
        allMarkers.add(
          Marker(
            point: LatLng(lat, lng),
            width: 40,
            height: 44,
            child: GestureDetector(
              onTap: () => _showRecommendResultDetail(r),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Container(
                    width: 32,
                    height: 32,
                    decoration: BoxDecoration(
                      color: bgColor,
                      shape: BoxShape.circle,
                      border: Border.all(color: Colors.white, width: 2.5),
                      boxShadow: [
                        BoxShadow(
                          color: bgColor.withValues(alpha: 0.5),
                          blurRadius: 8,
                          spreadRadius: 1,
                        ),
                      ],
                    ),
                    child: Center(
                      child: Text(
                        '${i + 1}',
                        style: const TextStyle(
                          color: Colors.white,
                          fontWeight: FontWeight.bold,
                          fontSize: 13,
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    '${(score * 100).toStringAsFixed(0)}%',
                    style: TextStyle(
                      fontSize: 9,
                      fontWeight: FontWeight.w600,
                      color: bgColor,
                    ),
                  ),
                ],
              ),
            ),
          ),
        );
      }
    }

    // --- 选点标记 ---
    if (_selectedPoint != null && (_isRecommendMode || _recommendResults.isNotEmpty)) {
      allMarkers.add(
        Marker(
          point: _selectedPoint!,
          width: 40,
          height: 48,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.location_on, color: Colors.purple, size: 34),
              const Text(
                'HERE',
                style: TextStyle(
                  fontSize: 9,
                  fontWeight: FontWeight.bold,
                  color: Colors.purple,
                ),
              ),
            ],
          ),
        ),
      );
    }

    if (!_shouldShowMarkers) {
      allMarkers.addAll(_currentLocationMarker);
      return allMarkers;
    }

    if (isHeatmapVisible && _recommendResults.isEmpty) {
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
    } else if (_recommendResults.isEmpty) {
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
    _loadBuildings();
    _loadHeatmap();
    _loadRecommendSettings();
  }

  Future<void> _loadRecommendSettings() async {
    final s = await StorageService.loadSettings();
    if (!mounted) return;
    setState(() {
      _recommendRadius = s['recommendRadiusMeters'] as int? ?? 500;
      _recommendMode = s['recommendMode'] as String? ?? 'balanced';
      _recommendBuilding = s['selectedBuilding'] as String? ?? '';
    });
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

  // =========================================================================
  //  Recommend 模式
  // =========================================================================

  void _toggleRecommendMode() {
    setState(() {
      if (_isRecommendMode) {
        // 退 出推荐模式
        _isRecommendMode = false;
        _selectedPoint = null;
        _recommendResults = [];
      } else {
        // 进入推荐模式
        _isRecommendMode = true;
        _selectedPoint = null;
        _recommendResults = [];
      }
    });
  }

  void _onMapTap(TapPosition pos, LatLng point) {
    if (!_isRecommendMode) return;
    // 只有点击在校园范围内才记录
    if (!_isNearCampus(point)) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please select a point inside the UAB campus.')),
      );
      return;
    }
    setState(() {
      _selectedPoint = point;
    });
    _showRecommendSettings();
  }

  Future<void> _showRecommendSettings() async {
    final result = await showModalBottomSheet<Map<String, dynamic>>(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setSheetState) => Padding(
          padding: EdgeInsets.only(
            left: 16,
            right: 16,
            top: 20,
            bottom: MediaQuery.of(ctx).viewInsets.bottom + 20,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Icon(Icons.tune, color: Colors.blue),
                  const SizedBox(width: 8),
                  const Text(
                    'Recommendation Settings',
                    style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                  ),
                  const Spacer(),
                  TextButton(
                    onPressed: () => Navigator.pop(ctx, {
                      'radius': _recommendRadius,
                      'mode': _recommendMode,
                      'building': _recommendBuilding,
                    }),
                    child: const Text('Confirm'),
                  ),
                ],
              ),
              const Divider(),
              // Radius slider
              Row(
                children: [
                  const Icon(Icons.radar, size: 18, color: Colors.grey),
                  const SizedBox(width: 8),
                  const Text('Search Radius: '),
                  Text(
                    '${_recommendRadius}m',
                    style: const TextStyle(fontWeight: FontWeight.bold),
                  ),
                ],
              ),
              Slider(
                value: _recommendRadius.toDouble(),
                min: 100,
                max: 1000,
                divisions: 9,
                label: '${_recommendRadius}m',
                onChanged: (v) => setSheetState(() => _recommendRadius = v.round()),
              ),
              const SizedBox(height: 8),
              // Mode selector
              Row(
                children: [
                  const Icon(Icons.auto_awesome, size: 18, color: Colors.grey),
                  const SizedBox(width: 8),
                  const Text('Mode:'),
                  const SizedBox(width: 8),
                  Expanded(
                    child: SegmentedButton<String>(
                      segments: _modes.entries
                          .map((e) => ButtonSegment<String>(
                                value: e.key,
                                label: Text(e.value.label, style: const TextStyle(fontSize: 11)),
                                icon: Icon(e.value.icon, size: 16),
                              ))
                          .toList(),
                      selected: {_recommendMode},
                      onSelectionChanged: (s) => setSheetState(() => _recommendMode = s.first),
                      showSelectedIcon: false,
                      style: ButtonStyle(
                        visualDensity: VisualDensity.compact,
                        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              // Building filter
              Row(
                children: [
                  const Icon(Icons.business, size: 18, color: Colors.grey),
                  const SizedBox(width: 8),
                  const Text('Building:'),
                  const SizedBox(width: 8),
                  Expanded(
                    child: DropdownButtonHideUnderline(
                      child: DropdownButton<String>(
                        value: _buildings.contains(_recommendBuilding) ? _recommendBuilding : '',
                        isExpanded: true,
                        hint: const Text('All Buildings', style: TextStyle(fontSize: 14)),
                        items: [
                          const DropdownMenuItem(value: '', child: Text('All Buildings', style: TextStyle(fontSize: 14))),
                          ..._buildings.map((b) => DropdownMenuItem(value: b, child: Text(b, style: const TextStyle(fontSize: 14)))),
                        ],
                        onChanged: (v) => setSheetState(() => _recommendBuilding = v ?? ''),
                      ),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );

    if (result != null && _selectedPoint != null) {
      setState(() {
        _recommendRadius = result['radius'] as int;
        _recommendMode = result['mode'] as String;
        _recommendBuilding = result['building'] as String;
      });
      await _performRecommend();
    }
  }

  Future<void> _performRecommend() async {
    if (_selectedPoint == null) return;

    setState(() => _isRecommending = true);

    try {
      final resp = await _apiService.recommendAPs(
        lat: _selectedPoint!.latitude,
        lng: _selectedPoint!.longitude,
        radius: _recommendRadius,
        mode: _recommendMode,
        building: _recommendBuilding,
        preferStable: true,
      );

      final recs = (resp['recommendations'] as List?)
              ?.map((e) => Map<String, dynamic>.from(e as Map))
              .toList() ??
          [];

      setState(() {
        _recommendResults = recs;
        _isRecommending = false;
      });

      if (recs.isNotEmpty) {
        _showRecommendResults();
      }
    } catch (e) {
      setState(() => _isRecommending = false);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Recommendation failed: $e')),
        );
      }
    }
  }

  void _showRecommendResults() {
    if (_recommendResults.isEmpty) return;

    final modeInfo = _modes[_recommendMode]!;
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) => DraggableScrollableSheet(
        initialChildSize: 0.45,
        minChildSize: 0.25,
        maxChildSize: 0.75,
        expand: false,
        builder: (ctx, scrollController) => Column(
          children: [
            const SizedBox(height: 8),
            Container(
              width: 40,
              height: 4,
              decoration: BoxDecoration(
                color: Colors.grey[300],
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(16),
              child: Row(
                children: [
                  Icon(modeInfo.icon, color: modeInfo.color),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'Top ${_recommendResults.length} APs ($_recommendRadius m)',
                      style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                    ),
                  ),
                  IconButton(
                    icon: const Icon(Icons.close),
                    onPressed: () => Navigator.pop(ctx),
                  ),
                ],
              ),
            ),
            Expanded(
              child: ListView.separated(
                controller: scrollController,
                itemCount: _recommendResults.length,
                separatorBuilder: (_, __) => const Divider(height: 1),
                itemBuilder: (ctx, i) {
                  final r = _recommendResults[i];
                  final name = r['name'] as String? ?? '';
                  final building = r['building'] as String? ?? 'Unknown';
                  final floor = r['floor'];
                  final distance = (r['distance'] as num?)?.toDouble() ?? 0;
                  final score = (r['score'] as num?)?.toDouble() ?? 0;
                  final prediction = r['prediction'] as String? ?? 'Unknown';
                  final signalDb = (r['signal_db'] as num?)?.toDouble() ?? -70;
                  final upProb = (r['up_probability'] as num?)?.toDouble() ?? 0;
                  final lat = (r['lat'] as num).toDouble();
                  final lng = (r['lng'] as num).toDouble();

                  return ListTile(
                    leading: Stack(
                      children: [
                        CircleAvatar(
                          backgroundColor: modeInfo.color.withValues(alpha: 0.15),
                          child: Text(
                            '${i + 1}',
                            style: TextStyle(fontWeight: FontWeight.bold, color: modeInfo.color),
                          ),
                        ),
                        if (i < 3)
                          Positioned(
                            right: 0,
                            top: 0,
                            child: Icon(Icons.star, size: 12, color: Colors.amber[700]),
                          ),
                      ],
                    ),
                    title: Text(name, style: const TextStyle(fontWeight: FontWeight.w600)),
                    subtitle: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '$building • ${floor != null ? 'Floor $floor' : 'Floor unknown'}',
                          style: TextStyle(fontSize: 12, color: Colors.grey[600]),
                        ),
                        const SizedBox(height: 2),
                        Row(
                          children: [
                            Icon(Icons.near_me, size: 12, color: Colors.grey[600]),
                            const SizedBox(width: 2),
                            Text('${distance.toStringAsFixed(0)} m', style: TextStyle(fontSize: 11, color: Colors.grey[600])),
                            const SizedBox(width: 10),
                            Icon(Icons.signal_wifi_4_bar, size: 12, color: _dbmToColor(signalDb)),
                            const SizedBox(width: 2),
                            Text('${signalDb.toStringAsFixed(1)} dBm', style: TextStyle(fontSize: 11, color: _dbmToColor(signalDb))),
                          ],
                        ),
                      ],
                    ),
                    trailing: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      crossAxisAlignment: CrossAxisAlignment.end,
                      children: [
                        Text(
                          '${(score * 100).toStringAsFixed(0)}%',
                          style: TextStyle(
                            fontWeight: FontWeight.bold,
                            color: prediction == 'Up' ? Colors.green : Colors.red,
                            fontSize: 16,
                          ),
                        ),
                        Text('${upProb.toStringAsFixed(0)}% ↑', style: TextStyle(fontSize: 10, color: Colors.grey[500])),
                      ],
                    ),
                    onTap: () {
                      Navigator.pop(ctx);
                      _navigateToRecommendAp(
                        name: name,
                        lat: lat,
                        lng: lng,
                      );
                    },
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  void _showRecommendResultDetail(Map<String, dynamic> r) {
    final name = r['name'] as String? ?? '';
    final building = r['building'] as String? ?? 'Unknown';
    final floor = r['floor'];
    final distance = (r['distance'] as num?)?.toDouble() ?? 0;
    final score = (r['score'] as num?)?.toDouble() ?? 0;
    final prediction = r['prediction'] as String? ?? 'Unknown';
    final signalDb = (r['signal_db'] as num?)?.toDouble() ?? -70;
    final upProb = (r['up_probability'] as num?)?.toDouble() ?? 0;
    final lat = (r['lat'] as num).toDouble();
    final lng = (r['lng'] as num).toDouble();

    final color = prediction == 'Up' ? Colors.green : Colors.red;
    showModalBottomSheet(
      context: context,
      builder: (ctx) => Container(
        padding: const EdgeInsets.all(16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(name, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            const SizedBox(height: 4),
            Text('$building • Floor ${floor ?? "?"}', style: TextStyle(color: Colors.grey[600])),
            const SizedBox(height: 12),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceEvenly,
              children: [
                _buildStat('Distance', '${distance.toStringAsFixed(0)} m', Icons.near_me, Colors.blue),
                _buildStat('Signal', '${signalDb.toStringAsFixed(1)} dBm', Icons.signal_wifi_4_bar, _dbmToColor(signalDb)),
                _buildStat('Stability', '${upProb.toStringAsFixed(0)}% ↑', Icons.trending_up, color),
                _buildStat('Score', '${(score * 100).toStringAsFixed(0)}%', Icons.star, Colors.amber),
              ],
            ),
            const SizedBox(height: 16),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceEvenly,
              children: [
                _buildActionButton(
                  icon: Icons.directions,
                  label: 'Navigate',
                  color: Colors.blue,
                  onPressed: () {
                    Navigator.pop(ctx);
                    _navigateToRecommendAp(name: name, lat: lat, lng: lng);
                  },
                ),
                _buildActionButton(
                  icon: Icons.cancel,
                  label: 'Close',
                  color: Colors.grey,
                  onPressed: () => Navigator.pop(ctx),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildStat(String label, String value, IconData icon, Color color) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, color: color, size: 22),
        const SizedBox(height: 4),
        Text(value, style: TextStyle(fontWeight: FontWeight.bold, color: color, fontSize: 13)),
        Text(label, style: TextStyle(fontSize: 10, color: Colors.grey[600])),
      ],
    );
  }

  // =========================================================================

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

  /// Navigate to a recommend-result AP.
  Future<void> _navigateToRecommendAp({
    required String name,
    required double lat,
    required double lng,
  }) async {
    try {
      final p = await LocationService.getCurrentPosition();
      final pos = LatLng(p.latitude, p.longitude);

      if (!LocationService.isNearCampus(pos)) {
        final useGate = await showDialog<bool>(
          context: context,
          builder: (c) => AlertDialog(
            title: const Text('Outside Campus'),
            content: const Text('Start navigation from campus gate?'),
            actions: [
              TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
              TextButton(onPressed: () => Navigator.pop(c, true), child: const Text('Use Gate')),
            ],
          ),
        );
        if (useGate != true) return;
        final path = await _apiService.fetchRoute(
          LocationService.campusGateLng,
          LocationService.campusGateLat,
          lng,
          lat,
        );
        if (path.isNotEmpty && mounted) {
          Navigator.push(
            context,
            MaterialPageRoute(
              builder: (_) => RoutePage(
                path: path,
                title: 'Navigate to $name (from Gate)',
              ),
            ),
          );
        }
        return;
      }

      final routeResult = await _apiService.fetchAdvancedRoute(
        p.longitude,
        p.latitude,
        lng,
        lat,
        acceptableRange: 500,
      );
      final pathData = routeResult['path'] as List<dynamic>;
      final path = pathData
          .map<LatLng>((item) => LatLng(
                (item['lat'] as num).toDouble(),
                (item['lng'] as num).toDouble(),
              ))
          .toList();

      if (path.isNotEmpty && mounted) {
        Navigator.push(
          context,
          MaterialPageRoute(
            builder: (_) => RoutePage(path: path, title: 'Navigate to $name'),
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Navigation error: $e')),
        );
      }
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

  /// Build smooth heatmap grid polygons from the loaded grid points
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

  // =========================================================================
  //  Recommend 模式提示条
  // =========================================================================
  Widget _buildRecommendBanner() {
    if (!_isRecommendMode) return const SizedBox.shrink();
    return Positioned(
      top: 10,
      left: 10,
      right: 70,
      child: Material(
        elevation: 4,
        borderRadius: BorderRadius.circular(12),
        color: Colors.blue.shade700,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          child: Row(
            children: [
              const Icon(Icons.touch_app, color: Colors.white, size: 20),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  _selectedPoint == null
                      ? 'Tap on the map to choose a location'
                      : 'Location selected! Tap ✓ to configure',
                  style: const TextStyle(color: Colors.white, fontSize: 13),
                ),
              ),
              if (_selectedPoint != null)
                IconButton(
                  icon: const Icon(Icons.check_circle, color: Colors.white),
                  onPressed: _showRecommendSettings,
                  padding: EdgeInsets.zero,
                  constraints: const BoxConstraints(),
                ),
              IconButton(
                icon: const Icon(Icons.close, color: Colors.white70),
                onPressed: _toggleRecommendMode,
                padding: EdgeInsets.zero,
                constraints: const BoxConstraints(),
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
              onTap: _onMapTap,
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
          // Recommend banner
          _buildRecommendBanner(),
          // Recommend loading indicator
          if (_isRecommending)
            const Positioned(
              top: 60,
              left: 10,
              child: Card(
                child: Padding(
                  padding: EdgeInsets.all(12),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)),
                      SizedBox(width: 8),
                      Text('Finding best APs...'),
                    ],
                  ),
                ),
              ),
            ),
        ],
      ),
      floatingActionButton: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          // Recommend FAB
          FloatingActionButton(
            heroTag: 'recommend',
            mini: true,
            backgroundColor: _isRecommendMode ? Colors.red : Colors.green,
            onPressed: _toggleRecommendMode,
            child: Icon(
              _isRecommendMode ? Icons.close : Icons.recommend,
              color: Colors.white,
            ),
          ),
          const SizedBox(height: 8),
          // Time picker FAB
          FloatingActionButton(
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
        ],
      ),
    );
  }
}

class _ModeDisplay {
  final String label;
  final IconData icon;
  final Color color;
  const _ModeDisplay(this.label, this.icon, this.color);
}