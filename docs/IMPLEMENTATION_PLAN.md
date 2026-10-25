# Implementation plan: model layer and visual layer

This plan lets two people (each with their own AI assistant) build the **model layer** and the **visual layer** at the same time, on top of the existing data layer, without blocking each other. The two layers meet at one place only: the **contract** in `src/contract/`. It's defined completely in section 3.

**How to use this document**
- Both of you: give your AI **sections 1–4 and 7–9** (shared context, the contract, rules), plus **your own track**: section 5 (model) or section 6 (visual).
- Phase 0 (section 4) is done **once, by one person, before the tracks split**. Both tracks then start from that commit.
- Where this plan gives exact code (section 3), use it as written. Where it gives a specification, the AI decides the implementation details.

---

## 1. Context: what already exists

**Project.** London Protest Predictor (HRT track: "best use of data for predictions and decision making"). It works in two modes:
- **Route mode:** given a start point, date and cause, predict where a march will go (street-level probabilities, top routes, likely destination).
- **Overspill mode:** given a planned route, predict crowd density, timing, and where the crowd spills into side streets.

Both modes feed two decision tools: **shopkeeper advice** (risk at my shop, and when and where to move stock) and **police allocation** (where to put a limited number of officers).

**Data layer: done.** `python ingest.py` downloads everything and loads it into `data/protest.duckdb` (DuckDB 1.5.5 with the spatial extension). Geometry is lon/lat, EPSG:4326. Use the `meters(a, b)` SQL macro for distances. Don't use `ST_Distance_Sphere`: it expects lat/lon axis order and gives wrong answers on our data.

Tables the model and UI will use:

| Table | Key columns |
|---|---|
| `segments` (≈308k directed street segments, walk network) | `segment_id` ("u:v:key"), `u`, `v`, `key`, `length_m`, `road_class`, `street_name`, `geom` (LineString), `n_published_route_examples`, `width_m`, `width_source`, `area_m2`, `capacity_people` (at 2 people/m²), `betweenness_main`, `betweenness_walk`, `from_degree`, `to_degree`, `is_main`, `is_bridge`, `is_tunnel`, `in_no_entry_zone`, `in_restricted_zone`, `in_royal_park` |
| `main_edges` | the main-road network (lanes, width tags) |
| `grid_cells` / `grid_adjacency` / `segment_cells` | ~200 m hexagons `cell_id`, `lat`, `lon`, `geometry`; neighbour pairs; `segment_id` → `cell_id` with `is_midpoint_cell` |
| `events` (65) | `event_id`, `event_date`, `event_name`, `event_category`, `start_time`, `end_time`, `route_detail`, `organiser`, `motivation`, `turnout` (text like `"50000±30000"` or `not_reported`) |
| `event_context` (65) | `event_id`, `cause`, calendar/daylight/weather/salience features (`is_weekend`, `daylight_after_start_h`, `precip_mm_4h`, `apparent_temp_mean_c`, `salience_spike_ratio`, …) |
| `waypoints` (285) | `event_id`, `sequence_index`, `waypoint_name`, `latitude`, `longitude`, `geom` (reviewed geocodes) |
| `route_segments` (7,216) | `event_id`, `segment_id`, `sequence_index`: training routes, **interpolated by shortest path between waypoints** (planned routes, not GPS traces) |
| `cause_targets` (21) | `cause` (`any` = all causes), `target_name`, `kind`, `iso2`, `lat`, `lon`, `weight` (prior), `seed_route_hit_rate`, `geom` |
| `targets` | OSM protest targets: `category` (diplomatic, government, political_party, townhall, court, memorial, attraction), `country` (ISO2 for embassies), `name`, `lat`, `lon`, `geometry` |
| `open_spaces` | squares/parks: `kind`, `royal_park`, `capacity_area_m2`, `geometry` |
| `shops` (19k), `warehouses` (630) | `osm_id`, `name`, `shop`, `lat`, `lon`, `geometry`; warehouses have `footprint_m2` |
| `legal_zones` | `zone_id`, `name`, `rule_type` (`no_entry`, `restricted_activity`, `royal_park`), `geom` |
| `weather_hourly`, `pageviews_daily`, `crimes`, `tfl_disruptions`, `protest_signals` | context; `protest_signals` = latest live crawler run |

Causes currently derived (`event_context.cause`): `palestine` (26 events), `iran` (9), `anti_racism`, `far_right`, `ethiopia`, `animal_rights`, `lgbtq`, `anti_trump`, `climate_nature`, `trade_union`, `digital_id`, `sudan`, `armenia`, `kashmir`, `ukraine`, `trans_rights`, plus 9 events with no cause (religious/community processions).

