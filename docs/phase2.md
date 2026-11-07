# Discipline B: Data Engineering and Geospatial, Full Audit

**Scope:** `src/ingestion/route_research/**` (14 modules, 9 seed files)
**Size:** 1,330 lines, 73 functions
**Authorship:** majority Claude-authored. `sources/` 5 Claude : 1 you : 1 Jakub. `processing/` 5 Claude : 2 you : 1 Jakub
**Audited against:** `MLH_SUBMISSION_STANDARDS.md` v1.0, **filtered through `PIPELINE_SCOPE_CUT.md` and `CLEANUP.md`**
**Date:** 2026-11-07, commit `ca9100d`
**Version:** 2.0. Section 2 is new and reorders everything after it.

> **Repo state.** Three commits since the Discipline A audit: `0cab173` (Part A remediation), `1211710` (crawler reduced to discovery-only), `ca9100d` (Marble Arch restored, organisers pruned to PSC). All three still authored `cl5924 <you@example.com>`: **S6.1 and S6.2 remain open blockers.**

---

## 0. Method, and what version 2.0 changes

Version 1.0 of this audit asked "is this code good?" That was the wrong first question. `PIPELINE_SCOPE_CUT.md` sets the right one:

> **Does this code produce something the model actually consumes?**

Polishing a module you should delete is wasted work, and worse, it enlarges the surface a reviewer must be walked through. So this version applies a **consumer trace** first and a quality audit second. Everything is verified three ways: `ruff`, manual reading, and executable checks against the real code and the real seed data.

**Four of my version-1.0 recommendations are reversed.** They are marked **[REVERSED]** where they appear. I was praising and proposing tests for code that has no consumer.

---

## 1. The consumer trace

Traced backwards from `features.py::NAMES` and `labels.py::read_events`, through `graph.py`'s SQL, through `load.py::TABLES`.

### 1.1 The model's real input surface

`graph.py:142-144` selects exactly these columns:

```sql
length_m, road_class, street_name, width_m,
COALESCE(betweenness_main, betweenness_walk, 0), to_degree,
is_main, is_bridge, is_tunnel, in_no_entry_zone, in_restricted_zone, in_royal_park
```

`labels.py:24` selects exactly three:

```sql
SELECT event_id, precip_mm_4h, daylight_after_start_h FROM event_context
```

And the context dict reaching every feature vector has three keys: `turnout`, `precip_mm_4h`, `dark_fraction`.

### 1.2 Verdict per B module

| B module | Output | Consumed by | Verdict |
|---|---|---|---|
| `download_boundary.py` | `zones_1_2.geojson` | clip area for `download_osm`, `download_landmarks` | **BACKBONE** (upstream only) |
| `download_osm.py` | `london_walk.graphml`, `london_main.graphml` | features 1, 2, 4, 5, 6 | **BACKBONE** |
| `download_landmarks.py` | `targets.geoparquet` | feature 7 `target_pull` | **BACKBONE** |
| `download_landmarks.py` | `open_spaces.geoparquet` | feature 8 `royal_park`, via `edge_features` | **BACKBONE** (file), table redundant |
| `download_weather.py` | `hourly.csv`, 7 variables | **1 of 7** reaches the model (`precipitation` → feature 11) | **BACKBONE, over-specified** |
| `download_pageviews.py` | `daily.csv` | **nothing** | **CUT** |
| `seed_coordinates.py` | `coordinate_review.csv` | `normalize.py` | **BACKBONE** |
| `normalize.py` | `events.csv`, `waypoints_approved.csv`, `route_segment_labels.csv`, `segments.geojson` | labels, features 1, 10 | **BACKBONE** |
| `edge_features.py` | 6 of 14 columns | features 2, 4, 5, 8, 9 | **BACKBONE, over-produced** |
| `event_context.py` | **3 of 24 columns** | features 11, 12, plus `cause` | **BACKBONE, heavily over-produced** |
| `cause_targets.py` | `cause_targets.csv` | feature 7 | **BACKBONE** |

### 1.3 Measured: dead tables in `load.py`

| DuckDB table | References outside `load.py` | Verdict |
|---|---|---|
| `events` | 46 | keep |
| `segments` | 26 | keep |
| `targets` | 23 | keep |
| `waypoints` | 13 | keep |
| `cause_targets` | 7 | keep |
| `boundary` | 4 | keep |
| `legal_zones` | 3 | keep |
| `event_context` | 3 | keep |
| `route_segments` | 2 | keep |
| **`open_spaces`** | **0** | table redundant; `edge_features` reads the file directly |
| **`weather_hourly`** | **0** | table redundant; `event_context` reads the file directly |
| **`pageviews_daily`** | **0** | **fully dead** |

