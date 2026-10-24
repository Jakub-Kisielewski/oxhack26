"""Pipeline database (data/pipeline.db): every SQL statement for cameras, the clip queue and observations.

SQLite only for now, but kept Postgres-ready: all SQL lives in this module, the atomic claim is one
function (claim_next), and only portable SQL is used (ON CONFLICT, RETURNING, window functions).
Every stored time goes through to_iso (UTC 'YYYY-MM-DDTHH:MM:SS+00:00'), so times compare correctly as text.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from src.pipeline.config import REPO_ROOT, SETTINGS

SCHEMA = """
CREATE TABLE IF NOT EXISTS cameras (
  camera_id TEXT PRIMARY KEY, name TEXT, lat REAL, lon REAL, view TEXT,
  image_url TEXT, video_url TEXT,
  tier INTEGER NOT NULL DEFAULT 0,          -- 2 = route (clips), 1 = central box (stills), 0 = not polled
  homography TEXT,                          -- JSON 3x3, NULL until calibrated
  active INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS clips (          -- also the job queue
  id INTEGER PRIMARY KEY,
  camera_id TEXT NOT NULL, frame_time TEXT NOT NULL,
  chunk_index INTEGER NOT NULL DEFAULT 0,
  kind TEXT NOT NULL DEFAULT 'clip' CHECK (kind IN ('clip', 'still')),
  etag TEXT, path TEXT,
  data BLOB,                                -- media bytes; NULL once processed
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'done', 'failed')),
  attempts INTEGER NOT NULL DEFAULT 0,
  error TEXT, ingested_at TEXT NOT NULL, claimed_at TEXT, finished_at TEXT,
  UNIQUE (camera_id, frame_time, chunk_index, kind)
);
CREATE INDEX IF NOT EXISTS idx_clips_status ON clips (status, frame_time);

CREATE TABLE IF NOT EXISTS observations (
  camera_id TEXT NOT NULL, frame_time TEXT NOT NULL,
  chunk_index INTEGER NOT NULL DEFAULT 0,
  kind TEXT NOT NULL DEFAULT 'clip',
  ingested_at TEXT NOT NULL,
  lat REAL, lon REAL, h3 TEXT,
  people REAL, density REAL,                -- people/m², NULL if camera uncalibrated
  speed REAL, heading REAL,                 -- m/s, degrees from north; NULL if no flow
  quality TEXT,                             -- ok | blank | dark | reaimed | stale
  proc_version TEXT,
  proc_ms INTEGER,                          -- extract_features wall time (perf_counter) in the worker
  UNIQUE (camera_id, frame_time, chunk_index, kind)
);
CREATE INDEX IF NOT EXISTS idx_obs_frame_time ON observations (frame_time);
CREATE INDEX IF NOT EXISTS idx_obs_camera_time ON observations (camera_id, frame_time);

CREATE TABLE IF NOT EXISTS station_crowding (naptan TEXT, time TEXT, pct_baseline REAL, ingested_at TEXT,
                                             UNIQUE (naptan, time));

CREATE TABLE IF NOT EXISTS model_runs (run_id INTEGER PRIMARY KEY, as_of TEXT, params TEXT, code_version TEXT);
CREATE TABLE IF NOT EXISTS route_probs (run_id INTEGER, route_id TEXT, prob REAL, geometry TEXT);
CREATE TABLE IF NOT EXISTS cell_risk (run_id INTEGER, h3 TEXT, window_start TEXT, window_end TEXT,
                                      prob REAL, tier INTEGER);
CREATE TABLE IF NOT EXISTS shop_alerts (run_id INTEGER, shop_id TEXT, expected_loss REAL, action TEXT,
                                        deadline TEXT, warehouse_id TEXT);
CREATE TABLE IF NOT EXISTS police_posts (run_id INTEGER, unit TEXT, lat REAL, lon REAL, coverage REAL);

CREATE VIEW IF NOT EXISTS latest_cell_risk AS
  SELECT * FROM cell_risk WHERE run_id = (SELECT MAX(run_id) FROM model_runs);
CREATE VIEW IF NOT EXISTS latest_route_probs AS
  SELECT * FROM route_probs WHERE run_id = (SELECT MAX(run_id) FROM model_runs);
CREATE VIEW IF NOT EXISTS latest_shop_alerts AS
  SELECT * FROM shop_alerts WHERE run_id = (SELECT MAX(run_id) FROM model_runs);
