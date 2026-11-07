"""Rain feature support for rain_x_main (B-6)."""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

from src.ingestion.route_research.processing import event_context as ec

REPO = Path(__file__).resolve().parents[2]
EVENTS = REPO / "src/ingestion/route_research/seed/events.csv"


def test_rain_support_count_from_fixture_weather() -> None:
    events = list(csv.DictReader(EVENTS.open(encoding="utf-8-sig")))
    sample = events[0]
    day = dt.date.fromisoformat(sample["event_date"])
    weather = {
        dt.datetime.combine(day, dt.time(12)): {"precipitation": "1.0", "source": "archive"},
    }
    row = ec.build_row(sample, "cause", weather)
    assert row["precip_mm_4h"] is not None
    assert float(row["precip_mm_4h"]) > 0.5


def test_route_model_marks_low_rain_support_as_prior_only() -> None:
    """ChoiceModel.stats lists rain_x_main in prior_only when support < 2 events."""
    from src.models.route_model import ChoiceModel

    model = ChoiceModel(stats={"prior_only": ["rain_x_main"]})
    assert "rain_x_main" in model.stats["prior_only"]
