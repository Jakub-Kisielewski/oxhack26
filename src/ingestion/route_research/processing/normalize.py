#!/usr/bin/env python3
"""Normalise heterogeneous public datasets into linked schema keyed by street segment.

Critical provenance: raw historical waypoints are *planned*. Network connections
between them are algorithmically *inferred*, NEVER observed trajectories.

Input:
 --graph raw/osm/london_walk.graphml
 --events seed/events.csv
 --waypoints seed/waypoints.csv
 --review coordinate_review.csv (approved rows from 06_review_geocode_waypoints.py)
 Optional: ACLED, police CSVs, TfL snapshot JSON files
Output: normalised/*.csv and normalised/segments.geojson
"""
import argparse, csv, glob, json, math
from collections import defaultdict
from pathlib import Path
import networkx as nx
import osmnx as ox
import geopandas as gpd
import pandas as pd
from pyproj import Transformer
from shapely.geometry import Point, LineString

FIELDS_LABEL=['event_id','event_date','segment_id','sequence_index','from_waypoint','to_waypoint','label_provenance','source_url']

def write(rows,path,cols):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');w.writeheader();w.writerows(rows)

def tag(value):
    if isinstance(value,(list,tuple,set)):return '|'.join(str(z) for z in value)
    if value is None:return ''
    return str(value)

def is_approved(d):return str(d.get('status','')).lower().strip()=='approved'

def safe_float(value):
    try: return float(value)
    except (ValueError,TypeError):return None

def point_from_tfl(obj):
    # TfL `point` may be a GeoJSON string or object; coordinate order is [lon,lat].
    for key in ('point','geometry'):
        p=obj.get(key)
        if not p:continue
        try:
            if isinstance(p,str):p=json.loads(p)
            if isinstance(p,dict) and p.get('type')=='Feature':p=p.get('geometry',{})
            if isinstance(p,dict) and p.get('type')=='Point':
                lon,lat=p['coordinates'][:2]
                return float(lat),float(lon)
        except (ValueError,TypeError,KeyError,IndexError):pass
    return None,None

def make_streets(graph,out):
    original = ox.graph_to_gdfs(graph,nodes=False,edges=True).reset_index()
    original = original.to_crs('EPSG:4326')
    rows=[]; geometries=[]
    for _,r in original.iterrows():
        i=f"{int(r['u'])}:{int(r['v'])}:{int(r['key'])}"
        g=r.geometry
        if g is None or g.is_empty:continue
        if g.geom_type=='MultiLineString':
            # OSMnx edges should be LineStrings; don't silently accept other shapes.
            raise ValueError(f'Unexpected MultiLineString edge {i}')
        row={'segment_id':i,'u':int(r['u']),'v':int(r['v']),'key':int(r['key']),
             'length_m':round(float(r.get('length',0)),2),
             'road_class':tag(r.get('highway','')),'street_name':tag(r.get('name','')),
             'network_type':'walk','crs':'EPSG:4326','source':'OpenStreetMap'}
        rows.append(row);geometries.append(g)
    df=pd.DataFrame(rows)
    df.to_csv(out/'segment_features.csv',index=False)
    streets=gpd.GeoDataFrame(df,geometry=geometries,crs='EPSG:4326')
    streets.to_file(out/'segments.geojson',driver='GeoJSON')
    return df

def join_waypoints(graph,events,waypoints,review,out,snap_max_m):
    eventdata=events.set_index('event_id').to_dict('index')
    ref={str(r['waypoint_name']).strip():r for _,r in review.iterrows() if is_approved(r)}
    gproj=ox.project_graph(graph)
    to_projected=Transformer.from_crs('EPSG:4326',gproj.graph['crs'],always_xy=True)
    ready=[]; routes=[]; rejects=[]
    for event_id,grp in waypoints.groupby('event_id',sort=False):
        if event_id not in eventdata:continue
        er=eventdata[event_id]
        grp=grp.sort_values('sequence_index')
        approved=[]
        for _,row in grp.iterrows():
            name=str(row['waypoint_name']).strip()
            r=ref.get(name)
            if r is None:
                rejects.append({'event_id':event_id,'waypoint_name':name,'reason':'not approved'});continue
            lat=safe_float(r.get('latitude'));lon=safe_float(r.get('longitude'))
            if lat is None or lon is None or not(51.2 < lat < 51.8 and -0.6<lon<0.4):
                rejects.append({'event_id':event_id,'waypoint_name':name,'reason':'bad coordinate'});continue
            x,y=to_projected.transform(lon,lat)
            nearest=ox.distance.nearest_nodes(gproj,x,y)
            distance=math.hypot(gproj.nodes[nearest]['x']-x,gproj.nodes[nearest]['y']-y)
            if distance>snap_max_m:
                rejects.append({'event_id':event_id,'waypoint_name':name,'reason':f'snap too far: {distance:.0f} m'})
                continue
            approved.append({'event_id':event_id,'sequence_index':int(row['sequence_index']),
                             'waypoint_name':name,'latitude':lat,'longitude':lon,
                             'nearest_node':int(nearest),'snap_distance_m':round(distance,1),
                             'geo_review_status':'approved','event_date':er.get('event_date','')})
        ready.extend(approved)
        # Never connect across missing intermediate reported waypoints: doing so would
        # create a false route across potentially arbitrary streets.
        by_order={a['sequence_index']:a for a in approved}
        for a,b in zip(grp.to_dict('records')[:-1],grp.to_dict('records')[1:]):
            left=by_order.get(int(a['sequence_index']));right=by_order.get(int(b['sequence_index']))
            if left is None or right is None:continue
            try:
                nodes=nx.shortest_path(graph,left['nearest_node'],right['nearest_node'],weight='length')
            except (nx.NetworkXNoPath,nx.NodeNotFound):
                rejects.append({'event_id':event_id,'waypoint_name':f"{left['waypoint_name']} -> {right['waypoint_name']}",
                                'reason':'graph has no walkable path'});continue
            for u,v in zip(nodes[:-1],nodes[1:]):
                if u not in graph or v not in graph[u]:continue
                # On a MultiDiGraph use the minimum-length parallel edge.
                k=min(graph[u][v],key=lambda key:float(graph[u][v][key].get('length',float('inf'))))
                routes.append({'event_id':event_id,'event_date':er.get('event_date',''),
                               'segment_id':f'{u}:{v}:{k}','sequence_index':len(routes),
                               'from_waypoint':left['waypoint_name'],'to_waypoint':right['waypoint_name'],
                               'label_provenance':'INFERRED_SHORTEST_PATH_BETWEEN_APPROVED_PLANNED_WAYPOINTS',
                               'source_url':er.get('source_url','')})
    write(ready,out/'waypoints_approved.csv',
        ['event_id','event_date','sequence_index','waypoint_name','latitude','longitude','nearest_node','snap_distance_m','geo_review_status'])
    # Route segment order should be per event, never globally incrementing.
    byevent=defaultdict(int)
    for r in routes:r['sequence_index']=byevent[r['event_id']];byevent[r['event_id']]+=1
    write(routes,out/'route_segment_labels.csv',FIELDS_LABEL)
    write(rejects,out/'review_issues.csv',['event_id','waypoint_name','reason'])
    print(f'approved waypoint appearances: {len(ready)}; inferred segment appearances: {len(routes)}; review issues: {len(rejects)}')
    return routes

