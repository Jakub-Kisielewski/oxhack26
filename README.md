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

## Protest ingestion

From the repo root (use `.venv`, not conda `base`):

```bash
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m src.ingestion
```

Ingest Met Police conditions posts, OSAC London demonstration alerts, TfL road disruptions, and organizer sites. List platform IDs with `python -m src.ingestion --list-platforms`.

Optional TfL API credentials (higher rate limits):

```bash
export TFL_APP_ID=your_app_id
export TFL_APP_KEY=your_app_key
python -m src.ingestion --met-limit 8 --osac-limit 12 --tfl-days-ahead 30
```

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
