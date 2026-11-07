"""Types for read-only map and reference data (lon/lat in EPSG:4326)."""

from __future__ import annotations

from dataclasses import asdict, dataclass

LonLat = tuple[float, float]
Path = list[LonLat]


class _Serialisable:
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CauseOption(_Serialisable):
    key: str
    label: str
    n_events: int


@dataclass
class HistoricalEvent(_Serialisable):
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
    name: str
    lonlat: LonLat
    probability: float
