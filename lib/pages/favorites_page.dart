import 'package:flutter/material.dart';
import 'package:latlong2/latlong.dart';
import 'package:wifers_app/models/ap_info.dart';
import 'package:wifers_app/services/storage_service.dart';
import 'package:wifers_app/services/location_service.dart';
import 'package:wifers_app/services/api_service.dart';
import 'package:wifers_app/pages/route_page.dart';
import 'package:wifers_app/pages/predictor_page.dart';

class FavoritesPage extends StatefulWidget {
  final VoidCallback? onSwitchToMap;

  const FavoritesPage({super.key, this.onSwitchToMap});

  @override
  FavoritesPageState createState() => FavoritesPageState();
}

class FavoritesPageState extends State<FavoritesPage> {
  final ApiService _apiService = ApiService();
  List<APInfo> _favorites = [];
  bool _isLoading = true;
  String? _statusMessage;

  @override
  void initState() {
    super.initState();
    loadFavorites();
  }

  Future<void> loadFavorites() async {
    setState(() {
      _isLoading = true;
    });

    try {
      final favorites = await StorageService.loadFavorites();
      setState(() {
        _favorites = favorites;
        _isLoading = false;
        if (favorites.isEmpty) {
          _statusMessage = 'No favorite APs yet. Go to the map and tap the heart icon to add one.';
        } else {
          _statusMessage = null;
        }
      });
    } catch (e) {
      setState(() {
        _isLoading = false;
        _statusMessage = 'Error loading favorites: $e';
      });
    }
  }

  Future<void> _removeFavorite(APInfo ap) async {
    try {
      await StorageService.removeFavorite(ap);
      setState(() {
        _favorites.removeWhere((item) => item.uniqueKey == ap.uniqueKey);
      });
      
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('${ap.name ?? 'AP'} removed from favorites')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error removing favorite: $e')),
        );
      }
    }
  }

  Future<void> _navigateToAP(APInfo ap) async {
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
                title: 'Navigate to ${ap.name ?? 'AP'} (from Gate)',
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
              title: 'Navigate to ${ap.name ?? 'AP'}',
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

  void _predictAP(APInfo ap) {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (context) => PredictorPage(selectedAp: ap),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return _isLoading
        ? const Center(child: CircularProgressIndicator())
        : _favorites.isEmpty
            ? Center(
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    const Icon(
                      Icons.favorite_border,
                      size: 64,
                      color: Colors.grey,
                    ),
                    const SizedBox(height: 16),
                    Text(
                      _statusMessage ?? 'No favorites yet',
                      style: const TextStyle(
                        fontSize: 16,
                        color: Colors.grey,
                      ),
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 24),
                    ElevatedButton.icon(
                      onPressed: () {
                        widget.onSwitchToMap?.call();
                      },
                      icon: const Icon(Icons.map),
                      label: const Text('Go to Map'),
                    ),
                  ],
                ),
              )
              : RefreshIndicator(
                onRefresh: loadFavorites,
                child: ListView.builder(
                  padding: const EdgeInsets.all(16.0),
                  itemCount: _favorites.length,
                  itemBuilder: (context, index) {
                    final ap = _favorites[index];
                    return Card(
                      margin: const EdgeInsets.only(bottom: 12),
                      child: ListTile(
                        leading: const CircleAvatar(
                          child: Icon(Icons.wifi),
                        ),
                        title: Text(
                          ap.name ?? 'AP ${index + 1}',
                          style: const TextStyle(fontWeight: FontWeight.bold),
                        ),
                        subtitle: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text('${ap.building}${ap.height != null ? ', Floor ${ap.height}' : ''}'),
                            Text(
                              '${ap.lat.toStringAsFixed(4)}, ${ap.lng.toStringAsFixed(4)}',
                              style: const TextStyle(fontSize: 12, color: Colors.grey),
                            ),
                          ],
                        ),
                        trailing: SizedBox(
                          width: 108,
                          child: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              IconButton(
                                icon: const Icon(Icons.directions, color: Colors.blue),
                                tooltip: 'Navigate',
                                onPressed: () => _navigateToAP(ap),
                                constraints: const BoxConstraints(minWidth: 32, minHeight: 32),
                                padding: EdgeInsets.zero,
                              ),
                              IconButton(
                                icon: const Icon(Icons.analytics, color: Colors.green),
                                tooltip: 'Predict Status',
                                onPressed: () => _predictAP(ap),
                                constraints: const BoxConstraints(minWidth: 32, minHeight: 32),
                                padding: EdgeInsets.zero,
                              ),
                              IconButton(
                                icon: const Icon(Icons.delete, color: Colors.red),
                                tooltip: 'Remove from favorites',
                                onPressed: () {
                                  showDialog(
                                    context: context,
                                    builder: (context) => AlertDialog(
                                      title: const Text('Remove Favorite'),
                                      content: Text('Remove ${ap.name ?? 'AP'} from favorites?'),
                                      actions: [
                                        TextButton(
                                          onPressed: () => Navigator.pop(context),
                                          child: const Text('Cancel'),
                                        ),
                                        TextButton(
                                          onPressed: () {
                                            Navigator.pop(context);
                                            _removeFavorite(ap);
                                          },
                                          child: const Text('Remove'),
                                        ),
                                      ],
                                    ),
                                  );
                                },
                                constraints: const BoxConstraints(minWidth: 32, minHeight: 32),
                                padding: EdgeInsets.zero,
                              ),
                            ],
                          ),
                        ),
                        isThreeLine: true,
                      ),
                    );
                  },
                ),
              );
  }
}