from pathlib import Path

import duckdb

from src.config import DB_PATH


def _install_spatial(con: duckdb.DuckDBPyConnection) -> None:
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
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path), read_only=read_only)
    try:
        con.execute("LOAD spatial")
    except duckdb.Error:
        _install_spatial(con)
        con.execute("LOAD spatial")
    return con


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS load_log (
            table_name   VARCHAR PRIMARY KEY,
            source_file  VARCHAR,
            rows         BIGINT,
            loaded_at    TIMESTAMP
        );
    """)
    con.execute("""
        CREATE OR REPLACE MACRO meters(a, b) AS ST_Distance(
            ST_Transform(a, 'EPSG:4326', 'EPSG:27700', always_xy := true),
            ST_Transform(b, 'EPSG:4326', 'EPSG:27700', always_xy := true));
    """)


if __name__ == "__main__":
    con = get_connection()
    try:
        init_schema(con)
        print(con.execute("SHOW TABLES").fetchall())
    finally:
        con.close()
