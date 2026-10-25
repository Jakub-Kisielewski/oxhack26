import json
from dataclasses import replace

import numpy as np
import pytest

from src.pipeline.boxes import banner_rects, filter_boxes, foot_points, load_rois
from src.pipeline.config import Settings

SHAPE = (288, 352, 3)
S = replace(Settings(), min_box_h=8)  # default banners: date (0,0,124,13), logo (260,0,352,36), name (40,273,312,288)


def _box(x0, y0, x1, y1, conf=0.9):
    return [x0, y0, x1, y1, conf]


def test_foot_point_is_bottom_centre():
    assert foot_points(np.array([_box(10, 20, 30, 80)])).tolist() == [[20, 80]]


def test_min_box_height_filter():
    boxes = np.array([_box(10, 100, 20, 107), _box(30, 100, 40, 108), _box(50, 100, 60, 140)])
    kept = filter_boxes(boxes, SHAPE, settings=S)
    assert kept[:, 0].tolist() == [30, 50]  # 7 px dropped, 8 px kept
    assert len(filter_boxes(boxes, SHAPE, min_box_h=0, settings=S)) == 3


def test_banner_exclusion_uses_the_foot_point():
    boxes = np.array([
        _box(290, 2, 310, 30),    # foot (300, 30) inside the TfL logo box -> dropped
        _box(290, 10, 310, 45),   # starts in the logo box but stands below it -> kept
        _box(40, 0, 60, 12),      # foot (50, 12) inside the date box -> dropped
        _box(150, 0, 170, 12),    # foot (160, 12) right of the date box -> kept
        _box(170, 250, 180, 280), # foot (175, 280) on the camera-name box -> dropped
        _box(5, 250, 15, 280),    # foot (10, 280) left of the name box -> kept
    ])
    kept = filter_boxes(boxes, SHAPE, settings=S)
    assert kept[:, 3].tolist() == [45, 12, 280]
    assert kept[:, 0].tolist() == [290, 150, 5]


def test_banner_rects_scale_with_frame_size():
    assert banner_rects(352, 288, S)[1] == (260, 0, 352, 36)
    assert banner_rects(704, 576, S)[1] == (520, 0, 704, 72)
    assert banner_rects(352, 288, replace(S, banner_rects_px=())) == []


def test_roi_keeps_only_feet_inside_the_polygon():
    roi = [[0, 150], [352, 150], [352, 260], [0, 260]]  # the pavement band
    boxes = np.array([_box(10, 100, 20, 140), _box(10, 120, 20, 200), _box(300, 200, 320, 259)])
    kept = filter_boxes(boxes, SHAPE, roi=roi, settings=S)
    assert kept[:, 3].tolist() == [200, 259]


def test_empty_and_no_roi():
    assert filter_boxes(np.zeros((0, 5)), SHAPE, settings=S).shape == (0, 5)
    assert len(filter_boxes(np.array([_box(10, 100, 20, 140)]), SHAPE, roi=None, settings=S)) == 1


def test_load_rois(tmp_path):
    assert load_rois(tmp_path / "none.json") == {}
    p = tmp_path / "rois.json"
    p.write_text(json.dumps({"A": [[0, 0], [10, 0], [10, 10]]}))
    assert load_rois(p) == {"A": [[0, 0], [10, 0], [10, 10]]}
    p.write_text(json.dumps({"A": [[0, 0], [10, 0]]}))
    with pytest.raises(ValueError):
        load_rois(p)


def test_committed_rois_file_is_valid():
    load_rois()
