import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../models/ap_info.dart';
import 'cache_service.dart';

/// Persistent storage service using SharedPreferences.
///
/// On web, SharedPreferences wraps `localStorage` which has a ~5 MB quota.
/// ALL methods that access SharedPreferences are wrapped in try-catch to
/// prevent `map: failed to execute setitem on storage` / `getItem` errors
/// when the quota is exceeded or localStorage is inaccessible.
class StorageService {
  static const String _favoritesKey = 'favorite_aps';
  static const String _settingsKey = 'app_settings';

  // ---------------------------------------------------------------------------
  // Favorites
  // ---------------------------------------------------------------------------

  /// Save favorites list.
  ///
  /// If storage fails (e.g. quota exceeded), clears cache and retries with a
  /// trimmed list (max 50 items).
  static Future<void> saveFavorites(List<APInfo> favorites) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final List<Map<String, dynamic>> jsonList =
          favorites.map((ap) => ap.toJson()).toList();
      final String encoded = jsonEncode(jsonList);

      // Proactively truncate very large data
      if (encoded.length > 100_000 && favorites.length > 50) {
        final trimmed = favorites.sublist(0, 50);
        await prefs.setString(
            _favoritesKey, jsonEncode(trimmed.map((ap) => ap.toJson()).toList()));
        return;
      }

      await prefs.setString(_favoritesKey, encoded);
    } catch (e) {
      debugPrint('StorageService.saveFavorites: failed ($e)');
      try {
        await clearCache();
        final trimmed =
            favorites.length > 50 ? favorites.sublist(0, 50) : favorites;
        final prefs = await SharedPreferences.getInstance();
        await prefs.setString(
            _favoritesKey, jsonEncode(trimmed.map((ap) => ap.toJson()).toList()));
      } catch (_) {
        debugPrint('StorageService.saveFavorites: still failed after cleanup');
      }
    }
  }

  /// Load favorites list.  Returns empty list on failure.
  static Future<List<APInfo>> loadFavorites() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final String? encoded = prefs.getString(_favoritesKey);
      if (encoded == null || encoded.isEmpty) return [];
      final List<dynamic> decoded = jsonDecode(encoded);
      return decoded
          .map((item) => APInfo.fromJson(item as Map<String, dynamic>))
          .toList();
    } catch (e) {
      debugPrint('StorageService.loadFavorites: failed ($e)');
      return [];
    }
  }

  /// Add single favorite (with deduplication).
  static Future<void> addFavorite(APInfo ap) async {
    try {
      final favorites = await loadFavorites();
      if (!favorites.any((item) => item.uniqueKey == ap.uniqueKey)) {
        favorites.add(ap);
        await saveFavorites(favorites);
      }
    } catch (e) {
      debugPrint('StorageService.addFavorite: failed ($e)');
    }
  }

  /// Remove a single favorite.
  static Future<void> removeFavorite(APInfo ap) async {
    try {
      final favorites = await loadFavorites();
      favorites.removeWhere((item) => item.uniqueKey == ap.uniqueKey);
      await saveFavorites(favorites);
    } catch (e) {
      debugPrint('StorageService.removeFavorite: failed ($e)');
    }
  }

  /// Clear all favorites.
  static Future<void> clearFavorites() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.remove(_favoritesKey);
    } catch (e) {
      debugPrint('StorageService.clearFavorites: failed ($e)');
    }
  }

  // ---------------------------------------------------------------------------
  // Settings
  // ---------------------------------------------------------------------------

  /// Save settings.  Silently catches localStorage errors.
  static Future<void> saveSettings(Map<String, dynamic> settings) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_settingsKey, jsonEncode(settings));
    } catch (e) {
      debugPrint('StorageService.saveSettings: failed ($e)');
    }
  }

  /// Load settings.  Returns defaults on failure.
  static Future<Map<String, dynamic>> loadSettings() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final String? encoded = prefs.getString(_settingsKey);
      if (encoded == null || encoded.isEmpty) return _defaultSettings();
      return jsonDecode(encoded) as Map<String, dynamic>;
    } catch (e) {
      debugPrint('StorageService.loadSettings: failed ($e)');
      return _defaultSettings();
    }
  }

  static Map<String, dynamic> _defaultSettings() {
    return {
      'notificationsEnabled': true,
      'cachePredictions': true,
      'cacheDurationMinutes': 60,
      'lowPowerLocation': true,
      'preferStableAps': true,
      'recommendRadiusMeters': 500,
      'recommendMode': 'balanced',
    };
  }

  // ---------------------------------------------------------------------------
  // Cache & Cleanup
  // ---------------------------------------------------------------------------

  /// Clear all cached data (both StorageService and CacheService).
  static Future<void> clearCache() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      for (final key in [
        'ap_cache',
        'ap_cache_time',
        'cached_lat',
        'cached_lng',
        'recommend_cache',
        'recommend_cache_time',
        'recommend_params',
      ]) {
        try {
          await prefs.remove(key);
        } catch (_) {
          // ignore per-key failures
        }
      }
    } catch (e) {
      debugPrint('StorageService.clearCache: failed ($e)');
    }
    try {
      await CacheService.clearAll();
    } catch (_) {}
  }

  /// Reset settings to defaults.
  static Future<void> resetSettings() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.remove(_settingsKey);
    } catch (e) {
      debugPrint('StorageService.resetSettings: failed ($e)');
    }
  }

  /// Proactively clean up stale cache entries to prevent localStorage quota
  /// errors.  Call this early in the app lifecycle (e.g. from main()).
  static Future<void> startupCleanup() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final now = DateTime.now();
      int removed = 0;

      // 1. Remove cache entries older than 24 hours
      for (final key in prefs.getKeys()) {
        if (key.startsWith('cache_time_')) {
          final timeStr = prefs.getString(key);
          if (timeStr != null) {
            final time = DateTime.tryParse(timeStr);
            if (time != null && now.difference(time).inHours > 24) {
              final cacheKey = key.replaceFirst('cache_time_', '');
              await prefs.remove('cache_$cacheKey');
              await prefs.remove(key);
              removed++;
            }
          }
        }
      }

      // 2. Remove favorites if they're extremely bloated (>500 KB)
      final fav = prefs.getString(_favoritesKey);
      if (fav != null && fav.length > 500_000) {
        debugPrint('StorageService.startupCleanup: clearing bloated favorites');
        await prefs.remove(_favoritesKey);
      }

      // 3. Remove old legacy cache keys
      for (final legacy in ['ap_cache_time', 'recommend_cache_time']) {
        await prefs.remove(legacy);
      }

      debugPrint('StorageService.startupCleanup: removed $removed expired entries');
    } catch (e) {
      debugPrint('StorageService.startupCleanup: failed ($e)');
    }
  }
}
