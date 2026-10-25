"""Build labels using *only* historical announced waypoints; interpolation gets 0.3 weight."""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
from src.contract import mapdata
from src.models.features import dark_fraction
from src.models.graph import MarchGraph

INTERPOLATED_WEIGHT=0.3

@dataclass
class TrainingEvent:
    event_id:str
    date:str
    cause:str|None
    context:dict
    destination:tuple[float,float]
    route:list[str]
    weight:list[float]
    destination_name:str=''


def read_events(g:MarchGraph, interpolated_weight:float=INTERPOLATED_WEIGHT)->list[TrainingEvent]:
    historic=mapdata.historical_events(protests_only=True)
    rows=mapdata.cursor().execute('''SELECT event_id, precip_mm_4h, daylight_after_start_h FROM event_context''').fetchall()
    rains={str(k):float(x or 0) for k,x,_ in rows}
    darks={str(k):dark_fraction(d) for k,_,d in rows}
    output=[]
    for e in historic:
        if len(e.waypoints)<2:continue
        pts=[p for _,p in e.waypoints]
        route=g.snap_route(pts)
        if len(route)<2:continue
        weights=[]
        for sid in route:
            seg=g.segments[sid]
            weights.append(1.0 if min(mapdata.distance_m(seg.mid,p) for p in pts)<=150 else interpolated_weight)
        output.append(TrainingEvent(e.event_id,e.date,e.cause,
                      {'turnout': e.turnout or 10000,'precip_mm_4h':rains.get(e.event_id,0),
                       'dark_fraction':darks.get(e.event_id,0)},
                      pts[-1],route,weights,str(e.waypoints[-1][0] or '').strip()))
    return output


def history_counts(events:list[TrainingEvent])->dict[str,int]:
    counts=Counter()
    for event in events:
        counts.update(set(event.route)) # one observation per event, not number of loops
    return dict(counts)
