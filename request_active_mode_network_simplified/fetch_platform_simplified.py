"""Simplified OSM fetch: public transport platforms and bus stops.

Retrieves:
- highway=platform         platform along a road
- highway=bus_stop         bus stop point
- public_transport=platform  generic PT platform (point, line, polygon)
- railway=platform         rail/tram platform
- amenity=bus_station      bus station area

No classification, no filtering — just the raw objects.
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

PLATFORM_TAGS = {
    "highway": ["platform", "bus_stop"],
    "public_transport": "platform",
    "railway": "platform",
    "amenity": "bus_station",
}

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

print("Fetching platforms and bus stops...")
gdf = ox.features_from_polygon(aoi_poly, tags=PLATFORM_TAGS).reset_index()
print(f"Platform objects fetched: {len(gdf)}")
print(f"Geometry types:\n{gdf.geometry.geom_type.value_counts()}")

# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

gdf_export = gdf.to_crs("EPSG:4326")
gdf_export.to_file(OUTPUT_DIR / "platforms.geojson", driver="GeoJSON")
print(f"Exported → {OUTPUT_DIR / 'platforms.geojson'}")
