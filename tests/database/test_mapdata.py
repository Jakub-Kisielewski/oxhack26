"""mapdata distance and formatting helpers."""

from __future__ import annotations

import math

from src.database import mapdata


def test_distance_m_zero() -> None:
    pt = (-0.1245, 51.5080)
    assert mapdata.distance_m(pt, pt) == 0.0


def test_distance_m_trafalgar_to_parliament() -> None:
    trafalgar = (-0.1281, 51.5080)
    parliament = (-0.1247, 51.4995)
    d = mapdata.distance_m(trafalgar, parliament)
    assert 900 < d < 1050


def test_distance_m_known_haversine() -> None:
    a = (0.0, 0.0)
    b = (0.0, 1.0)
    assert math.isclose(mapdata.distance_m(a, b), 111_195, rel_tol=0.01)
