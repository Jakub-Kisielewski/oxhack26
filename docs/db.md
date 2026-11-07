# Discipline E: Database Layer, Full Audit

**Scope:** `src/database/**` — `db.py`, `load.py`, `mapdata.py`, `types.py`, `__init__.py`
**Size:** 655 lines, 45 functions and classes
**Authorship:** 6 Claude : 4 you : 2 Jakub by commit count. `mapdata.py` and `types.py` arrived here via your Discipline C refactor
**Audited against:** `MLH_SUBMISSION_STANDARDS.md` v1.0, filtered through `PIPELINE_SCOPE_CUT.md`
**Date:** 2026-11-07, commit `1acc2e8`

> **Repo state.** Discipline C remediation has landed here: `src/contract/` is gone and its two surviving modules now live in `src/database/`, the three dead DuckDB tables (`open_spaces`, `weather_hourly`, `pageviews_daily`) are removed from `TABLES`, and every `S608` suppression now carries a line-level `# noqa` with a stated reason. Three of my recommendations executed correctly.

---

## 0. Method

1. **Manual read** of all 655 lines.
2. **Function-level consumer trace.** Every public function in `mapdata.py` matched against call sites in `src/models`, `src/ui`, `app.py`. This is the check that produced §2, and it corrects a claim I made in the C audit.
3. **Table reconciliation.** Every table name queried anywhere in `mapdata.py` matched against the tables `load.py` actually creates.
4. **Schema feature count** by grep: primary keys, foreign keys, indexes, constraints.

---

## 1. Scorecard

| Standard | Verdict | Evidence |
|---|---|---|
| **S2.3** Package boundaries | **PASS** | `db.py` connects, `load.py` builds, `mapdata.py` reads, `types.py` declares. Clean separation after the C refactor |
| **S2.4** Real package | **FAIL** (MINOR) | `src/database/__init__.py` is **0 bytes**, no docstring, no exports. `src/database/.gitkeep` still present in a directory with five files |
| **S3.1** Functions under 50 lines | **PASS** | Largest is 22 |
| **S3.2** Files under 400 lines | **PASS** | `mapdata.py` 379, just under |
| **S3.7** Descriptive names | **FAIL** | `types.Path` shadows `pathlib.Path` inside the same package. §5 |
| **S3.11 / S3.12** DRY | **FAIL** | `distance_m` is a verbatim duplicate of `cause_targets.haversine_m`, and a **fourth** distance implementation in the repo. §4 |
| **S3.13** Named constants | **PASS** | `CSV_OPTIONS`, config imports. Clean |
| **S3.15** Object-orientation | **PARTIAL** | Three dataclasses in `types.py`, but the `_Serialisable` mixin is unsound (§6.5) and `load.py` returns stringly-typed status dicts |
| **S3.16** Type annotations | **PARTIAL** | 100% of return types annotated, which is good. But `con` is unannotated on 5 functions in `load.py`, and `_first_int(text)` / `_hhmm(text)` take bare parameters |
| **S3.19** No silent excepts | **PASS** | Every handler catches `duckdb.Error` or narrower and records the failure |
| **S3.20** Logging not printing | **FAIL** | 5 `print()`, 0 `import logging` |
| **S3.22** No import-time side effects | **PASS** | Clean |
| **S3.27** No dead code | **FAIL, severe** | **14 of 18 public functions in `mapdata.py` have zero consumers; 167 of 291 lines of function body (57%) is orphaned.** Three of them query tables that do not exist. §2 |
| **S3.28** No secrets | **PASS** | `PROTEST_DB` via environment |
| **S4.x** Tests | **FAIL** | **Zero tests for 655 lines.** `tests/` covers `crawler/` and `route_research/` only. §7 |
| **S5.16** Module docstrings | **PARTIAL** | 3 of 5. `db.py` and `__init__.py` have none |
| **S5.17** Function docstrings | **FAIL** | **4 of 45 (9%)**. `db.py` 0 of 3, `load.py` 0 of 10, `types.py` 0 of 5 |
| **S5.18 / S5.19** Comments explain why | **PASS, strong** | `mapdata.py`'s module docstring explains the single-connection constraint and the shared-cache hazard. The `# noqa` reasons are specific |
| **Schema design** | **FAIL** | No declared schema at all: 1 primary key, 0 foreign keys, 0 indexes, 0 column constraints across 9 tables. §3 |

