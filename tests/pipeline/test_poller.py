import logging
import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest
import requests

from src.pipeline import db
from src.pipeline.config import Settings
from src.pipeline.poller import BandwidthValve, Poller, PriorityPool, TierLoop, check_camera, tier_loops
from media import make_mp4

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
CLIP = make_mp4(2, fps=10)


class Resp:
    def __init__(self, status=200, etag=None, last_modified=None, content=b""):
        self.status_code = status
        self.headers = {k: v for k, v in (("ETag", etag), ("Last-Modified", last_modified)) if v}
        self.content = content


class FakeTfL:
    """Serves one (etag, upload time, bytes) per URL; counts requests."""

    def __init__(self):
        self.files: dict[str, tuple[str, datetime, bytes]] = {}
        self.fail: set[str] = set()
        self.heads = self.gets = 0

    def publish(self, url, etag, uploaded, data=CLIP):
        self.files[url] = (etag, uploaded, data)

    def _resp(self, url, with_body):
        if url in self.fail:
            raise requests.ConnectionError("boom")
        etag, uploaded, data = self.files[url]
        return Resp(200, etag, format_datetime(uploaded, usegmt=True), data if with_body else b"")

    def head(self, url, timeout=None):
        self.heads += 1
        return self._resp(url, False)

    def get(self, url, timeout=None):
        self.gets += 1
        return self._resp(url, True)


def _cam(camera_id, tier=2):
    return {"camera_id": camera_id, "video_url": f"https://tfl/{camera_id}.mp4",
            "image_url": f"https://tfl/{camera_id}.jpg", "tier": tier}


@pytest.fixture
def tfl():
    return FakeTfL()


T2 = TierLoop(2, "clip", 15)


@pytest.fixture
def poller(db_url, con, tfl):
    p = Poller(replace(Settings(), head_threads=8, db_url=db_url), session=tfl, refresh_registry=False)
    yield p
    p.pool.shutdown()


def _clips(con):
    return [dict(r) for r in con.execute("SELECT camera_id, frame_time, kind, etag, data FROM clips ORDER BY id")]


def test_changed_etag_enqueues_with_last_modified_as_frame_time(poller, tfl, con):
    tfl.publish("https://tfl/A.mp4", '"e1"', NOW - timedelta(seconds=30))
    stats = poller.poll_round(con, [_cam("A")], T2, now=NOW)
    assert (stats.new, stats.enqueued) == (1, 1)
    [clip] = _clips(con)
    assert clip["frame_time"] == db.to_iso(NOW - timedelta(seconds=30))
    assert (clip["kind"], clip["etag"], clip["data"]) == ("clip", '"e1"', CLIP)


def test_unchanged_etag_does_nothing(poller, tfl, con):
    tfl.publish("https://tfl/A.mp4", '"e1"', NOW - timedelta(seconds=30))
    poller.poll_round(con, [_cam("A")], T2, now=NOW)
    gets = tfl.gets
    stats = poller.poll_round(con, [_cam("A")], T2, now=NOW + timedelta(seconds=15))
    assert (stats.unchanged, stats.new, stats.enqueued) == (1, 0, 0)
    assert tfl.gets == gets  # HEAD only, no download
    tfl.publish("https://tfl/A.mp4", '"e2"', NOW + timedelta(seconds=240))
    stats = poller.poll_round(con, [_cam("A")], T2, now=NOW + timedelta(seconds=250))
    assert stats.enqueued == 1 and len(_clips(con)) == 2


def test_stale_upload_is_skipped_without_download(poller, tfl, con):
    tfl.publish("https://tfl/A.mp4", '"e1"', NOW - timedelta(seconds=901))
    stats = poller.poll_round(con, [_cam("A")], T2, now=NOW)
    assert (stats.stale, stats.enqueued, tfl.gets) == (1, 0, 0)
    assert _clips(con) == []


