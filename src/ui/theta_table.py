"""Render-friendly rows for conditional logit coefficients."""

from __future__ import annotations

from src.models.route_model import ChoiceModel

FEATURE_DISPLAY_NAMES: dict[str, str] = {
    "progress": "Progress toward destination",
    "log_width": "Road width (log)",
    "is_main": "Main road",
    "turn": "Turn angle",
    "target_pull": "Pull toward target",
    "is_bridge": "Crosses bridge",
    "name_continuity": "Street-name continuity",
    "log_length": "Segment length (log)",
}


def feature_display_name(raw: str) -> str:
    return FEATURE_DISPLAY_NAMES.get(raw, raw.replace("_", " ").title())


def theta_rows(model: ChoiceModel) -> list[dict[str, float | str | bool]]:
    """One row per feature with learned vs prior-only labelling."""
    prior_only = set(model.stats.get("prior_only") or [])
    return [
        {
            "feature": name,
            "theta": float(model.theta[i]),
            "prior_only": name in prior_only,
            "basis": "assumed (prior only)" if name in prior_only else "learned",
        }
        for i, name in enumerate(model.features)
    ]
