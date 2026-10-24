import pytest

from src.pipeline.config import DEFAULT_ROUTE_POINTS, Settings, load_settings, parse_route_points


def test_defaults_when_env_empty():
    s = load_settings({})
    assert s == Settings()
    assert s.route_points == DEFAULT_ROUTE_POINTS
    assert (s.sample_fps, s.lag_seconds, s.tier1_enabled) == (2.0, 45, False)


def test_env_overrides():
    s = load_settings({"SAMPLE_FPS": "4", "LAG_SECONDS": "90", "TIER1_ENABLED": "true",
                       "ROUTE_POINTS": "51.5,-0.1; 51.6,-0.2", "CENTRAL_BBOX": "1,2,3,4", "YOLO_DEVICE": ""})
    assert s.sample_fps == 4.0
    assert s.lag_seconds == 90
    assert s.tier1_enabled is True
    assert s.route_points == ((51.5, -0.1), (51.6, -0.2))
    assert s.central_bbox == (1.0, 2.0, 3.0, 4.0)
    assert s.yolo_device == ""


def test_bad_route_points_rejected():
    with pytest.raises(ValueError):
        parse_route_points("51.5,-0.1,7")
