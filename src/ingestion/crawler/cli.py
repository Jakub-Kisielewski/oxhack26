"""CLI for sequential protest ingestion (one platform at a time)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from ingestion.crawler.pipeline import ProtestIngestionPipeline
from ingestion.crawler.sources.organizers import ORGANIZER_SITES

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _ensure_project_python() -> None:
    """Re-exec with project .venv when conda/system Python lacks deps."""
    try:
        import duckdb  # noqa: F401
    except ModuleNotFoundError:
        venv_python = _REPO_ROOT / ".venv" / "bin" / "python"
        if venv_python.is_file():
            os.execv(str(venv_python), [str(venv_python), *sys.argv])
        print(
            "Missing dependencies (duckdb). Create the venv and install:\n"
            "  python3 -m venv .venv\n"
            "  .venv/bin/pip install -r requirements.txt\n"
            "  .venv/bin/python -m src.ingestion",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


def _platform_choices() -> list[str]:
    tier1 = ["met_police", "osac", "tfl_road_disruption", "marble_arch_security"]
    organizers = [site.platform_id for site in ORGANIZER_SITES]
    return tier1 + organizers


def main() -> None:
    parser = argparse.ArgumentParser(
        description="London protest ingestion (sequential per-site saves)"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data"),
        help="Directory for pipeline outputs (default: data/)",
    )
    parser.add_argument(
        "--platform",
        action="append",
        dest="platforms",
        metavar="ID",
        help=(
            "Crawl only this platform (repeatable). "
            f"Examples: cnd, met_police. Omit to run all in order."
        ),
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Reuse an existing run folder under data/runs/ (append more platforms)",
    )
    parser.add_argument("--met-limit", type=int, default=8)
    parser.add_argument("--osac-limit", type=int, default=12)
    parser.add_argument("--tfl-days-ahead", type=int, default=30)
    parser.add_argument(
        "--organizer-event-days-back",
        type=int,
        default=0,
        help="Organizer sources: only keep events with a date in the last N days (0 = no limit)",
    )
    parser.add_argument(
        "--organizer-event-days-ahead",
        type=int,
        default=0,
        help="Organizer sources: also include events up to N days in the future (0 = no limit)",
    )
    parser.add_argument(
        "--list-platforms",
        action="store_true",
        help="Print platform IDs and exit",
    )
    args = parser.parse_args()

    if args.list_platforms:
        for platform_id in _platform_choices():
            print(platform_id)
        return

    def on_done(platform_id: str, result: dict) -> None:
        status = result.get("status", "?")
        count = result.get("records", 0)
        path = result.get("records_path", "")
        print(f"[{platform_id}] {status} — {count} records -> {path}", flush=True)

    pipeline = ProtestIngestionPipeline(args.output_dir)
    summary = pipeline.run(
        met_limit=args.met_limit,
        osac_limit=args.osac_limit,
        tfl_days_ahead=args.tfl_days_ahead,
        organizer_event_days_back=args.organizer_event_days_back,
        organizer_event_days_ahead=args.organizer_event_days_ahead,
        platforms=args.platforms,
        run_id=args.run_id,
        on_platform_complete=on_done,
    )
    print(json.dumps(summary, indent=2))

    outputs = summary.get("outputs", {})
    run_dir = outputs.get("run_dir")
    if run_dir:
        print(f"\nRun folder: data/{run_dir}/")
        print(f"Progress:   data/{run_dir}/run_progress.json")
        print(f"Merged:     data/{outputs.get('flat_json')}")
