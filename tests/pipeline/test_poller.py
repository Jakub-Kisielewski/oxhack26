from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest
import requests

from src.pipeline import db
from src.pipeline.config import Settings
from src.pipeline.poller import Poller, check_camera
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


@pytest.fixture
def poller(con, tfl):
    p = Poller(con, replace(Settings(), head_threads=4), session=tfl, refresh_registry=False)
    yield p
    p.pool.shutdown()


def _clips(con):
    return [dict(r) for r in con.execute("SELECT camera_id, frame_time, kind, etag, data FROM clips ORDER BY id")]


def test_changed_etag_enqueues_with_last_modified_as_frame_time(poller, tfl, con):
    tfl.publish("https://tfl/A.mp4", '"e1"', NOW - timedelta(seconds=60))
    stats = poller.poll_round([_cam("A")], "clip", now=NOW)
    assert (stats.new, stats.enqueued) == (1, 1)
    [clip] = _clips(con)
    assert clip["frame_time"] == db.to_iso(NOW - timedelta(seconds=60))
    assert (clip["kind"], clip["etag"], clip["data"]) == ("clip", '"e1"', CLIP)


def test_unchanged_etag_does_nothing(poller, tfl, con):
    tfl.publish("https://tfl/A.mp4", '"e1"', NOW - timedelta(seconds=60))
    poller.poll_round([_cam("A")], "clip", now=NOW)
    gets = tfl.gets
    stats = poller.poll_round([_cam("A")], "clip", now=NOW + timedelta(seconds=15))
    assert (stats.unchanged, stats.new, stats.enqueued) == (1, 0, 0)
    assert tfl.gets == gets  # HEAD only, no download
    tfl.publish("https://tfl/A.mp4", '"e2"', NOW + timedelta(seconds=240))
    stats = poller.poll_round([_cam("A")], "clip", now=NOW + timedelta(seconds=250))
    assert stats.enqueued == 1 and len(_clips(con)) == 2


def test_stale_upload_is_skipped_without_download(poller, tfl, con):
    tfl.publish("https://tfl/A.mp4", '"e1"', NOW - timedelta(seconds=901))
    stats = poller.poll_round([_cam("A")], "clip", now=NOW)
    assert (stats.stale, stats.enqueued, tfl.gets) == (1, 0, 0)
    assert _clips(con) == []


def test_errors_are_counted_and_do_not_stop_the_round(poller, tfl, con):
    tfl.publish("https://tfl/A.mp4", '"e1"', NOW - timedelta(seconds=10))
    tfl.publish("https://tfl/B.mp4", '"e1"', NOW - timedelta(seconds=10))
    tfl.fail.add("https://tfl/B.mp4")
    stats = poller.poll_round([_cam("A"), _cam("B")], "clip", now=NOW)
    assert (stats.errors, stats.enqueued) == (1, 1)
    assert ("B", "clip") not in poller.etags  # retried next round


def test_restart_does_not_double_enqueue(con, tfl):
    tfl.publish("https://tfl/A.mp4", '"e1"', NOW - timedelta(seconds=10))
    for _ in range(2):  # two poller processes in a row, each with empty ETag memory
        p = Poller(con, Settings(), session=tfl, refresh_registry=False)
        p.poll_round([_cam("A")], "clip", now=NOW)
        p.pool.shutdown()
    assert len(_clips(con)) == 1


def test_tier1_stills_enqueue_as_still(poller, tfl, con):
    tfl.publish("https://tfl/B.jpg", '"s1"', NOW - timedelta(seconds=30), b"jpeg-bytes")
    stats = poller.poll_round([_cam("B", tier=1)], "still", now=NOW)
    assert stats.enqueued == 1
    assert _clips(con)[0]["kind"] == "still" and _clips(con)[0]["data"] == b"jpeg-bytes"


def test_check_camera_reports_http_errors():
    class NotFound(FakeTfL):
        def head(self, url, timeout=None):
            return Resp(404)
    assert check_camera(NotFound(), "A", "u", None, 900, NOW).status == "error"


def test_run_once_polls_active_tier2_cameras_only(con, tfl):
    db.upsert_cameras(con, [_cam("A"), _cam("B", tier=1), {**_cam("C"), "active": False}])
    uploaded = db.utc_now() - timedelta(seconds=5)  # run() uses the real clock
    for cid in "ABC":
        tfl.publish(f"https://tfl/{cid}.mp4", '"e"', uploaded)
        tfl.publish(f"https://tfl/{cid}.jpg", '"e"', uploaded)
    Poller(con, Settings(), session=tfl, refresh_registry=False).run(once=True)
    assert [c["camera_id"] for c in _clips(con)] == ["A"]
