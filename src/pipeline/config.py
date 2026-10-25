"""Pipeline settings, read from environment variables with defaults; shared by every process."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
DETECTOR_CONFIG_PATH = REPO_ROOT / "config" / "detector.json"  # written by scripts/bench_detect.py --write-config

# JAMCAM.md DEFAULT_BBOX (lat_min, lon_min, lat_max, lon_max). Defined here rather than imported from
# jamcam_poller so that the UI, which imports db -> config, never imports poller code.
DEFAULT_CENTRAL_BBOX = (51.495, -0.180, 51.530, -0.070)

# Example march route from JAMCAM.md: Russell Sq -> Kingsway -> Aldwych -> Trafalgar Sq -> Whitehall
DEFAULT_ROUTE_POINTS = (
    (51.5212, -0.1236), (51.5168, -0.1197), (51.5130, -0.1173), (51.5074, -0.1277), (51.5033, -0.1260),
)


def _floats(text: str) -> tuple[float, ...]:
    return tuple(float(v) for v in text.split(","))


def parse_route_points(text: str) -> tuple[tuple[float, float], ...]:
    """'lat,lon;lat,lon;...' -> ((lat, lon), ...)."""
    points = tuple(_floats(p) for p in text.split(";") if p.strip())
    if len(points) < 2 or any(len(p) != 2 for p in points):
        raise ValueError(f"ROUTE_POINTS must be at least two 'lat,lon' points separated by ';', got {text!r}")
    return points  # type: ignore[return-value]


def _bool(text: str) -> bool:
    return text.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    db_url: str = "sqlite:///data/pipeline.db"
    # camera registry
    route_points: tuple[tuple[float, float], ...] = DEFAULT_ROUTE_POINTS
    route_buffer_m: float = 300.0
    central_bbox: tuple[float, float, float, float] = DEFAULT_CENTRAL_BBOX
    camera_refresh_seconds: int = 600
    # {camera_id: tier}, relative to the repo root: shared (committed) file, then a local file that wins
    camera_overrides_path: str = "config/camera_overrides.json"
    local_camera_overrides_path: str = "data/camera_overrides.json"
    # poller: one loop per tier (tier 2 always on; clips every POLL_SECONDS)
    poll_seconds: int = 15
    tier1_enabled: bool = True
    tier1_kind: str = "clip"       # clip | still
    tier1_poll_seconds: int = 15
    tier0_enabled: bool = True
    tier0_kind: str = "still"
    tier0_poll_seconds: int = 60
    head_threads: int = 16
    tier2_reserved_threads: int = 4   # of head_threads, serve tier 2 only
    # bandwidth safety valve: this many tier-2 rounds in a row slower than POLL_SECONDS pause tier 0
    valve_slow_rounds: int = 2
    valve_pause_seconds: int = 300
    stale_after_s: int = 900
    chunk_seconds: int = 15
    # detection / features
    sample_fps: float = 2.0
    yolo_model: str = "yolov8n.pt"
    yolo_conf: float = 0.25
    yolo_imgsz: int = 640
    yolo_device: str = ""  # "" = auto (mps > cuda > cpu)
    yolo_sahi: bool = False          # SAHI sliced inference
    sahi_slice: int = 192            # slice size in px (352x288 frames -> 2x2 slices with overlap)
    count_agg: str = "median"        # aggregation of per-frame counts over a clip: median | p75
    min_box_h: float = 8.0           # drop person boxes shorter than this (px)
    banner_top_px: float = 0.0       # TfL overlay strips on 352x288 frames (see docs/STEP5_MEASUREMENTS.md)
    banner_bottom_px: float = 0.0
    low_luma: float = 50.0           # mean grey level below this = low light: count_sd x dark_sd_factor
    dark_sd_factor: float = 2.0
    # queue
    claim_timeout_s: int = 300
    max_attempts: int = 3
    # twin: rows are late if written more than LAG after frame_time; stills are polled less often
    lag_seconds: int = 60
    still_lag_seconds: int = 120
    too_old_margin_s: int = 10       # don't download uploads older than LAG - margin (processing must fit)
    twin_tick_seconds: int = 15

    def tier_description(self, tier: int) -> str:
        """What the poller does with a tier, e.g. 'central box: clips every 15 s'."""
        area = {2: "route", 1: "central box", 0: "rest of zones 1-2"}.get(tier, f"tier {tier}")
        polling = {2: (True, "clip", self.poll_seconds),
                   1: (self.tier1_enabled, self.tier1_kind, self.tier1_poll_seconds),
                   0: (self.tier0_enabled, self.tier0_kind, self.tier0_poll_seconds)}.get(tier)
        if polling is None or not polling[0]:
            return f"{area}: not polled"
        return f"{area}: {polling[1]}s every {polling[2]:g} s"

    def lag_for(self, kind: str) -> int:
        """LAG for observations of this media kind; uploads older than this are not downloaded."""
        return self.still_lag_seconds if kind == "still" else self.lag_seconds

    @property
    def enabled_kinds(self) -> set[str]:
        kinds = {"clip"}
        if self.tier1_enabled:
            kinds.add(self.tier1_kind)
        if self.tier0_enabled:
            kinds.add(self.tier0_kind)
        return kinds

    @property
    def twin_lag_seconds(self) -> int:
        """The twin's single LAG: it applies observations in event-time order, so it waits for the slowest kind."""
        return max(self.lag_for(k) for k in self.enabled_kinds)

    @property
    def route_lines(self) -> tuple[tuple[tuple[float, float], ...], ...]:
        """Route polylines that define tier 2. One line for now; Step 9 adds the top alternatives."""
        return (self.route_points,)


