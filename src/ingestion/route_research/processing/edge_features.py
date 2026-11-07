#!/usr/bin/env python3
"""Per-street-segment features consumed by the route model (via segment_features merge).

For every directed edge of the walk network (segment_id = "u:v:key", same key as normalize.py):
  width_m                 feature 2 (`log_width`) and 3 (`turnout_x_width`)
  betweenness_main        feature 5 (`log_betweenness`): exact edge betweenness on the main-road
                          network only; 0 off main (one estimator, one graph)
  to_degree               junction degree at the downstream node (loaded in graph.py)
  is_main                 feature 4
  in_no_entry_zone        drops segments in graph.from_database (forbidden)
  in_restricted_zone      feature 9
  in_royal_park           feature 8

Royal park polygons: raw/landmarks/open_spaces.geoparquet. Legal zones: seed/legal_zones.geojson.
Crowd capacity / Fruin density were considered; see docs/crowd-density-note.md.

OUT: normalised/edge_features.csv
"""

from __future__ import annotations

import argparse
import ast
import re
import time
from pathlib import Path

import geopandas as gpd
import networkx as nx
import osmnx as ox
import pandas as pd

from src.config import LEGAL_ZONES_PATH
from src.ingestion.route_research.context import StepContext
from src.ingestion.route_research.runner import run_cli_step

LANE_M, PAVEMENTS_M = 3.25, 5.0
CARRIAGEWAYS = {
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "unclassified",
    "residential",
    "service",
    "living_street",
    "trunk_link",
    "primary_link",
    "secondary_link",
    "tertiary_link",
}
DEFAULT_WIDTH_M = {
    "trunk": 22,
    "trunk_link": 12,
    "primary": 18,
    "primary_link": 10,
    "secondary": 15,
    "secondary_link": 9,
    "tertiary": 12,
    "tertiary_link": 8,
    "unclassified": 10,
    "residential": 10,
    "living_street": 8,
    "service": 6,
    "pedestrian": 10,
    "footway": 3,
    "path": 2.5,
    "cycleway": 3,
    "steps": 2.5,
    "track": 3,
    "bridleway": 3,
    "corridor": 2,
}
FALLBACK_WIDTH_M = 6


def as_list(value: object) -> list:
    if value is None or value != value:
        return []
    if isinstance(value, str) and value.startswith("["):
        try:
            value = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            pass
    return value if isinstance(value, list) else [value]


def parse_width(value: object) -> float | None:
    """Parse OSM width tags into metres (feature 2)."""
    for raw in as_list(value):
        text = str(raw).strip().lower().replace(",", ".")
        match = re.search(r"\d+(?:\.\d+)?", text)
        if match:
            metres = float(match.group()) * (0.3048 if ("'" in text or "ft" in text) else 1)
            return metres if 0.5 <= metres <= 80 else None
    return None


def parse_lanes(value: object) -> int | None:
    for raw in as_list(value):
        match = re.search(r"\d+", str(raw))
        if match and 0 < int(match.group()) <= 12:
            return int(match.group())
    return None


def estimate_width(highway: object, width: object, lanes: object) -> float:
    classes = as_list(highway)
    road = any(highway_class in CARRIAGEWAYS for highway_class in classes)
    parsed = parse_width(width)
    if parsed is not None:
        return parsed + PAVEMENTS_M if road else parsed
    lane_count = parse_lanes(lanes)
    if lane_count is not None and road:
        return lane_count * LANE_M + PAVEMENTS_M
    defaults = [
        DEFAULT_WIDTH_M[highway_class]
        for highway_class in classes
        if highway_class in DEFAULT_WIDTH_M
    ]
    return max(defaults) if defaults else FALLBACK_WIDTH_M


def undirected(graph: nx.MultiDiGraph) -> nx.Graph:
    """Simple undirected graph keeping the shortest parallel edge."""
    simple = nx.Graph()
    for u, v, data in graph.edges(data=True):
        length = float(data.get("length", 1.0))
        if not simple.has_edge(u, v) or length < simple[u][v]["length"]:
            simple.add_edge(u, v, length=length)
    return simple


