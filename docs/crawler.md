# Discipline A: Web Crawler and Ingestion, Full Audit

**Scope:** `src/ingestion/crawler/**` (18 modules), `src/ingestion/__main__.py`, `ingest.py`
**Size:** 2,347 lines, 134 functions and classes
**Authorship:** 100% Cris Lu (sole author, verified via `git log --format='%an' -- src/ingestion/crawler`)
**Audited against:** `MLH_SUBMISSION_STANDARDS.md` v1.0
**Date:** 2026-11-07, commit `6927a1e`

---

## 0. Method

Three evidence sources, so nothing here is opinion dressed as fact:

1. **Static analysis.** `ruff check --select E,F,W,B,SIM,C90,UP,N,A,RET,ARG,PTH,TRY,EM,DTZ,S --line-length 100`. 174 findings, inventoried in Section 11.
2. **Manual read.** Every line of all 18 modules.
3. **Executable verification.** Each correctness claim in Section 2 was reproduced in an isolated script. Outputs are quoted verbatim. No bug is reported on suspicion alone.

---

## 1. Scorecard

| Standard | Verdict | Evidence |
|---|---|---|
| **S3.1** Functions under 50 lines | **FAIL** | `pipeline.run` 84, `cli.main` 77. 2 of 134 |
| **S3.2** Files under 400 lines | **FAIL** | `met_police.py` 493 |
| **S3.4** Complexity <= 10 | **FAIL** | 3 functions: `ingest.main` 14, `organizers/crawler._is_candidate_url` 14, `marble_arch._is_protest_entry` 11 |
| **S3.5** One responsibility per function | **PARTIAL** | Mostly good. `pipeline.run` orchestrates, writes, aggregates and reports |
| **S3.7** Descriptive names | **PASS** | Strong throughout. No cryptic abbreviations |
| **S3.8** One vocabulary per concept | **PARTIAL** | `source` / `platform_id` / `platform` used interchangeably for one concept |
| **S3.11** No copy-pasted blocks | **FAIL** | JSON-LD extraction duplicated 4x. `DATE_POST_RE` defined twice. Month-parse block duplicated in `date_window` |
| **S3.12** Shared logic extracted | **FAIL** | No shared JSON-LD helper, no shared "first regex that matches" helper (used 4x) |
| **S3.13** Named constants | **FAIL** | ~20 inline magic numbers: `[:1500]`, `[:2000]`, `body[:800]`, `max_pages=20`, `[:60]`, `w_2400`, `len(chunk) > 20` |
| **S3.15** Object-orientation | **PARTIAL, highest-value fix** | Classes and a dataclass exist, but the four crawlers share no base class or Protocol and have four incompatible `fetch_records` signatures. See Section 3 |
| **S3.16** Type annotations | **PARTIAL** | Good coverage, but `get_json -> object`, bare `dict` without parameters in 11 places, `source_id` rebound to two types |
| **S3.19** No bare or silent excepts | **FAIL** | `S110` try/except/pass, 2x `S112` try/except/continue, `SIM105`, all in `organizers/crawler.py`. Plus `assert` as a runtime guard (`S101`) |
| **S3.20** Logging not printing | **FAIL** | 14 `print()` calls, `import logging` appears 0 times in the entire repo |
| **S3.22** No import-time side effects | **FAIL** | `platforms.py` mutates a module global in a top-level `for` loop. `__main__.py` mutates `sys.path` at import |
| **S3.23** Timeout and retry | **PARTIAL** | Timeouts yes. **No retry or backoff anywhere**, despite crawling 9 flaky public sites |
| **S3.24** Portable paths | **PASS** | `pathlib` used correctly throughout |
| **S3.25** No commented-out code | **PASS** | Clean |
| **S3.27** No dead code | **FAIL** | `filters.py:155` branch is provably unreachable. `F401` unused import. `ARG002` unused parameter. 2x `ARG005` |
| **S3.28** No secrets | **PASS** | Credentials read from env correctly |
| **S3.29 / S3.30** Format and lint clean | **FAIL** | 174 ruff findings, 27 lines over 100 chars |
| **S4.x** Tests | **FAIL** | Zero tests. This package is the most testable in the repo |
| **S5.16** Module docstrings | **FAIL** | 4 of 18 modules |
| **S5.17** Function docstrings | **FAIL** | ~3 of 134 functions, **2.6% coverage**. `client.py` 0 of 12, `met_police.py` 0 of 25, `organizers/crawler.py` 0 of 16 |
| **S5.18 / S5.19** Comments explain why | **PARTIAL** | The few comments present are excellent (`client.py:104`, `met_police.py:40`). There are only 6 in 2,347 lines |

**Headline:** the architecture and naming are better than the standards document assumed from metrics alone. What fails is **everything a reviewer checks first**: tests, docstrings, logging, and four real correctness bugs.

---

## 2. Correctness defects (all reproduced)

These matter most. A reviewer who finds a logic bug you did not know about controls the rest of the interview. Fix these first, then you can raise them yourself as evidence of rigour.

### A1. Operator precedence inverts the Remembrance filter

`src/ingestion/crawler/sources/tfl.py:52`

```python
return "demonstration" in blob or "march" in blob and "remembrance" not in blob
```

`and` binds tighter than `or`, so Python reads this as:

```python
("demonstration" in blob) or (("march" in blob) and ("remembrance" not in blob))
```

The `remembrance` exclusion therefore guards only the `march` branch. Any Remembrance Sunday road closure whose text contains "demonstration" is ingested as a protest.

