"""pydeck layer builders, colour scales and the shared legend. All coordinates (lon, lat).

Colour follows the job each layer does (see the dataviz guidance):
  magnitude   p_visit, hexagon heat, crowd density (LOS)  -> blue sequential/ordinal ramp
  2nd magnitude  spill risk                                 -> orange ramp
  identity    warehouses / police posts                     -> aqua (categorical slot 3)
  routes, hotspots, start/end                               -> neutral ink + number labels
  legal zones / risk levels                                 -> reserved status colours, always labelled
Every pickable object carries `tooltip` (HTML) and `lon`/`lat` (used for pin drops).
"""
from __future__ import annotations

import html
import math
import unicodedata
from typing import Iterable, Optional

import pydeck as pdk
import streamlit as st

from src.contract.types import (CellValue, Destination, Hotspot, LonLat, Path, PolicePost, RouteOption, SegmentProb,
                                SegmentTiming, SpillRisk, WarehouseOption)
from src.ui import common

# ---------- palette (light / dark steps of the same ramps) ----------

BLUE = {"light": ["#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"],
        "dark": ["#184f95", "#1c5cab", "#256abf", "#2a78d6", "#3987e5", "#5598e7", "#6da7ec", "#86b6ef", "#9ec5f4", "#b7d3f6"]}
ORANGE = {"light": ["#f6c0a6", "#f3a07c", "#ef8456", "#eb6834", "#d4582a", "#b84a21", "#9a3d1a", "#7d3014"],
          "dark": ["#7d3014", "#9a3d1a", "#b84a21", "#d95926", "#ea7445", "#f08f68", "#f4ab8d", "#f8c7b2"]}
AQUA = {"light": "#1baf7a", "dark": "#199e70"}
MAGENTA = {"light": "#e87ba4", "dark": "#d55181"}
GREEN = "#008300"
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}
INK = {"light": {"primary": "#0b0b0b", "secondary": "#52514e", "surface": "#fcfcfb", "muted": "#9a9893"},
       "dark": {"primary": "#f0efec", "secondary": "#c3c2b7", "surface": "#1a1a19", "muted": "#6f6e69"}}
# pydeck turns plain strings into data accessors ("@@=pixels"), which deck.gl silently
# rejects for non-accessor props such as units; literal strings need pdk.types.String.
PIXELS = pdk.types.String("pixels")
# Overlays (routes, labels, markers) ignore depth so 3D hexagon columns never hide them.
ON_TOP = {"depthCompare": "always", "depthTest": False}
LOS_ORDER = ["A", "B", "C", "D", "E", "F"]
LOS_LABEL = {"A": "A: free", "B": "B: comfortable", "C": "C: crowded", "D": "D: very crowded",
             "E": "E: crush risk", "F": "F: dangerous"}
LEGAL = {"no_entry": (STATUS["critical"], "No entry (protected site)"),
         "restricted_activity": (STATUS["warning"], "Controlled area (processions allowed)"),
         "royal_park": (GREEN, "Royal Park (park regulations)")}


def mode() -> str:
    return "dark" if common.is_dark() else "light"


def rgba(hex_color: str, alpha: int = 255) -> list[int]:
    h = hex_color.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)] + [int(alpha)]


def ramp_color(value: float, ramp: list[str], alpha: Optional[int] = None) -> list[int]:
    """Value in [0, 1] -> interpolated ramp colour; low values also fade so they recede."""
    v = min(1.0, max(0.0, float(value)))
    pos = v * (len(ramp) - 1)
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    a, b = rgba(ramp[lo]), rgba(ramp[hi])
    t = pos - lo
    rgb = [round(a[i] + (b[i] - a[i]) * t) for i in range(3)]
    return rgb + [alpha if alpha is not None else round(110 + 140 * v)]


def blue(value: float, alpha: Optional[int] = None) -> list[int]:
    return ramp_color(value, BLUE[mode()], alpha)


def orange(value: float, alpha: Optional[int] = None) -> list[int]:
    return ramp_color(value, ORANGE[mode()], alpha)


def los_color(level: str) -> list[int]:
    ramp = BLUE[mode()]
    idx = LOS_ORDER.index(level) if level in LOS_ORDER else 0
    return rgba(ramp[round(idx * (len(ramp) - 1) / 5)], 235)


def ink(role: str = "primary", alpha: int = 255) -> list[int]:
    return rgba(INK[mode()][role], alpha)