---

## 2. Scope cut for Discipline B

Four tests, applied in order: **no consumer**, **redundant**, **demo-only**, **no mathematical support**.

### 2.1 CUT: pageviews and the whole salience block

| Item | Lines | Why |
|---|---|---|
| `sources/download_pageviews.py` | 81 | `pageviews_daily` has zero references. No feature reads salience |
| `event_context.index_pageviews`, `event_context.salience` | ~20 | Produce 4 columns no consumer reads |
| `views_7d`, `views_30d`, `views_baseline_90d_mean`, `salience_spike_ratio` | 4 columns | Unconsumed |
| `seed/cause_articles.csv` | 949 bytes | Input to the deleted step only |
| `pageviews_daily` entry in `load.py::TABLES` | 1 line | Dead table |
| `pageviews` step in `pipeline.py::STEPS` and `ingest.py` | 2 lines | Dead step |

**Total: ~110 lines, one pipeline step, one DuckDB table, one seed file, one external API dependency (Wikimedia).**

**[REVERSED] This deletes what version 1.0 called "the highest-value test in the project".** My leakage regression test targeted `salience`, on the grounds that it proves you understand look-ahead bias. That was wrong on priorities: a beautifully tested function with no consumer is still dead code, and a reviewer who asks "what reads this?" gets no answer.

The leakage insight is worth keeping, and it has a better home. `normalize.py` already prints:

```python
print(
    "WARNING: For backtesting, recompute historical counts using ONLY events before the test event date."
)
```

That warning is about `n_published_route_examples`, which feeds **feature 10 (`history`)**, which is backbone. **Retarget the leakage test there.** Same demonstration of the same understanding, aimed at a feature the model actually fits. That is a strictly better test, and I should have found it first.

### 2.2 CUT: 18 of 24 `event_context.csv` columns

Consumed: `event_id`, `precip_mm_4h`, `daylight_after_start_h`, `cause`.

Everything else has no consumer. The apparent hits are all in `src/contract/types.py`, a type declaration for the UI layer `CLEANUP.md` removed. A dataclass field is not a consumer.

| Column group | Columns | Takes with it |
|---|---|---|
| Salience | `views_7d`, `views_30d`, `views_baseline_90d_mean`, `salience_spike_ratio` | §2.1 |
| Unconsumed weather | `temp_mean_c`, `apparent_temp_mean_c`, `wind_gust_max_kmh`, `cloud_mean_pct`, `weather_source` | 5 of 7 `HOURLY` variables in `download_weather.py` |
| Calendar | `is_bank_holiday`, `is_school_holiday`, `is_ramadan`, `is_weekend`, `day_of_week` | `load_bank_holidays` + the gov.uk network call + its cache; `load_school_holidays` + `seed/school_holidays.csv`; **the `hijridate` dependency** |
| Display-only | `sunrise`, `sunset`, `start_time_imputed`, `cause_derived` | nothing |

**This is also the mathematically honest cut, not just the tidy one.** With **65 seed events**, adding calendar dummies (`is_ramadan`, `is_bank_holiday`, `is_weekend`) as candidate predictors has no plausible support: Ramadan overlaps a handful of events at most, UK bank holidays fewer. Carrying columns that could never be fitted invites exactly the question you do not want: "why is this here?" The answer "I computed it in case it helped" is the demo answer.

**Keep `is_ramadan` only if you can state its event count and it exceeds about 8.** Otherwise cut it and say in the README that calendar effects were considered and dropped for lack of support. That sentence is worth more than the column.

### 2.3 CUT: the unconsumed half of `edge_features.py`

| Column | Status |
|---|---|
| `width_m` | **consumed**, features 2 and 3 |
| `betweenness_main`, `betweenness_walk` | **consumed**, feature 5, but see §3 |
| `is_main` | **consumed**, feature 4 |
| `in_royal_park`, `in_restricted_zone` | **consumed**, features 8 and 9 |
| `length_m`, `road_class`, `street_name` | **consumed** via `segment_features.csv` |
| `is_bridge`, `is_tunnel` | loaded into `SegmentInfo`, **absent from `NAMES`**. Carried, never fitted |
| `to_degree` | selected in SQL at `graph.py:143`, **unpacked and discarded** |
| `in_no_entry_zone` | selected, unpacked into `forbidden`, **never stored on `SegmentInfo`** |
| `area_m2`, `capacity_people`, `width_source`, `from_degree` | **never selected at all** |

**[REVERSED] `area_m2` and `capacity_people` are demo-only, and that includes the Fruin docstring version 1.0 singled out as exemplary.**

