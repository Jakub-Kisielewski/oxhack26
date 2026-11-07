"""Met Police Newsroom conditions notices for central London protests."""

from __future__ import annotations

import html as html_lib
import logging
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

import requests

from ingestion.crawler.client import HttpClient
from ingestion.crawler.constants import (
    DEFAULT_MET_LIMIT,
    MAX_ARCHIVE_PAGES,
    MIN_DIV_CHUNK_CHARS,
    MIN_PARAGRAPH_CHARS,
    SUPPRESSION_SCAN_CHARS,
)
from ingestion.crawler.models import ProtestRecord
from ingestion.crawler.parse_utils import (
    clean_html_text,
    extract_paragraphs,
    first_match_group,
    iter_json_ld,
    turnout_estimate_from_text,
)
from ingestion.crawler.sources.base import ProtestSource

logger = logging.getLogger(__name__)

BASE = "https://news.met.police.uk"
CENTRAL_LONDON_TAG_URL = f"{BASE}/latest_news/tag/central-london"

PROTEST_KEYWORDS = (
    "condition",
    "protest",
    "march",
    "demonstration",
    "procession",
    "rally",
    "assembly",
    "public order",
    "quds",
    "coalition",
    "defend our juries",
    "palestine",
    "national march",
)

SUPPRESSED_EVENT_PATTERNS = (
    r"consented to (?:the )?(?:(?:metropolitan|met)(?: police)? )?banning",
    r"\bbanning (?:\w+\s+){0,4}march",
    r"\bhas banned\b",
    r"\bprotest ban\b",
    r"banning (?:sunday'?s? )?(?:\w+ )*march",
)