**Headline:** the *plumbing* is good. Connection handling, spatial-extension fallback, per-table failure isolation, parameterised queries and escaped paths are all handled competently. Two things fail: **the layer has no schema**, and **more than half of its largest module is dead code left behind by the scope cut.**

---

## 2. The scope cut: 57% of `mapdata.py` is orphaned

### 2.1 Function-level consumer trace

| Function | References in `src/models`, `src/ui`, `app.py` |
|---|---|
| `distance_m` | **8** |
| `cursor` | **3** |
| `cause_targets` | **3** |
| `historical_events` | **1** |
| `connection` | 0 (called internally by `cursor`) |
| `list_causes` | **0** |
| `segment_paths` | **0** |
| `cells_for_segments` | **0** |
| `boundary` | **0** |
| `legal_zones` | **0** |
| `targets` | **0** |
| `shops_near` | **0** |
| `search_shops` | **0** |
| `warehouses` | **0** |
| `cells` | **0** |
| `cell_at` | **0** |
| `assembly_points` | **0** |
| `in_boundary` | **0** |

**Four live functions. Thirteen orphans.** Measured by AST: 167 of 291 lines of function body, **57%**.

### 2.2 [REVERSED] My Discipline C audit got this wrong

The C audit stated:

> | `src/database/mapdata.py` | 26 references from `models/` | **BACKBONE** |

That 26 was a grep for the string `mapdata`, which counts the import plus every attribute access. At function granularity the picture is different: `mapdata.py` is **4 live functions wrapped in 13 dead ones**. The module is backbone; most of its contents are not. `CLEANUP.md` called it "harmless dead code" and I over-corrected. The honest position is in between, and it is measurable.

### 2.3 Three functions query tables that do not exist

| Function | Queries | Guarded? |
|---|---|---|
| `shops_near` | `FROM shops` | **No** |
| `search_shops` | `FROM shops` | **No** |
| `warehouses` | `FROM warehouses` | **No** |
| `cells_for_segments` | `FROM segment_cells` | yes, `_table_exists` |

`shops`, `warehouses` and `segment_cells` were all deleted with the prediction layer and the `build_grid` step. `load.py::TABLES` creates none of them. **Three functions would raise `duckdb.CatalogException` if anything called them**, and nothing does.

This also makes the `meters()` macro dead. `db.py::init_schema` creates it on **every connection**, and its only call site is the unreachable `shops_near` query:

```python
SELECT osm_id, name, shop, lon, lat, meters(geometry, ST_Point(?, ?)) AS d FROM shops
```

So `init_schema` installs a spatial macro, on every process start, for a query against a table that no longer exists.

### 2.4 The cut

| Delete | Lines |
|---|---|
| `shops_near`, `search_shops`, `warehouses` | 53 |
| `cells`, `cell_at`, `cells_for_segments` | 28 |
| `boundary`, `in_boundary`, `legal_zones`, `targets`, `assembly_points`, `segment_paths`, `list_causes` | 86 |
| `_bbox_params`, `_rings`, `_has_column` and any other helper left with no caller | ~20 |
| `meters()` macro in `db.py::init_schema` | 5 |
| `CauseOption` in `types.py` (only consumer is `list_causes`) | 6 |
| **Total** | **~198** |

`mapdata.py` goes from 379 lines to roughly **180**, every function has a named consumer, and `src/database` drops to ~455 lines.

