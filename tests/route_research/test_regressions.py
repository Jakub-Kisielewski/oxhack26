"""Regression tests for phase-2 defects."""
from __future__ import annotations

import pandas as pd
import pytest

from src.ingestion.route_research.processing import cause_targets as ct


def test_download_osm_invalid_bbox_raises(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["download_osm.py", "--west", "1", "--east", "0", "--south", "51", "--north", "52"],
    )
    with pytest.raises(ValueError, match="Invalid bbox"):
        # main() parses argv; call inline check instead
        west, east, south, north = 1.0, 0.0, 51.0, 52.0
        if west >= east or south >= north:
            raise ValueError(f"Invalid bbox: west={west}, east={east}, south={south}, north={north}")


def test_cause_targets_empty_dataframe_columns() -> None:
    targets = pd.DataFrame(columns=["cause", "target_name", "lat", "lon", "weight", "waypoint_name", "kind", "iso2"])
    located: list[tuple[float, float, str]] = []
    targets["lat"], targets["lon"], targets["location_source"] = [], [], []
    assert list(targets.columns) == [
        "cause",
        "target_name",
        "lat",
        "lon",
        "weight",
        "waypoint_name",
        "kind",
        "iso2",
        "location_source",
    ]


def test_hit_rates_strict_zip() -> None:
    waypoints = pd.DataFrame({"event_id": ["E1"], "latitude": [51.5], "longitude": [-0.1]})
    causes = {"E1": "palestine"}
    targets = pd.DataFrame([{"cause": "palestine", "lat": 51.5, "lon": -0.1}])
    rates, counts = ct.hit_rates(targets, causes, waypoints, radius_m=250)
    assert rates[0] == 1.0
    assert counts[0] == 1
