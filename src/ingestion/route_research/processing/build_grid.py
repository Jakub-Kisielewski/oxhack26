#!/usr/bin/env python3
"""Hexagon grid over the Zones 1-2 boundary, the summary layer next to the street graph.

Flat-top hexagons are laid out in British National Grid metres (EPSG:27700) and
kept where they touch the boundary. Used for the heatmap, pin lookups, spatial
statistics (cell contiguity for Moran's I / eigenvector filtering) and police
areas; street-level values are aggregated to cells through segment_cells.

OUT: normalised/grid_cells.geoparquet  cell_id, col, row, centroid lat/lon, area_m2, geometry (EPSG:4326)
     normalised/grid_adjacency.csv     cell_id, neighbor_id (cells sharing an edge, both directions)
     normalised/segment_cells.csv      segment_id, cell_id, is_midpoint_cell (one row per cell a segment crosses)
"""
import argparse
import math
from pathlib import Path

import geopandas as gpd
import osmnx as ox
import pandas as pd
from shapely.geometry import Polygon

METRIC_CRS = 'EPSG:27700'


def hexagon(cx, cy, size):
    return Polygon([(cx + size * math.cos(math.radians(a)), cy + size * math.sin(math.radians(a)))
                    for a in range(0, 360, 60)])


def hex_grid(boundary_metric, size):
    """Flat-top hexagons of circumradius `size` covering the boundary polygon."""
    minx, miny, maxx, maxy = boundary_metric.bounds
    dx, dy = 1.5 * size, math.sqrt(3) * size
    cells = []
    for col in range(int((maxx - minx) / dx) + 2):
        cx = minx + col * dx
        offset = dy / 2 if col % 2 else 0
        for row in range(int((maxy - miny) / dy) + 2):
            poly = hexagon(cx, miny + row * dy + offset, size)
            if poly.intersects(boundary_metric):
                cells.append({'col': col, 'row': row, 'geometry': poly})
    grid = gpd.GeoDataFrame(cells, crs=METRIC_CRS)
    grid.insert(0, 'cell_id', range(len(grid)))
    return grid


def adjacency(grid):
    # Neighbouring hexagons share an edge; a tiny buffer avoids floating-point misses.
    pairs = gpd.sjoin(grid[['cell_id', 'geometry']].assign(geometry=grid.buffer(0.01)),
                      grid[['cell_id', 'geometry']], predicate='intersects')
    pairs = pairs[pairs.cell_id_left != pairs.cell_id_right]
    return pairs.rename(columns={'cell_id_left': 'cell_id', 'cell_id_right': 'neighbor_id'})[['cell_id', 'neighbor_id']] \
        .sort_values(['cell_id', 'neighbor_id']).reset_index(drop=True)


def segment_cells(edges_metric, grid):
    hits = gpd.sjoin(edges_metric[['segment_id', 'geometry']], grid[['cell_id', 'geometry']], predicate='intersects')
    mids = edges_metric.assign(geometry=edges_metric.geometry.interpolate(0.5, normalized=True))
    mid_cell = gpd.sjoin(mids[['segment_id', 'geometry']], grid[['cell_id', 'geometry']], predicate='within') \
        .drop_duplicates('segment_id').set_index('segment_id').cell_id
    out = hits[['segment_id', 'cell_id']].drop_duplicates()
    out['is_midpoint_cell'] = out.cell_id.values == out.segment_id.map(mid_cell).values
    return out.sort_values(['segment_id', 'cell_id']).reset_index(drop=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--boundary', default='raw/boundary/zones_1_2.geojson')
    p.add_argument('--walk', default='raw/osm/london_walk.graphml')
    p.add_argument('--size-m', type=float, default=100, help='Hexagon circumradius; 100 m -> ~200 m across, ~2.6 ha')
    p.add_argument('--outdir', default='normalised')
    a = p.parse_args()
    out = Path(a.outdir); out.mkdir(parents=True, exist_ok=True)
    boundary = gpd.read_file(a.boundary).to_crs(METRIC_CRS).union_all()
    grid = hex_grid(boundary, a.size_m)
    adj = adjacency(grid)
    edges = ox.graph_to_gdfs(ox.load_graphml(a.walk), nodes=False, edges=True).reset_index()
    edges['segment_id'] = [f'{int(u)}:{int(v)}:{int(k)}' for u, v, k in zip(edges.u, edges.v, edges.key)]
    seg = segment_cells(edges.to_crs(METRIC_CRS), grid)

    grid['area_m2'] = grid.area.round(1)
    centroids = grid.centroid.to_crs('EPSG:4326')
    grid['lat'], grid['lon'] = centroids.y.round(6), centroids.x.round(6)
    grid.to_crs('EPSG:4326').to_parquet(out / 'grid_cells.geoparquet', index=False)
    adj.to_csv(out / 'grid_adjacency.csv', index=False)
    seg.to_csv(out / 'segment_cells.csv', index=False)
    print(f'{len(grid):,} hexagons ({a.size_m:.0f} m radius), {len(adj) // 2:,} neighbour pairs, '
          f'{seg.segment_id.nunique():,} segments mapped to cells')


if __name__ == '__main__':
    main()
