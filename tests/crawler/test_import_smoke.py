"""Smoke import tests."""

from __future__ import annotations


def test_cli_main_importable() -> None:
    from ingestion.crawler.cli import main

    assert callable(main)
