from __future__ import annotations

from src.models.features import NAMES
from src.models.route_model import ChoiceModel
from src.ui.theta_table import theta_rows


def test_theta_rows_count_matches_features() -> None:
    model = ChoiceModel(theta=list(range(len(NAMES))))
    rows = theta_rows(model)
    assert len(rows) == len(NAMES)


def test_theta_rows_prior_only_basis() -> None:
    model = ChoiceModel(stats={"prior_only": ["is_main"]})
    rows = {r["feature"]: r for r in theta_rows(model)}
    assert rows["is_main"]["prior_only"] is True
    assert rows["is_main"]["basis"] == "assumed (prior only)"
    assert rows["progress"]["basis"] == "learned"


def test_theta_rows_theta_values() -> None:
    model = ChoiceModel(theta=[0.5, -1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    rows = theta_rows(model)
    assert float(rows[0]["theta"]) == 0.5
    assert float(rows[1]["theta"]) == -1.0
