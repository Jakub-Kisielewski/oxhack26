#!/usr/bin/env python3
"""Per-street-segment features for the route and overspill models.

For every directed edge of the walk network (segment_id = "u:v:key", the same key
normalize.py uses):
  width_m, width_source   usable street width including pavements: OSM `width`
                          (+ pavements on roads), else lanes x 3.25 m + pavements,
                          else a default for the road class
  area_m2, capacity_people   width x length, and people it holds at 2 people/m2
                          (Fruin: above ~2/m2 a crowd is congested; ~4-5/m2 is dangerous)
  betweenness_main        exact edge betweenness on the main-road network (null off it)
  betweenness_walk        sampled edge betweenness on the full walk network
  from_degree, to_degree  streets meeting at each end (how many ways a crowd can spill)
  is_main, is_bridge, is_tunnel
  in_no_entry_zone, in_restricted_zone, in_royal_park   from seed/legal_zones.geojson
                          and Royal Parks in raw/landmarks/open_spaces.geoparquet

OUT: normalised/edge_features.csv
"""
import argparse
import ast
import re
import time
from pathlib import Path

import geopandas as gpd
import networkx as nx
import osmnx as ox
import pandas as pd

PACKAGE_SEED = Path(__file__).resolve().parents[1] / 'seed'
LANE_M, PAVEMENTS_M = 3.25, 5.0  # two 2.5 m pavements
SAFE_DENSITY = 2.0  # people per m2
CARRIAGEWAYS = {'trunk', 'primary', 'secondary', 'tertiary', 'unclassified', 'residential', 'service',
                'living_street', 'trunk_link', 'primary_link', 'secondary_link', 'tertiary_link'}
# Typical total usable width (carriageway + pavements) in central London, metres.
DEFAULT_WIDTH_M = {'trunk': 22, 'trunk_link': 12, 'primary': 18, 'primary_link': 10, 'secondary': 15,
                   'secondary_link': 9, 'tertiary': 12, 'tertiary_link': 8, 'unclassified': 10, 'residential': 10,
                   'living_street': 8, 'service': 6, 'pedestrian': 10, 'footway': 3, 'path': 2.5,
                   'cycleway': 3, 'steps': 2.5, 'track': 3, 'bridleway': 3, 'corridor': 2}
FALLBACK_WIDTH_M = 6


def as_list(value):
    if value is None or value != value:
        return []
    if isinstance(value, str) and value.startswith('['):
        try:
            value = ast.literal_eval(value)  # list tags serialised by GraphML
        except (ValueError, SyntaxError):
            pass
    return value if isinstance(value, list) else [value]


def parse_width(value):
    """OSM width tag -> metres: '5', '5 m', '5.5m', '3;4' (first value), "12'" or '12 ft' (feet)."""
    for raw in as_list(value):
        text = str(raw).strip().lower().replace(',', '.')
        m = re.search(r'\d+(?:\.\d+)?', text)
        if m:
            metres = float(m.group()) * (0.3048 if ("'" in text or 'ft' in text) else 1)
            return metres if 0.5 <= metres <= 80 else None
    return None


def parse_lanes(value):
    for raw in as_list(value):
        m = re.search(r'\d+', str(raw))
        if m and 0 < int(m.group()) <= 12:
            return int(m.group())
    return None


def estimate_width(highway, width, lanes):
    classes = as_list(highway)
    road = any(h in CARRIAGEWAYS for h in classes)
    w = parse_width(width)
    if w is not None:
        return (w + PAVEMENTS_M if road else w), 'osm_width'
    n = parse_lanes(lanes)
    if n is not None and road:
        return n * LANE_M + PAVEMENTS_M, 'osm_lanes'
    defaults = [DEFAULT_WIDTH_M[h] for h in classes if h in DEFAULT_WIDTH_M]
    return (max(defaults) if defaults else FALLBACK_WIDTH_M), 'road_class_default'


def flag(value):
    return any(str(v).lower() not in ('no', 'false', '0', '') for v in as_list(value))


def undirected(graph):
    """Simple undirected graph keeping the shortest parallel edge (walk networks are two-way)."""
    g = nx.Graph()
    for u, v, d in graph.edges(data=True):
        length = float(d.get('length', 1.0))
        if not g.has_edge(u, v) or length < g[u][v]['length']:
            g.add_edge(u, v, length=length)
    return g


