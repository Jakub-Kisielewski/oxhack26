"""load_log bookkeeping after a successful declared load."""

from __future__ import annotations

from pathlib import Path

from src.database.db import get_connection
from src.database.load import load

EVENTS_HEADER = (
    "event_id,event_date,event_name,event_category,official_planned_waypoints,"
    "start_time,end_time,route_detail,source_url,evidence_type,"
    "observed_route_verified,organiser,motivation,turnout\n"
)


def test_load_log_records_events(tmp_path: Path) -> None:
    norm = tmp_path / "normalised"
    norm.mkdir(parents=True)
    (norm / "events.csv").write_text(
        EVENTS_HEADER + "E1,2026-06-01,Test,protest,,12:00,13:00,detailed,http://x,,no,,,100\n",
        encoding="utf-8",
    )
    con = get_connection(path=tmp_path / "log.duckdb")
    try:
        load(con, tmp_path)
        row = con.execute(
            "SELECT source_file, rows FROM load_log WHERE table_name = 'events'"
        ).fetchone()
        assert row is not None
        assert row[1] == 1
    finally:
        con.close()
