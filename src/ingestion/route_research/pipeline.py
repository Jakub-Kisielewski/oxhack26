"""Isolated London research ingestion runner.

Run from repository root:
    python -m src.ingestion.route_research.pipeline status
    python -m src.ingestion.route_research.pipeline osm
    python -m src.ingestion.route_research.pipeline geocode --user-agent '...'
    python -m src.ingestion.route_research.pipeline normalize

No existing src/ingestion/*.py or src/ingestion/sources/*.py is modified.
Commands run from a separate repo-root data/route_research workspace.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[2]  # oxhack26-main/
DEFAULT_WORKSPACE = PROJECT_ROOT / 'data' / 'route_research'

STEPS: dict[str, tuple[str, list[str]]] = {
    'osm': ('sources/download_osm.py', []),
    'police': ('sources/download_police.py', []),
    'tfl': ('sources/download_tfl.py', []),
    'acled': ('sources/download_acled.py', []),
    'ghsl': ('sources/download_ghsl.py', []),
    'geocode': ('processing/review_geocode_waypoints.py', ['geocode', '--waypoints', 'seed/waypoints.csv', '--review', 'coordinate_review.csv']),
    'geocode-route': ('processing/review_geocode_waypoints.py', ['build', '--waypoints', 'seed/waypoints.csv', '--review', 'coordinate_review.csv']),
    'normalize': ('processing/normalize.py', []),
    'next-street': ('processing/next_street_demo.py', []),
    'sample-ghsl': ('processing/sample_ghsl.py', []),
    'export-parquet': ('processing/export_parquet.py', []),
    'legacy-geocode': ('legacy_tools/geocode_and_route.py', ['geocode', '--waypoints', 'seed/waypoints.csv']),
    'legacy-route': ('legacy_tools/geocode_and_route.py', ['build', '--waypoints', 'seed/waypoints.csv']),
    'legacy-acled-import': ('legacy_tools/acled_london_import.py', []),
    'legacy-merge-routes': ('legacy_tools/merge_curated_routes.py', []),
}

def initialise_workspace(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    (target / 'seed').mkdir(exist_ok=True)
    for source in (HERE / 'seed').glob('*.csv'):
        dest = target / 'seed' / source.name
        if not dest.exists():
            shutil.copy2(source, dest)
    for d in ['raw/osm','raw/police','raw/tfl','raw/acled','raw/ghsl','normalised']:
        (target / d).mkdir(parents=True, exist_ok=True)

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--workdir', type=Path, default=DEFAULT_WORKSPACE,
                        help='Where raw and normalized data are written (default: data/route_research)')
    parser.add_argument('step', choices=['status', 'test', *STEPS])
    args, forwarded = parser.parse_known_args(argv)
    if forwarded and forwarded[0] == '--':
        forwarded = forwarded[1:]
    initialise_workspace(args.workdir)
    if args.step == 'status':
        print(f'Isolated workspace: {args.workdir.resolve()}')
        print(f'Seed files: {", ".join(sorted(p.name for p in (args.workdir / "seed").glob("*.csv")))}')
        print('Available steps: ' + ', '.join(STEPS))
        return 0
    if args.step == 'test':
        return subprocess.run([sys.executable, str(HERE / 'tests' / 'test_offline.py')],
                              cwd=args.workdir, check=False).returncode
    relative_path, prefix = STEPS[args.step]
    return subprocess.run([sys.executable, str(HERE / relative_path), *prefix, *forwarded],
                          cwd=args.workdir, check=False).returncode

if __name__ == '__main__':
    raise SystemExit(main())
