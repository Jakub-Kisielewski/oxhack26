"""HTTP client with polite throttling, retries, and robots.txt checks."""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ingestion.crawler.constants import (
    DEFAULT_HTTP_TIMEOUT_SECONDS,
    DEFAULT_MIN_INTERVAL_SEC,
    DISCOVERY_USER_AGENT,
)

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": DISCOVERY_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}

RETRY_POLICY = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"GET"}),
    respect_retry_after_header=True,
)


class HttpClient:
    """Session-based HTTP access for public discovery pages."""

    def __init__(
        self,
        timeout: int = DEFAULT_HTTP_TIMEOUT_SECONDS,
        min_interval_sec: float = DEFAULT_MIN_INTERVAL_SEC,
        *,
        respect_robots: bool = True,
    ) -> None:
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        adapter = HTTPAdapter(max_retries=RETRY_POLICY)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.timeout = timeout
        self.min_interval_sec = min_interval_sec
        self.respect_robots = respect_robots
        self._last_request_at = 0.0
        self._robot_cache: dict[str, RobotFileParser | None] = {}

    def _throttle(self) -> None:
        """Sleep so consecutive requests are at least min_interval_sec apart."""
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval_sec:
            time.sleep(self.min_interval_sec - elapsed)
        self._last_request_at = time.monotonic()

    def _robots_allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._robot_cache:
            parser = RobotFileParser()
            robots_url = f"{origin}/robots.txt"
            parser.set_url(robots_url)
            try:
                parser.read()
                self._robot_cache[origin] = parser
            except OSError as exc:
                logger.debug("could not read robots.txt for %s: %s", origin, exc)
                self._robot_cache[origin] = None
        parser = self._robot_cache[origin]
        if parser is None:
            return True
        allowed = parser.can_fetch(DEFAULT_HEADERS["User-Agent"], url)
        if not allowed:
            logger.info("robots.txt disallows GET %s", url)
        return allowed

    def get_text(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
        referer: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> str:
        if not self._robots_allowed(url):
            msg = f"robots.txt disallows fetch: {url}"
            raise requests.RequestException(msg)
        self._throttle()
        logger.debug("GET %s", url)
        headers: dict[str, str] = {}
        if referer:
            headers["Referer"] = referer
        if extra_headers:
            headers.update(extra_headers)
        response = self.session.get(
            url,
            params=params,
            headers=headers or None,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.text

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
    ) -> list[Any] | dict[str, Any]:
        if not self._robots_allowed(url):
            msg = f"robots.txt disallows fetch: {url}"
            raise requests.RequestException(msg)
        self._throttle()
        logger.debug("GET JSON %s", url)
        response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, (list, dict)):
            return payload
        msg = f"unexpected JSON type from {url}"
        raise requests.RequestException(msg)
