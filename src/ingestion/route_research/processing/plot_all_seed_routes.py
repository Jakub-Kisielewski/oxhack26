#!/usr/bin/env python3
"""Plot every seed event route (waypoints.csv) on one OSM walk graph.

Geocodes unique waypoint names via Nominatim (cached on disk). Orange paths are
shortest walk routes between consecutive snapped nodes — not official polylines.

    python -m src.ingestion.protest_routes.processing.plot_all_seed_routes \\
        --graph raw/osm/london_walk.graphml \\
        --output testing/all_seed_routes.png
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import networkx as nx
import osmnx as ox
from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim

LONDON_VIEWBOX = [(51.44, -0.29), (51.57, 0.06)]
DEFAULT_CACHE = Path("src/ingestion/protest_routes/seed/geocode_cache.json")
DEFAULT_OVERRIDES = Path("src/ingestion/protest_routes/seed/waypoint_geocode_overrides.json")


def in_london(lat: float, lon: float) -> bool:
    return 51.44 <= lat <= 51.57 and -0.29 <= lon <= 0.06


def load_overrides(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def cache_entry_from_override(entry: dict) -> dict:
    return {
        "ok": True,
        "latitude": round(float(entry["latitude"]), 7),
        "longitude": round(float(entry["longitude"]), 7),
        "source": "manual_override",
        "nominatim_query": entry.get("nominatim_query"),
        "osm_display_name": entry.get("osm_display_name"),
        "notes": entry.get("notes"),
    }


def read_waypoints(path: Path) -> dict[str, list[dict]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    by_event: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_event[row["event_id"]].append(row)
    for seq in by_event.values():
        seq.sort(key=lambda r: int(r["sequence_index"]))
    return dict(by_event)


def load_cache(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_cache(path: Path, cache: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")


def geocode_labels(
    labels: list[str],
    cache_path: Path,
    overrides_path: Path,
    user_agent: str,
) -> dict[str, tuple[float, float]]:
    cache = load_cache(cache_path)
    overrides = load_overrides(overrides_path)
    geolocator = Nominatim(user_agent=user_agent, timeout=15)
    geocode_fn = RateLimiter(geolocator.geocode, min_delay_seconds=1.1, max_retries=2, error_wait_seconds=5)

    for label in labels:
        if label in overrides:
            cache[label] = cache_entry_from_override(overrides[label])
            save_cache(cache_path, cache)
            continue
        if label in cache and cache[label].get("ok"):
            continue
        query = f"{label}, London, England, UK"
        try:
            match = geocode_fn(
                query,
                exactly_one=True,
                country_codes="gb",
                viewbox=LONDON_VIEWBOX,
                bounded=True,
                addressdetails=False,
            )
        except Exception as exc:
            match = None
            cache[label] = {"ok": False, "error": str(exc), "nominatim_query": query}
            save_cache(cache_path, cache)
            continue
        if match and in_london(match.latitude, match.longitude):
            cache[label] = {
                "ok": True,
                "latitude": round(match.latitude, 7),
                "longitude": round(match.longitude, 7),
                "nominatim_query": query,
            }
        else:
            cache[label] = {"ok": False, "error": "out_of_bounds_or_unresolved", "nominatim_query": query}
        save_cache(cache_path, cache)
        print(f"Geocoded {label!r}: {cache[label]}")

    coords: dict[str, tuple[float, float]] = {}
    for label in labels:
        entry = cache.get(label, {})
        if entry.get("ok"):
            coords[label] = (entry["latitude"], entry["longitude"])
    return coords


def route_for_event(
    G: nx.MultiDiGraph,
    seq: list[dict],
    coords: dict[str, tuple[float, float]],
) -> list[int] | None:
    nodes: list[int] = []
    for item in seq:
        label = item["waypoint_name"].strip()
        if label not in coords:
            return None
        lat, lon = coords[label]
        node = ox.distance.nearest_nodes(G, X=lon, Y=lat)
        nodes.append(node)
    if len(nodes) < 2:
        return None
    full: list[int] = []
    for source, target in zip(nodes, nodes[1:]):
        try:
            segment = nx.shortest_path(G, source, target, weight="length")
        except nx.NetworkXNoPath:
            return None
        full.extend(segment if not full else segment[1:])
    return full if len(full) >= 2 else None


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--waypoints", default="src/ingestion/protest_routes/seed/waypoints.csv")
    p.add_argument("--graph", default="raw/osm/london_walk.graphml")
    p.add_argument("--geocode-cache", default=str(DEFAULT_CACHE))
    p.add_argument("--geocode-overrides", default=str(DEFAULT_OVERRIDES))
    p.add_argument("--output", default="testing/all_seed_routes.png")
    p.add_argument("--user-agent", default="oxhack26-seed-route-plot")
    p.add_argument("--margin", type=float, default=0.015, help="Degrees lat/lon pad around routes")
    args = p.parse_args()

    by_event = read_waypoints(Path(args.waypoints))
    labels = sorted({item["waypoint_name"].strip() for seq in by_event.values() for item in seq})
    coords = geocode_labels(
        labels,
        Path(args.geocode_cache),
        Path(args.geocode_overrides),
        args.user_agent,
    )
    print(f"Resolved {len(coords)}/{len(labels)} unique waypoint names")

    G = ox.load_graphml(args.graph)
    routes: list[tuple[str, list[int]]] = []
    skipped: list[str] = []
    for event_id, seq in sorted(by_event.items()):
        path = route_for_event(G, seq, coords)
        if path is None:
            skipped.append(event_id)
            continue
        routes.append((event_id, path))
    print(f"Routed {len(routes)}/{len(by_event)} events; skipped {len(skipped)}")

    if not routes:
        raise SystemExit("No routable events — check geocode cache and graph extent")

    xs, ys = [], []
    for _, path in routes:
        for n in path:
            xs.append(G.nodes[n]["x"])
            ys.append(G.nodes[n]["y"])
    north, south = max(ys) + args.margin, min(ys) - args.margin
    east, west = max(xs) + args.margin, min(xs) - args.margin
    G_sub = ox.truncate.truncate_graph_bbox(G, (west, south, east, north))

    fig, ax = ox.plot_graph(
        G_sub,
        node_size=0,
        edge_linewidth=0.35,
        bgcolor="#0d0d0d",
        edge_color="#2a3540",
        show=False,
        close=False,
        figsize=(16, 18),
    )

    cmap = plt.colormaps["turbo"]
    for i, (event_id, path) in enumerate(routes):
        try:
            path_sub: list[int] = []
            for source, target in zip(path, path[1:]):
                seg = nx.shortest_path(G_sub, source, target, weight="length")
                path_sub.extend(seg if not path_sub else seg[1:])
        except (nx.NetworkXNoPath, KeyError):
            continue
        color = cmap(i / max(len(routes) - 1, 1))
        ox.plot_graph_route(
            G_sub,
            path_sub,
            route_linewidth=1.8,
            route_color=color,
            route_alpha=0.55,
            orig_dest_size=0,
            ax=ax,
            show=False,
            close=False,
        )

    ax.set_title(
        f"Seed march routes on OSM walk graph ({len(routes)} events)\n"
        "Each line = shortest walk between geocoded waypoints (not GPS-observed)",
        color="white",
        fontsize=12,
    )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=160, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {out.resolve()}")
    if skipped:
        print("Skipped event_ids:", ", ".join(skipped[:20]), ("..." if len(skipped) > 20 else ""))


if __name__ == "__main__":
    main()
