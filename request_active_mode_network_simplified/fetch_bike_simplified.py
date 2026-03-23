"""Simplified OSM fetch: bike network (cycleways + primary/secondary road axes).

Retrieves:
- highway=cycleway                    dedicated cycle paths
- highway=primary/secondary(*_link)   road axes where cycling typically occurs

No cleanup, no classification, no fallback logic — just the raw query.
"""

from __future__ import annotations

from pathlib import Path

import osmnx as ox
from shapely.ops import unary_union

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

places = [
    "Carouge, Switzerland",
    "Lancy, Switzerland",
    "Thônex, Switzerland",
    "Saint-Julien-en-Genevois, France",
]

HIGHWAY_VALUES = ["cycleway", "secondary", "secondary_link", "primary", "primary_link"]

ox.settings.use_cache = True
ox.settings.requests_timeout = 300

# ---------------------------------------------------------------------------
# AOI
# ---------------------------------------------------------------------------

print("Loading AOI...")
polys = [
    unary_union(ox.geocode_to_gdf(place).to_crs("EPSG:4326").geometry.values)
    for place in places
]
aoi_poly = unary_union(polys)

# ---------------------------------------------------------------------------
# OSM query
# ---------------------------------------------------------------------------

print(f"Fetching highways: {HIGHWAY_VALUES}")
gdf = ox.features_from_polygon(
    aoi_poly,
    tags={"highway": HIGHWAY_VALUES},
)
gdf = gdf.reset_index()

# Keep only linear geometries
gdf = gdf[gdf.geometry.type.isin(["LineString", "MultiLineString"])].copy()

# Explode MultiLineStrings
gdf = gdf.explode(index_parts=False, ignore_index=True)

# Readable OSM id
if {"element", "id"}.issubset(gdf.columns):
    gdf["osm_id"] = gdf["element"].astype(str) + "/" + gdf["id"].astype(str)

print(f"Segments fetched: {len(gdf)}")
print(f"highway value counts:\n{gdf['highway'].value_counts()}")

# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

gdf_export = gdf.to_crs("EPSG:4326")
gdf_export.to_file(OUTPUT_DIR / "bike.geojson", driver="GeoJSON")
print(f"Exported → {OUTPUT_DIR / 'bike.geojson'}")
