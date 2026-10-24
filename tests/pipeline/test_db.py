import multiprocessing
import re
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import pytest

from src.pipeline import db

T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


def _cam(camera_id, tier=2, **kw):
    return {"camera_id": camera_id, "name": camera_id, "lat": 51.5, "lon": -0.12, "view": "v",
            "image_url": f"{camera_id}.jpg", "video_url": f"{camera_id}.mp4", "tier": tier, **kw}


def _status(con, clip_id):
    return dict(con.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone())


def _claim_all(db_url, start_at=0.0, work_s=0.001):
    """Wait until wall time `start_at`, then claim until the queue is empty; return the claimed ids."""
    con = db.connect(db_url)
    time.sleep(max(0.0, start_at - time.time()))
    ids = []
    while (clip := db.claim_next(con)) is not None:
        ids.append(clip["id"])
        time.sleep(work_s)  # simulated processing so claimers interleave
    con.close()
    return ids


# ------------------------------------------------------------------- helpers

CANONICAL = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$")


def test_to_iso_normalises_every_input_to_one_format():
    bst = timezone(timedelta(hours=1))
    expected = "2026-10-24T12:00:00+00:00"
    assert db.to_iso(datetime(2026, 10, 24, 13, 0, tzinfo=bst)) == expected
    assert db.to_iso(datetime(2026, 10, 24, 12, 0, 0, 987654, tzinfo=timezone.utc)) == expected
    assert db.to_iso("2026-10-24T12:00:00Z") == expected
    assert db.to_iso("2026-10-24T12:00:00.5+00:00") == expected
    assert db.to_iso("2026-10-24T13:00:00+01:00") == expected
    assert db.to_iso("Sat, 24 Oct 2026 12:00:00 GMT") == expected
    with pytest.raises(ValueError):
        db.to_iso(datetime(2026, 10, 24, 12, 0))


def test_stored_times_share_one_format_and_sort_chronologically(con):
    """Mix Last-Modified headers, datetime.now(utc) and 'Z' strings; text order must equal time order."""
    now = datetime.now(timezone.utc)  # has microseconds
    times = [
        ("hdr_early", "Sat, 24 Oct 2026 09:59:59 GMT"),
        ("hdr_late", "Sat, 24 Oct 2026 10:00:01 GMT"),
        ("iso_z", "2026-10-24T10:00:00Z"),
        ("bst", datetime(2026, 10, 24, 11, 0, 0, 500000, tzinfo=timezone(timedelta(hours=1)))),  # 10:00:00 UTC
        ("now", now),
        ("now_minus", now - timedelta(seconds=1)),
    ]

    def as_utc(t):  # independent of db.to_iso: parse to an aware datetime, whole seconds
        if isinstance(t, str):
            t = parsedate_to_datetime(t) if "GMT" in t else datetime.fromisoformat(t)
        return t.astimezone(timezone.utc).replace(microsecond=0)

    for cam, t in times:
        frame_time = parsedate_to_datetime(t) if isinstance(t, str) and "GMT" in t else t  # as the poller will
        db.insert_observation(con, _obs(cam, frame_time, 1), now=now)
        clip_id = db.enqueue_clip(con, cam, frame_time, b"x", now=now)
    db.claim_next(con, now=now)
    db.mark_done(con, clip_id, now=now)

    stored = [r[0] for r in con.execute(
        """SELECT frame_time FROM observations UNION ALL SELECT ingested_at FROM observations
           UNION ALL SELECT frame_time FROM clips UNION ALL SELECT ingested_at FROM clips
           UNION ALL SELECT claimed_at FROM clips WHERE claimed_at IS NOT NULL
           UNION ALL SELECT finished_at FROM clips WHERE finished_at IS NOT NULL""")]
    assert stored and all(CANONICAL.match(s) for s in stored), stored

    by_text = [r[0] for r in con.execute("SELECT camera_id FROM observations ORDER BY frame_time, camera_id")]
    by_time = [cam for cam, t in sorted(times, key=lambda ct: (as_utc(ct[1]), ct[0]))]
    assert by_text == by_time
    assert by_text[:4] == ["hdr_early", "bst", "iso_z", "hdr_late"]
    # text comparison against a cutoff matches time comparison
    newer = [r[0] for r in con.execute("SELECT camera_id FROM observations WHERE frame_time >= ? ORDER BY camera_id",
                                       (db.to_iso("2026-10-24T10:00:00+00:00"),))]
    assert newer == sorted(["bst", "iso_z", "hdr_late", "now", "now_minus"])


def test_sqlite_path_resolution_and_postgres_rejected():
    assert db.sqlite_path("sqlite:///data/pipeline.db") == db.REPO_ROOT / "data" / "pipeline.db"
    assert str(db.sqlite_path("sqlite:////tmp/x.db")) == "/tmp/x.db"
    with pytest.raises(NotImplementedError):
        db.connect("postgresql://localhost/pipeline")


