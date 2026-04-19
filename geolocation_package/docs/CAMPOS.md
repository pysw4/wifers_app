# Descripción de Campos - Datos de Geolocalización

## Campos Disponibles en GeoJSON

Cada Access Point en los archivos `aps_geolocalizados_*.geojson` contiene los siguientes campos:

---

### `USER_NOM_A` (string)
**Nombre del Access Point - CAMPO PRINCIPAL PARA MATCHING**

- **Descripción:** Identificador único del AP
- **Formato:** `"AP-XXXX##"` donde XXXX es el código del edificio
- **Ejemplos:**
  - `"AP-ETSE16"` - AP 16 de la Escola d'Enginyeria
  - `"AP-LLET95"` - AP 95 del edificio de Lletres
  - `"AP-CIEN40"` - AP 40 del edificio de Ciències
- **Uso:** Este campo coincide con el campo `name` en los archivos WiFi
- **Valores nulos:** 0 (todos los APs tienen nombre)

---

### `USER_EDIFI` (string)
**Nombre del Edificio**

- **Descripción:** Nombre completo del edificio donde está ubicado el AP
- **Ejemplos:**
  - `"ETSE"` - Escola Tècnica Superior d'Enginyeria
  - `"LLETRES-PSICOLOGIA"` - Facultad de Letras y Psicología
  - `"CIENCIES SUD"` - Edificio de Ciencias Sur
  - `"MEDICINA"` - Facultad de Medicina
- **Valores únicos:** 38 edificios diferentes
- **Valores nulos:** ~50 (5.2%)

---

### `Num_Planta` (integer)
**Número de Planta**

- **Descripción:** Planta donde está ubicado el AP
- **Valores:**
  - `0` = Planta baja
  - `1, 2, 3, 4` = Plantas superiores
  - `-1, -2` = Sótanos
- **Distribución:**
  - Planta 0: 388 APs (40.5%)
  - Planta 1: 288 APs (30.1%)
  - Planta 2: 140 APs (14.6%)
  - Sótano -1: 104 APs (10.9%)
  - Otras: 38 APs (4.0%)
- **Valores nulos:** 0

---

### `USER_Espai` (string)
**Código de Espacio/Puerta**

- **Descripción:** Código del espacio físico o puerta donde está el AP
- **Formato:** `"EDIFICIO/NUMERO"`
- **Ejemplos:**
  - `"C/5035"` - Puerta 5035 del edificio C
  - `"K/0037"` - Puerta 0037 del edificio K
  - `"Q/0026"` - Puerta 0026 del edificio Q
- **Uso:** Útil para identificación precisa dentro del edificio
- **Valores nulos:** 0

---

### `X` (float)
**Coordenada Este (UTM)**

- **Descripción:** Coordenada X en metros (sistema ETRS89 UTM 31N)
- **Unidad:** Metros
- **Rango:** 424,427 - 426,591 m
- **Sistema:** EPSG:25831 (ETRS89 UTM Zone 31N)
- **Uso:** Para cálculos precisos de distancia en metros
- **Nota:** Solo disponible en archivo `aps_geolocalizados_etrs89.geojson`

**Ejemplo:** `425291.73`

---

### `Y` (float)
**Coordenada Norte (UTM)**

- **Descripción:** Coordenada Y en metros (sistema ETRS89 UTM 31N)
- **Unidad:** Metros
- **Rango:** 4,594,330 - 4,599,898 m
- **Sistema:** EPSG:25831 (ETRS89 UTM Zone 31N)
- **Uso:** Para cálculos precisos de distancia en metros
- **Nota:** Solo disponible en archivo `aps_geolocalizados_etrs89.geojson`

**Ejemplo:** `4595107.19`

---

### `geometry` (Point)
**Geometría Geoespacial**

- **Descripción:** Punto geográfico con la ubicación del AP
- **Tipo:** Point (Shapely/GeoPandas)
- **Sistema:**
  - WGS84 (EPSG:4326) en `aps_geolocalizados_wgs84.geojson`
  - ETRS89 UTM 31N (EPSG:25831) en `aps_geolocalizados_etrs89.geojson`

**Formato WGS84:**
```json
{
  "type": "Point",
  "coordinates": [2.104839, 41.504109]
}
```
- `coordinates[0]` = Longitud (Este-Oeste) en grados
- `coordinates[1]` = Latitud (Norte-Sur) en grados

**Acceso en Python:**
```python
lat = row.geometry.y
lon = row.geometry.x
```

---

### `Ref_Curta` (string)
**Referencia Corta**

- **Descripción:** Referencia corta combinando espacio, edificio y planta
- **Formato:** `"ESPACIO, EDIFICIO, PLANTA"`
- **Ejemplos:**
  - `"K/0037, K, 0"`
  - `"C/5035, C, 5"`
