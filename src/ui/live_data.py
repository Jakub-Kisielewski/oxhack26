"""Read-only access to the pipeline DB (data/pipeline.db) for the live map page."""
from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from src.pipeline import db
from src.pipeline.config import SETTINGS


def _connect():
    """A read-only connection, or None if the pipeline DB doesn't exist yet."""
    if not db.sqlite_path(SETTINGS.db_url).exists():
        return None
    return db.connect(SETTINGS.db_url, read_only=True)


@st.cache_data(ttl=10)
def load_cameras() -> pd.DataFrame:
    """All registered cameras, active or not, with their latest reading from the last hour."""
    con = _connect()
    if con is None:
        return pd.DataFrame()
    try:
        return pd.DataFrame(db.latest_observation_per_camera(con, since_minutes=60, active_only=False))
    finally:
        con.close()


@st.cache_data(ttl=10)
def load_history(camera_id: str, minutes: int = 60) -> pd.DataFrame:
    """One camera's readings over the last `minutes`, with frame_time parsed."""
    con = _connect()
    if con is None:
        return pd.DataFrame()
    try:
        df = pd.DataFrame(db.camera_history(con, camera_id, minutes))
    finally:
        con.close()
    if not df.empty:
        df["frame_time"] = pd.to_datetime(df["frame_time"], utc=True)
    return df


@st.cache_data(ttl=10)
def load_queue_stats() -> dict[str, Any] | None:
    con = _connect()
    if con is None:
        return None
    try:
        return db.queue_stats(con)
    finally:
        con.close()


@st.cache_data(ttl=10)
def load_tier0_pause() -> dict[str, Any] | None:
    """The bandwidth valve's current tier-0 pause, if any."""
    con = _connect()
    if con is None:
        return None
    try:
        return db.active_pause(con, "tier0_paused")
    finally:
        con.close()
