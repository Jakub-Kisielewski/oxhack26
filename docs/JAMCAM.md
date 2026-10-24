# JamCam & video pipeline — context for coding agents

This is the reference for anything that touches TfL JamCam footage in the OxHack 26 London protest predictor.
Read it before writing ingestion, CV, queue, model-input or Streamlit-refresh code. Facts here were checked
against TfL's API and docs; don't "fix" them from memory.

---

## 1. Hard facts about the data source (do not contradict)

- **Source:** TfL Unified API, `https://api.tfl.gov.uk`. No key required. An optional `TFL_APP_KEY` env var
  (sent as the `app_key` query param) raises rate limits. Use it only if HTTP 429 appears.
- **No live stream exists.** Each camera publishes one still JPG and one MP4 clip a few seconds long. Both
  update about **every 5 minutes**. Never write code that assumes a continuous stream, RTSP or HLS.
- **15-minute blanking.** Frames older than 15 min are replaced by a blank placeholder image. Treat
  `now - Last-Modified > 900 s` as **stale**: log the row, don't count people, don't save the frame.
- **Polling interval ~60 s** per camera is enough. Faster returns the same frame. Use the ETag with
  `If-None-Match` and skip `304` responses.
- **Frame time = HTTP `Last-Modified`** of the image/clip response (TfL upload time). Always key data on this,
  never on download time.
- Cameras in control-room use may stop updating, or be re-aimed or zoomed. That breaks the calibration.

### Endpoints

| Purpose | Request | Response shape |
|---|---|---|
| All cameras | `GET /Place/Type/JamCam` | **plain JSON list** of Place objects |
| Cameras near a point | `GET /Place?lat={lat}&lon={lon}&radius={m}&type=JamCam` | **object** `{"centrePoint": [...], "places": [...]}`; each place has `distance` (m). Unwrap `places`. |
| Latest still | camera's `imageUrl` | JPG, e.g. `https://s3-eu-west-1.amazonaws.com/jamcams.tfl.gov.uk/00001.07450.jpg` |
| Latest clip | camera's `videoUrl` | MP4, same pattern with `.mp4` |

Place fields used: `id`, `commonName`, `lat`, `lon`, `distance` (radius search only), and
`additionalProperties[]` as `{key, value}` pairs with keys `imageUrl`, `videoUrl`, `available`
(the **string** `"true"`/`"false"`) and `view`.

```python
props = {p["key"]: p["value"] for p in place.get("additionalProperties", [])}
available = props.get("available", "false") == "true"
```

Default area, central London: `DEFAULT_BBOX = (51.495, -0.180, 51.530, -0.070)` as `(lat_min, lon_min, lat_max, lon_max)`.

Example march route (Russell Sq → Kingsway → Aldwych → Trafalgar Sq → Whitehall):
`(51.5212,-0.1236) (51.5168,-0.1197) (51.5130,-0.1173) (51.5074,-0.1277) (51.5033,-0.1260)`, radius 300 m.

---

## 2. What already exists

`jamcam_poller.py` (+ `requirements.txt`: `requests>=2.31, urllib3>=2.0, pillow>=10.0, ultralytics>=8.1`).
It is tested on macOS. Reuse its functions rather than rewriting them:

| Function | Does |
|---|---|
| `make_session()` | `requests.Session` with urllib3 `Retry` (429/5xx, backoff 1.0) |
| `tfl_get(path, **params)` | GET plus JSON, adds `app_key` if set |
| `_to_cam(place)` | Place → `{id, name, lat, lon, view, image_url, video_url, available, distance_m}` |
| `list_cameras(bbox)` | bbox filter + `available` |
| `cameras_near(lat, lon, radius_m)` | radius search, unwraps `places`, sorted by distance |
| `cameras_along_route(points, radius_m)` | union of `cameras_near`, deduplicated by id |
| `load_counter()` | returns `count_people(jpeg_bytes) -> int` (YOLOv8n, `classes=[0]`, `conf=0.25`) |
| `frame_time_and_age(resp)` | parses `Last-Modified` → `(iso_str, age_s)` |
| `poll(get_cams, ...)` | ETag polling loop → `jamcam_counts.csv` |

CLI: `--list`, `--near LAT,LON` (repeatable), `--radius`, `--bbox`, `--interval`, `--out`, `--once`,
`--no-yolo`, `--save`, `--clips`. Saved files go to `frames/<camera_id>/<YYYYmmddTHHMMSSZ>.jpg|mp4`.

CSV columns: `utc_time, camera_id, name, lat, lon, distance_m, frame_time, frame_age_s, stale, people`.

