"""TfL Unified API road disruption source for protest-related closures."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from ingestion.crawler.client import HttpClient, tfl_params
from ingestion.crawler.constants import (
    DEFAULT_TFL_DAYS_AHEAD,
    DEFAULT_TFL_PAST_HOURS,
    EXCLUDED_EVENT_TERMS,
    MAX_STREETS_PER_RECORD,
    PROTEST_TERMS,
    RAW_EXCERPT_DEFAULT_CHARS,
    TFL_MIN_INTERVAL_SEC,
)
from ingestion.crawler.models import ProtestRecord
from ingestion.crawler.sources.base import ProtestSource

logger = logging.getLogger(__name__)

TFL_API = "https://api.tfl.gov.uk/Road/all/Disruption"


class TflRoadDisruptionSource(ProtestSource):
    """Protest-related road disruptions from the TfL Unified API."""

    platform_id = "tfl_road_disruption"
    platform_name = "TfL Unified API (Road Disruptions)"
    platform_url = "https://api.tfl.gov.uk"

    def __init__(
        self,
        client: HttpClient | None = None,
        *,
        days_ahead: int = DEFAULT_TFL_DAYS_AHEAD,
        include_past_hours: int = DEFAULT_TFL_PAST_HOURS,
    ) -> None:
        super().__init__(client or HttpClient(min_interval_sec=TFL_MIN_INTERVAL_SEC))
        self.days_ahead = days_ahead
        self.include_past_hours = include_past_hours

    def fetch_records(self) -> list[ProtestRecord]:
        """Fetch disruptions in the configured date window."""
        fetched_at = datetime.now(UTC)
        start = fetched_at - timedelta(hours=self.include_past_hours)
        end = fetched_at + timedelta(days=self.days_ahead)
        params = {
            **tfl_params(),
            "startDate": start.strftime("%Y-%m-%dT%H:%M:%S"),
            "endDate": end.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        payload = self.client.get_json(TFL_API, params=params)
        if not isinstance(payload, list):
            logger.warning("TfL API returned non-list payload")
            return []

        records: list[ProtestRecord] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            if not self._is_protest_related(item):
                continue
            records.append(self._to_record(item, fetched_at.isoformat()))
        return records

    def _is_protest_related(self, item: dict[str, Any]) -> bool:
        """True when a TfL disruption describes a protest rather than a ceremonial event."""
        sub_category = (item.get("subCategory") or "").lower()
        if "demonstration" in sub_category:
            return True

        blob = " ".join(
            str(item.get(key, "")) for key in ("comments", "location", "category")
        ).lower()
        mentions_protest = any(term in blob for term in PROTEST_TERMS)
        is_excluded = any(term in blob for term in EXCLUDED_EVENT_TERMS)
        return mentions_protest and not is_excluded

    def _to_record(self, item: dict[str, Any], fetched_at: str) -> ProtestRecord:
        comments = item.get("comments") or ""
        location = item.get("location") or ""
        lat, lon = self._parse_point(item.get("point"))
        route_text = self._extract_route_from_comments(comments)

        return ProtestRecord(
            source=self.platform_id,
            source_id=str(item.get("id")),
            title=self._title_from_comments(comments),
            url=f"https://api.tfl.gov.uk{item.get('url', '')}",
            fetched_at=fetched_at,
            event_start=item.get("startDateTime"),
            event_end=item.get("endDateTime"),
            route_text=route_text or location,
            route_streets=self._streets_from_comments(comments),
            location_label=location,
            latitude=lat,
            longitude=lon,
            raw_excerpt=comments[:RAW_EXCERPT_DEFAULT_CHARS],
            extra={
                "severity": item.get("severity"),
                "category": item.get("category"),
                "sub_category": item.get("subCategory"),
                "status": item.get("status"),
            },
        )

    def _parse_point(self, point: object) -> tuple[float | None, float | None]:
        """Extract (latitude, longitude) from TfL's GeoJSON-style point field."""
        if not point:
            return None, None
        if isinstance(point, str):
            try:
                coords = json.loads(point)
            except json.JSONDecodeError:
                return None, None
        else:
            coords = point

        if not isinstance(coords, (list, tuple)) or len(coords) != 2:
            return None, None
        try:
            longitude, latitude = (float(value) for value in coords)
        except (TypeError, ValueError):
            return None, None
        return latitude, longitude

    def _title_from_comments(self, comments: str) -> str:
        first = comments.split(" - ", 1)[0].strip()
        return first or "TfL demonstration disruption"

    def _extract_route_from_comments(self, comments: str) -> str | None:
        match = re.search(r" - (.+)$", comments)
        return match.group(1).strip() if match else None

    def _streets_from_comments(self, comments: str) -> list[str]:
        route = self._extract_route_from_comments(comments) or comments
        parts = re.split(r"\s+at the junction of\s+|\s+between\s+", route, flags=re.I)
        streets: list[str] = []
        for part in parts:
            cleaned = part.strip(" .")
            if cleaned:
                streets.append(cleaned)
        return streets[:MAX_STREETS_PER_RECORD]


# Backward-compatible alias
TflRoadDisruptionCrawler = TflRoadDisruptionSource
