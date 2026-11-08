"""Streamlit page: leave-one-event-out backtest charts and per-event table."""

from __future__ import annotations

import streamlit as st

from src.config import BACKTEST_PATH, ROUTE_MODEL_PATH
from src.models.backtest import read_backtest
from src.ui import charts
from src.ui.resources import get_full_model
from src.ui.theta_table import theta_rows


def render() -> None:
    """Draw the backtest insights page."""
    st.title("Leave-one-event-out backtest")
    st.caption(
        "Metrics come from `data/models/backtest.json` after `python -m src.models.train`. "
        "Training data are published march plans joined by shortest paths, not GPS traces."
    )

    bt = read_backtest(BACKTEST_PATH)
    if bt is None:
        st.warning(
            "No backtest file at `data/models/backtest.json`. If you have already run training, "
            "check its output: the file is not written when a model scores no events."
        )
        st.code("python ingest.py\npython -m src.models.train", language="bash")
    else:
        st.markdown(f"**Events evaluated:** {bt.n_events} · **Saved at:** {bt.created_at}")
        charts.backtest_charts(bt)
        with st.expander("Per-event rows"):
            if bt.rows:
                st.dataframe(
                    [
                        {
                            "event_id": r.event_id,
                            "model": r.model,
                            "mean_log_likelihood": r.mean_log_likelihood,
                            "top1_jaccard": r.top1_jaccard,
                        }
                        for r in bt.rows
                    ],
                    width="stretch",
                    column_config={
                        "mean_log_likelihood": st.column_config.NumberColumn(format="%.2f"),
                        "top1_jaccard": st.column_config.NumberColumn(format="%.0f%%"),
                    },
                )
            else:
                st.caption("No per-event rows in this backtest file.")

    if ROUTE_MODEL_PATH.is_file():
        with st.expander("Model coefficients (θ)"):
            coeffs = theta_rows(get_full_model())
            st.dataframe(
                coeffs,
                width="stretch",
                column_config={
                    "theta": st.column_config.NumberColumn(format="%.3f"),
                },
            )
            st.caption(
                "Rows marked prior only were not moved by the training data "
                "(hand-set prior effects)."
            )

    st.subheader("What the model can and can't claim")
    st.markdown(
        """
- **Training data are planned routes.** Past marches are published itineraries joined by
  shortest paths.
- **Small sample.** Leave-one-event-out scores are honest but noisy with few labelled events.
- **What-if is not a forecast.** The route map can replay held-out predictions and exploratory rollouts; it does not score live marches.
"""
    )


render()
