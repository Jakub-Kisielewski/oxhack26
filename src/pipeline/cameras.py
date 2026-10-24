"""Camera registry: sync TfL JamCams in zones 1–2 into `cameras` with a polling tier (2 route, 1 box, 0 rest)."""
from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from pyproj import Transformer
from shapely.geometry import MultiLineString, Point, shape
from shapely.prepared import PreparedGeometry, prep

from src.pipeline import db
from src.pipeline.config import REPO_ROOT, SETTINGS, Settings
from src.pipeline.jamcam_poller import _to_cam, tfl_get

log = logging.getLogger(__name__)

ZONES_GEOJSON = Path(__file__).with_name("zones_1_2.geojson")
TIERS = (0, 1, 2)
TIER_LABELS = {2: "route: clips every 15 s", 1: "central box: stills every 60 s", 0: "registered, not polled"}

_TO_BNG = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)  # British National Grid, metres

Polyline = Sequence[tuple[float, float]]  # (lat, lon) points


@dataclass(frozen=True)
class TierChange:
    camera_id: str
    name: str
    old: int | None  # None = newly registered
    new: int


@dataclass(frozen=True)
class RefreshResult:
    summary: list[dict[str, Any]]
    changes: list[TierChange]


def load_zone(path: Path = ZONES_GEOJSON) -> PreparedGeometry:
    """The zones 1–2 polygon (lon/lat) from GeoJSON, prepared for fast point tests."""
    return prep(shape(json.loads(path.read_text())["geometry"]))


def route_geometry(lines: Sequence[Polyline]) -> MultiLineString:
    """Union of route polylines, projected to British National Grid so distances are in metres."""
    # TODO(Step 7): replace the straight segments between route points with the OSM street path between them.
    if not lines or any(len(line) < 2 for line in lines):
        raise ValueError("every route line needs at least two (lat, lon) points")
    return MultiLineString([[_TO_BNG.transform(lon, lat) for lat, lon in line] for line in lines])


def route_camera_ids(cams: Iterable[Mapping[str, Any]], lines: Sequence[Polyline], buffer_m: float) -> set[str]:
    """Ids of cameras within buffer_m metres of any segment of any route line."""
    route = route_geometry(lines)
    return {c["id"] for c in cams if route.distance(Point(_TO_BNG.transform(c["lon"], c["lat"]))) <= buffer_m}


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


def merged_overrides(settings: Settings) -> dict[str, int]:
    """Shared committed overrides, then the optional local file, which wins."""
    return {**load_overrides(REPO_ROOT / settings.camera_overrides_path),
            **load_overrides(REPO_ROOT / settings.local_camera_overrides_path)}


def fetch_all_cameras() -> list[dict[str, Any]]:
    """Every JamCam TfL lists, available or not, as jamcam_poller camera dicts."""
    return [_to_cam(p) for p in tfl_get("/Place/Type/JamCam")]


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
                    zone: PreparedGeometry | None = None) -> RefreshResult:
    """One registry sync. Never deletes: missing or unavailable cameras get active=0."""
    cams = fetch_all()
    if not cams:
        raise RuntimeError("TfL returned no cameras; registry left unchanged")
    route_ids = route_camera_ids(cams, settings.route_lines, settings.route_buffer_m)
    overrides = merged_overrides(settings)
    unknown = set(overrides) - {c["id"] for c in cams}
    if unknown:
        log.warning("overrides for cameras TfL no longer lists (kept inactive): %s", sorted(unknown))
    rows = build_registry(cams, route_ids, overrides, settings.central_bbox, zone or load_zone())
    before = db.camera_tiers(con)
    db.upsert_cameras(con, rows, deactivate_missing=True)
    changes = [TierChange(r["camera_id"], r["name"], before.get(r["camera_id"]), r["tier"])
               for r in rows if before.get(r["camera_id"]) != r["tier"]]
    log.info("registry: %d cameras synced, %d overrides applied, %d tier changes",
             len(rows), len(set(overrides) - unknown), len(changes))
    return RefreshResult(db.camera_tier_summary(con), changes)


def format_summary(summary: list[dict[str, Any]]) -> str:
    lines = [f"{'tier':>4}  {'meaning':<32} {'cameras':>7} {'active':>6}"]
    for r in summary:
        lines.append(f"{r['tier']:>4}  {TIER_LABELS.get(r['tier'], ''):<32} {r['cameras']:>7} {r['active']:>6}")
    lines.append(f"{'total':>5} {'':<32} {sum(r['cameras'] for r in summary):>7} "
                 f"{sum(r['active'] for r in summary):>6}")
    return "\n".join(lines)


def format_tier2_changes(changes: list[TierChange]) -> str:
    into = [c for c in changes if c.new == 2]
    out = [c for c in changes if c.old == 2]
    lines = [f"moved into tier 2: {len(into)}"]
    lines += [f"  {c.camera_id:<22} {c.name:<36} {'new' if c.old is None else f'from tier {c.old}'}" for c in into]
    lines.append(f"moved out of tier 2: {len(out)}")
    lines += [f"  {c.camera_id:<22} {c.name:<36} to tier {c.new}" for c in out]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Sync zones 1–2 JamCams into the cameras table with tiers.")
    ap.add_argument("--list", action="store_true", help="also print every registered camera")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    con = db.connect()
    db.init_db(con)
    result = refresh_cameras(con)
    print(format_summary(result.summary))
    print(format_tier2_changes(result.changes))
    if args.list:
        for r in con.execute("SELECT camera_id, tier, active, name FROM cameras ORDER BY tier DESC, name"):
            print(f"{r['tier']}  {'on ' if r['active'] else 'off'}  {r['camera_id']:<22} {r['name']}")


if __name__ == "__main__":
    main()
