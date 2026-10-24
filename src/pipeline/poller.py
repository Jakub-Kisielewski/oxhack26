"""Poller: one loop per tier with its own interval, sharing one requests.Session and a priority HEAD pool."""
from __future__ import annotations

import argparse
import itertools
import logging
import math
import queue
import signal
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import datetime
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
    """Bounded thread pool with a priority queue, so tier-2 checks never wait behind lower tiers' backlog."""

    def __init__(self, workers: int):
        self._queue: queue.PriorityQueue = queue.PriorityQueue()
        self._seq = itertools.count()
        self._threads = [threading.Thread(target=self._work, name=f"head-{i}", daemon=True) for i in range(workers)]
        for t in self._threads:
            t.start()

    def submit(self, priority: float, fn: Callable[..., Any], *args: Any) -> Future:
        future: Future = Future()
        self._queue.put((priority, next(self._seq), future, fn, args))
        return future

    def map(self, priority: float, fn: Callable[[Any], Any], items: Iterable[Any]) -> list[Any]:
        futures = [self.submit(priority, fn, item) for item in items]
        return [f.result() for f in futures]

    def _work(self) -> None:
        while True:
            _, _, future, fn, args = self._queue.get()
            if fn is None:
                return
            if future.set_running_or_notify_cancel():
                try:
                    future.set_result(fn(*args))
                except BaseException as e:
                    future.set_exception(e)

    def shutdown(self) -> None:
        for _ in self._threads:
            self._queue.put((math.inf, next(self._seq), None, None, ()))
        for t in self._threads:
            t.join()


@dataclass(frozen=True)
class Check:
    """Outcome of checking one camera's media URL."""
    camera_id: str
    status: str  # new | unchanged | stale | error
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
    errors: int = 0
    bytes: int = 0
    seconds: float = 0.0
    overran: bool = False
    error_samples: list[str] = field(default_factory=list)

    def line(self) -> str:
        return (f"tier {self.tier} {self.kind} round: checked={self.checked} new={self.new} "
                f"enqueued={self.enqueued} unchanged={self.unchanged} stale={self.stale} errors={self.errors} "
                f"{self.bytes / 1024:.0f} KB in {self.seconds:.2f}s")


def check_camera(session: requests.Session, camera_id: str, url: str, last_etag: str | None,
                 stale_after_s: int, now: datetime) -> Check:
    """HEAD the URL; GET it only if the ETag changed and the upload is fresh. frame_time = Last-Modified."""
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
        if (now - frame_time).total_seconds() > stale_after_s:
            return Check(camera_id, "stale", etag, frame_time)
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
        self.pool = PriorityPool(settings.head_threads)
        self.stop_event = threading.Event()

    def poll_round(self, con, cams: list[Mapping[str, Any]], loop: TierLoop, now: datetime | None = None) -> RoundStats:
        """Check every camera through the pool, enqueue new media, record the round. Never waits on processing."""
        now = now or db.utc_now()
        stats = RoundStats(loop.tier, loop.kind, checked=len(cams))
        t0 = time.perf_counter()
        checks = self.pool.map(
            loop.priority,
            lambda c: check_camera(self.session, c["camera_id"], c[URL_KEY[loop.kind]],
                                   self.etags.get((c["camera_id"], loop.kind)), self.settings.stale_after_s, now),
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
        if stats.error_samples:
            log.warning("tier %d errors: %s", loop.tier, "; ".join(stats.error_samples))
        return stats

    def tier_loop(self, loop: TierLoop) -> None:
        """Poll one tier every interval. Never overlaps itself: an overrun skips the missed ticks."""
        con = self.connect()
        next_tick = time.monotonic()
        try:
            while not self.stop_event.wait(max(0.0, next_tick - time.monotonic())):
                stats = self.poll_round(con, db.active_cameras(con, [loop.tier]), loop)
                next_tick += loop.interval_s
                if stats.overran:
                    log.warning("tier %d overran: %.1f s", loop.tier, stats.seconds)
                    while next_tick <= time.monotonic():
                        next_tick += loop.interval_s
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
