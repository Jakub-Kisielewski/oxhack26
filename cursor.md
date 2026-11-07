# MLH Fellowship Code Sample: Submission Quality Standards

**Track:** Software Engineering
**Candidate:** Cris Lu
**Repository under assessment:** `crislu05/london-protest-predictor`
**Document version:** 1.0 (2026-11-07)

---

## 0. How to use this document

Every standard below has an ID (`S1.1`, `S2.4`, ...), a **requirement**, a **measurable bar**, and a **verification method**. A standard is only "met" when the verification command or check passes, not when it feels done. Section 12 holds the live audit of the current repository against every standard.

Standards are graded:

| Grade | Meaning |
|---|---|
| **BLOCKER** | Maps directly to an official MLH review question or a hard eligibility gate. Failing this can sink the application on its own. |
| **MAJOR** | Strongly implied by the official criteria, or a known reviewer trigger. Failing several of these reads as an unpolished submission. |
| **MINOR** | Polish. Individually ignorable, collectively the difference between "competent" and "would hire". |

---

## 1. The official bar (primary sources)

### 1.1 The eight review questions

MLH's admissions team states it reviews every code sample by asking:

1. Is the project easy to navigate through?
2. Does the project follow clean code principles? (DRY code, good use of naming principles, etc.)
3. Is it original work, not a tutorial or classroom project?
4. If the project was built using any existing boilerplate, has the sample built upon it?
5. Is the sample well documented, with a descriptive README?
6. Is there any evidence of testing or test files?
7. If appropriate to the project and programming language, is there evidence of object-orientation?
8. Is there appropriate use of `.gitignore` and other config files?

The same source adds that the team **may also review your other public GitHub repositories and commits** to form a holistic view.

*Source: MLH Help Centre, "How does MLH review my code sample? What do you look for?"*

### 1.2 The application form's own requirements

- **Representative:** the sample must represent your abilities. For a group project, you must have contributed a substantial amount of code.
- **Existing sample:** code written for a purpose other than this application.
- **Public on GitHub:** private samples are not accepted. A secret Gist is the only fallback.
- **Multiple files, of substance:** "it's hard to have a conversation about a single function."
- **Not too large:** "it's difficult to have a conversation about a mono-repo with dozens of microservices."
- **A real problem:** the sample should solve a real problem or accomplish a real goal.
- **Language match:** written in the language of your preferred track (Python is in scope).
- **No Jupyter notebooks** or other exploratory code samples.
- **Explicitly discouraged:** algorithm implementations, competitive programming solutions, university or bootcamp coursework, heavy-boilerplate framework scaffolds.

### 1.3 The downstream consequence

If shortlisted, there is a **code walkthrough interview on this specific repository**. Every standard below should therefore be read twice: once as "will a reviewer scanning for 10 minutes be impressed", and once as "can I defend this line out loud".

---

## 2. Submission gates (hard pass/fail)

| ID | Requirement | Bar | Grade |
|---|---|---|---|
| **S1.1** | Repository is public on GitHub | Loads in a logged-out browser | BLOCKER |
| **S1.2** | Written in a track-supported language | Python, JavaScript, TypeScript or Rust as the dominant language by LOC | BLOCKER |
| **S1.3** | Not a notebook submission | Zero `.ipynb` files in the submitted tree; no empty `notebooks/` stub either | BLOCKER |
| **S1.4** | Not coursework, tutorial or boilerplate clone | Project solves a self-chosen real problem, documented as such in the README | BLOCKER |
| **S1.5** | Pre-existing work | Repository history predates the application date | BLOCKER |
| **S1.6** | Multiple files of substance | At least ~10 source files and ~1,000 lines of your own code | BLOCKER |
| **S1.7** | Not too large to discuss | See Section 9 on scoping. A 100-file, 12k-line multi-discipline repo is over the comfortable line and needs a reading path | MAJOR |
| **S1.8** | Your contribution is unambiguous | A reviewer can identify your code in under 60 seconds without asking you | BLOCKER |

