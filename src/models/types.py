"""Shared types for training outputs and the backtest UI."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any


def _json_safe(value: Any) -> Any:
    """Replace non-finite floats with ``None`` so ``json.dump(..., allow_nan=False)`` succeeds."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


class _Serialisable:
    """JSON-friendly ``dataclass`` mixin."""

    def to_dict(self) -> dict:
        return _json_safe(asdict(self))


@dataclass
class BacktestRow(_Serialisable):
    """One backtest metric row for a single held-out event and route predictor."""

    event_id: str
    model: str
    mean_log_likelihood: float
    top1_jaccard: float
    path: list[str] = field(default_factory=list)


@dataclass
class BacktestResult(_Serialisable):
    """Aggregated leave-one-out backtest for the UI and ``backtest.json``."""

    rows: list[BacktestRow]
    summary: dict[str, dict[str, float]]
    n_events: int
    created_at: str
    destination_summary: dict[str, float] | None = None
    actual_routes: dict[str, list[str]] | None = None
    chosen_ends: dict[str, tuple[float, float]] | None = None
