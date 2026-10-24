from datetime import datetime, timedelta, timezone

from src.pipeline import db, status

T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


def _t(frame_s, enq_s, obs_s, kind="clip", proc_ms=100):
    f = lambda s: db.to_iso(T0 + timedelta(seconds=s))  # noqa: E731
    return {"camera_id": "A", "kind": kind, "frame_time": f(frame_s), "enqueued_at": f(enq_s),
            "observed_at": f(obs_s), "proc_ms": proc_ms}


def test_bursts_split_on_enqueue_gaps_and_measure_drain():
    timings = [_t(0, 10, 12), _t(0, 30, 40, "still"), _t(0, 20, 50),  # burst 1: 10..50
               _t(300, 310, 311), _t(300, 315, 318)]                    # burst 2: 310..318
    b = status.bursts(timings, gap_s=60)
    assert [(x["chunks"], x["drain_s"], x["enqueue_span_s"]) for x in b] == [(3, 40.0, 20.0), (2, 8.0, 5.0)]
    assert b[0]["kinds"] == ["clip", "still"]


def test_latency_summary_and_proc_ms():
    timings = [_t(0, 10, 12, proc_ms=80), _t(0, 20, 50, proc_ms=120), _t(0, 30, 40, "still", proc_ms=20)]
    lat = status.latency_summary(timings)
    assert lat["frame_to_observation_s"]["max"] == 50 and lat["enqueue_to_observation_s"]["median"] == 10
    assert status.proc_ms_by_kind(timings)["clip"]["median_ms"] == 100


def test_late_counts_against_lag():
    timings = [_t(0, 10, 20), _t(0, 30, 50), _t(0, 40, 70, "still")]
    assert status.late_counts(timings, 45) == {"clip": (1, 2), "still": (1, 1)}
    assert status.late_counts(timings, 90) == {"clip": (0, 2), "still": (0, 1)}


def test_report_on_a_live_db(con):
    db.upsert_cameras(con, [{"camera_id": "A", "tier": 2}])
    cid = db.enqueue_clip(con, "A", T0, b"x", now=T0 + timedelta(seconds=20))
    db.claim_next(con, now=T0 + timedelta(seconds=21))
    db.insert_observation(con, {"camera_id": "A", "frame_time": T0, "people": 3, "proc_ms": 150},
                          now=T0 + timedelta(seconds=22))
    db.mark_done(con, cid, now=T0 + timedelta(seconds=22))
    text = status.report(con, minutes=10, now=T0 + timedelta(seconds=60))
    assert "proc clip: n=1 median 150 ms" in text
    assert "frame_to_observation_s: median 22 s" in text
    assert "drained in 2 s" in text
    assert "late at LAG_SECONDS=45: clip 0/1" in text
