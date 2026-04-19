"""
Ejemplo 1: Mapa Basico de Access Points
UAB THE HACK! 2025 - DTIC WiFi Analysis

Este script crea un mapa interactivo basico con todos los APs geolocalizados.
Muestra:
- Ubicacion de cada AP
- Estado (activo/inactivo)
- Informacion al hacer click

Ejecutar: python 01_basic_map.py
"""

import geopandas as gpd
import folium
import json
import pandas as pd
from pathlib import Path

print("=" * 70)
print("MAPA BASICO DE ACCESS POINTS - UAB THE HACK! 2025")
print("=" * 70)

# Rutas
BASE_DIR = Path(__file__).parent.parent
GEO_FILE = BASE_DIR / 'data' / 'aps_geolocalizados_wgs84.geojson'
WIFI_DIR = BASE_DIR.parent / 'anonymized_data' / 'aps'

# Paso 1: Cargar datos de geolocalizacion
print("\n[1/4] Cargando datos de geolocalizacion...")
gdf_geo = gpd.read_file(GEO_FILE)
print(f"  OK - {len(gdf_geo)} APs con geolocalizacion")

# Paso 2: Cargar un archivo WiFi (el mas reciente)
print("\n[2/4] Cargando datos WiFi...")
wifi_files = sorted(WIFI_DIR.glob('*.json'))
if wifi_files:
    with open(wifi_files[-1], 'r') as f:
        wifi_data = json.load(f)
    df_wifi = pd.DataFrame(wifi_data)
    print(f"  OK - {len(df_wifi)} APs WiFi en archivo {wifi_files[-1].name}")

    # Paso 3: Hacer matching
    print("\n[3/4] Combinando datos...")
    df_merged = df_wifi.merge(
        gdf_geo[['USER_NOM_A', 'USER_EDIFI', 'Num_Planta', 'geometry']],
        left_on='name',
        right_on='USER_NOM_A',
        how='left'
    )

    gdf_merged = gpd.GeoDataFrame(
        df_merged[df_merged['geometry'].notna()],
        geometry='geometry',
        crs='EPSG:4326'
    )
    print(f"  OK - {len(gdf_merged)} APs con geolocalizacion y datos WiFi")
else:
    print("  ADVERTENCIA - No se encontraron archivos WiFi, usando solo geolocalizacion")
    gdf_merged = gdf_geo.copy()
    # Crear columnas dummy
    gdf_merged['status'] = 'Unknown'
    gdf_merged['client_count'] = 0

# Paso 4: Crear mapa
print("\n[4/4] Creando mapa interactivo...")

# Calcular centro
center_lat = gdf_merged.geometry.y.mean()
center_lon = gdf_merged.geometry.x.mean()

# Crear mapa base
m = folium.Map(
    location=[center_lat, center_lon],
    zoom_start=15,
    tiles='OpenStreetMap'
)

# Agregar titulo
title_html = '''
    <div style="position: fixed;
                top: 10px;
                left: 50px;
                width: 400px;
                background-color: white;
                border:2px solid grey;
                z-index:9999;
                padding: 10px;
                font-family: Arial;">
        <h3 style="margin:0;">Access Points WiFi UAB</h3>
        <p style="margin:5px 0;">
            <span style="color:green;">●</span> Activo |
            <span style="color:red;">●</span> Inactivo
        </p>
    </div>
    '''
m.get_root().html.add_child(folium.Element(title_html))

# Agregar marcadores
for idx, row in gdf_merged.iterrows():
    # Color segun estado
    if 'status' in row and row['status'] == 'Up':
        color = 'green'
        status_text = 'Activo'
    elif 'status' in row and row['status'] == 'Down':
        color = 'red'
        status_text = 'Inactivo'
    else:
        color = 'gray'
        status_text = 'Desconocido'

    # Radio segun clientes
    client_count = row.get('client_count', 0) or 0
    radius = 5 + (client_count / 10)

    # Crear popup con informacion
    popup_html = f"""
    <div style="font-family: Arial; min-width: 200px;">
        <h4 style="margin:0 0 10px 0;">{row.get('USER_NOM_A', row.get('name', 'AP'))}</h4>
        <table style="width:100%; font-size:12px;">
            <tr><td><b>Edificio:</b></td><td>{row.get('USER_EDIFI', 'N/A')}</td></tr>
            <tr><td><b>Planta:</b></td><td>{row.get('Num_Planta', 'N/A')}</td></tr>
            <tr><td><b>Estado:</b></td><td>{status_text}</td></tr>
            <tr><td><b>Clientes:</b></td><td>{client_count}</td></tr>
        </table>
    </div>
    """

    folium.CircleMarker(
        location=[row.geometry.y, row.geometry.x],
        radius=radius,
        popup=folium.Popup(popup_html, max_width=300),
        color=color,
        fill=True,
        fillColor=color,
        fillOpacity=0.6,
        weight=2
    ).add_to(m)

# Guardar mapa
output_file = BASE_DIR / 'mapa_basico.html'
m.save(str(output_file))

print(f"\n  OK - Mapa guardado en: {output_file.name}")
print("\n" + "=" * 70)
print("COMPLETADO")
print("=" * 70)
print(f"\nAbre el archivo '{output_file.name}' en tu navegador para ver el mapa.")
print("\nTips:")
print("  - Haz click en los puntos para ver informacion detallada")
print("  - Usa los controles de zoom para explorar")
print("  - Los puntos verdes son APs activos, rojos inactivos")
print("  - El tamano indica la cantidad de clientes conectados")
