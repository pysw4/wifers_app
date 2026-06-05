import 'package:flutter/material.dart';

import 'package:wifers_app/pages/my_home_page.dart';
import 'package:wifers_app/services/cache_service.dart';
import 'package:wifers_app/services/storage_service.dart';

void main() async {
  // Bind Flutter to ensure plugins (SharedPreferences) are available.
  WidgetsFlutterBinding.ensureInitialized();

  // Proactively clean up stale localStorage entries so that
  // SharedPreferences / `map: failed to execute setitem on storage`
  // errors are minimised during normal app usage.
  try {
    await StorageService.startupCleanup();
  } catch (e) {
    debugPrint('main: startupCleanup failed ($e) — continuing');
  }

  // Invalidate persistent caches from an older code version.
  // This ensures the new accuracy_vs_actual data is fetched fresh.
  try {
    await CacheService.init();
  } catch (e) {
    debugPrint('main: CacheService.init failed ($e) — continuing');
  }

  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Wifers - UAB WiFi Map',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.blue),
        bottomNavigationBarTheme: const BottomNavigationBarThemeData(
          backgroundColor: Colors.white,
          selectedItemColor: Colors.blue,
          unselectedItemColor: Colors.black54,
        ),
      ),
      home: const MyHomePage(title: 'Wifers'),
    );
  }
}
