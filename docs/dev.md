# Discipline C: Repository and Developer Tooling, Full Audit

**Scope:** `pyproject.toml`, `requirements.txt`, `.github/workflows/test.yml`, `.gitignore`, `.env.example`, `.python-version`, `.streamlit/`, `tests/conftest.py`, root-level documents, licensing
**Authorship:** 100% Cris Lu. Every file in this discipline was created or last changed by you
**Audited against:** `MLH_SUBMISSION_STANDARDS.md` v1.0, filtered through `PIPELINE_SCOPE_CUT.md` and `CLEANUP.md`
**Date:** 2026-11-07, commit `436b8ce`

> **Repo state.** Since the Discipline A audit you have landed Part A remediation (`0cab173`), the crawler scope cut (`1211710`, `ca9100d`) and Discipline B phase 2 (`436b8ce`). Measured progress on tooling: `tests/` is no longer gitignored, `pyproject.toml` and CI exist, `tests/` holds **17 test files across two packages**, `ruff check .` has fallen from **410 findings to 83**, and `docs/internal/` is gone. Four of my earlier BLOCKERs are cleared. The remaining ones are concentrated here, and two are new.

---

## 0. Method

Discipline C is the one discipline where the standards can be tested by execution rather than inspection, so that is what I did.

1. **Static inspection** of every config file, line by line.
2. **`ruff check .` and `ruff format --check .`** under the repo's own committed configuration, and separately under CI's exact command, to compare what the project claims with what it enforces.
3. **Dependency reconciliation by AST.** Every `import` across `src/`, `app.py` and `ingest.py` resolved to a distribution name and matched against both manifests.
4. **An actual clean install.** A fresh virtualenv, `pip install -e .`, then an attempt to import the documented entry points. This is the only way to test S7.13, and it is the check that produced the most serious finding.

---

## 1. Scorecard

| Standard | Verdict | Evidence |
|---|---|---|
| **S7.1** `.gitignore` correct | **PASS** (was BLOCKER) | `git check-ignore tests/ src/` returns nothing. The test exclusions are gone |
| **S7.2** `.gitignore` tidy | **FAIL** | 270 lines, 92 of them comments. Still a concatenation of templates |
| **S7.3** `LICENSE` present | **FAIL, BLOCKER** | Absent. No `license` field in `pyproject.toml` either. §2 |
| **S7.4** Dependencies declared and pinned | **FAIL, BLOCKER** | Two manifests that disagree. **12 of 15 imported packages missing from `pyproject.toml`.** §3 |
| **S7.5** Python version pinned | **PASS** | `.python-version` = `3.12.4`, `requires-python = ">=3.12"` |
| **S7.6** No orphaned dependencies | **FAIL** | `geopy` and `openpyxl` declared, zero import sites. `urllib3` imported directly but declared nowhere |
| **S7.7** Linter configured in-repo | **PASS** | `[tool.ruff]` with an explicit 16-rule selection and `line-length = 100` |
| **S7.8** CI on push and PR | **PASS** | `.github/workflows/test.yml`, both triggers |
| **S7.9** CI green | **PASS** | CI's lint command exits 0. But see §6 for what it does not cover |
| **S7.10** Secrets from environment, `.env.example` | **PASS** | Exactly 3 env vars in the code (`PROTEST_DB`, `TFL_APP_ID`, `TFL_APP_KEY`), all 3 documented. Complete |
| **S7.11** Degrades without credentials | **PASS** | README states "none required for the default build" |
| **S7.12** `pre-commit` configured | **FAIL** (MINOR) | Absent. Would have prevented §6.2 |
| **S7.13** Reproducible from a clean clone | **FAIL, BLOCKER** | **Verified by execution.** §3.3 and §4 |
| **S7.14** No machine-specific paths | **PASS** | Clean |
| **S2.1** Root legible | **PASS, marginally** | 18 entries. At the limit |
| **S2.5** No placeholder scaffolding | **FAIL** (MINOR) | `notebooks/.gitkeep` remains: an empty notebook directory in a submission where notebooks are disqualifying |
| **S2.7** Docs in `docs/`, not root | **FAIL** | `cursor.md` and `CLEANUP.md` at root. §5 |
| **S3.29** Formatter clean | **FAIL** | **31 of 82 files would be reformatted.** CI does not check formatting at all |
| **S3.30** Linter clean | **PARTIAL** | `ruff check .` = **83 findings**, all in the four paths CI omits. §6.1 |
| **S4.1 / S4.2** Tests exist, real framework | **PASS** (was BLOCKER) | 17 files, `pytest` + `pytest-cov` as dev deps |
| **S4.12** Coverage visible | **FAIL** | `pytest-cov` installed, never invoked. No `--cov`, no badge |
| **S5.8** Quickstart actually works | **FAIL, BLOCKER** | README step 5 runs a module that **does not exist**. §4 |
| **S5.10** How to run tests documented | **FAIL** | README never mentions `pytest`. 17 test files are invisible to a reader |
| **S5.13** Licence stated | **FAIL** | No licence line, no file |
| **S5.22** No internal plans shipped | **FAIL, BLOCKER** | §5. This is the most damaging finding in the discipline |

