import 'package:flutter/material.dart';
import 'package:wifers_app/models/ap_info.dart';
import 'package:wifers_app/services/storage_service.dart';
import 'package:wifers_app/services/api_service.dart';
import 'package:wifers_app/services/location_service.dart';
import 'package:wifers_app/pages/RoutePage.dart';

class FavoritesPage extends StatefulWidget {
  const FavoritesPage({super.key});

  @override
  State<FavoritesPage> createState() => _FavoritesPageState();
}

class _FavoritesPageState extends State<FavoritesPage> {
  final ApiService _apiService = ApiService();
  List<APInfo> _favorites = [];
  bool _isLoading = true;
  String? _statusMessage;

  @override
  void initState() {
    super.initState();
    _loadFavorites();
  }

  Future<void> _loadFavorites() async {
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

  Future<void> _predictAP(APInfo ap) async {
    try {
      final features = {
        'client_count': 10,
        'cpu_utilization': 50.0,
        'mem_free': 1000.0,
        'mem_total': 2000.0,
        'last_modified': DateTime.now().toUtc().millisecondsSinceEpoch / 1000,
        'hour': DateTime.now().hour.toDouble(),
        'mem_usage': 50.0,
        'overloaded': 0,
      };
      
      final result = await _apiService.predictAPStatus(features);
      final predictedStatus = result['prediction'] ?? 'unknown';
      final confidence = (result['confidence'] as num?)?.toDouble() ?? 0.0;

      if (!mounted) return;

      showDialog(
        context: context,
        builder: (context) => AlertDialog(
          title: Text('AP Status Prediction'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('AP: ${ap.name ?? 'Unknown'}'),
              const SizedBox(height: 8),
              Text('Building: ${ap.building}'),
              if (ap.height != null) Text('Floor: ${ap.height}'),
              const SizedBox(height: 12),
              Row(
                children: [
                  Icon(
                    Icons.wifi,
                    color: predictedStatus == 'Up' ? Colors.green : Colors.red,
                  ),
                  const SizedBox(width: 8),
                  Text(
                    'Status: $predictedStatus',
                    style: TextStyle(
                      fontWeight: FontWeight.bold,
                      color: predictedStatus == 'Up' ? Colors.green : Colors.red,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              Text('Confidence: ${(confidence * 100).toStringAsFixed(1)}%'),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Close'),
            ),
          ],
        ),
      );
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Prediction error: $e')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Favorite APs'),
        backgroundColor: Theme.of(context).colorScheme.inversePrimary,
        actions: [
          if (_favorites.isNotEmpty)
            IconButton(
              icon: const Icon(Icons.refresh),
              tooltip: 'Refresh',
              onPressed: _loadFavorites,
            ),
        ],
      ),
      body: _isLoading
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
                        onPressed: () => Navigator.pop(context),
                        icon: const Icon(Icons.map),
                        label: const Text('Go to Map'),
                      ),
                    ],
                  ),
                )
              : RefreshIndicator(
                  onRefresh: _loadFavorites,
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
                          trailing: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              IconButton(
                                icon: const Icon(Icons.directions, color: Colors.blue),
                                tooltip: 'Navigate',
                                onPressed: () => _navigateToAP(ap),
                              ),
                              IconButton(
                                icon: const Icon(Icons.analytics, color: Colors.green),
                                tooltip: 'Predict Status',
                                onPressed: () => _predictAP(ap),
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
                              ),
                            ],
                          ),
                          isThreeLine: true,
                        ),
                      );
                    },
                  ),
                ),
      floatingActionButton: _favorites.isNotEmpty
          ? FloatingActionButton.extended(
              onPressed: () => Navigator.pop(context),
              icon: const Icon(Icons.map),
              label: const Text('Open Map'),
            )
          : null,
    );
  }
}