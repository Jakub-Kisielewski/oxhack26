"""Hand-labelled evaluation set for detection accuracy: files under data/eval/ (gitignored), labels.csv kept."""
from __future__ import annotations

import csv
import random
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.pipeline.config import REPO_ROOT

EVAL_DIR = REPO_ROOT / "data" / "eval"
LABEL_FIELDS = ("camera_id", "frame_time", "my_count")
MANIFEST_FIELDS = ("camera_id", "name", "tier", "frame_time", "clip", "frame", "frame_index", "sample_fps")


@dataclass(frozen=True)
class EvalItem:
    """One sampled clip: the labelled frame is frames[frame_index] of sample_clip(clip, sample_fps)."""
    camera_id: str
    name: str
    tier: int
    frame_time: str
    clip: str        # path relative to EVAL_DIR
    frame: str       # labelling image, relative to EVAL_DIR
    frame_index: int
    sample_fps: float


def file_stem(camera_id: str, frame_time: str) -> str:
    return f"{camera_id}_{datetime.fromisoformat(frame_time).strftime('%Y%m%dT%H%M%SZ')}"


def choose_cameras(cams: list[Mapping[str, Any]], n: int, rng: random.Random) -> list[Mapping[str, Any]]:
    """Half the busiest cameras by latest people count, the rest at random from the others (busy and quiet mix)."""
    with_counts = sorted((c for c in cams if c.get("people") is not None), key=lambda c: -c["people"])
    busy = with_counts[: n // 2]
    rest = [c for c in cams if c not in busy]
    return busy + rng.sample(rest, min(len(rest), n - len(busy)))


def _read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _append(path: Path, fields: Iterable[str], row: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(fields))
        if new:
            w.writeheader()
        w.writerow(row)


def read_manifest(eval_dir: Path = EVAL_DIR) -> list[EvalItem]:
    return [EvalItem(r["camera_id"], r["name"], int(r["tier"]), r["frame_time"], r["clip"], r["frame"],
                     int(r["frame_index"]), float(r["sample_fps"])) for r in _read(eval_dir / "manifest.csv")]


def add_to_manifest(item: EvalItem, eval_dir: Path = EVAL_DIR) -> None:
    _append(eval_dir / "manifest.csv", MANIFEST_FIELDS, asdict(item))


def read_labels(eval_dir: Path = EVAL_DIR) -> dict[tuple[str, str], int]:
    """{(camera_id, frame_time): my_count}; a later label for the same frame wins."""
    return {(r["camera_id"], r["frame_time"]): int(r["my_count"]) for r in _read(eval_dir / "labels.csv")}


def add_label(camera_id: str, frame_time: str, count: int, eval_dir: Path = EVAL_DIR) -> None:
    _append(eval_dir / "labels.csv", LABEL_FIELDS, {"camera_id": camera_id, "frame_time": frame_time,
                                                    "my_count": count})


def labelled_items(eval_dir: Path = EVAL_DIR) -> list[tuple[EvalItem, int]]:
    """Manifest items that have a label and whose clip is still on disk."""
    labels = read_labels(eval_dir)
    return [(it, labels[(it.camera_id, it.frame_time)]) for it in read_manifest(eval_dir)
            if (it.camera_id, it.frame_time) in labels and (eval_dir / it.clip).exists()]


def purge(eval_dir: Path = EVAL_DIR) -> int:
    """Delete the sampled clips, frames and view images (they show people). labels.csv is kept."""
    removed = 0
    for sub in ("clips", "frames", "view"):
        d = eval_dir / sub
        if d.exists():
            removed += sum(1 for p in d.rglob("*") if p.is_file())
            shutil.rmtree(d)
    manifest = eval_dir / "manifest.csv"
    if manifest.exists():
        manifest.unlink()
    return removed