```
  area_m2, capacity_people   width x length, and people it holds at 2 people/m2
                          (Fruin: above ~2/m2 a crowd is congested; ~4-5/m2 is dangerous)
```

The reasoning is genuinely good and the citation is real. But these two columns fed the **overspill model, which `CLEANUP.md` deleted**. Nothing computes with them now. Under the scope test they go, and `SAFE_DENSITY` goes with them.

**Do not throw away the reasoning.** Move the Fruin paragraph into `DEVPOST.md` or a `docs/` design note as *considered and out of scope*. You keep the evidence that you researched crowd dynamics, and you lose the unanswerable question "what uses capacity_people?"

`estimate_width` stays, in full: `width_m` is feature 2 and the single most-used input after geometry. Its pavement reasoning is load-bearing.

### 2.4 CUT: redundancy

| Item | Evidence |
|---|---|
| `normalize.py` writes `segment_features.csv` **twice** | line 60 in `make_streets`, then again at line 153 after the merge. The first write is overwritten every run |
| `DATE_POST_RE` defined twice | `date_window.py:10` and `organizers/filters.py:172` |
| `PACKAGE_SEED` redefined in 3 modules | `seed_coordinates`, `edge_features`, `cause_targets` |
| Three distance methods | `cause_targets.haversine_m`, `normalize`'s `math.hypot` on projected coords, GeoPandas metric CRS. Pick one |
| `open_spaces`, `weather_hourly` in `load.py::TABLES` | 0 references each. Both files are read directly by their consumers |
| `STEPS`' `prefix` field | always `[]` |

### 2.5 KEEP, and say why out loud

Everything in §1.2 marked BACKBONE, plus these, because a reviewer may mistake them for scope creep:

- **`download_boundary.py`** produces no model feature. It defines the clip area for OSM and landmarks, so without it the graph is a hardcoded bbox. Keep it and say so in one README line.
- **`event_context.derive_cause` and `CAUSE_KEYWORDS`.** Verified: **`seed/events.csv` has no `cause` column at all.** `derive_cause` therefore fires for all 65 events, and `cause` drives `destinations.candidates`, `mapdata.cause_targets` and feature 7. This is not an optional nicety; it is load-bearing. The comment ordering counter-protests before the causes they oppose is a real correctness decision.
- **The human-review gate.** `seed_coordinates.py` writing `status=missing` rather than geocoding is the project's provenance backbone and the best answer you have to "how do you know your labels are right?"

### 2.6 What B looks like after the cut

| | Before | After |
|---|---|---|
| Modules | 14 | **13** |
| Lines | 1,330 | **~1,150** |
| Pipeline steps | 10 | **9** |
| `event_context.csv` columns | 24 | **4** |
| `edge_features.csv` columns | 14 | **8** |
| External APIs | Overpass, Open-Meteo, Wikimedia, gov.uk, TfL | **Overpass, Open-Meteo, TfL** |
| Third-party deps | + `hijridate`, `astral` | **`astral` only** |
| `load.py` tables | 12 | **9** |
| Seed files | 9 | **7** |

Two network dependencies and one package removed, and every surviving column has a named consumer you can point at.

---

## 3. The mathematical finding: feature 5 mixes two estimators

This is the one item in Discipline B that fails the "rigorous mathematical assumption" test on its own terms, and it is in backbone code, so it must be fixed rather than deleted.

`graph.py:143`:

```sql
COALESCE(betweenness_main, betweenness_walk, 0)
```

`edge_features.py:129-131`:

```python
walk_scores, g_walk = betweenness(walk, k=k, seed=EDGE_BETWEENNESS_SEED)  # k = 150
main_scores = betweenness(main)[0] if main is not None else {}  # k = None, exact
```

So the single column behind feature 5, `log_betweenness`, is populated by **two different estimators on two different graphs**:

| | `betweenness_main` | `betweenness_walk` |
|---|---|---|
| Graph | main-road largest strongly-connected component | full walk network |
| Estimator | exact, all pairs | **Monte-Carlo, `k = 150` sampled sources** |
| Normalisation | per that graph | per that graph |

Three problems follow.

**3.1 The two values are not on a common scale.** `nx.edge_betweenness_centrality(normalized=True)` divides by a factor depending on the node count of the graph it is given. The main network and the walk network have different node counts, so a value of 0.01 means different things in each. `COALESCE` treats them as interchangeable, and `features.py:33` then applies one transform to both:

$$
x_5 = \log\!\left(1 + 1000 \cdot \beta_b\right)
$$

A single coefficient $\theta_5$ is fitted across a column whose units change between rows.

