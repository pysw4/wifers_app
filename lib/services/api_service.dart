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
  static const Duration _timeout = Duration(seconds: 30);

  /// Friendly user-facing message for common HTTP errors.
  static String friendlyErrorMessage(dynamic error) {
    final msg = error.toString();
    if (msg.contains('502') || msg.contains('Bad Gateway')) {
      return '服务器暂时不可用，请稍后重试 ⏳';
    }
    if (msg.contains('timeout') || msg.contains('TimedOut')) {
      return '请求超时，请检查网络连接 ⌛';
    }
    if (msg.contains('Connection refused')) {
      return '无法连接服务器，请稍后重试 🔌';
    }
    if (msg.contains('No address')) {
      return '无法解析服务器地址，请检查网络连接 🌐';
    }
    return msg;
  }

  Future<dynamic> _get(String path, [Map<String, String>? params]) async {
    final uri = Uri.parse('$baseUrl/$path').replace(queryParameters: params);
    final response = await http.get(uri).timeout(_timeout);
    if (response.statusCode == 200) return jsonDecode(response.body);
    if (response.statusCode == 422) {
      final detail = jsonDecode(response.body);
      throw ApiException(
        422,
        detail['detail'] ?? 'Input validation failed',
        details: detail,
      );
    }
    throw ApiException(response.statusCode, '${response.statusCode} $path');
  }

  Future<dynamic> _post(String path, Map<String, dynamic> body) async {
    final response = await http.post(
      Uri.parse('$baseUrl/$path'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode(body),
    ).timeout(_timeout);
    if (response.statusCode == 200) return jsonDecode(response.body);
    if (response.statusCode == 422) {
      final detail = jsonDecode(response.body);
      throw ApiException(
        422,
        detail['detail'] ?? 'Input validation failed',
        details: detail,
      );
    }
    throw ApiException(response.statusCode, '${response.statusCode} $path');
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

  /// Get weekday vs weekend comparison for AP signal strength trend
  Future<Map<String, dynamic>> getAPTrendCompare(String apName) async =>
      await _get('predict/signal_strength/ap_trend/$apName/compare') as Map<String, dynamic>;

  /// Submit user feedback on prediction accuracy
  Future<Map<String, dynamic>> submitPredictionFeedback({
    required String apName,
    required int hour,
    required String predicted,
    required String actual,
  }) async =>
      await _post('predict/feedback', {
        'ap_name': apName,
        'hour': hour,
        'predicted': predicted,
        'actual': actual,
      }) as Map<String, dynamic>;

  /// Get prediction accuracy statistics for a specific AP
  Future<Map<String, dynamic>> getPredictionStats(String apName) async =>
      await _get('predict/stats/$apName') as Map<String, dynamic>;

  /// Get detailed prediction vs actual signal accuracy for a specific AP
  Future<Map<String, dynamic>> getAPSignalAccuracy(String apName) async =>
      await _get('predict/signal_strength/accuracy/$apName') as Map<String, dynamic>;

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

  // --- Booking API methods ---

  /// Get room info (AP name, building, floor) for a room code
  Future<Map<String, dynamic>> getRoomInfo(String roomCode) async =>
      await _get('booking/room-info/${Uri.encodeComponent(roomCode)}') as Map<String, dynamic>;

  /// Get hourly availability for a room on a given date
  Future<Map<String, dynamic>> getBookingAvailability(String roomCode, String date) async =>
      await _get('booking/availability/${Uri.encodeComponent(roomCode)}/$date') as Map<String, dynamic>;

  /// Predict performance for a room/time slot without creating a booking
  Future<Map<String, dynamic>> predictBooking({
    String? roomCode,
    required String date,
    required int startHour,
    required int endHour,
    required int nStudents,
  }) async =>
      await _post('booking/predict', {
        'room_code': roomCode,
        'date': date,
        'start_hour': startHour,
        'end_hour': endHour,
        'n_students': nStudents,
      }) as Map<String, dynamic>;

  /// Create a new booking
  Future<Map<String, dynamic>> createBooking({
    String? teacherId,
    String? roomCode,
    required String date,
    required int startHour,
    required int endHour,
    required int nStudents,
    required String minPerformance,
  }) async =>
      await _post('booking/create', {
        'teacher_id': teacherId,
        'room_code': roomCode,
        'date': date,
        'start_hour': startHour,
        'end_hour': endHour,
        'n_students': nStudents,
        'min_performance': minPerformance,
      }) as Map<String, dynamic>;

  /// Cancel a booking by ID
  Future<Map<String, dynamic>> cancelBooking(String bookingId) async =>
      await _post('booking/cancel', {'booking_id': bookingId}) as Map<String, dynamic>;

  /// List bookings with optional filters
  Future<Map<String, dynamic>> listBookings({
    String? teacherId,
    String? roomCode,
    String? date,
  }) async {
    final params = <String, String>{};
    if (teacherId != null) params['teacher_id'] = teacherId;
    if (roomCode != null) params['room_code'] = roomCode;
    if (date != null) params['date'] = date;
    return await _get('booking/list', params) as Map<String, dynamic>;
  }

  /// Suggest the best available time slot
  Future<Map<String, dynamic>> suggestBestSlot({
    required String roomCode,
    required String date,
    required int durationHours,
    required int nStudents,
  }) async =>
      await _post('booking/suggest-slot', {
        'room_code': roomCode,
        'date': date,
        'duration_hours': durationHours,
        'n_students': nStudents,
      }) as Map<String, dynamic>;

  /// Find alternative rooms on the same floor
  Future<Map<String, dynamic>> findAlternatives({
    required String roomCode,
    required String date,
    required int startHour,
    required int endHour,
    required int nStudents,
    required String minPerformance,
  }) async =>
      await _post('booking/alternatives', {
        'room_code': roomCode,
        'date': date,
        'start_hour': startHour,
        'end_hour': endHour,
        'n_students': nStudents,
        'min_performance': minPerformance,
      }) as Map<String, dynamic>;
}
