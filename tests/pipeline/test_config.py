import pytest

from src.pipeline.config import DEFAULT_ROUTE_POINTS, Settings, load_settings, parse_route_points


def test_defaults_when_env_empty():
    s = load_settings({})
    assert s == Settings()
    assert s.route_points == DEFAULT_ROUTE_POINTS
    assert (s.sample_fps, s.lag_seconds, s.still_lag_seconds) == (2.0, 60, 120)
    assert (s.tier1_enabled, s.tier1_kind, s.tier1_poll_seconds) == (True, "clip", 15)
    assert (s.tier0_enabled, s.tier0_kind, s.tier0_poll_seconds) == (True, "still", 60)
    assert (s.lag_for("clip"), s.lag_for("still")) == (60, 120)
    assert (s.tier2_reserved_threads, s.valve_slow_rounds, s.valve_pause_seconds) == (4, 2, 300)


def test_env_overrides():
    s = load_settings({"SAMPLE_FPS": "4", "LAG_SECONDS": "90", "TIER1_ENABLED": "false",
                       "ROUTE_POINTS": "51.5,-0.1; 51.6,-0.2", "CENTRAL_BBOX": "1,2,3,4", "YOLO_DEVICE": ""})
    assert s.sample_fps == 4.0
    assert s.lag_seconds == 90
    assert s.tier1_enabled is False
    assert s.route_points == ((51.5, -0.1), (51.6, -0.2))
    assert s.central_bbox == (1.0, 2.0, 3.0, 4.0)
    assert s.yolo_device == ""


def test_bad_route_points_rejected():
    with pytest.raises(ValueError):
        parse_route_points("51.5,-0.1,7")
    with pytest.raises(ValueError):
        parse_route_points("51.5,-0.1")  # a line needs two points


def test_route_lines_wraps_route_points():
    s = load_settings({"ROUTE_POINTS": "51.5,-0.1;51.6,-0.2", "ROUTE_BUFFER_M": "150"})
    assert s.route_lines == (((51.5, -0.1), (51.6, -0.2)),)
    assert s.route_buffer_m == 150.0


def test_tier_description_follows_poller_settings():
    s = load_settings({})
    assert s.tier_description(2) == "route: clips every 15 s"
    assert s.tier_description(1) == "central box: clips every 15 s"
    assert s.tier_description(0) == "rest of zones 1-2: stills every 60 s"
    off = load_settings({"TIER0_ENABLED": "false", "TIER1_KIND": "still", "TIER1_POLL_SECONDS": "60"})
    assert off.tier_description(0) == "rest of zones 1-2: not polled"
    assert off.tier_description(1) == "central box: stills every 60 s"


def test_twin_lag_is_the_max_over_enabled_kinds():
    assert load_settings({}).twin_lag_seconds == 120  # tier 0 stills enabled
    assert load_settings({"TIER0_ENABLED": "false"}).twin_lag_seconds == 60  # clips only
    assert load_settings({"TIER0_KIND": "clip"}).twin_lag_seconds == 60


def test_banner_rects_env_override():
    s = load_settings({"BANNER_RECTS_PX": "0,0,10,10; 20,20,30,30"})
    assert s.banner_rects_px == ((0, 0, 10, 10), (20, 20, 30, 30))
    assert len(load_settings({}).banner_rects_px) == 3
