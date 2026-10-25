import pandas as pd
import streamlit as st

from src.contract import mapdata
from src.contract.types import MarchContext, OverspillRequest
from src.ui import charts, common, layers
from src.ui.context_form import context_form, set_context
from src.ui.pick_map import pick_map

common.page_header("Planned route", "For a known route: how crowded each street gets, when, and where the crowd "
                   "spills into side streets.")

state = st.session_state
events = common.historical_events()
by_id = {e.event_id: e for e in events}
sources = ["Past march", "Draw on the map"] + (["From the route predictor"] if state.get("overspill_request") and
                                                state.get("planned_source") == "From the route predictor" else [])

# ---------- inputs ----------
with st.sidebar:
    st.subheader("Route")
    default_source = state.get("planned_source") if state.get("planned_source") in sources else sources[0]
    source = st.radio("Route from", sources, index=sources.index(default_source), key="planned_source_radio",
                      label_visibility="collapsed")
    state["planned_source"] = source
    route_ids: tuple[str, ...] = ()
    if source == "Past march":
        ids = [e.event_id for e in events]
        current = state.get("selected_event_id") if state.get("selected_event_id") in ids else (ids[0] if ids else None)
        chosen = st.selectbox("Past march", ids, index=ids.index(current) if current else 0, key="planned_event",
                              format_func=lambda i: f"{by_id[i].date}: {by_id[i].name}") if ids else None
        if chosen and chosen != state.get("selected_event_id"):
            e = by_id[chosen]
            state["selected_event_id"] = chosen
            set_context(MarchContext(date=e.date, start_time=e.start_time or "12:00", cause=e.cause,
                                     organiser=e.organiser, turnout=e.turnout), "overspill")
            st.rerun()
        if chosen:
            route_ids = tuple(by_id[chosen].route_segment_ids)
            st.caption(f"{len(by_id[chosen].waypoints)} published waypoints, {len(route_ids)} street segments.")
    elif source == "Draw on the map":
        waypoints = state.setdefault("planned_waypoints", [])
        st.caption(f"{len(waypoints)} waypoints. Click the map to add them in order.")
        b1, b2 = st.columns(2)
        if b1.button("Undo last", disabled=not waypoints, width="stretch"):
            waypoints.pop()
            state.pop("planned_drawn_ids", None)
            st.rerun()
        if b2.button("Clear", disabled=not waypoints, width="stretch"):
            waypoints.clear()
            state.pop("planned_drawn_ids", None)
            st.rerun()
        if st.button("Snap to streets", disabled=len(waypoints) < 2, width="stretch", icon=":material/route:"):
            snapped = common.snap_route(list(waypoints))
            if snapped:
                state["planned_drawn_ids"] = tuple(snapped)
        route_ids = state.get("planned_drawn_ids", ())
        if route_ids:
            st.caption(f"Snapped to {len(route_ids)} street segments.")
    else:
        route_ids = tuple(state["overspill_request"].route_segment_ids)
        st.caption(f"Route 1 from the route predictor ({len(route_ids)} street segments).")

    st.subheader("March")
    ctx = context_form("overspill")
    st.subheader("Policing")
    police_on = st.toggle("Include police presence", key="planned_police_on")
    officers = st.slider("Officers", 0, 500, 100, step=5, key="planned_officers", disabled=not police_on)
    run = st.button("Analyse route", type="primary", icon=":material/groups:", width="stretch",
                    disabled=not route_ids)

# ---------- drawing ----------
if source == "Draw on the map":
    with st.expander("Draw the route", expanded=True, icon=":material/draw:"):
        waypoints = state.setdefault("planned_waypoints", [])
        markers = [{"lonlat": p, "label": f"Waypoint {i}", "kind": "waypoint"} for i, p in enumerate(waypoints, 1)]
        clicked = pick_map("planned_pick", markers=markers, line=list(waypoints),
                           center=waypoints[0] if waypoints else None)
        if clicked:
            waypoints.append(clicked)
            state.pop("planned_drawn_ids", None)
            st.rerun()

arrived = source == "From the route predictor" and not state.get("overspill_prediction")
if (run or arrived) and route_ids:
    req = OverspillRequest(context=ctx, route_segment_ids=route_ids, police_officers=officers if police_on else None)
    prediction = common.predict_overspill(req)
    if prediction:
        state["overspill_request"], state["overspill_prediction"] = req, prediction

prediction = state.get("overspill_prediction")
if not prediction:
    st.info("Pick a past march, draw a route or send one from the route predictor, then press **Analyse route**.",
            icon=":material/route:")
    st.stop()