_PARSERS = {
    "DB_URL": ("db_url", str),
    "ROUTE_POINTS": ("route_points", parse_route_points),
    "ROUTE_BUFFER_M": ("route_buffer_m", float),
    "CENTRAL_BBOX": ("central_bbox", _floats),
    "CAMERA_REFRESH_SECONDS": ("camera_refresh_seconds", int),
    "CAMERA_OVERRIDES_PATH": ("camera_overrides_path", str),
    "LOCAL_CAMERA_OVERRIDES_PATH": ("local_camera_overrides_path", str),
    "POLL_SECONDS": ("poll_seconds", int),
    "TIER1_ENABLED": ("tier1_enabled", _bool),
    "TIER1_KIND": ("tier1_kind", str),
    "TIER1_POLL_SECONDS": ("tier1_poll_seconds", int),
    "TIER0_ENABLED": ("tier0_enabled", _bool),
    "TIER0_KIND": ("tier0_kind", str),
    "TIER0_POLL_SECONDS": ("tier0_poll_seconds", int),
    "HEAD_THREADS": ("head_threads", int),
    "TIER2_RESERVED_THREADS": ("tier2_reserved_threads", int),
    "VALVE_SLOW_ROUNDS": ("valve_slow_rounds", int),
    "VALVE_PAUSE_SECONDS": ("valve_pause_seconds", int),
    "STALE_AFTER_S": ("stale_after_s", int),
    "CHUNK_SECONDS": ("chunk_seconds", int),
    "SAMPLE_FPS": ("sample_fps", float),
    "YOLO_MODEL": ("yolo_model", str),
    "YOLO_CONF": ("yolo_conf", float),
    "YOLO_IMGSZ": ("yolo_imgsz", int),
    "YOLO_DEVICE": ("yolo_device", str),
    "YOLO_SAHI": ("yolo_sahi", _bool),
    "SAHI_SLICE": ("sahi_slice", int),
    "COUNT_AGG": ("count_agg", str),
    "MIN_BOX_H": ("min_box_h", float),
    "BANNER_TOP_PX": ("banner_top_px", float),
    "BANNER_BOTTOM_PX": ("banner_bottom_px", float),
    "LOW_LUMA": ("low_luma", float),
    "DARK_SD_FACTOR": ("dark_sd_factor", float),
    "CLAIM_TIMEOUT_S": ("claim_timeout_s", int),
    "MAX_ATTEMPTS": ("max_attempts", int),
    "LAG_SECONDS": ("lag_seconds", int),
    "STILL_LAG_SECONDS": ("still_lag_seconds", int),
    "TOO_OLD_MARGIN_S": ("too_old_margin_s", int),
    "TWIN_TICK_SECONDS": ("twin_tick_seconds", int),
}


DETECTOR_KEYS = ("yolo_model", "yolo_imgsz", "yolo_conf", "yolo_sahi", "sahi_slice", "count_agg", "min_box_h")


def load_detector_config(path: Path = DETECTOR_CONFIG_PATH) -> dict:
    """The benchmarked detector settings ({setting: value} for DETECTOR_KEYS); {} if there is no file."""
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    unknown = set(raw) - set(DETECTOR_KEYS)
    if unknown:
        raise ValueError(f"{path}: unknown keys {sorted(unknown)}; allowed: {DETECTOR_KEYS}")
    return raw


def load_settings(env: Mapping[str, str] = os.environ, detector_path: Path = DETECTOR_CONFIG_PATH) -> Settings:
    """Defaults, then config/detector.json, then env vars (named as in _PARSERS), later ones winning."""
    kwargs = dict(load_detector_config(detector_path))
    kwargs.update({attr: parse(env[name]) for name, (attr, parse) in _PARSERS.items() if env.get(name)})
    return Settings(**kwargs)


SETTINGS = load_settings()
