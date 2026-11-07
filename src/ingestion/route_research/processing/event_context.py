#!/usr/bin/env python3
"""Per-event context for the route model: cause, precipitation, daylight.

Input:
 --events   seed/events.csv (`cause` optional; derived from text when missing)
 --weather  raw/weather/hourly.csv (download_weather.py)
Output: normalised/event_context.csv (event_id, event_date, cause, precip_mm_4h, daylight_after_start_h)

Weather: archive rows when available; forecast rows for prediction-time inputs (same as download_weather).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from astral import LocationInfo
from astral.sun import sun

LONDON = LocationInfo("London", "England", "Europe/London", 51.5074, -0.1278)
TZ = ZoneInfo("Europe/London")
DEFAULT_START = dt.time(12, 0)
WEATHER_WINDOW_H = 4
# First match wins, so counter-protests are classed before the causes they oppose.
CAUSE_KEYWORDS = [
    (
        "anti_racism",
        [
            "stand up to racism",
            "counter-protest",
            "counter-march",
            "against the far",
            "anti-racism",
            "together alliance",
        ],
    ),
    ("palestine", ["gaza", "palestin", "nakba", "al quds", "israel", "rafah"]),
    ("iran", ["iran"]),
    ("anti_trump", ["trump"]),
    (
        "far_right",
        ["unite the kingdom", "uniting the kingdom", "anti-immigration", "tommy robinson"],
    ),
    ("climate_nature", ["nature", "climate"]),
    ("trade_union", ["cost of living", "trades union", "tuc"]),
    ("digital_id", ["digital id"]),
    ("animal_rights", ["animal"]),
    ("sudan", ["sudan"]),
    ("ethiopia", ["amhara", "ethiopia"]),
    ("armenia", ["armenian"]),
    ("kashmir", ["kashmir", "awami"]),
    ("ukraine", ["ukrain", "vyshyvanka"]),
    ("trans_rights", ["trans+", "trans pride", "transgender"]),
    ("lgbtq", ["pride", "lesbian"]),
    ("education", ["student", "universit", "academ"]),
]
FIELDS = ["event_id", "event_date", "cause", "precip_mm_4h", "daylight_after_start_h"]

logger = logging.getLogger(__name__)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def parse_start(value: object) -> dt.time:
    """March start time for daylight; noon default when seed row has no time (feature 12)."""
    try:
        return dt.time.fromisoformat(str(value).strip()[:5])
    except (ValueError, AttributeError):
        return DEFAULT_START


def derive_cause(event: dict[str, str]) -> str:
    """Load-bearing for feature 7 (`target_pull`) and cause_targets for all seed events."""
    text = " ".join(
        event.get(key) or "" for key in ("motivation", "organiser", "event_name")
    ).lower()
    return next(
        (cause for cause, words in CAUSE_KEYWORDS if any(word in text for word in words)), ""
    )


def daylight_hours_after_start(day: dt.date, start: dt.time) -> float:
    sun_times = sun(LONDON.observer, date=day, tzinfo=TZ)
    start_dt = dt.datetime.combine(day, start, tzinfo=TZ)
    return round(max(0.0, (sun_times["sunset"] - start_dt).total_seconds() / 3600), 2)


def index_weather(rows: list[dict[str, str]]) -> dict[dt.datetime, dict[str, str]]:
    """time -> row, preferring observed archive values over forecasts."""
    out: dict[dt.datetime, dict[str, str]] = {}
    for row in rows:
        moment = dt.datetime.fromisoformat(row["time"])
        if moment not in out or row["source"] == "archive":
            out[moment] = row
    return out


def precip_mm_4h(
    weather: dict[dt.datetime, dict[str, str]], day: dt.date, start: dt.time
) -> float | None:
    """Sum precipitation over the first WEATHER_WINDOW_H hours from start (feature 11 `rain_x_main`)."""
    t0 = dt.datetime.combine(day, start).replace(minute=0)
    hours = [
        weather[t]
        for t in (t0 + dt.timedelta(hours=i) for i in range(WEATHER_WINDOW_H))
        if t in weather
    ]
    if not hours:
        return None
    amounts = [
        float(hour["precipitation"])
        for hour in hours
        if hour.get("precipitation") not in (None, "")
    ]
    return round(sum(amounts), 2) if amounts else None


def build_row(
    event: dict[str, str], cause_column: str, weather: dict[dt.datetime, dict[str, str]]
) -> dict:
    day = dt.date.fromisoformat(event["event_date"])
    start = parse_start(event.get("start_time") or event.get("start_or_assembly_time"))
    cause = (event.get(cause_column) or "").strip() or derive_cause(event)
    return {
        "event_id": event["event_id"],
        "event_date": day.isoformat(),
        "cause": cause,
        "precip_mm_4h": precip_mm_4h(weather, day, start),
        "daylight_after_start_h": daylight_hours_after_start(day, start),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", default="seed/events.csv")
    parser.add_argument("--weather", default="raw/weather/hourly.csv")
    parser.add_argument("--cause-column", default="cause")
    parser.add_argument("--output", default="normalised/event_context.csv")
    args = parser.parse_args()
    events = read_csv(Path(args.events))
    if events and args.cause_column not in events[0]:
        logger.info(
            "No `%s` column in events.csv; deriving cause from motivation/organiser/event_name",
            args.cause_column,
        )
    weather_path = Path(args.weather)
    weather = index_weather(read_csv(weather_path)) if weather_path.exists() else {}
    if not weather:
        logger.warning("%s missing; precip_mm_4h left empty", weather_path)
    rows = [
        build_row(event, args.cause_column, weather) for event in events if event.get("event_date")
    ]
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved context for {len(rows)} events to {output}")


if __name__ == "__main__":
    main()