---

## 3. Repository structure standards

*Maps to official question 1 (easy to navigate) and 8 (config files).*

| ID | Requirement | Bar | Grade |
|---|---|---|---|
| **S2.1** | Root directory is legible | At most ~12 entries at repo root. Every one is either a standard config file or an obvious top-level concern | MAJOR |
| **S2.2** | Source lives under one package root | A single `src/` (or package-named) tree. No source modules scattered at root alongside configs | MAJOR |
| **S2.3** | Package boundaries match responsibilities | Each sub-package has one stated job, written in a one-line module docstring or local README | MAJOR |
| **S2.4** | Every package is a real package | `__init__.py` present and non-trivially used (exports the public surface, not empty) | MINOR |
| **S2.5** | No placeholder scaffolding | No `.gitkeep` files in directories that now have content; no empty directories | MINOR |
| **S2.6** | Tests mirror the source tree | `tests/` mirrors `src/` layout so a reviewer can find the test for any module | MAJOR |
| **S2.7** | Docs live in `docs/`, not root | Only `README.md` (and `LICENSE`, `CONTRIBUTING.md` if present) are root-level markdown | MINOR |
| **S2.8** | Generated artefacts are absent | No build output, database files, caches, logs or downloaded datasets committed | MAJOR |
| **S2.9** | Committed data is justified | Any committed data file is small (< 100 KB), is genuinely seed/fixture data, and its presence is explained in the README | MINOR |
| **S2.10** | Single, obvious entry point | A reviewer can tell in one glance how to run the thing (`app.py`, `main.py`, `cli.py`, or a documented `python -m` target) | MAJOR |

**Verification:**
```bash
ls -1 | wc -l                                  # S2.1, target <= 12
find . -name '.gitkeep' -o -type d -empty      # S2.5, expect none
find . -name '*.db' -o -name '*.duckdb' -o -name '*.parquet' -o -name '*.log'   # S2.8
```

---

## 4. Code quality standards

*Maps to official question 2 (clean code, DRY, naming) and 7 (object-orientation).*

### 4.1 Structure and size

| ID | Requirement | Bar | Grade |
|---|---|---|---|
| **S3.1** | Functions are short | No function over 50 lines. Target median under 20 | MAJOR |
| **S3.2** | Files are focused | No source file over 400 lines. Target median under 200 | MAJOR |
| **S3.3** | Shallow nesting | Maximum nesting depth of 4 inside any function | MINOR |
| **S3.4** | Low branching complexity | Cyclomatic complexity grade A or B on every function (`ruff` rule `C901`, max 10) | MAJOR |
| **S3.5** | One responsibility per function | A function's name fully describes what it does, with no "and" in it | MAJOR |
| **S3.6** | Parameter lists are short | At most 5 positional parameters. Beyond that, pass a dataclass or config object | MINOR |

### 4.2 Naming and clarity

| ID | Requirement | Bar | Grade |
|---|---|---|---|
| **S3.7** | Names are descriptive and consistent | No single-letter names outside comprehensions and loop counters. No abbreviations a newcomer would not recognise | MAJOR |
| **S3.8** | One vocabulary per concept | The same domain concept uses one word everywhere (do not mix `event` / `protest` / `march` for the same entity). Maintain a glossary if the domain has overlapping terms | MAJOR |
| **S3.9** | Consistent naming conventions | `snake_case` functions and variables, `PascalCase` classes, `UPPER_SNAKE` constants, no exceptions | MINOR |
| **S3.10** | Module names are nouns, function names are verbs | Enforced by review, not tooling | MINOR |

### 4.3 DRY and abstraction

