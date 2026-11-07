"""Types for read-only map and reference data (lon/lat in EPSG:4326)."""

from __future__ import annotations

from dataclasses import asdict, dataclass

LonLat = tuple[float, float]
Path = list[LonLat]


class _Serialisable:
    """JSON-friendly ``dataclass`` mixin."""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CauseOption(_Serialisable):
    """Selectable protest cause with label and event count."""

    key: str
    label: str
    n_events: int


@dataclass
class HistoricalEvent(_Serialisable):
    """One historical march with geometry reconstructed from seed waypoints."""

    event_id: str
    name: str
    date: str
    start_time: str | None
    cause: str | None
    organiser: str | None
    turnout: int | None
    route_segment_ids: list[str]
    path: Path
    waypoints: list[tuple[str, LonLat]]


@dataclass
class Destination(_Serialisable):
    """Weighted end-point candidate for destination scoring."""

    name: str
    lonlat: LonLat
    probability: float
