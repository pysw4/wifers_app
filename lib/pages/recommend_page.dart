import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:wifers_app/services/api_service.dart' show ApiService, ApiException;
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
  final String id, name, building, prediction, signalQuality;
  final int? floor;
  final int bars;
  final double lat, lng, distance, confidence, score, signalDb, upProbability;

  RecommendedAp({
    required this.id, required this.name, required this.building,
    this.floor, required this.lat, required this.lng, required this.distance,
    required this.prediction, required this.confidence, required this.score,
    this.signalDb = -70, this.signalQuality = 'Fair', this.bars = 1,
    this.upProbability = 0,
  });

  factory RecommendedAp.fromJson(Map<String, dynamic> map) => RecommendedAp(
    id: map['id'] ?? '', name: map['name'] ?? '', building: map['building'] ?? 'Unknown',
    floor: map['floor'] as int?,
    lat: (map['lat'] as num?)?.toDouble() ?? 0, lng: (map['lng'] as num?)?.toDouble() ?? 0,
    distance: (map['distance'] as num?)?.toDouble() ?? 0,
    prediction: map['prediction'] ?? 'Unknown', confidence: (map['confidence'] as num?)?.toDouble() ?? 0,
    score: (map['score'] as num?)?.toDouble() ?? 0,
    signalDb: (map['signal_db'] as num?)?.toDouble() ?? -70,
    signalQuality: map['signal_quality'] ?? 'Fair', bars: map['bars'] as int? ?? 1,
    upProbability: (map['up_probability'] as num?)?.toDouble() ?? 0,
  );
}

class _ModeDisplay { final String label; final IconData icon; final Color color; const _ModeDisplay(this.label, this.icon, this.color); }

class RecommendPageState extends State<RecommendPage> {
  final _api = ApiService();
  final MapController _mapController = MapController();

  bool _loading = false, _preferStable = true;
  String _status = 'Waiting for recommendation', _mode = 'balanced', _building = '';
  List<RecommendedAp> _results = [];
  List<String> _buildings = [];

  // Selection mode: 'map' or 'building'
  String _selectionMode = 'map';

  // Map-based search area
  LatLng _searchCenter = const LatLng(41.503, 2.105); // UAB campus center default
  double _searchRadiusMeters = 100;

  static const _modes = {
    'distance': _ModeDisplay('Distance Priority', Icons.near_me, Colors.green),
    'signal': _ModeDisplay('Signal Priority', Icons.signal_wifi_4_bar, Colors.orange),
    'balanced': _ModeDisplay('Balanced', Icons.balance, Colors.blue),
  };

  // Campus bounds for map constraint
  static final LatLngBounds _campusBounds = LatLngBounds(
    const LatLng(41.492, 2.092),
    const LatLng(41.514, 2.118),
  );

  @override
  void initState() { super.initState(); _loadSettings(); _loadBuildings(); _initSearchCenter(); }
  void reloadSettings() => _loadSettings();

  Future<void> _loadSettings() async {
    final s = await StorageService.loadSettings();
    if (!mounted) return;
    setState(() {
      _preferStable = s['preferStableAps'] ?? true;
      _mode = s['recommendMode'] as String? ?? 'balanced';
      _building = s['selectedBuilding'] as String? ?? '';
      _selectionMode = s['recommendSelectionMode'] as String? ?? 'map';
    });
  }

  Future<void> _saveMode(String m) async { final s = await StorageService.loadSettings(); s['recommendMode'] = m; await StorageService.saveSettings(s); }
  Future<void> _saveBuilding(String b) async { final s = await StorageService.loadSettings(); s['selectedBuilding'] = b; await StorageService.saveSettings(s); }
  Future<void> _saveSelectionMode(String m) async { final s = await StorageService.loadSettings(); s['recommendSelectionMode'] = m; await StorageService.saveSettings(s); }

  Future<void> _initSearchCenter() async {
    try {
      final p = await LocationService.getCurrentPosition();
      if (mounted) {
        setState(() {
          _searchCenter = LatLng(p.latitude, p.longitude);
        });
      }
    } catch (_) {
      // Keep campus center default
    }
  }

  Future<void> _loadBuildings() async {
    try {
      final b = await ApDataService.loadBuildings();
      if (mounted) setState(() => _buildings = b);
    } catch (_) {}
  }

  String get _modeLabel => _modes[_mode]?.label ?? 'Balanced';
  IconData get _modeIcon => _modes[_mode]?.icon ?? Icons.balance;
  Color get _modeColor => _modes[_mode]?.color ?? Colors.blue;

