"""
Ejemplo 2: Mapa de Calor de Densidad de Clientes
UAB THE HACK! 2025 - DTIC WiFi Analysis

Este script crea un mapa de calor mostrando la densidad de clientes
conectados por zona del campus.

Ejecutar: python 02_heatmap.py
"""

import geopandas as gpd
import folium
from folium.plugins import HeatMap
import json
import pandas as pd
from pathlib import Path

print("=" * 70)
print("MAPA DE CALOR - DENSIDAD DE CLIENTES")
print("=" * 70)

# Rutas
BASE_DIR = Path(__file__).parent.parent
GEO_FILE = BASE_DIR / 'data' / 'aps_geolocalizados_wgs84.geojson'
WIFI_DIR = BASE_DIR.parent / 'anonymized_data' / 'aps'

# Paso 1: Cargar datos
print("\n[1/4] Cargando datos...")
gdf_geo = gpd.read_file(GEO_FILE)

wifi_files = sorted(WIFI_DIR.glob('*.json'))
if not wifi_files:
    print("  ERROR - No se encontraron archivos WiFi")
    exit(1)

with open(wifi_files[-1], 'r') as f:
    wifi_data = json.load(f)
df_wifi = pd.DataFrame(wifi_data)
print(f"  OK - Datos cargados")

# Paso 2: Combinar datos
print("\n[2/4] Combinando datos con geolocalizacion...")
df_merged = df_wifi.merge(
    gdf_geo[['USER_NOM_A', 'USER_EDIFI', 'geometry']],
    left_on='name',
    right_on='USER_NOM_A',
    how='inner'
)

gdf_merged = gpd.GeoDataFrame(
    df_merged,
    geometry='geometry',
    crs='EPSG:4326'
)
print(f"  OK - {len(gdf_merged)} APs con geolocalizacion")

# Paso 3: Preparar datos para heatmap
print("\n[3/4] Preparando datos para mapa de calor...")

# Filtrar solo APs con clientes
gdf_active = gdf_merged[gdf_merged['client_count'] > 0].copy()
print(f"  - APs activos (con clientes): {len(gdf_active)}")

# Crear datos para heatmap [lat, lon, peso]
heat_data = [
    [row.geometry.y, row.geometry.x, row['client_count']]
    for idx, row in gdf_active.iterrows()
]

print(f"  - Total clientes: {gdf_active['client_count'].sum()}")
print(f"  - Promedio por AP: {gdf_active['client_count'].mean():.1f}")
print(f"  - Maximo en un AP: {gdf_active['client_count'].max()}")

# Paso 4: Crear mapa
print("\n[4/4] Creando mapa de calor...")

center_lat = gdf_merged.geometry.y.mean()
center_lon = gdf_merged.geometry.x.mean()

# Crear mapa base
m = folium.Map(
    location=[center_lat, center_lon],
    zoom_start=15,
    tiles='OpenStreetMap'
)

# Agregar capa de heatmap
HeatMap(
    heat_data,
    name='Densidad de Clientes',
    min_opacity=0.3,
    max_val=gdf_active['client_count'].max(),
    radius=25,
    blur=15,
    gradient={
        0.0: 'blue',
        0.3: 'cyan',
        0.5: 'lime',
        0.7: 'yellow',
        1.0: 'red'
    }
).add_to(m)

# Agregar puntos de APs con mas clientes (Top 20)
top_aps = gdf_active.nlargest(20, 'client_count')
for idx, row in top_aps.iterrows():
    folium.CircleMarker(
        location=[row.geometry.y, row.geometry.x],
        radius=3,
        popup=f"<b>{row['USER_NOM_A']}</b><br>{row['USER_EDIFI']}<br>Clientes: {row['client_count']}",
        color='white',
        fill=True,
        fillColor='red',
        fillOpacity=0.8
    ).add_to(m)

# Agregar titulo y leyenda
title_html = '''
    <div style="position: fixed;
                top: 10px;
                left: 50px;
                width: 350px;
                background-color: white;
                border:2px solid grey;
                z-index:9999;
                padding: 10px;
                font-family: Arial;">
        <h3 style="margin:0 0 5px 0;">Mapa de Calor - Clientes WiFi</h3>
        <p style="margin:5px 0; font-size:12px;">
            Intensidad del color indica densidad de clientes.<br>
            <span style="color:blue;">●</span> Baja |
            <span style="color:yellow;">●</span> Media |
            <span style="color:red;">●</span> Alta<br>
            <span style="color:white; background:red; padding:2px;">●</span>
            Puntos rojos = Top 20 APs con mas clientes
        </p>
    </div>
    '''
m.get_root().html.add_child(folium.Element(title_html))

# Control de capas
folium.LayerControl().add_to(m)

# Guardar
output_file = BASE_DIR / 'mapa_calor.html'
m.save(str(output_file))

print(f"\n  OK - Mapa guardado en: {output_file.name}")

# Estadisticas adicionales
print("\n" + "=" * 70)
print("ESTADISTICAS")
print("=" * 70)

print("\nTop 10 edificios por total de clientes:")
building_stats = gdf_active.groupby('USER_EDIFI')['client_count'].sum().sort_values(ascending=False).head(10)
for building, count in building_stats.items():
    print(f"  {building[:40]:40s} {count:4d} clientes")

print("\n" + "=" * 70)
print("COMPLETADO")
print("=" * 70)
print(f"\nAbre '{output_file.name}' para ver el mapa de calor.")
print("\nTips:")
print("  - Las zonas rojas tienen mayor densidad de clientes")
print("  - Identifica patrones de uso por zona del campus")
print("  - Los puntos rojos muestran los APs mas utilizados")
