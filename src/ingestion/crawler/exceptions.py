"""Exceptions raised by the ingestion crawlers."""


class IngestionError(Exception):
    """Base class for every ingestion failure."""


class SourceUnavailableError(IngestionError):
    """A source could not be reached after exhausting retries."""

    def __init__(self, platform_id: str, reason: str) -> None:
        super().__init__(f"source {platform_id} unavailable: {reason}")
        self.platform_id = platform_id
        self.reason = reason


class UnknownPlatformError(IngestionError):
    """A platform ID was requested that no registered source provides."""
