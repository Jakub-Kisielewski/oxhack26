#!/usr/bin/env python3
"""Download diplomatic missions in London from Wikidata with the country that runs them.

Selects every embassy/high commission/consulate (subclasses of "diplomatic
mission", Q7843791) whose coordinates fall in a box around central London, rather
than following "located in" links, which most missions only have to a borough.
Country comes from "operator" (P137), else from the label ("Embassy of France,
London" -> France). The database load joins this onto OSM embassies in `targets`.

OUT: raw/landmarks/missions.geoparquet + .csv
"""
import argparse
import re
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

USER_AGENT = 'OxfordHack2026-protest-predictor/0.1 (https://github.com/Jakub-Kisielewski/oxhack26)'
SOUTH_WEST, NORTH_EAST = (-0.35, 51.40), (0.10, 51.62)  # lon, lat: covers zones 1-2 with margin
SPARQL = """
SELECT ?item ?itemLabel ?countryLabel ?coord WHERE {{
  SERVICE wikibase:box {{
    ?item wdt:P625 ?coord .
    bd:serviceParam wikibase:cornerSouthWest "Point({sw[0]} {sw[1]})"^^geo:wktLiteral ;
                    wikibase:cornerNorthEast "Point({ne[0]} {ne[1]})"^^geo:wktLiteral .
  }}
  ?item wdt:P31/wdt:P279* wd:Q7843791 .
  OPTIONAL {{ ?item wdt:P137 ?country . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}"""
LABEL_COUNTRY = re.compile(r'(?:Embassy|High Commission|Consulate(?:[- ]General)?|Mission|Permanent Mission)\s+of\s+(?:the\s+)?(.+?)(?:,|\s+in\s+|\s+to\s+|$)', re.I)


def parse_wkt_point(value):
    m = re.match(r'Point\(([-\d.eE]+) ([-\d.eE]+)\)', value or '')
    return (float(m.group(1)), float(m.group(2))) if m else (None, None)


def country_from_label(label):
    m = LABEL_COUNTRY.search(label or '')
    return m.group(1).strip() if m else None


def parse_bindings(bindings):
    rows = []
    for b in bindings:
        lon, lat = parse_wkt_point(b['coord']['value'])
        if lon is None:
            continue
        name = b.get('itemLabel', {}).get('value')
        operator = b.get('countryLabel', {}).get('value')
        country = operator or country_from_label(name)
        rows.append({'wikidata': b['item']['value'].rsplit('/', 1)[-1], 'name': name, 'mission_country': country,
                     'country_source': 'operator' if operator else ('label' if country else None), 'lat': lat, 'lon': lon})
    return pd.DataFrame(rows, columns=['wikidata', 'name', 'mission_country', 'country_source', 'lat', 'lon'])


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--boundary', default='raw/boundary/zones_1_2.geojson')
    p.add_argument('--outdir', default='raw/landmarks')
    p.add_argument('--user-agent', default=USER_AGENT)
    a = p.parse_args()
    r = requests.get('https://query.wikidata.org/sparql', timeout=180,
                     params={'query': SPARQL.format(sw=SOUTH_WEST, ne=NORTH_EAST), 'format': 'json'},
                     headers={'User-Agent': a.user_agent, 'Accept': 'application/sparql-results+json'})
    r.raise_for_status()
    df = parse_bindings(r.json()['results']['bindings'])
    # One row per mission, keeping the first country when several operators are listed.
    rank = df.country_source.map({'operator': 0, 'label': 1}).fillna(2)
    df = df.assign(_rank=rank).sort_values('_rank').drop_duplicates('wikidata').drop(columns='_rank')
    gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.lon, df.lat), crs='EPSG:4326')
    if Path(a.boundary).exists():
        gdf = gdf[gdf.intersects(gpd.read_file(a.boundary).to_crs('EPSG:4326').union_all())]
    out = Path(a.outdir); out.mkdir(parents=True, exist_ok=True)
    gdf.to_parquet(out / 'missions.geoparquet', index=False)
    gdf.drop(columns='geometry').to_csv(out / 'missions.csv', index=False)
    print(f'{len(gdf)} diplomatic missions in the boundary ({gdf.mission_country.notna().sum()} with a country)')


if __name__ == '__main__':
    main()
