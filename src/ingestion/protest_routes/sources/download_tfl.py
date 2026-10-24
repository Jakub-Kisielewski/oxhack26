#!/usr/bin/env python3
"""Save a time-stamped *snapshot* of TfL road disruptions and tube statuses.

RAW outputs JSON, preserved exactly as returned by the API; repeated invocations
produce separate timestamped files. No historical backfill is claimed.
"""
import argparse, datetime as dt, json, os
from pathlib import Path
import requests

BASE='https://api.tfl.gov.uk'
ENDPOINTS={'roads':'/Road/all/Disruption','tube':'/Line/Mode/tube/Status'}

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--outdir',default='raw/tfl')
    p.add_argument('--roads-only',action='store_true')
    a=p.parse_args()
    out=Path(a.outdir); out.mkdir(parents=True,exist_ok=True)
    now=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    params={}
    if os.environ.get('TFL_APP_KEY'): params['app_key']=os.environ['TFL_APP_KEY']
    if os.environ.get('TFL_APP_ID'): params['app_id']=os.environ['TFL_APP_ID']
    for label,path in ENDPOINTS.items():
        if a.roads_only and label!='roads': continue
        r=requests.get(BASE+path,params=params,timeout=50)
        r.raise_for_status()
        data=r.json()
        if not isinstance(data,list): raise ValueError(f'Unexpected TfL {label} response: {type(data)}')
        dst=out/f'{label}_{now}.json'
        dst.write_text(json.dumps({'captured_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
                                   'source_url':BASE+path,'items':data},indent=2,ensure_ascii=False),encoding='utf-8')
        print(f'{label}: {len(data)} records -> {dst}')

if __name__=='__main__': main()
