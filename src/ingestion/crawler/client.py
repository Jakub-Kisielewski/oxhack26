"""HTTP client with polite throttling, retries, and optional curl SSL fallback."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ingestion.crawler.constants import DEFAULT_HTTP_TIMEOUT_SECONDS, DEFAULT_MIN_INTERVAL_SEC
from ingestion.crawler.exceptions import CurlNotAvailableError

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

RETRY_POLICY = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"GET"}),
    respect_retry_after_header=True,
)


class HttpClient:
    """Session-based HTTP access for crawlers."""

    def __init__(
        self,
        timeout: int = DEFAULT_HTTP_TIMEOUT_SECONDS,
        min_interval_sec: float = DEFAULT_MIN_INTERVAL_SEC,
        *,
        cloudflare_fallback: bool = True,
        respect_robots: bool = True,
    ) -> None:
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        adapter = HTTPAdapter(max_retries=RETRY_POLICY)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.timeout = timeout
        self.min_interval_sec = min_interval_sec
        self.cloudflare_fallback = cloudflare_fallback
        self.respect_robots = respect_robots
        self._last_request_at = 0.0
        self._cloudscraper: Any = None
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
            except Exception as exc:
                logger.debug("could not read robots.txt for %s: %s", origin, exc)
                self._robot_cache[origin] = None
        parser = self._robot_cache[origin]
        if parser is None:
            return True
        allowed = parser.can_fetch(DEFAULT_HEADERS["User-Agent"], url)
        if not allowed:
            logger.info("robots.txt disallows GET %s", url)
        return allowed

    def _cloudscraper_session(self) -> Any:
        if self._cloudscraper is None:
            import cloudscraper

            self._cloudscraper = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "darwin", "desktop": True},
            )
        return self._cloudscraper

    def _sync_cookies(self, response: requests.Response) -> None:
        if response.cookies:
            self.session.cookies.update(response.cookies)

    def _request_get(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        response = self.session.get(
            url,
            params=params,
            headers=headers,
            timeout=self.timeout,
        )
        if response.status_code == 403 and self.cloudflare_fallback:
            try:
                cf = self._cloudscraper_session().get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=self.timeout,
                )
            except requests.exceptions.SSLError:
                return response
            if cf.status_code == 200:
                self._sync_cookies(cf)
                return cf  # type: ignore[return-value]
        return response

    @staticmethod
    def _looks_like_block_page(html: str) -> bool:
        head = html[:4000].lower()
        if "403 - forbidden" in head:
            return True
        if "security notifications" in head or "future protests and events" in head:
            return False
        return "noindex" in head and "robots" in head

    def _get_text_via_curl(self, url: str) -> str:
        curl = shutil.which("curl")
        if not curl:
            raise CurlNotAvailableError()
        # Some hosts (e.g. marble-arch.london) block the Chrome UA but accept a simple one.
        curl_user_agent = "Mozilla/5.0"
        proc = subprocess.run(
            [
                curl,
                "-sS",
                "-L",
                "--max-time",
                str(self.timeout),
                "-A",
                curl_user_agent,
                url,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise requests.RequestException(
                f"curl failed ({proc.returncode}): {proc.stderr.strip()}"
            )
        if not proc.stdout.strip():
            raise requests.RequestException("curl returned empty body")
        return proc.stdout

    def get_text(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
        referer: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> str:
        if not self._robots_allowed(url):
            raise requests.RequestException(f"robots.txt disallows fetch: {url}")
        self._throttle()
        logger.debug("GET %s", url)
        headers: dict[str, str] = {}
        if referer:
            headers["Referer"] = referer
            headers["Sec-Fetch-Site"] = "same-origin"
        if extra_headers:
            headers.update(extra_headers)
        try:
            response = self._request_get(
                url,
                params=params,
                headers=headers or None,
            )
            if response.status_code == 403:
                logger.info("403 from %s, retrying via curl fallback", url)
                return self._get_text_via_curl(url)
            response.raise_for_status()
            text = response.text
            if self._looks_like_block_page(text):
                return self._get_text_via_curl(url)
            return text
        except requests.exceptions.SSLError:
            logger.info("SSL error for %s, retrying via curl fallback", url)
            return self._get_text_via_curl(url)

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
    ) -> list[Any] | dict[str, Any]:
        if not self._robots_allowed(url):
            raise requests.RequestException(f"robots.txt disallows fetch: {url}")
        self._throttle()
        logger.debug("GET JSON %s", url)
        response = self._request_get(url, params=params)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, (list, dict)):
            return payload
        raise requests.RequestException(f"unexpected JSON type from {url}")

    def get_bytes(
        self,
        url: str,
        *,
        referer: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[bytes, str | None]:
        if not self._robots_allowed(url):
            raise requests.RequestException(f"robots.txt disallows fetch: {url}")
        self._throttle()
        headers: dict[str, str] = {}
        if referer:
            headers["Referer"] = referer
        if extra_headers:
            headers.update(extra_headers)
        response = self._request_get(url, headers=headers or None)
        response.raise_for_status()
        return response.content, response.headers.get("Content-Type")


def tfl_params() -> dict[str, str]:
    params: dict[str, str] = {}
    app_id = os.getenv("TFL_APP_ID")
    app_key = os.getenv("TFL_APP_KEY")
    if app_id:
        params["app_id"] = app_id
    if app_key:
        params["app_key"] = app_key
    return params