| ID | Requirement | Bar | Grade |
|---|---|---|---|
| **S3.11** | No copy-pasted blocks | Zero duplicate blocks of 6+ lines across the codebase | MAJOR |
| **S3.12** | Shared logic is extracted | Repeated parsing, HTTP, retry, geocoding or date logic lives in one utility module | MAJOR |
| **S3.13** | Magic values are named constants | No bare numeric or string literals carrying domain meaning inline (radii, thresholds, timeouts, URLs) | MAJOR |
| **S3.14** | Configuration is centralised | One config module or settings object. No constants redefined per file | MINOR |

### 4.4 Object-orientation and typing

| ID | Requirement | Bar | Grade |
|---|---|---|---|
| **S3.15** | Evidence of deliberate OO or structured design | Domain entities modelled as `dataclass` or classes, not passed around as raw dicts and tuples. At least one class hierarchy or protocol where polymorphism genuinely applies (for example, a `Source` base class with one subclass per data source) | **BLOCKER** (official question 7) |
| **S3.16** | Public functions are type-annotated | 100% of functions in `src/` have annotated parameters and return types | MAJOR |
| **S3.17** | Type checking passes | `mypy src/` or `pyright` clean, or with a documented, minimal ignore list | MINOR |
| **S3.18** | No mutable default arguments | Zero occurrences of `def f(x=[])` or `={}` | MINOR |

### 4.5 Errors, logging and side effects

