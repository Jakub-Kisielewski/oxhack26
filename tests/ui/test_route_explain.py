from __future__ import annotations

import numpy as np

from src.ui.route_explain import contribution_breakdown, contributions_sum_to_utility


def _fake_explanation() -> dict:
    z = np.array([[1.0, 0.0], [0.0, 1.0]])
    theta = np.array([2.0, -1.0])
    utility = z @ theta
    return {
        "candidates": ["a", "b"],
        "z": z,
        "theta": theta,
        "names": ["f0", "f1"],
        "utility": utility,
        "probs": np.array([0.7, 0.3]),
        "prior_only": ["f1"],
    }


def test_contribution_breakdown_sums_match_utility() -> None:
    expl = _fake_explanation()
    assert contributions_sum_to_utility(expl, 0)
    assert contributions_sum_to_utility(expl, 1)


def test_contribution_breakdown_prefers_higher_utility_alternative() -> None:
    expl = _fake_explanation()
    rows = contribution_breakdown(expl, "a")
    assert len(rows) == 2
    assert rows[0]["feature"] == "f0"
    assert float(rows[0]["contrib_chosen"]) == 2.0


def test_contribution_breakdown_empty_candidates() -> None:
    empty: dict = {
        "candidates": [],
        "z": np.empty((0, 2)),
        "theta": np.zeros(2),
        "names": [],
        "utility": np.array([]),
    }
    assert contribution_breakdown(empty, "x") == []
