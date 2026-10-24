import streamlit as st
from src.ui.common import get_db

st.title("London Protest Predictor")

with st.sidebar:
    st.header("Intelligence Controls")
    st.button("Query UK Police API")
    st.button("Fetch Live GTFS-RT Transit Data")
    st.button("Execute Hawkes Process Model")

st.subheader("Spatial Disruption Heatmap")
st.markdown("PyDeck 3D map will render here.")

if st.button("🗺️ Open Zone 1 & 2 Map", type="primary"):
    st.switch_page("src/ui/map_view.py")

conn = get_db()
