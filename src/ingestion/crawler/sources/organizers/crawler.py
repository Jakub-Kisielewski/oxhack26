from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from ingestion.crawler.client import HttpClient
from ingestion.crawler.date_window import (
    event_date_from_url,
    is_within_event_window,
    parse_event_datetime_str,
)
from ingestion.crawler.models import ProtestRecord
from ingestion.crawler.parse_utils import parse_route_streets
from ingestion.crawler.sources.organizers.filters import (
    ACTIONNETWORK_EVENT_RE,
    AN_EVENT_QUERY_RE,
    DATE_POST_RE,
    EVENT_SLUG_SKIP,
    event_slug_pattern,
    is_london_protest_event,
)
from ingestion.crawler.sources.organizers.parse_event_page import (
    parse_arrest_metadata,
    parse_event_datetime,
    parse_location_hint,
    parse_page_body,
    parse_page_title,
    parse_route_hint,
)
from ingestion.crawler.sources.organizers.sites import OrganizerSiteConfig

_LISTING_SLUG_SKIP = frozenset(
    {
        "/",
        "/press-releases/",
        "/press/",
        "/international-press/",
        "/local-press/",
        "/legal-press/",
        "/lift-the-ban/",
        "/events/",
        "/about/",
        "/contact/",
        "/donate/",
    }
)


def _strip_www(host: str) -> str:
    return host.lower().removeprefix("www.")


