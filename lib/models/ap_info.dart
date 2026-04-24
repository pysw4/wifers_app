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
  final String? id;       // 如果有唯一ID更好，这里假设使用经纬度组合作为标识
  final double lat;
  final double lng;
  final String building;
  final int? height;
  final String? espacio;

  APInfo({
    this.id,
    required this.lat,
    required this.lng,
    required this.building,
    this.height,
    this.espacio,
  });

  // 从 JSON 构造
  factory APInfo.fromJson(Map<String, dynamic> json) {
    return APInfo(
      id: json['id'] as String?,
      lat: (json['lat'] as num).toDouble(),
      lng: (json['lng'] as num).toDouble(),
      building: json['building'] as String,
      height: json['height'] as int?,
      espacio: json['espacio'] as String?,
    );
  }

  // 转换为 JSON
  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'lat': lat,
      'lng': lng,
      'building': building,
      'height': height,
      'espacio': espacio,
    };
  }
  
  // 生成唯一键（如果没有 id 则用坐标）
  String get uniqueKey => id ?? '${lat}_$lng';
}