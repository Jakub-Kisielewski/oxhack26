"""Tests for event context derivation."""
from __future__ import annotations

import datetime as dt

from src.ingestion.route_research.processing import event_context as ec


def test_parse_start_defaults_noon() -> None:
    assert ec.parse_start("") == dt.time(12, 0)


def test_derive_cause_palestine() -> None:
    event = {"motivation": "March for Gaza", "organiser": "", "event_name": ""}
    assert ec.derive_cause(event) == "palestine"


def test_derive_cause_counter_protest_first() -> None:
    event = {"motivation": "Stand up to racism counter-protest", "organiser": "Palestine"}
    assert ec.derive_cause(event) == "anti_racism"


def test_precip_mm_4h_sums_window() -> None:
    day = dt.date(2024, 3, 1)
    start = dt.time(12, 0)
    weather = {
        dt.datetime(2024, 3, 1, 12, 0): {"precipitation": "0.2", "source": "archive"},
        dt.datetime(2024, 3, 1, 13, 0): {"precipitation": "0.3", "source": "archive"},
    }
    assert ec.precip_mm_4h(weather, day, start) == 0.5
