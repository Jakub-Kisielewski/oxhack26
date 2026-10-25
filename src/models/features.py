"""Choice-specific, standardisable route features (plan A3)."""
from __future__ import annotations
import math
import numpy as np
from src.contract import mapdata
from src.models.graph import MarchGraph, angle

NAMES=('progress','log_width','turnout_x_width','is_main','log_betweenness',
       'turn','target_pull','royal_park','restricted','history','rain_x_main','dark_x_main')
MARCH_HOURS=4


def dark_fraction(daylight_after_start_h)->float:
    """Share of the first MARCH_HOURS after the start that falls after sunset (0 = all daylight, 1 = all dark)."""
    if daylight_after_start_h is None:return 0.0
    return min(1.0,max(0.0,(MARCH_HOURS-float(daylight_after_start_h))/MARCH_HOURS))


def feature_vector(g:MarchGraph, current:str, candidate:str, destination:tuple[float,float],
                   context:dict|None=None, history:dict|None=None, targets:list|None=None) -> np.ndarray:
    context=context or {}; history=history or {}; targets=targets or []
    a=g.segments[current]; b=g.segments[candidate]
    dw=max(0.0,float(context.get('turnout') or 10000))
    rain=float(context.get('precip_mm_4h') or 0.0)
    dark=float(context.get('dark_fraction') or 0.0)
    pull=sum(float(t.get('weight') or 0)*math.exp(-mapdata.distance_m(b.path[-1],t['lonlat'])/200)
             for t in targets)
    return np.array([
        (mapdata.distance_m(a.path[-1],destination)-mapdata.distance_m(b.path[-1],destination))/1000,
        math.log(b.width),
        math.log(max(1,dw))*math.log(b.width),
        float(b.is_main),
        math.log1p(max(0.0,b.betweenness)*1000),
        angle(a.end_bearing,b.start_bearing),
        pull,float(b.royal_park),float(b.restricted),
        math.log1p(history.get(candidate,0)),
        float(rain>0.5)*float(b.is_main),
        dark*float(b.is_main)
    ],dtype=np.float64)
