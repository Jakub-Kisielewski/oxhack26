"""Pipeline workspace paths for one ingest run."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StepContext:
    workdir: Path

    @property
    def raw(self) -> Path:
        return self.workdir / "raw"

    @property
    def normalised(self) -> Path:
        return self.workdir / "normalised"
