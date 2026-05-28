import 'dart:convert';

import 'package:flutter/services.dart';
import 'package:wifers_app/models/ap_info.dart';

/// Shared service for loading AP data from the GeoJSON asset.
///
/// Both [MapPage] and [RecommendPage] need to load AP data.
/// This service centralises that logic to avoid duplication.
class ApDataService {
  static const String _geojsonPath =
      'geolocation_package/data/aps_geolocalizados_wgs84.geojson';

  /// Load all APs from the bundled GeoJSON file.
  static Future<List<APInfo>> loadAllAps() async {
    final geojson = await rootBundle.loadString(_geojsonPath);
    final Map<String, dynamic> data =
        json.decode(geojson) as Map<String, dynamic>;
    final features = data['features'] as List<dynamic>;

    return features.map<APInfo>((dynamic feature) {
      final Map<String, dynamic> props =
          Map<String, dynamic>.from(feature['properties'] as Map);
      final coords = feature['geometry']['coordinates'] as List<dynamic>;

      return APInfo(
        id: props['USER_NOM_A']?.toString(),
        name: props['USER_NOM_A']?.toString(),
        building: props['USER_EDIFI']?.toString() ??
            props['Nom_Edific']?.toString() ??
            'Unknown',
        height: props['Num_Planta'] is num
            ? (props['Num_Planta'] as num).toInt()
            : null,
        espacio: props['USER_Espai']?.toString(),
        lat: (coords[1] as num).toDouble(),
        lng: (coords[0] as num).toDouble(),
      );
    }).toList();
  }

  /// Load unique building names from the GeoJSON asset.
  static Future<List<String>> loadBuildings() async {
    final geojson = await rootBundle.loadString(_geojsonPath);
    final Map<String, dynamic> data =
        json.decode(geojson) as Map<String, dynamic>;
    final features = data['features'] as List<dynamic>;

    final Set<String> buildings = {};
    for (final feature in features) {
      final props = Map<String, dynamic>.from(feature['properties'] as Map);
      final building = props['USER_EDIFI']?.toString() ??
          props['Nom_Edific']?.toString() ??
          'Unknown';
      buildings.add(building);
    }
    final sorted = buildings.toList()..sort();
    return sorted;
  }

  /// Pre-defined campus zones grouping buildings by geographic area.
  static const Map<String, List<String>> campusZones = {
    'Engineering & Sciences': [
      'ETSE', 'CIENCIES NORD', 'CIENCIES SUD',
      'CC.COMUNICACIO', 'EUREKA', 'CED',
    ],
    'Humanities & Arts': [
      'LLETRES-PSICOLOGIA', 'FAC. TRADUCCIÓ I INTERPRETACIÓ',
      'BIBLIOTECA HUMANITATS', 'BIB.COM.',
    ],
    'Social Sciences & Law': [
      'ECONOMIA i EMPRESA-POLÍTIQUES', 'FAC.DRET',
      'BIB.SOCIALS', 'IUEE',
    ],
    'Health & Medicine': [
      'MEDICINA', 'VETERINARIA-HCV', 'ESTABULARI', 'SAS',
    ],
    'Education': [
      'CIENCIES EDUCACIÓ', 'AULARI J', 'ESCOLA DE POSTGRAU',
    ],
    'Administration & Services': [
      'RECTORAT', 'PLAÇA CÍVICA', 'SERV.LLENGÜES',
      "Servei d'Informàtica", 'SAF', 'TERMICA',
    ],
    'Student Life': [
      'ESTUDIANTS', 'AMICS UAB', 'MRA', 'MRB',
    ],
    'Research Centers': [
      'ICTA-ICP', 'IBB', 'IAE', 'CEHIC', 'CBATEG',
    ],
    'Other': ['Campus Sabadell'],
  };

  /// Get all zone names.
  static List<String> getZoneNames() => campusZones.keys.toList();

  /// Get buildings for a given zone. Returns empty list if zone not found.
  static List<String> getBuildingsForZone(String zone) =>
      campusZones[zone] ?? [];

  /// Check if a building belongs to a given zone.
  static bool isBuildingInZone(String building, String zone) {
    final zoneBuildings = campusZones[zone];
    if (zoneBuildings == null) return false;
    return zoneBuildings.contains(building);
  }

  /// Get the zone name for a given building, or null if not found.
  static String? getZoneForBuilding(String building) {
    for (final entry in campusZones.entries) {
      if (entry.value.contains(building)) return entry.key;
    }
    return null;
  }
}
