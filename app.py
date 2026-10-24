import streamlit as st
import duckdb

st.set_page_config(page_title="London Protest Predictor", layout="wide")
st.title("London Protest Predictor")

with st.sidebar:
    st.header("Intelligence Controls")
    st.button("Query UK Police API")
    st.button("Fetch Live GTFS-RT Transit Data")
    st.button("Execute Hawkes Process Model")

st.subheader("Spatial Disruption Heatmap")
st.markdown("PyDeck 3D map will render here.")

# Initialize in-process database
@st.cache_resource
def init_db():
    return duckdb.connect(database=':memory:')

conn = init_db()
