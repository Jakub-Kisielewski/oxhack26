import pandas as pd
import streamlit as st

from src.contract.types import OverspillRequest, RouteRequest
from src.ui import charts, common, conditions_panel, layers
from src.ui.context_form import context_form
from src.ui.pick_map import pick_map

common.page_header("Route predictor", "Where will a march go from its start point? Probabilities, not a single guess.")

assembly = common.assembly_points()
state = st.session_state

# ---------- inputs ----------
with st.sidebar:
    st.subheader("March")
    ctx = context_form("route")

    st.subheader("Start")
    start_mode = st.radio("Start from", ["Known assembly point", "Click on the map"], key="route_start_mode",
                          horizontal=True, label_visibility="collapsed")
    if start_mode == "Known assembly point":
        names = [a["name"] for a in assembly]
        pick = st.selectbox("Assembly point", names, key="route_assembly",
                            format_func=lambda n: next(f"{a['name']} ({a['n_events']} past marches)" for a in assembly
                                                       if a["name"] == n)) if names else None
        start = next((a["lonlat"] for a in assembly if a["name"] == pick), None)
        start_label = pick or ""
    else:
        start = state.get("route_start_pick")
        start_label = "Picked point"
        st.caption(f"Start: {start[1]:.5f}, {start[0]:.5f}" if start else "Click the map to set the start.")

    st.subheader("End (optional)")
    know_end = st.toggle("I know where it ends", key="route_know_end")
    end, end_label = None, ""
    if know_end:
        end_mode = st.radio("End from", ["Known target", "Click on the map"], key="route_end_mode", horizontal=True,
                            label_visibility="collapsed")
        if end_mode == "Known target":
            options = common.cause_targets(ctx.cause)
            end_label = st.selectbox("End point", [t["target_name"] for t in options], key="route_end_target")
            end = next((t["lonlat"] for t in options if t["target_name"] == end_label), None)
        else:
            end, end_label = state.get("route_end_pick"), "Picked point"
            st.caption(f"End: {end[1]:.5f}, {end[0]:.5f}" if end else "Click the map to set the end.")

    n_routes = st.slider("Routes to show", 1, 5, 3, key="route_n")
    run = st.button("Predict route", type="primary", icon=":material/explore:", width="stretch",
                    disabled=start is None)

# ---------- point picking ----------
picking = [k for k, on in (("start", start_mode == "Click on the map"),
                           ("end", know_end and state.get("route_end_mode") == "Click on the map")) if on]
if picking:
    with st.expander("Pick points on the map", expanded=True, icon=":material/touch_app:"):
        target = st.radio("Clicking sets the", picking, horizontal=True, key="route_pick_target") if len(picking) > 1 \
            else picking[0]
        markers = [{"lonlat": p, "label": k.title(), "kind": k} for k, p in
                   (("start", state.get("route_start_pick")), ("end", state.get("route_end_pick"))) if p]
        clicked = pick_map("route_pick", markers=markers, center=state.get("route_start_pick"))
        if clicked:
            state[f"route_{target}_pick"] = clicked
            st.rerun()

if run and start is not None:
    req = RouteRequest(context=ctx, start=tuple(start), end=tuple(end) if end else None, n_routes=n_routes)
    prediction = common.predict_route(req)
    if prediction:
        state["route_request"], state["route_prediction"] = req, prediction
        state["route_labels"] = {"start": start_label, "end": end_label}
        state.pop("route_pin", None)

prediction = state.get("route_prediction")
if not prediction:
    st.info("Choose a start point and the march details in the sidebar, then press **Predict route**.",
            icon=":material/explore:")
    st.stop()

# ---------- results ----------
req = prediction.request
labels = state.get("route_labels", {})
st.caption(f"Prediction for: {common.describe_context(req.context)}, starting at {labels.get('start') or 'the chosen point'}"
           + (f", ending at {labels.get('end')}" if req.end else "") + f". Model {prediction.model_version}.")

top_route = prediction.routes[0] if prediction.routes else None
top_dest = prediction.destinations[0] if prediction.destinations else None
m1, m2, m3, m4 = st.columns(4)
m1.metric("Expected turnout", f"{prediction.turnout.expected:,}",
          help=f"Range {prediction.turnout.low:,} to {prediction.turnout.high:,} ({prediction.turnout.source}).")
m2.metric("Expected duration", common.duration(prediction.expected_duration_min),
          help=f"March and rally, ending around {common.clock(req.context, prediction.expected_duration_min)}.")
m3.metric("Likeliest end", common.pct(top_dest.probability) if top_dest else "-",
          top_dest.name if top_dest else None, delta_color="off", delta_arrow="off",
          help="Chance the march ends here; other likely end points are in the Destinations tab.")
m4.metric("Route 1", common.km(top_route.length_m) if top_route else "-",
          f"{common.pct(top_route.probability)} of predicted routes" if top_route else None, delta_color="off", delta_arrow="off")

shown = st.pills("Layers", ["Heatmap", "Street probabilities", "Top routes", "Destinations", "Legal zones",
                            "Cause targets"], selection_mode="multi", key="route_layers_2d",
                 default=["Heatmap", "Top routes", "Destinations"])
deck_layers = [layers.boundary_layer()]
if "Legal zones" in shown:
    deck_layers.append(layers.legal_zones_layer())
