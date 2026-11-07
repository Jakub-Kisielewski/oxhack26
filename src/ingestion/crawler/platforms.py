"""Platform metadata for discovery outputs."""

from __future__ import annotations

from typing import Final, TypedDict

from ingestion.crawler.sources.marble_arch_security import MarbleArchSecuritySource
from ingestion.crawler.sources.met_police import MetPoliceSource
from ingestion.crawler.sources.psc import PscSource


class PlatformMeta(TypedDict):
    platform_id: str
    platform_name: str
    platform_url: str


def build_platform_catalog() -> dict[str, PlatformMeta]:
    """Static metadata for every platform this project discovers."""
    stubs = (MetPoliceSource, MarbleArchSecuritySource, PscSource)
    return {
        stub.platform_id: {
            "platform_id": stub.platform_id,
            "platform_name": stub.platform_name,
            "platform_url": stub.platform_url,
        }
        for stub in stubs
    }


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
