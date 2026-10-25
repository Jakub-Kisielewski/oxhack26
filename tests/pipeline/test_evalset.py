import random

from src.pipeline import evalset


def test_choose_cameras_mixes_busiest_and_random():
    cams = [{"camera_id": f"c{i}", "people": float(i)} for i in range(20)] + [{"camera_id": "none", "people": None}]
    chosen = evalset.choose_cameras(cams, 6, random.Random(0))
    ids = [c["camera_id"] for c in chosen]
    assert ids[:3] == ["c19", "c18", "c17"] and len(set(ids)) == 6


def test_manifest_labels_and_purge(tmp_path):
    item = evalset.EvalItem("A", "Cam A", 2, "2026-10-25T09:00:00+00:00", "clips/a.mp4", "frames/a.png", 11, 2.0)
    (tmp_path / "clips").mkdir()
    (tmp_path / "clips" / "a.mp4").write_bytes(b"x")
    (tmp_path / "frames").mkdir()
    (tmp_path / "frames" / "a.png").write_bytes(b"x")
    evalset.add_to_manifest(item, tmp_path)
    assert evalset.read_manifest(tmp_path) == [item]
    assert evalset.labelled_items(tmp_path) == []
    evalset.add_label("A", item.frame_time, 3, tmp_path)
    evalset.add_label("A", item.frame_time, 4, tmp_path)  # relabel: later wins
    assert evalset.labelled_items(tmp_path) == [(item, 4)]
    assert evalset.purge(tmp_path) == 2
    assert not (tmp_path / "clips").exists() and (tmp_path / "labels.csv").exists()
    assert evalset.labelled_items(tmp_path) == []


def test_file_stem():
    assert evalset.file_stem("JamCams_1", "2026-10-25T09:00:05+00:00") == "JamCams_1_20261025T090005Z"
