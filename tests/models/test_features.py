from __future__ import annotations

import math

from src.models.features import NAMES, dark_fraction, feature_vector
from tests.models.conftest import _pt


def test_feature_vector_length_and_order(tiny_graph) -> None:
    dest = _pt(-0.10, 51.5)
    x = feature_vector(tiny_graph, "s0", "s1", dest)
    assert len(x) == len(NAMES)
    assert list(NAMES) == list(NAMES)


def test_progress_positive_when_candidate_nearer(tiny_graph) -> None:
    dest = _pt(-0.10, 51.5)
    net = tiny_graph.network_distances_to(dest)
    x_near = feature_vector(tiny_graph, "s0", "s1", dest, net_dist=net)
    x_far = feature_vector(tiny_graph, "s0", "s2", dest, net_dist=net)
    assert x_near[0] > x_far[0]


def test_turn_in_unit_interval(tiny_graph) -> None:
    dest = _pt(-0.10, 51.5)
    x = feature_vector(tiny_graph, "s0", "s1", dest)
    assert 0.0 <= x[3] <= 1.0


def test_name_continuity(tiny_graph) -> None:
    dest = _pt(-0.10, 51.5)
    x = feature_vector(tiny_graph, "s0", "s1", dest)
    assert x[NAMES.index("name_continuity")] == 1.0


def test_zero_width_does_not_produce_neg_inf(tiny_graph) -> None:
    seg = tiny_graph.segments["s1"]
    seg.width = 0.0
    dest = _pt(-0.10, 51.5)
    x = feature_vector(tiny_graph, "s0", "s1", dest)
    assert math.isfinite(x[NAMES.index("log_width")])


def test_dark_fraction_clamped() -> None:
    assert dark_fraction(0) == 1.0
    assert dark_fraction(10) == 0.0
    assert dark_fraction(None) == 0.0


def test_dark_fraction_respects_march_hours() -> None:
    assert dark_fraction(2.0, march_hours=4.0) == 0.5


def test_dark_fraction_boundary_at_march_hours() -> None:
    assert dark_fraction(4.0, march_hours=4.0) == 0.0