| ID | Requirement | Bar | Grade |
|---|---|---|---|
| **S3.19** | No bare `except:` and no silent `except Exception: pass` | Every handler catches a specific exception type and either handles, logs or re-raises | MAJOR |
| **S3.20** | Logging, not printing | Zero `print()` calls in `src/`. Use the `logging` module with a configured level. `print` is acceptable only in a CLI's final user-facing output | MAJOR |
| **S3.21** | Custom exceptions for domain failures | A small exception hierarchy for the project's own failure modes | MINOR |
| **S3.22** | No import-time side effects | Importing any module performs no I/O, no network calls and no file writes | MAJOR |
| **S3.23** | No network calls without timeout and retry | Every outbound request has an explicit timeout and a bounded retry policy | MAJOR |
| **S3.24** | Paths are constructed portably | `pathlib` throughout, no hardcoded `/Users/...` or `C:\` paths, no string concatenation of paths | MAJOR |

### 4.6 Hygiene

| ID | Requirement | Bar | Grade |
|---|---|---|---|
| **S3.25** | No commented-out code | Zero blocks of commented-out logic. Git history is the archive | MAJOR |
| **S3.26** | No stale `TODO` / `FIXME` | Either resolved, or converted into GitHub issues and removed from source | MINOR |
| **S3.27** | No dead code | No unused functions, imports or variables (`ruff` `F401`, `F841`, and a `vulture` pass) | MAJOR |
| **S3.28** | No secrets, ever | No credentials, tokens, keys or personal emails in source or history | **BLOCKER** |
| **S3.29** | Consistent formatting | A formatter runs clean across the repo with zero diff (`ruff format --check` or `black --check`) | MAJOR |
| **S3.30** | Linter passes clean | `ruff check .` exits 0 with a committed, non-trivial rule selection | MAJOR |

**Verification:**
```bash
ruff check . && ruff format --check .
mypy src/
grep -rn 'print(' src/ | wc -l                 # S3.20, target 0
grep -rnE 'except\s*:|except Exception:\s*$' src/
grep -rnE '^\s*#\s*(def |class |if |for |return |import )' src/   # S3.25
```

---

## 5. Testing standards

*Maps to official question 6, and this is the single most commonly failed criterion.*

| ID | Requirement | Bar | Grade |
|---|---|---|---|
| **S4.1** | Tests exist and are committed | A `tests/` directory is present and **not** excluded by `.gitignore` | **BLOCKER** |
| **S4.2** | A real test framework is used | `pytest` (or `unittest`), declared as a dev dependency | BLOCKER |
| **S4.3** | Tests run from a clean clone | `pytest` passes with no network access, no database and no credentials | **BLOCKER** |
| **S4.4** | Meaningful coverage of your own modules | At least 60% line coverage on the modules you authored. Coverage of the whole repo matters less than coverage of what you claim | MAJOR |
| **S4.5** | Pure logic is tested first | Every pure function (date windows, parsing, filtering, normalisation, feature construction) has at least one test | MAJOR |
| **S4.6** | Edge cases are explicit | Each tested function has at least one boundary or malformed-input case, not only a happy path | MAJOR |
| **S4.7** | External I/O is mocked or fixtured | HTTP responses and file reads come from committed fixtures, never from the live internet | MAJOR |
| **S4.8** | Test names describe behaviour | `test_<unit>_<condition>_<expected>`, readable as a sentence | MINOR |
| **S4.9** | No test interdependence | Tests pass in any order (`pytest -p no:randomly` and shuffled both pass) | MINOR |
| **S4.10** | Test fixtures are small and committed | Fixture files under `tests/fixtures/`, each under 50 KB | MINOR |
| **S4.11** | A smoke test for the entry point | One test asserts the app or CLI imports and initialises without error | MAJOR |
| **S4.12** | Coverage is visible | A coverage number appears in CI output or a README badge | MINOR |

**Minimum credible test suite for this project:** 15 to 25 tests covering date-window arithmetic, HTML and date parsing, organiser filters, normalisation joins, and schema initialisation.

**Verification:**
```bash
git check-ignore -v tests/            # S4.1, expect no match
python -m pytest -q --cov=src --cov-report=term-missing
```

---

## 6. Documentation standards

*Maps to official question 5 (descriptive README) and question 1 (navigability).*

### 6.1 README (the single highest-leverage artefact)

A reviewer forms their opinion in the first 30 seconds of the README. Required sections, in this order:

| ID | Requirement | Bar | Grade |
|---|---|---|---|
| **S5.1** | Title and one-sentence description | What it does, for whom, in one line, above the fold | **BLOCKER** |
| **S5.2** | The problem statement | Two to four sentences on the real problem being solved. Establishes originality (official question 3) | BLOCKER |
| **S5.3** | Visual proof it works | At least one screenshot or GIF of the running application, within the first screenful | MAJOR |
| **S5.4** | Live demo link, if one exists | Deployed URL, or an explicit note that it runs locally only | MINOR |
| **S5.5** | Tech stack | A short list of languages, frameworks and notable libraries with one-line rationale for the non-obvious choices | MAJOR |
| **S5.6** | Architecture overview | A diagram (Mermaid is ideal, as it renders natively on GitHub) plus a short paragraph on how data flows through the system | MAJOR |
| **S5.7** | Repository map | A directory tree with a one-line purpose per top-level package | MAJOR |
| **S5.8** | Quickstart that actually works | Copy-pasteable commands taking a clean clone to a running app. Tested on a clean machine | **BLOCKER** |
| **S5.9** | Prerequisites stated | Python version, OS caveats, external tool requirements | MAJOR |
| **S5.10** | How to run the tests | An explicit `pytest` command in the README | MAJOR |
| **S5.11** | Contribution attribution | For a team project, a section naming exactly which modules and features you authored, with commit or PR links | **BLOCKER** |
| **S5.12** | Known limitations | An honest short list. Signals engineering maturity and pre-empts interview questions | MAJOR |
| **S5.13** | Licence stated | A line in the README plus a `LICENSE` file | MAJOR |
| **S5.14** | Length is controlled | Under ~200 lines. Anything longer belongs in `docs/` | MAJOR |
| **S5.15** | Professional tone and formatting | No shouting headers, no unexplained jargon, correct spelling, consistent heading hierarchy, no broken links | MAJOR |

### 6.2 In-code documentation

| ID | Requirement | Bar | Grade |
|---|---|---|---|
| **S5.16** | Every module has a docstring | One to three lines at the top of each `.py` file in `src/`, stating the module's job | MAJOR |
| **S5.17** | Every public function and class has a docstring | Consistent style (Google or NumPy), covering purpose, args, returns and raises. 100% of public surface | MAJOR |
| **S5.18** | Comments explain *why*, not *what* | No comments restating the code. Comments justify non-obvious decisions, workarounds and domain quirks | MAJOR |
| **S5.19** | Non-obvious domain logic is explained | Any data-source quirk, coordinate system, time-zone or units decision carries a comment | MAJOR |
| **S5.20** | Docstring coverage is measurable | `interrogate` or equivalent reports >= 90% on `src/` | MINOR |

### 6.3 Supporting documents

| ID | Requirement | Bar | Grade |
|---|---|---|---|
| **S5.21** | `docs/` holds the deep material | Data provenance, design decisions, model methodology | MINOR |
| **S5.22** | No internal build plans in the shipped repo | Implementation plans, progress logs and task lists are either removed or clearly archived under `docs/archive/` | MAJOR |
| **S5.23** | Per-package READMEs where a package is substantial | A short README in each large sub-package | MINOR |
| **S5.24** | Architecture decisions recorded | Optional: short ADRs for the two or three genuinely contested choices | MINOR |

---

## 7. Git history and attribution standards

*Maps to the "representative" requirement and the stated practice of reviewing your commits.*

| ID | Requirement | Bar | Grade |
|---|---|---|---|
| **S6.1** | Your commits are linked to your GitHub account | `git log` author email matches a verified email on your GitHub profile, so commits show your avatar and count toward your contribution graph | **BLOCKER** |
| **S6.2** | No placeholder git identity | Zero commits authored as `you@example.com`, `root@localhost` or similar | **BLOCKER** |
| **S6.3** | Your share of authorship is substantial and visible | On the repository's Contributors graph, you are clearly a major contributor | **BLOCKER** |
| **S6.4** | AI-assisted commits are not misrepresented as a third party doing the engineering | Where an assistant co-authored work you directed, author it under your identity with a `Co-Authored-By:` trailer, rather than leaving a non-human name as the sole author of a large share of the history. Never claim as your own code you cannot explain | **BLOCKER** |
| **S6.5** | Commit messages are informative | Imperative mood, under 72-character subject, explaining the change not the file touched. No `fix`, `ui cleanup`, `model done`, `asdf` | MAJOR |
| **S6.6** | Commit count and granularity look like real engineering | 30+ commits, each a coherent unit of work. No single commit adding thousands of lines across unrelated areas | MAJOR |
| **S6.7** | Branching is visible | Evidence of feature branches and merges, which signals collaboration ability | MINOR |
| **S6.8** | Pull requests exist for a team project | Even a few PRs with review comments materially strengthen the sample | MAJOR |
| **S6.9** | History is clean of large binaries and secrets | `git log --stat` shows no committed datasets, databases or credentials at any point | MAJOR |
| **S6.10** | Default branch is `main` and is the submitted branch | No submission pointing at a stale or unmerged branch | MINOR |

---

## 8. Tooling, configuration and reproducibility

*Maps to official question 8 (`.gitignore` and other config files).*

| ID | Requirement | Bar | Grade |
|---|---|---|---|
| **S7.1** | `.gitignore` is correct and purposeful | Covers language artefacts, virtualenvs, IDE files, OS files, and the project's own generated data. **Must not exclude `tests/`, `test_*.py` or any source directory** | **BLOCKER** |
| **S7.2** | `.gitignore` is tidy | Curated for this project. Not a 270-line dump of every template concatenated together | MINOR |
| **S7.3** | `LICENSE` file present | A recognised OSI licence (MIT is the conventional default) | MAJOR |
| **S7.4** | Dependencies are declared and pinned sensibly | `pyproject.toml` (preferred) or `requirements.txt`, with compatible-release pins. Dev dependencies separated from runtime | MAJOR |
| **S7.5** | Python version is pinned | `.python-version` and/or `requires-python` in `pyproject.toml` | MINOR |
| **S7.6** | No commented-out or orphaned dependencies | Every declared dependency is actually imported; every import is declared | MAJOR |
| **S7.7** | Linter and formatter configured in-repo | `[tool.ruff]` section with an explicit rule selection and line length | MAJOR |
| **S7.8** | CI runs on every push and PR | A GitHub Actions workflow running install, lint, type-check and tests on at least one Python version. Badge in the README | MAJOR |
| **S7.9** | CI is green | The badge shows passing at submission time | **BLOCKER** (a red badge is worse than no badge) |
| **S7.10** | Secrets come from the environment | All credentials read from environment variables, with a committed `.env.example` listing every variable and no real values | MAJOR |
| **S7.11** | Graceful degradation without optional credentials | The documented quickstart works with zero credentials, skipping optional sources with a clear log line | MAJOR |
| **S7.12** | `pre-commit` configured | Optional but a strong signal: hooks for format, lint and trailing whitespace | MINOR |
| **S7.13** | Reproducible from a clean clone | Verified on a fresh container or machine, following only the README | **BLOCKER** |
| **S7.14** | No absolute or machine-specific paths in config | Verified by grep | MAJOR |

**Verification:**
```bash
git check-ignore -v tests/ src/      # S7.1, expect no matches
test -f LICENSE && test -f .env.example && test -f pyproject.toml
pip install -e '.[dev]' && ruff check . && mypy src/ && pytest -q
```

---

## 9. Scope and discussability

MLH explicitly warns against a sample that is "too large" to hold a conversation about. A 100-file, ~12,000-line repository spanning crawling, geospatial processing, a database layer, statistical modelling and a multi-page UI is above that line. The fix is not deletion, it is **a reading path**.

| ID | Requirement | Bar | Grade |
|---|---|---|---|
| **S8.1** | A declared "start here" path | The README names three to five files, in reading order, that constitute the core of the sample | MAJOR |
| **S8.2** | Your strongest discipline is the centre of gravity | The reading path points at code you wrote end to end and can defend line by line | **BLOCKER** |
| **S8.3** | Peripheral areas are clearly labelled as teammates' work | Nobody can accuse you of implicitly claiming the whole repository | **BLOCKER** |
| **S8.4** | The sample is coherent, not a monorepo of unrelated tools | One system, one data flow, one purpose | MAJOR |
| **S8.5** | Consider extracting the core as a standalone companion repo | If the full project cannot be made presentable in time, a clean, fully tested extraction of the ingestion package (sole-authored, 100% yours, CI green) is a stronger sample than a large shared repo. Keep the original linked for context | MAJOR |

---

## 10. Interview readiness standards

The shortlist stage is a walkthrough of this code with a human.

| ID | Requirement | Bar | Grade |
|---|---|---|---|
| **S9.1** | You can explain every line in the reading path | No exceptions. If you cannot, it does not belong in the path | **BLOCKER** |
| **S9.2** | You can justify every architectural choice | Why DuckDB over Postgres or SQLite. Why Streamlit. Why this schema. Why a crawler per source instead of one generic parser | MAJOR |
| **S9.3** | You can state what you would do differently | A prepared, specific answer. This question is asked | MAJOR |
| **S9.4** | You can give a two-minute and a ten-minute version of the walkthrough | Rehearsed out loud, not just planned | MAJOR |
| **S9.5** | You can describe your own debugging war story | One concrete, specific bug from this project: symptom, diagnosis, fix | MAJOR |
| **S9.6** | You can state your contribution boundary precisely | Which files, which features, which decisions were yours | **BLOCKER** |
| **S9.7** | You can discuss the trade-offs you knowingly accepted | Hackathon time pressure is a legitimate, respected answer when paired with "and here is what I would fix first" | MINOR |

---

## 11. Application form answers

Two short written answers accompany the sample. Both are graded alongside it.

| ID | Requirement | Bar | Grade |
|---|---|---|---|
| **S10.1** | "Briefly describe what this code sample does" (200 words) | Leads with the problem and the user, names the technical core, states your specific contribution explicitly | BLOCKER |
| **S10.2** | "Briefly describe what you learned" (200 words) | One or two concrete technical lessons with specifics, not generic reflections on teamwork | BLOCKER |
| **S10.3** | Consistency with the repository | Every claim in the answers is verifiable in the code and the README | BLOCKER |
| **S10.4** | Honest framing of team and tooling | Your scope is stated plainly. No overclaiming, which is the fastest way to fail a walkthrough | **BLOCKER** |

---

## 12. Audit: `london-protest-predictor` as of 2026-11-07

Measured on commit `6927a1e`. 52 commits, 100 files, 11,877 lines.

### 12.1 Failing BLOCKERs

| ID | Standard | Finding |
|---|---|---|
| **S6.1 / S6.2** | Commits linked to your account | Your 5 commits are authored `cl5924 <you@example.com>`. GitHub cannot attribute them to your profile |
| **S6.3 / S6.4** | Authorship share | Authorship splits: Claude 23, Jakub 17, Mykhailo 7, you 5. The largest single author on the Contributors graph is not a person |
| **S4.1 / S7.1** | Tests exist, `.gitignore` correct | `.gitignore` lines 47 to 50 exclude `tests/`, `test_output/`, `test_*.py`, `*_test.py`. The repository contains zero tests |
| **S4.3** | Tests run from clean clone | Nothing to run |
| **S5.11** | Contribution attribution | No section in the README states what you wrote |
| **S7.9** | CI green | No CI exists |
| **S8.2 / S8.3** | Reading path, labelled ownership | No reading path. Repository implicitly presents as wholly yours |
| **S3.15** | Evidence of object-orientation | Needs verification per package. The crawler's per-source modules are a natural place for a `Source` base class and currently use module-level functions |

### 12.2 Failing MAJORs

| ID | Standard | Finding |
|---|---|---|
| **S3.1** | Functions under 50 lines | 12 functions exceed it. Worst: `overspill.predict` 88, `plot_all_seed_routes.main` 89, `crawler/pipeline.run` 84, `crawler/cli.main` 77 |
| **S3.2** | Files under 400 lines | `scripts/enrich_events_csv.py` 539 lines with 2 functions. `crawler/sources/met_police.py` 493 lines |
| **S3.20** | Logging not printing | 98 `print()` calls across the codebase |
| **S3.16** | Type annotations | Partial: `met_police.py` 15 of 24 functions, `crawler/pipeline.py` 4 of 11 |
| **S5.16 / S5.17** | Docstrings | Near zero in your own modules: `crawler/client.py` 0 of 11 functions, `met_police.py` 0 of 24, `crawler/pipeline.py` 1 of 11 |
| **S5.1 to S5.8** | README structure | 322 lines. Opens with `## HOW TO SETUP` in capitals. No description, problem statement, screenshot, architecture or repository map. Roughly 80% is data-source provenance |
| **S5.14** | README length | 322 lines, over the bar |
| **S5.22** | No internal plans shipped | `docs/IMPLEMENTATION_PLAN.md`, 762 lines, is a build plan |
| **S7.3** | `LICENSE` | Absent |
| **S7.4 / S7.7** | `pyproject.toml`, linter config | Absent. `requirements.txt` only, with commented-out optional dependencies and inline prose |
| **S7.8** | CI | Absent |
| **S7.10** | `.env.example` | Absent, despite `ACLED_EMAIL`, `ACLED_PASSWORD`, `TFL_APP_KEY` being used |
| **S6.5** | Commit messages | Several uninformative: `ui cleanup`, `model done`, `finished report page`, `fix: folder name` |
| **S2.6** | Tests mirror source | No `tests/` tree |
| **S1.7 / S8.1** | Discussable scope | 100 files across 7 disciplines, no reading path |

