"""Common interface every protest source implements."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from ingestion.crawler.client import HttpClient
from ingestion.crawler.exceptions import SourceUnavailableError
from ingestion.crawler.models import ProtestRecord

logger = logging.getLogger(__name__)


class ProtestSource(ABC):
    """A single public source of London protest signals.

    Subclasses take tuning options in ``__init__`` and expose one uniform,
    zero-argument ``fetch_records`` so the pipeline can treat every source the same.
    """

    platform_id: str
    platform_name: str
    platform_url: str

    def __init__(self, client: HttpClient | None = None) -> None:
        self.client = client or HttpClient()

    @abstractmethod
    def fetch_records(self) -> list[ProtestRecord]:
        """Fetch and normalise every current protest signal from this source."""

    def fetch_records_safely(self) -> list[ProtestRecord]:
        """Fetch records, logging and swallowing source-specific failures."""
        try:
            return self.fetch_records()
        except SourceUnavailableError as exc:
            logger.warning("source %s unavailable, skipping: %s", self.platform_id, exc.reason)
            return []

    def platform_meta(self) -> dict[str, str]:
        """Stable metadata for run summaries and export."""
        return {
            "platform_id": self.platform_id,
            "platform_name": self.platform_name,
            "platform_url": self.platform_url,
        }
