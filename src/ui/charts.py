"""Plotly charts for backtest summary metrics."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.models.types import BacktestResult
from src.ui.backtest_analytics import event_level_frame, kpi_values
from src.ui.backtest_display import MODEL_LABELS, model_order
from src.ui.layout import section
from src.ui.plotly_style import GRID, GRID_STRONG, apply_chart_layout, model_marker_color
from src.ui.theta_table import feature_display_name


def _models_in(df: pd.DataFrame) -> list[str]:
    return [m for m in model_order({m: {} for m in MODEL_LABELS}) if m in set(df["model"])]


def _model_label(model_id: str) -> str:
    return MODEL_LABELS.get(model_id, model_id)


def _delta_caption(delta: float | None, suffix: str) -> None:
    if delta is None:
        return
    sign = "↑" if delta >= 0 else "↓"
    color = "#16A34A" if delta >= 0 else "#DC2626"
    st.markdown(
        f'<span style="color:{color};font-size:0.85rem">{sign} {delta:+.3f}{suffix}</span>',
        unsafe_allow_html=True,
    )


def kpi_row(kpi: dict) -> None:
    c1, c2, c3 = st.columns(3)
    dest = kpi.get("dest_rate")
    with c1:
        with st.container(border=True):
            st.metric("Destination top-3 hit rate", f"{dest:.0%}" if dest is not None else "—")
    ll = kpi.get("ll_rm")
    ll_d = kpi.get("ll_delta")
    with c2:
        with st.container(border=True):
            st.metric("Mean log-likelihood", f"{ll:.3f}" if ll is not None else "—")
            _delta_caption(ll_d, " vs shortest path")
    ov = kpi.get("overlap_rm")
    ov_d = kpi.get("overlap_delta")
    with c3:
        with st.container(border=True):
            st.metric("Mean route overlap", f"{ov * 100:.1f}%" if ov is not None else "—")
            if ov_d is not None:
                sign = "↑" if ov_d >= 0 else "↓"
                color = "#16A34A" if ov_d >= 0 else "#DC2626"
                st.markdown(
                    f'<span style="color:{color};font-size:0.85rem">{sign} {ov_d:+.1f} pp vs shortest path</span>',
                    unsafe_allow_html=True,
                )


def overlap_distribution_chart(long_df: pd.DataFrame) -> go.Figure | None:
    df = long_df.dropna(subset=["top1_jaccard"]).copy()
    if df.empty:
        return None
    df["overlap_pct"] = df["top1_jaccard"] * 100.0
    models = _models_in(df)
    labels = [_model_label(m) for m in models]
    fig = go.Figure()
    rng = np.random.default_rng(0)
    for model in models:
        subset = df.loc[df["model"] == model, "overlap_pct"]
        if subset.empty:
            continue
        fig.add_trace(
            go.Box(
                x=subset,
                y=[_model_label(model)] * len(subset),
                orientation="h",
                fillcolor="rgba(0,0,0,0)",
                line=dict(color=GRID_STRONG, width=1),
                boxmean=True,
                boxpoints=False,
                showlegend=False,
            )
        )
        jitter = subset + rng.uniform(-0.4, 0.4, len(subset))
        fig.add_trace(
            go.Scatter(
                x=jitter,
                y=[_model_label(model)] * len(subset),
                mode="markers",
                marker=dict(size=3, color="rgba(148,163,184,0.35)"),
                hovertemplate="%{x:.1f}%<extra></extra>",
                showlegend=False,
            )
        )
    fig.update_yaxes(categoryorder="array", categoryarray=labels[::-1])
    apply_chart_layout(fig, height=220, x_title="Overlap (%)", x_dtick=20, x_range=(0, 100))
    return fig


def theta_parameters_table(rows: list[dict]) -> None:
    """Two-column parameter table (replaces bar chart)."""
    if not rows:
        return
    table = pd.DataFrame(
        [
            {
                "Parameter": feature_display_name(str(r["feature"])),
                "Value": float(r["theta"]),
            }
            for r in rows
        ]
    )
    st.dataframe(
        table,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Parameter": st.column_config.TextColumn("Parameter", width="large"),
            "Value": st.column_config.NumberColumn("Value", format="%.3f"),
        },
    )


def backtest_charts(bt: BacktestResult) -> None:
    long_df = event_level_frame(bt.rows)
    kpi = kpi_values(bt)

    with section("Metrics"):
        kpi_row(kpi)

    dist = overlap_distribution_chart(long_df)
    if dist is not None:
        with section("Overlap by event"):
            st.plotly_chart(dist, use_container_width=True, config={"displayModeBar": False})
