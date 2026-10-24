import json
from dataclasses import replace

import pytest

from src.pipeline import cameras, db
from src.pipeline.config import Settings

BBOX = (51.495, -0.180, 51.530, -0.070)
ZONE = cameras.load_zone()

# real places: route (Trafalgar Sq), central box (Piccadilly), zone 2 (Brixton), outside zones 1-2 (Heathrow)
ROUTE = {"id": "R", "lat": 51.5080, "lon": -0.1281}
BOX = {"id": "B", "lat": 51.5096, "lon": -0.1348}
ZONE2 = {"id": "Z", "lat": 51.4627, "lon": -0.1145}
OUTSIDE = {"id": "H", "lat": 51.4700, "lon": -0.4543}


def _cam(base, available=True):
    return {**base, "name": base["id"], "view": "", "image_url": f"{base['id']}.jpg",
            "video_url": f"{base['id']}.mp4", "available": available, "distance_m": None}


def _state(con):
    return {r["camera_id"]: (r["tier"], r["active"]) for r in con.execute("SELECT * FROM cameras")}


@pytest.fixture
def settings(tmp_path):
    return replace(Settings(), camera_overrides_path=str(tmp_path / "camera_overrides.json"))


def _refresh(con, settings, cams, route_ids=frozenset({"R"})):
    return cameras.refresh_cameras(con, settings, fetch_all=lambda: cams, fetch_route=lambda s: set(route_ids),
                                   zone=ZONE)


def test_computed_tier_rules():
    assert cameras.computed_tier(ROUTE, {"R"}, BBOX, ZONE) == 2
    assert cameras.computed_tier(BOX, {"R"}, BBOX, ZONE) == 1
    assert cameras.computed_tier(ZONE2, {"R"}, BBOX, ZONE) == 0
    assert cameras.computed_tier(OUTSIDE, {"H"}, BBOX, ZONE) is None  # outside zones 1-2 even if "on route"


def test_load_overrides(tmp_path):
    path = tmp_path / "o.json"
    assert cameras.load_overrides(path) == {}
    path.write_text(json.dumps({"Z": 2, "B": 0}))
    assert cameras.load_overrides(path) == {"Z": 2, "B": 0}
    for bad in ({"Z": 3}, {"Z": "2"}, {"Z": True}, [["Z", 2]]):
        path.write_text(json.dumps(bad))
        with pytest.raises(ValueError):
            cameras.load_overrides(path)


def test_refresh_registers_zones_1_2_with_tiers_and_summary(con, settings):
    summary = _refresh(con, settings, [_cam(ROUTE), _cam(BOX), _cam(ZONE2), _cam(OUTSIDE)])
    assert _state(con) == {"R": (2, 1), "B": (1, 1), "Z": (0, 1)}
    assert summary == [{"tier": 2, "cameras": 1, "active": 1}, {"tier": 1, "cameras": 1, "active": 1},
                       {"tier": 0, "cameras": 1, "active": 1}]


def test_refresh_never_deletes_and_reactivates(con, settings):
    _refresh(con, settings, [_cam(ROUTE), _cam(BOX), _cam(ZONE2)])
    # B disappears from TfL's list, Z reports available=false
    _refresh(con, settings, [_cam(ROUTE), _cam(ZONE2, available=False)])
    assert _state(con) == {"R": (2, 1), "B": (1, 0), "Z": (0, 0)}
    # both come back
    _refresh(con, settings, [_cam(ROUTE), _cam(BOX), _cam(ZONE2)])
    assert _state(con) == {"R": (2, 1), "B": (1, 1), "Z": (0, 1)}


def test_overrides_win_and_survive_refreshes(con, settings):
    with open(settings.camera_overrides_path, "w") as f:
        json.dump({"Z": 2, "R": 0, "H": 1}, f)
    for _ in range(2):
        _refresh(con, settings, [_cam(ROUTE), _cam(BOX), _cam(ZONE2), _cam(OUTSIDE)])
        assert _state(con) == {"R": (0, 1), "B": (1, 1), "Z": (2, 1), "H": (1, 1)}


def test_refresh_keeps_homography(con, settings):
    _refresh(con, settings, [_cam(ROUTE)])
    con.execute("UPDATE cameras SET homography = '[[1,0,0],[0,1,0],[0,0,1]]'")
    _refresh(con, settings, [_cam(ROUTE)])
    assert con.execute("SELECT homography FROM cameras").fetchone()[0] is not None


def test_empty_tfl_list_leaves_registry_unchanged(con, settings):
    _refresh(con, settings, [_cam(ROUTE), _cam(BOX)])
    with pytest.raises(RuntimeError):
        _refresh(con, settings, [])
    assert _state(con) == {"R": (2, 1), "B": (1, 1)}


def test_upsert_refuses_to_deactivate_everything(con):
    with pytest.raises(ValueError):
        db.upsert_cameras(con, [], deactivate_missing=True)


def test_format_summary_totals():
    text = cameras.format_summary([{"tier": 2, "cameras": 7, "active": 7}, {"tier": 0, "cameras": 3, "active": 1}])
    assert text.splitlines()[-1].split()[-2:] == ["10", "8"]
