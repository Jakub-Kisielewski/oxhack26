import os
import tempfile
from dataclasses import replace

import cv2
import numpy as np
import pytest

from src.pipeline import features
from src.pipeline.calibrate import fit_calibration, to_local_m
from src.pipeline.config import Settings
from src.pipeline.features import Calibration, extract_features, frame_quality, sample_clip
from media import make_jpeg, make_mp4

CAM = {"camera_id": "TEST_CAM", "lat": 51.5, "lon": -0.12, "homography": None}


class FakeDetector:
    """Returns the same boxes for every frame and records calls."""
    name = "fake@0"

    def __init__(self, boxes=()):
        self.boxes = np.array(boxes, dtype=float).reshape(-1, 5)
        self.calls = 0

    def detect(self, frames):
        self.calls += 1
        return [self.boxes for _ in frames]


def _write_mp4(frames, fps=25):
    h, w = frames[0].shape[:2]
    fd, path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    try:
        out = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
        for f in frames:
            out.write(f)
        out.release()
        return open(path, "rb").read()
    finally:
        os.remove(path)


def test_sample_clip_gives_about_20_frames_for_10_s_at_2_fps():
    frames, dt = sample_clip(make_mp4(10, fps=25), sample_fps=2.0)
    assert 20 <= len(frames) <= 21
    assert dt == pytest.approx(12 / 25)
    assert frames[0].shape == (288, 352, 3)


def test_sample_fps_is_configurable():
    frames, _ = sample_clip(make_mp4(4, fps=25), sample_fps=5.0)
    assert 19 <= len(frames) <= 21


def test_frame_quality():
    rng = np.random.default_rng(0)
    scene = rng.integers(40, 200, (288, 352, 3), dtype=np.uint8)
    assert frame_quality(np.full((288, 352, 3), 128, np.uint8)) == "blank"
    night = rng.integers(0, 36, (288, 352, 3), dtype=np.uint8)  # dark but textured (mean ~17)
    assert frame_quality(night) == "dark"
    assert frame_quality(scene) == "ok"
    smooth = cv2.normalize(cv2.GaussianBlur(scene, (0, 0), 6), None, 0, 255, cv2.NORM_MINMAX)  # blobs, full contrast
    shifted = np.roll(smooth, 40, axis=1)
    assert frame_quality(shifted, reference=smooth) == "reaimed"
    assert frame_quality(smooth, reference=smooth) == "ok"


def test_uncalibrated_camera_gives_null_density_and_speed():
    det = FakeDetector([[10, 10, 30, 60, 0.9], [100, 50, 120, 110, 0.8]])
    out = extract_features(make_mp4(4), CAM, det)
    assert out["people"] == 2.0 and out["quality"] == "ok"
    assert (out["density"], out["speed"], out["heading"]) == (None, None, None)
    assert det.calls == 1  # one batched call per chunk
    assert out["proc_version"] == "features-v1+fake@0"


def test_people_is_the_median_over_frames():
    class Varying(FakeDetector):
        def detect(self, frames):
            box = np.array([[0, 0, 5, 5, 0.9]])
            return [np.repeat(box, k, axis=0) for k in ([0, 1, 1, 9] * 10)[:len(frames)]]
    assert extract_features(make_mp4(4), CAM, Varying())["people"] == 1.0


def test_blank_clip_is_not_counted():
    det = FakeDetector()
    blank = _write_mp4([np.full((288, 352, 3), 128, np.uint8)] * 50)
    out = extract_features(blank, CAM, det)
    assert out["quality"] == "blank" and out["people"] is None and det.calls == 0


def test_unreadable_clip_is_blank():
    out = extract_features(b"not an mp4", CAM, FakeDetector())
    assert out["quality"] == "blank" and out["people"] is None


def test_still_is_counted_from_one_frame():
    out = extract_features(make_jpeg(), {**CAM}, FakeDetector([[1, 1, 9, 9, 0.5]]), kind="still")
    assert out["people"] == 1.0 and out["speed"] is None


def test_calibrated_camera_gives_density_and_velocity():
    # a textured block moving 3 px right per frame; 1 px = 0.1 m, image x = east, image y = south
    rng = np.random.default_rng(1)
    texture = rng.integers(0, 255, (60, 40, 3), dtype=np.uint8)
    background = rng.integers(70, 110, (288, 352, 3), dtype=np.uint8)  # static textured street
    frames = []
    for i in range(25):
        f = background.copy()
        f[100:160, 50 + 3 * i:90 + 3 * i] = texture
        frames.append(f)
    H = np.array([[0.1, 0, 0], [0, -0.1, 0], [0, 0, 1]])
    cam = {**CAM, "homography": Calibration(H, 51.5, -0.12, area_m2=50.0).to_json()}

    class BoxOnBlock(FakeDetector):
        def detect(self, frames):
            return [np.array([[50 + 3 * k * self.step, 100, 90 + 3 * k * self.step, 160, 0.9]])
                    for k in range(len(frames))]
    det = BoxOnBlock()
    det.step = 1
    out = extract_features(_write_mp4(frames), cam, det, settings=replace(Settings(), sample_fps=25))
    assert out["density"] == pytest.approx(1 / 50)
    assert out["speed"] == pytest.approx(3 * 0.1 * 25, rel=0.25)  # 7.5 m/s
    assert out["heading"] == pytest.approx(90, abs=10)  # east


def test_fit_calibration_recovers_a_known_homography():
    H_true = np.array([[0.05, 0.01, -8.0], [0.002, -0.08, 12.0], [0.0001, 0.0002, 1.0]])
    lat0, lon0 = 51.508, -0.128
    px = np.array([[40, 250], [300, 260], [320, 120], [60, 110], [180, 190], [250, 200]], dtype=float)
    ground = Calibration(H_true, lat0, lon0).to_ground(px)
    lat = lat0 + ground[:, 1] / 110_540.0
    lon = lon0 + ground[:, 0] / (111_320.0 * np.cos(np.radians(lat0)))
    points = [{"px": p.tolist(), "lat": la, "lon": lo} for p, la, lo in zip(px, lat, lon)]
    calib, err = fit_calibration(points, area_m2=120.0)
    assert err == pytest.approx(0.0, abs=0.05)
    recovered = calib.to_ground(px)
    expected = to_local_m(lat, lon, calib.lat0, calib.lon0)
    assert np.abs(recovered - expected).max() < 0.05
    assert Calibration.from_json(calib.to_json()).area_m2 == 120.0
    with pytest.raises(ValueError):
        fit_calibration(points[:3])
    assert fit_calibration(points[:4])[1] is None  # 4 points: no hold-out


def test_reference_frame_is_used_when_present(tmp_path, monkeypatch):
    monkeypatch.setattr(features, "CALIBRATION_DIR", tmp_path)
    assert features.reference_frame("X") is None
    cv2.imwrite(str(tmp_path / "X.jpg"), np.zeros((10, 10, 3), np.uint8))
    assert features.reference_frame("X").shape == (10, 10, 3)


# ------------------------------------------------------------------- real YOLO (needs ultralytics)

@pytest.fixture(scope="module")
def yolo():
    pytest.importorskip("ultralytics")
    from src.pipeline.detector import Detector
    return Detector()


def test_synthetic_clip_with_no_people_counts_zero(yolo):
    out = extract_features(make_mp4(10), CAM, yolo)
    assert out["people"] == 0.0
    assert out["density"] is None and out["speed"] is None
