# Build plan: London protest digital twin

## Deviations (agreed with the team, override the plan below)

- **Layout:** code lives under `src/` to match the existing repo: `src/pipeline/` (layer 1), `src/twin/`
  (layer 2), and the map page plus its helpers in `src/ui/`. Modules run as `python -m src.pipeline.<name>`
  and `python -m src.twin.<name>`. Settings are in `src/pipeline/config.py`.
- **UI:** the live map is a **new page** registered in `app.py`'s existing `st.navigation` list. `app.py` gets
  only that registration line; existing pages are not touched. Existing helpers in `src/ui/` are reused where
  they fit.
- **Coverage:** all available JamCams in TfL zones 1–2 are registered. `cameras.tier` replaces `on_route`:
  - **2** = route cameras: `HEAD` every 15 s, full clip processing (YOLO + flow).
  - **1** = central box: poll the still every 60 s, count people on the still only. Off by default; enabled
    only if Step 5 shows spare worker capacity.
  - **0** = everything else: registered, not polled. Shown grey on the map and still clickable (the viewer
    loads TfL's image and clip directly, no processing).
  Tier assignment is configurable; Step 0 and Step 5 measurements decide tier sizes. Never poll all zones 1–2
  cameras every 15 s.
- **Tests:** `.gitignore` no longer ignores `tests/`, `test_*.py`, `*_test.py`.
- **Reference poller:** `jamcam_poller.py` lives at `src/pipeline/jamcam_poller.py` (logic unchanged; CLI is
  `python -m src.pipeline.jamcam_poller --list`). Other modules import its functions from there.
- **Branch:** work happens on `feature/live-twin`, one commit per step.

The spec for Claude Code. Read `docs/JAMCAM.md` first: its facts, invariants, schema, privacy rules and
don'ts are binding. Build **one step at a time**. After each step, run its "done when" check, show the
output, and **stop for review** before starting the next.

Two layers, built in order:

- **Layer 1, detection and live feed:** database → cameras → poller → YOLO → workers → live 2D map
  with a camera viewer. It must be demoable on its own before Layer 2 starts.
- **Layer 2, modelling:** static world → twin → route model and Hawkes → decisions → map overlays → replay.

```
LAYER 1   TfL JamCams ─► poller ─► clips (queue) ─► workers ×N (YOLO + features) ─► observations
                                                                                       │
LAYER 2   OSM streets / shops / warehouses ─► twin ×1 (predict every 15 s, update per observation)
                                                   ─► cell_risk, route_probs, shop_alerts, police_posts
UI        Streamlit 2D map: cameras + (layer 2) risk hexes and routes; click a camera ─► live street view
```

Package layout: `pipeline/` (layer 1), `twin/` (layer 2), `ui/` (helpers used by `app.py`). Settings live in
`pipeline/config.py`, read from env with defaults, and are shared by everything.

---

## Layer 1: detection and live feed

### Step 0: measure before building
- Fetch 5 current central-London JamCam clips and report duration, fps, resolution and size. Confirm that `HEAD`
  on a `videoUrl` returns `ETag` and `Last-Modified`.
- Report how `app.py` is structured today.
- Propose the file list. **Wait for OK.**

### Step 1: database (`pipeline/db.py`)
- Schema from JAMCAM.md §4, plus:
  - `clips.data BLOB`: clip bytes, set NULL when done, so workers on any machine can process;
  - `clips.chunk_index INTEGER DEFAULT 0`: UNIQUE becomes `(camera_id, frame_time, chunk_index)`;
  - `cameras.image_url, cameras.video_url, cameras.on_route INTEGER`.
- The same functions work on SQLite (default `sqlite:///data/pipeline.db`, WAL, `busy_timeout=5000`) and on
  Postgres (`DB_URL`): `init_db, upsert_cameras, enqueue_clip, claim_next, mark_done, mark_failed,
  requeue_expired, insert_observation, latest_observation_per_camera, camera_history(camera_id, minutes),
  queue_stats`.
- `claim_next` is atomic. SQLite: `BEGIN IMMEDIATE` + `UPDATE … RETURNING`. Postgres:
  `FOR UPDATE SKIP LOCKED`.
- **Done when:** pytest shows idempotent enqueue, no double-claims from two concurrent claimers, and
  expired claims requeued.

### Step 2: camera registry (`pipeline/cameras.py`)
- Reuse `jamcam_poller.py` listing functions (`list_cameras`, `cameras_along_route`).
- `python -m pipeline.cameras --mode route|bbox` upserts available cameras into `cameras`. Route mode uses
  `ROUTE_POINTS` and `RADIUS_M` and sets `on_route=1`.
- **Done when:** the command lists N cameras and `SELECT count(*) FROM cameras` matches.

### Step 3: poller (`pipeline/poller.py`) and chunking (`pipeline/chunking.py`)
- Every `POLL_SECONDS=15`: `HEAD` each active camera's `videoUrl`. If the ETag changed, `GET` it.
  `frame_time = Last-Modified`. Skip stale clips (> 900 s). Split with
  `split_clip(bytes, CHUNK_SECONDS=15)`: a clip ≤ 15 s is one chunk with no re-encode. Enqueue the chunks with
  their bytes. Refresh the camera list every 10 min. Never wait on processing.
- One log line per round: checked, new, stale, errors.
- **Done when:** 2 live rounds enqueue clips, and a mocked test shows unchanged ETag → nothing, changed →
  enqueue, stale → skip.

### Step 4: YOLO detection and features (`pipeline/detector.py`, `pipeline/features.py`)
- `Detector`:
  - load `YOLO_MODEL=yolov8n.pt` once;
  - pick the device: mps > cuda > cpu, with an env override;
  - `detect(frames)` = **one batched** `predict(classes=[0], conf=YOLO_CONF=0.25, imgsz=640, verbose=False)`,
    returning per-frame boxes and counts.
  - No `track()`, no faces, never write frames to disk.
- `extract_features(chunk_bytes, camera_row, detector)` per JAMCAM.md §5:
  - sample 2 fps via a temp file, deleted in `finally`;
  - median people count;
  - density and speed/heading only if `cameras.homography` is set (Farneback flow inside person boxes only),
    otherwise NULL;
  - quality = ok|blank|dark|reaimed.
- `pipeline/calibrate.py`: for one `camera_id`, save one current frame to `calibration/` and read 4–6
  pixel↔lat/lon pairs from `calibration/<id>.json`. Fit with `cv2.findHomography(..., cv2.RANSAC)`, print the
  error on a held-out point in metres, then store the homography.
- **Done when:** a synthetic clip with no people gives `people == 0`; a real clip gives a plausible count;
  an uncalibrated camera gives NULL density and speed.

### Step 5: workers (`pipeline/worker.py`, `pipeline/run_workers.py`, `pipeline/status.py`)
- Worker loop: `requeue_expired → claim_next → extract_features → insert_observation → mark_done` (clear
  `data`). On error, `mark_failed` and continue. Sleep 2 s when empty. Clean shutdown on SIGINT/SIGTERM.
- `python -m pipeline.run_workers --n 3`:
  - starts N processes (spawn);
  - sets `torch.set_num_threads(max(1, cpu_count // n))` in each;
  - restarts dead workers and stops all on Ctrl-C.
- `python -m pipeline.status`: queue by status, observations in the last 10 min, mean seconds per chunk,
  lag (now − newest `frame_time`).
- `Makefile`: `init-db`, `cameras`, `poller`, `workers N=3`, `status`.
- **Done when:** poller + 2 workers run against live TfL for 10 minutes, status shows lag < 2 min,
  and you report seconds per chunk and how many workers keep up.

### Step 6: live 2D map with camera viewer (`app.py`, `ui/`)
- The UI is **read-only**: it never runs the poller, workers or model. DB reads go through `ui/data.py`
  with `st.cache_data(ttl=10)`.
- Layout: map on the left (about 2/3 width), camera panel on the right.
- **2D map** (pydeck, `pitch=0`, `map_style=pdk.map_styles.LIGHT` or `DARK`):
  - `ScatterplotLayer` id `cameras`: one dot per camera, coloured by latest `people` (grey if stale or no
    data), radius ~25 m, `pickable=True`, tooltip with name, people, and age of the reading.
  - Render with `st.pydeck_chart(deck, on_select="rerun", selection_mode="single-object", key="map")`.
  - Wrap the map and panel in `@st.fragment(run_every=10)` so they refresh without a full page rerun.
- **Camera panel** (when a camera is selected; read it from the selection state's `objects["cameras"]`):
  - name, view, last reading time, people, density / speed / heading if calibrated, quality;
  - **street view** = TfL's live still `st.image(image_url + "?t=<epoch>")` and clip
    `st.video(video_url + "?t=<epoch>")` loaded straight from TfL. The cache-buster forces fresh frames.
    Nothing is stored or proxied.
  - a small line chart of that camera's `people` over the last 60 min (`camera_history`).
  - Nothing selected → show "Click a camera to see its live view" plus a top-5 table of busiest cameras.
- Sidebar: data freshness (lag), queue depth, worker throughput (from `queue_stats`).
- **Done when:** with the pipeline running, the map shows coloured cameras that update. Clicking one shows its
  live image, its clip and a count chart. The page refreshes without losing the selection.

**Layer 1 checkpoint:** stop. Layer 1 must work end to end before Layer 2.

---

## Layer 2: modelling (the digital twin)

### Step 7: static world (`twin/world.py`)
- Pull with osmnx and cache to `data/` (GeoPackage/Parquet), for the central bbox:
  - the walkable street graph (`network_type="walk"`) with edge length and width (OSM `width` tag; default by
    highway type);
  - shops (`shop=*`);
  - warehouses (`building=warehouse`, `shop=storage_rental`).
- Write `shops` and `warehouses` tables and an H3 res-9 cell table covering the bbox. Map each camera to its
  nearest street edge and H3 cell.
- **Done when:** counts are printed, and a test confirms every camera has an edge and a cell.

### Step 8: twin skeleton (`twin/core.py`, `twin/run.py`)
- One process only. State = density and velocity per street edge (or H3 cell) + route probabilities +
  `last_t`.
- Clock is injectable: `LiveClock` (now − LAG) or `ReplayClock(start, end, speed)`.
- Every `TWIN_TICK_SECONDS=15`:
  1. fetch observations with `frame_time ≤ clock`, after `last_t`;
  2. for each in `frame_time` order: `state = predict(state, obs.frame_time)` then `state = update(state, obs)`;
  3. `state = predict(state, clock)`;
  4. write a snapshot with a new `run_id`: `cell_risk` (+ an `uncertainty` column that rises with distance
     from cameras and with staleness) and `route_probs`;
  5. checkpoint.
- `predict` and `update` start as **placeholders with typed signatures and docstrings**: diffusion along
  edges, and blending toward the camera reading. The model owner replaces them.
- **Done when:** the twin runs alongside Layer 1, and a new `run_id` appears every 15 s.

### Step 9: route model and Hawkes (model owner, `twin/routes.py`, `twin/hawkes.py`)
- Routes: k-shortest paths (Yen) on the street graph between march start and end, scored with path-size logit.
  The route posterior is updated by camera observations.
- Hawkes: exponential time kernel × Gaussian space kernel, fitted by MLE in numpy/scipy (**not** `tick`).
  The background μ(x,y) comes from police monthly data.
- `forecast(state, horizon_min=60, n_samples=200)`, run every 60 s: per-cell P(crowd > threshold) by 5-min
  window, route probabilities, ETA per shop.
- **Done when:** on the example route, route_probs sum to 1 and cells along the likely route get the highest P.

### Step 10: decisions (`twin/decisions.py`)
- Police allocation: maximise Σ wₖ(1 − e^(−η λₖ rₖ)) s.t. Σ rₖ ≤ R. The closed form is
  rₖ = max(0, ln(η wₖ λₖ / ν)/(η λₖ)), with ν found by bisection. Write the result to `police_posts`.
- Warehouses: for each at-risk shop, rank warehouses by P(the shop→warehouse route stays clear **and** the move
  finishes before the crowd's ETA) × capacity. Write to `shop_alerts` with action and deadline.
- `what_if(state, intervention)`: an edge closure or extra police post → rerun the forecast and compare expected loss.
- **Done when:** unit tests check that the allocation sums to R and the warehouse ranking respects deadlines.

### Step 11: UI overlays
Add these to the same 2D map, each toggleable in the sidebar:
- `H3HexagonLayer` risk from `latest_cell_risk`: colour = probability, opacity reduced by uncertainty;
- `PathLayer` route options, width = probability;
- shops coloured by alert;
- police posts.

Clicking a hex shows P(protest) by time window for that point. Clicking a shop shows its alert, deadline and
recommended warehouse. Camera click behaviour from Step 6 stays unchanged. Add a time slider for forecast
windows and a what-if panel.
- **Done when:** all layers render and update, and each click type shows its panel.

### Step 12: replay and backtest
- `python -m twin.run --replay START END --speed 10` replays stored observations through the same twin.
  The UI shows a "REPLAY" badge.
- Backtest script: for 1–2 past marches with known routes, report the route hit rate and the share of
  events in the top 5% of cells, against a baseline.
- **Done when:** replay drives the UI, and backtest numbers are printed.

---

## Always
- Follow JAMCAM.md §7 privacy and §8 don'ts. Show density and counts, never per-person dots or tracks.
- The UI never runs model or pipeline code. One twin process only.
- No Kafka/Celery/Redis. Gitignore `data/`, `*.db`, `calibration/*.jpg`, model weights and clips.
- Small typed functions, a one-line docstring per module, and a test for every non-trivial function.
