# Datos de Geolocalización de Access Points WiFi UAB

**Challenge:** DTIC WiFi Analysis - UAB THE HACK! 2025
**Proporcionado por:** SIG Campus UAB

---

## ¿Qué contiene este paquete?

Este paquete te permite **cruzar los datos de APs y clientes WiFi con la ubicación física real** de los Access Points en el campus UAB.

### 958 Access Points geolocalizados

- 38 edificios diferentes (Campus Bellaterra + Sabadell)
- Coordenadas GPS precisas
- Información de edificio y planta
- **96.9% de matching** con los datos WiFi anonimizados

---

## Quick Start (3 minutos)

### 1. Instala las dependencias

```bash
pip install geopandas folium pandas matplotlib
```

### 2. Carga los datos

```python
import geopandas as gpd
import pandas as pd
import json

# Cargar datos de geolocalización
gdf_geo = gpd.read_file('data/aps_geolocalizados_wgs84.geojson')
print(f"✓ {len(gdf_geo)} APs con geolocalización")

# Cargar datos WiFi (ejemplo)
with open('../anonymized_data/aps/AP-info-v2-2025-06-13T14_45_01+02_00.json', 'r') as f:
    wifi_data = json.load(f)
df_wifi = pd.DataFrame(wifi_data)
print(f"✓ {len(df_wifi)} APs WiFi cargados")
```

### 3. Hacer matching

```python
# Combinar datos por nombre de AP
df_merged = df_wifi.merge(
    gdf_geo[['USER_NOM_A', 'USER_EDIFI', 'Num_Planta', 'geometry']],
    left_on='name',           # Nombre AP en datos WiFi
    right_on='USER_NOM_A',    # Nombre AP en geolocalización
    how='left'
)

# Convertir a GeoDataFrame
gdf_merged = gpd.GeoDataFrame(
    df_merged[df_merged['geometry'].notna()],
    geometry='geometry',
    crs='EPSG:4326'
)

print(f"✓ {len(gdf_merged)} APs con geolocalización y datos WiFi combinados")
```

### 4. Crear un mapa

```python
import folium

# Crear mapa centrado en UAB
m = folium.Map(location=[41.50, 2.10], zoom_start=15)

# Añadir APs al mapa
for idx, row in gdf_merged.iterrows():
    color = 'green' if row['status'] == 'Up' else 'red'

    folium.CircleMarker(
        location=[row.geometry.y, row.geometry.x],
        radius=5 + (row['client_count'] / 10),
        popup=f"{row['name']}<br>{row['USER_EDIFI']}<br>Clientes: {row['client_count']}",
        color=color,
        fill=True
    ).add_to(m)

m.save('mapa_aps.html')
print("✓ Mapa guardado en mapa_aps.html")
```

---

## Archivos Incluidos

### `data/`

- **`aps_geolocalizados_wgs84.geojson`** (326 KB)
  - Sistema: WGS84 (lat/lon) - Recomendado para mapas web
  - Compatible con: Folium, Leaflet, Google Maps, Mapbox

- **`aps_geolocalizados_etrs89.geojson`** (335 KB)
  - Sistema: ETRS89 UTM 31N (metros) - Sistema oficial Catalunya
  - Recomendado para: Cálculos de distancia precisos

### `examples/`

- **`01_basic_map.py`** - Mapa básico con todos los APs
- **`02_heatmap.py`** - Mapa de calor de densidad de clientes
- **`03_mobility_analysis.py`** - Análisis de movilidad entre edificios
- **`04_building_stats.py`** - Estadísticas por edificio

### `docs/`

- **`CAMPOS.md`** - Descripción de todos los campos disponibles
- **`FAQ.md`** - Preguntas frecuentes

---

## Campos Disponibles

Cada AP tiene estos campos:

| Campo | Descripción | Ejemplo |
|-------|-------------|---------|
| **`USER_NOM_A`** | **Nombre del AP (para matching)** | `"AP-ETSE16"` |
| `USER_EDIFI` | Nombre del edificio | `"ETSE"` |
| `Num_Planta` | Número de planta (0=baja, <0=sótano) | `1` |
| `USER_Espai` | Código de espacio/puerta | `"C/5035"` |
| `X` | Coordenada Este (metros UTM) | `425533.45` |
| `Y` | Coordenada Norte (metros UTM) | `4596210.32` |
| `geometry` | Geometría (lat/lon en WGS84) | `Point(2.108, 41.512)` |

---

## Matching con Datos WiFi

### Datos de APs

Campo de matching: **`name`** (en archivos `anonymized_data/aps/*.json`)

```python
# Coincide con USER_NOM_A en geolocalización
df_wifi['name'] == gdf_geo['USER_NOM_A']
```

**Ejemplos:** `"AP-ETSE16"`, `"AP-LLET95"`, `"AP-CIEN40"`

### Datos de Clientes

Los clientes tienen el campo **`associated_device`** que es el **serial anonimizado** del AP (NO el nombre).

**Para cruzar clientes con geolocalización:**

