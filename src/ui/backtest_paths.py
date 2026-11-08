"""Helpers for backtest path data used by the map page."""

from __future__ import annotations

from src.models.types import BacktestResult


def paths_for_event(bt: BacktestResult, event_id: str) -> dict[str, list[str]]:
    """Predicted segment ids per model for one held-out event."""
    return {r.model: list(r.path) for r in bt.rows if r.event_id == event_id and r.path}


def backtest_has_paths(bt: BacktestResult) -> bool:
    """True when at least one row persisted route geometry."""
    return any(r.path for r in bt.rows)
