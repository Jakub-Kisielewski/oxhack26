"""Scoring for scripts/bench_detect.py: post-filter grid over cached detections, MAE / bias, best-config choice."""
from __future__ import annotations

import itertools
from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from src.pipeline.boxes import filter_boxes
from src.pipeline.config import SETTINGS, Settings
from src.pipeline.correction import fit_line
from src.pipeline.features import aggregate_counts

AGGREGATIONS = ("frame", "median", "p75")  # frame = the labelled frame only; median / p75 over the clip


@dataclass(frozen=True)
class Clip:
    """Cached detections for one labelled clip under one detector config (boxes at the lowest conf)."""
    camera_id: str
    label: int
    frame_index: int
    frame_shape: tuple[int, ...]
    boxes: list[np.ndarray]  # per sampled frame; [frame_index] alone in quick mode
    ms: float                # detection time for this clip


def counts(clip: Clip, conf: float, min_box_h: float, roi=None, settings: Settings = SETTINGS) -> list[int]:
    s = replace(settings, min_box_h=min_box_h)
    return [len(filter_boxes(b[b[:, 4] >= conf] if len(b) else b, clip.frame_shape, roi, settings=s))
            for b in clip.boxes]


def predict(clip: Clip, agg: str, conf: float, min_box_h: float, roi=None, settings: Settings = SETTINGS) -> float:
    c = counts(clip, conf, min_box_h, roi, settings)
    if agg == "frame":
        return float(c[clip.frame_index] if len(c) > 1 else c[0])
    return aggregate_counts(c, agg)


def error_stats(pred: Sequence[float], labels: Sequence[float]) -> tuple[float, float]:
    """(MAE, bias = mean signed error pred - label)."""
    err = np.asarray(pred, dtype=float) - np.asarray(labels, dtype=float)
    return float(np.mean(np.abs(err))), float(np.mean(err))


def score_detector(det_name: dict[str, Any], clips: list[Clip], confs: Iterable[float], min_box_hs: Iterable[float],
                   aggs: Iterable[str], rois: Mapping[str, Any], settings: Settings = SETTINGS) -> list[dict[str, Any]]:
    """One row per (conf, min_box_h, aggregation) for a detector config's cached detections."""
    rows = []
    ms = float(np.mean([c.ms for c in clips]))
    labels = [c.label for c in clips]
    for conf, mbh, agg in itertools.product(confs, min_box_hs, aggs):
        pred = [predict(c, agg, conf, mbh, rois.get(c.camera_id), settings) for c in clips]
        mae, bias = error_stats(pred, labels)
        rows.append({**det_name, "conf": conf, "min_box_h": mbh, "agg": agg, "mae": mae, "bias": bias,
                     "ms_per_clip": ms, "n": len(clips)})
    return rows


def best_row(rows: list[dict[str, Any]], budget_ms: float, aggs: Iterable[str] = ("median", "p75")) -> dict | None:
    """Lowest MAE among clip aggregations within the time budget (ties: faster first)."""
    ok = [r for r in rows if r["agg"] in tuple(aggs) and r["ms_per_clip"] <= budget_ms]
    return min(ok, key=lambda r: (r["mae"], r["ms_per_clip"])) if ok else None


def leave_one_out_mae(samples: Sequence[Mapping[str, float]]) -> float:
    """MAE of the global correction when each sample is predicted by a line fitted on all the others."""
    errors = []
    for i, s in enumerate(samples):
        rest = [t for j, t in enumerate(samples) if j != i]
        line = fit_line([t["raw"] for t in rest], [t["label"] for t in rest])
        errors.append(abs(max(0.0, line.a * s["raw"] + line.b) - s["label"]))
    return float(np.mean(errors))
