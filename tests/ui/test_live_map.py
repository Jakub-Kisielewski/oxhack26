from dataclasses import replace

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from src.pipeline import db
from src.pipeline.config import REPO_ROOT, Settings
from src.ui import live_data


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


def test_load_cameras_includes_inactive(pipeline_db):
    db.upsert_cameras(pipeline_db, [_cam("A", 2), _cam("B", 0, active=False)])
    df = live_data.load_cameras()
    assert sorted(zip(df["camera_id"], df["active"])) == [("A", 1), ("B", 0)]


def test_load_cameras_empty_without_db(monkeypatch, tmp_path):
    monkeypatch.setattr(live_data, "SETTINGS", replace(Settings(), db_url=f"sqlite:///{tmp_path / 'none.db'}"))
    st.cache_data.clear()
    assert live_data.load_cameras().empty


def test_page_renders_map_and_tier_summary(pipeline_db):
    db.upsert_cameras(pipeline_db, [_cam("A", 2), _cam("B", 1), _cam("C", 0, active=False)])
    at = AppTest.from_file(str(REPO_ROOT / "src/ui/live_map.py"), default_timeout=30).run()
    assert not at.exception
    assert at.get("deck_gl_json_chart")
    summary = at.dataframe[0].value
    assert list(summary["tier"]) == [2, 1, 0] and list(summary["active"]) == [1, 1, 0]