**Before deleting, check two things.** `boundary()`, `legal_zones()` and `segment_paths()` are plausible future needs for a map view, and `historical_events` is live. Confirm with:

```bash
grep -rn "mapdata\.\(boundary\|legal_zones\|segment_paths\|targets\)" src app.py
```

If it returns nothing, they go. Git history keeps them.

---

## 3. The schema finding: there is no schema

### 3.1 Measured

Across all of `src/database`:

| Feature | Count |
|---|---|
| `PRIMARY KEY` | **1** (`load_log.table_name`) |
| `FOREIGN KEY` | **0** |
| `CREATE INDEX` | **0** |
| `UNIQUE` | **0** |
| `CHECK` | **0** |
| Column-level `NOT NULL` | **0** (the five `NOT NULL` hits are all `IS NOT NULL` in `WHERE` clauses) |

`init_schema` creates exactly one table, `load_log`, plus the macro. The nine data tables are created by:

```python
con.execute(f"CREATE OR REPLACE TABLE {table} AS {sql}")
```

So every column type in the database is **inferred by DuckDB from a CSV or GeoJSON file** at load time.

### 3.2 The cost is visible in the read path

Because types are inferred rather than declared, `mapdata.py` defends against them:

```python
SELECT e.event_id, e.event_name, CAST(e.event_date AS VARCHAR), CAST(e.start_time AS VARCHAR),
       c.cause, e.organiser, CAST(e.turnout AS VARCHAR), e.event_category
FROM events e LEFT JOIN event_context c USING (event_id)
```

and then, in Python:

```python
turnout = (_first_int(turnout),)  # regex: r"\d[\d,]*"
start_time = (_hhmm(start),)  # regex: r"^\s*(\d{1,2}):(\d{2})"
```

**`turnout` is an integer in the seed CSV, filled for 65 of 65 events.** It is loaded as whatever DuckDB infers, cast back to text in SQL, then recovered with a regular expression in Python. Same for `event_date` and `start_time`. That round trip exists because nothing in the pipeline ever declared what these columns are.

This is the kind of thing a reviewer with database experience asks about directly, and "DuckDB infers it" is a weaker answer than it needs to be.

### 3.3 The fix

Declare the schema for the tables the model reads, and load into it. Keep `CREATE OR REPLACE TABLE ... AS` for the geometry-heavy layers where inference genuinely helps.

```python
def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create the bookkeeping table and the declared schema for model inputs.

    Geometry layers are still created by inference in `load.py`, because their
    column sets come from OSM and vary. The tables the model reads are declared
    here so their types cannot drift with a CSV edit.
    """
    con.execute("""
        CREATE TABLE IF NOT EXISTS events (
            event_id        VARCHAR PRIMARY KEY,
            event_date      DATE        NOT NULL,
            event_name      VARCHAR     NOT NULL,
            start_time      TIME,
            turnout         INTEGER     CHECK (turnout IS NULL OR turnout > 0),
            organiser       VARCHAR,
            source_url      VARCHAR     NOT NULL
        );
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS waypoints (
            event_id        VARCHAR     NOT NULL REFERENCES events(event_id),
            sequence_index  INTEGER     NOT NULL,
            waypoint_name   VARCHAR     NOT NULL,
            latitude        DOUBLE      NOT NULL,
            longitude       DOUBLE      NOT NULL,
            PRIMARY KEY (event_id, sequence_index)
        );
    """)
```

Three things follow from that, all of which are interview material:

1. **`CAST(... AS VARCHAR)` and both regex parsers disappear.** `turnout` comes back as an `int`.
2. **`REFERENCES events(event_id)` makes an orphaned waypoint a load error** rather than a silently dropped join. Given your pipeline's whole point is label provenance, having the database enforce that every waypoint belongs to a known event is directly on-message.
3. **A `CHECK (turnout > 0)`** catches a seed-file typo at load time instead of propagating a negative turnout into `log(turnout) × log(width)`.

