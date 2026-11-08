"""Cached graph and model loads for Streamlit."""

from __future__ import annotations

import streamlit as st

from src.config import DB_PATH, GRAPH_PATH, ROUTE_MODEL_PATH
from src.models.graph import MarchGraph, load_graph
from src.models.labels import TrainingEvent, read_events
from src.models.route_model import ChoiceModel


@st.cache_resource
def get_graph() -> MarchGraph:
    """Street graph from ``data/models/graph.pkl``."""
    return load_graph(GRAPH_PATH)


@st.cache_resource
def get_full_model() -> ChoiceModel:
    """Full-data conditional logit from ``data/models/route_model.json``."""
    return ChoiceModel.from_json(ROUTE_MODEL_PATH)


@st.cache_data
def net_distances_for(dest_lon: float, dest_lat: float) -> dict[str, float]:
    """Network distances to a destination; keyed by rounded coordinates."""
    g = get_graph()
    return g.network_distances_to((dest_lon, dest_lat))


@st.cache_data
def load_training_events() -> tuple[TrainingEvent, ...]:
    """Labelled marches from DuckDB; empty when the database is missing."""
    if not DB_PATH.is_file():
        return ()
    return tuple(read_events(get_graph()))
