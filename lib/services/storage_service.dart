import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';
import '../models/ap_info.dart';

class StorageService {
  static const String _favoritesKey = 'favorite_aps';

  // 保存收藏列表
  static Future<void> saveFavorites(List<APInfo> favorites) async {
    final prefs = await SharedPreferences.getInstance();
    final List<Map<String, dynamic>> jsonList = favorites.map((ap) => ap.toJson()).toList();
    final String encoded = jsonEncode(jsonList);
    await prefs.setString(_favoritesKey, encoded);
  }

  // 读取收藏列表
  static Future<List<APInfo>> loadFavorites() async {
    final prefs = await SharedPreferences.getInstance();
    final String? encoded = prefs.getString(_favoritesKey);
    if (encoded == null) return [];
    final List<dynamic> decoded = jsonDecode(encoded);
    return decoded.map((item) => APInfo.fromJson(item as Map<String, dynamic>)).toList();
  }

  // 添加单个收藏（可去重）
  static Future<void> addFavorite(APInfo ap) async {
    final favorites = await loadFavorites();
    // 根据 uniqueKey 去重
    if (!favorites.any((item) => item.uniqueKey == ap.uniqueKey)) {
      favorites.add(ap);
      await saveFavorites(favorites);
    }
  }

  // 删除单个收藏
  static Future<void> removeFavorite(APInfo ap) async {
    final favorites = await loadFavorites();
    favorites.removeWhere((item) => item.uniqueKey == ap.uniqueKey);
    await saveFavorites(favorites);
  }

  // 清空收藏
  static Future<void> clearFavorites() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_favoritesKey);
  }
}