**Reproduced:**
```
input:  {"comments": "Remembrance Sunday demonstration road closures", ...}
output: is_protest_related(...) -> True      (intent: False)
```

**Fix.** Make the grouping explicit and name the two ideas separately:

```python
PROTEST_TERMS: Final = ("demonstration", "march")
EXCLUDED_TERMS: Final = ("remembrance",)

def _is_protest_related(self, item: dict[str, Any]) -> bool:
    """True when a TfL disruption describes a protest rather than a ceremonial event."""
    sub_category = (item.get("subCategory") or "").lower()
    if "demonstration" in sub_category:
        return True

    blob = " ".join(
        str(item.get(key, "")) for key in ("comments", "location", "category")
    ).lower()
    mentions_protest = any(term in blob for term in PROTEST_TERMS)
    is_excluded = any(term in blob for term in EXCLUDED_TERMS)
    return mentions_protest and not is_excluded
```

Also drop the redundant `sub_category == "demonstration/march"`, which the substring test already covers.

---

### A2. The non-protest-meeting filter is unreachable dead code

`src/ingestion/crawler/sources/organizers/filters.py:152-158`

```python
    if not has_primary_protest_language(title, body):
        return False                                     # line 152-153

    if looks_like_non_protest_meeting(lowered) and not has_primary_protest_language(
        title, body
    ):
        return False                                     # line 155-158
```

Line 152 already returns when `has_primary_protest_language` is false. At line 155, `not has_primary_protest_language(...)` is therefore always `False`, so the `and` short-circuits and the branch can never return. **`NON_PROTEST_MEETING` (12 curated terms) filters nothing.** AGMs, workshops, webinars and craft fairs pass through whenever they also contain a word like "rally".

**Reproduced:**
```
input:  title="PSC public meeting and rally", body="London workshop"
output: is_london_protest_event(...) -> True   (branch guard evaluated, outcome always False)
```

**Fix.** The intent was presumably "reject a meeting unless the *title* carries protest language". Separate the two signals:

```python
def is_london_protest_event(*, title: str, body: str, url: str) -> bool:
    """True when an organiser event page describes a protest action in London."""
    haystack = f"{title} {body} {url}".lower()

    if not mentions_london(haystack):
        return False
    if _mentions_other_uk_city(haystack):
        return False
    if not has_primary_protest_language(title=title, body=body):
        return False
    # A meeting is only an action if the title itself says so, not just the body.
    if looks_like_non_protest_meeting(haystack) and not has_primary_protest_language(
        title=title, body=""
    ):
        return False
    return True
```

This is also the single best test case in the package: the regression test writes itself.

---

### A3. Redundant condition masks the non-London city filter

`src/ingestion/crawler/sources/organizers/filters.py:141-150`

```python
    body_lower = body.lower()
    title_lower = title.lower()
    url_lower = url.lower()
    for city in UK_NON_LONDON:
        if city not in lowered:
            continue
        if "london" in lowered or "westminster" in lowered:
            continue
        if city in title_lower or city in url_lower or city in body_lower:
            return False
```

`lowered` is `f"{title} {body} {url}".lower()`, so line 149's three-way check is logically identical to line 145's `city not in lowered` guard that already passed. Three variables and a compound condition compute a tautology.

Worse, line 147 means **any** page mentioning London anywhere skips the city filter entirely, so a "Manchester march, organised from our London office" is kept. Whether that is intended is unclear from the code, which is itself the problem.

**Fix.** Extract to a named predicate with the rule stated once, in words:

```python
def _mentions_other_uk_city(haystack: str) -> bool:
    """True when a non-London UK city is named and no London location is.

    A page naming both (for example a national march with a London feeder)
    is treated as London, because the London leg is what this project models.
    """
    names_london = any(term in haystack for term in LONDON_TERMS)
    names_elsewhere = any(city in haystack for city in UK_NON_LONDON)
    return names_elsewhere and not names_london
```

---

### A4. Coordinate unpacking crashes on an unexpected payload shape

`src/ingestion/crawler/sources/tfl.py:82-95`

The `isinstance(point, str)` branch parses JSON but never validates length before `lon, lat = coords`. The list branch checks `len(point) == 2`; the string branch does not.

**Reproduced:**
```
input:  point = "[1.0, 2.0, 3.0]"
output: ValueError: too many values to unpack (expected 2)
```

An upstream API change propagates as an unhandled `ValueError` that aborts the whole TfL fetch.

**Fix.** Normalise once, then validate once:

```python
def _parse_point(self, point: object) -> tuple[float | None, float | None]:
    """Extract (latitude, longitude) from TfL's GeoJSON-style point field.

    TfL returns either a JSON string or a [longitude, latitude] sequence.
    Returns (None, None) for anything unparseable rather than raising,
    so one malformed disruption cannot abort the run.
    """
    if isinstance(point, str):
        try:
            coords = json.loads(point)
        except json.JSONDecodeError:
            return None, None
    else:
        coords = point

    if not isinstance(coords, (list, tuple)) or len(coords) != 2:
        return None, None
    try:
        longitude, latitude = (float(value) for value in coords)
    except (TypeError, ValueError):
        return None, None
    return latitude, longitude
```

---

### A5. `assert` used as a runtime guard

`src/ingestion/crawler/sources/met_police.py:360` (ruff `S101`)

```python
assert self.media_dir is not None
```

`assert` is stripped under `python -O`, so the guard vanishes in an optimised run and the next line raises an opaque `TypeError` on `None / str`. Asserts are for invariants in tests, not for argument validation.

