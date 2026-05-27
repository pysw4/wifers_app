import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:latlong2/latlong.dart';

class ApiException implements Exception {
  final int statusCode;
  final String message;
  final Map<String, dynamic>? details;

  ApiException(this.statusCode, this.message, {this.details});

  @override
  String toString() => message;
}

class ApiService {
  static const String baseUrl = 'https://wifers-app-api.onrender.com';

  Future<dynamic> _get(String path, [Map<String, String>? params]) async {
    final uri = Uri.parse('$baseUrl/$path').replace(queryParameters: params);
    final response = await http.get(uri);
    if (response.statusCode == 200) return jsonDecode(response.body);
    throw Exception('${response.statusCode} $path');
  }

  Future<dynamic> _post(String path, Map<String, dynamic> body) async {
    final response = await http.post(
      Uri.parse('$baseUrl/$path'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode(body),
    );
    if (response.statusCode == 200) return jsonDecode(response.body);
    if (response.statusCode == 422) {
      final detail = jsonDecode(response.body);
      throw ApiException(
        422,
        detail['detail'] ?? 'Input validation failed',
        details: detail,
      );
    }
    throw Exception('${response.statusCode} $path');
  }

  Future<List<LatLng>> fetchRoute(double lng, double lat, double destLng, double destLat) async {
    final data = await _get('route/$lat/$lng/$destLat/$destLng') as Map<String, dynamic>;
    return (data['path'] as List)
        .map((item) => LatLng(
              (item['lat'] as num).toDouble(),
              (item['lng'] as num).toDouble(),
            ))
        .toList();
  }

  Future<Map<String, dynamic>> predictAPStatus(Map<String, dynamic> features) async =>
      await _post('predict', features) as Map<String, dynamic>;

  Future<Map<String, dynamic>> fetchAdvancedRoute(
    double lng, double lat, double destLng, double destLat, {int acceptableRange = 500}) async {
    final q = 'acceptable_range=$acceptableRange';
    final data = await _get('route/advanced/$lat/$lng/$destLat/$destLng?$q') as Map<String, dynamic>;
    return data;
  }

  Future<Map<String, dynamic>> getSignalHeatmap({int? hour, String? day}) async {
    final params = <String, String>{};
    if (hour != null) params['hour'] = hour.toString();
    if (day != null) params['day'] = day;
    return await _get('predict/signal_strength/heatmap', params) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> getAPDailyTrend(String apName) async =>
      await _get('predict/signal_strength/ap_trend/$apName') as Map<String, dynamic>;

  Future<Map<String, dynamic>> recommendAPs({
    required double lat,
    required double lng,
    int radius = 500,
    String mode = 'balanced',
    String building = '',
    bool preferStable = true,
  }) async =>
      await _post('recommend', {
        'lat': lat, 'lng': lng, 'radius': radius,
        'mode': mode, 'building': building, 'prefer_stable': preferStable,
      }) as Map<String, dynamic>;
}