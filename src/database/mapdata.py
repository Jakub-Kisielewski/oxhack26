"""Read-only base data for the model layer and backtest UI.

Every function returns database types or plain dicts/lists with coordinates as
(lon, lat). All runtime database access goes through ``cursor()``, which shares one
read-only connection per process (DuckDB refuses a second connection to the same
file with a different configuration). PROTEST_DB (see src/database/db.py) selects the file.
Results of the cached functions are shared: treat them as read-only.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, time
from functools import lru_cache

import duckdb

from src.database.db import DB_PATH, get_connection
from src.database.types import CauseOption, HistoricalEvent, LonLat, Polyline


@lru_cache(maxsize=1)
def connection() -> duckdb.DuckDBPyConnection:
    """Shared read-only DuckDB connection for this process."""
    return get_connection(read_only=True, path=DB_PATH)


def cursor() -> duckdb.DuckDBPyConnection:
    """A cursor on the shared connection; use one per call/thread."""
    return connection().cursor()


def _coords(geojson: str) -> list:
    return json.loads(geojson)["coordinates"]


def _line(geojson: str) -> Polyline:
    return [(float(x), float(y)) for x, y, *_ in _coords(geojson)]


def _rings(geojson: str) -> list[Polyline]:
    """Outer ring of each polygon in a Polygon/MultiPolygon."""
    g = json.loads(geojson)
    polys = (
        [g["coordinates"]]
        if g["type"] == "Polygon"
        else g["coordinates"]
        if g["type"] == "MultiPolygon"
        else []
    )
    return [[(float(x), float(y)) for x, y, *_ in poly[0]] for poly in polys]


def distance_m(a: LonLat, b: LonLat) -> float:
    """Great-circle distance in metres on WGS84 (Haversine).

    Both arguments are ``(longitude, latitude)`` in degrees. Used by the route
    model for progress and target-pull features.
    """
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371000 * math.asin(math.sqrt(h))


def _table_exists(name: str) -> bool:
    return bool(
        cursor()
        .execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?", [name])
        .fetchone()[0]
    )


def _has_column(table: str, column: str) -> bool:
    return bool(
        cursor()
        .execute(
            "SELECT COUNT(*) FROM information_schema.columns WHERE table_name = ? AND column_name = ?",
            [table, column],
        )
        .fetchone()[0]
    )


def _format_date(value: date | datetime | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def _format_time(value: time | datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, time):
        return value.strftime("%H:%M")
    if isinstance(value, datetime):
        return value.time().strftime("%H:%M")
    text = str(value).strip()
    return text[:5] if len(text) >= 5 else text or None


# ---------- reference data ----------


@lru_cache(maxsize=1)
def list_causes() -> tuple[CauseOption, ...]:
    """Distinct protest causes with event counts for UI selectors."""
    counts = dict(
        cursor()
        .execute(
            "SELECT cause, COUNT(*) FROM event_context WHERE cause IS NOT NULL AND cause <> '' GROUP BY cause"
        )
        .fetchall()
    )
    if _table_exists("cause_targets"):
        for (cause,) in (
            cursor()
            .execute("SELECT DISTINCT cause FROM cause_targets WHERE cause <> 'any'")
            .fetchall()
        ):
            counts.setdefault(cause, 0)
    return tuple(
        sorted(
            (
                CauseOption(key=k, label=k.replace("_", " ").title(), n_events=int(n))
                for k, n in counts.items()
            ),
            key=lambda c: (-c.n_events, c.key),
        )
    )


@lru_cache(maxsize=2)
def historical_events(protests_only: bool = True) -> tuple[HistoricalEvent, ...]:
    """Events with snapped routes and waypoints from DuckDB."""
    cur = cursor()
    events = cur.execute("""
        SELECT e.event_id, e.event_name, e.event_date, e.start_time,
               c.cause, e.organiser, e.turnout, e.event_category
        FROM events e LEFT JOIN event_context c USING (event_id)
        ORDER BY e.event_date, e.event_id""").fetchall()
    routes: dict[str, list[tuple[str, Polyline]]] = {}
    for event_id, segment_id, geo in cur.execute("""
            SELECT r.event_id, r.segment_id, ST_AsGeoJSON(s.geom) FROM route_segments r
            JOIN segments s USING (segment_id) ORDER BY r.event_id, r.sequence_index""").fetchall():
        routes.setdefault(event_id, []).append((segment_id, _line(geo)))
    waypoints: dict[str, list[tuple[str, LonLat]]] = {}
    for event_id, name, lon, lat in cur.execute("""
            SELECT event_id, waypoint_name, longitude, latitude FROM waypoints
            WHERE latitude IS NOT NULL ORDER BY event_id, sequence_index""").fetchall():
        waypoints.setdefault(event_id, []).append((name, (float(lon), float(lat))))
    out: list[HistoricalEvent] = []
    for event_id, name, event_date, start, cause, organiser, turnout, category in events:
        segs = routes.get(event_id, [])
        if len(segs) < 2 or (protests_only and category != "protest"):
            continue
        path: Polyline = []
        for _, line in segs:
            path.extend(line[1:] if path and line and path[-1] == line[0] else line)
        turnout_val = int(turnout) if turnout is not None else None
        out.append(
            HistoricalEvent(
                event_id=event_id,
                name=name,
                date=_format_date(event_date),
                start_time=_format_time(start),
                cause=cause or None,
                organiser=organiser or None,
                turnout=turnout_val,
                route_segment_ids=[s for s, _ in segs],
                path=path,
                waypoints=waypoints.get(event_id, []),
            )
        )
    return tuple(out)


@lru_cache(maxsize=1)
def boundary() -> tuple[Polyline, ...]:
    """TfL zones 1-2 boundary polygon rings."""
    rings: list[Polyline] = []
    for (geo,) in cursor().execute("SELECT ST_AsGeoJSON(geom) FROM boundary").fetchall():
        rings.extend(_rings(geo))
    return tuple(rings)


@lru_cache(maxsize=1)
def legal_zones() -> tuple[dict, ...]:
    """Legal restriction polygons with rule metadata."""
    if not _table_exists("legal_zones"):
        return ()
    out: list[dict] = []
    for zone_id, name, rule, geo in (
        cursor()
        .execute("SELECT zone_id, name, rule_type, ST_AsGeoJSON(geom) FROM legal_zones")
        .fetchall()
    ):
        for ring in _rings(geo):
            out.append({"zone_id": zone_id, "name": name, "rule_type": rule, "polygon": ring})
    return tuple(out)


def targets(categories: list[str] | None = None) -> list[dict]:
    """Embassy and landmark targets, optionally filtered by ``categories``."""
    country_sel = "country" if _has_column("targets", "country") else "NULL"
    sql = f"SELECT name, category, {country_sel}, lon, lat FROM targets WHERE lat IS NOT NULL"  # noqa: S608 — country_sel is country|NULL literal
    params: list = []
    if categories:
        sql += " AND category IN (SELECT UNNEST(?))"
        params.append(list(categories))
    return [
        {"name": n, "category": c, "country": k, "lonlat": (float(lon), float(lat))}
        for n, c, k, lon, lat in cursor().execute(sql, params).fetchall()
    ]


def cause_targets(cause: str | None) -> list[dict]:
    """Weighted rally targets for a cause (plus ``any`` defaults)."""
    rows = (
        cursor()
        .execute(
            """SELECT cause, target_name, kind, lon, lat, weight FROM cause_targets
                               WHERE cause = 'any' OR cause = ? ORDER BY weight DESC""",
            [cause or "any"],
        )
        .fetchall()
    )
    return [
        {
            "cause": c,
            "target_name": n,
            "kind": k,
            "lonlat": (float(lon), float(lat)),
            "weight": float(w),
        }
        for c, n, k, lon, lat, w in rows
    ]


@lru_cache(maxsize=1)
def assembly_points() -> tuple[dict, ...]:
    """Frequent march start waypoint names averaged in lon/lat."""
    rows = (
        cursor()
        .execute("""
        WITH firsts AS (
            SELECT w.waypoint_name, w.longitude, w.latitude FROM waypoints w
            JOIN (SELECT event_id, MIN(sequence_index) AS s FROM waypoints GROUP BY event_id) f
              ON w.event_id = f.event_id AND w.sequence_index = f.s
        )
        SELECT waypoint_name, AVG(longitude), AVG(latitude), COUNT(*) FROM firsts
        GROUP BY waypoint_name ORDER BY COUNT(*) DESC, waypoint_name""")
        .fetchall()
    )
    return tuple(
        {"name": n, "lonlat": (float(lon), float(lat)), "n_events": int(k)}
        for n, lon, lat, k in rows
    )


def in_boundary(lonlat: LonLat) -> bool:
    """True when ``lonlat`` lies inside the zones 1-2 boundary."""
    return bool(
        cursor()
        .execute("SELECT bool_or(ST_Contains(geom, ST_Point(?, ?))) FROM boundary", list(lonlat))
        .fetchone()[0]
    )
