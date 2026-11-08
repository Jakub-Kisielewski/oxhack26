"""Unit tests for edge feature helpers and build output."""

from __future__ import annotations

import networkx as nx
import pandas as pd
import pytest
from shapely.geometry import LineString

from src.ingestion.route_research.processing import edge_features as ef


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("5 m", 5.0),
        ("12 ft", pytest.approx(3.6576, rel=0.01)),
        ("999", None),
        (None, None),
    ],
)
def test_parse_width(raw: object, expected: float | None) -> None:
    assert ef.parse_width(raw) == expected


def test_parse_lanes() -> None:
    assert ef.parse_lanes("2") == 2
    assert ef.parse_lanes("0") is None


def test_estimate_width_uses_osm_tag() -> None:
    assert ef.estimate_width("primary", "8", None) == pytest.approx(8 + ef.PAVEMENTS_M)


def test_as_list() -> None:
    assert ef.as_list("a;b") == ["a;b"]


def test_is_bridge_tag() -> None:
    assert ef.is_bridge_tag("yes")
    assert not ef.is_bridge_tag("no")


def test_undirected_keeps_shorter_parallel_edge() -> None:
    graph = nx.MultiDiGraph()
    graph.add_edge(1, 2, key=0, length=10)
    graph.add_edge(1, 2, key=1, length=5)
    simple = ef.undirected(graph)
    assert simple[1][2]["length"] == 5


def test_build_columns_match_route_model_consumers(monkeypatch) -> None:
    walk = nx.MultiDiGraph()
    walk.add_edge(1, 2, key=0, length=10, highway="primary", bridge="yes")
    walk.add_edge(2, 3, key=0, length=10, highway="footway")
    main = nx.MultiDiGraph()
    main.add_edge(1, 2, key=0, length=10, highway="primary")

    edges = pd.DataFrame(
        {
            "u": [1, 2],
            "v": [2, 3],
            "key": [0, 0],
            "highway": ["primary", "footway"],
            "width": [None, None],
            "lanes": [None, None],
            "length": [10.0, 10.0],
            "bridge": ["yes", None],
            "geometry": [
                LineString([(-0.1, 51.5), (-0.09, 51.5)]),
                LineString([(-0.09, 51.5), (-0.08, 51.5)]),
            ],
        }
    )

    monkeypatch.setattr(
        "src.ingestion.route_research.processing.edge_features.ox.graph_to_gdfs",
        lambda *a, **k: edges,
    )
    missing = __import__("pathlib").Path("nope")
    out = ef.build(walk, main, missing)
    assert set(out.columns) == {
        "segment_id",
        "width_m",
        "is_main",
        "is_bridge",
        "in_no_entry_zone",
        "in_restricted_zone",
    }
    assert out.loc[out.segment_id == "1:2:0", "is_bridge"].iloc[0]
    assert not out.loc[out.segment_id == "2:3:0", "is_main"].iloc[0]