def test_uploads_older_than_lag_minus_margin_are_not_downloaded(poller, tfl, con, caplog):
    tfl.publish("https://tfl/A.mp4", '"e1"', NOW - timedelta(seconds=55))   # clip LAG 60 - 10 s margin = 50
    tfl.publish("https://tfl/B.mp4", '"e1"', NOW - timedelta(seconds=20))
    tfl.publish("https://tfl/C.jpg", '"s1"', NOW - timedelta(seconds=100))  # still: 120 - 10 = 110, fresh enough
    tfl.publish("https://tfl/D.jpg", '"s1"', NOW - timedelta(seconds=115))  # still: too old
    with caplog.at_level(logging.INFO):
        stats = poller.poll_round(con, [_cam("A"), _cam("B")], T2, now=NOW)
    assert (stats.too_old, stats.enqueued, tfl.gets) == (1, 1, 1)
    assert "tier 2: skipped 1 too-old uploads" in caplog.text
    assert db.poll_rounds_since(con, NOW - timedelta(minutes=1))[0]["too_old"] == 1
    # remembered: the old upload is not re-checked for download next round
    assert poller.poll_round(con, [_cam("A")], T2, now=NOW + timedelta(seconds=15)).unchanged == 1
    still = poller.poll_round(con, [_cam("C", tier=0), _cam("D", tier=0)], TierLoop(0, "still", 60), now=NOW)
    assert (still.enqueued, still.too_old) == (1, 1)


def test_each_upload_is_enqueued_when_its_download_finishes(poller, tfl, con, monkeypatch):
    class OneSlow(FakeTfL):
        def head(self, url, timeout=None):
            if "SLOW" in url:
                time.sleep(1.0)
            return super().head(url, timeout)
    slow_tfl = OneSlow()
    poller.session = slow_tfl
    for cid in ("FAST", "SLOW"):
        slow_tfl.publish(f"https://tfl/{cid}.mp4", '"e"', NOW - timedelta(seconds=5))
    enqueued_at = {}
    real_enqueue = db.enqueue_clip
    monkeypatch.setattr(db, "enqueue_clip", lambda con_, cid, *a, **k: (enqueued_at.setdefault(cid, time.monotonic()),
                                                                         real_enqueue(con_, cid, *a, **k))[1])
    t0 = time.monotonic()
    stats = poller.poll_round(con, [_cam("SLOW"), _cam("FAST")], T2, now=NOW)
    assert stats.enqueued == 2
    assert enqueued_at["FAST"] - t0 < 0.5 and enqueued_at["SLOW"] - t0 >= 1.0  # FAST did not wait for SLOW


def test_errors_are_counted_and_do_not_stop_the_round(poller, tfl, con):
    tfl.publish("https://tfl/A.mp4", '"e1"', NOW - timedelta(seconds=10))
    tfl.publish("https://tfl/B.mp4", '"e1"', NOW - timedelta(seconds=10))
    tfl.fail.add("https://tfl/B.mp4")
    stats = poller.poll_round(con, [_cam("A"), _cam("B")], T2, now=NOW)
    assert (stats.errors, stats.enqueued) == (1, 1)
    assert ("B", "clip") not in poller.etags  # retried next round


def test_restart_does_not_double_enqueue(con, tfl):
    tfl.publish("https://tfl/A.mp4", '"e1"', NOW - timedelta(seconds=10))
    for _ in range(2):  # two poller processes in a row, each with empty ETag memory
        p = Poller(Settings(), session=tfl, refresh_registry=False)
        p.poll_round(con, [_cam("A")], T2, now=NOW)
        p.pool.shutdown()
    assert len(_clips(con)) == 1


def test_tier1_stills_enqueue_as_still(poller, tfl, con):
    tfl.publish("https://tfl/B.jpg", '"s1"', NOW - timedelta(seconds=30), b"jpeg-bytes")
    stats = poller.poll_round(con, [_cam("B", tier=1)], TierLoop(1, "still", 60), now=NOW)
    assert stats.enqueued == 1
    assert _clips(con)[0]["kind"] == "still" and _clips(con)[0]["data"] == b"jpeg-bytes"


