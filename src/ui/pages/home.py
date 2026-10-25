import streamlit as st

from src.contract import CONTRACT_VERSION
from src.ui import common

common.page_header("London Protest Predictor",
                   "Predict where a march will go, how crowded it gets, and what shops and police should do about it.")

predictor = common.get_predictor()
status, action = st.columns([3, 1], vertical_alignment="center")
with status:
    if common.is_mock():
        st.markdown(f"**Model:** mock predictor (`{predictor.version}`), illustrative outputs only.")
    else:
        st.markdown(f"**Model:** trained route model `{predictor.version}`")
with action:
    if st.button("Reload model", icon=":material/refresh:", width="stretch",
                 help="Pick up a model trained after the app started."):
        common.reload_predictor()
        st.rerun()

st.subheader("Tools")
tools = [
    ("src/ui/pages/route_predictor.py", "Route predictor", ":material/explore:",
     "From a start point, date and cause: where the march is likely to go and end."),
    ("src/ui/pages/planned_route.py", "Planned route", ":material/route:",
     "For a known route: crowd density over time and where it spills into side streets."),
    ("src/ui/pages/shopkeeper.py", "Shopkeeper advice", ":material/storefront:",
     "Is my shop at risk, when, and which nearby storage is safest for stock."),
    ("src/ui/pages/police.py", "Police allocation", ":material/local_police:",
     "Where a limited number of officers cut the most expected spill."),
    ("src/ui/pages/model_insights.py", "Model insights", ":material/insights:",
     "How the route model performs on past marches against simple baselines."),
    ("src/ui/pages/map_explorer.py", "Map explorer", ":material/map:",
     "Legal zones, protest targets, shops, storage and past march routes."),
]
for row in (tools[:3], tools[3:]):
    for col, (page, label, icon, text) in zip(st.columns(3), row):
        with col.container(border=True):
            st.page_link(page, label=label, icon=icon)
            st.caption(text)

bt = common.backtest()
if bt and "route_model" in bt.summary and "shortest_path" in bt.summary:
    st.subheader("How well it predicts past marches")
    model, base = bt.summary["route_model"], bt.summary["shortest_path"]
    a, b, c = st.columns(3)
    a.metric("Top route overlap", common.pct(model.get("top1_jaccard", 0)),
             f"{(model.get('top1_jaccard', 0) - base.get('top1_jaccard', 0)) * 100:+.0f} pts vs shortest path")
    b.metric("True end in top 3", common.pct(model.get("destination_in_top3", 0)),
             f"{(model.get('destination_in_top3', 0) - base.get('destination_in_top3', 0)) * 100:+.0f} pts vs shortest path")
    c.metric("Log-likelihood per step", f"{model.get('mean_log_likelihood', 0):.2f}",
             f"{model.get('mean_log_likelihood', 0) - base.get('mean_log_likelihood', 0):+.2f} vs shortest path")
    st.caption("Leave-one-event-out over past marches."
               + (" Sample numbers from the mock predictor." if common.is_mock() else ""))

route, overspill = st.session_state.get("route_prediction"), st.session_state.get("overspill_prediction")
if route or overspill:
    st.subheader("This session")
    if route:
        st.markdown(f"**Route prediction:** {common.describe_context(route.request.context)}, "
                    f"likeliest end {route.destinations[0].name if route.destinations else 'unknown'}.")
    if overspill:
        st.markdown(f"**Planned route:** {common.describe_context(overspill.request.context)}, "
                    f"{len([s for s in overspill.spill if s.p_spill >= 0.3])} side streets at high spill risk.")

st.subheader("Data status")
status = common.get_db().cursor().execute(
    "SELECT table_name, rows, loaded_at FROM load_log ORDER BY table_name").df()
if status.empty:
    st.info("No data loaded yet. Run `python ingest.py` with the app closed, then reopen it.")
else:
    st.dataframe(status, hide_index=True, width="stretch",
                 column_config={"table_name": "Table", "rows": st.column_config.NumberColumn("Rows", format="%d"),
                                "loaded_at": st.column_config.DatetimeColumn("Loaded", format="D MMM YYYY, HH:mm")})
st.caption(f"Training routes are published march plans, not GPS traces. Contract v{CONTRACT_VERSION}.")
