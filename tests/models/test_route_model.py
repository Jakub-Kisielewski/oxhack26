from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pytest

from src.models.features import NAMES
from src.models.route_model import PRIOR, ChoiceModel, fit


def test_fit_recovers_dominant_sign(tiny_graph, tiny_events) -> None:
    model = fit(tiny_graph, tiny_events, targets_for=lambda _: [], maxiter=30)
    assert model.fitted
    progress_idx = NAMES.index("progress")
    assert model.theta[progress_idx] > 0


def test_fit_empty_returns_unfitted() -> None:
    from src.models.graph import MarchGraph

    model = fit(MarchGraph({}), [])
    assert not model.fitted


def test_probs_sum_to_one(tiny_graph) -> None:
    model = ChoiceModel(theta=list(PRIOR), mean=[0.0] * len(NAMES), std=[1.0] * len(NAMES))
    dest = (-0.10, 51.5)
    p = model.probs(tiny_graph, "s0", ["s1", "s2"], dest)
    assert abs(p.sum() - 1.0) < 1e-6


def test_probs_empty_candidates(tiny_graph) -> None:
    model = ChoiceModel()
    assert len(model.probs(tiny_graph, "s0", [], (-0.1, 51.5))) == 0


def test_probs_clip_does_not_nan(tiny_graph) -> None:
    model = ChoiceModel(theta=[100.0] * len(NAMES), mean=[0.0] * len(NAMES), std=[1.0] * len(NAMES))
    p = model.probs(tiny_graph, "s0", ["s1", "s2"], (-0.10, 51.5))
    assert np.all(np.isfinite(p))


def test_json_round_trip(tiny_graph, tiny_events) -> None:
    model = fit(tiny_graph, tiny_events, maxiter=20)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "m.json"
        model.to_json(path)
        loaded = ChoiceModel.from_json(path)
        assert loaded.theta == model.theta


def test_json_feature_mismatch_raises(tiny_graph, tiny_events) -> None:
    model = fit(tiny_graph, tiny_events, maxiter=10)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "m.json"
        model.to_json(path)
        data = json.loads(path.read_text())
        data["features"] = ["bogus"]
        path.write_text(json.dumps(data))
        with pytest.raises(ValueError):
            ChoiceModel.from_json(path)


def test_fit_records_convergence(tiny_graph, tiny_events) -> None:
    model = fit(tiny_graph, tiny_events, maxiter=25)
    assert "converged" in model.stats
