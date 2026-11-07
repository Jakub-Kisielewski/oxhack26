"""Tests for organiser event filtering."""

from __future__ import annotations

from ingestion.crawler.sources.organizers.filters import is_london_protest_event


class TestIsLondonProtestEvent:
    def test_london_march_is_kept(self) -> None:
        assert is_london_protest_event(
            title="National march for Palestine",
            body="Assemble 12pm at Hyde Park, London.",
            url="https://palestinecampaign.org/events/national-march/",
        )

    def test_manchester_march_is_rejected(self) -> None:
        assert not is_london_protest_event(
            title="Manchester march for Palestine",
            body="Assemble 12pm, Manchester city centre.",
            url="https://example.org/events/manchester-march/",
        )

    def test_london_agm_is_rejected(self) -> None:
        """Regression: meeting filter must not be unreachable (bug A2)."""
        assert not is_london_protest_event(
            title="Annual general meeting",
            body="Our London AGM, followed by a rally report-back.",
            url="https://example.org/events/agm-2026/",
        )

    def test_london_workshop_with_rally_in_body_only_rejected(self) -> None:
        assert not is_london_protest_event(
            title="PSC public meeting",
            body="London workshop with rally report-back.",
            url="https://example.org/events/meeting/",
        )

    def test_national_march_with_london_feeder_kept(self) -> None:
        assert is_london_protest_event(
            title="Manchester march for Palestine",
            body="London feeder assemble Hyde Park.",
            url="https://example.org/events/feeder/",
        )

    def test_no_london_terms_rejected(self) -> None:
        assert not is_london_protest_event(
            title="National demo",
            body="Assemble in the city centre.",
            url="https://example.org/events/demo/",
        )
