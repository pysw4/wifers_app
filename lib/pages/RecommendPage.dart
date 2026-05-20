import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:latlong2/latlong.dart';
import 'package:wifers_app/services/api_service.dart';
import 'package:wifers_app/services/location_service.dart';
import 'package:wifers_app/services/storage_service.dart';
import 'package:wifers_app/pages/RoutePage.dart';

class RecommendPage extends StatefulWidget {
  const RecommendPage({super.key});

  @override
  State<RecommendPage> createState() => _RecommendPageState();
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
  });
}

class _RecommendPageState extends State<RecommendPage> {
  final ApiService _apiService = ApiService();
  final Distance _distanceCalculator = const Distance();
  bool _isLoading = false;
  String _statusMessage = 'Waiting for recommendation';
  String? _locationLabel;
  bool _preferStableAps = true;
  int _recommendRadiusMeters = 500;
  List<RecommendedAp> _recommendations = [];

  @override
  void initState() {
    super.initState();
    _loadSettings();
    _updateLocationLabel();
  }

  Future<void> _loadSettings() async {
    final settings = await StorageService.loadSettings();
    setState(() {
      _preferStableAps = settings['preferStableAps'] ?? true;
      _recommendRadiusMeters = settings['recommendRadiusMeters'] ?? 500;
    });
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
    final geojson = await rootBundle.loadString('geolocation_package/data/aps_geolocalizados_wgs84.geojson');
    final Map<String, dynamic> data = json.decode(geojson) as Map<String, dynamic>;
    final features = data['features'] as List<dynamic>;
    return features.map<Map<String, dynamic>>((feature) {
      final props = Map<String, dynamic>.from(feature['properties'] as Map);
      final coords = feature['geometry']['coordinates'] as List<dynamic>;
      return {
        'id': props['USER_NOM_A']?.toString() ?? 'unknown',
        'name': props['USER_NOM_A']?.toString() ?? 'AP',
        'building': props['USER_EDIFI']?.toString() ?? props['Nom_Edific']?.toString() ?? 'Unknown',
        'floor': props['Num_Planta'] is num ? (props['Num_Planta'] as num).toInt() : null,
        'lat': (coords[1] as num).toDouble(),
        'lng': (coords[0] as num).toDouble(),
      };
    }).toList();
  }

  Map<String, dynamic> _buildPredictionFeatures(Map<String, dynamic> ap, LatLng userLocation) {
    final floor = ap['floor'] as int? ?? 0;
    final distance = _distanceCalculator.as(
      LengthUnit.Meter,
      userLocation,
      LatLng(ap['lat'] as double, ap['lng'] as double),
    );
    final buildingHash = ap['building']?.toString().hashCode.abs() ?? 0;
    final clientCount = 10 + floor * 4 + (buildingHash % 15);
    final cpuUtilization = 35.0 + floor * 3 + (buildingHash % 25) * 0.5;
    final memFree = 1500.0 - floor * 20.0;
    final memTotal = 2500.0;
    final memUsage = 45.0 + (buildingHash % 30) * 0.7;
    final lastModified = DateTime.now().toUtc().millisecondsSinceEpoch ~/ 1000 - (distance ~/ 20);
    final overloaded = _preferStableAps ? 0 : 1;
    return {
      'client_count': clientCount,
      'cpu_utilization': cpuUtilization.clamp(0.0, 100.0),
      'mem_free': memFree.clamp(100.0, 4000.0),
      'mem_total': memTotal,
      'last_modified': lastModified.toDouble(),
      'hour': DateTime.now().hour.toDouble(),
      'mem_usage': memUsage.clamp(0.0, 100.0),
      'overloaded': overloaded,
    };
  }

