class APInfo {
  final double lng;
  final double lat;
  final String building;
  final int? height;
  final String? espacio;

  APInfo({
    required this.lng,
    required this.lat,
    required this.building,
    this.height,
    this.espacio,
  });

  factory APInfo.fromJson(Map<String, dynamic> json) {
    return APInfo(
      lng: (json['lng'] as num).toDouble(),
      lat: (json['lat'] as num).toDouble(),
      building: json['building'] as String,
      height: json['height'] as int?,
      espacio: json['espacio'] as String?,
    );
  }
}