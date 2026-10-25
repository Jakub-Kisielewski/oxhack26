"""Conditions for a march (weather, media attention, calendar) and what they change.

Weather: a live Open-Meteo forecast when the date is within the forecast window, the
recorded value when the date is in the weather archive (past marches), otherwise the
historical average for that month and hour from weather_hourly.
Media attention: the cause's Wikipedia views over the last 7 days of available data
before the march, divided by its 90-day daily average (1 = usual attention).

Effects are labelled by basis: "learned" (route-model weights fitted on past marches),
"data" (measured inputs used directly, e.g. the base turnout), "assumed" (hand-set
multipliers, documented below; there are too few turnout counts to fit them).
"""
from __future__ import annotations

import datetime as dt
import json
import math
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from src.contract import mapdata
from src.contract.types import Effect, MarchConditions, MarchContext
from src.models.features import dark_fraction

LONDON = (51.5074, -0.1278)
TZ = ZoneInfo("Europe/London")
FORECAST_DAYS = 15
MARCH_HOURS = 4
BANK_HOLIDAYS = Path(__file__).resolve().parents[2] / "data" / "route_research" / "raw" / "calendar" / "bank_holidays.json"

# Hand-set turnout multipliers (assumptions, shown to users as such).
SALIENCE_ELASTICITY = 0.5          # turnout ~ spike^0.5, clamped below
SALIENCE_CLAMP = (0.7, 2.0)
RAIN_HEAVY_MM, RAIN_HEAVY_X = 2.0, 0.85
RAIN_LIGHT_MM, RAIN_LIGHT_X = 0.5, 0.93
COLD_C, COLD_X = 3.0, 0.90
HOT_C, HOT_X = 28.0, 0.92
WEEKDAY_DAYTIME_X = 0.70           # most past marches were weekend days
BANK_HOLIDAY_X = 1.10
RAIN_RALLY_X = 0.75                # heavy rain shortens the rally


# ---------- inputs ----------

@lru_cache(maxsize=64)
def _forecast(date: str, hour: int) -> dict | None:
    try:
        r = requests.get("https://api.open-meteo.com/v1/forecast", timeout=4, params={
            "latitude": LONDON[0], "longitude": LONDON[1], "start_date": date, "end_date": date, "timezone": "Europe/London",
            "hourly": "temperature_2m,apparent_temperature,precipitation,wind_gusts_10m"})
        r.raise_for_status()
        h = r.json()["hourly"]
    except (requests.RequestException, KeyError, ValueError):
        return None
    idx = [i for i, t in enumerate(h["time"]) if hour <= int(t[11:13]) < hour + MARCH_HOURS]
    if not idx:
        return None
    pick = lambda k: [h[k][i] for i in idx if h[k][i] is not None]
    return _summary(pick("temperature_2m"), pick("apparent_temperature"), sum(pick("precipitation")),
                    pick("wind_gusts_10m"), "Open-Meteo forecast")


def _summary(temps, apparent, precip, gusts, source) -> dict:
    mean = lambda v: round(sum(v) / len(v), 1) if v else None
    return {"temperature_c": mean(temps), "apparent_temperature_c": mean(apparent),
            "precipitation_mm": round(precip, 1) if precip is not None else None,
            "wind_gust_kmh": round(max(gusts), 1) if gusts else None, "weather_source": source}


def weather(ctx: MarchContext) -> dict:
    day = dt.date.fromisoformat(ctx.date)
    hour = int(ctx.start_time[:2])
    if 0 <= (day - dt.date.today()).days <= FORECAST_DAYS:
        fc = _forecast(ctx.date, hour)
        if fc:
            return fc
    cur = mapdata.cursor()
    try:
        rows = cur.execute("""SELECT temperature_2m, apparent_temperature, precipitation, wind_gusts_10m FROM weather_hourly
                              WHERE CAST(time AS DATE) = ? AND hour(CAST(time AS TIMESTAMP)) BETWEEN ? AND ?""",
                           [day, hour, hour + MARCH_HOURS - 1]).fetchall()
        if rows:
            return _summary([r[0] for r in rows if r[0] is not None], [r[1] for r in rows if r[1] is not None],
                            sum(r[2] or 0 for r in rows), [r[3] for r in rows if r[3] is not None], "Recorded weather")
        rows = cur.execute("""SELECT avg(temperature_2m), avg(apparent_temperature), avg(precipitation) * ?, avg(wind_gusts_10m),
                                     count(DISTINCT CAST(time AS DATE))
                              FROM weather_hourly WHERE month(CAST(time AS TIMESTAMP)) = ?
                              AND hour(CAST(time AS TIMESTAMP)) BETWEEN ? AND ?""",
                           [MARCH_HOURS, day.month, hour, hour + MARCH_HOURS - 1]).fetchone()
    except Exception:   # table missing in a partial database
        rows = None
    if rows and rows[4]:
        return _summary([rows[0]], [rows[1]], rows[2], [rows[3]],
                        f"Historical average for {day.strftime('%B')} ({rows[4]} days of records)")
    return {"temperature_c": None, "apparent_temperature_c": None, "precipitation_mm": None, "wind_gust_kmh": None,
            "weather_source": "unavailable"}


