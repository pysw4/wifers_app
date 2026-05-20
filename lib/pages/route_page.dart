import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:geolocator/geolocator.dart';
import 'package:latlong2/latlong.dart';
import 'package:wifers_app/services/api_service.dart';

class RoutePage extends StatefulWidget {
  final List<LatLng> path;
  final String title;
  final List<RouteAlternative>? alternatives;
  final double? totalDistance;

  const RoutePage({
    super.key,
    required this.path,
    this.title = 'Navigation Route',
    this.alternatives,
    this.totalDistance,
  });

  @override
  State<RoutePage> createState() => _RoutePageState();
}

class RouteAlternative {
  final List<LatLng> path;
  final double distance;
  final LatLng? endpoint;

  RouteAlternative({
    required this.path,
    required this.distance,
    this.endpoint,
  });
}

class _RoutePageState extends State<RoutePage> {
  final MapController _mapController = MapController();
  final ApiService _apiService = ApiService();
  
  StreamSubscription<Position>? _positionSubscription;
  LatLng? _currentLocation;
  bool _followUser = true;
  double _currentZoom = 15.0;
  int _selectedRouteIndex = 0;
  List<List<LatLng>> _allRoutes = [];
  List<RouteAlternative> _alternatives = [];
  bool _isLoadingAlternatives = false;
  String? _routeMessage;

  LatLng get source => widget.path.first;
  LatLng get destination => widget.path.last;

  List<LatLng> get currentRoute => 
      _allRoutes.isNotEmpty ? _allRoutes[_selectedRouteIndex] : widget.path;

  double get routeDistanceMeters {
    double total = 0;
    for (var i = 0; i < currentRoute.length - 1; i++) {
      total += const Distance().as(LengthUnit.Meter, currentRoute[i], currentRoute[i + 1]);
    }
    return total;
  }

  @override
  void initState() {
    super.initState();
    _allRoutes = [widget.path];
    _startLocationTracking();
    
    // Load alternatives if available
    if (widget.alternatives != null && widget.alternatives!.isNotEmpty) {
      _alternatives = widget.alternatives!;
      for (var alt in _alternatives) {
        _allRoutes.add(alt.path);
      }
    }
  }

  @override
  void dispose() {
    _positionSubscription?.cancel();
    super.dispose();
  }

  Future<void> _startLocationTracking() async {
    final hasPermission = await _handleLocationPermission();
    if (!hasPermission) {
      return;
    }

    _positionSubscription = Geolocator.getPositionStream(
      locationSettings: const LocationSettings(
        accuracy: LocationAccuracy.best,
        distanceFilter: 5,
      ),
    ).listen((Position position) {
      final newLocation = LatLng(position.latitude, position.longitude);
      setState(() {
        _currentLocation = newLocation;
      });
      if (_followUser) {
        _mapController.move(newLocation, _currentZoom);
      }
    });
  }

  Future<bool> _handleLocationPermission() async {
    bool serviceEnabled = await Geolocator.isLocationServiceEnabled();
    if (!serviceEnabled) {
      return false;
    }

    LocationPermission permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
      if (permission == LocationPermission.denied) {
        return false;
      }
    }
    if (permission == LocationPermission.deniedForever) {
      return false;
    }

