# Pipeline scope cut: what the crawler must do, and what to delete

**Project:** `crislu05/london-protest-predictor`
**Date:** 2026-11-07
**Purpose:** reduce the system to the smallest pipeline that defensibly supports the route model, and remove everything that exists only to look impressive.

**Method and caveat.** This review was done by reading the repository through the project's synced index, not a clone. File and function references are reliable; line numbers are not, and a handful of claims are marked **[verify]** where I could not read the whole function. Verify those with `grep` before deleting anything.

---

## 1. The finding that reframes the whole question

**The crawler does not feed the model. Nothing in the training path reads crawler output.**

Trace the training data backwards:

| Step | File | Reads |
|---|---|---|
| Features | `src/models/features.py::feature_vector` | graph segment attributes, `context`, `history`, `targets` |
| Labels | `src/models/labels.py::read_events` | `mapdata.historical_events()`, `event_context.precip_mm_4h`, `event_context.daylight_after_start_h` |
| Those tables | `src/database/load.py::TABLES` | `normalised/events.csv`, `normalised/waypoints_approved.csv`, `normalised/route_segment_labels.csv`, `normalised/event_context.csv`, `normalised/cause_targets.csv` |
| Those files | `processing/normalize.py` | `seed/events.csv`, `seed/waypoints.csv`, `coordinate_review.csv` |
| `coordinate_review.csv` | `processing/seed_coordinates.py` | `seed/waypoint_geocode_overrides.json`, `seed/geocode_cache.json`. Its docstring states plainly: *no geocoding requests are made* |

The chain terminates in **hand-curated, version-controlled seed CSVs**. It never touches `src/ingestion/crawler/`.

Confirm the other direction: `ingest.py::STEPS` is

```
boundary, osm, landmarks, seed-coords, normalize, edge-features,
weather, pageviews, event-context, cause-targets, database
```

There is no crawler step. `src/ingestion/crawler/cli.py` is a separate entry point writing to `data/<run_id>/<platform>/records.json`, and `src/database/load.py::TABLES` has no entry for it.

### What this means

The crawler is currently a **parallel artefact**: roughly 2,500 lines, nine sources, Cloudflare evasion, image downloading, and a custom HTTP client, producing files that no model, no table and no app page consumes. Every defect in it is therefore a defect in dead weight.

You have two honest options. Only one of them is small.

| Option | Description | Verdict |
|---|---|---|
| **A. Wire it in** | Make the crawler the producer of `seed/events.csv` and `seed/waypoints.csv` | Rejected. Geocoding and route reconstruction are hand-reviewed by design, correctly so. Automating them would make the labels worse and the provenance weaker |
| **B. Scope it down** | Keep the crawler as the *discovery* stage that proposes candidate events for human review, and delete everything that does not serve that | **Recommended** |

Option B gives the crawler one sentence of purpose, which is what the review question "what does this do?" wants:

> **The crawler discovers published London march plans and emits candidate `(date, cause, ordered waypoint names, turnout estimate, source URL)` rows for human geocode review. It extracts nothing else.**

---

## 2. The model's actual input contract

This is the test every crawled field must pass. From `features.py::NAMES`:

$$
P(b \mid a) = \frac{\exp\!\big(\theta^{\top} x(a,b,c,d)\big)}{\sum_{b' \in N(a)} \exp\!\big(\theta^{\top} x(a,b',c,d)\big)}
$$

The 12 components of $x$ and their data origin:

| # | Feature | Source | From crawler? |
|---|---|---|---|
| 1 | `progress` | graph geometry + destination | no |
| 2 | `log_width` | `edge_features.csv` (OSM) | no |
| 3 | `turnout_x_width` | OSM + `events.csv` turnout | **turnout only** |
| 4 | `is_main` | OSM | no |
| 5 | `log_betweenness` | OSM + NetworkX | no |
| 6 | `turn` | graph bearings | no |
| 7 | `target_pull` | `cause_targets.csv` | no |
| 8 | `royal_park` | legal zones | no |
| 9 | `restricted` | legal zones | no |
| 10 | `history` | past routes | **waypoints only** |
| 11 | `rain_x_main` | Open-Meteo `precip_mm_4h` | no |
| 12 | `dark_x_main` | astral `daylight_after_start_h` | no |

