"""Tests for coordinate review rows."""

from __future__ import annotations

from src.ingestion.route_research.processing.seed_coordinates import review_rows


def test_review_rows_missing_status() -> None:
    rows = review_rows(["Hyde Park"], {}, {})
    assert rows[0]["status"] == "missing"


def test_review_rows_override_wins() -> None:
    overrides = {"Hyde Park": {"latitude": 51.5, "longitude": -0.15}}
    rows = review_rows(["Hyde Park"], {}, overrides)
    assert rows[0]["status"] == "approved"
    assert rows[0]["notes"] == "manual_override"
