"""Extract parking spaces and parking areas from OSM."""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import geopandas as gpd
import osmnx as ox
import pandas as pd
from shapely.geometry import box
from shapely.ops import unary_union

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Area of interest
area_mode = "geocode"  # "shapefile" or "geocode"
shapefile_path = INPUT_DIR / "AGGLO_PERIMETRE_AVEC_LAC.shp"
places = ["Carouge, Switzerland"]

# Export
export_formats = ["parquet", "geojson"]
operation_crs = "EPSG:2056"
export_crs = "EPSG:4326"

# OSM download robustness
overpass_urls = [
    "https://overpass-api.de/api",
    "https://overpass.kumi.systems/api",
    "https://overpass.private.coffee/api",
]
overpass_timeout_s = 240
download_tile_size_m = 8000
min_download_tile_size_m = 2000

ox.settings.use_cache = True
ox.settings.requests_timeout = overpass_timeout_s

parking_queries = [
    ("parking areas and points", {"amenity": "parking"}),
    ("individual parking spots", {"amenity": "parking_space"}),
    ("generic parking-tagged objects", {"parking": True}),
]

on_street_parking_tags = {
    "parking:left": True,
    "parking:right": True,
    "parking:both": True,
    "parking:lane:left": True,
    "parking:lane:right": True,
    "parking:lane:both": True,
    "parking:left:orientation": True,
    "parking:right:orientation": True,
    "parking:both:orientation": True,
}

ON_STREET_PARKING_NEGATIVE = {
    "",
    "no",
    "none",
    "separate",
    "no_parking",
    "no_stopping",
    "fire_lane",
    "bus_stop",
    "loading_only",
}
DEFAULT_CARRIAGEWAY_HALF_WIDTH_M = 3.0
PARKING_WIDTH_BY_ORIENTATION_M = {
    "parallel": 2.3,
    "diagonal": 4.2,
    "perpendicular": 5.0,
    "half_on_kerb": 2.0,
}


def first_scalar(value):
    if isinstance(value, (list, tuple, set)):
        value = list(value)
        return value[0] if value else None
    return value


def as_lower_str(value) -> str:
    value = first_scalar(value)
    if value is None or pd.isna(value):
        return ""
    return str(value).lower().strip()


def format_tags(tags: dict) -> str:
    parts = []
    for key, value in tags.items():
        parts.append(f"{key}=*" if value is True else f"{key}={value}")
    return ", ".join(parts)


def load_aoi(area_mode: str, shapefile_path: Path, places: list[str]) -> gpd.GeoDataFrame:
    if area_mode == "shapefile":
        gdf = gpd.read_file(shapefile_path)
        gdf = gdf.to_crs("EPSG:4326") if gdf.crs is not None else gdf.set_crs("EPSG:4326")
        return gpd.GeoDataFrame({"name": ["aoi"]}, geometry=[unary_union(gdf.geometry.values)], crs="EPSG:4326")
    if area_mode == "geocode":
        polys = [unary_union(ox.geocode_to_gdf(place).to_crs("EPSG:4326").geometry.values) for place in places]
        return gpd.GeoDataFrame({"name": ["aoi"]}, geometry=[unary_union(polys)], crs="EPSG:4326")
    raise ValueError(f"Unknown area_mode: {area_mode}")


def to_crs(gdf: gpd.GeoDataFrame, crs: str) -> gpd.GeoDataFrame:
    if gdf.crs is None:
        return gdf.set_crs("EPSG:4326").to_crs(crs)
    return gdf.to_crs(crs)


