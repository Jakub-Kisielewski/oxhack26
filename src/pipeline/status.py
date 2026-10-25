"""Pipeline status: queue by status, throughput, seconds per chunk, lag and upload-burst drain times."""
from __future__ import annotations

import argparse
import statistics
import time
from datetime import datetime, timedelta
from typing import Any, Callable

from src.pipeline import db
from src.pipeline.config import SETTINGS


def _secs(a: str, b: str) -> float:
    return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds()


def bursts(timings: list[dict[str, Any]], gap_s: float = 30) -> list[dict[str, Any]]:
    """Group processed chunks into upload bursts (a new burst after an enqueue gap > gap_s).

    drain_s = last observation written - first chunk enqueued, per burst.
    """
    groups: list[list[dict[str, Any]]] = []
    for t in sorted(timings, key=lambda t: t["enqueued_at"]):
        if not groups or _secs(groups[-1][-1]["enqueued_at"], t["enqueued_at"]) > gap_s:
            groups.append([])
        groups[-1].append(t)
    out = []
    for g in groups:
        first = min(t["enqueued_at"] for t in g)
        last = max(t["observed_at"] for t in g)
        out.append({"start": first, "chunks": len(g), "kinds": sorted({t["kind"] for t in g}),
                    "enqueue_span_s": _secs(first, max(t["enqueued_at"] for t in g)), "drain_s": _secs(first, last)})
    return out


def _pct(values: list[float], q: float) -> float:
    values = sorted(values)
    return values[min(len(values) - 1, round(q * (len(values) - 1)))]


def latency_summary(timings: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Median / p95 / max of: frame->observation (end to end), enqueue->observation (queue + processing)."""
    out = {}
    for name, start in (("frame_to_observation_s", "frame_time"), ("enqueue_to_observation_s", "enqueued_at")):
        vals = [_secs(t[start], t["observed_at"]) for t in timings]
        if vals:
            out[name] = {"median": statistics.median(vals), "p95": _pct(vals, 0.95), "max": max(vals)}
    return out


def late_counts(timings: list[dict[str, Any]], lag_for: Callable[[str], float]) -> dict[tuple[int, str], tuple[int, int]]:
    """Per (tier, kind): (rows written more than lag_for(kind) after their frame_time, all rows).

    The twin reads frame_time <= now - LAG, so these rows would arrive too late and be skipped.
    """
    out = {}
    for tier, kind in sorted({(t["tier"], t["kind"]) for t in timings}, key=lambda tk: (-(tk[0] or 0), tk[1])):
        delays = [_secs(t["frame_time"], t["observed_at"]) for t in timings if (t["tier"], t["kind"]) == (tier, kind)]
        out[(tier, kind)] = (sum(d > lag_for(kind) for d in delays), len(delays))
    return out


def round_summary(rounds: list[dict[str, Any]], window_s: float) -> dict[int, dict[str, float]]:
    """Per tier: rounds, median / max round seconds, overruns, media KB/s over the window."""
    out = {}
    for tier in sorted({r["tier"] for r in rounds}, reverse=True):
        rs = [r for r in rounds if r["tier"] == tier]
        secs = [r["seconds"] for r in rs]
        out[tier] = {"rounds": len(rs), "median_s": statistics.median(secs), "max_s": max(secs),
                     "overruns": sum(r["overran"] for r in rs), "kb_per_s": sum(r["bytes"] or 0 for r in rs) / 1024 / window_s,
                     "too_old": sum(r.get("too_old") or 0 for r in rs), "kind": rs[0]["kind"]}
    return out


def proc_ms_by_kind(timings: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    out = {}
    for kind in sorted({t["kind"] for t in timings}):
        ms = [t["proc_ms"] for t in timings if t["kind"] == kind and t["proc_ms"] is not None]
        if ms:
            out[kind] = {"n": len(ms), "median_ms": statistics.median(ms), "p95_ms": _pct(ms, 0.95)}
    return out


def report(con, minutes: int = 10, now: datetime | None = None,
           lag_for: Callable[[str], float] = SETTINGS.lag_for) -> str:
    now = now or db.utc_now()
    s = db.queue_stats(con, window_minutes=minutes, now=now)
    timings = db.pipeline_timings(con, now - timedelta(minutes=minutes))
    rounds = db.poll_rounds_since(con, now - timedelta(minutes=minutes))
    lines = [
        f"queue: {s['by_status']}",
        f"observations in the last {minutes} min: {s['observations_recent']}",
        f"mean seconds per chunk (proc_ms): "
        + (f"{s['mean_seconds_per_chunk']:.3f}" if s["mean_seconds_per_chunk"] is not None else "n/a"),
        f"lag (now - newest frame_time): " + (f"{s['lag_seconds']:.0f} s" if s["lag_seconds"] is not None else "n/a")
        + "  (TfL uploads every ~5 min, so this saw-tooths 0-300 s)",
    ]
    for kind, v in proc_ms_by_kind(timings).items():
        lines.append(f"proc {kind}: n={v['n']} median {v['median_ms']:.0f} ms, p95 {v['p95_ms']:.0f} ms")
    for name, v in latency_summary(timings).items():
        lines.append(f"{name}: median {v['median']:.0f} s, p95 {v['p95']:.0f} s, max {v['max']:.0f} s")
    summary = round_summary(rounds, minutes * 60) if rounds else {}
    for tier, r in summary.items():
        lines.append(f"tier {tier} {r['kind']} rounds: {r['rounds']}, median {r['median_s']:.1f} s, max {r['max_s']:.1f} s, "
                     f"overruns {r['overruns']}, {r['kb_per_s']:.1f} KB/s, too-old skipped {r['too_old']}")
    if summary:
        lines.append(f"network (media downloads, all tiers): {sum(r['kb_per_s'] for r in summary.values()):.1f} KB/s")
    for (tier, kind), (n, total) in late_counts(timings, lag_for).items():
        lines.append(f"late at LAG {lag_for(kind):g} s: tier {tier} {kind} {n}/{total}")
    for e in db.poller_events_since(con, now - timedelta(minutes=minutes)):
        lines.append(f"event {e['at']}: {e['event']}" + (f" until {e['until']}" if e["until"] else "")
                     + (f" ({e['detail']})" if e["detail"] else ""))
    for b in bursts(timings):
        lines.append(f"burst {b['start']}: {b['chunks']} chunks {'+'.join(b['kinds'])}, enqueued over "
                     f"{b['enqueue_span_s']:.0f} s, drained in {b['drain_s']:.0f} s")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Show pipeline status.")
    ap.add_argument("--minutes", type=int, default=10, help="window for throughput and timings")
    ap.add_argument("--watch", type=int, default=0, metavar="SECONDS", help="repeat every N seconds")
    args = ap.parse_args()
    con = db.connect(read_only=True)
    while True:
        print(report(con, args.minutes))
        if not args.watch:
            return
        print()
        time.sleep(args.watch)


if __name__ == "__main__":
    main()
