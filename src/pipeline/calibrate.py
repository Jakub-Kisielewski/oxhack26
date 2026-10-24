"""Camera calibration: save a reference frame, fit a ground-plane homography from pixel<->lat/lon pairs, store it."""
from __future__ import annotations

import argparse
import json
import math

import cv2
import numpy as np

from src.pipeline import db
from src.pipeline.features import CALIBRATION_DIR, Calibration
from src.pipeline.jamcam_poller import SESSION

M_PER_DEG_LAT = 110_540.0
M_PER_DEG_LON_EQUATOR = 111_320.0
TEMPLATE = {
    "points": [{"px": [0, 0], "lat": 0.0, "lon": 0.0} for _ in range(5)],
    "area_m2": None,
    "_help": "4-6 points on the ground (kerb corners, crossing stripes). px = [x, y] in calibration/<id>.jpg; "
             "lat/lon from OSM or satellite. The last point is held out to measure the error. "
             "area_m2 = visible pavement area, for density (optional).",
}


def to_local_m(lat: np.ndarray, lon: np.ndarray, lat0: float, lon0: float) -> np.ndarray:
    """Equirectangular metres (east, north) around (lat0, lon0); fine over a camera's field of view."""
    east = (np.asarray(lon) - lon0) * M_PER_DEG_LON_EQUATOR * math.cos(math.radians(lat0))
    north = (np.asarray(lat) - lat0) * M_PER_DEG_LAT
    return np.column_stack([east, north])


def fit_calibration(points: list[dict], area_m2: float | None = None) -> tuple[Calibration, float | None]:
    """Fit on all but the last point, report that point's error in metres, then refit on all points.

    Returns (calibration fitted on every point, held-out error in metres or None with only 4 points).
    """
    if len(points) < 4:
        raise ValueError("need at least 4 pixel<->lat/lon pairs")
    px = np.array([p["px"] for p in points], dtype=np.float64)
    lat = np.array([p["lat"] for p in points])
    lon = np.array([p["lon"] for p in points])
    lat0, lon0 = float(lat.mean()), float(lon.mean())
    ground = to_local_m(lat, lon, lat0, lon0)

    holdout_error = None
    if len(points) >= 5:
        H_fit, _ = cv2.findHomography(px[:-1], ground[:-1], cv2.RANSAC, 2.0)
        if H_fit is None:
            raise ValueError("homography fit failed: are the points collinear or duplicated?")
        predicted = Calibration(H_fit, lat0, lon0).to_ground(px[-1:])[0]
        holdout_error = float(np.linalg.norm(predicted - ground[-1]))
    H, _ = cv2.findHomography(px, ground, cv2.RANSAC, 2.0)
    if H is None:
        raise ValueError("homography fit failed: are the points collinear or duplicated?")
    return Calibration(H, lat0, lon0, area_m2), holdout_error


def save_frame(con, camera_id: str) -> None:
    cam = db.get_camera(con, camera_id)
    if cam is None:
        raise SystemExit(f"unknown camera {camera_id}; run python -m src.pipeline.cameras first")
    resp = SESSION.get(cam["image_url"], timeout=30)
    resp.raise_for_status()
    CALIBRATION_DIR.mkdir(exist_ok=True)
    (CALIBRATION_DIR / f"{camera_id}.jpg").write_bytes(resp.content)
    pairs = CALIBRATION_DIR / f"{camera_id}.json"
    if not pairs.exists():
        pairs.write_text(json.dumps(TEMPLATE, indent=2))
    print(f"saved {CALIBRATION_DIR / f'{camera_id}.jpg'} (Last-Modified {resp.headers.get('Last-Modified')})")
    print(f"now fill in {pairs}, then run: python -m src.pipeline.calibrate fit {camera_id}")


def fit(con, camera_id: str) -> None:
    spec = json.loads((CALIBRATION_DIR / f"{camera_id}.json").read_text())
    calib, err = fit_calibration(spec["points"], spec.get("area_m2"))
    print(f"held-out point error: {err:.2f} m" if err is not None else "only 4 points: no held-out error")
    db.set_homography(con, camera_id, calib.to_json())
    print(f"stored homography for {camera_id}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Calibrate a JamCam's ground plane.")
    ap.add_argument("action", choices=["save-frame", "fit", "clear"])
    ap.add_argument("camera_id")
    args = ap.parse_args()
    con = db.connect()
    db.init_db(con)
    if args.action == "save-frame":
        save_frame(con, args.camera_id)
    elif args.action == "fit":
        fit(con, args.camera_id)
    else:
        db.set_homography(con, args.camera_id, None)
        print(f"cleared homography for {args.camera_id}")


if __name__ == "__main__":
    main()
