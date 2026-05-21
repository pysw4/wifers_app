import 'package:geolocator/geolocator.dart';
import 'package:latlong2/latlong.dart';

class LocationService {
  // UAB campus center and radius
  static const double _campusCenterLat = 41.503;
  static const double _campusCenterLng = 2.105;
  static const double _campusRadiusKm = 1.2;
  static final LatLng _campusCenter = LatLng(_campusCenterLat, _campusCenterLng);

  // UAB Engineering School main entrance (door_main in helper_script.py)
  static const double campusGateLat = 41.500182;
  static const double campusGateLng = 2.111848;
  static final LatLng campusGate = LatLng(campusGateLat, campusGateLng);

  /// Check if the given location is near the UAB campus.
  static bool isNearCampus(LatLng location) {
    final distance = const Distance().as(
      LengthUnit.Kilometer,
      location,
      _campusCenter,
    );
    return distance <= _campusRadiusKm;
  }

  /// Check if the given coordinates are near the UAB campus.
  static bool isNearCampusCoords(double lat, double lng) {
    return isNearCampus(LatLng(lat, lng));
  }

  /// Get the current device position.
  ///
  /// Throws a user-friendly [Exception] if location services are disabled
  /// or permissions are denied.
  static Future<Position> getCurrentPosition() async {
    final bool serviceEnabled = await Geolocator.isLocationServiceEnabled();
    if (!serviceEnabled) {
      throw Exception(
        'Location services are disabled. Please enable them in Settings.',
      );
    }

    LocationPermission permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
      if (permission == LocationPermission.denied) {
        throw Exception('Location permission denied.');
      }
    }

    if (permission == LocationPermission.deniedForever) {
      throw Exception(
        'Location permission permanently denied. Please grant it from Settings.',
      );
    }

    return await Geolocator.getCurrentPosition(
      desiredAccuracy: LocationAccuracy.best,
    );
  }
}
