"""YOLO person detector: loaded once per process, one batched predict per chunk, persons only (no tracking)."""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from src.pipeline.config import REPO_ROOT, SETTINGS, Settings

log = logging.getLogger(__name__)

MODELS_DIR = REPO_ROOT / "models"  # weights (*.pt is gitignored)
PERSON = 0


def pick_device(override: str = "") -> str:
    """Env override if set, else mps > cuda > cpu."""
    if override:
        return override
    import torch

    if torch.backends.mps.is_available():
        return "mps"
    return "cuda" if torch.cuda.is_available() else "cpu"


def weights_path(model: str) -> str:
    """A bare weights name (e.g. 'yolov8n.pt') resolves to models/, where ultralytics downloads it."""
    path = Path(model)
    if path.is_absolute() or path.parent != Path("."):
        return str(path)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    return str(MODELS_DIR / path)


class Detector:
    """Wraps one ultralytics YOLO model. detect() never tracks, never looks at faces, never writes frames."""

    def __init__(self, settings: Settings = SETTINGS, model: str | None = None, imgsz: int | None = None,
                 conf: float | None = None, device: str | None = None, sahi: bool | None = None,
                 sahi_slice: int | None = None):
        from ultralytics import YOLO

        self.model_name = model or settings.yolo_model
        self.imgsz = imgsz or settings.yolo_imgsz
        self.conf = conf if conf is not None else settings.yolo_conf
        self.device = pick_device(device if device is not None else settings.yolo_device)
        self.sahi = settings.yolo_sahi if sahi is None else sahi
        self.sahi_slice = sahi_slice or settings.sahi_slice
        weights = weights_path(self.model_name)
        self.model = YOLO(weights)
        if self.sahi:
            from sahi import AutoDetectionModel

            self._sahi_model = AutoDetectionModel.from_pretrained(
                model_type="ultralytics", model_path=weights, confidence_threshold=self.conf,
                device=self.device, image_size=self.imgsz)
        log.info("detector %s on %s", self.name, self.device)

    @property
    def name(self) -> str:
        return f"{Path(self.model_name).stem}@{self.imgsz}" + ("+sahi" if self.sahi else "")

    def detect(self, frames: list[np.ndarray]) -> list[np.ndarray]:
        """One batched predict over BGR frames; per frame an (n, 5) array of x0, y0, x1, y1, confidence."""
        if not frames:
            return []
        if self.sahi:
            return [self._sliced(f) for f in frames]
        results = self.model.predict(frames, classes=[PERSON], conf=self.conf, imgsz=self.imgsz,
                                     device=self.device, verbose=False)
        return [np.hstack([r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy()[:, None]]) for r in results]

    def _sliced(self, frame: np.ndarray) -> np.ndarray:
        """SAHI: overlapping slices plus the full frame, merged; persons only."""
        from sahi.predict import get_sliced_prediction

        result = get_sliced_prediction(np.ascontiguousarray(frame[:, :, ::-1]), self._sahi_model,
                                       slice_height=self.sahi_slice, slice_width=self.sahi_slice,
                                       overlap_height_ratio=0.2, overlap_width_ratio=0.2, verbose=0)
        rows = [[*p.bbox.to_xyxy(), p.score.value] for p in result.object_prediction_list if p.category.id == PERSON]
        return np.array(rows, dtype=float).reshape(-1, 5)
