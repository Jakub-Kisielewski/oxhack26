"""Data types shared by the model layer (src/models) and the visual layer (src/ui).

Coordinates are (lon, lat) in EPSG:4326. Times inside predictions are minutes after
the march start. Distances in metres. Probabilities in [0, 1].
All fields are JSON-friendly; use `to_dict()` for caching/serialising.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal, Optional, Union

CONTRACT_VERSION = "1.1.0"

LonLat = tuple[float, float]
Path = list[LonLat]
RiskLevel = Literal["low", "medium", "high", "severe"]
SpillKind = Literal["pressure", "breakaway"]
LevelOfService = Literal["A", "B", "C", "D", "E", "F"]


def risk_level(p: float) -> RiskLevel:
    if p < 0.1:
        return "low"
    if p < 0.3:
        return "medium"
    if p < 0.6:
        return "high"
    return "severe"


class _Serialisable:
    def to_dict(self) -> dict:
        return asdict(self)


# ---------- inputs ----------

@dataclass(frozen=True)
class MarchContext(_Serialisable):
    date: str                          # "YYYY-MM-DD"
    start_time: str = "12:00"          # "HH:MM", Europe/London
    cause: Optional[str] = None        # a key from mapdata.list_causes(); None = unknown
    organiser: Optional[str] = None    # free text, e.g. "Palestine Solidarity Campaign"
    turnout: Optional[int] = None      # None = model estimates it


@dataclass(frozen=True)
class RouteRequest(_Serialisable):
    context: MarchContext
    start: LonLat
    end: Optional[LonLat] = None                  # known end point, if any
    exclusion_zones: tuple[tuple[LonLat, ...], ...] = ()  # closed polygons the march may not enter
    n_routes: int = 3


@dataclass(frozen=True)
class OverspillRequest(_Serialisable):
    context: MarchContext
    route_segment_ids: tuple[str, ...]            # ordered; from snap_route(), a RouteOption or a HistoricalEvent
    police_officers: Optional[int] = None         # None = no police effect applied


# ---------- shared output pieces ----------

@dataclass
class TurnoutEstimate(_Serialisable):
    expected: int
    low: int
    high: int
    source: Literal["user", "model", "mock"]


@dataclass
class Driver(_Serialisable):
    """One explanatory factor, for the UI's 'why' panel."""
    name: str                  # short label, e.g. "Pull towards Whitehall"
    value: Union[float, str]   # the input value, e.g. 0.82 or "rain"
    effect: float              # signed contribution; positive pushes the prediction up
    description: str           # one plain-English sentence


@dataclass
class CellValue(_Serialisable):
    cell_id: int
    value: float               # probability or risk in [0, 1]


@dataclass
class SegmentProb(_Serialisable):
    segment_id: str
    p_visit: float
    path: Path


@dataclass
class RouteOption(_Serialisable):
    rank: int                  # 1 = most likely
    probability: float         # probability of this whole route (relative among returned routes)
    segment_ids: list[str]
    path: Path
    length_m: float
    duration_min: float        # walking time of the head of the march
    end_label: Optional[str]   # e.g. "Whitehall (Cenotaph)"


@dataclass
class Destination(_Serialisable):
    name: str
    lonlat: LonLat
    probability: float


# ---------- conditions the model assumed, and what they changed (contract 1.1) ----------

@dataclass
class Effect(_Serialisable):
    """One factor's effect on one output, for the UI's 'conditions & effects' panel."""
    target: Literal["turnout", "route", "rowdiness", "duration"]
    factor: str                # e.g. "Rain", "Media attention"
    value: str                 # the input as shown to users, e.g. "2.4 mm in 4 h", "x1.8 usual views"
    effect: str                # human-readable change, e.g. "x0.90 turnout", "+0.15 rowdiness"
    size: float                # signed size for charts: relative change for turnout/duration, absolute otherwise
    basis: Literal["learned", "assumed", "data"]   # fitted from past marches, hand-set assumption, or measured
    description: str


@dataclass
class MarchConditions(_Serialisable):
    weather_source: str                        # e.g. "Open-Meteo forecast", "Historical average for March", "unavailable"
    temperature_c: Optional[float]
    apparent_temperature_c: Optional[float]
    precipitation_mm: Optional[float]          # over the first 4 hours of the march
    wind_gust_kmh: Optional[float]
    salience_spike: Optional[float]            # last 7 days' daily views / 90-day daily average (1 = usual)
    salience_views_7d: Optional[int]
    salience_as_of: Optional[str]              # date of the latest pageview data used
    salience_articles: list[str]
    weekday: str
    is_weekend: bool
    is_bank_holiday: Optional[bool]
    is_ramadan: bool
    sunset: str                                # "HH:MM"
    daylight_after_start_h: float
    turnout_base: int                          # before the adjustments in `effects`
    turnout_base_source: str
    rowdiness: float                           # 0-1 volatility used for breakaway risk
    effects: list[Effect] = field(default_factory=list)


