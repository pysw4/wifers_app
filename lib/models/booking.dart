class Booking {
  final String bookingId;
  final String teacherId;
  final String roomCode;
  final String apName;
  final String date;
  final int startHour;
  final int endHour;
  final int nStudents;
  final String minPerformance;
  final String? predictedPerformance;

  Booking({
    required this.bookingId,
    required this.teacherId,
    required this.roomCode,
    required this.apName,
    required this.date,
    required this.startHour,
    required this.endHour,
    required this.nStudents,
    required this.minPerformance,
    this.predictedPerformance,
  });

  factory Booking.fromJson(Map<String, dynamic> json) {
    return Booking(
      bookingId: json['booking_id'] as String,
      teacherId: json['teacher_id'] as String,
      roomCode: json['room_code'] as String,
      apName: json['ap_name'] as String,
      date: json['date'] as String,
      startHour: json['start_hour'] as int,
      endHour: json['end_hour'] as int,
      nStudents: json['n_students'] as int,
      minPerformance: json['min_performance'] as String,
      predictedPerformance: json['predicted_performance'] as String?,
    );
  }

  Map<String, dynamic> toJson() => {
    'booking_id': bookingId,
    'teacher_id': teacherId,
    'room_code': roomCode,
    'ap_name': apName,
    'date': date,
    'start_hour': startHour,
    'end_hour': endHour,
    'n_students': nStudents,
    'min_performance': minPerformance,
    'predicted_performance': predictedPerformance,
  };
}

class BookingPrediction {
  final String apName;
  final String? performance;
  final String? warning;

  BookingPrediction({
    required this.apName,
    this.performance,
    this.warning,
  });

  factory BookingPrediction.fromJson(Map<String, dynamic> json) {
    return BookingPrediction(
      apName: json['ap_name'] as String,
      performance: json['performance'] as String?,
      warning: json['warning'] as String?,
    );
  }
}

class AlternativeRoom {
  final String roomCode;
  final String performance;

  AlternativeRoom({required this.roomCode, required this.performance});

  factory AlternativeRoom.fromJson(Map<String, dynamic> json) {
    return AlternativeRoom(
      roomCode: json['room_code'] as String,
      performance: json['performance'] as String,
    );
  }
}

class BestSlot {
  final int startHour;
  final int endHour;
  final String performance;

  BestSlot({
    required this.startHour,
    required this.endHour,
    required this.performance,
  });

  factory BestSlot.fromJson(Map<String, dynamic> json) {
    return BestSlot(
      startHour: json['start_hour'] as int,
      endHour: json['end_hour'] as int,
      performance: json['performance'] as String,
    );
  }
}
