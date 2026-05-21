import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:latlong2/latlong.dart';
import 'package:wifers_app/services/api_service.dart';
import 'package:wifers_app/services/ap_data_service.dart';
import 'package:wifers_app/services/location_service.dart';
import 'package:wifers_app/services/storage_service.dart';
import 'package:wifers_app/services/cache_service.dart';
import 'package:wifers_app/pages/route_page.dart';

class RecommendPage extends StatefulWidget {
  const RecommendPage({super.key});

  @override
  State<RecommendPage> createState() => RecommendPageState();

}

class RecommendedAp {
  final String id;
  final String name;
  final String building;
  final int? floor;
  final double lat;
  final double lng;
  final double distance;
  final String prediction;
  final double confidence;
  final double score;
  final double signalDb;

  RecommendedAp({
    required this.id,
    required this.name,
    required this.building,
    this.floor,
    required this.lat,
    required this.lng,
    required this.distance,
    required this.prediction,
    required this.confidence,
    required this.score,
    this.signalDb = -70,
  });
}

class RecommendPageState extends State<RecommendPage> {
  final ApiService _apiService = ApiService();
  final Distance _distanceCalculator = const Distance();
  bool _isLoading = false;
  String _statusMessage = 'Waiting for recommendation';
  String? _locationLabel;
  bool _preferStableAps = true;
  int _recommendRadiusMeters = 500;
  String _recommendMode = 'balanced';
  List<RecommendedAp> _recommendations = [];
  List<String> _buildings = [];
  String _selectedBuilding = '';

  // Cache for signal strength predictions per AP
  final Map<String, Map<String, dynamic>> _signalCache = {};

  // Mode display info
  static const Map<String, _ModeDisplay> _modeDisplay = {
    'distance': _ModeDisplay('Distance Priority', Icons.near_me, Colors.green),
    'signal': _ModeDisplay('Signal Priority', Icons.signal_wifi_4_bar, Colors.orange),
    'balanced': _ModeDisplay('Balanced', Icons.balance, Colors.blue),
  };

  @override
  void initState() {
    super.initState();
    _loadSettings();
    _loadBuildings();
    _updateLocationLabel();
  }

  /// Public method to reload settings from storage (called when switching tabs)
  void reloadSettings() {
    _loadSettings();
  }

  Future<void> _loadSettings() async {
    final settings = await StorageService.loadSettings();
    if (!mounted) return;
    setState(() {
      _preferStableAps = settings['preferStableAps'] ?? true;
      _recommendRadiusMeters = settings['recommendRadiusMeters'] ?? 500;
      _recommendMode = settings['recommendMode'] as String? ?? 'balanced';
      _selectedBuilding = settings['selectedBuilding'] as String? ?? '';
    });
  }

  /// Save only the mode to storage without overwriting other settings
  Future<void> _saveModeToStorage(String mode) async {
    final settings = await StorageService.loadSettings();
    settings['recommendMode'] = mode;
    await StorageService.saveSettings(settings);
  }

  /// Save the selected building to storage
  Future<void> _saveBuildingToStorage(String building) async {
    final settings = await StorageService.loadSettings();
    settings['selectedBuilding'] = building;
    await StorageService.saveSettings(settings);
  }

  Future<void> _loadBuildings() async {

    try {
      final buildings = await ApDataService.loadBuildings();
      setState(() {
        _buildings = buildings;
      });
    } catch (e) {
      debugPrint('Failed to load buildings: $e');
    }
  }

  String get _modeLabel {
    final display = _modeDisplay[_recommendMode];
    return display?.label ?? 'Balanced';
  }

  IconData get _modeIconData {
    final display = _modeDisplay[_recommendMode];
    return display?.icon ?? Icons.balance;
  }

  Color get _modeColor {
    final display = _modeDisplay[_recommendMode];
    return display?.color ?? Colors.blue;
  }

