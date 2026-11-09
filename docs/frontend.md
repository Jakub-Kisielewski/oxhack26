# Discipline G: Front End, Full Audit

**Scope:** `app.py`, `src/ui/charts.py`, `src/ui/pages/model_insights.py`, `.streamlit/config.toml`
**Size:** 132 lines, 1 function
**Authorship:** 9 Claude : 5 Jakub : 3 you : 3 Mykhailo by commit count. **The least-yours discipline in the repository**
**Audited against:** `MLH_SUBMISSION_STANDARDS.md` v1.0, filtered through `PIPELINE_SCOPE_CUT.md`
**Date:** 2026-11-08, commit `8199f0e`

> **Repo state.** Since the E audit: audit docs and the contract shim removed (`5849475`), model remediation landed (`b3fd6b5`, `6be67aa`, `2c63e30`, `8199f0e`), and **CI now runs `ruff check .` and `ruff format --check .` with no path argument**. The front end passes both. `tests/` now covers `crawler`, `database`, `models` and `route_research`.

---

## 0. Method and a note on proportion

This discipline is 132 lines. An audit the length of the B or E reports would be theatre, so this one is short on purpose and says plainly where the work should stop.

1. **Manual read** of all four files.
2. **`ruff check` and `ruff format --check`** under the repo's own config.
3. **Cross-layer verification.** Every claim the UI makes about the backtest traced back into `src/models/backtest.py`, because a page whose entire purpose is reporting honest metrics is only as honest as the numbers it labels. This produced the one real defect, §3.1.

---

## 1. Scorecard

| Standard | Verdict | Evidence |
|---|---|---|
| **S2.3** Package boundaries | **PASS** | `app.py` routes, `charts.py` renders, the page composes. Clean |
| **S2.4** Real package | **FAIL** (MINOR) | No `__init__.py` in `src/ui`, and `src/ui/.gitkeep` sits beside two real modules |
| **S2.10** Single obvious entry point | **PASS** | `streamlit run app.py`, documented |
| **S3.1 / S3.2** Function and file size | **PASS** | Largest function 46 lines, largest file 74 |
| **S3.7** Descriptive names | **PASS** | `MODEL_LABELS`, `backtest_charts`, `help_text`. Clear throughout |
| **S3.11 / S3.12** DRY | **FAIL** (MINOR) | `#2a78d6` hardcoded in both `charts.py` and `.streamlit/config.toml`, with a comment asserting they agree. §3.3 |
| **S3.13** Named constants | **PARTIAL** | `MODEL_COLORS`, `METRICS` are good. `(MODEL_COLORS * 3)`, `dy=-8`/`12`, `height=220` are inline |
| **S3.15** Object-orientation | **N/A** | A 132-line rendering layer over typed dataclasses from `src/models/types.py`. Nothing to model here |
| **S3.16** Type annotations | **PASS** | `backtest_charts(bt: BacktestResult) -> None`. The only function, fully annotated |
| **S3.19** No silent excepts | **PASS** | No exception handling at all, which is correct at this size |
| **S3.20** Logging not printing | **PASS** | Zero `print()`. `st.warning` is the right channel here |
| **S3.22** No import-time side effects | **N/A, by design** | Streamlit pages are top-level scripts. Correct idiom, with a testability consequence (§5) |
| **S3.27** No dead code | **PARTIAL** | `st.navigation` wraps a single page: scaffolding left from the deleted five-page app. §3.4 |
| **S3.29 / S3.30** Format and lint | **PASS** | `ruff check` and `ruff format --check` both clean, now under repo-wide CI |
| **S4.x** Tests | **FAIL** | No `tests/ui`. 132 lines untested, though most of it is genuinely hard to test. §5 |
| **S5.3** Visual proof it works | **FAIL** | Still no screenshot anywhere in the repo. This is the discipline that provides one. Cross-reference D-4 |
| **S5.16** Module docstrings | **PARTIAL** | `app.py` and `charts.py` yes; `model_insights.py` no |
| **S5.17** Function docstrings | **FAIL** | `backtest_charts` has none. 0 of 1 |
| **S5.18 / S5.19** Comments explain why | **PASS** | `.streamlit/config.toml`'s one comment explains the colour choice. The in-page caveats are exemplary |
| **Honesty of presentation** | **FAIL, one item** | §3.1 |

