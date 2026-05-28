import 'package:flutter/material.dart';
import 'package:wifers_app/models/ap_info.dart';
import 'package:wifers_app/services/api_service.dart';

class PredictorPage extends StatefulWidget {
  final APInfo? selectedAp;

  const PredictorPage({super.key, this.selectedAp});

  @override
  State<PredictorPage> createState() => _PredictorPageState();
}

class _PredictorPageState extends State<PredictorPage> {
  final ApiService _apiService = ApiService();
  final _formKey = GlobalKey<FormState>();

  // v3: only use features available at inference time
  final _apNameController = TextEditingController();
  final _hourController = TextEditingController();

  Map<String, dynamic>? _predictionResult;
  bool _isLoading = false;
  bool _showManualForm = false;
  bool _feedbackSubmitted = false;
  bool _isSubmittingFeedback = false;


  @override
  void initState() {
    super.initState();
    if (widget.selectedAp != null) {
      _autoFillFeatures();
    }
  }

  void _autoFillFeatures() {
    final now = DateTime.now();
    _apNameController.text = widget.selectedAp!.name ?? '';
    _hourController.text = now.hour.toDouble().toStringAsFixed(0);
  }

  Map<String, dynamic> _buildFeatures() {
    final now = DateTime.now();
    final weekday = now.weekday; // 1=Mon, 7=Sun
    return {
      'ap_name': _apNameController.text.trim(),
      'hour': double.parse(_hourController.text),
      'day_of_week': (weekday - 1).toDouble(), // 0=Mon, 6=Sun
      'is_weekend': (weekday >= 6) ? 1.0 : 0.0,
      'month': now.month.toDouble(),
      'day_of_month': now.day.toDouble(),
    };
  }

  @override
  void dispose() {
    _apNameController.dispose();
    _hourController.dispose();
    super.dispose();
  }

