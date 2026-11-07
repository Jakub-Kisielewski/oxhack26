"""Candidate march record emitted by the discovery crawler."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProtestRecord:
    """A candidate march discovered from a published source, pending geocode review."""

    source: str
    source_id: str
    url: str
    title: str
    fetched_at: str
    event_start: str | None = None
    form_up_location: str | None = None
    route_text: str | None = None
    turnout_estimate: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CANDIDATE_CSV_COLUMNS: tuple[str, ...] = tuple(f.name for f in fields(ProtestRecord))


def write_candidates_csv(path: Path, records: list[ProtestRecord]) -> None:
    """Write discovery rows for human promotion into seed CSVs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CANDIDATE_CSV_COLUMNS))
        writer.writeheader()
        for record in records:
            writer.writerow(record.to_dict())