On indexes: DuckDB is columnar and does not need them the way Postgres does, so **do not add indexes for performance**. Add the primary keys for the constraint. If asked, that distinction is a good answer.

---

## 4. Four distance implementations, one of them duplicated verbatim

| Implementation | Location | Method |
|---|---|---|
| `mapdata.distance_m` | `src/database/mapdata.py:57` | Haversine on (lon, lat) |
| `haversine_m` | `route_research/processing/cause_targets.py:32` | **The same haversine formula, written again** with a different signature |
| `meters()` SQL macro | `src/database/db.py:45` | `ST_Distance` after `ST_Transform` to EPSG:27700 |
| `math.hypot` on projected coords | `normalize.py:175`, `graph.py:164` | Planar, in a projected CRS |

Numerically the haversine and British National Grid results differ by well under a metre across central London, so **this is not a correctness bug.** It is four definitions of one concept with no single source of truth, and `distance_m` feeds the model: `features.py` uses it for feature 1 (`progress`) and feature 7 (`target_pull`).

**Fix:** keep `mapdata.distance_m` as the one Python implementation, have `cause_targets.py` import it, and delete the `meters()` macro with §2.4. Then one function defines distance for the whole project, it has a docstring saying which formula and why, and it is testable in one place.

---

## 5. `types.Path` shadows `pathlib.Path` inside one package

`src/database/types.py:8`:

```python
LonLat = tuple[float, float]
Path = list[LonLat]
```

`mapdata.py:20` imports it:

```python
from src.database.types import CauseOption, HistoricalEvent, LonLat, Path
```

while its two sibling modules do:

```python
from pathlib import Path  # db.py:1, load.py:8
```

So within `src/database/`, `Path` means a filesystem path in two modules and a list of coordinates in the other two. Nothing breaks today because no module imports both, but it is one import away from a confusing bug, and a reader scanning the package has to track which `Path` is in scope.

**Fix:** rename to `Polyline`, or `LonLatPath`:

```python
LonLat = tuple[float, float]
Polyline = list[LonLat]
"""An ordered run of (lon, lat) points: a street segment or a march route."""
```

---

## 6. Defects

### E1. `load.py:162-163` destroys the existing database without asking

```python
old = a.db.with_suffix(a.db.suffix + ".old")
a.db.replace(old)
print(f"Moved {a.db.name} to {old.name} and rebuilding")
```

Triggered when DuckDB reports the file was written by a newer version. `Path.replace` **overwrites the destination silently**, so a second occurrence destroys the first backup. The user is told after the fact, by a `print` on stdout.

A destructive filesystem operation on an error path, with no confirmation and a one-shot backup, is the kind of thing that costs someone a day. Make it non-destructive and explicit:

```python
except duckdb.IOException as exc:
    if "newer version of DuckDB" not in str(exc):
        raise
    stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    backup = a.db.with_name(f"{a.db.stem}.{stamp}{a.db.suffix}.old")
    if not a.force:
        print(
            f"{a.db} was written by a newer DuckDB and cannot be opened.\n"
            f"Re-run with --rebuild to move it to {backup.name} and rebuild.",
            file=sys.stderr,
        )
        return 1
    a.db.rename(backup)
```

A timestamped name cannot clobber a previous backup, and `--rebuild` makes the destruction a choice.

### E2. The same value is parameterised in one function and interpolated in another

`load.py:100` does it correctly:

```python
con.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?", [table])
```

`load.py:49` does not:

```python
f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{table}'"
```

Both take `table` from the same source (`plan()` keys), so neither is exploitable. But a reviewer who sees the parameterised version first and the interpolated version second will ask why, and "no reason" is the honest answer. Parameterise line 49 and delete one `# noqa`.

### E3. Error detail is truncated before it can help

```python
except duckdb.Error as exc:
    status[table] = f"FAILED: {str(exc).splitlines()[0][:150]}"
```

