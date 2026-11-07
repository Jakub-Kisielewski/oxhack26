"""DuckDB connection setup and declared schema for model-input tables."""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from src.config import DB_PATH

logger = logging.getLogger(__name__)


def _install_spatial(con: duckdb.DuckDBPyConnection) -> None:
    """Install DuckDB's spatial extension, preferring the pip-bundled build.

    ``duckdb-extension-spatial`` ships the binary inside the wheel, so a normal
    ``pip install`` is enough on every platform with a wheel. Intel Macs have no
    wheel, so we fall back to ``INSTALL spatial``, which downloads from
    extensions.duckdb.org and needs network access. Extensions are pinned to
    the exact DuckDB version, which is why ``duckdb==1.5.5`` is an equality pin.
    """
    try:
        import duckdb_extension_spatial

        bundled = sorted(
            Path(duckdb_extension_spatial.__path__[0]).glob("extensions/*/spatial.duckdb_extension")
        )
    except ImportError:
        bundled = []
    if bundled:
        con.execute(f"INSTALL '{bundled[-1].as_posix()}'")
    else:
        con.execute("INSTALL spatial")


def get_connection(read_only: bool = False, path: Path = DB_PATH) -> duckdb.DuckDBPyConnection:
    """Open ``path``, loading the spatial extension on first use."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path), read_only=read_only)
    try:
        con.execute("LOAD spatial")
    except duckdb.CatalogException:
        _install_spatial(con)
        con.execute("LOAD spatial")
    except duckdb.IOException as exc:
        msg = str(exc).lower()
        if "spatial" in msg and ("not found" in msg or "install" in msg):
            _install_spatial(con)
            con.execute("LOAD spatial")
        else:
            raise
    return con


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create bookkeeping and declared schemas for CSV tables the model reads."""
    con.execute("""
        CREATE TABLE IF NOT EXISTS load_log (
            table_name   VARCHAR PRIMARY KEY,
            source_file  VARCHAR,
            rows         BIGINT,
            loaded_at    TIMESTAMP
        );
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS events (
            event_id                    VARCHAR PRIMARY KEY,
            event_date                  DATE NOT NULL,
            event_name                  VARCHAR NOT NULL,
            event_category              VARCHAR,
            official_planned_waypoints  VARCHAR,
            start_time                  TIME,
            end_time                    TIME,
            route_detail                VARCHAR,
            source_url                  VARCHAR NOT NULL,
            evidence_type               VARCHAR,
            observed_route_verified     VARCHAR,
            organiser                   VARCHAR,
            motivation                  VARCHAR,
            turnout                     INTEGER CHECK (turnout IS NULL OR turnout > 0)
        );
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS waypoints (
            event_id            VARCHAR NOT NULL REFERENCES events(event_id),
            event_date          DATE,
            sequence_index      INTEGER NOT NULL,
            waypoint_name       VARCHAR NOT NULL,
            latitude            DOUBLE NOT NULL,
            longitude           DOUBLE NOT NULL,
            nearest_node        VARCHAR,
            snap_distance_m     DOUBLE,
            geo_review_status   VARCHAR,
            geom                GEOMETRY,
            PRIMARY KEY (event_id, sequence_index)
        );
    """)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    con = get_connection()
    try:
        init_schema(con)
        logger.info("%s", con.execute("SHOW TABLES").fetchall())
    finally:
        con.close()
