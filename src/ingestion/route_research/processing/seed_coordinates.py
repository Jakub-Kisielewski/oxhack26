#!/usr/bin/env python3
"""Build coordinate_review.csv (the input normalize.py reads) from the reviewed seed geocodes.

Sources, both versioned in the package seed folder:
  seed/waypoint_geocode_overrides.json  hand-reviewed coordinates (take precedence)
  seed/geocode_cache.json               reviewed Nominatim results
Waypoint names found in neither are written with status=missing and listed, so
someone can add them to the overrides file. No geocoding requests are made.

OUT: coordinate_review.csv (same columns as review_geocode_waypoints.py)
"""
import argparse
import csv
import json
from pathlib import Path

PACKAGE_SEED = Path(__file__).resolve().parents[1] / 'seed'
FIELDS = ['waypoint_name', 'latitude', 'longitude', 'status', 'geocoded_display_name', 'notes']


def load_json(path):
    if not Path(path).exists():
        return {}
    return {k: v for k, v in json.loads(Path(path).read_text(encoding='utf-8')).items() if not k.startswith('_')}


def review_rows(labels, cache, overrides):
    rows = []
    for label in labels:
        if label in overrides:
            o = overrides[label]
            rows.append({'waypoint_name': label, 'latitude': o['latitude'], 'longitude': o['longitude'], 'status': 'approved',
                         'geocoded_display_name': o.get('osm_display_name', ''), 'notes': 'manual_override'})
        elif cache.get(label, {}).get('ok'):
            c = cache[label]
            rows.append({'waypoint_name': label, 'latitude': c['latitude'], 'longitude': c['longitude'], 'status': 'approved',
                         'geocoded_display_name': c.get('osm_display_name', ''), 'notes': 'geocode_cache'})
        else:
            rows.append({'waypoint_name': label, 'latitude': '', 'longitude': '', 'status': 'missing',
                         'geocoded_display_name': '', 'notes': 'add to waypoint_geocode_overrides.json'})
    return rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--waypoints', default='seed/waypoints.csv')
    p.add_argument('--cache', default=str(PACKAGE_SEED / 'geocode_cache.json'))
    p.add_argument('--overrides', default=str(PACKAGE_SEED / 'waypoint_geocode_overrides.json'))
    p.add_argument('--output', default='coordinate_review.csv')
    a = p.parse_args()
    with open(a.waypoints, encoding='utf-8-sig') as f:
        labels = sorted({r['waypoint_name'] for r in csv.DictReader(f) if r.get('waypoint_name')})
    rows = review_rows(labels, load_json(a.cache), load_json(a.overrides))
    with open(a.output, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS); w.writeheader(); w.writerows(rows)
    missing = [r['waypoint_name'] for r in rows if r['status'] == 'missing']
    print(f'{len(rows) - len(missing)}/{len(rows)} waypoint names have reviewed coordinates -> {a.output}')
    if missing:
        print(f'WARNING: no coordinates for {len(missing)}: {", ".join(missing)}')


if __name__ == '__main__':
    main()