**Fix:**
```python
if self.media_dir is None:
    raise MediaDirectoryNotConfiguredError(
        "download_images=True requires media_dir to be set"
    )
```

---

### A6. `source_id` is rebound to a different type

`src/ingestion/crawler/sources/met_police.py:220-221`

```python
source_id = re.search(r"-(\d+)\s*$", article["url"])
source_id = source_id.group(1) if source_id else article["url"]
```

One name holds an `re.Match | None` and then a `str`. `mypy` rejects this, and a reader has to hold two types in their head for one identifier.

**Fix:**
```python
article_id_match = re.search(r"-(\d+)\s*$", article["url"])
source_id = article_id_match.group(1) if article_id_match else article["url"]
```

---

### A7. Empty Parquet file is written as zero bytes

`src/ingestion/crawler/pipeline.py:257-260`

```python
if not records:
    path.write_bytes(b"")
    return
```

A zero-byte `.parquet` is not a valid Parquet file. Any downstream reader fails with a confusing format error rather than reading an empty table. Since the loader in `src/database/load.py` consumes these, this is a cross-discipline trap.

**Fix.** Write a real empty table with the expected schema, or skip the file and record that in the run summary. The former is better, because downstream code then needs no special case:

```python
def _write_parquet(self, path: Path, records: list[dict[str, Any]]) -> None:
    """Write records to Parquet, including a valid empty file when there are none."""
    frame = pd.DataFrame(records, columns=PROTEST_RECORD_COLUMNS)
    frame.to_parquet(path, index=False)
```

This also removes the DuckDB dependency from this method entirely, which fixes A8.

---

### A8. SQL built by f-string interpolation of a path

`src/ingestion/crawler/pipeline.py:262-264`

```python
conn.execute(f"COPY protests_df TO '{path.as_posix()}' (FORMAT PARQUET)")
```

The path is internally derived today, so this is not currently exploitable. It is still the pattern a reviewer is trained to flag, and a single quote in a run ID breaks it. Spinning up an in-memory DuckDB connection to write a DataFrame that pandas can write directly is also unnecessary machinery. A8 dissolves with the A7 fix.

---

## 3. Architecture: the missing `ProtestSource` abstraction

**This is the highest-value change in the package.** It maps directly to official review question 7 ("is there evidence of object-orientation?"), removes the ugliest code in the package, and makes everything testable.

### The problem

Four crawler classes, four incompatible signatures:

| Class | `fetch_records` signature |
|---|---|
| `MetPoliceCrawler` | `(limit: Optional[int] = 10)` |
| `OsacCrawler` | `(limit: Optional[int] = 15, london_only: bool = True)` |
| `TflRoadDisruptionCrawler` | `(*, days_ahead: int = 30, include_past_hours: int = 24)` |
| `MarbleArchSecurityCrawler` | `(limit: Optional[int] = None)` |
| `OrganizerSiteCrawler` | `()` |

Nothing declares that these are the same kind of thing. The consequence is `pipeline._build_crawlers` (lines 118-149), a 32-line method that exists only to paper over the mismatch with a dict of lambdas:

```python
crawlers: dict[str, Callable[[], list[ProtestRecord]]] = {
    "met_police": lambda: MetPoliceCrawler(media_dir=met_media_dir).fetch_records(
        limit=met_limit
    ),
    ...
}
for site in ORGANIZER_SITES:
    crawlers[site.platform_id] = (
        lambda s=site: OrganizerSiteCrawler(s, ...).fetch_records()
    )
```

Note the `lambda s=site:` default-argument trick on the last line: that is there to defeat Python's late-binding closure capture. It works, but it is a workaround for an abstraction that should not be missing. Ruff flags two of these lambdas (`ARG005`). It also forces `ProtestIngestionPipeline.run` to take seven per-source tuning parameters (`met_limit`, `osac_limit`, `tfl_days_ahead`, `marble_arch_limit`, `organizer_event_days_back`, `organizer_event_days_ahead`), which is why `run` is 84 lines and why `cli.main` is 77.

`platforms.record_export_dict` shows the same gap from the other side:

```python
if hasattr(record, "to_dict"):      ...
elif hasattr(record, "model_dump"): ...
else:                                data = dict(record)
```

A duck-typing ladder guessing at three possible record shapes, when only one record type exists in the codebase.

### The fix

Move per-source configuration into `__init__`, and give every source one uniform, zero-argument fetch. New file, `src/ingestion/crawler/sources/base.py`:

```python
"""Common interface every protest source implements."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from ingestion.crawler.client import HttpClient
from ingestion.crawler.models import ProtestRecord

logger = logging.getLogger(__name__)


class ProtestSource(ABC):
    """A single public source of London protest signals.

    Subclasses take their own tuning options in ``__init__`` and expose one
    uniform, zero-argument ``fetch_records``. That uniformity is what lets the
    pipeline treat every source identically and what makes each source
    independently testable with a stub client.
    """

    #: Stable identifier written into every record and used for output folders.
    platform_id: str
    #: Human-readable name for run summaries and the UI.
    platform_name: str
    #: Landing page, recorded for provenance.
    platform_url: str

    def __init__(self, client: HttpClient | None = None) -> None:
        self.client = client or HttpClient()

    @abstractmethod
    def fetch_records(self) -> list[ProtestRecord]:
        """Fetch and normalise every current protest signal from this source."""

    def fetch_records_safely(self) -> list[ProtestRecord]:
        """Fetch records, logging and swallowing source-specific failures.

        One unreachable site must never abort a nine-source run.
        """
        try:
            return self.fetch_records()
        except SourceUnavailableError:
            logger.warning("source %s unavailable, skipping", self.platform_id)
            return []
```

