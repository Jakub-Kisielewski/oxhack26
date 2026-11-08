#!/usr/bin/env python3
"""Run ingestion in dependency order: `python ingest.py`

Builds route research data under data/route_research/ and loads data/protest.duckdb.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from src.ingestion.route_research import pipeline as route_pipeline

ROOT = Path(__file__).resolve().parent
WORKDIR = route_pipeline.DEFAULT_WORKSPACE


def _no_skip(_: argparse.Namespace) -> str | None:
    return None


def _no_extra_args(_: argparse.Namespace) -> list[str]:
    return []


@dataclass
class Step:
    name: str
    description: str
    needs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    skip_reason: Callable[[argparse.Namespace], str | None] = _no_skip
    args: Callable[[argparse.Namespace], list[str]] = _no_extra_args
    kind: str = "route"


STEPS = [
    Step(
        "boundary",
        "Zones 1-2 polygon from TfL station zones",
        outputs=["raw/boundary/zones_1_2.geojson"],
    ),
    Step(
        "osm",
        "OSM walk network + main-road network clipped to the boundary",
        needs=["boundary"],
        outputs=["raw/osm/london_walk.graphml", "raw/osm/london_main.graphml"],
    ),
    Step(
        "landmarks",
        "Protest targets and open spaces (for cause targets and edge zone flags)",
        needs=["boundary"],
        outputs=[
            "raw/landmarks/targets.geoparquet",
            "raw/landmarks/open_spaces.geoparquet",
        ],
        args=lambda a: (
            ["--layers", "targets", "open_spaces"]
            + (["--refresh"] if "landmarks" in a.refresh_steps else [])
        ),
    ),
    Step("seed-coords", "coordinate_review.csv from the reviewed seed geocodes"),
    Step(
        "normalize",
        "Street segments, route labels and context tables",
        needs=["osm", "seed-coords"],
    ),
    Step(
        "edge-features",
        "Street width, main-network betweenness, junction degree, legal-zone flags",
        needs=["osm", "landmarks"],
        outputs=["normalised/edge_features.csv"],
    ),
    Step("weather", "Hourly Open-Meteo weather around each event date"),
    Step("event-context", "Per-event cause, precipitation and daylight (model context)"),
    Step(
        "cause-targets",
        "Cause -> target table located from the data and checked against seed routes",
        needs=["normalize", "event-context"],
    ),
    Step("database", "Load all outputs into data/protest.duckdb", kind="database"),
]


def run_step(step: Step, args) -> int:
    if step.kind == "route":
        return route_pipeline.main(["--workdir", str(args.workdir), step.name, *step.args(args)])
    from src.database.load import main as load_main

    return load_main([])


def cached(step: Step, args) -> bool:
    return (
        bool(step.outputs)
        and step.name not in args.refresh_steps
        and all((args.workdir / o).exists() for o in step.outputs)
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    names = [s.name for s in STEPS]
    p.add_argument("--only", nargs="+", choices=names, metavar="STEP")
    p.add_argument("--skip", nargs="+", choices=names, default=[], metavar="STEP")
    p.add_argument(
        "--refresh",
        nargs="*",
        choices=names,
        metavar="STEP",
        help="Re-run cached downloads (all, or named steps)",
    )
    p.add_argument("--workdir", type=Path, default=WORKDIR)
    p.add_argument("--list", action="store_true")
    args = p.parse_args(argv)
    args.refresh_steps = set(names) if args.refresh == [] else set(args.refresh or [])

    if args.list:
        for s in STEPS:
            extra = f"  (needs {', '.join(s.needs)})" if s.needs else ""
            print(f"{s.name:<15} {s.description}{extra}")
        return 0

    selected = [
        s for s in STEPS if (not args.only or s.name in args.only) and s.name not in args.skip
    ]
    status: dict[str, str] = {}
    timings: dict[str, float] = {}
    for step in selected:
        blocked = [
            n for n in step.needs if status.get(n, "ok").startswith(("FAILED", "skipped (needs"))
        ]
        reason = step.skip_reason(args)
        if blocked:
            status[step.name] = f"skipped (needs {', '.join(blocked)})"
        elif reason:
            status[step.name] = f"skipped ({reason})"
        elif cached(step, args):
            status[step.name] = "cached (use --refresh to redo)"
        else:
            print(f"\n=== {step.name}: {step.description} ===", flush=True)
            start = time.monotonic()
            try:
                code = run_step(step, args)
            except Exception as exc:
                print(f"{step.name} raised {exc!r}", file=sys.stderr)
                code = 1
            timings[step.name] = time.monotonic() - start
            status[step.name] = "ok" if code == 0 else f"FAILED (exit {code})"

    print("\n=== Ingestion summary ===")
    for step in selected:
        t = f" {timings[step.name]:.0f}s" if step.name in timings else ""
        print(f"{step.name:<15} {status[step.name]}{t}")
    return 1 if any(v.startswith("FAILED") for v in status.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
