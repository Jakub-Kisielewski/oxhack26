"""Hand-label people counts on current JamCam frames, for scripts/bench_detect.py.

    python scripts/label_frames.py              # sample 40 tier 1+2 clips (busy and quiet), then label them
    python scripts/label_frames.py --n 60       # sample more
    python scripts/label_frames.py --label-only # resume labelling what is already sampled
    python scripts/label_frames.py --purge      # delete the sampled clips/frames (do this after the bench)

Each frame opens in Preview (3x enlarged, camera name on top). Type the number of people you can see, Enter to skip,
q to stop. Labels go to data/eval/labels.csv (camera_id, frame_time, my_count). The sampled clips and frames show
people: they stay in data/eval/ (gitignored) only until --purge.
"""
from __future__ import annotations

import argparse
import random
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.pipeline import db, evalset  # noqa: E402
from src.pipeline.config import SETTINGS  # noqa: E402
from src.pipeline.features import sample_clip  # noqa: E402
from src.pipeline.jamcam_poller import SESSION  # noqa: E402


def sample(n: int, seed: int) -> None:
    con = db.connect(read_only=True)
    cams = [c for c in db.latest_observation_per_camera(con, since_minutes=60) if c["tier"] in (1, 2)]
    chosen = evalset.choose_cameras(cams, n, random.Random(seed))
    have = {(it.camera_id, it.frame_time) for it in evalset.read_manifest()}
    print(f"sampling {len(chosen)} of {len(cams)} tier 1+2 cameras")
    for cam in chosen:
        try:
            resp = SESSION.get(cam["video_url"], timeout=30)
            resp.raise_for_status()
        except Exception as e:
            print(f"  skip {cam['name']}: {e}")
            continue
        frame_time = db.to_iso(resp.headers["Last-Modified"])
        if (cam["camera_id"], frame_time) in have:
            continue
        frames, _ = sample_clip(resp.content, SETTINGS.sample_fps)
        if not frames:
            print(f"  skip {cam['name']}: unreadable clip")
            continue
        stem = evalset.file_stem(cam["camera_id"], frame_time)
        idx = len(frames) // 2
        (evalset.EVAL_DIR / "clips").mkdir(parents=True, exist_ok=True)
        (evalset.EVAL_DIR / "frames").mkdir(parents=True, exist_ok=True)
        (evalset.EVAL_DIR / "clips" / f"{stem}.mp4").write_bytes(resp.content)
        cv2.imwrite(str(evalset.EVAL_DIR / "frames" / f"{stem}.png"), frames[idx])
        evalset.add_to_manifest(evalset.EvalItem(cam["camera_id"], cam["name"], cam["tier"], frame_time,
                                                 f"clips/{stem}.mp4", f"frames/{stem}.png", idx, SETTINGS.sample_fps))
        print(f"  {cam['name']:<40} latest count {cam['people']}")


def view_image(item: evalset.EvalItem, i: int, total: int) -> Path:
    frame = cv2.imread(str(evalset.EVAL_DIR / item.frame))
    big = cv2.resize(frame, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    header = np.zeros((40, big.shape[1], 3), np.uint8)
    cv2.putText(header, f"{i}/{total}  {item.name}  (tier {item.tier})  {item.frame_time[11:19]} UTC",
                (8, 27), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1)
    out = evalset.EVAL_DIR / "view" / Path(item.frame).name
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), np.vstack([header, big]))
    return out


def label(open_images: bool) -> None:
    labels = evalset.read_labels()
    todo = [it for it in evalset.read_manifest() if (it.camera_id, it.frame_time) not in labels]
    print(f"{len(labels)} labelled, {len(todo)} to go. Count every person you can see, including partly hidden ones.")
    for i, item in enumerate(todo, 1):
        path = view_image(item, i, len(todo))
        if open_images:
            subprocess.run(["open", "-g", str(path)], check=False)
        else:
            print(f"  {path}")
        while True:
            answer = input(f"[{i}/{len(todo)}] {item.name}: people visible (Enter=skip, q=quit) > ").strip().lower()
            if answer in ("", "q") or answer.isdigit():
                break
            print("  type a whole number, Enter or q")
        if answer == "q":
            break
        if answer.isdigit():
            evalset.add_label(item.camera_id, item.frame_time, int(answer))
    print(f"labels: {len(evalset.read_labels())} in {evalset.EVAL_DIR / 'labels.csv'}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--label-only", action="store_true")
    ap.add_argument("--no-open", action="store_true", help="print image paths instead of opening Preview")
    ap.add_argument("--purge", action="store_true", help="delete sampled clips and frames, keep labels.csv")
    args = ap.parse_args()
    if args.purge:
        print(f"deleted {evalset.purge()} files; kept {evalset.EVAL_DIR / 'labels.csv'}")
        return
    if not args.label_only:
        sample(args.n, args.seed)
    label(open_images=not args.no_open)


if __name__ == "__main__":
    main()
