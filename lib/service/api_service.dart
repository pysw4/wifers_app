import 'package:http/http.dart' as http;
import 'dart:convert';

class ApiService {
  // your backend API base URL (ensure this matches your backend's IP and port)
  static const String baseUrl = 'http://192.168.1.214:8000';

  /// get candidates from the backend API
  Future<List<int>> fetchCandidates(double lng, double lat, int radius) async {
    final uri = Uri.parse('$baseUrl/candidates/$lng/$lat/$radius');
    print('正在请求: $uri');
    final response = await http.get(uri);
    
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      // get list of candidates from the response
      return List<int>.from(data['candidates']);
    } else {
      throw Exception('Request failed, status code: ${response.statusCode}');
    }
  }
}