Each crawler then declares its own config and metadata:

```python
class TflRoadDisruptionSource(ProtestSource):
    """Protest-related road disruptions from the TfL Unified API."""

    platform_id = "tfl_road_disruption"
    platform_name = "TfL Unified API (Road Disruptions)"
    platform_url = "https://api.tfl.gov.uk"

    def __init__(
        self,
        client: HttpClient | None = None,
        *,
        days_ahead: int = DEFAULT_TFL_DAYS_AHEAD,
        include_past_hours: int = DEFAULT_TFL_PAST_HOURS,
    ) -> None:
        super().__init__(client or HttpClient(min_interval_sec=0.2))
        self.days_ahead = days_ahead
        self.include_past_hours = include_past_hours

    def fetch_records(self) -> list[ProtestRecord]:
        ...
```

And `_build_crawlers` plus the seven pipeline parameters collapse to:

```python
def default_sources(*, met_media_dir: Path) -> list[ProtestSource]:
    """Every source this project ingests, in run order."""
    return [
        MetPoliceSource(media_dir=met_media_dir),
        OsacSource(),
        TflRoadDisruptionSource(),
        MarbleArchSecuritySource(),
        *(OrganizerSiteSource(config) for config in ORGANIZER_SITES),
    ]


class ProtestIngestionPipeline:
    def run(self, sources: list[ProtestSource], *, run_id: str | None = None) -> RunSummary:
        ...
```

`run` drops below 40 lines, `cli.main` loses six arguments, `PLATFORM_CATALOG` and `platform_meta` become derivable from the source objects rather than a hand-maintained parallel dict, and `record_export_dict`'s `hasattr` ladder disappears.

**What this buys you in the interview:** a clean, honest answer to "where is the object-orientation?" and to "how would you add a tenth source?" The answer becomes "subclass `ProtestSource`, add it to `default_sources`, nothing else changes."

---

## 4. DRY violations (S3.11, S3.12)

### D1. JSON-LD extraction, duplicated four times

`met_police.py:121`, `met_police.py:317`, `met_police.py:397`, `organizers/parse_event_page.py:181` all contain the same loop: find every `<script type="application/ld+json">`, `json.loads` it, `continue` on `JSONDecodeError`, check `@type`.

**Fix.** One generator in `parse_utils.py`:

```python
def iter_json_ld(raw_html: str, *, schema_type: str | None = None) -> Iterator[dict[str, Any]]:
    """Yield each JSON-LD payload embedded in a page.

    Args:
        raw_html: The full page source.
        schema_type: When given, yield only payloads whose ``@type`` matches.

    Malformed blocks are skipped: sites regularly ship one broken script tag
    alongside valid ones, and a single bad block must not lose the rest.
    """
    for match in re.finditer(
        r'<script type="application/ld\+json">(.*?)</script>', raw_html, re.S
    ):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            logger.debug("skipping malformed JSON-LD block")
            continue
        if not isinstance(payload, dict):
            continue
        if schema_type is None or payload.get("@type") == schema_type:
            yield payload
```

Three call sites become one-liners:

```python
for payload in iter_json_ld(html, schema_type="MediaObject"):
    if content_url := payload.get("contentUrl"):
        return {...}
```

### D2. `DATE_POST_RE` defined twice

`date_window.py:10` and `organizers/filters.py:172`, identical except for an `re.I` flag that has no effect on a digit-only pattern. `organizers/crawler.py` imports the `filters` copy while `date_window` uses its own. Delete the `filters.py` copy and import from `date_window`.

### D3. Month-name parsing, duplicated in one function

`date_window.parse_event_datetime_str` lines 49-59 and 61-76 are the same seven lines twice, differing only in abbreviated versus full month names. Collapse into one regex:

```python
_MONTH_NAME_RE = re.compile(
    r"(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(20\d{2})",
    re.I,
)

def _parse_human_date(text: str) -> datetime | None:
    """Parse '14 June 2026' or '14 Jun 2026' as a UTC midnight datetime."""
    match = _MONTH_NAME_RE.search(text)
    if not match:
        return None
    day, month_name, year = match.groups()
    month = _MONTH[month_name.lower()[:3]]
    try:
        return datetime(int(year), month, int(day), tzinfo=UTC)
    except ValueError:
        return None
```

### D4. "First pattern that matches" loop, repeated four times

`met_police._extract_section_12_route`, `met_police._extract_form_up`, `met_police._extract_event_window`, `organizers` parsing all run a list of regexes and take the first hit.

```python
def first_match_group(patterns: Sequence[str], text: str, *, group: int = 1) -> str | None:
    """Return the first capture group from the first pattern that matches."""
    for pattern in patterns:
        if match := re.search(pattern, text, re.I | re.S):
            return clean_html_text(match.group(group))
    return None
```

### D5. `_extract_image_stubs` couples a pattern list to its unpacking

`met_police.py:287-300` decides group order with `if pattern.startswith("title")`, a string test against the regex source. Replace the parallel list with a small structure:

```python
@dataclass(frozen=True)
class ImageLinkPattern:
    """A regex for image links, with which capture group holds which field."""
    pattern: re.Pattern[str]
    page_url_group: int
    caption_group: int | None
```

---

## 5. Observability (S3.20): zero logging in a 9-site crawler