CREATE VIEW IF NOT EXISTS latest_police_posts AS
  SELECT * FROM police_posts WHERE run_id = (SELECT MAX(run_id) FROM model_runs);
"""

# Columns added after a table was first created: init_db adds them to existing DB files.
ADDED_COLUMNS = {"observations": {"proc_ms": "INTEGER"}}

CAMERA_COLUMNS = ("camera_id", "name", "lat", "lon", "view", "image_url", "video_url", "tier")
OBSERVATION_COLUMNS = (
    "camera_id", "frame_time", "chunk_index", "kind", "ingested_at", "lat", "lon", "h3",
    "people", "density", "speed", "heading", "quality", "proc_version", "proc_ms",
)
STATUSES = ("pending", "processing", "done", "failed")


# ------------------------------------------------------------------- time

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(t: datetime | str) -> str:
    """The one stored time format: UTC 'YYYY-MM-DDTHH:MM:SS+00:00' (sub-seconds truncated).

    Accepts a timezone-aware datetime, an ISO 8601 string ('Z' or any offset) or an HTTP date
    such as a Last-Modified header ('Sat, 24 Oct 2026 21:01:53 GMT').
    """
    if isinstance(t, str):
        try:
            t = datetime.fromisoformat(t)
        except ValueError:
            t = parsedate_to_datetime(t)
    if t.tzinfo is None:
        raise ValueError(f"naive datetime {t!r}; pass a timezone-aware UTC time")
    return t.astimezone(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------- connection

def sqlite_path(db_url: str) -> Path:
    """sqlite:///relative/path is resolved against the repo root; sqlite:////abs/path is absolute."""
    prefix = "sqlite:///"
    if not db_url.startswith(prefix):
        raise NotImplementedError(f"only sqlite:/// URLs are supported for now, got {db_url!r}")
    path = Path(db_url[len(prefix):])
    return path if path.is_absolute() else REPO_ROOT / path


def connect(db_url: str | None = None, read_only: bool = False) -> sqlite3.Connection:
    """Open the pipeline DB in autocommit mode; transactions are explicit (see _tx)."""
    path = sqlite_path(db_url or SETTINGS.db_url)
    if read_only:
        con = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, isolation_level=None,
                              check_same_thread=False)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(path, isolation_level=None)
        con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    con.row_factory = sqlite3.Row
    return con


@contextmanager
def _tx(con: sqlite3.Connection, immediate: bool = False) -> Iterator[sqlite3.Connection]:
    con.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield con
    except BaseException:
        con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")


def init_db(con: sqlite3.Connection) -> None:
    """Create missing tables and views, and add columns introduced since the DB file was created."""
    con.executescript(SCHEMA)
    for table, columns in ADDED_COLUMNS.items():
        have = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
        for name, decl in columns.items():
            if name not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


# ------------------------------------------------------------------- cameras

def upsert_cameras(con: sqlite3.Connection, cameras: Iterable[Mapping[str, Any]],
                   deactivate_missing: bool = False, now: datetime | None = None) -> int:
    """Insert or refresh cameras keyed on camera_id. Never deletes; keeps any stored homography.

    Each row's `active` defaults to 1. With deactivate_missing=True, every camera not in `cameras`
    is set active=0 in the same transaction.
    """
    ts = to_iso(now or utc_now())
    rows = [tuple(c.get(k) for k in CAMERA_COLUMNS[:-1])
            + (int(c.get("tier") or 0), int(c.get("active", True)), ts) for c in cameras]
    if deactivate_missing and not rows:
        raise ValueError("refusing to deactivate every camera: empty camera list")
    with _tx(con):
        con.executemany(
            """INSERT INTO cameras (camera_id, name, lat, lon, view, image_url, video_url, tier, active, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (camera_id) DO UPDATE SET
                 name = excluded.name, lat = excluded.lat, lon = excluded.lon, view = excluded.view,
                 image_url = excluded.image_url, video_url = excluded.video_url, tier = excluded.tier,
                 active = excluded.active, updated_at = excluded.updated_at""",
            rows,
        )
        if deactivate_missing:
            marks = ", ".join("?" for _ in rows)
            con.execute(
                f"UPDATE cameras SET active = 0, updated_at = ? WHERE active = 1 AND camera_id NOT IN ({marks})",
                (ts, *(r[0] for r in rows)),
            )
    return len(rows)