def to_metric_crs(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return to_crs(gdf, operation_crs)


def to_export_crs(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return to_crs(gdf, export_crs)


def explode_lines(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    gdf = gdf[gdf.geometry.notna()].copy()
    return gdf.explode(index_parts=False, ignore_index=True)


def safe_object_columns_for_parquet(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = gdf.copy()
    for col in out.columns:
        if col == out.geometry.name:
            continue
        if out[col].dtype != "object":
            continue
        normalized = []
        for value in out[col]:
            if isinstance(value, (list, tuple, set)):
                normalized.append(json.dumps(list(value)))
            elif value is None or pd.isna(value):
                normalized.append(None)
            else:
                normalized.append(str(value))
        out[col] = normalized
    return out


def export_gdf(gdf: gpd.GeoDataFrame, stem: str) -> None:
    gdf_export = to_export_crs(gdf)
    if "parquet" in export_formats:
        safe_object_columns_for_parquet(gdf_export).to_parquet(OUTPUT_DIR / f"{stem}.parquet", index=False)
    if "geojson" in export_formats:
        gdf_export.to_file(OUTPUT_DIR / f"{stem}.geojson", driver="GeoJSON")


def subdivide_polygon_for_download(polygon, tile_size_m: float) -> list:
    polygon_metric = gpd.GeoSeries([polygon], crs="EPSG:4326").to_crs(operation_crs).iloc[0]
    minx, miny, maxx, maxy = polygon_metric.bounds
    pieces = []
    x = minx
    while x < maxx:
        y = miny
        while y < maxy:
            cell = box(x, y, min(x + tile_size_m, maxx), min(y + tile_size_m, maxy))
            clipped = polygon_metric.intersection(cell)
            if clipped is not None and not clipped.is_empty:
                pieces.append(clipped)
            y += tile_size_m
        x += tile_size_m
    if not pieces:
        pieces = [polygon_metric]
    pieces_wgs84 = gpd.GeoSeries(pieces, crs=operation_crs).to_crs("EPSG:4326")
    return [geom for geom in pieces_wgs84 if geom is not None and not geom.is_empty]


def download_features_with_fallback(aoi_poly, tags, query_label: str) -> gpd.GeoDataFrame:
    polygons = subdivide_polygon_for_download(aoi_poly, download_tile_size_m)
    print(
        f"Requesting OSM {query_label}: {format_tags(tags)} | "
        f"tiles={len(polygons)} | base_tile_size_m={download_tile_size_m}"
    )

    def fetch_tile(polygon, tile_label: str, tile_size_m: float) -> gpd.GeoDataFrame:
        last_error = None

        for overpass_url in overpass_urls:
            ox.settings.overpass_url = overpass_url
            ox.settings.requests_timeout = overpass_timeout_s
            try:
                print(f"  tile {tile_label} via {overpass_url} | size_m={int(tile_size_m)}")
                chunk = ox.features_from_polygon(polygon, tags).reset_index()
                chunk = gpd.GeoDataFrame(chunk, geometry="geometry", crs="EPSG:4326")
                return chunk
            except Exception as exc:
                last_error = exc
                print(f"  failed on {overpass_url}: {exc.__class__.__name__}")

        if tile_size_m <= min_download_tile_size_m:
            raise last_error

        next_tile_size_m = max(tile_size_m / 2.0, float(min_download_tile_size_m))
        subtiles = subdivide_polygon_for_download(polygon, next_tile_size_m)
        if len(subtiles) <= 1:
            raise last_error

        print(
            f"  splitting tile {tile_label} into {len(subtiles)} subtiles "
            f"after {last_error.__class__.__name__} | next_size_m={int(next_tile_size_m)}"
        )

        subchunks = []
        for sub_idx, subtile in enumerate(subtiles, start=1):
            subchunk = fetch_tile(subtile, f"{tile_label}.{sub_idx}", next_tile_size_m)
            if not subchunk.empty:
                subchunks.append(subchunk)

        if not subchunks:
            return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs="EPSG:4326")

        return gpd.GeoDataFrame(pd.concat(subchunks, ignore_index=True), geometry="geometry", crs="EPSG:4326")

    chunks = []
    for idx, polygon in enumerate(polygons, start=1):
        chunk = fetch_tile(polygon, f"{idx}/{len(polygons)}", float(download_tile_size_m))
        if not chunk.empty:
            chunks.append(chunk)

    if not chunks:
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs="EPSG:4326")

    merged = gpd.GeoDataFrame(pd.concat(chunks, ignore_index=True), geometry="geometry", crs="EPSG:4326")
    if {"element", "id"}.issubset(merged.columns):
        merged = merged.drop_duplicates(subset=["element", "id"]).copy()
    return merged.reset_index(drop=True)


def classify_parking_feature(row) -> str:
    if as_lower_str(row.get("source_layer")) == "on_street":
        return "on_street"

    amenity = as_lower_str(row.get("amenity"))
    parking = as_lower_str(row.get("parking"))

    if amenity == "parking_space":
        return "parking_space"
    if amenity == "parking":
        return parking or "parking"
    if parking:
        return parking
    return "parking_other"


def normalize_parking_geometries(parking: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if parking.empty:
        return parking

    out = parking.copy()
    out["geometry_type_osm"] = out.geometry.geom_type

    surface_mask = out["geometry_type_osm"].isin(["Polygon", "MultiPolygon"])
    point_mask = out["geometry_type_osm"].eq("Point")
    fallback_mask = ~(surface_mask | point_mask)

    surfaces = out[surface_mask].copy()
    points = out[point_mask].copy()
    fallback = out[fallback_mask].copy()

    if not surfaces.empty:
        surfaces["geometry_kind"] = "surface"
    if not points.empty:
        points["geometry_kind"] = "point"
    if not fallback.empty:
        fallback_metric = to_metric_crs(fallback)
        fallback_metric["geometry"] = fallback_metric.geometry.centroid
        fallback = fallback_metric.to_crs("EPSG:4326")
        fallback["geometry_kind"] = "point_fallback"

    combined = gpd.GeoDataFrame(
        pd.concat([surfaces, points, fallback], ignore_index=True),
        geometry="geometry",
        crs="EPSG:4326",
    )
    combined["surface_m2"] = pd.NA

    surface_rows = combined["geometry_kind"].eq("surface")
    if surface_rows.any():
        areas = to_metric_crs(combined.loc[surface_rows].copy()).geometry.area.round(3)
        combined.loc[surface_rows, "surface_m2"] = areas.values

    combined["has_surface"] = combined["geometry_kind"].eq("surface")
    return combined


def has_positive_parking_tag(value) -> bool:
    return as_lower_str(value) not in ON_STREET_PARKING_NEGATIVE


def has_on_street_side(row, side: str) -> bool:
    candidates = [
        row.get(f"parking:{side}"),
        row.get(f"parking:lane:{side}"),
        row.get("parking:both"),
        row.get("parking:lane:both"),
    ]
    return any(has_positive_parking_tag(value) for value in candidates)


def infer_on_street_orientation(row, side: str) -> str:
    candidates = [
        as_lower_str(row.get(f"parking:{side}:orientation")),
        as_lower_str(row.get("parking:both:orientation")),
        as_lower_str(row.get(f"parking:lane:{side}")),
        as_lower_str(row.get("parking:lane:both")),
        as_lower_str(row.get(f"parking:{side}")),
        as_lower_str(row.get("parking:both")),
    ]

    if any("half" in value and "kerb" in value for value in candidates):
        return "half_on_kerb"
    if any("perpendicular" in value or "orthogonal" in value for value in candidates):
        return "perpendicular"
    if any("diagonal" in value or "angled" in value or "echelon" in value for value in candidates):
        return "diagonal"
    return "parallel"


def estimate_on_street_width_m(orientation: str) -> float:
    return PARKING_WIDTH_BY_ORIENTATION_M.get(orientation, PARKING_WIDTH_BY_ORIENTATION_M["parallel"])


def build_on_street_parking_surfaces(parking_ways: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if parking_ways.empty:
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs="EPSG:4326")

    lines = parking_ways[parking_ways.geometry.type.isin(["LineString", "MultiLineString"])].copy()
    if lines.empty:
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs="EPSG:4326")

    lines = explode_lines(lines)
    lines_metric = to_metric_crs(lines)

    rows = []
    for _, row in lines_metric.iterrows():
        if row.geometry is None or row.geometry.is_empty:
            continue

        for side in ["left", "right"]:
            if not has_on_street_side(row, side):
                continue

            orientation = infer_on_street_orientation(row, side)
            parking_width_m = estimate_on_street_width_m(orientation)
            offset_m = DEFAULT_CARRIAGEWAY_HALF_WIDTH_M + parking_width_m / 2.0

            try:
                offset_line = row.geometry.parallel_offset(offset_m, side, join_style=2)
            except Exception:
                offset_line = None

            if offset_line is None or offset_line.is_empty:
                continue

            parking_band = offset_line.buffer(parking_width_m / 2.0, cap_style=2, join_style=2)
            if parking_band is None or parking_band.is_empty:
                continue

            new_row = row.drop(labels=["geometry"]).to_dict()
            new_row.update(
                {
                    "geometry": parking_band,
                    "source": "OSM_on_street_parking",
                    "source_layer": "on_street",
                    "geometry_kind": "surface_estimated",
                    "geometry_type_osm": "LineString",
                    "has_surface": True,
                    "parking_side": side,
                    "parking_orientation": orientation,
                    "estimated_width_m": parking_width_m,
                }
            )
            rows.append(new_row)

    if not rows:
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs="EPSG:4326")

    out = gpd.GeoDataFrame(rows, geometry="geometry", crs=operation_crs).to_crs("EPSG:4326")
    out["surface_m2"] = to_metric_crs(out).geometry.area.round(3).values
    return out


print("Loading AOI...")
aoi = load_aoi(area_mode, shapefile_path, places)
aoi_poly = aoi.geometry.iloc[0]

print("Downloading OSM parking features...")
parking_parts = []
for query_name, tags in parking_queries:
    chunk = download_features_with_fallback(aoi_poly, tags, query_name)
    if chunk.empty:
        continue
    chunk["query_name"] = query_name
    chunk["source_layer"] = "mapped"
    parking_parts.append(chunk)

if parking_parts:
    parking_raw = gpd.GeoDataFrame(pd.concat(parking_parts, ignore_index=True), geometry="geometry", crs="EPSG:4326")
else:
    parking_raw = gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs="EPSG:4326")