class OrganizerSiteCrawler:
    def __init__(
        self,
        config: OrganizerSiteConfig,
        client: Optional[HttpClient] = None,
        *,
        event_days_back: Optional[int] = None,
        event_days_ahead: int = 0,
    ):
        self.config = config
        self.client = client or HttpClient(min_interval_sec=0.45)
        self._site_host = _strip_www(urlparse(config.platform_url).netloc)
        self.event_days_back = event_days_back
        self.event_days_ahead = event_days_ahead
        self._event_slug_re = event_slug_pattern(config.event_slug_prefix)
        listing = config.event_slug_prefix.rstrip("/") + "/"
        self._event_listing_paths = frozenset({listing, "/events/", "/event/"})

    def fetch_records(self) -> list[ProtestRecord]:
        fetched_at = datetime.now(timezone.utc).isoformat()
        self._warm_session()
        listing_html: list[str] = []
        for seed in self.config.seed_urls:
            try:
                listing_html.append(self.client.get_text(seed, referer=self.config.platform_url))
            except Exception:
                continue
            listing_html.extend(self._paginate(seed))

        candidate_urls = self._collect_candidate_urls(listing_html)
        candidate_urls = self._filter_urls_by_window(candidate_urls)
        records: list[ProtestRecord] = []
        for url in candidate_urls[: self.config.max_detail_fetches]:
            record = self._fetch_detail(url, fetched_at)
            if record:
                records.append(record)
        return records

    def _warm_session(self) -> None:
        try:
            self.client.get_text(
                self.config.platform_url.rstrip("/") + "/",
                referer=None,
            )
        except Exception:
            pass

    def _paginate(self, seed: str) -> list[str]:
        if self.config.pagination == "none":
            return []

        pages: list[str] = []
        parsed = urlparse(seed)
        base_path = parsed.path or "/"
        for page_no in range(2, self.config.max_list_pages + 1):
            page_urls: list[str] = []
            if self.config.pagination == "query_pno":
                qs = parse_qs(parsed.query, keep_blank_values=True)
                qs["pno"] = [str(page_no)]
                page_urls.append(
                    urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))
                )
            elif self.config.pagination == "path_page":
                page_urls.append(
                    urljoin(seed, f"{base_path.rstrip('/')}/page/{page_no}/")
                )

            for page_url in page_urls:
                try:
                    html = self.client.get_text(page_url, referer=seed)
                except Exception:
                    continue
                if (
                    self._event_slug_re.search(html)
                    or (self.config.include_date_posts and DATE_POST_RE.search(html))
                    or self._html_has_slug_posts(html)
                    or ACTIONNETWORK_EVENT_RE.search(html)
                    or AN_EVENT_QUERY_RE.search(html)
                ):
                    pages.append(html)
                    break
        return pages

    def _collect_candidate_urls(self, html_pages: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for raw in html_pages:
            hrefs = re.findall(r'href="([^"]+)"', raw, re.I)
            hrefs.extend(re.findall(r"href='([^']+)'", raw, re.I))
            for fragment in re.findall(
                r"(https?://[^\s\"'<>]+actionnetwork\.org/(?:events|ticketed_events)/[a-z0-9_-]+/?)",
                raw,
                re.I,
            ):
                hrefs.append(fragment)
            for match in AN_EVENT_QUERY_RE.finditer(raw):
                hrefs.append(
                    urljoin(
                        self.config.platform_url,
                        f"/events/?an_event={match.group(1)}",
                    )
                )

            for href in hrefs:
                absolute = self._normalize_url(href)
                if not absolute or absolute in seen:
                    continue
                if not self._is_candidate_url(absolute):
                    continue
                seen.add(absolute)
                ordered.append(absolute)
        return ordered

    def _filter_urls_by_window(self, urls: list[str]) -> list[str]:
        if self.event_days_back is None or self.event_days_back <= 0:
            if self.event_days_ahead <= 0:
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

    def _normalize_url(self, href: str) -> str:
        href = href.replace("\\u0026", "&").replace("&#038;", "&")
        absolute = urljoin(self.config.platform_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            return ""

        query = ""
        if AN_EVENT_QUERY_RE.search(parsed.query):
            qs = parse_qs(parsed.query, keep_blank_values=True)
            an_event = qs.get("an_event", [None])[0]
            if an_event:
                query = urlencode({"an_event": an_event})

        clean = parsed._replace(fragment="", query=query)
        path = clean.path.rstrip("/") + "/"
        return urlunparse(clean._replace(path=path))

    def _host_matches(self, host: str) -> bool:
        host = _strip_www(host)
        return host == self._site_host or host.endswith(f".{self._site_host}")

    def _is_candidate_url(self, url: str) -> bool:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        path = parsed.path.lower()

        if self._host_matches(host):
            if AN_EVENT_QUERY_RE.search(url):
                return True
            normalized = path.rstrip("/") + "/"
            if self._event_slug_re.search(path) and normalized not in self._event_listing_paths:
                slug = self._event_slug_re.search(path)
                if slug and slug.group(1).lower() not in EVENT_SLUG_SKIP:
                    return True
            if self.config.include_date_posts and DATE_POST_RE.search(path):
                if any(
                    skip in path
                    for skip in ("/category/", "/tag/", "/author/", "/page/")
                ):
                    return False
                return True
            if self._is_slug_post_url(path):
                return True
            if self.config.include_listing_slugs and self._is_listing_article_slug(path):
                return True
            return False

        if self.config.include_actionnetwork and "actionnetwork.org" in host:
            if ACTIONNETWORK_EVENT_RE.search(url):
                if "/fundraising/" in path or "/forms/" in path:
                    return False
                return True
        for extra in self.config.extra_domains:
            if extra in host and self._event_slug_re.search(path):
                return True
        return False

    def _html_has_slug_posts(self, html: str) -> bool:
        if not self.config.slug_post_prefixes:
            return False
        for prefix in self.config.slug_post_prefixes:
            if prefix.rstrip("/") + "/" in html.lower():
                return True
        return False

    def _is_slug_post_url(self, path: str) -> bool:
        lowered = path.lower()
        if any(skip in lowered for skip in ("/category/", "/tag/", "/author/", "/page/")):
            return False
        for prefix in self.config.slug_post_prefixes:
            if not lowered.startswith(prefix):
                continue
            slug = lowered[len(prefix) :].strip("/")
            if len(slug) >= 5 and slug not in ("press-releases", "media"):
                return True
        return False

    def _is_listing_article_slug(self, path: str) -> bool:
        lowered = path.lower().rstrip("/") + "/"
        if lowered in _LISTING_SLUG_SKIP:
            return False
        if lowered.count("/") != 2:
            return False
        slug = lowered.strip("/")
        return len(slug) >= 20

    def _fetch_detail(self, url: str, fetched_at: str) -> Optional[ProtestRecord]:
        try:
            html = self.client.get_text(url, referer=self.config.platform_url)
        except Exception:
            return None

        title = parse_page_title(html)
        body = parse_page_body(html)
        if not title:
            return None
        if not is_london_protest_event(title=title, body=body, url=url):
            return None

        event_start, event_end = parse_event_datetime(html, body)
        if not self._event_in_window(event_start, url):
            return None

        location = parse_location_hint(html, body)
        route_text = parse_route_hint(body)
        source_id = urlparse(url).path.strip("/").replace("/", ":") or url
        parsed_query = parse_qs(urlparse(url).query)
        if parsed_query.get("an_event"):
            source_id = f"an_event:{parsed_query['an_event'][0]}"

        extra: dict[str, object] = {
            "organizer": self.config.platform_name,
            "organizer_url": self.config.platform_url,
        }
        arrest_meta = parse_arrest_metadata(body)
        if arrest_meta:
            extra.update(arrest_meta)

        return ProtestRecord(
            source=self.config.platform_id,
            source_id=source_id,
            title=title,
            url=url,
            fetched_at=fetched_at,
            event_start=event_start,
            event_end=event_end,
            form_up_location=location,
            route_text=route_text,
            route_streets=parse_route_streets(route_text or ""),
            location_label=location or "London",
            raw_excerpt=body[:1200],
            extra=extra,
        )

    def _event_in_window(self, event_start: Optional[str], url: str) -> bool:
        if self.event_days_back is None and self.event_days_ahead <= 0:
            return True
        days_back = self.event_days_back or 0
        if days_back <= 0 and self.event_days_ahead <= 0:
            return True
        event_dt = parse_event_datetime_str(event_start) or event_date_from_url(url)
        if event_dt is None:
            # No parseable date: keep only when URL carries a dated post path.
            return event_date_from_url(url) is not None
        return is_within_event_window(
            event_dt,
            days_back=days_back,
            days_ahead=self.event_days_ahead,
        )
