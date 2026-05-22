import 'package:flutter/material.dart';
import 'package:wifers_app/pages/map_page.dart';
import 'package:wifers_app/pages/recommend_page.dart';
import 'package:wifers_app/pages/setting_page.dart';
import 'package:wifers_app/pages/favorites_page.dart';

class MyHomePage extends StatefulWidget {
  const MyHomePage({super.key, required this.title});

  final String title;

  @override
  State<MyHomePage> createState() => _MyHomePageState();
}

class _MyHomePageState extends State<MyHomePage> {
  int currentIndex = 0;

  // Global keys to access child states
  final _recommendPageKey = GlobalKey<RecommendPageState>();
  final _settingPageKey = GlobalKey<SettingPageState>();

  // Page title list
  static const List<String> _titles = [
    'Map',
    'Favorites',
    'Recommend',
    'Settings',
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        backgroundColor: Theme.of(context).colorScheme.inversePrimary,
        title: Text(_titles[currentIndex]),
        actions: [
          if (currentIndex == 0)
            IconButton(
              icon: const Icon(Icons.favorite),
              tooltip: 'Favorites',
              onPressed: () {
                Navigator.push(
                  context,
                  MaterialPageRoute(builder: (context) => const FavoritesPage()),
                );
              },
            ),
        ],
      ),
      body: IndexedStack(
        index: currentIndex,
        children: [
          const MapPage(),
          FavoritesPage(
            onSwitchToMap: () {
              setState(() {
                currentIndex = 0;
              });
            },
          ),
          RecommendPage(key: _recommendPageKey),
          SettingPage(key: _settingPageKey),
        ],
      ),
      bottomNavigationBar: BottomNavigationBar(
        type: BottomNavigationBarType.fixed,
        backgroundColor: Theme.of(context).colorScheme.surface,
        selectedItemColor: Theme.of(context).colorScheme.primary,
        unselectedItemColor: Theme.of(context).colorScheme.onSurface.withAlpha(179),
        showUnselectedLabels: true,
        currentIndex: currentIndex,
        onTap: (index) {
          setState(() {
            currentIndex = index;
          });
          // Reload settings when switching between tabs
          if (index == 2) {
            _recommendPageKey.currentState?.reloadSettings();
          } else if (index == 3) {
            _settingPageKey.currentState?.reloadSettings();
          }
        },
        items: const [
          BottomNavigationBarItem(
            icon: Icon(Icons.map_outlined),
            activeIcon: Icon(Icons.map),
            label: "Map",
          ),
          BottomNavigationBarItem(
            icon: Icon(Icons.favorite_border),
            activeIcon: Icon(Icons.favorite),
            label: "Favorites",
          ),
          BottomNavigationBarItem(
            icon: Icon(Icons.recommend_outlined),
            activeIcon: Icon(Icons.recommend),
            label: "Recommend",
          ),
          BottomNavigationBarItem(
            icon: Icon(Icons.settings_outlined),
            activeIcon: Icon(Icons.settings),
            label: "Settings",
          ),
        ],
      ),
    );
  }
}


