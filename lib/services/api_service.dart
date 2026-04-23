import 'package:http/http.dart' as http;
import 'dart:convert';
import 'package:wifers_app/models/ap_info.dart';

class ApiService {
  // your backend API base URL (ensure this matches your backend's IP and port)
  static const String baseUrl = 'https://wifers-app.onrender.com';

  /// get candidates from the backend API
  Future<List<ApInfo>> fetchCandidates(double lng, double lat, int radius) async {
    final uri = Uri.parse('$baseUrl/candidates/$lng/$lat/$radius');
    print('正在请求: $uri');
    final response = await http.get(uri);
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      print('后端返回的 candidates 类型: ${data['candidates'].runtimeType}');
      print('前两个元素: ${data['candidates'].take(2).toList()}');
      final candidatesRaw = data['candidates'] as List;
      // get list of candidates from the response
      return candidatesRaw.map((item) => APInfo.fromJson(item)).toList();
    } else {
      throw Exception('Request failed, status code: ${response.statusCode}');
    }
  }
}
