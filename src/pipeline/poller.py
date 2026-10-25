"""Poller: one loop per tier with its own interval, sharing one requests.Session and a priority HEAD pool."""
from __future__ import annotations

import argparse
import heapq
import itertools
import logging
import signal
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Iterable, Mapping

import requests

from src.pipeline import cameras, db
from src.pipeline.chunking import split_clip
from src.pipeline.config import SETTINGS, Settings
from src.pipeline.jamcam_poller import SESSION

log = logging.getLogger(__name__)

URL_KEY = {"clip": "video_url", "still": "image_url"}


@dataclass(frozen=True)
class TierLoop:
    tier: int
    kind: str  # clip | still
    interval_s: float

    @property
    def priority(self) -> int:
        """Lower runs first in the HEAD pool: tier 2 -> 0, tier 1 -> 1, tier 0 -> 2."""
        return 2 - self.tier


def tier_loops(settings: Settings) -> list[TierLoop]:
    """The enabled tiers, highest first. Tier 2 is always polled."""
    loops = [TierLoop(2, "clip", settings.poll_seconds)]
    if settings.tier1_enabled:
        loops.append(TierLoop(1, settings.tier1_kind, settings.tier1_poll_seconds))
    if settings.tier0_enabled:
        loops.append(TierLoop(0, settings.tier0_kind, settings.tier0_poll_seconds))
    for loop in loops:
        if loop.kind not in URL_KEY:
            raise ValueError(f"tier {loop.tier}: kind must be 'clip' or 'still', got {loop.kind!r}")
    return loops


class PriorityPool:
    """Bounded thread pool with a priority queue (lower runs first).

    `reserved` of the threads only take tasks at priority <= reserved_priority (tier 2), so tier 2 always has
    threads even while lower tiers' slow downloads occupy all the others.
    """

    def __init__(self, workers: int, reserved: int = 0, reserved_priority: float = 0):
        if not 0 <= reserved < workers:
            raise ValueError(f"reserved threads ({reserved}) must be fewer than workers ({workers})")
        self._heap: list = []
        self._cv = threading.Condition()
        self._seq = itertools.count()
        self._closed = False
        self._reserved_priority = reserved_priority
        self._threads = [threading.Thread(target=self._work, args=(i < reserved,), daemon=True,
                                          name=f"head-{'r' if i < reserved else ''}{i}") for i in range(workers)]
        for t in self._threads:
            t.start()

    def submit(self, priority: float, fn: Callable[..., Any], *args: Any) -> Future:
        future: Future = Future()
        with self._cv:
            heapq.heappush(self._heap, (priority, next(self._seq), future, fn, args))
            self._cv.notify_all()
        return future

    def map(self, priority: float, fn: Callable[[Any], Any], items: Iterable[Any]) -> list[Any]:
        futures = [self.submit(priority, fn, item) for item in items]
        return [f.result() for f in futures]

    def _next(self, reserved: bool):
        with self._cv:
            while True:
                if self._heap and (not reserved or self._heap[0][0] <= self._reserved_priority):
                    return heapq.heappop(self._heap)
                if self._closed:
                    return None
                self._cv.wait()

    def _work(self, reserved: bool) -> None:
        while (item := self._next(reserved)) is not None:
            _, _, future, fn, args = item
            if future.set_running_or_notify_cancel():
                try:
                    future.set_result(fn(*args))
                except BaseException as e:
                    future.set_exception(e)

    def shutdown(self) -> None:
        """Finish queued tasks, then stop every thread."""
        with self._cv:
            self._closed = True
            self._cv.notify_all()
        for t in self._threads:
            t.join()


class BandwidthValve:
    """Pauses tier 0 after `slow_rounds` tier-2 rounds in a row slower than `slow_s`, for `pause_s` seconds."""

    def __init__(self, slow_s: float, slow_rounds: int, pause_s: float, clock: Callable[[], float] = time.monotonic):
        self.slow_s, self.slow_rounds, self.pause_s, self.clock = slow_s, slow_rounds, pause_s, clock
        self.streak = 0
        self.paused_until = 0.0

    def record_tier2(self, seconds: float) -> bool:
        """Feed one tier-2 round duration; True if it starts a pause."""
        self.streak = self.streak + 1 if seconds > self.slow_s else 0
        if self.streak >= self.slow_rounds and not self.is_paused():
            self.paused_until = self.clock() + self.pause_s
            self.streak = 0
            return True
        return False

    def is_paused(self) -> bool:
        return self.clock() < self.paused_until