**Headline:** this discipline is essentially finished. It is correctly scoped, lints clean, is fully annotated, and the page is unusually honest about what the model can claim. There is **one real defect** (a metric caption that asserts an invariant nothing guarantees), one cross-layer trap worth knowing about, and three cosmetic items. The main recommendation is to fix §3.1 and §3.2 and then stop.

---

## 2. Scope: already cut

Applying the `PIPELINE_SCOPE_CUT.md` test to the front end returns almost nothing, because the cut already happened:

| | Before | Now |
|---|---|---|
| Pages | 5 | **1** |
| Map libraries | pydeck, Folium | **none** |
| Lines | ~2,000 (per `DEVPOST.md`'s five-tool description) | **132** |
| Database access from the UI | yes, via `mapdata` | **none** |

That last row is worth noticing. The page reads `backtest.json` through `read_backtest` and touches DuckDB not at all, so the front end has no connection lifecycle, no caching problem and no query layer. For a Streamlit app that is a strong position, and it is why this audit is short.

The only residue is `st.navigation` around a single page (§3.4) and `src/ui/.gitkeep`.

---

## 3. Findings

### 3.1 The metric caption asserts an invariant nothing enforces

`charts.py:61-64`:

```python
n_key = f"{metric}_n"
n_vals = [bt.summary[m].get(n_key) for m in models if n_key in bt.summary.get(m, {})]
if n_vals:
    st.caption(f"{help_text} (n={int(n_vals[0])} events per model.)")
```

It takes `n_vals[0]`, which is the **route model's** count (first in `MODEL_LABELS` order), and captions it "**per model**", asserting all three models were scored on the same number of events.

Traced into `backtest.py`, that holds for one metric and not the other:

| Metric | Can `n` differ between models? |
|---|---|
| `top1_jaccard` | **No.** `jaccard()` returns `0.0` on an empty union and `_random_walk_jaccard` averages a fixed number of seeds, so every value is finite and `j_n` equals the event count for all three models |
| `mean_log_likelihood` | **Yes.** `baseline_ll` returns `float("nan")` when its list is empty (`backtest.py:131`), which happens if no shortest path to the chosen end exists for an event. `_mean_finite` then drops that event from `shortest_path`'s count only, while `route_model` keeps it |

So on the log-likelihood chart the caption can report the route model's `n` and attribute it to a baseline that was scored on fewer events. In a page built to present an honest comparison against baselines, that is the one claim that must not be loose.

The fix is small and removes the assumption rather than documenting it:

```python
n_by_model = {
    MODEL_LABELS.get(m, m): bt.summary[m][n_key]
    for m in models
    if n_key in bt.summary.get(m, {})
}
counts = set(n_by_model.values())
if len(counts) == 1:
    st.caption(f"{help_text} (n={int(counts.pop())} events, all models.)")
elif counts:
    detail = ", ".join(f"{label} {int(n)}" for label, n in n_by_model.items())
    st.caption(f"{help_text} (events scored: {detail}.)")
else:
    st.caption(help_text)
```

**This is good interview material.** "One of my baselines can fail to produce a score on an event, so I show the per-model event count rather than assuming they match" is exactly the kind of thing that separates someone who read their own output from someone who plotted it.

### 3.2 A cross-layer trap: a successful training run can leave the page saying "no backtest file yet"

`backtest.py:289`:

```python
json.dump(res.to_dict(), f, indent=2, allow_nan=False)
```

`allow_nan=False` makes `json.dump` **raise `ValueError`** on a NaN. But `summary` deliberately stores `float("nan")` when a model has no finite values (`backtest.py:265, 267, 272`). So a run in which any one model scores nothing writes no file at all, and the page then shows:

```python
st.warning("No backtest file yet. Run ingestion, then `python -m src.models.train`.")
```

The user has just run exactly that. The message sends them round the same loop.

The root cause belongs to Discipline F, and `claude/DISCIPLINE_F_MODEL_AUDIT.md` is where the fix should land (emit `null` rather than NaN, which is what `_mean_finite` returning `None` was already set up for). **The front end's share is one line:** distinguish "never run" from "ran and produced nothing usable", so the message matches reality.

```python
if bt is None:
    st.warning(
        "No backtest file at `data/models/backtest.json`. If you have already run training, "
        "check its output: the file is not written when a model scores no events."
    )
```

### 3.3 The theme colour is hardcoded twice

`.streamlit/config.toml`:

```toml
[theme]
# Blue from the chart palette (categorical slot 1 / sequential ramp), so buttons and charts agree.
primaryColor = "#2a78d6"
```

`charts.py:11`:

```python
MODEL_COLORS = ["#2a78d6", "#eb6834", "#1baf7a"]
```

The comment asserts the two agree, and today they do. Nothing keeps them in step: change the palette and the buttons silently diverge from the charts, with a comment still claiming otherwise. Streamlit's config cannot import from Python, so the honest fix is to make the dependency visible in the direction that can be checked:

```python
# Slot 1 must match primaryColor in .streamlit/config.toml.
MODEL_COLORS = ["#2a78d6", "#eb6834", "#1baf7a"]
```

A one-line comment on the Python side, pointing at the file that cannot point back. Cheap, and it survives the next palette change.

### 3.4 `st.navigation` wraps a single page

`app.py:7-16` builds a navigation container for one `st.Page`, which renders a sidebar with a single item. It is scaffolding from the deleted five-page app.

Two smaller problems come with it. The page is referenced as the **string** `"src/ui/pages/model_insights.py"`, resolved relative to the working directory, so `streamlit run app.py` only works from the repo root, and no linter, type checker or IDE can follow the reference or notice a rename. If the app stays single-page, `app.py` collapses to the page itself and both problems go.

Keeping `st.navigation` is defensible if a second page is planned. If so, say that in the module docstring, which costs nothing and converts vestige into intent.

### 3.5 Two Streamlit width APIs, one of them superseded

| Location | Call |
|---|---|
| `charts.py:60` | `st.altair_chart(..., width="stretch")` |
| `model_insights.py:31` | `st.dataframe(..., use_container_width=True)` |

`width="stretch"` is the current form and `use_container_width` is the older one that Streamlit has been migrating away from. With `streamlit>=1.40` unpinned at the top, a future minor release can start emitting deprecation warnings **inside the rendered page**, which is a bad place for them. Using both forms two files apart is also just inconsistent. Move `model_insights.py` to `width="stretch"`.

### 3.6 Minor: formatting assumptions and magic values

| Item | Location | Note |
|---|---|---|
| `fmt = ".2f" if metric == "mean_log_likelihood" else ".0%"` | `charts.py:46` | Assumes every future metric is a proportion. Formatting belongs in the `METRICS` dict beside the title and help text, as a third tuple element |
| `(MODEL_COLORS * 3)[: len(models)]` | `charts.py:34` | Magic `3`. Past nine models colours run out silently, and a fourth model would reuse the route model's blue in a chart where colour identifies the model. `itertools.cycle` or an explicit cap with a fallback grey |
| `dy=-8 if metric != "mean_log_likelihood" else 12` | `charts.py:56` | Correct (log-likelihood is negative so bars run downward and the label sits below), but uncommented. One clause of explanation |
| `height=220`, `width={"band": 0.6}`, `cornerRadiusEnd=4` | `charts.py:51, 60` | Fine as literals in a rendering function, but worth a single `CHART_HEIGHT` if a second chart type is added |
| No docstring on `backtest_charts` | `charts.py:29` | The only function in the discipline. One line |
| No module docstring on `model_insights.py` | `model_insights.py:1` | `app.py` and `charts.py` both have one |

---

## 4. Front-end concerns the standards document does not cover

`MLH_SUBMISSION_STANDARDS.md` was written for a Python code sample and has no front-end section, so these are graded as observations rather than against an S-number.

**Colour accessibility: passes, and not by accident.** The palette is blue, orange and green, and green against orange is the risky pair for the common forms of colour vision deficiency. It does not matter here, because `legend=None` and the model names sit on the x-axis, so colour is a redundant encoding rather than the only one. Values are also printed on the bars via `mark_text`. A reader who cannot distinguish the hues loses nothing. **This is worth saying out loud if asked**, because it reads as luck until you explain the redundancy.

**No interactive state.** No `st.session_state`, no widgets, no callbacks, so there is no state-management surface to get wrong. For a single reporting page that is the right design.

**Empty-data handling is partial.** `read_backtest` returning `None` is handled well, and `charts.py:44` skips a metric whose frame is empty. But `model_insights.py:21` passes `bt.rows` straight to `st.dataframe` with no check, so a result with a summary but no rows renders an empty table under an expander rather than a message. One `if bt.rows:` guard.

**Raw floats in the per-event table.** `mean_log_likelihood` and `top1_jaccard` render at full float precision. `st.column_config` with `format="%.2f"` and `format="%.0f%%"` would make the table readable, and it is the single cheapest visible improvement to the page.

---

## 5. Tests

No `tests/ui`. The honest position is that **most of this should not be tested**, and saying so is better than writing a test that imports Streamlit and asserts nothing.

`model_insights.py` executes `st.title(...)` at import, which is the correct Streamlit idiom and makes the module untestable by construction. `backtest_charts` calls `st.columns`, `st.markdown` and `st.altair_chart`, so testing it means mocking the Streamlit surface, which pins the mock rather than the behaviour.

What is worth testing is the **pure logic currently embedded in the rendering function**. Extracting it is a small refactor that makes the §3.1 fix testable, which is the real reason to do it:

```python
def model_order(summary: dict[str, dict[str, float]]) -> list[str]:
    """Known models first, in display order, then any others as they appear."""


def event_counts(summary: dict[str, dict[str, float]], metric: str) -> dict[str, int]:
    """Events actually scored per model for one metric; may differ between models."""
```

| Target | Tests |
|---|---|
| `model_order` | **3** — known models sorted, unknown appended, empty summary |
| `event_counts` | **3** — equal counts, **unequal counts** (the §3.1 regression), missing key |
| `metric_format` | **2** — log-likelihood is fixed-point, rates are percentages |
| **Total** | **8** |

Eight tests, and the second one is a regression test for a defect in a page about honest reporting. That is the whole case for touching this discipline at all.

---

## 6. Checked and cleared

**Lint and format are clean under repo-wide CI.** `ruff check .` and `ruff format --check .` now run with no path argument and the front end passes both. The C audit's §6.1 and §6.2 are fully closed, and `src/ui` is no longer in `per-file-ignores`.

**Type annotations are complete.** The one function is fully annotated, `from __future__ import annotations` is present, and it consumes `BacktestResult` from `src/models/types.py` rather than a loose dict. The front end is better typed than `src/database`.

**Colour is a redundant encoding, not the only one.** Verified: `legend=None` plus model names on the x-axis plus printed values. §4.

**Unknown models degrade gracefully.** `MODEL_LABELS.get(m, m)` falls back to the raw key and `model_order` appends unknown models rather than dropping them, so adding a fourth baseline in `backtest.py` shows up in the UI without a UI change. That is the right coupling direction.

**No database access, no caching, no session state.** The page reads one JSON file. Nothing to get wrong.

**The `.streamlit/config.toml` comment explains itself.** A one-line config file that says why its one value was chosen.

---

## 7. Strategic position

This discipline is **9 Claude : 5 Jakub : 3 you : 3 Mykhailo**, the most mixed authorship in the repository, and 132 lines.

Two consequences:

1. **Keep the front end out of the reading path.** S8.2 wants the submitted path centred on code you wrote end to end, and S9.1 wants you able to defend every line of it. `src/ingestion/**` is sole-authored by you; this is not. Naming it in `## My contribution` would weaken a section whose whole value is precision.
2. **The screenshot is the contribution this discipline makes to the submission.** S5.3 has been failing since the first audit, and the front end is the only visual artefact in the project. Ten minutes with `streamlit run app.py` produces the single highest-impact README change still outstanding, and taking a screenshot of a teammate's page is not a claim of authorship.

So: fix §3.1 because a wrong honesty claim is worse than no claim, fix §3.2's one line because the error message currently misleads, take the screenshot, and leave the rest.

---

## 8. Work plan

| Step | Work | Clears | Effort |
|---|---|---|---|
| **G-1** | Screenshot the backtest page into `docs/images/`, embed above the fold in the README | **S5.3**, the oldest open MAJOR | **15 min** |
| **G-2** | Fix §3.1: per-model event counts instead of `n_vals[0]`. Extract `model_order` / `event_counts` / `metric_format` and add the 8 tests from §5 | **honesty of presentation**, S4.x | **1 h** |
| **G-3** | Fix §3.2's UI message so "ran but wrote nothing" is distinguishable from "never ran". Raise the `allow_nan=False` root cause in Discipline F | correctness | 20 min |
| **G-4** | `width="stretch"` in `model_insights.py`. `st.column_config` number formats. `if bt.rows:` guard | §3.5, §4 | 30 min |
| **G-5** | Docstring on `backtest_charts` and `model_insights.py`. Comment the colour coupling (§3.3) and the `dy` ternary. Move `fmt` into `METRICS` | S5.16, S5.17, S3.13 | 30 min |
| **G-6** | Collapse `app.py` to the single page, or document the intent to add more. Add `src/ui/__init__.py`, delete `src/ui/.gitkeep` | S3.27, S2.4, S2.5 | 20 min |

**Total: about three hours, and G-1 through G-3 is the part that matters.** G-5 and G-6 are cosmetic on a layer you should not be presenting as yours.

---

## 9. What is already good

- **The page is honest without being asked to be.** "What the model can and can't claim" states that training data are planned routes, that leave-one-out scores are noisy with few events, and that there is no live prediction UI. The caption names the exact file the metrics come from and the command that writes it. The destination block says outright that it measures the shortlist, not the route logit. Putting the limitations *on the page* rather than in a README nobody reaches is the strongest thing about this discipline, and it is directly continuous with the provenance discipline in the ingestion layer.

- **The empty state is actionable.** `read_backtest` returning `None` produces a warning plus a runnable code block with the two commands, not a stack trace. Most people ship a `KeyError`.

- **Baselines are presented alongside the model, including where it loses.** Random walk is in the chart. A page that shows the floor it beats is more persuasive than one showing a single number.

- **Charts are built from typed dataclasses, not dicts.** `BacktestResult` crosses the boundary, so a model-layer change surfaces as a type error rather than a `KeyError` at render time.

- **Redundant encoding in the charts.** Axis labels plus printed values plus colour. Accessible, and it means the chart still reads in greyscale.

- **It degrades gracefully in both directions.** A metric missing from the summary is skipped; a model unknown to `MODEL_LABELS` is still shown with its raw key. Adding a baseline needs no UI change.

- **It is 132 lines.** Resisting the pull to keep a five-page app that no longer had a model behind it was the right call, and the fact that this audit is the shortest of the seven is the evidence.