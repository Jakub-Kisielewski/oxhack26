"""CLI for protest discovery (writes candidates.csv)."""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Sequence
from pathlib import Path

from ingestion.crawler.constants import DEFAULT_MET_LIMIT
from ingestion.crawler.pipeline import ProtestIngestionPipeline
from ingestion.crawler.platforms import PLATFORM_CATALOG


def _platform_choices() -> list[str]:
    return list(PLATFORM_CATALOG.keys())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Discover London march candidates for human geocode review",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--candidates-file",
        type=str,
        default="candidates.csv",
        help="CSV filename under --output-dir",
    )
    parser.add_argument("--platform", action="append", dest="platforms", metavar="ID")
    parser.add_argument("--met-limit", type=int, default=DEFAULT_MET_LIMIT)
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

    pipeline = ProtestIngestionPipeline(args.output_dir)
    summary = pipeline.discover(
        platforms=args.platforms,
        candidates_name=args.candidates_file,
        met_limit=args.met_limit,
        organizer_event_days_back=args.organizer_event_days_back,
        organizer_event_days_ahead=args.organizer_event_days_ahead,
    )
    print(json.dumps(summary.to_dict(), indent=2))
    print(f"\nCandidates: {summary.candidates_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
