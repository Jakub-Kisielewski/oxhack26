"""Streamlit entrypoint: backtest summary and route comparison map."""

import streamlit as st

st.set_page_config(page_title="London Protest Route Model", layout="wide")

st.navigation(
    [
        st.Page(
            "src/ui/pages/model_insights.py",
            title="Backtest results",
            icon=":material/insights:",
            default=True,
        ),
        st.Page(
            "src/ui/pages/route_map.py",
            title="Route comparison",
            icon=":material/map:",
        ),
    ]
).run()