def test_check_camera_reports_http_errors():
    class NotFound(FakeTfL):
        def head(self, url, timeout=None):
            return Resp(404)
    assert check_camera(NotFound(), "A", "u", None, 900, NOW).status == "error"


def test_rounds_are_recorded_with_bytes(poller, tfl, con):
    tfl.publish("https://tfl/A.mp4", '"e1"', NOW - timedelta(seconds=30))
    poller.poll_round(con, [_cam("A")], T2, now=NOW)
    [r] = db.poll_rounds_since(con, NOW - timedelta(minutes=1))
    assert (r["tier"], r["kind"], r["new"], r["bytes"], r["overran"]) == (2, "clip", 1, len(CLIP), 0)
    assert con.execute("SELECT size_bytes FROM clips").fetchone()[0] == len(CLIP)


def test_tier_loops_from_settings():
    assert [(l.tier, l.kind, l.interval_s) for l in tier_loops(Settings())] == [(2, "clip", 15), (1, "clip", 15),
                                                                               (0, "still", 60)]
    only2 = replace(Settings(), tier1_enabled=False, tier0_enabled=False)
    assert [l.tier for l in tier_loops(only2)] == [2]
    with pytest.raises(ValueError):
        tier_loops(replace(Settings(), tier0_kind="video"))


def test_priority_pool_runs_tier2_before_queued_lower_tiers():
    pool = PriorityPool(1)
    gate, order = threading.Event(), []
    pool.submit(0, gate.wait)  # occupy the only worker
    low = [pool.submit(2, order.append, f"t0-{i}") for i in range(3)]
    high = [pool.submit(0, order.append, f"t2-{i}") for i in range(2)]
    gate.set()
    for f in low + high:
        f.result(timeout=5)
    pool.shutdown()
    assert order == ["t2-0", "t2-1", "t0-0", "t0-1", "t0-2"]


def test_reserved_threads_keep_tier2_running_while_lower_tiers_block():
    pool = PriorityPool(3, reserved=1)
    gate, started = threading.Event(), []
    low = [pool.submit(2, lambda i=i: (started.append(i), gate.wait())) for i in range(4)]
    time.sleep(0.2)
    assert len(started) == 2  # the reserved thread never takes tier-0 work
    assert pool.submit(0, lambda: "tier2").result(timeout=2) == "tier2"  # runs while the others block
    gate.set()
    for f in low:
        f.result(timeout=5)
    pool.shutdown()
    with pytest.raises(ValueError):
        PriorityPool(4, reserved=4)


def test_valve_pauses_after_consecutive_slow_tier2_rounds():
    now = [0.0]
    valve = BandwidthValve(slow_s=15, slow_rounds=2, pause_s=300, clock=lambda: now[0])
    assert valve.record_tier2(20) is False          # one slow round
    assert valve.record_tier2(5) is False           # streak broken
    assert valve.record_tier2(16) is False
    assert valve.record_tier2(30) is True and valve.is_paused()
    now[0] = 299
    assert valve.is_paused() and valve.record_tier2(40) is False and valve.record_tier2(40) is False
    now[0] = 301
    assert not valve.is_paused()


def test_tier0_loop_skips_rounds_while_paused(db_url, con, tfl, caplog):
    db.upsert_cameras(con, [_cam("C", tier=0)])
    tfl.publish("https://tfl/C.jpg", '"s"', db.utc_now(), b"jpeg")
    p = Poller(replace(Settings(), db_url=db_url), session=tfl, refresh_registry=False)
    p.valve.paused_until = time.monotonic() + 0.6
    t = threading.Thread(target=p.tier_loop, args=(TierLoop(0, "still", 0.2),))
    with caplog.at_level(logging.INFO):
        t.start()
        time.sleep(0.4)
        assert db.poll_rounds_since(con, db.utc_now() - timedelta(minutes=1)) == []  # paused: no rounds
        time.sleep(0.6)
        p.stop_event.set()
        t.join(timeout=5)
    p.pool.shutdown()
    assert db.poll_rounds_since(con, db.utc_now() - timedelta(minutes=1))  # resumed
    assert "tier 0 resumed" in caplog.text


