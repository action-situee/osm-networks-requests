"""Minimal Step 0 pipeline exporting only walk_network and bike_network."""

from __future__ import annotations

import json
import re
import warnings
from pathlib import Path

import geopandas as gpd
import numpy as np
import osmnx as ox
import pandas as pd
from shapely.geometry import LineString, MultiPoint, Point, box
from shapely.ops import split, unary_union

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Outputs
output_dir = OUTPUT_DIR

# Area of interest
# Default: exact Grand Geneve perimeter shipped in ./input
# Alternative: set area_mode = "geocode" and adjust places.
area_mode = "geocode"  # "shapefile" or "geocode"
shapefile_path = INPUT_DIR / "AGGLO_PERIMETRE_AVEC_LAC.shp"
places = ["Carouge, Switzerland", "Lancy, Switzerland", "Thônex, Switzerland","Saint-Julien-en-Genevois, France"]

# Export
export_formats = ["parquet", "geojson"]
operation_crs = "EPSG:2056"
export_crs = "EPSG:4326"
apply_network_cleanup = True

# OSM download robustness
overpass_urls = [
    "https://overpass-api.de/api",
    "https://overpass.kumi.systems/api",
    "https://overpass.private.coffee/api",
]
overpass_timeout_s = 600
download_tile_size_m = 12000

ox.settings.use_cache = True
ox.settings.requests_timeout = overpass_timeout_s

# Walk consolidation
add_platform_edges = True
add_crossing_edges = True
add_sidewalk_proxy = True
clean_doublons = True
deduplicate_by_geometry = True
simplify_tol_m = 0.0

proxy_include_highways = {
    "residential",
    "living_street",
    "service",
    "unclassified",
    "tertiary",
    "path",
    "track",
}
proxy_maxspeed_kmh = 60
proxy_require_sidewalk_tag = False
crossing_snap_dist_m = 12.0
crossing_halfwidth_m = 6.0
crossing_min_road_classes = {
    "residential",
    "living_street",
    "service",
    "unclassified",
    "tertiary",
    "secondary",
    "primary",
    "path",
    "track",
}

