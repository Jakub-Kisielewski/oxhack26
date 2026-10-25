import pandas as pd
import streamlit as st
import altair as alt

from src.contract import CONTRACT_VERSION
from src.ui import charts, common

common.page_header("Model insights", "How well the route model predicts past marches, and what drives its predictions.")

predictor = common.get_predictor()
st.markdown(f"**Model:** `{predictor.name}` version `{predictor.version}` (contract v{CONTRACT_VERSION})")

st.subheader("Backtest on past marches")
st.caption("Illustrative comparison with manually specified metrics.")

models = ["Route model", "Shortest path", "Random walk"]

colors = alt.Scale(
    domain=models,
    range=["#2F80ED", "#F26B38", "#18A878"]
)

def draw_chart(values, labels, y_min, y_max, percent=False):
    df = pd.DataFrame({
        "Model": models,
        "Value": values,
        "Label": labels
    })

    x = alt.X("Model:N", sort=models, title=None,
              axis=alt.Axis(labelAngle=0))

    y = alt.Y(
        "Value:Q",
        title=None,
        scale=alt.Scale(domain=[y_min, y_max])
    )

    bars = alt.Chart(df).mark_bar(
        size=65,
        cornerRadiusEnd=5
    ).encode(
        x=x,
        y=y,
        color=alt.Color("Model:N", scale=colors, legend=None),
        tooltip=["Model:N", "Label:N"]
    )

    text = alt.Chart(df).mark_text(
        dy=12 if y_max == 0 else -10,
        fontWeight="bold",
        fontSize=13
    ).encode(
        x=x,
        y=y,
        text="Label:N"
    )

    return (bars + text).properties(height=300)


col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("**Log-likelihood per step**")
    st.altair_chart(
        draw_chart(
            [-0.1148, -0.1499, -0.1717],
            ["-0.11", "-0.15", "-0.17"],
            -0.20, 0
        ),
        use_container_width=True
    )

with col2:
    st.markdown("**Top route overlap**")
    st.altair_chart(
        draw_chart(
            [33, 29, 0],
            ["33%", "29%", "0%"],
            0, 40
        ),
        use_container_width=True
    )

with col3:
    st.markdown("**True end in top 3**")
    st.altair_chart(
        draw_chart(
            [75, 72, 0],
            ["75%", "72%", "0%"],
            0, 90
        ),
        use_container_width=True
    )
st.subheader("What drives the latest route prediction")
route = st.session_state.get("route_prediction")
if route:
    st.caption(common.describe_context(route.request.context))
    charts.drivers_chart(route.drivers)
else:
    st.caption("Predict a route to see its drivers here.")
    st.page_link("src/ui/pages/route_predictor.py", label="Predict a route", icon=":material/explore:")

st.subheader("What the model can and can't claim")
st.markdown("""
- **Training data are planned routes.** Past marches are published march plans joined by shortest paths,
  not GPS traces, so the model predicts likely *planned* routes.
- **Overspill is physics-based.** There are no recorded overspill events, so density and spill use hand-set
  coefficients (crowd density against street width, march speed about 2.5 km/h).
- **Approximate geography.** Some legal-zone outlines and target locations are hand-drawn approximations.
""")
