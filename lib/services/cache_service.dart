import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Unified cache service with memory + persistent storage + TTL expiration.
///
/// Provides two layers of caching:
/// 1. **Memory cache** (`Map`): Fast access within the app session
/// 2. **Persistent cache** (`SharedPreferences`): Survives app restarts
///
/// On web, SharedPreferences wraps `localStorage` which has a ~5 MB quota.
/// ALL SharedPreferences access is wrapped in try-catch to prevent
/// `map: failed to execute setitem on storage` errors.
class CacheService {
  /// Bump this on deploy to invalidate ALL persistent caches.
  /// v3: /compare API changed from weekday/weekend → predicted/historical
  static const int cacheVersion = 3;
  static const String _cacheVersionKey = '_cache_service_version';

  /// Call at app startup to wipe stale persistent caches from an older version.
  static Future<void> init() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final stored = prefs.getInt(_cacheVersionKey);
      if (stored != cacheVersion) {
        debugPrint('CacheService: version changed $stored → $cacheVersion, clearing persistent cache');
        await clearAll();
        await prefs.setInt(_cacheVersionKey, cacheVersion);
      }
    } catch (e) {
      debugPrint('CacheService.init: $e');
    }
  }

  // Memory cache
  static final Map<String, _CacheEntry> _memoryCache = {};

  // Persistent cache keys
  static const String _persistPrefix = 'cache_';
  static const String _persistTimePrefix = 'cache_time_';

  // ---------------------------------------------------------------------------
  // Limits to prevent localStorage quota errors
  // ---------------------------------------------------------------------------

  /// Maximum number of persistent cache entries.  If exceeded, the oldest
  /// entries are evicted during the next write.
  static const int _maxPersistentEntries = 50;

  /// Maximum serialized size of a single cache value.  Values larger than
  /// this are only stored in memory, never persisted to localStorage.
  static const int _maxValueSizeBytes = 50 * 1024; // 50 KB

  /// Get a cached value.
  ///
  /// Checks memory cache first, then persistent cache.
  /// Returns `null` if not found or expired.
  /// Never throws – returns `null` on any error.
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
    try {
      final prefs = await SharedPreferences.getInstance();
      final stored = prefs.getString('$_persistPrefix$key');
      final storedTime = prefs.getString('$_persistTimePrefix$key');

      if (stored != null && storedTime != null) {
        final savedTime = DateTime.tryParse(storedTime);
        if (savedTime != null) {
          if (ttl == null || now.difference(savedTime) < ttl) {
            final decoded = jsonDecode(stored) as T;
            _memoryCache[key] = _CacheEntry(value: decoded, timestamp: now);
            return decoded;
          }
          // Expired, clean up
          await _removePersistent(key, prefs);
        }
      }
    } catch (e) {
      debugPrint('CacheService.get: persistent read failed for key "$key": $e');
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

    // Persistent cache – only for JSON-serializable types under size limit
    if (value is String || value is num || value is bool || value is List || value is Map) {
      try {
        final encoded = jsonEncode(value);
        // Skip persistence for large values to avoid localStorage quota errors
        if (encoded.length > _maxValueSizeBytes) {
          debugPrint('CacheService.set: value too large ($encoded bytes), skipping persist for "$key"');
          return;
        }

        final prefs = await SharedPreferences.getInstance();

        // Enforce max entry count by removing oldest entries
        await _enforceMaxEntries(prefs);

        await prefs.setString('$_persistPrefix$key', encoded);
        await prefs.setString('$_persistTimePrefix$key', now.toIso8601String());
      } catch (e) {
        // localStorage quota exceeded or unavailable — persist silently skipped.
        debugPrint('CacheService.set: persistent write failed for "$key": $e');

        // Auto-cleanup: try to free space by removing expired entries
        try {
          await clearExpired();
          final prefs = await SharedPreferences.getInstance();
          await prefs.setString('$_persistPrefix$key', jsonEncode(value));
          await prefs.setString('$_persistTimePrefix$key', now.toIso8601String());
        } catch (_) {
          // Give up — the value is still available from the in-memory cache.
        }
      }
    }
  }

  /// Remove a specific cache entry.
  static Future<void> remove(String key) async {
    _memoryCache.remove(key);
    try {
      final prefs = await SharedPreferences.getInstance();
      await _removePersistent(key, prefs);
    } catch (e) {
      debugPrint('CacheService.remove: failed for "$key": $e');
    }
  }

  /// Clear all cached data.
  static Future<void> clearAll() async {
    _memoryCache.clear();
    try {
      final prefs = await SharedPreferences.getInstance();
      final keys = prefs.getKeys().where((k) => k.startsWith(_persistPrefix));
      for (final key in keys) {
        try {
          await prefs.remove(key);
        } catch (_) {}
      }
    } catch (e) {
      debugPrint('CacheService.clearAll: failed: $e');
    }
  }

  /// Clear only expired cache entries.
  static Future<void> clearExpired({Duration? defaultTtl}) async {
    final now = DateTime.now();
    final ttl = defaultTtl ?? const Duration(hours: 1);

    // Clear expired memory entries
    _memoryCache.removeWhere((_, entry) => now.difference(entry.timestamp) >= ttl);

    // Clear expired persistent entries
    try {
      final prefs = await SharedPreferences.getInstance();
      final timeKeys = prefs.getKeys().where((k) => k.startsWith(_persistTimePrefix));
      for (final timeKey in timeKeys) {
        try {
          final storedTime = prefs.getString(timeKey);
          if (storedTime != null) {
            final savedTime = DateTime.tryParse(storedTime);
            if (savedTime != null && now.difference(savedTime) >= ttl) {
              final cacheKey = timeKey.replaceFirst(_persistTimePrefix, '');
              await _removePersistent(cacheKey, prefs);
            }
          }
        } catch (_) {}
      }
    } catch (e) {
      debugPrint('CacheService.clearExpired: failed: $e');
    }
  }

  /// Check if a cache entry exists and is valid.
  static Future<bool> has(String key, {Duration? ttl}) async {
    try {
      final value = await get(key, ttl: ttl);
      return value != null;
    } catch (_) {
      return false;
    }
  }

  /// Get cache statistics.  Never throws.
  static Future<Map<String, dynamic>> stats() async {
    final entries = <String, dynamic>{};
    int persistentCount = 0;

    try {
      final prefs = await SharedPreferences.getInstance();
      final now = DateTime.now();
      final timeKeys = prefs.getKeys().where((k) => k.startsWith(_persistTimePrefix));
      persistentCount = timeKeys.length;

      for (final timeKey in timeKeys) {
        try {
          final storedTime = prefs.getString(timeKey);
          if (storedTime != null) {
            final savedTime = DateTime.tryParse(storedTime);
            final cacheKey = timeKey.replaceFirst(_persistTimePrefix, '');
            entries[cacheKey] = {
              'age_seconds':
                  savedTime != null ? now.difference(savedTime).inSeconds : null,
              'in_memory': _memoryCache.containsKey(cacheKey),
            };
          }
        } catch (_) {}
      }
    } catch (e) {
      debugPrint('CacheService.stats: failed: $e');
    }

    return {
      'memory_entries': _memoryCache.length,
      'persistent_entries': persistentCount,
      'entries': entries,
    };
  }

  static Future<void> _removePersistent(String key, SharedPreferences prefs) async {
    await prefs.remove('$_persistPrefix$key');
    await prefs.remove('$_persistTimePrefix$key');
  }

  /// Enforce the maximum number of persistent cache entries by removing
  /// the oldest entries when the limit is exceeded.
  static Future<void> _enforceMaxEntries(SharedPreferences prefs) async {
    try {
      final timeKeys = prefs
          .getKeys()
          .where((k) => k.startsWith(_persistTimePrefix))
          .toList();

      if (timeKeys.length >= _maxPersistentEntries) {
        // Sort by timestamp ascending (oldest first)
        timeKeys.sort((a, b) {
          final ta = DateTime.tryParse(prefs.getString(a) ?? '');
          final tb = DateTime.tryParse(prefs.getString(b) ?? '');
          if (ta == null && tb == null) return 0;
          if (ta == null) return -1;
          if (tb == null) return 1;
          return ta.compareTo(tb);
        });

        // Remove the oldest entries until we're under the limit
        final toRemove =
            timeKeys.length - _maxPersistentEntries + 5; // remove extra for headroom
        for (int i = 0; i < toRemove && i < timeKeys.length; i++) {
          final cacheKey = timeKeys[i].replaceFirst(_persistTimePrefix, '');
          await prefs.remove('$_persistPrefix$cacheKey');
          await prefs.remove(timeKeys[i]);
        }
        debugPrint('CacheService._enforceMaxEntries: removed $toRemove oldest entries');
      }
    } catch (e) {
      debugPrint('CacheService._enforceMaxEntries: failed: $e');
    }
  }
}

class _CacheEntry {
  final dynamic value;
  final DateTime timestamp;

  _CacheEntry({required this.value, required this.timestamp});
}
