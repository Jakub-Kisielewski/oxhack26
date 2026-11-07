#!/usr/bin/env python3
"""Normalise heterogeneous public datasets into linked schema keyed by street segment.

Critical provenance: raw historical waypoints are *planned*. Network connections
between them are algorithmically *inferred*, NEVER observed trajectories.

Input:
 --graph raw/osm/london_walk.graphml
 --events seed/events.csv
 --waypoints seed/waypoints.csv
 --review coordinate_review.csv (from seed-coords step)
Output: normalised/*.csv and normalised/segments.geojson
"""

from __future__ import annotations

import argparse
import csv
import logging
import math
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import networkx as nx
import osmnx as ox
import pandas as pd
from pyproj import Transformer

from src.config import (
    LONDON_LAT_MAX,
    LONDON_LAT_MIN,
    LONDON_LON_MAX,
    LONDON_LON_MIN,
    MAX_SNAP_DISTANCE_M,
)
from src.ingestion.route_research.context import StepContext
from src.ingestion.route_research.runner import run_cli_step

logger = logging.getLogger(__name__)

FIELDS_LABEL = [
    "event_id",
    "event_date",
    "segment_id",
    "sequence_index",
    "from_waypoint",
    "to_waypoint",
    "label_provenance",
    "source_url",
]


