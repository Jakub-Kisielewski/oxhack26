"""Run from repository root: python -m src.models.train [--force-graph] [--quick]."""

from __future__ import annotations

import argparse
import logging
import math

from src.config import (
    BACKTEST_PATH,
    CLUSTER_BOOTSTRAP_SAMPLES,
    DB_PATH,
    GRAPH_PATH,
    QUICK_BACKTEST_EVENTS,
    ROUTE_MODEL_PATH,
)
from src.database import mapdata
from src.models.backtest import evaluate, save_backtest
from src.models.graph import build_graph
from src.models.labels import read_events
from src.models.route_model import cluster_bootstrap, fit

logger = logging.getLogger(__name__)


def main():
    """Build the graph, fit the logit, run backtest, and write artefacts under ``data/models/``."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--force-graph", action="store_true")
    parser.add_argument(
        "--quick", action="store_true", help="Backtest only five events (smoke test)"
    )
    parser.add_argument(
        "--no-bootstrap",
        action="store_true",
        help="Skip cluster bootstrap (faster dev runs)",
    )
    args = parser.parse_args()
    if not DB_PATH.is_file():
        msg = (
            f"Database not found: {DB_PATH}\n"
            "Run ingestion first:  python ingest.py\n"
            "Or load DuckDB only:  python ingest.py --only database"
        )
        raise SystemExit(msg)
    graph = build_graph(force=args.force_graph)
    logger.info("Graph: %s directed segments", len(graph.segments))
    events = read_events(graph)
    n_obs = sum(max(0, len(x.route) - 1) for x in events)
    logger.info("Training events: %s observations: %s", len(events), n_obs)
    if len(events) < 2:
        raise SystemExit("Insufficient labelled routes: check DB waypoints and connectivity.")
    model = fit(graph, events, targets_for=mapdata.cause_targets)
    if not model.fitted:
        logger.error(
            "Conditional logit did not converge (loss=%s). Not writing %s.",
            model.stats.get("loss"),
            ROUTE_MODEL_PATH,
        )
        raise SystemExit(1)
    if not args.no_bootstrap:
        intervals = cluster_bootstrap(
            graph,
            events,
            mapdata.cause_targets,
            n_samples=CLUSTER_BOOTSTRAP_SAMPLES,
        )
        if intervals:
            model.stats["bootstrap_5_50_95"] = intervals
    model.to_json(ROUTE_MODEL_PATH)
    logger.info("Conditional logit fitted: %s", model.stats)
    backtest = evaluate(graph, events, max_events=QUICK_BACKTEST_EVENTS if args.quick else None)
    save_backtest(backtest, BACKTEST_PATH)
    logger.info("Backtest events: %s", backtest.n_events)
    for name, metric in backtest.summary.items():
        logger.info("%s %s", name, metric)
    if backtest.destination_summary:
        logger.info("destination_model %s", backtest.destination_summary)
    logger.info("Saved: %s %s %s", GRAPH_PATH, ROUTE_MODEL_PATH, BACKTEST_PATH)
    rm_ll = backtest.summary["route_model"]["mean_log_likelihood"]
    sp_ll = backtest.summary["shortest_path"]["mean_log_likelihood"]
    if not (
        rm_ll is not None
        and sp_ll is not None
        and math.isfinite(rm_ll)
        and math.isfinite(sp_ll)
        and rm_ll > sp_ll
    ):
        logger.warning(
            "Route model has NOT beaten the shortest-path baseline. Do not claim it has."
        )


if __name__ == "__main__":
    main()