def test_slow_tier2_rounds_record_a_pause_event(db_url, con, caplog):
    tfl = SlowTfL()
    db.upsert_cameras(con, [_cam("A")])
    tfl.publish("https://tfl/A.mp4", '"e"', db.utc_now())
    s = replace(Settings(), db_url=db_url, poll_seconds=0.1, valve_pause_seconds=60)
    p = Poller(s, session=tfl, refresh_registry=False)
    t = threading.Thread(target=p.tier_loop, args=(TierLoop(2, "clip", 0.1),))
    with caplog.at_level(logging.WARNING):
        t.start()
        time.sleep(1.0)
        p.stop_event.set()
        t.join(timeout=5)
    p.pool.shutdown()
    assert "tier 0 paused for 60 s (bandwidth)" in caplog.text
    assert db.active_pause(con)["event"] == "tier0_paused"


def test_run_once_polls_every_enabled_tier_with_its_kind(db_url, con, tfl):
    db.upsert_cameras(con, [_cam("A"), _cam("B", tier=1), _cam("C", tier=0), {**_cam("D"), "active": False}])
    uploaded = db.utc_now() - timedelta(seconds=5)  # run() uses the real clock
    for cid in "ABCD":
        tfl.publish(f"https://tfl/{cid}.mp4", '"e"', uploaded)
        tfl.publish(f"https://tfl/{cid}.jpg", '"e"', uploaded, b"jpeg")
    Poller(replace(Settings(), db_url=db_url), session=tfl, refresh_registry=False).run(once=True)
    assert {(c["camera_id"], c["kind"]) for c in _clips(con)} == {("A", "clip"), ("B", "clip"), ("C", "still")}


class SlowTfL(FakeTfL):
    def head(self, url, timeout=None):
        time.sleep(0.35)
        return super().head(url, timeout)


def test_overrunning_loop_skips_ticks_and_never_overlaps(db_url, con, caplog):
    tfl = SlowTfL()
    db.upsert_cameras(con, [_cam("A")])
    tfl.publish("https://tfl/A.mp4", '"e"', db.utc_now() - timedelta(seconds=5))
    p = Poller(replace(Settings(), db_url=db_url, poll_seconds=0.1), session=tfl, refresh_registry=False)
    loop = TierLoop(2, "clip", 0.1)
    t = threading.Thread(target=p.tier_loop, args=(loop,))
    with caplog.at_level(logging.WARNING):
        t.start()
        time.sleep(1.2)
        p.stop_event.set()
        t.join(timeout=5)
    p.pool.shutdown()
    rounds = db.poll_rounds_since(con, db.utc_now() - timedelta(minutes=1))
    assert 2 <= len(rounds) <= 4  # ~0.35 s rounds in 1.2 s, not one per 0.1 s tick
    assert all(r["overran"] for r in rounds)
    assert "tier 2 overran" in caplog.text
    assert not t.is_alive()


def test_run_stops_all_loops_on_stop_event(db_url, con, tfl):
    db.upsert_cameras(con, [_cam("A"), _cam("B", tier=1), _cam("C", tier=0)])
    for cid in "ABC":
        tfl.publish(f"https://tfl/{cid}.mp4", '"e"', db.utc_now())
        tfl.publish(f"https://tfl/{cid}.jpg", '"e"', db.utc_now())
    p = Poller(replace(Settings(), db_url=db_url), session=tfl, refresh_registry=False)
    runner = threading.Thread(target=p.run)
    runner.start()
    time.sleep(0.5)
    p.stop_event.set()
    runner.join(timeout=5)
    assert not runner.is_alive()
    assert {r["tier"] for r in db.poll_rounds_since(con, db.utc_now() - timedelta(minutes=1))} == {0, 1, 2}