**3.2 The estimator switches exactly where feature 4 switches.** `betweenness_main` is non-null precisely when the segment is on the main network, which is what `is_main` (feature 4) encodes. So the change of definition in feature 5 is perfectly aligned with feature 4. Any systematic offset between the two betweenness scales is absorbed into $\theta_4$, which makes "marches prefer main roads" and "the two betweenness scales differ" statistically indistinguishable in this fit. $\theta_4$ is not estimating what its name claims.

**3.3 Off-main values carry unacknowledged sampling error.** With `k = 150` sampled sources, `betweenness_walk` is an estimate with variance, not a measurement. It is seeded, so it is reproducible, but changing `--samples` changes every off-main feature value and therefore changes $\hat{\theta}$. No part of the pipeline records that feature 5 is partly stochastic.

**Fix, cheapest first:**

1. **Compute one betweenness on one graph.** Use the main-road network exactly, and give off-main segments 0 with a boolean `on_main_network` already covered by `is_main`. One estimator, one scale, no sampling error. This is the recommended option.
2. If you want walk-network betweenness, compute it **exactly** (no `k`) and drop `betweenness_main`, accepting the runtime.
3. If sampling must stay, **do not `COALESCE`**. Carry two separate features with two coefficients, and record the sample count and seed in `backtest.json` so a run is reproducible from its artefacts.

**Interview value.** "I found that one of my twelve features was populated by two different estimators on two different graphs, with the switch aligned to another feature, so I collapsed it to one exact computation" is a stronger answer than anything else in Discipline B. It is also the kind of thing a reviewer with a statistics background will test for.

### 3.4 Two of the scope document's model-side claims are wrong, measured

I checked both against the real seed data, because they would change what you cut.

| Claim in `PIPELINE_SCOPE_CUT.md` | Measured | Verdict |
|---|---|---|
| "If most seed events lack a turnout figure, features 2 and 3 are near-collinear" | **`turnout` is filled for 65 of 65 events** | **Does not apply.** `DEFAULT_TURNOUT` almost never fires, so the `turnout_x_width` collinearity concern is not realised. Keep feature 3 |
| "The audit cites 13 Met Police notices in the seed set... a 12-parameter model on that" | **`seed/events.csv` has 65 events and 285 waypoint rows** (4.4 per event). 13 was the Met Police *subset* | **Overstated.** 65 events against 12 parameters is roughly 5.4 events per parameter: thin, but far from the stated position. The recommendation to cut to 6 to 8 features is still reasonable, but on grounds of *per-feature support*, not total sample size |

The `rain_x_main` support question is still open and still worth answering, because it decides whether feature 11 is fitted or just a prior. It needs a pipeline run:

```bash
python ingest.py && \
awk -F, 'NR==1{for(i=1;i<=NF;i++) if($i=="precip_mm_4h") c=i; next} $c>0.5' \
  data/route_research/normalised/event_context.csv | wc -l
```

If that count is 0 or 1, feature 11 is prior-only in the same way `route_model.py`'s comment already admits `dark_x_main` is. Then do what the scope document recommends and set `Effect.basis = "assumed"` rather than `"learned"`. That field already exists.

---

## 4. Scorecard, scope-filtered

Only backbone code is graded. Items in the cut list are marked rather than scored, because grading code you are deleting is noise.

| Standard | Verdict | Evidence |
|---|---|---|
| **S2.3** Package boundaries | **PASS** | `sources/` downloads, `processing/` derives, `seed/` is versioned input |
| **S2.6** Tests mirror source | **FAIL** | Only `tests/crawler/`. Zero for B |
| **S2.9** Committed data justified | **PASS** | Largest seed file 42 KB. 2 files become unjustified after §2.1 |
| **S3.1** Functions under 50 lines | **PASS** | `join_waypoints` 61, the only one over |
| **S3.2** Files under 400 lines | **PASS** | Largest 208 |
| **S3.4** Complexity <= 10 | **FAIL** | `join_waypoints` 13 |
| **S3.7** Descriptive names | **FAIL** | `p`, `a`, `r`, `d`, `g`, `o`, `z`, `c`, `t`, `w`, `n`, `m`, `er`, `grp` |
| **S3.9** Consistent conventions | **FAIL, repo-level** | B single quotes, A double. Two standards in one repo |
| **S3.11 / S3.12** DRY | **FAIL** | §2.4 |
| **S3.13** Named constants | **PARTIAL** | Good in `edge_features` and `src/config.py`; `MAX_MATCH_M`, `--hit-radius-m 250` sit locally |
| **S3.15** Object-orientation | **FAIL** | Zero classes in 1,330 lines. §5 |
| **S3.16** Type annotations | **FAIL** | **2 of 73 return types (3%)**, 122 unannotated arguments |
| **S3.19** No silent excepts | **PARTIAL** | One commented `try/except/pass`; `assert` for validation |
| **S3.20** Logging not printing | **FAIL** | **38 `print()`, 0 `import logging`** |
| **S3.22** No import-time side effects | **PASS** | All work inside `main()` |
| **S3.27** No dead code | **FAIL** | Unused `json` import; and §2 is 180 lines of it |
| **S3.29 / S3.30** Format and lint | **FAIL** | 328 findings. **58 `E701`/`E702`**, 74 `E501` |
| **S4.x** Tests | **FAIL** | Zero. §6 |
| **S5.16** Module docstrings | **PASS, exemplary** | **14 of 14** with Input/OUT contracts |
| **S5.17** Function docstrings | **FAIL** | 14 of 73 (19%) |
| **S5.18 / S5.19** Comments explain why | **PASS** | Best in the repository, though §2.3 removes one of the best examples |
| **S7.9** CI green | **FAIL, scope problem** | §4.1 |
| **Mathematical soundness** | **FAIL, one item** | Feature 5, §3 |

