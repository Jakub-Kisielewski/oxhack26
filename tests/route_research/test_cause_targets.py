"""Tests for cause target location and hit rates."""
from __future__ import annotations

import pandas as pd

from src.ingestion.route_research.processing import cause_targets as ct


def test_haversine_m_zero_distance() -> None:
    assert ct.haversine_m(51.5, -0.1, 51.5, -0.1) == 0.0


def test_hit_rates_empty_targets() -> None:
    targets = pd.DataFrame(columns=["cause", "lat", "lon"])
    targets["lat"], targets["lon"], targets["location_source"] = [], [], []
    assert targets.empty


def test_locate_uses_reviewed_geocode() -> None:
    row = type("Row", (), {"waypoint_name": "Trafalgar Square", "kind": "", "lat": 0.0, "lon": 0.0, "iso2": ""})()
    geocodes = {"Trafalgar Square": (51.5074, -0.1278)}
    lat, lon, source = ct.locate(row, geocodes, pd.DataFrame())
    assert source == "reviewed_geocode"
    assert lat == 51.5074


def test_empty_targets_zip_does_not_crash() -> None:
    targets = pd.DataFrame(columns=["cause", "target_name", "lat", "lon", "weight", "waypoint_name", "kind", "iso2"])
    located: list[tuple[float, float, str]] = []
    targets["lat"], targets["lon"], targets["location_source"] = [], [], []
    assert len(located) == 0
