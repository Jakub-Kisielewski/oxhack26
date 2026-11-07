# Ingestion

Two entry points:

- **Protest crawler:** `lpp-ingest` or `python -m ingestion` (after `pip install -e .`)
- **Route research pipeline:** `python ingest.py` from the repo root

## Crawl etiquette

The crawler reads **public** listing and API pages only (Met Police newsroom, OSAC travel alerts, TfL disruptions API, BID security updates, and organiser event listings). Requests use:

- A documented browser-like `User-Agent` so site operators can identify automated access
- `min_interval_sec` throttling between requests (per-source defaults in `ingestion.crawler.constants`)
- `urllib.robotparser` checks before each fetch; disallowed URLs are skipped and logged
- HTTP retries with backoff for transient 429/5xx responses, honouring `Retry-After` when present

Optional credentials (`TFL_APP_ID`, `TFL_APP_KEY`) improve TfL API rate limits. Runs degrade without them where the API allows anonymous access.

Some hosts block the default TLS stack; `HttpClient` may fall back to the system `curl` binary when present (documented in `client.py`).
