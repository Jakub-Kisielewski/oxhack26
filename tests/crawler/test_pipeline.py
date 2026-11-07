"""Pipeline integration tests with stub sources."""

from __future__ import annotations

import csv
from pathlib import Path

from ingestion.crawler.models import CANDIDATE_CSV_COLUMNS, ProtestRecord
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
                title="Test march",
                url="https://example.org/1",
                fetched_at="2026-01-01T00:00:00Z",
                route_text="Whitehall to Parliament Square",
            )
        ]


class FailSource(ProtestSource):
    platform_id = "fail_source"
    platform_name = "Fail"
    platform_url = "https://example.org"

    def fetch_records(self) -> list[ProtestRecord]:
        raise RuntimeError("simulated failure")


def test_failing_source_does_not_abort_discover(tmp_path: Path) -> None:
    pipeline = ProtestIngestionPipeline(tmp_path)
    summary = pipeline.discover(sources=[OkSource(), FailSource()])
    assert summary.records_by_source["ok_source"] == 1
    assert summary.records_by_source["fail_source"] == 0
    assert len(summary.errors) == 1

    csv_path = Path(summary.candidates_path)
    with csv_path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert set(rows[0].keys()) == set(CANDIDATE_CSV_COLUMNS)


def test_empty_discover_writes_header_only_csv(tmp_path: Path) -> None:
    class EmptySource(ProtestSource):
        platform_id = "empty"
        platform_name = "Empty"
        platform_url = "https://example.org"

        def fetch_records(self) -> list[ProtestRecord]:
            return []

    pipeline = ProtestIngestionPipeline(tmp_path)
    summary = pipeline.discover(sources=[EmptySource()])
    csv_path = Path(summary.candidates_path)
    with csv_path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 0
    assert summary.total_records == 0
