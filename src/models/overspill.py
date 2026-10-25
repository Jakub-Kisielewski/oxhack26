"""Deterministic crowd-flow scenarios, not a fit to observed overspill labels.

All constants below are *assumptions*, not measured effects. Consequences for
police presence MUST be read as scenario outputs, not causal estimates.
"""
from __future__ import annotations
import math
import statistics
from collections import defaultdict
from src.contract import mapdata
from src.contract.types import (CellValue,Driver,Hotspot,MarchContext,OverspillPrediction,
    OverspillRequest,SegmentTiming,SpillRisk,TurnoutEstimate,risk_level)
from src.models.graph import MarchGraph

HEAD_SPEED=42.0   # m/min
MEAN_CROWD_DENSITY=1.5 # people/m2
RALLY_MIN=60.0
ETA=0.05
VOLATILITY_DEFAULT=0.2
CAUSE_VOLATILITY={'far_right':0.35,'anti_racism':0.25,'climate_nature':0.15}


def sigmoid(x):
    return 1/(1+math.exp(-max(-50,min(50,x))))


def level_of_service(d):
    return 'A' if d<.83 else 'B' if d<1.08 else 'C' if d<1.54 else 'D' if d<3.3 else 'E' if d<5 else 'F'


def volatility(context:MarchContext,context_features:dict|None=None):
    context_features=context_features or {}
    v=CAUSE_VOLATILITY.get(context.cause,VOLATILITY_DEFAULT)
    if 'counter-protest' in (context.organiser or '').lower():v+=.25
    if context.start_time>='17:00':v+=.15
    if float(context_features.get('salience_spike_ratio') or 0)>2:v+=.15
    return min(1,max(0,v))


def predict(g:MarchGraph,req:OverspillRequest,turnout:TurnoutEstimate,version:str,
            targets:list|None=None,context_features:dict|None=None) -> OverspillPrediction:
    ids=[sid for sid in req.route_segment_ids if sid in g.segments]
    warnings=['Overspill probabilities are uncalibrated scenarios: coefficients are hand-set, not trained.']
    if len(ids)!=len(req.route_segment_ids):warnings.append('Some route segments not found in graph')
    if not ids:
        return OverspillPrediction(req,turnout,[],[],[],[],0,[],version,warnings)
    median_width=statistics.median(g.segments[s].width for s in ids)
    tail_delay=turnout.expected/(MEAN_CROWD_DENSITY*median_width*HEAD_SPEED)
    timeline=[];cumulative=0.0
    for sid in ids:
        s=g.segments[sid]
        density=min(6.0,max(.1,MEAN_CROWD_DENSITY*median_width/s.width))
        timeline.append(SegmentTiming(sid,s.path,cumulative/HEAD_SPEED,
                       cumulative/HEAD_SPEED+tail_delay,density,level_of_service(density)))
        cumulative+=s.length
    route_set=set(ids)
    v=volatility(req.context,context_features)
    targets=targets or []
    # Nearby destination square capacity: a rough upper bound (2 people/m²).
    # If the database is missing the table or geometries, retain the basic
    # corridor-density scenario rather than inventing a capacity measurement.
    overflow_fraction=0.0
    try:
        end=g.segments[ids[-1]].path[-1]
        row=mapdata.cursor().execute("""SELECT capacity_area_m2 FROM open_spaces
               WHERE capacity_area_m2 IS NOT NULL
               ORDER BY meters(geometry, ST_Point(?, ?)) LIMIT 1""",list(end)).fetchone()
        if row and row[0]:
            capacity=max(1.,2*float(row[0]))
            overflow_fraction=min(1.,max(0.,(turnout.expected-capacity)/turnout.expected))
    except Exception:
        pass
    # Associate any side street touching a route endpoint with its earliest route segment.
    adj=defaultdict(list)
    for i,sid in enumerate(ids):
        s=g.segments[sid]
        for node in (s.u,s.v):adj[node].append(i)
    risks={}
    for i,sid in enumerate(ids):
        route_s=g.segments[sid];timing=timeline[i]
        for node in (route_s.u,route_s.v):
            for other in g.outgoing.get(node,[]):
                if other in route_set:continue
                side=g.segments[other]
                pres=sigmoid(2.0*(timing.peak_density_ppm2/2-1)+.5*math.log(max(1,side.degree))-1.0)
                pull=sum(float(t['weight'])*math.exp(-mapdata.distance_m(side.mid,t['lonlat'])/150)
                         for t in targets if mapdata.distance_m(side.mid,t['lonlat'])<=300)
                pbreak=min(1,v*pull)
                if i>=max(0,len(ids)-max(1,len(ids)//20)):
                    pres=1-(1-pres)*(1-0.5*overflow_fraction)
                p=1-(1-pres)*(1-pbreak)
                if req.police_officers:
                    # Approximate top-post allocation is applied *after* scenario generation.
                    # Do not use officer numbers as a feature of route selection.
                    pass
                kind='pressure' if pres>=pbreak else 'breakaway'
                reason=(f"Crowd pressure beside {route_s.street_name or 'the route'} "
                        f"(density {timing.peak_density_ppm2:.1f} people/m²)")
                record=SpillRisk(other,side.path,float(min(1,max(0,p))),kind,
                                 timing.head_arrival_min,timing.tail_departure_min+30,reason)
                if other not in risks or p>risks[other].p_spill: risks[other]=record
    spills=sorted(risks.values(),key=lambda r:-r.p_spill)[:500]
    if req.police_officers and spills:
        # Deterministic 5-officer greedy allocation, A8 utility is separable/concave.
        allocated=[0]*len(spills)
        for _ in range(max(0,req.police_officers)//5):
            j=max(range(len(spills)),key=lambda k:spills[k].p_spill*math.exp(-ETA*allocated[k])*(1-math.exp(-ETA*5)))
            allocated[j]+=5
        for spill,num in zip(spills,allocated):spill.p_spill*=math.exp(-ETA*num)
        spills.sort(key=lambda x:-x.p_spill)
        warnings.append('Police mitigation uses an assumed exponential response (not experimentally validated).')
    cellids=mapdata.cells_for_segments([s.segment_id for s in spills]);cells=defaultdict(float)
    for spill in spills:
        if spill.segment_id in cellids:
            c=cellids[spill.segment_id];cells[c]=max(cells[c],spill.p_spill)
    hotspot=[Hotspot(g.segments[s.segment_id].mid,s.p_spill,risk_level(s.p_spill),s.kind,s.reason)
             for s in spills[:20]]
    # Optional gathering space occupancy warning if nearest end open space lacks capacity.
    # Endpoint capacity is approximate because attendees may stand in streets too.
    if turnout.expected>0:
        warnings.append('End-point crowd capacity is approximate; gathering space is not independently measured.')
    return OverspillPrediction(req,turnout,timeline,spills,
        [CellValue(c,p) for c,p in sorted(cells.items(),key=lambda kv:-kv[1])],hotspot,
        round(timeline[-1].tail_departure_min+RALLY_MIN,1),
        [Driver('Scenario density',round(max(t.peak_density_ppm2 for t in timeline),2),0.5,
                'Pressure rises as the corridor becomes narrower.'),
         Driver('Assumed head speed',HEAD_SPEED,0,'Crowd head speed is fixed at 42 metres per minute.')],
        version,warnings)