# ---------- route mode ----------

@dataclass
class RoutePrediction(_Serialisable):
    request: RouteRequest
    turnout: TurnoutEstimate
    segments: list[SegmentProb]          # p_visit >= 0.01, sorted desc, <= 5000
    cells: list[CellValue]               # per hexagon: max p_visit of its segments
    routes: list[RouteOption]            # len <= request.n_routes
    destinations: list[Destination]      # sorted desc, probabilities sum to <= 1
    expected_duration_min: float         # march + rally
    drivers: list[Driver]
    model_version: str
    warnings: list[str] = field(default_factory=list)
    conditions: Optional[MarchConditions] = None   # contract 1.1; None if the predictor doesn't report it


# ---------- overspill mode ----------

@dataclass
class SegmentTiming(_Serialisable):
    segment_id: str
    path: Path
    head_arrival_min: float
    tail_departure_min: float
    peak_density_ppm2: float
    level_of_service: LevelOfService     # Fruin queuing LOS, see section 5 (A7)


@dataclass
class SpillRisk(_Serialisable):
    segment_id: str                      # a side street NOT on the route
    path: Path
    p_spill: float
    kind: SpillKind
    window_start_min: float
    window_end_min: float
    reason: str                          # e.g. "Bottleneck on Whitehall (4.1 people/m²)"


@dataclass
class Hotspot(_Serialisable):
    lonlat: LonLat
    risk: float
    level: RiskLevel
    kind: SpillKind
    label: str


@dataclass
class OverspillPrediction(_Serialisable):
    request: OverspillRequest
    turnout: TurnoutEstimate
    timeline: list[SegmentTiming]        # one per route segment, in route order
    spill: list[SpillRisk]               # sorted desc, <= 500
    cells: list[CellValue]               # per hexagon: max p_spill
    hotspots: list[Hotspot]              # sorted desc, <= 20
    expected_duration_min: float
    drivers: list[Driver]
    model_version: str
    warnings: list[str] = field(default_factory=list)
    conditions: Optional[MarchConditions] = None   # contract 1.1


Prediction = Union[RoutePrediction, OverspillPrediction]


# ---------- decision tools ----------

@dataclass
class PointRisk(_Serialisable):
    lonlat: LonLat
    nearest_segment_id: Optional[str]
    distance_m: Optional[float]          # to that segment
    cell_id: Optional[int]
    p_visit: float                       # 0 for overspill predictions
    p_spill: float                       # 0 for route predictions
    risk: float                          # max(p_visit, p_spill) within 50 m
    level: RiskLevel
    window_start_min: Optional[float]    # when the risk starts, if any
    window_end_min: Optional[float]
    explanation: str


@dataclass
class WarehouseOption(_Serialisable):
    osm_id: str
    name: Optional[str]
    lonlat: LonLat
    distance_m: float                    # network distance from the shop
    p_disruption: float
    capacity_m2: Optional[float]
    utility: float                       # section 5 (A8) formula; higher = better
    path: Path                           # shop -> warehouse


@dataclass
class ShopAdvice(_Serialisable):
    shop: LonLat
    risk: PointRisk
    act_by_min: Optional[float]          # move stock before this time (None = no action needed)
    recommendation: str                  # one plain-English sentence
    warehouses: list[WarehouseOption]    # best first, <= 3


@dataclass
class PolicePost(_Serialisable):
    lonlat: LonLat
    segment_id: str
    officers: int
    expected_spill_reduction: float      # drop in expected spill events at this post


@dataclass
class PoliceAllocation(_Serialisable):
    officers_total: int
    posts: list[PolicePost]              # sorted by officers desc
    expected_spill_before: float         # sum of p_spill over side streets
    expected_spill_after: float


# ---------- reference data and evaluation ----------

@dataclass
class CauseOption(_Serialisable):
    key: str                             # e.g. "palestine"
    label: str                           # e.g. "Palestine"
    n_events: int                        # historical seed events with this cause


@dataclass
class HistoricalEvent(_Serialisable):
    event_id: str
    name: str
    date: str
    start_time: Optional[str]
    cause: Optional[str]
    organiser: Optional[str]
    turnout: Optional[int]               # parsed central estimate, None if not reported
    route_segment_ids: list[str]
    path: Path
    waypoints: list[tuple[str, LonLat]]  # (name, (lon, lat)) in order


@dataclass
class BacktestRow(_Serialisable):
    event_id: str
    model: str                           # "route_model", "shortest_path", "random_walk"
    mean_log_likelihood: float           # per step of the true route
    top1_jaccard: float                  # segment overlap of the top route with the true route
    destination_in_top3: bool


@dataclass
class BacktestResult(_Serialisable):
    rows: list[BacktestRow]
    summary: dict[str, dict[str, float]]  # model -> metric -> mean
    n_events: int
    created_at: str                       # ISO timestamp
