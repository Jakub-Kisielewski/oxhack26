import pandas as pd
import streamlit as st

from src.ui import common, layers

common.page_header("Police allocation", "Where a limited number of officers cut the most expected spill into side streets.")

prediction = st.session_state.get("overspill_prediction")
if not prediction:
    common.need_prediction("overspill")
    st.stop()
ctx = prediction.request.context

with st.sidebar:
    st.subheader("Officers")
    officers = st.slider("Officers available", 0, 500, 100, step=5, key="police_officers")
    st.caption(f"For: {common.describe_context(ctx)}")

alloc = common.allocate_police(prediction, officers)
if not alloc:
    st.stop()

before, after = alloc.expected_spill_before, alloc.expected_spill_after
cut = (before - after) / before if before else 0.0
m1, m2, m3 = st.columns(3)
m1.metric("Expected spill events", f"{after:.1f}", f"{after - before:+.1f} with officers", delta_color="inverse",
          help="Sum of spill probabilities over all side streets: the number of side streets expected to see spill.")
m2.metric("Reduction", common.pct(cut))
m3.metric("Posts", f"{len(alloc.posts)}", f"{sum(p.officers for p in alloc.posts)} officers placed", delta_color="off", delta_arrow="off")

names = common.street_names(tuple(p.segment_id for p in alloc.posts))
deck_layers = [layers.boundary_layer(), layers.route_outline_layer([s.path for s in prediction.timeline]),
               layers.spill_layer(prediction.spill, ctx), layers.police_layer(alloc.posts, names)]
layers.show(layers.deck(deck_layers, layers.view_for([p for s in prediction.timeline for p in s.path])), key="police_deck")
layers.legend([("Police post (size = officers)", layers.aqua_css(), "dot"),
               ("March route", layers.ink_css("muted"), "line")])
layers.ramp_legend("Side-street spill risk:", ramp="orange")

st.subheader("Posts")
if alloc.posts:
    st.dataframe(pd.DataFrame([{"Officers": p.officers, "Street": names.get(p.segment_id) or "Side street",
                                "Spill cut here": p.expected_spill_reduction} for p in alloc.posts]),
                 hide_index=True, width="stretch",
                 column_config={"Spill cut here": st.column_config.NumberColumn(format="%.2f")})
else:
    st.caption("No officers placed. Increase the number of officers.")
st.caption("Officers are placed in small units, each where it cuts expected spill the most. Each extra officer at "
           "the same street helps a little less (diminishing returns), so officers spread over the riskiest streets.")
