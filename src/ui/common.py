import streamlit as st
from src.database.db import get_connection


@st.cache_resource
def get_db():
    """Shared read-only connection for all UI pages."""
    return get_connection(read_only=True)