  Future<bool> _showGateDialog(String title, String content) async {
    if (!mounted) return false;
    return await showDialog<bool>(context: context, builder: (c) => AlertDialog(title: Text(title), content: Text(content), actions: [
      TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
      TextButton(onPressed: () => Navigator.pop(c, true), child: const Text('Use Campus Gate')),
    ])) ?? false;
  }

  Future<void> _getRecommendation() async {
    setState(() { _loading = true; _status = 'Calculating...'; _results = []; });
    try {
      final pos = _searchCenter;

      final ck = 'recommend_${pos.latitude.toStringAsFixed(4)}_${pos.longitude.toStringAsFixed(4)}_${_building.isNotEmpty ? _building : 'all'}_${_searchRadiusMeters.toInt()}$_preferStable$_mode';
      final settings = await StorageService.loadSettings();
      final cached = await CacheService.get<String>(ck, ttl: Duration(minutes: settings['cacheDurationMinutes'] as int? ?? 60));
      if (cached != null) {
        final list = (jsonDecode(cached) as List).map((e) => RecommendedAp.fromJson(e as Map<String, dynamic>)).toList();
        setState(() { _results = list; _status = 'Top ${list.length} recommendations ($_modeLabel).'; _loading = false; });
        return;
      }

      final resp = await _api.recommendAPs(
        lat: pos.latitude, lng: pos.longitude,
        radius: _searchRadiusMeters.toInt(),
        mode: _mode, building: _building, preferStable: _preferStable,
      );
      final recs = (resp['recommendations'] as List?)?.map((e) => RecommendedAp.fromJson(e as Map<String, dynamic>)).toList() ?? [];
      await CacheService.set(ck, jsonEncode(recs.map((a) => {'id':a.id,'name':a.name,'building':a.building,'floor':a.floor,'lat':a.lat,'lng':a.lng,'distance':a.distance,'prediction':a.prediction,'confidence':a.confidence,'score':a.score,'signal_db':a.signalDb,'signal_quality':a.signalQuality,'bars':a.bars,'up_probability':a.upProbability}).toList()));
      setState(() { _results = recs; _status = 'Top ${recs.length} recommendations ($_modeLabel).'; });
    } catch (e) {
      if (e is ApiException && e.statusCode == 422 && mounted) {
        final errors = e.details?['errors'] as List? ?? [];
        final errorMessages = errors.isNotEmpty
            ? errors.map((err) => '• ${err['field']}: ${err['message']}').join('\n')
            : e.message;
        await showDialog(
          context: context,
          builder: (c) => AlertDialog(
            title: const Row(children: [Icon(Icons.warning_amber_rounded, color: Colors.orange), SizedBox(width: 8), Text('Invalid Input')]),
            content: SingleChildScrollView(child: Text(errorMessages)),
            actions: [TextButton(onPressed: () => Navigator.pop(c), child: const Text('OK'))],
          ),
        );
      }
      setState(() { _status = 'Failed: $e'; });
    } finally {
      setState(() { _loading = false; });
    }
  }

  Future<void> _navigateToAp(RecommendedAp ap) async {
    try {
      final p = await LocationService.getCurrentPosition();
      final pos = LatLng(p.latitude, p.longitude);
      if (!LocationService.isNearCampus(pos)) {
        if (!await _showGateDialog('Outside Campus', 'Navigation only available from within campus. Start from campus gate?')) return;
        final gp = await _api.fetchRoute(LocationService.campusGateLng, LocationService.campusGateLat, ap.lng, ap.lat);
        if (gp.isNotEmpty && mounted) Navigator.push(context, MaterialPageRoute(builder: (_) => RoutePage(path: gp, title: 'Navigate to ${ap.name} (from Gate)')));
        return;
      }
      final path = await _api.fetchRoute(p.longitude, p.latitude, ap.lng, ap.lat);
      if (path.isNotEmpty && mounted) Navigator.push(context, MaterialPageRoute(builder: (_) => RoutePage(path: path, title: 'Navigate to ${ap.name}')));
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Navigation error: $e')));
    }
  }