Smoke tests, in order:
```bash
python jamcam_poller.py --list
python jamcam_poller.py --list --near 51.5074,-0.1277
python jamcam_poller.py --once --no-yolo
python jamcam_poller.py --once
```
On a headless Ubuntu VM, install `libgl1 libglib2.0-0` first, or `import ultralytics` fails. On macOS, skip apt and use `python3`.

---

## 3. Target architecture

```
poller ──► clips (queue table) ──► workers ×N ──► observations ──► model ×1 ──► output tables ──► Streamlit
```

Invariants. Code must respect all of these:

1. **One job = one whole clip** (one camera, one 5-min update). Never split a clip across workers: speed
   and heading need consecutive frames.
2. **Workers are stateless and parallel** (run 1–6). **The model is a single process** that owns the crowd
   state. Never run two model processes.
3. **Model consumes observations in event-time order** (`frame_time`), waiting `LAG = 45 s` (range 30–60)
   behind the newest frame. Rows arriving later than LAG are logged and skipped, never applied out of order.
4. **Streamlit is read-only.** It never imports or runs the model, workers or poller. It reads `latest_*`
   views inside `@st.fragment(run_every=10)` with `st.cache_data(ttl=10)`.
5. **The model never reads video.** Only rows from `observations` (and other timestamped tables such as
   `station_crowding`).
6. **Clock abstraction:** the model queries "all rows with `frame_time <= T`". `T` comes from a clock
   that is either live (`now() - LAG`) or replay (a stored day at k× speed). The same code serves the demo
   and the backtest.
7. **Delete video after processing.** Keep at most a few clips per camera for calibration.

### Model interface (the one function the model owner implements)

```python
def predict(state, to_time) -> state      # advance crowd state from state.t to to_time (movement model)
def update(state, obs) -> state           # Bayes correction with one observation row
```
`obs` is one `observations` row as a dict. Persist `state` with a checkpoint (`pickle` / JSON) after each
batch so a restart resumes from `last_t`.

### Model loop (reference)

```python
state, last_t = load_checkpoint()
while True:
    rows = fetch_observations(after=last_t, before=clock.now() - LAG)
    for obs in sorted(rows, key=lambda r: r["frame_time"]):
        state = predict(state, obs["frame_time"])
        state = update(state, obs)
        last_t = obs["frame_time"]
    if rows:
        run_id = write_outputs(state)          # new run_id per write; never overwrite
        save_checkpoint(state, last_t)
    sleep(2)
```

### Worker loop (reference)

```python
while True:
    clip = claim_next_pending_clip()           # atomic claim, see §4
    if not clip:
        sleep(2); continue
    try:
        feats = extract_features(clip["path"], camera=load_camera(clip["camera_id"]))
        insert_observation(clip["camera_id"], clip["frame_time"], feats)   # idempotent
        mark_done(clip["id"]); os.remove(clip["path"])
    except Exception as e:
        mark_failed(clip["id"], str(e))
```

---

## 4. Database

**Default: SQLite in WAL mode** (`PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;`), one file shared by
processes on one machine. Keep every write transaction short. Switch to **Postgres + PostGIS** only if
processes run on different machines; the schema is the same.

```sql
CREATE TABLE cameras (
  camera_id TEXT PRIMARY KEY, name TEXT, lat REAL, lon REAL, view TEXT,
  homography TEXT,            -- JSON 3x3, NULL until calibrated
  active INTEGER DEFAULT 1
);

CREATE TABLE clips (            -- also the job queue
  id INTEGER PRIMARY KEY,
  camera_id TEXT NOT NULL, frame_time TEXT NOT NULL,   -- ISO 8601 UTC, from Last-Modified
  etag TEXT, path TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',              -- pending | processing | done | failed
  error TEXT, ingested_at TEXT NOT NULL, claimed_at TEXT,
  UNIQUE (camera_id, frame_time)
);

CREATE TABLE observations (
  camera_id TEXT NOT NULL, frame_time TEXT NOT NULL, ingested_at TEXT NOT NULL,
  lat REAL, lon REAL, h3 TEXT,
  people REAL, density REAL,          -- people/m², NULL if camera uncalibrated
  speed REAL, heading REAL,           -- m/s, degrees from north; NULL if no flow
  quality TEXT,                       -- ok | blank | dark | reaimed | stale
  proc_version TEXT,
  UNIQUE (camera_id, frame_time)
);

CREATE TABLE station_crowding (naptan TEXT, time TEXT, pct_baseline REAL, ingested_at TEXT,
                               UNIQUE (naptan, time));

CREATE TABLE model_runs (run_id INTEGER PRIMARY KEY, as_of TEXT, params TEXT, code_version TEXT);
CREATE TABLE route_probs (run_id INTEGER, route_id TEXT, prob REAL, geometry TEXT);   -- GeoJSON
CREATE TABLE cell_risk   (run_id INTEGER, h3 TEXT, window_start TEXT, window_end TEXT, prob REAL, tier INTEGER);
CREATE TABLE shop_alerts (run_id INTEGER, shop_id TEXT, expected_loss REAL, action TEXT, deadline TEXT, warehouse_id TEXT);
CREATE TABLE police_posts(run_id INTEGER, unit TEXT, lat REAL, lon REAL, coverage REAL);

CREATE VIEW latest_cell_risk AS
  SELECT * FROM cell_risk WHERE run_id = (SELECT MAX(run_id) FROM model_runs);
-- same pattern for latest_route_probs, latest_shop_alerts, latest_police_posts
```

