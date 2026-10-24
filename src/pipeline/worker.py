"""Worker: claim one chunk, extract features, store the observation, drop the media. Stateless; run several."""
from __future__ import annotations

import argparse
import logging
import signal
import threading
import time

from src.pipeline import db
from src.pipeline.config import SETTINGS, Settings
from src.pipeline.features import PersonDetector, extract_features

log = logging.getLogger(__name__)


class Worker:
    def __init__(self, con, detector: PersonDetector, settings: Settings = SETTINGS, name: str = "worker"):
        self.con = con
        self.detector = detector
        self.settings = settings
        self.name = name
        self.stop_event = threading.Event()

    def process_one(self) -> str | None:
        """Requeue expired claims, then claim and process one chunk. Returns 'done', 'failed' or None if idle."""
        db.requeue_expired(self.con, self.settings.claim_timeout_s, self.settings.max_attempts)
        clip = db.claim_next(self.con)
        if clip is None:
            return None
        camera = db.get_camera(self.con, clip["camera_id"]) or {"camera_id": clip["camera_id"]}
        try:
            t0 = time.perf_counter()
            feats = extract_features(clip["data"], camera, self.detector, kind=clip["kind"], settings=self.settings)
            proc_ms = round((time.perf_counter() - t0) * 1000)
            db.insert_observation(self.con, {**feats, "camera_id": clip["camera_id"], "frame_time": clip["frame_time"],
                                             "chunk_index": clip["chunk_index"], "kind": clip["kind"],
                                             "proc_ms": proc_ms})
            db.mark_done(self.con, clip["id"])
        except Exception as e:
            log.exception("%s: chunk %s (%s) failed", self.name, clip["id"], clip["camera_id"])
            db.mark_failed(self.con, clip["id"], f"{type(e).__name__}: {e}")
            return "failed"
        log.info("%s: %s %s people=%s quality=%s %d ms", self.name, clip["kind"], camera.get("name", clip["camera_id"]),
                 feats["people"], feats["quality"], proc_ms)
        return "done"

    def run(self, until_empty: bool = False) -> None:
        """Process until stopped (SIGINT/SIGTERM finish the current chunk first); sleep 2 s when the queue is empty."""
        while not self.stop_event.is_set():
            if self.process_one() is None:
                if until_empty:
                    return
                self.stop_event.wait(2)


def main() -> None:
    ap = argparse.ArgumentParser(description="Run one pipeline worker.")
    ap.add_argument("--until-empty", action="store_true", help="exit when the queue is empty")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from src.pipeline.detector import Detector

    worker = Worker(db.connect(), Detector())
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: worker.stop_event.set())
    worker.run(until_empty=args.until_empty)


if __name__ == "__main__":
    main()
