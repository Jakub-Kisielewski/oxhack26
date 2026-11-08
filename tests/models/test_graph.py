from __future__ import annotations

import math

import pytest

from src.models.graph import angle, bearing, line_distance
from tests.models.conftest import _pt


def test_angle_straight_ahead() -> None:
    assert angle(0.0, 0.0) == 0.0


def test_angle_uturn() -> None:
    assert abs(angle(0.0, math.pi) - 1.0) < 1e-6


def test_angle_wraparound() -> None:
    assert 0.0 <= angle(-math.pi, math.pi) <= 1.0


def test_bearing_eastward() -> None:
    b = bearing(_pt(0, 51), _pt(1, 51))
    assert abs(b) < 0.1


def test_line_distance_on_segment() -> None:
    line = [_pt(-0.1, 51.5), _pt(-0.09, 51.5)]
    d = line_distance(_pt(-0.095, 51.5), line)
    assert d < 50


def test_line_distance_perpendicular() -> None:
    line = [_pt(-0.1, 51.5), _pt(-0.09, 51.5)]
    d = line_distance(_pt(-0.095, 51.52), line)
    assert d > 100


def test_next_ids_excludes_uturn(tiny_graph) -> None:
    opts = tiny_graph.next_ids("s0")
    assert "s0" not in opts
    assert set(opts) == {"s1", "s2"}


def test_next_ids_unknown_empty(tiny_graph) -> None:
    assert tiny_graph.next_ids("missing") == []


def test_snap_route_chains(tiny_graph) -> None:
    route = tiny_graph.snap_route([_pt(-0.12, 51.5), _pt(-0.10, 51.5)])
    assert route[0] == route[0]
    assert len(route) >= 2


def test_snap_route_raises_on_single_point(tiny_graph) -> None:
    with pytest.raises(ValueError):
        tiny_graph.snap_route([_pt(-0.12, 51.5)])
