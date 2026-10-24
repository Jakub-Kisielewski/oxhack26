"""Camera registry: sync TfL JamCams in zones 1–2 into `cameras` with a polling tier (2 route, 1 box, 0 rest)."""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from shapely.geometry import Point, shape
from shapely.prepared import PreparedGeometry, prep

from src.pipeline import db
from src.pipeline.config import REPO_ROOT, SETTINGS, Settings
from src.pipeline.jamcam_poller import _to_cam, cameras_along_route, tfl_get

log = logging.getLogger(__name__)

ZONES_GEOJSON = Path(__file__).with_name("zones_1_2.geojson")
TIERS = (0, 1, 2)
TIER_LABELS = {2: "route: clips every 15 s", 1: "central box: stills every 60 s", 0: "registered, not polled"}


def load_zone(path: Path = ZONES_GEOJSON) -> PreparedGeometry:
    """The zones 1–2 polygon (lon/lat) from GeoJSON, prepared for fast point tests."""
    return prep(shape(json.loads(path.read_text())["geometry"]))


def load_overrides(path: Path) -> dict[str, int]:
    """Manual tiers as {camera_id: tier} from JSON; a missing file means no overrides."""
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a JSON object {{camera_id: tier}}")
    bad = {k: v for k, v in raw.items() if type(v) is not int or v not in TIERS}
    if bad:
        raise ValueError(f"{path}: tiers must be one of {TIERS}, got {bad}")
    return dict(raw)


def fetch_all_cameras() -> list[dict[str, Any]]:
    """Every JamCam TfL lists, available or not, as jamcam_poller camera dicts."""
    return [_to_cam(p) for p in tfl_get("/Place/Type/JamCam")]


def fetch_route_ids(settings: Settings) -> set[str]:
    """Ids of available cameras within RADIUS_M of any ROUTE_POINTS (TfL radius search)."""
    return {c["id"] for c in cameras_along_route(settings.route_points, settings.radius_m)}


def computed_tier(cam: Mapping[str, Any], route_ids: set[str], bbox: tuple[float, float, float, float],
                  zone: PreparedGeometry) -> int | None:
    """2 near the route, 1 in the central box, 0 elsewhere in zones 1–2; None outside zones 1–2."""
    if not zone.contains(Point(cam["lon"], cam["lat"])):
        return None
    if cam["id"] in route_ids:
        return 2
    lat0, lon0, lat1, lon1 = bbox
    return 1 if lat0 <= cam["lat"] <= lat1 and lon0 <= cam["lon"] <= lon1 else 0


def build_registry(cams: Iterable[Mapping[str, Any]], route_ids: set[str], overrides: Mapping[str, int],
                   bbox: tuple[float, float, float, float], zone: PreparedGeometry) -> list[dict[str, Any]]:
    """Rows for db.upsert_cameras: zones 1–2 cameras plus overridden ones; overrides win; active = available."""
    rows = []
    for cam in cams:
        tier = overrides.get(cam["id"], computed_tier(cam, route_ids, bbox, zone))
        if tier is None:
            continue
        rows.append({"camera_id": cam["id"], "name": cam["name"], "lat": cam["lat"], "lon": cam["lon"],
                     "view": cam["view"], "image_url": cam["image_url"], "video_url": cam["video_url"],
                     "tier": tier, "active": bool(cam["available"])})
    return rows


def refresh_cameras(con, settings: Settings = SETTINGS,
                    fetch_all: Callable[[], list[dict[str, Any]]] = fetch_all_cameras,
                    fetch_route: Callable[[Settings], set[str]] = fetch_route_ids,
                    zone: PreparedGeometry | None = None) -> list[dict[str, Any]]:
    """One registry sync. Never deletes: missing or unavailable cameras get active=0. Returns the tier summary."""
    cams = fetch_all()
    if not cams:
        raise RuntimeError("TfL returned no cameras; registry left unchanged")
    route_ids = fetch_route(settings)
    overrides = load_overrides(REPO_ROOT / settings.camera_overrides_path)
    unknown = set(overrides) - {c["id"] for c in cams}
    if unknown:
        log.warning("overrides for cameras TfL no longer lists (kept inactive): %s", sorted(unknown))
    rows = build_registry(cams, route_ids, overrides, settings.central_bbox, zone or load_zone())
    db.upsert_cameras(con, rows, deactivate_missing=True)
    log.info("registry: %d cameras synced, %d overrides applied", len(rows), len(set(overrides) - unknown))
    return db.camera_tier_summary(con)


def format_summary(summary: list[dict[str, Any]]) -> str:
    lines = [f"{'tier':>4}  {'meaning':<32} {'cameras':>7} {'active':>6}"]
    for r in summary:
        lines.append(f"{r['tier']:>4}  {TIER_LABELS.get(r['tier'], ''):<32} {r['cameras']:>7} {r['active']:>6}")
    lines.append(f"{'total':>5} {'':<32} {sum(r['cameras'] for r in summary):>7} "
                 f"{sum(r['active'] for r in summary):>6}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Sync zones 1–2 JamCams into the cameras table with tiers.")
    ap.add_argument("--list", action="store_true", help="also print every registered camera")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    con = db.connect()
    db.init_db(con)
    print(format_summary(refresh_cameras(con)))
    if args.list:
        for r in con.execute("SELECT camera_id, tier, active, name FROM cameras ORDER BY tier DESC, name"):
            print(f"{r['tier']}  {'on ' if r['active'] else 'off'}  {r['camera_id']:<22} {r['name']}")


if __name__ == "__main__":
    main()
