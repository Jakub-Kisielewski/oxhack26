from dataclasses import replace

import numpy as np
import pytest

from src.pipeline import benchmark
from src.pipeline.config import Settings

S = replace(Settings(), banner_rects_px=())


def _clip(label, per_frame, frame_index=1, camera_id="A"):
    """per_frame: list of (box_height, conf) lists."""
    boxes = [np.array([[10, 100, 20, 100 + h, c] for h, c in f], dtype=float).reshape(-1, 5) for f in per_frame]
    return benchmark.Clip(camera_id, label, frame_index, (288, 352, 3), boxes, ms=120.0)


def test_predict_applies_conf_min_height_and_aggregation():
    clip = _clip(3, [[(20, 0.9)], [(20, 0.9), (20, 0.2), (5, 0.9)], [(20, 0.9)] * 4])
    assert benchmark.predict(clip, "frame", 0.15, 8, settings=S) == 2.0    # labelled frame, 5 px box dropped
    assert benchmark.predict(clip, "frame", 0.25, 8, settings=S) == 1.0    # 0.2 conf dropped too
    assert benchmark.predict(clip, "frame", 0.15, 0, settings=S) == 3.0
    assert benchmark.predict(clip, "median", 0.25, 8, settings=S) == 1.0   # counts 1, 1, 4
    assert benchmark.predict(clip, "p75", 0.25, 8, settings=S) == 2.5


def test_error_stats():
    assert benchmark.error_stats([2, 4, 6], [3, 3, 3]) == (pytest.approx(5 / 3), pytest.approx(1.0))


def test_score_and_best_row_respect_budget():
    clips = [_clip(2, [[(20, 0.9)], [(20, 0.9)] * 2, [(20, 0.9)] * 2]) for _ in range(3)]
    rows = benchmark.score_detector({"model": "m", "imgsz": 640, "sahi": "off"}, clips, [0.25], [8],
                                    benchmark.AGGREGATIONS, {}, S)
    assert {r["agg"]: r["mae"] for r in rows} == {"frame": 0.0, "median": 0.0, "p75": 0.0}
    slow = [{**r, "ms_per_clip": 900.0, "mae": r["mae"] - 1} for r in rows]
    assert benchmark.best_row(rows + slow, budget_ms=500)["ms_per_clip"] == 120.0
    assert benchmark.best_row(slow, budget_ms=500) is None


def test_leave_one_out_mae_on_a_perfect_line():
    samples = [{"raw": r, "label": 2 * r + 1} for r in range(6)]
    assert benchmark.leave_one_out_mae(samples) == pytest.approx(0.0, abs=1e-9)
