"""Orchestrates protest source fetches and run artefacts under ``data/runs/``."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from ingestion.crawler.models import PROTEST_RECORD_COLUMNS
from ingestion.crawler.platforms import PLATFORM_CATALOG, platform_meta, record_export_dict
from ingestion.crawler.run_summary import RunSummary
from ingestion.crawler.sources.base import ProtestSource
from ingestion.crawler.sources.registry import default_sources

logger = logging.getLogger(__name__)


class ProtestIngestionPipeline:
    """Writes each run under data/runs/{run_id}/{platform_id}/records.json."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir = output_dir / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        sources: list[ProtestSource] | None = None,
        *,
        run_id: str | None = None,
        platforms: list[str] | None = None,
        on_platform_complete: Callable[[str, dict[str, Any]], None] | None = None,
        organizer_event_days_back: int = 0,
        organizer_event_days_ahead: int = 0,
        met_limit: int = 8,
        osac_limit: int = 12,
        tfl_days_ahead: int = 30,
        marble_arch_limit: int | None = None,
    ) -> RunSummary:
        """Fetch each source sequentially and persist progress after every platform."""
        run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        summary_path = run_dir / "run_progress.json"
        summary = self._load_or_init_summary(
            summary_path,
            run_id=run_id,
            organizer_event_days_back=organizer_event_days_back,
            organizer_event_days_ahead=organizer_event_days_ahead,
        )

        met_media_dir = run_dir / "met_police" / "media"
        if sources is None:
            sources = default_sources(
                met_media_dir=met_media_dir,
                met_limit=met_limit,
                osac_limit=osac_limit,
                tfl_days_ahead=tfl_days_ahead,
                marble_arch_limit=marble_arch_limit,
                organizer_event_days_back=organizer_event_days_back,
                organizer_event_days_ahead=organizer_event_days_ahead,
            )
        selected = self._resolve_platforms(platforms, sources)
        platform_paths: dict[str, str] = dict(summary.outputs.get("platform_folders", {}))

        for source in selected:
            platform_id = source.platform_id
            platform_dir = run_dir / platform_id
            platform_dir.mkdir(parents=True, exist_ok=True)
            records_path = platform_dir / "records.json"

            try:
                records = source.fetch_records()
                self._write_platform_records(records_path, run_id, platform_id, records)
                platform_paths[platform_id] = str(records_path.relative_to(self.output_dir))
                platform_result = {
                    **platform_meta(platform_id),
                    "status": "ok",
                    "records": len(records),
                    "records_path": platform_paths[platform_id],
                    "finished_at": datetime.now(UTC).isoformat(),
                }
                summary.platforms[platform_id] = platform_result
            except Exception as exc:  # noqa: BLE001 - one source must not abort the run
                logger.exception("platform %s failed", platform_id)
                platform_result = {
                    **platform_meta(platform_id),
                    "status": "error",
                    "error": str(exc),
                    "records_path": str(records_path.relative_to(self.output_dir)),
                    "finished_at": datetime.now(UTC).isoformat(),
                }
                summary.platforms[platform_id] = platform_result
                summary.errors.append({"platform_id": platform_id, "error": str(exc)})

            self._rebuild_aggregate(run_dir)
            summary.outputs = self._build_outputs(run_dir, run_id, platform_paths, met_media_dir)
            summary.updated_at = datetime.now(UTC).isoformat()
            self._write_json(summary_path, summary.to_dict())

            if on_platform_complete:
                on_platform_complete(platform_id, platform_result)

        summary.finished_at = datetime.now(UTC).isoformat()
        self._write_json(summary_path, summary.to_dict())
        return summary

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
            raise ValueError(f"Unknown platform(s): {', '.join(unknown)}. Known: {known}")
        return [by_id[p] for p in platforms]

    def _load_or_init_summary(
        self,
        path: Path,
        *,
        run_id: str,
        organizer_event_days_back: int,
        organizer_event_days_ahead: int,
    ) -> RunSummary:
        if path.exists():
            return RunSummary.from_dict(json.loads(path.read_text(encoding="utf-8")))
        return RunSummary(
            run_id=run_id,
            started_at=datetime.now(UTC).isoformat(),
            organizer_event_window={
                "days_back": organizer_event_days_back,
                "days_ahead": organizer_event_days_ahead,
            },
        )

    def _rebuild_aggregate(self, run_dir: Path) -> None:
        records = self._read_all_platform_records(run_dir)
        flat_path = run_dir / "_all" / "protests_flat.json"
        flat_path.parent.mkdir(parents=True, exist_ok=True)
        flat_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
        parquet_path = run_dir / "_all" / "protests.parquet"
        self._write_parquet(parquet_path, records)

    def _read_all_platform_records(self, run_dir: Path) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        for platform_dir in sorted(run_dir.iterdir()):
            if not platform_dir.is_dir() or platform_dir.name.startswith("_"):
                continue
            records_path = platform_dir / "records.json"
            if not records_path.exists():
                continue
            payload = json.loads(records_path.read_text(encoding="utf-8"))
            merged.extend(payload.get("records", []))
        return merged

    def _build_outputs(
        self,
        run_dir: Path,
        run_id: str,
        platform_paths: dict[str, str],
        met_media_dir: Path,
    ) -> dict[str, Any]:
        all_records = self._read_all_platform_records(run_dir)
        records_by_platform: dict[str, int] = {pid: 0 for pid in PLATFORM_CATALOG}
        for record in all_records:
            source = record.get("source") or record.get("platform_id") or ""
            if source in records_by_platform:
                records_by_platform[source] += 1

        met_images = sum(
            len(record.get("extra", {}).get("images", []))
            for record in all_records
            if record.get("source") == "met_police"
        )
        flat_rel = str((run_dir / "_all" / "protests_flat.json").relative_to(self.output_dir))
        parquet_rel = str((run_dir / "_all" / "protests.parquet").relative_to(self.output_dir))
        return {
            "run_dir": str(run_dir.relative_to(self.output_dir)),
            "run_id": run_id,
            "platform_folders": platform_paths,
            "flat_json": flat_rel,
            "parquet": parquet_rel,
            "total_records": len(all_records),
            "records_by_platform": records_by_platform,
            "met_police_media_dir": str(met_media_dir.relative_to(self.output_dir)),
            "met_police_images_indexed": met_images,
        }

    def _write_platform_records(
        self,
        path: Path,
        run_id: str,
        platform_id: str,
        records: list,
    ) -> None:
        payload = {
            "run_id": run_id,
            **platform_meta(platform_id),
            "record_count": len(records),
            "records": [record_export_dict(record) for record in records],
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _write_parquet(self, path: Path, records: list[dict[str, Any]]) -> None:
        """Write records to Parquet, including a valid empty file when there are none."""
        normalised: list[dict[str, Any]] = []
        for row in records:
            copy = dict(row)
            extra = copy.get("extra")
            if isinstance(extra, dict):
                copy["extra"] = json.dumps(extra) if extra else "{}"
            normalised.append(copy)
        frame = pd.DataFrame(normalised, columns=list(PROTEST_RECORD_COLUMNS))
        frame.to_parquet(path, index=False)