### 4.1 CI covers only Discipline A

`.github/workflows/test.yml`:

```yaml
      - run: python -m ruff check src/ingestion/crawler
      - run: python -m pytest tests/crawler -q
```

Both scoped to the crawler, while `pyproject.toml` commits a repo-wide ruleset. Measured:

| Command | Findings |
|---|---|
| `ruff check src/ingestion/crawler` (CI) | **0, exits 0** |
| `ruff check .` (what a reviewer runs after `pip install -e ".[dev]"`) | **410** |
| of those, in `route_research` | **167** |

A committed config is a public claim about the project's standard. 410 errors from the project's own configuration reads as a badge made green by narrowing scope. **The scope cut helps here directly:** deleting ~180 lines removes a share of those 167 findings before any formatting work begins.

---

## 5. Architecture: 13 scripts orchestrated by subprocess

`pipeline.py` is a shell script in Python. It holds relative path strings and launches each as a child process with `PYTHONPATH` injection and `cwd` switching:

```python
STEPS: dict[str, tuple[str, list[str]]] = {"boundary": ("sources/download_boundary.py", []), ...}
...
    env["PYTHONPATH"] = os.pathsep.join([str(PROJECT_ROOT), env.get("PYTHONPATH", "")])
    return subprocess.run([sys.executable, str(HERE / relative_path), *forwarded],
                          cwd=args.workdir, env=env, check=False).returncode
```

- **Steps are not importable, so they cannot be tested.** The direct cause of 1,330 lines with zero tests.
- **Steps are referenced by path string.** Renames break at runtime; no linter or IDE can follow the reference.
- **Failures arrive as exit codes.** No structured error, no run summary. Compare `run_summary.py`, which you just built for Discipline A.
- **Implicit cwd coupling.** Every default path is a bare relative string, resolving only because `pipeline.py` passes `cwd=args.workdir`.
- **Two import roots.** A imports `ingestion.*` (installed); B imports `from src.config import ...` in 6 modules, resolving only because the repo root is on the path.

**The fix mirrors `ProtestSource`.** Each step becomes an importable function with a typed context:

```python
@dataclass(frozen=True)
class StepContext:
    """Resolved directories for one pipeline run.

    Steps take paths from here rather than from cwd-relative defaults,
    so a step can be called from anywhere, including a test.
    """

    workdir: Path

    @property
    def raw(self) -> Path:
        return self.workdir / "raw"

    @property
    def normalised(self) -> Path:
        return self.workdir / "normalised"


@dataclass(frozen=True)
class StepResult:
    """What a step produced, for the run summary."""

    name: str
    outputs: tuple[Path, ...]
    rows_written: int
    warnings: tuple[str, ...] = ()


class PipelineStep(Protocol):
    """One unit of the route research pipeline."""

    name: str
    requires: tuple[str, ...]

    def run(self, context: StepContext) -> StepResult: ...
```

Then `pipeline.py` loses `subprocess`, `PYTHONPATH` surgery and `cwd` switching, and you can say one sentence about both halves of your ingestion: *every source implements `ProtestSource`, every step implements `PipelineStep`, both report into a `RunSummary`.*

**Do this after the scope cut.** Nine steps are cheaper to convert than ten, and you will not write a `PageviewsStep` you then delete.

---

## 6. The test suite B should have, post-cut

Cutting first removes 4 of my original 35 test targets and retargets the most important one. **31 tests on code with named consumers.**

