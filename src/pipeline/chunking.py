"""Split a downloaded clip into processing chunks (the one place to change if long clips ever need cutting)."""
from __future__ import annotations

import logging
import os
import tempfile

import cv2

log = logging.getLogger(__name__)


def clip_duration_s(data: bytes) -> float | None:
    """Duration of an MP4 in seconds (frames / fps), or None if OpenCV can't read it."""
    fd, path = tempfile.mkstemp(suffix=".mp4")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        cap = cv2.VideoCapture(path)
        try:
            fps, frames = cap.get(cv2.CAP_PROP_FPS), cap.get(cv2.CAP_PROP_FRAME_COUNT)
        finally:
            cap.release()
        return frames / fps if fps > 0 and frames > 0 else None
    finally:
        os.remove(path)


def split_clip(data: bytes, chunk_seconds: int) -> list[bytes]:
    """Chunks for one clip. TfL clips are ~10 s, so this is always one chunk with no re-encode.

    A clip longer than chunk_seconds stays a single chunk and logs a warning (no ffmpeg); change this
    function if that ever matters.
    """
    duration = clip_duration_s(data)
    if duration is not None and duration > chunk_seconds:
        log.warning("clip is %.1f s (> CHUNK_SECONDS=%d); keeping it as one chunk", duration, chunk_seconds)
    return [data]
