"""HTML cleanup and shared text parsing helpers for crawlers."""

from __future__ import annotations

import html
import json
import logging
import re
from collections.abc import Iterator, Sequence
from typing import Any

logger = logging.getLogger(__name__)

_WS = re.compile(r"\s+")


def clean_html_text(raw: str) -> str:
    """Strip tags and normalise whitespace in HTML or plain text."""
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw)
    text = re.sub(r"(?s)<br\s*/?>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    return _WS.sub(" ", text).strip()


def extract_paragraphs(raw_html: str, min_len: int = 25) -> list[str]:
    """Return paragraph texts from HTML that meet a minimum length."""
    paragraphs: list[str] = []
    for match in re.finditer(r"(?is)<p[^>]*>(.*?)</p>", raw_html):
        text = clean_html_text(match.group(1))
        if len(text) >= min_len:
            paragraphs.append(text)
    return paragraphs


def iter_json_ld(raw_html: str, *, schema_type: str | None = None) -> Iterator[dict[str, Any]]:
    """Yield each JSON-LD payload embedded in a page."""
    for match in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', raw_html, re.S):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            logger.debug("skipping malformed JSON-LD block")
            continue
        if not isinstance(payload, dict):
            continue
        if schema_type is None or payload.get("@type") == schema_type:
            yield payload


def first_match_group(patterns: Sequence[str], text: str, *, group: int = 1) -> str | None:
    """Return the first capture group from the first pattern that matches."""
    for pattern in patterns:
        if match := re.search(pattern, text, re.I | re.S):
            return clean_html_text(match.group(group))
    return None


def parse_participant_estimate(text: str) -> tuple[int | None, int | None, str | None]:
    """Parse human-readable crowd size text into min/max bounds."""
    lowered = text.lower()
    if "unknown" in lowered and not re.search(r"\d", text):
        return None, None, text.strip()

    between = re.search(r"between\s+([\d,]+)\s+and\s+([\d,]+)\s+people", text, re.I)
    if between:
        low = int(between.group(1).replace(",", ""))
        high = int(between.group(2).replace(",", ""))
        return low, high, between.group(0)

    plus = re.search(r"([\d,]+)\s*\+", text)
    if plus:
        val = int(plus.group(1).replace(",", ""))
        return val, None, plus.group(0)

    range_dash = re.search(
        r"([\d,]+)\s*[-–]\s*([\d,]+)\s*(?:people|participants|expected)?",
        text,
        re.I,
    )
    if range_dash:
        low = int(range_dash.group(1).replace(",", ""))
        high = int(range_dash.group(2).replace(",", ""))
        return low, high, range_dash.group(0)

    single = re.search(
        r"(?:approximately|around|about|up to|expected)?\s*([\d,]+)\s*(?:people|participants|expected)?",
        text,
        re.I,
    )
    if single:
        val = int(single.group(1).replace(",", ""))
        return val, val, single.group(0)

    return None, None, None


def parse_route_streets(route_text: str) -> list[str]:
    """Split a free-text route into street or segment labels."""
    if not route_text:
        return []
    parts = re.split(r"\s*(?:>|,| and | onto | via | travelling via )\s*", route_text, flags=re.I)
    streets: list[str] = []
    for part in parts:
        cleaned = part.strip(" .")
        cleaned = re.sub(r"^(?:namely|route:?|location:?)\s*", "", cleaned, flags=re.I)
        if cleaned and len(cleaned) > 2:
            streets.append(cleaned)
    return streets


def parse_counter_protest_flag(text: str) -> bool | None:
    """Detect whether copy mentions an expected counter-protest."""
    lowered = text.lower()
    if re.search(r"no counter[- ]protest", lowered):
        return False
    if "counter-protest" in lowered or "counter protest" in lowered:
        return True
    return None
