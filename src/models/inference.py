"""Absorbing-chain visit probabilities and top-k routes on -log transition scores.

The small independent termination hazard (1%) makes the transient system
well-conditioned when OSM subgraphs contain unreachable loops. Returned expected
visits are capped at one as requested by the Phase 0 contract; this is an
approximation to true hitting probabilities, not a calibrated street probability.
"""
from __future__ import annotations
import math
from collections import defaultdict
import networkx as nx
import numpy as np
from scipy.sparse import csr_matrix,eye
from scipy.sparse.linalg import spsolve
from src.contract import mapdata
from src.contract.types import CellValue,Driver,RouteOption,SegmentProb
from src.models.graph import MarchGraph
from src.models.route_model import ChoiceModel

HAZARD=.01
MAX_LOCAL=15000  # safeguards the sparse direct solve on laptop hardware


def local_ids(g:MarchGraph,start,destination,exclude=()):
    from shapely.geometry import Point,Polygon
    from src.models.graph import xy
    direct=mapdata.distance_m(start,destination)
    limit=1.6*direct+500
    # Vectorise the ellipse test over the cached projected street midpoints.
    mids=g._midtree.data
    a=np.array(xy(start));b=np.array(xy(destination))
    distances=np.linalg.norm(mids-a,axis=1)+np.linalg.norm(mids-b,axis=1)
    ix=np.flatnonzero(distances<=limit)
    if len(ix)>MAX_LOCAL:ix=ix[np.argsort(distances[ix])[:MAX_LOCAL]]
    ids=[g._ids[int(i)] for i in ix]
    if exclude:
        zones=[Polygon(poly) for poly in exclude if len(poly)>=3]
        if zones:ids=[sid for sid in ids if not any(z.contains(Point(g.segments[sid].mid)) for z in zones)]
    return ids


def _transitions(g,model,ids,destination,context,history,targets):
    valid=set(ids);adj={}; absorbing=set()
    for sid in ids:
        if mapdata.distance_m(g.segments[sid].path[-1],destination)<=75:
            absorbing.add(sid);adj[sid]=[];continue
        choices=[b for b in g.next_ids(sid) if b in valid]
        p=model.probs(g,sid,choices,destination,context,history,targets)
        adj[sid]=list(zip(choices,map(float,p)))
    return adj,absorbing


def visit_probabilities(adj,absorbing,start):
    if start not in adj:return {}
    # transient-to-transient Q; absorption is excluded from Q.
    trans=[s for s in adj if s not in absorbing]
    idx={s:i for i,s in enumerate(trans)}
    values=[]; rows=[];cols=[];abs_weights=defaultdict(float)
    for s,opts in adj.items():
        if s not in idx:continue
        for dest,p in opts:
            if dest in idx:
                rows.append(idx[s]);cols.append(idx[dest]);values.append((1-HAZARD)*p)
    if not trans:return {start:1.0}
    Q=csr_matrix((values,(rows,cols)),shape=(len(trans),len(trans)))
    b=np.zeros(len(trans))
    if start in idx:b[idx[start]]=1
    visits=spsolve(eye(len(trans),format='csr')-Q.T,b)
    ret={sid:float(np.clip(v,0,1)) for sid,v in zip(trans,visits) if np.isfinite(v) and v>=.01}
    if start in absorbing:ret[start]=1
    for sid,p in ret.copy().items():
        if sid not in adj:continue
        for nxt,weight in adj[sid]:
            if nxt in absorbing:abs_weights[nxt]+=(1-HAZARD)*p*weight
    ret.update({sid:float(min(1,val)) for sid,val in abs_weights.items() if val>=.01})
    return ret


