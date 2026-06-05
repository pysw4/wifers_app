import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';
import 'package:wifers_app/services/api_service.dart';
import 'package:wifers_app/services/cache_service.dart';

/// Displays the 24-hour signal strength trend chart for a specific AP
///
/// Features:
/// - Line chart / Bar chart toggle
/// - Actual average overlay (from clientes_processed.csv)
/// - **Predicted vs Historical comparison mode** (uses /compare endpoint)
/// - **CacheService** caching for faster re-open
class APTrendDialog extends StatefulWidget {
  final String apName;
  final String? building;

  const APTrendDialog({
    super.key,
    required this.apName,
    this.building,
  });

  @override
  State<APTrendDialog> createState() => _APTrendDialogState();
}

class _APTrendDialogState extends State<APTrendDialog> {
  final ApiService _apiService = ApiService();
  bool _isLoading = true;
  String? _error;
  List<Map<String, dynamic>> _trendData = [];
  String _dayType = 'weekday';
  String _dayLabel = 'Weekday';
  Map<String, dynamic> _stats = {};
  Map<String, dynamic> _accuracy = {};
  Map<String, dynamic>? _accuracyVsActual;
  bool _showBars = true;
  bool _showAverage = false;

  // -- Comparison mode state (Predicted vs Historical average) --
  bool _compareMode = false;
  bool _compareLoading = false;
  List<Map<String, dynamic>> _predictedTrend = [];   // today's prediction
  List<Map<String, dynamic>> _historicalTrend = [];  // historical actual average
  bool _hasHistorical = false;
  int _totalMeasurements = 0;
  String _predictedSource = '';

  /// Map backend day names ('mon'/'tue'/.../'sun') to display labels
  static const Map<String, String> _dayLabels = {
    'mon': 'Monday',
    'tue': 'Tuesday',
    'wed': 'Wednesday',
    'thu': 'Thursday',
    'fri': 'Friday',
    'sat': 'Saturday',
    'sun': 'Sunday',
  };

  static const Set<String> _weekendDays = {'sat', 'sun'};

  /// Compute day label from current date
  String _getCurrentDayLabel() {
    final now = DateTime.now();
    final dayNames = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
    final dayName = dayNames[now.weekday - 1];
    final label = _dayLabels[dayName] ?? 'Weekday';
    final isWeekend = _weekendDays.contains(dayName);
    return '$label (${isWeekend ? 'Weekend' : 'Weekday'})';
  }

  String _formatDayType(String dayName) {
    final label = _dayLabels[dayName] ?? 'Weekday';
    final isWeekend = _weekendDays.contains(dayName);
    return '$label (${isWeekend ? 'Weekend' : 'Weekday'})';
  }

  @override
  void initState() {
    super.initState();
    _loadTrend();
  }

  /// Load trend data, using CacheService for caching
  Future<void> _loadTrend() async {
    // Cache key v2 — version suffix forces cache refresh when backend changes
    final cacheKey = 'trend_v2_${widget.apName.toLowerCase()}';
    const ttl = Duration(minutes: 10);

    try {
      // 1) Try cache first
      final cached = await CacheService.get<Map<String, dynamic>>(
        cacheKey,
        ttl: ttl,
      );

      Map<String, dynamic> data;
      if (cached != null) {
        data = cached;
      } else {
        // 2) Fetch from API
        data = await _apiService.getAPDailyTrend(widget.apName);
        // Save to cache (fire & forget)
        CacheService.set(cacheKey, data);
      }

      final trend = (data['trend'] as List<dynamic>)
          .map((e) => Map<String, dynamic>.from(e as Map))
          .toList();
      setState(() {
        _trendData = trend;
        final backendDayType = data['day_type'] as String?;
        final backendDayName = data['day_name'] as String?;
        if (backendDayType != null && backendDayName != null) {
          _dayType = backendDayType;
          _dayLabel = _formatDayType(backendDayName);
        } else {
          final now = DateTime.now();
          final isWeekend =
              now.weekday == DateTime.saturday || now.weekday == DateTime.sunday;
          _dayType = isWeekend ? 'weekend' : 'weekday';
          _dayLabel = _getCurrentDayLabel();
        }
        _stats = data['stats'] as Map<String, dynamic>? ?? {};
        _accuracy = data['accuracy'] as Map<String, dynamic>? ?? {};
        _accuracyVsActual = data['accuracy_vs_actual'] as Map<String, dynamic>?;
        _isLoading = false;
      });
    } catch (e) {
      setState(() {
        _error = e.toString();
        _isLoading = false;
      });
    }
  }