  Future<void> _predictStatus() async {
    if (!_formKey.currentState!.validate()) return;

    setState(() {
      _isLoading = true;
      _predictionResult = null;
    });

    try {
      final features = _buildFeatures();
      final result = await _apiService.predictAPStatus(features);

      setState(() {
        _predictionResult = result;
      });
    } catch (e) {
      setState(() {
        _predictionResult = {'error': e.toString()};
      });
    } finally {
      setState(() {
        _isLoading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final hasAp = widget.selectedAp != null;

    return Scaffold(
      appBar: AppBar(
        title: const Text('WiFi AP Status Predictor'),
        backgroundColor: Theme.of(context).colorScheme.inversePrimary,
        actions: [
          if (!hasAp)
            IconButton(
              icon: Icon(
                _showManualForm ? Icons.visibility_off : Icons.developer_mode,
                size: 20,
              ),
              tooltip: _showManualForm ? 'Hide manual input' : 'Manual input',
              onPressed: () {
                setState(() {
                  _showManualForm = !_showManualForm;
                });
              },
            ),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16.0),
        child: Form(
          key: _formKey,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (hasAp) ...[
                Card(
                  color: Theme.of(context).colorScheme.primary.withAlpha(25),
                  margin: EdgeInsets.zero,
                  child: Padding(
                    padding: const EdgeInsets.all(12.0),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'Selected AP',
                          style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                        ),
                        const SizedBox(height: 8),
                        Text('AP: ${widget.selectedAp!.name}'),
                        Text('Building: ${widget.selectedAp!.building}'),
                        Text('Space: ${widget.selectedAp!.espacio ?? 'Unknown'}'),
                        Text('Coordinates: ${widget.selectedAp!.lat.toStringAsFixed(6)}, ${widget.selectedAp!.lng.toStringAsFixed(6)}'),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 16),

                // One-click predict button when AP is selected
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton.icon(
                    onPressed: _isLoading ? null : _predictStatus,
                    style: ElevatedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 16),
                      backgroundColor: Theme.of(context).colorScheme.primary,
                      foregroundColor: Theme.of(context).colorScheme.onPrimary,
                    ),
                    icon: _isLoading
                        ? const SizedBox(
                            width: 20,
                            height: 20,
                            child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                          )
                        : const Icon(Icons.auto_awesome),
                    label: Text(
                      _isLoading ? 'Predicting...' : 'Predict Status (Auto-filled)',
                      style: const TextStyle(fontSize: 16),
                    ),
                  ),
                ),
                const SizedBox(height: 24),

                // Show auto-filled values summary
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'Auto-filled Features (v3)',
                          style: TextStyle(fontWeight: FontWeight.bold, fontSize: 14),
                        ),
                        const SizedBox(height: 8),
                        _featureRow('AP Name', _apNameController.text),
                        _featureRow('Hour', _hourController.text),
                        const Text(
                          '  + day_of_week, is_weekend, month, day_of_month (auto)',
                          style: TextStyle(fontSize: 11, color: Colors.grey),
                        ),
                        const Text(
                          '  + building, floor, lat, lng (from GeoJSON)',
                          style: TextStyle(fontSize: 11, color: Colors.grey),
                        ),
                        const Text(
                          '  + predicted_signal_db (from signal model cascade)',
                          style: TextStyle(fontSize: 11, color: Colors.grey),
                        ),
                      ],
                    ),
                  ),
                ),
              ],

              // Manual form: shown when no AP selected (via debug icon) or always visible
              if (!hasAp && !_showManualForm)
                Padding(
                  padding: const EdgeInsets.only(top: 40),
                  child: Center(
                    child: Column(
                      children: [
                        Icon(
                          Icons.developer_mode,
                          size: 64,
                          color: Theme.of(context).colorScheme.outline,
                        ),
                        const SizedBox(height: 16),
                        Text(
                          'Tap the developer icon in the app bar\nto enter manual prediction mode.',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            color: Theme.of(context).colorScheme.outline,
                            fontSize: 14,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),

              if (hasAp || _showManualForm) ...[
                const SizedBox(height: 16),
                const Text(
                  'v3 Predictor - Only real available features',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 4),
                const Text(
                  'Removed fake defaults like client_count, cpu_utilization',
                  style: TextStyle(fontSize: 12, color: Colors.grey),
                ),
                const SizedBox(height: 20),

                // AP Name input
                TextFormField(
                  controller: _apNameController,
                  decoration: const InputDecoration(
                    labelText: 'AP Name',
                    hintText: 'e.g. AP-FTI02',
                    border: OutlineInputBorder(),
                  ),
                  validator: (value) {
                    if (value == null || value.trim().isEmpty) {
                      return 'Please enter AP name';
                    }
                    return null;
                  },
                ),
                const SizedBox(height: 16),

                // Hour input
                TextFormField(
                  controller: _hourController,
                  decoration: const InputDecoration(
                    labelText: 'Hour',
                    hintText: 'Enter hour (0-23)',
                    border: OutlineInputBorder(),
                  ),
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  validator: (value) {
                    if (value == null || value.isEmpty) {
                      return 'Please enter hour';
                    }
                    final parsed = double.tryParse(value);
                    if (parsed == null || parsed < 0 || parsed > 23) {
                      return 'Please enter a valid hour between 0 and 23';
                    }
                    return null;
                  },
                ),
                const SizedBox(height: 8),
                const Text(
                  'Other features (day_of_week, is_weekend, month, day_of_month) auto from system time',
                  style: TextStyle(fontSize: 11, color: Colors.grey),
                ),
                const SizedBox(height: 8),
                const Text(
                  'AP static features (building, floor, lat, lng) auto from GeoJSON database',
                  style: TextStyle(fontSize: 11, color: Colors.grey),
                ),
                const SizedBox(height: 8),
                const Text(
                  'Signal strength (predicted_signal_db) auto from signal model cascade',
                  style: TextStyle(fontSize: 11, color: Colors.grey),
                ),
                const SizedBox(height: 24),

                // Predict button
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton(
                    onPressed: _isLoading ? null : _predictStatus,
                    style: ElevatedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 16),
                    ),
                    child: _isLoading
                        ? const CircularProgressIndicator()
                        : const Text('Predict AP Status (v3)'),
                  ),
                ),
              ],

              const SizedBox(height: 24),

              // Results
              if (_predictionResult != null) ...[
                const Text(
                  'Prediction Result',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 12),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: _predictionResult!.containsKey('error')
                        ? Text(
                            'Error: ${_predictionResult!['error']}',
                            style: const TextStyle(color: Colors.red),
                          )
                        : Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                'Predicted Status: ${_predictionResult!['prediction']}',
                                style: const TextStyle(
                                  fontSize: 16,
                                  fontWeight: FontWeight.bold,
                                ),
                              ),
                              const SizedBox(height: 8),
                              Text(
                                'Confidence: ${(_predictionResult!['confidence'] * 100).toStringAsFixed(1)}%',
                              ),
                              const SizedBox(height: 8),
                              Text(
                                'Model: ${_predictionResult!['model_version'] ?? 'v3'}',
                                style: const TextStyle(fontSize: 12, color: Colors.grey),
                              ),
                              const SizedBox(height: 8),
                              if (_predictionResult!['ap_info'] != null) ...[
                                const Text(
                                  'AP Info:',
                                  style: TextStyle(fontWeight: FontWeight.bold),
                                ),
                                Text(
                                  '  ${_predictionResult!['ap_info']['name']} - '
                                  '${_predictionResult!['ap_info']['building']} '
                                  '(Floor ${_predictionResult!['ap_info']['floor']})',
                                  style: const TextStyle(fontSize: 12),
                                ),
                              ],
                              const SizedBox(height: 8),
                              if (_predictionResult!['features_used'] != null) ...[
                                const Text(
                                  'Features Used (v3 - all real available):',
                                  style: TextStyle(fontWeight: FontWeight.bold),
                                ),
                                Text(
                                  '  Time: ${_predictionResult!['features_used']['time']}',
                                  style: const TextStyle(fontSize: 11),
                                ),
                                Text(
                                  '  AP Static: ${_predictionResult!['features_used']['ap_static']}',
                                  style: const TextStyle(fontSize: 11),
                                ),
                                Text(
                                  '  Cascade Signal: ${_predictionResult!['features_used']['cascade']}',
                                  style: const TextStyle(fontSize: 11),
                                ),
                              ],
                              const SizedBox(height: 16),
                              const Divider(height: 1),
                              const SizedBox(height: 12),
                              // Feedback section
                              _buildFeedbackSection(),
                            ],
                          ),
                  ),
                ),
              ],

            ],
          ),
        ),
      ),
    );
  }

  Widget _buildFeedbackSection() {
    if (_feedbackSubmitted) {
      return Row(
        children: [
          const Icon(Icons.check_circle, color: Colors.green, size: 16),
          const SizedBox(width: 8),
          const Text(
            'Feedback submitted! Thank you.',
            style: TextStyle(color: Colors.green, fontSize: 12),
          ),
          const Spacer(),
          TextButton(
            onPressed: () => setState(() => _feedbackSubmitted = false),
            child: const Text('Submit again', style: TextStyle(fontSize: 11)),
          ),
        ],
      );
    }

    final prediction = _predictionResult?['prediction'] as String? ?? 'Up';
    final apName = _predictionResult?['ap_info']?['name'] as String? ?? _apNameController.text.trim();
    final hour = double.tryParse(_hourController.text)?.toInt() ?? DateTime.now().hour;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Was this prediction correct?',
          style: TextStyle(fontWeight: FontWeight.w500, fontSize: 13),
        ),
        const SizedBox(height: 8),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            SizedBox(
              width: 140,
              child: OutlinedButton.icon(
                onPressed: _isSubmittingFeedback
                    ? null
                    : () => _submitFeedback(apName, hour, prediction, 'Up'),
                icon: _isSubmittingFeedback
                    ? const SizedBox(
                        width: 14, height: 14,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.thumb_up, size: 16),
                label: const Text('Yes, Up', style: TextStyle(fontSize: 12)),
                style: OutlinedButton.styleFrom(
                  foregroundColor: Colors.green,
                  side: const BorderSide(color: Colors.green),
                ),
              ),
            ),
            SizedBox(
              width: 140,
              child: OutlinedButton.icon(
                onPressed: _isSubmittingFeedback
                    ? null
                    : () => _submitFeedback(apName, hour, prediction, 'Down'),
                icon: _isSubmittingFeedback
                    ? const SizedBox(
                        width: 14, height: 14,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.thumb_down, size: 16),
                label: const Text('No, Down', style: TextStyle(fontSize: 12)),
                style: OutlinedButton.styleFrom(
                  foregroundColor: Colors.red,
                  side: const BorderSide(color: Colors.red),
                ),
              ),
            ),
          ],
        ),
      ],
    );
  }

  Future<void> _submitFeedback(String apName, int hour, String predicted, String actual) async {
    setState(() => _isSubmittingFeedback = true);
    try {
      await _apiService.submitPredictionFeedback(
        apName: apName,
        hour: hour,
        predicted: predicted,
        actual: actual,
      );
      setState(() {
        _feedbackSubmitted = true;
        _isSubmittingFeedback = false;
      });
    } catch (e) {
      setState(() => _isSubmittingFeedback = false);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Failed to submit feedback: $e')),
        );
      }
    }
  }

  Widget _featureRow(String label, String value) {

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: const TextStyle(fontSize: 13)),
          Text(value, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w500)),
        ],
      ),
    );
  }
}
