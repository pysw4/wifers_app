import 'package:flutter/material.dart';
import 'package:wifers_app/services/storage_service.dart';

class SettingPage extends StatefulWidget {
  const SettingPage({super.key});

  @override
  State<SettingPage> createState() => SettingPageState();

}

class SettingPageState extends State<SettingPage> {
  bool _notificationsEnabled = true;
  bool _cachePredictions = true;
  bool _lowPowerLocation = true;
  bool _preferStableAps = true;
  int _cacheDurationMinutes = 60;
  int _recommendRadiusMeters = 500;
  String _recommendMode = 'balanced';

  final List<int> _cacheDurations = [15, 60, 240];
  final Map<int, String> _cacheDurationLabels = {
    15: '15 min',
    60: '1 hour',
    240: '4 hours',
  };
  final List<int> _recommendRadiusOptions = [200, 500, 800, 1000, 5000];
  final Map<int, String> _recommendRadiusLabels = {
    200: '200 m',
    500: '500 m',
    800: '800 m',
    1000: '1 km',
    5000: '5 km',
  };
  final List<String> _recommendModes = ['distance', 'signal', 'balanced'];
  final Map<String, _ModeInfo> _recommendModeInfo = {
    'distance': _ModeInfo('Distance Priority', Icons.near_me, 'Prefer the closest APs'),
    'signal': _ModeInfo('Signal Priority', Icons.signal_wifi_4_bar, 'Prefer APs with strongest predicted signal'),
    'balanced': _ModeInfo('Balanced', Icons.balance, 'Weighted mix of distance and signal quality'),
  };

  @override
  void initState() {
    super.initState();
    _loadSettings();
  }

  /// Public method to reload settings from storage (called when switching tabs)
  void reloadSettings() {
    _loadSettings();
  }

  Future<void> _loadSettings() async {
    final settings = await StorageService.loadSettings();
    if (!mounted) return;
    setState(() {

      _notificationsEnabled = settings['notificationsEnabled'] ?? true;
      _cachePredictions = settings['cachePredictions'] ?? true;
      _cacheDurationMinutes = settings['cacheDurationMinutes'] ?? 60;
      _lowPowerLocation = settings['lowPowerLocation'] ?? true;
      _preferStableAps = settings['preferStableAps'] ?? true;
      _recommendRadiusMeters = settings['recommendRadiusMeters'] ?? 500;
      _recommendMode = settings['recommendMode'] as String? ?? 'balanced';
    });
  }

