import streamlit as st
from src.database.db import get_connection, init_schema

st.set_page_config(page_title="London Protest Predictor", layout="wide")


@st.cache_resource
def bootstrap() -> bool:
    """Runs ONCE per server process, before any page opens a read-only connection.

    Ensures the schema exists; the data itself is loaded by `python ingest.py`
    (src/database/load.py). It uses a read-write connection that is CLOSED
    before the pages open their read-only ones, so we never hold two
    conflicting locks on the DB file.
    """
    con = get_connection(read_only=False)
    try:
        init_schema(con)
    finally:
        con.close()           # release the write lock before pages open read-only
    return True


bootstrap()

pages = [
    st.Page("src/ui/home.py",     title="Dashboard",       icon="📊", default=True),
    st.Page("src/ui/map_view.py", title="Zones 1 & 2 Map", icon="🗺️"),
]
st.navigation(pages).run()
