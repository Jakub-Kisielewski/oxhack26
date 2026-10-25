"""Shopkeeper point queries and illustrative constrained deployment scenarios."""
from __future__ import annotations
import math
from src.contract import mapdata
from src.contract.types import (OverspillPrediction,RoutePrediction,PointRisk,ShopAdvice,
    WarehouseOption,PolicePost,PoliceAllocation,risk_level)
from src.models.graph import MarchGraph,line_distance


def point_risk(g:MarchGraph,prediction,point):
    is_route=isinstance(prediction,RoutePrediction)
    if is_route:
        items=[(s.segment_id,s.p_visit,None,None,'route') for s in prediction.segments]
    else:
        # We report overspill risk for side streets, never police presence as a feature.
        items=[(s.segment_id,s.p_spill,s.window_start_min,s.window_end_min,'spill') for s in prediction.spill]
    # Exclude distant results; return nearest even when risk is zero.
    closest=None
    for sid,p,t0,t1,kind in items:
        if sid not in g.segments:continue
        d=line_distance(point,g.segments[sid].path)
        if closest is None or (d,-p)<(closest[0],-closest[2]):
            closest=(d,sid,p,t0,t1,kind)
    found=closest is not None and closest[0]<=50
    p=min(1,max(0,float(closest[2]))) if found else 0.0
    return PointRisk(point,closest[1] if closest else None,
                     round(closest[0],1) if closest else None,mapdata.cell_at(point),
                     p if is_route else 0.0, 0.0 if is_route else p,p,risk_level(p),
                     closest[3] if found else None,closest[4] if found else None,
                     f"{'Route' if is_route else 'Overspill'} scenario level {p:.0%} within 50 m."
                     if found else 'No predicted disruption within 50 m.')


def shop_advice(g:MarchGraph,prediction,shop):
    risk=point_risk(g,prediction,shop)
    act_by=(risk.window_start_min-60 if risk.window_start_min is not None else -60) if risk.risk>=.1 else None
    # Route-mode has no time estimate at segment level; 'before start' is conservative.
    candidates=sorted(mapdata.warehouses(),key=lambda w:mapdata.distance_m(shop,w['lonlat']))[:15]
    max_area=max([float(w.get('footprint_m2') or 0) for w in candidates]+[1])
    options=[]
    for w in candidates:
        ids=g.route_between(shop,w['lonlat'])
        if not ids:continue
        distance=sum(g.segments[sid].length for sid in ids)
        p=point_risk(g,prediction,w['lonlat']).risk
        area=w.get('footprint_m2');capacity=(float(area)/max_area if area else .5)
        utility=1/(distance+100)*(1-p)*capacity
        options.append(WarehouseOption(str(w['osm_id']),w.get('name'),w['lonlat'],
                                       distance,p,area,utility,[shop]+g.geometry(ids)+[w['lonlat']]))
    options.sort(key=lambda w:-w.utility)
    if act_by is None:msg='No stock movement indicated by this scenario.'
    elif act_by<0:msg=f'Consider protective steps at least {abs(act_by):.0f} minutes before the march begins.'
    else:msg=f'Consider protective steps by minute {act_by:.0f} after the march begins.'
    return ShopAdvice(shop,risk,act_by,msg,options[:3])


def allocate_police(g:MarchGraph,prediction:OverspillPrediction,officers:int)->PoliceAllocation:
    if not isinstance(prediction,OverspillPrediction):raise TypeError('OverspillPrediction needed')
    if officers<0:raise ValueError('Officer count must be nonnegative')
    spill=prediction.spill
    before=sum(s.p_spill for s in spill)
    alloc=[0]*len(spill)
    unit=5;eta=.05
    for _ in range(officers//unit):
        if not spill:break
        j=max(range(len(spill)),key=lambda i:spill[i].p_spill*math.exp(-eta*alloc[i])*(1-math.exp(-eta*unit)))
        alloc[j]+=unit
    posts=[]
    for s,num in zip(spill,alloc):
        if num:
            posts.append(PolicePost(g.segments[s.segment_id].mid,s.segment_id,num,
                                    s.p_spill*(1-math.exp(-eta*num))))
    after=sum(s.p_spill*math.exp(-eta*n) for s,n in zip(spill,alloc))
    return PoliceAllocation(officers,sorted(posts,key=lambda x:-x.officers),before,after)
