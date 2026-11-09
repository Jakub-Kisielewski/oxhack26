"""Build pydeck layers for London context and march paths."""

from __future__ import annotations

import math

import pydeck as pdk

from src.database import mapdata
from src.database.types import LonLat, Polyline
from src.models.graph import MarchGraph

# Central London; extent beyond this usually means chord-corrupted geometry.
MAX_ROUTE_LON = (-0.35, 0.15)
MAX_ROUTE_LAT = (51.35, 51.65)
MAX_ROUTE_SPAN_DEG = 0.2


def lon_lat_in_london(lon: float, lat: float) -> bool:
    """True when a lon/lat pair is inside the central London map window."""
    return MAX_ROUTE_LON[0] <= lon <= MAX_ROUTE_LON[1] and MAX_ROUTE_LAT[0] <= lat <= MAX_ROUTE_LAT[1]


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
        width_min_pixels=2,
        pickable=False,
    )


def trim_polyline_backtrack(
    coords: Polyline,
    *,
    min_gap: int = 25,
    close_m: float = 25.0,
) -> Polyline:
    """Drop short out-and-back spurs when a polyline nearly revisits an earlier point (map display)."""
    if len(coords) < min_gap + 2:
        return coords
    out: list[LonLat] = []
    for p in coords:
        cut: int | None = None
        for i in range(0, max(0, len(out) - min_gap)):
            if mapdata.distance_m(p, out[i]) < close_m:
                cut = i
        if cut is not None:
            out = out[: cut + 1]
        out.append(p)
    return out


def route_path_features(
    g: MarchGraph,
    segment_ids: list[str],
    color_hex: str,
    width: int,
    name: str,
    *,
    overlap: float | None = None,
    n_steps: int | None = None,
    dash_array: list[int] | None = None,
    alpha: int = 200,
    trim_backtrack: bool = False,
) -> list[dict]:
    """Deck.gl path rows (one row per contiguous run)."""
    features: list[dict] = []
    runs = g.geometry_runs(segment_ids) if segment_ids else []
    steps = n_steps if n_steps is not None else len(segment_ids)
    tip_extra = ""
    if overlap is not None:
        tip_extra = f" · overlap {overlap * 100:.1f}% · {steps} segments"
    for i, run in enumerate(runs):
        if not run:
            continue
        line = trim_polyline_backtrack(run) if trim_backtrack else run
        label = name if i == 0 else f"{name} (part {i + 1})"
        feat: dict = {
            "path": lonlat_path(line),
            "color": hex_to_rgb(color_hex, alpha),
            "width": width,
            "name": label,
            "tooltip": f"{label}{tip_extra}",
        }
        if dash_array:
            feat["dash_array"] = dash_array
        features.append(feat)
    return features


def feature_path_layer(feature: dict) -> pdk.Layer:
    """One path with fixed color/width (Streamlit pydeck often omits accessor-based PathLayers)."""
    row = {
        "path": feature["path"],
        "name": feature.get("name", ""),
        "tooltip": feature.get("tooltip", feature.get("name", "")),
    }
    layer_kw: dict = {
        "data": [row],
        "get_path": "path",
        "get_color": feature["color"],
        "get_width": feature["width"],
        "width_min_pixels": 2,
        "pickable": True,
    }
    dash = feature.get("dash_array")
    if dash:
        layer_kw["get_dash_array"] = dash
        layer_kw["dash_justified"] = True
    return pdk.Layer("PathLayer", **layer_kw)


def scatter_marker_layer(
    points: list[dict],
    radius_px: float = 10,
) -> pdk.Layer:
    """Start / end / destination markers (pixel radius — omit ``radius_units`` for Streamlit)."""
    if not points:
        return pdk.Layer("ScatterplotLayer", data=[])
    rows = [{**p, "radius_px": p.get("radius_px", radius_px)} for p in points]
    return pdk.Layer(
        "ScatterplotLayer",
        data=rows,
        get_position="position",
        get_fill_color="color",
        get_radius="radius_px",
        radius_min_pixels=4,
        radius_max_pixels=24,
        pickable=True,
    )


def feature_path_layers(features: list[dict]) -> list[pdk.Layer]:
    """Deck layers for each route run (fixed styling per layer)."""
    return [feature_path_layer(f) for f in features if f.get("path")]


