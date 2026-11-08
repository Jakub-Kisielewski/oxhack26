"""Streamlit page: compare held-out routes on a London map with optional what-if."""

from __future__ import annotations

import numpy as np
import pydeck as pdk
import streamlit as st

from src.config import BACKTEST_PATH, DB_PATH
from src.database import mapdata
from src.models.backtest import read_backtest, rollout_path
from src.models.destinations import candidates
from src.models.graph import MarchGraph
from src.models.labels import TrainingEvent
from src.models.types import BacktestResult
from src.ui import map_layers
from src.ui.backtest_display import MODEL_LABELS
from src.ui.backtest_paths import backtest_has_paths, paths_for_event
from src.ui.charts import MODEL_COLORS
from src.ui.resources import get_full_model, get_graph, load_training_events, net_distances_for
from src.ui.route_explain import contribution_breakdown

MODEL_ROUTE_COLORS = {
    "route_model": MODEL_COLORS[0],
    "shortest_path": MODEL_COLORS[1],
    "random_walk": MODEL_COLORS[2],
}
MAP_LABELS = {
    "route_model": "Route model (greedy)",
    "shortest_path": MODEL_LABELS["shortest_path"],
    "random_walk": MODEL_LABELS["random_walk"],
}


def _events_by_id(
    bt: BacktestResult,
    events: tuple[TrainingEvent, ...],
) -> dict[str, TrainingEvent]:
    ids = {r.event_id for r in bt.rows}
    return {e.event_id: e for e in events if e.event_id in ids}


def _event_ids(bt: BacktestResult) -> list[str]:
    if bt.actual_routes:
        return sorted(bt.actual_routes)
    return sorted({r.event_id for r in bt.rows})


def _prior_before(events: list[TrainingEvent], ev: TrainingEvent) -> list[TrainingEvent]:
    return [e for e in events if e.date < ev.date]


def _sync_event_state(ev: TrainingEvent, bt: BacktestResult) -> None:
    end = (bt.chosen_ends or {}).get(ev.event_id, ev.destination)
    st.session_state["map_start"] = ev.route[0]
    st.session_state["map_cause"] = ev.cause or ""
    st.session_state["map_end_lon"] = float(end[0])
    st.session_state["map_end_lat"] = float(end[1])
    st.session_state["what_if_active"] = False
    st.session_state.pop("what_if_path", None)


def _inputs_dirty(ev: TrainingEvent, bt: BacktestResult) -> bool:
    end = (bt.chosen_ends or {}).get(ev.event_id, ev.destination)
    if st.session_state.get("map_start") != ev.route[0]:
        return True
    if (st.session_state.get("map_cause") or "") != (ev.cause or ""):
        return True
    lon = st.session_state.get("map_end_lon")
    lat = st.session_state.get("map_end_lat")
    return abs(float(lon) - float(end[0])) > 1e-6 or abs(float(lat) - float(end[1])) > 1e-6


def _greedy_rollout(
    start: str,
    chosen_end: tuple[float, float],
    context: dict,
    targets: list,
) -> list[str]:
    g = get_graph()
    model = get_full_model()
    net_dist = net_distances_for(chosen_end[0], chosen_end[1])

    def pick(cur: str, options: list[str]) -> str:
        probs = model.probs(g, cur, options, chosen_end, context, None, targets, net_dist=net_dist)
        return options[int(np.argmax(probs))]

    return rollout_path(g, start, chosen_end, pick, 500, net_dist)


def _dest_index(dest_opts: list, default_end: tuple[float, float]) -> int:
    for i, d in enumerate(dest_opts):
        if abs(d.lonlat[0] - default_end[0]) < 1e-4 and abs(d.lonlat[1] - default_end[1]) < 1e-4:
            return i
    return 0


