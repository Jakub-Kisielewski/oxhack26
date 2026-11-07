"""Platform metadata for ingestion outputs."""

from __future__ import annotations

from typing import Any, Final, TypedDict

from ingestion.crawler.models import ProtestRecord
from ingestion.crawler.sources.marble_arch_security import MarbleArchSecuritySource
from ingestion.crawler.sources.met_police import MetPoliceSource
from ingestion.crawler.sources.organizers.sites import ORGANIZER_SITES
from ingestion.crawler.sources.osac import OsacSource
from ingestion.crawler.sources.tfl import TflRoadDisruptionSource


class PlatformMeta(TypedDict):
    platform_id: str
    platform_name: str
    platform_url: str


def build_platform_catalog() -> dict[str, PlatformMeta]:
    """Static metadata for every platform this project ingests."""
    catalog: dict[str, PlatformMeta] = {}
    for stub in (
        MetPoliceSource,
        OsacSource,
        TflRoadDisruptionSource,
        MarbleArchSecuritySource,
    ):
        catalog[stub.platform_id] = {
            "platform_id": stub.platform_id,
            "platform_name": stub.platform_name,
            "platform_url": stub.platform_url,
        }
    for site in ORGANIZER_SITES:
        catalog[site.platform_id] = {
            "platform_id": site.platform_id,
            "platform_name": site.platform_name,
            "platform_url": site.platform_url,
        }
    return catalog


PLATFORM_CATALOG: Final = build_platform_catalog()


def platform_meta(platform_id: str) -> PlatformMeta:
    return PLATFORM_CATALOG.get(
        platform_id,
        {
            "platform_id": platform_id,
            "platform_name": platform_id,
            "platform_url": "",
        },
    )


def record_export_dict(record: ProtestRecord) -> dict[str, Any]:
    """Serialise a record plus platform metadata for JSON export."""
    data = record.to_dict()
    data.update(platform_meta(data.get("source", "")))
    return data