def tip(title: str, *lines: str) -> str:
    body = "".join(f"<div>{html.escape(line)}</div>" for line in lines if line)
    return f"<b>{html.escape(title)}</b>{body}"


def _mid(path: Path) -> LonLat:
    """Point halfway along the path's length (not just the middle vertex)."""
    if len(path) < 2:
        return path[0]
    k = math.cos(math.radians(path[0][1]))
    legs = [math.hypot((b[0] - a[0]) * k, b[1] - a[1]) for a, b in zip(path, path[1:])]
    half = sum(legs) / 2
    for (a, b), leg in zip(zip(path, path[1:]), legs):
        if half <= leg and leg > 0:
            t = half / leg
            return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        half -= leg
    return path[-1]


def _ll(point: LonLat) -> dict:
    return {"lon": point[0], "lat": point[1], "position": [point[0], point[1]]}


def _path_layer(layer_id: str, data: list[dict], pickable: bool = True, on_top: bool = False, **kw) -> pdk.Layer:
    if on_top:
        kw["parameters"] = ON_TOP
    return pdk.Layer("PathLayer", data=data, id=layer_id, get_path="path", get_color="color", get_width="width",
                     width_units=PIXELS, width_min_pixels=1, cap_rounded=True, joint_rounded=True, pickable=pickable, **kw)


