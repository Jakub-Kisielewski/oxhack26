#!/usr/bin/env python3
"""Download the current pedestrian street network from OpenStreetMap via Overpass.

OUT: raw/osm/london_walk.graphml (OSMnx directed MultiDiGraph, full walk network)
     raw/osm/london_edges.geojson (LineString features in EPSG:4326)
     raw/osm/london_main.graphml / london_main_edges.geojson (main roads and
       pedestrian streets only, largest strongly connected component; the
       network large marches actually use)
Area: the Zones 1-2 polygon from download_boundary.py when it exists, otherwise
the bbox arguments (central Westminster/West End by default).
Run sparingly; requests to public Overpass may time out or be rate limited.
"""
import argparse
from pathlib import Path
import geopandas as gpd
import osmnx as ox

EXTRA_WAY_TAGS = ['lanes', 'width', 'bridge', 'tunnel', 'ref', 'maxspeed', 'junction']
EDGE_COLS = ['u', 'v', 'key', 'length', 'highway', 'name', 'oneway', *EXTRA_WAY_TAGS, 'geometry']
MAIN_HIGHWAYS = {'trunk', 'trunk_link', 'primary', 'primary_link', 'secondary', 'secondary_link',
                 'tertiary', 'tertiary_link', 'pedestrian', 'living_street'}


def is_main(highway):
    values = highway if isinstance(highway, list) else [highway]
    return any(h in MAIN_HIGHWAYS for h in values)


def main_roads(graph):
    keep = [(u, v, k) for u, v, k, hw in graph.edges(keys=True, data='highway') if is_main(hw)]
    sub = graph.edge_subgraph(keep).copy()
    return ox.truncate.largest_component(sub, strongly=True)


def save_edges(graph, path):
    edges = ox.graph_to_gdfs(graph, nodes=False, edges=True).reset_index()
    # Some OSM attributes are Python lists, which Fiona/GeoJSON won't accept directly.
    cols = [c for c in EDGE_COLS if c in edges]
    edges = edges[cols].copy()
    for c in cols:
        if c not in ('u', 'v', 'key', 'length', 'geometry'):
            edges[c] = edges[c].apply(lambda x: '|'.join(map(str, x)) if isinstance(x, list) else ('' if x is None or x != x else str(x)))
    edges['edge_id'] = edges.apply(lambda r:f"{r['u']}:{r['v']}:{r['key']}",axis=1)
    if edges.crs is None: edges = edges.set_crs('EPSG:4326')
    edges.to_file(path, driver='GeoJSON')
    return len(edges)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--boundary', default='raw/boundary/zones_1_2.geojson',
                   help='Polygon to clip to; falls back to the bbox below if the file is missing')
    p.add_argument('--west', type=float, default=-0.21)
    p.add_argument('--south', type=float, default=51.485)
    p.add_argument('--east', type=float, default=-0.07)
    p.add_argument('--north', type=float, default=51.54)
    p.add_argument('--outdir', default='raw/osm')
    a = p.parse_args()
    assert a.west < a.east and a.south < a.north, 'Invalid bbox'
    dest = Path(a.outdir); dest.mkdir(parents=True, exist_ok=True)
    ox.settings.use_cache = True
    ox.settings.log_console = True
    ox.settings.useful_tags_way = sorted(set(ox.settings.useful_tags_way) | set(EXTRA_WAY_TAGS))
    print('Fetching network from Overpass...')
    if Path(a.boundary).exists():
        polygon = gpd.read_file(a.boundary).to_crs('EPSG:4326').union_all()
        print(f'Using boundary {a.boundary}')
        graph = ox.graph_from_polygon(polygon, network_type='walk', simplify=True)
    else:
        print(f'{a.boundary} not found; using bbox')
        graph = ox.graph_from_bbox((a.west, a.south, a.east, a.north), network_type='walk', simplify=True)
    ox.save_graphml(graph, dest / 'london_walk.graphml')
    n_edges = save_edges(graph, dest / 'london_edges.geojson')
    print(f'Full walk network: {len(graph.nodes):,} nodes, {n_edges:,} directed edges')
    main_graph = main_roads(graph)
    ox.save_graphml(main_graph, dest / 'london_main.graphml')
    n_main = save_edges(main_graph, dest / 'london_main_edges.geojson')
    print(f'Main-road network: {len(main_graph.nodes):,} nodes, {n_main:,} directed edges; saved {dest}')

if __name__ == '__main__': main()
