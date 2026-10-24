#!/usr/bin/env python3
"""Download the current pedestrian street network from OpenStreetMap via Overpass.

OUT: raw/osm/london_walk.graphml (OSMnx directed MultiDiGraph)
     raw/osm/london_edges.geojson (LineString features in EPSG:4326)
Default bbox covers the central Westminster/West End area, not Greater London.
Run sparingly; requests to public Overpass may time out or be rate limited.
"""
import argparse
from pathlib import Path
import geopandas as gpd
import osmnx as ox


def main():
    p = argparse.ArgumentParser()
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
    print('Fetching network from Overpass...')
    graph = ox.graph_from_bbox((a.west, a.south, a.east, a.north), network_type='walk', simplify=True)
    ox.save_graphml(graph, dest / 'london_walk.graphml')
    edges = ox.graph_to_gdfs(graph, nodes=False, edges=True).reset_index()
    # Some OSM attributes are Python lists, which Fiona/GeoJSON won't accept directly.
    cols = [c for c in ['u','v','key','length','highway','name','oneway','geometry'] if c in edges]
    edges = edges[cols].copy()
    for c in ['highway','name']:
        if c in edges:
            edges[c] = edges[c].apply(lambda x: '|'.join(map(str, x)) if isinstance(x, list) else str(x or ''))
    edges['edge_id'] = edges.apply(lambda r:f"{r['u']}:{r['v']}:{r['key']}",axis=1)
    if edges.crs is None: edges = edges.set_crs('EPSG:4326')
    edges.to_file(dest/'london_edges.geojson', driver='GeoJSON')
    print(f'{len(graph.nodes):,} nodes, {len(edges):,} directed edges; saved {dest}')

if __name__ == '__main__': main()
