"""Read-only access to the pipeline DB (data/pipeline.db) for the live map page."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.pipeline import db
from src.pipeline.config import SETTINGS


@st.cache_data(ttl=10)
def load_cameras() -> pd.DataFrame:
    """All registered cameras, active or not; empty if the pipeline DB doesn't exist yet."""
    if not db.sqlite_path(SETTINGS.db_url).exists():
        return pd.DataFrame()
    con = db.connect(SETTINGS.db_url, read_only=True)
    try:
        return pd.DataFrame(db.all_cameras(con))
    finally:
        con.close()
