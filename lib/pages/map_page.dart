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
import 'package:wifers_app/services/foto2ap_service.dart';
import 'package:wifers_app/models/ap_info.dart';
import 'package:wifers_app/pages/route_page.dart';
import 'package:wifers_app/pages/ap_trend_dialog.dart';
import 'package:image_picker/image_picker.dart';

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

  // Day of week — always use current day
  static const List<String> _dayNames = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  static const List<String> _dayApiNames = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
  int get _currentDayIndex => DateTime.now().weekday - 1; // DateTime.monday=1 -> our index 0
  String get _currentDayApiName => _dayApiNames[_currentDayIndex];

  // Dynamic signal range (computed from actual data)
  double _signalMinDb = -75.0; // default fallback (legend display - actual min)
  double _signalMaxDb = -50.0; // default fallback (legend display - actual max)
  double _colorMapMinDb = -75.0; // color mapping uses p2~p98 to avoid outliers
  double _colorMapMaxDb = -50.0; // color mapping uses p2~p98 to avoid outliers

  // Cache heatmap predictions by AP name
  Map<String, Map<String, dynamic>> _heatmapCache = {};
  Timer? _heatmapRefreshTimer;

  // Smooth heatmap state (grid mode) - loaded together with AP heatmap data
  List<Map<String, dynamic>> _smoothHeatmapPoints = [];

  // -----------------------------------------------------------------------
  // Foto2AP state
  // -----------------------------------------------------------------------
  bool _isFoto2ApMode = false;
  bool _isFoto2ApLoading = false;
  Foto2ApResult? _foto2ApResult;

  /// Pick an image from gallery or camera and recognise the AP.
  Future<void> _startFoto2Ap(ImageSource source) async {
    final picker = ImagePicker();
    final XFile? image = await picker.pickImage(
      source: source,
      maxWidth: 1920,
      maxHeight: 1920,
      imageQuality: 85,
    );
    if (image == null) return;

    setState(() {
      _isFoto2ApLoading = true;
      _isFoto2ApMode = true;
      // Clear heatmap so we only show the recognised AP marker
      _heatmapCache = {};
      _smoothHeatmapPoints = [];
    });

    try {
      final result = await Foto2ApService.recognizeAp(image.path);
      setState(() {
        _foto2ApResult = result;
        _isFoto2ApLoading = false;
      });

      if (result.success && result.lat != null && result.lng != null) {
        // Fly to the recognised AP location
        _mapController.move(LatLng(result.lat!, result.lng!), 18.0);
      } else if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(result.errorMessage ?? 'No AP recognised'),
            backgroundColor: Colors.orange,
          ),
        );
      }
    } catch (e) {
      setState(() {
        _isFoto2ApLoading = false;
      });
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Foto2AP error: $e')),
        );
      }
    }
  }

  /// Show a bottom sheet to choose camera, gallery, or manual input.
  Future<void> _showFoto2ApSourcePicker() async {
    final action = await showModalBottomSheet<String>(
      context: context,
      builder: (context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text(
                'Find AP Location',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 16),
              ListTile(
                leading: const Icon(Icons.camera_alt, color: Colors.blue),
                title: const Text('Take a Photo'),
                subtitle: const Text('Use camera to capture AP label'),
                onTap: () => Navigator.pop(context, 'camera'),
              ),
              ListTile(
                leading: const Icon(Icons.photo_library, color: Colors.green),
                title: const Text('Choose from Gallery'),
                subtitle: const Text('Select an existing photo'),
                onTap: () => Navigator.pop(context, 'gallery'),
              ),
              const Divider(),
              ListTile(
                leading: const Icon(Icons.edit, color: Colors.orange),
                title: const Text('Manually enter AP name'),
                subtitle: const Text('Type the AP name to locate it'),
                onTap: () => Navigator.pop(context, 'manual'),
              ),
            ],
          ),
        ),
      ),
    );

    if (action == 'camera') {
      _startFoto2Ap(ImageSource.camera);
    } else if (action == 'gallery') {
      _startFoto2Ap(ImageSource.gallery);
    } else if (action == 'manual') {
      _showManualApInputDialog();
    }
  }

  /// Clear Foto2AP mode and restore heatmap.
  void _clearFoto2Ap() {
    setState(() {
      _isFoto2ApMode = false;
      _foto2ApResult = null;
    });
    _loadHeatmap();
  }

  /// Look up an AP by name (case-insensitive) in the loaded [_aps] list.
  APInfo? _lookupApByName(String query) {
    final q = query.trim().toUpperCase();
    for (final ap in _aps) {
      if (ap.name?.toUpperCase() == q) return ap;
    }
    return null;
  }

  /// Show a dialog to manually enter an AP name, with autocomplete suggestions.
  Future<void> _showManualApInputDialog() async {
    final controller = TextEditingController();
    final focusNode = FocusNode();
    String selectedName = '';
    List<APInfo> suggestions = [];

    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) {
        return StatefulBuilder(
          builder: (context, setDialogState) {
            // Filter suggestions based on input
            void updateSuggestions(String input) {
              final q = input.trim().toUpperCase();
              if (q.isEmpty) {
                setDialogState(() => suggestions = []);
                return;
              }
              setDialogState(() {
                suggestions = _aps.where((ap) {
                  final name = ap.name?.toUpperCase() ?? '';
                  return name.contains(q);
                }).take(20).toList();
              });
            }

            return AlertDialog(
              title: const Row(
                children: [
                  Icon(Icons.edit, color: Colors.orange, size: 22),
                  SizedBox(width: 8),
                  Text('Enter AP Name', style: TextStyle(fontSize: 17)),
                ],
              ),
              content: SizedBox(
                width: double.maxFinite,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    TextField(
                      controller: controller,
                      focusNode: focusNode,
                      autofocus: true,
                      decoration: InputDecoration(
                        hintText: 'e.g. AP-ETSE58',
                        prefixIcon: const Icon(Icons.search, size: 20),
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(12),
                        ),
                        contentPadding: const EdgeInsets.symmetric(
                          horizontal: 16,
                          vertical: 12,
                        ),
                      ),
                      textInputAction: TextInputAction.search,
                      onChanged: (value) {
                        selectedName = value;
                        updateSuggestions(value);
                      },
                      onSubmitted: (value) {
                        selectedName = value;
                        // Try to find and submit
                        final ap = _lookupApByName(value);
                        if (ap != null) {
                          Navigator.pop(dialogContext);
                          _applyManualApResult(ap);
                        }
                      },
                    ),
                    if (suggestions.isNotEmpty) ...[
                      const SizedBox(height: 8),
                      const Divider(height: 1),
                      const SizedBox(height: 4),
                      Text(
                        'Suggestions (${suggestions.length}):',
                        style: TextStyle(
                          fontSize: 12,
                          color: Colors.grey[600],
                        ),
                      ),
                      const SizedBox(height: 4),
                      SizedBox(
                        height: (suggestions.length * 44).clamp(0, 220).toDouble(),
                        child: ListView.builder(
                          itemCount: suggestions.length,
                          itemBuilder: (context, index) {
                            final ap = suggestions[index];
                            return ListTile(
                              dense: true,
                              leading: const Icon(
                                Icons.wifi,
                                size: 18,
                                color: Color(0xFF7C4DFF),
                              ),
                              title: Text(
                                ap.name ?? '',
                                style: const TextStyle(
                                  fontSize: 13,
                                  fontWeight: FontWeight.w500,
                                ),
                              ),
                              subtitle: Text(
                                '${ap.building} · Floor ${ap.height ?? '?'}',
                                style: TextStyle(
                                  fontSize: 11,
                                  color: Colors.grey[600],
                                ),
                              ),
                              onTap: () {
                                Navigator.pop(dialogContext);
                                _applyManualApResult(ap);
                              },
                            );
                          },
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(dialogContext),
                  child: const Text('Cancel'),
                ),
                FilledButton.icon(
                  onPressed: () {
                    final ap = _lookupApByName(selectedName);
                    if (ap != null) {
                      Navigator.pop(dialogContext);
                      _applyManualApResult(ap);
                    } else {
                      ScaffoldMessenger.of(context).showSnackBar(
                        SnackBar(
                          content: Text('No AP found matching "$selectedName"'),
                          backgroundColor: Colors.orange,
                        ),
                      );
                    }
                  },
                  icon: const Icon(Icons.search, size: 18),
                  label: const Text('Search'),
                ),
              ],
            );
          },
        );
      },
    );

    controller.dispose();
    focusNode.dispose();
  }

  /// Apply a manually selected AP result: enter Foto2AP mode and show the marker.
  void _applyManualApResult(APInfo ap) {
    setState(() {
      _isFoto2ApMode = true;
      _heatmapCache = {};
      _smoothHeatmapPoints = [];
      _foto2ApResult = Foto2ApResult(
        success: true,
        apName: ap.name,
        lat: ap.lat,
        lng: ap.lng,
        building: ap.building,
        floor: ap.height,
        espacio: ap.espacio,
      );
    });
    _mapController.move(LatLng(ap.lat, ap.lng), 18.0);
  }

  /// Build the Foto2AP result marker (large, prominent).
  List<Marker> get _foto2ApMarkers {
    if (!_isFoto2ApMode || _foto2ApResult == null || !_foto2ApResult!.success) {
      return [];
    }
    final r = _foto2ApResult!;
    if (r.lat == null || r.lng == null) return [];

    return [
      Marker(
        point: LatLng(r.lat!, r.lng!),
        width: 80,
        height: 80,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // Pulsing AP marker
            Container(
              width: 48,
              height: 48,
              decoration: BoxDecoration(
                color: const Color(0xFF7C4DFF).withValues(alpha: 0.9),
                shape: BoxShape.circle,
                border: Border.all(
                  color: Colors.white,
                  width: 3,
                ),
                boxShadow: [
                  BoxShadow(
                    color: const Color(0xFF7C4DFF).withValues(alpha: 0.6),
                    blurRadius: 16,
                    spreadRadius: 4,
                  ),
                ],
              ),
              child: const Icon(
                Icons.wifi_find,
                color: Colors.white,
                size: 26,
              ),
            ),
            const SizedBox(height: 4),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
              decoration: BoxDecoration(
                color: Colors.black87,
                borderRadius: BorderRadius.circular(12),
              ),
              child: Text(
                r.apName ?? 'AP',
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 11,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),
          ],
        ),
      ),
    ];
  }

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

  /// Calculate AP marker size based on current map zoom level.
  /// Higher zoom (more zoomed in) = larger markers.
  double _getMarkerSize({bool isHeatmap = false}) {
    final zoom = _currentZoom;

    if (isHeatmap) {
      if (zoom >= 18) return 32;
      if (zoom >= 16) return 24;
      if (zoom >= 14) return 16;
      if (zoom >= 12) return 10;
      return 8; // zoom < 12: heatmap markers also shrink
    }
    // Normal mode
    if (zoom >= 18) return 14;
    if (zoom >= 16) return 8;
    if (zoom >= 14) return 5;
    if (zoom >= 12) return 3;
    return 0; // zoom < 12: hide normal blue dots
  }

  /// Font size for heatmap mode signal strength numbers.
  double _getHeatmapTextSize() {
    final zoom = _currentZoom;

    if (zoom >= 18) return 9;
    if (zoom >= 16) return 7;
    if (zoom >= 14) return 6;
    if (zoom >= 12) return 5;
    return 4;
  }

  /// Whether to show AP markers in heatmap mode.
  /// At very low zoom levels, only show the smooth grid, not individual points.
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
      // Heatmap mode: color-coded markers using continuous gradient
      for (final ap in _aps) {
        final key = ap.id ?? ap.name ?? '';
        final prediction = _heatmapCache[key];
        if (prediction == null) continue;
        final dbm = prediction['signal_db'] as num? ?? -70;
        final color = _signalDbToColor(dbm.toDouble());
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

  /// Check if the user is near the UAB campus.
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

      // If user is outside campus, center map on campus by default
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
      // Handle location error - default to campus center
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
      // v2: resolution 100 (100x100 grid)
      final cacheKey = 'heatmap_v2_${_currentDayApiName}_$_selectedHour';
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
          day: _currentDayApiName,
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
        day: _currentDayApiName,
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
    // Parse AP point data
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

    // Parse smooth grid data
    final smoothGridData = data['smooth_grid'] as Map<String, dynamic>?;
    final smoothPoints = smoothGridData?['points'] as List<dynamic>? ?? [];
    final parsedSmoothPoints = smoothPoints
        .map<Map<String, dynamic>>((p) => Map<String, dynamic>.from(p as Map))
        .toList();

    // Compute dynamic signal range mapping
    // Uses two ranges:
    //   - _signalMinDb / _signalMaxDb: actual min/max for legend display (true range)
    //   - _colorMapMinDb / _colorMapMaxDb: p2~p98 percentile for color mapping (avoid outliers)
    double legendMinDb = -85.0;
    double legendMaxDb = -45.0;
    double colorMinDb = -75.0;
    double colorMaxDb = -50.0;
    if (parsedSmoothPoints.isNotEmpty) {
      final signals = parsedSmoothPoints
          .map<double>((p) => (p['signal_db'] as num?)?.toDouble() ?? -70.0)
          .toList()
        ..sort();
      final n = signals.length;

      // Legend shows actual min/max
      legendMinDb = signals.first;
      legendMaxDb = signals.last;

      // Color mapping uses p2~p98 to avoid outlier skew
      colorMinDb = signals[(n * 0.02).round().clamp(0, n - 1)];
      colorMaxDb = signals[(n * 0.98).round().clamp(0, n - 1)];
      // Ensure at least 3dB span
      if (colorMaxDb - colorMinDb < 3.0) {
        final mid = (colorMinDb + colorMaxDb) / 2;
        colorMinDb = mid - 1.5;
        colorMaxDb = mid + 1.5;
      }
    }

    setState(() {
      _heatmapCache = cache;
      _smoothHeatmapPoints = parsedSmoothPoints;
      _signalMinDb = legendMinDb;
      _signalMaxDb = legendMaxDb;
      _colorMapMinDb = colorMinDb;
      _colorMapMaxDb = colorMaxDb;
      _isLoadingHeatmap = false;
    });

    debugPrint('Loaded ${cache.length} AP points + ${parsedSmoothPoints.length} grid points');
    debugPrint('Signal range: ${legendMinDb.toStringAsFixed(1)} to ${legendMaxDb.toStringAsFixed(1)} dBm (color: ${colorMinDb.toStringAsFixed(1)} to ${colorMaxDb.toStringAsFixed(1)})');
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
    String? apiError;
    try {
      // v3 API: send ap_name + current time features for status prediction
      final now = DateTime.now();
      final weekday = now.weekday; // 1=Mon, 7=Sun
      final apName = ap.name?.trim() ?? '';
      if (apName.isEmpty) {
        apiError = 'AP name is empty';
        predictedStatus = 'error';
      } else {
        final result = await _apiService.predictAPStatus({
          'ap_name': apName,
          'hour': now.hour.toDouble(),
          'day_of_week': (weekday - 1).toDouble(), // 0=Mon, 6=Sun
          'is_weekend': (weekday >= 6) ? 1.0 : 0.0,
          'month': now.month.toDouble(),
          'day_of_month': now.day.toDouble(),
        });
        predictedStatus = result['prediction'] ?? result['status'] ?? 'unknown';
      }
    } catch (e) {
      predictedStatus = 'error';
      apiError = e.toString();
    }

    final color = predictedStatus == 'Up'
        ? Colors.green
        : predictedStatus == 'Down'
            ? Colors.red
            : Colors.orange;

    if (!mounted) return;

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      builder: (context) => SingleChildScrollView(
        child: Container(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                ap.name ?? 'AP',
                style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 6),
              Text('${ap.building}, Floor ${ap.height ?? 0}'),
              const SizedBox(height: 6),
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
                const SizedBox(height: 6),
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
              const SizedBox(height: 12),
              Wrap(
                alignment: WrapAlignment.spaceEvenly,
                runSpacing: 4,
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
      ),
    );
  }

  /// Build a compact action button for the AP bottom sheet.
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
    // Close bottom sheet first (use rootNavigator to only close the sheet, not pop the page)
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
  /// Routes directly from the campus gate to the target AP without checking user location.
  Future<void> _navigateFromGate(APInfo ap) async {
    // Close bottom sheet first
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
    // Close bottom sheet first
    Navigator.of(context, rootNavigator: true).pop();
    // Use rootNavigator to open dialog, avoiding context invalidation issues
    if (!mounted) return;
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
  static const double _apCoverageRadiusM = 40.0;

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

  /// Map a signal_db value to a color using the dynamic data range.
  /// Uses [_colorMapMinDb] and [_colorMapMaxDb] (p2~p98 percentile) for
  /// color mapping to avoid outliers skewing the distribution.
  /// The legend shows [_signalMinDb] / [_signalMaxDb] (actual min/max).
  /// Uses 4 distinct, high-contrast colors for maximum visual separation:
  ///   Red (#E53935) → Orange (#FB8C00) → Lime (#C0CA33) → Teal (#00897B)
  /// Each color is a flat (non-interpolated) band so adjacent grid cells
  /// with slightly different signal strengths are clearly distinguishable.
  Color _signalDbToColor(double signalDb) {
    final minDb = _colorMapMinDb;
    final maxDb = _colorMapMaxDb;
    final clamped = signalDb.clamp(minDb, maxDb);
    // Normalize: minDb → 0.0 (worst), maxDb → 1.0 (best)
    final t = (clamped - minDb) / (maxDb - minDb);

    // 4 discrete bands with high-contrast colors
    if (t < 0.25) {
      return const Color(0xFFE53935); // Red (worst)
    } else if (t < 0.50) {
      return const Color(0xFFFB8C00); // Orange
    } else if (t < 0.75) {
      return const Color(0xFFC0CA33); // Lime
    } else {
      return const Color(0xFF00897B); // Teal (best)
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
        color: color.withValues(alpha: 0.18),
        borderColor: color.withValues(alpha: 0.06),
        borderStrokeWidth: 0.5,
      );
    }).toList();
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
                  '${_dayNames[_currentDayIndex]} $_selectedHour:00',
                  style: const TextStyle(fontSize: 11, color: Colors.grey),
                ),
                const Divider(height: 8),
                // Discrete color bands legend (matches _signalDbToColor)
                Container(
                  height: 16,
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(4),
                    gradient: const LinearGradient(
                      colors: [
                        Color(0xFFE53935), // Red (worst)
                        Color(0xFFE53935),
                        Color(0xFFFB8C00), // Orange
                        Color(0xFFFB8C00),
                        Color(0xFFC0CA33), // Lime
                        Color(0xFFC0CA33),
                        Color(0xFF00897B), // Teal (best)
                        Color(0xFF00897B),
                      ],
                      stops: [0.0, 0.25, 0.25, 0.50, 0.50, 0.75, 0.75, 1.0],
                    ),
                  ),
                ),
                const SizedBox(height: 4),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(
                      '${_signalMinDb.toStringAsFixed(0)} dBm',
                      style: const TextStyle(fontSize: 10, color: Colors.grey),
                    ),
                    Text(
                      '${_signalMaxDb.toStringAsFixed(0)} dBm',
                      style: const TextStyle(fontSize: 10, color: Colors.grey),
                    ),
                  ],
                ),
                const SizedBox(height: 2),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: const [
                    Text('Worse', style: TextStyle(fontSize: 9, color: Colors.grey)),
                    Text('Better', style: TextStyle(fontSize: 9, color: Colors.grey)),
                  ],
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

  /// Build the Foto2AP result info card (shown at bottom when in Foto2AP mode).
  Widget _buildFoto2ApInfoCard() {
    if (!_isFoto2ApMode || _foto2ApResult == null) return const SizedBox.shrink();

    final r = _foto2ApResult!;

    if (_isFoto2ApLoading) {
      return Positioned(
        bottom: 20,
        left: 20,
        right: 20,
        child: Card(
          elevation: 6,
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const SizedBox(
                  width: 20,
                  height: 20,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
                const SizedBox(width: 12),
                Text(
                  'Recognising AP from photo...',
                  style: TextStyle(
                    fontSize: 14,
                    color: Colors.grey[600],
                  ),
                ),
              ],
            ),
          ),
        ),
      );
    }

    if (!r.success) {
      return Positioned(
        bottom: 20,
        left: 20,
        right: 20,
        child: Card(
          elevation: 6,
          color: Colors.orange.shade50,
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                const Icon(Icons.error_outline, color: Colors.orange),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    r.errorMessage ?? 'Could not recognise AP',
                    style: const TextStyle(fontSize: 13),
                  ),
                ),
                TextButton(
                  onPressed: _clearFoto2Ap,
                  child: const Text('Dismiss'),
                ),
              ],
            ),
          ),
        ),
      );
    }

    // Success card
    return Positioned(
      bottom: 20,
      left: 20,
      right: 20,
      child: Card(
        elevation: 8,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: BorderSide(
            color: const Color(0xFF7C4DFF).withValues(alpha: 0.3),
            width: 1.5,
          ),
        ),
        child: Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(16),
            gradient: LinearGradient(
              colors: [
                const Color(0xFF7C4DFF).withValues(alpha: 0.05),
                Colors.white,
              ],
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
            ),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Header
              Row(
                children: [
                  Container(
                    padding: const EdgeInsets.all(8),
                    decoration: BoxDecoration(
                      color: const Color(0xFF7C4DFF).withValues(alpha: 0.1),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: const Icon(
                      Icons.wifi_find,
                      color: Color(0xFF7C4DFF),
                      size: 24,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          r.apName ?? 'Unknown AP',
                          style: const TextStyle(
                            fontSize: 18,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                        Text(
                          r.building ?? 'Unknown building',
                          style: TextStyle(
                            fontSize: 13,
                            color: Colors.grey[600],
                          ),
                        ),
                      ],
                    ),
                  ),
                  // Close button
                  IconButton(
                    icon: const Icon(Icons.close),
                    onPressed: _clearFoto2Ap,
                    tooltip: 'Clear & restore heatmap',
                  ),
                ],
              ),
              const SizedBox(height: 12),
              // Details row
              Row(
                children: [
                  _buildInfoChip(Icons.location_on, 'Floor ${r.floor ?? '?'}'),
                  const SizedBox(width: 8),
                  if (r.espacio != null && r.espacio!.isNotEmpty)
                    _buildInfoChip(Icons.room, r.espacio!),
                  const Spacer(),
                  // Navigate button
                  TextButton.icon(
                    onPressed: () {
                      // Find the APInfo for this AP and navigate
                      final apInfo = _aps.where((a) =>
                        a.name?.toUpperCase() == r.apName?.toUpperCase()
                      ).firstOrNull;
                      if (apInfo != null) {
                        _showAPOptions(apInfo);
                      }
                    },
                    icon: const Icon(Icons.directions, size: 18),
                    label: const Text('Navigate'),
                    style: TextButton.styleFrom(
                      foregroundColor: const Color(0xFF7C4DFF),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildInfoChip(IconData icon, String label) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: Colors.grey.shade100,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: Colors.grey[600]),
          const SizedBox(width: 4),
          Text(
            label,
            style: TextStyle(fontSize: 12, color: Colors.grey[700]),
          ),
        ],
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
            ),
            children: [
              TileLayer(
                urlTemplate: 'https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png',
                userAgentPackageName: 'com.uab.wifers',
              ),
              // Smooth heatmap grid overlay (rendered below markers)
              // Hidden in Foto2AP mode
              if (!_isFoto2ApMode)
                PolygonLayer(
                  polygons: _smoothHeatmapPolygons,
                ),
              MarkerLayer(
                markers: [
                  // Normal heatmap/AP markers (hidden in Foto2AP mode)
                  if (!_isFoto2ApMode) ..._markers,
                  // Foto2AP result marker
                  ..._foto2ApMarkers,
                ],
              ),
            ],
          ),
          // Heatmap legend overlay (hidden in Foto2AP mode)
          if (!_isFoto2ApMode) _buildHeatmapLegend(),
          // Foto2AP info card
          _buildFoto2ApInfoCard(),
        ],
      ),
      floatingActionButton: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          // Time picker FAB (hidden in Foto2AP mode)
          if (!_isFoto2ApMode)
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
          if (!_isFoto2ApMode) const SizedBox(height: 12),
          // Camera FAB
          FloatingActionButton(
            heroTag: 'camera',
            mini: true,
            backgroundColor: _isFoto2ApMode
                ? const Color(0xFF7C4DFF)
                : Colors.blue,
            onPressed: _isFoto2ApLoading
                ? null
                : _showFoto2ApSourcePicker,
            child: _isFoto2ApLoading
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: Colors.white,
                    ),
                  )
                : const Icon(
                    Icons.camera_alt,
                    color: Colors.white,
                    size: 20,
                  ),
          ),
        ],
      ),
    );
  }
}