"""Model-owned sanity tests; run `python -m src.models.checks` after training."""
from __future__ import annotations
import math
import numpy as np
from src.contract import mapdata
from src.contract.types import MarchContext,RouteRequest,OverspillRequest
from src.models.predictor import RealPredictor


def main():
    if not RealPredictor.available():raise RuntimeError('Train first: python -m src.models.train')
    p=RealPredictor()
    req=RouteRequest(MarchContext('2026-03-21',cause='palestine'),(-.1586,51.5136),n_routes=3)
    out=p.predict_route(req)
    assert out.model_version==p.version
    assert all(0<=s.p_visit<=1 for s in out.segments)
    assert all(out.segments[i].p_visit>=out.segments[i+1].p_visit for i in range(len(out.segments)-1))
    assert sum(d.probability for d in out.destinations)<=1.000001
    ids=p.snap_route([(-.1586,51.5136),(-.1281,51.5080)])
    assert ids
    ev=mapdata.historical_events()[0]
    spill=p.predict_overspill(OverspillRequest(MarchContext(ev.date),tuple(ev.route_segment_ids)))
    assert not set(ev.route_segment_ids)&{s.segment_id for s in spill.spill}
    assert sum(x.officers for x in p.allocate_police(spill,50).posts)<=50
    print('Model checks passed')

if __name__=='__main__':main()