def _sidebar(
    bt: BacktestResult,
    events: list[TrainingEvent],
    by_id: dict[str, TrainingEvent],
    event_ids: list[str],
) -> tuple[str, TrainingEvent | None, bool, bool, bool, bool, bool, bool, str]:
    """Return event id, labels event, layer toggles, and cause string."""
    event_id = st.selectbox("Event", event_ids, key="map_event")
    ev = by_id.get(event_id)
    if ev and st.session_state.get("_map_event_loaded") != event_id:
        _sync_event_state(ev, bt)
        st.session_state["_map_event_loaded"] = event_id

    st.subheader("Show")
    show_actual = st.checkbox("Actual route", value=True)
    show_route = st.checkbox(MAP_LABELS["route_model"], value=True)
    show_sp = st.checkbox(MAP_LABELS["shortest_path"], value=True)
    show_rw = st.checkbox(MAP_LABELS["random_walk"], value=True)
    show_boundary = st.checkbox("Zones 1-2 boundary", value=False)
    show_zones = st.checkbox("Restricted zones", value=False)

    st.divider()
    st.subheader("What-if")
    causes = sorted({e.cause or "" for e in events}) or [""]
    cause = st.selectbox("Cause", causes, key="map_cause")
    prior = _prior_before(events, ev) if ev else []
    dest_opts = candidates(cause or None, prior) if ev else []
    if dest_opts:
        names = [d.name for d in dest_opts]
        default_end = (st.session_state["map_end_lon"], st.session_state["map_end_lat"])
        dest_choice = st.selectbox(
            "Destination",
            names,
            index=_dest_index(dest_opts, default_end),
            key="map_dest_choice",
        )
        chosen_end = dest_opts[names.index(dest_choice)].lonlat
        st.session_state["map_end_lon"] = float(chosen_end[0])
        st.session_state["map_end_lat"] = float(chosen_end[1])

    st.text_input("Start segment", key="map_start")
    if ev:
        st.caption(
            f"Context (read-only): turnout {ev.context.get('turnout', '—')}, "
            f"precip {ev.context.get('precip_mm_4h', 0):.1f} mm, "
            f"dark {ev.context.get('dark_fraction', 0):.2f}"
        )

    if ev and _inputs_dirty(ev, bt):
        st.session_state["what_if_active"] = True

    if st.button("Recompute route", type="primary"):
        if not ev:
            st.error("Select an event with training labels in DuckDB.")
        else:
            targets = mapdata.cause_targets(cause or None)
            end = (st.session_state["map_end_lon"], st.session_state["map_end_lat"])
            path = _greedy_rollout(st.session_state["map_start"], end, dict(ev.context), targets)
            st.session_state["what_if_path"] = path
            st.session_state["what_if_active"] = True

    return event_id, ev, show_actual, show_route, show_sp, show_rw, show_boundary, show_zones, cause


def _context_layers(show_boundary: bool, show_zones: bool) -> list[pdk.Layer]:
    layers: list[pdk.Layer] = []
    if not DB_PATH.is_file():
        st.sidebar.caption("DuckDB not found; boundary and zones omitted.")
        return layers
    try:
        if show_boundary:
            layers.extend(
                map_layers.polygon_layers_from_rings(
                    mapdata.boundary(), [100, 149, 237, 120], filled=False
                )
            )
        if show_zones:
            zones = mapdata.legal_zones()
            if zones:
                poly = [z["polygon"] for z in zones]
                layers.extend(
                    map_layers.polygon_layers_from_rings(poly, [220, 80, 80, 60], filled=True)
                )
    except OSError:
        st.sidebar.warning("Could not load map context from DuckDB.")
    return layers


def _route_layers(
    g: MarchGraph,
    bt: BacktestResult,
    event_id: str,
    what_if: bool,
    show_actual: bool,
    show_route: bool,
    show_sp: bool,
    show_rw: bool,
) -> tuple[list[pdk.Layer], list, bool]:
    layers: list[pdk.Layer] = []
    fit_coords: list = []
    fragmented = False
    paths = paths_for_event(bt, event_id)
    actual = (bt.actual_routes or {}).get(event_id, [])

    def add_route(ids: list[str], color: str, width: int, name: str) -> None:
        nonlocal fragmented
        if len(g.geometry_runs(ids)) > 1:
            fragmented = True
        fit_coords.extend(map_layers.coords_for_fit(g, ids))
        layers.extend(map_layers.path_layers_for_segments(g, ids, color, width, name))

    if what_if:
        wpath = st.session_state.get("what_if_path")
        if wpath:
            add_route(wpath, MODEL_COLORS[0], 5, "What-if route")
        return layers, fit_coords, fragmented

    if show_actual and actual:
        add_route(actual, "#000000", 7, "Actual")
    for model, visible in (
        ("route_model", show_route),
        ("shortest_path", show_sp),
        ("random_walk", show_rw),
    ):
        if visible and model in paths:
            add_route(paths[model], MODEL_ROUTE_COLORS[model], 4, MAP_LABELS[model])
    return layers, fit_coords, fragmented


