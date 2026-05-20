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

  // Model feature input controllers
  final _clientCountController = TextEditingController();
  final _cpuUtilizationController = TextEditingController();
  final _memFreeController = TextEditingController();
  final _memTotalController = TextEditingController();
  final _lastModifiedController = TextEditingController();
  final _hourController = TextEditingController();
  final _memUsageController = TextEditingController();
  bool _overloaded = false;

  Map<String, dynamic>? _predictionResult;
  bool _isLoading = false;

  @override
  void initState() {
    super.initState();
    if (widget.selectedAp != null) {
      // The model uses AP runtime metrics, not static AP location metadata.
      // Pre-filling is not possible without a live metrics source.
    }
  }

  @override
  void dispose() {
    _clientCountController.dispose();
    _cpuUtilizationController.dispose();
    _memFreeController.dispose();
    _memTotalController.dispose();
    _lastModifiedController.dispose();
    _hourController.dispose();
    _memUsageController.dispose();
    super.dispose();
  }

  Future<void> _predictStatus() async {
    if (!_formKey.currentState!.validate()) return;

    setState(() {
      _isLoading = true;
      _predictionResult = null;
    });

    try {
      final features = {
        'client_count': int.parse(_clientCountController.text),
        'cpu_utilization': double.parse(_cpuUtilizationController.text),
        'mem_free': double.parse(_memFreeController.text),
        'mem_total': double.parse(_memTotalController.text),
        'last_modified': double.parse(_lastModifiedController.text),
        'hour': double.parse(_hourController.text),
        'mem_usage': double.parse(_memUsageController.text),
        'overloaded': _overloaded ? 1 : 0,
      };

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
    return Scaffold(
      appBar: AppBar(
        title: const Text('WiFi AP Status Predictor'),
        backgroundColor: Theme.of(context).colorScheme.inversePrimary,
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16.0),
        child: Form(
          key: _formKey,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (widget.selectedAp != null) ...[
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
                        Text('Building: ${widget.selectedAp!.building}'),
                        Text('Space: ${widget.selectedAp!.espacio ?? 'Unknown'}'),
                        Text('Coordinates: ${widget.selectedAp!.lat.toStringAsFixed(6)}, ${widget.selectedAp!.lng.toStringAsFixed(6)}'),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 16),
              ],
              const Text(
                'Enter AP Features for Status Prediction',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 20),

              // Client count input
              TextFormField(
                controller: _clientCountController,
                decoration: const InputDecoration(
                  labelText: 'Client Count',
                  hintText: 'Number of connected clients',
                  border: OutlineInputBorder(),
                ),
                keyboardType: TextInputType.number,
                validator: (value) {
                  if (value == null || value.isEmpty) {
                    return 'Please enter client count';
                  }
                  if (int.tryParse(value) == null) {
                    return 'Please enter a valid integer';
                  }
                  return null;
                },
              ),
              const SizedBox(height: 16),

              // CPU utilization input
              TextFormField(
                controller: _cpuUtilizationController,
                decoration: const InputDecoration(
                  labelText: 'CPU Utilization (%)',
                  hintText: 'Enter CPU utilization',
                  border: OutlineInputBorder(),
                ),
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                validator: (value) {
                  if (value == null || value.isEmpty) {
                    return 'Please enter CPU utilization';
                  }
                  if (double.tryParse(value) == null) {
                    return 'Please enter a valid number';
                  }
                  return null;
                },
              ),
              const SizedBox(height: 16),

              // Memory free input
              TextFormField(
                controller: _memFreeController,
                decoration: const InputDecoration(
                  labelText: 'Memory Free',
                  hintText: 'Enter free memory bytes',
                  border: OutlineInputBorder(),
                ),
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                validator: (value) {
                  if (value == null || value.isEmpty) {
                    return 'Please enter free memory';
                  }
                  if (double.tryParse(value) == null) {
                    return 'Please enter a valid number';
                  }
                  return null;
                },
              ),
              const SizedBox(height: 16),

              // Memory total input
              TextFormField(
                controller: _memTotalController,
                decoration: const InputDecoration(
                  labelText: 'Memory Total',
                  hintText: 'Enter total memory bytes',
                  border: OutlineInputBorder(),
                ),
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                validator: (value) {
                  if (value == null || value.isEmpty) {
                    return 'Please enter total memory';
                  }
                  if (double.tryParse(value) == null) {
                    return 'Please enter a valid number';
                  }
                  return null;
                },
              ),
              const SizedBox(height: 16),

              // Last modified timestamp input
              TextFormField(
                controller: _lastModifiedController,
                decoration: const InputDecoration(
                  labelText: 'Last Modified (Unix)',
                  hintText: 'Enter unix timestamp',
                  border: OutlineInputBorder(),
                ),
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                validator: (value) {
                  if (value == null || value.isEmpty) {
                    return 'Please enter last modified timestamp';
                  }
                  if (double.tryParse(value) == null) {
                    return 'Please enter a valid timestamp';
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
              const SizedBox(height: 16),

              // Memory usage input
              TextFormField(
                controller: _memUsageController,
                decoration: const InputDecoration(
                  labelText: 'Memory Usage (%)',
                  hintText: 'Enter memory usage percentage',
                  border: OutlineInputBorder(),
                ),
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                validator: (value) {
                  if (value == null || value.isEmpty) {
                    return 'Please enter memory usage';
                  }
                  if (double.tryParse(value) == null) {
                    return 'Please enter a valid number';
                  }
                  return null;
                },
              ),
              const SizedBox(height: 16),

              // Overloaded switch
              SwitchListTile(
                title: const Text('Overloaded'),
                value: _overloaded,
                onChanged: (value) {
                  setState(() {
                    _overloaded = value;
                  });
                },
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
                      : const Text('Predict AP Status'),
                ),
              ),
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
                              const Text(
                                'Features Used:',
                                style: TextStyle(fontWeight: FontWeight.bold),
                              ),
                              Text(
                                '${_predictionResult!['features_used']}',
                                style: const TextStyle(fontSize: 12),
                              ),
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
}