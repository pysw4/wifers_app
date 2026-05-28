import 'package:flutter/material.dart';
import 'package:latlong2/latlong.dart';
import 'package:wifers_app/models/ap_info.dart';
import 'package:wifers_app/services/storage_service.dart';
import 'package:wifers_app/services/location_service.dart';
import 'package:wifers_app/services/api_service.dart';
import 'package:wifers_app/pages/route_page.dart';
import 'package:wifers_app/pages/predictor_page.dart';

class _PredictionDialog extends StatefulWidget {
  final APInfo ap;

  const _PredictionDialog({required this.ap});

  @override
  State<_PredictionDialog> createState() => _PredictionDialogState();
}

class _PredictionDialogState extends State<_PredictionDialog> {
  final ApiService _apiService = ApiService();
  Map<String, dynamic>? _result;
  bool _isLoading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _predict();
  }

  Future<void> _predict() async {
    final now = DateTime.now();
    final features = {
      'ap_name': widget.ap.name ?? '',
      'hour': now.hour.toDouble(),
      'day_of_week': (now.weekday - 1).toDouble(),
      'is_weekend': (now.weekday >= 6) ? 1.0 : 0.0,
      'month': now.month.toDouble(),
      'day_of_month': now.day.toDouble(),
    };

    try {
      final result = await _apiService.predictAPStatus(features);
      if (mounted) {
        setState(() {
          _result = result;
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = e.toString();
          _isLoading = false;
        });
      }
    }
  }

  String _signalDb() {
    final cascade = _result?['features_used']?['cascade'];
    if (cascade == null) return '--';
    final db = cascade['predicted_signal_db'];
    if (db == null) return '--';
    return '${db.toStringAsFixed(1)} dBm';
  }

  String _evaluation() {
    final prediction = _result?['prediction'] as String?;
    final confidence = _result?['confidence'] as double? ?? 0;
    if (prediction == null) return 'Unknown';

    if (prediction == 'Up') {
      if (confidence >= 0.8) return 'Excellent signal quality expected';
      if (confidence >= 0.6) return 'Good signal quality expected';
      return 'Fair signal quality expected';
    } else {
      if (confidence >= 0.8) return 'Poor signal expected, consider alternatives';
      if (confidence >= 0.6) return 'Weak signal expected';
      return 'Very poor signal expected';
    }
  }

  Color _statusColor() {
    final prediction = _result?['prediction'] as String?;
    if (prediction == 'Up') return Colors.green;
    return Colors.red;
  }

  IconData _statusIcon() {
    final prediction = _result?['prediction'] as String?;
    if (prediction == 'Up') return Icons.wifi;
    return Icons.wifi_off;
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      title: Row(
        children: [
          const Icon(Icons.analytics, color: Colors.indigo, size: 24),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              widget.ap.name ?? 'AP Prediction',
              style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ],
      ),
      content: _isLoading
          ? const SizedBox(
              height: 100,
              child: Center(child: CircularProgressIndicator()),
            )
          : _error != null
              ? Text('Error: $_error', style: const TextStyle(color: Colors.red))
              : Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    // Status
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.symmetric(vertical: 16),
                      decoration: BoxDecoration(
                        color: _statusColor().withValues(alpha: 0.1),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Column(
                        children: [
                          Icon(_statusIcon(), size: 40, color: _statusColor()),
                          const SizedBox(height: 8),
                          Text(
                            _result?['prediction'] as String? ?? '--',
                            style: TextStyle(
                              fontSize: 22,
                              fontWeight: FontWeight.bold,
                              color: _statusColor(),
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 16),
                    // Signal DB
                    _infoTile(Icons.signal_cellular_alt, 'Signal Strength', _signalDb()),
                    const SizedBox(height: 8),
                    // Evaluation
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: Colors.grey[50],
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(color: Colors.grey[200]!),
                      ),
                      child: Row(
                        children: [
                          Icon(Icons.rate_review, size: 18, color: Colors.grey[600]),
                          const SizedBox(width: 8),
                          Expanded(
                            child: Text(
                              _evaluation(),
                              style: TextStyle(fontSize: 13, color: Colors.grey[700]),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Close'),
        ),
      ],
    );
  }

  Widget _infoTile(IconData icon, String label, String value) {
    return Row(
      children: [
        Icon(icon, size: 18, color: Colors.grey[600]),
        const SizedBox(width: 8),
        Text(label, style: TextStyle(fontSize: 13, color: Colors.grey[600])),
        const Spacer(),
        Text(value, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
      ],
    );
  }
}

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

  void _predictAP(APInfo ap) async {
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => _PredictionDialog(ap: ap),
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