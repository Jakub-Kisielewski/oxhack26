from dataclasses import replace

import numpy as np
import pytest

from src.pipeline.config import Settings
from src.pipeline.correction import (Correction, Line, correct, default_sd, fit_correction, fit_line,
                                     load_correction)


def test_fit_line_recovers_slope_offset_and_residual_sd():
    rng = np.random.default_rng(0)
    raw = rng.integers(0, 20, 200).astype(float)
    labels = 1.6 * raw + 2.0 + rng.normal(0, 1.5, 200)
    line = fit_line(raw, labels)
    assert line.a == pytest.approx(1.6, abs=0.05) and line.b == pytest.approx(2.0, abs=0.4)
    assert line.sd == pytest.approx(1.5, abs=0.2) and line.n == 200


def test_fit_line_with_no_spread_fits_only_an_offset():
    line = fit_line([0, 0, 0], [1, 2, 3])
    assert (line.a, line.b) == (1.0, 2.0)
    with pytest.raises(ValueError):
        fit_line([1], [2])


def test_fit_correction_global_plus_per_camera_where_enough_labels():
    samples = [{"camera_id": "busy", "raw": r, "label": 2 * r} for r in range(12)]
    samples += [{"camera_id": "rare", "raw": r, "label": r + 1} for r in range(3)]
    c = fit_correction(samples, min_per_camera=10, detector="yolov8n@640")
    assert set(c.per_camera) == {"busy"}
    assert c.per_camera["busy"].a == pytest.approx(2.0)
    assert c.line_for("rare") is c.global_ and c.line_for("busy") is c.per_camera["busy"]
    again = Correction.from_json(c.to_json())
    assert again.per_camera["busy"].a == pytest.approx(2.0) and again.detector == "yolov8n@640"


def test_correct_applies_the_line_clamps_and_widens_sd_in_low_light():
    s = replace(Settings(), low_luma=50, dark_sd_factor=2.0)
    c = Correction(Line(a=1.5, b=1.0, sd=2.0, n=40))
    assert correct(4, "X", "ok", 120, c, s) == (7.0, 2.0)
    assert correct(4, "X", "dark", 15, c, s) == (7.0, 4.0)
    assert correct(4, "X", "ok", 40, c, s)[1] == 4.0  # low luma, not flagged dark
    assert correct(0, "X", "ok", 120, Correction(Line(a=1.0, b=-3.0, sd=1.0)), s)[0] == 0.0  # never negative


def test_unfitted_correction_is_identity_with_default_sd(tmp_path):
    c = load_correction(tmp_path / "none.json")
    assert correct(10, "X", "ok", 120, c) == (10.0, default_sd(10))
    assert default_sd(0) == 1.0