def betweenness(graph, k=None, seed=42):
    g = undirected(graph)
    k = None if k is None or k >= g.number_of_nodes() else k
    scores = nx.edge_betweenness_centrality(g, k=k, weight='length', normalized=True, seed=seed)
    return {frozenset(e): s for e, s in scores.items()}, g


def zone_flags(edges, zones_path, open_spaces_path):
    flags = pd.DataFrame(False, index=edges.index, columns=['in_no_entry_zone', 'in_restricted_zone', 'in_royal_park'])
    layers = []
    if Path(zones_path).exists():
        z = gpd.read_file(zones_path).to_crs('EPSG:4326')
        layers += [('in_no_entry_zone', z[z.rule_type == 'no_entry']), ('in_restricted_zone', z[z.rule_type == 'restricted_activity'])]
    if Path(open_spaces_path).exists():
        o = gpd.read_parquet(open_spaces_path).to_crs('EPSG:4326')
        if 'royal_park' in o:
            layers.append(('in_royal_park', o[o.royal_park.fillna(False).astype(bool) & o.geom_type.isin(['Polygon', 'MultiPolygon'])]))
    for column, polys in layers:
        if len(polys):
            hit = gpd.sjoin(edges[['geometry']], polys[['geometry']], predicate='intersects', how='inner').index.unique()
            flags.loc[hit, column] = True
    return flags


def build(walk, main, zones_path, open_spaces_path, k):
    t0 = time.monotonic()
    walk_scores, g_walk = betweenness(walk, k=k)
    print(f'walk betweenness ({k} samples): {time.monotonic() - t0:.0f}s')
    main_scores = betweenness(main)[0] if main is not None else {}
    main_ids = set(main.edges(keys=True)) if main is not None else set()
    edges = ox.graph_to_gdfs(walk, nodes=False, edges=True).reset_index()
    rows = []
    for r in edges.itertuples(index=False):
        d = r._asdict()
        width, source = estimate_width(d.get('highway'), d.get('width'), d.get('lanes'))
        length = float(d.get('length') or 0)
        pair = frozenset((r.u, r.v))
        rows.append({'segment_id': f'{int(r.u)}:{int(r.v)}:{int(r.key)}', 'length_m': round(length, 2),
                     'width_m': round(width, 1), 'width_source': source,
                     'area_m2': round(width * length, 1), 'capacity_people': int(width * length * SAFE_DENSITY),
                     'betweenness_main': main_scores.get(pair) if (r.u, r.v, r.key) in main_ids else None,
                     'betweenness_walk': walk_scores.get(pair),
                     'from_degree': g_walk.degree(r.u), 'to_degree': g_walk.degree(r.v),
                     'is_main': (r.u, r.v, r.key) in main_ids,
                     'is_bridge': flag(d.get('bridge')), 'is_tunnel': flag(d.get('tunnel'))})
    out = pd.DataFrame(rows)
    flags = zone_flags(edges, zones_path, open_spaces_path)
    return pd.concat([out, flags.reset_index(drop=True)], axis=1)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--walk', default='raw/osm/london_walk.graphml')
    p.add_argument('--main', default='raw/osm/london_main.graphml')
    p.add_argument('--legal-zones', default=str(PACKAGE_SEED / 'legal_zones.geojson'))
    p.add_argument('--open-spaces', default='raw/landmarks/open_spaces.geoparquet')
    p.add_argument('--samples', type=int, default=150, help='Source nodes sampled for walk-network betweenness')
    p.add_argument('--output', default='normalised/edge_features.csv')
    a = p.parse_args()
    walk = ox.load_graphml(a.walk)
    main_graph = ox.load_graphml(a.main) if Path(a.main).exists() else None
    out = build(walk, main_graph, a.legal_zones, a.open_spaces, a.samples)
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(a.output, index=False)
    print(f'{len(out):,} segments -> {a.output}; width from OSM tags for '
          f'{(out.width_source != "road_class_default").mean():.0%}; '
          f'{out.in_no_entry_zone.sum()} in no-entry zones, {out.in_royal_park.sum()} in Royal Parks')


if __name__ == '__main__':
    main()
