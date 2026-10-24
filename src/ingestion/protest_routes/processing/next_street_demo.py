#!/usr/bin/env python3
"""Demonstration: find possible *next streets in historical ANNOUNCED routes*
near one aggregate crowd location, not a calibrated/live movement predictor.

python 08_next_street_demo.py --lat 51.508 --lon -0.128 --as-of 2025-12-31

Requires normalised/segments.geojson and route_segment_labels.csv from script 07.
"""
import argparse, json
from collections import defaultdict
from datetime import date
from pathlib import Path
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--lat',type=float,required=True);p.add_argument('--lon',type=float,required=True)
    p.add_argument('--as-of',default='2026-10-24',help='Use only older historical route records, YYYY-MM-DD')
    p.add_argument('--data',default='normalised')
    p.add_argument('--max-distance-m',type=float,default=120)
    a=p.parse_args()
    src=Path(a.data)
    segments=gpd.read_file(src/'segments.geojson').to_crs('EPSG:27700')
    event_labels=pd.read_csv(src/'route_segment_labels.csv',keep_default_na=False)
    if event_labels.empty:
        print('No approved geocoded historical route sequences. Run geocoding review first.');return
    point=gpd.GeoSeries([Point(a.lon,a.lat)],crs='EPSG:4326').to_crs('EPSG:27700').iloc[0]
    distances=segments.geometry.distance(point)
    nearest_idx=distances.idxmin();nearest=segments.loc[nearest_idx]
    distance_m=float(distances.loc[nearest_idx]);segment=str(nearest.segment_id)
    if distance_m>a.max_distance_m:
        print(json.dumps({'message':'Location too far from downloaded pedestrian graph','distance_m':round(distance_m,1)}));return
    earlier=event_labels[event_labels.event_date.astype(str)<a.as_of].copy()
    next_counts=defaultdict(set)
    for eid,group in earlier.groupby('event_id'):
        # event-specific transitions, deduplicate repeated predictions per event.
        group=group.sort_values('sequence_index').reset_index(drop=True)
        for idx in range(len(group)-1):
            if str(group.loc[idx,'segment_id'])==segment:
                following=str(group.loc[idx+1,'segment_id'])
                next_counts[following].add(eid)
    names={str(r.segment_id):str(r.street_name) for _,r in segments.iterrows()}
    candidates=[{'segment_id':eid,'street_name':names.get(eid,''),'supporting_historical_events':len(ids)}
                for eid,ids in next_counts.items()]
    candidates.sort(key=lambda x:(-x['supporting_historical_events'],x['segment_id']))
    print(json.dumps({'mode':'historic_announced_route_continuation_demo',
                      'nearest_segment':segment,'nearest_segment_name':names.get(segment,''),
                      'distance_to_segment_m':round(distance_m,1),'trained_before':a.as_of,
                      'candidates':candidates[:8],
                      'warning':'Historical announced route transitions only; scores are not live crowd movement probabilities.'},indent=2))

if __name__=='__main__': main()
