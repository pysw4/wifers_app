"""
Ejemplo 3: Estadisticas por Edificio
UAB THE HACK! 2025 - DTIC WiFi Analysis

Analiza y visualiza estadisticas de uso WiFi por edificio.

Ejecutar: python 03_building_stats.py
"""

import geopandas as gpd
import pandas as pd
import json
import matplotlib.pyplot as plt
from pathlib import Path

print("=" * 70)
print("ANALISIS POR EDIFICIO - WiFi UAB")
print("=" * 70)

# Rutas
BASE_DIR = Path(__file__).parent.parent
GEO_FILE = BASE_DIR / 'data' / 'aps_geolocalizados_wgs84.geojson'
WIFI_DIR = BASE_DIR.parent / 'anonymized_data' / 'aps'

# Cargar datos
print("\n[1/3] Cargando datos...")
gdf_geo = gpd.read_file(GEO_FILE)

wifi_files = sorted(WIFI_DIR.glob('*.json'))
if not wifi_files:
    print("  ERROR - No se encontraron archivos WiFi")
    exit()

with open(wifi_files[-1], 'r') as f:
    wifi_data = json.load(f)
df_wifi = pd.DataFrame(wifi_data)

# Combinar
df_merged = df_wifi.merge(
    gdf_geo[['USER_NOM_A', 'USER_EDIFI', 'Num_Planta', 'geometry']],
    left_on='name',
    right_on='USER_NOM_A',
    how='inner'
)

gdf_merged = gpd.GeoDataFrame(df_merged, geometry='geometry', crs='EPSG:4326')
print(f"  OK - {len(gdf_merged)} APs analizados")

# Analisis por edificio
print("\n[2/3] Calculando estadisticas por edificio...")

stats = gdf_merged.groupby('USER_EDIFI').agg({
    'name': 'count',
    'client_count': ['sum', 'mean', 'max'],
    'cpu_utilization': 'mean',
    'status': lambda x: (x == 'Up').sum()
}).round(2)

stats.columns = ['num_aps', 'total_clients', 'avg_clients', 'max_clients', 'avg_cpu', 'aps_activos']
stats = stats.sort_values('total_clients', ascending=False)

print("  OK - Estadisticas calculadas")

# Mostrar resultados
print("\n" + "=" * 70)
print("TOP 15 EDIFICIOS POR TOTAL DE CLIENTES")
print("=" * 70)
print(f"\n{'Edificio':45s} {'APs':>5s} {'Activos':>7s} {'Clientes':>9s} {'Prom':>5s} {'CPU%':>5s}")
print("-" * 70)

for building, row in stats.head(15).iterrows():
    print(f"{building[:44]:45s} "
          f"{int(row['num_aps']):5d} "
          f"{int(row['aps_activos']):7d} "
          f"{int(row['total_clients']):9d} "
          f"{row['avg_clients']:5.1f} "
          f"{row['avg_cpu']:5.1f}")

# Analisis por planta
print("\n" + "=" * 70)
print("DISTRIBUCION POR PLANTA")
print("=" * 70)

planta_stats = gdf_merged.groupby('Num_Planta').agg({
    'name': 'count',
    'client_count': 'sum'
}).sort_index()

print(f"\n{'Planta':20s} {'APs':>6s} {'Clientes':>10s}")
print("-" * 40)
for planta, row in planta_stats.iterrows():
    planta_name = f"Planta {planta}" if planta >= 0 else f"Sotano {abs(planta)}"
    print(f"{planta_name:20s} {int(row['name']):6d} {int(row['client_count']):10d}")

# Visualizacion
print("\n[3/3] Creando graficos...")

fig, axes = plt.subplots(2, 2, figsize=(15, 12))
fig.suptitle('Analisis WiFi por Edificio - UAB Campus', fontsize=16, fontweight='bold')

# Grafico 1: Top 10 edificios por clientes
ax1 = axes[0, 0]
top10 = stats.head(10)
ax1.barh(range(len(top10)), top10['total_clients'], color='steelblue')
ax1.set_yticks(range(len(top10)))
ax1.set_yticklabels([name[:30] for name in top10.index], fontsize=9)
ax1.set_xlabel('Total Clientes', fontsize=10)
ax1.set_title('Top 10 Edificios por Total de Clientes', fontsize=11, fontweight='bold')
ax1.grid(axis='x', alpha=0.3)
ax1.invert_yaxis()

# Grafico 2: APs por edificio
ax2 = axes[0, 1]
top10_aps = stats.nlargest(10, 'num_aps')
ax2.barh(range(len(top10_aps)), top10_aps['num_aps'], color='coral')
ax2.set_yticks(range(len(top10_aps)))
ax2.set_yticklabels([name[:30] for name in top10_aps.index], fontsize=9)
ax2.set_xlabel('Numero de APs', fontsize=10)
ax2.set_title('Top 10 Edificios por Numero de APs', fontsize=11, fontweight='bold')
ax2.grid(axis='x', alpha=0.3)
ax2.invert_yaxis()

# Grafico 3: Distribucion por planta
ax3 = axes[1, 0]
plantas_labels = [f"P{p}" if p >= 0 else f"S{abs(p)}" for p in planta_stats.index]
ax3.bar(plantas_labels, planta_stats['name'], color='mediumseagreen')
ax3.set_xlabel('Planta', fontsize=10)
ax3.set_ylabel('Numero de APs', fontsize=10)
ax3.set_title('Distribucion de APs por Planta', fontsize=11, fontweight='bold')
ax3.grid(axis='y', alpha=0.3)

# Grafico 4: Clientes promedio por AP
ax4 = axes[1, 1]
top10_avg = stats.nlargest(10, 'avg_clients')
colors = ['green' if x >= stats['avg_clients'].median() else 'orange' for x in top10_avg['avg_clients']]
ax4.barh(range(len(top10_avg)), top10_avg['avg_clients'], color=colors)
ax4.set_yticks(range(len(top10_avg)))
ax4.set_yticklabels([name[:30] for name in top10_avg.index], fontsize=9)
ax4.set_xlabel('Clientes Promedio por AP', fontsize=10)
ax4.set_title('Top 10 Edificios por Clientes/AP (Media)', fontsize=11, fontweight='bold')
ax4.axvline(stats['avg_clients'].median(), color='red', linestyle='--', label='Mediana')
ax4.legend()
ax4.grid(axis='x', alpha=0.3)
ax4.invert_yaxis()

plt.tight_layout()

# Guardar grafico
output_file = BASE_DIR / 'estadisticas_edificios.png'
plt.savefig(output_file, dpi=150, bbox_inches='tight')
print(f"  OK - Grafico guardado en: {output_file.name}")

# Guardar CSV con estadisticas
csv_file = BASE_DIR / 'estadisticas_edificios.csv'
stats.to_csv(csv_file)
print(f"  OK - CSV guardado en: {csv_file.name}")

print("\n" + "=" * 70)
print("RESUMEN")
print("=" * 70)
print(f"\nTotal edificios analizados: {len(stats)}")
print(f"Total APs activos: {int(stats['aps_activos'].sum())}")
print(f"Total clientes conectados: {int(stats['total_clients'].sum())}")
print(f"Promedio clientes por edificio: {stats['total_clients'].mean():.1f}")
print(f"Edificio con mas clientes: {stats.index[0]}")
print(f"Edificio con mas APs: {stats.nlargest(1, 'num_aps').index[0]}")

print("\n" + "=" * 70)
print("COMPLETADO")
print("=" * 70)
print(f"\nArchivos generados:")
print(f"  - {output_file.name} (grafico)")
print(f"  - {csv_file.name} (datos)")
