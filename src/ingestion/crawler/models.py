from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class ProtestRecord:
    """Normalized protest signal from any Tier 1 source."""

    source: str
    source_id: str
    title: str
    url: str
    fetched_at: str
    event_start: Optional[str] = None
    event_end: Optional[str] = None
    form_up_location: Optional[str] = None
    route_text: Optional[str] = None
    route_streets: list[str] = field(default_factory=list)
    estimated_participants_min: Optional[int] = None
    estimated_participants_max: Optional[int] = None
    estimated_participants_text: Optional[str] = None
    counter_protest_expected: Optional[bool] = None
    location_label: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    raw_excerpt: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
