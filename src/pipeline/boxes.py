"""Person-box filters applied after detection: per-camera ROI, TfL overlay banners, minimum box height."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

import cv2
import numpy as np

from src.pipeline.config import REPO_ROOT, SETTINGS, Settings

ROIS_PATH = REPO_ROOT / "config" / "camera_rois.json"

Point = Sequence[float]


def load_rois(path: Path = ROIS_PATH) -> dict[str, list[list[float]]]:
    """{camera_id: [[x, y], ...]} polygons in image pixels; a missing file means no ROIs."""
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a JSON object {{camera_id: [[x, y], ...]}}")
    bad = [cid for cid, poly in raw.items() if not isinstance(poly, list) or len(poly) < 3
           or any(len(p) != 2 for p in poly)]
    if bad:
        raise ValueError(f"{path}: polygons need at least 3 [x, y] points: {bad}")
    return raw


def foot_points(boxes: np.ndarray) -> np.ndarray:
    """(n, 2) bottom-centre of each x0, y0, x1, y1[, conf] box."""
    boxes = np.asarray(boxes, dtype=float)
    return np.column_stack([(boxes[:, 0] + boxes[:, 2]) / 2, boxes[:, 3]])


def inside_polygon(points: np.ndarray, polygon: Sequence[Point]) -> np.ndarray:
    """Boolean mask: points inside (or on the edge of) the polygon."""
    contour = np.asarray(polygon, dtype=np.float32).reshape(-1, 1, 2)
    return np.array([cv2.pointPolygonTest(contour, (float(x), float(y)), False) >= 0 for x, y in points], dtype=bool)


def banner_rects(width: int, height: int, settings: Settings = SETTINGS) -> list[tuple[float, float, float, float]]:
    """TfL overlay boxes (date/time, logo, camera name) as (x0, y0, x1, y1), scaled from 352x288 to this frame."""
    sx, sy = width / 352, height / 288
    return [(x0 * sx, y0 * sy, x1 * sx, y1 * sy) for x0, y0, x1, y1 in settings.banner_rects_px]


def filter_boxes(boxes: np.ndarray, frame_shape: tuple[int, ...], roi: Sequence[Point] | None = None,
                 min_box_h: float | None = None, settings: Settings = SETTINGS) -> np.ndarray:
    """Keep boxes at least min_box_h tall whose foot point is outside the TfL banners and inside the ROI (if any)."""
    boxes = np.asarray(boxes, dtype=float)
    if boxes.size == 0:
        return boxes.reshape(0, boxes.shape[1] if boxes.ndim == 2 else 5)
    min_box_h = settings.min_box_h if min_box_h is None else min_box_h
    height, width = frame_shape[:2]
    keep = (boxes[:, 3] - boxes[:, 1]) >= min_box_h
    feet = foot_points(boxes)
    for x0, y0, x1, y1 in banner_rects(width, height, settings):
        keep &= ~((feet[:, 0] >= x0) & (feet[:, 0] <= x1) & (feet[:, 1] >= y0) & (feet[:, 1] <= y1))
    if roi:
        keep &= inside_polygon(feet, roi)
    return boxes[keep]
