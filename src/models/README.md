# Model track (Section 5 of `docs/IMPLEMENTATION_PLAN.md`)

This directory **only** implements the Track A model layer. It does not modify
Phase 0's contract, UI, ingestion or DuckDB database. It uses the shared,
read-only `src.contract.mapdata.cursor()` for data access.

## Train

From the repository root, using the **project's Python 3.12 environment**:

```bash
python -m src.models.train
python -m src.models.checks
python -m src.contract.selftest --predictor real
```

Training writes `data/models/graph.pkl`, `route_model.json`, and `backtest.json`.
To exercise a faster pipeline smoke test while developing, run:

```bash
python -m src.models.train --quick
```

**Quick is not a full backtest**; its five event examples must not be reported
as final validation. Use the command without `--quick` for all eligible
leave-one-event-out folds. After training, `PREDICTOR=auto` selects the real
predictor; `PREDICTOR=mock` forces the existing mock.

## Model files

- `graph.py`: allowed directed street segments and transitions, nearest nodes,
  shortest-route snapping; stored as a pickle for reuse.
- `labels.py`: convert source **planned** itineraries and waypoint coordinates
  to route-choice observations; weight interpolations down to 0.3.
- `features.py`: eleven choice-specific features from the plan.
- `route_model.py`: regularised weighted conditional logit with train-fold-only
  standardisation and historical route counts.
- `destinations.py`: cause-conditioned curated targets and historical endpoints.
- `inference.py`: sparse discounted absorbing-chain expected visits, Yen top-k
  candidate paths and hexagon aggregation.
- `turnout.py`: low-data conditional median and explicit uncertainty.
- `overspill.py`: hand-set crowd-flow and spill scenarios, not supervised labels.
- `decisions.py`: risk queries, warehouse utility, hypothetical officer allocation.
- `backtest.py`: honest leave-one-event-out metrics vs two baselines.
- `predictor.py`: concrete frozen-API implementation.
- `train.py`: entry point; `checks.py`: runnable model checks.

## Caveats

1. Historical routes are **announced** itineraries; the connections between
   geocoded waypoints are **algorithmically interpolated shortest paths**, not
   GPS traces. Comparisons to them evaluate reproduction of published plans.
2. Few labelled events are available; real-world street probabilities are not
   calibrated. Expected visits from the absorbing-chain solve are clipped to
   1, as specified by the contract. A small 1% per-step termination hazard is
   used to avoid singular systems on truncated OSM networks.
3. Overspill, officer effects and time windows are **illustrative scenarios**,
   not observed or causally validated effects. Don't use them for deployment
   or other consequential real-world decisions without further validation.
4. Training may take several minutes. Python package and runtime compatibility
   follow the repository's existing `requirements.txt`.
5. The benchmark results are **not manufactured**. A model that loses to the
   shortest-path baseline is still reported as losing.
