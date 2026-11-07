"""Event date parsing and sliding-window filters for ingestion records."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from ingestion.crawler.models import ProtestRecord

DATE_POST_RE = re.compile(r"/(20\d{2})/(\d{2})/(\d{2})/")

_MONTH_NAME_RE = re.compile(
    r"(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(20\d{2})",
    re.I,
)

_MONTH = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def _parse_human_date(text: str) -> datetime | None:
    """Parse '14 June 2026' or '14 Jun 2026' as a UTC midnight datetime."""
    match = _MONTH_NAME_RE.search(text)
    if not match:
        return None
    day, month_name, year = match.groups()
    month = _MONTH[month_name.lower()[:3]]
    try:
        return datetime(int(year), month, int(day), tzinfo=UTC)
    except ValueError:
        return None


def parse_event_datetime_str(value: str | None) -> datetime | None:
    """Parse ISO or human-readable event datetimes to UTC."""
    if not value:
        return None
    text = value.strip()
    if not text:
        return None

    iso = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except ValueError:
        pass

    return _parse_human_date(text)


def event_date_from_url(url: str) -> datetime | None:
    """Infer event date from a /YYYY/MM/DD/ path segment when present."""
    match = DATE_POST_RE.search(urlparse(url).path)
    if not match:
        return None
    year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
    try:
        return datetime(year, month, day, tzinfo=UTC)
    except ValueError:
        return None


def record_event_datetime(record: ProtestRecord) -> datetime | None:
    """Best-effort event datetime for a record."""
    parsed = parse_event_datetime_str(record.event_start)
    if parsed:
        return parsed
    return event_date_from_url(record.url)


def window_bounds(
    *,
    now: datetime | None = None,
    days_back: int,
    days_ahead: int = 0,
) -> tuple[datetime, datetime]:
    """Inclusive UTC window anchored on ``now``."""
    anchor = now or datetime.now(UTC)
    start = anchor - timedelta(days=days_back)
    end = anchor + timedelta(days=days_ahead)
    return start, end


def is_within_event_window(
    event_dt: datetime,
    *,
    now: datetime | None = None,
    days_back: int,
    days_ahead: int = 0,
) -> bool:
    """Whether ``event_dt`` falls inside the configured window."""
    anchor = now or datetime.now(UTC)
    window_start, window_end = window_bounds(now=anchor, days_back=days_back, days_ahead=days_ahead)
    if event_dt.tzinfo is None:
        event_dt = event_dt.replace(tzinfo=UTC)
    event_dt = event_dt.astimezone(UTC)
    return window_start <= event_dt <= window_end


def filter_records_by_event_window(
    records: list[ProtestRecord],
    *,
    days_back: int,
    days_ahead: int = 0,
    now: datetime | None = None,
) -> list[ProtestRecord]:
    """Drop records outside the event window when bounds are positive."""
    if days_back <= 0 and days_ahead <= 0:
        return records
    kept: list[ProtestRecord] = []
    for record in records:
        event_dt = record_event_datetime(record)
        if event_dt is None:
            continue
        if is_within_event_window(event_dt, now=now, days_back=days_back, days_ahead=days_ahead):
            kept.append(record)
    return kept