def main_network_betweenness(main: nx.MultiDiGraph) -> dict[frozenset, float]:
    """Exact normalized edge betweenness on the main-road graph only (feature 5)."""
    simple = undirected(main)
    scores = nx.edge_betweenness_centrality(simple, weight="length", normalized=True)
    return {frozenset(edge): score for edge, score in scores.items()}


def zone_flags(edges: gpd.GeoDataFrame, zones_path: Path, open_spaces_path: Path) -> pd.DataFrame:
    flags = pd.DataFrame(
        False,
        index=edges.index,
        columns=["in_no_entry_zone", "in_restricted_zone", "in_royal_park"],
    )
    layers: list[tuple[str, gpd.GeoDataFrame]] = []
    if zones_path.exists():
        zones = gpd.read_file(zones_path).to_crs("EPSG:4326")
        layers += [
            ("in_no_entry_zone", zones[zones.rule_type == "no_entry"]),
            ("in_restricted_zone", zones[zones.rule_type == "restricted_activity"]),
        ]
    if open_spaces_path.exists():
        parks = gpd.read_parquet(open_spaces_path).to_crs("EPSG:4326")
        if "royal_park" in parks:
            royal = parks[
                parks.royal_park.fillna(False).astype(bool)
                & parks.geom_type.isin(["Polygon", "MultiPolygon"])
            ]
            layers.append(("in_royal_park", royal))
    for column, polys in layers:
        if len(polys):
            hit = gpd.sjoin(
                edges[["geometry"]], polys[["geometry"]], predicate="intersects", how="inner"
            ).index.unique()
            flags.loc[hit, column] = True
    return flags


def build(
    walk: nx.MultiDiGraph,
    main: nx.MultiDiGraph | None,
    zones_path: Path,
    open_spaces_path: Path,
) -> pd.DataFrame:
    t0 = time.monotonic()
    main_scores = main_network_betweenness(main) if main is not None else {}
    print(f"main-network betweenness: {time.monotonic() - t0:.0f}s")
    main_ids = set(main.edges(keys=True)) if main is not None else set()
    walk_simple = undirected(walk)
    edges = ox.graph_to_gdfs(walk, nodes=False, edges=True).reset_index()
    rows = []
    for edge in edges.itertuples(index=False):
        attrs = edge._asdict()
        width = estimate_width(attrs.get("highway"), attrs.get("width"), attrs.get("lanes"))
        pair = frozenset((edge.u, edge.v))
        on_main = (edge.u, edge.v, edge.key) in main_ids
        betweenness = float(main_scores.get(pair, 0.0)) if on_main else 0.0
        to_degree = walk_simple.degree(edge.v)
        rows.append(
            {
                "segment_id": f"{int(edge.u)}:{int(edge.v)}:{int(edge.key)}",
                "width_m": round(width, 1),
                "betweenness_main": betweenness,
                "to_degree": to_degree,
                "is_main": on_main,
                "in_no_entry_zone": False,
                "in_restricted_zone": False,
                "in_royal_park": False,
            }
        )
    out = pd.DataFrame(rows)
    flags = zone_flags(edges, zones_path, open_spaces_path)
    out[["in_no_entry_zone", "in_restricted_zone", "in_royal_park"]] = flags[
        ["in_no_entry_zone", "in_restricted_zone", "in_royal_park"]
    ].values
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--walk", default="raw/osm/london_walk.graphml")
    parser.add_argument("--main", default="raw/osm/london_main.graphml")
    parser.add_argument("--legal-zones", default=str(LEGAL_ZONES_PATH))
    parser.add_argument("--open-spaces", default="raw/landmarks/open_spaces.geoparquet")
    parser.add_argument("--output", default="normalised/edge_features.csv")
    args = parser.parse_args(argv)
    walk = ox.load_graphml(args.walk)
    main_graph = ox.load_graphml(args.main) if Path(args.main).exists() else None
    out = build(walk, main_graph, Path(args.legal_zones), Path(args.open_spaces))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output, index=False)
    print(
        f"{len(out):,} segments -> {output}; "
        f"{out.in_no_entry_zone.sum()} in no-entry zones, {out.in_royal_park.sum()} in Royal Parks"
    )


def run(context: StepContext, argv: list[str] | None = None) -> int:
    return run_cli_step(main, context, argv)


if __name__ == "__main__":
    main()
