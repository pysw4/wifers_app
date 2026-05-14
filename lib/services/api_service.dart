import 'package:http/http.dart' as http;
import 'dart:convert';
import 'package:latlong2/latlong.dart';

class ApiService {
  //  backend API base URL (ensure this matches your backend's IP and port)
  static const String baseUrl = 'https://wifers-app.onrender.com';

  Future<List<LatLng>> fetchRoute(double lng, double lat, double destLng, double destLat) async {
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
    final uri = Uri.parse('$baseUrl/route/advanced/$lat/$lng/$destLat/$destLng?acceptable_range=$acceptableRange');
    final response = await http.get(uri);
    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    } else {
      throw Exception('Request failed, status code: ${response.statusCode}');
    }
  }
}

