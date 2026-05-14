import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:geolocator/geolocator.dart';
import 'package:latlong2/latlong.dart';
import 'package:wifers_app/services/api_service.dart';
import 'package:wifers_app/services/location_service.dart';
import 'package:wifers_app/services/storage_service.dart';
import 'package:wifers_app/models/ap_info.dart';
import 'package:wifers_app/pages/RoutePage.dart';
import 'package:wifers_app/pages/FavoritesPage.dart';

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

  final List<APInfo> _aps = [];

  Future<void> _loadAps() async {
    try {
      final geojson = await rootBundle.loadString('geolocation_package/data/aps_geolocalizados_wgs84.geojson');
      final Map<String, dynamic> data = json.decode(geojson) as Map<String, dynamic>;
      final features = data['features'] as List<dynamic>;

      final loaded = features.map<APInfo>((dynamic feature) {
        final Map<String, dynamic> props = Map<String, dynamic>.from(feature['properties'] as Map);
        final coords = feature['geometry']['coordinates'] as List<dynamic>;

        return APInfo(
          id: props['USER_NOM_A']?.toString(),
          name: props['USER_NOM_A']?.toString(),
          building: props['USER_EDIFI']?.toString() ?? props['Nom_Edific']?.toString() ?? 'Unknown',
          height: props['Num_Planta'] is num ? (props['Num_Planta'] as num).toInt() : null,
          espacio: props['USER_Espai']?.toString(),
          lat: (coords[1] as num).toDouble(),
          lng: (coords[0] as num).toDouble(),
        );
      }).toList();

      setState(() {
        _aps.clear();
        _aps.addAll(loaded);
      });
    } catch (e) {
      // If asset loading fails, leave sample list empty and keep map functional.
      debugPrint('Failed to load AP geojson: $e');
    }
  }

  List<Marker> get _markers {
    final List<Marker> markers = _aps.map((ap) {
      return Marker(
        point: LatLng(ap.lat, ap.lng),
        width: 24,
        height: 24,
        child: GestureDetector(
          onTap: () => _showAPOptions(ap),
          child: Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(
              color: const Color.fromRGBO(33, 150, 243, 0.5),
              shape: BoxShape.circle,
              border: Border.all(color: const Color.fromRGBO(255, 255, 255, 0.8), width: 1),
            ),
          ),
        ),
      );
    }).toList();

    if (_currentLocation != null) {
      markers.add(
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
      );
    }

    return markers;
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

  void _showAPOptions(APInfo ap) async {
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

  Future<void> _navigateToAP(APInfo ap) async {
    Navigator.pop(context);
    if (_currentLocation == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Current location not available')),
      );
      return;
    }

    try {
      // Use advanced routing to get best path with alternatives
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
        // Parse alternatives if available
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
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Error fetching route: $e')),
      );
    }
  }

  void _predictAP(APInfo ap) {
    Navigator.pop(context);
    _showPredictionDialog(ap);
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
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('${ap.name ?? 'AP'} added to favorites')),
    );
  }

  void _showPredictionDialog([APInfo? ap]) {
    final _formKey = GlobalKey<FormState>();
    final _clientCountController = TextEditingController(text: '10');
    final _cpuUtilizationController = TextEditingController(text: '50.0');
    final _memFreeController = TextEditingController(text: '1000.0');
    final _memTotalController = TextEditingController(text: '2000.0');
    final _lastModifiedController = TextEditingController(text: '1640995200.0');
    final _hourController = TextEditingController(text: '12.0');
    final _memUsageController = TextEditingController(text: '50.0');
    bool _overloaded = false;

    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Predict AP Status${ap != null ? ' for ${ap.name}' : ''}'),
        content: SingleChildScrollView(
          child: Form(
            key: _formKey,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextFormField(
                  controller: _clientCountController,
                  decoration: const InputDecoration(labelText: 'Client Count'),
                  keyboardType: TextInputType.number,
                  validator: (value) => value!.isEmpty ? 'Required' : null,
                ),
                TextFormField(
                  controller: _cpuUtilizationController,
                  decoration: const InputDecoration(labelText: 'CPU Utilization (%)'),
                  keyboardType: TextInputType.number,
                  validator: (value) => value!.isEmpty ? 'Required' : null,
                ),
                TextFormField(
                  controller: _memFreeController,
                  decoration: const InputDecoration(labelText: 'Memory Free'),
                  keyboardType: TextInputType.number,
                  validator: (value) => value!.isEmpty ? 'Required' : null,
                ),
                TextFormField(
                  controller: _memTotalController,
                  decoration: const InputDecoration(labelText: 'Memory Total'),
                  keyboardType: TextInputType.number,
                  validator: (value) => value!.isEmpty ? 'Required' : null,
                ),
                TextFormField(
                  controller: _lastModifiedController,
                  decoration: const InputDecoration(labelText: 'Last Modified (Unix)'),
                  keyboardType: TextInputType.number,
                  validator: (value) => value!.isEmpty ? 'Required' : null,
                ),
                TextFormField(
                  controller: _hourController,
                  decoration: const InputDecoration(labelText: 'Hour'),
                  keyboardType: TextInputType.number,
                  validator: (value) => value!.isEmpty ? 'Required' : null,
                ),
                TextFormField(
                  controller: _memUsageController,
                  decoration: const InputDecoration(labelText: 'Memory Usage (%)'),
                  keyboardType: TextInputType.number,
                  validator: (value) => value!.isEmpty ? 'Required' : null,
                ),
                SwitchListTile(
                  title: const Text('Overloaded'),
                  value: _overloaded,
                  onChanged: (value) => setState(() => _overloaded = value),
                ),
              ],
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () async {
              if (_formKey.currentState!.validate()) {
                Navigator.pop(context);
                try {
                  final features = {
                    'client_count': int.parse(_clientCountController.text),
                    'cpu_utilization': double.parse(_cpuUtilizationController.text),
                    'mem_free': double.parse(_memFreeController.text),
                    'mem_total': double.parse(_memTotalController.text),
                    'last_modified': double.parse(_lastModifiedController.text),
                    'hour': double.parse(_hourController.text),
                    'mem_usage': double.parse(_memUsageController.text),
                    'overloaded': _overloaded ? 1 : 0,
                  };
                  final result = await _apiService.predictAPStatus(features);
                  final status = result['prediction'];

                  setState(() {
                    _aps.add(APInfo(
                      id: 'predicted_${DateTime.now().millisecondsSinceEpoch}',
                      name: ap?.name ?? 'Predicted AP',
                      building: ap?.building ?? 'Predicted',
                      lat: ap?.lat ?? _center.latitude,
                      lng: ap?.lng ?? _center.longitude,
                      height: ap?.height,
                      espacio: ap?.espacio,
                    ));
                  });

                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text('Predicted status: $status')),
                  );
                } catch (e) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text('Error: $e')),
                  );
                }
              }
            },
            child: const Text('Predict'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final displayCenter = _currentLocation ?? _center;

    return Scaffold(
      body: FlutterMap(
        mapController: _mapController,
        options: MapOptions(
          initialCenter: displayCenter,
          initialZoom: 15.0,
          keepAlive: true,
        ),
        children: [
          TileLayer(
            urlTemplate: 'https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png',
            userAgentPackageName: 'com.uab.wifers',
          ),
          MarkerLayer(
            markers: _markers,
          ),
        ],
      ),
      floatingActionButton: Column(
        mainAxisAlignment: MainAxisAlignment.end,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
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
            onPressed: () => _showPredictionDialog(),
            icon: const Icon(Icons.analytics),
            label: const Text('Predict Hotspot'),
          ),
        ],
      ),
    );
  }
}
