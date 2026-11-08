"""Altair charts for backtest summary metrics."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from src.models.types import BacktestResult

MODEL_COLORS = ["#2a78d6", "#eb6834", "#1baf7a"]
MODEL_LABELS = {
    "route_model": "Route model",
    "shortest_path": "Shortest path",
    "random_walk": "Random walk",
}
METRICS = {
    "mean_log_likelihood": (
        "Log-likelihood per step",
        "Higher is better: probability assigned to the true route, step by step.",
    ),
    "top1_jaccard": (
        "Top route overlap",
        "Share of the true route's streets that the top predicted route uses.",
    ),
}


def backtest_charts(bt: BacktestResult) -> None:
    models = [m for m in MODEL_LABELS if m in bt.summary] + [
        m for m in bt.summary if m not in MODEL_LABELS
    ]
    labels = [MODEL_LABELS.get(m, m) for m in models]
    colors = (MODEL_COLORS * 3)[: len(models)]
    cols = st.columns(len(METRICS))
    for col, (metric, (title, help_text)) in zip(cols, METRICS.items(), strict=False):
        df = pd.DataFrame(
            [
                {"Model": MODEL_LABELS.get(m, m), "Value": bt.summary[m].get(metric)}
                for m in models
                if bt.summary[m].get(metric) is not None
            ]
        )
        if df.empty:
            continue
        fmt = ".2f" if metric == "mean_log_likelihood" else ".0%"
        base = alt.Chart(df).encode(
            x=alt.X("Model:N", sort=labels, title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("Value:Q", title=None, axis=alt.Axis(format=fmt)),
        )
        bars = base.mark_bar(cornerRadiusEnd=4, width={"band": 0.6}).encode(
            color=alt.Color("Model:N", scale=alt.Scale(domain=labels, range=colors), legend=None),
            tooltip=["Model", alt.Tooltip("Value:Q", format=fmt)],
        )
        text = base.mark_text(
            dy=-8 if metric != "mean_log_likelihood" else 12, fontWeight=600
        ).encode(text=alt.Text("Value:Q", format=fmt))
        with col:
            st.markdown(f"**{title}**")
            st.altair_chart((bars + text).properties(height=220), width="stretch")
            n_key = f"{metric}_n"
            n_vals = [bt.summary[m].get(n_key) for m in models if n_key in bt.summary.get(m, {})]
            if n_vals:
                st.caption(f"{help_text} (n={int(n_vals[0])} events per model.)")
            else:
                st.caption(help_text)
    if bt.destination_summary and bt.destination_summary.get("destination_top3_rate") is not None:
        rate = bt.destination_summary["destination_top3_rate"]
        n = int(bt.destination_summary.get("n_events", 0))
        st.markdown(
            f"**Destination model:** true end in top 3 candidates — "
            f"{rate:.0%} ({n} events). "
            "This measures the destination shortlist, not the route logit."
        )