def _bearing_deg(a: LonLat, b: LonLat) -> float:
    lon1, lat1 = math.radians(a[0]), math.radians(a[1])
    lon2, lat2 = math.radians(b[0]), math.radians(b[1])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def arrow_points_along_path(
    path: list[list[float]],
    color: list[int],
    *,
    spacing_m: float = 180.0,
) -> list[dict]:
    """Sample direction chevrons along a deck.gl path (cumulative arc length)."""
    if len(path) < 2:
        return []
    coords: list[LonLat] = [(float(p[0]), float(p[1])) for p in path]
    points: list[dict] = []
    travelled = 0.0
    next_mark = spacing_m * 0.55
    for i in range(len(coords) - 1):
        a, b = coords[i], coords[i + 1]
        seg_len = mapdata.distance_m(a, b)
        if seg_len < 0.5:
            continue
        bearing = _bearing_deg(a, b)
        while travelled + seg_len >= next_mark:
            along = next_mark - travelled
            t = along / seg_len
            lon = a[0] + (b[0] - a[0]) * t
            lat = a[1] + (b[1] - a[1]) * t
            points.append({"position": [lon, lat], "angle": bearing, "color": color})
            next_mark += spacing_m
        travelled += seg_len
    return points


def _offset_lonlat(lon: float, lat: float, bearing_deg: float, dist_m: float) -> LonLat:
    lat_r = math.radians(lat)
    m_lon = 111_320 * math.cos(lat_r)
    m_lat = 111_320
    br = math.radians(bearing_deg)
    return lon + dist_m * math.sin(br) / m_lon, lat + dist_m * math.cos(br) / m_lat


def _chevron_path(
    lon: float,
    lat: float,
    bearing_deg: float,
    *,
    size_m: float = 30.0,
) -> list[list[float]]:
    """Small V-shaped path pointing along ``bearing_deg`` (Streamlit-safe PathLayer)."""
    tip = _offset_lonlat(lon, lat, bearing_deg, size_m * 0.42)
    left = _offset_lonlat(lon, lat, (bearing_deg + 152) % 360, size_m * 0.38)
    right = _offset_lonlat(lon, lat, (bearing_deg - 152) % 360, size_m * 0.38)
    return [[left[0], left[1]], [tip[0], tip[1]], [right[0], right[1]]]