  Future<void> _updateLocationLabel() async {
    try {
      final position = await LocationService.getCurrentPosition();
      setState(() {
        _locationLabel = '${position.latitude.toStringAsFixed(5)}, ${position.longitude.toStringAsFixed(5)}';
      });
    } catch (e) {
      setState(() {
        _locationLabel = 'Location unavailable';
      });
    }
  }

  Future<List<Map<String, dynamic>>> _loadApsFromAsset() async {
    return ApDataService.loadAllApsAsMaps();
  }

  Map<String, dynamic> _buildPredictionFeatures(Map<String, dynamic> ap, LatLng userLocation) {
    return {
      'client_count': 10,
      'cpu_utilization': 50.0,
      'mem_free': 1000.0,
      'mem_total': 2000.0,
      'last_modified': 1640995200.0,
      'hour': DateTime.now().hour.toDouble(),
      'mem_usage': 50.0,
      'overloaded': _preferStableAps ? 0 : 1,
    };
  }

  /// Fetch signal strength prediction for a single AP from the heatmap endpoint.
  /// Falls back to the batch prediction if heatmap data is unavailable.
  Future<Map<String, dynamic>> _fetchSignalForAp(Map<String, dynamic> ap) async {
    final apName = ap['name'] as String? ?? '';
    final apId = ap['id'] as String? ?? '';
    final key = apName.isNotEmpty ? apName : apId;
    if (key.isEmpty) return {'signal_db': -70, 'signal_quality': 'Fair'};

    // Check cache first
    if (_signalCache.containsKey(key)) {
      return _signalCache[key]!;
    }

    try {
      final heatmap = await _apiService.getSignalHeatmap();
      final apPoints = heatmap['ap_points'] as Map<String, dynamic>?;
      final points = apPoints?['points'] as List<dynamic>? ?? [];
      for (final point in points) {
        final map = point as Map<String, dynamic>;
        final name = map['ap_name'] as String? ?? '';
        if (name == key || name == apName) {
          final result = {
            'signal_db': map['signal_db'] ?? -70,
            'signal_quality': map['signal_quality'] ?? 'Fair',
            'bars': map['bars'] ?? 1,
          };
          _signalCache[key] = result;
          return result;
        }
      }
    } catch (e) {
      debugPrint('Signal fetch failed for $key: $e');
    }

    // Fallback: return default
    return {'signal_db': -70, 'signal_quality': 'Fair'};
  }

  /// Score an AP based on the selected recommendation mode.
  /// Returns a score in [0, 1] range where higher = better.
  double _scoreAp({
    required double distance,
    required double upProbability,
    required double signalDb,
  }) {
    final distanceScore = (1.0 - (distance / _recommendRadiusMeters)).clamp(0.0, 1.0);
    final signalScore = _dbmToNormalizedScore(signalDb);
    final statusScore = upProbability / 100.0;

    switch (_recommendMode) {
      case 'distance':
        // Mostly distance (80%), slight weight on signal to break ties
        return distanceScore * 0.8 + signalScore * 0.15 + statusScore * 0.05;

      case 'signal':
        // Mostly signal strength (70%), some distance consideration
        return signalScore * 0.7 + statusScore * 0.2 + distanceScore * 0.1;

      case 'balanced':
      default:
        // Even weighted mix
        final stabilityWeight = _preferStableAps ? 0.4 : 0.25;
        return statusScore * stabilityWeight +
            distanceScore * (0.5 - stabilityWeight * 0.3) +
            signalScore * (0.5 - stabilityWeight * 0.2);
    }
  }

  /// Convert dBm to a normalized score [0, 1].
  /// -97 dBm (weakest) → 0.0, -22 dBm (strongest) → 1.0
  double _dbmToNormalizedScore(double dbm) {
    return ((dbm.clamp(-97.0, -22.0) + 97.0) / 75.0).clamp(0.0, 1.0);
  }