def _ascii(text: str) -> str:
    """TextLayer's default font atlas is ASCII; map curly quotes/dashes and drop other accents."""
    text = str(text).translate({0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"', 0x2013: "-", 0x2014: "-"})
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def _labels(layer_id: str, items: list[dict], size: int = 14) -> pdk.Layer:
    """Direct labels: ink text on a surface-coloured background pill."""
    data = [{**item, "text": _ascii(item["text"])} for item in items]
    return pdk.Layer("TextLayer", data=data, id=layer_id, get_position="position", get_text="text", get_size=size,
                     get_color=ink("primary"), background=True, get_background_color=ink("surface", 230),
                     background_padding=[4, 2], get_alignment_baseline=pdk.types.String("bottom"), get_pixel_offset=[0, -10],
                     font_weight=600, pickable=False, parameters=ON_TOP)


# ---------- prediction layers ----------

def segment_prob_layer(segments: list[SegmentProb], names: Optional[dict[str, str]] = None) -> pdk.Layer:
    names = names or {}
    data = [{"path": [list(p) for p in s.path], "color": blue(s.p_visit), "width": 1.5 + 5 * s.p_visit,
             "tooltip": tip(names.get(s.segment_id) or "Street", f"March passes here: {common.pct(s.p_visit)}"),
             **_ll(_mid(s.path))} for s in reversed(segments)]   # most likely drawn last, on top
    return _path_layer("segments", data)


def cell_layer(cells: list[CellValue], extruded: bool = True, label: str = "Chance the march passes") -> pdk.Layer:
    polys = common.cell_polygons()
    data = []
    for c in cells:
        poly = polys.get(c.cell_id)
        if poly:
            data.append({"polygon": [list(p) for p in poly["polygon"]], "color": blue(c.value, 170),
                         "elevation": c.value * 350, "tooltip": tip(f"Area #{c.cell_id}", f"{label}: {common.pct(c.value)}"),
                         **_ll(poly["lonlat"])})
    return pdk.Layer("PolygonLayer", data=data, id="cells", get_polygon="polygon", get_fill_color="color",
                     get_elevation="elevation", extruded=extruded, stroked=not extruded, get_line_color=ink("surface", 120),
                     line_width_min_pixels=1, pickable=True, auto_highlight=True)


def routes_layers(routes: list[RouteOption]) -> list[pdk.Layer]:
    """Top routes as ink lines (route 1 widest) with number labels, drawn over the heatmap."""
    widths = {1: 5.0, 2: 3.5, 3: 2.5}
    out = []
    for r in sorted(routes, key=lambda r: -r.rank):
        out.append(_path_layer(f"route_{r.rank}", [{
            "path": [list(p) for p in r.path], "color": ink("primary", 230 if r.rank == 1 else 170),
            "width": widths.get(r.rank, 2.0),
            "tooltip": tip(f"Route {r.rank} ({common.pct(r.probability)})", f"{common.km(r.length_m)}, about {common.duration(r.duration_min)}",
                           f"Ends at {r.end_label}" if r.end_label else ""), **_ll(_mid(r.path))}], on_top=True))
    out.append(_labels("route_labels", [{"text": str(r.rank), **_ll(_mid(r.path))} for r in routes]))
    return out


def destinations_layers(destinations: list[Destination]) -> list[pdk.Layer]:
    data = [{"radius": 8 + 18 * d.probability, "tooltip": tip(d.name, f"Likely end point: {common.pct(d.probability)}"),
             **_ll(d.lonlat)} for d in destinations]
    rings = pdk.Layer("ScatterplotLayer", data=data, id="destinations", get_position="position", get_radius="radius",
                      radius_units=PIXELS, stroked=True, filled=True, get_fill_color=ink("surface", 140),
                      get_line_color=ink("primary"), line_width_min_pixels=2, pickable=True, parameters=ON_TOP)
    # Only the likeliest end is labelled: nearby ends (e.g. Whitehall and Downing Street) would overlap.
    return [rings, _labels("destination_labels", [{"text": d.name, **_ll(d.lonlat)} for d in destinations[:1]], 12)]


def point_layer(layer_id: str, points: list[tuple[LonLat, str]], color: Optional[list[int]] = None,
                radius: int = 7) -> pdk.Layer:
    """Start/end/shop markers: filled dot with a surface-coloured ring."""
    data = [{"tooltip": tip(label), **_ll(p)} for p, label in points]
    return pdk.Layer("ScatterplotLayer", data=data, id=layer_id, get_position="position", get_radius=radius,
                     radius_units=PIXELS, stroked=True, get_fill_color=color or ink("primary"),
                     get_line_color=ink("surface"), line_width_min_pixels=2, pickable=True, parameters=ON_TOP)


def route_outline_layer(paths: list[Path], layer_id: str = "route_outline") -> pdk.Layer:
    data = [{"path": [list(p) for p in path], "color": ink("muted", 160), "width": 3} for path in paths]
    return _path_layer(layer_id, data, pickable=False)


def timeline_layer(timeline: list[SegmentTiming], t: float, ctx, names: Optional[dict[str, str]] = None) -> pdk.Layer:
    """Route segments occupied at minute t, coloured by crowd density level (LOS)."""
    names = names or {}
    data = [{"path": [list(p) for p in s.path], "color": los_color(s.level_of_service), "width": 7,
             "tooltip": tip(names.get(s.segment_id) or "On the route", f"Crowd level {LOS_LABEL[s.level_of_service]}",
                            f"{s.peak_density_ppm2:.1f} people/m² at peak",
                            f"Crowd here {common.clock(ctx, s.head_arrival_min)} to {common.clock(ctx, s.tail_departure_min)}"),
             **_ll(_mid(s.path))}
            for s in timeline if s.head_arrival_min <= t <= s.tail_departure_min]
    return _path_layer("timeline", data)


def spill_layer(spill: list[SpillRisk], ctx, t: Optional[float] = None) -> pdk.Layer:
    shown = [s for s in spill if t is None or s.window_start_min <= t <= s.window_end_min]
    data = [{"path": [list(p) for p in s.path], "color": orange(s.p_spill), "width": 2 + 5 * s.p_spill,
             "tooltip": tip(f"Spill risk {common.pct(s.p_spill)} ({s.kind})", s.reason,
                            f"{common.clock(ctx, s.window_start_min)} to {common.clock(ctx, s.window_end_min)}"),
             **_ll(_mid(s.path))} for s in reversed(shown)]
    return _path_layer("spill", data)


def hotspot_layers(hotspots: list[Hotspot]) -> list[pdk.Layer]:
    data = [{"tooltip": tip(f"Hotspot {i}: {h.label}", f"{h.level.title()} risk ({common.pct(h.risk)}), {h.kind}"),
             "text": str(i), **_ll(h.lonlat)} for i, h in enumerate(hotspots, 1)]
    rings = pdk.Layer("ScatterplotLayer", data=data, id="hotspots", get_position="position", get_radius=11,
                      radius_units=PIXELS, stroked=True, filled=True, get_fill_color=ink("surface", 90),
                      get_line_color=ink("primary"), line_width_min_pixels=2, pickable=True)
    return [rings, _labels("hotspot_labels", data, 12)]


def warehouse_layers(shop: LonLat, options: list[WarehouseOption]) -> list[pdk.Layer]:
    color = rgba(AQUA[mode()])
    paths = _path_layer("warehouse_paths", [{"path": [list(p) for p in w.path], "color": color[:3] + [200],
                                             "width": 3, "tooltip": tip(f"Option {i}: {w.name or 'Unnamed storage'}",
                                                                        f"{common.km(w.distance_m)} away"), **_ll(w.lonlat)}
                                            for i, w in enumerate(options, 1)])
    dots = pdk.Layer("ScatterplotLayer", id="warehouses_options", get_position="position", get_radius=9, radius_units=PIXELS,
                     stroked=True, get_fill_color=color, get_line_color=ink("surface"), line_width_min_pixels=2, pickable=True,
                     data=[{"text": str(i), "tooltip": tip(f"Option {i}: {w.name or 'Unnamed storage'}",
                                                           f"Disruption risk {common.pct(w.p_disruption)}",
                                                           f"Score {w.utility:.2f}"), **_ll(w.lonlat)}
                           for i, w in enumerate(options, 1)])
    labels = _labels("warehouse_labels", [{"text": str(i), **_ll(w.lonlat)} for i, w in enumerate(options, 1)], 12)
    return [paths, dots, labels]


def police_layer(posts: list[PolicePost], names: Optional[dict[str, str]] = None) -> pdk.Layer:
    names = names or {}
    biggest = max((p.officers for p in posts), default=1)
    data = [{"radius": 5 + 11 * math.sqrt(p.officers / biggest),
             "tooltip": tip(f"{p.officers} officers", names.get(p.segment_id) or "Side street",
                            f"Cuts expected spill here by {p.expected_spill_reduction:.2f}"), **_ll(p.lonlat)} for p in posts]
    return pdk.Layer("ScatterplotLayer", data=data, id="police", get_position="position", get_radius="radius",
                     radius_units=PIXELS, stroked=True, get_fill_color=rgba(AQUA[mode()], 220),
                     get_line_color=ink("surface"), line_width_min_pixels=2, pickable=True)


# ---------- base layers ----------

def boundary_layer() -> pdk.Layer:
    data = [{"path": [list(p) for p in ring], "color": ink("secondary", 150), "width": 1.5} for ring in common.boundary()]
    return _path_layer("boundary", data, pickable=False)


def legal_zones_layer() -> pdk.Layer:
    data = []
    for z in common.legal_zones():
        color, label = LEGAL.get(z["rule_type"], (INK[mode()]["muted"], z["rule_type"]))
        data.append({"polygon": [list(p) for p in z["polygon"]], "fill": rgba(color, 55), "line": rgba(color, 220),
                     "tooltip": tip(z["name"] or label, label), **_ll(z["polygon"][0])})
    return pdk.Layer("PolygonLayer", data=data, id="legal_zones", get_polygon="polygon", get_fill_color="fill",
                     get_line_color="line", line_width_min_pixels=1.5, stroked=True, filled=True, pickable=True)


def targets_layer(targets: list[dict], layer_id: str = "targets") -> pdk.Layer:
    data = [{"tooltip": tip(t.get("name") or t.get("target_name") or "Target",
                            (t.get("category") or t.get("kind") or "").replace("_", " ").title(),
                            f"Country: {t['country']}" if t.get("country") else "",
                            f"Prior weight {t['weight']:.1f}" if t.get("weight") is not None else ""), **_ll(t["lonlat"])}
            for t in targets]
    return pdk.Layer("ScatterplotLayer", data=data, id=layer_id, get_position="position", get_radius=5,
                     radius_units=PIXELS, stroked=True, get_fill_color=rgba(MAGENTA[mode()]),
                     get_line_color=ink("surface"), line_width_min_pixels=1, pickable=True)


def places_layer(places: list[dict], layer_id: str, color: list[int], radius: int = 3, label: str = "") -> pdk.Layer:
    data = [{"tooltip": tip(p.get("name") or label, (p.get("shop") or "").replace("_", " ")), **_ll(p["lonlat"])}
            for p in places]
    return pdk.Layer("ScatterplotLayer", data=data, id=layer_id, get_position="position", get_radius=radius,
                     radius_units=PIXELS, get_fill_color=color, pickable=True)


def path_layer(layer_id: str, path: Path, label: str, color: Optional[list[int]] = None, width: float = 4) -> pdk.Layer:
    return _path_layer(layer_id, [{"path": [list(p) for p in path], "color": color or blue(0.8, 230), "width": width,
                                   "tooltip": tip(label), **_ll(_mid(path))}])


# ---------- deck, view and legend ----------

def view_for(points: Iterable[LonLat], pitch: float = 0, zoom_cap: float = 16, width_px: int = 900,
             height_px: int = 520) -> pdk.ViewState:
    """Centre and zoom so every point fits in a width_px x height_px map with padding (Web Mercator,
    deck.gl's 512 px tiles). pydeck's compute_view assumes a much smaller viewport."""
    pts = [p for p in points]
    if not pts:
        return pdk.ViewState(longitude=-0.128, latitude=51.507, zoom=12.5, pitch=pitch)
    lons, lats = [p[0] for p in pts], [p[1] for p in pts]
    merc = lambda lat: math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    lon_span = max(max(lons) - min(lons), 1e-4)
    y_span = max(merc(max(lats)) - merc(min(lats)), 1e-6)
    zoom = min(math.log2(0.8 * width_px * 360 / (512 * lon_span)),
               math.log2(0.8 * height_px * 2 * math.pi / (512 * y_span)))
    mid_y = (merc(max(lats)) + merc(min(lats))) / 2
    centre_lat = math.degrees(2 * math.atan(math.exp(mid_y)) - math.pi / 2)
    return pdk.ViewState(longitude=(max(lons) + min(lons)) / 2, latitude=centre_lat,
                         zoom=min(zoom_cap, max(11, zoom)), pitch=pitch)


def deck(layers: list[pdk.Layer], view: pdk.ViewState) -> pdk.Deck:
    m = mode()
    style = {"backgroundColor": INK[m]["surface"], "color": INK[m]["primary"], "fontSize": "13px",
             "border": f"1px solid {INK[m]['muted']}", "borderRadius": "6px", "padding": "6px 8px"}
    return pdk.Deck(layers=layers, initial_view_state=view, map_provider="carto", map_style=m,
                    tooltip={"html": "{tooltip}", "style": style})


def show(deck_obj: pdk.Deck, key: str, height: int = 560, selectable: bool = False):
    """Render a deck; returns the selection event when selectable (for pin drops)."""
    if selectable:
        return st.pydeck_chart(deck_obj, height=height, key=key, on_select="rerun", selection_mode="single-object")
    st.pydeck_chart(deck_obj, height=height, key=key)
    return None


def selected_point(event) -> Optional[LonLat]:
    """(lon, lat) of the object clicked in a selectable deck, if any."""
    try:
        objects = event.selection.get("objects", {}) if event else {}
    except AttributeError:
        return None
    for items in objects.values():
        for obj in items or []:
            if "lon" in obj and "lat" in obj:
                return float(obj["lon"]), float(obj["lat"])
    return None


def _swatch(css_background: str, shape: str = "line") -> str:
    size = "width:22px;height:5px;border-radius:3px" if shape == "line" else \
        "width:12px;height:12px;border-radius:50%" if shape == "dot" else "width:14px;height:12px;border-radius:2px"
    return f'<span style="display:inline-block;{size};background:{css_background};margin-right:6px;vertical-align:middle"></span>'


def _css(color: list[int]) -> str:
    return f"rgba({color[0]},{color[1]},{color[2]},{color[3] / 255:.2f})"


def legend(items: list[tuple[str, str, str]]) -> None:
    """items: (label, css colour, shape in line|dot|box). Text stays in the normal ink colour."""
    parts = [f'<span style="margin-right:16px;white-space:nowrap">{_swatch(c, s)}{html.escape(label)}</span>'
             for label, c, s in items]
    st.markdown(f'<div style="font-size:0.85rem;line-height:1.9">{"".join(parts)}</div>', unsafe_allow_html=True)


def ramp_legend(title: str, ramp: str = "blue", low: str = "0%", high: str = "100%") -> None:
    fn = blue if ramp == "blue" else orange
    stops = ", ".join(_css(fn(v, 255)) for v in (0, 0.25, 0.5, 0.75, 1))
    st.markdown(
        f'<div style="font-size:0.85rem;display:flex;align-items:center;gap:8px;margin:2px 0 6px 0">'
        f'<span>{html.escape(title)}</span><span>{html.escape(low)}</span>'
        f'<span style="display:inline-block;width:140px;height:10px;border-radius:5px;background:linear-gradient(90deg,{stops})"></span>'
        f'<span>{html.escape(high)}</span></div>', unsafe_allow_html=True)


def los_legend() -> None:
    legend([(LOS_LABEL[level], _css(los_color(level)), "line") for level in LOS_ORDER])


def legal_legend() -> None:
    legend([(label, color, "box") for color, label in LEGAL.values()])


def ink_css(role: str = "primary") -> str:
    return INK[mode()][role]


def aqua_css() -> str:
    return AQUA[mode()]


def magenta_css() -> str:
    return MAGENTA[mode()]
