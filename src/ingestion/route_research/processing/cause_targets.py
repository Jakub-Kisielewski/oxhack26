#!/usr/bin/env python3
"""Resolve the hand-made cause -> target table and check it against the seed routes.

seed/cause_targets.csv lists, per cause, the places marches head for with a prior
weight (cause `any` applies to every cause). Each target is located from, in order:
the reviewed seed geocode named in `waypoint_name`; for embassies, the OSM
diplomatic target with that ISO country code within MAX_MATCH_M of the seed
coordinates (so a consulate elsewhere isn't picked); else the seed coordinates.

For each target, seed_route_hit_rate is the share of that cause's seed events with
an approved waypoint within --hit-radius-m, a sanity check of the prior weights.

Input: seed/cause_targets.csv (package seed folder), normalised/event_context.csv (cause per event),
       normalised/waypoints_approved.csv, raw/landmarks/targets.geoparquet
OUT:   normalised/cause_targets.csv
"""
import argparse
import math
from pathlib import Path

import json

import pandas as pd

PACKAGE_SEED = Path(__file__).resolve().parents[1] / 'seed'
MAX_MATCH_M = 400


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(a))


def read_layer(path, columns):
    if not Path(path).exists():
        return pd.DataFrame(columns=columns)
    import geopandas as gpd
    df = pd.DataFrame(gpd.read_parquet(path).drop(columns='geometry'))
    for c in columns:
        if c not in df:
            df[c] = None
    return df[columns]


def reviewed_geocodes(cache_path, overrides_path):
    coords = {}
    for path in (cache_path, overrides_path):  # overrides win
        if Path(path).exists():
            for name, v in json.loads(Path(path).read_text(encoding='utf-8')).items():
                if not name.startswith('_') and v.get('latitude') is not None and v.get('ok', True):
                    coords[name] = (float(v['latitude']), float(v['longitude']))
    return coords


def locate(row, geocodes, osm_targets):
    """(lat, lon, source) for a target row."""
    if row.waypoint_name and row.waypoint_name in geocodes:
        return (*geocodes[row.waypoint_name], 'reviewed_geocode')
    if row.kind == 'embassy':
        return locate_embassy(row, osm_targets)
    return row.lat, row.lon, 'seed_approx'


def locate_embassy(row, osm_targets):
    """(lat, lon, source) for an embassy row, nearest to the seed coordinates when several match."""
    candidates = []
    if row.iso2:
        o = osm_targets[(osm_targets.category == 'diplomatic') & (osm_targets.country.fillna('').str.upper() == row.iso2.upper())]
        candidates += [(r.lat, r.lon, 'osm_country_tag') for r in o.itertuples()]
    candidates = [c for c in candidates if haversine_m(row.lat, row.lon, c[0], c[1]) <= MAX_MATCH_M]
    if not candidates:
        return row.lat, row.lon, 'seed_approx'
    return min(candidates, key=lambda c: haversine_m(row.lat, row.lon, c[0], c[1]))


def hit_rates(targets, event_causes, waypoints, radius_m):
    """Share of each target's cause events that pass within radius_m of it."""
    by_event = {e: list(zip(g.latitude, g.longitude)) for e, g in waypoints.groupby('event_id')}
    rates, counts = [], []
    for t in targets.itertuples():
        events = [e for e, c in event_causes.items() if (t.cause == 'any' or c == t.cause) and e in by_event]
        hits = sum(any(haversine_m(t.lat, t.lon, la, lo) <= radius_m for la, lo in by_event[e]) for e in events)
        rates.append(round(hits / len(events), 3) if events else None)
        counts.append(len(events))
    return rates, counts


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--targets', default=str(PACKAGE_SEED / 'cause_targets.csv'))
    p.add_argument('--event-context', default='normalised/event_context.csv')
    p.add_argument('--waypoints', default='normalised/waypoints_approved.csv')
    p.add_argument('--osm-targets', default='raw/landmarks/targets.geoparquet')
    p.add_argument('--geocode-cache', default=str(PACKAGE_SEED / 'geocode_cache.json'))
    p.add_argument('--geocode-overrides', default=str(PACKAGE_SEED / 'waypoint_geocode_overrides.json'))
    p.add_argument('--hit-radius-m', type=float, default=250)
    p.add_argument('--output', default='normalised/cause_targets.csv')
    a = p.parse_args()
    targets = pd.read_csv(a.targets, keep_default_na=False).replace('', None)
    targets[['lat', 'lon', 'weight']] = targets[['lat', 'lon', 'weight']].astype(float)
    osm = read_layer(a.osm_targets, ['category', 'country', 'lat', 'lon'])
    geocodes = reviewed_geocodes(a.geocode_cache, a.geocode_overrides)
    located = [locate(r, geocodes, osm) for r in targets.itertuples()]
    targets['lat'], targets['lon'], targets['location_source'] = zip(*located)

    if Path(a.event_context).exists() and Path(a.waypoints).exists():
        causes = pd.read_csv(a.event_context, keep_default_na=False).set_index('event_id').cause.to_dict()
        wp = pd.read_csv(a.waypoints).dropna(subset=['latitude', 'longitude'])
        targets['seed_route_hit_rate'], targets['n_cause_events'] = hit_rates(targets, causes, wp, a.hit_radius_m)
    else:
        print('WARNING: event_context/waypoints missing; seed_route_hit_rate left empty')
        targets['seed_route_hit_rate'], targets['n_cause_events'] = None, 0

    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    targets.to_csv(a.output, index=False)
    print(targets[['cause', 'target_name', 'location_source', 'weight', 'seed_route_hit_rate', 'n_cause_events']]
          .to_string(index=False))


if __name__ == '__main__':
    main()