def direction_chevron_features(
    features: list[dict],
    *,
    spacing_m: float = 180.0,
    max_per_path: int = 14,
) -> list[dict]:
    """Path rows for direction chevrons along each visible route."""
    out: list[dict] = []
    for feat in features:
        path = feat.get("path")
        color = feat.get("color")
        if not path or not color:
            continue
        pts = arrow_points_along_path(path, color, spacing_m=spacing_m)
        if len(pts) > max_per_path:
            step = max(1, len(pts) // max_per_path)
            pts = pts[::step][:max_per_path]
        line_w = int(feat.get("width") or 3)
        chev_w = min(8, max(4, line_w))
        chev_color = list(color)
        if len(chev_color) == 4:
            chev_color[3] = 255
        for pt in pts:
            lon, lat = pt["position"]
            out.append(
                {
                    "path": _chevron_path(lon, lat, pt["angle"], size_m=28.0),
                    "color": chev_color,
                    "width": chev_w,
                    "name": "",
                }
            )
    return out


def route_path_and_chevron_layers(features: list[dict]) -> list[pdk.Layer]:
    """Each route path followed by its direction chevrons (visible on every layer)."""
    layers: list[pdk.Layer] = []
    for feat in features:
        if not feat.get("path"):
            continue
        layers.append(feature_path_layer(feat))
        chevrons = direction_chevron_features([feat])
        layers.extend(feature_path_layers(chevrons))
    return layers


def _closed_ring_path(ring: Polyline) -> list[list[float]]:
    pts = lonlat_path(ring)
    if len(pts) >= 2 and pts[0] != pts[-1]:
        pts = pts + [pts[0]]
    return pts


def ring_outline_layers(
    rings: tuple[Polyline, ...] | list[Polyline],
    color: list[int],
    width: int = 3,
) -> list[pdk.Layer]:
    """Ring outlines via PathLayer (PolygonLayer strokes are unreliable in Streamlit pydeck)."""
    layers: list[pdk.Layer] = []
    for ring in rings:
        path = _closed_ring_path(ring)
        if len(path) < 2:
            continue
        layers.append(
            feature_path_layer(
                {"path": path, "color": color, "width": width, "name": ""},
            )
        )
    return layers


RESTRICTED_ZONE_FILL = [239, 68, 68, 125]
RESTRICTED_ZONE_STROKE = [185, 28, 28, 230]


def legal_zone_layers(zones: tuple[dict, ...] | list[dict]) -> list[pdk.Layer]:
    """Filled red restricted areas (single GeoJsonLayer — reliable fill in Streamlit)."""
    if not zones:
        return []
    features: list[dict] = []
    for zone in zones:
        ring = zone.get("polygon") or []
        if len(ring) < 3:
            continue
        coords = [[float(lon), float(lat)] for lon, lat in ring]
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        features.append(
            {
                "type": "Feature",
                "properties": {"name": str(zone.get("name") or "")},
                "geometry": {"type": "Polygon", "coordinates": [coords]},
            }
        )
    if not features:
        return []
    return [
        pdk.Layer(
            "GeoJsonLayer",
            data={"type": "FeatureCollection", "features": features},
            get_fill_color=RESTRICTED_ZONE_FILL,
            get_line_color=RESTRICTED_ZONE_STROKE,
            get_line_width=2,
            line_width_min_pixels=2,
            filled=True,
            stroked=True,
            pickable=False,
        )
    ]


def polygon_fill_layers(
    rings: tuple[Polyline, ...] | list[Polyline],
    fill_color: list[int],
    line_color: list[int] | None = None,
) -> list[pdk.Layer]:
    """One filled PolygonLayer per ring (avoids multi-feature fill glitches)."""
    stroke = line_color if line_color is not None else fill_color
    layers: list[pdk.Layer] = []
    for ring in rings:
        if len(ring) < 3:
            continue
        layers.append(
            pdk.Layer(
                "PolygonLayer",
                data=[{"polygon": [lonlat_path(ring)]}],
                get_polygon="polygon",
                get_fill_color=fill_color,
                get_line_color=stroke,
                get_line_width=1,
                line_width_min_pixels=1,
                filled=True,
                stroked=True,
                pickable=False,
            )
        )
    return layers


def polygon_layers_from_rings(
    rings: tuple[Polyline, ...] | list[Polyline],
    color: list[int],
    filled: bool = False,
    outline_width: int = 3,
) -> list[pdk.Layer]:
    """Outline or fill rings from GeoJSON-derived polylines."""
    if not rings:
        return []
    if filled:
        return polygon_fill_layers(rings, color)
    return ring_outline_layers(rings, color, width=outline_width)


def coords_for_fit(g: MarchGraph, segment_ids: list[str]) -> list[LonLat]:
    """All points used to frame the map (every contiguous run)."""
    return [p for run in g.geometry_runs(segment_ids) for p in run]


def initial_view_state(g: MarchGraph) -> pdk.ViewState:
    """Centre on the graph midpoint."""
    if g.segments:
        mid = next(iter(g.segments.values())).path[0]
        return pdk.ViewState(longitude=mid[0], latitude=mid[1], zoom=11, pitch=0)
    return pdk.ViewState(longitude=-0.1278, latitude=51.5074, zoom=11, pitch=0)


def view_state_for_coords(coords: list[LonLat], *, pad_frac: float = 0.18) -> pdk.ViewState | None:
    """Fit view to route points with symmetric padding (central London)."""
    if not coords:
        return None
    lons = [float(c[0]) for c in coords]
    lats = [float(c[1]) for c in coords]
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)
    lon_span = max(max_lon - min_lon, 0.002)
    lat_span = max(max_lat - min_lat, 0.002)
    raw_span = max(lon_span, lat_span)
    if raw_span > MAX_ROUTE_SPAN_DEG:
        return None
    pad_lon = max(lon_span * pad_frac, 0.003)
    pad_lat = max(lat_span * pad_frac, 0.003)
    min_lon -= pad_lon
    max_lon += pad_lon
    min_lat -= pad_lat
    max_lat += pad_lat
    mid_lat = (min_lat + max_lat) / 2
    lat_rad = math.radians(mid_lat)
    meters_per_deg_lon = 111_320 * math.cos(lat_rad)
    meters_per_deg_lat = 111_320
    fit_lon = max_lon - min_lon
    fit_lat = max_lat - min_lat
    span_m = max(fit_lon * meters_per_deg_lon, fit_lat * meters_per_deg_lat)
    # viewport ~600px tall; include padding so every route stays in frame
    zoom = 16 - math.log2(max(span_m, 120.0) / 820.0)
    zoom = max(10.5, min(16.5, zoom))
    return pdk.ViewState(
        longitude=(min_lon + max_lon) / 2,
        latitude=(min_lat + max_lat) / 2,
        zoom=zoom,
        pitch=0,
    )


def map_view_interactive() -> pdk.View:
    """MapView with scroll-wheel zoom and pan enabled."""
    return pdk.View(
        type="MapView",
        controller={
            "scrollZoom": True,
            "dragPan": True,
            "doubleClickZoom": True,
            "touchZoom": True,
            "touchRotate": False,
        },
    )


def map_view_no_scroll() -> pdk.View:
    """Legacy alias — prefer :func:`map_view_interactive`."""
    return map_view_interactive()
