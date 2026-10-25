# London Protest Predictor

## HOW TO SETUP

Run these steps in order from the repo root.

| Step | Command | How often |
|---|---|---|
| 1. Python environment | `python3.12 -m venv .venv`, activate, `pip install -r requirements.txt` | once |
| 2. Optional credentials | `export ACLED_EMAIL=... ACLED_PASSWORD=... TFL_APP_KEY=...` | if you want those sources |
| 3. All ingestion + database | `python ingest.py` (with the app closed) | whenever you want fresh data |
| 4. App | `streamlit run app.py` | |

### 1. Python environment
The repo pins Python 3.12 (`.python-version`).

```bash
python3.12 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

DuckDB's spatial extension comes with `pip install` (the `duckdb-extension-spatial` package) and is installed automatically the first time the database is opened. **Intel Macs** have no wheel for it: see [Spatial extension on Intel Macs](#spatial-extension-on-intel-macs).

### 2. Optional credentials
```bash
export ACLED_EMAIL='...' ACLED_PASSWORD='...'   # ACLED step is skipped without these (or use --acled-file)
export TFL_APP_KEY='...'                          # optional, raises TfL rate limits
```
Never commit credentials.

### 3. Ingestion: one command
```bash
python ingest.py
```

This runs every step in dependency order:

| Step | What it does | Output |
|---|---|---|
| `boundary` | Zones 1-2 polygon from TfL station zones | `data/route_research/raw/boundary/` |
| `osm` | OSM walk network + main-road network inside the boundary | `data/route_research/raw/osm/` |
| `landmarks` | Protest targets, squares/parks (capacity), shops, warehouses, embassies with country | `data/route_research/raw/landmarks/` |
| `police` | Public-order crimes for the months of the seed events | `data/route_research/raw/police/` |
| `tfl` | Snapshot of current TfL road disruptions and tube status | `data/route_research/raw/tfl/` |
| `acled` | ACLED London protest events (only with credentials) | `data/route_research/raw/acled/` |
| `seed-coords` | Waypoint coordinates from the reviewed geocode cache | `data/route_research/coordinate_review.csv` |
| `normalize` | Street segments, route labels, context tables | `data/route_research/normalised/` |
| `export-parquet` | Parquet/GeoParquet copies of the normalised tables | `data/route_research/normalised/parquet/` |
| `weather` | Hourly Open-Meteo weather around each event date | `data/route_research/raw/weather/` |
| `pageviews` | Daily Wikipedia views per protest cause | `data/route_research/raw/pageviews/` |
| `event-context` | Per-event calendar, daylight, weather, media salience features | `data/route_research/normalised/event_context.csv` |
| `crawl` | Tier 1 crawlers (Met Police, OSAC, TfL, Marble Arch, organiser sites) | `data/runs/<run_id>/` |
| `database` | Loads all of the above into DuckDB (see [Database](#database)) | `data/protest.duckdb` |

Useful options:

```bash
python ingest.py --list                       # steps and their dependencies
python ingest.py --only weather event-context # run just these
python ingest.py --skip crawl acled           # leave these out
python ingest.py --refresh                    # re-download cached data (boundary, osm, landmarks, police)
python ingest.py --refresh osm                # re-download just one of them
python ingest.py --acled-file path/to/export.csv
python ingest.py --since 2024-01-01           # more police/crawler history (default: 1 January this year)
```

- The first run is slow: the OSM network and landmarks for zones 1-2 take several minutes each. The crawler runs in the background alongside the other steps (log in `data/runs/ingest_crawl.log`). Later runs skip downloads whose files already exist.
- `--since` only limits the police months and the crawler's organiser-event window. All 65 seed routes are always used for training.
- Landmarks retry busy Overpass servers with backoff across three mirrors. If a layer still fails, re-run `python ingest.py --only landmarks` and only the missing layers are fetched.
- If a step fails, the steps that depend on it are skipped, the rest still run, and a summary is printed at the end. Re-run a failed step with `--only <step>`.
- Every step can also be run on its own, see `src/ingestion/route_research/README.md`.

### 4. Run the app
```bash
streamlit run app.py
```
The dashboard's **Data status** table shows what was loaded and when.

### Database

`data/protest.duckdb` is the single store that the app, the models and notebooks read from, so none of them need to know file paths or formats. It's rebuilt from the ingestion files by the `database` step (or on its own with `python -m src.database.load`). **Close the Streamlit app first:** it holds the file open and the loader will say so.

| Group | Tables |
|---|---|
| Map | `boundary`, `segments` (walk network, with `n_published_route_examples`), `main_edges` (main roads with lanes/width), `targets`, `open_spaces` (`area_m2` = rally capacity), `shops`, `warehouses`, `missions` |
| Events and routes | `events`, `waypoints`, `route_segments` (ordered `segment_id`s per `event_id`), `event_context` |
| Context | `crimes`, `tfl_disruptions`, `acled_events`, `weather_hourly`, `pageviews_daily`, `protest_signals` (latest crawler run) |
| Bookkeeping | `load_log` (rows and load time per table) |

Geometry columns are lon/lat (EPSG:4326): `geom` on point and street tables, `geometry` on landmark layers. Use the `meters(a, b)` macro for distances; it works for points, lines and polygons. Don't use `ST_Distance_Sphere` directly: it expects lat/lon axis order.

```python
from src.database.db import get_connection
con = get_connection(read_only=True)

