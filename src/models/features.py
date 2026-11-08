"""Choice-specific, standardisable route features (plan A3)."""

from __future__ import annotations

import math

import numpy as np

from src.config import DEFAULT_TURNOUT, MARCH_HOURS, TARGET_PULL_LENGTH_M
from src.database import mapdata
from src.models.graph import MarchGraph, angle

NAMES = (
    "progress",
    "log_width",
    "is_main",
    "turn",
    "target_pull",
    "restricted",
    "is_bridge",
    "name_continuity",
    "log_length",
)


def dark_fraction(daylight_after_start_h: float | None, march_hours: float = MARCH_HOURS) -> float:
    """Share of the march window after the start that falls after sunset."""
    if daylight_after_start_h is None:
        return 0.0
    hours = max(0.1, float(march_hours))
    return min(1.0, max(0.0, (hours - float(daylight_after_start_h)) / hours))


def feature_vector(
    g: MarchGraph,
    current: str,
    candidate: str,
    destination: tuple[float, float],
    context: dict | None = None,
    history: dict | None = None,
    targets: list | None = None,
    net_dist: dict[str, float] | None = None,
) -> np.ndarray:
    """Return the feature vector for moving from ``current`` to ``candidate``.

    Components (aligned with ``NAMES``):

    1. **progress** — network-distance reduction toward ``destination`` (km), positive if
       ``candidate`` is nearer along the walk graph.
    2. **log_width** — log pedestrian width (m) of ``candidate``.
    3. **is_main** — 1 if ``candidate`` is classified as a main road.
    4. **turn** — normalised turn angle in ``[0, 1]`` from ``current`` into ``candidate``.
    5. **target_pull** — weighted sum of cause targets, exponential kernel in meters.
    6. **restricted** — 1 if ``candidate`` lies in a restricted zone.
    7. **is_bridge** — 1 if ``candidate`` crosses a bridge (e.g. Thames).
    8. **name_continuity** — 1 if street name matches ``current``.
    9. **log_length** — log segment length (m) of ``candidate``.
    """
    del history  # removed from the feature set; kept for call-site compatibility
    context = context or {}
    targets = targets or []
    a = g.segments[current]
    b = g.segments[candidate]
    if net_dist is not None:
        da = net_dist.get(current, float("inf"))
        db = net_dist.get(candidate, float("inf"))
        progress = (da - db) / 1000.0
    else:
        progress = (
            mapdata.distance_m(a.path[-1], destination) - mapdata.distance_m(b.path[-1], destination)
        ) / 1000.0
    pull = sum(
        float(t.get("weight") or 0)
        * math.exp(-mapdata.distance_m(b.path[-1], t["lonlat"]) / TARGET_PULL_LENGTH_M)
        for t in targets
    )
    name_a = (a.street_name or "").strip().lower()
    name_b = (b.street_name or "").strip().lower()
    name_match = float(bool(name_a and name_a == name_b))
    return np.array(
        [
            progress,
            math.log(max(1e-3, b.width)),
            float(b.is_main),
            angle(a.end_bearing, b.start_bearing),
            pull,
            float(b.restricted),
            float(b.is_bridge),
            name_match,
            math.log(max(1.0, b.length)),
        ],
        dtype=np.float64,
    )
