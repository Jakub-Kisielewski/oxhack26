"""Re-export database DTOs; ``Path`` is an alias for coordinate polylines (not ``pathlib.Path``)."""

from src.database.types import (
    CauseOption,
    Destination,
    HistoricalEvent,
    LonLat,
    Polyline,
)

Path = Polyline

__all__ = [
    "CauseOption",
    "Destination",
    "HistoricalEvent",
    "LonLat",
    "Path",
    "Polyline",
]
