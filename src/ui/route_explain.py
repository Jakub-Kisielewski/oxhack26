"""Pure helpers for per-junction logit contribution tables."""

from __future__ import annotations

from typing import Any

import numpy as np


def contribution_breakdown(
    explanation: dict[str, Any],
    chosen: str,
    alternative: str | None = None,
) -> list[dict[str, float | str | bool]]:
    """Compare feature contributions for ``chosen`` vs ``alternative`` (or best rejected)."""
    candidates: list[str] = list(explanation["candidates"])
    if chosen not in candidates:
        return []
    ci = candidates.index(chosen)
    if alternative is not None and alternative in candidates:
        ai = candidates.index(alternative)
    else:
        others = [i for i in range(len(candidates)) if i != ci]
        if not others:
            return []
        ai = max(others, key=lambda i: float(explanation["utility"][i]))

    names: list[str] = list(explanation["names"])
    z = explanation["z"]
    theta = explanation["theta"]
    prior_only: set[str] = set(explanation.get("prior_only") or [])
    rows: list[dict[str, float | str | bool]] = []
    for j, name in enumerate(names):
        rows.append(
            {
                "feature": name,
                "z_chosen": float(z[ci, j]),
                "z_alternative": float(z[ai, j]),
                "theta": float(theta[j]),
                "contrib_chosen": float(z[ci, j] * theta[j]),
                "contrib_alternative": float(z[ai, j] * theta[j]),
                "prior_only": name in prior_only,
            }
        )
    return rows


def contributions_sum_to_utility(explanation: dict[str, Any], index: int) -> bool:
    """Row contributions should sum to the clipped utility for one candidate."""
    z = explanation["z"]
    theta = explanation["theta"]
    contrib = float(np.dot(z[index], theta))
    utility = float(explanation["utility"][index])
    return abs(contrib - utility) < 1e-5
