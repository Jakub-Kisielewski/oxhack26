# Step 0 measurements (2026-10-24, ~21:07 UTC)

Machine: Apple M5 Pro (arm64), 18 cores, 48 GB RAM, so YOLO can use `mps`.

## Clips (5 central-London cameras)

| Camera | Size | Resolution | fps | Frames | Duration | Codec |
|---|---|---|---|---|---|---|
| Southampton Row/Vernon Place | 129 KB | 352x288 | 25 | 264 | 10.6 s | h264 |
| Theobalds Rd/Boswell St | 83 KB | 352x288 | 25 | 232 | 9.3 s | h264 |
| Kingsway/High Holborn | 81 KB | 352x288 | 25 | 258 | 10.3 s | h264 |
| A5 Edgware Rd/Broadley St | 117 KB | 352x288 | 25 | 241 | 9.6 s | h264 |
| Marylebone Rd/Great Portland St | 107 KB | 352x288 | 25 | 231 | 9.2 s | h264 |

- All clips are under `CHUNK_SECONDS=15`, so each clip is a single chunk and nothing is re-encoded.
  `ffmpeg` is not installed and is not needed.
- At 2 fps sampling, that's about 20 frames per clip for one batched YOLO call.
- 352x288 is low resolution. Small or distant people will be missed, so treat counts as a lower bound.
- The still is a 17 KB JPEG, also 352x288.

## Headers

- `HEAD` on `videoUrl`: 200, with `ETag` and `Last-Modified` on 5/5 clips. `HEAD` on `imageUrl` returns both too.
- `Last-Modified` values cluster (most within ~25 s of each other), so uploads arrive in bursts about every 5 min.

## Tier sizes (zones 1–2 polygon, example route, radius 300 m)

| | Cameras |
|---|---|
| JamCams total / available | 890 / 817 |
| Zones 1–2 (available) | 436 |
| Tier 2: within 300 m of the example route | 7 |
| Tier 1: central box minus route | 108 |
| Tier 0: rest of zones 1–2 | 321 |

Tier 2 load: 7 cameras × 1 clip per ~5 min ≈ 1.4 clips/min.

## HEAD latency (115 tier-1 + tier-2 cameras, sequential)

Median 79 ms, p95 207 ms, 11.5 s in total for one sequential pass. 2 of the 115 clips were stale (> 900 s).

## DuckDB spatial extension (needed by `app.py` bootstrap)

Installed with the README's manual steps (`bootstrap()` unchanged). On duckdb 2.0.0 the README's platform
check fails (`Relations no longer have fetchone()`); use the connection form instead:

```bash
python -c "import duckdb; print(duckdb.connect().execute('PRAGMA platform').fetchone()[0])"   # osx_arm64
curl -fL -C - -o spatial.duckdb_extension.gz \
  https://extensions.duckdb.org/v2.0.0/osx_arm64/spatial.duckdb_extension.gz   # ~80 MB unpacked
gunzip spatial.duckdb_extension.gz
python -c "import duckdb; duckdb.sql(\"INSTALL './spatial.duckdb_extension'\"); print('ok')"
python -m src.database.db   # [('crimes',), ('grid_cells',), ('transit_snapshots',)]
```