def _junction_explainer(
    what_if: bool,
    ev: TrainingEvent | None,
    g: MarchGraph,
    cause: str,
) -> None:
    wpath = st.session_state.get("what_if_path")
    if not (what_if and wpath and len(wpath) > 1 and ev):
        return
    chosen_end = (st.session_state["map_end_lon"], st.session_state["map_end_lat"])
    with st.expander("Why this turn?"):
        step = st.slider("Junction step", 0, len(wpath) - 2, 0)
        cur, nxt = wpath[step], wpath[step + 1]
        model = get_full_model()
        net_dist = net_distances_for(float(chosen_end[0]), float(chosen_end[1]))
        expl = model.explain_turn(
            g,
            cur,
            g.next_ids(cur),
            chosen_end,
            ev.context,
            None,
            mapdata.cause_targets(cause or None),
            net_dist=net_dist,
        )
        expl["prior_only"] = model.stats.get("prior_only", [])
        table = contribution_breakdown(expl, nxt)
        if table:
            st.dataframe(table, width="stretch")
        else:
            st.caption("No alternative at this junction.")


def _map_view(fit_coords: list, g: MarchGraph) -> pdk.ViewState:
    view = map_layers.view_state_for_coords(fit_coords)
    if view is None and fit_coords:
        span = max(
            max(c[0] for c in fit_coords) - min(c[0] for c in fit_coords),
            max(c[1] for c in fit_coords) - min(c[1] for c in fit_coords),
        )
        if span > map_layers.MAX_ROUTE_SPAN_DEG:
            st.error(
                "Route coordinates span an implausible area (graph/backtest mismatch). "
                "Rebuild the graph and backtest, then reload this page."
            )
    return view if view is not None else map_layers.initial_view_state(g)


def render() -> None:
    """Draw the route comparison map."""
    st.title("Route comparison")
    bt = read_backtest(BACKTEST_PATH)
    if bt is None:
        st.warning(
            "No backtest file at `data/models/backtest.json`. "
            "Run `python -m src.models.train` first."
        )
        return
    if not backtest_has_paths(bt):
        st.warning(
            "This backtest file has no persisted paths. Re-run training "
            "(`python -m src.models.train`)."
        )
        return

    events = list(load_training_events())
    by_id = _events_by_id(bt, tuple(events))
    event_ids = _event_ids(bt)
    if not event_ids:
        st.warning("No evaluated events in the backtest file.")
        return

    g = get_graph()
    if "map_event" not in st.session_state:
        st.session_state["map_event"] = event_ids[0]

    with st.sidebar:
        sidebar = _sidebar(bt, events, by_id, event_ids)
        (
            event_id,
            ev,
            show_actual,
            show_route,
            show_sp,
            show_rw,
            show_boundary,
            show_zones,
            cause,
        ) = sidebar

    what_if = st.session_state.get("what_if_active", False)
    if what_if:
        st.info("What-if: full-data model, not a held-out prediction.")
    else:
        st.success("Held-out prediction: this model never saw this march.")

    route_layers, fit_coords, fragmented = _route_layers(
        g, bt, event_id, what_if, show_actual, show_route, show_sp, show_rw
    )
    if fragmented:
        st.warning(
            "Some path segments are missing from the loaded street graph; "
            "routes are drawn as separate pieces (no chords across gaps). "
            "Re-run `python -m src.models.train --force-graph` if this persists."
        )
    layers = _context_layers(show_boundary, show_zones) + route_layers
    st.pydeck_chart(
        pdk.Deck(
            layers=layers,
            initial_view_state=_map_view(fit_coords, g),
            map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
        ),
        height=480,
        width="stretch",
    )

    rows = [r for r in bt.rows if r.event_id == event_id]
    if rows:
        st.dataframe(
            [
                {
                    "model": MAP_LABELS.get(r.model, r.model),
                    "mean_log_likelihood": r.mean_log_likelihood,
                    "top1_jaccard": r.top1_jaccard,
                }
                for r in rows
            ],
            width="stretch",
            column_config={
                "mean_log_likelihood": st.column_config.NumberColumn(format="%.2f"),
                "top1_jaccard": st.column_config.NumberColumn(format="%.0f%%"),
            },
        )

    _junction_explainer(what_if, ev, g, cause)


render()