| Module | Functions | Tests |
|---|---|---|
| `edge_features.py` | `parse_width`, `parse_lanes`, `estimate_width`, `as_list`, `flag`, `undirected` | **9** |
| `download_weather.py` | `date_ranges`, `split_by_source` | **5** |
| `normalize.py` | `tag`, `safe_float`, `is_approved`, `make_streets`, **history counting** | **6** |
| `download_boundary.py` | `parse_zones`, `zone_of`, `build_polygon` | **4** |
| `cause_targets.py` | `haversine_m`, `locate`, `hit_rates` | **4** |
| `event_context.py` | `parse_start`, `derive_cause` | **3** |
| `seed_coordinates.py` | `review_rows` | **2** |
| ~~`salience`~~ | cut with §2.1 | ~~4~~ |

### The retargeted leakage test

`normalize.py` computes `n_published_route_examples` over **all** events, then warns that backtests must use only prior events. That count feeds feature 10, `history`, which is fitted. Pin the promise where it matters:

```python
def test_history_counts_exclude_the_event_being_predicted() -> None:
    """Look-ahead regression test for feature 10 (`history`).

    n_published_route_examples is computed over the full corpus. A backtest
    fold must never count the fold's own event, or the model sees its own
    label as a feature.
    """
    routes = [
        {"event_id": "E1", "segment_id": "1:2:0", "event_date": "2026-01-01"},
        {"event_id": "E2", "segment_id": "1:2:0", "event_date": "2026-06-01"},
    ]
    counts = history_counts_before(routes, before="2026-06-01")
    assert counts["1:2:0"] == 1  # E1 only; E2 is the event under test
```

If `history_counts_before` does not exist yet, that is the finding: the warning says to do this, and nothing enforces it. Writing the test creates the function.

### The betweenness consistency test, for §3

```python
def test_betweenness_uses_one_estimator_on_one_graph() -> None:
    """Feature 5 must not mix an exact main-network score with a sampled walk score."""
    features = build_edge_features(context, samples=50)
    exact = build_edge_features(context, samples=None)
    pd.testing.assert_series_equal(features.betweenness, exact.betweenness)
```

That test fails today. It passes once §3 is fixed, which is exactly what a regression test is for.

### The geospatial smoke test

```python
def test_boundary_polygon_is_built_in_a_metric_crs() -> None:
    """A 300 m buffer must be 300 metres, not 300 degrees."""
    stations = [
        {"lat": 51.5074, "lon": -0.1278},
        {"lat": 51.5155, "lon": -0.1410},
        {"lat": 51.4980, "lon": -0.1195},
        {"lat": 51.5200, "lon": -0.1050},
    ]
    polygon = build_polygon(stations, buffer_m=300.0, ratio=1.0)
    area_km2 = gpd.GeoSeries([polygon], crs="EPSG:4326").to_crs("EPSG:27700").area.iloc[0] / 1e6
    assert 2 < area_km2 < 20  # degrees-as-metres would give a polygon the size of Europe
```

---

## 7. Defects

### B1. `cause_targets.py:105` crashes on an empty targets table

```python
located = [locate(r, geocodes, osm) for r in targets.itertuples()]
targets["lat"], targets["lon"], targets["location_source"] = zip(*located)
```

**Reproduced:** `ValueError: not enough values to unpack (expected 3, got 0)`. Reachable on a fresh workspace before the seed is populated, which is what a reviewer hits first.

```python
if targets.empty:
    logger.warning("no cause targets in %s; writing an empty table", args.targets)
    located: list[tuple[float, float, str]] = []
else:
    located = [locate(row, geocodes, osm) for row in targets.itertuples()]
targets["lat"], targets["lon"], targets["location_source"] = (
    zip(*located, strict=True) if located else ([], [], [])
)
```

### B2. `assert` used for argument validation

`download_osm.py:59` (`S101`): `assert a.west < a.east and a.south < a.north`. Stripped under `python -O`, after which an inverted bbox silently downloads the wrong area. Same bug class as A5; fix it the same way with a typed exception.

### B3. Four `zip()` calls without `strict=`

`normalize.py:100`, `normalize.py:108`, `cause_targets.py:79`, `cause_targets.py:105` (`B905`). Silently truncates to the shorter sequence.

### B4. `normalize.py:100` builds the same list twice

`grp.to_dict('records')` runs twice per event group. Hoist it.

### B5. `normalize.py:113` writes a value it then overwrites

`sequence_index` is set to the global `len(routes)`, then corrected to a per-event counter at lines 120-121. Your own comment says it should be per event. Any code reading `routes` between those points sees wrong data. Build the counter while appending.

### B6. `normalize.py` writes `segment_features.csv` twice