    return true;
  }

  void _toggleFollow() {
    setState(() {
      _followUser = !_followUser;
    });
    if (_followUser && _currentLocation != null) {
      _mapController.move(_currentLocation!, _currentZoom);
    }
  }

  void _selectRoute(int index) {
    setState(() {
      _selectedRouteIndex = index;
    });
    // Center map on selected route
    if (_allRoutes[index].isNotEmpty) {
      _mapController.fitCamera(
        CameraFit.bounds(
          bounds: LatLngBounds.fromPoints(_allRoutes[index]),
          padding: const EdgeInsets.all(50),
        ),
      );
    }
  }

  Future<void> _loadAdvancedRoute() async {
    if (_isLoadingAlternatives) return;

    setState(() {
      _isLoadingAlternatives = true;
      _routeMessage = null;
    });

    try {
      final result = await _apiService.fetchAdvancedRoute(
        source.longitude,
        source.latitude,
        destination.longitude,
        destination.latitude,
        acceptableRange: 500,
      );

      final pathData = result['path'] as List<dynamic>;
      final newPath = pathData.map<LatLng>((item) {
        return LatLng(
          (item['lat'] as num).toDouble(),
          (item['lng'] as num).toDouble(),
        );
      }).toList();

      final alternativesData = result['alternatives'] as List<dynamic>? ?? [];
      final newAlternatives = <RouteAlternative>[];
      
      for (var altData in alternativesData) {
        final altPathData = altData['path'] as List<dynamic>;
        final altPath = altPathData.map<LatLng>((item) {
          return LatLng(
            (item['lat'] as num).toDouble(),
            (item['lng'] as num).toDouble(),
          );
        }).toList();

        newAlternatives.add(RouteAlternative(
          path: altPath,
          distance: (altData['distance'] as num).toDouble(),
        ));
      }

      setState(() {
        _allRoutes = [newPath];
        _alternatives = newAlternatives;
        for (var alt in newAlternatives) {
          _allRoutes.add(alt.path);
        }
        _selectedRouteIndex = 0;
        _routeMessage = result['message'] as String?;
        _isLoadingAlternatives = false;
      });

      // Fit map to best route
      if (newPath.isNotEmpty) {
        _mapController.fitCamera(
          CameraFit.bounds(
            bounds: LatLngBounds.fromPoints(newPath),
            padding: const EdgeInsets.all(50),
          ),
        );
      }
    } catch (e) {
      setState(() {
        _routeMessage = 'Error loading alternatives: $e';
        _isLoadingAlternatives = false;
      });
    }
  }

  Color _getRouteColor(int index) {
    if (index == _selectedRouteIndex) {
      return Colors.blue;
    }
    // Show unselected routes in lighter color
    return Colors.blue.withValues(alpha: 0.3);
  }

  @override
  Widget build(BuildContext context) {
    final displayCenter = _currentLocation ?? source;

    return Scaffold(
      appBar: AppBar(
        title: Text(widget.title),
        actions: [
          IconButton(
            icon: Icon(
              _followUser ? Icons.location_searching : Icons.location_disabled,
            ),
            tooltip: _followUser ? 'Following user location' : 'Tap to follow',
            onPressed: _toggleFollow,
          ),
          if (_alternatives.isEmpty && !_isLoadingAlternatives)
            IconButton(
              icon: const Icon(Icons.alt_route),
              tooltip: 'Find alternative routes',
              onPressed: _loadAdvancedRoute,
            ),
        ],
      ),
      body: Column(
        children: [
          // Route selector (if multiple routes available)
          if (_allRoutes.length > 1)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              child: SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Row(
                  children: List.generate(
                    _allRoutes.length,
                    (index) => Padding(
                      padding: const EdgeInsets.only(right: 8),
                      child: ChoiceChip(
                        label: Text(
                          index == 0
                              ? 'Best Route'
                              : 'Alt $index (${(_alternatives[index - 1].distance / 1000).toStringAsFixed(1)} km)',

                        ),
                        selected: _selectedRouteIndex == index,
                        onSelected: (selected) {
                          if (selected) _selectRoute(index);
                        },
                        selectedColor: Colors.blue,
                        labelStyle: TextStyle(
                          color: _selectedRouteIndex == index
                              ? Colors.white
                              : Colors.black54,
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            ),

          // Map
          Expanded(
            child: FlutterMap(
              mapController: _mapController,
              options: MapOptions(
                initialCenter: displayCenter,
                initialZoom: _currentZoom,
                minZoom: 13.0,
                maxZoom: 19.0,
                keepAlive: true,
                cameraConstraint: CameraConstraint.contain(
                  bounds: LatLngBounds(
                    const LatLng(41.47, 2.07),  // 西南角
                    const LatLng(41.54, 2.14),  // 东北角
                  ),
                ),
                onPositionChanged: (position, bool hasGesture) {
                  _currentZoom = position.zoom;
                },
              ),
              children: [
                TileLayer(
                  urlTemplate: 'https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png',
                  userAgentPackageName: 'com.uab.wifers',
                ),
                // Draw all routes
                PolylineLayer(
                  polylines: List.generate(
                    _allRoutes.length,
                    (index) => Polyline(
                      points: _allRoutes[index],
                      color: _getRouteColor(index),
                      strokeWidth: index == _selectedRouteIndex ? 5.0 : 3.0,
                    ),
                  ),
                ),
                MarkerLayer(
                  markers: [
                    // Source marker
                    Marker(
                      point: source,
                      width: 40,
                      height: 40,
                      child: const Icon(Icons.flag, color: Colors.blue, size: 36),
                    ),
                    // Destination marker
                    Marker(
                      point: destination,
                      width: 40,
                      height: 40,
                      child: const Icon(Icons.location_pin, color: Colors.red, size: 36),
                    ),
                    // Current location marker
                    if (_currentLocation != null)
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
                  ],
                ),
              ],
            ),
          ),

          // Info panel
          Container(
            padding: const EdgeInsets.all(16.0),
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.surface,
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withValues(alpha: 0.1),
                  blurRadius: 10,
                  offset: const Offset(0, -2),
                ),
              ],
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                // Route info
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                  children: [
                    _buildInfoItem(
                      icon: Icons.navigation,
                      label: 'Distance',
                      value: '${(routeDistanceMeters / 1000).toStringAsFixed(2)} km',
                    ),
                    _buildInfoItem(
                      icon: Icons.timer,
                      label: 'Est. Time',
                      value: '~${(routeDistanceMeters / 80).round()} min',
                    ),
                    _buildInfoItem(
                      icon: Icons.route,
                      label: 'Routes',
                      value: '${_allRoutes.length}',
                    ),
                  ],
                ),
                
                // Status message
                if (_routeMessage != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(
                      _routeMessage!,
                      style: TextStyle(
                        fontSize: 12,
                        color: Colors.grey[600],
                        fontStyle: FontStyle.italic,
                      ),
                      textAlign: TextAlign.center,
                    ),
                  ),

                const SizedBox(height: 12),
                
                // Close button
                ElevatedButton.icon(
                  icon: const Icon(Icons.close),
                  label: const Text('Close Navigation'),
                  onPressed: () => Navigator.pop(context),
                ),
              ],
            ),
          ),
        ],
      ),
      floatingActionButton: _isLoadingAlternatives
          ? const FloatingActionButton(
              onPressed: null,
              child: CircularProgressIndicator(),
            )
          : null,
    );
  }

  Widget _buildInfoItem({
    required IconData icon,
    required String label,
    required String value,
  }) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 20, color: Colors.blue),
        const SizedBox(height: 4),
        Text(
          value,
          style: const TextStyle(
            fontSize: 16,
            fontWeight: FontWeight.bold,
          ),
        ),
        Text(
          label,
          style: TextStyle(
            fontSize: 12,
            color: Colors.grey[600],
          ),
        ),
      ],
    );
  }
}