from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin

from ingestion.client import HttpClient
from ingestion.models import ProtestRecord
from ingestion.parse_utils import (
    clean_html_text,
    extract_paragraphs,
    parse_participant_estimate,
    parse_route_streets,
)

BASE = "https://www.osac.gov"
LISTING_URL = (
    f"{BASE}/Country/UnitedKingdom/Content/Search"
    "?contentTypes=Report&subContentTypes=Travel%20Advisories%2CAlerts"
)


class OsacCrawler:
    source_name = "osac"

    def __init__(self, client: Optional[HttpClient] = None):
        self.client = client or HttpClient(min_interval_sec=0.5)

    def list_reports(self, london_only: bool = True) -> list[dict]:
        html = self.client.get_text(LISTING_URL, referer=BASE)
        reports: list[dict] = []
        for match in re.finditer(
            r'(?is)<div class="card-wrapper">\s*<a href="(?P<href>/Content/Report/[^"]+)"[^>]*>'
            r".*?<p class=\"card-text\">\s*(?P<meta>.*?)\s*</p>\s*"
            r"<h3 class=\"card-title\">(?P<title>.*?)</h3>",
            html,
        ):
            title = clean_html_text(match.group("title"))
            if london_only and "london" not in title.lower():
                continue
            if "demonstration alert" not in title.lower():
                continue
            meta = clean_html_text(match.group("meta"))
            reports.append(
                {
                    "title": title,
                    "url": urljoin(BASE, match.group("href")),
                    "listing_meta": meta,
                }
            )
        return reports

    def fetch_records(
        self, limit: Optional[int] = 15, london_only: bool = True
    ) -> list[ProtestRecord]:
        fetched_at = datetime.now(timezone.utc).isoformat()
        records: list[ProtestRecord] = []
        for report in self.list_reports(london_only=london_only)[: limit or None]:
            html = self.client.get_text(report["url"], referer=LISTING_URL)
            records.extend(self._parse_report(html, report, fetched_at))
        return records

    def _parse_report(
        self, html: str, report: dict, fetched_at: str
    ) -> list[ProtestRecord]:
        title = report["title"]
        source_id = report["url"].rstrip("/").split("/")[-1]
        paragraphs = extract_paragraphs(html, min_len=10)
        body = "\n".join(paragraphs)

        demo_blocks = self._extract_demo_blocks(paragraphs)
        if not demo_blocks:
            demo_blocks = [body]

        records: list[ProtestRecord] = []
        for idx, block in enumerate(demo_blocks):
            route_text = self._field(block, "route") or self._field(block, "location")
            participants_text = self._field(block, "number of participants")
            pmin, pmax, ptext = parse_participant_estimate(participants_text or block)
            if not ptext and participants_text:
                ptext = participants_text

            records.append(
                ProtestRecord(
                    source=self.source_name,
                    source_id=f"{source_id}:{idx}",
                    title=title,
                    url=report["url"],
                    fetched_at=fetched_at,
                    event_start=self._compose_datetime(block),
                    event_end=None,
                    form_up_location=self._field(block, "location"),
                    route_text=route_text,
                    route_streets=parse_route_streets(route_text or ""),
                    estimated_participants_min=pmin,
                    estimated_participants_max=pmax,
                    estimated_participants_text=ptext,
                    location_label=self._field(block, "location"),
                    raw_excerpt=block[:1500],
                    extra={
                        "demonstration_name": self._field(block, "demonstration"),
                        "listing_meta": report.get("listing_meta"),
                        "report_location": self._field(body, "location"),
                    },
                )
            )
        return records

    def _extract_demo_blocks(self, paragraphs: list[str]) -> list[str]:
        blocks: list[str] = []
        for paragraph in paragraphs:
            if re.search(r"\bDate\s*:", paragraph, re.I) and re.search(
                r"\bDemonstration\s*:", paragraph, re.I
            ):
                blocks.append(clean_html_text(paragraph))
        return blocks

    def _field(self, text: str, label: str) -> Optional[str]:
        pattern = rf"{re.escape(label)}\s*:?\s*(.+?)(?=\s*(?:Date|Demonstration|Time|Route|Location|Number of participants)\s*:|$)"
        match = re.search(pattern, text, re.I | re.S)
        if not match:
            return None
        return clean_html_text(match.group(1))

    def _compose_datetime(self, block: str) -> Optional[str]:
        date_val = self._field(block, "date")
        time_val = self._field(block, "time")
        if date_val and time_val:
            return f"{date_val} {time_val}"
        return date_val or time_val
