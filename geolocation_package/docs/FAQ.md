# FAQ - Preguntas Frecuentes

## Datos de Geolocalización de APs WiFi - UAB THE HACK! 2025

---

## General

### ¿Qué son estos datos?

Datos de ubicación física (coordenadas GPS) de 958 Access Points WiFi del campus UAB, proporcionados por el SIG (Servicio de Información Geográfica) de la UAB.

### ¿Para qué sirven?

Permiten **cruzar los datos de conectividad WiFi con la ubicación real** de los APs. Así puedes:
- Crear mapas de uso de la red
- Analizar movilidad de usuarios entre edificios
- Identificar zonas con alta/baja demanda
- Visualizar patrones geográficos

### ¿Qué archivos debo usar?

**Para la mayoría de casos:** `data/aps_geolocalizados_wgs84.geojson`

Es el formato estándar para mapas web y librerías de Python como folium.

---

## Instalación y Setup

### ¿Qué necesito instalar?

```bash
pip install geopandas folium pandas matplotlib
```

### ¿Cómo verifico que todo funciona?

Ejecuta desde el directorio raíz del challenge:
```bash
python verify_setup.py
```

### Error: "No module named 'geopandas'"

Instala geopandas:
```bash
pip install geopandas
```

Si falla, prueba:
```bash
conda install geopandas -c conda-forge
```

---

## Carga de Datos

### ¿Cómo cargo los datos de geolocalización?

```python
import geopandas as gpd

gdf = gpd.read_file('data/aps_geolocalizados_wgs84.geojson')
print(f"{len(gdf)} APs cargados")
```

### ¿Cómo los combino con datos WiFi?

```python
import pandas as pd
import json

# Cargar WiFi
with open('../anonymized_data/aps/AP-info-....json', 'r') as f:
    wifi_data = json.load(f)
df_wifi = pd.DataFrame(wifi_data)

# Combinar
df_merged = df_wifi.merge(
    gdf[['USER_NOM_A', 'USER_EDIFI', 'geometry']],
    left_on='name',
    right_on='USER_NOM_A',
    how='left'
)
```

### ¿Por qué no todos los APs WiFi tienen geolocalización?

**96.9% tienen match** (927 de 957). Los ~215 APs sin geolocalización pueden ser:
- De otros campus (no Bellaterra/Sabadell)
- APs temporales o nuevos (posteriores a julio 2023)
- APs de backup

---

## Matching

### ¿Qué campo uso para hacer matching?

**Datos de APs WiFi:**
- Campo WiFi: `name`
- Campo Geo: `USER_NOM_A`

Ambos contienen el nombre del AP (ej: `"AP-ETSE16"`)

### ¿Cómo cruzar CLIENTES con geolocalización?

En 2 pasos (los clientes tienen serial, no nombre):

```python
# 1. Crear diccionario serial → nombre
ap_dict = df_wifi.set_index('serial')['name'].to_dict()

# 2. Mapear clientes
df_clients['ap_name'] = df_clients['associated_device'].map(ap_dict)

# 3. Merge con geo
df_clients_geo = df_clients.merge(
    gdf[['USER_NOM_A', 'geometry']],
    left_on='ap_name',
    right_on='USER_NOM_A',
    how='left'
)
```

### ¿Por qué algunos clientes quedan sin geolocalización?

Si el AP al que están conectados no tiene geolocalización, el cliente tampoco la tendrá. Es normal para ~3% de los APs.

---

## Mapas

### ¿Cómo creo un mapa básico?

```python
import folium

# Crear mapa centrado en UAB
m = folium.Map(location=[41.50, 2.10], zoom_start=15)

# Añadir APs
for idx, row in gdf.iterrows():
    folium.CircleMarker(
        location=[row.geometry.y, row.geometry.x],
        radius=5,
        popup=row['USER_NOM_A']
    ).add_to(m)

m.save('mapa.html')
```

O simplemente ejecuta: `python examples/01_basic_map.py`

### ¿Cómo creo un mapa de calor?

Ejecuta:
```bash
python examples/02_heatmap.py
```

O usa:
```python
from folium.plugins import HeatMap

heat_data = [[row.geometry.y, row.geometry.x, row['client_count']]
             for idx, row in gdf_merged.iterrows()]

m = folium.Map(location=[41.50, 2.10], zoom_start=15)
HeatMap(heat_data).add_to(m)
m.save('heatmap.html')
```

### El mapa se ve mal / no aparecen los puntos

Verifica:
1. Estás usando `row.geometry.y` (latitud) primero, luego `row.geometry.x` (longitud)
2. Las coordenadas están en el rango correcto (~41.5° lat, ~2.1° lon)
3. No hay valores NaN en las geometrías: `gdf = gdf[gdf.geometry.notna()]`

---

## Coordenadas

### ¿Qué diferencia hay entre WGS84 y ETRS89?

**WGS84 (EPSG:4326)** - `aps_geolocalizados_wgs84.geojson`
- Coordenadas en grados (lat/lon)
- Para mapas web (Google Maps, Folium)
- Ejemplo: lat=41.504°, lon=2.105°

**ETRS89 UTM 31N (EPSG:25831)** - `aps_geolocalizados_etrs89.geojson`
- Coordenadas en metros (X/Y)
- Para cálculos de distancia precisos
- Ejemplo: X=425291 m, Y=4595107 m

### ¿Cómo calculo distancias entre APs?

Usa ETRS89 para distancias en metros:

