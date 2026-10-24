"""Synthetic media for tests (no people in any frame)."""
import os
import tempfile

import cv2
import numpy as np


def make_mp4(seconds: float, fps: int = 25, size=(352, 288), seed: int = 0) -> bytes:
    """A smooth moving gradient with mild noise: an empty street-like scene, no people."""
    w, h = size
    rng = np.random.default_rng(seed)
    fd, path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    try:
        out = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
        base = np.tile(np.linspace(60, 180, w, dtype=np.float32), (h, 1))
        for i in range(int(seconds * fps)):
            frame = np.roll(base, i, axis=1) + rng.normal(0, 3, (h, w))
            out.write(cv2.cvtColor(frame.clip(0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR))
        out.release()
        with open(path, "rb") as f:
            return f.read()
    finally:
        os.remove(path)


def make_jpeg(value: int | None = None, size=(352, 288), seed: int = 0) -> bytes:
    """A uniform image when value is given (TfL-placeholder-like), else a textured scene."""
    w, h = size
    if value is not None:
        img = np.full((h, w, 3), value, np.uint8)
    else:
        img = np.random.default_rng(seed).integers(40, 200, (h, w, 3), dtype=np.uint8)
    return cv2.imencode(".jpg", img)[1].tobytes()
