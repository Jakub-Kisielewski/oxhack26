"""Platform metadata for discovery outputs."""

from __future__ import annotations

from typing import Final, TypedDict

from ingestion.crawler.sources.marble_arch_security import MarbleArchSecuritySource
from ingestion.crawler.sources.met_police import MetPoliceSource
from ingestion.crawler.sources.organizers.sites import ORGANIZER_SITES


class PlatformMeta(TypedDict):
    platform_id: str
    platform_name: str
    platform_url: str


def build_platform_catalog() -> dict[str, PlatformMeta]:
    """Static metadata for every platform this project discovers."""
    catalog: dict[str, PlatformMeta] = {
        MetPoliceSource.platform_id: {
            "platform_id": MetPoliceSource.platform_id,
            "platform_name": MetPoliceSource.platform_name,
            "platform_url": MetPoliceSource.platform_url,
        },
        MarbleArchSecuritySource.platform_id: {
            "platform_id": MarbleArchSecuritySource.platform_id,
            "platform_name": MarbleArchSecuritySource.platform_name,
            "platform_url": MarbleArchSecuritySource.platform_url,
        },
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