@dataclass(frozen=True)
class Check:
    """Outcome of checking one camera's media URL."""
    camera_id: str
    status: str  # new | unchanged | stale | too_old | error
    etag: str | None = None
    frame_time: datetime | None = None
    data: bytes | None = None
    error: str | None = None


@dataclass
class RoundStats:
    tier: int
    kind: str
    checked: int = 0
    new: int = 0
    enqueued: int = 0
    unchanged: int = 0
    stale: int = 0
    too_old: int = 0
    errors: int = 0
    bytes: int = 0
    seconds: float = 0.0
    overran: bool = False
    error_samples: list[str] = field(default_factory=list)

    def line(self) -> str:
        return (f"tier {self.tier} {self.kind} round: checked={self.checked} new={self.new} "
                f"enqueued={self.enqueued} unchanged={self.unchanged} stale={self.stale} too_old={self.too_old} "
                f"errors={self.errors} "
                f"{self.bytes / 1024:.0f} KB in {self.seconds:.2f}s")


def check_camera(session: requests.Session, camera_id: str, url: str, last_etag: str | None,
                 stale_after_s: int, now: datetime, max_age_s: float | None = None) -> Check:
    """HEAD the URL; GET it only if the ETag changed and the upload is fresh. frame_time = Last-Modified.

    Uploads older than max_age_s (the kind's LAG) are not downloaded: the twin would skip them as late.
    """
    try:
        head = session.head(url, timeout=10)
        if head.status_code != 200:
            return Check(camera_id, "error", error=f"HEAD {head.status_code}")
        etag = head.headers.get("ETag")
        if etag and etag == last_etag:
            return Check(camera_id, "unchanged", etag)
        last_modified = head.headers.get("Last-Modified")
        if not last_modified:
            return Check(camera_id, "error", error="no Last-Modified")
        frame_time = parsedate_to_datetime(last_modified)
        age = (now - frame_time).total_seconds()
        if age > stale_after_s:
            return Check(camera_id, "stale", etag, frame_time)
        if max_age_s is not None and age > max_age_s:
            return Check(camera_id, "too_old", etag, frame_time)
        resp = session.get(url, timeout=30)
        if resp.status_code != 200:
            return Check(camera_id, "error", error=f"GET {resp.status_code}")
        frame_time = parsedate_to_datetime(resp.headers.get("Last-Modified", last_modified))
        return Check(camera_id, "new", resp.headers.get("ETag", etag), frame_time, resp.content)
    except (requests.RequestException, TypeError, ValueError) as e:
        return Check(camera_id, "error", error=f"{type(e).__name__}: {e}")


