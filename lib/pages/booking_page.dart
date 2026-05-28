import 'package:flutter/material.dart';
import 'package:wifers_app/services/api_service.dart' show ApiService, ApiException;
import 'package:wifers_app/models/booking.dart';

class BookingPage extends StatefulWidget {
  final bool showAppBar;

  const BookingPage({super.key, this.showAppBar = true});
  @override
  State<BookingPage> createState() => _BookingPageState();
}

class _BookingPageState extends State<BookingPage> {
  final _api = ApiService();
  final _teacherIdController = TextEditingController();
  final _roomCodeController = TextEditingController();
  final _nStudentsController = TextEditingController(text: '30');

  DateTime _selectedDate = DateTime.now();
  int _startHour = 10;
  int _endHour = 12;
  String _minPerformance = 'Fair';
  bool _loading = false;
  bool _myBookingsLoading = false;
  String _status = '';

  // Booking results
  List<Booking> _myBookings = [];
  bool _showMyBookings = false;

  // Prediction result
  String? _predictedPerformance;
  String? _predictionWarning;

  // Alternatives
  List<AlternativeRoom> _alternatives = [];
  bool _showAlternatives = false;

  // Availability grid
  List<HourAvailability> _availabilityHours = [];
  bool _availabilityLoading = false;

  static const _perfOptions = ['Fair', 'Good', 'Excellent'];
  static const _perfColors = {
    'Fair': Colors.orange,
    'Good': Colors.lightGreen,
    'Excellent': Colors.green,
  };

  @override
  void initState() {
    super.initState();
    _selectedDate = _selectedDate.add(const Duration(days: 1));
  }

  @override
  void dispose() {
    _teacherIdController.dispose();
    _roomCodeController.dispose();
    _nStudentsController.dispose();
    super.dispose();
  }