**Headline:** the tooling has gone from absent to substantially present, and that is real progress. What remains is a different class of problem: **the configuration no longer matches the repository it configures.** Dependencies describe only the crawler, the README documents a deleted module, and two internal working documents are committed at the root. Each of these is a reviewer discovering an inconsistency rather than a gap.

---

## 2. BLOCKER: no licence

| Item | State |
|---|---|
| `LICENSE` file | absent |
| `license` field in `pyproject.toml` | absent |
| Licence line in README | absent |
| `classifiers` | absent |

Without a licence, the default position is all rights reserved. For a sample submitted to be read, copied and discussed, that is a contradiction the applicant did not intend. It is also the single cheapest BLOCKER in the entire standards document to clear.

```
MIT License

Copyright (c) 2026 Cris Lu
...
```

```toml
[project]
license = "MIT"
license-files = ["LICENSE"]
```

Five minutes. Do it first.

---

## 3. BLOCKER: the dependency manifests do not describe the project

### 3.1 Two manifests, neither complete

| Manifest | Declares | Role |
|---|---|---|
| `pyproject.toml` `[project.dependencies]` | **4** packages | the installable metadata |
| `requirements.txt` | **17** packages | the actual working set |
| AST analysis of `src/`, `app.py`, `ingest.py` | **15** third-party packages imported | the truth |

`pyproject.toml` declares `requests`, `pandas`, `pyarrow`, `duckdb`. Resolved by AST, the project imports:

| Import | In `pyproject` | In `requirements` |
|---|---|---|
| `duckdb`, `pandas`, `requests` | yes | yes |
| `geopandas`, `osmnx`, `shapely`, `pyproj`, `networkx` | **NO** | yes |
| `numpy`, `scipy` | **NO** | yes |
| `astral` | **NO** | yes |
| `streamlit`, `altair` | **NO** | yes |
| `duckdb_extension_spatial` | **NO** | yes |
| `urllib3` | **NO** | **NO** |

**12 of 15 imported packages are absent from `pyproject.toml`.**

### 3.2 Why this happened, and why it matters

The pattern is diagnostic: the four declared packages are exactly what **Discipline A** needs. The Part A remediation wrote `pyproject.toml` for the crawler and the file was never widened as B, the models and the app came back into scope. The config fossilised at one moment in the repo's history.

It matters because `pyproject.toml` is now the file a reviewer trusts. It carries the ruff config, the pytest config and the console script. A reviewer who runs the modern, obvious command gets a broken project.

### 3.3 Verified by execution

```
$ python3 -m venv /tmp/c-test && /tmp/c-test/bin/pip install -e .
install exit: 0

$ /tmp/c-test/bin/python -c "import ingestion.crawler.cli"
  crawler cli: OK

$ /tmp/c-test/bin/python -c "import ingestion.route_research.processing.normalize"
ModuleNotFoundError: No module named 'geopandas'

$ /tmp/c-test/bin/python -c "import models.train"
ModuleNotFoundError: No module named 'networkx'
```

The install **succeeds** and the project **does not work**. Only Discipline A imports. Everything else fails on the first import. CI passes solely because `test.yml:15` installs `requirements.txt` before `test.yml:16` installs the package, so the gap is masked by ordering.

