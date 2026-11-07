"""Registry of in-process route-research pipeline steps."""

from __future__ import annotations

from collections.abc import Callable

from src.ingestion.route_research.context import StepContext
from src.ingestion.route_research.processing.cause_targets import run as run_cause_targets
from src.ingestion.route_research.processing.edge_features import run as run_edge_features
from src.ingestion.route_research.processing.event_context import run as run_event_context
from src.ingestion.route_research.processing.normalize import run as run_normalize
from src.ingestion.route_research.processing.seed_coordinates import run as run_seed_coords
from src.ingestion.route_research.sources.download_boundary import run as run_boundary
from src.ingestion.route_research.sources.download_landmarks import run as run_landmarks
from src.ingestion.route_research.sources.download_osm import run as run_osm
from src.ingestion.route_research.sources.download_weather import run as run_weather

StepRun = Callable[[StepContext, list[str]], int]

REGISTRY: dict[str, StepRun] = {
    "boundary": run_boundary,
    "osm": run_osm,
    "landmarks": run_landmarks,
    "weather": run_weather,
    "seed-coords": run_seed_coords,
    "normalize": run_normalize,
    "edge-features": run_edge_features,
    "event-context": run_event_context,
    "cause-targets": run_cause_targets,
}


def run_named_step(name: str, context: StepContext, argv: list[str] | None = None) -> int:
    return REGISTRY[name](context, argv or [])
