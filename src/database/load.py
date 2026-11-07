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
    "events": ("normalised/events.csv", "csv", None),
    "waypoints": ("normalised/waypoints_approved.csv", "csv", ("latitude", "longitude")),
    "route_segments": ("normalised/route_segment_labels.csv", "csv", None),
    "event_context": ("normalised/event_context.csv", "csv", None),
    "cause_targets": ("normalised/cause_targets.csv", "csv", ("lat", "lon")),
}

CSV_OPTIONS = "header = true, sample_size = -1"


def quote(path: Path) -> str:
    """SQL-safe single-quoted POSIX path."""
    return "'" + path.as_posix().replace("'", "''") + "'"


def reader_sql(path: Path, reader: str) -> str:
    """``SELECT`` fragment for csv, geojson, or parquet at ``path``."""
    if reader == "csv":
        return f"SELECT * FROM read_csv({quote(path)}, {CSV_OPTIONS})"  # noqa: S608 — quoted local ingestion paths
    if reader == "geojson":
        return f"SELECT * FROM ST_Read({quote(path)})"  # noqa: S608 — quoted local ingestion paths
    return f"SELECT * FROM read_parquet({quote(path)})"  # noqa: S608 — quoted local ingestion paths


def with_points(sql: str, lat: str, lon: str) -> str:
    """Wrap ``sql`` to add a ``geom`` point column from lat/lon columns."""
    return (
        f"SELECT *, CASE WHEN TRY_CAST({lon} AS DOUBLE) IS NOT NULL AND TRY_CAST({lat} AS DOUBLE) IS NOT NULL "  # noqa: S608 — lat/lon names from TABLES metadata
        f"THEN ST_Point(TRY_CAST({lon} AS DOUBLE), TRY_CAST({lat} AS DOUBLE)) END AS geom FROM ({sql})"
    )


def fix_wkb_geometry(con, table: str) -> None:
    """Promote WKB ``geometry`` columns to DuckDB ``GEOMETRY``."""
    for name, dtype in con.execute(
        f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{table}'"  # noqa: S608 — table from loader plan keys only
    ).fetchall():
        if name == "geometry" and dtype == "BLOB":
            con.execute(
                f"ALTER TABLE {table} ALTER geometry TYPE GEOMETRY USING ST_GeomFromWKB(geometry)"
            )


def segments_sql(route_dir: Path) -> str | None:
    """Join normalised segments geojson with route counts and edge features."""
    norm = route_dir / "normalised"
    geo, counts, feats = (
        norm / "segments.geojson",
        norm / "segment_features.csv",
        norm / "edge_features.csv",
    )
    if not geo.exists():
        return None
    select, joins = ["g.*"], []
    if counts.exists():
        select.append("COALESCE(c.n_published_route_examples, 0) AS n_published_route_examples")
        joins.append(f"LEFT JOIN read_csv({quote(counts)}, {CSV_OPTIONS}) c USING (segment_id)")
    if feats.exists():
        select.append("e.* EXCLUDE (segment_id, length_m)")
        joins.append(f"LEFT JOIN read_csv({quote(feats)}, {CSV_OPTIONS}) e USING (segment_id)")
    return f"SELECT {', '.join(select)} FROM ST_Read({quote(geo)}) g {' '.join(joins)}"  # noqa: S608 — paths quoted via quote()


def plan(route_dir: Path) -> dict[str, tuple[Path | None, str | None]]:
    """Map each DuckDB table to its source path and loader SQL (or skip)."""
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
        (
            f"SELECT zone_id, name, rule_type, legal_basis, notes, geom "  # noqa: S608 — seed legal_zones path only
            f"FROM ST_Read({quote(LEGAL_ZONES_PATH)})"
        )
        if LEGAL_ZONES_PATH.exists()
        else None,
    )
    return out


def table_exists(con, table: str) -> bool:
    """Return whether ``table`` is present in the connected database."""
    return bool(
        con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?", [table]
        ).fetchone()[0]
    )


def derive(con, route_dir: Path) -> dict[str, str]:
    """Post-load steps (e.g. Royal Park polygons into ``legal_zones``)."""
    status = {}
    open_spaces = route_dir / "raw/landmarks/open_spaces.geoparquet"
    if table_exists(con, "legal_zones") and open_spaces.exists():
        con.execute(f"""
            INSERT INTO legal_zones
            SELECT osm_id, name, 'royal_park', 'Royal Parks and Other Open Spaces Regulations 1997', 'from OSM', geometry
            FROM read_parquet({quote(open_spaces)})
            WHERE COALESCE(TRY_CAST(royal_park AS BOOLEAN), false)
              AND ST_GeometryType(geometry) IN ('POLYGON', 'MULTIPOLYGON')""")  # noqa: S608 — parquet path from route_dir
        n = con.execute(
            "SELECT COUNT(*) FROM legal_zones WHERE rule_type = 'royal_park'"
        ).fetchone()[0]
        status["legal_zones.royal_parks"] = f"{n:,} Royal Park polygons added"
    return status


def load(con, route_dir: Path) -> dict[str, str]:
    """Create or replace all tables from ``plan(route_dir)``."""
    init_schema(con)
    status = {}
    for table, (path, sql) in plan(route_dir).items():
        if sql is None:
            status[table] = f"skipped (missing {path})"
            continue
        try:
            con.execute(f"CREATE OR REPLACE TABLE {table} AS {sql}")
            fix_wkb_geometry(con, table)
            rows = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608 — table from plan keys only
            con.execute(
                "INSERT OR REPLACE INTO load_log VALUES (?, ?, ?, ?)",
                [table, str(path), rows, dt.datetime.now()],
            )
            status[table] = f"{rows:,} rows"
        except duckdb.Error as exc:
            status[table] = f"FAILED: {str(exc).splitlines()[0][:150]}"
    try:
        status.update(derive(con, route_dir))
    except duckdb.Error as exc:
        status["derived"] = f"FAILED: {str(exc).splitlines()[0][:150]}"
    return status


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for ``python -m src.database.load``."""
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
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
