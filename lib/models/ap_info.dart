// class APInfo {
//   final double lng;
//   final double lat;
//   final String building;
//   final int? height;
//   final String? espacio;

//   APInfo({
//     required this.lng,
//     required this.lat,
//     required this.building,
//     this.height,
//     this.espacio,
//   });

//   factory APInfo.fromJson(Map<String, dynamic> json) {
//     return APInfo(
//       lng: (json['lng'] as num).toDouble(),
//       lat: (json['lat'] as num).toDouble(),
//       building: json['building'] as String,
//       height: json['height'] as int?,
//       espacio: json['espacio'] as String?,
//     );
//   }
// }
class APInfo {
  final String? id;       // Better to have unique ID, here we assume lat/lng combination as identifier
  final double lat;
  final double lng;
  final String building;
  final String? name;
  final int? height;
  final String? espacio;
  final double? signalStrength; // Added signal strength field

  APInfo({
    this.id,
    required this.lat,
    required this.lng,
    required this.building,
    this.name,
    this.height,
    this.espacio,
    this.signalStrength,
  });

  // Construct from JSON
  factory APInfo.fromJson(Map<String, dynamic> json) {
    return APInfo(
      id: json['id'] as String?,
      lat: (json['lat'] as num).toDouble(),
      lng: (json['lng'] as num).toDouble(),
      building: json['building'] as String,
      name: json['name'] as String?,
      height: json['height'] as int?,
      espacio: json['espacio'] as String?,
      signalStrength: json['signalStrength'] as double?, // added
    );
  }

  // Convert to JSON
  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'lat': lat,
      'lng': lng,
      'building': building,
      'name': name,
      'height': height,
      'espacio': espacio,
      'signalStrength': signalStrength,
    };
  }
  
  // Generate unique key (coordinate fallback when no id)
  String get uniqueKey => id ?? '${lat}_$lng';
}