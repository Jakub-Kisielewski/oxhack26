"""Route research ingestion runner: `python -m src.ingestion.route_research.pipeline <step>`."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from src.ingestion.route_research import steps

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[2]
DEFAULT_WORKSPACE = PROJECT_ROOT / "data" / "route_research"

STEPS: dict[str, str] = dict(steps.RUNNERS)


def initialise_workspace(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    (target / "seed").mkdir(exist_ok=True)
    for source in (HERE / "seed").glob("*.csv"):
        dest = target / "seed" / source.name
        if not dest.exists():
            shutil.copy2(source, dest)
    for subdir in ("raw/boundary", "raw/osm", "raw/landmarks", "raw/weather", "normalised"):
        (target / subdir).mkdir(parents=True, exist_ok=True)


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
        print("Steps:", ", ".join(STEPS.keys()))
        return 0
    context = steps.StepContext(args.workdir)
    return steps.run_named_step(args.step, context, forwarded)


if __name__ == "__main__":
    raise SystemExit(main())
