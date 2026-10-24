from __future__ import annotations

import html as html_lib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin

from ingestion.client import HttpClient
from ingestion.models import ProtestRecord
from ingestion.parse_utils import (
    clean_html_text,
    extract_paragraphs,
    parse_counter_protest_flag,
    parse_participant_estimate,
    parse_route_streets,
)

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

# Met posts about bans/suppressions are not upcoming actionable marches.
SUPPRESSED_EVENT_PATTERNS = (
    r"consented to (?:the )?(?:(?:metropolitan|met)(?: police)? )?banning",
    r"\bbanning (?:\w+\s+){0,4}march",
    r"\bhas banned\b",
    r"\bprotest ban\b",
    r"banning (?:sunday'?s? )?(?:\w+ )*march",
)


class MetPoliceCrawler:
    source_name = "met_police"

    def __init__(
        self,
        client: Optional[HttpClient] = None,
        media_dir: Optional[Path] = None,
        download_images: bool = True,
    ):
        self.client = client or HttpClient()
        self.media_dir = media_dir
        self.download_images = download_images

    def list_articles(
        self, limit: Optional[int] = None, max_pages: int = 20
    ) -> list[dict]:
        articles: list[dict] = []
        seen_urls: set[str] = set()

        page_html = self.client.get_text(CENTRAL_LONDON_TAG_URL)
        self._collect_candidates(page_html, articles, seen_urls, limit)

        next_path = self._extract_next_page_path(page_html)
        pages_fetched = 0
        while (
            next_path
            and (limit is None or len(articles) < limit)
            and pages_fetched < max_pages
        ):
            page_html = self._fetch_archive_page(next_path)
            self._collect_candidates(page_html, articles, seen_urls, limit)
            next_path = self._extract_next_page_path(page_html)
            pages_fetched += 1

        if limit is not None:
            return articles[:limit]
        return articles

    def fetch_records(self, limit: Optional[int] = 10) -> list[ProtestRecord]:
        fetched_at = datetime.now(timezone.utc).isoformat()
        records: list[ProtestRecord] = []
        for article in self.list_articles(limit=limit):
            html = self.client.get_text(
                article["url"], referer=CENTRAL_LONDON_TAG_URL
            )
            records.extend(self._parse_article(html, article, fetched_at))
        return records

    def _collect_candidates(
        self,
        page_html: str,
        articles: list[dict],
        seen_urls: set[str],
        limit: Optional[int],
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

    def _extract_story_stubs(self, page_html: str) -> list[dict]:
        stubs: list[dict] = []
        for match in re.finditer(
            r'<script type="application/ld\+json">(.*?)</script>', page_html, re.S
        ):
            try:
                payload = json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
            if payload.get("@type") != "CollectionPage":
                continue
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

    def _extract_next_page_path(self, page_html: str) -> Optional[str]:
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

    def _is_suppressed_event(
        self, headline: str, description: str, body: str = ""
    ) -> bool:
        blob = f"{headline} {description} {body[:800]}".lower()
        return any(
            re.search(pattern, blob, re.I) for pattern in SUPPRESSED_EVENT_PATTERNS
        )

    def _normalize_article_url(self, url: str) -> str:
        if url.startswith("http"):
            return url
        return urljoin(BASE, url)

    def _canonical_url(self, item: dict) -> str:
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
        self, html: str, article: dict, fetched_at: str
    ) -> list[ProtestRecord]:
        body = self._extract_body_text(html)
        title = article["headline"]
        description = article.get("description", "")
        if self._is_suppressed_event(title, description, body):
            return []
        source_id = re.search(r"-(\d+)\s*$", article["url"])
        source_id = source_id.group(1) if source_id else article["url"]

        route_text = self._extract_section_12_route(body)
        form_up = self._extract_form_up(body)
        participants = self._extract_participants(body)
        counter = parse_counter_protest_flag(body)
        event_start, event_end = self._extract_event_window(body, title)

        images = self._crawl_article_images(html, source_id, article["url"])
        record = ProtestRecord(
            source=self.source_name,
            source_id=source_id,
            title=title,
            url=article["url"],
            fetched_at=fetched_at,
            event_start=event_start,
            event_end=event_end,
            form_up_location=form_up,
            route_text=route_text,
            route_streets=parse_route_streets(route_text or ""),
            estimated_participants_min=participants[0],
            estimated_participants_max=participants[1],
            estimated_participants_text=participants[2],
            counter_protest_expected=counter,
            raw_excerpt=body[:2000],
            extra={
                "published_at": article.get("date_published"),
                "description": article.get("description"),
                "listing_source": CENTRAL_LONDON_TAG_URL,
                "images": images,
            },
        )
        return [record]

    def _crawl_article_images(
        self, article_html: str, source_id: str, article_url: str
    ) -> list[dict[str, Any]]:
        images: list[dict[str, Any]] = []
        for stub in self._extract_image_stubs(article_html):
            if stub.get("role") == "stock":
                continue
            resolved = self._resolve_image_page(stub["page_url"])
            if not resolved:
                continue
            entry: dict[str, Any] = {
                "caption": stub.get("caption") or resolved.get("name"),
                "role": stub.get("role"),
                "page_url": stub["page_url"],
                "content_url": resolved.get("content_url"),
                "upload_date": resolved.get("upload_date"),
            }
            if self.download_images and self.media_dir and entry["content_url"]:
                local_path = self._download_image(
                    source_id=source_id,
                    caption=entry["caption"] or "image",
                    content_url=entry["content_url"],
                    referer=stub["page_url"],
                )
                if local_path:
                    entry["local_path"] = str(local_path)
            images.append(entry)
        return images

    def _extract_image_stubs(self, html: str) -> list[dict[str, str]]:
        stubs: list[dict[str, str]] = []
        seen: set[str] = set()
        patterns = [
            r'panel__content-media-link"[^>]*href="([^"]+)"[^>]*title="([^"]+)"',
            r'title="([^"]+)"[^>]*aria-label="\1"[^>]*href="(https://news\.met\.police\.uk/images/[^"]+)"',
            r'href="(https://news\.met\.police\.uk/images/[^"]+)"',
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, html, re.I):
                if len(match.groups()) == 2:
                    if pattern.startswith("title"):
                        caption, page_url = match.group(1), match.group(2)
                    else:
                        page_url, caption = match.group(1), match.group(2)
                else:
                    page_url, caption = match.group(1), ""
                page_url = self._normalize_article_url(page_url)
                if "/images/" not in page_url or page_url in seen:
                    continue
                seen.add(page_url)
                caption = clean_html_text(caption) or self._caption_from_image_slug(page_url)
                stubs.append(
                    {
                        "page_url": page_url,
                        "caption": caption,
                        "role": self._classify_image_role(caption),
                    }
                )
        return stubs

    def _resolve_image_page(self, page_url: str) -> Optional[dict[str, str]]:
        html = self.client.get_text(page_url, referer=CENTRAL_LONDON_TAG_URL)
        for match in re.finditer(
            r'<script type="application/ld\+json">(.*?)</script>', html, re.S
        ):
            try:
                payload = json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
            if payload.get("@type") != "MediaObject":
                continue
            content_url = payload.get("contentUrl")
            if not content_url:
                continue
            return {
                "name": payload.get("name", ""),
                "content_url": self._high_resolution_image_url(content_url),
                "upload_date": payload.get("uploadDate"),
            }
        og_image = re.search(
            r'<meta property="og:image" content="([^"]+)"', html, re.I
        )
        if og_image:
            return {
                "name": "",
                "content_url": self._high_resolution_image_url(og_image.group(1)),
                "upload_date": None,
            }
        return None

    def _high_resolution_image_url(self, content_url: str) -> str:
        if "mnd-assets.mynewsdesk.com/image/upload/" not in content_url:
            return content_url
        suffix = content_url.split("/upload/", 1)[1]
        token = suffix.split("/")[-1]
        return f"https://mnd-assets.mynewsdesk.com/image/upload/q_auto:good,w_2400/{token}"

    def _download_image(
        self,
        *,
        source_id: str,
        caption: str,
        content_url: str,
        referer: str,
    ) -> Optional[Path]:
        assert self.media_dir is not None
        article_dir = self.media_dir / str(source_id)
        article_dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", caption.lower()).strip("-")[:60] or "image"
        extension = ".jpg"
        if ".png" in content_url.lower():
            extension = ".png"
        destination = article_dir / f"{slug}{extension}"
        payload, content_type = self.client.get_bytes(content_url, referer=referer)
        if content_type and "png" in content_type and extension != ".png":
            destination = article_dir / f"{slug}.png"
        destination.write_bytes(payload)
        return destination

    def _caption_from_image_slug(self, page_url: str) -> str:
        slug = page_url.rstrip("/").split("/")[-1]
        return slug.replace("-dot-jpg", ".jpg").replace("-", " ")

    def _classify_image_role(self, caption: str) -> str:
        lowered = caption.lower()
        if "stock" in lowered:
            return "stock"
        if "form up" in lowered or "form-up" in lowered:
            return "form_up_map"
        if "procession route" in lowered or "route conditions" in lowered:
            return "route_map"
        if "rally" in lowered:
            return "rally_map"
        if "section 60" in lowered:
            return "section_60aa_map"
        if "emergency access" in lowered:
            return "emergency_lane_map"
        if "map" in lowered:
            return "conditions_map"
        return "media"

    def _extract_body_text(self, html: str) -> str:
        for match in re.finditer(
            r'<script type="application/ld\+json">(.*?)</script>', html, re.S
        ):
            try:
                payload = json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
            if payload.get("@type") == "NewsArticle" and payload.get("articleBody"):
                return clean_html_text(str(payload["articleBody"]))
        paragraphs = extract_paragraphs(html)
        div_chunks = [
            clean_html_text(chunk)
            for chunk in re.findall(r"(?is)<div[^>]*>(.*?)</div>", html)
        ]
        div_chunks = [chunk for chunk in div_chunks if len(chunk) > 20]
        return "\n".join([*paragraphs, *div_chunks])

    def _extract_section_12_route(self, text: str) -> Optional[str]:
        section = re.search(
            r"Section 12\(3\) Public Order Act 1986(.*?)(?:Section 14|Details of conditions|$)",
            text,
            re.I | re.S,
        )
        haystack = section.group(1) if section else text
        patterns = [
            r"route shown on the map below, which is:\s*(.+?)(?:\.|They must begin)",
            r"route specified on the map below, namely\s*(.+?)(?:\.|Anyone participating)",
            r"must not deviate from the route[^,]*,\s*(?:namely|which is:?)\s*(.+?)(?:\.|They must)",
            r"travel via\s*(.+?)(?:\.|A rally|The assembly|Anyone participating)",
            r"take a prescribed route to\s*(.+?)(?:\.|The rally|The assembly)",
        ]
        for pattern in patterns:
            match = re.search(pattern, haystack, re.I | re.S)
            if match:
                return clean_html_text(match.group(1))
        return None

    def _extract_form_up(self, text: str) -> Optional[str]:
        patterns = [
            r"form up (?:on|in|at)\s+(?:the\s+)?(.+?)\s+at\s+\d",
            r"remain in the area shaded on the map below \((.+?)\)",
            r"form up in a specific area,\s*(.+?),\s*by",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if match:
                return clean_html_text(match.group(1))
        return None

    def _extract_participants(
        self, text: str
    ) -> tuple[Optional[int], Optional[int], Optional[str]]:
        match = re.search(
            r"(?:anticipate|expect|expected|between)\s+(.{0,80}?(?:people|participants).{0,20})",
            text,
            re.I,
        )
        if match:
            return parse_participant_estimate(match.group(1))
        return None, None, None

    def _extract_event_window(
        self, text: str, title: str
    ) -> tuple[Optional[str], Optional[str]]:
        start_time = None
        end_time = None
        start_match = re.search(
            r"(?:will form up|form up|begins?|begin|starts?|starting)\s+(?:on|at)?\s*"
            r"(?:[^.]{0,40}?\s)?(?:at\s+)?(\d{1,2}:\d{2}\s*hrs)",
            text,
            re.I,
        )
        if start_match:
            start_time = start_match.group(1).replace(" ", "")
        end_match = re.search(
            r"(?:must conclude by|conclude by|ends? by|ending at)\s+(\d{1,2}:\d{2}\s*hrs)",
            text,
            re.I,
        )
        if end_match:
            end_time = end_match.group(1).replace(" ", "")

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
            return f"{event_date} {start_time}", (
                f"{event_date} {end_time}" if end_time else None
            )
        return event_date, None
