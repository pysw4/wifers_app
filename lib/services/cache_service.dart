import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Unified cache service with memory + persistent storage + TTL expiration.
///
/// Provides two layers of caching:
/// 1. **Memory cache** (`Map`): Fast access within the app session
/// 2. **Persistent cache** (`SharedPreferences`): Survives app restarts
///
/// Cache entries automatically expire based on configurable TTL.
class CacheService {
  // Memory cache
  static final Map<String, _CacheEntry> _memoryCache = {};

  // Persistent cache keys
  static const String _persistPrefix = 'cache_';
  static const String _persistTimePrefix = 'cache_time_';

  /// Get a cached value.
  ///
  /// Checks memory cache first, then persistent cache.
  /// Returns `null` if not found or expired.
  static Future<T?> get<T>(String key, {Duration? ttl}) async {
    final now = DateTime.now();

    // 1. Check memory cache
    final memEntry = _memoryCache[key];
    if (memEntry != null) {
      if (ttl == null || now.difference(memEntry.timestamp) < ttl) {
        return memEntry.value as T;
      }
      // Expired from memory
      _memoryCache.remove(key);
    }

    // 2. Check persistent cache
    final prefs = await SharedPreferences.getInstance();
    final stored = prefs.getString('$_persistPrefix$key');
    final storedTime = prefs.getString('$_persistTimePrefix$key');

    if (stored != null && storedTime != null) {
      final savedTime = DateTime.tryParse(storedTime);
      if (savedTime != null) {
        if (ttl == null || now.difference(savedTime) < ttl) {
          // Restore to memory cache
          final decoded = jsonDecode(stored) as T;
          _memoryCache[key] = _CacheEntry(value: decoded, timestamp: now);
          return decoded;
        }
        // Expired, clean up
        await _removePersistent(key, prefs);
      }
    }

    return null;
  }

  /// Set a cached value (both memory and persistent).
  ///
  /// If persistent storage (e.g. localStorage on web) fails — for instance
  /// because the quota is exceeded — the error is silently caught and the
  /// value remains available in the in-memory cache for the current session.
  static Future<void> set<T>(String key, T value) async {
    final now = DateTime.now();

    // Memory cache (always succeeds)
    _memoryCache[key] = _CacheEntry(value: value, timestamp: now);

    // Persistent cache (only for JSON-serializable types)
    // May fail on web when localStorage quota is exceeded.
    if (value is String || value is num || value is bool || value is List || value is Map) {
      try {
        final prefs = await SharedPreferences.getInstance();
        await prefs.setString('$_persistPrefix$key', jsonEncode(value));
        await prefs.setString('$_persistTimePrefix$key', now.toIso8601String());
      } catch (_) {
        // localStorage quota exceeded or unavailable — persist silently skipped.
        // The value is still available from the in-memory cache.
        debugPrint('CacheService.set: persistent storage write failed for key "$key"');
      }
    }
  }

  /// Remove a specific cache entry.
  static Future<void> remove(String key) async {
    _memoryCache.remove(key);
    final prefs = await SharedPreferences.getInstance();
    await _removePersistent(key, prefs);
  }

  /// Clear all cached data.
  static Future<void> clearAll() async {
    _memoryCache.clear();
    final prefs = await SharedPreferences.getInstance();
    final keys = prefs.getKeys().where((k) => k.startsWith(_persistPrefix));
    for (final key in keys) {
      await prefs.remove(key);
    }
  }

  /// Clear only expired cache entries.
  static Future<void> clearExpired({Duration? defaultTtl}) async {
    final now = DateTime.now();
    final ttl = defaultTtl ?? const Duration(hours: 1);

    // Clear expired memory entries
    _memoryCache.removeWhere((_, entry) => now.difference(entry.timestamp) >= ttl);

    // Clear expired persistent entries
    final prefs = await SharedPreferences.getInstance();
    final timeKeys = prefs.getKeys().where((k) => k.startsWith(_persistTimePrefix));
    for (final timeKey in timeKeys) {
      final storedTime = prefs.getString(timeKey);
      if (storedTime != null) {
        final savedTime = DateTime.tryParse(storedTime);
        if (savedTime != null && now.difference(savedTime) >= ttl) {
          final cacheKey = timeKey.replaceFirst(_persistTimePrefix, '');
          await _removePersistent(cacheKey, prefs);
        }
      }
    }
  }

  /// Check if a cache entry exists and is valid.
  static Future<bool> has(String key, {Duration? ttl}) async {
    final value = await get(key, ttl: ttl);
    return value != null;
  }

  /// Get cache statistics.
  static Future<Map<String, dynamic>> stats() async {
    final prefs = await SharedPreferences.getInstance();
    final timeKeys = prefs.getKeys().where((k) => k.startsWith(_persistTimePrefix));
    final now = DateTime.now();

    final entries = <String, dynamic>{};
    for (final timeKey in timeKeys) {
      final storedTime = prefs.getString(timeKey);
      if (storedTime != null) {
        final savedTime = DateTime.tryParse(storedTime);
        final cacheKey = timeKey.replaceFirst(_persistTimePrefix, '');
        entries[cacheKey] = {
          'age_seconds': savedTime != null ? now.difference(savedTime).inSeconds : null,
          'in_memory': _memoryCache.containsKey(cacheKey),
        };
      }
    }

    return {
      'memory_entries': _memoryCache.length,
      'persistent_entries': timeKeys.length,
      'entries': entries,
    };
  }

  static Future<void> _removePersistent(String key, SharedPreferences prefs) async {
    await prefs.remove('$_persistPrefix$key');
    await prefs.remove('$_persistTimePrefix$key');
  }
}

class _CacheEntry {
  final dynamic value;
  final DateTime timestamp;

  _CacheEntry({required this.value, required this.timestamp});
}
