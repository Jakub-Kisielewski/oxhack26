#!/usr/bin/env python3
"""Convert SOURCE REPORTED named waypoints -> REVIEWED coordinates -> INFERRED street routes.

1) python 01_geocode_and_route.py geocode --waypoints london_march_route_waypoints.csv
2) Open coordinate_review.csv and set status=approved ONLY after checking location.
3) python 01_geocode_and_route.py build --waypoints london_march_route_waypoints.csv

Nominatim/Overpass require internet. Outputs are *not* GPS observations.
"""
import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

FIELDS = ["waypoint_name", "latitude", "longitude", "status", "geocoded_display_name", "notes"]


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def save_csv(path, rows, columns):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def geocode(args):
    try:
        from geopy.geocoders import Nominatim
        from geopy.extra.rate_limiter import RateLimiter
    except ImportError as exc:
        raise SystemExit("Install dependencies: pip install geopy osmnx networkx") from exc
    route_rows = read_csv(args.waypoints)
    labels = sorted({r["waypoint_name"].strip() for r in route_rows if r.get("waypoint_name")})
    existing = {r["waypoint_name"]: r for r in read_csv(args.review)} if Path(args.review).exists() else {}
    geolocator = Nominatim(user_agent=args.user_agent, timeout=15)
    geocode_fn = RateLimiter(geolocator.geocode, min_delay_seconds=1.2, max_retries=2, error_wait_seconds=5)
    result = []
    for index, label in enumerate(labels, 1):
        if label in existing:
            result.append(existing[label]); continue
        # Road names and broad districts are ambiguous. This is a suggestion to REVIEW.
        query = f"{label}, London, England, UK"
        try:
            match = geocode_fn(query, exactly_one=True, country_codes="gb",
                viewbox=[(51.44, -0.29), (51.57, 0.06)], bounded=True,
                addressdetails=False)
        except Exception as exc:
            print(f"Geocoder error for {label!r}: {exc}")
            match = None
        coords_ok = bool(match and 51.44 <= match.latitude <= 51.57 and -0.29 <= match.longitude <= 0.06)
        r = {"waypoint_name": label, "latitude": round(match.latitude, 7) if coords_ok else "",
             "longitude": round(match.longitude, 7) if coords_ok else "",
             "status": "needs_review" if coords_ok else "unresolved",
             "geocoded_display_name": match.address if coords_ok else "",
             "notes": "Check exact road intersection / which end of street"}
        result.append(r)
        # Persist partial results to avoid losing expensive lookups.
        save_csv(args.review, result + [existing[l] for l in labels[index:] if l in existing], FIELDS)
        print(f"{index}/{len(labels)} {label}: {r['status']}")
    save_csv(args.review, result, FIELDS)
    print(f"Saved {len(result)} unique named locations to {args.review}. Review before building.")


def build(args):
    try:
        import osmnx as ox
        import networkx as nx
    except ImportError as exc:
        raise SystemExit("Install dependencies: pip install osmnx networkx geopy") from exc
    waypoints = read_csv(args.waypoints)
    reviewed = {r["waypoint_name"]: r for r in read_csv(args.review)}
    by_event = defaultdict(list)
    for row in waypoints:
        if args.protests_only and row.get("event_category") != "protest":
            continue
        by_event[row["event_id"]].append(row)

    ox.settings.use_cache = True
    ox.settings.cache_folder = str(Path(args.output).parent / "osm_cache")
    # OSMnx v2. Download graph near Westminster, with distance configurable.
    graph_path = Path(args.output).with_suffix(".graphml")
    if graph_path.exists() and not args.redownload:
        G = ox.load_graphml(graph_path)
    else:
        G = ox.graph_from_point((51.5074, -0.1278), dist=args.radius_m,
                                dist_type="bbox", network_type="walk", simplify=True)
        ox.save_graphml(G, graph_path)
    features, failures = [], []
    for event_id, seq in sorted(by_event.items()):
        seq.sort(key=lambda r: int(r["sequence_index"]))
        coords = []
        for item in seq:
            label = item["waypoint_name"]
            match = reviewed.get(label)
            if not match or (not args.allow_unreviewed and match["status"] != "approved"):
                failures.append([event_id, label, "no approved coordinates"])
                break
            try:
                lat, lon = float(match["latitude"]), float(match["longitude"])
            except (TypeError, ValueError):
                failures.append([event_id, label, "invalid coordinates"])
                break
            coords.append((lat, lon))
        if len(coords) != len(seq) or len(coords) < 2:
            continue
        try:
            nodes = [ox.distance.nearest_nodes(G, X=lon, Y=lat) for lat, lon in coords]
            route_nodes = []
            for source, target in zip(nodes, nodes[1:]):
                path = nx.shortest_path(G, source, target, weight="length")
                if route_nodes:
                    path = path[1:]
                route_nodes.extend(path)
            if len(route_nodes) < 2:
                raise ValueError("no usable route between snapped waypoints")
            line = [[float(G.nodes[n]["x"]), float(G.nodes[n]["y"])] for n in route_nodes]
            distance_m = sum(float(G[u][v][min(G[u][v], key=lambda key: G[u][v][key].get("length", math.inf))].get("length", 0)) for u, v in zip(route_nodes, route_nodes[1:]))
            first = seq[0]
            features.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": line},
                "properties": {"event_id": event_id, "event_date": first.get("event_date", ""),
                   "event_category": first.get("event_category", ""),
                   "source_url": first.get("source_url", ""),
                   "route_kind": "model_interpolated_NOT_observed",
                   "geocode_reviewed": not args.allow_unreviewed,
                   "waypoint_count": len(coords), "length_m_approx": round(distance_m),
                   "waypoints": [item["waypoint_name"] for item in seq]}})
            print(f"{event_id}: {distance_m/1000:.1f} km")
        except (nx.NetworkXNoPath, nx.NodeNotFound, ValueError, KeyError) as exc:
            failures.append([event_id, "", f"routing error: {exc}"])
    Path(args.output).write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, indent=2), encoding="utf-8")
    save_csv(Path(args.output).with_suffix(".failures.csv"),
             [dict(event_id=x[0], waypoint=x[1], problem=x[2]) for x in failures],
             ["event_id", "waypoint", "problem"])
    print(f"Saved {len(features)} provisional LineStrings to {args.output}; {len(failures)} issues logged.")
    print("All paths are street-network interpolations; NOT known crowd trajectories.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("phase", choices=["geocode", "build"])
    p.add_argument("--waypoints", default="london_march_route_waypoints.csv")
    p.add_argument("--review", default="coordinate_review.csv")
    p.add_argument("--output", default="inferred_march_routes.geojson")
    p.add_argument("--user-agent", default="hackathon-route-research/0.1 (contact via GitHub project)")
    p.add_argument("--radius-m", type=int, default=6000)
    p.add_argument("--allow-unreviewed", action="store_true", help="DEMO ONLY: use machine geocoding without manual approval")
    p.add_argument("--protests-only", action="store_true")
    p.add_argument("--redownload", action="store_true")
    args = p.parse_args()
    (geocode if args.phase == "geocode" else build)(args)


if __name__ == "__main__":
    main()
