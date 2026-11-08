"""Cause-conditional destinations, combining curated targets and historical end points."""

from __future__ import annotations

from src.config import (
    DESTINATION_HISTORICAL_RADIUS_M,
    DESTINATION_HIT_RADIUS_M,
    DESTINATION_MAX_CANDIDATES,
    DESTINATION_MIN_PROB,
    DESTINATION_MATCH_RADIUS_M,
)
from src.database import mapdata
from src.database.types import Destination
from src.models.labels import TrainingEvent


def candidates(
    cause: str | None,
    events: list[TrainingEvent],
    end: tuple[float, float] | None = None,
    max_n: int = DESTINATION_MAX_CANDIDATES,
) -> list[Destination]:
    """Rank likely march end points from cause targets and training history."""
    if end is not None:
        return [Destination("Selected destination", tuple(end), 1.0)]
    raw: list[tuple[str, tuple[float, float], float]] = []
    for t in mapdata.cause_targets(cause):
        weight = max(0.001, float(t["weight"]))
        raw.append((str(t["target_name"]), tuple(t["lonlat"]), weight))
    for e in events:
        if cause and e.cause != cause:
            continue
        if not any(
            mapdata.distance_m(e.destination, p) < DESTINATION_HISTORICAL_RADIUS_M for _, p, _ in raw
        ):
            name = getattr(e, "destination_name", "")
            raw.append(
                (
                    f"{name[:1].upper()}{name[1:]} (past end point)" if name else "Past end point",
                    e.destination,
                    1.0,
                )
            )
    scored: list[tuple[str, tuple[float, float], float]] = []
    for name, pt, w in raw:
        n = sum(
            1
            for e in events
            if (not cause or e.cause == cause)
            and mapdata.distance_m(pt, e.destination) <= DESTINATION_MATCH_RADIUS_M
        )
        scored.append((name, pt, w * (1 + n)))
    scored.sort(key=lambda s: -s[2])
    if not scored:
        return []
    total = sum(score for _, _, score in scored)
    normed = [(name, pt, score / total) for name, pt, score in scored]
    filtered = [x for x in normed if x[2] >= DESTINATION_MIN_PROB][:max_n]
    if not filtered:
        name, pt, prob = normed[0]
        return [Destination(name, pt, 1.0)]
    return [Destination(name, pt, prob) for name, pt, prob in filtered]


def destination_top3_hit(event: TrainingEvent, training: list[TrainingEvent]) -> bool:
    """True when the realised end point is among the top three destination candidates."""
    dests = candidates(event.cause, training)
    return any(
        mapdata.distance_m(d.lonlat, event.destination) < DESTINATION_HIT_RADIUS_M for d in dests[:3]
    )
