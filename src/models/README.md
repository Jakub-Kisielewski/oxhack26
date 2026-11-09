# Route choice model

Train from the repository root (Python 3.12):

```bash
python ingest.py
python -m src.models.train
streamlit run app.py
```

Writes `data/models/graph.pkl`, `route_model.json`, and `backtest.json`. Training exits with code 1 if the optimiser does not converge.

```bash
python -m src.models.train --quick          # backtest on five events only
python -m src.models.train --no-bootstrap   # skip coefficient resampling
```

Historical routes are **announced** itineraries; connections between geocoded waypoints are **shortest-path interpolations**, not GPS traces.

## Eight features and `prior_only`

`route_model.json` lists features whose fitted weight stayed at the declared `PRIOR` (within `1e-6`), usually because the data never vary within choice sets:

| Feature | Typical status |
|---------|----------------|
| `progress`, `turn`, `target_pull`, `log_width`, `name_continuity`, `log_length` | Usually learned when labels support them |
| `is_main`, `is_bridge` | Often **prior-only** — few junctions offer a main-road or bridge alternative |

No-entry segments are dropped at graph build time (`forbidden`). Restricted-activity zones appear on the route map for context only — they are not logit features.
