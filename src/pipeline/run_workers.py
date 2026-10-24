"""Run N worker processes (spawn), restart any that die, stop them all on Ctrl-C."""
from __future__ import annotations

import argparse
import logging
import multiprocessing as mp
import os
import signal
import threading
from typing import Callable, Protocol

log = logging.getLogger(__name__)


class Proc(Protocol):
    def is_alive(self) -> bool: ...


def worker_process(index: int, n: int) -> None:
    """Entry point of one worker process: share the CPU fairly, then run until SIGTERM."""
    import torch

    torch.set_num_threads(max(1, (os.cpu_count() or 1) // n))
    signal.signal(signal.SIGINT, signal.SIG_IGN)  # the parent owns Ctrl-C and sends SIGTERM
    logging.basicConfig(level=logging.INFO, format=f"%(asctime)s w{index} %(levelname)s %(message)s")
    from src.pipeline import db
    from src.pipeline.detector import Detector
    from src.pipeline.worker import Worker

    worker = Worker(db.connect(), Detector(), name=f"w{index}")
    signal.signal(signal.SIGTERM, lambda *_: worker.stop_event.set())
    worker.run()


def restart_dead(procs: dict[int, Proc], start: Callable[[int], Proc]) -> list[int]:
    """Replace every dead process in place; returns the restarted indices."""
    dead = [i for i, p in procs.items() if not p.is_alive()]
    for i in dead:
        procs[i] = start(i)
    return dead


def main() -> None:
    ap = argparse.ArgumentParser(description="Run N pipeline workers.")
    ap.add_argument("--n", type=int, default=3)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s supervisor %(levelname)s %(message)s")

    ctx = mp.get_context("spawn")

    def start(i: int) -> mp.Process:
        p = ctx.Process(target=worker_process, args=(i, args.n), name=f"worker-{i}")
        p.start()
        return p

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    procs: dict[int, mp.Process] = {i: start(i) for i in range(args.n)}
    log.info("started %d workers, %d torch threads each", args.n, max(1, (os.cpu_count() or 1) // args.n))
    while not stop.wait(2):
        for i in restart_dead(procs, start):
            log.warning("worker %d died; restarted", i)
    log.info("stopping workers")
    for p in procs.values():
        p.terminate()  # SIGTERM: each worker finishes its current chunk
    for p in procs.values():
        p.join(timeout=30)
        if p.is_alive():
            p.kill()


if __name__ == "__main__":
    main()
