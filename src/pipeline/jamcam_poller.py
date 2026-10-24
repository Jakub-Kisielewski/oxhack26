"""
JamCam poller (OxHack): pulls TfL traffic-camera frames for central London or for
points along a march route, and logs a people count for every new frame.

How the "feed" works
--------------------
TfL does not publish a live stream. Each camera uploads a new still image (and a short
MP4 clip) roughly every 5 minutes; anything older than 15 minutes is replaced by a
blank placeholder. This script re-checks every camera each round (default 60 s) and
only processes a frame when it has actually changed, so you get one record per real
update: a ~5-minute time-lapse per camera.

Privacy
-------
By default frames are counted in memory and thrown away. Only counts go to the CSV.
Use --save / --clips only to collect a few frames for calibration.

Examples
--------
    python jamcam_poller.py --list                          # cameras in central London
    python jamcam_poller.py --list --near 51.5074,-0.1277   # cameras within 300 m of Trafalgar Sq
    python jamcam_poller.py --once                          # one pass, then exit (quick test)
    python jamcam_poller.py                                 # run continuously, counts -> jamcam_counts.csv
    python jamcam_poller.py --near 51.5212,-0.1236 --near 51.5130,-0.1173 \
                            --near 51.5074,-0.1277 --near 51.5033,-0.1260 --radius 300
                                                            # cameras along a march route
    python jamcam_poller.py --no-yolo --save --clips        # just collect frames + clips

Optional: export TFL_APP_KEY=...  (free key from the TfL API portal; higher rate limits)
"""

import argparse
import csv
import io
import os
import signal
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

TFL = "https://api.tfl.gov.uk"
APP_KEY = os.environ.get("TFL_APP_KEY")

# Central London: roughly Hyde Park Corner to Aldgate, Euston Road to the river
DEFAULT_BBOX = (51.495, -0.180, 51.530, -0.070)  # (lat_min, lon_min, lat_max, lon_max)

STALE_AFTER_S = 15 * 60  # TfL blanks frames older than this
CSV_FIELDS = ["utc_time", "camera_id", "name", "lat", "lon", "distance_m",
              "frame_time", "frame_age_s", "stale", "people"]


# --------------------------------------------------------------------------- HTTP

def make_session():
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=1.0, status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=("GET", "HEAD"))
    s.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=16))
    s.headers["User-Agent"] = "oxhack-jamcam-poller/1.0"
    return s


SESSION = make_session()


def tfl_get(path, **params):
    if APP_KEY:
        params["app_key"] = APP_KEY
    r = SESSION.get(f"{TFL}{path}", params=params, timeout=20)
    r.raise_for_status()
    return r.json()


# ------------------------------------------------------------------- camera lists

def _to_cam(place):
    """Flatten one TfL Place record into a simple camera dict."""
    props = {p["key"]: p["value"] for p in place.get("additionalProperties", [])}
    return {
        "id": place["id"],
        "name": place["commonName"],
        "lat": place["lat"],
        "lon": place["lon"],
        "view": props.get("view", ""),
        "image_url": props.get("imageUrl"),
        "video_url": props.get("videoUrl"),
        "available": props.get("available", "false") == "true",
        "distance_m": place.get("distance"),  # only set by the radius search
    }


def list_cameras(bbox=DEFAULT_BBOX, only_available=True):
    """All JamCams in a bounding box. /Place/Type/JamCam returns a plain list."""
    lat0, lon0, lat1, lon1 = bbox
    cams = []
    for place in tfl_get("/Place/Type/JamCam"):
        cam = _to_cam(place)
        if not (lat0 <= cam["lat"] <= lat1 and lon0 <= cam["lon"] <= lon1):
            continue
        if only_available and not cam["available"]:
            continue
        cams.append(cam)
    return cams


def cameras_near(lat, lon, radius_m=300, only_available=True):
    """Cameras within radius_m metres of a point.

    The radius search returns {"centrePoint": [...], "places": [...]}, so unwrap "places".
    """
    data = tfl_get("/Place", lat=lat, lon=lon, radius=radius_m, type="JamCam")
    cams = [_to_cam(p) for p in data.get("places", [])]
    if only_available:
        cams = [c for c in cams if c["available"]]
    return sorted(cams, key=lambda c: c["distance_m"] or 0)


def cameras_along_route(points, radius_m=300):
    """Cameras near any of several (lat, lon) points, without duplicates."""
    seen = {}
    for lat, lon in points:
        for cam in cameras_near(lat, lon, radius_m):
            seen.setdefault(cam["id"], cam)
    return list(seen.values())


# ------------------------------------------------------------------- counting

def load_counter(model_name="yolov8n.pt", conf=0.25):
    """Returns a function jpeg_bytes -> number of people detected."""
    from PIL import Image
    from ultralytics import YOLO

    model = YOLO(model_name)  # downloads weights on first run

    def count_people(jpeg_bytes):
        img = Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")
        res = model(img, classes=[0], conf=conf, verbose=False)  # class 0 = person
        return len(res[0].boxes)

    return count_people


# ------------------------------------------------------------------- polling

def frame_time_and_age(resp):
    """Upload time of the frame (from Last-Modified) and its age in seconds."""
    lm = resp.headers.get("Last-Modified")
    if not lm:
        return "", ""
    try:
        t = parsedate_to_datetime(lm)
        age = (datetime.now(timezone.utc) - t).total_seconds()
        return t.isoformat(), round(age)
    except (TypeError, ValueError):
        return lm, ""


