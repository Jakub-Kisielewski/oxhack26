from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from src.pipeline import db
from src.pipeline.config import REPO_ROOT, Settings
from src.ui import live_data
from src.ui.live_display import NO_DATA_COLOUR, age_text, cache_buster, people_colour, prepare, tier_label

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def pipeline_db(monkeypatch, db_url, con):
    monkeypatch.setattr(live_data, "SETTINGS", replace(Settings(), db_url=db_url))
    st.cache_data.clear()
    yield con
    st.cache_data.clear()


def _cam(camera_id, tier, active=True):
    return {"camera_id": camera_id, "name": f"Cam {camera_id}", "lat": 51.508, "lon": -0.128, "view": None,
            "image_url": f"https://example.invalid/{camera_id}.jpg",
            "video_url": f"https://example.invalid/{camera_id}.mp4", "tier": tier, "active": active}


# ------------------------------------------------------------------- display rules

def test_people_colour_ramp():
    assert people_colour(0)[:3] == [255, 237, 160]
    assert people_colour(10)[:3] == [128, 0, 38] == people_colour(50)[:3]
    reds = [people_colour(p)[1] for p in (0, 1, 2, 5, 10)]
    assert reds == sorted(reds, reverse=True)  # darker as counts rise


def test_tier_label_is_capitalised_settings_text():
    assert tier_label(2) == "Route: clips every 15 s"


def test_age_text():
    assert age_text(None) == "no reading in the last hour"
    assert age_text(45) == "45 s ago" and age_text(600) == "10 min ago"


def test_prepare_greys_out_missing_stale_and_inactive_readings():
    rows = pd.DataFrame([
        {"camera_id": "fresh", "tier": 2, "active": 1, "people": 4.0, "frame_time": db.to_iso(NOW - timedelta(minutes=3))},
        {"camera_id": "stale", "tier": 2, "active": 1, "people": 4.0, "frame_time": db.to_iso(NOW - timedelta(minutes=20))},
        {"camera_id": "none", "tier": 0, "active": 1, "people": None, "frame_time": None},
        {"camera_id": "off", "tier": 1, "active": 0, "people": 4.0, "frame_time": db.to_iso(NOW - timedelta(minutes=1))},
    ]).assign(name="n", view=None)
    out = prepare(rows, NOW).set_index("camera_id")
    assert out.loc["fresh", "fresh"] and out.loc["fresh", "color"] == people_colour(4)
    for cid in ("stale", "none", "off"):
        assert not out.loc[cid, "fresh"] and out.loc[cid, "color"] == NO_DATA_COLOUR
    assert out.loc["fresh", "people_txt"] == "4 people" and out.loc["stale", "people_txt"] == "no current count"
    assert out.loc["fresh", "radius"] > out.loc["off", "radius"] > out.loc["none", "radius"]


def test_cache_buster_follows_the_frame_time():
    row = pd.Series({"frame_time": pd.Timestamp(NOW)})
    assert cache_buster(row) == int(NOW.timestamp())
    assert cache_buster(pd.Series({"frame_time": pd.NaT})) % 60 == 0


# ------------------------------------------------------------------- data access

def test_load_cameras_includes_inactive_and_latest_reading(pipeline_db):
    db.upsert_cameras(pipeline_db, [_cam("A", 2), _cam("B", 0, active=False)])
    db.insert_observation(pipeline_db, {"camera_id": "A", "frame_time": db.utc_now() - timedelta(minutes=2),
                                        "people": 3, "quality": "ok"})
    df = live_data.load_cameras().set_index("camera_id")
    assert df.loc["A", "people"] == 3 and df.loc["B", "active"] == 0 and pd.isna(df.loc["B", "people"])


def test_loaders_without_db(monkeypatch, tmp_path):
    monkeypatch.setattr(live_data, "SETTINGS", replace(Settings(), db_url=f"sqlite:///{tmp_path / 'none.db'}"))
    st.cache_data.clear()
    assert live_data.load_cameras().empty and live_data.load_history("A").empty
    assert live_data.load_queue_stats() is None


def test_load_history_and_queue_stats(pipeline_db):
    for m, n in [(50, 1), (20, 2), (5, 3)]:
        db.insert_observation(pipeline_db, {"camera_id": "A", "frame_time": db.utc_now() - timedelta(minutes=m),
                                            "people": n, "proc_ms": 100})
    hist = live_data.load_history("A")
    assert list(hist["people"]) == [1, 2, 3] and str(hist["frame_time"].dt.tz) == "UTC"
    assert live_data.load_queue_stats()["observations_recent"] == 3


# ------------------------------------------------------------------- page

def test_page_renders_map_sidebar_and_busiest(pipeline_db):
    db.upsert_cameras(pipeline_db, [_cam("A", 2), _cam("B", 1), _cam("C", 0, active=False)])
    db.insert_observation(pipeline_db, {"camera_id": "B", "frame_time": db.utc_now() - timedelta(minutes=1),
                                        "people": 7, "quality": "ok", "kind": "still", "proc_ms": 30})
    at = AppTest.from_file(str(REPO_ROOT / "src/ui/live_map.py"), default_timeout=30).run()
    assert not at.exception
    assert at.get("deck_gl_json_chart")
    assert at.sidebar.metric[1].value == "0 / 0"  # queue
    busiest = at.dataframe[0].value
    assert list(busiest["name"]) == ["Cam B"] and busiest["people"].iloc[0] == 7
