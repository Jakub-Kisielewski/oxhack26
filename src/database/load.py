"""Load ingestion outputs into DuckDB: `python -m src.database.load`."""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import duckdb

from src.config import LEGAL_ZONES_PATH, ROUTE_RESEARCH_DIR
from src.database.db import DB_PATH, get_connection, init_schema

TABLES = {
    "boundary": ("raw/boundary/zones_1_2.geojson", "geojson", None),
    "targets": ("raw/landmarks/targets.geoparquet", "parquet", None),
    "open_spaces": ("raw/landmarks/open_spaces.geoparquet", "parquet", None),
    "events": ("normalised/events.csv", "csv", None),
    "waypoints": ("normalised/waypoints_approved.csv", "csv", ("latitude", "longitude")),
    "route_segments": ("normalised/route_segment_labels.csv", "csv", None),
    "event_context": ("normalised/event_context.csv", "csv", None),
    "cause_targets": ("normalised/cause_targets.csv", "csv", ("lat", "lon")),
    "weather_hourly": ("raw/weather/hourly.csv", "csv", None),
    "pageviews_daily": ("raw/pageviews/daily.csv", "csv", None),
}

CSV_OPTIONS = "header = true, sample_size = -1"


def quote(path: Path) -> str:
    return "'" + path.as_posix().replace("'", "''") + "'"


def reader_sql(path: Path, reader: str) -> str:
    if reader == "csv":
        return f"SELECT * FROM read_csv({quote(path)}, {CSV_OPTIONS})"
    if reader == "geojson":
        return f"SELECT * FROM ST_Read({quote(path)})"
    return f"SELECT * FROM read_parquet({quote(path)})"


def with_points(sql: str, lat: str, lon: str) -> str:
    return (
        f"SELECT *, CASE WHEN TRY_CAST({lon} AS DOUBLE) IS NOT NULL AND TRY_CAST({lat} AS DOUBLE) IS NOT NULL "
        f"THEN ST_Point(TRY_CAST({lon} AS DOUBLE), TRY_CAST({lat} AS DOUBLE)) END AS geom FROM ({sql})"
    )


def fix_wkb_geometry(con, table: str) -> None:
    for name, dtype in con.execute(
        f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{table}'"
    ).fetchall():
        if name == "geometry" and dtype == "BLOB":
            con.execute(f"ALTER TABLE {table} ALTER geometry TYPE GEOMETRY USING ST_GeomFromWKB(geometry)")


def segments_sql(route_dir: Path) -> str | None:
    norm = route_dir / "normalised"
    geo, counts, feats = norm / "segments.geojson", norm / "segment_features.csv", norm / "edge_features.csv"
    if not geo.exists():
        return None
    select, joins = ["g.*"], []
    if counts.exists():
        select.append("COALESCE(c.n_published_route_examples, 0) AS n_published_route_examples")
        joins.append(f"LEFT JOIN read_csv({quote(counts)}, {CSV_OPTIONS}) c USING (segment_id)")
    if feats.exists():
        select.append("e.* EXCLUDE (segment_id, length_m)")
        joins.append(f"LEFT JOIN read_csv({quote(feats)}, {CSV_OPTIONS}) e USING (segment_id)")
    return f"SELECT {', '.join(select)} FROM ST_Read({quote(geo)}) g {' '.join(joins)}"


def plan(route_dir: Path) -> dict[str, tuple[Path | None, str | None]]:
    out = {}
    for table, (rel, reader, point_cols) in TABLES.items():
        path = route_dir / rel
        sql = reader_sql(path, reader) if path.exists() else None
        if sql and point_cols:
            sql = with_points(sql, *point_cols)
        out[table] = (path, sql)
    out["segments"] = (route_dir / "normalised/segments.geojson", segments_sql(route_dir))
    out["legal_zones"] = (
        LEGAL_ZONES_PATH,
        f"SELECT zone_id, name, rule_type, legal_basis, notes, geom "
        f"FROM ST_Read({quote(LEGAL_ZONES_PATH)})"
        if LEGAL_ZONES_PATH.exists()
        else None,
    )
    return out


def table_exists(con, table: str) -> bool:
    return bool(
        con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?", [table]
        ).fetchone()[0]
    )


def derive(con) -> dict[str, str]:
    status = {}
    if table_exists(con, "legal_zones") and table_exists(con, "open_spaces"):
        con.execute("""
            INSERT INTO legal_zones
            SELECT osm_id, name, 'royal_park', 'Royal Parks and Other Open Spaces Regulations 1997', 'from OSM', geometry
            FROM open_spaces
            WHERE COALESCE(TRY_CAST(royal_park AS BOOLEAN), false)
              AND ST_GeometryType(geometry) IN ('POLYGON', 'MULTIPOLYGON')""")
        n = con.execute("SELECT COUNT(*) FROM legal_zones WHERE rule_type = 'royal_park'").fetchone()[0]
        status["legal_zones.royal_parks"] = f"{n:,} Royal Park polygons added"
    return status


def load(con, route_dir: Path) -> dict[str, str]:
    init_schema(con)
    status = {}
    for table, (path, sql) in plan(route_dir).items():
        if sql is None:
            status[table] = f"skipped (missing {path})"
            continue
        try:
            con.execute(f"CREATE OR REPLACE TABLE {table} AS {sql}")
            fix_wkb_geometry(con, table)
            rows = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            con.execute(
                "INSERT OR REPLACE INTO load_log VALUES (?, ?, ?, ?)",
                [table, str(path), rows, dt.datetime.now()],
            )
            status[table] = f"{rows:,} rows"
        except duckdb.Error as exc:
            status[table] = f"FAILED: {str(exc).splitlines()[0][:150]}"
    try:
        status.update(derive(con))
    except duckdb.Error as exc:
        status["derived"] = f"FAILED: {str(exc).splitlines()[0][:150]}"
    return status


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", type=Path, default=DB_PATH)
    p.add_argument("--route-dir", type=Path, default=ROUTE_RESEARCH_DIR)
    a = p.parse_args(argv)
    try:
        con = get_connection(path=a.db)
    except duckdb.IOException as exc:
        if "lock" in str(exc).lower():
            print(f"{a.db} is open elsewhere. Close it and retry.", file=sys.stderr)
            return 1
        if "newer version of DuckDB" not in str(exc):
            raise
        old = a.db.with_suffix(a.db.suffix + ".old")
        a.db.replace(old)
        print(f"Moved {a.db.name} to {old.name} and rebuilding")
        con = get_connection(path=a.db)
    try:
        status = load(con, a.route_dir)
    finally:
        con.close()
    width = max(map(len, status))
    for table, s in status.items():
        print(f"{table:<{width}}  {s}")
    print(f"Database: {a.db}")
    return 1 if any(s.startswith("FAILED") for s in status.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
