"""Streamlit page: leave-one-event-out backtest charts."""

from __future__ import annotations

import streamlit as st

from src.config import BACKTEST_PATH, ROUTE_MODEL_PATH
from src.models.backtest import read_backtest
from src.ui import charts
from src.ui.layout import page_body, section
from src.ui.resources import get_full_model
from src.ui.theta_table import theta_rows


def render() -> None:
    with page_body():
        st.title("Model performance")

        bt = read_backtest(BACKTEST_PATH)
        if bt is None:
            st.warning("No model performance data found. Run `python -m src.models.train`.")
            return

        charts.backtest_charts(bt)

        if ROUTE_MODEL_PATH.is_file():
            with section("Model parameters"):
                charts.theta_parameters_table(theta_rows(get_full_model()))


render()
