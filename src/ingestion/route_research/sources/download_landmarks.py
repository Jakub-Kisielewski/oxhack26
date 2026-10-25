#!/usr/bin/env python3
"""Download protest-relevant places inside the Zones 1-2 polygon from OSM and Wikidata.

Layers (each written as raw/landmarks/<layer>.geoparquet + <layer>.csv):
  targets      embassies/high commissions, government offices, party HQs, town halls,
               courts, attractions, monuments/memorials (route "pull")
  open_spaces  squares and parks with area_m2, the end-point/rally capacity
  shops        every shop=* (shopkeeper warnings)
  warehouses   warehouses, self-storage, industrial land with footprint_m2 as a
               capacity proxy (stock evacuation)
  missions_wikidata  diplomatic missions with the country that runs them;
               OSM embassies within 100 m get a `mission_country` from this

Requires raw/boundary/zones_1_2.geojson (download_boundary.py).
Overpass and Wikidata are public services: run sparingly. Busy Overpass servers
(HTTP 429/502/504) are retried with backoff across OVERPASS_URLS. Layers that
already exist are kept unless --refresh; a failed layer doesn't stop the others.
"""
import argparse
import re
import sys
import time
from pathlib import Path

import geopandas as gpd
import osmnx as ox
import pandas as pd
import requests
from osmnx._errors import InsufficientResponseError

USER_AGENT = 'OxfordHack2026-protest-predictor/0.1 (https://github.com/Jakub-Kisielewski/oxhack26)'
METRIC_CRS = 'EPSG:27700'
OVERPASS_URLS = ['https://overpass-api.de/api', 'https://overpass.private.coffee/api',
                 'https://overpass.kumi.systems/api']
BACKOFF_S = [0, 30, 60, 120]  # wait before each round over all servers

LAYERS = {
    'targets': {'amenity': ['embassy', 'townhall', 'courthouse'],
                'office': ['diplomatic', 'government', 'political_party'],
                'building': ['government'],
                'tourism': ['attraction'],
                'historic': ['memorial', 'monument']},
    'open_spaces': {'place': ['square'], 'leisure': ['park', 'common']},
    'shops': {'shop': True},
    'warehouses': {'building': ['warehouse'], 'shop': ['storage_rental'], 'landuse': ['industrial']},
}
KEEP_TAGS = ['name', 'amenity', 'office', 'diplomatic', 'country', 'government', 'building', 'tourism',
             'historic', 'memorial', 'place', 'leisure', 'operator', 'shop', 'brand', 'landuse',
             'addr:street', 'addr:postcode', 'wikidata']
# Thousands of small memorials (blue plaques, benches) are not protest targets.
MINOR_MEMORIALS = {'plaque', 'bench', 'stolperstein', 'blue_plaque', 'stone', 'tree'}

MISSIONS_SPARQL = """
SELECT ?item ?itemLabel ?countryLabel ?coord WHERE {
  ?item wdt:P31/wdt:P279* wd:Q7843791 ;
        wdt:P131* wd:Q84 ;
        wdt:P625 ?coord .
  OPTIONAL { ?item wdt:P137 ?country . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}"""


def target_category(row):
    """Single category per target, most specific first."""
    def has(tag, *values):
        v = row.get(tag)
        return isinstance(v, str) and (not values or v in values)
    if has('amenity', 'embassy') or has('office', 'diplomatic'): return 'diplomatic'
    if has('office', 'political_party'): return 'political_party'
    if has('office', 'government') or has('building', 'government'): return 'government'
    if has('amenity', 'townhall'): return 'townhall'
    if has('amenity', 'courthouse'): return 'court'
    if has('historic', 'memorial', 'monument'): return 'memorial'
    if has('tourism', 'attraction'): return 'attraction'
    return 'other'


def col(gdf, name):
    """Tag column, or an all-missing column if no feature had that tag."""
    return gdf[name] if name in gdf else pd.Series(None, index=gdf.index, dtype=object)


def flatten(value):
    if isinstance(value, (list, tuple, set)): return '|'.join(map(str, value))
    return value


def prepare(gdf, boundary):
    gdf = gdf.reset_index()
    gdf['osm_id'] = gdf['element'].astype(str) + '/' + gdf['id'].astype(str)
    cols = ['osm_id', *[c for c in KEEP_TAGS if c in gdf], 'geometry']
    gdf = gdf[cols].copy()
    for c in cols[1:-1]:
        gdf[c] = gdf[c].map(flatten)
    gdf = gdf[gdf.intersects(boundary)]
    metric = gdf.to_crs(METRIC_CRS)
    gdf['area_m2'] = metric.geometry.area.round(1)  # 0 for point features
    centroids = metric.geometry.centroid.to_crs('EPSG:4326')
    gdf['lat'], gdf['lon'] = centroids.y.round(6), centroids.x.round(6)
    return gdf


def parse_wkt_point(value):
    m = re.match(r'Point\(([-\d.eE]+) ([-\d.eE]+)\)', value or '')
    return (float(m.group(1)), float(m.group(2))) if m else (None, None)


