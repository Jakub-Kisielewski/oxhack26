"""Tests for TfL road disruption source."""

from __future__ import annotations

from typing import Any

from ingestion.crawler.sources.tfl import TflRoadDisruptionSource


class StubHttpClient:
    def __init__(self, json_payload: list[dict[str, Any]]) -> None:
        self._json_payload = json_payload

    def get_json(self, url: str, *, params: dict | None = None) -> object:
        return self._json_payload


def test_remembrance_event_is_excluded() -> None:
    """Regression for operator-precedence bug (A1)."""
    payload = [
        {
            "id": "TIMS-1",
            "subCategory": "Event",
            "comments": "Remembrance Sunday demonstration road closures",
            "location": "Whitehall",
            "category": "Event",
            "url": "/Road/disruptions/1",
        }
    ]
    source = TflRoadDisruptionSource(client=StubHttpClient(payload))  # type: ignore[arg-type]
    assert source.fetch_records() == []


def test_demonstration_march_without_remembrance_kept() -> None:
    payload = [
        {
            "id": "TIMS-2",
            "subCategory": "Event",
            "comments": "Demonstration - Whitehall",
            "location": "Whitehall",
            "category": "Event",
            "url": "/Road/disruptions/2",
        }
    ]
    source = TflRoadDisruptionSource(client=StubHttpClient(payload))  # type: ignore[arg-type]
    records = source.fetch_records()
    assert len(records) == 1


def test_parse_point_rejects_bad_json_list() -> None:
    source = TflRoadDisruptionSource()
    assert source._parse_point("[1.0, 2.0, 3.0]") == (None, None)


def test_parse_point_accepts_valid_pair() -> None:
    source = TflRoadDisruptionSource()
    lat, lon = source._parse_point([-0.1, 51.5])
    assert lat == 51.5 and lon == -0.1
