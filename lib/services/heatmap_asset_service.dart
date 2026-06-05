import 'dart:convert';
import 'package:http/http.dart' as http;

/// Service to load pre-computed heatmap data from static files
/// served alongside the Flutter web app (not the API backend).
///
/// This avoids Render free-tier CPU quota exhaustion and cold starts.
/// Files are stored in web/heatmaps/{day}/heatmap_h{hour}.json
/// and served from the same origin as the Flutter web app.
///
/// Features:
/// - **In-memory cache** with TTL for fast re-access within same session
/// - Graceful fallback to API service if static file is not available
class HeatmapAssetService {
  /// In-memory cache: key = 'heatmap_{day}_h{hour}', value = parsed JSON
  static final Map<String, _CachedHeatmap> _memoryCache = {};

  /// Default TTL for cached heatmap data: 5 minutes
  static const Duration _defaultTtl = Duration(minutes: 5);

  /// Maximum number of cached heatmaps in memory
  static const int _maxCacheEntries = 20;

  /// Load heatmap data for a given day and hour from static files.
  ///
  /// Falls back to the API service if the static file is not available.
  static Future<Map<String, dynamic>> loadHeatmap({
    required int hour,
    required String day,
  }) async {
    final effectiveHour = hour < 7
        ? 3
        : hour; // Match backend's NIGHT_REPRESENTATIVE_HOUR
    final cacheKey = 'heatmap_${day}_h$effectiveHour';

    // 1) Check in-memory cache
    final cached = _memoryCache[cacheKey];
    if (cached != null) {
      final age = DateTime.now().difference(cached.timestamp);
      if (age < _defaultTtl) {
        return cached.data;
      }
      // Expired — remove and re-fetch
      _memoryCache.remove(cacheKey);
    }

    // 2) Fetch from static file
    final url = 'heatmaps/$day/heatmap_h$effectiveHour.json';
    try {
      final response = await http.get(Uri.parse(url));
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body) as Map<String, dynamic>;

        // Store in memory cache (with eviction if needed)
        _cacheWithEviction(cacheKey, data);

        return data;
      }
      throw Exception('HTTP ${response.statusCode}');
    } catch (e) {
      throw Exception(
          'Failed to load heatmap from static file: $e');
    }
  }

  /// Pre-warm the cache with heatmap data for common hours.
  /// Call this during app startup to reduce perceived load time.
  static Future<void> prewarm({
    required int currentHour,
    required String day,
  }) async {
    // Pre-warm current hour and adjacent hours
    for (int offset = -1; offset <= 1; offset++) {
      final hour = (currentHour + offset).clamp(0, 23);
      try {
        await loadHeatmap(hour: hour, day: day);
      } catch (_) {
        // Silently ignore pre-warm failures
      }
    }
  }

  /// Clear the in-memory heatmap cache.
  static void clearCache() {
    _memoryCache.clear();
  }

  /// Remove a specific heatmap from the cache.
  static void invalidate({required int hour, required String day}) {
    final effectiveHour = hour < 7 ? 3 : hour;
    final cacheKey = 'heatmap_${day}_h$effectiveHour';
    _memoryCache.remove(cacheKey);
  }

  /// Store data in cache, evicting oldest entries if over limit.
  static void _cacheWithEviction(String key, Map<String, dynamic> data) {
    if (_memoryCache.length >= _maxCacheEntries) {
      // Evict the oldest entry
      String? oldestKey;
      DateTime? oldestTime;
      for (final entry in _memoryCache.entries) {
        if (oldestKey == null ||
            entry.value.timestamp.isBefore(oldestTime!)) {
          oldestKey = entry.key;
          oldestTime = entry.value.timestamp;
        }
      }
      if (oldestKey != null) {
        _memoryCache.remove(oldestKey);
      }
    }

    _memoryCache[key] = _CachedHeatmap(
      data: data,
      timestamp: DateTime.now(),
    );
  }
}

/// Internal cache entry with timestamp for TTL-based expiration.
class _CachedHeatmap {
  final Map<String, dynamic> data;
  final DateTime timestamp;

  _CachedHeatmap({required this.data, required this.timestamp});
}
