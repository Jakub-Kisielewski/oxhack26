"""The interface the model layer implements and the visual layer calls."""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from src.contract.types import (BacktestResult, LonLat, OverspillPrediction, OverspillRequest, PointRisk,
                                PoliceAllocation, Prediction, RoutePrediction, RouteRequest, ShopAdvice)


@runtime_checkable
class Predictor(Protocol):
    name: str            # "mock" or "real"
    version: str         # model version string, shown in the UI

    def snap_route(self, points: list[LonLat]) -> list[str]:
        """Ordered segment_ids of a walkable route through the given points (>= 2), in order."""

    def predict_route(self, req: RouteRequest) -> RoutePrediction:
        """Route mode. Raises PredictionError for unusable input (e.g. start outside the boundary)."""

    def predict_overspill(self, req: OverspillRequest) -> OverspillPrediction:
        """Overspill mode for a given route."""

    def point_risk(self, prediction: Prediction, point: LonLat) -> PointRisk:
        """Risk at one location under a prediction (pin drop)."""

    def shop_advice(self, prediction: Prediction, shop: LonLat) -> ShopAdvice:
        """Whether and when to move stock, and the best nearby warehouses."""

    def allocate_police(self, prediction: OverspillPrediction, officers: int) -> PoliceAllocation:
        """Where to place `officers` to minimise expected spill."""

    def backtest(self) -> Optional[BacktestResult]:
        """Saved leave-one-event-out results, or None if not computed."""