### 3.4 Orphans and a transitive import

| Package | Finding |
|---|---|
| `geopy` | Declared in `requirements.txt`, **zero import sites.** Left over from the deleted live-geocoding path |
| `openpyxl` | Declared, **zero import sites.** Left over from deleted Excel handling |
| `pyarrow` | Declared in both, zero *direct* imports. **Legitimate**: pandas and geopandas need it for Parquet. Keep it, add a comment saying why |
| `urllib3` | `client.py:13` does `from urllib3.util.retry import Retry`, and it is declared nowhere. It resolves only as a transitive dependency of `requests`. If `requests` ever vendors or drops it, the crawler breaks |

### 3.5 Fix

Make `pyproject.toml` the single source of truth and delete `requirements.txt`, or keep `requirements.txt` as a generated lock file that `pyproject.toml` is the source for. Do not keep two hand-maintained lists.

```toml
[project]
dependencies = [
    # HTTP and data
    "requests>=2.31.0",
    "urllib3>=2.0",            # imported directly for Retry in crawler/client.py
    "pandas>=2.2.2",
    "pyarrow>=15.0.0",         # not imported directly; pandas/geopandas Parquet backend
    "duckdb==1.5.5",
    "duckdb-extension-spatial==1.5.5; sys_platform != 'darwin' or platform_machine != 'x86_64'",
    # Geospatial
    "geopandas>=1.0",
    "shapely>=2.0.6",
    "pyproj>=3.6",
    "osmnx>=2.0,<3",
    "networkx>=3.2,<4",
    # Modelling
    "numpy>=2.0",
    "scipy>=1.11",
    "astral>=3.2",
    # App
    "streamlit>=1.40",
    "altair>=5.0",
]
```

Then `pip install -e ".[dev]"` is the one documented command, and §3.3 passes. Dropping `geopy` and `openpyxl` clears S7.6 in the same edit.