DuckDB's load errors are multi-line and the useful part — the offending column, the row number, the conversion that failed — is usually **after** the first line. Taking `splitlines()[0][:150]` discards exactly the diagnostic you need. Keep the short form for the summary table and log the full exception:

```python
except duckdb.Error as exc:
    logger.warning("table %s failed to load", table, exc_info=True)
    status[table] = f"FAILED: {str(exc).splitlines()[0][:150]}"
```

### E4. `lru_cache` returns shared mutable lists

```python
@lru_cache(maxsize=2)
def historical_events(protests_only: bool = True) -> list[HistoricalEvent]: ...
```

The module docstring is honest about it: *"Results of the cached functions are shared: treat them as read-only."* But that invariant is enforced by a comment. One caller doing `events.sort()` or `events.pop()` mutates every other caller's view, and the symptom appears somewhere unrelated.

Return a `tuple` instead. The annotation then enforces what the docstring asks, at zero cost, and `HistoricalEvent` is already a dataclass of immutable fields.

### E5. `_Serialisable` cannot work on its own terms

```python
class _Serialisable:
    def to_dict(self) -> dict:
        return asdict(self)
```

`dataclasses.asdict` raises `TypeError` on a non-dataclass, so `_Serialisable().to_dict()` fails. The mixin only works by the convention that every subclass is decorated `@dataclass`, which nothing enforces. The return type is also unparameterised.

Either drop the mixin and call `dataclasses.asdict(obj)` at the two or three call sites, or make the constraint explicit:

```python
@dataclass
class _Serialisable:
    """Base for the read-only DTOs below; subclasses must be dataclasses."""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
```

### E6. `get_connection` swallows real errors into an install attempt

```python
try:
    con.execute("LOAD spatial")
except duckdb.Error:
    _install_spatial(con)
    con.execute("LOAD spatial")
```

`duckdb.Error` is the base class, so a corrupt database or a permissions failure also lands in `_install_spatial`, and the user gets an extension-installation error instead of the real one. Catch `duckdb.CatalogException` and `duckdb.IOException` specifically, or inspect the message before deciding to install.

### E7. `__init__.py` is empty and `.gitkeep` is stale

`src/database/__init__.py` is 0 bytes: no docstring, no re-exports, so callers reach in with `from src.database.db import get_connection`. A three-line `__init__.py` naming the package's job and exporting `get_connection`, `cursor` and `load` would make the package boundary real (S2.4, S5.16). And `src/database/.gitkeep` sits in a directory with five files (S2.5).

---

## 7. Zero tests for 655 lines

`tests/` covers `crawler/` and `route_research/`. **Nothing covers the database layer**, which sits between the two tested packages and the model, and which every table claim in the README depends on.

The good news is that `load.py` is unusually testable, because `get_connection(path=...)` takes a path and DuckDB has in-memory and temp-file modes. No fixtures beyond a few tiny CSVs.

| Target | Tests | Why |
|---|---|---|
| `quote()` | **3** | Pure. Must escape `'` correctly; this is the function standing between a path and SQL |
| `reader_sql()`, `with_points()` | **3** | Pure string builders. Assert the right reader per extension |
| `plan()` | **3** | Pure given a directory. Missing file yields `None`, present file yields SQL, point columns wrap |
| `load()` end to end | **4** | `tmp_path` with two tiny CSVs: asserts row counts, `load_log` entries, a missing file is `skipped`, and a malformed CSV is `FAILED` without aborting the other tables |
| `init_schema()` | **2** | Idempotent: run twice, no error. `load_log` exists |
| `mapdata.distance_m` | **3** | Known pairs: Trafalgar Square to Parliament Square is ~700 m. Also the zero case |
| `_first_int`, `_hhmm` | **4** | Pure regex parsers currently untested and used on every event read |
| `historical_events` | **2** | Against a `tmp_path` database built by `load()`: asserts the join and that `turnout` comes back as an `int` |
| **Total** | **24** | |