```python
# Paso 1: Crear diccionario AP_serial → AP_name
ap_dict = df_wifi.set_index('serial')['name'].to_dict()

# Paso 2: Añadir nombre de AP a datos de clientes
df_clients['ap_name'] = df_clients['associated_device'].map(ap_dict)

# Paso 3: Hacer merge con geolocalización
df_clients_geo = df_clients.merge(
    gdf_geo[['USER_NOM_A', 'geometry']],
    left_on='ap_name',
    right_on='USER_NOM_A',
    how='left'
)
```

---

## Estadísticas del Dataset

### Top 10 Edificios con Más APs

1. **LLETRES-PSICOLOGIA** - 104 APs
2. **CIENCIES SUD** - 92 APs
3. **ETSE** (Escola Enginyeria) - 86 APs
4. **ECONOMIA i EMPRESA** - 78 APs
5. **CIENCIES EDUCACIÓ** - 73 APs
6. **VETERINARIA-HCV** - 69 APs
7. **MEDICINA** - 65 APs
8. **CIENCIES NORD** - 63 APs
9. **CC.COMUNICACIO** - 42 APs
10. **AULARI J** - 35 APs

### Distribución por Planta

- Planta 0 (baja): 388 APs (40.5%)
- Planta 1: 288 APs (30.1%)
- Planta 2: 140 APs (14.6%)
- Sótano -1: 104 APs (10.9%)
- Otras: 38 APs (4.0%)

### Matching con Datos WiFi

- ✓ 927 APs coinciden (96.9%)
- ⚠ 30 APs geolocalizados sin datos WiFi (pueden estar inactivos)
- ⚠ ~215 APs WiFi sin geolocalización (otros campus o temporales)

---

## Ideas de Análisis

### Nivel ROOKIE

- Mapa con ubicación de todos los APs
- Distribución de APs por edificio
- Identificar edificios con más/menos cobertura
- Visualizar APs activos vs inactivos

### Nivel INTERMEDIO

- Mapa de calor de densidad de clientes
- Análisis de movilidad entre edificios
- Identificar zonas con señal débil
- Comparar uso entre diferentes plantas
- Clustering de APs por características

### Nivel AVANZADO

- Predicción de demanda por zona geográfica
- Optimización de ubicación de nuevos APs
- Análisis de cobertura y overlap
- Sistema de recomendación de mejor AP
- Simulación de movimientos de usuarios
- Digital twin del campus WiFi
- Chatbot con contexto geográfico (RAG)

---

## Ejemplos de Visualizaciones

### Mapa de Calor

```python
from folium.plugins import HeatMap

heat_data = [
    [row.geometry.y, row.geometry.x, row['client_count']]
    for idx, row in gdf_merged.iterrows()
]

m = folium.Map(location=[41.50, 2.10], zoom_start=15)
HeatMap(heat_data, radius=25).add_to(m)
m.save('heatmap.html')
```

### Análisis por Edificio

```python
stats = gdf_merged.groupby('USER_EDIFI').agg({
    'client_count': ['sum', 'mean', 'max'],
    'cpu_utilization': 'mean',
    'name': 'count'
}).round(2)

print(stats.sort_values(('client_count', 'sum'), ascending=False).head(10))
```

### Movilidad entre Edificios

```python
# Cargar múltiples archivos de clientes en diferentes momentos
# Seguir dispositivos por su CLIENT_xxx hash
# Ver en qué edificios aparecen a lo largo del tiempo

# Pseudocódigo:
client_path = track_client_movement('CLIENT_abc123', all_client_files)
visualize_path_on_map(client_path, gdf_geo)
```

---

## Conversión de Sistemas de Coordenadas

Si necesitas cambiar entre sistemas:

```python
# De WGS84 a ETRS89
gdf_wgs84 = gpd.read_file('data/aps_geolocalizados_wgs84.geojson')
gdf_etrs89 = gdf_wgs84.to_crs(epsg=25831)

# De ETRS89 a WGS84
gdf_etrs89 = gpd.read_file('data/aps_geolocalizados_etrs89.geojson')
gdf_wgs84 = gdf_etrs89.to_crs(epsg=4326)

# Calcular distancias (en metros, usar ETRS89)
from shapely.geometry import Point

point1 = Point(gdf_etrs89.iloc[0].geometry.x, gdf_etrs89.iloc[0].geometry.y)
point2 = Point(gdf_etrs89.iloc[1].geometry.x, gdf_etrs89.iloc[1].geometry.y)
distance_m = point1.distance(point2)
print(f"Distancia: {distance_m:.2f} metros")
```

---

## Limitaciones

1. **48 APs sin geometría** (4.8%) - Excluidos de los archivos
2. **30 APs geolocalizados sin datos WiFi** - Pueden estar inactivos
3. **~215 APs WiFi sin geolocalización** - Otros campus o APs temporales
4. **Fecha de geocodificación:** Julio 2023 - Puede haber cambios recientes

---

## Recursos Adicionales

- **Script de verificación:** `../verify_setup.py`
- **Documentación completa:** `../anonymized_data/README_GEOLOCALIZACION.md`
- **Guía de uso general:** `../USAGE_GUIDE.md`