def salience(cause: str | None, day: dt.date) -> dict:
    empty = {"salience_spike": None, "salience_views_7d": None, "salience_as_of": None, "salience_articles": []}
    if not cause:
        return empty
    try:
        rows = mapdata.cursor().execute("""SELECT CAST(date AS DATE) d, sum(views) FROM pageviews_daily
                                           WHERE cause = ? AND CAST(date AS DATE) < ? GROUP BY d ORDER BY d""",
                                        [cause, day]).fetchall()
        articles = [a for (a,) in mapdata.cursor().execute(
            "SELECT DISTINCT article FROM pageviews_daily WHERE cause = ? ORDER BY article", [cause]).fetchall()]
    except Exception:
        return empty
    if not rows:
        return empty
    as_of = rows[-1][0]
    last7 = [v for d, v in rows if (as_of - d).days < 7]
    last90 = [v for d, v in rows if (as_of - d).days < 90]
    base = sum(last90) / len(last90) if last90 else 0
    spike = (sum(last7) / len(last7)) / base if base and last7 else None
    return {"salience_spike": round(spike, 2) if spike else None, "salience_views_7d": int(sum(last7)),
            "salience_as_of": as_of.isoformat(), "salience_articles": articles}


def calendar(ctx: MarchContext) -> dict:
    from astral import LocationInfo
    from astral.sun import sun
    from hijridate import Gregorian
    day = dt.date.fromisoformat(ctx.date)
    start = dt.datetime.combine(day, dt.time.fromisoformat(ctx.start_time), tzinfo=TZ)
    s = sun(LocationInfo("London", "England", "Europe/London", *LONDON).observer, date=day, tzinfo=TZ)
    bank = None
    if BANK_HOLIDAYS.exists():
        events = json.loads(BANK_HOLIDAYS.read_text(encoding="utf-8"))["england-and-wales"]["events"]
        bank = day.isoformat() in {e["date"] for e in events}
    return {"weekday": day.strftime("%A"), "is_weekend": day.weekday() >= 5, "is_bank_holiday": bank,
            "is_ramadan": Gregorian(day.year, day.month, day.day).to_hijri().month == 9,
            "sunset": s["sunset"].strftime("%H:%M"),
            "daylight_after_start_h": round(max(0.0, (s["sunset"] - start).total_seconds() / 3600), 1)}


# ---------- effects ----------

def turnout_effects(c: dict, ctx: MarchContext) -> list[Effect]:
    out = []
    spike = c.get("salience_spike")
    if spike:
        x = min(SALIENCE_CLAMP[1], max(SALIENCE_CLAMP[0], spike ** SALIENCE_ELASTICITY))
        out.append(Effect("turnout", "Media attention", f"x{spike:.2f} usual Wikipedia views", f"x{x:.2f} turnout", x - 1,
                          "assumed", "More public attention in the week before brings more people out."))
    rain = c.get("precipitation_mm")
    if rain is not None and rain >= RAIN_LIGHT_MM:
        x = RAIN_HEAVY_X if rain >= RAIN_HEAVY_MM else RAIN_LIGHT_X
        out.append(Effect("turnout", "Rain", f"{rain:.1f} mm in {MARCH_HOURS} h", f"x{x:.2f} turnout", x - 1,
                          "assumed", "Rain keeps some people at home."))
    feels = c.get("apparent_temperature_c")
    if feels is not None and (feels < COLD_C or feels > HOT_C):
        x = COLD_X if feels < COLD_C else HOT_X
        out.append(Effect("turnout", "Cold" if feels < COLD_C else "Heat", f"feels like {int(round(feels)) + 0}°C",
                          f"x{x:.2f} turnout", x - 1, "assumed", "Uncomfortable temperatures reduce turnout."))
    if not c["is_weekend"] and not c.get("is_bank_holiday") and ctx.start_time < "17:00":
        out.append(Effect("turnout", "Weekday daytime", c["weekday"], f"x{WEEKDAY_DAYTIME_X:.2f} turnout",
                          WEEKDAY_DAYTIME_X - 1, "assumed", "Most past marches were at weekends; fewer people can come "
                          "during working hours."))
    if c.get("is_bank_holiday"):
        out.append(Effect("turnout", "Bank holiday", "yes", f"x{BANK_HOLIDAY_X:.2f} turnout", BANK_HOLIDAY_X - 1,
                          "assumed", "More people are free on bank holidays."))
    return out


