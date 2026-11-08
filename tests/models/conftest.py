from __future__ import annotations

import pytest

from src.models.graph import MarchGraph, Segment, bearing
from src.models.labels import TrainingEvent


def _pt(lon: float, lat: float) -> tuple[float, float]:
    return (lon, lat)


def _seg(
    sid: str,
    u: str,
    v: str,
    p0: tuple[float, float],
    p1: tuple[float, float],
    *,
    name: str = "High Street",
    is_main: bool = True,
    width: float = 5.0,
    bridge: bool = False,
) -> Segment:
    path = [p0, p1]
    return Segment(
        sid,
        u,
        v,
        100.0,
        "primary",
        name,
        width,
        0.0,
        2.0,
        is_main,
        bridge,
        False,
        False,
        False,
        path,
        ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2),
        bearing(p0, p1),
        bearing(p0, p1),
    )


@pytest.fixture
def tiny_graph() -> MarchGraph:
    """Three segments: approach, straight ahead, and side branch at one junction."""
    s0 = _seg("s0", "n1", "n2", _pt(-0.12, 51.5), _pt(-0.11, 51.5))
    s1 = _seg("s1", "n2", "n3", _pt(-0.11, 51.5), _pt(-0.10, 51.5), name="High Street")
    s2 = _seg(
        "s2", "n2", "n4", _pt(-0.11, 51.5), _pt(-0.11, 51.51), name="Side Road", is_main=False
    )
    return MarchGraph({"s0": s0, "s1": s1, "s2": s2})


def make_event(
    event_id: str,
    date: str,
    route: list[str],
    dest: tuple[float, float] | None = None,
) -> TrainingEvent:
    dest = dest or _pt(-0.10, 51.5)
    return TrainingEvent(
        event_id,
        date,
        "test",
        {"turnout": 1000, "precip_mm_4h": 0.0, "dark_fraction": 0.0},
        dest,
        route,
        [1.0] * len(route),
        "Parliament",
    )


@pytest.fixture(autouse=True)
def stub_cause_targets(monkeypatch):
    monkeypatch.setattr(
        "src.models.backtest.mapdata.cause_targets",
        lambda _cause=None: [],
    )
    monkeypatch.setattr(
        "src.models.destinations.mapdata.cause_targets",
        lambda _cause=None: [],
    )


@pytest.fixture
def tiny_events(tiny_graph: MarchGraph) -> list[TrainingEvent]:
    return [
        make_event("e1", "2024-01-01", ["s0", "s1"]),
        make_event("e2", "2024-02-01", ["s0", "s2"]),
        make_event("e3", "2024-03-01", ["s0", "s1"]),
    ]