And from `labels.py::read_events`, the context dict passed into every feature vector is exactly three keys:

```python
{'turnout': ..., 'precip_mm_4h': ..., 'dark_fraction': ...}
```

### The irreducible crawler output

A crawled record can influence $\theta$ only through:

1. an **ordered sequence of named waypoints** that survives geocode review and snaps to the walk graph
2. the event **date** (keys weather, daylight, salience, and ordering)
3. the **cause** (keys `cause_targets`, destination candidates, turnout median)
4. a **turnout** figure
5. a **source URL** for provenance

That is five fields. `ProtestRecord` has nineteen.

---

## 3. Cut list

### 3.1 Fields on `ProtestRecord` that cannot reach the model

`src/ingestion/crawler/models.py`

| Field | Status | Reason |
|---|---|---|
| `route_streets: list[str]` | **cut** | Produced by `parse_route_streets()`. Street name strings are never geocoded, never snapped, never read by `normalize.py`. The pipeline uses *waypoints*, not street names. This is a parse that goes nowhere |
| `counter_protest_expected: bool` | **cut** | No feature, no table, no UI consumer found **[verify]**. `parse_counter_protest_flag` exists solely to populate it |
| `estimated_participants_min/max/text` | **keep one** | Collapse three fields to one `turnout_estimate: int \| None`. The model takes a single integer. The min/max/text triple is never read as a range |
| `raw_excerpt: str` (1200 to 2000 chars) | **cut from the record** | A text dump carried through JSON and Parquet for every record. If you want provenance, keep the URL. If you want debugging, log it |
| `latitude` / `longitude` | **cut** | Always `None` from every source read **[verify]**. The crawler does no geocoding, by design |
| `location_label` | **cut** | Set to the literal `"London"` as a fallback in `organizers/crawler.py`. A constant is not data |
| `extra: dict[str, Any]` | **cut** | Untyped escape hatch holding `images`, `published_at`, `description`, `listing_source`, `organizer`, and arrest metadata. None of it is consumed. An untyped dict in a dataclass is the thing a reviewer asks about first |
| `event_end` | **cut** | Not used by `event_context.py`, which takes `event_date` and `start_time` only |
| `form_up_location` | **keep** | This is waypoint 1. It is the one location field with a real downstream role |
| `route_text` | **keep** | The raw text a human reads when entering waypoints. The *parsed* `route_streets` goes; the text stays |

**Proposed record:**

```python
@dataclass(frozen=True)
class ProtestRecord:
    """A candidate march discovered from a published source, pending geocode review."""
    source: str
    source_id: str
    url: str
    title: str
    fetched_at: str
    event_start: str | None      # ISO date, keys weather/daylight/salience
    form_up_location: str | None # first waypoint, as published
    route_text: str | None       # the route sentence, for human waypoint entry
    turnout_estimate: int | None # context['turnout']
```

Nineteen fields to nine, and every one has a named consumer.

### 3.2 Whole features to delete

