"""Load the ingestion outputs into data/protest.duckdb: `python -m src.database.load`

Every table is rebuilt from its source file on each run (CREATE OR REPLACE), so
the database always matches the latest ingestion. Missing files are skipped and
a failing table doesn't stop the others. Point tables get a `geom` column
(EPSG:4326 lon/lat) for spatial queries; map layers keep their OSM geometry.

The Streamlit app holds the database open; close it before loading.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import duckdb

from src.database.db import DB_PATH, get_connection, init_schema

ROOT = Path(__file__).resolve().parents[2]
LEGAL_ZONES = ROOT / "src" / "ingestion" / "route_research" / "seed" / "legal_zones.geojson"
ROUTE_DIR = ROOT / "data" / "route_research"
RUNS_DIR = ROOT / "data" / "runs"

# table -> (source path relative to the route workspace, reader, (lat, lon) columns for geom)
TABLES = {
    # Map
    "boundary":        ("raw/boundary/zones_1_2.geojson", "geojson", None),
    "main_edges":      ("raw/osm/london_main_edges.geojson", "geojson", None),
    "targets":         ("raw/landmarks/targets.geoparquet", "parquet", None),
    "open_spaces":     ("raw/landmarks/open_spaces.geoparquet", "parquet", None),
    "shops":           ("raw/landmarks/shops.geoparquet", "parquet", None),
    "warehouses":      ("raw/landmarks/warehouses.geoparquet", "parquet", None),
    "missions":        ("raw/landmarks/missions.geoparquet", "parquet", None),
    "grid_cells":      ("normalised/grid_cells.geoparquet", "parquet", None),
    "grid_adjacency":  ("normalised/grid_adjacency.csv", "csv", None),
    "segment_cells":   ("normalised/segment_cells.csv", "csv", None),
    # Events and training routes
    "events":          ("normalised/events.csv", "csv", None),
    "waypoints":       ("normalised/waypoints_approved.csv", "csv", ("latitude", "longitude")),
    "route_segments":  ("normalised/route_segment_labels.csv", "csv", None),
    "event_context":   ("normalised/event_context.csv", "csv", None),
    "cause_targets":   ("normalised/cause_targets.csv", "csv", ("lat", "lon")),
    # Context
    "crimes":          ("normalised/police_monthly_context.csv", "csv", ("latitude", "longitude")),
    "tfl_disruptions": ("normalised/tfl_road_disruption_snapshots.csv", "csv", ("latitude", "longitude")),
    "acled_events":    ("normalised/acled_event_points.csv", "csv", ("latitude", "longitude")),
    "weather_hourly":  ("raw/weather/hourly.csv", "csv", None),
    "pageviews_daily": ("raw/pageviews/daily.csv", "csv", None),
}


# Infer column types from the whole file, not the first ~20k rows: a value that
# only appears late (e.g. text in a mostly numeric column) otherwise fails the load.
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
    return (f"SELECT *, CASE WHEN TRY_CAST({lon} AS DOUBLE) IS NOT NULL AND TRY_CAST({lat} AS DOUBLE) IS NOT NULL "
            f"THEN ST_Point(TRY_CAST({lon} AS DOUBLE), TRY_CAST({lat} AS DOUBLE)) END AS geom FROM ({sql})")


def fix_wkb_geometry(con, table: str) -> None:
    """GeoParquet geometry arrives as GEOMETRY when spatial reads it, but older files may be raw WKB."""
    for name, dtype in con.execute(f"SELECT column_name, data_type FROM information_schema.columns "
                                   f"WHERE table_name = '{table}'").fetchall():
        if name == "geometry" and dtype == "BLOB":
            con.execute(f"ALTER TABLE {table} ALTER geometry TYPE GEOMETRY USING ST_GeomFromWKB(geometry)")


def latest_crawler_parquet(runs_dir: Path) -> Path | None:
    """Newest crawler run with a non-empty merged parquet (empty runs write a 0-byte file)."""
    files = sorted(runs_dir.glob("*/_all/protests.parquet"), reverse=True)
    return next((f for f in files if f.stat().st_size > 0), None)


def segments_sql(route_dir: Path) -> str | None:
    """Street segments with their historical route counts and edge_features columns."""
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


def plan(route_dir: Path, runs_dir: Path) -> dict[str, tuple[Path | None, str | None]]:
    """table -> (source file, SELECT) or (path, None) when the source is missing."""
    out = {}
    for table, (rel, reader, point_cols) in TABLES.items():
        path = route_dir / rel
        sql = reader_sql(path, reader) if path.exists() else None
        if sql and point_cols:
            sql = with_points(sql, *point_cols)
        out[table] = (path, sql)
    out["segments"] = (route_dir / "normalised/segments.geojson", segments_sql(route_dir))
    out["legal_zones"] = (LEGAL_ZONES, f"SELECT zone_id, name, rule_type, legal_basis, notes, geom "
                                       f"FROM ST_Read({quote(LEGAL_ZONES)})" if LEGAL_ZONES.exists() else None)
    crawler = latest_crawler_parquet(runs_dir)
    out["protest_signals"] = (crawler or runs_dir / "<run>/_all/protests.parquet",
                              with_points(reader_sql(crawler, "parquet"), "latitude", "longitude") if crawler else None)
    return out


def table_exists(con, table: str) -> bool:
    return bool(con.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?", [table]).fetchone()[0])


def column_exists(con, table: str, column: str) -> bool:
    return bool(con.execute("SELECT COUNT(*) FROM information_schema.columns WHERE table_name = ? AND column_name = ?",
                            [table, column]).fetchone()[0])


def derive(con) -> dict[str, str]:
    """Columns and rows that combine several loaded tables."""
    status = {}
    if table_exists(con, "targets") and table_exists(con, "missions"):
        # OSM embassies get the country of the nearest Wikidata mission within 100 m,
        # else OSM's own ISO country code (`country` tag).
        con.execute("ALTER TABLE targets ADD COLUMN IF NOT EXISTS mission_country VARCHAR")
        osm_code = "t.country" if column_exists(con, "targets", "country") else "NULL"
        con.execute(f"""
            UPDATE targets t SET mission_country = COALESCE((
                SELECT arg_min(m.mission_country, meters(m.geometry, t.geometry)) FROM missions m
                WHERE m.mission_country IS NOT NULL AND meters(m.geometry, t.geometry) < 100), {osm_code})
            WHERE t.category = 'diplomatic'""")
        n, total = con.execute("SELECT COUNT(mission_country), COUNT(*) FROM targets WHERE category = 'diplomatic'").fetchone()
        status["targets.mission_country"] = f"{n:,} of {total:,} embassies have a country"
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


def load(con, route_dir: Path, runs_dir: Path) -> dict[str, str]:
    init_schema(con)
    status = {}
    for table, (path, sql) in plan(route_dir, runs_dir).items():
        if sql is None:
            status[table] = f"skipped (missing {path})"
            continue
        try:
            con.execute(f"CREATE OR REPLACE TABLE {table} AS {sql}")
            fix_wkb_geometry(con, table)
            rows = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            con.execute("INSERT OR REPLACE INTO load_log VALUES (?, ?, ?, ?)",
                        [table, str(path), rows, dt.datetime.now()])
            status[table] = f"{rows:,} rows"
        except duckdb.Error as exc:
            status[table] = f"FAILED: {str(exc).splitlines()[0][:150]}"
    try:
        status.update(derive(con))
    except duckdb.Error as exc:
        status["derived columns"] = f"FAILED: {str(exc).splitlines()[0][:150]}"
    return status


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", type=Path, default=DB_PATH)
    p.add_argument("--route-dir", type=Path, default=ROUTE_DIR)
    p.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    a = p.parse_args(argv)
    try:
        con = get_connection(path=a.db)
    except duckdb.IOException as exc:
        if "lock" in str(exc).lower():
            print(f"{a.db} is open in another process (is the Streamlit app running?). Close it and retry.",
                  file=sys.stderr)
            return 1
        if "newer version of DuckDB" not in str(exc):
            raise
        # Every table is rebuilt from the ingestion files, so a file from another
        # DuckDB version (e.g. 2.0) can be set aside and recreated.
        old = a.db.with_suffix(a.db.suffix + ".old")
        a.db.replace(old)
        print(f"{a.db.name} was written by a newer DuckDB; moved it to {old.name} and rebuilding")
        con = get_connection(path=a.db)
    try:
        status = load(con, a.route_dir, a.runs_dir)
    finally:
        con.close()
    width = max(map(len, status))
    for table, s in status.items():
        print(f"{table:<{width}}  {s}")
    print(f"Database: {a.db}")
    return 1 if any(s.startswith("FAILED") for s in status.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