`import logging` appears **0 times in the entire repository**. There are 14 `print()` calls. For a long-running crawler hitting nine external sites with Cloudflare fallbacks, silent retries and per-site failures, this is the most practically damaging gap after the missing tests.

What is currently invisible: which URL is being fetched, whether the Cloudflare or curl fallback fired, why a page was rejected by the filters, how long a source took, which records were dropped by the date window.

**Fix.** Module-level loggers, one `basicConfig` at the CLI edge only.

```python
# src/ingestion/crawler/client.py
logger = logging.getLogger(__name__)

    def get_text(self, url: str, ...) -> str:
        self._throttle()
        logger.debug("GET %s", url)
        ...
        if response.status_code == 403:
            logger.info("403 from %s, retrying via curl fallback", url)
            return self._get_text_via_curl(url)
```

```python
# src/ingestion/crawler/cli.py, the only place that configures logging
def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    ...
```

Keep `print` only for the final machine-readable summary, which is legitimate CLI stdout. Add `--verbose`.

---

## 6. Robustness (S3.19, S3.23)

### R1. No retry or backoff anywhere

`HttpClient` has a timeout and polite throttling, both good. It has no retry. A single transient 502 from any of nine sites loses that source's entire run. For a crawler, retry with exponential backoff is table stakes, and a reviewer will ask.

**Fix.** `requests`' own adapter, six lines, no new dependency:

```python
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

RETRY_POLICY = Retry(
    total=3,
    backoff_factor=0.5,                       # 0.5s, 1s, 2s
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"GET"}),
    respect_retry_after_header=True,
)

class HttpClient:
    def __init__(self, timeout: int = DEFAULT_TIMEOUT_SECONDS, ...) -> None:
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        adapter = HTTPAdapter(max_retries=RETRY_POLICY)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
```

Note `respect_retry_after_header=True`: it makes the crawler obey a server asking it to slow down, which is worth saying out loud in the interview.

### R2. Silent exception swallowing

Four sites in `organizers/crawler.py`:

| Line | Ruff | Pattern |
|---|---|---|
| 80 | `S112` | `try/except/continue` with no log |
| 94 | `SIM105` | `try/except/pass` |
| 99 | `S110` | `try/except/pass` with no log |
| 125 | `S112` | `try/except/continue` with no log |

Each is a place where a parse failure is indistinguishable from "this page had nothing". **Fix:** catch the specific exception and `logger.debug("could not parse %s: %s", url, exc)` before continuing. The control flow stays identical; the failure stops being invisible.

### R3. No per-item error isolation inside a source

`pipeline.run` isolates failures per *platform* (good). Inside a source, it is all or nothing: `met_police.fetch_records` loops over N articles, and one bad article aborts all N.

```python
def fetch_records(self) -> list[ProtestRecord]:
    """Fetch every candidate article, skipping any single article that fails."""
    fetched_at = datetime.now(UTC).isoformat()
    records: list[ProtestRecord] = []
    for article in self.list_articles(limit=self.limit):
        try:
            page = self.client.get_text(article["url"], referer=CENTRAL_LONDON_TAG_URL)
            records.extend(self._parse_article(page, article, fetched_at))
        except requests.RequestException as exc:
            logger.warning("skipping article %s: %s", article["url"], exc)
    return records
```

### R4. Shelling out to `curl` as an SSL fallback

`client.py:100-127` (ruff `S603`) and `cli.py:24` (`S606`, `os.execv`). The curl fallback is a pragmatic hackathon fix with an honest comment explaining why, which earns some credit. It is still a subprocess dependency on an external binary that breaks on Windows and in slim containers.

**Direction.** Either solve it in-process with a relaxed `requests` SSL context for the one offending host, scoped and commented, or keep curl but document the dependency in the README and raise a typed `SourceUnavailableError` when `curl` is absent rather than a generic `RequestException`. State the trade-off in the docstring; do not leave the reviewer to discover it.

### R5. `_throttle` does not own its own clock

`_throttle` (line 45) reads `self._last_request_at` but never writes it. Every caller must remember to set it afterwards, and `_request_get`'s Cloudflare fallback path does not. The invariant is spread across five methods.

**Fix.** Make the throttle responsible for its own state:

```python
def _throttle(self) -> None:
    """Sleep so consecutive requests are at least min_interval_sec apart."""
    elapsed = time.monotonic() - self._last_request_at
    if elapsed < self.min_interval_sec:
        time.sleep(self.min_interval_sec - elapsed)
    self._last_request_at = time.monotonic()
```

Then delete all five `self._last_request_at = time.monotonic()` lines from the callers.

---

## 7. Import-time side effects (S3.22)

### I1. `platforms.py:30-35` mutates a global at import

```python
for _site in ORGANIZER_SITES:
    PLATFORM_CATALOG[_site.platform_id] = {...}
```

Module state built by a top-level loop, leaving `_site` as a module global. **Fix:** build it in a function and call it once, or better, derive it from the `ProtestSource` classes in Section 3:

```python
def build_platform_catalog() -> dict[str, PlatformMeta]:
    """Static metadata for every platform this project ingests."""
    ...

PLATFORM_CATALOG: Final = build_platform_catalog()
```

### I2. `__main__.py:8-14` mutates `sys.path` at import

```python
_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
from ingestion.crawler.cli import _ensure_project_python, main
```

Three smells together: `sys.path` surgery, an import below executable code, and importing an underscore-private function across modules. The cause is that the package uses `ingestion.*` absolute imports while living at `src/ingestion`, so it only resolves when `src/` is on the path.

