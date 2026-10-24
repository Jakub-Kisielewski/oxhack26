"""Check detections by eye: fetch a camera's live still (or clip), run the detector, save an annotated image.

    python scripts/debug_detect.py JamCams_00001.06502            # still
    python scripts/debug_detect.py JamCams_00001.06502 --clip     # clip: frame with the median count
    python scripts/debug_detect.py JamCams_00001.06502 --model yolov8s.pt --imgsz 960 --open

Images go to data/debug/ (gitignored). They contain people: keep them local and delete them when done.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.pipeline import db  # noqa: E402
from src.pipeline.config import REPO_ROOT, SETTINGS  # noqa: E402
from src.pipeline.detector import Detector  # noqa: E402
from src.pipeline.features import decode_still, frame_quality, sample_clip  # noqa: E402
from src.pipeline.jamcam_poller import SESSION  # noqa: E402

OUT_DIR = REPO_ROOT / "data" / "debug"


def annotate(frame: np.ndarray, boxes: np.ndarray, title: str) -> np.ndarray:
    img = cv2.resize(frame, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)  # 352x288 is tiny
    for x0, y0, x1, y1, conf in boxes:
        p0, p1 = (int(x0 * 2), int(y0 * 2)), (int(x1 * 2), int(y1 * 2))
        cv2.rectangle(img, p0, p1, (0, 255, 0), 2)
        cv2.putText(img, f"{conf:.2f}", (p0[0], max(12, p0[1] - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)
    cv2.rectangle(img, (0, 0), (img.shape[1], 26), (0, 0, 0), -1)
    cv2.putText(img, title, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    return img


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("camera_id")
    ap.add_argument("--clip", action="store_true", help="use the MP4 clip instead of the still")
    ap.add_argument("--model", default=SETTINGS.yolo_model)
    ap.add_argument("--imgsz", type=int, default=SETTINGS.yolo_imgsz)
    ap.add_argument("--conf", type=float, default=SETTINGS.yolo_conf)
    ap.add_argument("--open", action="store_true", help="open the result in Preview")
    args = ap.parse_args()

    cam = db.get_camera(db.connect(read_only=True), args.camera_id)
    if cam is None:
        raise SystemExit(f"unknown camera {args.camera_id}")
    resp = SESSION.get(cam["video_url" if args.clip else "image_url"], timeout=30)
    resp.raise_for_status()
    frames = sample_clip(resp.content, SETTINGS.sample_fps)[0] if args.clip else decode_still(resp.content)
    if not frames:
        raise SystemExit("could not decode any frame")

    det = Detector(model=args.model, imgsz=args.imgsz, conf=args.conf)
    t0 = time.perf_counter()
    boxes = det.detect(frames)
    ms = (time.perf_counter() - t0) * 1000
    counts = [len(b) for b in boxes]
    median = float(np.median(counts))
    pick = int(np.argmin([abs(c - median) for c in counts]))
    quality = frame_quality(frames[len(frames) // 2])

    title = (f"{cam['name']} | {det.name} conf>={args.conf} | {counts[pick]} people "
             f"(median {median:g} over {len(frames)} frame{'s' * (len(frames) > 1)}) | {quality}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{args.camera_id}_{'clip' if args.clip else 'still'}_{det.name}_{time.strftime('%Y%m%dT%H%M%S')}.jpg"
    cv2.imwrite(str(out), annotate(frames[pick], boxes[pick], title))
    print(f"Last-Modified: {resp.headers.get('Last-Modified')}")
    print(f"counts per frame: {counts}  median={median:g}  quality={quality}  {ms:.0f} ms for {len(frames)} frames")
    print(f"saved {out}")
    if args.open:
        subprocess.run(["open", str(out)], check=False)


if __name__ == "__main__":
    main()
