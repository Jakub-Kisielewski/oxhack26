"""Directed march graph built from the Phase-0 DuckDB streets table.

The only database access in this module is through contract.mapdata.cursor().
No writes to the source DuckDB database are made.
"""
from __future__ import annotations

import json
import math
import pickle
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import networkx as nx
import numpy as np
from scipy.spatial import cKDTree

from src.contract import mapdata
from src.contract.types import LonLat

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / 'data' / 'models'
GRAPH_PATH = ARTIFACTS / 'graph.pkl'
ALLOWED = {'trunk','primary','secondary','tertiary','trunk_link','primary_link',
           'secondary_link','tertiary_link','unclassified','residential',
           'living_street','pedestrian'}


def xy(p: LonLat) -> tuple[float, float]:
    return (float(p[0]) * 111_320 * math.cos(math.radians(51.51)), float(p[1]) * 111_320)


def bearing(a: LonLat, b: LonLat) -> float:
    x1,y1 = xy(a); x2,y2 = xy(b)
    return math.atan2(y2-y1,x2-x1)


def angle(a: float,b: float) -> float:
    return abs((b-a+math.pi) % (2*math.pi)-math.pi) / math.pi


@dataclass
class Segment:
    id: str
    u: str
    v: str
    length: float
    road_class: str
    street_name: str
    width: float
    betweenness: float
    degree: float
    is_main: bool
    is_bridge: bool
    is_tunnel: bool
    royal_park: bool
    restricted: bool
    path: list[LonLat]
    mid: LonLat
    start_bearing: float
    end_bearing: float


class MarchGraph:
    def __init__(self, segments: dict[str,Segment]):
        self.segments = segments
        self.outgoing = defaultdict(list)
        self.nodes: dict[str,LonLat] = {}
        self.node_graph = nx.DiGraph()
        self.pair_segment: dict[tuple[str,str],str] = {}
        for sid,s in segments.items():
            self.nodes.setdefault(s.u,s.path[0]); self.nodes.setdefault(s.v,s.path[-1])
            self.outgoing[s.u].append(sid)
            pair=(s.u,s.v)
            if pair not in self.pair_segment or s.length < segments[self.pair_segment[pair]].length:
                self.pair_segment[pair]=sid
                self.node_graph.add_edge(s.u,s.v,weight=s.length)
        self._build_index()

    def _build_index(self):
        self._ids=list(self.segments)
        self._midtree=cKDTree(np.array([xy(self.segments[s].mid) for s in self._ids])) if self._ids else None
        self._nodeids=list(self.nodes)
        self._nodetree=cKDTree(np.array([xy(self.nodes[n]) for n in self._nodeids])) if self._nodeids else None

    def next_ids(self, sid: str) -> list[str]:
        if sid not in self.segments: return []
        a=self.segments[sid]
        return [b for b in self.outgoing[a.v] if self.segments[b].v != a.u]

    def nearest_segment(self, p: LonLat) -> tuple[str,float]:
        if self._midtree is None: raise ValueError('Empty street graph')
        d,i=self._midtree.query(xy(p),k=min(12,len(self._ids)))
        ix=np.atleast_1d(i)
        # Re-rank approximate midpoint candidates by distance to polylines.
        sid=min((self._ids[int(j)] for j in ix), key=lambda k: line_distance(p,self.segments[k].path))
        return sid,line_distance(p,self.segments[sid].path)

    def nearest_node(self, p: LonLat) -> str:
        if self._nodetree is None: raise ValueError('Empty street graph')
        return self._nodeids[int(self._nodetree.query(xy(p))[1])]

    def route_nodes(self,a: str,b: str) -> list[str]:
        try:return nx.shortest_path(self.node_graph,a,b,weight='weight')
        except (nx.NetworkXNoPath,nx.NodeNotFound): return []

    def route_between(self, a:LonLat,b:LonLat) -> list[str]:
        nodes=self.route_nodes(self.nearest_node(a),self.nearest_node(b))
        return [self.pair_segment[(u,v)] for u,v in zip(nodes,nodes[1:])]

    def snap_route(self,points:list[LonLat]) -> list[str]:
        if len(points)<2: raise ValueError('Need at least two route points')
        route=[]
        for a,b in zip(points,points[1:]):
            chunk=self.route_between(a,b)
            route.extend(chunk if not route else (chunk[1:] if chunk and route[-1]==chunk[0] else chunk))
        return route

    def geometry(self, ids: list[str]) -> list[LonLat]:
        points=[]
        for sid in ids:
            if sid not in self.segments:continue
            coords=self.segments[sid].path
            points.extend(coords[1:] if points and points[-1]==coords[0] else coords)
        return points


