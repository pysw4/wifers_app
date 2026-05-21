import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';
import 'package:wifers_app/services/api_service.dart';

/// 显示指定AP在24小时内的信号强度变化趋势图表
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

  @override
  void initState() {
    super.initState();
    _loadTrend();
  }

  Future<void> _loadTrend() async {
    try {
      final data = await _apiService.getAPDailyTrend(widget.apName);
      final trend = (data['trend'] as List<dynamic>)
          .map((e) => Map<String, dynamic>.from(e as Map))
          .toList();
      setState(() {
        _trendData = trend;
        _dayType = data['day_type'] as String? ?? 'weekday';
        _isLoading = false;
      });
    } catch (e) {
      setState(() {
        _error = e.toString();
        _isLoading = false;
      });
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
      insetPadding: const EdgeInsets.all(16),
      child: Container(
        width: double.maxFinite,
        constraints: const BoxConstraints(maxHeight: 520),
        padding: const EdgeInsets.all(20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 标题行
            Row(
              children: [
                const Icon(Icons.trending_up, color: Colors.blue),
                const SizedBox(width: 8),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        widget.apName,
                        style: const TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      if (widget.building != null)
                        Text(
                          widget.building!,
                          style: TextStyle(
                            fontSize: 13,
                            color: Colors.grey[600],
                          ),
                        ),
                    ],
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: _dayType == 'weekend' ? Colors.orange[50] : Colors.blue[50],
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Text(
                    _dayType == 'weekend' ? 'Weekend' : 'Weekday',
                    style: TextStyle(
                      fontSize: 11,
                      color: _dayType == 'weekend' ? Colors.orange[800] : Colors.blue[800],
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              '24-Hour Signal Strength Trend',
              style: TextStyle(fontSize: 13, color: Colors.grey[500]),
            ),
            const Divider(height: 20),

            // 图表区域
            Expanded(
              child: _isLoading
                  ? const Center(child: CircularProgressIndicator())
                  : _error != null
                      ? Center(
                          child: Column(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              const Icon(Icons.error_outline, color: Colors.red, size: 40),
                              const SizedBox(height: 8),
                              Text(
                                'Failed to load trend',
                                style: TextStyle(color: Colors.grey[600]),
                              ),
                              const SizedBox(height: 4),
                              Text(
                                _error!,
                                style: const TextStyle(fontSize: 11, color: Colors.red),
                                textAlign: TextAlign.center,
                              ),
                            ],
                          ),
                        )
                      : _buildChart(),
            ),

            const SizedBox(height: 12),

            // 关闭按钮
            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: () => Navigator.pop(context),
                child: const Text('Close'),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildChart() {
    // 过滤掉 null 值的数据点
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

    // 计算 Y 轴范围
    double minDb = -97;
    double maxDb = -22;
    for (final d in validData) {
      final db = (d['signal_db'] as num).toDouble();
      if (db < minDb) minDb = db;
      if (db > maxDb) maxDb = db;
    }
    // 留一些边距
    minDb -= 3;
    maxDb += 3;

    // 构建折线图数据点
    final spots = validData.map((d) {
      final hour = (d['hour'] as num).toDouble();
      final db = (d['signal_db'] as num).toDouble();
      return FlSpot(hour, db);
    }).toList();

    // 构建柱状图数据（用 bars 字段）
    final barData = validData.map((d) {
      final hour = (d['hour'] as num).toDouble();
      final bars = (d['bars'] as num?)?.toDouble() ?? 0;
      return BarChartGroupData(
        x: hour.toInt(),
        barRods: [
          BarChartRodData(
            toY: bars,
            color: _dbmToColor((d['signal_db'] as num).toDouble()).withValues(alpha: 0.6),
            width: 6,
            borderRadius: const BorderRadius.vertical(top: Radius.circular(2)),
          ),
        ],
      );
    }).toList();

    return Column(
      children: [
        // 信号强度折线图
        Expanded(
          flex: 3,
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
                topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
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
              ],
              lineTouchData: LineTouchData(
                touchTooltipData: LineTouchTooltipData(
                  getTooltipItems: (touchedSpots) {
                    return touchedSpots.map((spot) {
                      final db = spot.y;
                      final quality = _dbmToQuality(db);
                      return LineTooltipItem(
                        '${spot.x.toInt()}:00\n${db.toStringAsFixed(1)} dBm\n$quality',
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
          ),
        ),
        const SizedBox(height: 8),
        // 信号格数柱状图
        Expanded(
          flex: 2,
          child: BarChart(
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
                topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                leftTitles: AxisTitles(
                  sideTitles: SideTitles(
                    showTitles: true,
                    reservedSize: 20,
                    interval: 1,
                    getTitlesWidget: (value, meta) {
                      return Text(
                        '${value.toInt()}',
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
                    return BarTooltipItem(
                      '${group.x}:00\nBars: ${rod.toY.toInt()}\n${db.toStringAsFixed(1)} dBm',
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
          ),
        ),
      ],
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
