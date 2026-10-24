#!/usr/bin/env python3
"""Build an approximate TfL Zones 1-2 area-of-interest polygon from station zones.

TfL publishes fare zones per station, not as polygons. We take every tube, DLR,
Overground and Elizabeth line station whose `Zone` property includes 1 or 2,
draw a concave hull around them and buffer it, so streets just outside the
outermost zone-2 stations are kept.

OUT: raw/boundary/zones_1_2.geojson (one polygon, EPSG:4326)
     raw/boundary/zone_stations.csv  (stations used to build it)
Optional TFL_APP_KEY / TFL_APP_ID environment variables raise rate limits.
"""
import argparse
import csv
import os
import re
from pathlib import Path

import geopandas as gpd
import requests
import shapely
from shapely.geometry import MultiPoint

BASE = 'https://api.tfl.gov.uk'
MODES = 'tube,dlr,overground,elizabeth-line'
STATION_TYPES = {'NaptanMetroStation', 'NaptanRailStation'}
FIELDS = ['naptan_id', 'name', 'lat', 'lon', 'zone', 'modes']


def parse_zones(value):
    """'2+3' -> {2, 3}; '1' -> {1}; '' -> set(). TfL also uses '/' between zones."""
    return {int(z) for z in re.findall(r'\d+', str(value or ''))}


def zone_of(stop):
    for prop in stop.get('additionalProperties') or []:
        if prop.get('key') == 'Zone':
            return prop.get('value') or ''
    return ''


def fetch_stations(session, params):
    stations, page = [], 1
    while True:
        r = session.get(f'{BASE}/StopPoint/Mode/{MODES}', params={**params, 'page': page}, timeout=60)
        r.raise_for_status()
        data = r.json()
        batch = data.get('stopPoints', []) if isinstance(data, dict) else data
        if not batch:
            break
        stations.extend(batch)
        total = data.get('total') if isinstance(data, dict) else None
        if total is None or len(stations) >= total:
            break
        page += 1
    return stations


def select_zone_stations(stops, zones=(1, 2)):
    rows, seen = [], set()
    for s in stops:
        if s.get('stopType') not in STATION_TYPES or s.get('lat') is None:
            continue
        zone = zone_of(s)
        if not parse_zones(zone) & set(zones):
            continue
        key = s.get('naptanId') or s.get('id')
        if key in seen:
            continue
        seen.add(key)
        rows.append({'naptan_id': key, 'name': s.get('commonName'), 'lat': s['lat'], 'lon': s['lon'],
                     'zone': zone, 'modes': '|'.join(s.get('modes') or [])})
    return rows


def build_polygon(rows, buffer_m, ratio):
    pts = gpd.GeoSeries.from_xy([r['lon'] for r in rows], [r['lat'] for r in rows], crs='EPSG:4326').to_crs('EPSG:27700')
    hull = shapely.concave_hull(MultiPoint(list(pts)), ratio=ratio)
    return gpd.GeoSeries([hull.buffer(buffer_m)], crs='EPSG:27700').to_crs('EPSG:4326').iloc[0]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--outdir', default='raw/boundary')
    p.add_argument('--buffer-m', type=float, default=300, help='Buffer around the hull in metres')
    p.add_argument('--ratio', type=float, default=0.3, help='shapely concave_hull ratio (1 = convex hull)')
    a = p.parse_args()
    out = Path(a.outdir); out.mkdir(parents=True, exist_ok=True)
    params = {}
    if os.environ.get('TFL_APP_KEY'): params['app_key'] = os.environ['TFL_APP_KEY']
    if os.environ.get('TFL_APP_ID'): params['app_id'] = os.environ['TFL_APP_ID']
    rows = select_zone_stations(fetch_stations(requests.Session(), params))
    if len(rows) < 3:
        raise SystemExit(f'Only {len(rows)} zone 1-2 stations found; TfL response format may have changed')
    with (out / 'zone_stations.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS); w.writeheader(); w.writerows(rows)
    poly = build_polygon(rows, a.buffer_m, a.ratio)
    gdf = gpd.GeoDataFrame({'name': ['TfL Zones 1-2 (approx)'], 'n_stations': [len(rows)]}, geometry=[poly], crs='EPSG:4326')
    gdf.to_file(out / 'zones_1_2.geojson', driver='GeoJSON')
    area_km2 = gdf.to_crs('EPSG:27700').area.iloc[0] / 1e6
    print(f'{len(rows)} zone 1-2 stations -> polygon of {area_km2:.1f} km2; saved {out}')


if __name__ == '__main__':
    main()
