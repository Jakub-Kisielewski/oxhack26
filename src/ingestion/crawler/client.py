from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import Any, Optional

import requests

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


class HttpClient:
    def __init__(
        self,
        timeout: int = 30,
        min_interval_sec: float = 0.35,
        *,
        cloudflare_fallback: bool = True,
    ):
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.timeout = timeout
        self.min_interval_sec = min_interval_sec
        self.cloudflare_fallback = cloudflare_fallback
        self._last_request_at = 0.0
        self._cloudscraper: Any = None

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval_sec:
            time.sleep(self.min_interval_sec - elapsed)

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
        params: Optional[dict] = None,
        headers: Optional[dict] = None,
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
            raise requests.RequestException("curl not found for SSL fallback")
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
        params: Optional[dict] = None,
        referer: Optional[str] = None,
        extra_headers: Optional[dict] = None,
    ) -> str:
        self._throttle()
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
            self._last_request_at = time.monotonic()
            if response.status_code == 403:
                return self._get_text_via_curl(url)
            response.raise_for_status()
            text = response.text
            if self._looks_like_block_page(text):
                return self._get_text_via_curl(url)
            return text
        except requests.exceptions.SSLError:
            self._last_request_at = time.monotonic()
            return self._get_text_via_curl(url)

    def get_json(
        self,
        url: str,
        *,
        params: Optional[dict] = None,
    ) -> object:
        self._throttle()
        response = self._request_get(url, params=params)
        self._last_request_at = time.monotonic()
        response.raise_for_status()
        return response.json()

    def get_bytes(
        self,
        url: str,
        *,
        referer: Optional[str] = None,
        extra_headers: Optional[dict] = None,
    ) -> tuple[bytes, Optional[str]]:
        self._throttle()
        headers: dict[str, str] = {}
        if referer:
            headers["Referer"] = referer
        if extra_headers:
            headers.update(extra_headers)
        response = self._request_get(url, headers=headers or None)
        self._last_request_at = time.monotonic()
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
