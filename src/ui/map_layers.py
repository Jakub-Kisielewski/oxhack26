"""Build pydeck layers for London context and march paths."""

from __future__ import annotations

import pydeck as pdk

from src.database.types import LonLat, Polyline
from src.models.graph import MarchGraph


def hex_to_rgb(hex_color: str, alpha: int = 200) -> list[int]:
    """Convert ``#rrggbb`` to deck.gl ``[r,g,b,a]``."""
    h = hex_color.lstrip("#")
    return [int(h[i : i + 2], 16) for i in (0, 2, 4)] + [alpha]


def lonlat_path(coords: list[LonLat]) -> list[list[float]]:
    """Deck.gl path as ``[[lon, lat], ...]``."""
    return [[float(lon), float(lat)] for lon, lat in coords]


def path_layer(
    coords: list[LonLat],
    color_hex: str,
    width: int = 4,
    name: str = "",
) -> pdk.Layer:
    """One coloured route polyline."""
    data = [{"path": lonlat_path(coords), "name": name}] if coords else []
    return pdk.Layer(
        "PathLayer",
        data=data,
        get_path="path",
        get_color=hex_to_rgb(color_hex),
        get_width=width,
        width_units="pixels",
        pickable=True,
    )


def polygon_layers_from_rings(
    rings: tuple[Polyline, ...] | list[Polyline],
    color: list[int],
    filled: bool = False,
) -> list[pdk.Layer]:
    """Outline or fill rings from GeoJSON-derived polylines."""
    if not rings:
        return []
    # deck.gl expects GeoJSON-style nesting: [outer_ring, hole, ...].
    data = [{"polygon": [lonlat_path(ring)]} for ring in rings]
    return [
        pdk.Layer(
            "PolygonLayer",
            data=data,
            get_polygon="polygon",
            get_fill_color=color if filled else [0, 0, 0, 0],
            get_line_color=color,
            get_line_width=2,
            line_width_units="pixels",
            filled=filled,
            stroked=True,
            pickable=False,
        )
    ]


def geometry_path(g: MarchGraph, segment_ids: list[str]) -> list[LonLat]:
    """Concatenated coordinates for segment ids."""
    return g.geometry(segment_ids) if segment_ids else []


def initial_view_state(g: MarchGraph) -> pdk.ViewState:
    """Centre on the graph midpoint."""
    if g.segments:
        mid = next(iter(g.segments.values())).path[0]
        return pdk.ViewState(longitude=mid[0], latitude=mid[1], zoom=11, pitch=0)
    return pdk.ViewState(longitude=-0.1278, latitude=51.5074, zoom=11, pitch=0)


def view_state_for_coords(coords: list[LonLat]) -> pdk.ViewState | None:
    """Fit view to a set of route points (central London scale)."""
    if not coords:
        return None
    lons = [float(c[0]) for c in coords]
    lats = [float(c[1]) for c in coords]
    span = max(max(lons) - min(lons), max(lats) - min(lats), 1e-5)
    zoom = 14 if span < 0.015 else 13 if span < 0.04 else 12 if span < 0.08 else 11
    return pdk.ViewState(
        longitude=(min(lons) + max(lons)) / 2,
        latitude=(min(lats) + max(lats)) / 2,
        zoom=zoom,
        pitch=0,
    )
