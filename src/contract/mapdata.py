"""Read-only base data for both the model layer and the visual layer.

Every function returns contract types or plain dicts/lists with coordinates as
(lon, lat). All runtime database access goes through `cursor()`, which shares one
read-only connection per process (DuckDB refuses a second connection to the same
file with a different configuration). PROTEST_DB (see src/database/db.py) selects the file.
Results of the cached functions are shared: treat them as read-only.
"""
from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from typing import Optional

import duckdb

from src.contract.types import CauseOption, HistoricalEvent, LonLat, Path
from src.database.db import DB_PATH, get_connection


@lru_cache(maxsize=1)
def connection() -> duckdb.DuckDBPyConnection:
    return get_connection(read_only=True, path=DB_PATH)


def cursor() -> duckdb.DuckDBPyConnection:
    """A cursor on the shared connection; use one per call/thread."""
    return connection().cursor()


# ---------- geometry helpers ----------

def _coords(geojson: str) -> list:
    return json.loads(geojson)["coordinates"]


def _line(geojson: str) -> Path:
    return [(float(x), float(y)) for x, y, *_ in _coords(geojson)]


def _rings(geojson: str) -> list[Path]:
    """Outer ring of each polygon in a Polygon/MultiPolygon."""
    g = json.loads(geojson)
    polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"] if g["type"] == "MultiPolygon" else []
    return [[(float(x), float(y)) for x, y, *_ in poly[0]] for poly in polys]


