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
    OrganizerSiteConfig(
        platform_id="cnd",
        platform_name="Campaign for Nuclear Disarmament (CND)",
        platform_url="https://cnduk.org",
        seed_urls=("https://cnduk.org/events/",),
        pagination="query_pno",
    ),
    OrganizerSiteConfig(
        platform_id="stop_the_war",
        platform_name="Stop the War Coalition",
        platform_url="https://www.stopwar.org.uk",
        seed_urls=("https://www.stopwar.org.uk/events/",),
        pagination="query_pno",
    ),
    OrganizerSiteConfig(
        platform_id="together_alliance",
        platform_name="Together Alliance",
        platform_url="https://www.togetheralliance.org.uk",
        seed_urls=("https://www.togetheralliance.org.uk/",),
        include_actionnetwork=True,
        extra_domains=("actionnetwork.org",),
        pagination="none",
    ),
)
