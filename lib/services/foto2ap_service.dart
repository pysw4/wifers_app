import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

/// Result of a Foto2AP recognition request.
class Foto2ApResult {
  final bool success;
  final String? apName;
  final double? lat;
  final double? lng;
  final String? building;
  final int? floor;
  final String? espacio;
  final String? errorMessage;

  Foto2ApResult({
    required this.success,
    this.apName,
    this.lat,
    this.lng,
    this.building,
    this.floor,
    this.espacio,
    this.errorMessage,
  });

  factory Foto2ApResult.fromJson(Map<String, dynamic> json) {
    return Foto2ApResult(
      success: json['success'] as bool? ?? false,
      apName: json['ap_name'] as String?,
      lat: (json['lat'] as num?)?.toDouble(),
      lng: (json['lng'] as num?)?.toDouble(),
      building: json['building'] as String?,
      floor: json['floor'] as int?,
      espacio: json['espacio'] as String?,
      errorMessage: json['message'] as String?,
    );
  }
}

/// Service to recognise AP names from photos using the backend OCR endpoint.
class Foto2ApService {
  static const String _baseUrl = 'https://wifers-app-api.onrender.com';

  /// Upload an image file and recognise the AP in it.
  ///
  /// [imagePath] — local path to the image file (JPEG/PNG).
  /// Returns a [Foto2ApResult] with the recognised AP info.
  static Future<Foto2ApResult> recognizeAp(String imagePath) async {
    try {
      final uri = Uri.parse('$_baseUrl/foto2ap/recognize');
      final request = http.MultipartRequest('POST', uri);

      // Attach the image file
      request.files.add(
        await http.MultipartFile.fromPath('file', imagePath),
      );

      final streamedResponse = await request.send();
      final response = await http.Response.fromStream(streamedResponse);

      if (response.statusCode == 200) {
        final json = jsonDecode(response.body) as Map<String, dynamic>;
        return Foto2ApResult.fromJson(json);
      } else if (response.statusCode == 404) {
        final json = jsonDecode(response.body) as Map<String, dynamic>;
        return Foto2ApResult(
          success: false,
          errorMessage: json['message'] as String? ?? 'No AP recognised',
        );
      } else {
        return Foto2ApResult(
          success: false,
          errorMessage: 'Server error (${response.statusCode})',
        );
      }
    } on SocketException {
      return Foto2ApResult(
        success: false,
        errorMessage: 'Network error: could not reach server',
      );
    } catch (e) {
      return Foto2ApResult(
        success: false,
        errorMessage: 'Error: $e',
      );
    }
  }
}
