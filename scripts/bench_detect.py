"""Detector accuracy benchmark on hand-labelled clips (from scripts/label_frames.py).

    python scripts/bench_detect.py                  # full grid; ~20-40 min on mps
    python scripts/bench_detect.py --quick          # labelled frame only (no clip aggregation); much faster
    python scripts/bench_detect.py --write-config   # also write config/detector.json + config/count_correction.json

Grid: models x imgsz x SAHI are detection runs (cached at the lowest conf); conf, MIN_BOX_H and the aggregation
(labelled frame, clip median, clip p75) are applied afterwards with the production filters (ROI, banners).
Reports MAE, bias (mean signed error) and ms per clip, sorted by MAE; picks the best clip config under
--budget-ms. Full results: data/eval/bench_results.csv.
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.pipeline import benchmark, evalset  # noqa: E402
from src.pipeline.boxes import load_rois  # noqa: E402
from src.pipeline.config import DETECTOR_CONFIG_PATH, SETTINGS  # noqa: E402
from src.pipeline.correction import CORRECTION_PATH, fit_correction  # noqa: E402
from src.pipeline.detector import Detector  # noqa: E402
from src.pipeline.features import sample_clip  # noqa: E402

SLOW_FACTOR = 4  # give up on a detector config whose first clips average over budget x this
MIN_FIT_LABELS = 20  # don't write a correction fitted on fewer labels


def load_frames(items) -> list[tuple[evalset.EvalItem, int, list[np.ndarray]]]:
    out = []
    for item, label in items:
        frames, _ = sample_clip((evalset.EVAL_DIR / item.clip).read_bytes(), item.sample_fps)
        if len(frames) > item.frame_index:
            out.append((item, label, frames))
    return out


def run_detector(det: Detector, data, quick: bool, budget_ms: float) -> list[benchmark.Clip] | None:
    """Detections for every clip, or None if the config is far over budget."""
    det.detect(data[0][2][:2])  # warm-up: weights, mps kernels
    clips, timed = [], []
    for i, (item, label, frames) in enumerate(data):
        if quick:
            boxes = det.detect([frames[item.frame_index]])
            if i < 3:  # time real full-clip batches on a few clips; batching makes per-frame extrapolation wrong
                t0 = time.perf_counter()
                det.detect(frames)
                timed.append((time.perf_counter() - t0) * 1000)
            ms = float(np.mean(timed))
        else:
            t0 = time.perf_counter()
            boxes = det.detect(frames)
            ms = (time.perf_counter() - t0) * 1000
        clips.append(benchmark.Clip(item.camera_id, label, 0 if quick else item.frame_index, frames[0].shape, boxes, ms))
        if i == 2 and np.mean([c.ms for c in clips]) > budget_ms * SLOW_FACTOR:
            return None
    return clips


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--models", nargs="+", default=["yolov8n.pt", "yolov8s.pt", "yolo11s.pt", "yolo11m.pt"])
    ap.add_argument("--imgsz", nargs="+", type=int, default=[640, 960, 1280])
    ap.add_argument("--conf", nargs="+", type=float, default=[0.15, 0.25])
    ap.add_argument("--sahi", nargs="+", choices=["off", "on"], default=["off", "on"])
    ap.add_argument("--min-box-h", nargs="+", type=float, default=[0, 6, 8, 10, 12])
    ap.add_argument("--budget-ms", type=float, default=500)
    ap.add_argument("--quick", action="store_true", help="labelled frame only; no clip aggregation")
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--write-config", action="store_true")
    args = ap.parse_args()

    data = load_frames(evalset.labelled_items())
    if len(data) < 5:
        raise SystemExit(f"only {len(data)} labelled clips on disk; run scripts/label_frames.py first")
    rois = load_rois()
    aggs = ("frame",) if args.quick else benchmark.AGGREGATIONS
    luma = sorted(float(cv2.cvtColor(f[it.frame_index], cv2.COLOR_BGR2GRAY).mean()) for it, _, f in data)
    print(f"{len(data)} labelled clips, {np.mean([len(f) for _, _, f in data]):.1f} frames each; "
          f"labels: mean {np.mean([l for _, l, _ in data]):.1f}, max {max(l for _, l, _ in data)}; "
          f"luma min {luma[0]:.0f} / median {np.median(luma):.0f} / max {luma[-1]:.0f} "
          f"({sum(l < SETTINGS.low_luma for l in luma)} under LOW_LUMA={SETTINGS.low_luma:g})")

    rows, cache = [], {}
    for model, imgsz, sahi in itertools.product(args.models, args.imgsz, args.sahi):
        name = {"model": Path(model).stem, "imgsz": imgsz, "sahi": sahi}
        t0 = time.perf_counter()
        det = Detector(model=model, imgsz=imgsz, conf=min(args.conf), sahi=sahi == "on")
        clips = run_detector(det, data, args.quick, args.budget_ms)
        if clips is None:
            print(f"  {name}: skipped, over {SLOW_FACTOR}x the {args.budget_ms:g} ms budget")
            continue
        cache[(name["model"], imgsz, sahi)] = clips
        rows += benchmark.score_detector(name, clips, args.conf, args.min_box_h, aggs, rois)
        print(f"  {name}: {np.mean([c.ms for c in clips]):.0f} ms/clip ({time.perf_counter() - t0:.0f} s)")

    rows.sort(key=lambda r: (r["mae"], r["ms_per_clip"]))
    out = evalset.EVAL_DIR / "bench_results.csv"
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    header = f"{'model':<10}{'imgsz':>6}{'sahi':>5}{'conf':>6}{'minh':>5}{'agg':>7}{'MAE':>7}{'bias':>7}{'ms/clip':>9}"
    print("\n" + header + "\n" + "-" * len(header))
    for r in rows[: args.top]:
        print(f"{r['model']:<10}{r['imgsz']:>6}{r['sahi']:>5}{r['conf']:>6.2f}{r['min_box_h']:>5.0f}{r['agg']:>7}"
              f"{r['mae']:>7.2f}{r['bias']:>+7.2f}{r['ms_per_clip']:>9.0f}")
    print(f"(all {len(rows)} rows in {out})")

    best = benchmark.best_row(rows, args.budget_ms, ("frame",) if args.quick else ("median", "p75"))
    if best is None:
        raise SystemExit(f"no config under {args.budget_ms:g} ms per clip")
    print(f"\nbest under {args.budget_ms:g} ms/clip: {best}")

    clips = cache[(best["model"], best["imgsz"], best["sahi"])]
    samples = [{"camera_id": c.camera_id, "label": c.label,
                "raw": benchmark.predict(c, best["agg"], best["conf"], best["min_box_h"], rois.get(c.camera_id))}
               for c in clips]
    detector_name = f"{best['model']}@{best['imgsz']}{'+sahi' if best['sahi'] == 'on' else ''}"
    correction = fit_correction(samples, detector=detector_name)
    g = correction.global_
    print(f"correction: people = {g.a:.3f} * raw {g.b:+.3f}, residual sd {g.sd:.2f}, n={g.n}, "
          f"{len(correction.per_camera)} per-camera fits; leave-one-out MAE "
          f"{benchmark.leave_one_out_mae(samples):.2f} (uncorrected {best['mae']:.2f})")

    if args.write_config:
        DETECTOR_CONFIG_PATH.write_text(json.dumps({
            "yolo_model": f"{best['model']}.pt", "yolo_imgsz": best["imgsz"], "yolo_conf": best["conf"],
            "yolo_sahi": best["sahi"] == "on", "count_agg": "median" if args.quick else best["agg"],
            "min_box_h": best["min_box_h"]}, indent=2) + "\n")
        print(f"wrote {DETECTOR_CONFIG_PATH}")
        if g.n >= MIN_FIT_LABELS and g.a > 0:
            CORRECTION_PATH.write_text(correction.to_json() + "\n")
            print(f"wrote {CORRECTION_PATH}")
        else:
            print(f"NOT writing {CORRECTION_PATH}: need >= {MIN_FIT_LABELS} labels and a positive slope "
                  f"(n={g.n}, a={g.a:.2f})")
        print("restart the workers to use the new settings")


if __name__ == "__main__":
    main()
