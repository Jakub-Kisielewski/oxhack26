"""Mock predictor: contract-valid, deterministic, illustrative outputs built from real streets.

Lets the visual layer be built before the model exists. Segment ids and geometry come
from the real `segments` table so the UI renders exactly what the real model will
return; the numbers are made up (corridors around straight lines, simple physics).
Needs no files under data/models/.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
from datetime import datetime

from src.contract import mapdata
from src.contract.errors import PredictionError
from src.contract.types import (BacktestResult, BacktestRow, CellValue, Destination, Driver, Hotspot, LonLat,
                                OverspillPrediction, OverspillRequest, Path, PointRisk, PoliceAllocation, PolicePost,
                                Prediction, RouteOption, RoutePrediction, RouteRequest, SegmentProb, SegmentTiming,
                                ShopAdvice, SpillRisk, TurnoutEstimate, WarehouseOption, risk_level)

WARNING = "Mock predictor: outputs are illustrative, not model predictions."
SPEED_M_PER_MIN = 42.0         # 2.5 km/h
DEFAULT_TURNOUT = 20_000
RALLY_MIN = 60.0
FRUIN_QUEUING = [(0.83, "A"), (1.08, "B"), (1.54, "C"), (3.3, "D"), (5.0, "E")]  # people/m2 upper bounds


def level_of_service(density: float) -> str:
    return next((los for limit, los in FRUIN_QUEUING if density < limit), "F")


# ---------- flat-earth geometry (fine at city scale) ----------

def _xy(p: LonLat, lat0: float) -> tuple[float, float]:
    return p[0] * 111_320 * math.cos(math.radians(lat0)), p[1] * 110_540


def _lonlat(xy: tuple[float, float], lat0: float) -> LonLat:
    return xy[0] / (111_320 * math.cos(math.radians(lat0))), xy[1] / 110_540


def _project(p: LonLat, line: Path, lat0: float) -> tuple[float, float]:
    """(distance to the polyline, distance along it to the closest point), in metres."""
    px, py = _xy(p, lat0)
    best, along_best, along = math.inf, 0.0, 0.0
    for a, b in zip(line, line[1:]):
        (ax, ay), (bx, by) = _xy(a, lat0), _xy(b, lat0)
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
        d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
        if d < best:
            best, along_best = d, along + t * math.sqrt(seg2)
        along += math.sqrt(seg2)
    return best, along_best


def _length_m(line: Path) -> float:
    return sum(mapdata.distance_m(a, b) for a, b in zip(line, line[1:]))


def _inside(p: LonLat, ring) -> bool:
    inside, (x, y) = False, p
    for (x1, y1), (x2, y2) in zip(ring, list(ring[1:]) + [ring[0]]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def _street(name) -> str:
    """Street name, or '' for the 'None'/'nan' strings missing OSM names become."""
    return "" if str(name or "").strip().lower() in ("", "none", "nan") else str(name)


def _mid(path: Path) -> LonLat:
    return path[len(path) // 2]


def _segments_near(lines: list[Path], corridor_m: float) -> list[dict]:
    """Segments whose midpoint lies within corridor_m of any line, with distance/along per line."""
    pts = [p for line in lines for p in line]
    lat0 = statistics.fmean(p[1] for p in pts)
    pad_lat, pad_lon = corridor_m / 110_540, corridor_m / (111_320 * math.cos(math.radians(lat0)))
    box = [min(p[0] for p in pts) - pad_lon, min(p[1] for p in pts) - pad_lat,
           max(p[0] for p in pts) + pad_lon, max(p[1] for p in pts) + pad_lat]
    rows = mapdata.cursor().execute("""
        SELECT segment_id, ST_X(ST_Centroid(geom)), ST_Y(ST_Centroid(geom)) FROM segments
        WHERE ST_Intersects(geom, ST_MakeEnvelope(?, ?, ?, ?))""", box).fetchall()
    out = []
    for sid, x, y in rows:
        proj = [_project((x, y), line, lat0) for line in lines]
        if min(d for d, _ in proj) <= corridor_m:
            out.append({"segment_id": sid, "mid": (x, y), "dist": [d for d, _ in proj], "along": [a for _, a in proj]})
    return out


class MockPredictor:
    name = "mock"
    version = "mock-1"

    @staticmethod
    def _rng(req) -> random.Random:
        digest = hashlib.sha256(json.dumps(req.to_dict(), sort_keys=True, default=str).encode()).hexdigest()
        return random.Random(int(digest[:16], 16))

    @staticmethod
    def _turnout(ctx) -> TurnoutEstimate:
        if ctx.turnout:
            return TurnoutEstimate(ctx.turnout, int(ctx.turnout * 0.7), int(ctx.turnout * 1.5), "user")
        return TurnoutEstimate(DEFAULT_TURNOUT, DEFAULT_TURNOUT // 2, DEFAULT_TURNOUT * 2, "mock")

    # ---------- route mode ----------

    def snap_route(self, points: list[LonLat]) -> list[str]:
        if len(points) < 2:
            raise PredictionError("Pick at least two points to make a route.")
        near = [c for c in _segments_near([list(points)], 60) if c["dist"][0] <= 60]
        if not near:
            raise PredictionError("No streets found along those points.")
        return [c["segment_id"] for c in sorted(near, key=lambda c: c["along"][0])]

    def predict_route(self, req: RouteRequest) -> RoutePrediction:
        ctx = req.context
        if not mapdata.in_boundary(req.start):
            raise PredictionError("The start point is outside the zones 1-2 area.")
        targets = mapdata.cause_targets(ctx.cause)
        end = req.end or targets[0]["lonlat"]
        end_label = "Chosen end point" if req.end else targets[0]["target_name"]
        lat0 = (req.start[1] + end[1]) / 2
        (sx, sy), (ex, ey) = _xy(req.start, lat0), _xy(end, lat0)
        norm = math.hypot(ex - sx, ey - sy) or 1.0
        nx_, ny_ = -(ey - sy) / norm, (ex - sx) / norm
        bend = lambda k: _lonlat(((sx + ex) / 2 + k * nx_, (sy + ey) / 2 + k * ny_), lat0)
        lines = [[req.start, end], [req.start, bend(300), end], [req.start, bend(-300), end]][:max(1, req.n_routes)]
        weights, route_probs = [0.9, 0.5, 0.3], [0.6, 0.25, 0.15]

        near = _segments_near(lines, 150)
        if req.exclusion_zones:
            near = [c for c in near if not any(_inside(c["mid"], ring) for ring in req.exclusion_zones)]
        probs = {c["segment_id"]: max(w * math.exp(-(d / 60) ** 2) for w, d in zip(weights, c["dist"])) for c in near}
        kept = sorted(((sid, p) for sid, p in probs.items() if p >= 0.01), key=lambda t: -t[1])[:5000]
        paths = mapdata.segment_paths([sid for sid, _ in kept])
        segments = [SegmentProb(sid, round(p, 4), paths[sid]) for sid, p in kept if sid in paths]

        cell_of = mapdata.cells_for_segments([s.segment_id for s in segments])
        cells: dict[int, float] = {}
        for s in segments:
            if s.segment_id in cell_of:
                cells[cell_of[s.segment_id]] = max(cells.get(cell_of[s.segment_id], 0.0), s.p_visit)

        routes = []
        for r, line in enumerate(lines):
            ids = [c["segment_id"] for c in sorted((c for c in near if c["dist"][r] <= 40), key=lambda c: c["along"][r])]
            length = _length_m(line)
            routes.append(RouteOption(rank=r + 1, probability=route_probs[r], segment_ids=ids, path=list(line),
                                      length_m=round(length, 1), duration_min=round(length / SPEED_M_PER_MIN, 1),
                                      end_label=end_label))

        top = targets[:3]
        total = sum(t["weight"] for t in top) or 1.0
        destinations = [Destination(t["target_name"], t["lonlat"], round(0.9 * t["weight"] / total, 3)) for t in top]
        drivers = [Driver(f"Pull towards {end_label}", targets[0]["weight"], 0.6, "Marches head for the main target of this cause."),
                   Driver("Wide main roads", "preferred", 0.3, "Large crowds stay on wide roads."),
                   Driver("Sharp turns", "avoided", -0.2, "Routes with fewer turns are more likely.")]
        return RoutePrediction(request=req, turnout=self._turnout(ctx), segments=segments,
                               cells=[CellValue(k, round(v, 4)) for k, v in sorted(cells.items(), key=lambda kv: -kv[1])],
                               routes=routes, destinations=destinations,
                               expected_duration_min=round(routes[0].length_m / SPEED_M_PER_MIN + RALLY_MIN, 1),
                               drivers=drivers, model_version=self.version, warnings=[WARNING])

    # ---------- overspill mode ----------

    def predict_overspill(self, req: OverspillRequest) -> OverspillPrediction:
        ids = list(req.route_segment_ids)
        if not ids:
            raise PredictionError("The route is empty.")
        cur = mapdata.cursor()
        width = "COALESCE(width_m, 10.0)" if mapdata._has_column("segments", "width_m") else "10.0"
        rows = {r[0]: r for r in cur.execute(f"""
            SELECT segment_id, length_m, {width}, u, v, ST_AsGeoJSON(geom) FROM segments
            WHERE segment_id IN (SELECT UNNEST(?))""", [ids]).fetchall()}
        warnings = [WARNING]
        missing = [s for s in ids if s not in rows]
        if missing:
            warnings.append(f"{len(missing)} route segments were not found and were skipped.")
        ids = [s for s in ids if s in rows]
        if not ids:
            raise PredictionError("None of the route's streets were found.")
        rng, turnout = self._rng(req), self._turnout(req.context)
        median_w = statistics.median(float(rows[s][2]) for s in ids)
        crowd_length = turnout.expected / (1.5 * median_w)

        timeline, node_index, cum = [], {}, 0.0
        for i, sid in enumerate(ids):
            _, length, w, u, v, geo = rows[sid]
            head = cum / SPEED_M_PER_MIN
            density = max(0.5, min(6.0, 1.5 * median_w / float(w)))
            timeline.append(SegmentTiming(sid, mapdata._line(geo),
                                          round(head, 1), round(head + crowd_length / SPEED_M_PER_MIN, 1),
                                          round(density, 2), level_of_service(density)))
            node_index.setdefault(u, i)
            node_index.setdefault(v, i)
            cum += float(length or 0)

        name = "COALESCE(street_name, '')" if mapdata._has_column("segments", "street_name") else "''"
        side = cur.execute(f"""
            SELECT segment_id, u, v, {name}, ST_AsGeoJSON(geom) FROM segments
            WHERE (u IN (SELECT UNNEST(?)) OR v IN (SELECT UNNEST(?))) AND segment_id NOT IN (SELECT UNNEST(?))""",
                           [list(node_index), list(node_index), ids]).fetchall()
        target_points = [t["lonlat"] for t in mapdata.targets()]
        spill = []
        for sid, u, v, street, geo in side:
            i = node_index.get(u, node_index.get(v))
            t = timeline[i]
            path = mapdata._line(geo)
            p = 0.6 * (t.peak_density_ppm2 / 6.0) * rng.uniform(0.5, 1.0)
            if req.police_officers:
                p *= 0.8
            breakaway = any(mapdata.distance_m(_mid(path), tp) <= 150 for tp in target_points)
            spill.append(SpillRisk(sid, path, round(p, 4), "breakaway" if breakaway else "pressure",
                                   t.head_arrival_min, round(t.tail_departure_min + 30, 1),
                                   f"{_street(street) or 'Side street'} next to a {t.peak_density_ppm2:.1f} people/m² stretch"))
        spill = sorted(spill, key=lambda s: -s.p_spill)[:500]

        cell_of = mapdata.cells_for_segments([s.segment_id for s in spill])
        cells: dict[int, float] = {}
        for s in spill:
            if s.segment_id in cell_of:
                cells[cell_of[s.segment_id]] = max(cells.get(cell_of[s.segment_id], 0.0), s.p_spill)
        hotspots = [Hotspot(_mid(s.path), s.p_spill, risk_level(s.p_spill), s.kind, s.reason) for s in spill[:10]]
        return OverspillPrediction(
            request=req, turnout=turnout, timeline=timeline, spill=spill,
            cells=[CellValue(k, round(v, 4)) for k, v in sorted(cells.items(), key=lambda kv: -kv[1])],
            hotspots=hotspots, expected_duration_min=round(timeline[-1].tail_departure_min + RALLY_MIN, 1),
            drivers=[Driver("Bottlenecks", round(max(t.peak_density_ppm2 for t in timeline), 2), 0.5,
                            "Narrow stretches push the crowd into side streets."),
                     Driver("Turnout", turnout.expected, 0.3, "Bigger crowds take longer to pass and press harder.")],
            model_version=self.version, warnings=warnings)

    # ---------- decision tools ----------

    def point_risk(self, prediction: Prediction, point: LonLat) -> PointRisk:
        lat0 = point[1]
        if isinstance(prediction, RoutePrediction):
            items = [(s.segment_id, s.path, s.p_visit, None, None) for s in prediction.segments]
        else:
            items = [(t.segment_id, t.path, 1.0, t.head_arrival_min, t.tail_departure_min) for t in prediction.timeline]
            items += [(s.segment_id, s.path, s.p_spill, s.window_start_min, s.window_end_min) for s in prediction.spill]
        best = min(((_project(point, path, lat0)[0], sid, p, w0, w1) for sid, path, p, w0, w1 in items if len(path) > 1),
                   default=None)
        nearby = [b for b in [best] if b and b[0] <= 50]
        risk = nearby[0][2] if nearby else 0.0
        is_route = isinstance(prediction, RoutePrediction)
        return PointRisk(
            lonlat=point, nearest_segment_id=best[1] if best else None,
            distance_m=round(best[0], 1) if best else None, cell_id=mapdata.cell_at(point),
            p_visit=risk if is_route else 0.0, p_spill=0.0 if is_route else risk, risk=round(risk, 4),
            level=risk_level(risk), window_start_min=nearby[0][3] if nearby else None,
            window_end_min=nearby[0][4] if nearby else None,
            explanation=(f"{'March' if is_route else 'Crowd'} risk {risk:.0%} within 50 m." if nearby
                         else "No predicted crowd within 50 m."))

    def shop_advice(self, prediction: Prediction, shop: LonLat) -> ShopAdvice:
        risk = self.point_risk(prediction, shop)
        act_by = None
        if risk.risk >= 0.1:
            act_by = (risk.window_start_min if risk.window_start_min is not None else 0.0) - 60
        nearest = sorted(mapdata.warehouses(), key=lambda w: mapdata.distance_m(shop, w["lonlat"]))[:10]
        max_fp = max((w["footprint_m2"] or 0 for w in nearest), default=0) or 1.0
        options = []
        for w in nearest:
            d = mapdata.distance_m(shop, w["lonlat"]) * 1.3   # network distance approximation
            p = self.point_risk(prediction, w["lonlat"]).risk
            cap = (w["footprint_m2"] / max_fp) if w["footprint_m2"] else 0.5
            options.append(WarehouseOption(w["osm_id"], w["name"], w["lonlat"], round(d, 1), p, w["footprint_m2"],
                                           round(1 / (d + 100) * (1 - p) * cap * 1000, 4), [shop, w["lonlat"]]))
        options = sorted(options, key=lambda o: -o.utility)[:3]
        rec = ("No action needed." if act_by is None else
               f"Move stock {abs(act_by):.0f} min {'before' if act_by < 0 else 'after'} the march starts"
               + (f" to {options[0].name or 'the nearest warehouse'}." if options else "."))
        return ShopAdvice(shop=shop, risk=risk, act_by_min=act_by, recommendation=rec, warehouses=options)

    def allocate_police(self, prediction: OverspillPrediction, officers: int) -> PoliceAllocation:
        if not isinstance(prediction, OverspillPrediction):
            raise PredictionError("Police allocation needs an overspill prediction.")
        before = sum(s.p_spill for s in prediction.spill)
        top, units = prediction.spill[:50], max(0, officers) // 10
        total_p = sum(s.p_spill for s in top) or 1.0
        shares = [units * s.p_spill / total_p for s in top]
        counts = [int(x) for x in shares]
        for i in sorted(range(len(top)), key=lambda i: -(shares[i] - counts[i]))[:units - sum(counts)]:
            counts[i] += 1
        posts = [PolicePost(_mid(s.path), s.segment_id, n * 10, round(s.p_spill * (1 - math.exp(-0.05 * n * 10)), 4))
                 for s, n in zip(top, counts) if n]
        return PoliceAllocation(officers_total=officers, posts=sorted(posts, key=lambda p: -p.officers),
                                expected_spill_before=round(before, 3),
                                expected_spill_after=round(before * (0.7 if posts else 1.0), 3))

    def backtest(self) -> BacktestResult:
        events = [e.event_id for e in mapdata.historical_events()[:3]] or ["sample-1", "sample-2", "sample-3"]
        rows, sample = [], {"route_model": (-1.1, 0.62, True), "shortest_path": (-1.6, 0.48, False),
                            "random_walk": (-2.3, 0.12, False)}
        for e in events:
            for model, (ll, jac, hit) in sample.items():
                rows.append(BacktestRow(e, model, ll, jac, hit))
        summary = {m: {"mean_log_likelihood": ll, "top1_jaccard": j, "destination_in_top3": float(h)}
                   for m, (ll, j, h) in sample.items()}
        return BacktestResult(rows=rows, summary=summary, n_events=len(events),
                              created_at=datetime(2026, 1, 1).isoformat())