| Feature | File | Why it goes |
|---|---|---|
| **Met Police image crawling** | `met_police.py::_crawl_article_images`, plus `media_dir` plumbing through `pipeline.py` and `cli.py`, plus `MediaDirectoryNotConfiguredError` | Downloads press photos into `data/`. No model reads an image. No app page shows one. This is the clearest demo-only feature in the package, and it is also the one that puts third-party photographs on disk |
| **Arrest metadata parsing** | `organizers/parse_event_page.py::parse_arrest_metadata` | Writes into `extra`. No consumer **[verify]** |
| **Parquet output** | `pipeline.py::_write_parquet` | The zero-byte empty-file bug and the f-string SQL both live here. Nothing reads the Parquet; `load.py::TABLES` has no entry for it. Delete the method, the DuckDB import in the crawler, and both defects with it |
| **Per-run folder machinery** | `pipeline.py` run dirs, `run_progress.json`, `_rebuild_aggregate`, `flat_json`, incremental summary rewriting after every platform | Resumable multi-run bookkeeping for a crawl that produces one reviewable CSV. Replace with: write one `candidates.csv`, print a summary |
| **Legacy class aliases** | `sources/__init__.py` exports both `MetPoliceCrawler` and `MetPoliceSource`, and `crawler.py` ends with `OrganizerSiteCrawler = OrganizerSiteSource` | Two public names for one class, kept for a migration that is finished. A reviewer reads this as dead code |
| **Hardcoded tier-1 list** | `cli.py::_platform_choices` lists `["met_police", "osac", "tfl_road_disruption", "marble_arch_security"]` | Duplicates `platforms.build_platform_catalog()`. Derive it |

### 3.3 Sources to drop

Apply the test from section 2: *does this source publish an ordered route that a human can turn into waypoints?*

| Source | Publishes a route? | Verdict |
|---|---|---|
| **Met Police notices** (`met_police.py`) | Yes. `_extract_section_12_route` parses the prescribed route from Section 12 Public Order Act notices, five known phrasings | **Keep. This is the core of the project** |
| **Organiser sites** (`organizers/`) | Sometimes. Assembly point reliably, full route occasionally | **Keep, but prune the site list.** See below |
| **OSAC** (`osac.py`) | Partially. Demonstration alerts carry a `route`/`location` field | **Keep only if it has produced a seed route.** Check `seed/events.csv` `source_url` column. If no row came from OSAC, drop it |
| **TfL road disruptions** (`tfl.py`) | **No.** `_is_protest_related` keyword-filters disruption notices. A closure notice is a consequence of a march, published without an ordered route, usually after the fact | **Drop.** It cannot produce a label. Its only possible role is map decoration, and `tfl_disruptions` is not in `load.py::TABLES` |
| **Marble Arch security** (`marble_arch_security.py`) | **[verify]** | A single building's security updates. Unless it produced seed rows, drop it |
| **Police.uk crime, ACLED** | Not in the crawler at all | Already absent from `ingest.py::STEPS`. The README still advertises `crimes` and `acled_events` tables. **Delete those README claims** |

**On the organiser sites.** `ORGANIZER_SITES` holds at least `psc`, `cnd`, `counterfire` and more. Each carries its own pagination style, slug prefix, `include_actionnetwork`, `include_date_posts`, `extra_domains`, `slug_post_prefixes`, `include_listing_slugs`. That is eight configuration knobs per site to handle sites' quirks.

Run the crawler and count records per site. Any site with **zero records in the last run and zero rows in `seed/events.csv`** is config complexity bought with nothing. My expectation is that PSC carries most of the signal and the tail returns empty. Keep the sites that produce; delete the configs that do not, and delete the config fields that no surviving site sets.

---

## 4. Where the crawl is more complicated than the data justifies

| Machinery | File | Assessment |
|---|---|---|
| `cloudscraper` Cloudflare evasion | `client.py` | You are crawling public police and campaign pages a handful of times. Evading a bot challenge to do it is a question you do not want asked. Try plain `requests` with a stated User-Agent and a `robots.txt` check first. If a site genuinely blocks you, that site's records belong in a committed fixture, not in a live crawl |
| `curl` subprocess SSL fallback | `client.py` (ruff `S603`) | A subprocess dependency on an external binary, for one host's certificate chain. Breaks on Windows and in slim containers. Either scope a documented SSL context to that host, or drop the host |
| Hardcoded macOS Chrome User-Agent | `client.py` | Says "I am pretending to be a browser". Replace with an honest identifying string |
| Pagination across `max_list_pages=4..6` and `max_detail_fetches=35` per site | `organizers/sites.py` | Nine sites times up to 35 detail fetches is roughly 300 HTTP requests per run, to find a handful of candidate marches. Cut the depth hard |
| Four duplicated JSON-LD extraction loops | `met_police.py` x3, `parse_event_page.py` | One `iter_json_ld()` generator in `parse_utils.py` |

