"""The shared march-context widget (date, start time, cause, organiser, turnout).

The context lives in st.session_state["ctx"] so every page starts from the same
values. Each page renders the form with its own key prefix; `set_context` replaces
the context (e.g. from a historical march) and resets that page's widgets to it.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

import streamlit as st

from src.contract.types import MarchContext
from src.ui import common

FIELDS = ("date", "time", "cause", "organiser", "turnout")


def default_context() -> MarchContext:
    today = dt.date.today()
    saturday = today + dt.timedelta(days=(5 - today.weekday()) % 7)   # most national marches are on Saturdays
    return MarchContext(date=saturday.isoformat(), start_time="12:00")


def current_context() -> MarchContext:
    return st.session_state.get("ctx") or default_context()


def set_context(ctx: MarchContext, prefix: str) -> None:
    st.session_state["ctx"] = ctx
    for field in FIELDS:
        st.session_state.pop(f"{prefix}_{field}", None)


def context_form(prefix: str) -> MarchContext:
    ctx = current_context()
    options: list[Optional[str]] = [None] + [c.key for c in common.causes()]
    if ctx.cause and ctx.cause not in options:
        options.append(ctx.cause)
    labels = {c.key: f"{c.label} ({c.n_events} past marches)" if c.n_events else c.label for c in common.causes()}

    date = st.date_input("Date", value=dt.date.fromisoformat(ctx.date), key=f"{prefix}_date", format="DD/MM/YYYY")
    start = st.time_input("Start time", value=dt.time.fromisoformat(ctx.start_time), step=dt.timedelta(minutes=15),
                          key=f"{prefix}_time")
    cause = st.selectbox("Cause", options, index=options.index(ctx.cause) if ctx.cause in options else 0,
                         format_func=lambda k: "Unknown / other" if k is None else labels.get(k, k), key=f"{prefix}_cause",
                         help="Decides which places the march is drawn towards.")
    organiser = st.text_input("Organiser (optional)", value=ctx.organiser or "", key=f"{prefix}_organiser")
    turnout = st.number_input("Expected turnout", min_value=0, step=1000, value=int(ctx.turnout or 0),
                              key=f"{prefix}_turnout", help="Leave at 0 to let the model estimate it.")
    new = MarchContext(date=date.isoformat(), start_time=start.strftime("%H:%M"), cause=cause,
                       organiser=organiser.strip() or None, turnout=int(turnout) or None)
    st.session_state["ctx"] = new
    return new
