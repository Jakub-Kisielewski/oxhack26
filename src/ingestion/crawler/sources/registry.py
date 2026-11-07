"""Default protest sources for discovery crawls."""

from __future__ import annotations

from ingestion.crawler.constants import DEFAULT_MET_LIMIT
from ingestion.crawler.sources.base import ProtestSource
from ingestion.crawler.sources.met_police import MetPoliceSource
from ingestion.crawler.sources.organizers import ORGANIZER_SITES
from ingestion.crawler.sources.organizers.crawler import OrganizerSiteSource


def default_sources(
    *,
    met_limit: int = DEFAULT_MET_LIMIT,
    organizer_event_days_back: int = 0,
    organizer_event_days_ahead: int = 0,
) -> list[ProtestSource]:
    """Met Police conditions notices plus pruned organiser sites."""
    return [
        MetPoliceSource(limit=met_limit),
        *(
            OrganizerSiteSource(
                site,
                event_days_back=organizer_event_days_back,
                event_days_ahead=organizer_event_days_ahead,
            )
            for site in ORGANIZER_SITES
        ),
    ]