Two worth writing first:

```python
def test_quote_escapes_single_quotes() -> None:
    """A path containing a quote must not break out of the SQL string."""
    assert quote(Path("/tmp/o'brien/data.csv")) == "'/tmp/o''brien/data.csv'"


def test_one_malformed_csv_does_not_abort_the_other_tables(tmp_path: Path) -> None:
    """Per-table isolation: a bad file is reported, the rest still load."""
    norm = tmp_path / "normalised"
    norm.mkdir(parents=True)
    (norm / "events.csv").write_text("event_id,event_date\nE1,2026-06-01\n")
    (norm / "event_context.csv").write_text("not,a,valid\ncsv\n")

    con = get_connection(path=tmp_path / "test.duckdb")
    try:
        status = load(con, tmp_path)
    finally:
        con.close()

    assert status["events"] == "1 rows"
    assert status["event_context"].startswith("FAILED")
```

The second test pins the per-table isolation that is `load.py`'s best design property and is currently unverified.

---

## 8. Documentation and typing

| Module | Functions and classes | Docstrings | Module docstring |
|---|---|---|---|
| `mapdata.py` | 27 | 4 (15%) | yes, and it is the best in the layer |
| `load.py` | 10 | **0** | yes |
| `types.py` | 5 | **0** | yes |
| `db.py` | 3 | **0** | **no** |
| `__init__.py` | 0 | — | **no** |
| **Total** | **45** | **4 (9%)** | 3 of 5 |

`db.py` is the worst case and the most load-bearing: three functions, no docstrings, no module docstring, and it holds the spatial-extension fallback logic that nobody will understand in six months.

```python
def _install_spatial(con: duckdb.DuckDBPyConnection) -> None:
    """Install DuckDB's spatial extension, preferring the pip-bundled build.

    `duckdb-extension-spatial` ships the binary inside the wheel, so a normal
    `pip install` is enough on every platform with a wheel. Intel Macs have no
    wheel, so we fall back to `INSTALL spatial`, which downloads from
    extensions.duckdb.org and needs network access. Extensions are pinned to
    the exact DuckDB version, which is why `duckdb==1.5.5` is an equality pin.
    """
```

That docstring is worth more than the function: the pin and the Intel Mac caveat are currently explained only in the README, 100 lines from the code that implements them.

**Typing** is better than elsewhere in the repo: every function has a return annotation. The gaps are the untyped `con` parameter on five `load.py` functions and the bare `text` on `_first_int` / `_hhmm`.

---

## 9. Checked and cleared

Verified, so you can state these confidently.

**The three dead tables are gone.** `TABLES` no longer contains `open_spaces`, `weather_hourly` or `pageviews_daily`. `open_spaces` is now read directly as a Parquet file inside `derive()` for the Royal Parks insert, which is the right call: it is used once, for one predicate, and never needed to be a table.

**Every `S608` suppression carries a reason.** Seven line-level `# noqa: S608 — ...` comments, each naming why the interpolated value is safe ("quoted local ingestion paths", "table from plan keys only", "country_sel is country|NULL literal"). This is exactly what the C audit asked for and it is done properly.

**`quote()` escapes correctly.** `"'" + path.as_posix().replace("'", "''") + "'"` is the right SQL string escape, and every path interpolation goes through it.

**Per-table failure isolation works.** `load()` catches `duckdb.Error` per table, records `FAILED: ...`, continues, and `main()` returns exit code 1 if anything failed. Same pattern as the crawler pipeline, which makes the repo consistent.

**`derive()` is idempotent.** `load()` recreates `legal_zones` from seed before `derive()` inserts Royal Parks, so repeated runs cannot duplicate rows.