Line 60 in `make_streets`, line 153 after the merge. The first write is dead I/O on every run.

### B7. Unused import, dead tuple field

`json` at `normalize.py:14` (`F401`). `STEPS`' always-empty `prefix`.

---

## 8. Formatting: the worst readability problem in the repository

58 `E701`/`E702` across B, 24 in `normalize.py` alone, which is also where the project's most important logic lives:

```python
def write(rows, path, cols):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def is_approved(d):
    return str(d.get("status", "")).lower().strip() == "approved"
```

Three violations at once: no whitespace around operators, multiple statements per line, single-character names for domain objects (`r` is a review row on line 78 and a route dict on line 121).

This matters beyond its severity. A reviewer who opens `met_police.py` (now clean, annotated, docstringed) and then `normalize.py` sees two people's work in one repository, which undercuts the attribution story S5.11 and S8.2 require.

```bash
ruff format src/ingestion/route_research     # resolves the 58 E701/E702 and most E501
ruff check src/ingestion/route_research --fix
```

Then rename the one-letter identifiers, `normalize.py` first. **Run this after the scope cut**, so you are not formatting 180 lines you are about to delete.

---

## 9. Typing and documentation

| Metric | B |
|---|---|
| Module docstrings | **14 of 14 (100%)** |
| Function docstrings | 14 of 73 (**19%**) |
| Functions with return types | **2 of 73 (3%)** |
| Unannotated arguments (`ANN001`) | **122** |
| `print()` | **38** |
| `import logging` | **0** |

The parsers need docstrings most, because the domain knowledge exists only in their thresholds:

```python
def parse_width(value: object) -> float | None:
    """Parse an OSM `width` tag into metres, or None when implausible.

    OSM width tags are free text. Observed forms in central London include
    '5', '5 m', '5.5m', '3;4' (take the first), "12'" and '12 ft' (feet).
    Values outside 0.5 to 80 m are rejected as tagging errors rather than
    propagated into feature 2 (`log_width`).
    """
```

Note the docstring names the downstream feature. Post-scope-cut, every function in B can do that, and it is the cheapest way to prove the pipeline has no dead branches.

Two of the 38 prints are scientific-validity warnings that currently scroll away:

```python
print("WARNING: review file missing; no route segment labels will be generated.")
print(
    "WARNING: For backtesting, recompute historical counts using ONLY events before the test event date."
)
```

Both belong in `StepResult.warnings`, surfaced in the run summary.

---

## 10. Checked and cleared

Verified rather than assumed, so you can answer confidently.

**Geospatial CRS discipline.** I looked specifically for the classic error of buffering or measuring in EPSG:4326 degrees. **It is not present.** `build_polygon` projects to EPSG:27700 before `concave_hull` and `buffer`. `download_landmarks` projects to a metric CRS before centroids. `join_waypoints` uses `ox.project_graph` and measures with `math.hypot` in projected metres. `zone_flags` runs `sjoin` with both layers in 4326, where `intersects` is topological so CRS does not affect correctness. This is the thing most people get wrong, throughout. Say so.

**Weather timezone handling.** I expected a naive-versus-aware key mismatch silently emptying every weather column. `download_weather.py:64` requests `timezone=Europe/London` and Open-Meteo returns naive local ISO strings, so both sides match. **Not a bug.** One narrow edge survives: on DST-transition Sundays, naive wall-clock hours are ambiguous or missing and `index_weather` dedupes by key, so a 4-hour window can draw on 3 or 5 real hours. Marches rarely start at 01:00. One comment, not a code change.

**`turnout` collinearity.** The scope document's feature-3 concern assumed most events lack a turnout figure. **65 of 65 have one.** Not realised; keep feature 3.

**Sample size.** The scope document's "13 Met Police notices" is the Met subset, not the corpus. **65 events, 285 waypoint rows.** The 12-parameter concern stands but is much weaker than stated.

**Seed provenance.** Measured from `source_url`, this reorders the scope document's source cuts:

| Domain | Seed events | Verdict |
|---|---|---|
| **marble-arch.london** | **29 of 65 (45%)** | The scope document marked this `[verify]` and suggested dropping it. **It is your largest single source.** Commit `ca9100d` restoring it was the right call |
| news.met.police.uk + met.police.uk | 15 | Core, as expected |
| palestinecampaign.org | 12 | Justifies pruning organisers to PSC |
| TfL, OSAC | **0** | Drop confirmed |
| 10 one-off domains | 1 each | Hand-entered, no crawler involved |

Also measured: **`observed_route_verified` is `no` for all 65 events.** Every seed route is a *planned* route. Your provenance labelling already says this, and it bounds what the model can honestly claim. Lead with it rather than letting a reviewer discover it.

