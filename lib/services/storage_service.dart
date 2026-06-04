import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../models/ap_info.dart';
import 'cache_service.dart';

class StorageService {
  static const String _favoritesKey = 'favorite_aps';
  static const String _settingsKey = 'app_settings';

  // Save favorites list
  static Future<void> saveFavorites(List<APInfo> favorites) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final List<Map<String, dynamic>> jsonList = favorites.map((ap) => ap.toJson()).toList();
      final String encoded = jsonEncode(jsonList);
      await prefs.setString(_favoritesKey, encoded);
    } catch (_) {
      debugPrint('StorageService.saveFavorites: failed to save');
    }
  }

  // Load favorites list
  static Future<List<APInfo>> loadFavorites() async {
    final prefs = await SharedPreferences.getInstance();
    final String? encoded = prefs.getString(_favoritesKey);
    if (encoded == null) return [];
    final List<dynamic> decoded = jsonDecode(encoded);
    return decoded.map((item) => APInfo.fromJson(item as Map<String, dynamic>)).toList();
  }

  // Add single favorite (with deduplication)
  static Future<void> addFavorite(APInfo ap) async {
    final favorites = await loadFavorites();
    // Deduplicate by uniqueKey
    if (!favorites.any((item) => item.uniqueKey == ap.uniqueKey)) {
      favorites.add(ap);
      await saveFavorites(favorites);
    }
  }

  // Remove a single favorite
  static Future<void> removeFavorite(APInfo ap) async {
    final favorites = await loadFavorites();
    favorites.removeWhere((item) => item.uniqueKey == ap.uniqueKey);
    await saveFavorites(favorites);
  }

  // Clear all favorites
  static Future<void> clearFavorites() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_favoritesKey);
  }

  // Save settings
  static Future<void> saveSettings(Map<String, dynamic> settings) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final String encoded = jsonEncode(settings);
      await prefs.setString(_settingsKey, encoded);
    } catch (_) {
      debugPrint('StorageService.saveSettings: failed to save');
    }
  }

  // Load settings
  static Future<Map<String, dynamic>> loadSettings() async {
    final prefs = await SharedPreferences.getInstance();
    final String? encoded = prefs.getString(_settingsKey);
    if (encoded == null) {
      // Default settings
      return {
        'notificationsEnabled': true,
        'cachePredictions': true,
        'cacheDurationMinutes': 60,
        'lowPowerLocation': true,
        'preferStableAps': true,
        'recommendRadiusMeters': 500,
        'recommendMode': 'balanced', // "distance", "signal", or "balanced"
      };
    }
    return jsonDecode(encoded) as Map<String, dynamic>;
  }

  static Future<void> clearCache() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('ap_cache');
    await prefs.remove('ap_cache_time');
    await prefs.remove('cached_lat');
    await prefs.remove('cached_lng');
    await prefs.remove('recommend_cache');
    await prefs.remove('recommend_cache_time');
    await prefs.remove('recommend_params');
    // Also clear the new CacheService
    await CacheService.clearAll();
  }

  static Future<void> resetSettings() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_settingsKey);
  }
}