"""Streamlit page: compare held-out routes on a London map."""

from __future__ import annotations

import html
import re
from datetime import date, datetime, time

import pydeck as pdk
import pandas as pd
import streamlit as st

from src.config import BACKTEST_PATH, DB_PATH
from src.database import mapdata
from src.database.types import LonLat
from src.models.backtest import read_backtest
from src.models.graph import MarchGraph
from src.models.labels import TrainingEvent
from src.models.types import BacktestResult, BacktestRow
from src.ui import map_layers
from src.ui.backtest_display import MODEL_LABELS
from src.ui.backtest_paths import backtest_has_paths, paths_for_event
from src.ui.layout import page_body, section
from src.ui.map_styles import LAYER_PILL_COLORS, MAP_LAYER_STYLES
from src.ui.resources import get_graph, load_training_events

MAP_LABELS = {
    "route_model": "Route model",
    "shortest_path": MODEL_LABELS["shortest_path"],
    "random_walk": MODEL_LABELS["random_walk"],
}
LAYER_OPTIONS = [
    "Actual",
    "Route model",
    "Shortest path",
    "Random walk",
    "Zone boundary",
    "Restricted zones",
]
DEFAULT_LAYERS = LAYER_OPTIONS[:4]
DECK_TOOLTIP = {"html": "<b>{tooltip}</b>", "style": {"color": "white"}}
_DEBUG_LOG = r"d:\oxhack26\.cursor\debug-9a926a.log"


def _agent_debug_log(hypothesis_id: str, message: str, data: dict, *, run_id: str = "metric-scale") -> None:
    #region agent log
    import json
    import time

    try:
        with open(_DEBUG_LOG, "a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "sessionId": "9a926a",
                        "hypothesisId": hypothesis_id,
                        "location": "route_map.py:_event_header",
                        "message": message,
                        "data": data,
                        "timestamp": int(time.time() * 1000),
                        "runId": run_id,
                    }
                )
                + "\n"
            )
    except OSError:
        pass
    #endregion


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


def _row_metrics(bt: BacktestResult, event_id: str) -> dict[str, BacktestRow]:
    return {r.model: r for r in bt.rows if r.event_id == event_id}


def _historic(event_id: str):
    for he in mapdata.historical_events():
        if he.event_id == event_id:
            return he
    return None


_ORG_PARENS = re.compile(r"\s*\([^)]*\)")


def _short_organisation_name(text: str) -> str:
    """Drop parenthetical acronyms so picker labels fit (e.g. ``(PSC)``)."""
    cleaned = _ORG_PARENS.sub("", text)
    return re.sub(r"\s+", " ", cleaned).strip()


def _organisation_label(event_id: str) -> str:
    he = _historic(event_id)
    if he and he.organiser:
        return _short_organisation_name(he.organiser.strip())
    if he and he.name:
        return _short_organisation_name(he.name.strip())
    return event_id


def _format_clock(value: time | datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, time):
        return value.strftime("%H:%M")
    if isinstance(value, datetime):
        return value.time().strftime("%H:%M")
    text = str(value).strip()
    return text[:5] if len(text) >= 5 else text or None


def _display_date(iso: str) -> str:
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return iso
    return d.strftime("%d %B %Y").lstrip("0")


def _end_time(event_id: str) -> str | None:
    row = mapdata.cursor().execute(
        "SELECT end_time FROM events WHERE event_id = ?", [event_id]
    ).fetchone()
    if not row or row[0] is None:
        return None
    return _format_clock(row[0])


def _schedule_label(event_id: str, he) -> str | None:
    start = he.start_time if he else None
    end = _end_time(event_id)
    if start and end:
        return f"{start} to {end}"
    if start:
        return start
    if end:
        return f"Ends {end}"
    return None


def _turnout_label(turnout: int | None) -> str:
    if turnout is None:
        return "—"
    if turnout >= 1_000_000:
        return f"{turnout / 1_000_000:.1f}M"
    if turnout >= 10_000:
        return f"{turnout // 1000}k"
    return f"{turnout:,}"


def _weather_label(ev: TrainingEvent) -> str:
    precip = float(ev.context.get("precip_mm_4h") or 0)
    if precip < 0.05:
        summary = "Dry"
    elif precip < 2.0:
        summary = "Light rain"
    else:
        summary = "Rain"
    return f"{summary}, {precip:.1f} mm"


def _waypoint_stops(he) -> str:
    if not he or not he.waypoints:
        return "—"
    names = [str(n or "").strip() for n, _ in he.waypoints if str(n or "").strip()]
    if not names:
        return "—"
    return " · ".join(names)


def _cause_label(cause: str | None) -> str | None:
    if not cause:
        return None
    return cause.replace("_", " ").strip().title()


