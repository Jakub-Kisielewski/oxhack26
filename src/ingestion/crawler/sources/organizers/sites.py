"""Configuration for organiser sites used in discovery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PaginationStyle = Literal["query_pno", "path_page", "none"]


@dataclass(frozen=True)
class OrganizerSiteConfig:
    platform_id: str
    platform_name: str
    platform_url: str
    seed_urls: tuple[str, ...]
    max_list_pages: int = 3
    max_detail_fetches: int = 15
    include_actionnetwork: bool = False
    include_date_posts: bool = False
    extra_domains: tuple[str, ...] = ()
    slug_post_prefixes: tuple[str, ...] = ()
    include_listing_slugs: bool = False
    event_slug_prefix: str = "/events/"
    pagination: PaginationStyle = "query_pno"


ORGANIZER_SITES: tuple[OrganizerSiteConfig, ...] = (
    OrganizerSiteConfig(
        platform_id="psc",
        platform_name="Palestine Solidarity Campaign",
        platform_url="https://palestinecampaign.org",
        seed_urls=("https://palestinecampaign.org/events/",),
        pagination="query_pno",
    ),
)
