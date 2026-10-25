"""Per-chunk features (JAMCAM.md §5): median people count, density/speed/heading if calibrated, frame quality."""
from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

import cv2
import numpy as np

from src.pipeline.boxes import filter_boxes
from src.pipeline.config import REPO_ROOT, SETTINGS, Settings
from src.pipeline.correction import Correction, correct

PROC_VERSION = "features-v1"
CALIBRATION_DIR = REPO_ROOT / "calibration"

BLANK_STD = 6.0           # grey-level std below this = near-uniform image (TfL placeholder / dead feed)
BLANK_MODE_FRACTION = 0.85
DARK_MEAN = 20.0          # mean grey level below this = too dark; people are still counted
REAIMED_SHIFT_PX = 15.0   # global shift vs the calibration frame above this = camera moved


class PersonDetector(Protocol):
    name: str

    def detect(self, frames: list[np.ndarray]) -> list[np.ndarray]: ...


@dataclass(frozen=True)
class Calibration:
    """Ground-plane homography: image pixels -> metres east/north of (lat0, lon0)."""
    H: np.ndarray
    lat0: float
    lon0: float
    area_m2: float | None = None  # visible pavement area, for density

    @classmethod
    def from_json(cls, text: str) -> "Calibration":
        d = json.loads(text)
        return cls(np.array(d["H"], dtype=float), d["lat0"], d["lon0"], d.get("area_m2"))

    def to_json(self) -> str:
        return json.dumps({"H": self.H.tolist(), "lat0": self.lat0, "lon0": self.lon0, "area_m2": self.area_m2})

    def to_ground(self, pts_px: np.ndarray) -> np.ndarray:
        """(n, 2) pixel points -> (n, 2) metres (east, north)."""
        return cv2.perspectiveTransform(np.asarray(pts_px, dtype=np.float64).reshape(-1, 1, 2), self.H).reshape(-1, 2)


def sample_clip(data: bytes, sample_fps: float) -> tuple[list[np.ndarray], float]:
    """Frames sampled at ~sample_fps from an MP4 (via a temp file deleted in finally) and seconds between them."""
    fd, path = tempfile.mkstemp(suffix=".mp4")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        cap = cv2.VideoCapture(path)
        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            step = max(1, round(fps / sample_fps))
            frames, i = [], 0
            while cap.grab():
                if i % step == 0:
                    ok, frame = cap.retrieve()
                    if ok:
                        frames.append(frame)
                i += 1
        finally:
            cap.release()
        return frames, step / fps
    finally:
        os.remove(path)


def decode_still(data: bytes) -> list[np.ndarray]:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    return [] if img is None else [img]


def reference_frame(camera_id: str) -> np.ndarray | None:
    """The frame saved at calibration time (calibration/<id>.jpg), if any."""
    path = CALIBRATION_DIR / f"{camera_id}.jpg"
    return cv2.imread(str(path)) if path.exists() else None


def frame_quality(frame: np.ndarray, reference: np.ndarray | None = None) -> str:
    """blank | dark | reaimed | ok for one representative frame."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mode_fraction = np.bincount(gray.ravel(), minlength=256).max() / gray.size
    if gray.std() < BLANK_STD or mode_fraction > BLANK_MODE_FRACTION:
        return "blank"
    if gray.mean() < DARK_MEAN:
        return "dark"
    if reference is not None and reference.shape == frame.shape:
        ref = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY).astype(np.float32)
        (dx, dy), _ = cv2.phaseCorrelate(ref, gray.astype(np.float32))
        if math.hypot(dx, dy) > REAIMED_SHIFT_PX:
            return "reaimed"
    return "ok"


def ground_velocity(frames: list[np.ndarray], boxes: list[np.ndarray], dt: float,
                    calib: Calibration) -> tuple[float | None, float | None]:
    """Mean crowd velocity from Farneback flow inside person boxes only, as (speed m/s, heading deg from north)."""
    vectors = []
    grays = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]
    for g0, g1, frame_boxes in zip(grays, grays[1:], boxes):
        if len(frame_boxes) == 0:
            continue
        flow = cv2.calcOpticalFlowFarneback(g0, g1, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        h, w = g0.shape
        for x0, y0, x1, y1 in frame_boxes[:, :4]:
            xa, ya, xb, yb = max(0, int(x0)), max(0, int(y0)), min(w, int(x1)), min(h, int(y1))
            if xb <= xa or yb <= ya:
                continue
            dx, dy = flow[ya:yb, xa:xb].reshape(-1, 2).mean(axis=0)
            foot = np.array([[(x0 + x1) / 2, y1]])
            start, end = calib.to_ground(foot)[0], calib.to_ground(foot + [dx, dy])[0]
            vectors.append((end - start) / dt)
    if not vectors:
        return None, None
    east, north = np.mean(vectors, axis=0)
    return float(math.hypot(east, north)), float(math.degrees(math.atan2(east, north)) % 360)


def aggregate_counts(counts: list[int], how: str = "median") -> float:
    """One count for a clip from its per-frame counts: median, or p75 (catches people hidden in some frames)."""
    if how == "median":
        return float(np.median(counts))
    if how == "p75":
        return float(np.percentile(counts, 75))
    raise ValueError(f"count aggregation must be 'median' or 'p75', got {how!r}")


def detect_filtered(frames: list[np.ndarray], detector: PersonDetector, roi=None,
                    settings: Settings = SETTINGS) -> list[np.ndarray]:
    """Per-frame person boxes after the ROI, banner and minimum-height filters."""
    return [filter_boxes(b, f.shape, roi, settings=settings) for b, f in zip(detector.detect(frames), frames)]


def extract_features(data: bytes, camera: Mapping[str, Any], detector: PersonDetector, kind: str = "clip",
                     settings: Settings = SETTINGS, rois: Mapping[str, Any] | None = None,
                     correction: Correction | None = None) -> dict[str, Any]:
    """Observation fields for one chunk (a clip or a still). Frames exist only in memory."""
    if kind == "still":
        frames, dt = decode_still(data), 0.0
    else:
        frames, dt = sample_clip(data, settings.sample_fps)
    out: dict[str, Any] = {"lat": camera.get("lat"), "lon": camera.get("lon"), "people": None, "raw_people": None,
                           "count_sd": None, "luma": None, "density": None, "speed": None, "heading": None,
                           "proc_version": f"{PROC_VERSION}+{detector.name}"}
    if not frames:
        return {**out, "quality": "blank"}
    middle = frames[len(frames) // 2]
    out["luma"] = float(cv2.cvtColor(middle, cv2.COLOR_BGR2GRAY).mean())
    out["quality"] = frame_quality(middle, reference_frame(camera["camera_id"]))
    if out["quality"] == "blank":
        return out
    boxes = detect_filtered(frames, detector, (rois or {}).get(camera["camera_id"]), settings)
    out["raw_people"] = aggregate_counts([len(b) for b in boxes], settings.count_agg)
    out["people"], out["count_sd"] = correct(out["raw_people"], camera["camera_id"], out["quality"], out["luma"],
                                             correction or Correction(), settings)
    calib = Calibration.from_json(camera["homography"]) if camera.get("homography") else None
    if calib is not None:
        if calib.area_m2:
            out["density"] = out["people"] / calib.area_m2
        if kind == "clip" and len(frames) > 1:
            out["speed"], out["heading"] = ground_velocity(frames, boxes, dt, calib)
    return out