**Fix.** A `pyproject.toml` with a proper package declaration makes all of this unnecessary:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "london-protest-predictor"
requires-python = ">=3.12"

[project.scripts]
lpp-ingest = "ingestion.crawler.cli:main"

[tool.setuptools.packages.find]
where = ["src"]
```

Then `pip install -e .` and `__main__.py` becomes two lines. This also clears S7.4 and S7.7 from the standards document and gives you a real console entry point, which looks notably more professional than `python -m src.ingestion`.

### I3. `_ensure_project_python` re-execs the interpreter

`cli.py:17-32` calls `os.execv` to relaunch under `.venv/bin/python`. It is a thoughtful convenience, but a function that silently replaces the running process is surprising, is hard-coded to POSIX (`/bin/python`), and is not what a reviewer expects from a CLI. With `pip install -e .` and a documented quickstart, delete it.

---

## 8. Typing and documentation (S3.16, S5.16, S5.17)

### Docstring coverage: 2.6%

| Module | Functions and classes | Docstrings |
|---|---|---|
| `met_police.py` | 25 | **0** |
| `organizers/crawler.py` | 16 | **0** |
| `client.py` | 12 | **0** |
| `pipeline.py` | 12 | 1 |
| `organizers/parse_event_page.py` | 11 | 1 |
| `marble_arch_security.py` | 11 | **0** |
| `tfl.py` | 9 | **0** |
| `osac.py` | 8 | **0** |
| `date_window.py` | 6 | **0** |
| `organizers/filters.py` | 6 | **0** |
| `parse_utils.py` | 5 | **0** |
| **Total** | **134** | **~3** |

This is the cheapest large win available. The regex-heavy parsers need it most: `_extract_section_12_route` encodes five hard-won phrasings of real Met Police legal notices, and that knowledge exists nowhere but in the regexes.

```python
def _extract_section_12_route(self, text: str) -> str | None:
    """Pull the prescribed march route from a Section 12 Public Order Act notice.

    Met Police conditions notices describe the mandated route in one of five
    recurring phrasings ("must not deviate from the route, namely ...",
    "route shown on the map below, which is: ...", and so on), observed across
    the 13 notices in the seed set. We search the Section 12(3) block first and
    fall back to the whole article, because some notices omit the heading.

    Args:
        text: Cleaned article body text.

    Returns:
        The route description, or None when no known phrasing matches.
    """
```

That docstring is worth more to a reviewer than the function it documents: it shows you studied the source material rather than guessing.

### Typing gaps

| Issue | Location | Fix |
|---|---|---|
| `get_json() -> object` forces `isinstance` checks on callers | `client.py:167` | `-> list[dict[str, Any]] \| dict[str, Any]`, or a typed `fetch_disruptions()` on the source |
| Bare `dict` without parameters, 11 places | `tfl.py:45,54`, `osac.py:30,65`, `met_police.py:119,201` | `dict[str, Any]` |
| 82 `Optional[X]` on Python 3.12 | package-wide | `X \| None` (`ruff --fix`) |
| 23 `datetime.timezone.utc` | package-wide | `datetime.UTC` (`ruff --fix`) |
| 4 naive-datetime constructions (`DTZ011`) | `date_window.py` | already tz-aware in most paths; audit the four |

82 of the 174 ruff findings are the `Optional` modernisation and 23 are `datetime.UTC`: **105 of 174 clear with one `ruff check --fix`.**

---

## 9. Magic values and configuration (S3.13)

Inline values carrying domain meaning, with no name and no stated reason:

| Value | Location | Should be |
|---|---|---|
| `body[:2000]` | `met_police.py:245` | `RAW_EXCERPT_MAX_CHARS` |
| `comments[:1500]`, `block[:1500]` | `tfl.py:73`, `osac.py:100` | same constant, currently inconsistent at 2000 vs 1500 |
| `body[:800]` | `met_police.py:191` | `SUPPRESSION_SCAN_CHARS` |
| `max_pages: int = 20` | `met_police.py:64` | `MAX_ARCHIVE_PAGES` |
| `[:60]` on image slug | `met_police.py:363` | `MAX_SLUG_CHARS` |
| `w_2400` | `met_police.py:350` | `HIGH_RES_IMAGE_WIDTH_PX` |
| `len(chunk) > 20`, `min_len=25`, `min_len=10` | `met_police.py:411`, `parse_utils.py:19`, `osac.py:69` | `MIN_PARAGRAPH_CHARS`, with the three call sites reconciled |
| `streets[:6]` | `tfl.py:113` | `MAX_STREETS_PER_RECORD` |
| `0.35`, `0.5`, `0.2` crawl intervals | `client.py:32`, `osac.py:28`, `tfl.py:18` | named per-source politeness constants |
| `8`, `12`, `30` CLI defaults | `cli.py:67-69` | shared `DEFAULT_*` constants, so CLI and source defaults cannot drift |

The 1500-versus-2000 excerpt inconsistency is the tell: these drifted because they were never named.

---

## 10. The test suite this package should have (S4.x)

The crawler is the most testable code in the repository: `parse_utils`, `date_window` and `organizers/filters` are **pure functions over strings**. No network, no database, no fixtures needed for most of it.

### Structure

```
tests/
  conftest.py
  fixtures/
    met_police_article.html          # one real saved article, trimmed
    met_police_listing.html
    osac_report.html
    tfl_disruptions.json
  crawler/
    test_parse_utils.py
    test_date_window.py
    test_organizer_filters.py
    test_tfl_source.py
    test_met_police_source.py
    test_pipeline.py