**The single-connection constraint is documented.** `mapdata.py`'s module docstring explains that DuckDB refuses a second connection to the same file with a different configuration, which is why there is one cached read-only connection and `cursor()` per call. That is a real constraint discovered in practice and written down, and `app.py`'s bootstrap comment explains the matching write-lock release. Good work.

**`table_exists` and most query parameters are bound, not interpolated.** `?` placeholders with `UNNEST(?)` for list parameters throughout `mapdata.py`.

---

## 10. Work plan

| Step | Work | Clears | Effort |
|---|---|---|---|
| **E-1** | **Scope cut §2.4:** delete the 13 orphaned functions, the three dead-table queries, the `meters()` macro and `CauseOption`. Run the grep in §2.4 first | **S3.27**, ~198 lines | **1 h** |
| **E-2** | Fix defects E1 to E7, each with a regression test. E1 and E2 first | 7 defects | 2 h |
| **E-3** | Declare the schema for `events` and `waypoints` (§3.3). Delete both `CAST(... AS VARCHAR)` and both regex parsers from the read path | **schema design**, S3.11 | 3 h |
| **E-4** | Add `tests/database/` with the 24 tests in §7 | S4.x, S2.6 | 4 h |
| **E-5** | Docstrings for all 45 functions, starting with `db.py`'s three. Annotate `con` parameters | S5.16, S5.17 | 3 h |
| **E-6** | Rename `types.Path` to `Polyline` | S3.7 | 20 min |
| **E-7** | Consolidate distance: `cause_targets.py` imports `mapdata.distance_m` | S3.11, S3.12 | 30 min |
| **E-8** | `logging` instead of 5 `print()`. Populate `__init__.py`. Delete `.gitkeep` | S3.20, S2.4, S2.5 | 45 min |

**Sequencing.** E-1 first: it is an hour and it removes 30% of the discipline, including three functions that would crash if called. E-3 is the highest-value change for the walkthrough, because "the database declares and enforces that every waypoint belongs to a known event" is a sentence that lands with anyone who has worked with data, and it is directly continuous with your provenance story. E-4 before E-5, as everywhere else.

**Authorship note.** `src/database` is 6 Claude : 4 you : 2 Jakub, so this discipline is more yours than B but less than A or C. E-1 through E-3 are worth doing on their own merits: E-1 because dead code that crashes is indefensible, E-3 because it is the best interview answer available in this layer. E-5's 45 docstrings are lower priority than the same work in `src/models`, which has 43 functions at 2%.

---

## 11. What is already good

- **The connection strategy is correct and documented.** One cached read-only connection per process with `cursor()` per call, because DuckDB will not open a second connection with a different configuration. The constraint is explained in the module docstring, and `app.py`'s bootstrap releases the write lock before pages open read-only connections. That is a non-obvious problem solved properly and written down.

- **The spatial-extension fallback is thoughtful.** Prefer the pip-bundled binary, fall back to `INSTALL spatial` over the network, and pin `duckdb==1.5.5` because extensions are version-locked. The Intel Mac path is handled. It only needs a docstring.

- **Failure isolation and honest exit codes.** One bad table does not abort the load, every outcome is reported in the status table, and `main()` exits non-zero if anything failed. Consistent with the crawler pipeline.

- **Parameterised queries are the default**, including `UNNEST(?)` for list parameters, which many people do not know DuckDB supports.

- **The `# noqa` reasons are specific and accurate.** Not `# noqa: S608` but `# noqa: S608 — table from plan keys only`. That is the difference between suppressing a warning and documenting a decision.

- **`quote()` exists at all.** Having one escaping function that every path interpolation passes through is the right structure, and it is the thing that makes the remaining `S608` suppressions defensible.

- **The three dead tables were removed promptly** after the B audit identified them, and `open_spaces` was correctly demoted to a direct file read rather than deleted outright.

- **`load_log`** records table name, source file, row count and load time. A small bookkeeping table that makes a build auditable is the kind of thing that distinguishes someone who has operated a pipeline from someone who has only written one.