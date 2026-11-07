"""Default protest sources for a full ingestion run."""

from __future__ import annotations

from pathlib import Path

from ingestion.crawler.constants import (
    DEFAULT_MET_LIMIT,
    DEFAULT_OSAC_LIMIT,
    DEFAULT_TFL_DAYS_AHEAD,
    DEFAULT_TFL_PAST_HOURS,
)
from ingestion.crawler.sources.base import ProtestSource
from ingestion.crawler.sources.marble_arch_security import MarbleArchSecuritySource
from ingestion.crawler.sources.met_police import MetPoliceSource
from ingestion.crawler.sources.organizers import ORGANIZER_SITES
from ingestion.crawler.sources.organizers.crawler import OrganizerSiteSource
from ingestion.crawler.sources.osac import OsacSource
from ingestion.crawler.sources.tfl import TflRoadDisruptionSource


def default_sources(
    *,
    met_media_dir: Path,
    met_limit: int = DEFAULT_MET_LIMIT,
    osac_limit: int = DEFAULT_OSAC_LIMIT,
    tfl_days_ahead: int = DEFAULT_TFL_DAYS_AHEAD,
    marble_arch_limit: int | None = None,
    organizer_event_days_back: int = 0,
    organizer_event_days_ahead: int = 0,
) -> list[ProtestSource]:
    """Every source this project ingests, in run order."""
    return [
        MetPoliceSource(media_dir=met_media_dir, limit=met_limit),
        OsacSource(limit=osac_limit),
        TflRoadDisruptionSource(
            days_ahead=tfl_days_ahead,
            include_past_hours=DEFAULT_TFL_PAST_HOURS,
        ),
        MarbleArchSecuritySource(limit=marble_arch_limit),
        *(
            OrganizerSiteSource(
                site,
                event_days_back=organizer_event_days_back,
                event_days_ahead=organizer_event_days_ahead,
            )
            for site in ORGANIZER_SITES
        ),
    ]