def all_cameras(con: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every registered camera, active or not (for the map)."""
    rows = con.execute(
        """SELECT camera_id, name, lat, lon, view, image_url, video_url, tier, active,
                  homography IS NOT NULL AS calibrated, updated_at
           FROM cameras ORDER BY camera_id"""
    ).fetchall()
    return [dict(r) for r in rows]


def active_cameras(con: sqlite3.Connection, tiers: Iterable[int]) -> list[dict[str, Any]]:
    """Active cameras in the given tiers (what the poller polls)."""
    tiers = tuple(tiers)
    if not tiers:
        return []
    marks = ", ".join("?" for _ in tiers)
    rows = con.execute(
        f"""SELECT camera_id, name, lat, lon, image_url, video_url, tier FROM cameras
            WHERE active = 1 AND tier IN ({marks}) ORDER BY camera_id""",
        tiers,
    ).fetchall()
    return [dict(r) for r in rows]


def get_camera(con: sqlite3.Connection, camera_id: str) -> dict[str, Any] | None:
    row = con.execute("SELECT * FROM cameras WHERE camera_id = ?", (camera_id,)).fetchone()
    return dict(row) if row else None


def set_homography(con: sqlite3.Connection, camera_id: str, homography_json: str | None) -> None:
    """Store (or clear, with None) a camera's calibration JSON."""
    con.execute("UPDATE cameras SET homography = ? WHERE camera_id = ?", (homography_json, camera_id))


def camera_tiers(con: sqlite3.Connection) -> dict[str, int]:
    """{camera_id: tier} for every registered camera."""
    return {r["camera_id"]: r["tier"] for r in con.execute("SELECT camera_id, tier FROM cameras")}


def camera_tier_summary(con: sqlite3.Connection) -> list[dict[str, Any]]:
    """Per tier (highest first): number of registered cameras and how many are active."""
    rows = con.execute(
        """SELECT tier, COUNT(*) AS cameras, SUM(active) AS active FROM cameras
           GROUP BY tier ORDER BY tier DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------- queue

def enqueue_clip(con: sqlite3.Connection, camera_id: str, frame_time: datetime | str, data: bytes, *,
                 etag: str | None = None, chunk_index: int = 0, kind: str = "clip",
                 now: datetime | None = None) -> int | None:
    """Queue one chunk; returns its id, or None if (camera, frame_time, chunk, kind) is already queued."""
    row = con.execute(
        """INSERT INTO clips (camera_id, frame_time, chunk_index, kind, etag, data, ingested_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (camera_id, frame_time, chunk_index, kind) DO NOTHING
           RETURNING id""",
        (camera_id, to_iso(frame_time), chunk_index, kind, etag, data, to_iso(now or utc_now())),
    ).fetchall()
    return row[0]["id"] if row else None


def claim_next(con: sqlite3.Connection, now: datetime | None = None) -> dict[str, Any] | None:
    """Atomically move the oldest pending chunk to 'processing' and return it (None if the queue is empty).

    Postgres equivalent: the same UPDATE with `... LIMIT 1 FOR UPDATE SKIP LOCKED` in the subquery.
    """
    with _tx(con, immediate=True):
        rows = con.execute(
            """UPDATE clips SET status = 'processing', claimed_at = ?, attempts = attempts + 1
               WHERE id = (SELECT id FROM clips WHERE status = 'pending' ORDER BY frame_time, id LIMIT 1)
               RETURNING *""",
            (to_iso(now or utc_now()),),
        ).fetchall()
    return dict(rows[0]) if rows else None


def mark_done(con: sqlite3.Connection, clip_id: int, now: datetime | None = None) -> None:
    """Mark a chunk processed and drop its media bytes."""
    con.execute("UPDATE clips SET status = 'done', data = NULL, finished_at = ? WHERE id = ?",
                (to_iso(now or utc_now()), clip_id))


def mark_failed(con: sqlite3.Connection, clip_id: int, error: str, now: datetime | None = None) -> None:
    """Mark a chunk failed with its error and drop its media bytes (privacy: no video kept)."""
    con.execute("UPDATE clips SET status = 'failed', error = ?, data = NULL, finished_at = ? WHERE id = ?",
                (error[:2000], to_iso(now or utc_now()), clip_id))


def requeue_expired(con: sqlite3.Connection, timeout_s: int | None = None, max_attempts: int | None = None,
                    now: datetime | None = None) -> int:
    """Return stale 'processing' claims (crashed worker) to 'pending'; fail those out of attempts.

    Returns the number requeued.
    """
    now = now or utc_now()
    cutoff = to_iso(now - timedelta(seconds=timeout_s if timeout_s is not None else SETTINGS.claim_timeout_s))
    max_attempts = max_attempts if max_attempts is not None else SETTINGS.max_attempts
    with _tx(con, immediate=True):
        con.execute(
            """UPDATE clips SET status = 'failed', error = 'claim expired after max attempts',
                                data = NULL, finished_at = ?
               WHERE status = 'processing' AND claimed_at < ? AND attempts >= ?""",
            (to_iso(now), cutoff, max_attempts),
        )
        cur = con.execute(
            "UPDATE clips SET status = 'pending', claimed_at = NULL WHERE status = 'processing' AND claimed_at < ?",
            (cutoff,),
        )
    return cur.rowcount


# ------------------------------------------------------------------- observations

def insert_observation(con: sqlite3.Connection, obs: Mapping[str, Any], now: datetime | None = None) -> bool:
    """Idempotently store one observation row; returns False if it was already there."""
    row = {k: obs[k] for k in OBSERVATION_COLUMNS if k in obs}
    row["frame_time"] = to_iso(row["frame_time"])
    row["ingested_at"] = to_iso(row.get("ingested_at") or now or utc_now())
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    cur = con.execute(
        f"""INSERT INTO observations ({cols}) VALUES ({marks})
            ON CONFLICT (camera_id, frame_time, chunk_index, kind) DO NOTHING""",
        tuple(row.values()),
    )
    return cur.rowcount == 1


def latest_observation_per_camera(con: sqlite3.Connection, since_minutes: int = 60,
                                  now: datetime | None = None) -> list[dict[str, Any]]:
    """Every active camera with its newest observation in the last `since_minutes` (obs fields None if none)."""
    cutoff = to_iso((now or utc_now()) - timedelta(minutes=since_minutes))
    rows = con.execute(
        """SELECT c.camera_id, c.name, c.lat, c.lon, c.view, c.image_url, c.video_url, c.tier,
                  c.homography IS NOT NULL AS calibrated,
                  o.frame_time, o.ingested_at, o.kind, o.people, o.density, o.speed, o.heading, o.quality
           FROM cameras c
           LEFT JOIN (
             SELECT *, ROW_NUMBER() OVER (PARTITION BY camera_id
                                          ORDER BY frame_time DESC, chunk_index DESC) AS rn
             FROM observations WHERE frame_time >= ?
           ) o ON o.camera_id = c.camera_id AND o.rn = 1
           WHERE c.active = 1
           ORDER BY c.camera_id""",
        (cutoff,),
    ).fetchall()
    return [dict(r) for r in rows]


def camera_history(con: sqlite3.Connection, camera_id: str, minutes: int = 60,
                   now: datetime | None = None) -> list[dict[str, Any]]:
    """One camera's observations from the last `minutes`, oldest first."""
    cutoff = to_iso((now or utc_now()) - timedelta(minutes=minutes))
    rows = con.execute(
        """SELECT frame_time, kind, people, density, speed, heading, quality FROM observations
           WHERE camera_id = ? AND frame_time >= ? ORDER BY frame_time, chunk_index""",
        (camera_id, cutoff),
    ).fetchall()
    return [dict(r) for r in rows]


def queue_stats(con: sqlite3.Connection, window_minutes: int = 10,
                now: datetime | None = None) -> dict[str, Any]:
    """Queue depth by status, recent throughput, mean seconds per chunk and data lag."""
    now = now or utc_now()
    cutoff = to_iso(now - timedelta(minutes=window_minutes))
    by_status = dict.fromkeys(STATUSES, 0)
    by_status.update({r["status"]: r["n"] for r in
                      con.execute("SELECT status, COUNT(*) AS n FROM clips GROUP BY status")})
    recent_obs, mean_ms = con.execute(
        "SELECT COUNT(*), AVG(proc_ms) FROM observations WHERE ingested_at >= ?", (cutoff,)).fetchone()
    newest = con.execute("SELECT MAX(frame_time) FROM observations").fetchone()[0]
    return {
        "by_status": by_status,
        "observations_recent": recent_obs,
        "window_minutes": window_minutes,
        "mean_seconds_per_chunk": mean_ms / 1000 if mean_ms is not None else None,  # from proc_ms
        "newest_frame_time": newest,
        "lag_seconds": (now - datetime.fromisoformat(newest)).total_seconds() if newest else None,
    }


if __name__ == "__main__":
    con = connect()
    init_db(con)
    print(sqlite_path(SETTINGS.db_url))
    print([r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view') ORDER BY name")])
