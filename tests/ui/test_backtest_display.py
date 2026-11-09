from __future__ import annotations

from src.ui.backtest_display import (
    METRICS,
    event_count_caption,
    event_counts,
    format_overlap_pct,
    metric_format,
    model_order,
)


def test_model_order_puts_known_models_first() -> None:
    summary = {
        "random_walk": {},
        "route_model": {},
        "shortest_path": {},
    }
    assert model_order(summary) == ["route_model", "shortest_path", "random_walk"]


def test_model_order_appends_unknown_models() -> None:
    summary = {"route_model": {}, "extra_baseline": {}}
    assert model_order(summary) == ["route_model", "extra_baseline"]


def test_model_order_empty_summary() -> None:
    assert model_order({}) == []


def test_event_counts_equal_across_models() -> None:
    summary = {
        "route_model": {"mean_log_likelihood_n": 10},
        "shortest_path": {"mean_log_likelihood_n": 10},
    }
    assert event_counts(summary, "mean_log_likelihood") == {
        "route_model": 10,
        "shortest_path": 10,
    }


def test_event_counts_unequal_per_model() -> None:
    summary = {
        "route_model": {"mean_log_likelihood_n": 5},
        "shortest_path": {"mean_log_likelihood_n": 3},
    }
    assert event_counts(summary, "mean_log_likelihood") == {
        "route_model": 5,
        "shortest_path": 3,
    }


def test_event_counts_missing_n_key() -> None:
    summary = {"route_model": {"mean_log_likelihood": -2.0}}
    assert event_counts(summary, "mean_log_likelihood") == {}


def test_metric_format_log_likelihood() -> None:
    assert metric_format("mean_log_likelihood") == ".2f"


def test_metric_format_jaccard() -> None:
    assert metric_format("top1_jaccard") == ".1%"
    assert METRICS["top1_jaccard"][1] == ".1%"


def test_format_overlap_pct() -> None:
    assert format_overlap_pct(0.5673076923076923) == "56.7%"
    assert format_overlap_pct(0) == "0.0%"
    assert format_overlap_pct(None) == "—"


def test_event_count_caption_unequal_counts() -> None:
    summary = {
        "route_model": {"mean_log_likelihood_n": 5},
        "shortest_path": {"mean_log_likelihood_n": 3},
    }
    caption = event_count_caption("Help.", summary, "mean_log_likelihood", list(summary))
    assert "events scored:" in caption
    assert "Route model 5" in caption
    assert "Shortest path 3" in caption
