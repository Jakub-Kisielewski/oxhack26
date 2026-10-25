from datetime import datetime, timedelta, timezone

import pytest

from src.pipeline import db, status

T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


def _t(frame_s, enq_s, obs_s, kind="clip", proc_ms=100, tier=2):
    f = lambda s: db.to_iso(T0 + timedelta(seconds=s))  # noqa: E731
    return {"camera_id": "A", "tier": tier, "kind": kind, "frame_time": f(frame_s), "enqueued_at": f(enq_s),
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


def test_late_counts_per_tier_use_the_lag_for_each_kind():
    timings = [_t(0, 10, 20), _t(0, 30, 70), _t(0, 40, 70, tier=1), _t(0, 40, 80, "still", tier=0)]
    lag_for = lambda kind: 90 if kind == "still" else 60  # noqa: E731
    assert status.late_counts(timings, lag_for) == {(2, "clip"): (1, 2), (1, "clip"): (1, 1), (0, "still"): (0, 1)}


def test_round_summary_per_tier():
    rounds = [{"tier": 2, "kind": "clip", "seconds": s, "overran": o, "bytes": b, "too_old": 1}
              for s, o, b in [(0.5, 0, 102400), (0.7, 0, 0), (16.0, 1, 204800)]]
    rounds.append({"tier": 0, "kind": "still", "seconds": 3.0, "overran": 0, "bytes": 61440})
    out = status.round_summary(rounds, window_s=60)
    assert out[2]["rounds"] == 3 and out[2]["median_s"] == 0.7 and out[2]["max_s"] == 16.0
    assert out[2]["overruns"] == 1 and out[2]["kb_per_s"] == pytest.approx(5.0)
    assert out[0]["kb_per_s"] == pytest.approx(1.0)
    assert out[2]["too_old"] == 3 and out[0]["too_old"] == 0


def test_report_on_a_live_db(con):
    db.upsert_cameras(con, [{"camera_id": "A", "tier": 2}])
    cid = db.enqueue_clip(con, "A", T0, b"x", now=T0 + timedelta(seconds=20))
    db.claim_next(con, now=T0 + timedelta(seconds=21))
    db.insert_observation(con, {"camera_id": "A", "frame_time": T0, "people": 3, "proc_ms": 150},
                          now=T0 + timedelta(seconds=22))
    db.mark_done(con, cid, now=T0 + timedelta(seconds=22))
    db.record_poll_round(con, {"tier": 2, "kind": "clip", "started_at": T0 + timedelta(seconds=19), "seconds": 0.8,
                               "checked": 1, "new": 1, "enqueued": 1, "bytes": 30720, "overran": False})
    text = status.report(con, minutes=10, now=T0 + timedelta(seconds=60))
    assert "tier 2 clip rounds: 1, median 0.8 s, max 0.8 s, overruns 0, 0.1 KB/s, too-old skipped 0" in text
    db.record_poller_event(con, "tier0_paused", until=T0 + timedelta(minutes=5), now=T0 + timedelta(seconds=30))
    assert "tier0_paused until 2026-10-24T12:05:00+00:00" in status.report(con, minutes=10, now=T0 + timedelta(seconds=60))
    assert "proc clip: n=1 median 150 ms" in text
    assert "frame_to_observation_s: median 22 s" in text
    assert "drained in 2 s" in text
    assert "late at LAG 60 s: tier 2 clip 0/1" in text
