# Design decisions

This repository implements a focused pipeline: **ingestion → DuckDB → conditional logit training → backtest visualisation**.

## What we deliberately removed

- **Live signal crawling** (`protest_signals`) — never consumed by training.
- **Police / TfL / ACLED context downloads** — no model consumer after scope cut.
- **Grid, shops, and warehouse tables** — only served deleted prediction UI layers.
- **Prediction and decision layers** — inference, turnout, overspill, multi-page Streamlit flows — removed because nothing in the submitted pipeline trains on or validates those outputs.
- **Mock/contract self-test stack** — replaced by `pytest` and training backtests read from `backtest.json`.
- **Fabricated backtest metrics** — chart values now come from `data/models/backtest.json` after `python -m src.models.train`, not hardcoded overrides.

## What remains and why

- **`ingest.py`** — orchestrates route-research steps and loads into DuckDB.
- **`python -m src.models.train`** — leave-one-event-out backtest; metrics persist to `backtest.json`.
- **`app.py`** — single Streamlit page for backtest insights only.
- **Manual geocode review** — coordinates stay in a reviewed cache so unverified points do not enter the training set automatically.

## Geocode and data integrity

Automating geocode approval would have allowed unverified coordinates into training. The pipeline uses `seed-coords` and approved waypoint tables instead.

## Backtest thresholds

Distance checks in backtest (for example 75 m / 250 m cutoffs and random-walk baseline weights) are documented inline in `src/models/backtest.py` rather than in user-facing UI.

## Phase-2 scope cut

Wikipedia pageviews (media salience) and UK calendar flags (bank holidays, Hijri months)
were removed from ingestion: no feature in `src/models/features.py` reads them, and with
65 seed events a calendar dummy has no support to fit. Crowd-capacity columns went the
same way; see [crowd-density-note.md](crowd-density-note.md).

## Lint suppressions

Lint suppressions in `pyproject.toml` are scoped per package and tracked here. They
cover formatting and complexity in `src/models` and `src/database`, which are not yet
at the standard the crawler and route-research packages meet.