def _event_header(ev: TrainingEvent | None) -> None:
    if ev is None:
        return
    he = _historic(ev.event_id)
    org = _organisation_label(ev.event_id)
    cause = _cause_label(ev.cause or (he.cause if he else None))
    subtitle_parts = [_display_date(ev.date)]
    if cause:
        subtitle_parts.append(cause)
    subtitle = " · ".join(subtitle_parts)

    turnout = he.turnout if he else int(ev.context.get("turnout") or 0) or None
    turnout_s = _turnout_label(turnout)
    schedule = _schedule_label(ev.event_id, he) or "—"
    weather = _weather_label(ev)
    stops = _waypoint_stops(he)
    #region agent log
    _agent_debug_log(
        "B",
        "metric display strings",
        {
            "event_id": ev.event_id,
            "turnout_len": len(turnout_s),
            "schedule_len": len(schedule),
            "weather_len": len(weather),
            "weather": weather,
            "renderer": "custom_grid",
        },
    )
    #endregion

    with st.container(border=True):
        st.markdown(
            f'<p class="route-event-title">{html.escape(org)}</p>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<p class="route-event-sub">{html.escape(subtitle)}</p>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f"""
            <div class="route-event-metrics">
              <div class="route-event-metric">
                <span class="k">Turnout</span>
                <span class="v">{html.escape(turnout_s)}</span>
              </div>
              <div class="route-event-metric">
                <span class="k">Schedule</span>
                <span class="v">{html.escape(schedule)}</span>
              </div>
              <div class="route-event-metric">
                <span class="k">Weather</span>
                <span class="v">{html.escape(weather)}</span>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown('<p class="route-event-stops-label">Planned stops</p>', unsafe_allow_html=True)
        st.markdown(
            f'<p class="route-event-stops">{html.escape(stops)}</p>',
            unsafe_allow_html=True,
        )


def _event_picker_label(event_id: str, by_id: dict[str, TrainingEvent]) -> str:
    ev = by_id.get(event_id)
    if not ev:
        return event_id
    return f"{ev.date}: {_organisation_label(event_id)}"


_ROUTE_STYLE_KEY: dict[str, str] = {
    "Actual": "actual_casing",
    "Route model": "route_model",
    "Shortest path": "shortest_path",
    "Random walk": "random_walk",
}


def _layer_color(label: str) -> str:
    style = _ROUTE_STYLE_KEY.get(label)
    if style:
        return MAP_LAYER_STYLES[style]["hex"]
    return LAYER_PILL_COLORS.get(label, "#64748B")


def _active_layers_from_session() -> set[str]:
    active: set[str] = set()
    for opt in LAYER_OPTIONS:
        key = f"layer_toggle_{opt}"
        if st.session_state.get(key, opt in DEFAULT_LAYERS):
            active.add(opt)
    return active or set(DEFAULT_LAYERS)


def _legend_swatch_html(opt: str, color: str) -> str:
    if opt == "Restricted zones":
        return (
            f'<span class="map-legend-square" style="background:{color};'
            f'border:1px solid #DC2626"></span>'
        )
    return f'<span class="map-legend-swatch" style="color:{color}">━</span>'


def _map_layer_legend() -> None:
    """Coloured swatch + label with a checkbox for each map layer."""
    st.markdown('<span class="map-legend-marker"></span>', unsafe_allow_html=True)
    col_widths = [1.0, 1.05, 1.12, 1.0, 1.18, 1.32]
    cols = st.columns(col_widths, gap="small", vertical_alignment="center")
    for col, opt in zip(cols, LAYER_OPTIONS, strict=True):
        color = _layer_color(opt)
        key = f"layer_toggle_{opt}"
        default = opt in DEFAULT_LAYERS
        with col:
            pick, label = st.columns([0.11, 0.89], gap="small", vertical_alignment="center")
            with pick:
                st.checkbox(
                    "on",
                    value=default,
                    key=key,
                    label_visibility="collapsed",
                )
            with label:
                st.markdown(
                    f'<span class="map-legend-label">'
                    f"{_legend_swatch_html(opt, color)}"
                    f"<span>{html.escape(opt)}</span></span>",
                    unsafe_allow_html=True,
                )


def _toolbar(event_ids: list[str], by_id: dict[str, TrainingEvent]) -> str:
    if "map_event" not in st.session_state and event_ids:
        st.session_state["map_event"] = event_ids[0]
    event_id = st.session_state.get("map_event", event_ids[0])
    if event_id not in event_ids:
        event_id = event_ids[0]
        st.session_state["map_event"] = event_id
    idx = event_ids.index(event_id)
    label = _event_picker_label(event_id, by_id)

    st.markdown('<span class="route-event-nav-marker"></span>', unsafe_allow_html=True)
    nav = st.columns([1.1, 4, 1.1], gap="medium", vertical_alignment="center")
    with nav[0]:
        if st.button(
            "◀  Previous",
            disabled=idx <= 0,
            use_container_width=True,
            type="secondary",
            key="map_event_prev",
        ):
            st.session_state["map_event"] = event_ids[idx - 1]
            st.rerun()
    with nav[1]:
        st.markdown(
            f'<p class="route-event-nav-title">{html.escape(label)}</p>',
            unsafe_allow_html=True,
        )
    with nav[2]:
        if st.button(
            "Next  ▶",
            disabled=idx >= len(event_ids) - 1,
            use_container_width=True,
            type="secondary",
            key="map_event_next",
        ):
            st.session_state["map_event"] = event_ids[idx + 1]
            st.rerun()
    return event_id


def _context_layers(active: set[str]) -> tuple[list[pdk.Layer], list[pdk.Layer]]:
    under: list[pdk.Layer] = []
    over: list[pdk.Layer] = []
    if not DB_PATH.is_file():
        return under, over
    try:
        if "Restricted zones" in active:
            zones = mapdata.legal_zones()
            if zones:
                under.extend(map_layers.legal_zone_layers(zones))
        if "Zone boundary" in active:
            over.extend(
                map_layers.ring_outline_layers(
                    mapdata.boundary(),
                    [156, 163, 175, 200],
                    width=3,
                )
            )
    except OSError:
        pass
    return under, over


def _route_layers(
    g: MarchGraph,
    bt: BacktestResult,
    event_id: str,
    metrics: dict[str, BacktestRow],
    active: set[str],
) -> tuple[list[dict], list[LonLat]]:
    features: list[dict] = []
    fit_coords: list[LonLat] = []
    paths = paths_for_event(bt, event_id)
    actual = (bt.actual_routes or {}).get(event_id, [])

    def add_route(
        model_key: str | None,
        ids: list[str],
        style_key: str,
        name: str,
    ) -> None:
        stl = MAP_LAYER_STYLES[style_key]
        row = metrics.get(model_key) if model_key else None
        overlap = row.top1_jaccard if row else None
        features.extend(
            map_layers.route_path_features(
                g,
                ids,
                stl["hex"],
                stl["width"],
                name,
                overlap=overlap,
                n_steps=len(ids),
                dash_array=stl["dash"],
                alpha=stl["alpha"],
                trim_backtrack=style_key == "actual_casing",
            )
        )
        fit_coords.extend(map_layers.coords_for_fit(g, ids))

    # Draw order: casing / baselines first, route model last on top
    if "Actual" in active and actual:
        add_route(None, actual, "actual_casing", "Actual")
    if "Shortest path" in active and "shortest_path" in paths:
        add_route("shortest_path", paths["shortest_path"], "shortest_path", MAP_LABELS["shortest_path"])
    if "Random walk" in active and "random_walk" in paths:
        add_route("random_walk", paths["random_walk"], "random_walk", MAP_LABELS["random_walk"])
    if "Route model" in active and "route_model" in paths:
        add_route("route_model", paths["route_model"], "route_model", MAP_LABELS["route_model"])
    return features, fit_coords


def _fit_coords_all_routes(
    g: MarchGraph,
    bt: BacktestResult,
    event_id: str,
) -> list[LonLat]:
    """Bounding points for every route variant on this event (for map framing)."""
    paths = paths_for_event(bt, event_id)
    actual = (bt.actual_routes or {}).get(event_id, [])
    fit: list[LonLat] = []
    for ids in (
        actual,
        paths.get("shortest_path"),
        paths.get("random_walk"),
        paths.get("route_model"),
    ):
        if ids:
            fit.extend(map_layers.coords_for_fit(g, ids))
    return fit


def _view_state_key(event_id: str, active: set[str]) -> str:
    return f"{event_id}|{'|'.join(sorted(active))}"


def _resolve_map_view(fit_coords: list[LonLat], g: MarchGraph, frame_key: str) -> pdk.ViewState:
    reset = st.session_state.pop("map_reset_view", False)
    reframe = reset or st.session_state.get("map_frame_key") != frame_key
    if reframe:
        st.session_state["map_frame_key"] = frame_key
        default = map_layers.view_state_for_coords(fit_coords)
        if default is None:
            if fit_coords:
                span = max(
                    max(c[0] for c in fit_coords) - min(c[0] for c in fit_coords),
                    max(c[1] for c in fit_coords) - min(c[1] for c in fit_coords),
                )
                if span > map_layers.MAX_ROUTE_SPAN_DEG:
                    st.error("Could not frame this route on the map.")
            default = map_layers.initial_view_state(g)
        st.session_state["map_default_view"] = default
        #region agent log
        vs = st.session_state["map_default_view"]
        _agent_debug_log(
            "fit",
            "map view reframe",
            {
                "frame_key": frame_key,
                "n_fit_coords": len(fit_coords),
                "zoom": float(vs.zoom),
                "lon": float(vs.longitude),
                "lat": float(vs.latitude),
                "scroll_zoom": True,
            },
            run_id="map-frame",
        )
        #endregion
    return st.session_state.get("map_default_view", map_layers.initial_view_state(g))


def _metrics_table(rows: list[BacktestRow]) -> None:
    df = pd.DataFrame(
        [
            {
                "model_id": r.model,
                "Model": MAP_LABELS.get(r.model, r.model),
                "swatch": MAP_LAYER_STYLES.get(r.model, MAP_LAYER_STYLES["route_model"])["hex"],
                "Mean log-likelihood": r.mean_log_likelihood,
                "Route overlap": (
                    float(r.top1_jaccard) * 100.0 if r.top1_jaccard is not None else None
                ),
            }
            for r in rows
        ]
    )
    best_ll = df["Mean log-likelihood"].max()
    best_ov = df["Route overlap"].max()
    winner_ids = set(
        df.loc[(df["Mean log-likelihood"] == best_ll) | (df["Route overlap"] == best_ov), "model_id"]
    )
    swatches = list(df["swatch"])

    def model_border(_series: pd.Series) -> list[str]:
        return [f"border-left: 4px solid {c}; padding-left: 6px" for c in swatches]

    show = df.drop(columns=["model_id", "swatch"])

    def row_bg(row: pd.Series) -> list[str]:
        mid = df.loc[row.name, "model_id"]
        bg = "background-color: #F8FAFC" if mid in winner_ids else ""
        return [bg] * len(row)
    styled = (
        show.style.format(
            {
                "Mean log-likelihood": "{:.4f}",
                "Route overlap": "{:.1f}%",
            }
        )
        .bar(subset=["Route overlap"], color="#E2E8F0", vmin=0, vmax=100)
        .apply(model_border, subset=["Model"])
        .apply(row_bg, axis=1)
        .apply(
            lambda col: [
                "font-weight:700"
                if (col.name == "Mean log-likelihood" and v == best_ll)
                or (col.name == "Route overlap" and v == best_ov)
                else ""
                for v in col
            ],
            axis=0,
        )
    )
    st.dataframe(
        styled,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Model": st.column_config.TextColumn("Model"),
            "Mean log-likelihood": st.column_config.NumberColumn(
                "Mean log-likelihood",
                format="%.4f",
            ),
            "Route overlap": st.column_config.ProgressColumn(
                "Route overlap",
                format="%.1f%%",
                min_value=0,
                max_value=100,
            ),
        },
    )


