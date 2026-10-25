"""Leakage-controlled leave-one-event-out test (reported routes, not observed GPS).

No metric is invented: if the learned model loses to the baseline, that loss is
recorded and surfaced in the dashboard.
"""
from __future__ import annotations
import json
import math
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
from src.contract import mapdata
from src.contract.types import BacktestResult,BacktestRow
from src.models.graph import MarchGraph
from src.models.labels import TrainingEvent,history_counts
from src.models.route_model import ChoiceModel,fit
from src.models.destinations import candidates


def jaccard(a,b):
    sa,sb=set(a),set(b)
    return len(sa&sb)/len(sa|sb) if sa|sb else 0.0


def step_loglik(g:MarchGraph,event:TrainingEvent,model:ChoiceModel|None,history,targets):
    ll=[]
    for a,b in zip(event.route,event.route[1:]):
        choices=g.next_ids(a)
        if b not in choices or not choices:continue
        if model is None: p=1/len(choices)
        else:p=float(model.probs(g,a,choices,event.destination,event.context,history,targets)[choices.index(b)])
        ll.append(math.log(max(1e-12,p)))
    return sum(ll)/len(ll) if ll else float('nan')


def baseline_ll(g:MarchGraph,event:TrainingEvent,route:list[str]):
    # An epsilon-smoothed greedy-path distribution: 90% preferred turn,
    # 10% allocated to alternatives. This is a modelling choice, not a fitted score.
    pathnext=dict(zip(route,route[1:]));ll=[]
    for a,b in zip(event.route,event.route[1:]):
        choices=g.next_ids(a)
        if b not in choices or not choices:continue
        chosen=pathnext.get(a)
        p=(0.9 if chosen==b else 0.1/max(1,len(choices)-1)) if chosen in choices and len(choices)>1 else 1/len(choices)
        ll.append(math.log(max(1e-12,p)))
    return sum(ll)/len(ll) if ll else float('nan')


def evaluate(g:MarchGraph,events:list[TrainingEvent],max_events:int|None=None)->BacktestResult:
    rows=[];eligible=[e for e in events if len(e.route)>=2]
    if max_events is not None:eligible=eligible[:max_events]
    for i,event in enumerate(eligible):
        training=[e for e in events if e.event_id!=event.event_id]
        hist=history_counts(training)
        def targets(cause):return mapdata.cause_targets(cause)
        model=fit(g,training,targets_for=targets,maxiter=55)
        dests=candidates(event.cause,training)
        chosen_end=dests[0].lonlat if dests else event.destination
        start=g.segments[event.route[0]].path[0]
        baseline=g.route_between(start,chosen_end)
        # Model top1 path: evaluate a short greedy rollout using learned probabilities;
        # route inference (which uses Yen and a sparse solve) is tested separately.
        cur=event.route[0]; top=[cur];seen={cur}
        for _ in range(min(500,max(30,len(event.route)*2))):
            if mapdata.distance_m(g.segments[cur].path[-1],chosen_end)<75:break
            options=[x for x in g.next_ids(cur) if x not in seen]
            if not options:break
            probs=model.probs(g,cur,options,chosen_end,event.context,hist,targets(event.cause))
            cur=options[int(np.argmax(probs))];top.append(cur);seen.add(cur)
        hit=any(mapdata.distance_m(d.lonlat,event.destination)<250 for d in dests[:3])
        rows.extend([
            BacktestRow(event.event_id,'route_model',step_loglik(g,event,model,hist,targets(event.cause)),jaccard(top,event.route),hit),
            BacktestRow(event.event_id,'shortest_path',baseline_ll(g,event,baseline),jaccard(baseline,event.route),hit),
            BacktestRow(event.event_id,'random_walk',step_loglik(g,event,None,hist,[]),0.0,False)
        ])
    summary={}
    for name in ('route_model','shortest_path','random_walk'):
        selected=[r for r in rows if r.model==name]
        def avg(values):
            valid=[v for v in values if math.isfinite(v)]
            return sum(valid)/len(valid) if valid else 0.0
        summary[name]={
            'mean_log_likelihood':avg([r.mean_log_likelihood for r in selected]),
            'top1_jaccard':avg([r.top1_jaccard for r in selected]),
            'destination_top3_rate':avg([int(r.destination_in_top3) for r in selected])}
    return BacktestResult(rows,summary,len(eligible),datetime.now(timezone.utc).isoformat())


def save_backtest(res:BacktestResult,path:Path):
    path.parent.mkdir(parents=True,exist_ok=True)
    with open(path,'w') as f:json.dump(res.to_dict(),f,indent=2,allow_nan=False)


def read_backtest(path:Path):
    if not path.exists():return None
    data=json.loads(path.read_text())
    return BacktestResult([BacktestRow(**r) for r in data['rows']],data['summary'],data['n_events'],data['created_at'])
