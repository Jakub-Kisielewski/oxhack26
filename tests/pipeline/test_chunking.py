import logging

from src.pipeline.chunking import clip_duration_s, split_clip
from media import make_mp4


def test_short_clip_is_one_chunk_without_reencode(caplog):
    data = make_mp4(4, fps=10)
    assert abs(clip_duration_s(data) - 4.0) < 0.2
    with caplog.at_level(logging.WARNING):
        assert split_clip(data, chunk_seconds=15) == [data]
    assert not caplog.records


def test_long_clip_stays_one_chunk_and_warns(caplog):
    data = make_mp4(17, fps=5)
    with caplog.at_level(logging.WARNING):
        assert split_clip(data, chunk_seconds=15) == [data]
    assert "keeping it as one chunk" in caplog.text


def test_unreadable_bytes_pass_through():
    assert clip_duration_s(b"not a video") is None
    assert split_clip(b"not a video", 15) == [b"not a video"]
