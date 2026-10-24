from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import unquote

from ingestion.crawler.parse_utils import clean_html_text, extract_paragraphs

_WEEKDAY_DATE_RE = re.compile(
    r"(?i)(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
    r"\s+(\d{1,2})\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"(?:\s+(20\d{2}))?"
)
_DAY_MONTH_RE = re.compile(
    r"(?i)(\d{1,2})\s+"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
    r"(?:\s+(20\d{2}))?"
)
_MONTH_NUM = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def parse_page_title(raw_html: str) -> str:
    og = re.search(
        r'property="og:title"\s+content="([^"]+)"', raw_html, re.I
    )
    if og:
        return _decode_entities(og.group(1))
    h1 = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", raw_html)
    if h1:
        return clean_html_text(h1.group(1))
    title = re.search(r"(?is)<title>(.*?)</title>", raw_html)
    if title:
        text = clean_html_text(title.group(1))
        text = re.sub(r"\s*[-|]\s*[^-|]+$", "", text).strip()
        return text
    return ""


def parse_page_body(raw_html: str) -> str:
    for pattern in (
        r'(?is)<div[^>]+class="[^"]*entry-content[^"]*"[^>]*>(.*?)</div>',
        r'(?is)<article[^>]*>(.*?)</article>',
        r'(?is)<main[^>]*>(.*?)</main>',
    ):
        match = re.search(pattern, raw_html)
        if match:
            paragraphs = extract_paragraphs(match.group(1), min_len=15)
            if paragraphs:
                return "\n".join(paragraphs)
    return "\n".join(extract_paragraphs(raw_html, min_len=40)[:12])


def parse_event_datetime(raw_html: str, body: str) -> tuple[Optional[str], Optional[str]]:
    for blob in (raw_html, body):
        iso = re.search(
            r'<time[^>]+datetime="(\d{4}-\d{2}-\d{2}T[^"]+)"', blob, re.I
        )
        if iso:
            start = iso.group(1)
            end_match = re.search(
                r'<time[^>]+datetime="(\d{4}-\d{2}-\d{2}T[^"]+)"',
                blob[iso.end() :],
                re.I,
            )
            end = end_match.group(1) if end_match else None
            return start, end

    for source in (raw_html, body):
        human = re.search(
            r"(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+20\d{2})"
            r"(?:[^0-9]{0,40}(\d{1,2}:\d{2}\s*(?:am|pm)?))?",
            source,
            re.I,
        )
        if human:
            return human.group(0).strip(), None

        weekday = _WEEKDAY_DATE_RE.search(source)
        if weekday:
            iso = _weekday_or_day_month_to_iso(weekday)
            if iso:
                return iso, None

        day_month = _DAY_MONTH_RE.search(source)
        if day_month and not day_month.group(3):
            iso = _weekday_or_day_month_to_iso(day_month)
            if iso:
                return iso, None

    ld = _json_ld_events(raw_html)
    if ld:
        return ld.get("startDate"), ld.get("endDate")

    return None, None


def parse_location_hint(raw_html: str, body: str) -> Optional[str]:
    for text in (body, clean_html_text(raw_html)):
        pin = re.search(r"📍\s*([^\n]{6,120})", text)
        if pin:
            return pin.group(1).strip()
        loc = re.search(
            r"(?im)(?:location|assemble|meeting point|gather(?:ing)?(?: at)?)\s*:?\s*([^\n.]{8,120})",
            text,
        )
        if loc:
            return loc.group(1).strip()
    ld = _json_ld_events(raw_html)
    if ld and isinstance(ld.get("location"), dict):
        name = ld["location"].get("name")
        if name:
            return str(name)
    return None


def parse_arrest_metadata(body: str) -> dict[str, object]:
    """Event-only signals for court / arrest actions (e.g. Defend Our Juries)."""
    if not body:
        return {}
    lowered = body.lower()
    if "arrest" not in lowered and "court" not in lowered:
        return {}

    out: dict[str, object] = {}
    arrest_match = re.search(
        r"(?i)(\d{1,4})\s+(?:people\s+)?arrested",
        body,
    )
    if arrest_match:
        out["arrests_reported"] = int(arrest_match.group(1))

    place = re.search(
        r"(?im)(?:at|outside|near)\s+(?:the\s+)?([^\n.]{8,80}(?:court|magistrates|westminster)[^\n.]*)",
        body,
    )
    if place:
        out["action_place"] = place.group(1).strip()
    return out


def parse_route_hint(body: str) -> Optional[str]:
    route = re.search(
        r"(?im)(?:route|march route|assembly point)\s*:?\s*([^\n]{10,240})",
        body,
    )
    if route:
        return route.group(1).strip()
    return None


def _json_ld_events(raw_html: str) -> Optional[dict[str, Any]]:
    for match in re.finditer(
        r'<script type="application/ld\+json">(.*?)</script>', raw_html, re.S
    ):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        event = _find_event_node(payload)
        if event:
            return event
    return None


def _find_event_node(payload: Any) -> Optional[dict[str, Any]]:
    if isinstance(payload, list):
        for item in payload:
            found = _find_event_node(item)
            if found:
                return found
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("@type") in ("Event", "SocialEvent", "PublicEvent"):
        return payload
    graph = payload.get("@graph")
    if isinstance(graph, list):
        return _find_event_node(graph)
    return None


def _decode_entities(value: str) -> str:
    return html.unescape(unquote(value.replace("&#039;", "'")))


def _weekday_or_day_month_to_iso(match: re.Match[str]) -> Optional[str]:
    day = int(match.group(1))
    month_key = match.group(2).lower()[:3]
    month_full = match.group(2).lower()
    month = _MONTH_NUM.get(month_full) or _MONTH_NUM.get(month_key)
    if not month:
        return None
    year_group = match.lastindex or 0
    year: Optional[int] = None
    if year_group >= 3 and match.group(3):
        year = int(match.group(3))
    if year is None:
        year = _infer_event_year(month, day)
    try:
        dt = datetime(year, month, day, tzinfo=timezone.utc)
    except ValueError:
        return None
    return dt.date().isoformat()


def _infer_event_year(month: int, day: int) -> int:
    now = datetime.now(timezone.utc)
    try:
        candidate = datetime(now.year, month, day, tzinfo=timezone.utc)
    except ValueError:
        return now.year
    if (now - candidate).days > 45:
        return now.year + 1
    return now.year