def test_read_only_connection_cannot_write(con, db_url):
    ro = db.connect(db_url, read_only=True)
    with pytest.raises(Exception):
        ro.execute("INSERT INTO cameras (camera_id) VALUES ('x')")
    ro.close()


# ------------------------------------------------------------------- cameras

def test_upsert_cameras_updates_fields_and_keeps_homography(con):
    db.upsert_cameras(con, [_cam("A", tier=0)], now=T0)
    con.execute("UPDATE cameras SET homography = '[[1,0,0],[0,1,0],[0,0,1]]' WHERE camera_id = 'A'")
    db.upsert_cameras(con, [_cam("A", tier=2, name="renamed")], now=T0)
    row = dict(con.execute("SELECT * FROM cameras WHERE camera_id = 'A'").fetchone())
    assert (row["name"], row["tier"], row["active"]) == ("renamed", 2, 1)
    assert row["homography"] is not None
    assert con.execute("SELECT COUNT(*) FROM cameras").fetchone()[0] == 1


# ------------------------------------------------------------------- queue

def test_enqueue_is_idempotent(con):
    first = db.enqueue_clip(con, "A", T0, b"mp4", etag="e1", now=T0)
    again = db.enqueue_clip(con, "A", T0.isoformat(), b"mp4", etag="e1", now=T0)
    assert first is not None and again is None
    assert con.execute("SELECT COUNT(*) FROM clips").fetchone()[0] == 1
    # a different chunk, kind or frame_time is a different job
    assert db.enqueue_clip(con, "A", T0, b"mp4", chunk_index=1) is not None
    assert db.enqueue_clip(con, "A", T0, b"jpg", kind="still") is not None
    assert db.enqueue_clip(con, "A", T0 + timedelta(minutes=5), b"mp4") is not None


def test_enqueue_rejects_unknown_kind(con):
    with pytest.raises(Exception):
        db.enqueue_clip(con, "A", T0, b"x", kind="video")


def test_claim_returns_oldest_first_and_marks_processing(con):
    late = db.enqueue_clip(con, "A", T0 + timedelta(minutes=5), b"late")
    early = db.enqueue_clip(con, "B", T0, b"early")
    clip = db.claim_next(con, now=T0)
    assert clip["id"] == early and clip["data"] == b"early"
    assert (clip["status"], clip["attempts"], clip["claimed_at"]) == ("processing", 1, "2026-10-24T12:00:00+00:00")
    assert db.claim_next(con)["id"] == late
    assert db.claim_next(con) is None


def test_two_threads_never_double_claim(con, db_url):
    ids = {db.enqueue_clip(con, f"cam{i % 7}", T0 + timedelta(seconds=i), b"x") for i in range(300)}
    results: list[list[int]] = [[] for _ in range(4)]
    start_at = time.time() + 0.3
    threads = [threading.Thread(target=lambda r=r: r.extend(_claim_all(db_url, start_at))) for r in results]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    claimed = [i for r in results for i in r]
    assert len(claimed) == len(set(claimed)) == 300
    assert set(claimed) == ids
    assert all(results)  # every claimer got work, so they really ran concurrently


def test_two_processes_never_double_claim(con, db_url):
    ids = {db.enqueue_clip(con, f"cam{i % 7}", T0 + timedelta(seconds=i), b"x") for i in range(200)}
    with ProcessPoolExecutor(2, mp_context=multiprocessing.get_context("spawn")) as pool:
        start_at = time.time() + 2.0  # covers spawn start-up
        results = list(pool.map(_claim_all, [db_url, db_url], [start_at, start_at]))
    claimed = [i for r in results for i in r]
    assert len(claimed) == len(set(claimed)) == 200
    assert set(claimed) == ids
    assert all(results)


def test_requeue_expired_returns_stale_claims_to_pending(con):
    clip_id = db.enqueue_clip(con, "A", T0, b"x")
    db.claim_next(con, now=T0)
    assert db.requeue_expired(con, timeout_s=300, now=T0 + timedelta(seconds=299)) == 0
    assert db.requeue_expired(con, timeout_s=300, now=T0 + timedelta(seconds=301)) == 1
    row = _status(con, clip_id)
    assert (row["status"], row["claimed_at"], row["data"]) == ("pending", None, b"x")
    assert db.claim_next(con)["id"] == clip_id


def test_requeue_expired_fails_after_max_attempts(con):
    clip_id = db.enqueue_clip(con, "A", T0, b"x")
    t = T0
    for _ in range(2):
        db.claim_next(con, now=t)
        t += timedelta(seconds=400)
        db.requeue_expired(con, timeout_s=300, max_attempts=2, now=t)
    row = _status(con, clip_id)
    assert row["status"] == "failed" and row["data"] is None and "max attempts" in row["error"]


