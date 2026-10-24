from pathlib import Path
import duckdb

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "protest.duckdb"

def get_connection(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    DB_PATH.parent.mkdir(exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=read_only)
    try:
        con.execute("LOAD spatial")
    except duckdb.Error:
        con.execute("INSTALL spatial")
        con.execute("LOAD spatial")
    return con

def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS crimes (
            id           VARCHAR,
            category     VARCHAR,
            month        DATE,
            lat          DOUBLE,
            lon          DOUBLE,
            geom         GEOMETRY,
            street_name  VARCHAR
        );
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS transit_snapshots (
            ts          TIMESTAMP,
            route_id    VARCHAR,
            vehicle_id  VARCHAR,
            lat         DOUBLE,
            lon         DOUBLE,
            delay_sec   INTEGER
        );
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS grid_cells (
            cell_id   INTEGER PRIMARY KEY,
            geom      GEOMETRY,
            centroid_lat DOUBLE,
            centroid_lon DOUBLE
        );
    """)

if __name__ == "__main__":
    con = get_connection()
    try:
        init_schema(con)
        print(con.execute("SHOW TABLES").fetchall())
    finally:
        con.close()
