"""Weighted conditional logit on directed street-segment choices, trained by L-BFGS-B."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.optimize import minimize
from scipy.special import softmax

from src.config import BACKTEST_FOLD_MAXITER, LOGIT_MAXITER, LOGIT_REG
from src.models.features import NAMES, feature_vector, reachable_candidates
from src.models.graph import MarchGraph
from src.models.labels import TrainingEvent


# Shrink toward small, interpretable prior effects on standardised features.
PRIOR = np.array([0.5, 0.1, 0.1, -0.5, 0.1, -0.3, 0.15, 0.2, -0.05], dtype=float)


@dataclass
class ChoiceModel:
    """Fitted conditional logit weights with per-feature standardisation from training."""

    theta: list[float] = field(default_factory=lambda: list(PRIOR))
    mean: list[float] = field(default_factory=lambda: [0.0] * len(NAMES))
    std: list[float] = field(default_factory=lambda: [1.0] * len(NAMES))
    features: tuple[str, ...] = NAMES
    fitted: bool = False
    stats: dict = field(default_factory=dict)

    def to_json(self, path: Path):
        """Serialise model parameters to JSON at ``path``."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(
                dict(
                    theta=self.theta,
                    mean=self.mean,
                    std=self.std,
                    features=self.features,
                    fitted=bool(self.fitted),
                    stats=self.stats,
                ),
                f,
                indent=2,
            )

    @classmethod
    def from_json(cls, path: Path):
        """Load a model from JSON, padding newer features with ``PRIOR`` when needed."""
        with open(path) as f:
            d = json.load(f)
        saved = list(d["features"])
        if saved != list(NAMES)[: len(saved)]:
            raise ValueError("Feature version mismatch; retrain model")
        n = len(saved)
        return cls(
            list(d["theta"]) + PRIOR[n:].tolist(),
            list(d["mean"]) + [0.0] * (len(NAMES) - n),
            list(d["std"]) + [1.0] * (len(NAMES) - n),
            NAMES,
            d["fitted"],
            {**d["stats"], "prior_only": list(NAMES[n:])},
        )

    def probs(
        self,
        g: MarchGraph,
        current: str,
        candidates: list[str],
        destination: tuple[float, float],
        context: dict | None = None,
        history: dict | None = None,
        targets: list | None = None,
        net_dist: dict[str, float] | None = None,
    ):
        """Softmax turn probabilities over ``candidates`` at junction ``current``."""
        if not candidates:
            return np.array([])
        if net_dist is not None:
            candidates = reachable_candidates(candidates, net_dist, current)
        if not candidates:
            return np.array([])
        X = np.stack(
            [
                feature_vector(
                    g, current, b, destination, context, history, targets, net_dist=net_dist
                )
                for b in candidates
            ]
        )
        x = (X - np.asarray(self.mean)) / np.maximum(np.asarray(self.std), 1e-6)
        return softmax(np.clip(x @ np.asarray(self.theta), -100, 100))


def fit(
    g: MarchGraph,
    events: list[TrainingEvent],
    targets_for=None,
    reg: float = LOGIT_REG,
    maxiter: int = LOGIT_MAXITER,
) -> ChoiceModel:
    """Fit L-BFGS-B conditional logit on junction choices from ``events``."""
    arrays = []
    indices = []
    weights = []
    n_events = 0
    for event in events:
        targ = targets_for(event.cause) if targets_for else []
        net_dist = g.network_distances_to(event.destination)
        n = 0
        for k, (current, chosen) in enumerate(zip(event.route, event.route[1:])):
            options = reachable_candidates(g.next_ids(current), net_dist, current)
            if len(options) < 2 or chosen not in options:
                continue
            X = np.stack(
                [
                    feature_vector(
                        g,
                        current,
                        b,
                        event.destination,
                        event.context,
                        None,
                        targ,
                        net_dist=net_dist,
                    )
                    for b in options
                ]
            )
            if not np.isfinite(X).all():
                bad = [name for i, name in enumerate(NAMES) if not np.isfinite(X[:, i]).all()]
                msg = f"non-finite features at junction {current!r}: {bad}"
                raise ValueError(msg)
            arrays.append(X)
            indices.append(options.index(chosen))
            weights.append(event.weight[k + 1])
            n += 1
        n_events += bool(n)
    if not arrays:
        return ChoiceModel(stats={"n_events": 0, "n_choices": 0})
    sizes = [len(a) for a in arrays]
    X = np.concatenate(arrays)
    means = X.mean(axis=0)
    std = X.std(axis=0)
    std[std < 1e-6] = 1.0
    X = (X - means) / std
    offsets = np.cumsum([0] + sizes)
    prior = PRIOR.copy()
    chosen = np.asarray(indices)
    w = np.asarray(weights, dtype=float)
    chosen_idx = offsets[:-1] + chosen
    repeated_weights = np.repeat(w, sizes)
    weighted_chosen_X = w @ X[chosen_idx]

    def loss_grad(theta):
        logits = X @ theta
        maxima = np.maximum.reduceat(logits, offsets[:-1])
        expvalues = np.exp(logits - np.repeat(maxima, sizes))
        totals = np.add.reduceat(expvalues, offsets[:-1])
        probs = expvalues / np.repeat(totals, sizes)
        loss = np.dot(w, maxima + np.log(totals) - logits[chosen_idx])
        grad = X.T @ (probs * repeated_weights) - weighted_chosen_X
        deviation = theta - prior
        return float(loss + reg / 2 * (deviation @ deviation)), grad + reg * deviation

    result = minimize(
        loss_grad, prior, method="L-BFGS-B", jac=True, options={"maxiter": maxiter, "ftol": 1e-7}
    )
    loss = float(result.fun)
    fitted = bool(result.success and np.isfinite(loss))
    moved = np.abs(result.x - prior) > 1e-6
    prior_only = (
        [] if not fitted else [name for name, ok in zip(NAMES, moved, strict=True) if not ok]
    )
    return ChoiceModel(
        result.x.tolist(),
        means.tolist(),
        std.tolist(),
        NAMES,
        fitted,
        {
            "n_events": n_events,
            "n_choices": len(arrays),
            "weighted_choices": float(w.sum()),
            "loss": loss,
            "converged": bool(result.success),
            "prior_only": prior_only,
            "reg": reg,
        },
    )


def cluster_bootstrap(
    g: MarchGraph,
    events: list[TrainingEvent],
    targets_for,
    n_samples: int = 100,
    reg: float = LOGIT_REG,
) -> dict[str, list[float]]:
    """Resample events with replacement, refit, and return coefficient percentiles."""
    if len(events) < 2:
        return {}
    thetas: list[np.ndarray] = []
    rng = np.random.default_rng(42)
    for _ in range(n_samples):
        idx = rng.integers(0, len(events), len(events))
        sample = [events[int(i)] for i in idx]
        if len(sample) < 2:
            continue
        model = fit(g, sample, targets_for=targets_for, reg=reg, maxiter=BACKTEST_FOLD_MAXITER)
        if model.fitted:
            thetas.append(np.asarray(model.theta))
    if not thetas:
        return {}
    stack = np.vstack(thetas)
    return {
        name: [
            float(np.percentile(stack[:, j], 5)),
            float(np.percentile(stack[:, j], 50)),
            float(np.percentile(stack[:, j], 95)),
        ]
        for j, name in enumerate(NAMES)
    }