  Future<void> _getRecommendation() async {
    setState(() {
      _isLoading = true;
      _statusMessage = 'Calculating recommendations...';
      _recommendations = [];
    });

    try {
      final position = await LocationService.getCurrentPosition();
      final userLocation = LatLng(position.latitude, position.longitude);
      final allAps = await _loadApsFromAsset();
      final nearbyAps = allAps.map((ap) {
        final distance = _distanceCalculator.as(
          LengthUnit.Meter,
          userLocation,
          LatLng(ap['lat'] as double, ap['lng'] as double),
        );
        return {...ap, 'distance': distance};
      }).where((ap) => (ap['distance'] as double) <= _recommendRadiusMeters).toList();

      if (nearbyAps.isEmpty) {
        setState(() {
          _statusMessage = 'No APs found within $_recommendRadiusMeters meters.';
        });
        return;
      }

      nearbyAps.sort((a, b) => (a['distance'] as double).compareTo(b['distance'] as double));
      final selectedAps = nearbyAps.take(100).toList();
      final featureBatch = selectedAps.map((ap) => _buildPredictionFeatures(ap, userLocation)).toList();
      final predictionResponse = await _apiService.predictAPStatusBatch(featureBatch);
      final predictions = predictionResponse['predictions'] as List<dynamic>;

      final scoredAps = <RecommendedAp>[];
      for (var i = 0; i < selectedAps.length; i++) {
        final ap = selectedAps[i];
        final predictionInfo = predictions[i] as Map<String, dynamic>;
        final prediction = predictionInfo['prediction'] as String? ?? 'Unknown';
        final confidence = (predictionInfo['confidence'] as num?)?.toDouble() ?? 0.0;
        // up_probability is the model's confidence that AP is "Up" (0-100%)
        final upProbability = (predictionInfo['up_probability'] as num?)?.toDouble() ?? 0.0;
        final distance = ap['distance'] as double;
        
        // Use up_probability (0-100) instead of binary Up/Down for smoother scoring
        final statusScore = upProbability / 100.0;
        final distanceScore = (1.0 - (distance / _recommendRadiusMeters)).clamp(0.0, 1.0);
        final stabilityWeight = _preferStableAps ? 0.7 : 0.5;
        final score = statusScore * stabilityWeight + distanceScore * (1.0 - stabilityWeight);

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
        ));
      }

      scoredAps.sort((a, b) => b.score.compareTo(a.score));

      setState(() {
        _recommendations = scoredAps.take(5).toList();
        _statusMessage = 'Top ${_recommendations.length} recommendations ready.';
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
            Text(
              'Your location: ${_locationLabel ?? 'Locating...'}',
              style: const TextStyle(fontSize: 16),
            ),
            const SizedBox(height: 12),
            Text(
              _statusMessage,
              style: const TextStyle(fontSize: 14, color: Colors.black54),
            ),
            const SizedBox(height: 16),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: _isLoading ? null : _getRecommendation,
                style: ElevatedButton.styleFrom(
                  padding: const EdgeInsets.symmetric(vertical: 16),
                ),
                child: _isLoading
                    ? const SizedBox(
                        height: 24,
                        width: 24,
                        child: CircularProgressIndicator(
                          strokeWidth: 2.5,
                          color: Colors.white,
                        ),
                      )
                    : const Text('Recommend Best APs'),
              ),
            ),
            const SizedBox(height: 16),
            Expanded(
              child: _recommendations.isEmpty
                  ? const Center(
                      child: Text('No recommendations yet. Tap the button above.'),
                    )
                  : ListView.builder(
                      itemCount: _recommendations.length,
                      itemBuilder: (context, index) {
                        final ap = _recommendations[index];
                        return Card(
                          margin: const EdgeInsets.symmetric(vertical: 8),
                          child: ListTile(
                            title: Text(ap.name),
                            subtitle: Text('${ap.building} • ${ap.floor != null ? 'Floor ${ap.floor}' : 'Floor unknown'}'),
                            trailing: Column(
                              mainAxisAlignment: MainAxisAlignment.center,
                              crossAxisAlignment: CrossAxisAlignment.end,
                              children: [
                                Text('${ap.distance.toStringAsFixed(0)} m'),
                                const SizedBox(height: 4),
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
