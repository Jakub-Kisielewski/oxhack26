#!/usr/bin/env python3
"""Per-event context features: calendar, daylight, weather and media salience.

Input:
 --events     seed/events.csv (event_date, start_time; `cause` if present, otherwise
              derived from motivation/organiser/event_name with CAUSE_KEYWORDS)
 --weather    raw/weather/hourly.csv (download_weather.py)
 --pageviews  raw/pageviews/daily.csv (download_pageviews.py)
 --school-holidays seed/school_holidays.csv (optional, hand-filled)
 UK bank holidays from gov.uk, cached to raw/calendar/bank_holidays.json
Output: normalised/event_context.csv, one row per event_id.

Leakage: salience uses only pageviews from days strictly BEFORE the event.
Weather is the observed (archive) value when available; at prediction time the
same columns are filled from the forecast rows instead.
"""
import argparse
import csv
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from astral import LocationInfo
from astral.sun import sun
from hijridate import Gregorian

LONDON = LocationInfo('London', 'England', 'Europe/London', 51.5074, -0.1278)
TZ = ZoneInfo('Europe/London')
BANK_HOLIDAYS_URL = 'https://www.gov.uk/bank-holidays.json'
DEFAULT_START = dt.time(12, 0)  # Typical Saturday march assembly time
WEATHER_WINDOW_H = 4
# First match wins, so counter-protests are classed before the causes they oppose.
CAUSE_KEYWORDS = [
    ('anti_racism', ['stand up to racism', 'counter-protest', 'counter-march', 'against the far', 'anti-racism', 'together alliance']),
    ('palestine', ['gaza', 'palestin', 'nakba', 'al quds', 'israel', 'rafah']),
    ('iran', ['iran']),
    ('anti_trump', ['trump']),
    ('far_right', ['unite the kingdom', 'uniting the kingdom', 'anti-immigration', 'tommy robinson']),
    ('climate_nature', ['nature', 'climate']),
    ('trade_union', ['cost of living', 'trades union', 'tuc']),
    ('digital_id', ['digital id']),
    ('animal_rights', ['animal']),
    ('sudan', ['sudan']),
    ('ethiopia', ['amhara', 'ethiopia']),
    ('armenia', ['armenian']),
    ('kashmir', ['kashmir', 'awami']),
    ('ukraine', ['ukrain', 'vyshyvanka']),
    ('trans_rights', ['trans+', 'trans pride', 'transgender']),
    ('lgbtq', ['pride', 'lesbian']),
    ('education', ['student', 'universit', 'academ']),
]
FIELDS = ['event_id', 'event_date', 'cause', 'cause_derived', 'start_time', 'start_time_imputed',
          'day_of_week', 'is_weekend', 'is_bank_holiday', 'is_school_holiday', 'is_ramadan',
          'sunrise', 'sunset', 'daylight_after_start_h',
          'weather_source', 'precip_mm_4h', 'temp_mean_c', 'apparent_temp_mean_c', 'wind_gust_max_kmh', 'cloud_mean_pct',
          'views_7d', 'views_30d', 'views_baseline_90d_mean', 'salience_spike_ratio']


