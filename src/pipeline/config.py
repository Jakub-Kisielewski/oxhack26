"""Pipeline settings, read from environment variables with defaults; shared by every process."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from src.pipeline.jamcam_poller import DEFAULT_BBOX

REPO_ROOT = Path(__file__).resolve().parents[2]

# Example march route from JAMCAM.md: Russell Sq -> Kingsway -> Aldwych -> Trafalgar Sq -> Whitehall
DEFAULT_ROUTE_POINTS = (
    (51.5212, -0.1236), (51.5168, -0.1197), (51.5130, -0.1173), (51.5074, -0.1277), (51.5033, -0.1260),
)


def _floats(text: str) -> tuple[float, ...]:
    return tuple(float(v) for v in text.split(","))


def parse_route_points(text: str) -> tuple[tuple[float, float], ...]:
    """'lat,lon;lat,lon;...' -> ((lat, lon), ...)."""
    points = tuple(_floats(p) for p in text.split(";") if p.strip())
    if any(len(p) != 2 for p in points):
        raise ValueError(f"ROUTE_POINTS must be 'lat,lon;lat,lon;...', got {text!r}")
    return points  # type: ignore[return-value]


def _bool(text: str) -> bool:
    return text.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    db_url: str = "sqlite:///data/pipeline.db"
    # camera registry
    route_points: tuple[tuple[float, float], ...] = DEFAULT_ROUTE_POINTS
    radius_m: float = 300.0
    central_bbox: tuple[float, float, float, float] = DEFAULT_BBOX
    camera_refresh_seconds: int = 600
    # poller
    poll_seconds: int = 15
    still_poll_seconds: int = 60
    tier1_enabled: bool = False
    head_threads: int = 16
    stale_after_s: int = 900
    chunk_seconds: int = 15
    # detection / features
    sample_fps: float = 2.0
    yolo_model: str = "yolov8n.pt"
    yolo_conf: float = 0.25
    yolo_imgsz: int = 640
    yolo_device: str = ""  # "" = auto (mps > cuda > cpu)
    # queue
    claim_timeout_s: int = 300
    max_attempts: int = 3
    # twin
    lag_seconds: int = 45
    twin_tick_seconds: int = 15


_PARSERS = {
    "DB_URL": ("db_url", str),
    "ROUTE_POINTS": ("route_points", parse_route_points),
    "RADIUS_M": ("radius_m", float),
    "CENTRAL_BBOX": ("central_bbox", _floats),
    "CAMERA_REFRESH_SECONDS": ("camera_refresh_seconds", int),
    "POLL_SECONDS": ("poll_seconds", int),
    "STILL_POLL_SECONDS": ("still_poll_seconds", int),
    "TIER1_ENABLED": ("tier1_enabled", _bool),
    "HEAD_THREADS": ("head_threads", int),
    "STALE_AFTER_S": ("stale_after_s", int),
    "CHUNK_SECONDS": ("chunk_seconds", int),
    "SAMPLE_FPS": ("sample_fps", float),
    "YOLO_MODEL": ("yolo_model", str),
    "YOLO_CONF": ("yolo_conf", float),
    "YOLO_IMGSZ": ("yolo_imgsz", int),
    "YOLO_DEVICE": ("yolo_device", str),
    "CLAIM_TIMEOUT_S": ("claim_timeout_s", int),
    "MAX_ATTEMPTS": ("max_attempts", int),
    "LAG_SECONDS": ("lag_seconds", int),
    "TWIN_TICK_SECONDS": ("twin_tick_seconds", int),
}


def load_settings(env: Mapping[str, str] = os.environ) -> Settings:
    """Build Settings from env vars named as in _PARSERS; unset vars keep their defaults."""
    kwargs = {attr: parse(env[name]) for name, (attr, parse) in _PARSERS.items() if env.get(name)}
    return Settings(**kwargs)


SETTINGS = load_settings()
