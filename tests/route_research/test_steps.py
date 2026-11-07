"""Pipeline step imports run without subprocess."""
from __future__ import annotations

from pathlib import Path

from src.ingestion.route_research import steps


def test_step_context_paths(tmp_path: Path) -> None:
    ctx = steps.StepContext(tmp_path)
    assert ctx.raw == tmp_path / "raw"
    assert ctx.normalised == tmp_path / "normalised"


def test_runners_cover_nine_steps() -> None:
    assert len(steps.RUNNERS) == 9
    assert "pageviews" not in steps.RUNNERS