def render() -> None:
    """Draw the route comparison map."""
    with page_body():
        st.title("Route comparison")
        bt = read_backtest(BACKTEST_PATH)
        if bt is None or not backtest_has_paths(bt):
            st.warning("No route data for the map.")
            return

        events = list(load_training_events())
        by_id = _events_by_id(bt, tuple(events))
        event_ids = _event_ids(bt)
        if not event_ids:
            st.warning("No events in backtest.")
            return

        g = get_graph()
        event_id = _toolbar(event_ids, by_id)
        ev = by_id.get(event_id)
        _event_header(ev)

        metrics = _row_metrics(bt, event_id)
        active = _active_layers_from_session()
        route_features, _layer_fit = _route_layers(g, bt, event_id, metrics, active)
        fit_coords = _fit_coords_all_routes(g, bt, event_id)
        if not fit_coords:
            fit_coords = _layer_fit
        frame_key = _view_state_key(event_id, active)

        with section("Route map"):
            _map_layer_legend()
            route_layers = map_layers.route_path_and_chevron_layers(route_features)
            if not route_layers:
                st.info("No layers selected.")
            else:
                view = _resolve_map_view(fit_coords, g, frame_key)
                under_layers, over_layers = _context_layers(active)
                layers = [*under_layers, *route_layers, *over_layers]
                #region agent log
                chevron_n = max(0, len(route_layers) - len(route_features))
                _agent_debug_log(
                    "deck",
                    "deck layers built",
                    {
                        "route_features": len(route_features),
                        "route_layers": len(route_layers),
                        "chevron_layers_est": chevron_n,
                        "interleaved": True,
                        "frame_key": frame_key,
                    },
                    run_id="map-frame-postfix",
                )
                #endregion
                st.pydeck_chart(
                    pdk.Deck(
                        layers=layers,
                        initial_view_state=view,
                        views=[map_layers.map_view_interactive()],
                        map_style=pdk.map_styles.CARTO_LIGHT,
                        map_provider="carto",
                        tooltip=DECK_TOOLTIP,
                    ),
                    height=600,
                    use_container_width=True,
                    key=f"route_map_deck_{frame_key}",
                )

        event_rows = [r for r in bt.rows if r.event_id == event_id]
        if event_rows:
            with section("Metrics for this event"):
                _metrics_table(event_rows)


render()
