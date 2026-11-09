"""Shared Plotly layout for backtest charts."""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

TEXT = "#0F172A"
GRID = "rgba(15,23,42,0.08)"
GRID_STRONG = "rgba(15,23,42,0.25)"
FONT = dict(family="Inter, sans-serif", size=13, color=TEXT)
ACCENT = "#2563EB"
NEGATIVE = "#F59E0B"

pio.templates["route"] = go.layout.Template(
    layout=dict(
        font=FONT,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=8, r=8, t=48, b=8),
        xaxis=dict(
            showgrid=True,
            gridcolor=GRID,
            zeroline=False,
            ticks="",
            linecolor="rgba(15,23,42,0.15)",
        ),
        yaxis=dict(showgrid=False, zeroline=False, ticks="", showline=False),
        colorway=["#2563EB", "#94A3B8", "#CBD5E1"],
        hoverlabel=dict(bgcolor="#0F172A", font_size=12, font_color="#FFFFFF"),
    )
)
pio.templates.default = "route"


def model_marker_color(model_id: str) -> str:
    from src.ui.backtest_display import MODEL_PALETTE_HEX

    return MODEL_PALETTE_HEX.get(model_id, "#94A3B8")


def apply_chart_layout(
    fig: go.Figure,
    *,
    title: str | None = None,
    height: int = 220,
    x_title: str | None = None,
    y_title: str | None = None,
    x_dtick: float | None = None,
    x_range: tuple[float, float] | None = None,
) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, font=dict(size=13, color=TEXT), x=0, xanchor="left") if title else None,
        font=FONT,
        height=height,
        showlegend=False,
    )
    fig.update_xaxes(
        title_text=x_title or "",
        showline=False,
        showgrid=True,
        gridcolor=GRID,
        dtick=x_dtick,
        range=list(x_range) if x_range else None,
    )
    fig.update_yaxes(title_text=y_title or "", showline=False, showgrid=False)
    return fig
