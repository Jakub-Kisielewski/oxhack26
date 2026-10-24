## HOW TO SETUP
### Run the following in order of appearance
```bash
# Create virtual environment
python -m venv .venv

# Activate it
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### To setup the database
DuckDB runs inside Python, so there is no server to install. The only slow part is the **spatial extension** (~35 MB), which DuckDB downloads silently with no progress bar. On a slow network it looks frozen for 10+ minutes and ignores Ctrl+C, so please follow the steps below rather than just running the script.
`requirements.txt` pins `duckdb==2.0.0`. Extensions are tied to the exact DuckDB version, so don't upgrade it.

#### install spatial extension
```bash
python -c "import duckdb; print(duckdb.__version__)"            # should print 2.0.0
python -c "import duckdb; print(duckdb.sql('PRAGMA platform').fetchone()[0])"
```

Common platforms: `linux_amd64`, `osx_arm64` (Apple Silicon), `osx_amd64` (Intel Mac), `windows_amd64`.

Replace `<platform>` with your value from above (no angle brackets):

```bash
curl -fL -C - -o spatial.duckdb_extension.gz \
  https://extensions.duckdb.org/v2.0.0/<platform>/spatial.duckdb_extension.gz
file spatial.duckdb_extension.gz     # must say "gzip compressed data"
gunzip spatial.duckdb_extension.gz
python -c "import duckdb; duckdb.sql(\"INSTALL './spatial.duckdb_extension'\"); print('ok')"
```

- `-f` makes curl fail on a wrong URL instead of saving an error page, and `-C -` resumes if interrupted.
- Don't Ctrl+C a slow download. If it does get interrupted, re-run the same command and it will resume.
- On Windows, use Git Bash or WSL for these commands, or download the `.gz` in a browser and extract it with 7-Zip.

Once it prints `ok`, the extension is cached in `~/.duckdb/extensions/` and works offline from then on. You can delete the `spatial.duckdb_extension` file afterwards (it's gitignored anyway).

Verify that it loads:

```bash
python -c "import duckdb; c=duckdb.connect(); c.sql('LOAD spatial'); print(c.sql('SELECT ST_Point(0,0)'))"
```
#### create the db
From the repo root:

```bash
python -m src.database.db
```

This should finish in under a second and print the tables: `crimes`, `grid_cells`, `transit_snapshots`. It creates `data/protest.duckdb`. It's safe to re-run.

#### Load data

Either run the ingestion scripts yourself:

```bash
python -m src.{waiting for global ingestion script}
```

### Run the app
```bash
streamlit run app.py
```

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

From the repo root (use `.venv`, not conda `base`):

```bash
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m src.ingestion
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
