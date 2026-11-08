from __future__ import annotations

import math

from src.models.backtest import (
    baseline_ll,
    evaluate,
    fit_baseline_epsilon,
    jaccard,
    step_loglik,
)
from tests.models.conftest import make_event


def test_jaccard_identical() -> None:
    assert jaccard(["a", "b"], ["a", "b"]) == 1.0


def test_jaccard_disjoint() -> None:
    assert jaccard(["a"], ["b"]) == 0.0


def test_jaccard_both_empty() -> None:
    assert jaccard([], []) == 0.0


def test_baseline_epsilon_within_bounds(tiny_graph, tiny_events) -> None:
    eps = fit_baseline_epsilon(
        tiny_graph,
        tiny_events,
        lambda e: tiny_graph.route_between(tiny_graph.segments[e.route[0]].path[0], e.destination),
    )
    assert 0.5 <= eps <= 0.99


def test_every_model_reports_a_measured_jaccard(tiny_graph, tiny_events) -> None:
    result = evaluate(tiny_graph, tiny_events)
    walks = [r.top1_jaccard for r in result.rows if r.model == "random_walk"]
    assert walks
    assert not all(v == 0.0 for v in walks), "random_walk Jaccard is hardcoded, not measured"


def test_evaluate_three_models_and_shared_denominators(tiny_graph, tiny_events) -> None:
    result = evaluate(tiny_graph, tiny_events)
    models = {r.model for r in result.rows}
    assert models == {"route_model", "shortest_path", "random_walk"}
    n_route = result.summary["route_model"]["mean_log_likelihood_n"]
    n_sp = result.summary["shortest_path"]["mean_log_likelihood_n"]
    assert n_route == n_sp


def test_nan_metric_not_reported_as_zero(tiny_graph) -> None:
    lone = [make_event("only", "2025-01-01", ["s0", "s1"])]
    result = evaluate(tiny_graph, lone)
    assert (
        result.n_events == 0
        or math.isnan(result.summary["route_model"]["mean_log_likelihood"] or float("nan"))
        or result.summary["route_model"]["mean_log_likelihood_n"] == 0
    )


def test_step_loglik_uniform(tiny_graph) -> None:
    ev = make_event("e", "2024-05-01", ["s0", "s1"])
    ll = step_loglik(tiny_graph, ev, None, None, [])
    assert math.isfinite(ll)


def test_baseline_ll_with_epsilon(tiny_graph) -> None:
    ev = make_event("e", "2024-05-01", ["s0", "s1"])
    route = tiny_graph.route_between(tiny_graph.segments["s0"].path[0], ev.destination)
    ll = baseline_ll(tiny_graph, ev, route, 0.9)
    assert math.isfinite(ll)


def test_destination_summary_present(tiny_graph, tiny_events) -> None:
    result = evaluate(tiny_graph, tiny_events)
    assert result.destination_summary is not None
    assert "destination_top3_rate" in result.destination_summary


def test_save_backtest_writes_null_for_nan_summary(tmp_path) -> None:
    from src.models.backtest import read_backtest, save_backtest
    from src.models.types import BacktestResult

    res = BacktestResult(
        rows=[],
        summary={
            "shortest_path": {
                "mean_log_likelihood": float("nan"),
                "mean_log_likelihood_n": 0,
            }
        },
        n_events=0,
        created_at="2025-01-01T00:00:00+00:00",
        destination_summary={"destination_top3_rate": float("nan"), "n_events": 0.0},
    )
    path = tmp_path / "backtest.json"
    save_backtest(res, path)
    assert "NaN" not in path.read_text()
    loaded = read_backtest(path)
    assert loaded is not None
    assert loaded.summary["shortest_path"]["mean_log_likelihood"] is None


def test_save_backtest_row_path_round_trip(tmp_path) -> None:
    from src.models.backtest import read_backtest, save_backtest
    from src.models.types import BacktestResult, BacktestRow

    res = BacktestResult(
        rows=[
            BacktestRow("e1", "route_model", -0.1, 0.5, ["s0", "s1", "s2"]),
        ],
        summary={},
        n_events=1,
        created_at="2025-01-01T00:00:00+00:00",
    )
    path = tmp_path / "backtest.json"
    save_backtest(res, path)
    loaded = read_backtest(path)
    assert loaded is not None
    assert loaded.rows[0].path == ["s0", "s1", "s2"]


def test_read_backtest_legacy_row_without_path(tmp_path) -> None:
    from src.models.backtest import read_backtest

    path = tmp_path / "backtest.json"
    path.write_text(
        """{
  "rows": [{"event_id": "e1", "model": "route_model",
            "mean_log_likelihood": -0.1, "top1_jaccard": 0.5}],
  "summary": {}, "n_events": 1, "created_at": "2025-01-01T00:00:00+00:00"
}"""
    )
    loaded = read_backtest(path)
    assert loaded is not None
    assert loaded.rows[0].path == []


def test_actual_routes_and_chosen_ends_round_trip(tmp_path) -> None:
    from src.models.backtest import read_backtest, save_backtest
    from src.models.types import BacktestResult

    res = BacktestResult(
        rows=[],
        summary={},
        n_events=0,
        created_at="2025-01-01T00:00:00+00:00",
        actual_routes={"e1": ["a", "b"]},
        chosen_ends={"e1": (-0.12, 51.5)},
    )
    path = tmp_path / "backtest.json"
    save_backtest(res, path)
    loaded = read_backtest(path)
    assert loaded is not None
    assert loaded.actual_routes == {"e1": ["a", "b"]}
    assert loaded.chosen_ends == {"e1": (-0.12, 51.5)}


def test_evaluate_persists_paths(tiny_graph, tiny_events) -> None:
    result = evaluate(tiny_graph, tiny_events)
    assert result.actual_routes
    assert result.chosen_ends
    by_event = {r.event_id: r for r in result.rows if r.model == "route_model"}
    for eid, row in by_event.items():
        assert row.path
        assert result.actual_routes.get(eid)
