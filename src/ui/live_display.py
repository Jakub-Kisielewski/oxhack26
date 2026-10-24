"""Display rules for the live map: people-count colours, reading age, staleness, cache-busting."""
import math
import time
from datetime import datetime

import pandas as pd

from src.pipeline.config import SETTINGS

TIER_LABELS = {2: "Route: clips every 15 s", 1: "Central box: stills every 60 s", 0: "Registered, not polled"}
TIER_RADIUS_M = {2: 34, 1: 24, 0: 18}
NO_DATA_COLOUR = [150, 150, 150, 150]
# people count -> colour, interpolated on log1p(count); 10+ people is the darkest
RAMP = [(0, [255, 237, 160]), (2, [254, 178, 76]), (5, [240, 59, 32]), (10, [128, 0, 38])]
DECK_COLUMNS = ["camera_id", "name", "view", "lat", "lon", "tier", "active", "status", "color", "radius",
                "people_txt", "age_txt", "image_url", "video_url"]


def people_colour(people: float) -> list[int]:
    x = math.log1p(max(0.0, people))
    for (p0, c0), (p1, c1) in zip(RAMP, RAMP[1:]):
        x0, x1 = math.log1p(p0), math.log1p(p1)
        if x <= x1:
            f = (x - x0) / (x1 - x0)
            return [round(a + f * (b - a)) for a, b in zip(c0, c1)] + [235]
    return RAMP[-1][1] + [235]


def age_text(seconds: float | None) -> str:
    if seconds is None or pd.isna(seconds):
        return "no reading in the last hour"
    return f"{seconds:.0f} s ago" if seconds < 90 else f"{seconds / 60:.0f} min ago"


def prepare(cams: pd.DataFrame, now: datetime) -> pd.DataFrame:
    """Add display columns: reading age, fresh flag, colour (grey = no data, stale or inactive), tooltip text."""
    cams = cams.fillna({"view": "", "name": ""})
    frame_time = pd.to_datetime(cams["frame_time"], utc=True)
    age_s = (pd.Timestamp(now) - frame_time).dt.total_seconds()
    fresh = cams["people"].notna() & (age_s <= SETTINGS.stale_after_s) & (cams["active"] == 1)
    return cams.assign(
        frame_time=frame_time,
        age_s=age_s,
        fresh=fresh,
        color=[people_colour(p) if f else NO_DATA_COLOUR for p, f in zip(cams["people"], fresh)],
        radius=cams["tier"].map(TIER_RADIUS_M).fillna(18),
        status=["active" if a else "inactive" for a in cams["active"]],
        people_txt=[f"{p:g} people" if f else "no current count" for p, f in zip(cams["people"], fresh)],
        age_txt=[age_text(a) for a in age_s],
    )


def cache_buster(row: pd.Series) -> int:
    """Changes only when TfL publishes new media: the latest frame_time, else a 60 s bucket."""
    if pd.notna(row.get("frame_time")):
        return int(row["frame_time"].timestamp())
    return int(time.time() // 60 * 60)