  String _formatDate(DateTime d) =>
      '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  Future<void> _loadMyBookings() async {
    final tid = _teacherIdController.text.trim();
    if (tid.isEmpty) {
      _showSnackBar('Please enter a Teacher ID first');
      return;
    }
    setState(() => _myBookingsLoading = true);
    try {
      final resp = await _api.listBookings(teacherId: tid);
      final list = (resp['bookings'] as List)
          .map((b) => Booking.fromJson(b as Map<String, dynamic>))
          .toList();
      setState(() {
        _myBookings = list;
        _showMyBookings = true;
        _status = '${list.length} booking(s) found';
      });
    } on ApiException catch (e) {
      _showSnackBar('Failed to load bookings: ${e.message}');
    } catch (e) {
      _showSnackBar('Failed to load bookings: $e');
    } finally {
      setState(() => _myBookingsLoading = false);
    }
  }

  Future<void> _checkAndBook() async {
    final roomCode = _roomCodeController.text.trim().toUpperCase();
    final teacherId = _teacherIdController.text.trim();
    final nStudentsStr = _nStudentsController.text.trim();

    if (teacherId.isEmpty) {
      _showSnackBar('Please enter a Teacher ID');
      return;
    }
    if (roomCode.isEmpty) {
      _showSnackBar('Please enter a Room Code');
      return;
    }
    final nStudents = int.tryParse(nStudentsStr) ?? 30;
    if (nStudents < 1 || nStudents > 200) {
      _showSnackBar('Students must be between 1 and 200');
      return;
    }
    if (_endHour <= _startHour) {
      _showSnackBar('End time must be after start time');
      return;
    }

    setState(() {
      _loading = true;
      _status = 'Checking availability & predicting...';
      _predictedPerformance = null;
      _predictionWarning = null;
      _alternatives = [];

      _showAlternatives = false;
    });

    try {
      // First predict to check availability and performance
      final predResp = await _api.predictBooking(
        roomCode: roomCode,
        date: _formatDate(_selectedDate),
        startHour: _startHour,
        endHour: _endHour,
        nStudents: nStudents,
      );

      final available = predResp['available'] as bool? ?? false;
      final perf = predResp['prediction']?['performance'] as String?;
      final warning = predResp['prediction']?['warning'] as String?;

      setState(() {
        _predictedPerformance = perf;
        _predictionWarning = warning;
      });


      if (!available) {
        final conflict = predResp['conflict'];
        if (conflict != null) {
          _showSnackBar(
            'Room already booked ${conflict['start_hour']}:00-${conflict['end_hour']}:00',
          );
        }
        setState(() => _status = 'Room not available for this time slot');
        return;
      }

      if (perf == null && warning != null) {
        // Prediction not available but room is free - allow booking anyway
        setState(() => _status = 'Warning: $warning');
      }

      // Check if performance meets minimum
      bool perfTooLow = false;
      if (perf != null) {
        final perfRank = {'Very Poor': 0, 'Weak': 1, 'Fair': 2, 'Good': 3, 'Excellent': 4};
        final minRank = perfRank[_minPerformance] ?? 2;
        final actualRank = perfRank[perf] ?? 0;

        if (actualRank < minRank) {
          perfTooLow = true;
          setState(() {
            _status =
                'Predicted performance ($perf) is below minimum ($_minPerformance). Consider alternatives.';
          });
          _showSnackBar(
            'Performance too low. Try alternatives below.',
            isError: true,
          );
          // Load alternatives automatically
          _loadAlternatives();
        }
      }

      if (perfTooLow) return;

      // Proceed to create booking
      final createResp = await _api.createBooking(
        teacherId: teacherId,
        roomCode: roomCode,
        date: _formatDate(_selectedDate),
        startHour: _startHour,
        endHour: _endHour,
        nStudents: nStudents,
        minPerformance: _minPerformance,
      );

      final booking = Booking.fromJson(
          createResp['booking'] as Map<String, dynamic>);

      setState(() {
        _status =
            '✅ Booking confirmed! ID: ${booking.bookingId}';
      });

      _showSuccessDialog(booking);
    } on ApiException catch (e) {
      if (e.statusCode == 409) {
        _showSnackBar('Room already booked for this time slot');
        setState(() => _status = 'Conflict: Room already booked');
      } else {
        _showSnackBar('Booking failed: ${e.message}');
        setState(() => _status = 'Failed: ${e.message}');
      }
    } catch (e) {
      _showSnackBar('Error: $e');
      setState(() => _status = 'Error: $e');
    } finally {
      setState(() => _loading = false);
    }
  }

  Future<void> _loadAvailability() async {
    final roomCode = _roomCodeController.text.trim().toUpperCase();
    if (roomCode.isEmpty) return;

    setState(() => _availabilityLoading = true);
    try {
      final resp = await _api.getBookingAvailability(
        roomCode,
        _formatDate(_selectedDate),
      );
      final hours = (resp['hours'] as List)
          .map((h) => HourAvailability.fromJson(h as Map<String, dynamic>))
          .toList();
      setState(() => _availabilityHours = hours);
    } catch (e) {
      // Silently fail – availability is non-critical
    } finally {
      setState(() => _availabilityLoading = false);
    }
  }

  Future<void> _loadAlternatives() async {
    final roomCode = _roomCodeController.text.trim().toUpperCase();
    final nStudents = int.tryParse(_nStudentsController.text.trim()) ?? 30;

    try {
      final resp = await _api.findAlternatives(
        roomCode: roomCode,
        date: _formatDate(_selectedDate),
        startHour: _startHour,
        endHour: _endHour,
        nStudents: nStudents,
        minPerformance: _minPerformance,
      );
      final list = (resp['alternatives'] as List)
          .map((a) => AlternativeRoom.fromJson(a as Map<String, dynamic>))
          .toList();
      setState(() {
        _alternatives = list;
        _showAlternatives = true;
      });
    } on ApiException catch (e) {
      _showSnackBar('Failed to find alternatives: ${e.message}');
    } catch (e) {
      _showSnackBar('Failed to find alternatives: $e');
    }
  }

  Future<void> _cancelBooking(String bookingId) async {
    try {
      await _api.cancelBooking(bookingId);
      _showSnackBar('Booking cancelled');
      await _loadMyBookings();
    } on ApiException catch (e) {
      _showSnackBar('Failed to cancel: ${e.message}');
    } catch (e) {
      _showSnackBar('Failed to cancel: $e');
    }
  }

  void _showSuccessDialog(Booking booking) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Row(
          children: [
            Icon(Icons.check_circle, color: Colors.green, size: 28),
            SizedBox(width: 8),
            Text('Booking Confirmed'),
          ],
        ),
        content: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              _infoRow('Booking ID', booking.bookingId),
              _infoRow('Room', booking.roomCode),
              _infoRow('AP', booking.apName),
              _infoRow('Date', booking.date),
              _infoRow(
                  'Time', '${booking.startHour}:00-${booking.endHour}:00'),
              _infoRow('Students', '${booking.nStudents}'),
              _infoRow('Min. Performance', booking.minPerformance),
              if (booking.predictedPerformance != null)
                _infoRow(
                    'Predicted', booking.predictedPerformance!),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('OK'),
          ),
        ],
      ),
    );
  }

  Widget _infoRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 120,
            child: Text(label,
                style: TextStyle(
                    fontWeight: FontWeight.w500, color: Colors.grey[700])),
          ),
          Expanded(child: Text(value)),
        ],
      ),
    );
  }

  Widget _availabilityDot(Color color, String label) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 10, height: 10,
          decoration: BoxDecoration(
            color: color,
            shape: BoxShape.circle,
          ),
        ),
        const SizedBox(width: 4),
        Text(label, style: const TextStyle(fontSize: 11)),
      ],
    );
  }

  void _showSnackBar(String msg, {bool isError = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(msg),
        backgroundColor: isError ? Colors.red[700] : null,
        duration: const Duration(seconds: 3),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: widget.showAppBar
          ? AppBar(
              title: const Text('Room Booking'),
              backgroundColor: Theme.of(context).colorScheme.inversePrimary,
              actions: [
                IconButton(
                  icon: Icon(
                      _showMyBookings ? Icons.list : Icons.person_search),
                  tooltip: 'My Bookings',
                  onPressed: _myBookingsLoading ? null : _loadMyBookings,
                ),
              ],
            )
          : null,
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Teacher ID
            TextField(
              controller: _teacherIdController,
              decoration: const InputDecoration(
                labelText: 'Teacher ID',
                hintText: 'e.g. teacher@uab.cat',
                prefixIcon: Icon(Icons.person),
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),

            // Room code
            TextField(
              controller: _roomCodeController,
              decoration: const InputDecoration(
                labelText: 'Room Code',
                hintText: 'e.g. Q4/1007',
                prefixIcon: Icon(Icons.meeting_room),
                border: OutlineInputBorder(),
              ),
              textCapitalization: TextCapitalization.characters,
              onChanged: (_) => setState(() => _availabilityHours = []),
            ),
            const SizedBox(height: 12),

            // Date picker
            InkWell(
              onTap: () async {
                final picked = await showDatePicker(
                  context: context,
                  initialDate: _selectedDate,
                  firstDate: DateTime.now(),
                  lastDate: DateTime.now().add(const Duration(days: 60)),
                );
                if (picked != null) {
                  setState(() {
                    _selectedDate = picked;
                    _availabilityHours = [];
                  });
                }
              },
              child: InputDecorator(
                decoration: const InputDecoration(
                  labelText: 'Date',
                  prefixIcon: Icon(Icons.calendar_today),
                  border: OutlineInputBorder(),
                ),
                child: Text(_formatDate(_selectedDate)),
              ),
            ),
            const SizedBox(height: 12),

            // Start/End hour
            Row(
              children: [
                Expanded(
                  child: DropdownButtonFormField<int>(
                    value: _startHour,
                    decoration: const InputDecoration(
                      labelText: 'Start',
                      border: OutlineInputBorder(),
                    ),
                    items: List.generate(15, (i) => i + 7)
                        .map((h) => DropdownMenuItem(
                            value: h, child: Text('${h.toString().padLeft(2, '0')}:00')))
                        .toList(),
                    onChanged: (v) {
                      if (v != null) {
                        setState(() {
                          _startHour = v;
                          if (_endHour <= v) _endHour = v + 1;
                        });
                      }
                    },
                  ),
                ),
                const Padding(
                  padding: EdgeInsets.symmetric(horizontal: 8),
                  child: Text('to', style: TextStyle(fontSize: 16)),
                ),
                Expanded(
                  child: DropdownButtonFormField<int>(
                    value: _endHour,
                    decoration: const InputDecoration(
                      labelText: 'End',
                      border: OutlineInputBorder(),
                    ),
                    items: List.generate(15, (i) => i + 8)
                        .map((h) => DropdownMenuItem(
                            value: h, child: Text('${h.toString().padLeft(2, '0')}:00')))
                        .toList(),
                    onChanged: (v) {
                      if (v != null) setState(() => _endHour = v);
                    },
                  ),
                ),

              ],
            ),
            const SizedBox(height: 12),

            // Number of students
            TextField(
              controller: _nStudentsController,
              decoration: const InputDecoration(
                labelText: 'Number of Students',
                prefixIcon: Icon(Icons.people),
                border: OutlineInputBorder(),
              ),
              keyboardType: TextInputType.number,
            ),
            const SizedBox(height: 12),

            // Min performance
            DropdownButtonFormField<String>(
              value: _minPerformance,
              decoration: const InputDecoration(
                labelText: 'Minimum Acceptable Performance',
                prefixIcon: Icon(Icons.signal_wifi_4_bar),
                border: OutlineInputBorder(),
              ),
              items: _perfOptions
                  .map((p) => DropdownMenuItem(
                      value: p,
                      child: Row(
                        children: [
                          Icon(Icons.circle,
                              size: 12, color: _perfColors[p]),
                          const SizedBox(width: 8),
                          Text(p),
                        ],
                      )))
                  .toList(),
              onChanged: (v) {
                if (v != null) setState(() => _minPerformance = v);
              },
            ),

            const SizedBox(height: 12),

            // Availability grid
            if (_roomCodeController.text.trim().isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Row(
                  children: [
                    OutlinedButton.icon(
                      onPressed: _availabilityLoading ? null : _loadAvailability,
                      icon: _availabilityLoading
                          ? const SizedBox(
                              width: 16, height: 16,
                              child: CircularProgressIndicator(strokeWidth: 2))
                          : const Icon(Icons.calendar_view_week, size: 18),
                      label: const Text('Show Availability'),
                    ),
                    if (_availabilityHours.isNotEmpty)
                      Padding(
                        padding: const EdgeInsets.only(left: 8),
                        child: Text(
                          '${_availabilityHours.where((h) => h.available).length} free slots',
                          style: TextStyle(fontSize: 12, color: Colors.grey[600]),
                        ),
                      ),
                  ],
                ),
              ),

            // Availability grid display
            if (_availabilityHours.isNotEmpty)
              Container(
                margin: const EdgeInsets.only(bottom: 8),
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: Colors.grey[50],
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: Colors.grey[300]!),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        const Text('Slot Availability',
                            style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
                        const Spacer(),
                        Row(
                          children: [
                            _availabilityDot(Colors.green, 'Free'),
                            const SizedBox(width: 8),
                            _availabilityDot(Colors.red, 'Booked'),
                          ],
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    SingleChildScrollView(
                      scrollDirection: Axis.horizontal,
                      child: Row(
                        children: _availabilityHours.map((h) {
                          final isSelected = h.hour >= _startHour && h.hour < _endHour;
                          return Padding(
                            padding: const EdgeInsets.only(right: 4),
                            child: GestureDetector(
                              onTap: h.available
                                  ? () {
                                      setState(() {
                                        _startHour = h.hour;
                                        _endHour = h.hour + 1;
                                      });
                                    }
                                  : null,
                              child: Container(
                                width: 36,
                                padding: const EdgeInsets.symmetric(vertical: 6),
                                decoration: BoxDecoration(
                                  color: isSelected
                                      ? Colors.indigo
                                      : h.available
                                          ? Colors.green[100]
                                          : Colors.red[100],
                                  borderRadius: BorderRadius.circular(6),
                                  border: isSelected
                                      ? Border.all(color: Colors.indigo[800]!, width: 2)
                                      : null,
                                ),
                                child: Column(
                                  children: [
                                    Text(
                                      '${h.hour.toString().padLeft(2, '0')}',
                                      style: TextStyle(
                                        fontSize: 11,
                                        fontWeight: isSelected ? FontWeight.bold : FontWeight.normal,
                                        color: isSelected
                                            ? Colors.white
                                            : h.available
                                                ? Colors.green[800]
                                                : Colors.red[800],
                                      ),
                                    ),
                                    Text(
                                      h.available ? '🟢' : '🔴',
                                      style: const TextStyle(fontSize: 10),
                                    ),
                                  ],
                                ),
                              ),
                            ),
                          );
                        }).toList(),
                      ),
                    ),
                  ],
                ),
              ),

            const SizedBox(height: 8),

            // Check & Book button
            SizedBox(
              width: double.infinity,
              child: ElevatedButton.icon(
                onPressed: _loading ? null : _checkAndBook,
                icon: _loading
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(strokeWidth: 2))
                    : const Icon(Icons.book_online),
                label: Text(_loading ? 'Processing...' : 'Check & Book'),
                style: ElevatedButton.styleFrom(
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  backgroundColor: Colors.indigo,
                  foregroundColor: Colors.white,
                ),
              ),
            ),
            const SizedBox(height: 8),

            // Status
            if (_status.isNotEmpty)
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                margin: const EdgeInsets.only(bottom: 8),
                decoration: BoxDecoration(
                  color: _status.startsWith('✅')
                      ? Colors.green[50]
                      : _status.startsWith('Error') ||
                              _status.startsWith('Failed')
                          ? Colors.red[50]
                          : Colors.blue[50],
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(_status,
                    style: TextStyle(
                      color: _status.startsWith('✅')
                          ? Colors.green[800]
                          : _status.startsWith('Error') ||
                                  _status.startsWith('Failed')
                              ? Colors.red[800]
                              : Colors.blue[800],
                    )),
              ),

            // Prediction result
            if (_predictedPerformance != null || _predictionWarning != null)
              Card(
                margin: const EdgeInsets.only(bottom: 8),
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('Prediction',
                          style: TextStyle(fontWeight: FontWeight.w600)),
                      const SizedBox(height: 4),
                      if (_predictedPerformance != null)
                        Row(children: [
                          Icon(Icons.signal_wifi_4_bar,
                              size: 18,
                              color: _perfColors[_predictedPerformance] ??
                                  Colors.grey),
                          const SizedBox(width: 8),
                          Text('Performance: $_predictedPerformance',
                              style: const TextStyle(fontSize: 14)),
                        ]),
                      if (_predictionWarning != null)
                        Row(children: [
                          const Icon(Icons.warning_amber,
                              size: 18, color: Colors.orange),
                          const SizedBox(width: 8),
                          Expanded(
                            child: Text(_predictionWarning!,
                                style: const TextStyle(
                                    fontSize: 13, color: Colors.orange)),
                          ),
                        ]),
                    ],
                  ),
                ),
              ),

            // Alternatives
            if (_showAlternatives && _alternatives.isNotEmpty)
              Card(
                margin: const EdgeInsets.only(bottom: 8),
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          const Icon(Icons.swap_horiz,
                              size: 18, color: Colors.teal),
                          const SizedBox(width: 8),
                          const Text('Alternative Rooms',
                              style: TextStyle(fontWeight: FontWeight.w600)),
                          const Spacer(),
                          Text('${_alternatives.length} found',
                              style: TextStyle(
                                  fontSize: 12, color: Colors.grey[600])),
                        ],
                      ),
                      const SizedBox(height: 8),
                      ..._alternatives.map((alt) => Padding(
                            padding: const EdgeInsets.symmetric(vertical: 4),
                            child: Row(
                              children: [
                                Icon(Icons.meeting_room,
                                    size: 16, color: Colors.teal[400]),
                                const SizedBox(width: 8),
                                Expanded(
                                    child: Text(alt.roomCode,
                                        style:
                                            const TextStyle(fontSize: 14))),
                                Container(
                                  padding: const EdgeInsets.symmetric(
                                      horizontal: 8, vertical: 2),
                                  decoration: BoxDecoration(
                                    color: (_perfColors[alt.performance] ??
                                            Colors.grey)
                                        .withValues(alpha: 0.15),
                                    borderRadius: BorderRadius.circular(12),
                                  ),
                                  child: Text(
                                    alt.performance,
                                    style: TextStyle(
                                      fontSize: 12,
                                      color: _perfColors[alt.performance] ??
                                          Colors.grey,
                                      fontWeight: FontWeight.w500,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          )),
                    ],
                  ),
                ),
              ),

            // My Bookings section
            if (_showMyBookings) ...[
              const Divider(),
              Row(
                children: [
                  const Text('My Bookings',
                      style: TextStyle(
                          fontWeight: FontWeight.w600, fontSize: 16)),
                  const Spacer(),
                  if (_myBookings.isNotEmpty)
                    Text('${_myBookings.length} total',
                        style: TextStyle(color: Colors.grey[600])),
                  IconButton(
                    icon: const Icon(Icons.close, size: 20),
                    onPressed: () =>
                        setState(() => _showMyBookings = false),
                  ),
                ],
              ),
              if (_myBookings.isEmpty)
                const Padding(
                  padding: EdgeInsets.all(16),
                  child: Center(
                    child: Text('No bookings yet',
                        style: TextStyle(color: Colors.grey)),
                  ),
                )
              else
                ..._myBookings.map((b) => Card(
                      margin: const EdgeInsets.symmetric(vertical: 4),
                      child: ListTile(
                        dense: true,
                        leading: CircleAvatar(
                          backgroundColor: Colors.indigo[50],
                          radius: 18,
                          child: Text(
                            b.bookingId.length >= 3
                                ? b.bookingId.substring(0, 3)
                                : b.bookingId,
                            style: TextStyle(
                                fontSize: 11,
                                fontWeight: FontWeight.bold,
                                color: Colors.indigo[700]),
                          ),
                        ),
                        title: Text('${b.roomCode} • ${b.apName}',
                            style: const TextStyle(fontSize: 13)),
                        subtitle: Text(
                          '${b.date} • ${b.startHour}:00-${b.endHour}:00 • ${b.nStudents} students',
                          style: const TextStyle(fontSize: 11),
                        ),
                        trailing: SizedBox(
                          width: 90,
                          child: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              if (b.predictedPerformance != null)
                                Flexible(
                                  child: Container(
                                    padding: const EdgeInsets.symmetric(
                                        horizontal: 4, vertical: 2),
                                    decoration: BoxDecoration(
                                      color: (_perfColors[b.predictedPerformance] ??
                                              Colors.grey)
                                          .withValues(alpha: 0.15),
                                      borderRadius: BorderRadius.circular(8),
                                    ),
                                    child: Text(
                                      b.predictedPerformance!,
                                      style: TextStyle(
                                        fontSize: 10,
                                        color: _perfColors[
                                            b.predictedPerformance],
                                        fontWeight: FontWeight.w500,
                                      ),
                                      overflow: TextOverflow.ellipsis,
                                    ),
                                  ),
                                ),
                              const SizedBox(width: 2),
                              IconButton(
                                icon: const Icon(Icons.cancel_outlined,
                                    size: 18, color: Colors.red),
                                onPressed: () => _cancelBooking(b.bookingId),
                                constraints: const BoxConstraints(minWidth: 28, minHeight: 28),
                                padding: EdgeInsets.zero,
                              ),
                            ],
                          ),
                        ),
                      ),
                    )),
            ],
          ],
        ),
      ),
    );
  }
}