class MetPoliceSource(ProtestSource):
    """Met Police Newsroom protest conditions articles."""

    platform_id = "met_police"
    platform_name = "Met Police Newsroom"
    platform_url = BASE

    def __init__(
        self,
        client: HttpClient | None = None,
        *,
        limit: int = DEFAULT_MET_LIMIT,
    ) -> None:
        super().__init__(client)
        self.limit = limit

    def list_articles(
        self, limit: int | None = None, max_pages: int = MAX_ARCHIVE_PAGES
    ) -> list[dict[str, Any]]:
        articles: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        page_html = self.client.get_text(CENTRAL_LONDON_TAG_URL)
        self._collect_candidates(page_html, articles, seen_urls, limit)

        next_path = self._extract_next_page_path(page_html)
        pages_fetched = 0
        while next_path and (limit is None or len(articles) < limit) and pages_fetched < max_pages:
            page_html = self._fetch_archive_page(next_path)
            self._collect_candidates(page_html, articles, seen_urls, limit)
            next_path = self._extract_next_page_path(page_html)
            pages_fetched += 1

        if limit is not None:
            return articles[:limit]
        return articles

    def fetch_records(self) -> list[ProtestRecord]:
        fetched_at = datetime.now(UTC).isoformat()
        records: list[ProtestRecord] = []
        for article in self.list_articles(limit=self.limit):
            try:
                html = self.client.get_text(article["url"], referer=CENTRAL_LONDON_TAG_URL)
                records.extend(self._parse_article(html, article, fetched_at))
            except requests.RequestException as exc:
                logger.warning("skipping article %s: %s", article["url"], exc)
        return records

    def _collect_candidates(
        self,
        page_html: str,
        articles: list[dict[str, Any]],
        seen_urls: set[str],
        limit: int | None,
    ) -> None:
        for stub in self._extract_story_stubs(page_html):
            if stub["url"] in seen_urls:
                continue
            seen_urls.add(stub["url"])
            headline = stub.get("headline", "")
            description = stub.get("description", "")
            if not self._is_protest_related(headline, description):
                continue
            if self._is_suppressed_event(headline, description):
                continue
            articles.append(stub)
            if limit is not None and len(articles) >= limit:
                return

    def _extract_story_stubs(self, page_html: str) -> list[dict[str, Any]]:
        stubs: list[dict[str, Any]] = []
        for payload in iter_json_ld(page_html, schema_type="CollectionPage"):
            for item in payload.get("mainEntity", []):
                if item.get("@type") != "NewsArticle":
                    continue
                stubs.append(
                    {
                        "headline": item.get("headline", ""),
                        "date_published": item.get("datePublished"),
                        "url": self._canonical_url(item),
                        "description": item.get("description", ""),
                    }
                )

        for match in re.finditer(
            r'(?is)<li class="[^"]*"[^>]*aria-labelledby="storyLabel\d+News">(.*?)</li>',
            page_html,
        ):
            block = match.group(1)
            heading = re.search(
                r'(?is)<h2[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                block,
            )
            if not heading:
                continue
            teaser = re.search(r"(?is)<p[^>]*>(.*?)</p>", block)
            stubs.append(
                {
                    "headline": clean_html_text(heading.group(2)),
                    "date_published": None,
                    "url": self._normalize_article_url(heading.group(1)),
                    "description": clean_html_text(teaser.group(1)) if teaser else "",
                }
            )
        return stubs

    def _fetch_archive_page(self, next_path: str) -> str:
        url = urljoin(BASE, html_lib.unescape(next_path))
        if "infinite-pagination" not in url:
            url = f"{url}&infinite-pagination" if "?" in url else f"{url}?infinite-pagination"
        return self.client.get_text(
            url,
            referer=CENTRAL_LONDON_TAG_URL,
            extra_headers={"X-Requested-With": "XMLHttpRequest"},
        )

    def _extract_next_page_path(self, page_html: str) -> str | None:
        match = re.search(
            r'infinite-pagination__item__next-button[^>]*href="([^"]+)"',
            page_html,
            re.I,
        )
        if not match:
            return None
        return html_lib.unescape(match.group(1))

    def _is_protest_related(self, headline: str, description: str) -> bool:
        blob = f"{headline} {description}".lower()
        return any(keyword in blob for keyword in PROTEST_KEYWORDS)

    def _is_suppressed_event(self, headline: str, description: str, body: str = "") -> bool:
        blob = f"{headline} {description} {body[:SUPPRESSION_SCAN_CHARS]}".lower()
        return any(re.search(pattern, blob, re.I) for pattern in SUPPRESSED_EVENT_PATTERNS)

    def _normalize_article_url(self, url: str) -> str:
        if url.startswith("http"):
            return url
        return urljoin(BASE, url)

    def _canonical_url(self, item: dict[str, Any]) -> str:
        for candidate in (item.get("url"), item.get("mainEntityOfPage")):
            if not candidate:
                continue
            if "news.met.police.uk" in candidate:
                return candidate
            slug_match = re.search(r"/(?:news|pressreleases)/([^/?#]+)", candidate)
            if slug_match:
                return f"{BASE}/news/{slug_match.group(1)}"
        return self._normalize_article_url(item.get("url") or CENTRAL_LONDON_TAG_URL)

    def _parse_article(
        self, html: str, article: dict[str, Any], fetched_at: str
    ) -> list[ProtestRecord]:
        body = self._extract_body_text(html)
        title = article["headline"]
        description = article.get("description", "")
        if self._is_suppressed_event(title, description, body):
            return []
        article_id_match = re.search(r"-(\d+)\s*$", article["url"])
        source_id = article_id_match.group(1) if article_id_match else article["url"]

        route_text = self._extract_section_12_route(body)
        form_up = self._extract_form_up(body)
        event_start = self._extract_event_start(body, title)
        turnout = None
        match = re.search(
            r"(?:anticipate|expect|expected|between)\s+(.{0,80}?(?:people|participants).{0,20})",
            body,
            re.I,
        )
        if match:
            turnout = turnout_estimate_from_text(match.group(1))

        record = ProtestRecord(
            source=self.platform_id,
            source_id=source_id,
            title=title,
            url=article["url"],
            fetched_at=fetched_at,
            event_start=event_start,
            form_up_location=form_up,
            route_text=route_text,
            turnout_estimate=turnout,
        )
        return [record]

    def _extract_body_text(self, html: str) -> str:
        for payload in iter_json_ld(html, schema_type="NewsArticle"):
            if payload.get("articleBody"):
                return clean_html_text(str(payload["articleBody"]))
        paragraphs = extract_paragraphs(html, min_len=MIN_PARAGRAPH_CHARS)
        div_chunks = [
            clean_html_text(chunk) for chunk in re.findall(r"(?is)<div[^>]*>(.*?)</div>", html)
        ]
        div_chunks = [chunk for chunk in div_chunks if len(chunk) > MIN_DIV_CHUNK_CHARS]
        return "\n".join([*paragraphs, *div_chunks])

    def _extract_section_12_route(self, text: str) -> str | None:
        section = re.search(
            r"Section 12\(3\) Public Order Act 1986(.*?)(?:Section 14|Details of conditions|$)",
            text,
            re.I | re.S,
        )
        haystack = section.group(1) if section else text
        patterns = [
            r"route shown on the map below, which is:\s*(.+?)(?:\.|They must begin)",
            r"route specified on the map below, namely\s*(.+?)(?:\.|Anyone participating)",
            r"must not deviate from the route[^,]*,\s*(?:namely|which is:?)\s*"
            r"(.+?)(?:\.|They must)",
            r"travel via\s*(.+?)(?:\.|A rally|The assembly|Anyone participating)",
            r"take a prescribed route to\s*(.+?)(?:\.|The rally|The assembly)",
        ]
        return first_match_group(patterns, haystack)

    def _extract_form_up(self, text: str) -> str | None:
        patterns = [
            r"form up (?:on|in|at)\s+(?:the\s+)?(.+?)\s+at\s+\d",
            r"remain in the area shaded on the map below \((.+?)\)",
            r"form up in a specific area,\s*(.+?),\s*by",
        ]
        return first_match_group(patterns, text)

    def _extract_event_start(self, text: str, title: str) -> str | None:
        start_time = None
        start_match = re.search(
            r"(?:will form up|form up|begins?|begin|starts?|starting)\s+(?:on|at)?\s*"
            r"(?:[^.]{0,40}?\s)?(?:at\s+)?(\d{1,2}:\d{2}\s*hrs)",
            text,
            re.I,
        )
        if start_match:
            start_time = start_match.group(1).replace(" ", "")

        date_match = re.search(
            r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+\d{1,2}\s+\w+",
            text,
        )
        if not date_match:
            date_match = re.search(
                r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+\d{1,2}\s+\w+",
                title,
            )
        event_date = date_match.group(0) if date_match else None
        if event_date and start_time:
            return f"{event_date} {start_time}"
        return event_date
