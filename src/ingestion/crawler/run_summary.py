"""Structured result of a protest ingestion run."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunSummary:
    """Schema for ``run_progress.json`` and CLI output."""

    run_id: str
    started_at: str
    finished_at: str | None = None
    organizer_event_window: dict[str, int] = field(default_factory=dict)
    platforms: dict[str, dict[str, Any]] = field(default_factory=dict)
    errors: list[dict[str, str]] = field(default_factory=list)
    outputs: dict[str, Any] = field(default_factory=dict)
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "organizer_event_window": self.organizer_event_window,
            "platforms": self.platforms,
            "errors": self.errors,
            "outputs": self.outputs,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunSummary:
        return cls(
            run_id=data["run_id"],
            started_at=data["started_at"],
            finished_at=data.get("finished_at"),
            organizer_event_window=data.get("organizer_event_window", {}),
            platforms=data.get("platforms", {}),
            errors=list(data.get("errors", [])),
            outputs=data.get("outputs", {}),
            updated_at=data.get("updated_at"),
        )
