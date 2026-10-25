"""'Conditions & effects' panel: what the model assumed about the day and what each factor changed."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from src.contract.types import Effect, MarchConditions, Prediction, TurnoutEstimate, risk_level
from src.ui import common, layers
from src.ui.charts import DIVERGING

BASIS = {"learned": "Learned from past marches", "assumed": "Hand-set assumption", "data": "Measured input"}
TARGET = {"turnout": "Turnout", "route": "Route", "rowdiness": "Rowdiness", "duration": "Duration"}


def _fmt(v, unit: str = "", digits: int = 1) -> str:
    return "-" if v is None else f"{v:.{digits}f}{unit}"


def _tiles(c: MarchConditions) -> None:
    a, b, m, d = st.columns(4)
    a.metric("Temperature", _fmt(c.temperature_c, "°C"),
             f"feels like {_fmt(c.apparent_temperature_c, '°C')}" if c.apparent_temperature_c is not None else None,
             delta_color="off", delta_arrow="off", help=c.weather_source)
    b.metric("Rain (first 4 h)", _fmt(c.precipitation_mm, " mm"),
             f"gusts {_fmt(c.wind_gust_kmh, ' km/h', 0)}" if c.wind_gust_kmh is not None else None,
             delta_color="off", delta_arrow="off", help=c.weather_source)
    m.metric("Media attention", f"x{c.salience_spike:.2f}" if c.salience_spike else "no data",
             f"{c.salience_views_7d:,} views in 7 days" if c.salience_views_7d else None, delta_color="off",
             delta_arrow="off", help="Wikipedia views of the cause's articles in the last 7 days of data, against "
                                     "their 90-day average (x1 = usual)."
                                     + (f" Articles: {', '.join(c.salience_articles)}." if c.salience_articles else ""))
    flags = [f for f, on in (("bank holiday", c.is_bank_holiday), ("Ramadan", c.is_ramadan)) if on]
    d.metric("Day", c.weekday, ", ".join(flags) if flags else f"sunset {c.sunset}", delta_color="off", delta_arrow="off",
             help=f"Sunset {c.sunset}: {c.daylight_after_start_h:.1f} h of daylight after the start.")
    notes = [f"Weather: {c.weather_source[:1].lower() + c.weather_source[1:]}."]
    if c.salience_as_of:
        notes.append(f"Media attention as of {c.salience_as_of}.")
    st.caption(" ".join(notes))


def _turnout_waterfall(c: MarchConditions, turnout: TurnoutEstimate, effects: list[Effect]) -> None:
    rows, running = [{"Step": "Base", "Start": 0, "End": c.turnout_base, "Kind": "Total",
                      "Label": f"{c.turnout_base:,}", "Why": c.turnout_base_source}], float(c.turnout_base)
    for e in effects:
        new = running * (1 + e.size)
        rows.append({"Step": e.factor, "Start": running, "End": new, "Kind": "Up" if new >= running else "Down",
                     "Label": e.effect, "Why": f"{e.value}: {e.description}"})
        running = new
    rows.append({"Step": "Expected", "Start": 0, "End": turnout.expected, "Kind": "Total",
                 "Label": f"{turnout.expected:,}", "Why": f"Range {turnout.low:,} to {turnout.high:,}"})
    df = pd.DataFrame(rows)
    up, down = DIVERGING[layers.mode()]
    order = df["Step"].tolist()
    base = alt.Chart(df).encode(x=alt.X("Step:N", sort=order, title=None, axis=alt.Axis(labelAngle=0)))
    bars = base.mark_bar(cornerRadius=3, width={"band": 0.6}).encode(
        y=alt.Y("Start:Q", title="People"), y2="End:Q",
        color=alt.Color("Kind:N", scale=alt.Scale(domain=["Total", "Up", "Down"], range=["#8a8984", up, down]),
                        legend=alt.Legend(title=None)),
        tooltip=["Step", "Label", "Why"])
    text = base.mark_text(dy=-8, fontWeight=600).encode(y="End:Q", text="Label:N")
    st.altair_chart((bars + text).properties(height=260), width="stretch")


def show(prediction: Prediction) -> None:
    c = prediction.conditions
    if c is None:
        st.info("This predictor doesn't report the conditions it assumed"
                + (" (the mock predictor never does)." if common.is_mock() else "."), icon=":material/info:")
        return
    _tiles(c)

    effects = c.effects
    turnout_fx = [e for e in effects if e.target == "turnout"]
    st.markdown("**Turnout**")
    if prediction.turnout.source == "user":
        st.caption(f"Set to {prediction.turnout.expected:,} by you, so no adjustments were applied.")
    elif not turnout_fx:
        st.caption(f"{prediction.turnout.expected:,} people: the {c.turnout_base_source}. Nothing about the day "
                   "(media attention, weather, weekday, bank holiday) moved it.")
    else:
        _turnout_waterfall(c, prediction.turnout, turnout_fx)
        st.caption(f"Starts from the {c.turnout_base_source}, then each factor multiplies it.")

    left, right = st.columns(2)
    with left:
        st.markdown("**Rowdiness**")
        level = risk_level(c.rowdiness)
        common.risk_badge(level)
        st.metric("Volatility score", f"{c.rowdiness:.2f}")
        for e in [e for e in effects if e.target == "rowdiness"]:
            st.markdown(f"- **{e.factor}** ({e.value}): {e.effect}. {e.description}")
    with right:
        st.markdown("**Route**")
        for e in [e for e in effects if e.target == "route"] or []:
            st.markdown(f"- **{e.factor}** ({e.value}): {e.effect}. {e.description}")
        dur = [e for e in effects if e.target == "duration"]
        if dur:
            st.markdown("**Duration**")
            for e in dur:
                st.markdown(f"- **{e.factor}** ({e.value}): {e.effect}. {e.description}")