**Existing UI.** `app.py` (Streamlit navigation), `src/ui/common.py` (`get_db()` read-only connection), `src/ui/home.py` (placeholder dashboard plus a "Data status" table), `src/ui/map_view.py` (Folium placeholder map). Dependencies already include `streamlit`, `pydeck`, `folium`, `streamlit-folium`, `networkx`, `osmnx`, `geopandas`, `scikit-learn`, `numpy`, `pandas`.

**Design decisions already made (don't revisit):**
- The street graph is the main representation; hexagons are for display and aggregation only.
- Route model = **supervised step-by-step choice model** (a Markov chain on the street graph; conditional logit at each junction), fitted by maximum likelihood on the real routes. **No synthetic training data.**
- Predictions are **probabilities**, never just the argmax. Street visit probabilities are computed exactly from the absorbing chain (sparse solve of `(I − Q)`). The "most likely route" comes from shortest path on `−log p`, and top-k routes from Yen's algorithm.
- Overspill is **physics-based** (density against capacity, timing from march speed) plus a hand-set breakaway score. There are no overspill labels, so its coefficients are set by hand and documented.
- **Police numbers are a decision variable** (optimised), never a predictive feature.
- Validation: hold out one event at a time (or split by date); baseline = shortest path.

---

## 2. Architecture, ownership and rules

```
data/protest.duckdb (read-only at runtime)
        │
        ├──► src/models/  (Track A)  ── implements ──► src/contract/api.py: Predictor
        │        writes artefacts to data/models/
        │
        └──► src/contract/mapdata.py (shared, read-only map/base data)
                                   │
src/ui/ + app.py (Track B) ──► src.contract.get_predictor()  +  src.contract.mapdata
```

**Directory ownership**

| Path | Owner | Notes |
|---|---|---|
| `src/contract/` | **Shared, frozen after Phase 0** | Changes follow the rules in section 3.8 |
| `src/models/`, `data/models/` | Track A (model) | |
| `src/ui/`, `app.py`, `.streamlit/` | Track B (visual) | |
| `ingest.py`, `src/ingestion/`, `src/database/` | Neither, unless agreed | Data layer is done. Track A may add **one** `train` step to `ingest.py` (section 5, A10) |
| `requirements.txt` | Both, **append-only** | Add a line, never change existing pins |
| `README.md` | Both, each edits only its own section | |
| `docs/IMPLEMENTATION_PLAN.md` | Shared | Update when the contract changes |

**Hard rules (put these in both AIs' instructions)**
1. `src/models/` **never imports `streamlit`** or anything from `src/ui/`.
2. `src/ui/` **never imports from `src/models/`**. It only uses `src.contract.get_predictor()`, `src.contract.types`, `src.contract.errors` and `src.contract.mapdata`.
3. All runtime database access goes through `src.contract.mapdata.cursor()`, which uses one shared **read-only** connection. DuckDB refuses a second connection to the same file with a different configuration, and Streamlit already holds one open.
4. Coordinates crossing the contract are **`(lon, lat)` tuples** (pydeck order). Folium uses `[lat, lon]`, so the UI converts at the Folium boundary only.
5. Run `python -m src.contract.selftest` before every push; it must pass. It's the sync guarantee between the tracks.
6. Note that `.gitignore` excludes `tests/` and `test_*.py`. Put any tests you want committed under `src/` (e.g. `src/models/checks.py`, `src/contract/selftest.py`).
7. Work on branches (`model/...`, `ui/...`) and merge into `main` often, at least at each checkpoint in section 7. Merge, never force-push, `main`.

---

## 3. The contract (`src/contract/`)

Five files. `types.py`, `api.py`, `errors.py` and `__init__.py` are given **exactly**. `mapdata.py`, `mock.py` and `selftest.py` are specified precisely below.

### 3.1 Conventions
- **Coordinates:** `LonLat = (lon, lat)` floats, EPSG:4326. A polyline `Path` is a list of `LonLat`.
- **IDs:** `segment_id` is the string `"u:v:key"` from `segments`; `cell_id` is an int from `grid_cells`.
- **Times:** the march context has `date` `"YYYY-MM-DD"` and `start_time` `"HH:MM"` (Europe/London). Every time inside a prediction is **minutes after the march start** (float). The UI converts to clock time for display.
- **Units:** metres, minutes, people, people/m².
- **Probabilities:** floats in `[0, 1]`.
- **Lists are sorted:** `segments` by `p_visit` desc; `spill` by `p_spill` desc; `routes` by `rank`; `hotspots` by `risk` desc.
- **Size limits** (to keep the UI fast): `RoutePrediction.segments` only includes `p_visit ≥ 0.01`, at most 5,000 items. `spill` at most 500 items, `hotspots` at most 20.
- **Risk levels** come from one shared function, `risk_level(p)`: `< 0.1` low, `< 0.3` medium, `< 0.6` high, else severe.

### 3.2 `src/contract/types.py` (exact)

```python
"""Data types shared by the model layer (src/models) and the visual layer (src/ui).

Coordinates are (lon, lat) in EPSG:4326. Times inside predictions are minutes after
the march start. Distances in metres. Probabilities in [0, 1].
All fields are JSON-friendly; use `to_dict()` for caching/serialising.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal, Optional, Union

CONTRACT_VERSION = "1.0.0"

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
```

### 3.3 `src/contract/api.py` (exact)

```python
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
```

Performance budget (warm, on a laptop): `predict_route` ≤ 3 s, `predict_overspill` ≤ 3 s, `snap_route` ≤ 1 s, `point_risk` ≤ 100 ms, `shop_advice` ≤ 1 s, `allocate_police` ≤ 1 s. Loading the real predictor (graph and parameters) may take up to 30 s once per process.

### 3.4 `src/contract/errors.py` (exact)

```python
class PredictionError(Exception):
    """Invalid or unusable input. `user_message` is shown to the user as-is."""

    def __init__(self, user_message: str):
        super().__init__(user_message)
        self.user_message = user_message
```

### 3.5 `src/contract/__init__.py` (exact)

```python
"""Single entry point for the visual layer: `from src.contract import get_predictor`.

PREDICTOR environment variable: "mock", "real", or "auto" (default). "auto" uses the
real model when its artefacts exist (src.models.predictor.RealPredictor.available()),
otherwise the mock.
"""
from __future__ import annotations

import os

from src.contract.api import Predictor
from src.contract.types import CONTRACT_VERSION


def get_predictor() -> Predictor:
    choice = os.environ.get("PREDICTOR", "auto").lower()
    if choice in ("real", "auto"):
        try:
            from src.models.predictor import RealPredictor
            if choice == "real" or RealPredictor.available():
                return RealPredictor()
        except ImportError:
            if choice == "real":
                raise
    from src.contract.mock import MockPredictor
    return MockPredictor()


__all__ = ["get_predictor", "Predictor", "CONTRACT_VERSION"]
```

### 3.6 `src/contract/mapdata.py` (specified)

Read-only access to base data for **both** tracks. Every function returns contract types or plain dicts/lists in `(lon, lat)` order. Paths are parsed from `ST_AsGeoJSON(geom)`.

| Function | Returns | Source |
|---|---|---|
| `connection()` | one cached `duckdb` connection, `read_only=True`, via `src.database.db.get_connection` | `functools.lru_cache` (not `st.cache_resource`, since models can't import streamlit) |
| `cursor()` | `connection().cursor()`. Use one per call/thread | |
| `list_causes() -> list[CauseOption]` | distinct `event_context.cause` (non-empty) with counts, plus causes only in `cause_targets` (n_events 0), sorted by `n_events` desc. Label = key with `_` → space, title case | `event_context`, `cause_targets` |
| `historical_events(protests_only=True) -> list[HistoricalEvent]` | events with ≥ 2 `route_segments`; `turnout` parsed: first integer in the text, `None` for `not_reported`; path = concatenated segment paths in `sequence_index` order | `events`, `event_context`, `route_segments`, `segments`, `waypoints` |
| `segment_paths(ids: list[str]) -> dict[str, Path]` | geometry per segment id (batch query) | `segments` |
| `boundary() -> list[Path]` | outer ring(s) of the zones 1–2 polygon | `boundary` |
| `legal_zones() -> list[dict]` | `{zone_id, name, rule_type, polygon: Path}` | `legal_zones` |
| `targets(categories: Optional[list[str]] = None) -> list[dict]` | `{name, category, country, lonlat}` | `targets` |
| `cause_targets(cause: Optional[str]) -> list[dict]` | rows for `cause` plus `any`: `{target_name, kind, lonlat, weight}` | `cause_targets` |
| `shops_near(lonlat, radius_m=300, limit=50) -> list[dict]` | `{osm_id, name, shop, lonlat, distance_m}` nearest first | `shops` |
| `search_shops(text, limit=20) -> list[dict]` | case-insensitive name match | `shops` |
| `warehouses() -> list[dict]` | `{osm_id, name, lonlat, footprint_m2}` | `warehouses` |
| `cells(ids: Optional[list[int]] = None) -> list[dict]` | `{cell_id, lonlat (centroid), polygon: Path}` | `grid_cells` |
| `assembly_points() -> list[dict]` | first waypoint of each historical event, grouped by name: `{name, lonlat, n_events}` | `waypoints` |
| `in_boundary(lonlat) -> bool` | point-in-polygon | `boundary` |

### 3.7 `src/contract/mock.py` (specified)

`MockPredictor` implements `Predictor` with `name = "mock"` and `version = "mock-1"`. It must:
- return **real `segment_id`s and real geometry** from `segments`, so the UI renders exactly what the real model will produce;
- be **deterministic** (seed a `random.Random` with a hash of `request.to_dict()`);
- run in ≤ 1 s and need **no files under `data/models/`**;
- add the warning `"Mock predictor: outputs are illustrative, not model predictions."` to every prediction.

Behaviour:
- `predict_route`: pick the end point (`req.end`, else the highest-weight `mapdata.cause_targets(cause)` target). Select `segments` whose midpoint is within 150 m of the straight line from start to end (pre-filter with a bounding box). Give each `p_visit = 0.9 · exp(−(distance from line / 60 m)²)`, keep ≥ 0.01, and order route 1 by projection along the line. Return 3 routes: route 1 from those segments, and routes 2–3 from lines bent ±300 m through a midpoint, with probabilities 0.6/0.25/0.15. Also fill `cells` (max per `segment_cells` midpoint cell), 3 `destinations` from `cause_targets`, turnout = `context.turnout` or 20,000 (`source="mock"`), duration = length / 42 m/min + 60, and 3 sample `drivers`.
- `snap_route`: for consecutive point pairs, segments within 60 m of the connecting line, ordered along it.
- `predict_overspill`: timeline with head = cumulative length / 42 m/min, tail = head + 45, density = `turnout / (crowd_length · width_m)` clamped to 0.5–6, and LOS from the Fruin table in section 5 (A7). Spill = segments sharing a `u`/`v` node with the route but not on it, with `p_spill` = 0.6 × (density / 6) × random(0.5–1), `kind` "pressure" (or "breakaway" if within 150 m of a `targets` row), and window = [head, tail + 30]. Top 10 as hotspots.
- `point_risk`: nearest segment in the prediction within 50 m, otherwise zeros. `shop_advice`: `point_risk` at the shop, `act_by_min = window_start − 60`, and the 3 nearest `warehouses` with a straight-line path. `allocate_police`: distribute officers in units of 10 over the top-risk spill segments in proportion to `p_spill`, with `expected_spill_after = before · 0.7`.
- `backtest`: return a fixed sample `BacktestResult` with 3 events × 3 models.

### 3.8 `src/contract/selftest.py` (specified)

`python -m src.contract.selftest [--predictor mock|real|both]` (default `both` when the real one is available). For each predictor it runs every method with:
- a fixed route request (start `(-0.1586, 51.5136)` Marble Arch, date `2026-03-21`, cause `palestine`);
- an overspill request built from the first `HistoricalEvent`;
- `point_risk`/`shop_advice` at `(-0.1281, 51.5080)`;
- `allocate_police(…, 100)`.

It **asserts the invariants**:
- every return type is the declared dataclass;
- all probabilities are in [0, 1];
- every `LonLat` lies inside lon −0.6…0.4, lat 51.2…51.8 (this catches swapped axes);
- lists are sorted and within the size limits in 3.1;
- every `segment_id` exists in `segments`;
- `timeline` length equals the route length, and `head_arrival_min ≤ tail_departure_min`;
- `to_dict()` is JSON-serialisable;
- the timing budgets in 3.3, as warnings rather than failures.

Exit code 1 on any failure.

### 3.9 Shared Streamlit session-state keys (visual track; listed here so pages agree)

| Key | Type | Set by |
|---|---|---|
| `"ctx"` | `MarchContext` | context form (shared widget) |
| `"route_request"` / `"route_prediction"` | `RouteRequest` / `RoutePrediction` | Route predictor page |
| `"overspill_request"` / `"overspill_prediction"` | `OverspillRequest` / `OverspillPrediction` | Planned route page, or "Send top route to overspill" |
| `"selected_event_id"` | `str` | any page that picks a historical event |

### 3.10 Changing the contract
- **Additive changes** (new optional field with a default, new mapdata function, new method with a default in the mock): either track may make them. Bump the minor version (`1.1.0`), update this document, and tell the other person.
- **Breaking changes** (rename/remove/retype): both people agree first, then bump the major version and update the mock, the real predictor and the UI in the same merge.
- `selftest` must pass on `main` at all times.

---

## 4. Phase 0: shared setup (one person, about 1 hour, before splitting)

1. Create `src/contract/` with the 5 exact files (3.2–3.5) plus `mapdata.py`, `mock.py` and `selftest.py` implementing 3.6–3.8.
2. Add `scipy>=1.11` to `requirements.txt`. It's already pulled in by scikit-learn, but list it explicitly.
3. Point `src/ui/common.py:get_db()` at `src.contract.mapdata.connection()` so the app has only one connection.
4. Run `python -m src.contract.selftest --predictor mock` against the real `data/protest.duckdb`. It must pass.
5. Commit to `main` as "Add model/UI contract and mock predictor". Both tracks branch from this commit.

---

## 5. Track A: model layer (`src/models/`)

Goal: `RealPredictor` implementing `Predictor`, with trained artefacts in `data/models/`, plus a backtest that shows the model beating the shortest-path baseline.

**Files**

| File | Purpose |
|---|---|
| `graph.py` | builds the march graph from DuckDB; caches it to `data/models/graph.pkl` |
| `labels.py` | training routes and choice observations from `waypoints` |
| `features.py` | edge and choice features (A3) |
| `route_model.py` | conditional logit: fit/predict, parameters to and from JSON |
| `destinations.py` | destination prior per cause |
| `inference.py` | visit probabilities, top-k routes, cells |
| `turnout.py` | turnout estimate |
| `overspill.py` | timing, density, LOS, spill |
| `decisions.py` | shop advice, warehouses, police allocation |
| `backtest.py` | leave-one-event-out evaluation; writes `data/models/backtest.json` |
| `train.py` | `python -m src.models.train` runs everything and writes artefacts |
| `predictor.py` | `RealPredictor` (loads artefacts, implements the contract) |
| `checks.py` | sanity checks runnable as `python -m src.models.checks` |

**A1. March graph** (`graph.py`)
- States are **directed segments**. Use segments with `road_class` in {trunk, primary, secondary, tertiary, their `_link`s, unclassified, residential, living_street, pedestrian} plus any segment used by a training route. Drop segments with `in_no_entry_zone`. Keep the largest strongly connected component.
- Transitions: segment `a = (u→v)` → segment `b = (v→w)`, excluding the U-turn `w = u`.
- Store per segment: length, width, betweenness, degree, flags, midpoint and end-node coordinates, and the bearing at each end (for turn angles).
- Cache with pickle. Target ≤ 10 s to load.

**A2. Training labels** (`labels.py`)
- For each protest event with ≥ 2 waypoints, snap the waypoints (from the `waypoints` table) to the march graph and connect them by shortest path on it. This gives each event an ordered segment sequence (planned route, interpolated).
- Each step on the path is one **choice observation**: (current segment, the candidate next segments, the chosen one, event context).
- **Weight observations:** choices within 150 m of a waypoint get weight 1. Interpolated choices get weight 0.3 (configurable), because between waypoints the path is a shortest path, not a human decision. Report the number of observations per event.

**A3. Features** (`features.py`). Keep it to about 10 parameters (65 events). For candidate next segment `b`, given the current segment `a`, context `c` and destination `d`:
1. `progress`: reduction in straight-line distance to `d` (km) from moving along `b`. This drives movement towards the destination.
2. `log_width`: `log(width_m)`.
3. `turnout_x_width`: `log(turnout) · log(width_m)` (big crowds prefer wide roads).
4. `is_main`.
5. `log_betweenness`: `log1p(betweenness_main or betweenness_walk, scaled)`.
6. `turn`: |turn angle| / 180.
7. `target_pull`: `Σ_targets weight · exp(−dist(b_end, target)/200 m)` over `mapdata.cause_targets(cause)` (includes `any`).
8. `royal_park` and `restricted` flags.
9. `history`: `log1p(n_published_route_examples)`, recomputed **from training events only** (in the backtest, exclude the held-out event).
10. `rain_x_main`: `precip_mm_4h > 0.5` × `is_main`.

Context-only variables (weather, cause, organiser) cancel out in a conditional logit unless they're **interacted with a segment feature**. That's why turnout, rain and cause enter through 3, 10 and 7. Standardise features using training statistics.

**A4. Route model** (`route_model.py`)
- `P(b | a) = softmax_b(θ · x(a, b, c, d))` over the candidate next segments.
- Fit by weighted maximum likelihood with L2 regularisation (`scipy.optimize.minimize`, L-BFGS-B) towards prior signs (progress +, width +, turn −).
- Save θ, feature means/standard deviations and the feature names to `data/models/route_model.json`.
- Expose `transition_matrix(subgraph, context, destination) -> scipy.sparse.csr_matrix`.

**A5. Destinations** (`destinations.py`)
- Candidate destinations: the `cause_targets` rows for the cause plus `any`, and historical final waypoints clustered within 150 m.
- `P(d | cause)` ∝ prior weight × (1 + count of training events of that cause ending within 250 m), normalised. Unknown cause uses the `any` rows and all historical end points.
- If `req.end` is given, use that single destination.

**A6. Inference** (`inference.py`)
- For each destination with `P ≥ 0.05` (at most 5): take the subgraph inside an ellipse with foci at start and destination, major axis = 1.6 × distance + 500 m. Make segments within 75 m of `d` absorbing. Build `Q` (the transient-to-transient transitions) and solve `(I − Q)ᵀ x = e_start` (`scipy.sparse.linalg.spsolve`) to get expected visits.
- Mix over destinations by `P(d)`. `p_visit` is the expected visits clipped to 1.
- Remove segments inside `req.exclusion_zones` before building `Q`.
- Top-k routes: Yen's algorithm (`networkx.shortest_simple_paths`) on cost `−log P(b|a)` to the most likely destinations, giving `RouteOption`s with relative probabilities.
- `cells`: max `p_visit` per `segment_cells` midpoint cell.
- `expected_duration_min` = top route length / 42 m/min + rally time (60 min, or a duration model if time allows).
- `drivers`: the top contributions `θ_k · x̄_k` along route 1, with plain-English descriptions.

**A7. Overspill** (`overspill.py`): physics plus hand-set coefficients, all documented as module-level constants.
- **Speed:** head moves at 42 m/min (2.5 km/h).
- **Crowd length:** `L = turnout / (1.5 people/m² · median route width)`. `head_arrival` = cumulative length / speed. `tail_departure` = head + L / speed.
- **Density per segment** = `1.5 · median_width / width_i`, capped at 6.
- **End point:** compare peak occupancy with the nearest `open_spaces.capacity_area_m2` × 2; overflow becomes pressure risk around the end.
- **LOS (Fruin queuing):** A < 0.83, B < 1.08, C < 1.54, D < 3.3, E < 5.0, F ≥ 5.0 people/m².
- **Pressure spill** for a side street `s` touching route segment `i`: `σ(2.0·(density_i/2 − 1) + 0.5·log(to_degree_s) − 1.0)`.
- **Breakaway spill:** `volatility · Σ_targets weight · exp(−d/150 m)` within 300 m. `volatility` ∈ [0, 1] comes from a table by cause (default 0.2; higher with `counter-protest` in the event name/motivation, start ≥ 17:00, or `salience_spike_ratio` > 2).
- Combine: `p = 1 − (1 − p_pressure)(1 − p_breakaway)`; `kind` = the larger term.
- **Police:** if `police_officers` is set, `p · exp(−η · officers_at_s)` with η = 0.05 per officer, using the allocation from A8.
- Window = [head_arrival_i, tail_departure_i + 30]. Hotspots = the top 20 spill segments.

**A8. Decision tools** (`decisions.py`)
- `point_risk`: nearest predicted segment within 50 m; risk = max(`p_visit`, `p_spill`); window from the timeline or spill entry.
- `shop_advice`: `act_by_min = window_start − 60` if risk ≥ 0.1, otherwise None. Warehouse utility from the original plan: `U(j) = 1/(d_ij + 100) · (1 − P_disruption(j)) · C(j)`, where `d_ij` is the network distance on the walk graph, `P_disruption(j)` is `point_risk` at the warehouse, and `C(j)` is `footprint_m2` normalised to [0, 1] (0.5 if unknown). Return the top 3 with paths.
- `allocate_police`: candidate posts = the spill segments; allocate in units of 5 officers greedily by largest marginal reduction of `Σ p_s · (1 − e^{−η r_s})`. This is optimal for this concave, separable objective.

**A9. Backtest** (`backtest.py`)
- Leave one event out over protest events with ≥ 2 waypoints: refit θ and recompute `history` without the held-out event.
- Metrics: mean log-likelihood per step of the true path, top-1 route Jaccard overlap, and whether the true end is in the top-3 destinations.
- Baselines: `shortest_path` (to the most likely destination) and `random_walk` (uniform over the next segments).
- Write a `BacktestResult` to `data/models/backtest.json`. This is the headline evidence for the pitch.

**A10. Training CLI and predictor**
- `python -m src.models.train` builds the graph, labels, fit, backtest and saves artefacts, printing a summary.
- `RealPredictor.available()` is true when `route_model.json` and `graph.pkl` exist.
- Optionally add a `train` step to `ingest.py` after `database`, with `needs=['database']`.

**Model track checkpoints:** C1 = `RealPredictor.predict_route` returns valid contract objects (even from a crude baseline, e.g. shortest path to the top destination) and `selftest --predictor real` passes. C2 = trained route model plus backtest. C3 = overspill plus decisions.

---

## 6. Track B: visual layer (`src/ui/`, `app.py`)

Goal: a polished Streamlit app that works fully on the mock first, then switches to the real predictor with no code changes.

**Files**

| File | Purpose |
|---|---|
| `src/ui/common.py` | `get_db()` (from mapdata), `get_predictor()` with `@st.cache_resource`, cached prediction wrappers, error display, mock banner |
| `src/ui/context_form.py` | the shared march-context widget (date, start time, cause, organiser, turnout) writing `st.session_state["ctx"]` |
| `src/ui/layers.py` | pydeck layer builders and colour scales (B2) |
| `src/ui/pick_map.py` | Folium click map for picking points (start, end, route waypoints, shop) |
| `src/ui/pages/home.py` | dashboard |
| `src/ui/pages/route_predictor.py` | route mode |
| `src/ui/pages/planned_route.py` | overspill mode |
| `src/ui/pages/shopkeeper.py` | shop advice |
| `src/ui/pages/police.py` | police allocation |
| `src/ui/pages/model_insights.py` | backtest and drivers |
| `src/ui/pages/map_explorer.py` | base data explorer (replaces `map_view.py`) |

**B1. App shell.** Update `app.py` navigation to the pages above. Move the existing `home.py`/`map_view.py` into `src/ui/pages/` and keep the Data status table on the dashboard. Show a top banner on every page when `get_predictor().name == "mock"`. Use a consistent page layout: inputs in the sidebar, map in the main area, details below.

**B2. Map layers** (`layers.py`), all pydeck, `(lon, lat)` order:
- `segment_prob_layer(segments)`: `PathLayer`, width by probability, sequential colour scale.
- `cell_layer(cells, extruded=True)`: `PolygonLayer` from `mapdata.cells`, with height and colour by value. This is the plan's 3D heatmap.
- `routes_layer(routes)`: one `PathLayer` per route, in distinct colours by rank.
- `spill_layer(spill)`: `PathLayer` coloured by `kind` with opacity by `p_spill`.
- `hotspot_layer(hotspots)`: `ScatterplotLayer`.
- `timeline_layer(timeline, t)`: segments occupied at minute `t` (`head ≤ t ≤ tail`), coloured by LOS.
- Base layers: `boundary_layer`, `legal_zones_layer` (no_entry red, restricted amber, royal_park green), `targets_layer`, `shops_layer`, `warehouses_layer`.
- Tooltips on every layer: street name if available, probability, time window, reason.
- A shared legend component. Colour scales must be colour-blind safe and readable in light and dark themes.

**B3. Point picking** (`pick_map.py`). A `streamlit_folium` map returning `last_clicked`, converted to `(lon, lat)`, with a mode selector (start / end / add waypoint / shop) and an "assembly point" dropdown from `mapdata.assembly_points()` as an alternative. Reject points outside `mapdata.in_boundary` with a friendly message.

**B4. Route predictor page**
- Inputs: context form, start (pin or assembly point), optional end, n_routes. A **Predict** button (no automatic rerun on every widget change).
- Calls `predict_route` through a cached wrapper keyed by the request JSON.
- Output map: cell heatmap toggle, segment probabilities, top routes, destinations. Panels: turnout estimate with range, expected duration, top-route table (rank, probability, length, duration, end), drivers bar chart, warnings.
- **Pin drop:** clicking the result map (or entering coordinates) shows `point_risk`.
- Button: "Analyse overspill for route 1", which builds an `OverspillRequest` from `routes[0].segment_ids` and switches to the planned-route page.

**B5. Planned route (overspill) page**
- Route input: (a) choose a historical event (`mapdata.historical_events()`), which fills the route and context, or (b) click waypoints, then `snap_route`, or (c) arrive from B4.
- Optional police officers slider.
- Output: **time slider** (minutes since start, 0 → `expected_duration_min`) animating the occupied segments with LOS colours; spill layer filtered to windows containing `t`; hotspots list; LOS summary (minutes at level E/F); drivers.

**B6. Shopkeeper page**
- Find my shop: search by name (`mapdata.search_shops`) or click (`shops_near`).
- Uses the current route or overspill prediction from session state, or prompts to make one.
- Shows the risk level badge, the time window as clock times, "move stock by HH:MM", and the top-3 warehouses on the map with paths and a utility breakdown.

**B7. Police page.** Officers slider (0–500, step 5) runs `allocate_police` on the current overspill prediction. Map of posts sized by officers, a before/after expected spill metric, and a posts table.

**B8. Model insights page.** Backtest summary chart (model vs shortest-path vs random-walk, per metric), per-event table, and the "drivers" explanation of features. Show a clear empty state when `backtest()` is None.

**B9. Map explorer.** Base layers with toggles: boundary, legal zones, targets by category, cause targets for a chosen cause, shops/warehouses heat, historical routes (select an event to draw its path and waypoints).

**Caching rules:**
- `@st.cache_resource` for `get_predictor()`.
- `@st.cache_data` for predictions keyed by `json.dumps(request.to_dict(), sort_keys=True)`; the wrapper takes that string and rebuilds the request.
- `@st.cache_data` for mapdata calls (static).

**Visual track checkpoints:** C1 = shell, layers and the route predictor page on the mock. C2 = all pages on the mock. C3 = switched to `PREDICTOR=auto` with the real model, plus polish.

---

## 7. Timeline and checkpoints (assumes ~14 working hours left)

| Time | Shared | Track A (model) | Track B (visual) |
|---|---|---|---|
| 0–1 h | **Phase 0** (section 4), merged to `main` | | |
| 1–4 h | **C1 merge**: selftest passes for mock **and** a baseline real predictor | A1, A2, baseline `predict_route` (shortest path to top destination) | B1, B2, B3, B4 on mock |
| 4–9 h | **C2 merge** | A3–A6 trained model, A9 backtest | B5–B8 on mock |
| 9–12 h | **C3 merge**: `PREDICTOR=auto` uses the real model end to end | A7, A8, A10 | Switch to real, fix display issues, B9 |
| 12–14 h | Demo rehearsal, pitch numbers from `backtest.json` | Tuning, drivers text | Polish, screenshots |

At each merge: pull `main`, run `python -m src.contract.selftest`, run the app, and click through every page.

---

## 8. Definition of done and demo script

**Done when:**
1. `python ingest.py && python -m src.models.train && streamlit run app.py` works from a fresh clone (ingest is already done).
2. `python -m src.contract.selftest` passes for both predictors.
3. Every page works on the real model with no mock banner.
4. The backtest shows the route model beating the shortest-path baseline on at least log-likelihood, with the numbers on the dashboard.

**Demo (about 4 minutes):**
1. Route mode: a Palestine march from Marble Arch on a Saturday. Show the probability corridor, the top 3 routes and the destination split, and explain the drivers.
2. Send route 1 to overspill. Move the time slider and show the Whitehall bottleneck turning to LOS F and the side streets lighting up.
3. Shopkeeper: a shop on a side street off the route gets "move stock by 13:10", plus the best warehouse.
4. Police: 200 officers and their placement, cutting expected spill by X%.
5. Model insights: the backtest against shortest path. Close on the data provenance (planned routes, not GPS) and the limits of what the model claims.

---

## 9. Known limitations to keep in mind
- Training routes are **planned** routes with shortest-path interpolation between waypoints, not observed GPS. Say so in the UI and the pitch.
- 65 events (≈56 with a cause): keep the model small, regularise, and report uncertainty.
- Overspill has no ground truth. Its coefficients are hand-set; present them as a physics-based estimate.
- Hand-drawn legal zones and some target coordinates are approximate (`location_source = seed_approx`).
- ACLED is not loaded (no credentials). The data layer handles it if added later.
