"""Importable route-research pipeline steps (no subprocess)."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Protocol

RUNNERS: dict[str, str] = {
    "boundary": "src.ingestion.route_research.sources.download_boundary",
    "osm": "src.ingestion.route_research.sources.download_osm",
    "landmarks": "src.ingestion.route_research.sources.download_landmarks",
    "weather": "src.ingestion.route_research.sources.download_weather",
    "seed-coords": "src.ingestion.route_research.processing.seed_coordinates",
    "normalize": "src.ingestion.route_research.processing.normalize",
    "edge-features": "src.ingestion.route_research.processing.edge_features",
    "event-context": "src.ingestion.route_research.processing.event_context",
    "cause-targets": "src.ingestion.route_research.processing.cause_targets",
}


@dataclass(frozen=True)
class StepContext:
    """Resolved directories for one pipeline run."""

    workdir: Path

    @property
    def raw(self) -> Path:
        return self.workdir / "raw"

    @property
    def normalised(self) -> Path:
        return self.workdir / "normalised"


@dataclass(frozen=True)
class StepResult:
    """What a step produced, for run summaries."""

    name: str
    outputs: tuple[Path, ...]
    rows_written: int
    warnings: tuple[str, ...] = ()


class PipelineStep(Protocol):
    name: str
    requires: tuple[str, ...]

    def run(self, context: StepContext) -> StepResult: ...


def run_module_main(module: str, workdir: Path, argv: list[str]) -> int:
    """Run a step's ``main()`` with ``workdir`` as cwd and optional extra CLI args."""
    prev_cwd = os.getcwd()
    prev_argv = sys.argv[:]
    os.chdir(workdir)
    sys.argv = [module, *argv]
    try:
        import_module(module).main()
        return 0
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 1
    finally:
        os.chdir(prev_cwd)
        sys.argv = prev_argv


def run_named_step(name: str, context: StepContext, argv: list[str] | None = None) -> int:
    module = RUNNERS[name]
    return run_module_main(module, context.workdir, argv or [])
