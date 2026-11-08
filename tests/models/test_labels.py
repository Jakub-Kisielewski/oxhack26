from __future__ import annotations

from src.models.labels import history_counts
from tests.models.conftest import make_event


def test_history_counts_one_per_event() -> None:
    e1 = make_event("e1", "2024-01-01", ["s0", "s1", "s1"])
    counts = history_counts([e1])
    assert counts["s1"] == 1


def test_history_counts_empty() -> None:
    assert history_counts([]) == {}


def test_history_counts_excludes_events_on_or_after_the_cutoff() -> None:
    early = make_event("e1", "2024-01-01", ["s0", "s1"])
    late = make_event("e2", "2025-01-01", ["s0", "s2"])
    counts = history_counts([early, late], before="2024-06-01")
    assert counts == {"s0": 1, "s1": 1}
    assert "s2" not in counts