  Future<void> _getRecommendation() async {
    setState(() {
      _isLoading = true;
      _statusMessage = 'Calculating recommendations...';
      _recommendations = [];
    });

    try {
      LatLng userLocation;
      bool usingGate = false;

      try {
        final position = await LocationService.getCurrentPosition();
        userLocation = LatLng(position.latitude, position.longitude);

        // If outside campus, offer to use campus gate as reference
        if (!LocationService.isNearCampus(userLocation)) {
          if (!mounted) return;
          final useGate = await showDialog<bool>(
            context: context,
            builder: (context) => AlertDialog(
              title: const Text('Outside Campus Area'),
              content: const Text(
                'You are currently outside the UAB campus area. '
                'Recommendations will be based on the campus main entrance.\n\n'
                'Would you like to continue?',
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(context, false),
                  child: const Text('Cancel'),
                ),
                TextButton(
                  onPressed: () => Navigator.pop(context, true),
                  child: const Text('Use Campus Gate'),
                ),
              ],
            ),
          );
          if (useGate != true) {
            setState(() {
              _statusMessage = 'Recommendation cancelled.';
              _isLoading = false;
            });
            return;
          }
          userLocation = LocationService.campusGate;
          usingGate = true;
        }
      } catch (e) {
        // Location unavailable, fallback to campus gate
        if (!mounted) return;
        final useGate = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: const Text('Location Unavailable'),
            content: const Text(
              'Could not determine your current location.\n\n'
              'Would you like to use the campus main entrance as the starting point for recommendations?',
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('Cancel'),
              ),
              TextButton(
                onPressed: () => Navigator.pop(context, true),
                child: const Text('Use Campus Gate'),
              ),
            ],
          ),
        );
        if (useGate != true) {
          setState(() {
            _statusMessage = 'Recommendation cancelled.';
            _isLoading = false;
          });
          return;
        }
        userLocation = LocationService.campusGate;
        usingGate = true;
      }

      // Build a cache key based on location, building filter, and current settings
      final cacheLat = userLocation.latitude.toStringAsFixed(4);
      final cacheLng = userLocation.longitude.toStringAsFixed(4);
      final buildingKey = _selectedBuilding.isNotEmpty ? _selectedBuilding.replaceAll(' ', '_') : 'all';
      final cacheKey = 'recommend_${cacheLat}_${cacheLng}_${buildingKey}_$_recommendRadiusMeters$_preferStableAps$_recommendMode${usingGate ? '_gate' : ''}';

      // Try to load from cache first
      final settings = await StorageService.loadSettings();
      final cacheDuration = Duration(
        minutes: settings['cacheDurationMinutes'] as int? ?? 60,
      );

      final cachedResult = await CacheService.get<String>(cacheKey, ttl: cacheDuration);
      if (cachedResult != null) {
        final decoded = jsonDecode(cachedResult) as List<dynamic>;
        final cachedAps = decoded.map((item) {
          final map = item as Map<String, dynamic>;
          return RecommendedAp(
            id: map['id'] as String,
            name: map['name'] as String,
            building: map['building'] as String,
            floor: map['floor'] as int?,
            lat: (map['lat'] as num).toDouble(),
            lng: (map['lng'] as num).toDouble(),
            distance: (map['distance'] as num).toDouble(),
            prediction: map['prediction'] as String,
            confidence: (map['confidence'] as num).toDouble(),
            score: (map['score'] as num).toDouble(),
            signalDb: (map['signal_db'] as num?)?.toDouble() ?? -70,
          );
        }).toList();

        setState(() {
          _recommendations = cachedAps;
          _statusMessage = 'Top ${cachedAps.length} recommendations ($_modeLabel).';
        });
        return;
      }

      final allAps = await _loadApsFromAsset();
      final nearbyAps = allAps.map((ap) {
        final distance = _distanceCalculator.as(
          LengthUnit.Meter,
          userLocation,
          LatLng(ap['lat'] as double, ap['lng'] as double),
        );
        return {...ap, 'distance': distance};
      }).where((ap) {
        final withinRadius = (ap['distance'] as double) <= _recommendRadiusMeters;
        final matchesBuilding = _selectedBuilding.isEmpty || ap['building'] == _selectedBuilding;
        return withinRadius && matchesBuilding;
      }).toList();

      if (nearbyAps.isEmpty) {
        setState(() {
          _statusMessage = 'No APs found within $_recommendRadiusMeters meters.';
          _isLoading = false;
        });
        return;
      }

      // Sort by distance first, take top 100 for prediction
      nearbyAps.sort((a, b) => (a['distance'] as double).compareTo(b['distance'] as double));
      final selectedAps = nearbyAps.take(100).toList();

      // Batch predict AP status
      final featureBatch = selectedAps.map((ap) => _buildPredictionFeatures(ap, userLocation)).toList();
      final predictionResponse = await _apiService.predictAPStatusBatch(featureBatch);
      final predictions = predictionResponse['predictions'] as List<dynamic>;

      // Fetch signal strengths for all selected APs
      final signalResults = <Map<String, dynamic>>[];
      for (final ap in selectedAps) {
        signalResults.add(await _fetchSignalForAp(ap));
      }

      final scoredAps = <RecommendedAp>[];
      for (var i = 0; i < selectedAps.length; i++) {
        final ap = selectedAps[i];
        final predictionInfo = predictions[i] as Map<String, dynamic>;
        final prediction = predictionInfo['prediction'] as String? ?? 'Unknown';
        final confidence = (predictionInfo['confidence'] as num?)?.toDouble() ?? 0.0;
        final upProbability = (predictionInfo['up_probability'] as num?)?.toDouble() ?? 0.0;
        final distance = ap['distance'] as double;

        // Get signal data (either from heatmap or fallback)
        final signalData = i < signalResults.length ? signalResults[i] : <String, dynamic>{};
        final signalDb = (signalData['signal_db'] as num?)?.toDouble() ?? -70;

        // Score based on selected mode
        final score = _scoreAp(
          distance: distance,
          upProbability: upProbability,
          signalDb: signalDb,
        );

        scoredAps.add(RecommendedAp(
          id: ap['id'] as String,
          name: ap['name'] as String,
          building: ap['building'] as String,
          floor: ap['floor'] as int?,
          lat: ap['lat'] as double,
          lng: ap['lng'] as double,
          distance: distance,
          prediction: prediction,
          confidence: confidence,
          score: score,
          signalDb: signalDb,
        ));
      }

      scoredAps.sort((a, b) => b.score.compareTo(a.score));
      final topAps = scoredAps.take(5).toList();

      // Save to cache
      final cacheData = topAps.map((ap) => {
        'id': ap.id,
        'name': ap.name,
        'building': ap.building,
        'floor': ap.floor,
        'lat': ap.lat,
        'lng': ap.lng,
        'distance': ap.distance,
        'prediction': ap.prediction,
        'confidence': ap.confidence,
        'score': ap.score,
        'signal_db': ap.signalDb,
      }).toList();
      await CacheService.set(cacheKey, jsonEncode(cacheData));

      setState(() {
        _recommendations = topAps;
        _statusMessage = 'Top ${topAps.length} recommendations ($_modeLabel).';
      });
    } catch (e) {
      setState(() {
        _statusMessage = 'Recommendation failed: $e';
      });
    } finally {
      setState(() {
        _isLoading = false;
      });
    }
  }

  Future<void> _navigateToAp(RecommendedAp ap) async {
    try {
      final position = await LocationService.getCurrentPosition();
      final userLocation = LatLng(position.latitude, position.longitude);

      // Check if user is near campus
      if (!LocationService.isNearCampus(userLocation)) {
        if (!mounted) return;
        final startFromGate = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: const Text('Outside Campus Area'),
            content: const Text(
              'You are currently outside the UAB campus area. '
              'Navigation is only available from within the campus.\n\n'
              'Would you like to start navigation from the campus main entrance instead?',
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('Cancel'),
              ),
              TextButton(
                onPressed: () => Navigator.pop(context, true),
                child: const Text('Start from Gate'),
              ),
            ],
          ),
        );
        if (startFromGate != true) return;
        // Navigate from campus gate
        final gatePath = await _apiService.fetchRoute(
          LocationService.campusGateLng,
          LocationService.campusGateLat,
          ap.lng,
          ap.lat,
        );
        if (gatePath.isNotEmpty && mounted) {
          Navigator.push(
            context,
            MaterialPageRoute(
              builder: (context) => RoutePage(
                path: gatePath,
                title: 'Navigate to ${ap.name} (from Gate)',
              ),
            ),
          );
        }
        return;
      }

      final path = await _apiService.fetchRoute(
        position.longitude,
        position.latitude,
        ap.lng,
        ap.lat,
      );
      if (path.isNotEmpty && mounted) {
        Navigator.push(
          context,
          MaterialPageRoute(
            builder: (context) => RoutePage(
              path: path,
              title: 'Navigate to ${ap.name}',
            ),
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

  /// Convert dBm to color for signal indicator
  Color _dbmToColor(double dbm) {
    final clamped = dbm.clamp(-97.0, -22.0);
    final t = (clamped + 97.0) / 75.0;
    if (t > 0.66) return Colors.green;
    if (t > 0.33) return Colors.orange;
    return Colors.red;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('AP Recommendation'),
        backgroundColor: Theme.of(context).colorScheme.inversePrimary,
      ),
      body: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Location info
            Row(
              children: [
                Icon(Icons.my_location, size: 16, color: Colors.grey[600]),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    _locationLabel ?? 'Locating...',
                    style: TextStyle(fontSize: 14, color: Colors.grey[600]),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),

            // Mode selector
            SizedBox(
              width: double.infinity,
              child: SegmentedButton<String>(
                segments: _modeDisplay.entries.map((entry) {
                  return ButtonSegment<String>(
                    value: entry.key,
                    label: Text(entry.value.label, style: const TextStyle(fontSize: 11)),
                    icon: Icon(entry.value.icon, size: 16),
                  );
                }).toList(),
                selected: {_recommendMode},
                onSelectionChanged: (Set<String> selection) {
                  final newMode = selection.first;
                  setState(() {
                    _recommendMode = newMode;
                  });
                  // Persist to storage (merge with existing settings)
                  _saveModeToStorage(newMode);
                },

                showSelectedIcon: false,
                style: ButtonStyle(
                  visualDensity: VisualDensity.compact,
                  tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                ),
              ),
            ),
            const SizedBox(height: 12),

            // Building selector
            Card(
              margin: EdgeInsets.zero,
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                child: Row(
                  children: [
                    Icon(Icons.business, size: 18, color: Colors.grey[600]),
                    const SizedBox(width: 8),
                    Expanded(
                      child: DropdownButtonHideUnderline(
                        child: DropdownButton<String>(
                          value: _buildings.contains(_selectedBuilding) ? _selectedBuilding : '',
                          isExpanded: true,
                          hint: const Text('All Buildings', style: TextStyle(fontSize: 14)),
                          items: [
                            const DropdownMenuItem<String>(
                              value: '',
                              child: Text('All Buildings', style: TextStyle(fontSize: 14)),
                            ),
                            ..._buildings.map((building) => DropdownMenuItem<String>(
                              value: building,
                              child: Text(building, style: const TextStyle(fontSize: 14)),
                            )),
                          ],
                          onChanged: (String? value) {
                            if (value != null) {
                              setState(() {
                                _selectedBuilding = value;
                              });
                              _saveBuildingToStorage(value);
                            }
                          },
                        ),
                      ),
                    ),
                    if (_selectedBuilding.isNotEmpty)
                      GestureDetector(
                        onTap: () {
                          setState(() {
                            _selectedBuilding = '';
                          });
                          _saveBuildingToStorage('');
                        },
                        child: Icon(Icons.close, size: 16, color: Colors.grey[400]),
                      ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 12),

            // Status message
            Text(
              _statusMessage,
              style: const TextStyle(fontSize: 14, color: Colors.black54),
            ),
            const SizedBox(height: 16),

            // Recommend button
            SizedBox(
              width: double.infinity,
              child: ElevatedButton.icon(
                onPressed: _isLoading ? null : _getRecommendation,
                icon: _isLoading
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : Icon(_modeIconData),
                label: Text(_isLoading ? 'Calculating...' : 'Find Best APs ($_modeLabel)'),
                style: ElevatedButton.styleFrom(
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  backgroundColor: _modeColor,
                  foregroundColor: Colors.white,
                ),
              ),
            ),
            const SizedBox(height: 16),

            // Recommendations list
            Expanded(
              child: _recommendations.isEmpty
                  ? Center(
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(_modeIconData, size: 64, color: Colors.grey[300]),
                          const SizedBox(height: 16),
                          Text(
                            'No recommendations yet.\nTap the button above.',
                            textAlign: TextAlign.center,
                            style: TextStyle(color: Colors.grey[500]),
                          ),
                        ],
                      ),
                    )
                  : ListView.builder(
                      itemCount: _recommendations.length,
                      itemBuilder: (context, index) {
                        final ap = _recommendations[index];
                        final signalColor = _dbmToColor(ap.signalDb);
                        return Card(
                          margin: const EdgeInsets.symmetric(vertical: 6),
                          child: ListTile(
                            leading: CircleAvatar(
                              backgroundColor: _modeColor.withValues(alpha: 0.15),
                              child: Text(
                                '${index + 1}',
                                style: TextStyle(
                                  fontWeight: FontWeight.bold,
                                  color: _modeColor,
                                ),
                              ),
                            ),
                            title: Text(
                              ap.name,
                              style: const TextStyle(fontWeight: FontWeight.w600),
                            ),
                            subtitle: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text('${ap.building} • ${ap.floor != null ? 'Floor ${ap.floor}' : 'Floor unknown'}'),
                                const SizedBox(height: 4),
                                Row(
                                  children: [
                                    // Distance
                                    Icon(Icons.near_me, size: 12, color: Colors.grey[600]),
                                    const SizedBox(width: 2),
                                    Text(
                                      '${ap.distance.toStringAsFixed(0)} m',
                                      style: TextStyle(fontSize: 11, color: Colors.grey[600]),
                                    ),
                                    const SizedBox(width: 12),
                                    // Signal
                                    Icon(Icons.signal_wifi_4_bar, size: 12, color: signalColor),
                                    const SizedBox(width: 2),
                                    Text(
                                      '${ap.signalDb.toStringAsFixed(1)} dBm',
                                      style: TextStyle(fontSize: 11, color: signalColor),
                                    ),
                                  ],
                                ),
                              ],
                            ),
                            trailing: Column(
                              mainAxisAlignment: MainAxisAlignment.center,
                              crossAxisAlignment: CrossAxisAlignment.end,
                              children: [
                                Row(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    Icon(
                                      Icons.wifi,
                                      size: 14,
                                      color: ap.prediction == 'Up' ? Colors.green : Colors.red,
                                    ),
                                    const SizedBox(width: 4),
                                    Text(
                                      '${(ap.score * 100).toStringAsFixed(0)}%',
                                      style: TextStyle(
                                        fontWeight: FontWeight.bold,
                                        color: ap.prediction == 'Up' ? Colors.green : Colors.red,
                                      ),
                                    ),
                                  ],
                                ),
                                const SizedBox(height: 2),
                                Text(
                                  '${ap.confidence.toStringAsFixed(2)} conf',
                                  style: TextStyle(fontSize: 10, color: Colors.grey[500]),
                                ),
                              ],
                            ),
                            onTap: () => _navigateToAp(ap),
                          ),
                        );
                      },
                    ),
            ),
          ],
        ),
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