"""Shared helpers for every page: predictor access, cached calls, formatting, page header.

Pages only talk to the model through this module (which only uses src.contract),
so swapping the mock for the real predictor needs no page changes.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Callable, Optional

import streamlit as st

from src.contract import get_predictor as _contract_predictor
from src.contract import mapdata
from src.contract.errors import PredictionError
from src.contract.types import (BacktestResult, CauseOption, HistoricalEvent, LonLat, MarchContext,
                                OverspillPrediction, OverspillRequest, PointRisk, PoliceAllocation, Prediction,
                                RoutePrediction, RouteRequest, ShopAdvice)

# ---------- connection and predictor ----------


@st.cache_resource
def get_db():
    """The shared read-only connection (same one the model layer uses)."""
    return mapdata.connection()


@st.cache_resource(show_spinner="Loading the prediction model...")
def get_predictor():
    return _contract_predictor()


def reload_predictor() -> None:
    """Pick up a newly trained model without restarting the app."""
    get_predictor.clear()
    st.cache_data.clear()


def is_mock() -> bool:
    return get_predictor().name == "mock"


def is_dark() -> bool:
    try:
        return st.context.theme.type == "dark"
    except Exception:  # no active session (scripts, tests) or an older Streamlit
        return False


# ---------- request (de)serialisation for caching ----------

def request_key(req) -> str:
    return json.dumps(req.to_dict(), sort_keys=True)


def route_request_from_dict(d: dict) -> RouteRequest:
    return RouteRequest(context=MarchContext(**d["context"]), start=tuple(d["start"]),
                        end=tuple(d["end"]) if d.get("end") else None,
                        exclusion_zones=tuple(tuple(tuple(p) for p in ring) for ring in d.get("exclusion_zones", ())),
                        n_routes=d.get("n_routes", 3))


def overspill_request_from_dict(d: dict) -> OverspillRequest:
    return OverspillRequest(context=MarchContext(**d["context"]), route_segment_ids=tuple(d["route_segment_ids"]),
                            police_officers=d.get("police_officers"))


@st.cache_data(show_spinner="Predicting where the march goes...", max_entries=50)
def _predict_route(key: str, version: str) -> RoutePrediction:
    return get_predictor().predict_route(route_request_from_dict(json.loads(key)))


@st.cache_data(show_spinner="Simulating the crowd along the route...", max_entries=50)
def _predict_overspill(key: str, version: str) -> OverspillPrediction:
    return get_predictor().predict_overspill(overspill_request_from_dict(json.loads(key)))


@st.cache_data(show_spinner="Snapping the route to streets...", max_entries=50)
def _snap_route(points_json: str, version: str) -> list[str]:
    return get_predictor().snap_route([tuple(p) for p in json.loads(points_json)])


def _prediction_for(kind: str, key: str, version: str) -> Prediction:
    return _predict_route(key, version) if kind == "route" else _predict_overspill(key, version)


@st.cache_data(show_spinner="Working out the advice for your shop...", max_entries=200)
def _shop_advice(kind: str, key: str, version: str, shop: tuple[float, float]) -> ShopAdvice:
    return get_predictor().shop_advice(_prediction_for(kind, key, version), shop)


@st.cache_data(show_spinner="Placing officers...", max_entries=200)
def _allocate_police(key: str, version: str, officers: int) -> PoliceAllocation:
    return get_predictor().allocate_police(_predict_overspill(key, version), officers)


@st.cache_data(max_entries=4)
def _backtest(version: str) -> Optional[BacktestResult]:
    return get_predictor().backtest()


def _guard(fn: Callable, *args):
    """Run a model call; show PredictionError messages to the user instead of crashing."""
    try:
        return fn(*args)
    except PredictionError as exc:
        st.error(exc.user_message, icon=":material/error:")
    except Exception as exc:  # a model bug should not take the page down
        st.error("The prediction model hit an unexpected error.", icon=":material/bug_report:")
        with st.expander("Technical details"):
            st.exception(exc)
    return None


def _version() -> str:
    p = get_predictor()
    return f"{p.name}:{p.version}"


def predict_route(req: RouteRequest) -> Optional[RoutePrediction]:
    return _guard(_predict_route, request_key(req), _version())


def predict_overspill(req: OverspillRequest) -> Optional[OverspillPrediction]:
    return _guard(_predict_overspill, request_key(req), _version())


def snap_route(points: list[LonLat]) -> Optional[list[str]]:
    return _guard(_snap_route, json.dumps([list(p) for p in points]), _version())


def point_risk(prediction: Prediction, point: LonLat) -> Optional[PointRisk]:
    return _guard(get_predictor().point_risk, prediction, point)


def shop_advice(prediction: Prediction, shop: LonLat) -> Optional[ShopAdvice]:
    kind = "route" if isinstance(prediction, RoutePrediction) else "overspill"
    return _guard(_shop_advice, kind, request_key(prediction.request), _version(), tuple(shop))


def allocate_police(prediction: OverspillPrediction, officers: int) -> Optional[PoliceAllocation]:
    return _guard(_allocate_police, request_key(prediction.request), _version(), int(officers))


# The contract leaves summary metric names open; accept the model's names for the UI's keys.
METRIC_ALIASES = {"destination_top3_rate": "destination_in_top3", "destination_in_top3_rate": "destination_in_top3"}


def backtest() -> Optional[BacktestResult]:
    bt = _guard(_backtest, _version())
    if bt:
        for metrics in bt.summary.values():
            for alias, key in METRIC_ALIASES.items():
                if alias in metrics and key not in metrics:
                    metrics[key] = metrics[alias]
    return bt


# ---------- cached base data ----------

@st.cache_data
def causes() -> list[CauseOption]:
    return mapdata.list_causes()


@st.cache_data
def historical_events() -> list[HistoricalEvent]:
    return mapdata.historical_events()


@st.cache_data
def assembly_points() -> list[dict]:
    return mapdata.assembly_points()


@st.cache_data
def boundary() -> list:
    return mapdata.boundary()


@st.cache_data
def legal_zones() -> list[dict]:
    return mapdata.legal_zones()


@st.cache_data
def targets(categories: Optional[tuple[str, ...]] = None) -> list[dict]:
    return mapdata.targets(list(categories) if categories else None)


@st.cache_data
def cause_targets(cause: Optional[str]) -> list[dict]:
    return mapdata.cause_targets(cause)


@st.cache_data
def warehouses() -> list[dict]:
    return mapdata.warehouses()


@st.cache_data
def cell_polygons() -> dict[int, dict]:
    return {c["cell_id"]: c for c in mapdata.cells()}


@st.cache_data(max_entries=200)
def shops_near(point: tuple[float, float], radius_m: float = 300) -> list[dict]:
    return mapdata.shops_near(point, radius_m)


@st.cache_data(max_entries=200)
def search_shops(text: str) -> list[dict]:
    return mapdata.search_shops(text) if text.strip() else []


def _clean_street(name) -> str:
    return "" if str(name or "").strip().lower() in ("", "none", "nan") else str(name)


@st.cache_data(max_entries=100)
def street_names(ids: tuple[str, ...]) -> dict[str, str]:
    if not ids:
        return {}
    rows = mapdata.cursor().execute(
        "SELECT segment_id, street_name FROM segments WHERE segment_id IN (SELECT UNNEST(?))", [list(ids)]).fetchall()
    return {sid: _clean_street(name) for sid, name in rows}


def in_boundary(point: LonLat) -> bool:
    return mapdata.in_boundary(point)


# ---------- formatting ----------

RISK_BADGE = {"low": ("green", ":material/check_circle:", "Low risk"),
              "medium": ("orange", ":material/warning:", "Medium risk"),
              "high": ("red", ":material/error:", "High risk"),
              "severe": ("red", ":material/dangerous:", "Severe risk")}


def risk_badge(level: str) -> None:
    color, icon, label = RISK_BADGE.get(level, ("gray", ":material/help:", level))
    st.badge(label, icon=icon, color=color)


def clock(ctx: MarchContext, minutes: Optional[float]) -> str:
    """Minutes after the march start -> 'HH:MM' local time (with a day marker if it rolls over)."""
    if minutes is None:
        return "-"
    start = dt.datetime.combine(dt.date.fromisoformat(ctx.date), dt.time.fromisoformat(ctx.start_time))
    t = start + dt.timedelta(minutes=float(minutes))
    days = (t.date() - start.date()).days
    suffix = f" (+{days} day)" if days > 0 else (" (day before)" if days < 0 else "")
    return t.strftime("%H:%M") + suffix


def duration(minutes: float) -> str:
    minutes = max(0, round(minutes))
    h, m = divmod(minutes, 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


def pct(p: float) -> str:
    return f"{p:.0%}" if p >= 0.01 or p == 0 else "<1%"


def km(metres: float) -> str:
    return f"{metres / 1000:.1f} km"


def describe_context(ctx: MarchContext) -> str:
    cause = next((c.label for c in causes() if c.key == ctx.cause), ctx.cause or "unknown cause")
    date = dt.date.fromisoformat(ctx.date).strftime("%a %d %b %Y")
    turnout = f", {ctx.turnout:,} people" if ctx.turnout else ""
    return f"{cause}, {date} at {ctx.start_time}{turnout}"


# ---------- page furniture ----------

def page_header(title: str, subtitle: str) -> None:
    st.title(title)
    st.caption(subtitle)
    if is_mock():
        st.warning("Showing illustrative outputs from the **mock predictor**: the trained model isn't available yet "
                   "(run `python -m src.models.train`, then **Reload model** on the dashboard).",
                   icon=":material/science:")


def need_prediction(kind: str) -> None:
    """Empty state for pages that need a prediction first."""
    if kind == "overspill":
        st.info("This needs a planned-route analysis first.", icon=":material/info:")
        st.page_link("src/ui/pages/planned_route.py", label="Analyse a planned route", icon=":material/route:")
    else:
        st.info("This needs a prediction first: predict a route or analyse a planned route.", icon=":material/info:")
        st.page_link("src/ui/pages/route_predictor.py", label="Predict a route", icon=":material/explore:")
        st.page_link("src/ui/pages/planned_route.py", label="Analyse a planned route", icon=":material/route:")
