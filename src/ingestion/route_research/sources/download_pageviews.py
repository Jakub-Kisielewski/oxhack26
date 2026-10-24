#!/usr/bin/env python3
"""Download daily English Wikipedia pageviews per cause, a proxy for public attention.

Articles per cause come from seed/cause_articles.csv. The Wikimedia API counts
each exact title separately (views of a redirect are NOT added to its target),
so list old titles too when an article was renamed. Data exist from 2015-07-01.

Default window: 120 days before the earliest seed event to yesterday, enough for
the 90-day baseline used in event_context.py.

OUT: raw/pageviews/daily.csv  (cause, article, date, views)
"""
import argparse
import csv
import datetime as dt
import time
from pathlib import Path
from urllib.parse import quote

import requests

API = 'https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/{article}/daily/{start}/{end}'
USER_AGENT = 'OxfordHack2026-protest-predictor/0.1 (https://github.com/Jakub-Kisielewski/oxhack26)'
LOOKBACK_DAYS = 120


def read_articles(path):
    with open(path, encoding='utf-8-sig') as f:
        return [(r['cause'].strip(), r['article'].strip()) for r in csv.DictReader(f) if r.get('article', '').strip()]


def default_window(events_path, today):
    with open(events_path, encoding='utf-8-sig') as f:
        dates = [dt.date.fromisoformat(r['event_date']) for r in csv.DictReader(f) if r.get('event_date')]
    return min(dates) - dt.timedelta(days=LOOKBACK_DAYS), today - dt.timedelta(days=1)


def fetch_article(session, article, start, end):
    url = API.format(article=quote(article.replace(' ', '_'), safe=''),
                     start=start.strftime('%Y%m%d00'), end=end.strftime('%Y%m%d00'))
    r = session.get(url, timeout=60)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return [(dt.datetime.strptime(i['timestamp'], '%Y%m%d%H').date().isoformat(), i['views']) for i in r.json()['items']]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--articles', default='seed/cause_articles.csv')
    p.add_argument('--events', default='seed/events.csv')
    p.add_argument('--start', type=dt.date.fromisoformat)
    p.add_argument('--end', type=dt.date.fromisoformat)
    p.add_argument('--output', default='raw/pageviews/daily.csv')
    p.add_argument('--user-agent', default=USER_AGENT)
    a = p.parse_args()
    start, end = default_window(a.events, dt.date.today())
    start, end = a.start or start, a.end or end
    session = requests.Session()
    session.headers['User-Agent'] = a.user_agent
    rows, missing = [], []
    for cause, article in read_articles(a.articles):
        series = fetch_article(session, article, start, end)
        if series is None:
            missing.append(article)
            continue
        rows.extend({'cause': cause, 'article': article, 'date': d, 'views': v} for d, v in series)
        print(f'{cause}: {article} -> {len(series)} days')
        time.sleep(0.1)  # Wikimedia asks clients to stay well under 100 req/s
    if missing:
        print(f'WARNING: no data for {len(missing)} title(s), check spelling/renames: {", ".join(missing)}')
    out = Path(a.output); out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['cause', 'article', 'date', 'views']); w.writeheader(); w.writerows(rows)
    print(f'Saved {len(rows)} rows ({start}..{end}) to {out}')


if __name__ == '__main__':
    main()
