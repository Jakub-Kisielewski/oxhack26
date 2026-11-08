"""Pure helpers for ordering backtest models and formatting metric captions."""

from __future__ import annotations

MODEL_LABELS = {
    "route_model": "Route model",
    "shortest_path": "Shortest path",
    "random_walk": "Random walk",
}
METRICS = {
    "mean_log_likelihood": (
        "Log-likelihood per step",
        "Higher is better: probability assigned to the true route, step by step.",
        ".2f",
    ),
    "top1_jaccard": (
        "Top route overlap",
        "Share of the true route's streets that the top predicted route uses.",
        ".0%",
    ),
}


def model_order(summary: dict[str, dict[str, float]]) -> list[str]:
    """Known models first, in display order, then any others as they appear."""
    known = tuple(MODEL_LABELS)
    return [m for m in known if m in summary] + [m for m in summary if m not in known]


def event_counts(summary: dict[str, dict[str, float]], metric: str) -> dict[str, int]:
    """Events actually scored per model for one metric; may differ between models."""
    n_key = f"{metric}_n"
    return {m: int(summary[m][n_key]) for m in summary if n_key in summary.get(m, {})}


def metric_format(metric: str) -> str:
    """Altair axis / tooltip format string for a summary metric key."""
    return METRICS[metric][2]


def event_count_caption(
    help_text: str,
    summary: dict[str, dict[str, float]],
    metric: str,
    models: list[str],
) -> str:
    """Append honest per-model event counts when ``_n`` keys are present."""
    n_key = f"{metric}_n"
    n_by_model = {
        MODEL_LABELS.get(m, m): summary[m][n_key] for m in models if n_key in summary.get(m, {})
    }
    counts = set(n_by_model.values())
    if len(counts) == 1:
        return f"{help_text} (n={int(counts.pop())} events, all models.)"
    if counts:
        detail = ", ".join(f"{label} {int(n)}" for label, n in n_by_model.items())
        return f"{help_text} (events scored: {detail}.)"
    return help_text
