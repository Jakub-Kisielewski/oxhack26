"""Pipeline step registry (in-process runners)."""

from __future__ import annotations

from pathlib import Path

from src.ingestion.route_research import steps
from src.ingestion.route_research.context import StepContext


def test_step_context_paths(tmp_path: Path) -> None:
    ctx = StepContext(tmp_path)
    assert ctx.raw == tmp_path / "raw"
    assert ctx.normalised == tmp_path / "normalised"


def test_registry_covers_nine_steps() -> None:
    assert len(steps.REGISTRY) == 9
    assert "pageviews" not in steps.REGISTRY


def test_each_step_exposes_run() -> None:
    for name, runner in steps.REGISTRY.items():
        assert callable(runner), name
