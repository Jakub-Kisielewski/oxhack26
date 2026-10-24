# Step 4–5 measurements (2026-10-24, night)

Setup: Apple M5 Pro, `mps`, `yolov8n.pt` at imgsz 640, SAMPLE_FPS 2. The network was slow throughout (HEAD ~0.8 s
vs 79 ms in Step 0; downloads ~100 KB/s).

## Live run: poller + 2 workers, 10 min (23:16–23:26 UTC)

Tier 2 clips (7 cameras, every 15 s) plus tier 1 stills (108 cameras, every 60 s). Tier 1 was enabled for this run
only, to measure load; the default stays off.

| | Result |
|---|---|
| Chunks processed / failed / left in queue | 244 / 0 / 0 |
| Processing per clip (~22 frames) | median 125 ms, p95 868 ms (n=20) |
| Processing per still | median 6 ms, p95 25 ms (n=224) |
| Enqueue → observation (queue + processing) | median 1 s, p95 2 s, max 3 s |
| Burst drain (first enqueue → last observation) | about 1 s after the burst's last enqueue (e.g. 62 chunks over 62 s drained at 62 s) |
| Total worker busy time | ~4 s per 10 min across both workers (< 1% utilisation) |

Frame time → observation, steady state (excluding the first round, which picks up existing uploads up to ~9 min old):

| Kind | n | median | p95 | max | late at LAG 45 s | 60 s | 90 s |
|---|---|---|---|---|---|---|---|
| clip (polled every 15 s) | 8 | 14 s | 36 s | 36 s | 0 | 0 | 0 |
| still (polled every 60 s) | 112 | 30 s | 59 s | 64 s | 21 | 3 | 0 |

Uploads are **not** synchronised bursts: still uploads fall across the whole 5-minute cycle (seconds 24 to 295 of
the cycle, n=112). The Step 0 clustering was a coincidence among 5 clips.

### What sets LAG

The twin reads rows with `frame_time <= now - LAG`, so LAG must exceed the frame → observation delay. That delay is
dominated by the poll interval (up to one interval, plus HEAD/GET time), not by processing (≤ 3 s).

- Tier 2 clips only: max 36 s tonight. LAG 45 s works, but a slow clip round (up to 21 s tonight) eats the margin;
  **LAG 60 s** is safer.
- With tier 1 stills (60 s poll): **LAG 90 s**, or 45 s skips ~19% of stills.

### Headroom

Workers are idle > 99% of the time. Promoting tier 1 to full clip processing adds 108 cameras × 1 clip / 5 min ≈
22 clips/min. At the median 125 ms per clip that is ~3 s of compute per minute (~5% of one worker); even at
yolo11s@960 (~3.7× slower) it is ~10 s/min. Compute is not the limit; the network is (108 × ~100 KB per 5 min
≈ 36 KB/s sustained on top of HEAD traffic).

**Poller limit:** clip and still rounds run one after another on one thread, so a slow stills round (up to 28 s
tonight) delays the next tier-2 round past its 15 s interval. Running each tier on its own thread fixes this.

## Detector comparison (night: dark, rain, few people)

7 tier-2 clips, 22.4 sampled frames each, time 00:10 BST. ms per batch = one batched predict over a clip's frames.

| Model | imgsz | ms/batch | ms/frame | median people per clip |
|---|---|---|---|---|
| yolov8n | 640 | 64 | 2.8 | 0, 0, 0, 0, 0, 0.5, 1 |
| yolov8n | 960 | 116 | 5.2 | 0, 0, 0, 0, 0, 0, 0 |
| yolov8s | 640 | 123 | 5.5 | 0, 0, 0, 0, 0, 0, 1 |
| yolov8s | 960 | 241 | 10.7 | 0, 0, 0, 0, 0, 0, 2 |
| yolo11n | 640 | 65 | 2.9 | 0, 0, 0, 0, 0, 1, 2 |
| yolo11n | 960 | 120 | 5.3 | 0, 0, 0, 0, 0, 0, 1 |
| yolo11s | 640 | 119 | 5.3 | 0, 0, 0, 0, 0, 0, 1 |
| yolo11s | 960 | 238 | 10.6 | 0, 0, 0, 0, 0, 0, 3 |

Night counts are too low to choose a model; re-run `python scripts/bench_detect.py` (and `--tier 1`) in daylight.
`scripts/debug_detect.py` checks showed the zeros are genuine (empty wet streets) and that distant people
(~10–20 px tall at 352×288) are missed, so counts are a lower bound. Default stays `yolov8n@640` until the daylight run.