def read_csv(path):
    with open(path, encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def parse_start(value):
    try:
        return dt.time.fromisoformat(value.strip()[:5]), False
    except (ValueError, AttributeError):
        return DEFAULT_START, True


def derive_cause(event):
    text = ' '.join(event.get(k) or '' for k in ('motivation', 'organiser', 'event_name')).lower()
    return next((cause for cause, words in CAUSE_KEYWORDS if any(w in text for w in words)), '')


def is_ramadan(day):
    return Gregorian(day.year, day.month, day.day).to_hijri().month == 9


def load_bank_holidays(cache, offline):
    cache = Path(cache)
    if not cache.exists():
        if offline:
            print(f'WARNING: {cache} missing and --offline set; is_bank_holiday left empty')
            return None
        try:
            r = requests.get(BANK_HOLIDAYS_URL, timeout=30)
            r.raise_for_status()
        except requests.RequestException as exc:
            print(f'WARNING: could not download bank holidays ({exc.__class__.__name__}); is_bank_holiday left empty')
            return None
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(r.text, encoding='utf-8')
    data = json.loads(cache.read_text(encoding='utf-8'))
    return {dt.date.fromisoformat(e['date']) for e in data['england-and-wales']['events']}


def load_school_holidays(path):
    if not Path(path).exists():
        return None
    ranges = [(dt.date.fromisoformat(r['start_date']), dt.date.fromisoformat(r['end_date']))
              for r in read_csv(path) if r.get('start_date') and r.get('end_date')]
    return ranges or None


def daylight(day, start):
    s = sun(LONDON.observer, date=day, tzinfo=TZ)
    start_dt = dt.datetime.combine(day, start, tzinfo=TZ)
    after = max(0.0, (s['sunset'] - start_dt).total_seconds() / 3600)
    return s['sunrise'].strftime('%H:%M'), s['sunset'].strftime('%H:%M'), round(after, 2)


def index_weather(rows):
    """time -> row, preferring observed archive values over forecasts."""
    out = {}
    for r in rows:
        t = dt.datetime.fromisoformat(r['time'])
        if t not in out or r['source'] == 'archive':
            out[t] = r
    return out


def weather_window(weather, day, start):
    t0 = dt.datetime.combine(day, start).replace(minute=0)
    hours = [weather[t] for t in (t0 + dt.timedelta(hours=i) for i in range(WEATHER_WINDOW_H)) if t in weather]
    if not hours:
        return {}
    def vals(k): return [float(h[k]) for h in hours if h.get(k) not in (None, '')]
    def mean(k): v = vals(k); return round(sum(v) / len(v), 2) if v else None
    return {'weather_source': '|'.join(sorted({h['source'] for h in hours})),
            'precip_mm_4h': round(sum(vals('precipitation')), 2),
            'temp_mean_c': mean('temperature_2m'),
            'apparent_temp_mean_c': mean('apparent_temperature'),
            'wind_gust_max_kmh': max(vals('wind_gusts_10m'), default=None),
            'cloud_mean_pct': mean('cloud_cover')}


def index_pageviews(rows):
    """cause -> date -> total views over all of that cause's articles."""
    out = defaultdict(lambda: defaultdict(int))
    for r in rows:
        out[r['cause']][dt.date.fromisoformat(r['date'])] += int(r['views'])
    return out


def salience(series, day):
    """Views strictly before `day`; None when the window has no data at all."""
    def window(n): return [series[d] for d in (day - dt.timedelta(days=i) for i in range(1, n + 1)) if d in series]
    w7, w30, w90 = window(7), window(30), window(90)
    if not w7 or not w90:
        return {}
    base = sum(w90) / len(w90)
    return {'views_7d': sum(w7), 'views_30d': sum(w30), 'views_baseline_90d_mean': round(base, 1),
            'salience_spike_ratio': round((sum(w7) / len(w7)) / base, 3) if base else None}


def build_row(event, cause_column, bank_holidays, school_holidays, weather, pageviews):
    day = dt.date.fromisoformat(event['event_date'])
    start, imputed = parse_start(event.get('start_time') or event.get('start_or_assembly_time'))
    sunrise, sunset, after = daylight(day, start)
    cause = (event.get(cause_column) or '').strip()
    derived = not cause
    if derived:
        cause = derive_cause(event)
    row = {'event_id': event['event_id'], 'event_date': day.isoformat(), 'cause': cause, 'cause_derived': derived,
           'start_time': start.strftime('%H:%M'), 'start_time_imputed': imputed,
           'day_of_week': day.strftime('%A'), 'is_weekend': day.weekday() >= 5,
           'is_bank_holiday': None if bank_holidays is None else day in bank_holidays,
           'is_school_holiday': None if school_holidays is None else any(a <= day <= b for a, b in school_holidays),
           'is_ramadan': is_ramadan(day), 'sunrise': sunrise, 'sunset': sunset, 'daylight_after_start_h': after}
    row.update(weather_window(weather, day, start))
    if cause and cause in pageviews:
        row.update(salience(pageviews[cause], day))
    return row


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--events', default='seed/events.csv')
    p.add_argument('--weather', default='raw/weather/hourly.csv')
    p.add_argument('--pageviews', default='raw/pageviews/daily.csv')
    p.add_argument('--school-holidays', default='seed/school_holidays.csv')
    p.add_argument('--bank-holidays-cache', default='raw/calendar/bank_holidays.json')
    p.add_argument('--cause-column', default='cause', help='Column in events.csv naming the cause (keys of cause_articles.csv)')
    p.add_argument('--offline', action='store_true', help='Do not download bank holidays')
    p.add_argument('--output', default='normalised/event_context.csv')
    a = p.parse_args()
    events = read_csv(a.events)
    if events and a.cause_column not in events[0]:
        print(f'No `{a.cause_column}` column in events.csv; deriving cause from motivation/organiser/event_name')
    weather = index_weather(read_csv(a.weather)) if Path(a.weather).exists() else {}
    if not weather: print(f'WARNING: {a.weather} missing; weather columns left empty')
    pageviews = index_pageviews(read_csv(a.pageviews)) if Path(a.pageviews).exists() else {}
    if not pageviews: print(f'WARNING: {a.pageviews} missing; salience columns left empty')
    bank = load_bank_holidays(a.bank_holidays_cache, a.offline)
    school = load_school_holidays(a.school_holidays)
    rows = [build_row(e, a.cause_column, bank, school, weather, pageviews) for e in events if e.get('event_date')]
    out = Path(a.output); out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS); w.writeheader(); w.writerows(rows)
    print(f'Saved context for {len(rows)} events to {out}')


if __name__ == '__main__':
    main()
