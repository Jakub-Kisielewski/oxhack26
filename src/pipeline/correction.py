"""Count bias correction: people = a * raw + b (least squares on hand labels), with count_sd from the residuals."""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

import numpy as np

from src.pipeline.config import REPO_ROOT, SETTINGS, Settings

CORRECTION_PATH = REPO_ROOT / "config" / "count_correction.json"


@dataclass(frozen=True)
class Line:
    a: float = 1.0
    b: float = 0.0
    sd: float | None = None  # residual standard deviation; None = not fitted yet
    n: int = 0


@dataclass(frozen=True)
class Correction:
    global_: Line = Line()
    per_camera: dict[str, Line] = field(default_factory=dict)
    detector: str = ""  # detector config the fit was made with

    def line_for(self, camera_id: str | None) -> Line:
        return self.per_camera.get(camera_id or "", self.global_)

    def to_json(self) -> str:
        return json.dumps({"global": asdict(self.global_), "detector": self.detector,
                           "per_camera": {k: asdict(v) for k, v in self.per_camera.items()}}, indent=2)

    @classmethod
    def from_json(cls, text: str) -> "Correction":
        d = json.loads(text)
        return cls(Line(**d.get("global", {})), {k: Line(**v) for k, v in d.get("per_camera", {}).items()},
                   d.get("detector", ""))


def load_correction(path: Path = CORRECTION_PATH) -> Correction:
    """The committed correction; identity (a=1, b=0, sd unfitted) if there is none yet."""
    return Correction.from_json(path.read_text()) if path.exists() else Correction()


def fit_line(raw: Iterable[float], labels: Iterable[float]) -> Line:
    """Least-squares labels ~ a * raw + b. With no spread in raw, fit only the offset (a = 1)."""
    x, y = np.asarray(list(raw), dtype=float), np.asarray(list(labels), dtype=float)
    if len(x) < 2:
        raise ValueError("need at least 2 labelled samples")
    if np.ptp(x) == 0:
        a, b = 1.0, float(np.mean(y - x))
    else:
        a, b = np.polyfit(x, y, 1)
    resid = y - (a * x + b)
    dof = max(1, len(x) - 2)
    return Line(float(a), float(b), float(math.sqrt(np.sum(resid ** 2) / dof)), len(x))


def fit_correction(samples: Iterable[Mapping], min_per_camera: int = 10, detector: str = "") -> Correction:
    """samples: dicts with camera_id, raw, label. Global fit, plus per-camera fits where n >= min_per_camera."""
    samples = list(samples)
    global_ = fit_line([s["raw"] for s in samples], [s["label"] for s in samples])
    per_camera = {}
    for cid in sorted({s["camera_id"] for s in samples}):
        cam = [s for s in samples if s["camera_id"] == cid]
        if len(cam) >= min_per_camera:
            per_camera[cid] = fit_line([s["raw"] for s in cam], [s["label"] for s in cam])
    return Correction(global_, per_camera, detector)


def default_sd(raw: float) -> float:
    """Placeholder uncertainty before any fit: grows with the count."""
    return max(1.0, 0.3 * raw)


def correct(raw: float, camera_id: str | None, quality: str | None, luma: float | None,
            correction: Correction, settings: Settings = SETTINGS) -> tuple[float, float]:
    """(people, count_sd) for one raw count. Dark or low-light frames get a larger sd."""
    line = correction.line_for(camera_id)
    people = max(0.0, line.a * raw + line.b)
    sd = max(0.5, line.sd) if line.sd is not None else default_sd(raw)
    if quality == "dark" or (luma is not None and luma < settings.low_luma):
        sd *= settings.dark_sd_factor
    return people, sd
