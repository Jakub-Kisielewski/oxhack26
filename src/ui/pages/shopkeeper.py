import pandas as pd
import streamlit as st

from src.contract.types import OverspillPrediction
from src.ui import common, layers
from src.ui.pick_map import pick_map

common.page_header("Shopkeeper advice", "Is my shop at risk, when, and where is the safest place to move stock?")

state = st.session_state
available = {label: state.get(key) for label, key in (("Planned route", "overspill_prediction"),
                                                      ("Predicted route", "route_prediction")) if state.get(key)}
if not available:
    common.need_prediction("any")
    st.stop()

# ---------- inputs ----------
with st.sidebar:
    st.subheader("Prediction")
    which = st.radio("Use", list(available), key="shop_prediction", label_visibility="collapsed",
                     help="The planned-route analysis includes timings and side-street spill.")
    prediction = available[which]
    ctx = prediction.request.context
    st.caption(common.describe_context(ctx))

    st.subheader("Your shop")
    find = st.radio("Find it by", ["Name", "Clicking the map"], key="shop_find", horizontal=True)
    shop, shop_name = None, ""
    if find == "Name":
        query = st.text_input("Shop name", key="shop_query", placeholder="e.g. Boots")
        results = common.search_shops(query)
        if query and not results:
            st.caption("No shops with that name. Try part of the name, or click the map.")
        if results:
            idx = st.selectbox("Matches", range(len(results)), key="shop_match",
                               format_func=lambda i: f"{results[i]['name']} ({(results[i]['shop'] or 'shop').replace('_', ' ')})")
            shop, shop_name = results[idx]["lonlat"], results[idx]["name"]
    else:
        clicked = state.get("shop_click")
        if clicked:
            nearby = common.shops_near(tuple(clicked), 150)
            options = [("Exactly where I clicked", tuple(clicked))] + [
                (f"{s['name'] or 'Unnamed ' + (s['shop'] or 'shop').replace('_', ' ')} ({s['distance_m']:.0f} m)", s["lonlat"])
                for s in nearby[:15]]
            idx = st.selectbox("Shop", range(len(options)), key="shop_nearby", format_func=lambda i: options[i][0])
            shop_name, shop = options[idx]
        else:
            st.caption("Click your shop's location on the map.")

if find == "Clicking the map":
    with st.expander("Click your shop", expanded=shop is None, icon=":material/touch_app:"):
        center = prediction.timeline[0].path[0] if isinstance(prediction, OverspillPrediction) and prediction.timeline \
            else prediction.request.start
        point = pick_map("shop_pick", markers=[{"lonlat": state["shop_click"], "label": "Your shop", "kind": "shop"}]
                         if state.get("shop_click") else [], center=state.get("shop_click") or center, zoom=15)
        if point:
            state["shop_click"] = point
            state.pop("shop_nearby", None)
            st.rerun()

if shop is None:
    st.info("Find your shop in the sidebar to see its risk and the best place to move stock.", icon=":material/storefront:")
    st.stop()

advice = common.shop_advice(prediction, tuple(shop))
if not advice:
    st.stop()

# ---------- results ----------
risk = advice.risk
st.subheader(shop_name or "Your shop")
common.risk_badge(risk.level)
m1, m2, m3 = st.columns(3)
m1.metric("Risk at your shop", common.pct(risk.risk), help=risk.explanation)
m2.metric("Crowd expected", f"{common.clock(ctx, risk.window_start_min)} to {common.clock(ctx, risk.window_end_min)}"
          if risk.window_start_min is not None else "No timing", help="Local time on the day of the march.")
m3.metric("Move stock by", common.clock(ctx, advice.act_by_min) if advice.act_by_min is not None else "No action needed")
box = st.success if risk.level == "low" else st.warning if risk.level == "medium" else st.error
box(advice.recommendation, icon=":material/inventory_2:")

deck_layers = [layers.boundary_layer()]
if isinstance(prediction, OverspillPrediction):
    deck_layers += [layers.route_outline_layer([s.path for s in prediction.timeline]),
                    layers.spill_layer(prediction.spill, ctx)]
    ramp_note = ("Side-street spill risk:", "orange", "100%")
else:
    deck_layers.append(layers.segment_prob_layer(prediction.segments))
    ramp_note = ("Chance the march passes:", "blue", common.pct(layers.heat_max(x.p_visit for x in prediction.segments)))
deck_layers += layers.warehouse_layers(tuple(shop), advice.warehouses)
deck_layers.append(layers.point_layer("shop", [(tuple(shop), shop_name or "Your shop")], color=layers.rgba(layers.magenta_css())))
layers.show(layers.deck(deck_layers, layers.view_for([tuple(shop)] + [w.lonlat for w in advice.warehouses], zoom_cap=16)),
            key="shop_deck", height=480)
layers.legend([("Your shop", layers.magenta_css(), "dot"), ("Storage option (numbered)", layers.aqua_css(), "dot"),
               ("Way to the storage", layers.aqua_css(), "line")]
              + ([("March route", layers.ink_css("muted"), "line")] if isinstance(prediction, OverspillPrediction) else []))
layers.ramp_legend(ramp_note[0], ramp=ramp_note[1], high=ramp_note[2])

st.subheader("Where to move stock")
if advice.warehouses:
    st.dataframe(pd.DataFrame([{"#": i, "Storage": w.name or "Unnamed storage", "Distance (km)": w.distance_m / 1000,
                                "Disruption risk": w.p_disruption, "Floor area (m²)": w.capacity_m2, "Score": w.utility}
                               for i, w in enumerate(advice.warehouses, 1)]),
                 hide_index=True, width="stretch",
                 column_config={"Distance (km)": st.column_config.NumberColumn(format="%.1f"),
                                "Disruption risk": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
                                "Floor area (m²)": st.column_config.NumberColumn(format="%.0f"),
                                "Score": st.column_config.NumberColumn(format="%.2f")})
    st.caption("Score = closeness × (1 − disruption risk) × storage size: nearer, safer and bigger storage scores "
               "higher. Distances follow the street network.")
else:
    st.caption("No storage found nearby.")
