# Detection accuracy: labelling and benchmark

Counts are checked against hand labels, the detector config is chosen by benchmark, and a linear correction is
fitted. Run this in daylight (and again at dusk if night accuracy matters).

## 1. Label (about 15 min)

```bash
python scripts/label_frames.py            # samples 40 tier 1+2 clips (half the busiest, half random), then labels
```

Each frame opens in Preview, 3x enlarged with the camera name on top. Type the number of people you can see
(include partly hidden ones), Enter to skip, q to stop. `--label-only` resumes; `--n 60` samples more. Labels go to
`data/eval/labels.csv` (`camera_id, frame_time, my_count`). The labelled frame is the middle sampled frame of the
clip; the clip is kept so the benchmark can test clip aggregation.

## 2. Benchmark

```bash
python scripts/bench_detect.py --quick    # a few minutes: labelled frame only, to see the landscape
python scripts/bench_detect.py            # full grid incl. median vs p75 over clips; ~20-40 min on mps
```

Grid: `yolov8n, yolov8s, yolo11s, yolo11m` × imgsz `640, 960, 1280` × SAHI off/on (detection runs), then conf
`0.15, 0.25` × `MIN_BOX_H 0, 6, 8, 10, 12` × aggregation (labelled frame, clip median, clip p75), all with the
production banner and ROI filters. Configs far over the time budget are skipped after 3 clips. Output: MAE, bias
(mean signed error, negative = undercount) and ms per clip, sorted by MAE; full table in
`data/eval/bench_results.csv`. It also prints the labelled frames' brightness against `LOW_LUMA`.

The best clip config under `--budget-ms 500` is picked, and a correction `people = a * raw + b` is fitted on its
raw counts (global, plus per camera where a camera has >= 10 labels), with a leave-one-out MAE.

## 3. Apply

```bash
python scripts/bench_detect.py --write-config   # writes config/detector.json and config/count_correction.json
```

The correction is only written with >= 20 labels and a positive slope. Commit both files, then restart the workers.

## 4. Purge

```bash
python scripts/label_frames.py --purge          # deletes the sampled clips and frames; keeps labels.csv
```

## ROIs

`config/camera_rois.json` maps `camera_id` to a polygon `[[x, y], ...]` in 352×288 pixels. A detection counts only
if the bottom-centre of its box is inside. Use it to exclude roads, bus shelters with adverts, or operator overlays
(some cameras show a number at top left).
