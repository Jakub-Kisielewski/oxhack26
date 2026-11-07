"""Palestine Solidarity Campaign event listings."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from ingestion.crawler.client import HttpClient
from ingestion.crawler.date_window import (
    event_date_from_url,
    is_within_event_window,
    parse_event_datetime_str,
)
from ingestion.crawler.models import ProtestRecord
from ingestion.crawler.parse_utils import turnout_estimate_from_text
from ingestion.crawler.sources.base import ProtestSource
from ingestion.crawler.sources.organizers.filters import (
    EVENT_SLUG_SKIP,
    event_slug_pattern,
    is_london_protest_event,
)
from ingestion.crawler.sources.organizers.parse_event_page import (
    parse_event_datetime,
    parse_location_hint,
    parse_page_body,
    parse_page_title,
    parse_route_hint,
)

logger = logging.getLogger(__name__)

LISTING_URL = "https://palestinecampaign.org/events/"
SITE_URL = "https://palestinecampaign.org"
MAX_LIST_PAGES = 3
MAX_DETAIL_FETCHES = 15

_EVENT_SLUG_RE = event_slug_pattern("/events/")


class PscSource(ProtestSource):
    """PSC public event pages (London marches only, via shared organiser filters)."""

    platform_id = "psc"
    platform_name = "Palestine Solidarity Campaign"
    platform_url = SITE_URL

    def __init__(
        self,
        client: HttpClient | None = None,
        *,
        event_days_back: int | None = None,
        event_days_ahead: int = 0,
    ) -> None:
        super().__init__(client or HttpClient(min_interval_sec=0.45))
        self.event_days_back = event_days_back
        self.event_days_ahead = event_days_ahead
        self._site_host = "palestinecampaign.org"

    def fetch_records(self) -> list[ProtestRecord]:
        fetched_at = datetime.now(UTC).isoformat()
        html_pages = [self._fetch_listing(LISTING_URL)]
        html_pages.extend(self._paginate(LISTING_URL))

        candidate_urls = self._collect_candidate_urls(html_pages)
        candidate_urls = self._filter_urls_by_window(candidate_urls)

        records: list[ProtestRecord] = []
        for url in candidate_urls[:MAX_DETAIL_FETCHES]:
            record = self._fetch_detail(url, fetched_at)
            if record:
                records.append(record)
        return records

    def _fetch_listing(self, url: str) -> str:
        return self.client.get_text(url, referer=SITE_URL)

    def _paginate(self, seed: str) -> list[str]:
        pages: list[str] = []
        parsed = urlparse(seed)
        for page_no in range(2, MAX_LIST_PAGES + 1):
            qs = parse_qs(parsed.query, keep_blank_values=True)
            qs["pno"] = [str(page_no)]
            page_url = urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))
            try:
                html = self.client.get_text(page_url, referer=seed)
            except Exception as exc:
                logger.debug("paginate skip %s: %s", page_url, exc)
                continue
            if _EVENT_SLUG_RE.search(html):
                pages.append(html)
                break
        return pages

    def _collect_candidate_urls(self, html_pages: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        listing_paths = frozenset({"/events/", "/event/"})
        for raw in html_pages:
            for href in re.findall(r'href=["\']([^"\']+)["\']', raw, re.I):
                absolute = self._normalize_url(href)
                if not absolute or absolute in seen:
                    continue
                if not self._is_event_url(absolute, listing_paths):
                    continue
                seen.add(absolute)
                ordered.append(absolute)
        return ordered

    def _normalize_url(self, href: str) -> str:
        absolute = urljoin(SITE_URL, href.replace("\\u0026", "&").replace("&#038;", "&"))
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            return ""
        if parsed.netloc.lower().removeprefix("www.") != self._site_host:
            return ""
        path = parsed._replace(fragment="", query="").path.rstrip("/") + "/"
        return urlunparse(parsed._replace(path=path, query="", fragment=""))

    def _is_event_url(self, url: str, listing_paths: frozenset[str]) -> bool:
        path = urlparse(url).path.lower()
        normalized = path.rstrip("/") + "/"
        if normalized in listing_paths:
            return False
        match = _EVENT_SLUG_RE.search(path)
        if not match:
            return False
        return match.group(1).lower() not in EVENT_SLUG_SKIP

    def _filter_urls_by_window(self, urls: list[str]) -> list[str]:
        no_window = self.event_days_back is None or self.event_days_back <= 0
        if no_window and self.event_days_ahead <= 0:
            return urls
        filtered: list[str] = []
        for url in urls:
            url_date = event_date_from_url(url)
            if url_date is None:
                filtered.append(url)
                continue
            if is_within_event_window(
                url_date,
                days_back=self.event_days_back or 0,
                days_ahead=self.event_days_ahead,
            ):
                filtered.append(url)
        return filtered

    def _fetch_detail(self, url: str, fetched_at: str) -> ProtestRecord | None:
        try:
            html = self.client.get_text(url, referer=SITE_URL)
        except Exception as exc:
            logger.debug("detail fetch failed %s: %s", url, exc)
            return None

        title = parse_page_title(html)
        body = parse_page_body(html)
        if not title or not is_london_protest_event(title=title, body=body, url=url):
            return None

        event_start, _ = parse_event_datetime(html, body)
        if not self._event_in_window(event_start, url):
            return None

        source_id = urlparse(url).path.strip("/").replace("/", ":") or url
        return ProtestRecord(
            source=self.platform_id,
            source_id=source_id,
            title=title,
            url=url,
            fetched_at=fetched_at,
            event_start=event_start,
            form_up_location=parse_location_hint(html, body),
            route_text=parse_route_hint(body),
            turnout_estimate=turnout_estimate_from_text(body),
        )

    def _event_in_window(self, event_start: str | None, url: str) -> bool:
        if self.event_days_back is None and self.event_days_ahead <= 0:
            return True
        days_back = self.event_days_back or 0
        if days_back <= 0 and self.event_days_ahead <= 0:
            return True
        event_dt = parse_event_datetime_str(event_start) or event_date_from_url(url)
        if event_dt is None:
            return event_date_from_url(url) is not None
        return is_within_event_window(
            event_dt,
            days_back=days_back,
            days_ahead=self.event_days_ahead,
        )
