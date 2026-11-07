# Ingestion

Two entry points:

- **Discovery crawler:** `lpp-ingest` or `python -m ingestion` (after `pip install -e .`) writes `data/candidates.csv`
- **Route research pipeline:** `python ingest.py` from the repo root (deterministic build from committed seed files)

## Human review gate

The crawler **proposes** candidate marches (date, title, form-up, route text, turnout estimate, source URL). A human promotes approved rows into `src/ingestion/route_research/seed/`. The route build (`ingest.py`) **never** reads crawler output directly; it only reads those committed seed CSVs.

## Crawl etiquette

Discovery reads **public** Met Police conditions notices, the Marble Arch London BID security feed, and PSC organiser listings. Requests use:

- An identifying `User-Agent` (`DISCOVERY_USER_AGENT` in `ingestion.crawler.constants`)
- `min_interval_sec` throttling between requests
- `urllib.robotparser` checks before each fetch; disallowed URLs are skipped and logged
- HTTP retries with backoff for transient 429/5xx responses, honouring `Retry-After` when present

## Discovery output

```bash
lpp-ingest --output-dir data
# -> data/candidates.csv
lpp-ingest --list-platforms
```

Columns match `ProtestRecord` in `ingestion.crawler.models` (nine fields).
