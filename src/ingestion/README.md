# Ingestion

Tier 1 crawlers live under `src/ingestion/crawler/` (Met Police, OSAC, TfL, Marble Arch, organizer sites).

## Run

From repo root:

```bash
source .venv/bin/activate
pip install -r requirements.txt
python -m src.ingestion
```

Outputs: `data/runs/{run_id}/{platform_id}/records.json` plus merged files under `data/runs/{run_id}/_all/`.
