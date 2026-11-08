"""Altair charts for backtest summary metrics."""

from __future__ import annotations

import itertools

import altair as alt
import pandas as pd
import streamlit as st

from src.models.types import BacktestResult
from src.ui.backtest_display import (
    METRICS,
    MODEL_LABELS,
    event_count_caption,
    metric_format,
    model_order,
)

# Slot 1 must match primaryColor in .streamlit/config.toml.
MODEL_COLORS = ["#2a78d6", "#eb6834", "#1baf7a"]


def backtest_charts(bt: BacktestResult) -> None:
    """Render summary bar charts and destination headline for one backtest."""
    models = model_order(bt.summary)
    labels = [MODEL_LABELS.get(m, m) for m in models]
    colors = list(itertools.islice(itertools.cycle(MODEL_COLORS), len(models)))
    cols = st.columns(len(METRICS))
    for col, (metric, spec) in zip(cols, METRICS.items(), strict=False):
        title, help_text, _ = spec
        df = pd.DataFrame(
            [
                {"Model": MODEL_LABELS.get(m, m), "Value": bt.summary[m].get(metric)}
                for m in models
                if bt.summary[m].get(metric) is not None
            ]
        )
        if df.empty:
            continue
        fmt = metric_format(metric)
        base = alt.Chart(df).encode(
            x=alt.X("Model:N", sort=labels, title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("Value:Q", title=None, axis=alt.Axis(format=fmt)),
        )
        bars = base.mark_bar(cornerRadiusEnd=4, width={"band": 0.6}).encode(
            color=alt.Color("Model:N", scale=alt.Scale(domain=labels, range=colors), legend=None),
            tooltip=["Model", alt.Tooltip("Value:Q", format=fmt)],
        )
        # Log-likelihood is negative so bars extend downward; label sits below the bar.
        text_dy = 12 if metric == "mean_log_likelihood" else -8
        text = base.mark_text(dy=text_dy, fontWeight=600).encode(
            text=alt.Text("Value:Q", format=fmt)
        )
        with col:
            st.markdown(f"**{title}**")
            st.altair_chart((bars + text).properties(height=220), width="stretch")
            st.caption(event_count_caption(help_text, bt.summary, metric, models))
    if bt.destination_summary and bt.destination_summary.get("destination_top3_rate") is not None:
        rate = bt.destination_summary["destination_top3_rate"]
        n = int(bt.destination_summary.get("n_events", 0))
        st.markdown(
            f"**Destination model:** true end in top 3 candidates — "
            f"{rate:.0%} ({n} events). "
            "This measures the destination shortlist, not the route logit."
        )
