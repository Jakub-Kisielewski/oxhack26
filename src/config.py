"""Paths and constants for the training pipeline.

Secrets come from the environment; see `.env.example`.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
ROUTE_RESEARCH_DIR = DATA_DIR / "route_research"
MODELS_DIR = DATA_DIR / "models"

DB_PATH = Path(os.environ.get("PROTEST_DB", DATA_DIR / "protest.duckdb"))
GRAPH_PATH = MODELS_DIR / "graph.pkl"
ROUTE_MODEL_PATH = MODELS_DIR / "route_model.json"
BACKTEST_PATH = MODELS_DIR / "backtest.json"

LEGAL_ZONES_PATH = (
    REPO_ROOT / "src" / "ingestion" / "route_research" / "seed" / "legal_zones.geojson"
)

# Central London reference (Trafalgar Square); used for weather and sanity checks.
LONDON_LAT = 51.5074
LONDON_LON = -0.1278
LONDON_LAT_MIN, LONDON_LAT_MAX = 51.2, 51.8
LONDON_LON_MIN, LONDON_LON_MAX = -0.6, 0.4

MARCH_HOURS = 4

# Training / labels
INTERPOLATED_WEIGHT = 0.3
WAYPOINT_LABEL_RADIUS_M = 150
DEFAULT_TURNOUT = 10_000
LOGIT_REG = 2.0
LOGIT_MAXITER = 90
BACKTEST_FOLD_MAXITER = 55
QUICK_BACKTEST_EVENTS = 5

# Route model / backtest
TARGET_PULL_LENGTH_M = 1000.0
ROLLOUT_STOP_DISTANCE_M = 75.0
DESTINATION_HIT_RADIUS_M = 250.0
DESTINATION_HISTORICAL_RADIUS_M = 150.0
DESTINATION_MATCH_RADIUS_M = 250.0
DESTINATION_MIN_PROB = 0.05
DESTINATION_MAX_CANDIDATES = 5
BASELINE_EPSILON_BOUNDS = (0.5, 0.99)
RANDOM_WALK_ROLLOUT_SEEDS = 5
CLUSTER_BOOTSTRAP_SAMPLES = 100

# Ingestion
BOUNDARY_BUFFER_M = 300.0
BOUNDARY_HULL_RATIO = 0.3
MAX_SNAP_DISTANCE_M = 350.0
# External APIs (no keys in repo)
TFL_API_BASE = "https://api.tfl.gov.uk"
OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
OVERPASS_URLS = (
    "https://overpass-api.de/api",
    "https://overpass.private.coffee/api",
    "https://overpass.kumi.systems/api",
)
