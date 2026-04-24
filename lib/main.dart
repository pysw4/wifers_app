import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:wifers_app/services/api_service.dart';
import 'package:wifers_app/services/location_service.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:wifers_app/models/ap_info.dart';
import 'package:wifers_app/pages/MyHomePage.dart';



void main() {
  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Flutter Demo',
      theme: ThemeData(
        colorScheme: .fromSeed(seedColor: Colors.blue),
      ),
      home: const MyHomePage(title: 'Wifers Flutter Demo'),
    );
  }
}
