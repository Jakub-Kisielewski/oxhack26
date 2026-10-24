#!/usr/bin/env python3
"""Optional unified columnar storage: convert normalised tables to Parquet / GeoParquet.

All output files use Parquet family, `segment_id` is the join key, event_id is
an event key. DO NOT concatenate all source types into one dataset of fake
observations: monthly police points, TfL snapshots, routes have different units.
"""
import argparse
from pathlib import Path
import pandas as pd
import geopandas as gpd


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--input',default='normalised');p.add_argument('--output',default='normalised/parquet')
    a=p.parse_args();src=Path(a.input);dest=Path(a.output);dest.mkdir(exist_ok=True,parents=True)
    geoms=gpd.read_file(src/'segments.geojson')
    geoms.to_parquet(dest/'segments.geoparquet',index=False)
    print('Converted',len(geoms),'street segments to GeoParquet EPSG:4326')
    for csv_path in src.glob('*.csv'):
        d=pd.read_csv(csv_path,low_memory=False)
        if 'segment_id' in d:d['segment_id']=d.segment_id.astype('string')
        if 'event_id' in d:d['event_id']=d.event_id.astype('string')
        path=dest/(csv_path.stem+'.parquet')
        d.to_parquet(path,engine='pyarrow',index=False)
        print(path,'rows',len(d))

if __name__=='__main__':main()
