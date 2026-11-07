"""Regression: DuckDB version mismatch requires --rebuild."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import duckdb

from src.database.load import main


def test_newer_duckdb_without_rebuild_returns_one(tmp_path: Path) -> None:
    db = tmp_path / "protest.duckdb"
    db.touch()

    def raise_newer(*_args, **_kwargs):
        raise duckdb.IOException("file has been written by a newer version of DuckDB")

    with patch("src.database.load.get_connection", side_effect=raise_newer):
        assert main(["--db", str(db)]) == 1
    assert db.exists()