if {"element", "id"}.issubset(parking_raw.columns):
    parking_raw["osm_id"] = parking_raw["element"].astype(str) + "/" + parking_raw["id"].astype(str)
    parking_raw = parking_raw.drop_duplicates(subset=["osm_id"]).copy()
else:
    parking_raw["osm_id"] = None

parking_raw = parking_raw[parking_raw.geometry.notna()].copy()
parking_spaces = normalize_parking_geometries(parking_raw)
parking_spaces["parking_type"] = parking_spaces.apply(classify_parking_feature, axis=1)
parking_spaces["source"] = "OSM_parking"

street_parking_raw = download_features_with_fallback(
    aoi_poly,
    on_street_parking_tags,
    "on-street parking tags on road axes",
)
street_parking_raw = street_parking_raw[street_parking_raw.geometry.notna()].copy()
if not street_parking_raw.empty and {"element", "id"}.issubset(street_parking_raw.columns):
    street_parking_raw["osm_id"] = street_parking_raw["element"].astype(str) + "/" + street_parking_raw["id"].astype(str)
street_parking = build_on_street_parking_surfaces(street_parking_raw)
if not street_parking.empty:
    street_parking["parking_type"] = street_parking.apply(classify_parking_feature, axis=1)

parking_spaces = gpd.GeoDataFrame(
    pd.concat([parking_spaces, street_parking], ignore_index=True),
    geometry="geometry",
    crs="EPSG:4326",
)

