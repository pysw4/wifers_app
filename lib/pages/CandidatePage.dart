import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:wifers_app/services/api_service.dart';
import 'package:wifers_app/services/location_service.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:wifers_app/models/ap_info.dart';
import 'package:wifers_app/services/storage_service.dart';

class CandidatePage extends StatefulWidget {
  const CandidatePage({super.key});
  @override
  State<CandidatePage> createState() => _CandidatePageState();
}

class _CandidatePageState extends State<CandidatePage> {
  final ApiService _api = ApiService();
  
  double? _currentLng;
  double? _currentLat;
  late Future<List<APInfo>> _candidatesFuture;
//   final MapController _mapController = MapController();
  List<APInfo> favoriteAps = [];
  
  @override
  void initState(){
    super.initState(); 
    _loadFavorites();     
    _candidatesFuture = _fetchLocationAndCandidates();
  }
    // load favorite
  Future<void> _loadFavorites() async {
    final favorites = await StorageService.loadFavorites();
    setState(() {
      favoriteAps = favorites;
    });
  }

  // add favorite
  Future<void> _addToFavorites(APInfo ap) async {
    await StorageService.addFavorite(ap);
    await _loadFavorites();          // reload UI
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('已收藏: ${ap.building}')),
    );
  }

  //remove favorite
  Future<void> _removeFromFavorites(APInfo ap) async {
    await StorageService.removeFavorite(ap);
    await _loadFavorites();
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('Canceled favorite: ${ap.building}')),
    );
  }

  // 
  bool _isFavorite(APInfo ap) {
    return favoriteAps.any((item) => item.uniqueKey == ap.uniqueKey);
  }

  Future<List<APInfo>> _fetchLocationAndCandidates() async {
  
    final position = await LocationService.getCurrentPosition();
    setState(() {
        // _currentLng = position.longitude;
        // _currentLat = position.latitude;
        _currentLng = 2.115;
        _currentLat = 41.5;
    });
    final future = _api.fetchCandidates(_currentLng!, _currentLat!, 1000);
    return future;
    //  catch (e) {
    //   ScaffoldMessenger.of(context).showSnackBar(
    //     SnackBar(content: Text('Error at access the local location: $e')),
    //   );
    // }
  }

 void _showFavoriteAPs() {
  if (favoriteAps.isEmpty) {
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('there is no faborite AP')),
    );
    return;
  }

  showModalBottomSheet(
    context: context,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
    ),
    builder: (BuildContext ctx) {
      return SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const SizedBox(height: 8),
            Container(
              width: 40,
              height: 4,
              decoration: BoxDecoration(
                color: Colors.grey[400],
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            const SizedBox(height: 16),
            const Text(
              'my favorite',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
            ),
            const Divider(),
            // list
            Flexible(
              child: ListView.builder(
                shrinkWrap: true,
                itemCount: favoriteAps.length,
                itemBuilder: (ctx, index) {
                  final ap = favoriteAps[index];
                  return ListTile(
                    leading: const Icon(Icons.location_on, color: Colors.red),
                    title: Text(ap.building),
                    subtitle: Text('floor: ${ap.height ?? "unknown"} | ${ap.espacio ?? ""}'),
                    trailing: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        IconButton(
                          icon: const Icon(Icons.navigation, color: Colors.blue),
                          onPressed: () {
                            Navigator.pop(ctx);
                            _navigateToExternal(ap.lat, ap.lng); 
                          },
                        ),
                        IconButton(
                          icon: const Icon(Icons.delete, color: Colors.grey),
                          onPressed: () {
                            setState(() {
                              favoriteAps.removeAt(index);
                            });
                            Navigator.pop(ctx);
                            _showFavoriteAPs(); 
                          },
                        ),
                      ],
                    ),
                  );
                },
              ),
            ),
            const SizedBox(height: 8),
          ],
        ),
      );
    },
  );
}
  
  void _onMarkerTapped(APInfo ap) {
    double lat = ap.lat;
    double lng = ap.lng;
    String building = ap.building;
    String? espacio = ap.espacio;
    //int?r height = ap.height;
    showModalBottomSheet(
      context: context,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (BuildContext bottomSheetContext) {
        return SafeArea(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const SizedBox(height: 8),
              // top dragging bar
              Container(
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: Colors.grey[400],
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
              const SizedBox(height: 16),

              // coordinate
              ListTile(
                leading: const Icon(Icons.location_on, color: Colors.red),
                title: Text('${building} ${espacio}'),
                subtitle: Text('lat: ${lat.toStringAsFixed(6)} lng: ${lng.toStringAsFixed(6)}'),
            
              ),
              const Divider(),

              // navigator
              ListTile(
                leading: const Icon(Icons.directions_walk, color: Colors.blue),
                title: const Text('Navigate to there'),
                onTap: () {
                  Navigator.pop(bottomSheetContext); //close botton menu
                  _navigateToExternal(lat, lng);           
                },
              ),
              
              ListTile(
                leading: Icon(Icons.bookmark_border),
                title: Text('save this ap'),
                onTap: () { 
                  Navigator.pop(bottomSheetContext); 
                  _addToFavorites(ap);
                },
              ),
            ],
          ),
        );
      },
    );
  }
  void _saveToFavorite(ap){
    favoriteAps.add(ap);
  }
  void _navigateToExternal(double destLat, double destLng) async {

    final startLat = _currentLat;
    final startLng = _currentLng;

    String url;
    if (startLat != null && startLng != null) {
  
      url = 'https://www.google.com/maps/dir/?api=1&origin=$startLat,$startLng&destination=$destLat,$destLng&travelmode=walking';
    } else {
    
      url = 'https://www.google.com/maps/search/?api=1&query=$destLat,$destLng';
    }

    final uri = Uri.parse(url);
    try {
      if (await canLaunchUrl(uri)) {
        await launchUrl(uri, mode: LaunchMode.externalApplication);
      } else {
        // try Apple Maps (iOS)
        final appleUrl = Uri.parse('http://maps.apple.com/?daddr=$destLat,$destLng&dirflg=w');
        if (await canLaunchUrl(appleUrl)) {
          await launchUrl(appleUrl, mode: LaunchMode.externalApplication);
        } else {
          throw 'can not open external navigator';
        }
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('failed: $e')),
      );
    }
  }
  List<Marker> _buildMarkers(List apList) {
    List<Marker> markers = apList.map((coord) {
      return Marker(
        point: LatLng(coord.lat, coord.lng),   
        width: 20,
        height: 20,
        child: GestureDetector(
          onTap: () {
            _onMarkerTapped(coord);
          },
          child: const Icon(
            Icons.location_pin,
            color: Colors.red,
            size: 20,
          ),
        ),
      );
    }).toList();

    if (_currentLat != null && _currentLng != null) {
    markers.add(
      Marker(
        point: LatLng(_currentLat!, _currentLng!),
        width: 30,
        height: 30,
        child: const Icon(Icons.person_pin_circle, color: Colors.blue, size: 30),
      ),
    );
  }
    return markers;
  }
    @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Aps Nearby:')),
      body: _candidatesFuture == null
          ? _buildInitialView()
          : FutureBuilder<List<APInfo>>(
              future: _candidatesFuture,
              builder: (context, snapshot) {
                if (snapshot.connectionState == ConnectionState.waiting) {
                  return const Center(child: CircularProgressIndicator());
                }
                if (snapshot.hasError) {
                  return Center(child: Text('Error: ${snapshot.error}'));
                }
                if (!snapshot.hasData || snapshot.data!.isEmpty) {
                  return const Center(child: Text('No aps found'));
                }

                final apList = snapshot.data!;
                
                //center of map
                final centerLat = _currentLat ?? apList[0].lat;
                final centerLng = _currentLng ?? apList[0].lng;
                 return FlutterMap(
                    // mapController: _mapController,
                    options: MapOptions(
                    initialCenter: LatLng(centerLat, centerLng),
                    initialZoom: 17,
                  ),
                  children: [
                    TileLayer(
                      urlTemplate: 'https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png',
                      userAgentPackageName: 'com.uab.wifers',
                    ),
                    MarkerLayer(
                      markers: _buildMarkers(apList),
                    ),
                  ],
                );
              },
            ),
      floatingActionButton: FloatingActionButton(
        onPressed: _showFavoriteAPs,
        child: const Icon(Icons.favorite),
      ),
    );
  }
  Widget _buildInitialView() {
    return const Scaffold(
    body: Center(
      child: Text('Waiting'),
    ),
    );
 }
}