---

## 5. The same problem on the model side

You asked specifically about things that do not make rigorous mathematical sense. Two live on the model side and are worth cutting in the same pass, because a reviewer will find them.

**5.1 Features that are never fitted.** `route_model.py` comments state it outright for one of them:

> `dark_x_main` gets a real prior (+0.5) because most training marches finish in daylight; **with no dark marches the fit leaves it at this prior.**

A coefficient that no training example can move is not a learned parameter. It is a hand-set constant wearing a $\theta$ label. Check the same for `rain_x_main`: count training events with `precip_mm_4h > 0.5`. If that count is 0 or 1, the feature is prior-only too.

**Recommendation.** Keep the features if you want, but have `fit()` record which coefficients had zero effective support, and surface them in the UI as `basis="assumed"` rather than `"learned"`. The `Effect.basis` field already exists for exactly this. Honesty here is a strength, not a weakness: it is the difference between a hackathon demo and someone who understands their own estimator.

**5.2 `turnout_x_width` collinearity.** From `features.py`:

```python
dw = max(0.0, float(context.get('turnout') or 10000))
...
math.log(max(1, dw)) * math.log(b.width)
```

When `turnout` is missing, `dw` falls back to `DEFAULT_TURNOUT`. For every such event the feature becomes

$$
\log(10000)\cdot\log(w_b) = 9.21 \cdot \log(w_b)
$$

which is an exact scalar multiple of feature 2, `log_width`. If most seed events lack a turnout figure, features 2 and 3 are near-collinear across the training set, the likelihood surface is flat along that direction, and only the L2 prior pins the two coefficients down. The split between them is then an artefact of `PRIOR`, not of the data.

**Check:** count non-null `turnout` in `seed/events.csv`. If it is below roughly half, either drop `turnout_x_width` or restrict the fit to events with an observed turnout.

**5.3 Count your parameters.** 12 features. The audit cites 13 Met Police notices in the seed set. Even counting every junction choice as an observation, the choices within one march are strongly dependent, so the effective sample size is closer to the number of marches than the number of junctions. A 12-parameter model on that is held up almost entirely by `PRIOR` and `LOGIT_REG`. Dropping to 6 to 8 features with real support is a stronger result and a much better interview answer than 12 features where four are priors.

---

## 6. The target pipeline

```
                     HUMAN REVIEW GATE
                            |
  [discover] ---------------+--------------> [build] ------> [model]
                            |
  crawler                   |                ingest.py        train
  Met Police notices        |                                 backtest
  organiser events          |
      |                     |
      v                     v
  candidates.csv  -->  seed/events.csv
  (date, cause,        seed/waypoints.csv
   route_text,         seed/waypoint_geocode_overrides.json
   turnout, url)       (reviewed, committed)
```

One rule, stated in the README: **the crawler proposes, a human approves, the build is deterministic from committed seed files.**

That rule is already true of the code. It is just not written down, and the crawler is doing nine other things that obscure it.

### Revised `ingest.py` step list

Unchanged, except that `seed-coords` gains a documented upstream: `python -m ingestion.crawler discover` writes `candidates.csv`, a human promotes rows into `seed/`, and the build runs. The crawler stays out of `ingest.py`, deliberately and visibly.

---

## 7. Execution order