for col, default in {
    "geometry_kind": None,
    "geometry_type_osm": None,
    "has_surface": False,
    "surface_m2": pd.NA,
    "osm_id": None,
    "source_layer": "mapped",
    "parking_side": None,
    "parking_orientation": None,
    "estimated_width_m": pd.NA,
}.items():
    if col not in parking_spaces.columns:
        parking_spaces[col] = default

keep_cols = [
    "geometry",
    "source",
    "parking_type",
    "geometry_kind",
    "geometry_type_osm",
    "has_surface",
    "surface_m2",
    "osm_id",
    "source_layer",
    "parking_side",
    "parking_orientation",
    "estimated_width_m",
]
for col in [
    "element",
    "id",
    "amenity",
    "parking",
    "capacity",
    "access",
    "covered",
    "fee",
    "name",
    "operator",
    "supervised",
    "surface",
    "parking_space",
    "parking:left",
    "parking:right",
    "parking:both",
    "parking:lane:left",
    "parking:lane:right",
    "parking:lane:both",
    "parking:left:orientation",
    "parking:right:orientation",
    "parking:both:orientation",
    "highway",
    "query_name",
]:
    if col in parking_spaces.columns:
        keep_cols.append(col)

parking_spaces = gpd.GeoDataFrame(parking_spaces[keep_cols].copy(), geometry="geometry", crs="EPSG:4326")

print("Exporting parking_spaces...")
export_gdf(parking_spaces, "parking_spaces")

surface_count = int(parking_spaces["geometry_kind"].isin(["surface", "surface_estimated"]).sum()) if not parking_spaces.empty else 0
point_count = int(parking_spaces["geometry_kind"].isin(["point", "point_fallback"]).sum()) if not parking_spaces.empty else 0
on_street_count = int(parking_spaces["source_layer"].eq("on_street").sum()) if not parking_spaces.empty else 0

print(f"parking_spaces: {len(parking_spaces)} features")
print(f"surfaces: {surface_count}")
print(f"points: {point_count}")
print(f"on_street_surfaces: {on_street_count}")
print(f"Export directory: {OUTPUT_DIR.resolve()}")
