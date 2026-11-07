"""Date/time formatting on the declared schema read path."""

from __future__ import annotations

from datetime import date, time

from src.database import mapdata


def test_format_date_from_date() -> None:
    assert mapdata._format_date(date(2026, 6, 1)) == "2026-06-01"


def test_format_time_from_time() -> None:
    assert mapdata._format_time(time(12, 30)) == "12:30"


def test_format_time_none() -> None:
    assert mapdata._format_time(None) is None
