"""Pure loader helpers: quote, reader_sql, with_points, plan."""

from __future__ import annotations

from pathlib import Path

from src.database.load import plan, quote, reader_sql, with_points


def test_quote_escapes_single_quotes() -> None:
    assert quote(Path("/tmp/o'brien/data.csv")) == "'/tmp/o''brien/data.csv'"


def test_reader_sql_csv() -> None:
    p = Path("data/events.csv")
    sql = reader_sql(p, "csv")
    assert "read_csv" in sql
    assert "data/events.csv" in sql


def test_reader_sql_geojson() -> None:
    sql = reader_sql(Path("x.geojson"), "geojson")
    assert "ST_Read" in sql


def test_with_points_wraps() -> None:
    inner = "SELECT 1 AS latitude, 2 AS longitude"
    wrapped = with_points(inner, "latitude", "longitude")
    assert "ST_Point" in wrapped
    assert inner in wrapped


def test_plan_missing_file_yields_none_sql(tmp_path: Path) -> None:
    mapped = plan(tmp_path)
    assert mapped["events"][1] is None


def test_plan_present_csv(tmp_path: Path) -> None:
    norm = tmp_path / "normalised"
    norm.mkdir(parents=True)
    (norm / "events.csv").write_text("event_id,event_date\nE1,2026-06-01\n", encoding="utf-8")
    _path, sql = plan(tmp_path)["events"]
    assert sql is not None
    assert "read_csv" in sql
