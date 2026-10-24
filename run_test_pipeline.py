#!/usr/bin/env python3
"""Run Tier 1 protest ingestion (Met Police, OSAC, TfL) and write test artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ingestion.pipeline import ProtestIngestionPipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="London protest Tier-1 test pipeline")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data"),
        help="Directory for pipeline outputs (default: data/)",
    )
    parser.add_argument("--met-limit", type=int, default=8)
    parser.add_argument("--osac-limit", type=int, default=12)
    parser.add_argument("--tfl-days-ahead", type=int, default=30)
    args = parser.parse_args()

    pipeline = ProtestIngestionPipeline(args.output_dir)
    summary = pipeline.run(
        met_limit=args.met_limit,
        osac_limit=args.osac_limit,
        tfl_days_ahead=args.tfl_days_ahead,
    )
    print(json.dumps(summary, indent=2))

    outputs = summary.get("outputs", {})
    run_dir = outputs.get("run_dir")
    if run_dir:
        print(f"\nData is in subfolders under: data/{run_dir}/")
        for platform_id, rel_path in outputs.get("platform_folders", {}).items():
            print(f"  {platform_id:22} -> data/{rel_path}")


if __name__ == "__main__":
    main()
