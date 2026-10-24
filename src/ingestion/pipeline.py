from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from ingestion.models import ProtestRecord
from ingestion.platforms import PLATFORM_CATALOG, platform_meta, record_export_dict
from ingestion.sources import MetPoliceCrawler, OsacCrawler, TflRoadDisruptionCrawler


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
    ) -> dict[str, Any]:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        summary: dict[str, Any] = {
            "run_id": run_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "platforms": {},
            "errors": [],
        }

        all_records: list[ProtestRecord] = []
        records_by_platform: dict[str, list[ProtestRecord]] = {
            platform_id: [] for platform_id in PLATFORM_CATALOG
        }

        met_media_dir = run_dir / "met_police" / "media"

        crawlers = [
            (
                "met_police",
                lambda: MetPoliceCrawler(media_dir=met_media_dir).fetch_records(
                    limit=met_limit
                ),
            ),
            ("osac", lambda: OsacCrawler().fetch_records(limit=osac_limit)),
            (
                "tfl_road_disruption",
                lambda: TflRoadDisruptionCrawler().fetch_records(days_ahead=tfl_days_ahead),
            ),
        ]

        platform_paths: dict[str, str] = {}

        for platform_id, fetch_fn in crawlers:
            platform_dir = run_dir / platform_id
            platform_dir.mkdir(parents=True, exist_ok=True)
            records_path = platform_dir / "records.json"

            try:
                records = fetch_fn()
                records_by_platform[platform_id] = records
                all_records.extend(records)
                self._write_platform_records(records_path, run_id, platform_id, records)
                platform_paths[platform_id] = str(records_path.relative_to(self.output_dir))
                summary["platforms"][platform_id] = {
                    **platform_meta(platform_id),
                    "status": "ok",
                    "records": len(records),
                    "records_path": platform_paths[platform_id],
                }
            except Exception as exc:  # noqa: BLE001 - test pipeline should continue
                summary["platforms"][platform_id] = {
                    **platform_meta(platform_id),
                    "status": "error",
                    "error": str(exc),
                    "records_path": str(records_path.relative_to(self.output_dir)),
                }
                summary["errors"].append({"platform_id": platform_id, "error": str(exc)})

        flat_path = run_dir / "_all" / "protests_flat.json"
        flat_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json(flat_path, all_records)
        parquet_path = run_dir / "_all" / "protests.parquet"
        self._write_parquet(parquet_path, all_records)

        met_images = sum(
            len(record.extra.get("images", []))
            for record in all_records
            if record.source == "met_police"
        )
        summary["outputs"] = {
            "run_dir": str(run_dir.relative_to(self.output_dir)),
            "platform_folders": platform_paths,
            "flat_json": str(flat_path.relative_to(self.output_dir)),
            "parquet": str(parquet_path.relative_to(self.output_dir)),
            "total_records": len(all_records),
            "records_by_platform": {
                platform_id: len(records)
                for platform_id, records in records_by_platform.items()
            },
            "met_police_media_dir": str(met_media_dir.relative_to(self.output_dir)),
            "met_police_images_indexed": met_images,
        }
        summary["finished_at"] = datetime.now(timezone.utc).isoformat()
        return summary

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

    def _write_json(self, path: Path, records: list[ProtestRecord] | dict) -> None:
        if isinstance(records, list):
            payload = [record_export_dict(record) for record in records]
        else:
            payload = records
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _write_parquet(self, path: Path, records: list[ProtestRecord]) -> None:
        if not records:
            path.write_bytes(b"")
            return
        frame = pd.DataFrame([record_export_dict(record) for record in records])
        conn = duckdb.connect(database=":memory:")
        conn.register("protests_df", frame)
        conn.execute(f"COPY protests_df TO '{path.as_posix()}' (FORMAT PARQUET)")
        conn.close()
