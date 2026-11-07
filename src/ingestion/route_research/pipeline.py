"""Route research ingestion runner: `python -m src.ingestion.route_research.pipeline <step>`."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[2]
DEFAULT_WORKSPACE = PROJECT_ROOT / "data" / "route_research"

STEPS: dict[str, tuple[str, list[str]]] = {
    "boundary": ("sources/download_boundary.py", []),
    "osm": ("sources/download_osm.py", []),
    "landmarks": ("sources/download_landmarks.py", []),
    "weather": ("sources/download_weather.py", []),
    "pageviews": ("sources/download_pageviews.py", []),
    "seed-coords": ("processing/seed_coordinates.py", []),
    "normalize": ("processing/normalize.py", []),
    "edge-features": ("processing/edge_features.py", []),
    "event-context": ("processing/event_context.py", []),
    "cause-targets": ("processing/cause_targets.py", []),
}


def initialise_workspace(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    (target / "seed").mkdir(exist_ok=True)
    for source in (HERE / "seed").glob("*.csv"):
        dest = target / "seed" / source.name
        if not dest.exists():
            shutil.copy2(source, dest)
    for d in [
        "raw/boundary",
        "raw/osm",
        "raw/landmarks",
        "raw/weather",
        "raw/pageviews",
        "raw/calendar",
        "normalised",
    ]:
        (target / d).mkdir(parents=True, exist_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workdir", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("step", choices=["status", *STEPS])
    args, forwarded = parser.parse_known_args(argv)
    if forwarded and forwarded[0] == "--":
        forwarded = forwarded[1:]
    initialise_workspace(args.workdir)
    if args.step == "status":
        print(f"Workspace: {args.workdir.resolve()}")
        print(f"Seed CSVs: {', '.join(sorted(p.name for p in (args.workdir / 'seed').glob('*.csv')))}")
        print("Steps:", ", ".join(STEPS))
        return 0
    relative_path, prefix = STEPS[args.step]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(PROJECT_ROOT), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    return subprocess.run(
        [sys.executable, str(HERE / relative_path), *prefix, *forwarded],
        cwd=args.workdir,
        env=env,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
