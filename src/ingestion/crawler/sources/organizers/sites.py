from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

PaginationStyle = Literal["query_pno", "path_page", "none"]


@dataclass(frozen=True)
class OrganizerSiteConfig:
    platform_id: str
    platform_name: str
    platform_url: str
    seed_urls: list[str]
    max_list_pages: int = 4
    max_detail_fetches: int = 35
    include_actionnetwork: bool = False
    include_date_posts: bool = False
    extra_domains: tuple[str, ...] = field(default_factory=tuple)
    slug_post_prefixes: tuple[str, ...] = field(default_factory=tuple)
    include_listing_slugs: bool = False
    event_slug_prefix: str = "/events/"
    pagination: PaginationStyle = "query_pno"


ORGANIZER_SITES: tuple[OrganizerSiteConfig, ...] = (
    OrganizerSiteConfig(
        platform_id="psc",
        platform_name="Palestine Solidarity Campaign",
        platform_url="https://palestinecampaign.org",
        seed_urls=["https://palestinecampaign.org/events/"],
        pagination="query_pno",
    ),
    OrganizerSiteConfig(
        platform_id="cnd",
        platform_name="Campaign for Nuclear Disarmament (CND)",
        platform_url="https://cnduk.org",
        seed_urls=["https://cnduk.org/events/"],
        max_list_pages=6,
        pagination="query_pno",
    ),
    OrganizerSiteConfig(
        platform_id="counterfire",
        platform_name="Counterfire",
        platform_url="https://www.counterfire.org",
        seed_urls=["https://www.counterfire.org/events/"],
        event_slug_prefix="/event/",
        max_detail_fetches=50,
        pagination="none",
    ),
    OrganizerSiteConfig(
        platform_id="foa",
        platform_name="Friends of Al-Aqsa",
        platform_url="https://www.foa.org.uk",
        seed_urls=["https://www.foa.org.uk/events"],
        pagination="query_pno",
    ),
    OrganizerSiteConfig(
        platform_id="stop_the_war",
        platform_name="Stop the War Coalition",
        platform_url="https://www.stopwar.org.uk",
        seed_urls=["https://www.stopwar.org.uk/events/"],
        max_list_pages=5,
        pagination="query_pno",
    ),
    OrganizerSiteConfig(
        platform_id="mab",
        platform_name="Muslim Association of Britain",
        platform_url="https://www.mabonline.net",
        seed_urls=["https://www.mabonline.net/media/press-releases"],
        include_date_posts=True,
        slug_post_prefixes=("/media/press-releases/",),
        pagination="path_page",
    ),
    OrganizerSiteConfig(
        platform_id="peoples_assembly",
        platform_name="People's Assembly",
        platform_url="https://thepeoplesassembly.org.uk",
        seed_urls=["https://thepeoplesassembly.org.uk/news"],
        include_date_posts=True,
        max_detail_fetches=40,
        pagination="path_page",
    ),
    OrganizerSiteConfig(
        platform_id="together_alliance",
        platform_name="Together Alliance",
        platform_url="https://www.togetheralliance.org.uk",
        seed_urls=["https://www.togetheralliance.org.uk/"],
        include_actionnetwork=True,
        extra_domains=("actionnetwork.org",),
        pagination="none",
    ),
    OrganizerSiteConfig(
        platform_id="stand_up_to_racism",
        platform_name="Stand Up To Racism",
        platform_url="https://standuptoracism.org.uk",
        seed_urls=[
            "https://www.standuptoracism.org.uk/events/",
            "https://standuptoracism.org.uk/events/",
            "https://standuptoracism.org.uk/events/?past=1",
        ],
        include_actionnetwork=True,
        pagination="query_pno",
    ),
    OrganizerSiteConfig(
        platform_id="xr_uk",
        platform_name="Extinction Rebellion UK",
        platform_url="https://extinctionrebellion.uk",
        seed_urls=["https://extinctionrebellion.uk/category/actions/"],
        include_date_posts=True,
        max_list_pages=10,
        pagination="path_page",
    ),
    OrganizerSiteConfig(
        platform_id="youth_demand",
        platform_name="Youth Demand",
        platform_url="https://youthdemand.org",
        seed_urls=["https://youthdemand.org/news-press/"],
        include_date_posts=True,
        max_detail_fetches=15,
        pagination="path_page",
    ),
    OrganizerSiteConfig(
        platform_id="defend_our_juries",
        platform_name="Defend Our Juries",
        platform_url="https://defendourjuries.net",
        seed_urls=[
            "https://defendourjuries.net/press-releases/",
            "https://defendourjuries.net/lift-the-ban/",
        ],
        include_date_posts=True,
        include_actionnetwork=True,
        slug_post_prefixes=("/press-releases/",),
        pagination="path_page",
    ),
)