class Poller:
    """Runs one loop per tier. Each loop has its own DB connection; HTTP goes through the shared pool."""

    def __init__(self, settings: Settings = SETTINGS, session: requests.Session = SESSION,
                 refresh_registry: bool = True, connect: Callable[[], Any] | None = None):
        self.settings = settings
        self.session = session
        self.refresh_registry = refresh_registry
        self.connect = connect or (lambda: db.connect(settings.db_url))
        self.etags: dict[tuple[str, str], str | None] = {}  # (camera_id, kind) -> last ETag seen
        self.pool = PriorityPool(settings.head_threads, reserved=settings.tier2_reserved_threads,
                                 reserved_priority=TierLoop(2, "clip", 0).priority)
        self.valve = BandwidthValve(settings.poll_seconds, settings.valve_slow_rounds, settings.valve_pause_seconds)
        self.stop_event = threading.Event()

    def poll_round(self, con, cams: list[Mapping[str, Any]], loop: TierLoop, now: datetime | None = None) -> RoundStats:
        """Check every camera through the pool, enqueue new media, record the round. Never waits on processing."""
        now = now or db.utc_now()
        stats = RoundStats(loop.tier, loop.kind, checked=len(cams))
        t0 = time.perf_counter()
        checks = self.pool.map(
            loop.priority,
            lambda c: check_camera(self.session, c["camera_id"], c[URL_KEY[loop.kind]],
                                   self.etags.get((c["camera_id"], loop.kind)), self.settings.stale_after_s, now,
                                   self.settings.lag_for(loop.kind)),
            cams)
        for chk in checks:
            if chk.status == "error":
                stats.errors += 1
                if len(stats.error_samples) < 3:
                    stats.error_samples.append(f"{chk.camera_id}: {chk.error}")
                continue
            self.etags[(chk.camera_id, loop.kind)] = chk.etag
            if chk.status == "unchanged":
                stats.unchanged += 1
            elif chk.status == "stale":
                stats.stale += 1
            elif chk.status == "too_old":
                stats.too_old += 1
            else:
                stats.new += 1
                stats.bytes += len(chk.data)
                chunks = split_clip(chk.data, self.settings.chunk_seconds) if loop.kind == "clip" else [chk.data]
                for i, chunk in enumerate(chunks):
                    if db.enqueue_clip(con, chk.camera_id, chk.frame_time, chunk, etag=chk.etag,
                                       chunk_index=i, kind=loop.kind) is not None:
                        stats.enqueued += 1
        stats.seconds = time.perf_counter() - t0
        stats.overran = stats.seconds > loop.interval_s
        db.record_poll_round(con, {**vars(stats), "started_at": now})
        log.info(stats.line())
        if stats.too_old:
            log.info("tier %d: skipped %d too-old uploads (older than LAG %d s)", loop.tier, stats.too_old,
                     self.settings.lag_for(loop.kind))
        if stats.error_samples:
            log.warning("tier %d errors: %s", loop.tier, "; ".join(stats.error_samples))
        return stats

    def tier_loop(self, loop: TierLoop) -> None:
        """Poll one tier every interval. Never overlaps itself: an overrun skips the missed ticks.

        Tier 2 feeds the bandwidth valve; tier 0 skips its rounds while the valve is closed.
        """
        con = self.connect()
        next_tick = time.monotonic()
        paused = False
        try:
            while not self.stop_event.wait(max(0.0, next_tick - time.monotonic())):
                next_tick += loop.interval_s
                if loop.tier == 0 and self.valve.is_paused():
                    paused = True
                    continue
                if paused:
                    paused = False
                    log.info("tier 0 resumed")
                    db.record_poller_event(con, "tier0_resumed")
                stats = self.poll_round(con, db.active_cameras(con, [loop.tier]), loop)
                if stats.overran:
                    log.warning("tier %d overran: %.1f s", loop.tier, stats.seconds)
                    while next_tick <= time.monotonic():
                        next_tick += loop.interval_s
                if loop.tier == 2 and self.valve.record_tier2(stats.seconds):
                    s = self.settings
                    log.warning("tier 0 paused for %d s (bandwidth): %d tier-2 rounds in a row over %d s",
                                s.valve_pause_seconds, s.valve_slow_rounds, s.poll_seconds)
                    db.record_poller_event(con, "tier0_paused",
                                           until=db.utc_now() + timedelta(seconds=s.valve_pause_seconds),
                                           detail=f"{s.valve_slow_rounds} tier-2 rounds over {s.poll_seconds} s")
        finally:
            con.close()

    def refresh(self, con) -> None:
        try:
            result = cameras.refresh_cameras(con, self.settings)
            log.info("registry refreshed: %s", ", ".join(f"tier {r['tier']}: {r['active']}/{r['cameras']} active"
                                                         for r in result.summary))
        except Exception as e:  # keep polling the cameras we already have
            log.warning("registry refresh failed, keeping current cameras: %s", e)

    def refresh_loop(self) -> None:
        con = self.connect()
        try:
            while not self.stop_event.wait(self.settings.camera_refresh_seconds):
                self.refresh(con)
        finally:
            con.close()

    def run(self, once: bool = False) -> None:
        """Start every tier loop (and the registry refresh) and block until stop_event is set."""
        loops = tier_loops(self.settings)
        con = self.connect()
        if self.refresh_registry:
            self.refresh(con)
        if once:
            for loop in loops:
                self.poll_round(con, db.active_cameras(con, [loop.tier]), loop)
            con.close()
            self.pool.shutdown()
            return
        con.close()
        threads = [threading.Thread(target=self.tier_loop, args=(loop,), name=f"tier-{loop.tier}") for loop in loops]
        if self.refresh_registry:
            threads.append(threading.Thread(target=self.refresh_loop, name="registry"))
        for t in threads:
            t.start()
        while not self.stop_event.wait(0.5):
            pass
        for t in threads:
            t.join()  # each loop finishes its current round
        self.pool.shutdown()


def main() -> None:
    ap = argparse.ArgumentParser(description="Poll JamCam media per tier and enqueue new clips/stills.")
    ap.add_argument("--once", action="store_true", help="one round per enabled tier, then exit")
    ap.add_argument("--no-refresh", action="store_true", help="don't refresh the camera registry from TfL")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(threadName)s %(levelname)s %(message)s")

    con = db.connect(SETTINGS.db_url)
    db.init_db(con)
    con.close()
    poller = Poller(SETTINGS, refresh_registry=not args.no_refresh)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: poller.stop_event.set())
    log.info("poller: %s", ", ".join(f"tier {l.tier} {l.kind}s every {l.interval_s:g}s" for l in tier_loops(SETTINGS)))
    poller.run(once=args.once)
    log.info("poller stopped")


if __name__ == "__main__":
    main()
