#!/usr/bin/env python3
"""Fetch ACLED UK protest events (point events, *not* march routes).

Requires myACLED registration and credentials in environment variables.
ACLED_EMAIL=... ACLED_PASSWORD=... python 04_download_acled.py
Or pass a manual myACLED export with --import-file /path/export.csv.
Produces raw/acled/london_protest_events.csv containing ORIGINAL ACLED columns.
Geographic bbox selection is coarse London; boundary overlaps may be included.
"""
import argparse, io, os
from pathlib import Path
import pandas as pd
import requests

BBOX = (-0.52, 51.27, 0.34, 51.71) # broad London envelope W,S,E,N

def london_subset(df):
    if not {'latitude','longitude'}.issubset(df.columns):
        raise ValueError('ACLED data must include latitude and longitude columns')
    d=df.copy()
    d['latitude']=pd.to_numeric(d.latitude,errors='coerce')
    d['longitude']=pd.to_numeric(d.longitude,errors='coerce')
    w,s,e,n=BBOX
    d=d[d.latitude.between(s,n)&d.longitude.between(w,e)]
    if 'event_type' in d.columns:
        d=d[d.event_type.astype(str).str.lower().str.contains('protest',na=False)]
    if 'country' in d.columns:
        d=d[d.country.astype(str).str.lower().eq('united kingdom')]
    if 'event_id_cnty' in d.columns:
        d=d.drop_duplicates('event_id_cnty')
    return d

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--start',default='2020-01-01');p.add_argument('--end',default='2026-10-24')
    p.add_argument('--out',default='raw/acled/london_protest_events.csv')
    p.add_argument('--import-file',default=None,help='ACLED CSV/XLSX export instead of API authentication')
    p.add_argument('--limit',type=int,default=1000);p.add_argument('--max-pages',type=int,default=100)
    a=p.parse_args()
    if a.import_file:
        if Path(a.import_file).suffix.lower() in {'.xls','.xlsx'}: df=pd.read_excel(a.import_file)
        else: df=pd.read_csv(a.import_file,low_memory=False)
    else:
        email=os.getenv('ACLED_EMAIL'); password=os.getenv('ACLED_PASSWORD')
        if not email or not password: raise SystemExit('Set ACLED_EMAIL and ACLED_PASSWORD, or use --import-file')
        s=requests.Session()
        tok=s.post('https://acleddata.com/oauth/token',data={'username':email,'password':password,
                   'grant_type':'password','client_id':'acled','scope':'authenticated'},timeout=60)
        tok.raise_for_status()
        token=tok.json()['access_token']
        s.headers.update({'Authorization':f'Bearer {token}'})
        frames=[]
        for page in range(1,a.max_pages+1):
            params={'_format':'csv','country':'United Kingdom','event_type':'Protests',
                    'event_date':f'{a.start}|{a.end}','event_date_where':'BETWEEN',
                    'limit':a.limit,'page':page}
            r=s.get('https://acleddata.com/api/acled/read',params=params,timeout=120)
            r.raise_for_status()
            part=pd.read_csv(io.BytesIO(r.content),low_memory=False)
            print('ACLED API page',page,'rows',len(part))
            if len(part)==0: break
            frames.append(part)
            if len(part)<a.limit: break
        else: raise RuntimeError('Reached --max-pages; refusing to silently truncate API results')
        df=pd.concat(frames,ignore_index=True) if frames else pd.DataFrame(columns=['latitude','longitude'])
    raw=london_subset(df)
    target=Path(a.out);target.parent.mkdir(parents=True,exist_ok=True)
    raw.to_csv(target,index=False)
    print(f'Saved {len(raw)} London-area protest event POINTS to {target}. Not routes.')

if __name__=='__main__': main()
