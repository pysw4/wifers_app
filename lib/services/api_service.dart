import 'package:http/http.dart' as http;
import 'dart:convert';
import 'package:latlong2/latlong.dart';

class ApiService {
  // Backend API base URL (update this after deploying the API service)
  static const String baseUrl = 'https://wifers-app-api.onrender.com';

  Future<List<LatLng>> fetchRoute(double lng, double lat, double destLng, double destLat) async {
    // Backend expects: /route/{lat}/{lng}/{dest_lat}/{dest_lng}
    final uri = Uri.parse('$baseUrl/route/$lat/$lng/$destLat/$destLng');
    final response = await http.get(uri);
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      final path = data['path'] as List<dynamic>;
      return path.map<LatLng>((item) {
        final map = item as Map<String, dynamic>;
        final lat = map['lat'];
        final lng = map['lng'];
        return LatLng((lat as num).toDouble(), (lng as num).toDouble());
      }).toList();
    } else {
      throw Exception('Request failed, status code: ${response.statusCode}');
    }
  }

  Future<Map<String, dynamic>> predictAPStatus(Map<String, dynamic> features) async {
    final uri = Uri.parse('$baseUrl/predict');
    final response = await http.post(
      uri,
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode(features),
    );
    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    } else {
      throw Exception('Request failed, status code: ${response.statusCode}');
    }
  }

  Future<Map<String, dynamic>> predictAPStatusBatch(List<Map<String, dynamic>> items) async {
    final uri = Uri.parse('$baseUrl/predict/batch');
    final response = await http.post(
      uri,
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode(items),
    );
    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    } else {
      throw Exception('Request failed, status code: ${response.statusCode}');
    }
  }

  /// Advanced route with alternatives using find_paths_to_candidates
  /// Returns best path and alternative routes within acceptable range
  Future<Map<String, dynamic>> fetchAdvancedRoute(
    double lng,
    double lat,
    double destLng,
    double destLat, {
    int acceptableRange = 500,
  }) async {
    // Backend expects: /route/advanced/{lat}/{lng}/{dest_lat}/{dest_lng}
    final uri = Uri.parse('$baseUrl/route/advanced/$lat/$lng/$destLat/$destLng?acceptable_range=$acceptableRange');
    final response = await http.get(uri);
    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    } else {
      throw Exception('Request failed, status code: ${response.statusCode}');
    }
  }

  /// Get signal strength heatmap data for ALL APs across campus
  /// Returns merged data with both AP points and smooth grid.
  /// Parameters:
  ///   [hour] - hour of day (0-23, default: current hour)
  Future<Map<String, dynamic>> getSignalHeatmap({int? hour}) async {
    final params = <String, String>{};
    if (hour != null) {
      params['hour'] = hour.toString();
    }
    final uri = Uri.parse('$baseUrl/predict/signal_strength/heatmap').replace(queryParameters: params);
    final response = await http.get(uri);
    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    } else {
      throw Exception('Request failed, status code: ${response.statusCode}');
    }
  }

  /// Get 24-hour signal strength trend for a specific AP.
  /// Returns hourly data points with signal_db, signal_quality, and bars.
  Future<Map<String, dynamic>> getAPDailyTrend(String apName) async {
    final uri = Uri.parse('$baseUrl/predict/signal_strength/ap_trend/$apName');
    final response = await http.get(uri);
    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    } else {
      throw Exception('Request failed, status code: ${response.statusCode}');
    }
  }
}