| # | Work | Deletes | Effort |
|---|---|---|---|
| 1 | Run the crawler once. Record records-per-source and rows-per-source in `seed/events.csv`. **This table decides steps 2 and 3** | nothing yet | 30 min |
| 2 | Drop TfL, Marble Arch, and every zero-yield organiser site | 2 source files, N site configs, the unused `OrganizerSiteConfig` fields | 1 h |
| 3 | Shrink `ProtestRecord` to 9 fields. Delete `parse_route_streets`, `parse_counter_protest_flag`, `parse_arrest_metadata`, and the `extra` dict | 3 parsers, ~200 lines | 2 h |
| 4 | Delete image crawling and all `media_dir` plumbing | `_crawl_article_images`, 1 exception class, 3 signatures | 1 h |
| 5 | Delete Parquet writing and per-run folder machinery. Output one `candidates.csv` | bugs A7 and A8 disappear with it | 2 h |
| 6 | Replace `cloudscraper` and the `curl` fallback with `requests` plus `robots.txt`. Commit HTML fixtures for anything that then fails | `S603`, `S606`, the User-Agent question | 3 h |
| 7 | Delete legacy `*Crawler` aliases, derive `_platform_choices` from the catalog, fold the four JSON-LD loops into `iter_json_ld` | duplication | 2 h |
| 8 | Fix the README: remove `crimes`, `tfl_disruptions`, `acled_events`, `protest_signals` from the table list unless `load.py` actually creates them. Remove unbuilt sources from the DEVPOST data table | false claims | 1 h |
| 9 | Model side: audit `rain_x_main` support, test `turnout` null rate, cut features without support | 4 of 12 features, possibly | 3 h |

Steps 2 to 7 run before writing tests. Testing a module you are about to delete is wasted work, and the test count target in the standards doc is much easier to hit against 9 record fields and 2 sources than against 19 and 9.

---

## 8. What this buys you

**Before:** nine sources, nineteen record fields, three output formats, Cloudflare evasion, image downloads, and a README claiming four database tables that do not exist. When the reviewer asks "why does the crawler download images?", there is no good answer.

**After:** two sources, nine fields, one CSV, one sentence of purpose, and a human-review gate you can defend on provenance grounds. When the reviewer asks "why is the crawler not in `ingest.py`?", the answer is the strongest thing you can say in a data interview:

> Because the labels are hand-reviewed geocodes. Automating that step would put unverified coordinates into the training set, and I would rather have 13 marches I can defend than 200 I cannot.

That is a real engineering judgement, made visible by cutting everything that was hiding it.

---

## 9. Items to verify before deleting

```bash
# Does anything read these?
grep -rn "route_streets\|counter_protest_expected\|raw_excerpt" src/ --include=*.py | grep -v "crawler/"
grep -rn "\.extra\[" src/ --include=*.py
grep -rn "protest_signals\|tfl_disruptions\|acled_events\|crimes" src/ --include=*.py

# Which sources actually produced seed rows?
cut -d, -f<source_url_col> src/ingestion/route_research/seed/events.csv | sort | uniq -c

# Turnout null rate (feature 3 collinearity)
python -c "import csv;r=list(csv.DictReader(open('src/ingestion/route_research/seed/events.csv')));print(sum(1 for x in r if x.get('turnout')),'/',len(r))"

# Rain support (feature 11)
awk -F, 'NR>1 && $<precip_col> > 0.5' data/route_research/normalised/event_context.csv | wc -l
```

---

## Progression log

| Date | Step | Notes |
|---|---|---|
| 2026-11-07 | 1 | Seed evidence: 65 events, turnout 65/65; seed URLs — marble-arch.london 29, met 15, PSC 12; **0** OSAC/TfL → drop those sources |
| 2026-11-07 | 2–8 | Scope reduction implemented: 9-field `ProtestRecord`, `candidates.csv` pipeline, Met + 4 organiser sites, plain `requests` client, tests + CI |
| 2026-11-07 | fix | Restored `marble_arch_security` (29 seed URLs); organiser sites cut to PSC only; planning docs moved to `docs/internal/` |
| 2026-11-07 | 9 | `route_model.fit` records `prior_only` for `rain_x_main` / `dark_x_main` when training support &lt; 2 events |