if "Heatmap" in shown:
    deck_layers.append(layers.cell_layer(prediction.cells, extruded=False))
if "Street probabilities" in shown:
    names = common.street_names(tuple(s.segment_id for s in prediction.segments[:1500]))
    deck_layers.append(layers.segment_prob_layer(prediction.segments, names))
if "Cause targets" in shown:
    deck_layers.append(layers.targets_layer(common.cause_targets(req.context.cause), "cause_targets"))
if "Top routes" in shown:
    deck_layers += layers.routes_layers(prediction.routes)
if "Destinations" in shown:
    deck_layers += layers.destinations_layers(prediction.destinations)
deck_layers.append(layers.point_layer("start", [(req.start, "Start")]))
if req.end:
    deck_layers.append(layers.point_layer("end", [(req.end, "End")], color=layers.ink("surface")))
pin = state.get("route_pin")
if pin:
    deck_layers.append(layers.point_layer("pin", [(pin, "Checked location")], color=layers.rgba(layers.magenta_css())))

view_points = [p for r in prediction.routes for p in r.path] + [req.start] + [d.lonlat for d in prediction.destinations]
# Flat, top-down view (constant: changing the camera between reruns can blank the deck).
event = layers.show(layers.deck(deck_layers, layers.view_for(view_points, pitch=0)), key="route_deck", selectable=True)
legend = [("Route (1 = likeliest)", layers.ink_css("primary"), "line"), ("Start", layers.ink_css("primary"), "dot")]
if "Destinations" in shown:
    legend.append(("Likely end point (size = chance)", layers.ink_css("surface"), "dot"))
if "Cause targets" in shown:
    legend.append(("Cause target", layers.magenta_css(), "dot"))
layers.legend(legend)
if "Heatmap" in shown or "Street probabilities" in shown:
    shown_values = ([c.value for c in prediction.cells] if "Heatmap" in shown else []) + \
        ([x.p_visit for x in prediction.segments] if "Street probabilities" in shown else [])
    layers.ramp_legend("Chance the march passes:", high=common.pct(layers.heat_max(shown_values)))
if "Legal zones" in shown:
    layers.legal_legend()

# ---------- pin drop ----------
clicked = layers.selected_point(event)
if clicked and clicked != state.get("route_pin_source"):
    state["route_pin"], state["route_pin_source"] = clicked, clicked
    state.pop("route_pin_lat", None), state.pop("route_pin_lon", None)
    st.rerun()
with st.expander("Check a location", expanded=bool(pin), icon=":material/location_on:"):
    st.caption("Click any hexagon or street on the map, or enter coordinates.")
    c1, c2, c3 = st.columns([2, 2, 1], vertical_alignment="bottom")
    lat = c1.number_input("Latitude", value=float(pin[1]) if pin else 51.5080, format="%.5f", key="route_pin_lat")
    lon = c2.number_input("Longitude", value=float(pin[0]) if pin else -0.1281, format="%.5f", key="route_pin_lon")
    if c3.button("Check", width="stretch"):
        state["route_pin"] = (lon, lat)
        st.rerun()
    if pin:
        risk = common.point_risk(prediction, pin)
        if risk:
            common.risk_badge(risk.level)
            st.markdown(f"**{common.pct(risk.p_visit)}** chance the march passes within 50 m. {risk.explanation}")

# ---------- details ----------
tab_routes, tab_dest, tab_cond, tab_why, tab_notes = st.tabs(["Top routes", "Destinations", "Conditions & effects",
                                                             "Why", "Notes"])
with tab_routes:
    st.dataframe(pd.DataFrame([{"Route": r.rank, "Chance": r.probability, "Length (km)": r.length_m / 1000,
                                "Walking time (min)": r.duration_min, "Ends at": r.end_label or "-",
                                "Streets": len(r.segment_ids)} for r in prediction.routes]),
                 hide_index=True, width="stretch",
                 column_config={"Chance": st.column_config.ProgressColumn("Chance", format="percent", min_value=0, max_value=1),
                                "Length (km)": st.column_config.NumberColumn(format="%.1f"),
                                "Walking time (min)": st.column_config.NumberColumn(format="%.0f")})
    if top_route and st.button("Analyse overspill for route 1", icon=":material/arrow_forward:", type="primary"):
        state["overspill_request"] = OverspillRequest(context=req.context, route_segment_ids=tuple(top_route.segment_ids))
        state.pop("overspill_prediction", None)
        state["planned_source"] = "From the route predictor"
        state.pop("planned_source_radio", None)
        st.switch_page("src/ui/pages/planned_route.py")
with tab_dest:
    st.dataframe(pd.DataFrame([{"End point": d.name, "Chance": d.probability} for d in prediction.destinations]),
                 hide_index=True, width="stretch",
                 column_config={"Chance": st.column_config.ProgressColumn("Chance", format="percent", min_value=0, max_value=1)})
with tab_cond:
    conditions_panel.show(prediction)
with tab_why:
    charts.drivers_chart(prediction.drivers)
with tab_notes:
    for w in prediction.warnings:
        st.warning(w, icon=":material/info:")
    st.markdown("Training routes are **published march plans** joined by shortest paths, not GPS traces, so the "
                "model predicts planned routes. Probabilities are per street; the routes are the likeliest paths.")
