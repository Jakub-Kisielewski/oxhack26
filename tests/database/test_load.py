"""Loader integration: per-table isolation and declared schema loads."""

from __future__ import annotations

from pathlib import Path

from src.database.db import get_connection, init_schema
from src.database.load import load


EVENTS_HEADER = (
    "event_id,event_date,event_name,event_category,official_planned_waypoints,"
    "start_time,end_time,route_detail,source_url,evidence_type,"
    "observed_route_verified,organiser,motivation,turnout\n"
)


def test_init_schema_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "t.duckdb"
    con = get_connection(path=db)
    try:
        init_schema(con)
        init_schema(con)
        names = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        assert "load_log" in names
        assert "events" in names
        assert "waypoints" in names
    finally:
        con.close()


def test_one_malformed_csv_does_not_abort_the_other_tables(tmp_path: Path) -> None:
    norm = tmp_path / "normalised"
    norm.mkdir(parents=True)
    (norm / "events.csv").write_text(
        EVENTS_HEADER + "E1,2026-06-01,Test,protest,,12:00,13:00,detailed,http://x,,no,,,5000\n",
        encoding="utf-8",
    )
    boundary_dir = tmp_path / "raw/boundary"
    boundary_dir.mkdir(parents=True)
    (boundary_dir / "zones_1_2.geojson").write_text("{not valid geojson", encoding="utf-8")

    con = get_connection(path=tmp_path / "test.duckdb")
    try:
        status = load(con, tmp_path)
    finally:
        con.close()

    assert status["events"] == "1 rows"
    assert status["boundary"].startswith("FAILED")


def test_events_turnout_parsed_as_integer(tmp_path: Path) -> None:
    norm = tmp_path / "normalised"
    norm.mkdir(parents=True)
    (norm / "events.csv").write_text(
        EVENTS_HEADER + "E1,2026-06-01,Test,protest,,12:00,13:00,detailed,http://x,,no,,,50000±30000\n",
        encoding="utf-8",
    )
    con = get_connection(path=tmp_path / "typed.duckdb")
    try:
        load(con, tmp_path)
        turnout = con.execute("SELECT turnout FROM events").fetchone()[0]
        assert turnout == 50_000
    finally:
        con.close()


def test_waypoints_require_known_event(tmp_path: Path) -> None:
    norm = tmp_path / "normalised"
    norm.mkdir(parents=True)
    (norm / "events.csv").write_text(
        EVENTS_HEADER + "E1,2026-06-01,Test,protest,,12:00,13:00,detailed,http://x,,no,,,1000\n",
        encoding="utf-8",
    )
    (norm / "waypoints_approved.csv").write_text(
        "event_id,event_date,sequence_index,waypoint_name,latitude,longitude\n"
        "E9,2026-06-01,1,Nowhere,51.5,-0.1\n",
        encoding="utf-8",
    )
    con = get_connection(path=tmp_path / "fk.duckdb")
    try:
        status = load(con, tmp_path)
        assert status["waypoints"].startswith("FAILED")
    finally:
        con.close()
