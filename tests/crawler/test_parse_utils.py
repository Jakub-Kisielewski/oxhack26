"""Tests for shared HTML and text parsers."""

from __future__ import annotations

from ingestion.crawler.parse_utils import (
    clean_html_text,
    first_match_group,
    iter_json_ld,
    parse_participant_estimate,
    turnout_estimate_from_text,
)


def test_clean_html_text_strips_tags() -> None:
    assert clean_html_text("<p>Hello <b>world</b></p>") == "Hello world"


def test_parse_participant_between() -> None:
    low, high, text = parse_participant_estimate("between 1,000 and 2,000 people")
    assert low == 1000 and high == 2000 and text


def test_turnout_estimate_from_range() -> None:
    assert turnout_estimate_from_text("between 1,000 and 3,000 people") == 2000


def test_iter_json_ld_skips_malformed() -> None:
    html = """
    <script type="application/ld+json">{broken</script>
    <script type="application/ld+json">{"@type": "Event", "name": "Demo"}</script>
    """
    payloads = list(iter_json_ld(html, schema_type="Event"))
    assert len(payloads) == 1
    assert payloads[0]["name"] == "Demo"


def test_first_match_group_returns_first_hit() -> None:
    text = "form up in Hyde Park at 12"
    assert first_match_group([r"form up in (.+?) at"], text) == "Hyde Park"