def test_mark_done_and_failed_drop_media(con):
    done_id = db.enqueue_clip(con, "A", T0, b"x")
    fail_id = db.enqueue_clip(con, "B", T0, b"y")
    db.claim_next(con, now=T0)
    db.claim_next(con, now=T0)
    db.mark_done(con, done_id, now=T0 + timedelta(seconds=4))
    db.mark_failed(con, fail_id, "cannot open clip", now=T0 + timedelta(seconds=1))
    done, failed = _status(con, done_id), _status(con, fail_id)
    assert (done["status"], done["data"], done["finished_at"]) == ("done", None, db.to_iso(T0 + timedelta(seconds=4)))
    assert (failed["status"], failed["data"], failed["error"]) == ("failed", None, "cannot open clip")


# ------------------------------------------------------------------- observations

def _obs(camera_id, t, people, **kw):
    return {"camera_id": camera_id, "frame_time": t, "people": people, "quality": "ok",
            "lat": 51.5, "lon": -0.12, **kw}


def test_insert_observation_is_idempotent(con):
    assert db.insert_observation(con, _obs("A", T0, 3), now=T0) is True
    assert db.insert_observation(con, _obs("A", T0, 99), now=T0) is False
    row = dict(con.execute("SELECT * FROM observations").fetchone())
    assert row["people"] == 3 and row["ingested_at"] == db.to_iso(T0) and row["kind"] == "clip"


def test_latest_observation_per_camera(con):
    db.upsert_cameras(con, [_cam("A"), _cam("B", tier=0)])
    db.insert_observation(con, _obs("A", T0 - timedelta(minutes=10), 1))
    db.insert_observation(con, _obs("A", T0 - timedelta(minutes=5), 7, speed=0.8))
    db.insert_observation(con, _obs("A", T0 - timedelta(minutes=90), 50))  # outside the window
    rows = {r["camera_id"]: r for r in db.latest_observation_per_camera(con, since_minutes=60, now=T0)}
    assert set(rows) == {"A", "B"}
    assert rows["A"]["people"] == 7 and rows["A"]["speed"] == 0.8 and rows["A"]["calibrated"] == 0
    assert rows["B"]["people"] is None and rows["B"]["frame_time"] is None


def test_camera_history_window_and_order(con):
    for m, n in [(70, 1), (30, 2), (10, 3)]:
        db.insert_observation(con, _obs("A", T0 - timedelta(minutes=m), n))
    db.insert_observation(con, _obs("B", T0 - timedelta(minutes=10), 9))
    hist = db.camera_history(con, "A", minutes=60, now=T0)
    assert [h["people"] for h in hist] == [2, 3]


def test_queue_stats(con):
    a = db.enqueue_clip(con, "A", T0, b"x")
    db.enqueue_clip(con, "B", T0, b"y")
    db.claim_next(con, now=T0)
    db.mark_done(con, a, now=T0 + timedelta(seconds=9))  # whole-second timestamps are not used for timing
    db.insert_observation(con, _obs("A", T0 - timedelta(seconds=30), 2, proc_ms=3500), now=T0 + timedelta(seconds=4))
    db.insert_observation(con, _obs("C", T0 - timedelta(seconds=40), 2, proc_ms=4500), now=T0 + timedelta(seconds=4))
    s = db.queue_stats(con, now=T0 + timedelta(seconds=60))
    assert s["by_status"] == {"pending": 1, "processing": 0, "done": 1, "failed": 0}
    assert s["observations_recent"] == 2
    assert s["mean_seconds_per_chunk"] == pytest.approx(4.0)
    assert s["lag_seconds"] == pytest.approx(90.0)


def test_init_db_adds_proc_ms_to_an_existing_db(db_url):
    old = db.connect(db_url)
    old.execute("CREATE TABLE observations (camera_id TEXT NOT NULL, frame_time TEXT NOT NULL, "
                "chunk_index INTEGER NOT NULL DEFAULT 0, kind TEXT NOT NULL DEFAULT 'clip', ingested_at TEXT NOT NULL, "
                "people REAL, UNIQUE (camera_id, frame_time, chunk_index, kind))")
    db.init_db(old)
    db.init_db(old)  # idempotent
    assert "proc_ms" in {r["name"] for r in old.execute("PRAGMA table_info(observations)")}
    old.close()


def test_all_cameras_includes_inactive(con):
    db.upsert_cameras(con, [_cam("A"), _cam("B", active=False)])
    assert {(c["camera_id"], c["active"]) for c in db.all_cameras(con)} == {("A", 1), ("B", 0)}
    assert db.camera_tiers(con) == {"A": 2, "B": 2}


def test_queue_stats_empty(con):
    s = db.queue_stats(con, now=T0)
    assert s["mean_seconds_per_chunk"] is None and s["lag_seconds"] is None
