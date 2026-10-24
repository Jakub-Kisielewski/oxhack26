"""YOLO person detector: loaded once per process, one batched predict per chunk, persons only (no tracking)."""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from src.pipeline.config import REPO_ROOT, SETTINGS, Settings

log = logging.getLogger(__name__)

MODELS_DIR = REPO_ROOT / "data" / "models"  # weights live under data/ (gitignored)
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
    """A bare weights name (e.g. 'yolov8n.pt') resolves to data/models/, where ultralytics downloads it."""
    path = Path(model)
    if path.is_absolute() or path.parent != Path("."):
        return str(path)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    return str(MODELS_DIR / path)


class Detector:
    """Wraps one ultralytics YOLO model. detect() never tracks, never looks at faces, never writes frames."""

    def __init__(self, settings: Settings = SETTINGS, model: str | None = None, imgsz: int | None = None,
                 conf: float | None = None, device: str | None = None):
        from ultralytics import YOLO

        self.model_name = model or settings.yolo_model
        self.imgsz = imgsz or settings.yolo_imgsz
        self.conf = conf if conf is not None else settings.yolo_conf
        self.device = pick_device(device if device is not None else settings.yolo_device)
        self.model = YOLO(weights_path(self.model_name))
        log.info("detector %s on %s", self.name, self.device)

    @property
    def name(self) -> str:
        return f"{Path(self.model_name).stem}@{self.imgsz}"

    def detect(self, frames: list[np.ndarray]) -> list[np.ndarray]:
        """One batched predict over BGR frames; per frame an (n, 5) array of x0, y0, x1, y1, confidence."""
        if not frames:
            return []
        results = self.model.predict(frames, classes=[PERSON], conf=self.conf, imgsz=self.imgsz,
                                     device=self.device, verbose=False)
        return [np.hstack([r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy()[:, None]]) for r in results]
