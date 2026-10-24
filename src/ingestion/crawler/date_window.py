from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

from ingestion.crawler.models import ProtestRecord

DATE_POST_RE = re.compile(r"/(20\d{2})/(\d{2})/(\d{2})/")

_HUMAN_DATE_RE = re.compile(
    r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(20\d{2})",
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


def parse_event_datetime_str(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None

    iso = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        pass

    match = _HUMAN_DATE_RE.search(text)
    if match:
        month_key = match.group(2).lower()[:3]
        month = _MONTH.get(month_key)
        if month:
            return datetime(
                int(match.group(3)),
                month,
                int(match.group(1)),
                tzinfo=timezone.utc,
            )

    dmy = re.search(
        r"(?i)(\d{1,2})\s+"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(20\d{2})",
        text,
    )
    if dmy:
        month_key = dmy.group(2).lower()[:3]
        month = _MONTH.get(month_key)
        if month:
            return datetime(
                int(dmy.group(3)),
                month,
                int(dmy.group(1)),
                tzinfo=timezone.utc,
            )
    return None


def event_date_from_url(url: str) -> Optional[datetime]:
    match = DATE_POST_RE.search(urlparse(url).path)
    if not match:
        return None
    year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
    try:
        return datetime(year, month, day, tzinfo=timezone.utc)
    except ValueError:
        return None


def record_event_datetime(record: ProtestRecord) -> Optional[datetime]:
    parsed = parse_event_datetime_str(record.event_start)
    if parsed:
        return parsed
    return event_date_from_url(record.url)


def window_bounds(
    *,
    now: Optional[datetime] = None,
    days_back: int,
    days_ahead: int = 0,
) -> tuple[datetime, datetime]:
    anchor = now or datetime.now(timezone.utc)
    start = anchor - timedelta(days=days_back)
    end = anchor + timedelta(days=days_ahead)
    return start, end


def is_within_event_window(
    event_dt: datetime,
    *,
    now: Optional[datetime] = None,
    days_back: int,
    days_ahead: int = 0,
) -> bool:
    anchor = now or datetime.now(timezone.utc)
    window_start, window_end = window_bounds(
        now=anchor, days_back=days_back, days_ahead=days_ahead
    )
    if event_dt.tzinfo is None:
        event_dt = event_dt.replace(tzinfo=timezone.utc)
    event_dt = event_dt.astimezone(timezone.utc)
    return window_start <= event_dt <= window_end


def filter_records_by_event_window(
    records: list[ProtestRecord],
    *,
    days_back: int,
    days_ahead: int = 0,
    now: Optional[datetime] = None,
) -> list[ProtestRecord]:
    if days_back <= 0 and days_ahead <= 0:
        return records
    kept: list[ProtestRecord] = []
    for record in records:
        event_dt = record_event_datetime(record)
        if event_dt is None:
            continue
        if is_within_event_window(
            event_dt, now=now, days_back=days_back, days_ahead=days_ahead
        ):
            kept.append(record)
    return kept
