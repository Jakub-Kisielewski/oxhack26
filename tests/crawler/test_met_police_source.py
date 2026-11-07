"""Tests for Met Police article parsing helpers."""

from __future__ import annotations

from ingestion.crawler.sources.met_police import MetPoliceSource


def test_extract_section_12_route_finds_phrase() -> None:
    source = MetPoliceSource()
    text = (
        "Section 12(3) Public Order Act 1986\n"
        "must not deviate from the route, namely Whitehall to Parliament Square."
    )
    route = source._extract_section_12_route(text)
    assert route and "Whitehall" in route


def test_form_up_extraction() -> None:
    source = MetPoliceSource()
    text = "Participants will form up in Hyde Park at 12:00 hrs"
    assert source._extract_form_up(text) and "Hyde Park" in source._extract_form_up(text)
