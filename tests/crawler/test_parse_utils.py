"""Tests for shared HTML and text parsers."""

from __future__ import annotations

from ingestion.crawler.parse_utils import (
    clean_html_text,
    first_match_group,
    iter_json_ld,
    parse_counter_protest_flag,
    parse_participant_estimate,
    parse_route_streets,
)


def test_clean_html_text_strips_tags() -> None:
    assert clean_html_text("<p>Hello <b>world</b></p>") == "Hello world"


def test_parse_participant_between() -> None:
    low, high, text = parse_participant_estimate("between 1,000 and 2,000 people")
    assert low == 1000 and high == 2000 and text


def test_parse_route_streets_splits_on_via() -> None:
    streets = parse_route_streets("Whitehall via Parliament Square")
    assert "Whitehall" in streets[0]
    assert any("Parliament" in s for s in streets)


def test_counter_protest_flag() -> None:
    assert parse_counter_protest_flag("no counter-protest expected") is False
    assert parse_counter_protest_flag("counter-protest likely") is True


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
