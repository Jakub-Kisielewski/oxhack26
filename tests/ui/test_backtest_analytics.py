from __future__ import annotations

import numpy as np

from src.ui.backtest_analytics import bootstrap_mean_ci, format_saved_at


def test_format_saved_at_strips_tz() -> None:
    assert format_saved_at("2026-11-08T18:38:00+00:00").startswith("8 Nov 2026, 18:38")


def test_bootstrap_mean_ci_finite() -> None:
    mean, lo, hi = bootstrap_mean_ci([0.1, 0.2, 0.3], n=200, seed=1)
    assert lo <= mean <= hi
    assert np.isfinite(lo) and np.isfinite(hi)
