#!/usr/bin/env python3
"""OPTIONAL: Sample a locally extracted GHSL GeoTIFF at segment midpoints.

Input: GeoTIFF already selected from official GHSL download archive, plus
normalised/segments.geojson. Output: normalised/ghsl_edge_context.csv.
These are static built-up/population contextual pixels, not crowd observations.
"""
import argparse
from pathlib import Path
import geopandas as gpd
import pandas as pd
import rasterio


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--raster',required=True,help='Extracted GHSL .tif file')
    p.add_argument('--segments',default='normalised/segments.geojson')
    p.add_argument('--out',default='normalised/ghsl_edge_context.csv')
    args=p.parse_args()
    gdf=gpd.read_file(args.segments)
    with rasterio.open(args.raster) as dataset:
        projected=gdf.to_crs(dataset.crs)
        coords=[(g.interpolate(0.5,normalized=True).x,g.interpolate(0.5,normalized=True).y) for g in projected.geometry]
        sample=list(dataset.sample(coords,masked=True,indexes=1))
        values=[float(x[0]) if not bool(x.mask[0]) else None for x in sample]
        df=pd.DataFrame({'segment_id':gdf.segment_id.astype(str),'ghsl_pixel_value':values,
                         'ghsl_raster_name':Path(args.raster).name,'ghsl_pixel_semantics':'see source metadata'})
    target=Path(args.out);target.parent.mkdir(exist_ok=True,parents=True)
    df.to_csv(target,index=False)
    print('Saved',target,'rows',len(df),'valid pixel values',df.ghsl_pixel_value.notna().sum())

if __name__=='__main__':main()
