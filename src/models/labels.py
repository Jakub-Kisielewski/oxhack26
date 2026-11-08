"""Build labels using *only* historical announced waypoints; interpolation gets 0.3 weight."""

from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
from src.database import mapdata
from src.models.features import dark_fraction
from src.config import DEFAULT_TURNOUT, INTERPOLATED_WEIGHT, WAYPOINT_LABEL_RADIUS_M
from src.models.graph import MarchGraph


@dataclass
class TrainingEvent:
    """One labelled march: snapped route, per-segment weights, and model context."""

    event_id: str
    date: str
    cause: str | None
    context: dict
    destination: tuple[float, float]
    route: list[str]
    weight: list[float]
    destination_name: str = ""


def read_events(
    g: MarchGraph, interpolated_weight: float = INTERPOLATED_WEIGHT
) -> list[TrainingEvent]:
    """Load protest events from DuckDB and snap waypoints onto ``g``."""
    historic = mapdata.historical_events(protests_only=True)
    ctx_rows = (
        mapdata.cursor()
        .execute("""SELECT event_id, precip_mm_4h, daylight_after_start_h FROM event_context""")
        .fetchall()
    )
    rains = {str(k): float(x or 0) for k, x, _ in ctx_rows}
    daylight = {str(k): d for k, _, d in ctx_rows}
    time_rows = mapdata.cursor().execute(
        """SELECT event_id, start_time, end_time FROM events"""
    ).fetchall()
    march_hours: dict[str, float] = {}
    for eid, start, end in time_rows:
        eid = str(eid)
        if start is not None and end is not None:
            delta = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
            if delta > 0:
                march_hours[eid] = delta / 60.0
    from src.config import MARCH_HOURS as default_hours

    darks = {
        eid: dark_fraction(daylight.get(eid), march_hours.get(eid, default_hours)) for eid in rains
    }
    output = []
    for e in historic:
        if len(e.waypoints) < 2:
            continue
        pts = [p for _, p in e.waypoints]
        route = g.snap_route(pts)
        if len(route) < 2:
            continue
        weights = []
        for sid in route:
            seg = g.segments[sid]
            weights.append(
                1.0
                if min(mapdata.distance_m(seg.mid, p) for p in pts) <= WAYPOINT_LABEL_RADIUS_M
                else interpolated_weight
            )
        output.append(
            TrainingEvent(
                e.event_id,
                e.date,
                e.cause,
                {
                    "turnout": e.turnout or DEFAULT_TURNOUT,
                    "precip_mm_4h": rains.get(e.event_id, 0),
                    "dark_fraction": darks.get(e.event_id, 0),
                },
                pts[-1],
                route,
                weights,
                str(e.waypoints[-1][0] or "").strip(),
            )
        )
    return output


def history_counts(events: list[TrainingEvent], before: str | None = None) -> dict[str, int]:
    """Count prior segment use per event, optionally strictly before ``before`` (ISO date).

    Used only where legacy callers still pass a history dict; the current feature set
    no longer includes street history.
    """
    counts: Counter[str] = Counter()
    for event in events:
        if before is not None and event.date >= before:
            continue
        counts.update(set(event.route))
    return dict(counts)
