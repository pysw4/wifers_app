import 'dart:convert';
import 'package:http/http.dart' as http;

/// Service to load pre-computed heatmap data from static files
/// served alongside the Flutter web app (not the API backend).
///
/// This avoids Render free-tier CPU quota exhaustion and cold starts.
/// Files are stored in web/heatmaps/{day}/heatmap_h{hour}.json
/// and served from the same origin as the Flutter web app.
class HeatmapAssetService {
  /// Base URL for heatmap static files.
  /// Uses the same host as the Flutter web app itself (relative path).
  static String get _baseUrl {
    // Use relative path so it works in both development and production
    // (same origin as the Flutter web app)
    return '';
  }

  /// Load heatmap data for a given day and hour from static files.
  ///
  /// Falls back to the API service if the static file is not available.
  static Future<Map<String, dynamic>> loadHeatmap({
    required int hour,
    required String day,
  }) async {
    final effectiveHour = hour < 7 ? 3 : hour; // Match backend's NIGHT_REPRESENTATIVE_HOUR
    final url = '/heatmaps/$day/heatmap_h$effectiveHour.json';

    try {
      final response = await http.get(Uri.parse(url));
      if (response.statusCode == 200) {
        return jsonDecode(response.body) as Map<String, dynamic>;
      }
      throw Exception('HTTP ${response.statusCode}');
    } catch (e) {
      throw Exception('Failed to load heatmap from static file: $e');
    }
  }
}
