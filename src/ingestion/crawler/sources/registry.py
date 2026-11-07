"""Default protest sources for discovery crawls."""

from __future__ import annotations

from ingestion.crawler.constants import DEFAULT_MET_LIMIT
from ingestion.crawler.sources.base import ProtestSource
from ingestion.crawler.sources.marble_arch_security import MarbleArchSecuritySource
from ingestion.crawler.sources.met_police import MetPoliceSource
from ingestion.crawler.sources.psc import PscSource


def default_sources(
    *,
    met_limit: int = DEFAULT_MET_LIMIT,
    organizer_event_days_back: int = 0,
    organizer_event_days_ahead: int = 0,
) -> list[ProtestSource]:
    """Met Police, Marble Arch BID feed, and PSC — sources aligned with seed provenance."""
    return [
        MetPoliceSource(limit=met_limit),
        MarbleArchSecuritySource(),
        PscSource(
            event_days_back=organizer_event_days_back,
            event_days_ahead=organizer_event_days_ahead,
        ),
    ]
