"""Tests for Open-Meteo date merging."""
from __future__ import annotations

import datetime as dt

from src.ingestion.route_research.sources import download_weather as dw


def test_date_ranges_merges_adjacent_days() -> None:
    days = {dt.date(2024, 1, 1), dt.date(2024, 1, 2), dt.date(2024, 1, 5)}
    ranges = dw.date_ranges(days)
    assert len(ranges) == 1


def test_split_by_source_archive_then_forecast() -> None:
    today = dt.date(2024, 6, 15)
    start, end = dt.date(2024, 6, 1), dt.date(2024, 6, 20)
    pieces = list(dw.split_by_source(start, end, today))
    sources = {piece[0] for piece in pieces}
    assert "archive" in sources
