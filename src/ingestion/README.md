# Ingestion (Tier 1)

Crawlers for Met Police newsroom, OSAC embassy alerts, and TfL road disruptions.

## Run

From repo root:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run_test_pipeline.py
```

Outputs: `data/runs/{run_id}/{met_police,osac,tfl_road_disruption}/records.json`
