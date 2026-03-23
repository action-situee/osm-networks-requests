"""Simplified OSM fetch: walk network with priority / secondary tiers.

Based on the filtering logic from old_Load_osm_network_option1.ipynb.
No snap, no cleanup, no graph simplification beyond osmnx defaults.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import osmnx as ox
import pandas as pd

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

# OSMnx custom filter: pull all highway types potentially walkable.
# Motorway, trunk and construction are excluded upfront.
CUSTOM_FILTER = (
    '["area"!~"yes"]'
    '["highway"!~"motorway|motorway_link|trunk|trunk_link|construction|proposed"]'
    '["highway"~"footway|path|pedestrian|steps|living_street|residential|service'
    '|unclassified|tertiary|secondary|primary|platform"]'
)

# Roads considered "local" — foot access assumed OK if not tagged otherwise
LOCAL_ROADS = {"residential", "service", "unclassified", "tertiary"}

SIDEWALK_OK = {"both", "left", "right", "yes", "separate"}
FOOT_POSITIVE = {"yes", "designated", "permissive"}
FOOT_NEGATIVE = {"no", "private", "use_sidepath"}

ox.settings.use_cache = True
ox.settings.requests_timeout = 300

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lower(x) -> str:
    return str(x).lower() if x is not None else ""


def _as_set(v) -> set:
    if isinstance(v, (list, tuple, set)):
        return {_lower(e) for e in v}
    return {_lower(v)}


def has_sidewalk(row) -> bool:
    vals = {
        _lower(row.get("sidewalk")),
        _lower(row.get("sidewalk:left")),
        _lower(row.get("sidewalk:right")),
    }
    return bool(SIDEWALK_OK & vals)


def foot_allowed_on_path(row) -> bool:
    """Paths are walkable by default unless explicitly forbidden."""
    f = _lower(row.get("foot"))
    acc = _lower(row.get("access"))
    return f not in {"no", "private"} and acc not in {"no", "private"}


def foot_allowed_on_local(row) -> bool:
    """Local roads: assume OK if not negated."""
    f = _lower(row.get("foot"))
    acc = _lower(row.get("access"))
    if f in FOOT_NEGATIVE or acc in {"no", "private"}:
        return False
    return True  # assume foot OK on local roads


# ---------------------------------------------------------------------------
# AOI
# ---------------------------------------------------------------------------

print("Loading AOI...")
from shapely.ops import unary_union
polys = [
    unary_union(ox.geocode_to_gdf(place).to_crs("EPSG:4326").geometry.values)
    for place in places
]
aoi_poly = unary_union(polys)

# ---------------------------------------------------------------------------
# Download graph
# ---------------------------------------------------------------------------

print("Downloading walk graph from OSM...")
G = ox.graph_from_polygon(
    polygon=aoi_poly,
    custom_filter=CUSTOM_FILTER,
    simplify=True,
    retain_all=True,
)

print("Converting to GeoDataFrame...")
edges = ox.graph_to_gdfs(G, nodes=False, fill_edge_geometry=True).reset_index(drop=True)
print(f"Edges fetched: {len(edges)}")

edges["hw_set"] = edges["highway"].apply(_as_set)

# ---------------------------------------------------------------------------
# Priority tier
#   - footway / pedestrian / steps / living_street
#   - path (walkable unless forbidden)
#   - local roads WITH explicit sidewalk tag
# ---------------------------------------------------------------------------

priority_mask = (
    edges["hw_set"].apply(lambda s: bool({"footway", "pedestrian", "steps", "living_street"} & s))
    | (edges["hw_set"].apply(lambda s: "path" in s) & edges.apply(foot_allowed_on_path, axis=1))
    | (edges["hw_set"].apply(lambda s: bool(LOCAL_ROADS & s)) & edges.apply(has_sidewalk, axis=1))
)

priority = edges[priority_mask].copy()
priority["tier"] = "priority"

# ---------------------------------------------------------------------------
# Secondary tier
#   - local roads WITHOUT explicit sidewalk but foot not forbidden
# ---------------------------------------------------------------------------

secondary_mask = (
    edges["hw_set"].apply(lambda s: bool(LOCAL_ROADS & s))
    & ~edges.apply(has_sidewalk, axis=1)
    & edges.apply(foot_allowed_on_local, axis=1)
)

secondary = edges[secondary_mask].copy()
secondary["tier"] = "secondary"

print(f"Priority segments : {len(priority)}")
print(f"Secondary segments: {len(secondary)}")

# ---------------------------------------------------------------------------
# Combined network
# ---------------------------------------------------------------------------

walk_all = gpd.GeoDataFrame(
    pd.concat([priority, secondary], ignore_index=True),
    geometry="geometry",
    crs=edges.crs,
)

# Drop helper column
walk_all = walk_all.drop(columns=["hw_set"], errors="ignore")
priority = priority.drop(columns=["hw_set"], errors="ignore")
secondary = secondary.drop(columns=["hw_set"], errors="ignore")

print(f"Total walk network: {len(walk_all)} segments")

# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export(gdf: gpd.GeoDataFrame, stem: str) -> None:
    gdf_exp = gdf.to_crs("EPSG:4326")
    gdf_exp.to_file(OUTPUT_DIR / f"{stem}.geojson", driver="GeoJSON")
    print(f"Exported → {OUTPUT_DIR / stem}.geojson")


export(priority,  "walk_priority")
export(secondary, "walk_secondary")
export(walk_all,  "walk_all")
