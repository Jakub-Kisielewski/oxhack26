"""Poller: HEAD tier-2 clips every POLL_SECONDS (and tier-1 stills every STILL_POLL_SECONDS if enabled); enqueue new media."""
from __future__ import annotations

import argparse
import logging
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any, Mapping

import requests

from src.pipeline import cameras, db
from src.pipeline.chunking import split_clip
from src.pipeline.config import SETTINGS, Settings
from src.pipeline.jamcam_poller import SESSION

log = logging.getLogger(__name__)

URL_KEY = {"clip": "video_url", "still": "image_url"}


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
    kind: str
    checked: int = 0
    new: int = 0
    enqueued: int = 0
    unchanged: int = 0
    stale: int = 0
    errors: int = 0
    seconds: float = 0.0
    error_samples: list[str] = field(default_factory=list)

    def line(self) -> str:
        return (f"{self.kind} round: checked={self.checked} new={self.new} enqueued={self.enqueued} "
                f"unchanged={self.unchanged} stale={self.stale} errors={self.errors} in {self.seconds:.2f}s")


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
    """Owns the ETag memory, the HTTP thread pool and the DB connection (DB writes stay on this thread)."""

    def __init__(self, con, settings: Settings = SETTINGS, session: requests.Session = SESSION,
                 refresh_registry: bool = True):
        self.con = con
        self.settings = settings
        self.session = session
        self.refresh_registry = refresh_registry
        self.etags: dict[tuple[str, str], str | None] = {}  # (camera_id, kind) -> last ETag seen
        self.pool = ThreadPoolExecutor(settings.head_threads, thread_name_prefix="head")
        self.stop_event = threading.Event()

    def poll_round(self, cams: list[Mapping[str, Any]], kind: str, now: datetime | None = None) -> RoundStats:
        """Check every camera concurrently, then enqueue new media. Never waits on processing."""
        now = now or db.utc_now()
        stats = RoundStats(kind, checked=len(cams))
        t0 = time.perf_counter()
        checks = list(self.pool.map(
            lambda c: check_camera(self.session, c["camera_id"], c[URL_KEY[kind]],
                                   self.etags.get((c["camera_id"], kind)), self.settings.stale_after_s, now),
            cams))
        for chk in checks:
            if chk.status == "error":
                stats.errors += 1
                if len(stats.error_samples) < 3:
                    stats.error_samples.append(f"{chk.camera_id}: {chk.error}")
                continue
            self.etags[(chk.camera_id, kind)] = chk.etag
            if chk.status == "unchanged":
                stats.unchanged += 1
            elif chk.status == "stale":
                stats.stale += 1
            else:
                stats.new += 1
                chunks = split_clip(chk.data, self.settings.chunk_seconds) if kind == "clip" else [chk.data]
                for i, chunk in enumerate(chunks):
                    if db.enqueue_clip(self.con, chk.camera_id, chk.frame_time, chunk, etag=chk.etag,
                                       chunk_index=i, kind=kind) is not None:
                        stats.enqueued += 1
        stats.seconds = time.perf_counter() - t0
        log.info(stats.line())
        if stats.error_samples:
            log.warning("errors: %s", "; ".join(stats.error_samples))
        return stats

    def refresh(self) -> None:
        try:
            result = cameras.refresh_cameras(self.con, self.settings)
            log.info("registry refreshed: %s", ", ".join(f"tier {r['tier']}: {r['active']}/{r['cameras']} active"
                                                         for r in result.summary))
        except Exception as e:  # keep polling the cameras we already have
            log.warning("registry refresh failed, keeping current cameras: %s", e)

    def run(self, once: bool = False) -> None:
        s = self.settings
        next_clip = next_still = next_refresh = time.monotonic()
        while not self.stop_event.is_set():
            now = time.monotonic()
            if self.refresh_registry and now >= next_refresh:
                self.refresh()
                next_refresh = now + s.camera_refresh_seconds
            if now >= next_clip:
                self.poll_round(db.active_cameras(self.con, [2]), "clip")
                next_clip = now + s.poll_seconds
            if s.tier1_enabled and now >= next_still:
                self.poll_round(db.active_cameras(self.con, [1]), "still")
                next_still = now + s.still_poll_seconds
            if once:
                break
            due = min([next_clip] + ([next_still] if s.tier1_enabled else []))
            self.stop_event.wait(max(0.0, due - time.monotonic()))
        self.pool.shutdown(wait=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Poll JamCam media and enqueue new clips/stills.")
    ap.add_argument("--once", action="store_true", help="one round per enabled tier, then exit")
    ap.add_argument("--tier1", action="store_true", help="also poll tier-1 stills (overrides TIER1_ENABLED)")
    ap.add_argument("--no-refresh", action="store_true", help="don't refresh the camera registry from TfL")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    settings = replace(SETTINGS, tier1_enabled=True) if args.tier1 else SETTINGS
    con = db.connect(settings.db_url)
    db.init_db(con)
    poller = Poller(con, settings, refresh_registry=not args.no_refresh)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: poller.stop_event.set())
    log.info("poller: clips every %ds (tier 2)%s", settings.poll_seconds,
             f", stills every {settings.still_poll_seconds}s (tier 1)" if settings.tier1_enabled else "")
    poller.run(once=args.once)
    log.info("poller stopped")


if __name__ == "__main__":
    main()
