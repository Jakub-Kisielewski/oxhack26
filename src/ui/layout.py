"""Shared Streamlit layout helpers."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import streamlit as st

MAX_CONTENT_PX = 1150


def inject_layout_css() -> None:
    st.markdown(
        f"""
        <style>
        [data-testid="stMainBlockContainer"] {{
            max-width: {MAX_CONTENT_PX}px;
            margin-left: auto;
            margin-right: auto;
        }}
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
        html, body, [class*="css"] {{
            font-family: Inter, sans-serif;
        }}
        /* Event picker: closed value + portaled Baseweb menu */
        [data-testid="stSelectbox"] [data-baseweb="select"] > div {{
            overflow: visible !important;
        }}
        [data-testid="stSelectbox"] [data-baseweb="select"] span {{
            overflow: visible !important;
            text-overflow: clip !important;
            white-space: nowrap !important;
        }}
        div[data-baseweb="popover"] [data-baseweb="menu"] {{
            min-width: 24rem !important;
            width: max-content !important;
        }}
        div[data-baseweb="popover"] [data-baseweb="menu"] li {{
            white-space: nowrap !important;
        }}
        .route-event-title {{
            font-size: 1.35rem;
            font-weight: 600;
            margin: 0 0 0.15rem 0;
            line-height: 1.3;
        }}
        .route-event-sub {{
            color: #5c6370;
            font-size: 0.9rem;
            margin: 0 0 0.75rem 0;
        }}
        .route-event-stops {{
            font-size: 0.92rem;
            line-height: 1.55;
            margin: 0;
            color: #31333f;
        }}
        .route-event-stops-label {{
            font-size: 0.75rem;
            font-weight: 600;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            color: #808495;
            margin: 0 0 0.35rem 0;
        }}
        .route-event-metrics {{
            display: grid;
            grid-template-columns: minmax(0, 0.95fr) minmax(0, 1.15fr) minmax(0, 1.25fr);
            gap: 0.75rem 1.25rem;
            margin: 0 0 0.85rem 0;
        }}
        .route-event-metric {{
            min-width: 0;
        }}
        .route-event-metric .k {{
            display: block;
            font-size: 0.8rem;
            color: #808495;
            margin-bottom: 0.2rem;
        }}
        .route-event-metric .v {{
            display: block;
            font-size: 1.05rem;
            font-weight: 600;
            line-height: 1.35;
            color: #31333f;
            overflow-wrap: anywhere;
        }}
        .map-legend-label {{
            display: inline-flex;
            align-items: center;
            gap: 0.3rem;
            white-space: nowrap;
            font-size: 0.85rem;
            line-height: 1.25;
            color: #31333f;
        }}
        .map-legend-swatch {{
            font-weight: 600;
            font-size: 1.05rem;
            line-height: 1;
        }}
        .map-legend-square {{
            display: inline-block;
            width: 0.72rem;
            height: 0.72rem;
            border-radius: 2px;
            flex-shrink: 0;
        }}
        [data-testid="stHorizontalBlock"]:has(.map-legend-marker) {{
            align-items: center !important;
            padding: 0.35rem 0 0.65rem 0;
        }}
        [data-testid="stHorizontalBlock"]:has(.map-legend-marker) [data-testid="stCheckbox"] {{
            margin-bottom: 0 !important;
            padding-right: 0 !important;
        }}
        [data-testid="stHorizontalBlock"]:has(.map-legend-marker)
            [data-testid="column"] [data-testid="stHorizontalBlock"] {{
            gap: 0.2rem !important;
        }}
        [data-testid="stHorizontalBlock"]:has(.map-legend-marker)
            [data-testid="column"] [data-testid="stCheckbox"] label {{
            min-width: 0 !important;
            padding-left: 0 !important;
        }}
        [data-testid="stHorizontalBlock"]:has(.map-legend-marker)
            [data-testid="column"] [data-testid="stVerticalBlockBorderWrapper"] {{
            padding-left: 0 !important;
        }}
        .route-event-nav-title {{
            text-align: center;
            font-size: 1.05rem;
            font-weight: 600;
            color: #1e293b;
            margin: 0.35rem 0;
        }}
        [data-testid="stHorizontalBlock"]:has(.route-event-nav-marker) button {{
            font-size: 1rem !important;
            font-weight: 600 !important;
            min-height: 2.6rem;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


@contextmanager
def page_body() -> Iterator[Any]:
    inject_layout_css()
    yield st.container()


@contextmanager
def section(title: str) -> Iterator[Any]:
    with st.container(border=True):
        st.markdown(f"**{title}**")
        yield st.container()
