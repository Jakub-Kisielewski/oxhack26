"""Structured result of a discovery crawl."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DiscoverSummary:
    """Summary printed by the CLI after ``discover``."""

    started_at: str
    finished_at: str
    candidates_path: str
    total_records: int
    records_by_source: dict[str, int] = field(default_factory=dict)
    errors: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "candidates_path": self.candidates_path,
            "total_records": self.total_records,
            "records_by_source": self.records_by_source,
            "errors": self.errors,
        }