Rules:
- **Every live row carries `frame_time` (event) and `ingested_at` (arrival).**
- **Idempotent inserts:** `INSERT ... ON CONFLICT (camera_id, frame_time) DO NOTHING`.
- **Atomic claim:**
  - SQLite (≥3.35): inside `BEGIN IMMEDIATE`, run
    `UPDATE clips SET status='processing', claimed_at=? WHERE id = (SELECT id FROM clips WHERE status='pending' ORDER BY frame_time LIMIT 1) RETURNING *;`
  - Postgres: `SELECT ... FOR UPDATE SKIP LOCKED`.
  - Reset `processing` rows whose `claimed_at` is older than 5 min back to `pending` (crashed worker).
- **Outputs are append-only per `run_id`.** Never UPDATE or DELETE model outputs; the UI reads `latest_*`.
- Store `h3` (resolution 9) on spatial rows so click-on-hex lookups are a single equality query.

---

## 5. Feature extraction spec (`extract_features`)

Input: path to one MP4 plus the camera row. Output: a dict matching the `observations` columns.

| Feature | Method |
|---|---|
| frames | sample ~2 fps with `cv2.VideoCapture`; if the clip won't open, `quality='blank'` |
| people | YOLOv8n, `classes=[0]`, `conf=0.25`, **median** count over sampled frames. Optional for dense scenes: CSRNet / DM-Count |
| density | if `homography` is set: project box foot-points to ground, people ÷ visible pavement area (m²); else NULL |
| speed, heading | `cv2.calcOpticalFlowFarneback(prev, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)`; average flow **inside person boxes only** (excludes vehicles); convert px/frame → m/s through the homography; heading in degrees |
| quality | `blank` (near-uniform image / TfL placeholder), `dark` (low mean luminance), `reaimed` (large global frame shift vs. the camera's reference frame), else `ok` |

Load the YOLO model **once per worker process**, not per clip.

Calibration: for each of 3–4 chosen cameras, pick 4 image points with known ground positions (OSM or
satellite), run `cv2.findHomography`, and store it as JSON in `cameras.homography`.

---

## 6. Throughput budget

About 50 cameras give about 10 clips/min. YOLOv8n on CPU at 2 fps of clip takes ~3–5 s per clip, so ~40 s of
compute per minute. Run **2–3 workers**. Stills-only counting needs 1. At about 600 clips/hour, delete-after-process
keeps disk near zero.

---

## 7. Privacy and legal constraints (non-negotiable)

- Images of people are personal data under UK GDPR. **Store counts and aggregates only.**
- **No** face detection or recognition, **no** re-identification across cameras, **no** per-person tracks
  persisted. Optical flow is averaged per clip and never stored per person.
- Delete frames and clips after processing. `--save` is for a handful of calibration frames only.
- Out of scope: station CCTV (TfL/BTP only, not public) and police radio (Airwave is encrypted; interception is
  an offence under the Wireless Telegraphy Act 2006). Don't write code that targets either.

---

## 8. Don'ts

- Don't run model logic inside `app.py` / Streamlit.
- Don't key anything on download time; use `Last-Modified`.
- Don't count stale frames (>15 min) or `available="false"` cameras.
- Don't split one clip across workers.
- Don't add Kafka, Celery, Redis or cloud storage. Processes + SQLite (or Postgres) are enough.
- Don't install `tick` for the Hawkes model. Implement the exponential-kernel Hawkes in numpy/scipy.
- Don't assume `/Place?lat=...` returns a list; it returns `{centrePoint, places}`.

## 9. Open decisions (ask the team before assuming)

- SQLite on one machine vs. shared Postgres (depends on where the workers run).
- Which cameras on the route actually show pavement (needs a human to eyeball frames).
- Exact `state` representation for `predict` / `update` (route filter + Hawkes intensity), owned by the model person.