  Color _dbmToColor(double dbm) { final t = (dbm.clamp(-97, -22) + 97) / 75; return t > 0.66 ? Colors.green : t > 0.33 ? Colors.orange : Colors.red; }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('AP Recommendation'),
        backgroundColor: Theme.of(context).colorScheme.inversePrimary,
      ),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Selection mode toggle: Map or Building
            SizedBox(
              width: double.infinity,
              child: SegmentedButton<String>(
                segments: const [
                  ButtonSegment(
                    value: 'map',
                    label: Text('On Map', style: TextStyle(fontSize: 11)),
                    icon: Icon(Icons.map, size: 16),
                  ),
                  ButtonSegment(
                    value: 'building',
                    label: Text('By Building', style: TextStyle(fontSize: 11)),
                    icon: Icon(Icons.business, size: 16),
                  ),
                ],
                selected: {_selectionMode},
                onSelectionChanged: (s) {
                  setState(() {
                    _selectionMode = s.first;
                    // When switching to building mode, default to all buildings
                    if (s.first == 'building') {
                      _building = '';
                      _saveBuilding('');
                    }
                  });
                  _saveSelectionMode(s.first);
                },
                showSelectedIcon: false,
                style: ButtonStyle(visualDensity: VisualDensity.compact, tapTargetSize: MaterialTapTargetSize.shrinkWrap),
              ),
            ),
            const SizedBox(height: 8),
            // Recommendation mode selector
            SizedBox(
              width: double.infinity,
              child: SegmentedButton<String>(
                segments: _modes.entries.map((e) => ButtonSegment(
                  value: e.key,
                  label: Text(e.value.label, style: const TextStyle(fontSize: 11)),
                  icon: Icon(e.value.icon, size: 16),
                )).toList(),
                selected: {_mode},
                onSelectionChanged: (s) { setState(() => _mode = s.first); _saveMode(s.first); },
                showSelectedIcon: false,
                style: ButtonStyle(visualDensity: VisualDensity.compact, tapTargetSize: MaterialTapTargetSize.shrinkWrap),
              ),
            ),
            const SizedBox(height: 8),
            // Conditional UI: Map selection or Building selection
            if (_selectionMode == 'map') ...[
              // Mini map for area selection
              Card(
                margin: EdgeInsets.zero,
                clipBehavior: Clip.antiAlias,
                child: SizedBox(
                  height: 250,
                  child: Stack(
                    children: [
                      FlutterMap(
                        mapController: _mapController,
                        options: MapOptions(
                          initialCenter: _searchCenter,
                          initialZoom: 15.5,
                          minZoom: 14.5,
                          maxZoom: 18.0,
                          cameraConstraint: CameraConstraint.contain(bounds: _campusBounds),
                          onTap: (tapPos, latlng) {
                            setState(() => _searchCenter = latlng);
                          },
                        ),
                        children: [
                          TileLayer(
                            urlTemplate: 'https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png',
                            userAgentPackageName: 'com.uab.wifers',
                          ),
                          // Search radius circle
                          CircleLayer(
                            circles: [
                              CircleMarker(
                                point: _searchCenter,
                                radius: _searchRadiusMeters,
                                useRadiusInMeter: true,
                                color: Colors.blue.withValues(alpha: 0.12),
                                borderColor: Colors.blue.withValues(alpha: 0.4),
                                borderStrokeWidth: 2,
                              ),
                            ],
                          ),
                          // Center pin marker
                          MarkerLayer(
                            markers: [
                              Marker(
                                point: _searchCenter,
                                width: 40,
                                height: 40,
                                child: const Icon(Icons.location_on, color: Colors.blue, size: 36),
                              ),
                            ],
                          ),
                        ],
                      ),
                      // Top-left info overlay
                      Positioned(
                        top: 8,
                        left: 8,
                        child: Container(
                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                          decoration: BoxDecoration(
                            color: Colors.white.withValues(alpha: 0.85),
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: Text(
                            'Tap map to set center',
                            style: TextStyle(fontSize: 11, color: Colors.grey[700]),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 8),
              // Radius slider
              Row(children: [
                const Icon(Icons.radio_button_unchecked, size: 16, color: Colors.blue),
                const SizedBox(width: 8),
                Expanded(
                  child: Slider(
                    value: _searchRadiusMeters,
                    min: 20,
                    max: 300,
                    divisions: 28,
                    label: '${_searchRadiusMeters.toInt()} m',
                    onChanged: (v) => setState(() => _searchRadiusMeters = v),
                  ),
                ),
                SizedBox(
                  width: 60,
                  child: Text('${_searchRadiusMeters.toInt()} m', style: const TextStyle(fontSize: 13)),
                ),
              ]),
              // Center coordinates display
              Padding(
                padding: const EdgeInsets.only(left: 24, bottom: 4),
                child: Text(
                  'Center: ${_searchCenter.latitude.toStringAsFixed(5)}, ${_searchCenter.longitude.toStringAsFixed(5)}',
                  style: TextStyle(fontSize: 11, color: Colors.grey[500]),
                ),
              ),
            ] else ...[
              // Building selector
              Card(
                margin: EdgeInsets.zero,
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                  child: Row(children: [
                    Icon(Icons.business, size: 18, color: Colors.grey[600]),
                    const SizedBox(width: 8),
                    Expanded(
                      child: DropdownButtonHideUnderline(
                        child: DropdownButton<String>(
                          value: _buildings.contains(_building) ? _building : '',
                          isExpanded: true,
                          hint: const Text('Select a building', style: TextStyle(fontSize: 14)),
                          items: [
                            const DropdownMenuItem(value: '', child: Text('Select a building', style: TextStyle(fontSize: 14))),
                            ..._buildings.map((b) => DropdownMenuItem(value: b, child: Text(b, style: const TextStyle(fontSize: 14)))),
                          ],
                          onChanged: (v) { if (v != null) { setState(() => _building = v); _saveBuilding(v); } },
                        ),
                      ),
                    ),
                    if (_building.isNotEmpty)
                      GestureDetector(
                        onTap: () { setState(() => _building = ''); _saveBuilding(''); },
                        child: Icon(Icons.close, size: 16, color: Colors.grey[400]),
                      ),
                  ]),
                ),
              ),
              const SizedBox(height: 8),
              // Show selected building info
              if (_building.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(left: 8),
                  child: Row(children: [
                    Icon(Icons.check_circle, size: 16, color: Colors.green[600]),
                    const SizedBox(width: 6),
                    Text('Building: $_building', style: TextStyle(fontSize: 13, color: Colors.green[700], fontWeight: FontWeight.w500)),
                  ]),
                ),
            ],
            const SizedBox(height: 8),
            // Status text
            Text(_status, style: const TextStyle(fontSize: 14, color: Colors.black54)),
            const SizedBox(height: 8),
            // Recommend button
            SizedBox(
              width: double.infinity,
              child: ElevatedButton.icon(
                onPressed: _loading ? null : _getRecommendation,
                icon: _loading
                    ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
                    : Icon(_modeIcon),
                label: Text(_loading ? 'Calculating...' : 'Find Best APs ($_modeLabel)'),
                style: ElevatedButton.styleFrom(
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  backgroundColor: _modeColor,
                  foregroundColor: Colors.white,
                ),
              ),
            ),
            const SizedBox(height: 12),
            // Results list
            Expanded(
              child: _results.isEmpty
                  ? Center(
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(_modeIcon, size: 64, color: Colors.grey[300]),
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
                      itemCount: _results.length,
                      itemBuilder: (c, i) {
                        final a = _results[i];
                        final sc = _dbmToColor(a.signalDb);
                        return Card(
                          margin: const EdgeInsets.symmetric(vertical: 6),
                          child: ListTile(
                            leading: CircleAvatar(
                              backgroundColor: _modeColor.withValues(alpha: 0.15),
                              child: Text('${i+1}', style: TextStyle(fontWeight: FontWeight.bold, color: _modeColor)),
                            ),
                            title: Text(a.name, style: const TextStyle(fontWeight: FontWeight.w600)),
                            subtitle: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text('${a.building} • ${a.floor != null ? "Floor ${a.floor}" : "Floor unknown"}'),
                                const SizedBox(height: 4),
                                Row(children: [
                                  Icon(Icons.near_me, size: 12, color: Colors.grey[600]),
                                  const SizedBox(width: 2),
                                  Text('${a.distance.toStringAsFixed(0)} m', style: TextStyle(fontSize: 11, color: Colors.grey[600])),
                                  const SizedBox(width: 12),
                                  Icon(Icons.signal_wifi_4_bar, size: 12, color: sc),
                                  const SizedBox(width: 2),
                                  Text('${a.signalDb.toStringAsFixed(1)} dBm', style: TextStyle(fontSize: 11, color: sc)),
                                ]),
                              ],
                            ),
                            trailing: Column(
                              mainAxisAlignment: MainAxisAlignment.center,
                              crossAxisAlignment: CrossAxisAlignment.end,
                              children: [
                                Row(mainAxisSize: MainAxisSize.min, children: [
                                  Icon(Icons.wifi, size: 14, color: a.prediction == 'Up' ? Colors.green : Colors.red),
                                  const SizedBox(width: 4),
                                  Text('${(a.score*100).toStringAsFixed(0)}%', style: TextStyle(fontWeight: FontWeight.bold, color: a.prediction == 'Up' ? Colors.green : Colors.red)),
                                ]),
                                const SizedBox(height: 2),
                                Text('${a.confidence.toStringAsFixed(2)} conf', style: TextStyle(fontSize: 10, color: Colors.grey[500])),
                              ],
                            ),
                            onTap: () => _navigateToAp(a),
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
