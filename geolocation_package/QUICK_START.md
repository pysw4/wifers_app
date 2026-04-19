# Quick Start - 5 Minutos

## Geolocalización de APs WiFi UAB

---

## 1. Instalar (1 min)

```bash
pip install geopandas folium pandas matplotlib
```

---

## 2. Código Mínimo (2 min)

```python
import geopandas as gpd
import folium
import pandas as pd
import json

# Cargar geolocalización
gdf_geo = gpd.read_file('data/aps_geolocalizados_wgs84.geojson')
print(f"✓ {len(gdf_geo)} APs con geolocalización")

# Cargar datos WiFi
with open('../anonymized_data/aps/AP-info-v2-2025-06-13T14_45_01+02_00.json') as f:
    wifi_data = json.load(f)
df_wifi = pd.DataFrame(wifi_data)

# Combinar
df_merged = df_wifi.merge(
    gdf_geo[['USER_NOM_A', 'USER_EDIFI', 'geometry']],
    left_on='name',
    right_on='USER_NOM_A',
    how='left'
)

# Crear mapa
m = folium.Map(location=[41.50, 2.10], zoom_start=15)
for idx, row in df_merged[df_merged['geometry'].notna()].iterrows():
    folium.CircleMarker(
        [row.geometry.y, row.geometry.x],
        radius=5,
        popup=f"{row['name']}<br>{row['USER_EDIFI']}"
    ).add_to(m)

m.save('mapa.html')
print("✓ Mapa guardado en mapa.html")
```

---

## 3. Ejecutar Ejemplos (2 min)

```bash
# Mapa básico
python examples/01_basic_map.py

# Mapa de calor
python examples/02_heatmap.py

# Estadísticas
python examples/03_building_stats.py
```

---

## ¡Listo! 🎉

**Archivos generados:**
- `mapa_basico.html` - Mapa interactivo con todos los APs
- `mapa_calor.html` - Mapa de calor de densidad
- `estadisticas_edificios.png` - Gráficos de análisis

**Siguiente paso:**
- Lee `README.md` para más detalles
- Consulta `docs/FAQ.md` si tienes dudas
- Revisa `docs/CAMPOS.md` para entender todos los campos

---

## Campos Principales

| Campo | Descripción |
|-------|-------------|
| `USER_NOM_A` | Nombre del AP (para matching) |
| `USER_EDIFI` | Edificio |
| `Num_Planta` | Número de planta |
| `geometry` | Coordenadas GPS |

---

## Matching Rápido

### Con APs WiFi:
```python
left_on='name'        # Campo en WiFi
right_on='USER_NOM_A' # Campo en geo
```

### Con Clientes WiFi:
```python
# 1. Crear diccionario
ap_dict = df_wifi.set_index('serial')['name'].to_dict()

# 2. Mapear
df_clients['ap_name'] = df_clients['associated_device'].map(ap_dict)

# 3. Merge
df_clients_geo = df_clients.merge(gdf_geo, left_on='ap_name', right_on='USER_NOM_A')
```