def save_bytes(root, cam_id, stamp, ext, data):
    d = os.path.join(root, cam_id)  # one folder per camera = a time-lapse per camera
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{stamp}.{ext}"), "wb") as fh:
        fh.write(data)


def poll(get_cams, interval_s=60, out_csv="jamcam_counts.csv", use_yolo=True,
         save_dir=None, save_clips=False, once=False, refresh_every=30):
    count_people = load_counter() if use_yolo else None
    etags = {}  # camera id -> ETag of the last frame we processed
    cams = get_cams()
    print(f"Polling {len(cams)} cameras every {interval_s}s -> {out_csv}")

    new_file = not os.path.exists(out_csv)
    with open(out_csv, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new_file:
            w.writeheader()

        rnd = 0
        while True:
            rnd += 1
            if rnd > 1 and refresh_every and rnd % refresh_every == 0:
                try:  # cameras go in and out of service; refresh the list now and then
                    cams = get_cams()
                    print(f"[refresh] {len(cams)} cameras")
                except requests.RequestException as e:
                    print(f"[refresh failed] {e}")

            new_frames = 0
            for cam in cams:
                headers = {"If-None-Match": etags[cam["id"]]} if cam["id"] in etags else {}
                try:
                    r = SESSION.get(cam["image_url"], headers=headers, timeout=15)
                except requests.RequestException as e:
                    print(f"[skip] {cam['name']}: {e}")
                    continue
                if r.status_code == 304:  # unchanged since last round
                    continue
                if r.status_code != 200:
                    print(f"[skip] {cam['name']}: HTTP {r.status_code}")
                    continue

                etags[cam["id"]] = r.headers.get("ETag", "")
                frame_time, age = frame_time_and_age(r)
                stale = isinstance(age, int) and age > STALE_AFTER_S
                people = ""
                if count_people and not stale:  # a stale frame is TfL's blank placeholder
                    try:
                        people = count_people(r.content)
                    except Exception as e:  # bad/partial JPEG
                        print(f"[count failed] {cam['name']}: {e}")

                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                if save_dir and not stale:
                    save_bytes(save_dir, cam["id"], stamp, "jpg", r.content)
                    if save_clips and cam.get("video_url"):
                        try:
                            v = SESSION.get(cam["video_url"], timeout=30)
                            if v.status_code == 200:
                                save_bytes(save_dir, cam["id"], stamp, "mp4", v.content)
                        except requests.RequestException as e:
                            print(f"[clip failed] {cam['name']}: {e}")

                w.writerow({
                    "utc_time": datetime.now(timezone.utc).isoformat(),
                    "camera_id": cam["id"], "name": cam["name"],
                    "lat": cam["lat"], "lon": cam["lon"],
                    "distance_m": cam.get("distance_m") or "",
                    "frame_time": frame_time, "frame_age_s": age,
                    "stale": stale, "people": people,
                })
                f.flush()
                new_frames += 1
                print(f"{cam['name']:<42} age={age!s:>4}s  stale={stale!s:<5}  people={people}")

            print(f"--- round {rnd}: {new_frames} new frame(s) at "
                  f"{datetime.now().strftime('%H:%M:%S')}")
            if once:
                return
            time.sleep(interval_s)


# ------------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(description="Poll TfL JamCams and log people counts.")
    ap.add_argument("--list", action="store_true", help="list cameras and exit")
    ap.add_argument("--near", action="append", metavar="LAT,LON",
                    help="only cameras near this point; repeat for points along a route")
    ap.add_argument("--radius", type=int, default=300, help="search radius in metres for --near")
    ap.add_argument("--bbox", metavar="LAT0,LON0,LAT1,LON1",
                    help="bounding box instead of central London (ignored with --near)")
    ap.add_argument("--interval", type=int, default=60, help="seconds between polling rounds")
    ap.add_argument("--out", default="jamcam_counts.csv", help="CSV output path")
    ap.add_argument("--once", action="store_true", help="one polling round, then exit")
    ap.add_argument("--no-yolo", action="store_true", help="log frames without counting people")
    ap.add_argument("--save", action="store_true", help="save frames to ./frames/<camera_id>/")
    ap.add_argument("--clips", action="store_true", help="with --save, also save the MP4 clips")
    args = ap.parse_args()

    if args.near:
        points = [tuple(float(v) for v in p.split(",")) for p in args.near]
        get_cams = lambda: cameras_along_route(points, radius_m=args.radius)  # noqa: E731
        where = f"within {args.radius} m of {len(points)} point(s)"
    else:
        bbox = tuple(float(v) for v in args.bbox.split(",")) if args.bbox else DEFAULT_BBOX
        get_cams = lambda: list_cameras(bbox)  # noqa: E731
        where = f"in bbox {bbox}"

    if args.list:
        cams = get_cams()
        print(f"{len(cams)} available JamCams {where}")
        for c in cams:
            dist = f"  {c['distance_m']:.0f} m" if c.get("distance_m") is not None else ""
            print(f"{c['id']:<22} {c['name']:<40} {c['lat']:.5f},{c['lon']:.5f}{dist}  view: {c['view']}")
            print(f"{'':<22} {c['image_url']}")
        return

    signal.signal(signal.SIGINT, lambda *_: (print("\nStopped."), sys.exit(0)))
    poll(get_cams, interval_s=args.interval, out_csv=args.out, use_yolo=not args.no_yolo,
         save_dir="frames" if args.save else None, save_clips=args.clips, once=args.once)


if __name__ == "__main__":
    main()
