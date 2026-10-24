#!/usr/bin/env python3
"""Download hourly central-London weather from Open-Meteo (free, no key).

Dates older than ARCHIVE_LAG_DAYS come from the Archive API (ERA5 reanalysis);
more recent and upcoming dates (up to 16 days ahead) come from the Forecast API.
Use archive rows for training and forecast rows only for prediction-time inputs.

By default covers every event_date in seed/events.csv (each day +/- 1 day);
--start/--end download a continuous range instead.

OUT: raw/weather/hourly.csv  (time in Europe/London local time, one row per hour,
     `source` = archive | forecast)
"""
import argparse
import csv
import datetime as dt
from pathlib import Path

import requests

LAT, LON = 51.5074, -0.1278  # Trafalgar Square; zones 1-2 fit in one ~10 km model cell
ARCHIVE_URL = 'https://archive-api.open-meteo.com/v1/archive'
FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'
ARCHIVE_LAG_DAYS = 6
FORECAST_MAX_AHEAD = 16
FORECAST_MAX_PAST = 92
HOURLY = ['temperature_2m', 'apparent_temperature', 'precipitation', 'rain',
          'wind_speed_10m', 'wind_gusts_10m', 'cloud_cover']


def event_dates(path):
    with open(path, encoding='utf-8-sig') as f:
        return sorted({dt.date.fromisoformat(r['event_date']) for r in csv.DictReader(f) if r.get('event_date')})


def date_ranges(days):
    """Merge each day +/- 1 into continuous ranges so we make few requests."""
    ranges = []
    for d in sorted(days):
        lo, hi = d - dt.timedelta(days=1), d + dt.timedelta(days=1)
        if ranges and lo <= ranges[-1][1] + dt.timedelta(days=1):
            ranges[-1][1] = max(ranges[-1][1], hi)
        else:
            ranges.append([lo, hi])
    return ranges


def split_by_source(start, end, today):
    """Yield (source, start, end) pieces of one range according to API coverage."""
    archive_end = today - dt.timedelta(days=ARCHIVE_LAG_DAYS)
    if start <= archive_end:
        yield 'archive', start, min(end, archive_end)
    f_start = max(start, archive_end + dt.timedelta(days=1), today - dt.timedelta(days=FORECAST_MAX_PAST))
    f_end = min(end, today + dt.timedelta(days=FORECAST_MAX_AHEAD))
    if f_start <= f_end:
        yield 'forecast', f_start, f_end


def fetch(session, source, start, end):
    r = session.get(ARCHIVE_URL if source == 'archive' else FORECAST_URL, timeout=60, params={
        'latitude': LAT, 'longitude': LON, 'start_date': start.isoformat(), 'end_date': end.isoformat(),
        'hourly': ','.join(HOURLY), 'timezone': 'Europe/London'})
    r.raise_for_status()
    return hourly_rows(r.json(), source)


def hourly_rows(payload, source):
    h = payload['hourly']
    return [{'time': t, 'source': source, **{v: h[v][i] for v in HOURLY}} for i, t in enumerate(h['time'])]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--events', default='seed/events.csv')
    p.add_argument('--start', type=dt.date.fromisoformat)
    p.add_argument('--end', type=dt.date.fromisoformat)
    p.add_argument('--output', default='raw/weather/hourly.csv')
    a = p.parse_args()
    today = dt.date.today()
    if a.start and a.end:
        ranges = [[a.start, a.end]]
    else:
        ranges = date_ranges(event_dates(a.events))
    session = requests.Session()
    rows = []
    for start, end in ranges:
        for source, s, e in split_by_source(start, end, today):
            got = fetch(session, source, s, e)
            print(f'{source} {s}..{e}: {len(got)} hours')
            rows.extend(got)
    skipped = [r for r in ranges if r[0] > today + dt.timedelta(days=FORECAST_MAX_AHEAD)]
    if skipped:
        print(f'WARNING: {len(skipped)} date range(s) more than {FORECAST_MAX_AHEAD} days ahead have no forecast yet')
    out = Path(a.output); out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['time', 'source', *HOURLY]); w.writeheader(); w.writerows(rows)
    print(f'Saved {len(rows)} hourly rows to {out}')


if __name__ == '__main__':
    main()
