"""Walk-forward leave-one-event-out test (reported routes, not observed GPS).

No metric is invented: if the learned model loses to the baseline, that loss is
recorded and surfaced in the dashboard.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from functools import partial
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.optimize import minimize_scalar

from src.config import (
    BACKTEST_FOLD_MAXITER,
    BASELINE_EPSILON_BOUNDS,
    LOGIT_REG,
    RANDOM_WALK_ROLLOUT_SEEDS,
    ROLLOUT_STOP_DISTANCE_M,
)
from src.database import mapdata
from src.models.destinations import candidates, destination_top3_hit
from src.models.graph import MarchGraph
from src.models.labels import TrainingEvent
from src.models.features import reachable_candidates
from src.models.route_model import ChoiceModel, fit
from src.models.types import BacktestResult, BacktestRow


def jaccard(a: list[str], b: list[str]) -> float:
    """Jaccard similarity between two segment-id sequences."""
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb) if sa | sb else 0.0


def step_loglik(
    g: MarchGraph,
    event: TrainingEvent,
    model: ChoiceModel | None,
    history: dict[str, int] | None,
    targets: list,
    net_dist: dict[str, float] | None = None,
) -> float:
    """Mean log-probability of realised turns (uniform if ``model`` is None)."""
    del history
    ll = []
    if net_dist is None:
        net_dist = g.network_distances_to(event.destination)
    for a, b in zip(event.route, event.route[1:]):
        raw = g.next_ids(a)
        choices = raw if model is None else reachable_candidates(raw, net_dist, a)
        if b not in choices or not choices:
            continue
        if model is None:
            p = 1 / len(choices)
        else:
            p = float(
                model.probs(
                    g,
                    a,
                    choices,
                    event.destination,
                    event.context,
                    None,
                    targets,
                    net_dist=net_dist,
                )[choices.index(b)]
            )
        ll.append(math.log(max(1e-12, p)))
    return sum(ll) / len(ll) if ll else float("nan")


def _baseline_prob(epsilon: float, choices: list[str], sp_next: str | None, actual: str) -> float:
    if len(choices) == 1:
        return 1.0
    if sp_next not in choices:
        return 1.0 / len(choices)
    if actual == sp_next:
        return epsilon
    return (1.0 - epsilon) / max(1, len(choices) - 1)


def fit_baseline_epsilon(
    g: MarchGraph,
    events: list[TrainingEvent],
    route_for: Callable[[TrainingEvent], list[str]],
) -> float:
    """MLE for epsilon in an epsilon-greedy shortest-path policy."""

    def neg_ll(epsilon: float) -> float:
        total = 0.0
        for event in events:
            route = route_for(event)
            pathnext = dict(zip(route, route[1:]))
            for a, b in zip(event.route, event.route[1:]):
                choices = g.next_ids(a)
                if b not in choices or not choices:
                    continue
                p = _baseline_prob(epsilon, choices, pathnext.get(a), b)
                total += math.log(max(1e-12, p))
        return -total

    if not events:
        return 0.9
    result = minimize_scalar(
        neg_ll, bounds=BASELINE_EPSILON_BOUNDS, method="bounded", options={"xatol": 1e-4}
    )
    return float(result.x) if result.success else 0.9


def baseline_ll(
    g: MarchGraph,
    event: TrainingEvent,
    route: list[str],
    epsilon: float,
) -> float:
    """Mean log-likelihood under a fitted epsilon-smoothed shortest-path policy."""
    pathnext = dict(zip(route, route[1:]))
    ll = []
    for a, b in zip(event.route, event.route[1:]):
        choices = g.next_ids(a)
        if b not in choices or not choices:
            continue
        p = _baseline_prob(epsilon, choices, pathnext.get(a), b)
        ll.append(math.log(max(1e-12, p)))
    return sum(ll) / len(ll) if ll else float("nan")


def rollout_path(
    g: MarchGraph,
    start_seg: str,
    chosen_end: tuple[float, float],
    pick: Callable[[str, list[str]], str],
    max_steps: int,
    net_dist: dict[str, float] | None = None,
) -> list[str]:
    """Rollout without a no-revisit constraint (matches the likelihood)."""
    if not start_seg or start_seg not in g.segments:
        return []
    if net_dist is None:
        net_dist = g.network_distances_to(chosen_end)
    cur = start_seg
    path = [cur]
    for _ in range(max_steps):
        if mapdata.distance_m(g.segments[cur].path[-1], chosen_end) < ROLLOUT_STOP_DISTANCE_M:
            break
        options = reachable_candidates(g.next_ids(cur), net_dist, cur)
        if not options:
            break
        cur = pick(cur, options)
        path.append(cur)
    return path


def _max_steps(event: TrainingEvent) -> int:
    return min(500, max(30, len(event.route) * 2))


def _model_rollout(
    g: MarchGraph,
    event: TrainingEvent,
    model: ChoiceModel,
    chosen_end: tuple[float, float],
    targets: list,
    net_dist: dict[str, float],
) -> list[str]:
    def pick(cur: str, options: list[str]) -> str:
        probs = model.probs(
            g, cur, options, chosen_end, event.context, None, targets, net_dist=net_dist
        )
        return options[int(np.argmax(probs))]

    return rollout_path(g, event.route[0], chosen_end, pick, _max_steps(event), net_dist)


def _pick_uniform(_cur: str, options: list[str], generator: np.random.Generator) -> str:
    return options[int(generator.integers(len(options)))]


def _random_walk_jaccard(
    g: MarchGraph,
    event: TrainingEvent,
    chosen_end: tuple[float, float],
) -> float:
    scores = []
    net_dist = g.network_distances_to(chosen_end)
    for seed in range(RANDOM_WALK_ROLLOUT_SEEDS):
        pick = partial(_pick_uniform, generator=np.random.default_rng(seed))
        path = rollout_path(g, event.route[0], chosen_end, pick, _max_steps(event), net_dist)
        scores.append(jaccard(path, event.route))
    return sum(scores) / len(scores) if scores else float("nan")


def _mean_finite(values: list[float]) -> tuple[float | None, int]:
    valid = [v for v in values if math.isfinite(v)]
    if not valid:
        return None, 0
    return sum(valid) / len(valid), len(valid)


def evaluate(
    g: MarchGraph,
    events: list[TrainingEvent],
    max_events: int | None = None,
    reg: float = LOGIT_REG,
) -> BacktestResult:
    """Walk-forward backtest against shortest-path and random-walk baselines."""
    rows: list[BacktestRow] = []
    actual_routes: dict[str, list[str]] = {}
    chosen_ends: dict[str, tuple[float, float]] = {}
    destination_hits: list[float] = []
    eligible = sorted([e for e in events if len(e.route) >= 2], key=lambda e: e.date)
    if max_events is not None:
        eligible = eligible[:max_events]
    targets_fn = mapdata.cause_targets

    def sp_route_for(train_event: TrainingEvent) -> list[str]:
        prior = [e for e in eligible if e.date < train_event.date]
        ev_dests = candidates(train_event.cause, prior)
        end_pt = ev_dests[0].lonlat if ev_dests else train_event.destination
        return g.route_between(g.segments[train_event.route[0]].path[0], end_pt)

    for event in eligible:
        training = [e for e in eligible if e.date < event.date]
        if len(training) < 2:
            continue
        model = fit(g, training, targets_for=targets_fn, maxiter=BACKTEST_FOLD_MAXITER, reg=reg)
        net_dist = g.network_distances_to(event.destination)
        dests = candidates(event.cause, training)
        chosen_end = dests[0].lonlat if dests else event.destination
        sp_route = g.route_between(g.segments[event.route[0]].path[0], chosen_end)
        epsilon = fit_baseline_epsilon(g, training, sp_route_for)
        targ = targets_fn(event.cause)
        model_path = _model_rollout(g, event, model, chosen_end, targ, net_dist)
        rw_pick = partial(_pick_uniform, generator=np.random.default_rng(0))
        rw_path = rollout_path(g, event.route[0], chosen_end, rw_pick, _max_steps(event), net_dist)
        actual_routes[event.event_id] = list(event.route)
        chosen_ends[event.event_id] = chosen_end
        destination_hits.append(float(destination_top3_hit(event, training)))
        rows.extend(
            [
                BacktestRow(
                    event.event_id,
                    "route_model",
                    step_loglik(g, event, model, None, targ, net_dist),
                    jaccard(model_path, event.route),
                    model_path,
                ),
                BacktestRow(
                    event.event_id,
                    "shortest_path",
                    baseline_ll(g, event, sp_route, epsilon),
                    jaccard(sp_route, event.route),
                    sp_route,
                ),
                BacktestRow(
                    event.event_id,
                    "random_walk",
                    step_loglik(g, event, None, None, [], net_dist),
                    _random_walk_jaccard(g, event, chosen_end),
                    rw_path,
                ),
            ]
        )
    summary: dict[str, dict[str, float | int | None]] = {}
    for name in ("route_model", "shortest_path", "random_walk"):
        selected = [r for r in rows if r.model == name]
        ll_mean, ll_n = _mean_finite([r.mean_log_likelihood for r in selected])
        j_mean, j_n = _mean_finite([r.top1_jaccard for r in selected])
        summary[name] = {
            "mean_log_likelihood": ll_mean,
            "mean_log_likelihood_n": ll_n,
            "top1_jaccard": j_mean,
            "top1_jaccard_n": j_n,
        }
    dest_rate, dest_n = _mean_finite(destination_hits)
    destination_summary = {
        "destination_top3_rate": dest_rate,
        "n_events": float(dest_n),
    }
    n_eval = len({r.event_id for r in rows})
    return BacktestResult(
        rows,
        summary,
        n_eval,
        datetime.now(timezone.utc).isoformat(),
        destination_summary,
        actual_routes=actual_routes or None,
        chosen_ends=chosen_ends or None,
    )


def save_backtest(res: BacktestResult, path: Path):
    """Write ``res`` to ``path`` as JSON for the Streamlit UI."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(res.to_dict(), f, indent=2, allow_nan=False)


def read_backtest(path: Path) -> BacktestResult | None:
    """Load a backtest JSON file; return ``None`` if missing."""
    if not path.exists():
        return None
    data = json.loads(path.read_text())

    def _row_float(v: object) -> float:
        if v is None:
            return float("nan")
        return float(v)

    rows = [
        BacktestRow(
            r["event_id"],
            r["model"],
            _row_float(r["mean_log_likelihood"]),
            _row_float(r["top1_jaccard"]),
            list(r.get("path") or []),
        )
        for r in data["rows"]
    ]
    raw_ends = data.get("chosen_ends") or {}
    chosen_ends = (
        {str(k): (float(v[0]), float(v[1])) for k, v in raw_ends.items()} if raw_ends else None
    )
    actual = data.get("actual_routes")
    return BacktestResult(
        rows,
        data["summary"],
        data["n_events"],
        data["created_at"],
        data.get("destination_summary"),
        actual_routes={str(k): list(v) for k, v in actual.items()} if actual else None,
        chosen_ends=chosen_ends,
    )