**Optional, and a strong signal:** commit a lock file (`uv.lock` or `pip-compile`'s `requirements.lock`) and have CI install from it. That is what turns S7.13 from "it worked on my machine" into a verified claim.

---

## 4. BLOCKER: the documented quickstart runs a deleted module

`README.md:23`, inside the copy-pasteable quickstart block:

```bash
python -m src.contract.selftest      # should print PASS for mock and real
```

`src/contract/` now contains `__init__.py`, `mapdata.py`, `types.py`. **`selftest.py` was deleted by the `CLEANUP.md` pass.** A reviewer following the quickstart hits `No module named src.contract.selftest` at step 5 of 6.

This is the worst possible failure mode for S5.8 and S7.13. A reviewer who cannot run the project stops evaluating it, and the specific way it fails suggests the README was not re-read after the cleanup.

**Also stale in the README**, measured against `load.py::TABLES`:

| Claim | README mentions | `load.py` creates |
|---|---|---|
| `grid` table | 1 | **0** |
| `shops` table | 3 | **0** |
| `warehouses` table | 2 | **0** |

All three were deleted with the prediction layer. The earlier false claims (`crimes`, `acled_events`, `protest_signals`, `tfl_disruptions`) are already cleaned, so this is the last of them.

**Two documented install paths, one of them broken.** `README.md:9,20,33` use `pip install -r requirements.txt`. `README.md:263` uses `pip install -e .` followed by `lpp-ingest`. Per §3.3 the second path works for the crawler and nothing else, and the README does not say so.

**And three missing README facts, all in this discipline:**

| Standard | Missing |
|---|---|
| S5.10 | No `pytest` command anywhere. **17 test files are invisible to a reader**, and tests are an official MLH review question |
| S5.13 | No licence line |
| S7.8 | No CI badge, though the workflow exists and passes |

The badge is three lines of work for a visible, verifiable quality signal:

```markdown
[![tests](https://github.com/crislu05/london-protest-predictor/actions/workflows/test.yml/badge.svg)](https://github.com/crislu05/london-protest-predictor/actions/workflows/test.yml)
```

**Verification before submitting.** A clean clone, following only the README, with nothing else installed. This is the single check that most protects the submission, and it currently fails at step 5.

---

## 5. BLOCKER: two internal documents are committed at the repository root

### 5.1 `cursor.md`, 446 lines

```
# MLH Fellowship Code Sample: Submission Quality Standards

**Track:** Software Engineering
**Candidate:** Cris Lu
**Repository under assessment:** `crislu05/london-protest-predictor`
```

This is a verbatim copy of the standards document, **committed to the root of the repository you are submitting.** It contains, in the applicant's own repo, a section titled "Failing BLOCKERs" that states:

- the authorship split, naming Claude as the largest single author of the history
- "No reading path. Repository implicitly presents as wholly yours"
- every measured weakness of the submission

A reviewer who opens `cursor.md` is handed the applicant's private assessment of why the application might fail, including the AI-authorship share, before forming their own view. There is no framing that recovers this.

**Delete it from the repository.** Keep it where it belongs: in the project workspace, in a gist, anywhere outside the submitted tree. Add `cursor.md` to `.gitignore` so a future editor session does not recommit it.

Note that deleting the file does not remove it from history. `git log --all -- cursor.md` will still find it, and S6.9 covers history cleanliness. For a 55-commit hackathon repo, a reviewer is very unlikely to go looking, so **do not rewrite history over this** — the risk of breaking the repo exceeds the risk of discovery. Delete it in a normal commit and move on.

### 5.2 `CLEANUP.md`, 32 lines

Its own first line is `# Cleanup pass (local, uncommitted)`, which is now false: it is committed. It is an internal work log, and two of its lines are actively harmful in a submitted repository:

```
| `train.py` backtest metric override (Jaccard 0.33, top-3 0.75) | Fabricated scores |
| Hardcoded chart numbers in old `model_insights.py` | Replaced with `charts.backtest_charts` |
```

Removing fabricated metrics was exactly the right call, and the integrity behind it is genuinely to your credit. But a committed document whose table reads "Fabricated scores" invites a reviewer to ask what else was fabricated, and the honest answer ("nothing, I found and removed it myself") is one you only get to give if they ask rather than assume.

**The content is worth keeping; the location and framing are wrong.** Move it to `docs/design-decisions.md`, rewritten in the present tense as *what this project deliberately does not do and why*:

> The pipeline ends at training and backtesting. The prediction and decision layers, the multi-page UI, and the crawler-to-training path were removed because none of them had a model consumer, and because automating the geocode review would have put unverified coordinates into the training set. Backtest metrics are read from `backtest.json` rather than hardcoded.

That version is a strength. The current version is an internal note a reviewer was not meant to read.

### 5.3 S2.7 and S5.22

Root-level markdown should be `README.md`, `LICENSE` and at most `CONTRIBUTING.md`. Currently: `README.md`, `DEVPOST.md`, `CLEANUP.md`, `cursor.md`. `DEVPOST.md` is a legitimate hackathon artefact and can stay (or move to `docs/`); the other two should not be there.

---

## 6. CI: what it enforces, and what it does not

```yaml
name: tests
on:
  push:
  pull_request:
jobs:
  pytest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - run: pip install -e ".[dev]"
      - run: python -m ruff check src/ingestion src/models src/database tests
      - run: python -m pytest -q
```

This is a real, working CI and it passes. Credit where due: the lint scope has widened from `src/ingestion/crawler` to four paths, and `pytest` now runs unscoped.

### 6.1 The lint scope still has a hole, and it is now precisely measurable

| Command | Findings |
|---|---|
| `ruff check src/ingestion src/models src/database tests` (CI) | **0** |
| `ruff check .` (the repo's own config) | **83** |

Those 83 are entirely in the four paths CI omits:

| Path | Findings | Status |
|---|---|---|
| `src/contract` | **70** | §6.4 |
| `ingest.py` | 8 | the project's main entry point |
| `src/ui` | 4 | the surviving Streamlit page |
| `src/config.py` | 1 | imported by 6 B modules |

`ingest.py` is the single command the README tells a reviewer to run, and it is excluded from lint. `src/config.py` is imported throughout Discipline B. Neither exclusion is defensible on scope grounds.

**Fix:** `ruff check .`, with the 83 cleared first. 38 of them are auto-fixable.

### 6.2 Formatting is not enforced at all

```
$ ruff format --check .
31 files would be reformatted, 51 files already formatted
```

CI runs `ruff check` but never `ruff format --check`, so **S3.29 is unverified and 31 files are already drifting.** The Discipline B formatting work will silently regress. One line fixes it:

```yaml
      - run: python -m ruff format --check .
```

Run `ruff format .` once, commit the result, then add the gate.

### 6.3 Four smaller CI gaps

| Gap | Fix |
|---|---|
| **No coverage**, despite `pytest-cov` being a declared dev dependency | `pytest --cov=src --cov-report=term-missing`. Clears S4.12 |
| **No dependency caching** | `cache: pip` on `setup-python`. `geopandas` plus `osmnx` on every push is slow |
| **No concurrency group** | Pushing twice runs two full jobs |
| **Workflow named `tests` but it also lints** | Rename to `ci`, or split into `lint` and `test` jobs so a failure names itself |

A single Python version is the right call here. A matrix would be noise for a project pinned to 3.12.

### 6.4 `src/contract` holds 70 of the 83 findings, and is mostly dead

Apply the scope test from `PIPELINE_SCOPE_CUT.md`:

| Module | Consumers | Verdict |
|---|---|---|
| `src/contract/mapdata.py` | 26 references from `models/` | **BACKBONE** |
| `src/contract/types.py` | **declaration only.** Its fields are what made unconsumed `event_context` columns look consumed in the Discipline B trace | **CUT** |

`CLEANUP.md` already calls `mapdata.py` "harmless dead code" for the deleted UI, but the measurement disagrees: `mapdata` is live and `types.py` is not. Deleting `types.py` removes a large share of the 70 findings before any lint work begins, and removes the false-positive consumer that cost time in the B audit.

While there: a package named `contract` whose only live member is a data-access helper is misnamed. Move `mapdata.py` to `src/database/mapdata.py` and delete `src/contract/` entirely.

---

## 7. The `per-file-ignores` block

```toml
# Discipline B: tighten after phase-2 cleanup (see docs/phase2.md).
[tool.ruff.lint.per-file-ignores]
"src/ingestion/route_research/**" = ["E501", "TRY003", "EM102", "PTH123", "DTZ011",
                                    "SIM108", "SIM105", "PTH109", "TRY300", "C901", "E402"]
"src/models/**" = ["E501", "E701", "E702", "N806", "S101", "B905", "B007",
                   "PTH123", "S301", "TRY003", "EM101", "I001", "UP017"]
"src/database/**" = ["E501", "E701", "S608", "DTZ005"]
"tests/**" = ["S101", "ARG001", "PLC0415"]
...
```

Making the narrowing explicit was the right move, and I recommended it. Four problems with how it landed.

### 7.1 The dangling reference

The comment points at `docs/phase2.md`. **That file does not exist.** `docs/` contains `crawler.md` and `crowd-density-note.md`. A comment pointing at a missing document is worse than no comment: it tells a reviewer that the suppression was meant to be justified somewhere and the justification was never written.

Either create `docs/phase2.md` (or fold it into `docs/design-decisions.md` from §5.2) stating which suppressions are temporary and what clears them, or rewrite the comment to stand alone.

### 7.2 Three suppressions are not style, and should be decisions

| Rule | Where | What it suppresses |
|---|---|---|
| **`S301`** | `src/models/**` | `pickle` load. `GRAPH_PATH = MODELS_DIR / "graph.pkl"` is unpickled at training and inference. Unpickling executes arbitrary code; the file is locally generated so this is low risk, but it is a deliberate trade-off and should be a one-line comment at the call site, not a silent global suppression |
| **`S608`** | `src/database/**` | Hardcoded SQL expression. `load.py` builds SQL by f-string from paths. Internally derived today, but this is the rule a reviewer looks for |
| **`C901`** | `route_research/**` | Complexity over 10. Currently hides `join_waypoints` at 13 |

A suppressed security rule reads differently from a suppressed line-length rule. Move these three out of `per-file-ignores` into `# noqa: S301 — locally generated artefact, see docs/design-decisions.md` at the specific lines. Then the suppression is visible where the risk is, and the global block contains only formatting.

### 7.3 `E701` and `E702` are suppressed for `src/models/**`

Those are the compressed-statement rules: `path=Path(path);path.parent.mkdir(...)` and `if x:return y`. Suppressing them for the model package means the style problem Discipline B just fixed is **permitted** in Discipline F rather than fixed. Given `features.py` and `route_model.py` are written that way, that is a conscious choice, but it guarantees the repo keeps two formatting standards. Prefer running `ruff format` over `src/models/` and dropping the two ignores.

### 7.4 The rule selection has gaps and one dead entry

```toml
select = ["E", "F", "W", "B", "SIM", "C90", "UP", "N", "RET", "ARG", "PTH", "TRY", "EM", "DTZ", "S", "I"]
```

| Missing | Would catch |
|---|---|
| **`ANN`** | **The 122 unannotated arguments and 67 missing return types in Discipline B are invisible to CI.** The largest single quality gap in the repo is unmeasured |
| **`D`** (pydocstyle) | Docstring coverage, currently 19% in B. Also an official review consideration |
| **`RUF`** | Ruff's own correctness rules, cheap and high-value |
| **`PL`** | Pylint subset. Note `"tests/**" = [..., "PLC0415"]` suppresses a `PL` rule that is **not selected**, so that entry is a no-op |

Adding `ANN` and `D` with per-file-ignores where the work is not done yet is more honest than omitting them: the config then describes the target, and the ignore list describes the backlog.

---

## 8. `.gitignore`

| Standard | Verdict |
|---|---|
| S7.1 correctness | **PASS.** The test exclusions are gone. This was a BLOCKER and it is cleared |
| S7.2 tidiness | **FAIL.** 270 lines, 92 of them comments, assembled from several templates. Covers Java (`*.class`, `*.jar`), C (`*.o`, `*.dll`), PDM, nose, Spotlight |

A reviewer reading a 270-line `.gitignore` in a pure-Python project sees a file nobody curated. The real content is maybe 25 lines:

```gitignore
# Python
__pycache__/
*.py[cod]
.venv/
*.egg-info/

# Tooling
.pytest_cache/
.ruff_cache/
.mypy_cache/
.coverage
htmlcov/

# Editors and OS
.vscode/
.idea/
.DS_Store

# Project data: generated by `python ingest.py`, never committed
data/
raw/
cache/

# Local secrets
.env

# Internal working notes, not part of the submission
cursor.md
```

That last stanza is the §5.1 fix made durable.

Also delete `notebooks/.gitkeep`. MLH does not accept Jupyter notebooks as samples, so an empty `notebooks/` directory raises the one question you want nobody asking.

---

## 9. Checked and cleared

Measured, not assumed, so you can state these confidently.

**`.env.example` is complete.** AST-extracted every environment variable read anywhere in `src/`, `app.py` and `ingest.py`: exactly `PROTEST_DB`, `TFL_APP_ID`, `TFL_APP_KEY`. All three are documented in `.env.example`, all commented out, no real values. **S7.10 passes cleanly**, which is uncommon.

**`tests/` is no longer gitignored.** `git check-ignore -v tests/ src/` returns nothing. The highest-severity finding of the first audit is fully cleared, and 17 test files now exist.

**No secrets in the tree or the config.** Clean.

**The console script is correctly typed.** `lpp-ingest = "ingestion.crawler.cli:main"`, and `cli.main(argv: Sequence[str] | None = None) -> int` returns an exit code. Many people get this wrong by returning `None`.

**`.python-version` and `requires-python` agree.** `3.12.4` and `>=3.12`.

**CI genuinely passes.** `ruff check src/ingestion src/models src/database tests` exits 0, and `pytest -q` runs the whole suite. The green badge, once added, will be honest within its scope.

**`tests/conftest.py` is redundant but harmless.** It inserts `src` on `sys.path`, which `[tool.pytest.ini_options] pythonpath = ["src"]` already does. Delete the body and keep the file only if you add fixtures. Not a finding, just tidying.

---

## 10. Work plan

Ordered by severity divided by effort. The first four total under two hours and clear three BLOCKERs.

| Step | Work | Clears | Effort |
|---|---|---|---|
| **C-1** | **Delete `cursor.md`.** Add it to `.gitignore`. Move `CLEANUP.md` to `docs/design-decisions.md`, rewritten in the present tense | **S5.22 BLOCKER**, S2.7 | **10 min** |
| **C-2** | Add `LICENSE` (MIT) plus `license` in `pyproject.toml` and a README line | **S7.3 BLOCKER**, S5.13 | **10 min** |
| **C-3** | **Fix the README quickstart.** Remove the `src.contract.selftest` line, remove the `grid`/`shops`/`warehouses` claims, add a `pytest` command, add the CI badge, reconcile the two install paths | **S5.8 BLOCKER**, S5.10, S7.8 | **45 min** |
| **C-4** | Move all 15 runtime deps into `pyproject.toml`. Drop `geopy` and `openpyxl`. Declare `urllib3`. Delete `requirements.txt` or generate it. **Re-run the §3.3 clean-install test** | **S7.4, S7.13 BLOCKERs**, S7.6 | **1 h** |
| **C-5** | Delete `src/contract/types.py`, move `mapdata.py` to `src/database/`, delete `src/contract/`. Delete `notebooks/.gitkeep` | ~70 of the 83 lint findings, S2.5 | 1 h |
| **C-6** | `ruff format .` across the repo, commit, then add `ruff format --check .` to CI | **S3.29** | 45 min |
| **C-7** | Widen CI lint to `ruff check .` after clearing the remaining ~13 findings in `ingest.py`, `src/ui`, `src/config.py` | S3.30 | 1 h |
| **C-8** | Add `--cov=src --cov-report=term-missing`, `cache: pip`, a concurrency group. Rename the workflow `ci` | S4.12 | 30 min |
| **C-9** | Fix the `per-file-ignores` block: create the referenced doc, move `S301`/`S608`/`C901` to line-level `# noqa` with reasons, drop the no-op `PLC0415` | S7.7 integrity | 1 h |
| **C-10** | Add `ANN` and `D` to `select`, with per-file-ignores recording the backlog honestly | measures S3.16, S5.17 | 30 min |
| **C-11** | Rewrite `.gitignore` to ~25 curated lines | S7.2 | 20 min |
| **C-12** | Add `.pre-commit-config.yaml` (ruff, ruff-format, trailing whitespace) | S7.12 | 30 min |

**Why this order.** C-1 is first because it is ten minutes and it is the finding with no recovery if a reviewer sees it. C-2 and C-3 are the next cheapest BLOCKERs. C-4 needs the §3.3 test re-run as its acceptance criterion, not just an edited file. C-5 before C-6 and C-7, because deleting `types.py` removes most of what those steps would otherwise have to fix.

**Discipline C is the best-value work left in the repository.** Unlike B, it is 100% yours, there is nothing to attribute, and C-1 through C-4 clear four BLOCKERs in about two hours. Do this before any further work on B or the model.

---

## 11. What is already good

Worth saying, because this discipline has moved the furthest since the first audit.

- **Four BLOCKERs cleared in a day.** `tests/` unignored, tests written across both packages, `pyproject.toml` and CI created, `docs/internal/` removed. `ruff check .` has fallen from 410 findings to 83. That is a real remediation pace and the commit history shows it.

- **`.env.example` is exactly right**, verified by AST against every environment read in the codebase. Three variables, three documented, no values. Most projects either over-document or miss one.

- **The `per-file-ignores` approach is the correct instinct.** An acknowledged, scoped exclusion is defensible in an interview in a way that a silently narrowed command is not. §7 is about finishing the job, not reversing it.

- **CI is real and it passes.** Both triggers, a pinned Python version, install then lint then test. The ordering bug in §3.3 is a dependency problem, not a workflow problem.

- **The console script is properly typed** and returns an exit code.

- **`.streamlit/config.toml` carries a reasoned comment**, tying the theme colour to the chart palette so buttons and charts agree. A one-line config file that explains itself is a good sign, and reviewers notice small evidence of care.

- **The integrity call recorded in `CLEANUP.md`.** Finding hardcoded backtest metrics in your own repository and removing them, rather than leaving numbers that flatter the model, is the single most creditable decision in the project's history. §5.2 is about *where* that is written down, not whether it was right. Rewritten as a design note, it becomes something to lead with rather than something to hope goes unread.