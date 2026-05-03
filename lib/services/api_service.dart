import 'package:http/http.dart' as http;
import 'dart:convert';
import 'package:wifers_app/models/ap_info.dart';

class ApiService {
  // your backend API base URL (ensure this matches your backend's IP and port)
  static const String baseUrl = 'https://wifers-app.onrender.com';

  /// get candidates from the backend API
  Future<List<APInfo>> fetchCandidates(double lng, double lat, int radius) async {
    final uri = Uri.parse('$baseUrl/candidates/$lng/$lat/$radius');
    print('requesting: $uri');
    final response = await http.get(uri);
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      final candidatesRaw = data['candidates'] as List;
      // get list of candidates from the response
      return candidatesRaw.map((item) => APInfo.fromJson(item)).toList();
    } else {
      throw Exception('Request failed, status code: ${response.statusCode}');
    }
  }
  Future<List<double>> fetchRecommend(double lng, double lat, int radius) async {
    final uri = Uri.parse('$baseUrl/recommend/$lat/$lng/$radius');
    print('requesting: $uri');
    final response = await http.get(uri);
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      final recommendList = data['recommend'] as List;
      return recommendList.map((e) => (e as num).toDouble()).toList();
    } else {
      throw Exception('Request failed, status code: ${response.statusCode}');
    }
  }
}