def fetch_missions(user_agent):
    r = requests.get('https://query.wikidata.org/sparql', params={'query': MISSIONS_SPARQL, 'format': 'json'},
                     headers={'User-Agent': user_agent, 'Accept': 'application/sparql-results+json'}, timeout=120)
    r.raise_for_status()
    rows = []
    for b in r.json()['results']['bindings']:
        lon, lat = parse_wkt_point(b['coord']['value'])
        if lon is None: continue
        rows.append({'wikidata': b['item']['value'].rsplit('/', 1)[-1], 'name': b.get('itemLabel', {}).get('value'),
                     'mission_country': b.get('countryLabel', {}).get('value'), 'lat': lat, 'lon': lon})
    df = pd.DataFrame(rows).drop_duplicates('wikidata')
    return gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.lon, df.lat), crs='EPSG:4326')


def attach_country(targets, missions, max_m=100):
    """Give OSM diplomatic targets the operating country of the nearest Wikidata mission."""
    diplo = targets[targets.category == 'diplomatic'].to_crs(METRIC_CRS)
    if diplo.empty or missions.empty:
        targets['mission_country'] = None
        return targets
    joined = gpd.sjoin_nearest(diplo[['osm_id', 'geometry']], missions[['mission_country', 'geometry']].to_crs(METRIC_CRS),
                               max_distance=max_m, how='left').drop_duplicates('osm_id')
    return targets.merge(joined[['osm_id', 'mission_country']], on='osm_id', how='left')


def fetch_features(boundary, tags):
    """features_from_polygon, retrying busy servers; an empty result is not an error."""
    last = None
    for wait in BACKOFF_S:
        if wait:
            print(f'  all Overpass servers failed; waiting {wait}s before retrying')
            time.sleep(wait)
        for url in OVERPASS_URLS:
            ox.settings.overpass_url = url
            try:
                return ox.features_from_polygon(boundary, tags=tags)
            except InsufficientResponseError:
                return None
            except Exception as exc:  # 429/502/504 and timeouts all surface as different osmnx/requests errors
                last = exc
                print(f'  {url}: {exc.__class__.__name__}: {str(exc).splitlines()[0][:120]}')
    raise RuntimeError(f'Overpass unavailable after {len(BACKOFF_S)} rounds') from last


def load_missions(out, boundary, user_agent, refresh):
    path = out / 'missions_wikidata.geoparquet'
    if path.exists() and not refresh:
        return gpd.read_parquet(path)
    try:
        missions = fetch_missions(user_agent)
    except (requests.RequestException, KeyError, ValueError) as exc:
        print(f'WARNING: Wikidata query failed ({exc.__class__.__name__}); embassies get no mission_country')
        return None
    missions = missions[missions.intersects(boundary)]
    save(missions, out, 'missions_wikidata')
    return missions


def save(gdf, out, layer):
    gdf.to_parquet(out / f'{layer}.geoparquet', index=False)
    gdf.drop(columns='geometry').to_csv(out / f'{layer}.csv', index=False)
    print(f'{layer}: {len(gdf):,} features')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--boundary', default='raw/boundary/zones_1_2.geojson')
    p.add_argument('--outdir', default='raw/landmarks')
    p.add_argument('--layers', nargs='+', choices=list(LAYERS), default=list(LAYERS))
    p.add_argument('--skip-wikidata', action='store_true')
    p.add_argument('--user-agent', default=USER_AGENT)
    p.add_argument('--refresh', action='store_true', help='Re-download layers that already exist')
    a = p.parse_args()
    if not Path(a.boundary).exists():
        raise SystemExit(f'{a.boundary} missing: run the `boundary` step first')
    out = Path(a.outdir); out.mkdir(parents=True, exist_ok=True)
    boundary = gpd.read_file(a.boundary).to_crs('EPSG:4326').union_all()
    ox.settings.use_cache = True
    ox.settings.log_console = True

    missions = None if a.skip_wikidata else load_missions(out, boundary, a.user_agent, a.refresh)

    failed = []
    for layer in a.layers:
        if (out / f'{layer}.geoparquet').exists() and not a.refresh:
            print(f'{layer}: already downloaded (use --refresh to redo)')
            continue
        print(f'Fetching {layer} from Overpass...')
        try:
            raw = fetch_features(boundary, LAYERS[layer])
        except RuntimeError as exc:
            print(f'ERROR: {layer}: {exc}', file=sys.stderr)
            failed.append(layer)
            continue
        if raw is None:
            print(f'{layer}: no features found')
            continue
        gdf = prepare(raw, boundary)
        if layer == 'targets':
            gdf = gdf[~col(gdf, 'memorial').isin(MINOR_MEMORIALS)]
            gdf['category'] = gdf.apply(target_category, axis=1)
            if missions is not None:
                gdf = attach_country(gdf, missions)
        elif layer == 'open_spaces':
            gdf['kind'] = col(gdf, 'place').fillna(col(gdf, 'leisure'))
            gdf['royal_park'] = col(gdf, 'operator').fillna('').str.contains('Royal Parks')
            gdf['capacity_area_m2'] = gdf['area_m2'].where(gdf['area_m2'] > 0)
        elif layer == 'warehouses':
            gdf['footprint_m2'] = gdf['area_m2'].where(gdf['area_m2'] > 0)
        save(gdf, out, layer)
    if failed:
        raise SystemExit(f'Failed layers: {", ".join(failed)}; re-run to fetch just those')


if __name__ == '__main__':
    main()
