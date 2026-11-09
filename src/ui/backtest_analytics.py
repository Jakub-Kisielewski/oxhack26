"""Backtest aggregates and bootstrap CIs for the UI."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from src.models.types import BacktestResult, BacktestRow
from src.ui.backtest_display import MODEL_LABELS
BOOTSTRAP_N = 2000
BOOTSTRAP_SEED = 0


def format_saved_at(iso: str) -> str:
    """``8 Nov 2026, 18:38`` from an ISO timestamp."""
    raw = iso.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return iso
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return f"{dt.day} {dt.strftime('%b %Y')}, {dt.strftime('%H:%M')}"


def bootstrap_mean_ci(values: list[float], n: int = BOOTSTRAP_N, seed: int = BOOTSTRAP_SEED) -> tuple[float, float, float]:
    """Mean and approximate 95% CI from event-level resampling."""
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    boots = np.array(
        [rng.choice(arr, size=arr.size, replace=True).mean() for _ in range(n)],
        dtype=float,
    )
    return float(arr.mean()), float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))


def rows_by_event(rows: list[BacktestRow]) -> dict[str, dict[str, BacktestRow]]:
    out: dict[str, dict[str, BacktestRow]] = defaultdict(dict)
    for r in rows:
        out[r.event_id][r.model] = r
    return dict(out)


def event_level_frame(rows: list[BacktestRow]) -> pd.DataFrame:
    """Long-form metrics for charts (one row per event × model)."""
    records: list[dict[str, Any]] = []
    for eid, by_model in rows_by_event(rows).items():
        rw = by_model.get("random_walk")
        rw_ll = rw.mean_log_likelihood if rw else float("nan")
        for model, row in by_model.items():
            records.append(
                {
                    "event_id": eid,
                    "model": model,
                    "model_label": MODEL_LABELS.get(model, model),
                    "mean_log_likelihood": row.mean_log_likelihood,
                    "ll_gain_vs_rw": row.mean_log_likelihood - rw_ll if rw else float("nan"),
                    "top1_jaccard": row.top1_jaccard,
                }
            )
    return pd.DataFrame.from_records(records)


def kpi_values(bt: BacktestResult) -> dict[str, Any]:
    """Headline means and deltas (route model vs shortest path)."""
    sm = bt.summary
    rm, sp = sm.get("route_model", {}), sm.get("shortest_path", {})
    dest = bt.destination_summary or {}
    ll_rm = rm.get("mean_log_likelihood")
    ll_sp = sp.get("mean_log_likelihood")
    j_rm = rm.get("top1_jaccard")
    j_sp = sp.get("top1_jaccard")
    ll_delta = (ll_rm - ll_sp) if ll_rm is not None and ll_sp is not None else None
    j_delta = (j_rm - j_sp) * 100.0 if j_rm is not None and j_sp is not None else None
    return {
        "dest_rate": dest.get("destination_top3_rate"),
        "dest_n": int(dest.get("n_events", bt.n_events)),
        "ll_rm": ll_rm,
        "ll_delta": ll_delta,
        "overlap_rm": j_rm,
        "overlap_delta": j_delta,
    }


def delta_label(delta: float | None, suffix: str = "pts vs shortest path") -> str | None:
    if delta is None or not np.isfinite(delta):
        return None
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:.3f} {suffix}"