def top_routes(g:MarchGraph,adj,absorbing,start,limit,destination_name):
    if start not in adj:return []
    edges=nx.DiGraph();goal='_GOAL_'
    for sid,options in adj.items():
        for b,p in options:
            if p>0:edges.add_edge(sid,b,weight=-math.log(max(1e-10,p*(1-HAZARD))))
        if sid in absorbing:edges.add_edge(sid,goal,weight=0.0)
    if goal not in edges or start not in edges:return []
    try: pathgen=nx.shortest_simple_paths(edges,start,goal,weight='weight')
    except (nx.NetworkXNoPath,nx.NodeNotFound):return []
    out=[]
    try:
        for nodes in pathgen:
            ids=[x for x in nodes if x!=goal]
            if len(ids)>1000:continue
            length=sum(g.segments[s].length for s in ids)
            cost=sum(edges[u][v]['weight'] for u,v in zip(nodes,nodes[1:]))
            out.append((ids,length,cost,destination_name))
            if len(out)>=limit:break
    except (nx.NetworkXNoPath,nx.NodeNotFound):pass
    return out


def infer(g:MarchGraph,model:ChoiceModel,start,ends,context,history,targets_for,
          exclusions=(),n_routes=3):
    sid,dist=g.nearest_segment(start)
    combined=defaultdict(float);all_paths=[]; warnings=[]
    for dest in ends:
        if dest.probability<.05:continue
        ids=local_ids(g,start,dest.lonlat,exclusions)
        ids=list(set(ids)|{sid})
        adj,absorbing=_transitions(g,model,ids,dest.lonlat,context,history,targets_for(context.get('cause')))
        if not absorbing:
            # On sparse or highly restricted graphs, use a nearest end-segment.
            closest=min(ids,key=lambda x:mapdata.distance_m(g.segments[x].path[-1],dest.lonlat))
            absorbing={closest};adj[closest]=[]
            warnings.append(f'Endpoint {dest.name} approximated at closest reachable street')
        try:
            probabilities=visit_probabilities(adj,absorbing,sid)
        except Exception as exc:
            warnings.append(f'Sparse solve failed for {dest.name}: {exc}')
            probabilities={sid:1.0}
        for segment,p in probabilities.items():combined[segment]+=dest.probability*p
        all_paths.extend((route,length,cost-math.log(max(dest.probability,1e-8)),name)
                         for route,length,cost,name in top_routes(g,adj,absorbing,sid,max(n_routes,3),dest.name))
    if not all_paths:
        # Fallback: shortest path to top destination (ensures useful baseline).
        if ends:
            route=g.route_between(start,ends[0].lonlat)
            if route:all_paths=[(route,sum(g.segments[s].length for s in route),0.0,ends[0].name)]
        warnings.append('Using shortest-path fallback; route scores are not calibrated')
    all_paths.sort(key=lambda v:v[2])
    # Avoid duplicate identical paths from similar nearby destinations.
    unique=[];seen=set()
    for item in all_paths:
        key=tuple(item[0])
        if key not in seen:unique.append(item);seen.add(key)
        if len(unique)>=n_routes:break
    if unique:
        cost=np.array([i[2] for i in unique]); prob=np.exp(-(cost-cost.min()));prob/=prob.sum()
    else:prob=[]
    routes=[RouteOption(k+1,float(p),ids,g.geometry(ids),float(length),float(length/42),name)
            for k,((ids,length,_,name),p) in enumerate(zip(unique,prob))]
    values=sorted(((sid,min(1,max(0,p))) for sid,p in combined.items() if p>=.01),
                  key=lambda kv:-kv[1])[:5000]
    segs=[SegmentProb(sid,float(p),g.segments[sid].path) for sid,p in values]
    cells=mapdata.cells_for_segments([s.segment_id for s in segs])
    grouped=defaultdict(float)
    for s in segs:
        if s.segment_id in cells: grouped[cells[s.segment_id]]=max(grouped[cells[s.segment_id]],s.p_visit)
    cell_values=[CellValue(k,v) for k,v in sorted(grouped.items(),key=lambda kv:-kv[1])]
    drivers=[]
    if routes:
        ids=routes[0].segment_ids
        drivers=[Driver('Destination progress',round(routes[0].length_m/1000,2),float(model.theta[0]),
                        'The choice model favours streets that move toward a likely destination.'),
                 Driver('Road width',round(sum(g.segments[s].width for s in ids)/len(ids),1),float(model.theta[1]),
                        'Wider streets can change the predicted preference for a route.'),
                 Driver('Turning',len(ids),float(model.theta[5]),
                        'Changes of direction carry a learned cost in the model.')]
    return segs,cell_values,routes,drivers,warnings
