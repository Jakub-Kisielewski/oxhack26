# London Protest Predictor

[![tests](https://github.com/crislu05/london-protest-predictor/actions/workflows/test.yml/badge.svg)](https://github.com/crislu05/london-protest-predictor/actions/workflows/test.yml)

## HOW TO SETUP

Run these steps in order from the repo root.

| Step | Command | How often |
|---|---|---|
| 1. Python environment | `python3.12 -m venv .venv`, activate, `pip install -e ".[dev]"` | once |
| 2. Optional credentials | none required for the default build | — |
| 3. All ingestion + database | `python ingest.py` (with the app closed) | whenever you want fresh data |
| 4. Train the route model | `python -m src.models.train` | after each ingestion |
| 5. Tests | `pytest -q` | before pushing |
| 6. App | `streamlit run app.py` | |

Quick version, from a fresh clone:

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python ingest.py                     # data -> data/protest.duckdb
python -m src.models.train           # model -> data/models/
pytest -q
streamlit run app.py
```

### 1. Python environment
The repo pins Python 3.12 (`.python-version`).

```bash
python3.12 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

DuckDB's spatial extension comes with `pip install` (the `duckdb-extension-spatial` package) and is installed automatically the first time the database is opened. **Intel Macs** have no wheel for it: see [Spatial extension on Intel Macs](#spatial-extension-on-intel-macs).

### 2. Ingestion: one command
```bash
python ingest.py
```

This runs every step in dependency order:

| Step | What it does | Output |
|---|---|---|
| `boundary` | Zones 1-2 polygon from TfL station zones | `data/route_research/raw/boundary/` |
| `osm` | OSM walk network + main-road network inside the boundary | `data/route_research/raw/osm/` |
| `landmarks` | Protest targets, squares/parks (capacity), shops, warehouses | `data/route_research/raw/landmarks/` |
| `seed-coords` | Waypoint coordinates from the reviewed geocode cache | `data/route_research/coordinate_review.csv` |
| `normalize` | Street segments, route labels, context tables | `data/route_research/normalised/` |
| `edge-features` | Per street: usable width, main-network betweenness, junction degree, legal-zone and Royal Park flags | `data/route_research/normalised/edge_features.csv` |
| `weather` | Hourly Open-Meteo precipitation around each event date | `data/route_research/raw/weather/` |
| `event-context` | Per-event cause, 4 h precipitation, daylight after start (model context) | `data/route_research/normalised/event_context.csv` |
| `cause-targets` | Where each cause marches to (`seed/cause_targets.csv`), embassies located from the data, checked against the seed routes | `data/route_research/normalised/cause_targets.csv` |
| `database` | Loads all of the above into DuckDB (see [Database](#database)) | `data/protest.duckdb` |

Useful options:

```bash
python ingest.py --list                       # steps and their dependencies
python ingest.py --only weather event-context # run just these
python ingest.py --refresh                    # redo cached steps (boundary, osm, landmarks, edge-features)
python ingest.py --refresh osm                # re-download just one of them
```

- The first run is slow: the OSM network and landmarks for zones 1-2 take several minutes each. Later runs skip downloads whose files already exist.
- All 65 seed routes are always used for training.
- Landmarks retry busy Overpass servers with backoff across three mirrors. If a layer still fails, re-run `python ingest.py --only landmarks` and only the missing layers are fetched.
- If a step fails, the steps that depend on it are skipped, the rest still run, and a summary is printed at the end. Re-run a failed step with `--only <step>`.
- Every step can also be run on its own, see `src/ingestion/route_research/README.md`.

### 3. Train the route model
```bash
python -m src.models.train           # full leave-one-event-out backtest
python -m src.models.train --quick   # 5-event smoke test while developing (don't report its numbers)
```
Training reads `data/protest.duckdb` read-only and writes `data/models/graph.pkl`, `route_model.json` and
`backtest.json`. It prints the backtest against the shortest-path and random-walk baselines, and warns if the
route model doesn't beat shortest path. Re-train after every ingestion. Add `--force-graph` to rebuild the
street graph. See `src/models/README.md`.

### 4. Run tests
```bash
pytest -q
pytest --cov=src --cov-report=term-missing   # optional local coverage
```
The same suite runs in CI on every push and pull request.

### 5. Run the app
```bash
streamlit run app.py
```
- The app shows **leave-one-event-out backtest** charts from `data/models/backtest.json` after training.
- Close the app before re-running `python ingest.py`: it holds the database open.

## Licence

Released under the [MIT License](LICENSE).

### Database

`data/protest.duckdb` is the single store that the app, the models and notebooks read from, so none of them need to know file paths or formats. It's rebuilt from the ingestion files by the `database` step (or on its own with `python -m src.database.load`). **Close the Streamlit app first:** it holds the file open and the loader will say so.

| Group | Tables |
|---|---|
| Map | `boundary`, `segments` (walk network with `n_published_route_examples` and `edge_features`: `width_m`, `betweenness_main`, `to_degree`, `is_main`, `in_*_zone`), `targets` (embassies have an ISO `country` code), `legal_zones` (no-entry sites, Parliament Square controlled area, Royal Parks from seed + OSM) |
| Events and routes | `events`, `waypoints`, `route_segments` (ordered `segment_id`s per `event_id`), `event_context`, `cause_targets` |
| Bookkeeping | `load_log` (rows and load time per table) |

Geometry columns are lon/lat (EPSG:4326): `geom` on point and street tables, `geometry` on landmark layers. Use the `meters(a, b)` macro for distances; it works for points, lines and polygons. Don't use `ST_Distance_Sphere` directly: it expects lat/lon axis order.

```python
from src.database.db import get_connection

con = get_connection(read_only=True)

# Nearest street segment to a point
con.execute(
    """SELECT segment_id, street_name, meters(geom, ST_Point(?, ?)) AS m
               FROM segments ORDER BY m LIMIT 1""",
    [lon, lat],
).df()
```

### Spatial extension on Intel Macs
`pip` skips `duckdb-extension-spatial` on Intel Macs because there is no wheel, so install the extension once by hand. Extensions are tied to the exact DuckDB version, so keep `duckdb==1.5.5`.

```bash
curl -fL -C - -o spatial.duckdb_extension.gz \
  https://extensions.duckdb.org/v1.5.5/osx_amd64/spatial.duckdb_extension.gz
gunzip spatial.duckdb_extension.gz
python -c "import duckdb; duckdb.connect().execute(\"INSTALL './spatial.duckdb_extension'\"); print('ok')"
```
DuckDB downloads extensions silently with no progress bar, which is why this is done with curl (`-C -` resumes an interrupted download). Once it prints `ok` the extension is cached in `~/.duckdb/extensions/` and you can delete the file.

## Discovery crawler URLs (optional, not part of `ingest.py`)

Used by `lpp-ingest` only — see [Protest discovery](#protest-discovery-crawler):

- https://news.met.police.uk/latest_news/tag/central-london
- https://marble-arch.london/security-updates/
- https://palestinecampaign.org/events/






## ADDITIONAL DATA SOURCES — ROUTE RESEARCH INGESTION

The `src/ingestion/route_research/` pipeline downloads additional geographic, historical and contextual data to support London protest-route modelling.

### Data APIs and download services

- **OpenStreetMap / OSMnx — London pedestrian street network:** https://www.openstreetmap.org/  
  Documentation: https://osmnx.readthedocs.io/en/stable/

- **OpenStreetMap Nominatim — Geocoding historical protest waypoints:** https://nominatim.openstreetmap.org/  
  Usage policy: https://operations.osmfoundation.org/policies/nominatim/

- **Copernicus GHSL — Satellite-derived urban population and built-up-area datasets:** https://human-settlement.emergency.copernicus.eu/downloadWizard.php

- **TfL Unified API — Station fare zones (for the Zones 1-2 boundary):** https://api.tfl.gov.uk/StopPoint/Mode/tube,dlr,overground,elizabeth-line

- **OpenStreetMap Overpass (via OSMnx) — Embassies, government buildings, landmarks, squares, parks, shops, warehouses:** https://overpass-api.de/

- **Open-Meteo — Historical and forecast hourly precipitation (no key):** https://open-meteo.com/en/docs/historical-weather-api

**Out of scope after the phase-2 cut:** Wikipedia pageviews (media salience) and UK bank-holiday / Hijri calendar flags were removed from ingestion because nothing in the route model reads them; see [docs/phase2.md](docs/phase2.md).

These sources provide street geometry, protest-event locations, transport conditions and urban characteristics. They do not directly provide historical sequences of crowd movement.

## HISTORICAL PROTEST ROUTE SEED DATA — ORIGINAL SOURCES

The `route_research/seed/` directory contains 65 historical march and procession records, including 54 classified as protests, and 285 ordered waypoints.

The dataset was manually compiled from published route descriptions, police announcements, event organisers, security updates and reporting.

### 1. Metropolitan Police announcements (13 records)

- [Met Police — October 2023 demonstration route](https://news.met.police.uk/news/update-met-response-to-terror-attacks-in-israel-and-ongoing-military-action-in-gaza-474080)
- [Met Police — October 2024 policing operation](https://news.met.police.uk/news/policing-operation-for-weekend-ahead-of-october-7th-anniversary-488935)
- [Met Police — October 2024 protest plans](https://news.met.police.uk/news/met-sets-out-policing-plans-ahead-of-saturday-protests-489744)
- [Met Police — October 2024 weekend events](https://news.met.police.uk/news/met-sets-out-policing-plan-ahead-of-a-busy-weekend-of-events-in-london-489967)
- [Met Police — 2025 weekend protests](https://news.met.police.uk/news/met-ready-for-busy-weekend-of-protests-and-other-events-495139)
- [Met Police — 2025 weekend policing plans](https://news.met.police.uk/news/met-sets-out-policing-plans-ahead-of-weekend-protests-495387)
- [Met Police — October 2025 protest conditions](https://news.met.police.uk/news/conditions-for-protest-on-11th-october-502033)
- [Met Police — July 2026 national march](https://news.met.police.uk/news/conditions-for-national-march-for-palestine-on-saturday-18-july-511412)
- [Met Police — October 2026 student march](https://news.met.police.uk/news/conditions-imposed-on-student-march-on-wednesday-7-october-513621)
- [Met Police — October 2026 policing briefing](https://news.met.police.uk/news/dac-james-harmans-statement-at-media-briefing-ahead-of-public-order-events-513525)
- [Met Police — October 2026 Palestine coalition protest](https://news.met.police.uk/news/met-announces-conditions-for-palestine-coalition-protest-513794)

Additional official Met source:

- [Met Police — September 2025 procession information](https://www.met.police.uk/foi-ai/metropolitan-police/disclosure-2025/september-2025/mps-urges-muslim-londoners-change-their-plans/)

### 2. Marble Arch London — Security and operations updates (29 records)

- [Marble Arch London — Historical security and march updates](https://marble-arch.london/security-updates/)

This archive provides event dates, proposed routes, assembly locations and sometimes estimated attendance. Multiple seed records originate from this archive.

### 3. Palestine Solidarity Campaign (12 records)

- [November 2023 march statement](https://palestinecampaign.org/statement-on-the-march-on-saturday-11-november/)
- [National March for Palestine — Stop the Genocide](https://palestinecampaign.org/events/national-march-for-palestine-stop-the-genocide/)
- [National Demonstration — Ceasefire Now](https://palestinecampaign.org/events/national-demonstration-ceasefire-now-stop-the-genocide-in-gaza-2/)
- [Nakba anniversary coalition announcement](https://palestinecampaign.org/palestine-coalition-joins-the-global-day-of-action-for-gaza-on-76th-nakba-anniversary/)
- [National March for Gaza](https://palestinecampaign.org/events/national-march-for-gaza-end-the-genocide-stop-arming-israel/)
- [Nakba 77 National Demonstration](https://palestinecampaign.org/events/national-demonstration-nakba-77/)
- [June 2025 National Demonstration](https://palestinecampaign.org/events/national-demonstration-21-june-25/)
- [September National March](https://palestinecampaign.org/events/national-march-for-palestine-stop-starving-gaza-6-sept/)
- [National March — Stop Starving Gaza](https://palestinecampaign.org/events/national-march-for-palestine-stop-starving-gaza-stop-arming-israel/)
- [30 November National Demonstration](https://palestinecampaign.org/events/30-november-national-demonstration-for-palestine/)
- [Nakba 78 March](https://palestinecampaign.org/events/nakba-78-march-for-palestine-2/)
- [Day of Action — Iran, Lebanon and Palestine](https://palestinecampaign.org/events/day-of-action-stop-bombing-iran-hands-off-lebanon-free-palestine/)

### 4. Other organisers, official notices and reporting (11 records)

- [Trades Union Congress — March route](https://www.tuc.org.uk/march-route)
- [PCS Union — Palestine march information](https://www.pcs.org.uk/print/pdf/node/11861)
- [Restore Nature Now — March route](https://www.restorenaturenow.com/the-march)
- [Stop Trump Coalition — Protest information](https://stoptrump.org.uk/protest/)
- [Together Alliance — Route and accessibility information](https://www.togetheralliance.org.uk/access)
- [London Trans+ Pride — Accessibility and route](https://londontranspride.org/access)
- [Westminster Council — Pride in London 2026 information](https://www.westminster.gov.uk/pride-london-2026-information-businesses-and-residents)
- [ITV London — February 2024 Palestine march reporting](https://www.itv.com/news/london/2024-02-02/police-increase-patrols-for-palestine-solidarity-campaign-in-london)
- [London News Online — January 2024 Gaza march reporting](https://londonnewsonline.org.uk/news/thousands-of-protesters-turn-out-in-support-of-gaza/)

### Data provenance and limitations

Every historical event in `seed/events.csv` includes a `source_url`, `evidence_type` and route description.

The `seed/waypoints.csv` file contains the corresponding ordered locations. The `event_id` field connects each waypoint to its event.

Historical routes are primarily **published or announced procession itineraries**, not GPS measurements of actual protest crowds. Some routes are incomplete, and connecting waypoints using shortest paths produces inferred geometry, not directly observed movements.

The seed dataset is a versioned research snapshot. The current ingestion scripts download complementary geographic and event data, but do not automatically scrape new historical route announcements.

Sources may change or become unavailable over time. Their reuse and redistribution must comply with the respective source terms.




## Protest discovery (crawler)

The crawler is **not** a step in `python ingest.py`. It proposes new marches for human review:

```bash
pip install -e ".[dev]"
lpp-ingest --output-dir data    # writes data/candidates.csv
lpp-ingest --list-platforms     # met_police, marble_arch_security, psc
```

### Development (optional)

```bash
pre-commit install   # runs ruff check/format before each commit
```

Promote selected rows into `src/ingestion/route_research/seed/events.csv` and `waypoints.csv`, then run the normal build.
