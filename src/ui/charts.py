"""Altair charts shared by the pages. Colours follow layers.py; text stays in normal ink."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from src.contract.types import BacktestResult, Driver, SegmentTiming
from src.ui import layers

DIVERGING = {"light": ("#2a78d6", "#e34948"), "dark": ("#3987e5", "#e66767")}   # blue <-> red pair
MODEL_COLORS = {"light": ["#2a78d6", "#eb6834", "#1baf7a"], "dark": ["#3987e5", "#d95926", "#199e70"]}
MODEL_LABELS = {"route_model": "Route model", "shortest_path": "Shortest path", "random_walk": "Random walk"}
METRICS = {"mean_log_likelihood": ("Log-likelihood per step", "Higher is better: how much probability the model "
                                   "gave the real route, step by step."),
           "top1_jaccard": ("Top route overlap", "Share of the real route's streets that the top predicted route uses."),
           "destination_in_top3": ("True end in top 3", "How often the real end point was among the 3 likeliest.")}


def drivers_chart(drivers: list[Driver]) -> None:
    if not drivers:
        st.caption("The model didn't report any explanatory factors.")
        return
    up, down = DIVERGING[layers.mode()]
    df = pd.DataFrame([{"Factor": d.name, "Effect": d.effect, "Value": str(d.value), "Why": d.description,
                        "Direction": "Pushes up" if d.effect >= 0 else "Pushes down"} for d in drivers])
    order = df.sort_values("Effect", ascending=False)["Factor"].tolist()
    bars = alt.Chart(df).mark_bar(cornerRadiusEnd=4, height={"band": 0.6}).encode(
        x=alt.X("Effect:Q", title="Effect on the prediction", scale=alt.Scale(zero=True)),
        y=alt.Y("Factor:N", sort=order, title=None, axis=alt.Axis(labelLimit=260)),
        # Default (right) legend: a top legend is taken out of the fixed height and collapses the bars.
        color=alt.Color("Direction:N", scale=alt.Scale(domain=["Pushes up", "Pushes down"], range=[up, down]),
                        legend=alt.Legend(title=None)),
        tooltip=["Factor", "Value", alt.Tooltip("Effect:Q", format="+.2f"), "Why"])
    st.altair_chart(bars.properties(height=48 * len(df) + 20), width="stretch")
    with st.expander("What these factors mean"):
        for d in drivers:
            st.markdown(f"**{d.name}** ({d.value}): {d.description}")


def backtest_charts(bt: BacktestResult) -> None:
    models = [m for m in MODEL_LABELS if m in bt.summary] + [m for m in bt.summary if m not in MODEL_LABELS]
    labels = [MODEL_LABELS.get(m, m) for m in models]
    colors = (MODEL_COLORS[layers.mode()] * 3)[:len(models)]
    cols = st.columns(len(METRICS))
    for col, (metric, (title, help_text)) in zip(cols, METRICS.items()):
        df = pd.DataFrame([{"Model": MODEL_LABELS.get(m, m), "Value": bt.summary[m].get(metric)} for m in models
                           if bt.summary[m].get(metric) is not None])
        if df.empty:
            continue
        fmt = ".2f" if metric == "mean_log_likelihood" else ".0%"
        base = alt.Chart(df).encode(x=alt.X("Model:N", sort=labels, title=None, axis=alt.Axis(labelAngle=0)),
                                    y=alt.Y("Value:Q", title=None, axis=alt.Axis(format=fmt)))
        bars = base.mark_bar(cornerRadiusEnd=4, width={"band": 0.6}).encode(
            color=alt.Color("Model:N", scale=alt.Scale(domain=labels, range=colors), legend=None),
            tooltip=["Model", alt.Tooltip("Value:Q", format=fmt)])
        text = base.mark_text(dy=-8 if metric != "mean_log_likelihood" else 12, fontWeight=600).encode(
            text=alt.Text("Value:Q", format=fmt))
        with col:
            st.markdown(f"**{title}**")
            st.altair_chart((bars + text).properties(height=220), width="stretch")
            st.caption(help_text)


def los_chart(timeline: list[SegmentTiming], lengths: dict[str, float]) -> None:
    """Share of the route's length at each crowd level (LOS)."""
    total = sum(lengths.get(t.segment_id, 0.0) for t in timeline) or 1.0
    rows = []
    for level in layers.LOS_ORDER:
        share = sum(lengths.get(t.segment_id, 0.0) for t in timeline if t.level_of_service == level) / total
        rows.append({"Level": layers.LOS_LABEL[level], "Share": share})
    df = pd.DataFrame(rows)
    colors = ["#%02x%02x%02x" % tuple(layers.los_color(level)[:3]) for level in layers.LOS_ORDER]
    labels = [layers.LOS_LABEL[level] for level in layers.LOS_ORDER]
    bars = alt.Chart(df).mark_bar(cornerRadiusEnd=4, height={"band": 0.6}).encode(
        x=alt.X("Share:Q", title="Share of the route", axis=alt.Axis(format=".0%")),
        y=alt.Y("Level:N", sort=labels, title=None),
        color=alt.Color("Level:N", scale=alt.Scale(domain=labels, range=colors), legend=None),
        tooltip=["Level", alt.Tooltip("Share:Q", format=".0%")])
    st.altair_chart(bars.properties(height=220), width="stretch")
