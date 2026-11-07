"""Tests for normalize helpers and temporal history counts."""
from __future__ import annotations

import inspect

from src.ingestion.route_research.processing.normalize import (
    history_counts_before,
    is_approved,
    make_streets,
    safe_float,
    tag,
)


def test_tag_joins_lists() -> None:
    assert tag(["a", "b"]) == "a|b"


def test_safe_float() -> None:
    assert safe_float("3.5") == 3.5
    assert safe_float("x") is None


def test_is_approved() -> None:
    assert is_approved({"status": "Approved"})
    assert not is_approved({"status": "missing"})


def test_history_counts_exclude_the_event_being_predicted() -> None:
    routes = [
        {"event_id": "E1", "segment_id": "1:2:0", "event_date": "2026-01-01"},
        {"event_id": "E2", "segment_id": "1:2:0", "event_date": "2026-06-01"},
    ]
    counts = history_counts_before(routes, before="2026-06-01")
    assert counts["1:2:0"] == 1


def test_make_streets_does_not_write_segment_features_csv() -> None:
    source = inspect.getsource(make_streets)
    assert "segment_features.csv" not in source
