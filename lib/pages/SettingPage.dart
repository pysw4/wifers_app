import 'package:flutter/material.dart';

class SettingPage extends StatefulWidget {
  const SettingPage({super.key});

  @override
  State<SettingPage> createState() => _SettingPageState();
}

class _SettingPageState extends State<SettingPage> {
  // range 
  double _currentMin = 20.0;
  double _currentMax = 80.0;
  final double _minRange = 0.0;
  final double _maxRange = 100.0;

  // other state
  bool _notificationsEnabled = true;
  String _selectedDistance = "middle 2km";
  String _selectedGender = "no limits";

  // distance options
  final List<String> _distanceOptions = ["near (1km)", "middle (2km)", "far (5km)"];


  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text("Settings"),
        backgroundColor: Theme.of(context).colorScheme.inversePrimary,
      ),
      body: ListView(
        padding: const EdgeInsets.all(16.0),
        children: [
          // ===== （RangeSlider）=====
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16.0),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    "acceptable range",
                    style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 12),
                  RangeSlider(
                    values: RangeValues(_currentMin, _currentMax),
                    min: _minRange,
                    max: _maxRange,
                    divisions: 100,
                    labels: RangeLabels(
                      "${_currentMin.round()}",
                      "${_currentMax.round()}",
                    ),
                    onChanged: (RangeValues values) {
                      setState(() {
                        _currentMin = values.start;
                        _currentMax = values.end;
                      });
                    },
                  ),
                  const SizedBox(height: 8),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text("min: ${_currentMin.round()*20} meters"),
                      Text("max: ${_currentMax.round() *20} meters"),
                    ],
                  ),
                ],
              ),
            ),
          ),

          const SizedBox(height: 16),


          // 1. range choice
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16.0),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    "Searching range",
                    style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 12),
                  SegmentedButton<String>(
                    segments: _distanceOptions
                        .map((option) => ButtonSegment(value: option, label: Text(option)))
                        .toList(),
                    selected: {_selectedDistance},
                    onSelectionChanged: (Set<String> newSelection) {
                      setState(() {
                        _selectedDistance = newSelection.first;
                      });
                    },
                  ),
                ],
              ),
            ),
          ),

          const SizedBox(height: 16),


          const SizedBox(height: 16),

          // notification button
          Card(
            child: SwitchListTile(
              title: const Text(
                "Receive notifications",
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
              ),
              subtitle: const Text(" open to receive notifications"),
              value: _notificationsEnabled,
              onChanged: (bool value) {
                setState(() {
                  _notificationsEnabled = value;
                });
              },
              secondary: const Icon(Icons.notifications_active),
            ),
          ),

          const SizedBox(height: 16),

          // 4. clear 
          Card(
            child: ListTile(
              leading: const Icon(Icons.clear_all),
              title: const Text(
                "Clear data",
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
              ),
              subtitle: const Text("clear local data"),
              trailing: const Icon(Icons.chevron_right),
              onTap: () {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text("data cleared")),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}