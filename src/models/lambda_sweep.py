"""Log regularisation sensitivity: LOEO mean log-likelihood vs ``LOGIT_REG``."""

from __future__ import annotations

import json
import logging

from src.config import MODELS_DIR
from src.models.backtest import evaluate
from src.models.graph import build_graph
from src.models.labels import read_events

logger = logging.getLogger(__name__)

LAMBDA_GRID = (0.5, 1.0, 2.0, 4.0, 8.0)
OUT_PATH = MODELS_DIR / "lambda_sensitivity.json"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    graph = build_graph()
    events = read_events(graph)
    curve = []
    for reg in LAMBDA_GRID:
        bt = evaluate(graph, events, reg=reg)
        curve.append(
            {
                "reg": reg,
                "route_model_ll": bt.summary["route_model"]["mean_log_likelihood"],
                "shortest_path_ll": bt.summary["shortest_path"]["mean_log_likelihood"],
                "n_events": bt.n_events,
            }
        )
        logger.info("reg=%s route_model_ll=%s", reg, curve[-1]["route_model_ll"])
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(curve, indent=2), encoding="utf-8")
    logger.info("Wrote %s", OUT_PATH)


if __name__ == "__main__":
    main()