  /// Load predicted vs historical comparison data
  Future<void> _loadCompare() async {
    final cacheKey = 'trend_compare_${widget.apName.toLowerCase()}';
    const ttl = Duration(minutes: 15);

    setState(() => _compareLoading = true);

    try {
      // 1) Try cache
      final cached = await CacheService.get<Map<String, dynamic>>(
        cacheKey,
        ttl: ttl,
      );

      Map<String, dynamic> data;
      if (cached != null) {
        data = cached;
      } else {
        data = await _apiService.getAPTrendCompare(widget.apName);
        CacheService.set(cacheKey, data);
      }

      final predicted = ((data['predicted'] as List<dynamic>?) ?? [])
          .map((e) => Map<String, dynamic>.from(e as Map))
          .toList();
      final historical = ((data['historical'] as List<dynamic>?) ?? [])
          .map((e) => Map<String, dynamic>.from(e as Map))
          .toList();

      setState(() {
        _predictedTrend = predicted;
        _historicalTrend = historical;
        _hasHistorical = data['has_historical'] == true;
        _totalMeasurements = data['total_measurements'] as int? ?? 0;
        _predictedSource = data['predicted_source'] as String? ?? '';
        _compareLoading = false;
        _compareMode = true;
        // Auto-switch to line chart for comparison
        _showBars = false;
      });
    } catch (e) {
      setState(() => _compareLoading = false);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Failed to load comparison: $e')),
        );
      }
    }
  }

  Color _dbmToColor(double dbm) {
    final clamped = dbm.clamp(-97.0, -22.0);
    final t = (clamped - (-97.0)) / (-22.0 - (-97.0));
    const stops = [0.0, 0.33, 0.66, 1.0];
    const colors = [
      Color(0xFFD50000),
      Color(0xFFFF6D00),
      Color(0xFFFFEA00),
      Color(0xFF00E676),
    ];
    for (int i = 0; i < stops.length - 1; i++) {
      if (t >= stops[i] && t <= stops[i + 1]) {
        final localT = (t - stops[i]) / (stops[i + 1] - stops[i]);
        return Color.lerp(colors[i], colors[i + 1], localT)!;
      }
    }
    return colors.last;
  }

  @override
  Widget build(BuildContext context) {
    return Dialog(
      insetPadding: const EdgeInsets.all(12),
      child: Container(
        width: double.maxFinite,
        constraints: const BoxConstraints(maxHeight: 660),
        padding: const EdgeInsets.all(16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Title row
            Row(
              children: [
                const Icon(Icons.trending_up, color: Colors.blue),
                const SizedBox(width: 8),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        _compareMode
                            ? '${widget.apName} — Compare'
                            : widget.apName,
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      if (widget.building != null)
                        Text(
                          widget.building!,
                          style: TextStyle(
                            fontSize: 12,
                            color: Colors.grey[600],
                          ),
                        ),
                    ],
                  ),
                ),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: _compareMode
                        ? Colors.purple[50]
                        : _dayType == 'weekend'
                            ? Colors.orange[50]
                            : Colors.blue[50],
                    borderRadius: BorderRadius.circular(12),
                  ),
              child: Text(
                _compareMode ? 'Pred vs Hist' : _dayLabel,
                    style: TextStyle(
                      fontSize: 11,
                      color: _compareMode
                          ? Colors.purple[800]
                          : _dayType == 'weekend'
                              ? Colors.orange[800]
                              : Colors.blue[800],
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              _compareMode
                  ? 'Predicted vs Historical Average Comparison'
                  : '24-Hour Signal Strength Trend',
              style: TextStyle(fontSize: 12, color: Colors.grey[500]),
            ),

            // Stats row
            if (!_compareMode && _stats.isNotEmpty) ...[
              const SizedBox(height: 8),
              _buildStatsRow(),
            ],

            // Accuracy row
            if (!_compareMode &&
                _accuracy.isNotEmpty &&
                _accuracy['total_feedback'] != null &&
                _accuracy['total_feedback'] > 0) ...[
              const SizedBox(height: 6),
              _buildAccuracyRow(),
            ],

            // Accuracy vs Actual row
            if (!_compareMode && _accuracyVsActual != null) ...[
              const SizedBox(height: 6),
              _buildAccuracyVsActualRow(),
            ],

            const Divider(height: 12),

            // Chart area
            Expanded(
              child: _isLoading
                  ? const Center(child: CircularProgressIndicator())
                  : _error != null
                      ? Center(
                          child: Column(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              const Icon(Icons.error_outline,
                                  color: Colors.red, size: 40),
                              const SizedBox(height: 8),
                              Text(
                                'Failed to load trend',
                                style: TextStyle(color: Colors.grey[600]),
                              ),
                              const SizedBox(height: 4),
                              Text(
                                _error!,
                                style: const TextStyle(
                                    fontSize: 11, color: Colors.red),
                                textAlign: TextAlign.center,
                              ),
                            ],
                          ),
                        )
                      : _compareMode
                          ? _buildCompareChart()
                          : _buildChart(),
            ),

            const SizedBox(height: 8),

            // Bottom action bar
            Row(
              children: [
                // Toggle chart type
                TextButton.icon(
                  onPressed: () => setState(() => _showBars = !_showBars),
                  icon: Icon(
                    _showBars ? Icons.show_chart : Icons.bar_chart,
                    size: 18,
                  ),
                  label: Text(
                    _showBars ? 'Line' : 'Bars',
                    style: const TextStyle(fontSize: 12),
                  ),
                ),
                // Toggle actual average overlay
                if (!_compareMode &&
                    _accuracyVsActual != null &&
                    _accuracyVsActual!['hourly'] != null)
                  TextButton.icon(
                    onPressed: () {
                      setState(() {
                        _showAverage = !_showAverage;
                        if (_showAverage && _showBars) {
                          _showBars = false;
                        }
                      });
                    },
                    icon: Icon(
                      _showAverage ? Icons.visibility : Icons.visibility_off,
                      size: 18,
                      color: Colors.green,
                    ),
                    label: Text(
                      _showAverage ? 'Hide Avg' : 'Show Avg',
                      style:
                          const TextStyle(fontSize: 12, color: Colors.green),
                    ),
                  ),
                // Compare toggle
                if (!_isLoading && _error == null)
                  TextButton.icon(
                    onPressed: _compareLoading
                        ? null
                        : () {
                            if (_compareMode) {
                              // Exit comparison mode
                              setState(() => _compareMode = false);
                            } else {
                              _loadCompare();
                            }
                          },
                    icon: _compareLoading
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(strokeWidth: 2))
                        : Icon(
                            _compareMode
                                ? Icons.cancel_outlined
                                : Icons.compare_arrows,
                            size: 18,
                            color: Colors.deepPurple,
                          ),
                    label: Text(
                      _compareMode ? 'Exit Compare' : 'Compare',
                      style: const TextStyle(
                          fontSize: 12, color: Colors.deepPurple),
                    ),
                  ),
                const Spacer(),
                SizedBox(
                  width: 100,
                  child: ElevatedButton(
                    onPressed: () => Navigator.pop(context),
                    child: const Text('Close'),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildStatsRow() {
    final avg = _stats['avg_db'] as num?;
    final maxDb = _stats['max_db'] as num?;
    final minDb = _stats['min_db'] as num?;
    final bestHour = _stats['best_hour'] as int?;
    final worstHour = _stats['worst_hour'] as int?;

    return Container(
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: Colors.grey[50],
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: Colors.grey[200]!),
      ),
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceAround,
          children: [
            _buildStatItem(Icons.show_chart, 'Avg',
                '${avg?.toStringAsFixed(1) ?? "-"} dBm', _dbmToColor(avg?.toDouble() ?? -70)),
            const SizedBox(width: 12),
            _buildStatItem(Icons.arrow_upward, 'Best',
                '${maxDb?.toStringAsFixed(1) ?? "-"} dBm', Colors.green),
            const SizedBox(width: 12),
            _buildStatItem(Icons.arrow_downward, 'Worst',
                '${minDb?.toStringAsFixed(1) ?? "-"} dBm', Colors.red),
            if (bestHour != null) ...[
              const SizedBox(width: 12),
              _buildStatItem(
                  Icons.access_time, 'Peak', '${bestHour}:00', Colors.blue),
            ],
            if (worstHour != null) ...[
              const SizedBox(width: 12),
              _buildStatItem(
                  Icons.access_time, 'Low', '${worstHour}:00', Colors.orange),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildAccuracyRow() {
    final total = _accuracy['total_feedback'] as int? ?? 0;
    final accuracy = _accuracy['accuracy'] as num?;
    final upAccuracy = _accuracy['up_accuracy'] as num?;
    final downAccuracy = _accuracy['down_accuracy'] as num?;
    final correct = _accuracy['correct'] as int? ?? 0;

    Color accuracyColor;
    if (accuracy == null) {
      accuracyColor = Colors.grey;
    } else if (accuracy >= 0.8) {
      accuracyColor = Colors.green;
    } else if (accuracy >= 0.6) {
      accuracyColor = Colors.orange;
    } else {
      accuracyColor = Colors.red;
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
      decoration: BoxDecoration(
        color: accuracyColor.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: accuracyColor.withValues(alpha: 0.3)),
      ),
      child: Row(
        children: [
          Icon(Icons.check_circle_outline, size: 14, color: accuracyColor),
          const SizedBox(width: 6),
          Text(
            'Accuracy: ${accuracy != null ? "${(accuracy * 100).toStringAsFixed(1)}%" : "N/A"}',
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.bold,
              color: accuracyColor,
            ),
          ),
          const SizedBox(width: 8),
          if (upAccuracy != null)
            _buildMiniStat('Up', upAccuracy, Colors.green),
          if (downAccuracy != null)
            _buildMiniStat('Down', downAccuracy, Colors.red),
          const Spacer(),
          Text(
            '$correct/$total',
            style: TextStyle(fontSize: 10, color: Colors.grey[500]),
          ),
        ],
      ),
    );
  }

  Widget _buildAccuracyVsActualRow() {
    final mae = _accuracyVsActual!['mae'] as num?;
    final signalAccuracy = _accuracyVsActual!['signal_accuracy'] as num?;
    final statusAccuracy = _accuracyVsActual!['status_accuracy'] as num?;
    final totalMeasurements =
        _accuracyVsActual!['total_measurements'] as int? ?? 0;
    final comparedHours = _accuracyVsActual!['compared_hours'] as int? ?? 0;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
      decoration: BoxDecoration(
        color: Colors.indigo.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: Colors.indigo.withValues(alpha: 0.3)),
      ),
      child: Row(
        children: [
          const Icon(Icons.analytics_outlined, size: 14, color: Colors.indigo),
          const SizedBox(width: 6),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Row(
                  children: [
                    Text(
                      'MAE: ±${mae?.toStringAsFixed(1) ?? "?"} dBm',
                      style: const TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.bold,
                        color: Colors.indigo,
                      ),
                    ),
                    const SizedBox(width: 8),
                    if (signalAccuracy != null)
                      Text(
                        'Signal: ${(signalAccuracy * 100).toStringAsFixed(0)}%',
                        style: TextStyle(
                          fontSize: 10,
                          color: signalAccuracy >= 0.7
                              ? Colors.green[700]
                              : Colors.orange[700],
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    if (statusAccuracy != null) ...[
                      const SizedBox(width: 8),
                      Text(
                        'Status: ${(statusAccuracy * 100).toStringAsFixed(0)}%',
                        style: TextStyle(
                          fontSize: 10,
                          color: statusAccuracy >= 0.8
                              ? Colors.green[700]
                              : Colors.orange[700],
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    ],
                  ],
                ),
                Text(
                  'Based on $totalMeasurements measurements across $comparedHours hours',
                  style: TextStyle(fontSize: 9, color: Colors.grey[500]),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildMiniStat(String label, num accuracy, Color color) {
    return Padding(
      padding: const EdgeInsets.only(right: 6),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 1),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.1),
          borderRadius: BorderRadius.circular(4),
        ),
        child: Text(
          '$label: ${(accuracy * 100).toStringAsFixed(0)}%',
          style: TextStyle(
              fontSize: 9, color: color, fontWeight: FontWeight.w500),
        ),
      ),
    );
  }

  Widget _buildStatItem(
      IconData icon, String label, String value, Color color) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 14, color: color),
        const SizedBox(height: 2),
        Text(
          value,
          style: TextStyle(
            fontSize: 11,
            fontWeight: FontWeight.bold,
            color: color,
          ),
        ),
        Text(
          label,
          style: TextStyle(fontSize: 9, color: Colors.grey[500]),
        ),
      ],
    );
  }

  /// Get actual average data points for overlay
  List<FlSpot>? _getActualSpots() {
    if (_accuracyVsActual == null) return null;
    final hourly = _accuracyVsActual!['hourly'] as List<dynamic>?;
    if (hourly == null || hourly.isEmpty) return null;

    final spots = <FlSpot>[];
    for (final entry in hourly) {
      final h = (entry['hour'] as num).toDouble();
      final actualDb = (entry['actual_mean'] as num).toDouble();
      spots.add(FlSpot(h, actualDb));
    }
    return spots;
  }

  /// Build the main single-trend chart (line or bars)
  Widget _buildChart() {
    final validData = _trendData
        .where((d) => d['signal_db'] != null)
        .toList();

    if (validData.isEmpty) {
      return Center(
        child: Text(
          'No signal data available for this AP',
          style: TextStyle(color: Colors.grey[500]),
        ),
      );
    }

    // Calculate Y-axis range
    double minDb = -97;
    double maxDb = -22;
    for (final d in validData) {
      final db = (d['signal_db'] as num).toDouble();
      if (db < minDb) minDb = db;
      if (db > maxDb) maxDb = db;
    }
    final actualSpots = _getActualSpots();
    if (actualSpots != null) {
      for (final spot in actualSpots) {
        if (spot.y < minDb) minDb = spot.y;
        if (spot.y > maxDb) maxDb = spot.y;
      }
    }
    minDb -= 3;
    maxDb += 3;

    final spots = validData.map((d) {
      final hour = (d['hour'] as num).toDouble();
      final db = (d['signal_db'] as num).toDouble();
      return FlSpot(hour, db);
    }).toList();

    // Bar chart data
    final barData = validData.map((d) {
      final hour = (d['hour'] as num).toDouble();
      final signalDb = (d['signal_db'] as num).toDouble();
      final barValue = signalDb + 100;
      return BarChartGroupData(
        x: hour.toInt(),
        barRods: [
          BarChartRodData(
            toY: barValue.clamp(0, 100),
            color: _dbmToColor(signalDb).withValues(alpha: 0.6),
            width: 6,
            borderRadius:
                const BorderRadius.vertical(top: Radius.circular(2)),
          ),
        ],
      );
    }).toList();

    if (_showBars) {
      return _buildBarChart(barData, validData);
    }

    return _buildLineChart(spots, validData, minDb, maxDb, actualSpots);
  }

  /// Build the comparison chart (Predicted vs Historical dual-line)
  Widget _buildCompareChart() {
    if (_predictedTrend.isEmpty) {
      return Center(
        child: Text(
          'No comparison data available',
          style: TextStyle(color: Colors.grey[500]),
        ),
      );
    }

    // Compute Y range from both datasets
    double minDb = -97;
    double maxDb = -22;
    for (final d in _predictedTrend) {
      final db = (d['signal_db'] as num?)?.toDouble();
      if (db != null && db < minDb) minDb = db;
      if (db != null && db > maxDb) maxDb = db;
    }
    for (final d in _historicalTrend) {
      final db = (d['signal_db'] as num?)?.toDouble();
      if (db != null && db < minDb) minDb = db;
      if (db != null && db > maxDb) maxDb = db;
    }
    minDb -= 3;
    maxDb += 3;

    // Build spots from both datasets
    final predictedSpots = _predictedTrend
        .where((d) => d['signal_db'] != null)
        .map((d) => FlSpot(
              (d['hour'] as num).toDouble(),
              (d['signal_db'] as num).toDouble(),
            ))
        .toList();

    final historicalSpots = _historicalTrend
        .where((d) => d['signal_db'] != null)
        .map((d) => FlSpot(
              (d['hour'] as num).toDouble(),
              (d['signal_db'] as num).toDouble(),
            ))
        .toList();

    // Compute stats for both
    String predictedAvg = '-', historicalAvg = '-';
    if (predictedSpots.isNotEmpty) {
      final avg = predictedSpots.map((s) => s.y).reduce((a, b) => a + b) /
          predictedSpots.length;
      predictedAvg = '${avg.toStringAsFixed(1)} dBm';
    }
    if (historicalSpots.isNotEmpty) {
      final avg = historicalSpots.map((s) => s.y).reduce((a, b) => a + b) /
          historicalSpots.length;
      historicalAvg = '${avg.toStringAsFixed(1)} dBm';
    }

    // Source display label
    final sourceLabel = _predictedSource == 'lstm' ? 'LSTM' :
        _predictedSource == 'profiles' ? 'Profiles' : 'RF';

    return Column(
      children: [
        // Comparison legend
        Container(
          padding: const EdgeInsets.all(8),
          decoration: BoxDecoration(
            color: Colors.grey[50],
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: Colors.grey[200]!),
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceAround,
            children: [
              _buildCompareLegendItem('Predicted ($sourceLabel)', Colors.blue, predictedAvg),
              if (_hasHistorical)
                _buildCompareLegendItem('Historical', Colors.green, historicalAvg)
              else
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: Text(
                    'No historical data',
                    style: TextStyle(fontSize: 11, color: Colors.grey[500]),
                  ),
                ),
            ],
          ),
        ),
        if (_hasHistorical && _totalMeasurements > 0)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(
              'Based on $_totalMeasurements historical measurements',
              style: TextStyle(fontSize: 9, color: Colors.grey[500]),
            ),
          ),
        const SizedBox(height: 8),
        // Dual-line chart
        Expanded(
          child: LineChart(
            LineChartData(
              gridData: FlGridData(
                show: true,
                drawVerticalLine: false,
                horizontalInterval: 10,
                getDrawingHorizontalLine: (value) => FlLine(
                  color: Colors.grey.withValues(alpha: 0.15),
                  strokeWidth: 1,
                ),
              ),
              titlesData: FlTitlesData(
                topTitles: const AxisTitles(
                    sideTitles: SideTitles(showTitles: false)),
                rightTitles: const AxisTitles(
                    sideTitles: SideTitles(showTitles: false)),
                bottomTitles: AxisTitles(
                  sideTitles: SideTitles(
                    showTitles: true,
                    interval: 4,
                    reservedSize: 22,
                    getTitlesWidget: (value, meta) {
                      if (value % 4 == 0) {
                        return Text(
                          '${value.toInt()}:00',
                          style: const TextStyle(fontSize: 10),
                        );
                      }
                      return const SizedBox.shrink();
                    },
                  ),
                ),
                leftTitles: AxisTitles(
                  sideTitles: SideTitles(
                    showTitles: true,
                    reservedSize: 36,
                    interval: 10,
                    getTitlesWidget: (value, meta) {
                      return Text(
                        '${value.toInt()} dBm',
                        style: const TextStyle(fontSize: 9),
                      );
                    },
                  ),
                ),
              ),
              borderData: FlBorderData(
                show: true,
                border: Border.all(color: Colors.grey.withValues(alpha: 0.2)),
              ),
              minX: 0,
              maxX: 23,
              minY: minDb,
              maxY: maxDb,
              lineBarsData: [
                // Predicted line (blue)
                LineChartBarData(
                  spots: predictedSpots,
                  isCurved: true,
                  curveSmoothness: 0.3,
                  color: Colors.blue,
                  barWidth: 2.5,
                  isStrokeCapRound: true,
                  dotData: FlDotData(
                    show: true,
                    getDotPainter: (spot, percent, barData, index) {
                      return FlDotCirclePainter(
                        radius: 3,
                        color: Colors.blue,
                        strokeWidth: 1.5,
                        strokeColor: Colors.white,
                      );
                    },
                  ),
                  belowBarData: BarAreaData(
                    show: true,
                    color: Colors.blue.withValues(alpha: 0.06),
                  ),
                ),
                // Historical line (green, dashed)
                if (_hasHistorical && historicalSpots.isNotEmpty)
                  LineChartBarData(
                    spots: historicalSpots,
                    isCurved: true,
                    curveSmoothness: 0.3,
                    color: Colors.green,
                    barWidth: 2.5,
                    isStrokeCapRound: true,
                    dashArray: [6, 3],
                    dotData: FlDotData(
                      show: true,
                      getDotPainter: (spot, percent, barData, index) {
                        return FlDotCirclePainter(
                          radius: 3,
                          color: Colors.green,
                          strokeWidth: 1.5,
                          strokeColor: Colors.white,
                        );
                      },
                    ),
                    belowBarData: BarAreaData(
                      show: true,
                      color: Colors.green.withValues(alpha: 0.06),
                    ),
                  ),
              ],
              lineTouchData: LineTouchData(
                touchTooltipData: LineTouchTooltipData(
                  getTooltipItems: (touchedSpots) {
                    return touchedSpots.map((spot) {
                      final label = spot.barIndex == 0 ? 'Pred' : 'Hist';
                      final db = spot.y;
                      return LineTooltipItem(
                        '${spot.x.toInt()}:00\n$label: ${db.toStringAsFixed(1)} dBm',
                        TextStyle(
                          color: spot.barIndex == 0
                              ? Colors.blue
                              : Colors.green,
                          fontWeight: FontWeight.bold,
                          fontSize: 12,
                        ),
                      );
                    }).toList();
                  },
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildCompareLegendItem(
      String label, Color color, String avgValue) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 12,
          height: 12,
          decoration: BoxDecoration(
            color: color,
            borderRadius: BorderRadius.circular(3),
          ),
        ),
        const SizedBox(width: 6),
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(label,
                style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w500,
                    color: color)),
            Text(avgValue,
                style: TextStyle(fontSize: 9, color: Colors.grey[600])),
          ],
        ),
      ],
    );
  }

  /// Build line chart (reused for single-trend mode)
  Widget _buildLineChart(
    List<FlSpot> spots,
    List<Map<String, dynamic>> validData,
    double minDb,
    double maxDb,
    List<FlSpot>? actualSpots,
  ) {
    return LineChart(
      LineChartData(
        gridData: FlGridData(
          show: true,
          drawVerticalLine: false,
          horizontalInterval: 10,
          getDrawingHorizontalLine: (value) => FlLine(
            color: Colors.grey.withValues(alpha: 0.15),
            strokeWidth: 1,
          ),
        ),
        titlesData: FlTitlesData(
          topTitles:
              const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          rightTitles:
              const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          bottomTitles: AxisTitles(
            sideTitles: SideTitles(
              showTitles: true,
              interval: 4,
              reservedSize: 22,
              getTitlesWidget: (value, meta) {
                if (value % 4 == 0) {
                  return Text(
                    '${value.toInt()}:00',
                    style: const TextStyle(fontSize: 10),
                  );
                }
                return const SizedBox.shrink();
              },
            ),
          ),
          leftTitles: AxisTitles(
            sideTitles: SideTitles(
              showTitles: true,
              reservedSize: 36,
              interval: 10,
              getTitlesWidget: (value, meta) {
                return Text(
                  '${value.toInt()} dBm',
                  style: const TextStyle(fontSize: 9),
                );
              },
            ),
          ),
        ),
        borderData: FlBorderData(
          show: true,
          border: Border.all(color: Colors.grey.withValues(alpha: 0.2)),
        ),
        minX: 0,
        maxX: 23,
        minY: minDb,
        maxY: maxDb,
        lineBarsData: [
          // Predicted line (blue)
          LineChartBarData(
            spots: spots,
            isCurved: true,
            curveSmoothness: 0.3,
            color: Colors.blue,
            barWidth: 2.5,
            isStrokeCapRound: true,
            dotData: FlDotData(
              show: true,
              getDotPainter: (spot, percent, barData, index) {
                final db = spot.y;
                return FlDotCirclePainter(
                  radius: 3,
                  color: _dbmToColor(db),
                  strokeWidth: 1.5,
                  strokeColor: Colors.white,
                );
              },
            ),
            belowBarData: BarAreaData(
              show: true,
              color: Colors.blue.withValues(alpha: 0.08),
            ),
          ),
          // Actual average line (green, dashed)
          if (_showAverage && actualSpots != null)
            LineChartBarData(
              spots: actualSpots,
              isCurved: true,
              curveSmoothness: 0.3,
              color: Colors.green,
              barWidth: 2,
              isStrokeCapRound: true,
              dashArray: [6, 3],
              dotData: FlDotData(
                show: true,
                getDotPainter: (spot, percent, barData, index) {
                  return FlDotCirclePainter(
                    radius: 3,
                    color: Colors.green,
                    strokeWidth: 1,
                    strokeColor: Colors.white,
                  );
                },
              ),
            ),
        ],
        lineTouchData: LineTouchData(
          touchTooltipData: LineTouchTooltipData(
            getTooltipItems: (touchedSpots) {
              return touchedSpots.map((spot) {
                final db = spot.y;
                final quality = _dbmToQuality(db);
                final matchingData = validData.where(
                  (d) => (d['hour'] as num).toInt() == spot.x.toInt(),
                );
                final status = matchingData.isNotEmpty
                    ? (matchingData.first['predicted_status'] as String? ??
                        quality)
                    : quality;

                String actualStr = '';
                if (_showAverage && _accuracyVsActual != null) {
                  final hourly =
                      _accuracyVsActual!['hourly'] as List<dynamic>?;
                  if (hourly != null) {
                    for (final entry in hourly) {
                      if ((entry['hour'] as num).toInt() == spot.x.toInt()) {
                        final actualDb =
                            (entry['actual_mean'] as num).toDouble();
                        final diff = (entry['diff'] as num).toDouble();
              final interp =
                  entry['interpolated'] == true ? ' (interpolated)' : '';
              actualStr =
                  '\nAvg: ${actualDb.toStringAsFixed(1)} dBm$interp\nDiff: ${diff.toStringAsFixed(1)} dBm';
                        break;
                      }
                    }
                  }
                }

                return LineTooltipItem(
                  '${spot.x.toInt()}:00\n${db.toStringAsFixed(1)} dBm\nStatus: $status$actualStr',
                  TextStyle(
                    color: _dbmToColor(db),
                    fontWeight: FontWeight.bold,
                    fontSize: 12,
                  ),
                );
              }).toList();
            },
          ),
        ),
      ),
    );
  }

  /// Build bar chart
  Widget _buildBarChart(
    List<BarChartGroupData> barData,
    List<Map<String, dynamic>> validData,
  ) {
    return BarChart(
      BarChartData(
        gridData: FlGridData(
          show: true,
          drawVerticalLine: false,
          getDrawingHorizontalLine: (value) => FlLine(
            color: Colors.grey.withValues(alpha: 0.15),
            strokeWidth: 1,
          ),
        ),
        titlesData: FlTitlesData(
          topTitles:
              const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          rightTitles:
              const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          leftTitles: AxisTitles(
            sideTitles: SideTitles(
              showTitles: true,
              reservedSize: 36,
              interval: 10,
              getTitlesWidget: (value, meta) {
                final dbm = value.toInt() - 100;
                return Text(
                  '$dbm',
                  style: const TextStyle(fontSize: 9),
                );
              },
            ),
          ),
          bottomTitles: AxisTitles(
            sideTitles: SideTitles(
              showTitles: true,
              interval: 4,
              reservedSize: 22,
              getTitlesWidget: (value, meta) {
                if (value % 4 == 0) {
                  return Text(
                    '${value.toInt()}:00',
                    style: const TextStyle(fontSize: 10),
                  );
                }
                return const SizedBox.shrink();
              },
            ),
          ),
        ),
        borderData: FlBorderData(
          show: true,
          border: Border.all(color: Colors.grey.withValues(alpha: 0.2)),
        ),
        barGroups: barData,
        barTouchData: BarTouchData(
          touchTooltipData: BarTouchTooltipData(
            getTooltipItem: (group, groupIndex, rod, rodIndex) {
              final data = validData.firstWhere(
                (d) => (d['hour'] as num).toInt() == group.x,
              );
              final db = (data['signal_db'] as num).toDouble();
              final status =
                  data['predicted_status'] as String? ?? _dbmToQuality(db);

              String actualStr = '';
              if (_showAverage && _accuracyVsActual != null) {
                final hourly =
                    _accuracyVsActual!['hourly'] as List<dynamic>?;
                if (hourly != null) {
                  for (final entry in hourly) {
                    if ((entry['hour'] as num).toInt() == group.x) {
                      final actualDb =
                          (entry['actual_mean'] as num).toDouble();
                      final diff = (entry['diff'] as num).toDouble();
                      final interp = entry['interpolated'] == true
                          ? ' (interpolated)'
                          : '';
                      actualStr =
                          '\nAvg: ${actualDb.toStringAsFixed(1)} dBm$interp\nDiff: ${diff.toStringAsFixed(1)} dBm';
                      break;
                    }
                  }
                }
              }

              return BarTooltipItem(
                '${group.x}:00\n${db.toStringAsFixed(1)} dBm\nStatus: $status$actualStr',
                TextStyle(
                  color: _dbmToColor(db),
                  fontWeight: FontWeight.bold,
                  fontSize: 12,
                ),
              );
            },
          ),
        ),
      ),
    );
  }

  String _dbmToQuality(double dbm) {
    if (dbm >= -50) return 'Excellent';
    if (dbm >= -60) return 'Good';
    if (dbm >= -70) return 'Fair';
    if (dbm >= -80) return 'Weak';
    return 'Very Poor';
  }
}
