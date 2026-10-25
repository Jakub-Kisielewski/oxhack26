"""Folium click map for picking points (start, end, route waypoints, shop).

Folium works in [lat, lon]; everything returned here is (lon, lat) like the contract.
`pick_map` returns a point only for a NEW click inside the zones 1-2 boundary, so
reruns caused by other widgets don't re-add the same click.
"""
from __future__ import annotations

from typing import Optional

import folium
import streamlit as st
from streamlit_folium import st_folium

from src.contract.types import LonLat, Path
from src.ui import common, layers

DEFAULT_CENTER: LonLat = (-0.128, 51.507)


def _latlon(p: LonLat) -> list[float]:
    return [p[1], p[0]]


def pick_map(key: str, markers: Optional[list[dict]] = None, line: Optional[Path] = None,
             center: Optional[LonLat] = None, zoom: int = 13, height: int = 420) -> Optional[LonLat]:
    """markers: [{"lonlat", "label", "kind": start|end|waypoint|shop|place}]."""
    # OpenStreetMap tiles: folium's built-in CartoDB tiles now ask for an API key.
    m = folium.Map(location=_latlon(center or DEFAULT_CENTER), zoom_start=zoom, control_scale=True,
                   tiles="OpenStreetMap")
    ink = layers.INK["light"]   # OSM tiles are light in either app theme
    for ring in common.boundary():
        folium.PolyLine([_latlon(p) for p in ring], color=ink["secondary"], weight=1.5, dash_array="6 6",
                        tooltip="Zones 1-2 boundary").add_to(m)
    if line and len(line) > 1:
        folium.PolyLine([_latlon(p) for p in line], color=ink["primary"], weight=3, opacity=0.8).add_to(m)
    fills = {"start": ink["primary"], "end": ink["surface"], "waypoint": ink["primary"],
             "shop": layers.MAGENTA["light"], "place": layers.AQUA["light"]}
    for marker in markers or []:
        kind = marker.get("kind", "place")
        folium.CircleMarker(_latlon(marker["lonlat"]), radius=8 if kind in ("start", "end", "shop") else 6,
                            color=ink["primary"], weight=2, fill=True, fill_opacity=1,
                            fill_color=fills.get(kind, layers.AQUA["light"]), tooltip=marker.get("label", "")).add_to(m)
    out = st_folium(m, height=height, use_container_width=True, returned_objects=["last_clicked"], key=key)
    click = (out or {}).get("last_clicked")
    if not click:
        return None
    point = (round(float(click["lng"]), 6), round(float(click["lat"]), 6))
    seen_key = f"{key}__last_click"
    if st.session_state.get(seen_key) == point:
        return None
    st.session_state[seen_key] = point
    if not common.in_boundary(point):
        st.warning("That point is outside the zones 1-2 area. Pick a point inside the dashed line.",
                   icon=":material/wrong_location:")
        return None
    return point