```

### Sample: the regression test for bug A2

```python
"""Tests for organiser event filtering."""

import pytest

from ingestion.crawler.sources.organizers.filters import is_london_protest_event


class TestIsLondonProtestEvent:
    def test_london_march_is_kept(self) -> None:
        assert is_london_protest_event(
            title="National march for Palestine",
            body="Assemble 12pm at Hyde Park, London.",
            url="https://palestinecampaign.org/events/national-march/",
        )

    def test_manchester_march_is_rejected(self) -> None:
        assert not is_london_protest_event(
            title="Manchester march for Palestine",
            body="Assemble 12pm, Manchester city centre.",
            url="https://example.org/events/manchester-march/",
        )

    def test_london_agm_is_rejected(self) -> None:
        """Regression test: the meeting filter was unreachable (bug A2)."""
        assert not is_london_protest_event(
            title="Annual general meeting",
            body="Our London AGM, followed by a rally report-back.",
            url="https://example.org/events/agm-2026/",
        )

    def test_substring_city_name_does_not_match(self) -> None:
        """'march' must not match inside 'Marchmont Street' (bug A3)."""
        assert not is_london_protest_event(
            title="Office relocation",
            body="We have moved to Marchmont Street, London.",
            url="https://example.org/news/moving/",
        )
```

### Sample: the regression test for bug A1, with a stub client

```python
class StubHttpClient:
    """HttpClient stand-in returning canned payloads, so tests never hit the network."""

    def __init__(self, json_payload: object) -> None:
        self._json_payload = json_payload
        self.requested_urls: list[str] = []

    def get_json(self, url: str, *, params: dict | None = None) -> object:
        self.requested_urls.append(url)
        return self._json_payload


def test_remembrance_event_is_excluded() -> None:
    """Regression test for the operator-precedence bug (A1)."""
    payload = [
        {
            "id": "TIMS-1",
            "subCategory": "Event",
            "comments": "Remembrance Sunday demonstration road closures",
            "location": "Whitehall",
            "category": "Event",
        }
    ]
    source = TflRoadDisruptionSource(client=StubHttpClient(payload))
    assert source.fetch_records() == []
```

### Sample: date-window boundaries with an injected clock

`window_bounds` and `is_within_event_window` already accept `now`, which is good design and makes them trivially testable. Use it:

```python
@pytest.mark.parametrize(
    ("event_offset_days", "expected"),
    [(-8, False), (-7, True), (0, True), (3, True), (4, False)],
)
def test_event_window_boundaries(event_offset_days: int, expected: bool) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    event = now + timedelta(days=event_offset_days)
    assert is_within_event_window(event, now=now, days_back=7, days_ahead=3) is expected
```

### Target

| Module | Tests | Why first |
|---|---|---|
| `organizers/filters.py` | 6 | Pure, and holds two confirmed bugs |
| `date_window.py` | 6 | Pure, clock already injectable, boundary-rich |
| `parse_utils.py` | 6 | Pure, 5 functions, regex-heavy so most valuable to pin |
| `sources/tfl.py` | 4 | Stub client, holds two confirmed bugs |
| `sources/met_police.py` | 3 | One saved HTML fixture, asserts route and participant extraction |
| `pipeline.py` | 2 | `tmp_path` plus a stub source: asserts a failing source does not abort the run |
| **Total** | **27** | Clears S4.1 to S4.11, 60%+ coverage on this package |

---

## 11. Ruff inventory

`ruff check src/ingestion/crawler ingest.py --select E,F,W,B,SIM,C90,UP,N,A,RET,ARG,PTH,TRY,EM,DTZ,S --line-length 100`

| Rule | Count | Meaning | Action |
|---|---|---|---|
| `UP045` | 82 | `Optional[X]` on 3.12 | `--fix` |
| `E501` | 27 | Line over 100 chars | `ruff format` |
| `UP017` | 23 | `timezone.utc` | `--fix` |
| `SIM103` | 7 | Return the condition directly | `--fix`, review each |
| `TRY003` | 4 | Long message outside exception class | Define typed exceptions (Section 12) |
| `DTZ011` | 4 | Naive datetime | Manual audit |
| `S603` | 3 | Subprocess call | R4, document or remove |
| `C901` | 3 | Complexity over 10 | Manual split |
| `SIM102` | 2 | Collapsible nested `if` | `--fix` |
| `S112` | 2 | `try/except/continue` without logging | R2 |
| `EM101`, `EM102` | 4 | String literal in `raise` | Typed exceptions |
| `ARG005` | 2 | Unused lambda argument | Dissolves with Section 3 |
| `S110` | 1 | `try/except/pass` | R2 |
| `S101` | 1 | `assert` in production code | A5 |
| `S324` | 1 | `sha1` | Use `sha256`, or `usedforsecurity=False` |
| `S606` | 1 | Process start without shell (`os.execv`) | I3 |
| `F401` | 1 | Unused import (`models.py:4`) | `--fix` |
| `F541` | 1 | f-string with no placeholder (`cli.py:58`) | `--fix` |
| `ARG002` | 1 | Unused argument (`met_police.py:256`) | Remove `article_url` |
| `RET504` | 1 | Redundant assign before return | `--fix` |
| `UP035`, `TRY300`, `SIM105` | 3 | Misc | `--fix` |

**105 of 174 clear automatically.** The remaining ~69 are the substantive work.

---

## 12. Suggested additions

### A typed exception hierarchy (S3.21, clears 4x `TRY003` and 4x `EM1xx`)

```python
"""Exceptions raised by the ingestion crawlers."""


