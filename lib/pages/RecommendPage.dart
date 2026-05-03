import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:wifers_app/services/api_service.dart';
import 'package:wifers_app/services/location_service.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:wifers_app/models/ap_info.dart';


class RecommendPage extends StatefulWidget {
  const RecommendPage({super.key});

  @override
  State<RecommendPage> createState() => _RecommendPageState();
}

class _RecommendPageState extends State<RecommendPage> {
  final ApiService _apiService = ApiService();
  late final Future<List<double>> _recommendFuture;

  @override
  void initState() {
    super.initState();
    // request to future
    // _recommendFuture = _apiService.fetchRecommend(41.5, 2.115, 1000);
    // type transfer 
    _recommendFuture = _apiService.fetchRecommend(41.5, 2.115, 1000).then((value) {
      return value.map((e) => (e as num).toDouble()).toList();
    });

  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('recommend')),
      body: Center(
        child: FutureBuilder<List<double>>(
          future: _recommendFuture,
          builder: (context, snapshot) {
            if (snapshot.connectionState == ConnectionState.waiting) {
              return const CircularProgressIndicator();
            }
            if (snapshot.hasError) {
              return Center(child: Text('Error: ${snapshot.error}'));
            }
            if (!snapshot.hasData) {
              return const Text('no data');
            }
            final list = snapshot.data!;
            print(list);
            // safely access 
            if (list.length > 1) {
              return Text('second: ${list}');
            } else {
              return const Text('no data');
            }
          },
        ),
      ),
    );
  }
}