### 12.3 Passing

| ID | Standard | Evidence |
|---|---|---|
| S1.1, S1.2, S1.5, S1.6 | Public, Python, pre-existing, substantial | Confirmed |
| S1.4 | Original work on a real problem | Hackathon project on a genuine London problem. Strong |
| S2.2 | Single `src/` package root | Confirmed |
| S2.10 | Single entry point | `app.py` plus `ingest.py`, both documented |
| S3.26 | No `TODO` / `FIXME` | Zero found |
| S3.28 | No secrets | Clean scan of source and config |
| S2.9 | Committed data is small seed data | Largest file 42 KB, all genuine seed data |
| S5.9 | Prerequisites stated | Python 3.12 pinned, Intel Mac caveat documented |
| S7.5 | Python version pinned | `.python-version` present |
| S7.11 | Degrades without credentials | ACLED and TfL steps skip cleanly |

### 12.4 Headline numbers

| Metric | Current | Bar |
|---|---|---|
| Tests | 0 | 15 to 25 |
| Test coverage on your modules | 0% | >= 60% |
| `print()` calls in `src/` | 98 | 0 |
| Docstring coverage, your modules | ~3% | >= 90% |
| Functions over 50 lines | 12 | 0 |
| Files over 400 lines | 2 | 0 |
| Your commits linked to your GitHub account | 0 of 5 | 5 of 5 |
| CI status | none | green |
| README length | 322 lines | <= 200 |
| Root-level entries | 11 | <= 12 |

