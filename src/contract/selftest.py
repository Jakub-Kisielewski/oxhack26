"""Contract self-test: `python -m src.contract.selftest [--predictor mock|real|both]`

Runs every Predictor method with fixed inputs and checks the contract's invariants
(types, probability ranges, (lon, lat) order, sorting, size limits, segment ids that
exist, JSON-serialisable outputs). Timing budgets are reported as warnings.
Exits with status 1 on any failure. Both tracks run this before every push.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Callable

from src.contract import mapdata
from src.contract.api import Predictor
from src.contract.errors import PredictionError
from src.contract.types import (BacktestResult, MarchContext, OverspillPrediction, OverspillRequest, PointRisk,
                                PoliceAllocation, RoutePrediction, RouteRequest, ShopAdvice, risk_level)

START = (-0.1586, 51.5136)        # Marble Arch
POINT = (-0.1281, 51.5080)        # Trafalgar Square
OUTSIDE = (0.30, 51.70)           # well outside zones 1-2
BUDGET_S = {"predict_route": 3, "predict_overspill": 3, "snap_route": 1, "point_risk": 0.1,
            "shop_advice": 1, "allocate_police": 1}
LOS = {"A", "B", "C", "D", "E", "F"}


class Checker:
    def __init__(self, label: str):
        self.label, self.failures, self.warnings = label, [], []

    def check(self, ok: bool, message: str) -> bool:
        if not ok:
            self.failures.append(message)
        return ok

    def timed(self, name: str, fn: Callable, *args):
        start = time.monotonic()
        result = fn(*args)
        elapsed = time.monotonic() - start
        if elapsed > BUDGET_S.get(name, 1e9):
            self.warnings.append(f"{name} took {elapsed:.2f}s (budget {BUDGET_S[name]}s)")
        return result


def lonlat_ok(p) -> bool:
    return (isinstance(p, (tuple, list)) and len(p) == 2 and all(isinstance(v, (int, float)) for v in p)
            and -0.6 <= p[0] <= 0.4 and 51.2 <= p[1] <= 51.8)


def path_ok(path) -> bool:
    return isinstance(path, list) and len(path) >= 1 and all(lonlat_ok(p) for p in path)


def prob_ok(x) -> bool:
    return isinstance(x, (int, float)) and 0.0 <= x <= 1.0


def is_desc(values) -> bool:
    values = list(values)
    return all(a >= b for a, b in zip(values, values[1:]))


def unknown_segments(ids) -> set:
    ids = set(ids)
    if not ids:
        return set()
    found = {r[0] for r in mapdata.cursor().execute(
        "SELECT segment_id FROM segments WHERE segment_id IN (SELECT UNNEST(?))", [list(ids)]).fetchall()}
    return ids - found


def json_ok(c: Checker, obj, what: str) -> None:
    try:
        json.dumps(obj.to_dict())
    except (TypeError, ValueError) as exc:
        c.check(False, f"{what}.to_dict() is not JSON-serialisable: {exc}")


def check_route(c: Checker, p: RoutePrediction, req: RouteRequest) -> None:
    if not c.check(isinstance(p, RoutePrediction), f"predict_route returned {type(p).__name__}"):
        return
    c.check(p.turnout.low <= p.turnout.expected <= p.turnout.high, "turnout: low <= expected <= high")
    c.check(len(p.segments) <= 5000, "segments: at most 5000")
    c.check(is_desc(s.p_visit for s in p.segments), "segments: sorted by p_visit desc")
    c.check(all(prob_ok(s.p_visit) and s.p_visit >= 0.01 for s in p.segments), "segments: p_visit in [0.01, 1]")
    c.check(all(path_ok(s.path) for s in p.segments), "segments: paths are (lon, lat) inside London")
    c.check(all(prob_ok(x.value) for x in p.cells), "cells: values in [0, 1]")
    c.check(len(p.routes) <= req.n_routes, "routes: at most n_routes")
    c.check([r.rank for r in p.routes] == list(range(1, len(p.routes) + 1)), "routes: ranks 1..n in order")
    c.check(all(prob_ok(r.probability) and path_ok(r.path) and r.length_m >= 0 and r.duration_min >= 0
                for r in p.routes), "routes: probability, path, length, duration valid")
    c.check(is_desc(d.probability for d in p.destinations), "destinations: sorted desc")
    c.check(sum(d.probability for d in p.destinations) <= 1 + 1e-6, "destinations: probabilities sum to <= 1")
    c.check(all(lonlat_ok(d.lonlat) for d in p.destinations), "destinations: (lon, lat) inside London")
    ids = {s.segment_id for s in p.segments} | {i for r in p.routes for i in r.segment_ids}
    missing = unknown_segments(ids)
    c.check(not missing, f"route prediction: {len(missing)} unknown segment ids, e.g. {sorted(missing)[:3]}")
    c.check(p.expected_duration_min > 0, "expected_duration_min > 0")
    json_ok(c, p, "RoutePrediction")


def check_overspill(c: Checker, p: OverspillPrediction, req: OverspillRequest) -> None:
    if not c.check(isinstance(p, OverspillPrediction), f"predict_overspill returned {type(p).__name__}"):
        return
    route = list(req.route_segment_ids)
    c.check(len(p.timeline) == len(route) or any("not found" in w for w in p.warnings),
            f"timeline: one entry per route segment ({len(p.timeline)} vs {len(route)})")
    c.check([t.segment_id for t in p.timeline] == [s for s in route if s in {t.segment_id for t in p.timeline}],
            "timeline: in route order")
    c.check(all(t.head_arrival_min <= t.tail_departure_min for t in p.timeline), "timeline: head <= tail")
    c.check(all(t.level_of_service in LOS and t.peak_density_ppm2 >= 0 and path_ok(t.path) for t in p.timeline),
            "timeline: LOS A-F, density >= 0, valid paths")
    c.check(len(p.spill) <= 500 and is_desc(s.p_spill for s in p.spill), "spill: <= 500, sorted desc")
    c.check(all(prob_ok(s.p_spill) and s.kind in ("pressure", "breakaway") and s.window_start_min <= s.window_end_min
                and path_ok(s.path) for s in p.spill), "spill: p in [0,1], kind, window, path valid")
    c.check(not ({s.segment_id for s in p.spill} & set(route)), "spill: side streets are not on the route")
    c.check(len(p.hotspots) <= 20 and is_desc(h.risk for h in p.hotspots), "hotspots: <= 20, sorted desc")
    c.check(all(lonlat_ok(h.lonlat) and prob_ok(h.risk) and h.level == risk_level(h.risk) for h in p.hotspots),
            "hotspots: (lon, lat), risk, level consistent")
    c.check(all(prob_ok(x.value) for x in p.cells), "cells: values in [0, 1]")
    missing = unknown_segments({s.segment_id for s in p.spill} | {t.segment_id for t in p.timeline})
    c.check(not missing, f"overspill: {len(missing)} unknown segment ids")
    json_ok(c, p, "OverspillPrediction")


def check_point(c: Checker, r: PointRisk) -> None:
    if not c.check(isinstance(r, PointRisk), f"point_risk returned {type(r).__name__}"):
        return
    c.check(all(prob_ok(x) for x in (r.p_visit, r.p_spill, r.risk)), "point_risk: probabilities in [0, 1]")
    c.check(r.level == risk_level(r.risk), "point_risk: level matches risk_level(risk)")
    c.check(lonlat_ok(r.lonlat), "point_risk: (lon, lat)")
    json_ok(c, r, "PointRisk")


def run(predictor: Predictor) -> Checker:
    c = Checker(predictor.name)
    c.check(isinstance(predictor, Predictor), "predictor does not implement the Predictor protocol")

    route_req = RouteRequest(MarchContext(date="2026-03-21", start_time="12:00", cause="palestine"), start=START)
    route = c.timed("predict_route", predictor.predict_route, route_req)
    check_route(c, route, route_req)

    try:
        predictor.predict_route(RouteRequest(route_req.context, start=OUTSIDE))
        c.check(False, "predict_route: a start outside the boundary should raise PredictionError")
    except PredictionError as exc:
        c.check(bool(exc.user_message), "PredictionError needs a user_message")

    snapped = c.timed("snap_route", predictor.snap_route, [START, POINT])
    c.check(isinstance(snapped, list) and snapped and all(isinstance(s, str) for s in snapped),
            "snap_route: non-empty list of segment ids")
    c.check(not unknown_segments(snapped), "snap_route: unknown segment ids")

    events = mapdata.historical_events()
    if c.check(bool(events), "mapdata.historical_events() returned no events"):
        e = events[0]
        ov_req = OverspillRequest(MarchContext(date=e.date, start_time=e.start_time or "12:00", cause=e.cause,
                                               turnout=e.turnout), tuple(e.route_segment_ids))
        overspill = c.timed("predict_overspill", predictor.predict_overspill, ov_req)
        check_overspill(c, overspill, ov_req)
        check_point(c, c.timed("point_risk", predictor.point_risk, overspill, POINT))

        alloc = c.timed("allocate_police", predictor.allocate_police, overspill, 100)
        if c.check(isinstance(alloc, PoliceAllocation), "allocate_police: wrong type"):
            c.check(sum(p.officers for p in alloc.posts) <= 100, "allocate_police: no more officers than given")
            c.check(is_desc(p.officers for p in alloc.posts), "allocate_police: posts sorted by officers desc")
            c.check(alloc.expected_spill_after <= alloc.expected_spill_before + 1e-9, "allocate_police: spill not increased")
            c.check(all(lonlat_ok(p.lonlat) for p in alloc.posts), "allocate_police: (lon, lat)")
            json_ok(c, alloc, "PoliceAllocation")

    check_point(c, c.timed("point_risk", predictor.point_risk, route, POINT))
    advice = c.timed("shop_advice", predictor.shop_advice, route, POINT)
    if c.check(isinstance(advice, ShopAdvice), "shop_advice: wrong type"):
        c.check(len(advice.warehouses) <= 3 and is_desc(w.utility for w in advice.warehouses),
                "shop_advice: <= 3 warehouses, sorted by utility desc")
        c.check(all(lonlat_ok(w.lonlat) and path_ok(w.path) and prob_ok(w.p_disruption) for w in advice.warehouses),
                "shop_advice: warehouse coordinates, paths, p_disruption valid")
        check_point(c, advice.risk)
        json_ok(c, advice, "ShopAdvice")

    bt = predictor.backtest()
    if bt is not None and c.check(isinstance(bt, BacktestResult), "backtest: wrong type"):
        c.check(bool(bt.rows) and bt.n_events > 0, "backtest: has rows")
        json_ok(c, bt, "BacktestResult")
    return c


def predictors(choice: str) -> list[Predictor]:
    from src.contract.mock import MockPredictor
    out = [MockPredictor()] if choice in ("mock", "both") else []
    if choice in ("real", "both"):
        try:
            from src.models.predictor import RealPredictor
            if choice == "real" or RealPredictor.available():
                out.append(RealPredictor())
            else:
                print("real predictor: artefacts not found, skipped (run python -m src.models.train)")
        except ImportError as exc:
            if choice == "real":
                raise
            print(f"real predictor: not available yet ({exc.name}), skipped")
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--predictor", choices=["mock", "real", "both"], default="both")
    a = p.parse_args(argv)
    failed = False
    for predictor in predictors(a.predictor):
        try:
            c = run(predictor)
        except Exception as exc:  # report a crash as a failure of that predictor
            c = Checker(predictor.name)
            c.check(False, f"crashed: {exc.__class__.__name__}: {exc}")
        status = "PASS" if not c.failures else "FAIL"
        print(f"[{status}] {c.label} predictor ({getattr(predictor, 'version', '?')})")
        for msg in c.failures:
            print(f"   x {msg}")
        for msg in c.warnings:
            print(f"   ! {msg}")
        failed |= bool(c.failures)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
