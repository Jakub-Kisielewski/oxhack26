"""Tests for event date window helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ingestion.crawler.date_window import (
    event_date_from_url,
    is_within_event_window,
    parse_event_datetime_str,
)


def test_parse_iso_datetime() -> None:
    dt = parse_event_datetime_str("2026-06-14T12:00:00Z")
    assert dt == datetime(2026, 6, 14, 12, 0, tzinfo=UTC)


def test_parse_human_date() -> None:
    dt = parse_event_datetime_str("14 June 2026")
    assert dt == datetime(2026, 6, 14, tzinfo=UTC)


def test_event_date_from_url() -> None:
    dt = event_date_from_url("https://example.org/2026/03/15/post-title/")
    assert dt == datetime(2026, 3, 15, tzinfo=UTC)


@pytest.mark.parametrize(
    ("event_offset_days", "expected"),
    [(-8, False), (-7, True), (0, True), (3, True), (4, False)],
)
def test_event_window_boundaries(event_offset_days: int, expected: bool) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    event = now + timedelta(days=event_offset_days)
    assert (
        is_within_event_window(event, now=now, days_back=7, days_ahead=3) is expected
    )