---

## 13. Remediation order

Ordered by MLH weight divided by effort.

| Phase | Work | Standards cleared | Effort |
|---|---|---|---|
| **1** | Fix git identity. Add README "My contribution" section with commit links and a reading path | S6.1, S6.2, S5.11, S8.1, S8.2, S8.3 | 1 hour |
| **2** | Remove the test exclusions from `.gitignore`. Add `tests/` with 15 to 25 pytest tests over the crawler's pure functions and committed HTML fixtures | S4.1 to S4.11, S7.1, S2.6 | 1 day |
| **3** | Add `LICENSE`, `pyproject.toml` with ruff and mypy config, `.env.example`, and a GitHub Actions workflow. Get the badge green | S7.3, S7.4, S7.7, S7.8, S7.9, S7.10 | 3 hours |
| **4** | Rewrite the README to the Section 6.1 structure. Move provenance to `docs/DATA_SOURCES.md`, archive the implementation plan | S5.1 to S5.15, S5.22, S5.14 | 3 hours |
| **5** | Refactor the crawler package: module and function docstrings, `logging` instead of `print`, full type annotations, split the oversized functions, introduce a `Source` base class | S3.1, S3.15, S3.16, S3.20, S5.16, S5.17 | 1 day |
| **6** | Same treatment for `scripts/enrich_events_csv.py` and the route-research processing modules | S3.2, S3.11 to S3.14 | 1 day |
| **7** | Leave the model, contract and UI packages functional but note them as teammates' work. Light formatting pass only | S6.3, S8.3 | 2 hours |

---

## 14. Appendix: automatic red flags

Any one of these, spotted in a 10-minute scan, materially damages the submission.

- A `.gitignore` that excludes tests
- Zero test files
- Commits authored by a placeholder or non-human identity as the largest share of history
- A README that starts with installation instructions instead of what the project is
- No screenshot of a project that has a user interface
- A red CI badge
- Committed `.env`, database files or datasets
- Commented-out blocks of code
- A 500-line file containing two functions
- `except: pass`
- Hardcoded absolute paths
- Commit messages like `fix`, `update`, `asdf`
- Internal planning documents and progress logs shipped in the repository root
- A group project with no statement of who did what