WALK_DEDICATED_HW = {"footway", "pedestrian", "steps", "corridor", "platform"}
WALK_PATHLIKE_HW = {"path"}
SIDEWALK_OK = {"both", "left", "right", "yes", "separate"}
WALK_PROXY_ROAD_HW = {
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "motorway_link",
    "trunk_link",
    "primary_link",
    "secondary_link",
    "tertiary_link",
    "unclassified",
    "residential",
    "living_street",
    "service",
}
BIKE_VALID_CLASSES = {
    "bike_cycleway",
    "bike_track",
    "bike_lane",
    "bike_shared",
    "bike_path",
    "bike_path_designated",
    "bike_pedestrian_area",
    "bike_road",
    "bike_busway",
}
MOTOR_AXES = {
    "primary",
    "secondary",
    "tertiary",
    "primary_link",
    "secondary_link",
    "tertiary_link",
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


def simplify_gdf(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if simplify_tol_m <= 0:
        return gdf
    original_crs = gdf.crs
    gdf_metric = to_metric_crs(gdf).copy()
    gdf_metric["geometry"] = gdf_metric.geometry.simplify(simplify_tol_m, preserve_topology=True)
    return to_crs(gdf_metric, str(original_crs))


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
        safe_object_columns_for_parquet(gdf_export).to_parquet(output_dir / f"{stem}.parquet", index=False)
    if "geojson" in export_formats:
        gdf_export.to_file(output_dir / f"{stem}.geojson", driver="GeoJSON")
    if "gpkg" in export_formats:
        gdf_export.to_file(output_dir / f"{stem}.gpkg", driver="GPKG")


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


def download_features_with_fallback(aoi_poly, tags, geometry_types: set[str], query_label: str) -> gpd.GeoDataFrame:
    polygons = subdivide_polygon_for_download(aoi_poly, download_tile_size_m)
    chunks = []
    last_error = None

    print(f"Requesting OSM {query_label}: {format_tags(tags)} | tiles={len(polygons)}")

    for idx, polygon in enumerate(polygons, start=1):
        success = False
        for overpass_url in overpass_urls:
            ox.settings.overpass_url = overpass_url
            ox.settings.requests_timeout = overpass_timeout_s
            try:
                print(f"  tile {idx}/{len(polygons)} via {overpass_url}")
                chunk = ox.features_from_polygon(polygon, tags).reset_index()
                chunk = gpd.GeoDataFrame(chunk, geometry="geometry", crs="EPSG:4326")
                if geometry_types:
                    chunk = chunk[chunk.geometry.type.isin(geometry_types)].copy()
                if not chunk.empty:
                    chunks.append(chunk)
                success = True
                break
            except Exception as exc:
                last_error = exc
                print(f"  failed on {overpass_url}: {exc.__class__.__name__}")
        if not success and last_error is not None:
            raise last_error

    if not chunks:
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs="EPSG:4326")

    merged = gpd.GeoDataFrame(pd.concat(chunks, ignore_index=True), geometry="geometry", crs="EPSG:4326")
    if {"element", "id"}.issubset(merged.columns):
        merged = merged.drop_duplicates(subset=["element", "id"]).copy()
    return merged.reset_index(drop=True)


def parse_maxspeed_kmh(value) -> float | None:
    value = first_scalar(value)
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    text = str(value).lower().replace("km/h", "").replace("kph", "").strip()
    if text in {"none", "signals", "variable"}:
        return None
    if ";" in text:
        text = text.split(";")[0].strip()
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    return float(match.group(1)) if match else None


def has_explicit_sidewalk(row) -> bool:
    sidewalk = as_lower_str(row.get("sidewalk"))
    if sidewalk == "no":
        return False
    if sidewalk in {"yes", "both", "left", "right", "separate"}:
        return True
    return as_lower_str(row.get("footway")) == "sidewalk"


def has_priority_sidewalk_tag(row) -> bool:
    values = {
        as_lower_str(row.get("sidewalk")),
        as_lower_str(row.get("sidewalk:left")),
        as_lower_str(row.get("sidewalk:right")),
    }
    if values & SIDEWALK_OK:
        return True
    return as_lower_str(row.get("footway")) == "sidewalk"


def has_sidewalk_tag(value) -> bool:
    text = as_lower_str(value)
    return text not in {"", "no", "none", "separate", "separated"}


def is_zone_20(row) -> bool:
    return as_lower_str(row.get("zone:maxspeed")) == "ch:zone20" or as_lower_str(row.get("maxspeed:type")) == "ch:zone20"


def classify_walk(row) -> str:
    highway = as_lower_str(row.get("highway"))
    foot = as_lower_str(row.get("foot"))
    access = as_lower_str(row.get("access"))
    if foot == "no":
        return "exclude"
    if access in {"no", "private"} and foot not in {"yes", "designated", "permissive"}:
        return "exclude"
    if highway in WALK_DEDICATED_HW:
        return "walk_dedicated"
    if highway in WALK_PATHLIKE_HW:
        return "walk_path"
    if highway in WALK_PROXY_ROAD_HW and has_explicit_sidewalk(row):
        return "walk_proxy_sidewalk"
    if highway in WALK_PROXY_ROAD_HW:
        maxspeed = parse_maxspeed_kmh(row.get("maxspeed"))
        if is_zone_20(row) or (maxspeed is not None and maxspeed <= 20):
            return "walk_proxy_zone20"
    return "other"


def classify_bike(row) -> str:
    highway = as_lower_str(row.get("highway"))
    bicycle = as_lower_str(row.get("bicycle"))
    access = as_lower_str(row.get("access"))
    if bicycle == "no":
        return "exclude"
    if access in {"no", "private"} and bicycle not in {"yes", "designated", "permissive"}:
        return "exclude"
    if highway == "cycleway":
        return "bike_cycleway"
    cycleway_tags = [
        as_lower_str(row.get("cycleway")),
        as_lower_str(row.get("cycleway:left")),
        as_lower_str(row.get("cycleway:right")),
        as_lower_str(row.get("cycleway:both")),
    ]
    if any("track" in tag or "separated" in tag for tag in cycleway_tags):
        return "bike_track"
    if any("lane" in tag or "advisory" in tag for tag in cycleway_tags):
        return "bike_lane"
    if any("shared" in tag for tag in cycleway_tags):
        return "bike_shared"
    if highway in {"path", "track", "bridleway"}:
        return "bike_path_designated" if bicycle in {"designated", "yes"} else "bike_path"
    if highway == "pedestrian" and bicycle in {"yes", "designated", "permissive"}:
        return "bike_pedestrian_area"
    motorized = {
        "motorway",
        "trunk",
        "primary",
        "secondary",
        "tertiary",
        "motorway_link",
        "trunk_link",
        "primary_link",
        "secondary_link",
        "tertiary_link",
        "unclassified",
        "residential",
        "living_street",
        "service",
    }
    if highway in motorized:
        if highway in {"motorway", "motorway_link"} and bicycle not in {"yes", "designated"}:
            return "exclude"
        if highway in {"trunk", "trunk_link"} and bicycle not in {"yes", "designated", "permissive"}:
            return "exclude"
        return "bike_road"
    if highway == "bus_guideway" and bicycle in {"yes", "designated"}:
        return "bike_busway"
    return "other"


def platform_edges_from_polygon(aoi_poly) -> gpd.GeoDataFrame:
    out_cols = ["geometry", "walk_class", "source", "osm_id"]
    try:
        platforms = download_features_with_fallback(
            aoi_poly,
            {"public_transport": "platform"},
            {"Polygon", "MultiPolygon"},
            "platform polygons for walk network",
        )
    except Exception:
        return gpd.GeoDataFrame(columns=out_cols, geometry="geometry", crs="EPSG:4326")
    if "element" in platforms.columns and "id" in platforms.columns:
        platforms["osm_id"] = platforms["element"].astype(str) + "/" + platforms["id"].astype(str)
    else:
        platforms["osm_id"] = None
    platforms = platforms[platforms.geometry.type.isin(["Polygon", "MultiPolygon"])].copy()
    platforms["geometry"] = platforms.geometry.boundary
    platforms = explode_lines(platforms)
    platforms["walk_class"] = "platform_edge"
    platforms["source"] = "OSM_platform_polygon"
    return platforms[out_cols].copy()


def sidewalk_proxy_from_roads(ways: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    roads = ways[ways["highway"].isin(proxy_include_highways)].copy()
    if roads.empty:
        return gpd.GeoDataFrame(columns=["geometry", "walk_class", "source", "osm_id"], geometry="geometry", crs=ways.crs)
    roads["_has_sidewalk"] = roads["sidewalk"].apply(has_sidewalk_tag) if "sidewalk" in roads.columns else False
    roads["_maxspeed_kmh"] = roads["maxspeed"].apply(parse_maxspeed_kmh) if "maxspeed" in roads.columns else None
    keep_mask = roads["_has_sidewalk"] | roads["_maxspeed_kmh"].isna() | (roads["_maxspeed_kmh"] <= float(proxy_maxspeed_kmh))
    if proxy_require_sidewalk_tag:
        keep_mask = roads["_has_sidewalk"]
    roads = roads[keep_mask].drop(columns=["_has_sidewalk", "_maxspeed_kmh"], errors="ignore")
    roads["walk_class"] = "sidewalk_proxy_road_axis"
    roads["source"] = "OSM_highway_proxy"
    keep_cols = ["geometry", "walk_class", "source", "highway", "osm_id"]
    for col in ["id", "element", "sidewalk", "sidewalk:left", "sidewalk:right", "footway", "maxspeed", "name", "service", "access", "foot"]:
        if col in roads.columns:
            keep_cols.append(col)
    return roads[keep_cols].copy()


def build_crossing_edges(nodes_cross: gpd.GeoDataFrame, roads: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out_cols = ["geometry", "walk_class", "source", "osm_id"]
    if nodes_cross.empty or roads.empty:
        return gpd.GeoDataFrame(columns=out_cols, geometry="geometry", crs="EPSG:4326")
    nodes = to_metric_crs(nodes_cross)
    roads_metric = to_metric_crs(roads)
    roads_metric = roads_metric[roads_metric.geometry.type.isin(["LineString", "MultiLineString"])].copy()
    if roads_metric.empty:
        return gpd.GeoDataFrame(columns=out_cols, geometry="geometry", crs="EPSG:4326")
    sindex = roads_metric.sindex
    segments = []
    for point in nodes.geometry:
        if point is None or point.is_empty:
            continue
        candidates = roads_metric.iloc[list(sindex.intersection(point.buffer(crossing_snap_dist_m).bounds))].copy()
        if candidates.empty:
            continue
        candidates["dist"] = candidates.distance(point)
        candidates = candidates[candidates["dist"] <= crossing_snap_dist_m].sort_values("dist")
        if candidates.empty:
            continue
        road = candidates.iloc[0].geometry
        proj_d = road.project(point)
        proj = road.interpolate(proj_d)
        p1 = road.interpolate(max(proj_d - 1.0, 0.0))
        p2 = road.interpolate(min(proj_d + 1.0, road.length))
        vx = p2.x - p1.x
        vy = p2.y - p1.y
        norm = (vx**2 + vy**2) ** 0.5
        if norm == 0:
            continue
        nx_ = -vy / norm
        ny_ = vx / norm
        segments.append(
            LineString(
                [
                    (proj.x - nx_ * crossing_halfwidth_m, proj.y - ny_ * crossing_halfwidth_m),
                    (proj.x + nx_ * crossing_halfwidth_m, proj.y + ny_ * crossing_halfwidth_m),
                ]
            )
        )
    if not segments:
        return gpd.GeoDataFrame(columns=out_cols, geometry="geometry", crs="EPSG:4326")
    gdf = gpd.GeoDataFrame(
        {"walk_class": ["crossing_synthetic"] * len(segments), "source": ["OSM_crossing_node_proxy"] * len(segments), "osm_id": [None] * len(segments)},
        geometry=segments,
        crs=operation_crs,
    )
    return gdf.to_crs("EPSG:4326")[out_cols].copy()


def map_bike_infra(row) -> str:
    bike_class = str(row.get("bike_class", ""))
    if bike_class in {"bike_cycleway", "bike_track"}:
        return "piste_cyclable"
    if bike_class in {"bike_lane", "bike_shared"}:
        return "bande_cyclable"
    if bike_class in {"bike_path", "bike_path_designated"}:
        return "chemin"
    if bike_class in {"bike_pedestrian_area", "bike_busway"}:
        return "voie_speciale"
    if bike_class == "bike_road":
        return "sur_chaussee"
    return "inconnu"


def get_bike_direction(row) -> str:
    oneway_bicycle = as_lower_str(row.get("oneway:bicycle"))
    oneway = as_lower_str(row.get("oneway"))
    if oneway_bicycle == "yes":
        return "oneway"
    if oneway_bicycle == "-1":
        return "reverse"
    if oneway_bicycle == "no":
        return "both"
    if oneway == "yes":
        return "oneway"
    if oneway == "-1":
        return "reverse"
    return "both"


def assign_walk_role(row) -> str:
    walk_class = str(row.get("walk_class", ""))
    highway = str(row.get("highway", ""))
    if walk_class == "crossing_synthetic":
        return "crossing"
    if walk_class == "sidewalk_proxy_road_axis":
        return "proxy_primary" if highway in MOTOR_AXES else "proxy_local"
    return "dedicated"


def assign_walk_tier(row) -> str:
    walk_class = str(row.get("walk_class", ""))
    highway = as_lower_str(row.get("highway"))

    if walk_class in {"walk_dedicated", "walk_path", "platform_edge", "crossing_synthetic"}:
        return "priority"

    if highway == "living_street":
        return "priority"

    if walk_class == "sidewalk_proxy_road_axis":
        return "priority" if has_priority_sidewalk_tag(row) else "secondary"

    return "secondary"


def drop_proxy_duplicates(walk_edges: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if not clean_doublons:
        return walk_edges
    dedicated = walk_edges[walk_edges["walk_class"] != "sidewalk_proxy_road_axis"].copy()
    proxy = walk_edges[walk_edges["walk_class"] == "sidewalk_proxy_road_axis"].copy()
    proxy_test_highways = {"primary", "secondary", "tertiary", "primary_link", "secondary_link", "tertiary_link", "residential", "living_street"}
    proxy_keep = proxy[~proxy["highway"].isin(proxy_test_highways)].copy()
    proxy_test = proxy[proxy["highway"].isin(proxy_test_highways)].copy()
    if dedicated.empty or proxy_test.empty:
        return pd.concat([dedicated, proxy_keep, proxy_test], ignore_index=True)
    sindex = dedicated.sindex
    keep_flags = []
    for _, row in proxy_test.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            keep_flags.append(True)
            continue
        hits = list(sindex.intersection(geom.buffer(6.0).bounds))
        if not hits:
            keep_flags.append(True)
            continue
        nearby = dedicated.iloc[hits].copy()
        nearby = nearby[nearby.distance(geom) <= 6.0]
        if "len_m" in nearby.columns:
            nearby = nearby[nearby["len_m"] >= 8.0]
        if nearby.empty:
            keep_flags.append(True)
            continue
        cover_zone = unary_union(list(nearby.geometry)).buffer(6.0)
        covered = geom.intersection(cover_zone).length if not geom.intersection(cover_zone).is_empty else 0.0
        total = geom.length if geom.length else 0.0
        keep_flags.append(not (covered >= 20.0 and total > 0 and covered / total >= 0.5))
    proxy_test = proxy_test.loc[keep_flags].copy()
    return pd.concat([dedicated, proxy_keep, proxy_test], ignore_index=True)


def deduplicate_geometry(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if not deduplicate_by_geometry or gdf.empty:
        return gdf
    out = gdf.copy()
    out["__wkb"] = out.geometry.to_wkb()
    out = out.drop_duplicates(subset="__wkb").drop(columns="__wkb")
    return out


def _iter_intersection_points(geom):
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "Point":
        return [geom]
    if geom.geom_type == "MultiPoint":
        return list(geom.geoms)
    if geom.geom_type == "GeometryCollection":
        points = []
        for part in geom.geoms:
            points.extend(_iter_intersection_points(part))
        return points
    return []


def split_edges_at_intersections(edges: gpd.GeoDataFrame, min_seg_len_m: float = 1.0) -> gpd.GeoDataFrame:
    edges_metric = to_metric_crs(edges).copy()
    edges_metric = edges_metric[edges_metric.geometry.notna()].copy()
    edges_metric = edges_metric[edges_metric.geometry.geom_type == "LineString"].copy()
    edges_metric = edges_metric.reset_index(drop=True)
    if edges_metric.empty:
        return edges_metric
    sindex = edges_metric.sindex
    split_points = {idx: [] for idx in edges_metric.index}
    for idx, geom_i in zip(edges_metric.index, edges_metric.geometry):
        for jdx in sindex.intersection(geom_i.bounds):
            if jdx <= idx:
                continue
            geom_j = edges_metric.geometry.iloc[jdx]
            if not geom_i.intersects(geom_j):
                continue
            points = _iter_intersection_points(geom_i.intersection(geom_j))
            if not points:
                continue
            split_points[idx].extend(points)
            split_points[jdx].extend(points)
    rows = []
    for idx, row in edges_metric.iterrows():
        geom = row.geometry
        points = split_points[idx] + [Point(geom.coords[0]), Point(geom.coords[-1])]
        seen = set()
        unique_points = []
        for point in points:
            if point.wkb in seen:
                continue
            seen.add(point.wkb)
            unique_points.append(point)
        try:
            pieces = list(split(geom, MultiPoint(unique_points)).geoms) if len(unique_points) > 2 else [geom]
        except Exception:
            pieces = [geom]
        for piece in pieces:
            if piece is None or piece.is_empty or piece.length < min_seg_len_m:
                continue
            new_row = row.drop(labels=["geometry"]).to_dict()
            rows.append({**new_row, "geometry": piece})
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=operation_crs).reset_index(drop=True)


print("Loading AOI...")
aoi = load_aoi(area_mode, shapefile_path, places)
aoi_poly = aoi.geometry.iloc[0]

print(f"Network cleanup: {'enabled' if apply_network_cleanup else 'disabled'}")

ways_raw = download_features_with_fallback(
    aoi_poly,
    {"highway": True},
    {"LineString", "MultiLineString"},
    "linear ways for bike and walk network",
)
ways_raw = explode_lines(ways_raw)
ways_raw["osm_id"] = ways_raw["element"].astype(str) + "/" + ways_raw["id"].astype(str)

try:
    nodes_cross = download_features_with_fallback(
        aoi_poly,
        {"highway": "crossing"},
        {"Point"},
        "crossing nodes for synthetic walk crossings",
    )
except Exception:
    nodes_cross = gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs="EPSG:4326")

print("Classifying OSM ways...")
ways = ways_raw.copy()
ways["walk_class"] = ways.apply(classify_walk, axis=1)
ways["bike_class"] = ways.apply(classify_bike, axis=1)

walk_dedicated = ways[ways["walk_class"].isin({"walk_dedicated", "walk_path"})].copy()
bike_base = ways[ways["bike_class"].isin(BIKE_VALID_CLASSES)].copy()

walk_parts = []
walk_dedicated["source"] = "OSM_highway_dedicated"
walk_keep_cols = ["geometry", "walk_class", "source", "highway", "osm_id"]
for col in ["id", "element", "footway", "sidewalk", "sidewalk:left", "sidewalk:right", "name", "maxspeed", "service", "access", "foot"]:
    if col in walk_dedicated.columns:
        walk_keep_cols.append(col)
walk_parts.append(walk_dedicated[walk_keep_cols])

if add_platform_edges:
    if apply_network_cleanup:
        walk_parts.append(platform_edges_from_polygon(aoi_poly))
if add_sidewalk_proxy:
    walk_parts.append(sidewalk_proxy_from_roads(ways))
if add_crossing_edges:
    if apply_network_cleanup:
        roads_for_crossings = ways[ways["highway"].isin(crossing_min_road_classes)].copy()
        walk_parts.append(build_crossing_edges(nodes_cross, roads_for_crossings))

walk_network = gpd.GeoDataFrame(pd.concat(walk_parts, ignore_index=True), geometry="geometry", crs="EPSG:4326")
walk_network = walk_network[walk_network.geometry.notna()].copy()
walk_network = to_metric_crs(walk_network)
walk_network = explode_lines(walk_network)
if apply_network_cleanup:
    walk_network = simplify_gdf(walk_network)
walk_network["len_m"] = walk_network.length
walk_network["walk_role"] = walk_network.apply(assign_walk_role, axis=1)
if apply_network_cleanup:
    walk_network = drop_proxy_duplicates(walk_network)
    walk_network = deduplicate_geometry(walk_network)
    walk_network = split_edges_at_intersections(walk_network, min_seg_len_m=1.0)
walk_network["length"] = walk_network.length
walk_network["tier"] = walk_network.apply(assign_walk_tier, axis=1)

bike_network = bike_base.copy()
bike_network["infra_bike"] = bike_network.apply(map_bike_infra, axis=1)
bike_network["bike_direction"] = bike_network.apply(get_bike_direction, axis=1)
bike_network["source"] = "OSM_highway_bike"
bike_keep_cols = ["geometry", "infra_bike", "bike_direction", "source", "highway"]
for col in ["cycleway", "cycleway:left", "cycleway:right", "bicycle", "oneway", "oneway:bicycle", "name", "maxspeed", "osmid"]:
    if col in bike_network.columns:
        bike_keep_cols.append(col)
bike_network = gpd.GeoDataFrame(bike_network[bike_keep_cols].copy(), geometry="geometry", crs="EPSG:4326")
bike_network = to_metric_crs(bike_network)
bike_network = explode_lines(bike_network)
if apply_network_cleanup:
    bike_network = simplify_gdf(bike_network)
bike_network["len_m"] = bike_network.length
if apply_network_cleanup:
    bike_network = deduplicate_geometry(bike_network)
    bike_network = split_edges_at_intersections(bike_network, min_seg_len_m=1.0)
bike_network["length"] = bike_network.length

print("Exporting walk_network and bike_network...")
export_gdf(walk_network, "walk_network")
export_gdf(bike_network, "bike_network")

print(f"walk_network: {len(walk_network)} segments")
print(f"bike_network: {len(bike_network)} segments")
print(f"Export directory: {output_dir.resolve()}")