---

## 11. Work plan, scope-cut first

| Step | Work | Clears | Effort |
|---|---|---|---|
| **B-0** | **Scope cut §2.** Delete pageviews and salience, 18 `event_context` columns, 6 unconsumed `edge_features` columns, 3 dead `load.py` tables, the `hijridate` dep, 2 seed files. Move the Fruin paragraph to `docs/` | S3.27, shrinks everything below | **3 h** |
| **B-1** | Fix feature 5 (§3): one estimator, one graph. Add the consistency test | **Mathematical soundness** | **3 h** |
| **B-2** | `ruff format` plus `--fix` across what remains. Rename one-letter identifiers, `normalize.py` first | S3.9, S3.29, S3.30 | 2 h |
| **B-3** | Fix defects B1 to B7, each with a regression test | 7 defects | 3 h |
| **B-4** | `tests/route_research/`, the 31 tests in §6, **including the retargeted leakage test** | S4.1 to S4.11, S2.6 | 1 day |
| **B-5** | Widen CI to `ruff check .` and bare `pytest`. Until then, explicit `per-file-ignores` with a comment | **S7.9** | 1 h |
| **B-6** | Answer the `rain_x_main` support question. If unsupported, set `Effect.basis = "assumed"` | Mathematical honesty | 1 h |
| **B-7** | Type annotations and docstrings across the surviving functions, each naming its downstream feature | S3.16, S5.17 | 1 day |
| **B-8** | `logging` instead of `print`. Promote the two warnings into `StepResult.warnings` | S3.20 | 2 h |
| **B-9** | Extract `PipelineStep` / `StepContext` / `StepResult`. Remove `subprocess` and `PYTHONPATH` injection | S3.15, S3.22, S3.24 | 1 day |
| **B-10** | Unify the import root, consolidate constants, one distance method | S3.13, S3.14, S3.11 | 4 h |

**Sequencing rationale.** B-0 first and nothing before it: every later step is cheaper against a smaller codebase, and three of them (B-2, B-4, B-7) scale directly with line count. B-1 is second because it is the only finding that makes the *model* wrong rather than the code untidy, and it is your best interview material in this discipline. B-5 matters more than one hour suggests, because `ruff check .` is a likely reviewer action.

**Strategic caveat, unchanged and now sharper.** B is majority Claude-authored, and after the scope cut it is ~1,150 lines. Per S8.2 and S8.3 your reading path should centre on Discipline A, which is sole-authored by you. Do **B-0 through B-5** (about 2.5 days: they remove dead code, fix the one real mathematical defect, and clear an official criterion). Treat **B-7 and B-9 as optional**. Do not spend two more days perfecting code you must then label as not primarily yours.

---

## 12. What is already good

Still true after the scope cut, and worth leading with.

- **Provenance discipline that is genuinely rare.** `label_provenance='INFERRED_SHORTEST_PATH_BETWEEN_APPROVED_PLANNED_WAYPOINTS'`. The docstring states that waypoints are *planned*, not observed. The code refuses to join across a missing intermediate waypoint, with a comment saying that doing so would fabricate a route. Measured: `observed_route_verified` is `no` for all 65 events, and your schema says so rather than hiding it. Most applicants would have interpolated and reported a better number.

- **Refusal to fabricate.** Missing review file produces an empty template and a warning, not on-the-fly geocoding. `seed_coordinates.py` writes `status=missing` and names the waypoints needing human review. A human-in-the-loop gate with an `approved` status is real data engineering, and it is the answer to "how do you know your labels are right?"

- **Leakage awareness, documented before it was asked about.** Two explicit warnings about temporal leakage in your own feature pipeline. §6 now turns the important one into an enforced test.

- **Correct CRS handling throughout.** Verified in §10. The most common geospatial error, absent.

- **Fail-loud where it matters.** `make_streets` raises on an unexpected `MultiLineString`. `download_boundary` exits if fewer than three stations are found, because that means TfL changed their response format. Both carry a comment explaining why.

- **Module docstrings with Input/OUT contracts, 14 of 14.** Better than Discipline A managed, and the template for the whole repo.

- **Domain reasoning cited in code.** Pavement widths separated from carriageway widths in `estimate_width`, which survives the cut and feeds feature 2. Counter-protest keywords ordered before the causes they oppose, with a comment saying why, in a `derive_cause` that is load-bearing for all 65 events.

- **Thoughtful API economy.** `date_ranges` merges event dates into continuous ranges to minimise requests; `split_by_source` routes each piece to the archive or forecast endpoint by actual API coverage. Careful work against a real external constraint.