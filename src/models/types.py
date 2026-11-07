"""Shared types for training outputs and the backtest UI."""

from __future__ import annotations

from dataclasses import asdict, dataclass


class _Serialisable:
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BacktestRow(_Serialisable):
    event_id: str
    model: str
    mean_log_likelihood: float
    top1_jaccard: float
    destination_in_top3: bool


@dataclass
class BacktestResult(_Serialisable):
    rows: list[BacktestRow]
    summary: dict[str, dict[str, float]]
    n_events: int
    created_at: str
