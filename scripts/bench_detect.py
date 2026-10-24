"""Compare detector models/image sizes on the same live frames: people counts and ms per batch.

    python scripts/bench_detect.py                       # tier-2 cameras, default model grid
    python scripts/bench_detect.py --tier 1 --limit 10 --models yolov8n.pt yolo11s.pt --imgsz 640 960

Frames are kept in memory only.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.pipeline import db  # noqa: E402
from src.pipeline.config import SETTINGS  # noqa: E402
from src.pipeline.detector import Detector  # noqa: E402
from src.pipeline.features import frame_quality, sample_clip  # noqa: E402
from src.pipeline.jamcam_poller import SESSION  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tier", type=int, default=2)
    ap.add_argument("--limit", type=int, default=7)
    ap.add_argument("--models", nargs="+", default=["yolov8n.pt", "yolov8s.pt", "yolo11n.pt", "yolo11s.pt"])
    ap.add_argument("--imgsz", nargs="+", type=int, default=[640, 960])
    ap.add_argument("--repeats", type=int, default=3, help="timed runs per clip (after one warm-up)")
    args = ap.parse_args()

    cams = db.active_cameras(db.connect(read_only=True), [args.tier])[: args.limit]
    clips = []
    for cam in cams:
        r = SESSION.get(cam["video_url"], timeout=30)
        frames, _ = sample_clip(r.content, SETTINGS.sample_fps) if r.ok else ([], 0)
        if frames:
            clips.append((cam["name"][:28], frames, frame_quality(frames[len(frames) // 2])))
    print(f"{len(clips)} clips, {statistics.mean(len(f) for _, f, _ in clips):.1f} frames each at "
          f"{SETTINGS.sample_fps} fps; time of day {time.strftime('%H:%M')}")
    print("qualities:", {name: q for name, _, q in clips})

    header = f"{'model':<14}{'imgsz':>6}{'ms/batch':>10}{'ms/frame':>10}  median people per clip"
    print(header)
    print("-" * len(header))
    for model in args.models:
        for imgsz in args.imgsz:
            det = Detector(model=model, imgsz=imgsz)
            det.detect(clips[0][1])  # warm-up (model load, mps kernels)
            times, medians = [], []
            for _, frames, _ in clips:
                for _ in range(args.repeats):
                    t0 = time.perf_counter()
                    boxes = det.detect(frames)
                    times.append((time.perf_counter() - t0) * 1000 / 1)
                medians.append(float(np.median([len(b) for b in boxes])))
            per_batch = statistics.median(times)
            per_frame = per_batch / statistics.mean(len(f) for _, f, _ in clips)
            print(f"{Path(model).stem:<14}{imgsz:>6}{per_batch:>10.0f}{per_frame:>10.1f}  {medians}")


if __name__ == "__main__":
    main()
