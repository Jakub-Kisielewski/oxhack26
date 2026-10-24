from datetime import datetime, timedelta, timezone

import numpy as np

from src.pipeline import db
from src.pipeline.run_workers import restart_dead
from src.pipeline.worker import Worker
from media import make_mp4

T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


class FakeDetector:
    name = "fake@0"

    def detect(self, frames):
        return [np.array([[0, 0, 5, 5, 0.9], [9, 9, 20, 20, 0.8]]) for _ in frames]


class Exploding(FakeDetector):
    def detect(self, frames):
        raise RuntimeError("mps out of memory")


def _setup(con):
    db.upsert_cameras(con, [{"camera_id": "A", "name": "Cam A", "lat": 51.5, "lon": -0.12, "tier": 2}])
    return db.enqueue_clip(con, "A", T0, make_mp4(3))


def test_process_one_stores_observation_with_proc_ms_and_drops_media(con):
    clip_id = _setup(con)
    assert Worker(con, FakeDetector()).process_one() == "done"
    obs = dict(con.execute("SELECT * FROM observations").fetchone())
    assert (obs["camera_id"], obs["frame_time"], obs["people"], obs["quality"]) == ("A", db.to_iso(T0), 2.0, "ok")
    assert obs["lat"] == 51.5 and obs["kind"] == "clip"
    assert isinstance(obs["proc_ms"], int) and obs["proc_ms"] >= 0
    clip = dict(con.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone())
    assert clip["status"] == "done" and clip["data"] is None


def test_process_one_marks_failures_and_keeps_going(con):
    clip_id = _setup(con)
    w = Worker(con, Exploding())
    assert w.process_one() == "failed"
    clip = dict(con.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone())
    assert clip["status"] == "failed" and "out of memory" in clip["error"] and clip["data"] is None
    assert w.process_one() is None


def test_process_one_requeues_expired_claims_first(con):
    clip_id = _setup(con)
    db.claim_next(con, now=db.utc_now() - timedelta(minutes=10))  # a crashed worker's claim
    assert Worker(con, FakeDetector()).process_one() == "done"
    assert con.execute("SELECT status FROM clips WHERE id = ?", (clip_id,)).fetchone()[0] == "done"


def test_run_until_empty_processes_everything(con):
    _setup(con)
    db.enqueue_clip(con, "A", T0 + timedelta(minutes=5), make_mp4(2))
    Worker(con, FakeDetector()).run(until_empty=True)
    assert con.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 2


def test_restart_dead_replaces_only_dead_processes():
    class P:
        def __init__(self, alive):
            self.alive = alive

        def is_alive(self):
            return self.alive

    procs = {0: P(True), 1: P(False), 2: P(False)}
    started = []
    assert restart_dead(procs, lambda i: started.append(i) or P(True)) == [1, 2]
    assert started == [1, 2] and all(p.is_alive() for p in procs.values())
