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


class MediaDirectoryNotConfiguredError(IngestionError):
    """Image download was requested without a media directory."""


class CurlNotAvailableError(SourceUnavailableError):
    """The curl binary is required for an SSL fallback but was not found."""

    def __init__(self, reason: str = "curl not found for SSL fallback") -> None:
        super().__init__(platform_id="", reason=reason)
