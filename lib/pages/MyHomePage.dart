import 'package:flutter/material.dart';
import 'package:wifers_app/pages/CandidatePage.dart';
import 'package:wifers_app/pages/RecommendPage.dart';
import 'package:wifers_app/pages/SettingPage.dart';

class MyHomePage extends StatefulWidget {
  const MyHomePage({super.key, required this.title});
  final String title;
  @override
  State<MyHomePage> createState() => _MyHomePageState();
}
class _MyHomePageState extends State<MyHomePage> {
  int currentIndex = 0;

  final pages = [
    SettingPage(),
    RecommendPage(),
    CandidatePage(),
  ];

  @override
  Widget build(BuildContext context) {
    
    return Scaffold(
      appBar: AppBar(
        backgroundColor: Theme.of(context).colorScheme.inversePrimary,
        title: Text(widget.title),
      ),
      body: pages[currentIndex],

       bottomNavigationBar: BottomNavigationBar(
        currentIndex: currentIndex,
        onTap: (index) {
          setState(() {
            currentIndex = index;  
          });
        },
        items: [
          BottomNavigationBarItem(
            icon: Icon(Icons.settings),
            label: "Settings",
          ),
          BottomNavigationBarItem(
            icon: Icon(Icons.star),
            label: "Recommend",
          ),
          BottomNavigationBarItem(
            icon: Icon(Icons.search),
            label: "Map",
          ),
        ],
      ),
    );
  }
}
