# Índice del Paquete - Geolocalización WiFi UAB

**UAB THE HACK! 2025 - Challenge DTIC WiFi Analysis**

---

## Estructura del Paquete

```
geolocation_package/
│
├── README.md              ← Documentación principal (EMPIEZA AQUÍ)
├── QUICK_START.md         ← Guía rápida de 5 minutos
├── INDEX.md              ← Este archivo (índice)
│
├── data/                  ← Datos de geolocalización
│   ├── aps_geolocalizados_wgs84.geojson    (326 KB) WGS84
│   └── aps_geolocalizados_etrs89.geojson   (335 KB) ETRS89
│
├── examples/              ← Scripts de ejemplo listos para ejecutar
│   ├── 01_basic_map.py           - Mapa básico interactivo
│   ├── 02_heatmap.py             - Mapa de calor de densidad
│   └── 03_building_stats.py      - Estadísticas por edificio
│
└── docs/                  ← Documentación detallada
    ├── CAMPOS.md                  - Descripción de todos los campos
    └── FAQ.md                     - Preguntas frecuentes
```

---

## ¿Por Dónde Empezar?

### Si tienes 5 minutos
📄 **QUICK_START.md** - Código mínimo para empezar

### Si tienes 15 minutos
📄 **README.md** - Documentación completa con ejemplos