def write(rows: list[dict], path: Path, cols: list[str]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def tag(value: object) -> str:
    if isinstance(value, (list, tuple, set)):
        return "|".join(str(part) for part in value)
    if value is None:
        return ""
    return str(value)


def is_approved(row: dict) -> bool:
    return str(row.get("status", "")).lower().strip() == "approved"


def safe_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return None


def history_counts_before(routes: list[dict], before: str) -> dict[str, int]:
    """Per-segment counts using only events with event_date strictly before `before` (feature 10)."""
    counts: dict[str, int] = defaultdict(int)
    seen: set[tuple[str, str]] = set()
    for route in routes:
        if route.get("event_date", "") >= before:
            continue
        pair = (route["event_id"], route["segment_id"])
        if pair in seen:
            continue
        seen.add(pair)
        counts[route["segment_id"]] += 1
    return dict(counts)


def make_streets(graph: nx.MultiDiGraph, out: Path) -> pd.DataFrame:
    original = ox.graph_to_gdfs(graph, nodes=False, edges=True).reset_index()
    original = original.to_crs("EPSG:4326")
    rows: list[dict] = []
    geometries = []
    for _, edge in original.iterrows():
        segment_id = f"{int(edge['u'])}:{int(edge['v'])}:{int(edge['key'])}"
        geom = edge.geometry
        if geom is None or geom.is_empty:
            continue
        if geom.geom_type == "MultiLineString":
            raise ValueError(f"Unexpected MultiLineString edge {segment_id}")
        row = {
            "segment_id": segment_id,
            "u": int(edge["u"]),
            "v": int(edge["v"]),
            "key": int(edge["key"]),
            "length_m": round(float(edge.get("length", 0)), 2),
            "road_class": tag(edge.get("highway", "")),
            "street_name": tag(edge.get("name", "")),
            "network_type": "walk",
            "crs": "EPSG:4326",
            "source": "OpenStreetMap",
        }
        rows.append(row)
        geometries.append(geom)
    frame = pd.DataFrame(rows)
    streets = gpd.GeoDataFrame(frame, geometry=geometries, crs="EPSG:4326")
    streets.to_file(out / "segments.geojson", driver="GeoJSON")
    return frame


def join_waypoints(  # noqa: C901
    graph: nx.MultiDiGraph,
    events: pd.DataFrame,
    waypoints: pd.DataFrame,
    review: pd.DataFrame,
    out: Path,
    snap_max_m: float,
) -> list[dict]:
    eventdata = events.set_index("event_id").to_dict("index")
    ref = {
        str(row["waypoint_name"]).strip(): row for _, row in review.iterrows() if is_approved(row)
    }
    projected = ox.project_graph(graph)
    to_projected = Transformer.from_crs("EPSG:4326", projected.graph["crs"], always_xy=True)
    ready: list[dict] = []
    routes: list[dict] = []
    rejects: list[dict] = []
    for event_id, group in waypoints.groupby("event_id", sort=False):
        if event_id not in eventdata:
            continue
        event_row = eventdata[event_id]
        ordered = group.sort_values("sequence_index")
        approved: list[dict] = []
        for _, waypoint in ordered.iterrows():
            name = str(waypoint["waypoint_name"]).strip()
            review_row = ref.get(name)
            if review_row is None:
                rejects.append(
                    {"event_id": event_id, "waypoint_name": name, "reason": "not approved"}
                )
                continue
            lat = safe_float(review_row.get("latitude"))
            lon = safe_float(review_row.get("longitude"))
            if (
                lat is None
                or lon is None
                or not (
                    LONDON_LAT_MIN < lat < LONDON_LAT_MAX and LONDON_LON_MIN < lon < LONDON_LON_MAX
                )
            ):
                rejects.append(
                    {"event_id": event_id, "waypoint_name": name, "reason": "bad coordinate"}
                )
                continue
            proj_x, proj_y = to_projected.transform(lon, lat)
            nearest = ox.distance.nearest_nodes(projected, proj_x, proj_y)
            distance = math.hypot(
                projected.nodes[nearest]["x"] - proj_x, projected.nodes[nearest]["y"] - proj_y
            )
            if distance > snap_max_m:
                rejects.append(
                    {
                        "event_id": event_id,
                        "waypoint_name": name,
                        "reason": f"snap too far: {distance:.0f} m",
                    }
                )
                continue
            approved.append(
                {
                    "event_id": event_id,
                    "sequence_index": int(waypoint["sequence_index"]),
                    "waypoint_name": name,
                    "latitude": lat,
                    "longitude": lon,
                    "nearest_node": int(nearest),
                    "snap_distance_m": round(distance, 1),
                    "geo_review_status": "approved",
                    "event_date": event_row.get("event_date", ""),
                }
            )
        ready.extend(approved)
        by_order = {row["sequence_index"]: row for row in approved}
        records = ordered.to_dict("records")
        for left, right in zip(records[:-1], records[1:], strict=False):
            origin = by_order.get(int(left["sequence_index"]))
            dest = by_order.get(int(right["sequence_index"]))
            if origin is None or dest is None:
                continue
            try:
                nodes = nx.shortest_path(
                    graph, origin["nearest_node"], dest["nearest_node"], weight="length"
                )
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                rejects.append(
                    {
                        "event_id": event_id,
                        "waypoint_name": f"{origin['waypoint_name']} -> {dest['waypoint_name']}",
                        "reason": "graph has no walkable path",
                    }
                )
                continue
            sequence_index = sum(1 for existing in routes if existing["event_id"] == event_id)
            for start, end in zip(nodes[:-1], nodes[1:], strict=False):
                if start not in graph or end not in graph[start]:
                    continue
                parallel_key = min(
                    graph[start][end],
                    key=lambda key: float(graph[start][end][key].get("length", float("inf"))),
                )
                routes.append(
                    {
                        "event_id": event_id,
                        "event_date": event_row.get("event_date", ""),
                        "segment_id": f"{start}:{end}:{parallel_key}",
                        "sequence_index": sequence_index,
                        "from_waypoint": origin["waypoint_name"],
                        "to_waypoint": dest["waypoint_name"],
                        "label_provenance": "INFERRED_SHORTEST_PATH_BETWEEN_APPROVED_PLANNED_WAYPOINTS",
                        "source_url": event_row.get("source_url", ""),
                    }
                )
                sequence_index += 1
    write(
        ready,
        out / "waypoints_approved.csv",
        [
            "event_id",
            "event_date",
            "sequence_index",
            "waypoint_name",
            "latitude",
            "longitude",
            "nearest_node",
            "snap_distance_m",
            "geo_review_status",
        ],
    )
    write(routes, out / "route_segment_labels.csv", FIELDS_LABEL)
    write(rejects, out / "review_issues.csv", ["event_id", "waypoint_name", "reason"])
    print(
        f"approved waypoint appearances: {len(ready)}; inferred segment appearances: {len(routes)}; review issues: {len(rejects)}"
    )
    return routes


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", default="raw/osm/london_walk.graphml")
    parser.add_argument("--events", default="seed/events.csv")
    parser.add_argument("--waypoints", default="seed/waypoints.csv")
    parser.add_argument("--review", default="coordinate_review.csv")
    parser.add_argument("--outdir", default="normalised")
    parser.add_argument("--max-snap-distance-m", type=float, default=MAX_SNAP_DISTANCE_M)
    args = parser.parse_args(argv)
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    graph = ox.load_graphml(args.graph)
    edges = make_streets(graph, out)
    events = pd.read_csv(args.events, keep_default_na=False)
    waypoint_rows = pd.read_csv(args.waypoints, keep_default_na=False)
    events.to_csv(out / "events.csv", index=False)
    if Path(args.review).exists():
        review = pd.read_csv(args.review, keep_default_na=False)
    else:
        review = pd.DataFrame(columns=["waypoint_name", "latitude", "longitude", "status"])
        logger.warning("review file missing; no route segment labels will be generated")
    route = join_waypoints(graph, events, waypoint_rows, review, out, args.max_snap_distance_m)
    counts = pd.DataFrame(route)
    if len(counts):
        counts = (
            counts[["event_id", "segment_id"]]
            .drop_duplicates()
            .groupby("segment_id")
            .size()
            .rename("n_published_route_examples")
            .reset_index()
        )
        edges = edges.merge(counts, on="segment_id", how="left")
    else:
        edges["n_published_route_examples"] = 0
    edges["n_published_route_examples"] = edges.n_published_route_examples.fillna(0).astype(int)
    edges.to_csv(out / "segment_features.csv", index=False)
    print(
        f"Normalised {len(edges)} OSM segments into {out}; historic counts describe the full corpus only."
    )
    logger.warning(
        "For backtesting, recompute historical counts using ONLY events before the test event date"
    )


def run(context: StepContext, argv: list[str] | None = None) -> int:
    return run_cli_step(main, context, argv)


if __name__ == "__main__":
    main()