- **Uso:** Identificación rápida del AP
- **Valores nulos:** ~52 (5.4%)

---

### `USER_PLANT` (string)
**Planta (formato texto)**

- **Descripción:** Número de planta en formato string
- **Valores:** `"0"`, `"1"`, `"2"`, `"-1"`, etc.
- **Nota:** Es la versión string de `Num_Planta`
- **Uso:** Puede ser útil para agrupaciones o etiquetas

---

## Matching con Datos WiFi

### Datos de Access Points WiFi

**Archivo:** `anonymized_data/aps/*.json`

**Campo de matching:** `name`

```python
# Hacer matching
df_merged = df_wifi.merge(
    gdf_geo,
    left_on='name',        # Campo en datos WiFi
    right_on='USER_NOM_A', # Campo en geolocalización
    how='left'
)
```

### Datos de Clientes WiFi

**Archivo:** `anonymized_data/clients/*.json`

**Campo disponible:** `associated_device` (serial del AP, anonimizado)

**Proceso de matching en 2 pasos:**

```python
# Paso 1: Crear diccionario serial → nombre
ap_dict = df_wifi.set_index('serial')['name'].to_dict()

# Paso 2: Mapear clientes a nombres de AP
df_clients['ap_name'] = df_clients['associated_device'].map(ap_dict)

# Paso 3: Hacer merge con geolocalización
df_clients_geo = df_clients.merge(
    gdf_geo,
    left_on='ap_name',
    right_on='USER_NOM_A',
    how='left'
)
```

---

## Sistemas de Coordenadas

### WGS84 (EPSG:4326)
- **Archivo:** `aps_geolocalizados_wgs84.geojson`
- **Uso:** Mapas web (Google Maps, Leaflet, Folium)
- **Coordenadas:** Latitud/Longitud en grados decimales
- **Ejemplo:** lat=41.504109°, lon=2.104839°

### ETRS89 UTM 31N (EPSG:25831)
- **Archivo:** `aps_geolocalizados_etrs89.geojson`
- **Uso:** Cálculos de distancia precisos, GIS profesional
- **Coordenadas:** X/Y en metros
- **Ejemplo:** X=425291.73 m, Y=4595107.19 m
- **Ventaja:** Distancias en metros directamente calculables

### Conversión

```python
import geopandas as gpd

# WGS84 → ETRS89
gdf_wgs84 = gpd.read_file('aps_geolocalizados_wgs84.geojson')
gdf_etrs89 = gdf_wgs84.to_crs(epsg=25831)

# ETRS89 → WGS84
gdf_etrs89 = gpd.read_file('aps_geolocalizados_etrs89.geojson')
gdf_wgs84 = gdf_etrs89.to_crs(epsg=4326)
```

---

## Valores Nulos y Limitaciones

| Campo | Nulos | % |
|-------|-------|---|
| `USER_NOM_A` | 0 | 0% |
| `USER_EDIFI` | ~50 | 5.2% |
| `Num_Planta` | 0 | 0% |
| `USER_Espai` | 0 | 0% |
| `Ref_Curta` | ~52 | 5.4% |
| `geometry` | 48* | 4.8%* |

*Los 48 APs sin geometría fueron excluidos de los archivos GeoJSON

---

## Ejemplos de Uso

### Obtener coordenadas

```python
import geopandas as gpd

gdf = gpd.read_file('data/aps_geolocalizados_wgs84.geojson')

# Primera fila
ap = gdf.iloc[0]

# Acceder a campos
nombre = ap['USER_NOM_A']
edificio = ap['USER_EDIFI']
planta = ap['Num_Planta']
lat = ap.geometry.y
lon = ap.geometry.x

print(f"{nombre} en {edificio}, planta {planta}")
print(f"Coordenadas: {lat}, {lon}")
```

### Filtrar por edificio

```python
# APs de la Escola d'Enginyeria
etse_aps = gdf[gdf['USER_EDIFI'] == 'ETSE']
print(f"ETSE tiene {len(etse_aps)} APs")
```

### Filtrar por planta

```python
# APs en planta baja
planta_baja = gdf[gdf['Num_Planta'] == 0]

# APs en sótanos
sotanos = gdf[gdf['Num_Planta'] < 0]
```

### Calcular distancia entre APs

```python
# Usar ETRS89 para cálculos en metros
gdf_etrs = gpd.read_file('data/aps_geolocalizados_etrs89.geojson')

ap1 = gdf_etrs.iloc[0].geometry
ap2 = gdf_etrs.iloc[1].geometry

distance = ap1.distance(ap2)
print(f"Distancia: {distance:.2f} metros")
```

---

## Soporte

**Preguntas sobre geolocalización:**
- SIG Campus UAB: sig.campus@uab.cat

**Preguntas sobre el challenge:**
- Albert Gil López: albert.gil.lopez@uab.cat
