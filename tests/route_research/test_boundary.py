"""Geospatial smoke tests for TfL boundary polygon."""
from __future__ import annotations

import geopandas as gpd

from src.ingestion.route_research.sources.download_boundary import (
    build_polygon,
    parse_zones,
    zone_of,
)


def test_parse_zones() -> None:
    assert parse_zones("1/2") == {1, 2}


def test_zone_of_reads_property() -> None:
    stop = {"additionalProperties": [{"key": "Zone", "value": "2"}]}
    assert zone_of(stop) == "2"


def test_boundary_polygon_is_built_in_a_metric_crs() -> None:
    stations = [
        {"lat": 51.5074, "lon": -0.1278},
        {"lat": 51.5155, "lon": -0.1410},
        {"lat": 51.4980, "lon": -0.1195},
        {"lat": 51.5200, "lon": -0.1050},
    ]
    polygon = build_polygon(stations, buffer_m=300.0, ratio=1.0)
    area_km2 = gpd.GeoSeries([polygon], crs="EPSG:4326").to_crs("EPSG:27700").area.iloc[0] / 1e6
    assert 2 < area_km2 < 20