# ---------- results ----------
req, rctx = prediction.request, prediction.request.context
tl = prediction.timeline
st.caption(f"Analysis for: {common.describe_context(rctx)}"
           + (f", {req.police_officers} officers" if req.police_officers else "") + f". Model {prediction.model_version}.")
lengths = {t.segment_id: sum(mapdata.distance_m(a, b) for a, b in zip(t.path, t.path[1:])) for t in tl}
end_min = max((t.tail_departure_min for t in tl), default=0.0)
danger_minutes = sum(1 for minute in range(int(end_min) + 1)
                     if any(t.head_arrival_min <= minute <= t.tail_departure_min and t.level_of_service in "EF" for t in tl))
worst = max(tl, key=lambda t: t.peak_density_ppm2) if tl else None
high_spill = [s for s in prediction.spill if s.p_spill >= 0.3]

m1, m2, m3, m4 = st.columns(4)
m1.metric("Turnout", f"{prediction.turnout.expected:,}",
          help=f"Range {prediction.turnout.low:,} to {prediction.turnout.high:,} ({prediction.turnout.source}).")
m2.metric("Crowd on the route", f"{common.clock(rctx, 0)} to {common.clock(rctx, end_min)}",
          help=f"Total with rally: {common.duration(prediction.expected_duration_min)}.")
m3.metric("Worst crowding", layers.LOS_LABEL[worst.level_of_service] if worst else "-",
          f"{worst.peak_density_ppm2:.1f} people/m²" if worst else None, delta_color="off", delta_arrow="off")
m4.metric("Minutes at crush risk (E/F)", f"{danger_minutes}", f"{len(high_spill)} side streets at high spill risk",
          delta_color="off", delta_arrow="off")

horizon = max(1, int(round(max(end_min, prediction.expected_duration_min))))
busiest = max(range(0, int(end_min) + 1, 2) or [0],
              key=lambda minute: sum(s.head_arrival_min <= minute <= s.tail_departure_min for s in tl))
t = st.slider("Minutes since the march starts", 0, horizon, min(horizon, busiest), key="planned_t",
              help="Starts at the busiest moment. Move it to watch the crowd pass along the route.")
active = [s for s in tl if s.head_arrival_min <= t <= s.tail_departure_min]
st.markdown(f"**{common.clock(rctx, t)}**: crowd on {len(active)} of {len(tl)} route segments, "
            f"{len([s for s in prediction.spill if s.window_start_min <= t <= s.window_end_min])} side streets at risk.")

names = common.street_names(tuple(s.segment_id for s in tl))
deck_layers = [layers.boundary_layer(), layers.route_outline_layer([s.path for s in tl]),
               layers.spill_layer(prediction.spill, rctx, t), layers.timeline_layer(tl, t, rctx, names)]
deck_layers += layers.hotspot_layers(prediction.hotspots)
layers.show(layers.deck(deck_layers, layers.view_for([p for s in tl for p in s.path])), key="planned_deck")
layers.legend([("Route (no crowd at this time)", layers.ink_css("muted"), "line"),
               ("Hotspot (numbered, see table)", layers.ink_css("primary"), "dot")])
layers.los_legend()
layers.ramp_legend("Side-street spill risk:", ramp="orange")

# ---------- details ----------
tab_hot, tab_los, tab_why, tab_notes = st.tabs(["Hotspots", "Crowd levels", "Why", "Notes"])
with tab_hot:
    if prediction.hotspots:
        st.dataframe(pd.DataFrame([{"#": i, "Where": h.label, "Risk": h.risk, "Level": h.level.title(),
                                    "Type": "Crowd pressure" if h.kind == "pressure" else "Breakaway towards a target"}
                                   for i, h in enumerate(prediction.hotspots, 1)]),
                     hide_index=True, width="stretch",
                     column_config={"Risk": st.column_config.ProgressColumn("Risk", format="percent", min_value=0, max_value=1)})
    else:
        st.caption("No hotspots predicted.")
    c1, c2 = st.columns(2)
    c1.page_link("src/ui/pages/shopkeeper.py", label="Check a shop on this route", icon=":material/storefront:")
    c2.page_link("src/ui/pages/police.py", label="Place police for this route", icon=":material/local_police:")
with tab_los:
    charts.los_chart(tl, lengths)
    st.caption("Crowd levels follow Fruin's queuing levels of service (people per m²): "
               "A < 0.83, B < 1.08, C < 1.54, D < 3.3, E < 5, F ≥ 5.")
with tab_why:
    charts.drivers_chart(prediction.drivers)
with tab_notes:
    for w in prediction.warnings:
        st.warning(w, icon=":material/info:")
    st.markdown("Overspill is a **physics-based estimate** (crowd density against street width, march speed "
                "about 2.5 km/h) with hand-set coefficients: there are no recorded overspill events to train on.")
