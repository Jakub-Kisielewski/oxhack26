from __future__ import annotations

import os
import time
from typing import Optional

import requests

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


class HttpClient:
    def __init__(self, timeout: int = 30, min_interval_sec: float = 0.35):
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.timeout = timeout
        self.min_interval_sec = min_interval_sec
        self._last_request_at = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval_sec:
            time.sleep(self.min_interval_sec - elapsed)

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
        if extra_headers:
            headers.update(extra_headers)
        response = self.session.get(
            url,
            params=params,
            headers=headers or None,
            timeout=self.timeout,
        )
        self._last_request_at = time.monotonic()
        response.raise_for_status()
        return response.text

    def get_json(
        self,
        url: str,
        *,
        params: Optional[dict] = None,
    ) -> object:
        self._throttle()
        response = self.session.get(url, params=params, timeout=self.timeout)
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
        response = self.session.get(
            url,
            headers=headers or None,
            timeout=self.timeout,
        )
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