```python
gdf_etrs = gpd.read_file('data/aps_geolocalizados_etrs89.geojson')

ap1 = gdf_etrs.iloc[0].geometry
ap2 = gdf_etrs.iloc[1].geometry

distance_m = ap1.distance(ap2)
print(f"{distance_m:.2f} metros")
```

### ¿Cómo convierto entre sistemas?

```python
# WGS84 → ETRS89
gdf_wgs84 = gpd.read_file('data/aps_geolocalizados_wgs84.geojson')
gdf_etrs89 = gdf_wgs84.to_crs(epsg=25831)

# ETRS89 → WGS84
gdf_etrs89 = gpd.read_file('data/aps_geolocalizados_etrs89.geojson')
gdf_wgs84 = gdf_etrs89.to_crs(epsg=4326)
```

---

## Análisis

### ¿Qué análisis puedo hacer?

**Básicos:**
- Mapa de todos los APs
- Distribución por edificio/planta
- Zonas con más/menos cobertura

**Intermedios:**
- Mapas de calor de densidad
- Análisis de movilidad entre edificios
- Identificar zonas problemáticas
- Clustering de APs

**Avanzados:**
- Predicción de demanda por zona
- Optimización de ubicación de APs
- Análisis de cobertura y overlap
- Digital twin del campus
- Chatbots con contexto geográfico

### ¿Cómo analizo movilidad entre edificios?

```python
# Cargar múltiples archivos de clientes
# Seguir un cliente por su hash CLIENT_xxx

client_id = 'CLIENT_abc123'
visits = []

for file in client_files:
    # Cargar archivo
    # Buscar client_id
    # Si existe, anotar AP, timestamp, edificio
    # ...

# Visualizar ruta en mapa
```

### ¿Cómo identifico zonas con baja cobertura?

1. Analiza APs por zona
2. Compara con densidad de clientes
3. Identifica zonas con pocos APs pero muchos clientes (saturación)
4. Identifica edificios con pocos APs (baja cobertura)

---

## Errores Comunes

### KeyError: 'USER_NOM_A'

Estás accediendo a un DataFrame en lugar de GeoDataFrame. Asegúrate de cargar con geopandas:

```python
gdf = gpd.read_file('data/aps_geolocalizados_wgs84.geojson')
```

### AttributeError: 'DataFrame' object has no attribute 'geometry'

Convierte a GeoDataFrame:

```python
gdf = gpd.GeoDataFrame(df, geometry='geometry', crs='EPSG:4326')
```

### Error al guardar mapa: 'str' object has no attribute 'save'

`folium.Map.save()` requiere una ruta string, no un objeto Path:

```python
# Correcto
m.save('mapa.html')
m.save(str(path_object))

# Incorrecto
m.save(path_object)  # Si path_object es pathlib.Path
```

### Merge devuelve 0 filas

Verifica que los campos de matching existen y tienen el formato correcto:

```python
print(df_wifi['name'].head())
print(gdf['USER_NOM_A'].head())

# Verificar matches
common = set(df_wifi['name']) & set(gdf['USER_NOM_A'])
print(f"{len(common)} nombres coinciden")
```

---

## Rendimiento

### Los archivos son muy grandes, ¿cómo los optimizo?

**Para desarrollo, usa subconjunto:**

```python
# Solo top 100 APs
gdf_sample = gdf.head(100)

# Solo un edificio
gdf_etse = gdf[gdf['USER_EDIFI'] == 'ETSE']

# APs con clientes
gdf_active = gdf_merged[gdf_merged['client_count'] > 0]
```

### ¿Puedo filtrar por zona geográfica?

Sí, con bounding box:

```python
# Definir área
min_lon, min_lat = 2.10, 41.50
max_lon, max_lat = 2.11, 41.51

# Filtrar
gdf_zona = gdf[
    (gdf.geometry.x >= min_lon) & (gdf.geometry.x <= max_lon) &
    (gdf.geometry.y >= min_lat) & (gdf.geometry.y <= max_lat)
]
```

---

## Ejemplos Rápidos

### Código completo mínimo

```python
import geopandas as gpd
import folium

# Cargar
gdf = gpd.read_file('data/aps_geolocalizados_wgs84.geojson')

# Mapa
m = folium.Map(location=[41.50, 2.10], zoom_start=15)
for idx, row in gdf.iterrows():
    folium.CircleMarker(
        [row.geometry.y, row.geometry.x],
        radius=5,
        popup=row['USER_NOM_A']
    ).add_to(m)
m.save('mapa.html')
```

### Estadísticas rápidas

```python
print(f"Total APs: {len(gdf)}")
print(f"Edificios: {gdf['USER_EDIFI'].nunique()}")
print("\nTop 5 edificios:")
print(gdf['USER_EDIFI'].value_counts().head())
```

---

## Contacto

### ¿Dónde busco más ayuda?

1. **Documentación:**
   - `README.md` - Este paquete
   - `docs/CAMPOS.md` - Descripción de campos
   - `../USAGE_GUIDE.md` - Guía completa del challenge

2. **Ejemplos:**
   - `examples/01_basic_map.py`
   - `examples/02_heatmap.py`
   - `examples/03_building_stats.py`

3. **Soporte:**
   - Albert Gil López: albert.gil.lopez@uab.cat
   - SIG UAB: sig.campus@uab.cat

### ¿Los datos están actualizados?

La geocodificación es de **julio 2023**. DTIC confirma que no ha habido cambios significativos en la ubicación de APs desde entonces.

---

## ¡Buena suerte en el hackathon! 🚀