class IngestionError(Exception):
    """Base class for every ingestion failure."""


class SourceUnavailableError(IngestionError):
    """A source could not be reached after exhausting retries."""

    def __init__(self, platform_id: str, reason: str) -> None:
        super().__init__(f"source {platform_id} unavailable: {reason}")
        self.platform_id = platform_id
        self.reason = reason


class UnknownPlatformError(IngestionError):
    """A platform ID was requested that no registered source provides."""


class MediaDirectoryNotConfiguredError(IngestionError):
    """Image download was requested without a media directory."""
```

### A `RunSummary` dataclass

`pipeline.run` currently builds and returns a nested `dict[str, Any]`, which `cli.main` then navigates with `.get()` chains (`summary.get("outputs", {}).get("platform_folders", {})`). A dataclass gives the run summary a schema, removes the `.get()` defensiveness, and is more OO evidence for question 7.

### Crawl etiquette, stated explicitly

`client.py:11-26` sends a hardcoded macOS Chrome User-Agent, and `cloudscraper` is used to get past Cloudflare challenges. For a project crawling police and campaign-group sites, a reviewer may well ask about this, and "I had not thought about it" is a weak answer.

Strengthen it on two fronts:

1. **Code.** Add a `robots.txt` check via `urllib.robotparser`, keep the existing polite `min_interval_sec` throttle, and honour `Retry-After` (already covered by R1's retry policy).
2. **Docs.** A short "Crawl etiquette" section in `src/ingestion/README.md`: which sources are crawled, at what rate, that all are public pages, that `robots.txt` is respected, and why the browser User-Agent is set.

This converts a possible liability into a deliberate engineering decision you can speak to.

---

## 13. Work plan

| Step | Work | Clears | Effort |
|---|---|---|---|
| **A-1** | Fix bugs A1 to A6, each with the regression test that catches it | 6 defects, S3.27 | 3 h |
| **A-2** | `ruff --fix` the 105 mechanical findings, add `pyproject.toml` with `[tool.ruff]` | S3.29, S3.30, S7.4, S7.7 | 1 h |
| **A-3** | Stand up `tests/` with the 27 tests in Section 10, plus CI | S4.1 to S4.12, S7.8, S7.9 | 1 day |
| **A-4** | Introduce `logging`, delete the 14 `print()` calls, add `--verbose` | S3.20, R2 | 3 h |
| **A-5** | Docstrings: 18 module, then all public functions in `client`, `date_window`, `parse_utils`, `filters`, the four sources | S5.16, S5.17 | 1 day |
| **A-6** | Extract `ProtestSource` ABC, collapse `_build_crawlers`, shrink `run` and `cli.main` | **S3.15**, S3.1, S3.4 | 1 day |
| **A-7** | DRY pass: `iter_json_ld`, `first_match_group`, dedupe `DATE_POST_RE`, merge month parsing | S3.11, S3.12 | 4 h |
| **A-8** | Name the ~20 magic values, reconcile the 1500/2000 and 10/20/25 inconsistencies | S3.13, S3.14 | 2 h |
| **A-9** | Retry policy, per-item error isolation, fix `_throttle` state, typed exceptions | S3.19, S3.23, S3.21 | 4 h |
| **A-10** | `pyproject.toml` packaging so `sys.path` surgery and `os.execv` can go | S3.22, S2.4 | 2 h |
| **A-11** | Crawl-etiquette section plus `robots.txt` check | S9.2 readiness | 2 h |

**Order matters.** A-1 first: fixing bugs you found yourself is the strongest interview material in this whole audit. A-3 next, because tests are the one official criterion currently scoring zero. A-6 is the largest single quality gain but should come after tests exist, so the refactor is verifiable.

---

## 14. What is already good

Worth knowing, both for morale and because you should say these out loud in the walkthrough:

- **Naming is genuinely strong.** `_is_suppressed_event`, `filter_records_by_event_window`, `SUPPRESSED_EVENT_PATTERNS`, `_classify_image_role`. Clear intent, no cryptic abbreviations, consistent conventions across 2,347 lines.
- **`ProtestRecord` is a well-designed normalisation boundary.** One dataclass that five very different sources all map into is the right call, and it is why the model and UI layers could be built in parallel by teammates.
- **Dependency injection is already there.** Every crawler takes `client: Optional[HttpClient] = None`. You built for testability even without writing tests, which is why Section 10 is cheap to deliver.
- **Injectable clocks.** `window_bounds` and `is_within_event_window` take `now`. Most people hardcode `datetime.now()` and then cannot test date logic.
- **`OrganizerSiteConfig` is a real abstraction.** A frozen dataclass with per-site pagination strategy, driving one crawler across many organiser sites, instead of five near-duplicate crawler classes. This is the best design decision in the package. (One flaw: `seed_urls: list[str]` is mutable inside a frozen dataclass and breaks hashability. Make it `tuple[str, ...]`.)
- **The comments that exist are the right kind.** `client.py:104` explains *why* curl uses a simpler UA. `met_police.py:40` explains *why* ban announcements are excluded. Both are why-comments, which is exactly the standard. There are only six; write more like them.
- **Per-platform failure isolation and resumable runs.** `pipeline.run` continues past a failed source, writes progress after each one, and supports `--run-id` to append to an existing run. That is production thinking, not hackathon thinking, and it is worth leading with.