def distance_m(a: LonLat, b: LonLat) -> float:
    """Haversine distance in metres between two (lon, lat) points."""
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def _table_exists(name: str) -> bool:
    return bool(cursor().execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?", [name]).fetchone()[0])


def _first_int(text) -> Optional[int]:
    m = re.search(r"\d[\d,]*", str(text or ""))
    return int(m.group().replace(",", "")) if m else None


def _hhmm(text) -> Optional[str]:
    m = re.match(r"^\s*(\d{1,2}):(\d{2})", str(text or ""))
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


# ---------- reference data ----------

@lru_cache(maxsize=1)
def list_causes() -> list[CauseOption]:
    counts = dict(cursor().execute(
        "SELECT cause, COUNT(*) FROM event_context WHERE cause IS NOT NULL AND cause <> '' GROUP BY cause").fetchall())
    if _table_exists("cause_targets"):
        for (cause,) in cursor().execute("SELECT DISTINCT cause FROM cause_targets WHERE cause <> 'any'").fetchall():
            counts.setdefault(cause, 0)
    return sorted((CauseOption(key=k, label=k.replace("_", " ").title(), n_events=int(n)) for k, n in counts.items()),
                  key=lambda c: (-c.n_events, c.key))


@lru_cache(maxsize=2)
def historical_events(protests_only: bool = True) -> list[HistoricalEvent]:
    cur = cursor()
    events = cur.execute("""
        SELECT e.event_id, e.event_name, CAST(e.event_date AS VARCHAR), CAST(e.start_time AS VARCHAR),
               c.cause, e.organiser, CAST(e.turnout AS VARCHAR), e.event_category
        FROM events e LEFT JOIN event_context c USING (event_id) ORDER BY e.event_date, e.event_id""").fetchall()
    routes: dict[str, list[tuple[str, Path]]] = {}
    for event_id, segment_id, geo in cur.execute("""
            SELECT r.event_id, r.segment_id, ST_AsGeoJSON(s.geom) FROM route_segments r
            JOIN segments s USING (segment_id) ORDER BY r.event_id, r.sequence_index""").fetchall():
        routes.setdefault(event_id, []).append((segment_id, _line(geo)))
    waypoints: dict[str, list[tuple[str, LonLat]]] = {}
    for event_id, name, lon, lat in cur.execute("""
            SELECT event_id, waypoint_name, longitude, latitude FROM waypoints
            WHERE latitude IS NOT NULL ORDER BY event_id, sequence_index""").fetchall():
        waypoints.setdefault(event_id, []).append((name, (float(lon), float(lat))))
    out = []
    for event_id, name, date, start, cause, organiser, turnout, category in events:
        segs = routes.get(event_id, [])
        if len(segs) < 2 or (protests_only and category != "protest"):
            continue
        path: Path = []
        for _, line in segs:
            path.extend(line[1:] if path and line and path[-1] == line[0] else line)
        out.append(HistoricalEvent(event_id=event_id, name=name, date=str(date)[:10], start_time=_hhmm(start),
                                   cause=cause or None, organiser=organiser or None, turnout=_first_int(turnout),
                                   route_segment_ids=[s for s, _ in segs], path=path,
                                   waypoints=waypoints.get(event_id, [])))
    return out


def segment_paths(ids: list[str]) -> dict[str, Path]:
    if not ids:
        return {}
    rows = cursor().execute("SELECT segment_id, ST_AsGeoJSON(geom) FROM segments WHERE segment_id IN (SELECT UNNEST(?))",
                            [list(ids)]).fetchall()
    return {sid: _line(geo) for sid, geo in rows}


def cells_for_segments(ids: list[str]) -> dict[str, int]:
    """Midpoint hexagon of each segment."""
    if not ids or not _table_exists("segment_cells"):
        return {}
    return dict(cursor().execute("""SELECT segment_id, cell_id FROM segment_cells
                                    WHERE is_midpoint_cell AND segment_id IN (SELECT UNNEST(?))""", [list(ids)]).fetchall())


@lru_cache(maxsize=1)
def boundary() -> list[Path]:
    rings = []
    for (geo,) in cursor().execute("SELECT ST_AsGeoJSON(geom) FROM boundary").fetchall():
        rings.extend(_rings(geo))
    return rings


@lru_cache(maxsize=1)
def legal_zones() -> list[dict]:
    if not _table_exists("legal_zones"):
        return []
    out = []
    for zone_id, name, rule, geo in cursor().execute(
            "SELECT zone_id, name, rule_type, ST_AsGeoJSON(geom) FROM legal_zones").fetchall():
        for ring in _rings(geo):
            out.append({"zone_id": zone_id, "name": name, "rule_type": rule, "polygon": ring})
    return out


def targets(categories: Optional[list[str]] = None) -> list[dict]:
    sql = "SELECT name, category, " + ("country" if _has_column("targets", "country") else "NULL") + \
          ", lon, lat FROM targets WHERE lat IS NOT NULL"
    params = []
    if categories:
        sql += " AND category IN (SELECT UNNEST(?))"
        params.append(list(categories))
    return [{"name": n, "category": c, "country": k, "lonlat": (float(lon), float(lat))}
            for n, c, k, lon, lat in cursor().execute(sql, params).fetchall()]


def cause_targets(cause: Optional[str]) -> list[dict]:
    rows = cursor().execute("""SELECT cause, target_name, kind, lon, lat, weight FROM cause_targets
                               WHERE cause = 'any' OR cause = ? ORDER BY weight DESC""", [cause or "any"]).fetchall()
    return [{"cause": c, "target_name": n, "kind": k, "lonlat": (float(lon), float(lat)), "weight": float(w)}
            for c, n, k, lon, lat, w in rows]


def _has_column(table: str, column: str) -> bool:
    return bool(cursor().execute("SELECT COUNT(*) FROM information_schema.columns WHERE table_name = ? AND column_name = ?",
                                 [table, column]).fetchone()[0])


def _bbox_params(lonlat: LonLat, radius_m: float) -> list[float]:
    dlat = radius_m / 111_320
    dlon = radius_m / (111_320 * math.cos(math.radians(lonlat[1])))
    return [lonlat[1] - dlat, lonlat[1] + dlat, lonlat[0] - dlon, lonlat[0] + dlon]


def shops_near(lonlat: LonLat, radius_m: float = 300, limit: int = 50) -> list[dict]:
    rows = cursor().execute("""
        SELECT osm_id, name, shop, lon, lat, meters(geometry, ST_Point(?, ?)) AS d FROM shops
        WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? AND d <= ? ORDER BY d LIMIT ?""",
                            [*lonlat, *_bbox_params(lonlat, radius_m), radius_m, limit]).fetchall()
    return [{"osm_id": o, "name": n, "shop": s, "lonlat": (float(lon), float(lat)), "distance_m": round(float(d), 1)}
            for o, n, s, lon, lat, d in rows]


def search_shops(text: str, limit: int = 20) -> list[dict]:
    rows = cursor().execute("""SELECT osm_id, name, shop, lon, lat FROM shops WHERE name ILIKE ?
                               ORDER BY length(name), name LIMIT ?""", [f"%{text.strip()}%", limit]).fetchall()
    return [{"osm_id": o, "name": n, "shop": s, "lonlat": (float(lon), float(lat))} for o, n, s, lon, lat in rows]


@lru_cache(maxsize=1)
def warehouses() -> list[dict]:
    fp = "footprint_m2" if _has_column("warehouses", "footprint_m2") else "NULL"
    rows = cursor().execute(f"SELECT osm_id, name, lon, lat, {fp} FROM warehouses WHERE lat IS NOT NULL").fetchall()
    return [{"osm_id": o, "name": n, "lonlat": (float(lon), float(lat)), "footprint_m2": float(f) if f is not None else None}
            for o, n, lon, lat, f in rows]


def cells(ids: Optional[list[int]] = None) -> list[dict]:
    if ids is None:
        return _all_cells()
    wanted = set(ids)
    return [c for c in _all_cells() if c["cell_id"] in wanted]


@lru_cache(maxsize=1)
def _all_cells() -> list[dict]:
    rows = cursor().execute("SELECT cell_id, lon, lat, ST_AsGeoJSON(geometry) FROM grid_cells ORDER BY cell_id").fetchall()
    return [{"cell_id": int(i), "lonlat": (float(lon), float(lat)), "polygon": _rings(geo)[0]} for i, lon, lat, geo in rows]


def cell_at(lonlat: LonLat) -> Optional[int]:
    row = cursor().execute("SELECT cell_id FROM grid_cells WHERE ST_Contains(geometry, ST_Point(?, ?)) LIMIT 1",
                           list(lonlat)).fetchone()
    return int(row[0]) if row else None


@lru_cache(maxsize=1)
def assembly_points() -> list[dict]:
    rows = cursor().execute("""
        WITH firsts AS (
            SELECT w.waypoint_name, w.longitude, w.latitude FROM waypoints w
            JOIN (SELECT event_id, MIN(sequence_index) AS s FROM waypoints GROUP BY event_id) f
              ON w.event_id = f.event_id AND w.sequence_index = f.s)
        SELECT waypoint_name, AVG(longitude), AVG(latitude), COUNT(*) FROM firsts
        GROUP BY waypoint_name ORDER BY COUNT(*) DESC, waypoint_name""").fetchall()
    return [{"name": n, "lonlat": (float(lon), float(lat)), "n_events": int(k)} for n, lon, lat, k in rows]


def in_boundary(lonlat: LonLat) -> bool:
    return bool(cursor().execute("SELECT bool_or(ST_Contains(geom, ST_Point(?, ?))) FROM boundary",
                                 list(lonlat)).fetchone()[0])
