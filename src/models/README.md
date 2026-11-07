# Route choice model

Train from the repository root (Python 3.12):

```bash
python ingest.py
python -m src.models.train
streamlit run app.py
```

Writes `data/models/graph.pkl`, `route_model.json`, and `backtest.json`.

```bash
python -m src.models.train --quick   # smoke test on five events only
```

Historical routes are **announced** itineraries; connections between geocoded waypoints are **shortest-path interpolations**, not GPS traces.
