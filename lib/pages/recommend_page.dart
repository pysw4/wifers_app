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
  bool _loading = false, _preferStable = true, _useGate = false;
  String _status = 'Waiting for recommendation', _mode = 'balanced', _building = '';
  String? _locLabel;
  int _radius = 500;
  List<RecommendedAp> _results = [];
  List<String> _buildings = [];

  static const _modes = {
    'distance': _ModeDisplay('Distance Priority', Icons.near_me, Colors.green),
    'signal': _ModeDisplay('Signal Priority', Icons.signal_wifi_4_bar, Colors.orange),
    'balanced': _ModeDisplay('Balanced', Icons.balance, Colors.blue),
  };

  @override
  void initState() { super.initState(); _loadSettings(); _loadBuildings(); _updateLoc(); }
  void reloadSettings() => _loadSettings();

  Future<void> _loadSettings() async {
    final s = await StorageService.loadSettings();
    if (!mounted) return;
    setState(() { _preferStable = s['preferStableAps'] ?? true; _radius = s['recommendRadiusMeters'] ?? 500; _mode = s['recommendMode'] as String? ?? 'balanced'; _building = s['selectedBuilding'] as String? ?? ''; });
  }

  Future<void> _saveMode(String m) async { final s = await StorageService.loadSettings(); s['recommendMode'] = m; await StorageService.saveSettings(s); }
  Future<void> _saveBuilding(String b) async { final s = await StorageService.loadSettings(); s['selectedBuilding'] = b; await StorageService.saveSettings(s); }

  Future<void> _loadBuildings() async {
    try { setState(() { _buildings = await ApDataService.loadBuildings(); }); } catch (_) {}
  }

  String get _modeLabel => _modes[_mode]?.label ?? 'Balanced';
  IconData get _modeIcon => _modes[_mode]?.icon ?? Icons.balance;
  Color get _modeColor => _modes[_mode]?.color ?? Colors.blue;

  Future<void> _updateLoc() async {
    try { final p = await LocationService.getCurrentPosition(); setState(() { _locLabel = '${p.latitude.toStringAsFixed(5)}, ${p.longitude.toStringAsFixed(5)}'; }); } catch (_) { setState(() { _locLabel = 'Location unavailable'; }); }
  }

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
      LatLng pos;
      try {
        final p = await LocationService.getCurrentPosition(); pos = LatLng(p.latitude, p.longitude);
        if (!LocationService.isNearCampus(pos)) {
          if (!await _showGateDialog('Outside Campus', 'You are outside the UAB campus. Use the campus main entrance?')) {
            if (mounted) setState(() { _status = 'Cancelled.'; _loading = false; }); return;
          }
          pos = LocationService.campusGate; _useGate = true;
        }
      } catch (_) {
        if (!await _showGateDialog('Location Unavailable', 'Could not determine your location. Use campus main entrance?')) {
          if (mounted) setState(() { _status = 'Cancelled.'; _loading = false; }); return;
        }
        pos = LocationService.campusGate; _useGate = true;
      }

      final ck = 'recommend_${pos.latitude.toStringAsFixed(4)}_${pos.longitude.toStringAsFixed(4)}_${_building.isNotEmpty ? _building : 'all'}_$_radius$_preferStable$_mode${_useGate ? '_gate' : ''}';
      final settings = await StorageService.loadSettings();
      final cached = await CacheService.get<String>(ck, ttl: Duration(minutes: settings['cacheDurationMinutes'] as int? ?? 60));
      if (cached != null) {
        final list = (jsonDecode(cached) as List).map((e) => RecommendedAp.fromJson(e as Map<String, dynamic>)).toList();
        setState(() { _results = list; _status = 'Top ${list.length} recommendations ($_modeLabel).'; _loading = false; });
        return;
      }

      final resp = await _api.recommendAPs(lat: pos.latitude, lng: pos.longitude, radius: _radius, mode: _mode, building: _building, preferStable: _preferStable);
      final recs = (resp['recommendations'] as List?)?.map((e) => RecommendedAp.fromJson(e as Map<String, dynamic>)).toList() ?? [];
      await CacheService.set(ck, jsonEncode(recs.map((a) => {'id':a.id,'name':a.name,'building':a.building,'floor':a.floor,'lat':a.lat,'lng':a.lng,'distance':a.distance,'prediction':a.prediction,'confidence':a.confidence,'score':a.score,'signal_db':a.signalDb,'signal_quality':a.signalQuality,'bars':a.bars,'up_probability':a.upProbability}).toList()));
      setState(() { _results = recs; _status = 'Top ${recs.length} recommendations ($_modeLabel).'; });
    } catch (e) {
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
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('AP Recommendation'), backgroundColor: Theme.of(context).colorScheme.inversePrimary),
    body: Padding(padding: const EdgeInsets.all(16), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [Icon(Icons.my_location, size: 16, color: Colors.grey[600]), const SizedBox(width: 6), Expanded(child: Text(_locLabel ?? 'Locating...', style: TextStyle(fontSize: 14, color: Colors.grey[600])))]),
      const SizedBox(height: 8),
      SizedBox(width: double.infinity, child: SegmentedButton<String>(segments: _modes.entries.map((e) => ButtonSegment(value: e.key, label: Text(e.value.label, style: const TextStyle(fontSize: 11)), icon: Icon(e.value.icon, size: 16))).toList(), selected: {_mode}, onSelectionChanged: (s) { setState(() => _mode = s.first); _saveMode(s.first); }, showSelectedIcon: false, style: ButtonStyle(visualDensity: VisualDensity.compact, tapTargetSize: MaterialTapTargetSize.shrinkWrap))),
      const SizedBox(height: 12),
      Card(margin: EdgeInsets.zero, child: Padding(padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4), child: Row(children: [
        Icon(Icons.business, size: 18, color: Colors.grey[600]), const SizedBox(width: 8),
        Expanded(child: DropdownButtonHideUnderline(child: DropdownButton<String>(value: _buildings.contains(_building) ? _building : '', isExpanded: true, hint: const Text('All Buildings', style: TextStyle(fontSize: 14)), items: [const DropdownMenuItem(value: '', child: Text('All Buildings', style: TextStyle(fontSize: 14))), ..._buildings.map((b) => DropdownMenuItem(value: b, child: Text(b, style: const TextStyle(fontSize: 14))))], onChanged: (v) { if (v != null) { setState(() => _building = v); _saveBuilding(v); } }))),
        if (_building.isNotEmpty) GestureDetector(onTap: () { setState(() => _building = ''); _saveBuilding(''); }, child: Icon(Icons.close, size: 16, color: Colors.grey[400])),
      ]))),
      const SizedBox(height: 12),
      Text(_status, style: const TextStyle(fontSize: 14, color: Colors.black54)), const SizedBox(height: 16),
      SizedBox(width: double.infinity, child: ElevatedButton.icon(
        onPressed: _loading ? null : _getRecommendation,
        icon: _loading ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2)) : Icon(_modeIcon),
        label: Text(_loading ? 'Calculating...' : 'Find Best APs ($_modeLabel)'),
        style: ElevatedButton.styleFrom(padding: const EdgeInsets.symmetric(vertical: 16), backgroundColor: _modeColor, foregroundColor: Colors.white))),
      const SizedBox(height: 16),
      Expanded(child: _results.isEmpty
        ? Center(child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [Icon(_modeIcon, size: 64, color: Colors.grey[300]), const SizedBox(height: 16), Text('No recommendations yet.\nTap the button above.', textAlign: TextAlign.center, style: TextStyle(color: Colors.grey[500]))]))
        : ListView.builder(itemCount: _results.length, itemBuilder: (c, i) {
            final a = _results[i]; final sc = _dbmToColor(a.signalDb);
            return Card(margin: const EdgeInsets.symmetric(vertical: 6), child: ListTile(
              leading: CircleAvatar(backgroundColor: _modeColor.withValues(alpha: 0.15), child: Text('${i+1}', style: TextStyle(fontWeight: FontWeight.bold, color: _modeColor))),
              title: Text(a.name, style: const TextStyle(fontWeight: FontWeight.w600)),
              subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('${a.building} • ${a.floor != null ? 'Floor ${a.floor}' : 'Floor unknown'}'), const SizedBox(height: 4),
                Row(children: [Icon(Icons.near_me, size: 12, color: Colors.grey[600]), const SizedBox(width: 2), Text('${a.distance.toStringAsFixed(0)} m', style: TextStyle(fontSize: 11, color: Colors.grey[600])), const SizedBox(width: 12), Icon(Icons.signal_wifi_4_bar, size: 12, color: sc), const SizedBox(width: 2), Text('${a.signalDb.toStringAsFixed(1)} dBm', style: TextStyle(fontSize: 11, color: sc))])]),
              trailing: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.end, children: [
                Row(mainAxisSize: MainAxisSize.min, children: [Icon(Icons.wifi, size: 14, color: a.prediction == 'Up' ? Colors.green : Colors.red), const SizedBox(width: 4), Text('${(a.score*100).toStringAsFixed(0)}%', style: TextStyle(fontWeight: FontWeight.bold, color: a.prediction == 'Up' ? Colors.green : Colors.red))]),
                const SizedBox(height: 2), Text('${a.confidence.toStringAsFixed(2)} conf', style: TextStyle(fontSize: 10, color: Colors.grey[500]))]),
              onTap: () => _navigateToAp(a)));
          })),
  ]))));
}