# Pin query: nearest street segment to a clicked point
con.execute("""SELECT segment_id, street_name, meters(geom, ST_Point(?, ?)) AS m
               FROM segments ORDER BY m LIMIT 1""", [lon, lat]).df()

# Shops within 100 m of a historical route
con.execute("""SELECT DISTINCT s.name, s.shop FROM route_segments r
               JOIN segments g USING (segment_id)
               JOIN shops s ON meters(s.geometry, g.geom) < 100
               WHERE r.event_id = ?""", ["2023-10-21-psc"]).df()
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

## LIST OF APIS CURRENTLY USED
https://news.met.police.uk/latest_news/tag/central-london
https://www.osac.gov/Country/UnitedKingdom/Content/Search?contentTypes=Report&subContentTypes=Travel%20Advisories%2CAlerts
https://api.tfl.gov.uk/Road/all/Disruption
https://marble-arch.london/security-updates/
https://palestinecampaign.org/events/
https://cnduk.org/events/
https://www.counterfire.org/events/
https://www.foa.org.uk/events
https://www.stopwar.org.uk/events/
https://www.mabonline.net/media/press-releases
https://thepeoplesassembly.org.uk/news
https://www.togetheralliance.org.uk/
https://standuptoracism.org.uk/events/
https://extinctionrebellion.uk/category/actions/
https://youthdemand.org/news-press/
https://defendourjuries.net/press-releases/






## ADDITIONAL DATA SOURCES — ROUTE RESEARCH INGESTION

The `src/ingestion/route_research/` pipeline downloads additional geographic, historical and contextual data to support London protest-route modelling.

### Data APIs and download services

- **OpenStreetMap / OSMnx — London pedestrian street network:** https://www.openstreetmap.org/  
  Documentation: https://osmnx.readthedocs.io/en/stable/

- **UK Police Data API — Historical public-order offence records:** https://data.police.uk/api/crimes-street/public-order  
  Documentation: https://data.police.uk/docs/method/crime-street/

- **TfL Unified API — Road disruptions:** https://api.tfl.gov.uk/Road/all/Disruption

- **TfL Unified API — Tube line status:** https://api.tfl.gov.uk/Line/Mode/tube/Status

- **ACLED — Historical protest-event data:** https://acleddata.com/conflict-data/data-export-tool  
  API documentation: https://acleddata.com/api-documentation/getting-started

- **OpenStreetMap Nominatim — Geocoding historical protest waypoints:** https://nominatim.openstreetmap.org/  
  Usage policy: https://operations.osmfoundation.org/policies/nominatim/

- **Copernicus GHSL — Satellite-derived urban population and built-up-area datasets:** https://human-settlement.emergency.copernicus.eu/downloadWizard.php

- **TfL Unified API — Station fare zones (for the Zones 1-2 boundary):** https://api.tfl.gov.uk/StopPoint/Mode/tube,dlr,overground,elizabeth-line

- **OpenStreetMap Overpass (via OSMnx) — Embassies, government buildings, landmarks, squares, parks, shops, warehouses:** https://overpass-api.de/

- **Wikidata SPARQL — Diplomatic missions in London and the country that runs them:** https://query.wikidata.org/

- **Open-Meteo — Historical and forecast hourly weather (no key):** https://open-meteo.com/en/docs/historical-weather-api

- **Wikimedia Pageviews API — Daily Wikipedia views per protest cause (media salience):** https://wikimedia.org/api/rest_v1/  
  Documentation: https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/

- **GOV.UK — UK bank holidays:** https://www.gov.uk/bank-holidays.json

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




## Protest ingestion

This crawler runs as the `crawl` step of `python ingest.py`. To run it on its own from the repo root (use `.venv`, not conda `base`):

```bash
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python ingest.py --only crawl   # or: python -m src.ingestion
```

Ingest Met Police conditions posts, OSAC London demonstration alerts, TfL road disruptions, and organizer sites. List platform IDs with `python -m src.ingestion --list-platforms`.

Each pipeline run writes **one subfolder per platform** (extraction source):

```
data/runs/{run_id}/
  met_police/
    records.json
    media/{article_id}/*.jpg    # condition route maps
  osac/
    records.json
  tfl_road_disruption/
    records.json
  _all/
    protests_flat.json
    protests.parquet
```

After `python -m src.ingestion`, open e.g. `data/runs/<run_id>/osac/records.json`.
