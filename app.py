import duckdb
import streamlit as st
from src.database.db import get_connection, init_schema

st.set_page_config(page_title="London Protest Predictor", page_icon=":material/groups:", layout="wide")


@st.cache_resource
def bootstrap() -> bool:
    """Runs ONCE per server process, before any page opens a read-only connection.

    Ensures the schema exists; the data itself is loaded by `python ingest.py`
    (src/database/load.py). It uses a read-write connection that is CLOSED
    before the pages open their read-only ones, so we never hold two
    conflicting locks on the DB file.
    """
    try:
        con = get_connection(read_only=False)
    except duckdb.IOException:
        # Another process (model training, a notebook, a second app) has the file open.
        # The loader already created the schema, so pages can still read it.
        return False
    try:
        init_schema(con)
    finally:
        con.close()           # release the write lock before pages open read-only
    return True


bootstrap()

pages = {
    "Overview": [
        st.Page("src/ui/pages/home.py", title="Dashboard", icon=":material/dashboard:", default=True),
    ],
    "Predict": [
        st.Page("src/ui/pages/route_predictor.py", title="Route predictor", icon=":material/explore:"),
        st.Page("src/ui/pages/planned_route.py", title="Planned route", icon=":material/route:"),
    ],
    "Decide": [
        st.Page("src/ui/pages/shopkeeper.py", title="Shopkeeper advice", icon=":material/storefront:"),
        st.Page("src/ui/pages/police.py", title="Police allocation", icon=":material/local_police:"),
    ],
    "Explore": [
        st.Page("src/ui/pages/model_insights.py", title="Model insights", icon=":material/insights:"),
        st.Page("src/ui/pages/map_explorer.py", title="Map explorer", icon=":material/map:"),
    ],
}
st.navigation(pages).run()
