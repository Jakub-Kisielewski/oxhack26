from __future__ import annotations

import html
import re
from typing import Optional

_WS = re.compile(r"\s+")


def clean_html_text(raw: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw)
    text = re.sub(r"(?s)<br\s*/?>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    return _WS.sub(" ", text).strip()


def extract_paragraphs(raw_html: str, min_len: int = 25) -> list[str]:
    paragraphs: list[str] = []
    for match in re.finditer(r"(?is)<p[^>]*>(.*?)</p>", raw_html):
        text = clean_html_text(match.group(1))
        if len(text) >= min_len:
            paragraphs.append(text)
    return paragraphs


def parse_participant_estimate(text: str) -> tuple[Optional[int], Optional[int], Optional[str]]:
    lowered = text.lower()
    if "unknown" in lowered and not re.search(r"\d", text):
        return None, None, text.strip()

    between = re.search(
        r"between\s+([\d,]+)\s+and\s+([\d,]+)\s+people", text, re.I
    )
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


def parse_counter_protest_flag(text: str) -> Optional[bool]:
    lowered = text.lower()
    if re.search(r"no counter[- ]protest", lowered):
        return False
    if "counter-protest" in lowered or "counter protest" in lowered:
        return True
    return None