def normalize_context(a,out):
    if a.acled and Path(a.acled).exists():
        d=pd.read_csv(a.acled,low_memory=False)
        fields=['event_id_cnty','event_date','event_type','sub_event_type','country','location','latitude','longitude','geo_precision','source']
        for f in fields:
            if f not in d.columns:d[f]=None
        d[fields].to_csv(out/'acled_event_points.csv',index=False)
    if a.police and Path(a.police).exists():
        p=pd.read_csv(a.police)
        p.to_csv(out/'police_monthly_context.csv',index=False)
    rows=[]
    for f in sorted(glob.glob(a.tfl_glob)):
        content=json.loads(Path(f).read_text(encoding='utf-8'))
        ts=content.get('captured_at_utc','')
        for obj in content.get('items',[]):
            if 'roads_' not in Path(f).name:continue
            lat,lon=point_from_tfl(obj)
            rows.append({'snapshot_at_utc':ts,'disruption_id':obj.get('id',''),
                         'latitude':lat,'longitude':lon,'status':obj.get('status',''),
                         'severity':obj.get('severity',''),'category':obj.get('category',''),
                         'location':obj.get('location',''), 'start_at':obj.get('startDateTime',''),
                         'end_at':obj.get('endDateTime',''), 'source':'TfL'})
    write(rows,out/'tfl_road_disruption_snapshots.csv',
       ['snapshot_at_utc','disruption_id','latitude','longitude','status','severity','category','location','start_at','end_at','source'])

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--graph',default='raw/osm/london_walk.graphml')
    p.add_argument('--events',default='seed/events.csv');p.add_argument('--waypoints',default='seed/waypoints.csv')
    p.add_argument('--review',default='coordinate_review.csv')
    p.add_argument('--acled',default='raw/acled/london_protest_events.csv')
    p.add_argument('--police',default='raw/police/police_public_order_context.csv')
    p.add_argument('--tfl-glob',default='raw/tfl/roads_*.json')
    p.add_argument('--outdir',default='normalised');p.add_argument('--max-snap-distance-m',type=float,default=350)
    a=p.parse_args()
    out=Path(a.outdir);out.mkdir(parents=True,exist_ok=True)
    graph=ox.load_graphml(a.graph)
    edges=make_streets(graph,out)
    events=pd.read_csv(a.events,keep_default_na=False)
    waypoints=pd.read_csv(a.waypoints,keep_default_na=False)
    events.to_csv(out/'events.csv',index=False)
    # Emit an EMPTY review template instead of fabricating coordinates.
    if Path(a.review).exists():review=pd.read_csv(a.review,keep_default_na=False)
    else:
        review=pd.DataFrame(columns=['waypoint_name','latitude','longitude','status'])
        print('WARNING: review file missing; no route segment labels will be generated.')
    route=join_waypoints(graph,events,waypoints,review,out,a.max_snap_distance_m)
    counts=pd.DataFrame(route)
    if len(counts):
        counts=counts[['event_id','segment_id']].drop_duplicates().groupby('segment_id').size().rename('n_published_route_examples').reset_index()
        edges=edges.merge(counts,on='segment_id',how='left')
    else:edges['n_published_route_examples']=0
    edges['n_published_route_examples']=edges.n_published_route_examples.fillna(0).astype(int)
    edges.to_csv(out/'segment_features.csv',index=False)
    normalize_context(a,out)
    print(f'Normalised {len(edges)} OSM segments into {out}; historic counts describe the full corpus only.')
    print('WARNING: For backtesting, recompute historical counts using ONLY events before the test event date.')

if __name__=='__main__': main()