def line_distance(p: LonLat, line: list[LonLat]) -> float:
    px,py=xy(p)
    best=float('inf')
    for a,b in zip(line,line[1:]):
        ax,ay=xy(a);bx,by=xy(b)
        den=(bx-ax)**2+(by-ay)**2
        t=max(0,min(1,((px-ax)*(bx-ax)+(py-ay)*(by-ay))/den)) if den else 0
        best=min(best,math.hypot(px-ax-t*(bx-ax),py-ay-t*(by-ay)))
    return best if math.isfinite(best) else float('inf')


def from_database() -> MarchGraph:
    cur=mapdata.cursor()
    # The DB stores EPSG:4326 lon/lat geometries; do not swap coordinate axes.
    rows=cur.execute('''
        SELECT segment_id, CAST(u AS VARCHAR), CAST(v AS VARCHAR),
          length_m, road_class, street_name, width_m,
          COALESCE(betweenness_main,betweenness_walk,0), to_degree,
          is_main,is_bridge,is_tunnel,in_no_entry_zone,in_restricted_zone,in_royal_park,
          ST_AsGeoJSON(geom)
        FROM segments WHERE geom IS NOT NULL
    ''').fetchall()
    route_ids={str(r[0]) for r in cur.execute('SELECT DISTINCT segment_id FROM route_segments').fetchall()}
    candidates={}
    for row in rows:
        (sid,u,v,length,road,name,width,between,degree,ismain,bridge,tunnel,forbidden,restricted,park,geo)=row
        sid=str(sid)
        if forbidden: continue
        road=str(road or '').lower().split(';')[0].strip()
        if road not in ALLOWED and sid not in route_ids:continue
        geom=json.loads(geo)
        if geom['type'] != 'LineString':continue
        path=[(float(p[0]),float(p[1])) for p in geom['coordinates']]
        if len(path)<2:continue
        length=max(1.0,float(length or 1.0))
        candidates[sid]=Segment(sid,str(u),str(v),length,road,str(name or ''),
            max(1.0,float(width or 3.0)),max(0.0,float(between or 0)),
            max(1.0,float(degree or 1)),bool(ismain),bool(bridge),bool(tunnel),
            bool(park),bool(restricted),path,path[len(path)//2],
            bearing(path[0],path[1]),bearing(path[-2],path[-1]))
    # Retain the largest strongly connected component of graph nodes.
    dg=nx.DiGraph()
    dg.add_edges_from((s.u,s.v) for s in candidates.values())
    largest=max(nx.strongly_connected_components(dg),key=len) if len(dg) else set()
    # Keep route labels in the graph even if OSM connectivity strands a tiny portion.
    kept={k:s for k,s in candidates.items() if (s.u in largest and s.v in largest) or k in route_ids}
    return MarchGraph(kept)


def load_graph(path:Path=GRAPH_PATH) -> MarchGraph:
    with open(path,'rb') as f: return pickle.load(f)


def build_graph(path:Path=GRAPH_PATH, force:bool=False) -> MarchGraph:
    if path.exists() and not force:return load_graph(path)
    graph=from_database()
    path.parent.mkdir(parents=True,exist_ok=True)
    with open(path,'wb') as f: pickle.dump(graph,f,pickle.HIGHEST_PROTOCOL)
    return graph
