# Protest discovery crawler

**Package:** `src/ingestion/crawler/`  
**CLI:** `lpp-ingest` (or `python -m ingestion` after `pip install -e .`)

## Purpose

The crawler **proposes** candidate London marches for human review. It does **not** feed the route model or DuckDB. Training uses committed files under `src/ingestion/route_research/seed/` built by `python ingest.py`.

Output is a single CSV, default `data/candidates.csv`, with nine fields per row (`ProtestRecord` in `ingestion.crawler.models`).

## Sources

Three `ProtestSource` implementations — same pattern as adding a fourth source: subclass `ProtestSource`, register in `default_sources()` and `build_platform_catalog()`.

| `platform_id` | Class | Seed provenance |
|---|---|---|
| `met_police` | `MetPoliceSource` | Met Newsroom Section 12 conditions |
| `marble_arch_security` | `MarbleArchSecuritySource` | Marble Arch BID security feed |
| `psc` | `PscSource` | Palestine Solidarity Campaign events |

Dropped sources (no seed route value or out of scope): TfL disruptions, OSAC alerts, generic multi-site organiser framework.

## Commands

```bash
lpp-ingest --list-platforms
lpp-ingest --output-dir data
lpp-ingest --platform met_police --met-limit 5
lpp-ingest --organizer-event-days-back 7 --organizer-event-days-ahead 14
```

## Pipeline

`ProtestIngestionPipeline.discover()` calls `fetch_records_safely()` on each source, merges rows, writes CSV via `write_candidates_csv()`.

## Shared helpers

- `ingestion.crawler.client.HttpClient` — polite `requests`, robots.txt, retries
- `ingestion.crawler.sources.organizers.filters` — London protest heuristics (PSC detail pages)
- `ingestion.crawler.sources.organizers.parse_event_page` — PSC HTML field extraction

## Human review gate

Promote selected CSV rows into `seed/events.csv` and `seed/waypoints.csv`. The build path never reads crawler output automatically.
