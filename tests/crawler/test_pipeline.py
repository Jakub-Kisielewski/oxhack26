"""Pipeline integration tests with stub sources."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ingestion.crawler.models import ProtestRecord
from ingestion.crawler.pipeline import ProtestIngestionPipeline
from ingestion.crawler.sources.base import ProtestSource


class OkSource(ProtestSource):
    platform_id = "ok_source"
    platform_name = "OK"
    platform_url = "https://example.org"

    def fetch_records(self) -> list[ProtestRecord]:
        return [
            ProtestRecord(
                source=self.platform_id,
                source_id="1",
                title="Test",
                url="https://example.org/1",
                fetched_at="2026-01-01T00:00:00Z",
            )
        ]


class FailSource(ProtestSource):
    platform_id = "fail_source"
    platform_name = "Fail"
    platform_url = "https://example.org"

    def fetch_records(self) -> list[ProtestRecord]:
        raise RuntimeError("simulated failure")


def test_failing_source_does_not_abort_run(tmp_path: Path) -> None:
    pipeline = ProtestIngestionPipeline(tmp_path)
    summary = pipeline.run(sources=[OkSource(), FailSource()])
    assert summary.platforms["ok_source"]["status"] == "ok"
    assert summary.platforms["fail_source"]["status"] == "error"
    parquet = tmp_path / summary.outputs["parquet"]
    assert parquet.exists()
    frame = pd.read_parquet(parquet)
    assert len(frame) == 1


def test_empty_run_writes_valid_parquet(tmp_path: Path) -> None:
    class EmptySource(ProtestSource):
        platform_id = "empty"
        platform_name = "Empty"
        platform_url = "https://example.org"

        def fetch_records(self) -> list[ProtestRecord]:
            return []

    pipeline = ProtestIngestionPipeline(tmp_path)
    summary = pipeline.run(sources=[EmptySource()])
    parquet = tmp_path / summary.outputs["parquet"]
    frame = pd.read_parquet(parquet)
    assert len(frame) == 0
    assert list(frame.columns)
