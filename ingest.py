#!/usr/bin/env python3
"""Run the whole ingestion process in dependency order: `python ingest.py`

Steps (see --list) download the zones 1-2 map, landmarks, police/TfL/ACLED
context, build the training routes and per-event features, crawl the live
protest sources, and create the DuckDB schema. Route data is written under
data/route_research/, crawler runs under data/runs/.

If a step fails, the steps that depend on it are skipped and the rest still
run; a summary is printed at the end. Slow downloads (boundary, osm, landmarks,
police) are skipped when their outputs already exist; use --refresh to redo them.

Examples:
    python ingest.py                      # everything
    python ingest.py --list               # show steps and what they need
    python ingest.py --only weather event-context
    python ingest.py --skip crawl acled
    python ingest.py --refresh osm        # re-download only the street network
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from src.ingestion.route_research import pipeline as route_pipeline

ROOT = Path(__file__).resolve().parent
WORKDIR = route_pipeline.DEFAULT_WORKSPACE
EVENTS = route_pipeline.HERE / 'seed' / 'events.csv'
POLICE_LAG_MONTHS = 2  # data.police.uk publishes about two months behind


@dataclass
class Step:
    name: str
    description: str
    needs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)  # relative to WORKDIR; existing outputs = cached
    skip_reason: Callable[[argparse.Namespace], Optional[str]] = lambda a: None
    args: Callable[[argparse.Namespace], list[str]] = lambda a: []
    kind: str = 'route'  # route | crawl | database


def police_months(_args) -> list[str]:
    """Event months the police API can serve (it keeps about three years)."""
    today = dt.date.today()
    latest = (today.replace(day=1) - dt.timedelta(days=31 * POLICE_LAG_MONTHS)).strftime('%Y-%m')
    earliest = f'{today.year - 3}-{today.month:02d}'
    with EVENTS.open(encoding='utf-8-sig') as f:
        months = {r['event_date'][:7] for r in csv.DictReader(f) if r.get('event_date')}
    return sorted(m for m in months if earliest <= m <= latest)


def acled_skip(args) -> Optional[str]:
    if args.acled_file or (os.environ.get('ACLED_EMAIL') and os.environ.get('ACLED_PASSWORD')):
        return None
    return 'set ACLED_EMAIL/ACLED_PASSWORD or pass --acled-file'


STEPS = [
    Step('boundary', 'Zones 1-2 polygon from TfL station zones',
         outputs=['raw/boundary/zones_1_2.geojson']),
    Step('osm', 'OSM walk network + main-road network clipped to the boundary', needs=['boundary'],
         outputs=['raw/osm/london_walk.graphml', 'raw/osm/london_main.graphml']),
    Step('landmarks', 'Targets, open spaces, shops, warehouses, diplomatic missions', needs=['boundary'],
         outputs=['raw/landmarks/targets.geoparquet', 'raw/landmarks/open_spaces.geoparquet',
                  'raw/landmarks/shops.geoparquet', 'raw/landmarks/warehouses.geoparquet']),
    Step('police', 'Public-order crimes for event months', outputs=['raw/police/police_public_order_context.csv'],
         skip_reason=lambda a: None if police_months(a) else 'no event months inside the police API window',
         args=lambda a: ['--months', *police_months(a)]),
    Step('tfl', 'Snapshot of current TfL road disruptions and tube status'),
    Step('acled', 'ACLED protest events for London', skip_reason=acled_skip,
         args=lambda a: ['--import-file', a.acled_file] if a.acled_file else ['--end', dt.date.today().isoformat()]),
    Step('seed-coords', 'coordinate_review.csv from the reviewed seed geocodes'),
    Step('normalize', 'Street segments, route labels and context tables', needs=['osm', 'seed-coords']),
    Step('export-parquet', 'Parquet/GeoParquet copies of the normalised tables', needs=['normalize']),
    Step('weather', 'Hourly Open-Meteo weather around each event date'),
    Step('pageviews', 'Daily Wikipedia views per cause'),
    Step('event-context', 'Per-event calendar, daylight, weather and salience features'),
    Step('crawl', 'Tier 1 crawlers: Met Police, OSAC, TfL, Marble Arch, organiser sites', kind='crawl'),
    Step('database', 'Create the DuckDB schema in data/protest.duckdb', kind='database'),
]
BY_NAME = {s.name: s for s in STEPS}


def run_step(step: Step, args) -> int:
    if step.kind == 'route':
        return route_pipeline.main(['--workdir', str(args.workdir), step.name, *step.args(args)])
    if step.kind == 'crawl':
        return subprocess.run([sys.executable, '-m', 'src.ingestion'], cwd=ROOT, check=False).returncode
    from src.database.db import get_connection, init_schema
    con = get_connection()
    try:
        init_schema(con)
        print('Tables:', ', '.join(t for (t,) in con.execute('SHOW TABLES').fetchall()))
    finally:
        con.close()
    return 0


def cached(step: Step, args) -> bool:
    return bool(step.outputs) and step.name not in args.refresh_steps and \
        all((args.workdir / o).exists() for o in step.outputs)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    names = [s.name for s in STEPS]
    p.add_argument('--only', nargs='+', choices=names, metavar='STEP', help='Run just these steps')
    p.add_argument('--skip', nargs='+', choices=names, default=[], metavar='STEP', help='Leave these steps out')
    p.add_argument('--refresh', nargs='*', choices=names, metavar='STEP',
                   help='Re-run cached downloads (all of them, or just the named steps)')
    p.add_argument('--acled-file', help='Manually downloaded ACLED CSV/XLSX instead of API credentials')
    p.add_argument('--workdir', type=Path, default=WORKDIR)
    p.add_argument('--list', action='store_true', help='Show the steps and exit')
    args = p.parse_args(argv)
    args.refresh_steps = set(names) if args.refresh == [] else set(args.refresh or [])

    if args.list:
        for s in STEPS:
            extra = f"  (needs {', '.join(s.needs)})" if s.needs else ''
            print(f'{s.name:<15} {s.description}{extra}')
        return 0

    selected = [s for s in STEPS if (not args.only or s.name in args.only) and s.name not in args.skip]
    status: dict[str, str] = {}
    timings: dict[str, float] = {}
    for step in selected:
        blocked = [n for n in step.needs if status.get(n, 'ok').startswith(('FAILED', 'skipped (needs'))]
        reason = step.skip_reason(args)
        if blocked:
            status[step.name] = f"skipped (needs {', '.join(blocked)})"
        elif reason:
            status[step.name] = f'skipped ({reason})'
        elif cached(step, args):
            status[step.name] = 'cached (use --refresh to redo)'
        else:
            print(f'\n=== {step.name}: {step.description} ===', flush=True)
            start = time.monotonic()
            try:
                code = run_step(step, args)
            except Exception as exc:  # keep going so one broken source doesn't stop the rest
                print(f'{step.name} raised {exc!r}', file=sys.stderr)
                code = 1
            timings[step.name] = time.monotonic() - start
            status[step.name] = 'ok' if code == 0 else f'FAILED (exit {code})'

    print('\n=== Ingestion summary ===')
    for step in selected:
        t = f' {timings[step.name]:.0f}s' if step.name in timings else ''
        print(f'{step.name:<15} {status[step.name]}{t}')
    return 1 if any(v.startswith('FAILED') for v in status.values()) else 0


if __name__ == '__main__':
    raise SystemExit(main())
