# Cleanup pass (local, uncommitted)

Stripped the repo to: **ingestion → DuckDB → conditional logit training → backtest visualisation**.

## Removed

| Area | Why |
|------|-----|
| `src/ingestion/crawler/**` + crawl step | `protest_signals` was never read by training |
| Police / TfL / ACLED downloaders and DB tables | Context only; no model consumer |
| GHSL, export-parquet, geocode review, next-street demo, seed route plot | Optional, demo, or duplicate of seed-coords |
| `build_grid` step and grid/shop/warehouse DB tables | Used only by deleted prediction/UI |
| Entire prediction layer (`predictor`, `inference`, `conditions`, `turnout`, `overspill`, `decisions`, `checks`) | User scope: pipeline ends at training |
| `contract/mock`, `api`, `selftest`, `errors` | UI/mock contract layer |
| Streamlit pages except backtest insights | Shopkeeper, police, maps, route predictor, etc. |
| `train.py` backtest metric override (Jaccard 0.33, top-3 0.75) | Fabricated scores |
| Hardcoded chart numbers in old `model_insights.py` | Replaced with `charts.backtest_charts` + `backtest.json` |
| `docs/IMPLEMENTATION_PLAN.md`, `scripts/enrich_events_csv.py`, `route_research/README.md` | Stale or one-off |
| `route_model.transition_matrix` | No callers |

## Kept / added

- `src/config.py`, `.env.example` — paths, API URLs, training constants
- `ingest.py` — 11 steps (no crawl, police, grid, export-parquet)
- Minimal `app.py` + `model_insights.py` reading real backtest output
- `DEVPOST.md` unchanged

## Flagged (not changed)

- Many magic numbers in `backtest.py` (baseline 0.9/0.1, distance thresholds 75 m / 250 m) — purpose documented in code comments only
- `mapdata.py` still exposes helpers for deleted UI (harmless dead code)
- Full end-to-end ingest not re-run here (needs network + Python 3.12 + time); run locally: `python ingest.py` then `python -m src.models.train`
