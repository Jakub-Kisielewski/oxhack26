"""Discovery crawl: fetch sources and write a single candidates CSV."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from ingestion.crawler.models import ProtestRecord, write_candidates_csv
from ingestion.crawler.run_summary import DiscoverSummary
from ingestion.crawler.sources.base import ProtestSource
from ingestion.crawler.sources.registry import default_sources

logger = logging.getLogger(__name__)


class ProtestIngestionPipeline:
    """Fetches protest sources and writes ``candidates.csv`` under the output directory."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def discover(
        self,
        sources: list[ProtestSource] | None = None,
        *,
        platforms: list[str] | None = None,
        candidates_name: str = "candidates.csv",
        met_limit: int | None = None,
        organizer_event_days_back: int = 0,
        organizer_event_days_ahead: int = 0,
    ) -> DiscoverSummary:
        """Fetch each source and merge rows into one reviewable CSV."""
        started_at = datetime.now(UTC).isoformat()
        kwargs: dict = {
            "organizer_event_days_back": organizer_event_days_back,
            "organizer_event_days_ahead": organizer_event_days_ahead,
        }
        if met_limit is not None:
            kwargs["met_limit"] = met_limit
        if sources is None:
            sources = default_sources(**kwargs)
        selected = self._resolve_platforms(platforms, sources)

        all_records: list[ProtestRecord] = []
        counts: dict[str, int] = {}
        errors: list[dict[str, str]] = []

        for source in selected:
            platform_id = source.platform_id
            try:
                records = source.fetch_records_safely()
                counts[platform_id] = len(records)
                all_records.extend(records)
                logger.info("source %s: %s candidates", platform_id, len(records))
            except Exception as exc:  # noqa: BLE001 — one source must not abort the run
                logger.exception("platform %s failed", platform_id)
                counts[platform_id] = 0
                errors.append({"source": platform_id, "error": str(exc)})

        candidates_path = self.output_dir / candidates_name
        write_candidates_csv(candidates_path, all_records)
        finished_at = datetime.now(UTC).isoformat()
        return DiscoverSummary(
            started_at=started_at,
            finished_at=finished_at,
            candidates_path=str(candidates_path),
            total_records=len(all_records),
            records_by_source=counts,
            errors=errors,
        )

    def _resolve_platforms(
        self,
        platforms: list[str] | None,
        sources: list[ProtestSource],
    ) -> list[ProtestSource]:
        by_id = {source.platform_id: source for source in sources}
        if not platforms:
            return sources
        unknown = [p for p in platforms if p not in by_id]
        if unknown:
            known = ", ".join(sorted(by_id.keys()))
            msg = f"Unknown platform(s): {', '.join(unknown)}. Known: {known}"
            raise ValueError(msg)
        return [by_id[p] for p in platforms]
