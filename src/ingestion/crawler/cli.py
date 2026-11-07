"""CLI for sequential protest ingestion (one platform at a time)."""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Sequence
from pathlib import Path

from ingestion.crawler.constants import (
    DEFAULT_MET_LIMIT,
    DEFAULT_OSAC_LIMIT,
    DEFAULT_TFL_DAYS_AHEAD,
)
from ingestion.crawler.pipeline import ProtestIngestionPipeline
from ingestion.crawler.sources.organizers import ORGANIZER_SITES


def _platform_choices() -> list[str]:
    tier1 = ["met_police", "osac", "tfl_road_disruption", "marble_arch_security"]
    organizers = [site.platform_id for site in ORGANIZER_SITES]
    return tier1 + organizers


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="London protest ingestion (sequential per-site saves)"
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data"))
    parser.add_argument("--platform", action="append", dest="platforms", metavar="ID")
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--met-limit", type=int, default=DEFAULT_MET_LIMIT)
    parser.add_argument("--osac-limit", type=int, default=DEFAULT_OSAC_LIMIT)
    parser.add_argument("--tfl-days-ahead", type=int, default=DEFAULT_TFL_DAYS_AHEAD)
    parser.add_argument("--organizer-event-days-back", type=int, default=0)
    parser.add_argument("--organizer-event-days-ahead", type=int, default=0)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--list-platforms", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    if args.list_platforms:
        for platform_id in _platform_choices():
            print(platform_id)
        return 0

    def on_done(platform_id: str, result: dict) -> None:
        logging.getLogger(__name__).info(
            "[%s] %s — %s records -> %s",
            platform_id,
            result.get("status", "?"),
            result.get("records", 0),
            result.get("records_path", ""),
        )

    pipeline = ProtestIngestionPipeline(args.output_dir)
    summary = pipeline.run(
        run_id=args.run_id,
        platforms=args.platforms,
        on_platform_complete=on_done,
        organizer_event_days_back=args.organizer_event_days_back,
        organizer_event_days_ahead=args.organizer_event_days_ahead,
        met_limit=args.met_limit,
        osac_limit=args.osac_limit,
        tfl_days_ahead=args.tfl_days_ahead,
    )
    print(json.dumps(summary.to_dict(), indent=2))

    outputs = summary.outputs
    run_folder = outputs.get("run_dir")
    if run_folder:
        print(f"\nRun folder: data/{run_folder}/")
        print(f"Progress:   data/{run_folder}/run_progress.json")
        print(f"Merged:     {outputs.get('flat_json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
