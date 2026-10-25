"""Track A real predictor: implements the frozen Phase-0 src.contract.api.Predictor."""
from __future__ import annotations
from pathlib import Path
from src.contract import mapdata
from src.contract.errors import PredictionError
from src.contract.types import (RouteRequest,RoutePrediction,OverspillRequest,PointRisk)
from src.models.graph import GRAPH_PATH,load_graph
from src.models.route_model import ChoiceModel
from src.models.labels import read_events,history_counts
from src.models.destinations import candidates
from src.models.turnout import estimate,base as turnout_base
from src.models import conditions
from src.models.overspill import volatility,volatility_parts
from src.models.inference import infer
from src.models.overspill import predict as predict_spill
from src.models.decisions import point_risk,shop_advice,allocate_police
from src.models.backtest import read_backtest

MODEL_PATH=GRAPH_PATH.parent/'route_model.json'
BACKTEST_PATH=GRAPH_PATH.parent/'backtest.json'

class RealPredictor:
    name='real'
    version='route-logit-1.0'

    @staticmethod
    def available()->bool:
        return GRAPH_PATH.exists() and MODEL_PATH.exists()

    def __init__(self):
        if not self.available():
            raise PredictionError('Model not trained. Run python -m src.models.train first.')
        self.graph=load_graph()
        self.model=ChoiceModel.from_json(MODEL_PATH)
        self.events=read_events(self.graph)
        self.history=history_counts(self.events)

    def snap_route(self,points):
        if len(points)<2:raise PredictionError('Two or more points are required.')
        route=self.graph.snap_route(points)
        if not route:raise PredictionError('Cannot connect these points on the walk network.')
        return route

    def _conditions(self,ctx):
        """Weather, media attention and calendar for this march, the turnout they imply, and every effect."""
        c=conditions.estimate(ctx)
        base,source=turnout_base(ctx,self.events)
        t_effects=[] if ctx.turnout is not None else conditions.turnout_effects(c,ctx)
        turnout=estimate(ctx,self.events,conditions.apply_turnout(base,t_effects))
        effects=(t_effects+conditions.route_effects(c,turnout.expected,self.model)+conditions.duration_effects(c)
                 +conditions.rowdiness_effects(volatility_parts(ctx,c)))
        if ctx.turnout is not None:
            base,source=int(ctx.turnout),'set by the user'
        return c,turnout,conditions.build(c,base,source,volatility(ctx,c),effects)

    def predict_route(self,req:RouteRequest):
        if not mapdata.in_boundary(req.start):
            raise PredictionError('Start is outside the London model boundary. Choose a point in central London.')
        c,turnout,march_conditions=self._conditions(req.context)
        ends=candidates(req.context.cause,self.events,req.end)
        if not ends:
            raise PredictionError('No candidate destinations. Provide a destination or train with historical events.')
        context={'turnout':turnout.expected,'cause':req.context.cause,'precip_mm_4h':c['precip_mm_4h'],
                 'dark_fraction':c['dark_fraction']}
        segs,cells,routes,drivers,warnings=infer(self.graph,self.model,req.start,ends,context,
            self.history,mapdata.cause_targets,req.exclusion_zones,max(1,min(int(req.n_routes),10)))
        if not routes:warnings.append('No connected route found; check start, end and exclusion areas.')
        rally=60.0*(1+sum(e.size for e in march_conditions.effects if e.target=='duration'))
        duration=(routes[0].duration_min if routes else 0.0)+rally
        warnings.insert(0,'Routes are based on announced itineraries and shortest-path interpolations, not GPS traces.')
        return RoutePrediction(req,turnout,segs,cells,routes,ends,duration,drivers,
                               self.version,warnings,march_conditions)

    def predict_overspill(self,req:OverspillRequest):
        c,turnout,march_conditions=self._conditions(req.context)
        prediction=predict_spill(self.graph,req,turnout,self.version,mapdata.cause_targets(req.context.cause),
                                 context_features=c)
        prediction.conditions=march_conditions
        return prediction

    def point_risk(self,prediction,point):
        return point_risk(self.graph,prediction,point)

    def shop_advice(self,prediction,shop):
        return shop_advice(self.graph,prediction,shop)

    def allocate_police(self,prediction,officers):
        return allocate_police(self.graph,prediction,officers)

    def backtest(self):
        return read_backtest(BACKTEST_PATH)