  Future<void> _saveSettings() async {
    final settings = {
      'notificationsEnabled': _notificationsEnabled,
      'cachePredictions': _cachePredictions,
      'cacheDurationMinutes': _cacheDurationMinutes,
      'lowPowerLocation': _lowPowerLocation,
      'preferStableAps': _preferStableAps,
      'recommendRadiusMeters': _recommendRadiusMeters,
      'recommendMode': _recommendMode,
    };
    await StorageService.saveSettings(settings);
  }

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
          // --- Prediction Settings ---
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16.0),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    "Prediction Settings",
                    style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 12),
                  SwitchListTile(
                    title: const Text('Cache prediction results'),
                    subtitle: const Text('Reuse recent model predictions for faster response'),
                    value: _cachePredictions,
                    onChanged: (bool value) {
                      setState(() {
                        _cachePredictions = value;
                      });
                      _saveSettings();
                    },
                    secondary: const Icon(Icons.memory),
                  ),
                  const SizedBox(height: 12),
                  ListTile(
                    leading: const Icon(Icons.timer),
                    title: const Text('Cache duration'),
                    subtitle: Text(_cacheDurationLabels[_cacheDurationMinutes] ?? '1 hour'),
                    trailing: DropdownButton<int>(
                      value: _cacheDurationMinutes,
                      items: _cacheDurations
                          .map((minutes) => DropdownMenuItem(
                                value: minutes,
                                child: Text(_cacheDurationLabels[minutes]!),
                              ))
                          .toList(),
                      onChanged: _cachePredictions
                          ? (int? value) {
                              if (value != null) {
                                setState(() {
                                  _cacheDurationMinutes = value;
                                });
                                _saveSettings();
                              }
                            }
                          : null,
                    ),
                  ),
                ],
              ),
            ),
          ),

          const SizedBox(height: 16),

          // --- Recommendation Preferences ---
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16.0),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'Recommendation Mode',
                    style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 8),
                  ..._recommendModes.map((mode) {
                    final info = _recommendModeInfo[mode]!;
                    final isSelected = _recommendMode == mode;
                    return Padding(
                      padding: const EdgeInsets.symmetric(vertical: 4),
                      child: Card(
                        color: isSelected
                            ? Theme.of(context).colorScheme.primaryContainer
                            : null,
                        child: ListTile(
                          leading: Icon(
                            info.icon,
                            color: isSelected
                                ? Theme.of(context).colorScheme.primary
                                : null,
                          ),
                          title: Text(
                            info.label,
                            style: TextStyle(
                              fontWeight:
                                  isSelected ? FontWeight.bold : FontWeight.normal,
                            ),
                          ),
                          subtitle: Text(info.description),
                          trailing: isSelected
                              ? Icon(
                                  Icons.check_circle,
                                  color: Theme.of(context).colorScheme.primary,
                                )
                              : null,
                          selected: isSelected,
                          onTap: () {
                            setState(() {
                              _recommendMode = mode;
                            });
                            _saveSettings();
                          },
                        ),
                      ),
                    );
                  }),
                  const Divider(height: 24),
                  SwitchListTile(
                    title: const Text('Prefer stable APs'),
                    subtitle: const Text('Rank APs with predicted Up status higher'),
                    value: _preferStableAps,
                    onChanged: (bool value) {
                      setState(() {
                        _preferStableAps = value;
                      });
                      _saveSettings();
                    },
                    secondary: const Icon(Icons.thumb_up),
                  ),
                  const SizedBox(height: 12),
                  ListTile(
                    leading: const Icon(Icons.map),
                    title: const Text('Recommendation radius'),
                    subtitle: Text(_recommendRadiusLabels[_recommendRadiusMeters] ?? '500 m'),
                    trailing: DropdownButton<int>(
                      value: _recommendRadiusMeters,
                      items: _recommendRadiusOptions
                          .map((meters) => DropdownMenuItem(
                                value: meters,
                                child: Text(_recommendRadiusLabels[meters]!),
                              ))
                          .toList(),
                      onChanged: (int? value) {
                        if (value != null) {
                          setState(() {
                            _recommendRadiusMeters = value;
                          });
                          _saveSettings();
                        }
                      },
                    ),
                  ),
                ],
              ),
            ),
          ),

          const SizedBox(height: 16),

          // --- Battery & Notifications ---
          Card(
            child: Column(
              children: [
                SwitchListTile(
                  title: const Text('Low-power location mode'),
                  subtitle: const Text('Reduce background location checks for better battery life'),
                  value: _lowPowerLocation,
                  onChanged: (bool value) {
                    setState(() {
                      _lowPowerLocation = value;
                    });
                    _saveSettings();
                  },
                  secondary: const Icon(Icons.battery_saver),
                ),
                const Divider(height: 1),
                SwitchListTile(
                  title: const Text('Receive notifications'),
                  subtitle: const Text('Enable status alerts and results updates'),
                  value: _notificationsEnabled,
                  onChanged: (bool value) {
                    setState(() {
                      _notificationsEnabled = value;
                    });
                    _saveSettings();
                  },
                  secondary: const Icon(Icons.notifications_active),
                ),
              ],
            ),
          ),

          const SizedBox(height: 16),

          // --- Data Management ---
          Card(
            child: Column(
              children: [
                ListTile(
                  leading: const Icon(Icons.delete_forever),
                  title: const Text(
                    'Clear cached data',
                    style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                  ),
                  subtitle: const Text('Remove locally stored prediction and location cache'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () async {
                    final messenger = ScaffoldMessenger.of(context);
                    await StorageService.clearCache();
                    if (!mounted) return;
                    messenger.showSnackBar(
                      const SnackBar(content: Text('Cached data cleared')),
                    );
                  },
                ),
                const Divider(height: 1),
                ListTile(
                  leading: const Icon(Icons.refresh),
                  title: const Text(
                    'Reset settings',
                    style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                  ),
                  subtitle: const Text('Restore default app preferences'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () async {
                    final messenger = ScaffoldMessenger.of(context);
                    await StorageService.resetSettings();
                    await _loadSettings();
                    if (!mounted) return;
                    messenger.showSnackBar(
                      const SnackBar(content: Text('Settings reset to defaults')),
                    );
                  },
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _ModeInfo {
  final String label;
  final IconData icon;
  final String description;

  const _ModeInfo(this.label, this.icon, this.description);
}