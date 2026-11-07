"""Normalised protest record shared by every ingestion source."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any


@dataclass
class ProtestRecord:
    """Normalized protest signal from any Tier 1 source."""

    source: str
    source_id: str
    title: str
    url: str
    fetched_at: str
    event_start: str | None = None
    event_end: str | None = None
    form_up_location: str | None = None
    route_text: str | None = None
    route_streets: list[str] = field(default_factory=list)
    estimated_participants_min: int | None = None
    estimated_participants_max: int | None = None
    estimated_participants_text: str | None = None
    counter_protest_expected: bool | None = None
    location_label: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    raw_excerpt: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PROTEST_RECORD_COLUMNS: tuple[str, ...] = tuple(f.name for f in fields(ProtestRecord))