### Si quieres ver ejemplos funcionando
📁 **examples/** - Ejecuta los scripts de ejemplo:
```bash
python examples/01_basic_map.py
python examples/02_heatmap.py
python examples/03_building_stats.py
```

### Si tienes dudas específicas
📄 **docs/FAQ.md** - Respuestas a preguntas comunes

### Si necesitas detalles técnicos
📄 **docs/CAMPOS.md** - Descripción completa de todos los campos

---

## Archivos Principales

### 📄 README.md
- **Qué es:** Documentación principal del paquete
- **Incluye:**
  - Quick start (3 minutos)
  - Campos disponibles
  - Matching con datos WiFi
  - Ejemplos de código
  - Estadísticas del dataset
  - Ideas de análisis por nivel

### 📄 QUICK_START.md
- **Qué es:** Guía ultra-rápida de 5 minutos
- **Incluye:**
  - Instalación en 1 línea
  - Código mínimo para empezar
  - Comandos para ejecutar ejemplos

---

## Datos

### 📊 data/aps_geolocalizados_wgs84.geojson (326 KB)
- **Sistema:** WGS84 (EPSG:4326) - Latitud/Longitud
- **Uso:** Mapas web (Folium, Leaflet, Google Maps)
- **Recomendado para:** La mayoría de análisis
- **Contenido:** 958 APs con coordenadas GPS

### 📊 data/aps_geolocalizados_etrs89.geojson (335 KB)
- **Sistema:** ETRS89 UTM 31N (EPSG:25831) - Metros
- **Uso:** Cálculos de distancia precisos
- **Recomendado para:** Análisis GIS avanzado
- **Contenido:** 958 APs con coordenadas UTM

**¿Cuál usar?**
- 95% de casos → **WGS84**
- Solo si necesitas calcular distancias en metros → ETRS89

---

## Ejemplos

### 🐍 examples/01_basic_map.py
**Mapa Básico con Todos los APs**

- **Tiempo:** ~10 segundos
- **Output:** `mapa_basico.html`
- **Muestra:**
  - Ubicación de cada AP
  - Estado (activo/inactivo)
  - Información al hacer click
  - Tamaño según número de clientes

**Ejecutar:**
```bash
python examples/01_basic_map.py
```

### 🔥 examples/02_heatmap.py
**Mapa de Calor de Densidad de Clientes**

- **Tiempo:** ~10 segundos
- **Output:** `mapa_calor.html`
- **Muestra:**
  - Zonas con mayor densidad de clientes
  - Gradiente de color (azul→verde→amarillo→rojo)
  - Top 20 APs más utilizados

**Ejecutar:**
```bash
python examples/02_heatmap.py
```

### 📊 examples/03_building_stats.py
**Estadísticas por Edificio**

- **Tiempo:** ~15 segundos
- **Output:**
  - `estadisticas_edificios.png` (gráficos)
  - `estadisticas_edificios.csv` (datos)
- **Muestra:**
  - Top edificios por clientes
  - Top edificios por número de APs
  - Distribución por planta
  - Clientes promedio por AP

**Ejecutar:**
```bash
python examples/03_building_stats.py
```

---

## Documentación

### 📖 docs/CAMPOS.md
**Descripción Completa de Campos**

- **Contenido:**
  - Descripción detallada de cada campo
  - Ejemplos de valores
  - Formatos y tipos de datos
  - Valores nulos y limitaciones
  - Guía de matching con datos WiFi
  - Sistemas de coordenadas
  - Ejemplos de código

**Lee esto si:**
- No entiendes qué es `USER_NOM_A`
- Quieres saber qué campos están disponibles
- Necesitas hacer matching con datos WiFi

### ❓ docs/FAQ.md
**Preguntas Frecuentes**

- **Contenido:**
  - 30+ preguntas respondidas
  - Errores comunes y soluciones
  - Ejemplos de código rápidos
  - Tips de rendimiento
  - Guía de troubleshooting

**Lee esto si:**
- Tienes un error y no sabes por qué
- Quieres código de ejemplo rápido
- No sabes cómo hacer algo específico

---

## Contenido de los Datos

### ¿Qué contienen los archivos GeoJSON?

**958 Access Points** con estos campos principales:

| Campo | Descripción |
|-------|-------------|
| `USER_NOM_A` | Nombre del AP (para matching con WiFi) |
| `USER_EDIFI` | Nombre del edificio |
| `Num_Planta` | Número de planta |
| `USER_Espai` | Código de espacio/puerta |
| `geometry` | Coordenadas GPS (Point) |

### Estadísticas

- **38 edificios** diferentes
- **7 plantas** (desde sótano -2 hasta planta 4)
- **96.9% de matching** con datos WiFi (927 de 957 APs)
- **Extensión:** ~2.2 km × 5.6 km

### Top 5 Edificios

1. LLETRES-PSICOLOGIA (104 APs)
2. CIENCIES SUD (92 APs)
3. ETSE (86 APs)
4. ECONOMIA (78 APs)
5. CIENCIES EDUCACIÓ (73 APs)

---

## Flujo de Trabajo Recomendado

### 1️⃣ Setup Inicial (5 min)
```bash
pip install geopandas folium pandas matplotlib
```

### 2️⃣ Exploración (10 min)
- Lee `QUICK_START.md`
- Ejecuta `examples/01_basic_map.py`
- Abre `mapa_basico.html` en navegador

### 3️⃣ Entender Datos (15 min)
- Lee `README.md` sección "Campos Disponibles"
- Lee `README.md` sección "Matching con Datos WiFi"
- Ejecuta otros ejemplos

### 4️⃣ Desarrollo (resto del hackathon)
- Copia y modifica código de ejemplos
- Consulta `docs/FAQ.md` cuando tengas dudas
- Consulta `docs/CAMPOS.md` para detalles técnicos

---

## Ideas de Análisis

Ver **README.md** sección "Ideas de Análisis" para:
- **Nivel ROOKIE:** Visualizaciones básicas
- **Nivel INTERMEDIO:** Mapas de calor, movilidad
- **Nivel AVANZADO:** ML, predicciones, optimización

---

## Requisitos

### Python
```bash
pip install geopandas folium pandas matplotlib
```

### Datos WiFi
Este paquete se usa **junto con** los datos WiFi anonimizados en:
```
../anonymized_data/aps/       (2,333 archivos)
../anonymized_data/clients/   (3,199 archivos)
```

---

## Soporte

### Documentación
1. `QUICK_START.md` - Empezar en 5 min
2. `README.md` - Guía completa
3. `docs/FAQ.md` - Preguntas frecuentes
4. `docs/CAMPOS.md` - Detalles técnicos

### Ejemplos
- `examples/01_basic_map.py`
- `examples/02_heatmap.py`
- `examples/03_building_stats.py`

## Changelog

**2025-11-08:** Primera versión
- 958 APs geolocalizados
- 2 formatos (WGS84 y ETRS89)
- 3 scripts de ejemplo
- Documentación completa

---

**Siguiente paso:** Abre `QUICK_START.md` o `README.md`
