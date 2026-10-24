from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import duckdb
import pandas as pd

from ingestion.crawler.models import ProtestRecord
from ingestion.crawler.platforms import PLATFORM_CATALOG, platform_meta, record_export_dict
from ingestion.crawler.sources import (
    MarbleArchSecurityCrawler,
    MetPoliceCrawler,
    OsacCrawler,
    TflRoadDisruptionCrawler,
)
from ingestion.crawler.sources.organizers import ORGANIZER_SITES, OrganizerSiteCrawler


class ProtestIngestionPipeline:
    """Writes each run under data/runs/{run_id}/{platform_id}/records.json."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir = output_dir / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        *,
        met_limit: int = 8,
        osac_limit: int = 12,
        tfl_days_ahead: int = 30,
        marble_arch_limit: Optional[int] = None,
        organizer_event_days_back: int = 0,
        organizer_event_days_ahead: int = 0,
        platforms: Optional[list[str]] = None,
        run_id: Optional[str] = None,
        on_platform_complete: Optional[Callable[[str, dict[str, Any]], None]] = None,
    ) -> dict[str, Any]:
        run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
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
        crawlers = self._build_crawlers(
            met_media_dir=met_media_dir,
            met_limit=met_limit,
            osac_limit=osac_limit,
            tfl_days_ahead=tfl_days_ahead,
            marble_arch_limit=marble_arch_limit,
            organizer_event_days_back=organizer_event_days_back,
            organizer_event_days_ahead=organizer_event_days_ahead,
        )

        selected = self._resolve_platforms(platforms, crawlers)
        platform_paths: dict[str, str] = dict(
            summary.get("outputs", {}).get("platform_folders", {})
        )

        for platform_id in selected:
            platform_dir = run_dir / platform_id
            platform_dir.mkdir(parents=True, exist_ok=True)
            records_path = platform_dir / "records.json"
            fetch_fn = crawlers[platform_id]

            try:
                records = fetch_fn()
                self._write_platform_records(records_path, run_id, platform_id, records)
                platform_paths[platform_id] = str(
                    records_path.relative_to(self.output_dir)
                )
                platform_result = {
                    **platform_meta(platform_id),
                    "status": "ok",
                    "records": len(records),
                    "records_path": platform_paths[platform_id],
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                }
                summary["platforms"][platform_id] = platform_result
            except Exception as exc:  # noqa: BLE001 - test pipeline should continue
                platform_result = {
                    **platform_meta(platform_id),
                    "status": "error",
                    "error": str(exc),
                    "records_path": str(records_path.relative_to(self.output_dir)),
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                }
                summary["platforms"][platform_id] = platform_result
                summary["errors"].append({"platform_id": platform_id, "error": str(exc)})

            self._rebuild_aggregate(run_dir)
            summary["outputs"] = self._build_outputs(
                run_dir, run_id, platform_paths, met_media_dir
            )
            summary["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._write_json(summary_path, summary)

            if on_platform_complete:
                on_platform_complete(platform_id, platform_result)

        summary["finished_at"] = datetime.now(timezone.utc).isoformat()
        self._write_json(summary_path, summary)
        return summary

    def _build_crawlers(
        self,
        *,
        met_media_dir: Path,
        met_limit: int,
        osac_limit: int,
        tfl_days_ahead: int,
        marble_arch_limit: Optional[int],
        organizer_event_days_back: int,
        organizer_event_days_ahead: int,
    ) -> dict[str, Callable[[], list[ProtestRecord]]]:
        crawlers: dict[str, Callable[[], list[ProtestRecord]]] = {
            "met_police": lambda: MetPoliceCrawler(media_dir=met_media_dir).fetch_records(
                limit=met_limit
            ),
            "osac": lambda: OsacCrawler().fetch_records(limit=osac_limit),
            "tfl_road_disruption": lambda: TflRoadDisruptionCrawler().fetch_records(
                days_ahead=tfl_days_ahead
            ),
            "marble_arch_security": lambda: MarbleArchSecurityCrawler().fetch_records(
                limit=marble_arch_limit
            ),
        }
        for site in ORGANIZER_SITES:
            crawlers[site.platform_id] = (
                lambda s=site: OrganizerSiteCrawler(
                    s,
                    event_days_back=organizer_event_days_back,
                    event_days_ahead=organizer_event_days_ahead,
                ).fetch_records()
            )
        return crawlers

    def _resolve_platforms(
        self,
        platforms: Optional[list[str]],
        crawlers: dict[str, Callable[[], list[ProtestRecord]]],
    ) -> list[str]:
        if not platforms:
            return list(crawlers.keys())
        unknown = [p for p in platforms if p not in crawlers]
        if unknown:
            known = ", ".join(sorted(crawlers.keys()))
            raise ValueError(f"Unknown platform(s): {', '.join(unknown)}. Known: {known}")
        return platforms

    def _load_or_init_summary(
        self,
        path: Path,
        *,
        run_id: str,
        organizer_event_days_back: int,
        organizer_event_days_ahead: int,
    ) -> dict[str, Any]:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {
            "run_id": run_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "organizer_event_window": {
                "days_back": organizer_event_days_back,
                "days_ahead": organizer_event_days_ahead,
            },
            "platforms": {},
            "errors": [],
            "outputs": {},
        }

    def _rebuild_aggregate(self, run_dir: Path) -> None:
        records = self._read_all_platform_records(run_dir)
        flat_path = run_dir / "_all" / "protests_flat.json"
        flat_path.parent.mkdir(parents=True, exist_ok=True)
        flat_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
        parquet_path = run_dir / "_all" / "protests.parquet"
        self._write_parquet_from_dicts(parquet_path, records)

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
        records: list[ProtestRecord],
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

    def _write_parquet_from_dicts(self, path: Path, records: list[dict[str, Any]]) -> None:
        if not records:
            path.write_bytes(b"")
            return
        frame = pd.DataFrame(records)
        conn = duckdb.connect(database=":memory:")
        conn.register("protests_df", frame)
        conn.execute(f"COPY protests_df TO '{path.as_posix()}' (FORMAT PARQUET)")
        conn.close()
