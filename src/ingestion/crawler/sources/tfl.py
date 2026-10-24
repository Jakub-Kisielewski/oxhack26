from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from ingestion.crawler.client import HttpClient, tfl_params
from ingestion.crawler.models import ProtestRecord

TFL_API = "https://api.tfl.gov.uk/Road/all/Disruption"


class TflRoadDisruptionCrawler:
    source_name = "tfl_road_disruption"

    def __init__(self, client: Optional[HttpClient] = None):
        self.client = client or HttpClient(min_interval_sec=0.2)

    def fetch_records(
        self,
        *,
        days_ahead: int = 30,
        include_past_hours: int = 24,
    ) -> list[ProtestRecord]:
        fetched_at = datetime.now(timezone.utc)
        start = fetched_at - timedelta(hours=include_past_hours)
        end = fetched_at + timedelta(days=days_ahead)
        params = {
            **tfl_params(),
            "startDate": start.strftime("%Y-%m-%dT%H:%M:%S"),
            "endDate": end.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        payload = self.client.get_json(TFL_API, params=params)
        if not isinstance(payload, list):
            return []

        records: list[ProtestRecord] = []
        for item in payload:
            if not self._is_protest_related(item):
                continue
            records.append(self._to_record(item, fetched_at.isoformat()))
        return records

    def _is_protest_related(self, item: dict) -> bool:
        sub_category = (item.get("subCategory") or "").lower()
        if "demonstration" in sub_category or sub_category == "demonstration/march":
            return True
        blob = " ".join(
            str(item.get(key, "")) for key in ("comments", "location", "category")
        ).lower()
        return "demonstration" in blob or "march" in blob and "remembrance" not in blob

    def _to_record(self, item: dict, fetched_at: str) -> ProtestRecord:
        comments = item.get("comments") or ""
        location = item.get("location") or ""
        lat, lon = self._parse_point(item.get("point"))
        route_text = self._extract_route_from_comments(comments)

        return ProtestRecord(
            source=self.source_name,
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
            raw_excerpt=comments[:1500],
            extra={
                "severity": item.get("severity"),
                "category": item.get("category"),
                "sub_category": item.get("subCategory"),
                "status": item.get("status"),
            },
        )

    def _parse_point(self, point: object) -> tuple[Optional[float], Optional[float]]:
        if not point:
            return None, None
        if isinstance(point, str):
            try:
                coords = json.loads(point)
            except json.JSONDecodeError:
                return None, None
        elif isinstance(point, (list, tuple)) and len(point) == 2:
            coords = point
        else:
            return None, None
        lon, lat = coords
        return float(lat), float(lon)

    def _title_from_comments(self, comments: str) -> str:
        first = comments.split(" - ", 1)[0].strip()
        return first or "TfL demonstration disruption"

    def _extract_route_from_comments(self, comments: str) -> Optional[str]:
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
        return streets[:6]
