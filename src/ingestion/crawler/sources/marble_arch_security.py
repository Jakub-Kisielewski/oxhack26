"""Marble Arch London BID security updates listing."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime

from ingestion.crawler.client import HttpClient
from ingestion.crawler.models import ProtestRecord
from ingestion.crawler.parse_utils import clean_html_text, turnout_estimate_from_text
from ingestion.crawler.sources.base import ProtestSource
from ingestion.crawler.sources.organizers.filters import (
    has_primary_protest_language,
    looks_like_non_protest_meeting,
)

logger = logging.getLogger(__name__)

LISTING_URL = "https://marble-arch.london/security-updates/"
BASE = "https://marble-arch.london"

_BLOCK_RE = re.compile(
    r'(?is)<div class="subsubtitle">\s*<div>\s*<h5>(?P<title>.*?)</h5>\s*</div>\s*</div>\s*'
    r'<div class="col-xs-12 col-sm-12 col-md-12 col-lg-12 textcontent">(?P<body>.*?)'
    r"(?=</div>\s*(?:<div class=\"subsubtitle\"|</div>\s*<div class=\"subtitle\"|$))",
)

_FUTURE_LI_RE = re.compile(r"(?is)<li>(?P<item>.*?)</li>")

_SKIP_TITLE = re.compile(
    r"(?i)\b("
    r"a40|westway|phone snatch|advice for all|closure|marathon|half marathon|"
    r"race for the|winter run|swim serpentine|resurfacing|cycleway|"
    r"state opening|world cup|traffic free|winter wonderland|construction|"
    r"christmas lights|overnight road|park lane overnight|elevated section|"
    r"q run|gosh race|royal parks half|landmarks half|"
    r"bst hyde park|k pop|random dance"
    r")\b",
)

_NON_PROTEST_EVENT = re.compile(
    r"(?i)\b("
    r"procession|parade|celebration|plaque unveiling|book launch|"
    r"rathayatra|hussaini association|ichthus christian|walk with jesus|"
    r"walk & talk|walk and talk|let women speak|let women sing|"
    r"filipino vigil|charlie kirk vigil|royal parks half|winter run|"
    r"swim serpentine|q run|race for the kids|craft fair|conference|"
    r"vyshyvanka march|peace & craft|peace and craft|"
    r"world cup|winter wonderland|christmas lights|"
    r"k pop|random dance|running event|family run|open water swim|"
    r"\bvigil\b|climate change event"
    r")\b",
)

_TITLE_PROTEST = re.compile(
    r"(?i)\b("
    r"protest|demonstration|rally|day of action|counter.?protest|"
    r"strike and rally|static demonstration|march against|march for|"
    r"national march|mass march|national demonstration|"
    r"protest march|boycott.*day of action"
    r")\b",
)

_BODY_PROTEST = re.compile(
    r"(?i)\b("
    r"this protest|protest and march|static demonstration|"
    r"demonstration at|national demonstration|counter.?protest"
    r")\b",
)

_ROUTE_RE = re.compile(
    r"(?im)(?:route (?:given|shown|from|to)|heading to|proceeding to|"
    r"march(?:ing)? from|starting from|form(?:ing)? up at|meeting (?:up )?at)"
    r"[^.]{0,20}?(.{15,320})",
)


def _marble_turnout(body: str) -> int | None:
    c_style = re.search(r"\bc\.?\s*([\d,]+)", body, re.I)
    if c_style:
        return int(c_style.group(1).replace(",", ""))
    return turnout_estimate_from_text(body)


def _is_protest_entry(title: str, body: str) -> bool:
    if _SKIP_TITLE.search(title):
        return False
    if _NON_PROTEST_EVENT.search(title):
        return False
    if re.search(r"(?i)\bmovement\b", title) and not re.search(
        r"(?i)\b(protest|demonstration|rally)\b", title
    ):
        return False

    combined = f"{title} {body}"
    if looks_like_non_protest_meeting(combined) and not _TITLE_PROTEST.search(title):
        return False

    if _TITLE_PROTEST.search(title):
        return not (_NON_PROTEST_EVENT.search(body) and not _BODY_PROTEST.search(body))

    if _BODY_PROTEST.search(body):
        return True

    lowered = combined.lower()
    if "metropolitan police have provided" in lowered and _BODY_PROTEST.search(body):
        return True
    if "metropolitan police have provided" in lowered and re.search(
        r"(?i)\b(protest|demonstration)\b", body
    ):
        return True

    return bool(
        has_primary_protest_language(title, body) and _TITLE_PROTEST.search(f"{title} {body[:200]}")
    )


def _parse_route(body: str) -> str | None:
    match = _ROUTE_RE.search(body)
    if match:
        return clean_html_text(match.group(1))
    via = re.search(r"(?im)(?:via|route given as)\s+(.{10,280})", body)
    if via:
        return clean_html_text(via.group(1))
    return None


def _source_id(title: str, body: str) -> str:
    digest = hashlib.sha256(f"{title}|{body[:120]}".encode()).hexdigest()[:12]
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48]
    return f"{slug}:{digest}"


class MarbleArchSecuritySource(ProtestSource):
    """Security update feed from Marble Arch London BID."""

    platform_id = "marble_arch_security"
    platform_name = "Marble Arch London (Security Updates)"
    platform_url = LISTING_URL

    def __init__(self, client: HttpClient | None = None, *, limit: int | None = None) -> None:
        super().__init__(client or HttpClient(min_interval_sec=0.4))
        self.limit = limit

    def fetch_records(self) -> list[ProtestRecord]:
        fetched_at = datetime.now(UTC).isoformat()
        html = self.client.get_text(LISTING_URL, referer=BASE)
        raw_entries = self._parse_future_items(html) + self._parse_update_blocks(html)

        records: list[ProtestRecord] = []
        seen: set[str] = set()
        for title, body in raw_entries:
            title = clean_html_text(title)
            body = clean_html_text(body)
            if not title or not _is_protest_entry(title, body):
                continue
            sid = _source_id(title, body)
            if sid in seen:
                continue
            seen.add(sid)

            route_text = _parse_route(body)
            records.append(
                ProtestRecord(
                    source=self.platform_id,
                    source_id=sid,
                    title=title,
                    url=LISTING_URL,
                    fetched_at=fetched_at,
                    event_start=title,
                    form_up_location=self._location_hint(title, body),
                    route_text=route_text,
                    turnout_estimate=_marble_turnout(body) if body else None,
                )
            )
            if self.limit and len(records) >= self.limit:
                break
        return records

    def _parse_future_items(self, html: str) -> list[tuple[str, str]]:
        section = html
        start = re.search(r"(?is)Future protests and events", html)
        if not start:
            return []
        section = html[start.start() :]
        end = re.search(r"(?is)<h5>\s*A40 Westway", section)
        if end:
            section = section[: end.start()]

        entries: list[tuple[str, str]] = []
        for match in _FUTURE_LI_RE.finditer(section):
            item = clean_html_text(match.group("item"))
            if not item:
                continue
            entries.append((item, ""))
        return entries

    def _parse_update_blocks(self, html: str) -> list[tuple[str, str]]:
        entries: list[tuple[str, str]] = []
        for match in _BLOCK_RE.finditer(html):
            title = match.group("title")
            if title.strip().lower() == "future protests and events":
                continue
            body_html = match.group("body")
            paragraphs = re.findall(r"(?is)<p[^>]*>(.*?)</p>", body_html)
            body = "\n".join(clean_html_text(p) for p in paragraphs if clean_html_text(p))
            entries.append((title, body))
        return entries

    def _location_hint(self, title: str, body: str) -> str | None:
        for text in (title, body):
            loc = re.search(
                r"(?i)(Marble Arch|Hyde Park|Park Lane|Oxford Street|Whitehall|"
                r"Downing Street|Speakers Corner|Reformers Tree|Westminster|"
                r"Hyde Park Corner|Edgware Road)",
                text,
            )
            if loc:
                return loc.group(1)
        return None
