import pandas as pd
import streamlit as st

from src.contract import CONTRACT_VERSION
from src.ui import charts, common

common.page_header("Model insights", "How well the route model predicts past marches, and what drives its predictions.")

predictor = common.get_predictor()
st.markdown(f"**Model:** `{predictor.name}` version `{predictor.version}` (contract v{CONTRACT_VERSION})")

bt = common.backtest()
st.subheader("Backtest on past marches")
if not bt:
    st.info("No backtest results yet. They are created by `python -m src.models.train`.", icon=":material/insights:")
else:
    st.caption(f"Each past march is held out in turn, the model is fitted on the others and asked to predict it "
               f"({bt.n_events} marches). Baselines: the shortest path to the likeliest end, and a random walk."
               + (" These are sample numbers from the mock predictor." if common.is_mock() else ""))
    charts.backtest_charts(bt)
    with st.expander("Per-march results"):
        metric = st.selectbox("Metric", list(charts.METRICS), format_func=lambda m: charts.METRICS[m][0])
        df = pd.DataFrame([{"March": r.event_id, "Model": charts.MODEL_LABELS.get(r.model, r.model),
                            "Value": float(getattr(r, metric))} for r in bt.rows])
        if not df.empty:
            st.dataframe(df.pivot_table(index="March", columns="Model", values="Value").reset_index(),
                         hide_index=True, width="stretch")

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
- **Training data are planned routes.** The 65 past events are published march plans joined by shortest paths,
  not GPS traces, so the model predicts likely *planned* routes.
- **Small data.** About 56 marches have a known cause, so the model is deliberately small and regularised.
- **Overspill is physics-based.** There are no recorded overspill events, so density and spill use hand-set
  coefficients (crowd density against street width, march speed about 2.5 km/h).
- **Approximate geography.** Some legal-zone outlines and target locations are hand-drawn approximations.
""")
