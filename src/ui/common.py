import streamlit as st
from src.contract import mapdata


@st.cache_resource
def get_db():
    """The shared read-only connection (same one the model layer uses)."""
    return mapdata.connection()
