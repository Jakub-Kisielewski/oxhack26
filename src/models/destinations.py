"""Cause-conditional destinations, combining curated targets and historical end points."""
from __future__ import annotations
from collections import Counter
from src.contract import mapdata
from src.contract.types import Destination
from src.models.graph import MarchGraph
from src.models.labels import TrainingEvent


def candidates(cause:str|None,events:list[TrainingEvent],end=None,max_n:int=5)->list[Destination]:
    if end is not None:return [Destination('Selected destination',tuple(end),1.0)]
    raw=[]
    for t in mapdata.cause_targets(cause):
        weight=max(.001,float(t['weight']))
        raw.append((str(t['target_name']),tuple(t['lonlat']),weight))
    for e in events:
        if cause and e.cause!=cause:continue
        if not any(mapdata.distance_m(e.destination,p)<150 for _,p,_ in raw):
            name=getattr(e,'destination_name','')
            raw.append((f'{name[:1].upper()}{name[1:]} (past end point)' if name else 'Past end point',e.destination,1.0))
    scores=[]
    for name,pt,w in raw:
        n=sum(1 for e in events if (not cause or e.cause==cause) and
              mapdata.distance_m(pt,e.destination)<=250)
        scores.append(Destination(name,pt,w*(1+n)))
    scores.sort(key=lambda s:-s.probability)
    if not scores:return []
    # Normalise *before* filtering and keep the missing tail mass explicit (<1).
    total=sum(x.probability for x in scores)
    return [Destination(x.name,x.lonlat,x.probability/total) for x in scores
            if x.probability/total>=.05][:max_n] or [Destination(scores[0].name,scores[0].lonlat,1.0)]