def apply_turnout(base: int, effects: list[Effect]) -> int:
    x = 1.0
    for e in effects:
        if e.target == "turnout":
            x *= 1 + e.size
    return max(50, int(round(base * x, -1)))


def route_effects(c: dict, turnout: int, model) -> list[Effect]:
    """How the learned route-model weights respond to this march's rain and turnout."""
    names = list(model.features)
    out = []

    def weight(name):
        i = names.index(name)
        varied = abs(model.std[i] - 1.0) > 1e-9 or abs(model.mean[i]) > 1e-9
        return model.theta[i] / max(model.std[i], 1e-6), varied

    if "rain_x_main" in names:
        w, varied = weight("rain_x_main")
        rain = c.get("precipitation_mm") or 0
        if not varied:
            out.append(Effect("route", "Rain", f"{rain:.1f} mm", "no learned effect", 0.0, "learned",
                              "None of the training marches had rain, so the model couldn't learn how rain changes routes."))
        elif rain >= 0.5:
            lean = "towards" if w > 0 else "away from"
            out.append(Effect("route", "Rain", f"{rain:.1f} mm", f"leans {lean} main roads", w, "learned",
                              f"In past rainy marches, routes leaned {lean} main roads (weight {w:+.2f})."))
        else:
            out.append(Effect("route", "Rain", f"{rain:.1f} mm", "not applied", 0.0, "learned",
                              "Little or no rain expected, so the learned rain effect doesn't change the route."))
    if "dark_x_main" in names:
        w, varied = weight("dark_x_main")
        dark = c.get("dark_fraction") or 0.0
        value = f"{dark:.0%} after sunset ({c['sunset']})"
        basis = "learned" if varied and "dark_x_main" not in model.stats.get("prior_only", []) else "assumed"
        source = ("In past marches that ran after dark," if basis == "learned"
                  else "Too few past marches ran after dark to learn this, so a hand-set prior is used:")
        if dark <= 0:
            out.append(Effect("route", "Darkness", value, "not applied", 0.0, basis,
                              f"The march should finish before sunset, so darkness doesn't change the route. "
                              f"{source} routes lean {'towards' if w > 0 else 'away from'} main roads after dark."))
        else:
            lean = "towards" if w > 0 else "away from"
            out.append(Effect("route", "Darkness", value, f"leans {lean} main roads", w * dark, basis,
                              f"{source} routes lean {lean} main, better-lit roads (weight {w:+.2f} at full "
                              f"darkness, scaled by the {dark:.0%} of the march after sunset)."))
    if "turnout_x_width" in names:
        w, _ = weight("turnout_x_width")
        lean = "wider" if w > 0 else "narrower"
        out.append(Effect("route", "Crowd size", f"{turnout:,} people", f"bigger crowds lean to {lean} streets",
                          w * math.log(max(1, turnout)), "learned",
                          f"The model learned that larger marches prefer {lean} streets (weight {w:+.3f} per log-person "
                          f"per log-metre of width)."))
    return out


def duration_effects(c: dict) -> list[Effect]:
    rain = c.get("precipitation_mm")
    if rain is not None and rain >= RAIN_HEAVY_MM:
        return [Effect("duration", "Rain", f"{rain:.1f} mm in {MARCH_HOURS} h", f"x{RAIN_RALLY_X:.2f} rally length",
                       RAIN_RALLY_X - 1, "assumed", "Heavy rain shortens the rally at the end.")]
    return []


def rowdiness_effects(parts: list[tuple[str, str, float, str]]) -> list[Effect]:
    return [Effect("rowdiness", name, value, f"{delta:+.2f} rowdiness" if name != "Base for this cause" else f"{delta:.2f} base",
                   delta, "assumed", why) for name, value, delta, why in parts]


def estimate(ctx: MarchContext) -> dict:
    """All raw inputs for a march, as a flat dict (also used as model context features)."""
    c = {**weather(ctx), **salience(ctx.cause, dt.date.fromisoformat(ctx.date)), **calendar(ctx)}
    c["salience_spike_ratio"] = c.get("salience_spike")
    c["precip_mm_4h"] = c.get("precipitation_mm") or 0.0
    c["dark_fraction"] = dark_fraction(c.get("daylight_after_start_h"))
    return c


def build(c: dict, base: int, base_source: str, rowdiness: float, effects: list[Effect]) -> MarchConditions:
    keys = ("weather_source", "temperature_c", "apparent_temperature_c", "precipitation_mm", "wind_gust_kmh",
            "salience_spike", "salience_views_7d", "salience_as_of", "salience_articles", "weekday", "is_weekend",
            "is_bank_holiday", "is_ramadan", "sunset", "daylight_after_start_h")
    return MarchConditions(**{k: c.get(k) for k in keys}, turnout_base=base, turnout_base_source=base_source,
                           rowdiness=round(rowdiness, 2), effects=effects)
