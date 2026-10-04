# Hypothex Phase 1b (Backend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the phase 1b backend that the new UI needs: pure statistics, the git state fix, task kinds, SDK trace/usage/samples/checkpoint logging, leaderboard test-set noise and paired tests with generated headlines and stat strips, YAML views (kind presets, custom and inline views, validation with line numbers), a server-side panel query engine, the cross-project Overview, a deterministic demo seed, and the HTTP, CLI, and MCP surface for all of it, with `hx serve` serving the built UI.

**Architecture:** Files stay the source of truth; everything builds on phase 1a's `Context`, `RunStore`, and index. Pure modules (`core.stats`, `core.headlines`) feed `core.leaderboard`, which now carries labels, seed values, test-set intervals, `vs_best`, a headline, and a stat strip. `core.views` parses and validates view YAML; `core.sources` flattens run-folder files into rows and `core.panels` turns each panel into `PanelResult` rows, so the UI never reads files. The API, CLI, and MCP share one set of view helpers in `hypothex.mcp.server`.

**Tech Stack:** Python ≥ 3.11, uv, hatchling, pydantic 2, PyYAML (`yaml.compose` marks for line numbers), `difflib`, FastAPI + Starlette `StaticFiles`, Typer, official `mcp` SDK, pytest, ruff, ty, Sphinx + sphinx-rtd-theme + numpydoc. No scipy or numpy in `hypothex` (statistics use the standard library only).

**Spec:** `docs/superpowers/specs/2026-09-26-hypothex-design.md`, section 8 (read 8.1–8.8 before starting; sections 5.3, 6, 10, 11 for context).

**Contract:** `docs/superpowers/plans/2026-09-27-hypothex-phase1b-contract.md`, sections 1–3 (and section 5 for scope). Every name, field, and route listed there is exact. This plan adds private helpers and a few public helpers (listed in each task's Interfaces) but never renames or reshapes a contract name.

**Mockups (visual reference, numbers for the demo):** `docs/mockups/ui-v4/`, `docs/mockups/kinds/{training,agent_eval,agent_iteration,system_bench,custom_view}/`.

**Frontend:** `docs/superpowers/plans/2026-09-27-hypothex-phase1b-frontend.md` (contract section 4) starts after this plan is merged and uses `hx demo` for fixtures.

## Global Constraints

- Python `>=3.11`. Package manager **uv** only (`uv add`, `uv run`, `uv sync`). The UI uses **Bun** (frontend plan); this plan only documents `cd ui && bun run build`.
- Lint and format with **ruff** (line length 100, rules `E F I B UP SIM`), types with **ty**, tests with **pytest** in `tests/` mirroring `src/`. Every task ends with its tests green and `ruff check`, `ruff format --check`, `ty check` clean.
- Every public function has type annotations and a numpydoc docstring (summary, Parameters, Returns, Raises where any, Examples where they help).
- Contract names, fields, row keys, and routes are exact. Phase 1a routes and commands keep working. API errors keep the `{error, type}` shape (view validation adds `issues`).
- Statistics are pure and typed; scipy is not a dependency. `Z95 = 1.959963984540054`.
- Test-set interval per seed group: binary per-example field (`correct`, `solved`, any bool) → Wilson 95% interval with `n` = examples scored; otherwise percentile bootstrap over examples, 1,000 resamples, fixed seed 0. Seeds are pooled by averaging per example first.
- Paired comparison vs best: binary → exact two-sided sign test on discordant examples (fixed vs broken); continuous → paired bootstrap of the mean difference; no per-example data → Welch t-test over seed values (`None` when either sample has n < 2 or both variances are 0).
- Examples needed: the smallest `n` at which the observed discordant rates give `p < 0.05`, search limit `max_n = 100_000`, shown as `≈n`.
- Quantiles use linear interpolation (numpy `"linear"`). ECDFs have at most 200 points. NaN inputs are dropped by every stats function.
- Spike rule for curves: `value > 5 × median(previous 20 values)` for metrics whose name contains `loss` (no zero-median exemption: after a flat 0, any positive value is a spike).
- Git: `GitInfo.dirty` counts tracked changes only. Untracked files are recorded as `untracked_count` plus the first 20 repo-relative paths. Wording: `untracked files only (N)`.
- Task kinds are exactly `generic` (default), `training`, `agent_eval`, `agent_iteration`, `system_bench`. A kind picks the preset view and run-detail layout; it never changes storage or evaluation.
- Views: names match `^[a-z0-9][a-z0-9_-]*$`; `overview` is reserved for the kind preset; files live at `<repo>/.hypothex/views/<task>/<name>.yaml` (atomic write, text stored byte for byte); presets ship at `src/hypothex/views/presets/<kind>.yaml`; an invalid view is never saved.
- Example-id and sample-name file stems: `[^A-Za-z0-9_.-]` → `_`, plus `-<sha1(name)[:8]>` when that changed the name or when the name already ends in `-` + 8 lowercase hex digits, through the one helper `store.safe_stem`. Files store the original id or name in every row, and writers call `store.check_stem_owner` first: an existing file that stores a different original raises `StoreError("id collision: ...")`.
- Telemetry floats (usage `usd`/`seconds`, trace `seconds`) must be finite: `inf` is rejected like `nan` by the SDK and skipped by the readers.
- Seed-group id: `<config hash hex[:8]>@<commit[:7]>` (`nogit` without git), plus `+<diff hash hex[:4]>` for a run with uncommitted changes (`+dirty` when the record has no `git.diff_hash`), through the one helper `leaderboard.group_id_for`. Group labels come from the one helper `leaderboard.group_label`.
- Headlines are one line generated from data. Metrics in [0, 1] get 3 decimals; p-values read `p = 0.15` (two decimals), `p = 0.004` (three decimals when 0.001 ≤ p < 0.01, so a value never reads `p = 0.00`), or `p < 0.001` when tiny; negatives use U+2212 `−`.
- Copy is terse: numbers, glyphs, short labels; explanations live only in tooltips (`stat_strip` rows carry `tooltip`). Identical seeds show `◇×N`, never a fake `± 0`.
- Overview default window: the last 24 h. Naive datetimes are read as UTC everywhere (API `since`, view `runs.since`, `build_overview`).
- `hx demo` is hidden from `--help`. The demo is deterministic (fixed seeds, fixed anchor in tests) and mirrors `docs/mockups/kinds/*/data.js` and `docs/mockups/ui-v4/data.js`.
- `src/hypothex/ui_dist/` is git-ignored and ships in the wheel only when present.
- Git commands in tests pass `-c user.email=t@t -c user.name=t` (use `tests.factories.git` / `init_git_repo`).
- Commits: one conventional message per task, exactly as given in the task. No `Co-Authored-By` lines and no AI or Claude mentions in commits or PR text.

## Review Focus

Five failure modes the spec implies that no part's tests covered, most likely first. Each has a test in the task that owns the code.

1. **A metric returns NaN for one run** (a mean over an empty batch). The leaderboard, headline, stat strip, and Overview must ignore that value as they ignore error scores. Otherwise the NaN group sorts unpredictably, the headline prints `nan`, and Starlette refuses to encode NaN, so the Task page and the Overview answer 500. Test: Task 10 `test_nan_score_is_ignored_like_an_error` (code: `math.isfinite(s.value)` in the score filter of `build_leaderboard`, kept in Tasks 11 and 12).
2. **Example ids with `/`** (`HumanEval/0`, `algebra/123`) are common in agent evals. The run's trace list shows them, and `GET /api/v1/runs/{id}/traces/{example_id}` must open them raw or `%2F`-encoded instead of answering 404. Test: Task 32 `test_trace_ids_with_slashes` (route uses `{example_id:path}`).
3. **`hx demo` run against the user's real home** would mix five demo projects into their Overview, and runs are never deleted. `hx demo` must refuse a home that already has non-demo projects and name a clean alternative. Test: Task 34 `test_demo_refuses_a_home_with_real_projects`.
4. **A run launched with only untracked scratch files** (the acceptance-run case). `hx show` must say `untracked files only (N)`, not `(dirty)` (spec 8.8). The core wording existed (Task 4) but no interface used it. Test: Task 34 `test_show_says_untracked_files_only`.
5. **Two runs scored on different example subsets** (the test split grew between runs). Each group's test-set interval uses its own `n`, and the paired test counts only shared examples. Test: Task 11 `test_paired_test_uses_only_shared_examples`.

---

## File Structure

```
src/hypothex/
  core/
    stats.py           NEW  Wilson, exact sign test, bootstraps, Welch, quantile, ECDF, examples needed  (Tasks 1-2)
    records.py              GitInfo.untracked*, Artifact.step/metrics, UsageTotals, RunRecord.usage     (Task 3)
    gitinfo.py              dirty = tracked only, untracked_files, git_state_label                       (Task 4)
    config.py               TaskKind, TaskSpec.kind/views/baseline/version_param, VIEW_NAME_PATTERN     (Task 5)
    store.py                safe_stem, UsageRow, TraceStep, sum_usage, read_usage/list_traces/
                            read_trace/read_samples: the only readers of usage, traces, samples         (Task 6)
    execution.py            usage totals summed into RunRecord.usage when a run ends                     (Task 8)
    headlines.py       NEW  number formatting, Welch intervals, task headline, stat strip, overview line (Tasks 9, 12, 13)
    leaderboard.py          labels, group_id_for, seed values, launchers, usage, test-set noise,
                            vs_best, baseline/version reference, headline, stat strip                    (Tasks 10-12)
    queries.py              primary_examples; get_leaderboard loads per-example scores                  (Task 14)
    views.py           NEW  view models, presets, resolve, validation, list/get/save/delete, view_context (Tasks 15-17, 19)
    sources.py         NEW  iter_rows: flat rows per data source over run folders                        (Task 18)
    panels.py          NEW  PanelResult, query_panel, query_view (all ten panel types)                    (Tasks 20-23)
    overview.py        NEW  build_overview: timeline, ideas, running, failures, projects                 (Task 24)
  views/presets/       NEW  generic.yaml, training.yaml, agent_eval.yaml, agent_iteration.yaml,
                            system_bench.yaml (package data)                                             (Task 15)
  sdk.py                    log_trace, log_usage, log_samples, log_checkpoint (Run and NoopRun)          (Task 7)
  demo.py              NEW  seed_demo: one demo project per kind, mirroring the mockups                  (Tasks 25-29)
  mcp/server.py             shared view helpers (API, CLI, MCP) + list_views/get_view/add_view/query_view (Task 30)
  api/app.py                view routes, overview, run traces, task kind, SPA serving of ui_dist        (Tasks 31-33)
  cli/main.py               hx view ..., hidden hx demo, git wording in hx show, issues in CLI errors    (Task 34)
pyproject.toml              `pydantic>=2.11` (Task 15); wheel `artifacts` include for src/hypothex/ui_dist/** (Task 33)
.gitignore                  + src/hypothex/ui_dist/                                                      (Task 33)
skills/hypothex/SKILL.md    Views section                                                                (Task 35)
docs/views.rst         NEW  views page; docs/index.rst toctree; docs/cli.rst hx serve + Views           (Tasks 33, 35)
tests/
  core/test_stats.py NEW (1-2), test_records.py NEW (3), test_gitinfo.py (4), test_config.py (5),
  test_store.py (6), test_execution.py (8), test_headlines.py NEW (9, 12, 13),
  test_leaderboard.py (10-12), test_queries.py (14), test_views.py NEW (15-17, 19),
  test_sources.py NEW (18), test_panels.py NEW (20-23), test_overview.py NEW (24)
  test_sdk.py (7), test_demo.py NEW (25-29), mcp/test_server.py (30), api/test_app.py (31-33),
  cli/test_cli.py (34), test_skill.py (35)
```

Dependency order: Part 1 → Part 2 → Part 3 → Part 4 → Part 5 → Part 6 → Part 7. Inside Part 5, Task 19 (`view_context`) needs `sources.iter_rows` from Task 18.

---

## Part 1: Statistics, git state fix, record and config fields (Tasks 1–5)

Contract 1.1, 1.2, 1.3. Spec 8.4, 8.5, 8.7, 8.8.

Scope: `src/hypothex/core/stats.py` (new), `src/hypothex/core/records.py`, `src/hypothex/core/gitinfo.py`, `src/hypothex/core/config.py`, and their tests. `git_state_label()` in core gives the one wording of a run's git state (`untracked files only (N)`); Task 34 prints it in `hx show` and the UI run page (frontend plan) uses the same words.

The part author ran every code block of this part on branch `phase-1b` at `5f76fe1`: full suite 270 passed, `ruff check`, `ruff format --check`, `ty check src` clean.

---

### Task 1: Statistics module: Wilson, exact sign test, bootstrap, quantiles, ECDF, examples needed

**Files:**
- Create: `src/hypothex/core/stats.py`
- Test: `tests/core/test_stats.py` (new)

**Interfaces:**
- Consumes: nothing (pure standard library: `math`, `random`, `bisect`).
- Produces (`hypothex.core.stats`, exact contract 1.1 signatures):
  - `Z95 = 1.959963984540054`
  - `wilson_interval(successes: int, n: int, z: float = Z95) -> tuple[float, float]` (`(0.0, 1.0)` when `n == 0`; ValueError if `successes` is outside `[0, n]`)
  - `binom_two_sided_p(k: int, n: int) -> float` (exact, p = 0.5; 1.0 when `n == 0`)
  - `sign_test(fixed: int, broken: int) -> float` (1.0 if both 0)
  - `bootstrap_mean_interval(values: Sequence[float], resamples: int = 1000, seed: int = 0) -> tuple[float, float]` (percentile 2.5/97.5 of resampled means; ValueError on empty)
  - `paired_bootstrap_p(a: Sequence[float], b: Sequence[float], resamples: int = 1000, seed: int = 0) -> float` (1.0 when no pairs; ValueError on length mismatch)
  - `examples_needed(fixed: int, broken: int, n_total: int, alpha: float = 0.05, max_n: int = 100_000) -> int | None`
  - `quantile(values: Sequence[float], q: float) -> float` (numpy "linear"; ValueError on empty or q outside [0, 1])
  - `ecdf_points(values: Sequence[float], max_points: int = 200) -> list[tuple[float, float]]`
  - All of them ignore NaN inputs. `welch_p` comes in Task 2.

- [ ] **Step 1: Write the failing tests**

Create `tests/core/test_stats.py`:

```python
"""Tests for hypothex.core.stats.

Reference values marked "scipy" were computed with scipy 1.18.1 (``scipy.stats``):
``binomtest(k, n, 0.5).pvalue``, ``2 * t.sf(|t|, df)``, ``beta.cdf(x, a, b)``,
and ``ttest_ind(a, b, equal_var=False).pvalue``. Values marked "statsmodels"
come from statsmodels 0.15 ``proportion_confint(method="wilson")``.
Values marked "numpy" come from numpy 2.5 ``numpy.quantile`` (default ``"linear"``).
"""

import math

import pytest

from hypothex.core.stats import (
    Z95,
    binom_two_sided_p,
    bootstrap_mean_interval,
    ecdf_points,
    examples_needed,
    paired_bootstrap_p,
    quantile,
    sign_test,
    wilson_interval,
)


@pytest.mark.parametrize(
    ("successes", "n", "lo", "hi"),
    [
        (8, 10, 0.49016247153664183, 0.9433178485456247),  # statsmodels
        (45, 50, 0.7863976856252034, 0.9565242350681095),  # statsmodels
        (0, 10, 0.0, Z95**2 / (10 + Z95**2)),  # closed form for 0 successes
    ],
)
def test_wilson_interval_known_values(successes: int, n: int, lo: float, hi: float) -> None:
    got_lo, got_hi = wilson_interval(successes, n)
    assert got_lo == pytest.approx(lo, abs=1e-12)
    assert got_hi == pytest.approx(hi, abs=1e-12)


def test_wilson_interval_is_symmetric_and_handles_edges() -> None:
    lo, hi = wilson_interval(3, 10)
    mirror_lo, mirror_hi = wilson_interval(7, 10)
    assert lo == pytest.approx(1 - mirror_hi, abs=1e-12)
    assert hi == pytest.approx(1 - mirror_lo, abs=1e-12)
    assert wilson_interval(10, 10)[1] == 1.0
    assert wilson_interval(0, 0) == (0.0, 1.0)
    with pytest.raises(ValueError, match="successes"):
        wilson_interval(11, 10)
    with pytest.raises(ValueError, match="successes"):
        wilson_interval(-1, 10)


@pytest.mark.parametrize(
    ("k", "n", "expected"),
    [
        (2, 10, 0.109375),  # 2 * (1 + 10 + 45) / 1024
        (8, 10, 0.109375),  # symmetric
        (0, 5, 0.0625),  # 2 / 32
        (1, 6, 0.21875),  # 2 * (1 + 6) / 64
        (5, 10, 1.0),  # the mode: every outcome is as extreme
        (40, 100, 0.05688793364098089),  # scipy
        (450, 1000, 0.0017305360849763033),  # scipy
        (4900, 10000, 0.04658552770494646),  # scipy (log-space path, n > 1000)
    ],
)
def test_binom_two_sided_p_known_values(k: int, n: int, expected: float) -> None:
    assert binom_two_sided_p(k, n) == pytest.approx(expected, rel=1e-9)


def test_binom_two_sided_p_edges() -> None:
    assert binom_two_sided_p(0, 0) == 1.0
    assert binom_two_sided_p(0, 2000) == 0.0  # true value ~1e-602 underflows
    with pytest.raises(ValueError, match="k"):
        binom_two_sided_p(3, 2)


def test_sign_test() -> None:
    assert sign_test(8, 2) == 0.109375
    assert sign_test(2, 8) == 0.109375
    assert sign_test(15, 3) == pytest.approx(0.007537841796875, rel=1e-12)  # scipy
    assert sign_test(0, 0) == 1.0
    assert sign_test(4, 4) == 1.0
    with pytest.raises(ValueError, match="counts"):
        sign_test(-1, 2)


def test_quantile_matches_numpy_linear() -> None:
    assert quantile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    assert quantile([4.0, 1.0, 3.0, 2.0], 0.25) == 1.75
    values = [float(i) for i in range(1, 101)]
    assert quantile(values, 0.95) == pytest.approx(95.05)  # numpy
    assert quantile(values, 0.99) == pytest.approx(99.01)  # numpy
    assert quantile(values, 0.0) == 1.0
    assert quantile(values, 1.0) == 100.0
    assert quantile([7.0], 0.3) == 7.0
    assert quantile([1.0, math.nan, 3.0], 0.5) == 2.0


def test_quantile_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="empty"):
        quantile([], 0.5)
    with pytest.raises(ValueError, match="empty"):
        quantile([math.nan], 0.5)
    with pytest.raises(ValueError, match="q must be"):
        quantile([1.0], 1.5)


def test_bootstrap_mean_interval_is_near_normal_theory_and_deterministic() -> None:
    values = [0.0] * 50 + [1.0] * 50
    lo, hi = bootstrap_mean_interval(values)
    # normal theory: 0.5 +- 1.96 * sqrt(0.25 / 100) = [0.402, 0.598]
    assert 0.38 <= lo <= 0.42
    assert 0.58 <= hi <= 0.62
    assert bootstrap_mean_interval(values) == (lo, hi)
    assert bootstrap_mean_interval([0.5, 0.5, 0.5]) == (0.5, 0.5)
    assert bootstrap_mean_interval([2.0]) == (2.0, 2.0)
    assert bootstrap_mean_interval([2.0, math.nan]) == (2.0, 2.0)


def test_bootstrap_mean_interval_rejects_empty() -> None:
    with pytest.raises(ValueError, match="empty"):
        bootstrap_mean_interval([])
    with pytest.raises(ValueError, match="resamples"):
        bootstrap_mean_interval([1.0], resamples=0)


def test_paired_bootstrap_p() -> None:
    assert paired_bootstrap_p([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == 1.0
    # a always beats b: no resample reaches 0, so p = 2 * (0 + 1) / 1001
    assert paired_bootstrap_p([1.0] * 20, [0.0] * 20) == pytest.approx(2 / 1001)
    # mean diff 0.1, sd 1.0, n = 400 -> z = 2, normal-theory two-sided p = 0.0455
    diffs = [1.1, -0.9] * 200
    p = paired_bootstrap_p(diffs, [0.0] * 400)
    assert 0.02 < p < 0.09
    assert paired_bootstrap_p(diffs, [0.0] * 400) == p
    assert paired_bootstrap_p([], []) == 1.0
    assert paired_bootstrap_p([1.0, math.nan], [0.0, 5.0]) == pytest.approx(2 / 1001)


def test_paired_bootstrap_p_rejects_length_mismatch() -> None:
    with pytest.raises(ValueError, match="length"):
        paired_bootstrap_p([1.0, 2.0], [1.0])


def test_examples_needed_matches_linear_scan() -> None:
    # at 100 examples, 6 fixed vs 2 broken gives p = 0.289; scaling the rates up,
    # 209 examples (13 fixed, 4 broken: p = 0.049) is the first n below 0.05
    assert examples_needed(6, 2, 100) == 209
    assert sign_test(13, 4) < 0.05 <= sign_test(12, 4)
    scan = next(n for n in range(1, 5000) if sign_test(round(n * 0.06), round(n * 0.02)) < 0.05)
    assert scan == 209
    assert examples_needed(60, 20, 1000) == 209


def test_examples_needed_none_cases() -> None:
    assert examples_needed(3, 3, 100) is None  # no difference to detect
    assert examples_needed(0, 0, 100) is None
    assert examples_needed(1, 0, 0) is None
    assert examples_needed(501, 499, 1000) is None  # needs more than max_n


def test_examples_needed_is_the_true_minimum_when_p_is_not_monotone() -> None:
    # 96,500 examples at rates 0.051 / 0.049: 4922 fixed vs 4728 broken
    assert examples_needed(51, 49, 1000) == 96500
    assert examples_needed(49, 51, 1000) == 96500  # symmetric in fixed and broken
    assert sign_test(4922, 4728) == pytest.approx(0.049444708448976166, rel=1e-9)  # scipy
    # one example fewer rounds fixed down to 4921: p = 0.0506, not significant
    assert sign_test(4921, 4728) == pytest.approx(0.05062351738864937, rel=1e-9)  # scipy
    # one example more rounds broken up to 4729: p = 0.0506 again. p is not monotone in n,
    # so a binary search can land later (it returned 96,677 here); the scan cannot.
    assert sign_test(4922, 4729) == pytest.approx(0.050647447534179824, rel=1e-9)  # scipy


@pytest.mark.parametrize(
    ("fixed", "broken", "n_total", "expected"),
    [
        (6, 2, 100, 209),
        (2, 6, 100, 209),
        (5, 1, 10, 19),
        (3, 0, 5, 10),
        (9, 3, 180, 251),
        (7, 4, 50, 254),
        (13, 9, 120, 670),
    ],
)
def test_examples_needed_matches_a_full_scan(
    fixed: int, broken: int, n_total: int, expected: int
) -> None:
    fixed_rate, broken_rate = fixed / n_total, broken / n_total
    scan = next(
        n
        for n in range(1, 20_001)
        if sign_test(round(n * fixed_rate), round(n * broken_rate)) < 0.05
    )
    assert scan == expected
    assert examples_needed(fixed, broken, n_total, max_n=20_000) == expected


def test_ecdf_points_small_sample() -> None:
    assert ecdf_points([3.0, 1.0, 2.0, 2.0]) == [(1.0, 0.25), (2.0, 0.75), (3.0, 1.0)]
    assert ecdf_points([]) == []
    assert ecdf_points([1.0, math.nan, 2.0]) == [(1.0, 0.5), (2.0, 1.0)]


def test_ecdf_points_downsamples_and_keeps_max() -> None:
    points = ecdf_points([float(i) for i in range(1000)], max_points=200)
    assert len(points) == 200
    assert points[0] == (4.0, 0.005)
    assert points[1] == (9.0, 0.01)
    assert points[-1] == (999.0, 1.0)
    assert all(a[0] < b[0] and a[1] < b[1] for a, b in zip(points, points[1:], strict=False))
    with pytest.raises(ValueError, match="max_points"):
        ecdf_points([1.0], max_points=0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/core/test_stats.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'hypothex.core.stats'`.

- [ ] **Step 3: Write the implementation**

Create `src/hypothex/core/stats.py`:

```python
"""Pure statistics helpers for leaderboards and views (no scipy)."""

from __future__ import annotations

import math
import random
from bisect import bisect_right
from collections.abc import Sequence

Z95 = 1.959963984540054
_EXACT_BINOM_MAX_N = 1000


def _clean(values: Sequence[float]) -> list[float]:
    """Return ``values`` as floats with NaN entries removed."""
    return [float(v) for v in values if not math.isnan(float(v))]


def wilson_interval(successes: int, n: int, z: float = Z95) -> tuple[float, float]:
    """
    Wilson score interval for a binomial proportion.

    Parameters
    ----------
    successes : int
        Number of successes, ``0 <= successes <= n``.
    n : int
        Number of trials.
    z : float
        Normal quantile; the default gives a 95% interval.

    Returns
    -------
    tuple of (float, float)
        Lower and upper bound, both in ``[0, 1]``. ``(0.0, 1.0)`` when ``n == 0``.

    Raises
    ------
    ValueError
        If ``successes`` is outside ``[0, n]``.

    Examples
    --------
    >>> lo, hi = wilson_interval(8, 10)
    >>> round(lo, 4), round(hi, 4)
    (0.4902, 0.9433)
    """
    if n < 0 or not 0 <= successes <= n:
        raise ValueError(f"need 0 <= successes <= n, got successes={successes}, n={n}")
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    half = z / denom * math.sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n))
    lo = 0.0 if successes == 0 else max(0.0, center - half)
    hi = 1.0 if successes == n else min(1.0, center + half)
    return (lo, hi)


def _log_binom_pmf_half(i: int, n: int) -> float:
    """Log of ``C(n, i) / 2**n``."""
    return math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) - n * math.log(2.0)


def binom_two_sided_p(k: int, n: int) -> float:
    """
    Exact two-sided binomial test p-value with success probability 0.5.

    The distribution is symmetric, so the p-value is
    ``min(1, 2 * P(X <= min(k, n - k)))`` for ``X ~ Binomial(n, 0.5)``. Up to
    ``n = 1000`` the tail is an exact integer sum; above that it is summed
    from its largest term down, scaled by that term's log-space value, so it
    stays accurate and fast. Tails below the smallest float return 0.0.

    Parameters
    ----------
    k : int
        Observed number of successes, ``0 <= k <= n``.
    n : int
        Number of trials.

    Returns
    -------
    float
        The p-value in ``[0, 1]``; 1.0 when ``n == 0``.

    Raises
    ------
    ValueError
        If ``k`` is outside ``[0, n]``.

    Examples
    --------
    >>> binom_two_sided_p(2, 10)
    0.109375
    """
    if n < 0 or not 0 <= k <= n:
        raise ValueError(f"need 0 <= k <= n, got k={k}, n={n}")
    m = min(k, n - k)
    if n == 0 or 2 * m >= n:
        return 1.0
    if n <= _EXACT_BINOM_MAX_N:
        return min(1.0, 2 * sum(math.comb(n, i) for i in range(m + 1)) / 2**n)
    total = 1.0
    term = 1.0
    for i in range(m, 0, -1):
        term *= i / (n - i + 1)
        total += term
        if term < 1e-17 * total:
            break
    return min(1.0, 2.0 * math.exp(_log_binom_pmf_half(m, n)) * total)


def sign_test(fixed: int, broken: int) -> float:
    """
    Exact two-sided sign test on discordant pairs.

    Parameters
    ----------
    fixed : int
        Examples the candidate gets right and the reference gets wrong.
    broken : int
        Examples the candidate gets wrong and the reference gets right.

    Returns
    -------
    float
        The p-value; 1.0 when there are no discordant pairs.

    Examples
    --------
    >>> sign_test(8, 2)
    0.109375
    """
    if fixed < 0 or broken < 0:
        raise ValueError(f"counts must be >= 0, got fixed={fixed}, broken={broken}")
    return binom_two_sided_p(fixed, fixed + broken)


def quantile(values: Sequence[float], q: float) -> float:
    """
    Quantile with linear interpolation (numpy's default ``"linear"`` method).

    NaN values are ignored.

    Parameters
    ----------
    values : sequence of float
        Sample values.
    q : float
        Quantile in ``[0, 1]``.

    Returns
    -------
    float
        The interpolated quantile.

    Raises
    ------
    ValueError
        If ``q`` is outside ``[0, 1]`` or no non-NaN values are given.

    Examples
    --------
    >>> quantile([1.0, 2.0, 3.0, 4.0], 0.25)
    1.75
    """
    if not 0.0 <= q <= 1.0:
        raise ValueError(f"q must be in [0, 1], got {q}")
    xs = sorted(_clean(values))
    if not xs:
        raise ValueError("quantile of an empty sample")
    h = (len(xs) - 1) * q
    lo = math.floor(h)
    if lo + 1 >= len(xs):
        return xs[-1]
    return xs[lo] + (h - lo) * (xs[lo + 1] - xs[lo])


def bootstrap_mean_interval(
    values: Sequence[float], resamples: int = 1000, seed: int = 0
) -> tuple[float, float]:
    """
    Percentile bootstrap 95% interval for the mean.

    NaN values are ignored. Resampling uses ``random.Random(seed)``, so the
    result is deterministic for a given input.

    Parameters
    ----------
    values : sequence of float
        Per-example values.
    resamples : int
        Number of bootstrap resamples.
    seed : int
        Seed of the resampling generator.

    Returns
    -------
    tuple of (float, float)
        The 2.5th and 97.5th percentiles of the resampled means.

    Raises
    ------
    ValueError
        If no non-NaN values are given or ``resamples < 1``.

    Examples
    --------
    >>> bootstrap_mean_interval([0.5, 0.5, 0.5])
    (0.5, 0.5)
    """
    xs = _clean(values)
    if not xs:
        raise ValueError("bootstrap of an empty sample")
    if resamples < 1:
        raise ValueError(f"resamples must be >= 1, got {resamples}")
    n = len(xs)
    rng = random.Random(seed)
    means = [sum(rng.choices(xs, k=n)) / n for _ in range(resamples)]
    return (quantile(means, 0.025), quantile(means, 0.975))


def paired_bootstrap_p(
    a: Sequence[float], b: Sequence[float], resamples: int = 1000, seed: int = 0
) -> float:
    """
    Two-sided paired bootstrap p-value for ``mean(a - b) != 0``.

    Pairs are resampled together. The p-value is
    ``min(1, 2 * (min(#(m <= 0), #(m >= 0)) + 1) / (resamples + 1))`` where
    ``m`` runs over the resampled mean differences; the ``+ 1`` keeps it
    above zero. Pairs with a NaN on either side are dropped.

    Parameters
    ----------
    a, b : sequence of float
        Per-example values of the two runs, in the same example order.
    resamples : int
        Number of bootstrap resamples.
    seed : int
        Seed of the resampling generator.

    Returns
    -------
    float
        The p-value in ``(0, 1]``; 1.0 when no pairs remain.

    Raises
    ------
    ValueError
        If ``a`` and ``b`` differ in length or ``resamples < 1``.

    Examples
    --------
    >>> paired_bootstrap_p([1.0, 2.0], [1.0, 2.0])
    1.0
    """
    if len(a) != len(b):
        raise ValueError(f"paired samples differ in length: {len(a)} != {len(b)}")
    if resamples < 1:
        raise ValueError(f"resamples must be >= 1, got {resamples}")
    diffs = [
        float(x) - float(y)
        for x, y in zip(a, b, strict=True)
        if not (math.isnan(float(x)) or math.isnan(float(y)))
    ]
    if not diffs:
        return 1.0
    n = len(diffs)
    rng = random.Random(seed)
    at_or_below = 0
    at_or_above = 0
    for _ in range(resamples):
        m = sum(rng.choices(diffs, k=n)) / n
        at_or_below += m <= 0.0
        at_or_above += m >= 0.0
    return min(1.0, 2.0 * (min(at_or_below, at_or_above) + 1) / (resamples + 1))


def examples_needed(
    fixed: int, broken: int, n_total: int, alpha: float = 0.05, max_n: int = 100_000
) -> int | None:
    """
    Smallest test-set size at which the observed discordant rates would be significant.

    The fixed and broken rates (``fixed / n_total``, ``broken / n_total``) are
    held constant and scaled to ``n`` examples (counts rounded to the nearest
    integer, ``round``). The result is the true minimum ``n <= max_n`` with
    ``sign_test(round(n * fixed_rate), round(n * broken_rate)) < alpha``.
    Rounded counts make the p-value non-monotone in ``n`` (a larger ``n`` can
    round the smaller count up and lose significance), so a binary search could
    miss the minimum. Instead every ``n`` is scanned: the p-value changes only
    when a count changes (by one), and the tail ``P(X <= small)`` of
    ``X ~ Binomial(small + large, 1/2)`` is updated in O(1) per change with

    - larger count + 1: ``F(s; d + 1) = F(s; d) - pmf(s; d) / 2``
    - smaller count + 1: ``F(s + 1; d + 1) = F(s; d) + pmf(s + 1; d) / 2``

    (``pmf`` from ``lgamma``). A candidate below ``alpha`` is confirmed with the
    exact ``binom_two_sided_p`` before it is returned, so float drift in the
    running tail never changes the answer. The scan to ``max_n = 100_000`` takes
    about 0.1 s in the worst case.

    Parameters
    ----------
    fixed : int
        Discordant examples in favour of the candidate.
    broken : int
        Discordant examples against the candidate.
    n_total : int
        Examples scored for both runs.
    alpha : float
        Significance level.
    max_n : int
        Search limit.

    Returns
    -------
    int or None
        The number of examples, or None when ``fixed == broken``,
        ``n_total <= 0``, or ``max_n`` examples would not be enough.

    Examples
    --------
    >>> examples_needed(6, 2, 100)
    209
    """
    if n_total <= 0 or fixed == broken:
        return None
    small_rate = min(fixed, broken) / n_total
    large_rate = max(fixed, broken) / n_total
    small = large = 0
    cdf = 1.0  # P(X <= small) for X ~ Binomial(small + large, 1/2)
    for n in range(1, max_n + 1):
        new_small, new_large = round(n * small_rate), round(n * large_rate)
        if (new_small, new_large) == (small, large):
            continue
        if new_large != large:
            cdf -= 0.5 * math.exp(_log_binom_pmf_half(small, small + large))
            large += 1
        if new_small != small:
            cdf += 0.5 * math.exp(_log_binom_pmf_half(small + 1, small + large))
            small += 1
        total = small + large
        if 2 * min(small, large) >= total:
            continue  # p = 1
        # rounding can briefly put the smaller rate's count above the larger one
        tail = cdf if small < large else 1.0 - cdf + math.exp(_log_binom_pmf_half(small, total))
        if 2.0 * tail < alpha + 1e-9 and binom_two_sided_p(small, total) < alpha:
            return n
    return None


def ecdf_points(values: Sequence[float], max_points: int = 200) -> list[tuple[float, float]]:
    """
    Points ``(x, F(x))`` of the empirical CDF, at most ``max_points`` of them.

    ``F(x)`` is the fraction of values ``<= x``. With more distinct values
    than ``max_points``, points are taken at evenly spaced ranks; the maximum
    (``F = 1``) is always included. NaN values are ignored.

    Parameters
    ----------
    values : sequence of float
        Sample values.
    max_points : int
        Maximum number of points returned, ``>= 1``.

    Returns
    -------
    list of tuple of (float, float)
        Points sorted by ``x``; empty for an empty sample.

    Raises
    ------
    ValueError
        If ``max_points < 1``.

    Examples
    --------
    >>> ecdf_points([3.0, 1.0, 2.0, 2.0])
    [(1.0, 0.25), (2.0, 0.75), (3.0, 1.0)]
    """
    if max_points < 1:
        raise ValueError(f"max_points must be >= 1, got {max_points}")
    xs = sorted(_clean(values))
    n = len(xs)
    if n == 0:
        return []
    distinct = sorted(set(xs))
    if len(distinct) <= max_points:
        candidates = distinct
    else:
        candidates = [xs[-(-(i + 1) * n // max_points) - 1] for i in range(max_points)]
    points: list[tuple[float, float]] = []
    for x in candidates:
        if points and points[-1][0] == x:
            continue
        points.append((x, bisect_right(xs, x) / n))
    return points
```

- [ ] **Step 4: Run the tests, doctests, lint, and types**

Run: `uv run pytest tests/core/test_stats.py -q`
Expected: `32 passed`.

Run: `uv run python -m doctest src/hypothex/core/stats.py && uv run ruff check src/hypothex/core/stats.py tests/core/test_stats.py && uv run ruff format --check src/hypothex/core/stats.py tests/core/test_stats.py && uv run ty check src/hypothex/core/stats.py`
Expected: no doctest output, then `All checks passed!`, `2 files already formatted`, `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/stats.py tests/core/test_stats.py
git commit -m "feat(stats): add Wilson interval, exact sign test, bootstrap, quantiles, and ECDF"
```

---

### Task 2: Welch t-test via the regularized incomplete beta function

**Files:**
- Modify: `src/hypothex/core/stats.py` (append at the end)
- Test: `tests/core/test_stats.py` (replace the import block, append tests)

**Interfaces:**
- Consumes: Task 1 (`hypothex.core.stats`, private `_clean`).
- Produces:
  - `welch_p(a: Sequence[float], b: Sequence[float]) -> float | None` (two-sided; None if either sample has fewer than 2 non-NaN values or both variances are 0; Welch-Satterthwaite df).
  - Private helpers (tested directly, not for other modules): `_regularized_beta(a: float, b: float, x: float) -> float` (`I_x(a, b)`, Numerical Recipes `betacf` continued fraction), `_t_two_sided_p(t: float, df: float) -> float` (`I_{df/(df+t^2)}(df/2, 1/2)`).

- [ ] **Step 1: Write the failing tests**

In `tests/core/test_stats.py`, replace the import block

```python
from hypothex.core.stats import (
    Z95,
    binom_two_sided_p,
    bootstrap_mean_interval,
    ecdf_points,
    examples_needed,
    paired_bootstrap_p,
    quantile,
    sign_test,
    wilson_interval,
)
```

with

```python
from hypothex.core.stats import (
    Z95,
    _regularized_beta,
    _t_two_sided_p,
    binom_two_sided_p,
    bootstrap_mean_interval,
    ecdf_points,
    examples_needed,
    paired_bootstrap_p,
    quantile,
    sign_test,
    welch_p,
    wilson_interval,
)
```

Then append to the end of the file (two blank lines before it):

```python
@pytest.mark.parametrize(
    ("a", "b", "x", "expected"),
    [
        (2.0, 3.0, 0.4, 0.5248),  # 6x^2(1-x)^2 + 4x^3(1-x) + x^4 at x = 0.4
        (0.5, 0.5, 0.3, 0.36901011956554536),  # scipy; also (2/pi) * asin(sqrt(0.3))
        (5.0, 0.5, 0.9, 0.3166429150200122),  # scipy
        (1.0, 1.0, 0.3, 0.3),  # uniform CDF
        (3.0, 3.0, 0.5, 0.5),  # symmetry
    ],
)
def test_regularized_beta_known_values(a: float, b: float, x: float, expected: float) -> None:
    assert _regularized_beta(a, b, x) == pytest.approx(expected, rel=1e-12)


def test_regularized_beta_closed_forms_and_bounds() -> None:
    assert _regularized_beta(0.5, 0.5, 0.3) == pytest.approx(
        2 / math.pi * math.asin(math.sqrt(0.3)), rel=1e-12
    )
    assert _regularized_beta(4.0, 1.0, 0.7) == pytest.approx(0.7**4, rel=1e-12)
    assert _regularized_beta(2.0, 2.0, 0.0) == 0.0
    assert _regularized_beta(2.0, 2.0, 1.0) == 1.0


@pytest.mark.parametrize(
    ("t", "df", "expected"),
    [
        (2.228138851986274, 10, 0.05),  # t_{0.975, 10} from standard t tables
        (12.706204736174707, 1, 0.05),  # t_{0.975, 1}
        (2.570581835636314, 5, 0.05),  # t_{0.975, 5}
        (1.0, 1, 0.5),  # Cauchy: 1 - (2/pi) * atan(1)
        (1.0, 2, 1 - 1 / math.sqrt(3)),  # df=2 closed form: 1 - t / sqrt(2 + t^2)
        (3.0, 30, 0.005389964065651945),  # scipy
        (50.0, 3, 1.761715204127197e-05),  # scipy
        (-2.228138851986274, 10, 0.05),  # sign does not matter
        (0.0, 7, 1.0),
    ],
)
def test_t_two_sided_p_known_values(t: float, df: float, expected: float) -> None:
    assert _t_two_sided_p(t, df) == pytest.approx(expected, rel=1e-9)


def test_t_two_sided_p_large_df_matches_normal() -> None:
    assert _t_two_sided_p(Z95, 1e6) == pytest.approx(0.05, abs=1e-6)
    assert _t_two_sided_p(math.inf, 5) == 0.0


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ([1.0, 2.0, 3.0], [4.0, 5.0, 6.0], 0.021311641128756713),  # scipy; t=-3.674, df=4
        ([1.0, 2.0, 3.0, 4.0, 5.0], [2.0, 4.0, 6.0, 8.0, 10.0], 0.10753119493062724),  # scipy
        ([0.81, 0.79, 0.80], [0.78, 0.77, 0.795], 0.12299329488698767),  # scipy
        ([1.0, 1.0, 1.0], [2.0, 3.0, 4.0], 0.07417990022744854),  # scipy; one zero variance
        ([0.7, 0.72, 0.71, 0.69], [0.65, 0.66], 0.0046605042659501085),  # scipy; unequal n
    ],
)
def test_welch_p_matches_scipy(a: list[float], b: list[float], expected: float) -> None:
    assert welch_p(a, b) == pytest.approx(expected, rel=1e-9)


def test_welch_p_none_cases_and_nan() -> None:
    assert welch_p([1.0], [2.0, 3.0]) is None
    assert welch_p([1.0, 1.0], [2.0, 2.0]) is None  # both variances zero
    assert welch_p([1.0, 2.0, 3.0, math.nan], [4.0, 5.0, 6.0]) == pytest.approx(
        0.021311641128756713, rel=1e-9
    )
    assert welch_p([1.0, math.nan], [2.0, 3.0]) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/core/test_stats.py -q`
Expected: collection error `ImportError: cannot import name '_regularized_beta' from 'hypothex.core.stats'`.

- [ ] **Step 3: Write the implementation**

Append to the end of `src/hypothex/core/stats.py` (two blank lines before it):

```python
_BETACF_MAX_ITER = 300
_BETACF_EPS = 3.0e-16
_BETACF_FPMIN = 1.0e-300


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Numerical Recipes ``betacf``)."""
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < _BETACF_FPMIN:
        d = _BETACF_FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, _BETACF_MAX_ITER + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < _BETACF_FPMIN:
            d = _BETACF_FPMIN
        c = 1.0 + aa / c
        if abs(c) < _BETACF_FPMIN:
            c = _BETACF_FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < _BETACF_FPMIN:
            d = _BETACF_FPMIN
        c = 1.0 + aa / c
        if abs(c) < _BETACF_FPMIN:
            c = _BETACF_FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _BETACF_EPS:
            break
    return h


def _regularized_beta(a: float, b: float, x: float) -> float:
    """
    Regularized incomplete beta function ``I_x(a, b)``.

    Parameters
    ----------
    a, b : float
        Positive shape parameters.
    x : float
        Point in ``[0, 1]``.

    Returns
    -------
    float
        ``I_x(a, b)`` in ``[0, 1]``.
    """
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_front = (
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    )
    front = math.exp(log_front)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def _t_two_sided_p(t: float, df: float) -> float:
    """
    Two-sided p-value ``P(|T| >= |t|)`` for Student's t with ``df`` degrees of freedom.

    Uses ``P(|T| >= |t|) = I_{df / (df + t^2)}(df / 2, 1 / 2)``.

    Parameters
    ----------
    t : float
        The t statistic.
    df : float
        Degrees of freedom (may be fractional), ``> 0``.

    Returns
    -------
    float
        The two-sided p-value.
    """
    if math.isinf(t):
        return 0.0
    return min(1.0, _regularized_beta(df / 2.0, 0.5, df / (df + t * t)))


def welch_p(a: Sequence[float], b: Sequence[float]) -> float | None:
    """
    Two-sided Welch t-test p-value for a difference in means.

    NaN values are ignored. Degrees of freedom follow Welch-Satterthwaite.

    Parameters
    ----------
    a, b : sequence of float
        The two independent samples (for example, one value per seed).

    Returns
    -------
    float or None
        The p-value, or None when either sample has fewer than 2 values or
        both samples have zero variance.

    Examples
    --------
    >>> round(welch_p([1.0, 2.0, 3.0], [4.0, 5.0, 6.0]), 6)
    0.021312
    """
    xs = _clean(a)
    ys = _clean(b)
    if len(xs) < 2 or len(ys) < 2:
        return None
    na, nb = len(xs), len(ys)
    ma, mb = sum(xs) / na, sum(ys) / nb
    va = sum((x - ma) ** 2 for x in xs) / (na - 1)
    vb = sum((y - mb) ** 2 for y in ys) / (nb - 1)
    if va == 0.0 and vb == 0.0:
        return None
    sa, sb = va / na, vb / nb
    t = (ma - mb) / math.sqrt(sa + sb)
    df = (sa + sb) ** 2 / (sa * sa / (na - 1) + sb * sb / (nb - 1))
    return _t_two_sided_p(t, df)
```

- [ ] **Step 4: Run the tests, doctests, lint, and types**

Run: `uv run pytest tests/core/test_stats.py -q`
Expected: `54 passed`.

Run: `uv run python -m doctest src/hypothex/core/stats.py && uv run ruff check src/hypothex/core/stats.py tests/core/test_stats.py && uv run ruff format --check src/hypothex/core/stats.py tests/core/test_stats.py && uv run ty check src/hypothex/core/stats.py`
Expected: no doctest output, then `All checks passed!`, `2 files already formatted`, `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/stats.py tests/core/test_stats.py
git commit -m "feat(stats): add Welch t-test using the regularized incomplete beta function"
```

---

### Task 3: Record fields: untracked git state, checkpoint step and metrics, usage totals

**Files:**
- Modify: `src/hypothex/core/records.py` (`GitInfo`, `Artifact`, new `UsageTotals`, `RunRecord.usage`)
- Test: `tests/core/test_records.py` (new)

**Interfaces:**
- Consumes: phase 1a `RunStore`, `Layout`, `append_jsonl`, `tests.factories.make_record`.
- Produces (`hypothex.core.records`, exact contract 1.2):
  - `GitInfo(repo: str | None, commit: str | None, branch: str | None, dirty: bool = False, untracked_count: int = 0, untracked: list[str] = [])`; `dirty` now means tracked changes only (set by Task 4).
  - `Artifact(kind, path, host="local", size=None, step: int | None = None, metrics: dict[str, float] = {})`.
  - `UsageTotals(tokens_in: int = 0, tokens_out: int = 0, usd: float = 0.0, seconds: float = 0.0, calls: int = 0)`.
  - `RunRecord.usage: UsageTotals | None = None` (filled by `execute_run` finalisation in Task 8; this task only adds the field).

- [ ] **Step 1: Write the failing tests**

Create `tests/core/test_records.py`:

```python
from pathlib import Path

from hypothex.core.fsutil import append_jsonl
from hypothex.core.layout import Layout
from hypothex.core.records import Artifact, GitInfo, RunRecord, UsageTotals
from hypothex.core.store import RunStore
from tests.factories import make_record

PHASE_1A_RUN = {
    "run_id": "r-old",
    "project": "toy",
    "command": ["echo", "hi"],
    "command_template": ["echo", "hi"],
    "cwd": "/tmp",
    "environment_id": "env1",
    "host": "mac",
    "config_hash": "sha256:abc",
    "status": "finished",
    "created_at": "2026-09-26T10:00:00Z",
    "git": {"repo": None, "commit": "a" * 40, "branch": "main", "dirty": True},
    "artifacts": [{"kind": "checkpoint", "path": "/ck/1.pt", "host": "local", "size": 3}],
}


def test_phase_1a_run_yaml_still_loads_with_new_defaults() -> None:
    record = RunRecord.model_validate(PHASE_1A_RUN)
    assert record.git.dirty is True
    assert record.git.untracked_count == 0 and record.git.untracked == []
    assert record.artifacts[0].step is None and record.artifacts[0].metrics == {}
    assert record.usage is None


def test_usage_totals_defaults() -> None:
    assert UsageTotals().model_dump() == {
        "tokens_in": 0,
        "tokens_out": 0,
        "usd": 0.0,
        "seconds": 0.0,
        "calls": 0,
    }


def test_new_fields_round_trip_through_run_yaml(tmp_path: Path) -> None:
    layout = Layout(tmp_path)
    layout.ensure()
    store = RunStore(layout)
    record = make_record(
        git=GitInfo(commit="b" * 40, dirty=False, untracked_count=2, untracked=["a.txt", "b.txt"]),
        artifacts=[
            Artifact(kind="checkpoint", path="/ck/5.pt", step=500, metrics={"val_loss": 1.92})
        ],
        usage=UsageTotals(tokens_in=1200, tokens_out=300, usd=0.042, seconds=12.5, calls=4),
    )
    store.create_run(record)
    loaded = store.read_record("toy", "r1")
    assert loaded.git.untracked_count == 2 and loaded.git.untracked == ["a.txt", "b.txt"]
    assert loaded.artifacts[0].step == 500
    assert loaded.artifacts[0].metrics == {"val_loss": 1.92}
    assert loaded.usage == UsageTotals(
        tokens_in=1200, tokens_out=300, usd=0.042, seconds=12.5, calls=4
    )


def test_sdk_style_artifact_rows_without_step_still_parse(tmp_path: Path) -> None:
    layout = Layout(tmp_path)
    layout.ensure()
    store = RunStore(layout)
    store.create_run(make_record())
    run_dir = layout.run_dir("toy", "r1")
    append_jsonl(run_dir / "artifacts.jsonl", {"kind": "model", "path": "/m.pt", "size": 1})
    append_jsonl(
        run_dir / "artifacts.jsonl",
        {"kind": "checkpoint", "path": "/c.pt", "step": 10, "metrics": {"loss": 0.5}},
    )
    arts = store.read_artifacts("toy", "r1")
    assert [(a.kind, a.step, a.metrics) for a in arts] == [
        ("model", None, {}),
        ("checkpoint", 10, {"loss": 0.5}),
    ]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/core/test_records.py -q`
Expected: collection error `ImportError: cannot import name 'UsageTotals' from 'hypothex.core.records'`.

- [ ] **Step 3: Add the fields**

In `src/hypothex/core/records.py`, replace

```python
class GitInfo(BaseModel):
    """Git state of the working copy a run was launched from."""

    repo: str | None = None
    commit: str | None = None
    branch: str | None = None
    dirty: bool = False
```

with

```python
class GitInfo(BaseModel):
    """
    Git state of the working copy a run was launched from.

    ``dirty`` is True only for changes to tracked files (what ``git.diff``
    captures). Untracked files are counted separately in
    ``untracked_count``; ``untracked`` holds the first 20 of their paths,
    relative to the repo root.
    """

    repo: str | None = None
    commit: str | None = None
    branch: str | None = None
    dirty: bool = False
    untracked_count: int = 0
    untracked: list[str] = Field(default_factory=list)
```

Replace

```python
class Artifact(BaseModel):
    """A large file recorded by path, not copied."""

    kind: str
    path: str
    host: str = "local"
    size: int | None = None
```

with

```python
class Artifact(BaseModel):
    """
    A large file recorded by path, not copied.

    Checkpoints also carry the training ``step`` they were saved at and the
    ``metrics`` logged with them (for example ``{"val_loss": 1.92}``).
    """

    kind: str
    path: str
    host: str = "local"
    size: int | None = None
    step: int | None = None
    metrics: dict[str, float] = Field(default_factory=dict)


class UsageTotals(BaseModel):
    """Summed resource use of a run (from ``usage.jsonl``) or of a group of runs."""

    tokens_in: int = 0
    tokens_out: int = 0
    usd: float = 0.0
    seconds: float = 0.0
    calls: int = 0
```

In `class RunRecord`, replace

```python
    created_by: str = "human"

    @property
```

with

```python
    created_by: str = "human"
    usage: UsageTotals | None = None

    @property
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/core/test_records.py tests/core/test_store.py -q`
Expected: all pass (`4 passed` from `test_records.py`, and every `test_store.py` test still passes).

Run: `uv run ruff check src/hypothex/core/records.py tests/core/test_records.py && uv run ruff format --check src/hypothex/core/records.py tests/core/test_records.py && uv run ty check src/hypothex/core/records.py`
Expected: `All checks passed!`, `2 files already formatted`, `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/records.py tests/core/test_records.py
git commit -m "feat(records): add untracked git fields, checkpoint step and metrics, usage totals"
```

---

### Task 4: Git state fix: dirty means tracked changes; untracked files recorded separately

**Files:**
- Modify: `src/hypothex/core/gitinfo.py` (new constant, new `untracked_files`, `git_info` body, new `git_state_label`)
- Test: `tests/core/test_gitinfo.py` (import block, appended tests)

**Interfaces:**
- Consumes: Task 3 (`GitInfo.untracked_count`, `GitInfo.untracked`).
- Produces (`hypothex.core.gitinfo`):
  - `UNTRACKED_LIST_LIMIT = 20`
  - `git_info(path: Path) -> GitInfo` (same signature): `dirty` from `git status --porcelain --untracked-files=no`; untracked from `git ls-files --others --exclude-standard -z` run at the repo top level.
  - `untracked_files(path: Path) -> list[str]`: repo-relative, git-sorted, whole repo; `[]` outside a repo.
  - `git_state_label(info: GitInfo) -> str`: `"no git"`, `"dirty"`, `"dirty, N untracked"`, `"untracked files only (N)"`, or `"clean"`. Task 34 makes `hx show` print this string instead of ` (dirty)`; the UI run page (frontend plan) uses the same words.

- [ ] **Step 1: Write the failing tests**

In `tests/core/test_gitinfo.py`, replace

```python
from hypothex.core.gitinfo import capture_diff, create_worktree, git_info, head_commit
```

with

```python
from hypothex.core.gitinfo import (
    capture_diff,
    create_worktree,
    git_info,
    git_state_label,
    head_commit,
    untracked_files,
)
from hypothex.core.records import GitInfo
```

Then append to the end of the file (two blank lines before it):

```python
def test_untracked_only_is_not_dirty(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.txt").write_text("one\n")
    init_git_repo(repo)
    (repo / "notes.txt").write_text("scratch\n")
    info = git_info(repo)
    assert not info.dirty
    assert info.untracked_count == 1 and info.untracked == ["notes.txt"]
    assert capture_diff(repo).diff is None
    assert git_state_label(info) == "untracked files only (1)"


def test_tracked_change_is_dirty_and_untracked_counted_separately(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.txt").write_text("one\n")
    init_git_repo(repo)
    (repo / "a.txt").write_text("two\n")
    (repo / "new.txt").write_text("x\n")
    info = git_info(repo)
    assert info.dirty and info.untracked_count == 1
    assert git_state_label(info) == "dirty, 1 untracked"


def test_staged_new_file_is_dirty_not_untracked(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.txt").write_text("one\n")
    init_git_repo(repo)
    (repo / "added.txt").write_text("x\n")
    git(repo, "add", "added.txt")
    info = git_info(repo)
    assert info.dirty and info.untracked_count == 0 and info.untracked == []
    assert git_state_label(info) == "dirty"


def test_ignored_files_are_not_untracked(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".gitignore").write_text("*.log\nout/\n")
    init_git_repo(repo)
    (repo / "train.log").write_text("x\n")
    (repo / "out").mkdir()
    (repo / "out" / "p.jsonl").write_text("{}\n")
    info = git_info(repo)
    assert not info.dirty and info.untracked_count == 0
    assert git_state_label(info) == "clean"


def test_untracked_list_is_capped_at_20_but_counts_all(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)
    for i in range(25):
        (repo / f"f{i:02d}.txt").write_text("x\n")
    info = git_info(repo)
    assert info.untracked_count == 25
    assert info.untracked == [f"f{i:02d}.txt" for i in range(20)]


def test_untracked_paths_are_repo_relative_from_a_subdirectory(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "m.py").write_text("x = 1\n")
    init_git_repo(repo)
    (repo / "top level é.txt").write_text("x\n")
    (repo / "src" / "new.py").write_text("y = 2\n")
    assert untracked_files(repo / "src") == ["src/new.py", "top level é.txt"]
    info = git_info(repo / "src")
    assert info.untracked_count == 2 and not info.dirty


def test_untracked_files_outside_a_repo(tmp_path: Path) -> None:
    assert untracked_files(tmp_path) == []
    assert git_state_label(git_info(tmp_path)) == "no git"


def test_git_state_label_from_stored_records() -> None:
    assert git_state_label(GitInfo()) == "no git"
    assert git_state_label(GitInfo(commit="abc")) == "clean"
    assert git_state_label(GitInfo(commit="abc", dirty=True)) == "dirty"
    label = git_state_label(GitInfo(commit="abc", untracked_count=3))
    assert label == "untracked files only (3)"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/core/test_gitinfo.py -q`
Expected: collection error `ImportError: cannot import name 'git_state_label' from 'hypothex.core.gitinfo'`.

- [ ] **Step 3: Write the implementation**

In `src/hypothex/core/gitinfo.py`, replace

```python
DIFF_LIMIT_BYTES = 5 * 1024 * 1024
```

with

```python
DIFF_LIMIT_BYTES = 5 * 1024 * 1024
UNTRACKED_LIST_LIMIT = 20
```

Then replace the whole `def git_info(path: Path) -> GitInfo:` function (from its `def` line down to the blank lines before `def capture_diff`) with:

```python
def untracked_files(path: Path) -> list[str]:
    """
    List untracked, non-ignored files of the whole repo containing ``path``.

    Parameters
    ----------
    path : Path
        Directory inside a git repo (any subdirectory works).

    Returns
    -------
    list of str
        Paths relative to the repo root, in git's (sorted) order; empty when
        ``path`` is not inside a git repo.
    """
    top = _git(path, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        return []
    out = _git(Path(top.stdout.strip()), "ls-files", "--others", "--exclude-standard", "-z")
    if out.returncode != 0:
        return []
    return [name for name in out.stdout.split("\0") if name]


def git_info(path: Path) -> GitInfo:
    """
    Describe the git state of ``path``.

    ``dirty`` counts tracked changes only (staged or unstaged), matching what
    ``capture_diff`` saves. Untracked files are reported separately.

    Parameters
    ----------
    path : Path
        Directory inside (or outside) a git repo.

    Returns
    -------
    GitInfo
        Empty (all None) when ``path`` is not inside a git repo.
    """
    commit = head_commit(path)
    if commit is None:
        return GitInfo()
    branch = _git(path, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or None
    remote = _git(path, "remote", "get-url", "origin")
    status = _git(path, "status", "--porcelain", "--untracked-files=no")
    untracked = untracked_files(path)
    return GitInfo(
        repo=strip_credentials(remote.stdout.strip()) if remote.returncode == 0 else None,
        commit=commit,
        branch=branch,
        dirty=bool(status.stdout.strip()),
        untracked_count=len(untracked),
        untracked=untracked[:UNTRACKED_LIST_LIMIT],
    )


def git_state_label(info: GitInfo) -> str:
    """
    One-line wording of a run's git state for run pages and ``hx show``.

    Parameters
    ----------
    info : GitInfo
        The run's recorded git state.

    Returns
    -------
    str
        ``"no git"``, ``"dirty"``, ``"dirty, N untracked"``,
        ``"untracked files only (N)"``, or ``"clean"``.

    Examples
    --------
    >>> git_state_label(GitInfo(commit="abc", untracked_count=2))
    'untracked files only (2)'
    >>> git_state_label(GitInfo(commit="abc", dirty=True))
    'dirty'
    """
    if info.commit is None:
        return "no git"
    if info.dirty:
        return f"dirty, {info.untracked_count} untracked" if info.untracked_count else "dirty"
    if info.untracked_count:
        return f"untracked files only ({info.untracked_count})"
    return "clean"
```

Note: `split("\0")` is a NUL split. `-z` makes git print paths raw (no quoting of spaces or non-ASCII names). `git ls-files` only lists the current directory's subtree, so it runs at `rev-parse --show-toplevel`; `git status` is already repo-wide.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/core/test_gitinfo.py tests/core/test_execution.py tests/core/test_control.py -q`
Expected: all pass (`16 passed` from `test_gitinfo.py`; execution and control tests unchanged).

Run: `uv run python -m doctest src/hypothex/core/gitinfo.py && uv run ruff check src/hypothex/core/gitinfo.py tests/core/test_gitinfo.py && uv run ruff format --check src/hypothex/core/gitinfo.py tests/core/test_gitinfo.py && uv run ty check src/hypothex/core/gitinfo.py`
Expected: no doctest output, then `All checks passed!`, `2 files already formatted`, `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/gitinfo.py tests/core/test_gitinfo.py
git commit -m "fix(git): count only tracked changes as dirty and record untracked files separately"
```

---

### Task 5: Task kind, inline views, baseline, and version param in `hypothex.yaml`

**Files:**
- Modify: `src/hypothex/core/config.py` (imports, constants, `TaskSpec`, `ProjectConfig._check_references`, `starter_config`, YAML guards and `load_project_config`)
- Test: `tests/core/test_config.py` (one assertion added, tests appended)

**Interfaces:**
- Consumes: phase 1a `ProjectConfig`, `load_project_config`.
- Produces (`hypothex.core.config`, exact contract 1.3):
  - `TaskKind = Literal["generic", "training", "agent_eval", "agent_iteration", "system_bench"]`
  - `TaskSpec.kind: TaskKind = "generic"`, `TaskSpec.views: dict[str, dict[str, Any]] = {}` (bodies validated later by `hypothex.core.views`), `TaskSpec.baseline: str | None = None`, `TaskSpec.version_param: str = "version"` (non-empty).
  - `VIEW_NAME_PATTERN = r"^[a-z0-9][a-z0-9_-]*$"` and `RESERVED_VIEW_NAMES = frozenset({"overview"})`; `hypothex.core.views` should import these instead of redefining them. Bad or reserved inline view names fail at config load with `ConfigError`.
  - Two general YAML guards, used by `load_project_config` here and by `views.validate_view_text` (Task 16):
    - `scan_yaml(text) -> YamlScan` streams the `yaml.parse` events before anything is composed or loaded (the loader recurses once per level, so 600 nested `[` raised `RecursionError`). `YamlScan(problem, first_anchor, views_anchor, cycle)`: `problem = ("YAML nested too deeply (over 64 levels)", line)` at the first collection deeper than `YAML_MAX_DEPTH = 64`, or `("YAML too large (over 100000 events)", line)` past `YAML_MAX_EVENTS = 100_000` (the scan stops there); `first_anchor` = line of the first anchor or alias anywhere; `views_anchor` = line of the first anchor or alias at or under `tasks.<task>.views`, where a key written as an alias (`*vk:` with `&vk views` elsewhere) is resolved to the scalar its anchor names; `cycle` = line of the first alias to a collection that is still open.
    - `has_cycle(data) -> bool`: an iterative (non-recursive) walk of the loaded value; a dict or list met again while on the current path (by `id()`) is a cycle.
  - `load_project_config` raises `ConfigError("<path>: <message> (line N)")` with, in this order: the `scan_yaml` problem; `YAML anchors and aliases are not allowed in views` (`NO_VIEW_ANCHORS`) for `views_anchor`; `YAML aliases must not form a cycle` (`YAML_CYCLE`) when `has_cycle` finds one anywhere (line = `scan.cycle`, omitted if None). Anchors elsewhere in `hypothex.yaml` stay allowed.

- [ ] **Step 1: Write the failing tests**

In `tests/core/test_config.py`, replace

```python
def test_starter_config_is_valid(tmp_path: Path) -> None:
    cfg = load_project_config(_write(tmp_path, starter_config("my-proj")))
    assert cfg.project == "my-proj"
```

with

```python
def test_starter_config_is_valid(tmp_path: Path) -> None:
    cfg = load_project_config(_write(tmp_path, starter_config("my-proj")))
    assert cfg.project == "my-proj"
    assert cfg.tasks["example-test"].kind == "generic"
```

Then append to the end of the file (two blank lines before it):

```python
def test_task_kind_and_view_fields_default(tmp_path: Path) -> None:
    task = load_project_config(_write(tmp_path, VALID)).tasks["uspto-topk"]
    assert task.kind == "generic"
    assert task.views == {}
    assert task.baseline is None
    assert task.version_param == "version"


def test_task_kind_and_views_load(tmp_path: Path) -> None:
    text = VALID.replace(
        "    primary: topk/k=1\n",
        "    primary: topk/k=1\n"
        "    kind: system_bench\n"
        "    baseline: tag:baseline\n"
        "    version_param: prompt_version\n"
        "    views:\n"
        "      route-quality:\n"
        "        title: route quality\n"
        "        panels: [{type: leaderboard}]\n",
    )
    task = load_project_config(_write(tmp_path, text)).tasks["uspto-topk"]
    assert task.kind == "system_bench"
    assert task.baseline == "tag:baseline"
    assert task.version_param == "prompt_version"
    assert task.views == {
        "route-quality": {"title": "route quality", "panels": [{"type": "leaderboard"}]}
    }


@pytest.mark.parametrize(
    ("addition", "message"),
    [
        ("    kind: benchmark\n", "kind"),
        ("    version_param: ''\n", "version_param"),
        ("    views: {Route: {title: x}}\n", "view name 'Route' must match"),
        ("    views: {overview: {title: x}}\n", "reserved"),
        ("    views: {a.b: {title: x}}\n", "view name 'a.b' must match"),
    ],
)
def test_invalid_task_kind_and_view_names(tmp_path: Path, addition: str, message: str) -> None:
    text = VALID.replace("    primary: topk/k=1\n", "    primary: topk/k=1\n" + addition)
    with pytest.raises(ConfigError, match=message):
        load_project_config(_write(tmp_path, text))


LOOP_LINE = "            spec: &s {mark: point, layer: [*s]}"


def _line_of(text: str, needle: str) -> int:
    return next(i for i, row in enumerate(text.splitlines(), 1) if needle in row)


def test_inline_view_anchors_and_aliases_are_rejected_with_their_line(tmp_path: Path) -> None:
    # regression: this inline view contains itself; it loaded, then views recursed forever
    loop = (
        "    views:\n      loop:\n        title: loop\n        panels:\n"
        f"          - type: vega_lite\n{LOOP_LINE}\n"
    )
    text = VALID.replace("    primary: topk/k=1\n", "    primary: topk/k=1\n" + loop)
    line = _line_of(text, LOOP_LINE)
    with pytest.raises(
        ConfigError, match=rf"YAML anchors and aliases are not allowed in views \(line {line}\)"
    ):
        load_project_config(_write(tmp_path, text))
    # an alias inside views to an anchor outside them is rejected as well
    text = VALID.replace("    split: test\n", "    split: &sp test\n").replace(
        "    primary: topk/k=1\n", "    primary: topk/k=1\n    views: {v: {title: *sp}}\n"
    )
    line = _line_of(text, "views: {v: {title: *sp}}")
    with pytest.raises(ConfigError, match=rf"not allowed in views \(line {line}\)"):
        load_project_config(_write(tmp_path, text))


@pytest.mark.parametrize(
    "views",
    [
        "{loop: {title: loop, panels: [{type: vega_lite, spec: &s {mark: point, layer: [*s]}}]}}",
        "{v: {title: x}}",
    ],
)
def test_views_key_written_as_an_alias_is_resolved(tmp_path: Path, views: str) -> None:
    # regression: `*vk:` names `views` through an anchor defined elsewhere, which hid
    # the self-referencing view below it from a check that only read plain keys
    text = VALID.replace("    split: test\n", "    split: test\n    description: &vk views\n")
    text = text.replace("    primary: topk/k=1\n", f"    primary: topk/k=1\n    *vk: {views}\n")
    line = _line_of(text, "*vk:")
    with pytest.raises(
        ConfigError, match=rf"YAML anchors and aliases are not allowed in views \(line {line}\)"
    ):
        load_project_config(_write(tmp_path, text))


def test_deep_or_cyclic_yaml_is_a_config_error(tmp_path: Path) -> None:
    # regression: 600 nested lists raised RecursionError inside the YAML loader
    deep = "[" * 600 + "]" * 600
    text = VALID.replace("    split: test\n", f"    split: test\n    description: {deep}\n")
    line = _line_of(text, "description:")
    with pytest.raises(
        ConfigError, match=rf"YAML nested too deeply \(over 64 levels\) \(line {line}\)"
    ):
        load_project_config(_write(tmp_path, text))
    # a cycle outside views: metric params that contain themselves
    text = VALID.replace("    params: {k: [1, 5]}\n", "    params: &p {k: [1, 5], again: *p}\n")
    line = _line_of(text, "again: *p")
    with pytest.raises(ConfigError, match=rf"YAML aliases must not form a cycle \(line {line}\)"):
        load_project_config(_write(tmp_path, text))


def test_anchors_outside_views_stay_allowed(tmp_path: Path) -> None:
    text = VALID.replace(
        "    path: data/test.jsonl\n", "    path: &test data/test.jsonl\n"
    ).replace("test: data/test.jsonl}", "test: *test}")
    assert "*test" in text
    cfg = load_project_config(_write(tmp_path, text))
    assert cfg.datasets["uspto50k"].splits["test"] == "data/test.jsonl"
    shared = VALID.replace("    params: {k: [1, 5]}\n", "    params: &p {k: [1, 5]}\n")
    shared = shared.replace("    split: test\n", "    split: test\n    description: *p\n")
    assert "*p" in shared  # a shared (not cyclic) mapping: passes the guards
    with pytest.raises(ConfigError, match="description"):  # then fails the model: not a str
        load_project_config(_write(tmp_path, shared))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/core/test_config.py -q`
Expected: `10 failed, 14 passed` (`AttributeError: 'TaskSpec' object has no attribute 'kind'`; `ConfigError ... Extra inputs are not permitted` for the `views`/`baseline` keys, also in the anchor and aliased-key tests, where it does not match the expected message; `RecursionError` in `test_deep_or_cyclic_yaml_is_a_config_error`). The `kind: benchmark` and `version_param: ''` cases, and `test_anchors_outside_views_stay_allowed`, already pass.

- [ ] **Step 3: Write the implementation**

In `src/hypothex/core/config.py`, replace

```python
from typing import Any
```

with

```python
from typing import Any, Literal, NamedTuple
```

Replace

```python
NAME_PATTERN = r"^[a-z0-9][a-z0-9_.-]*$"
```

with

```python
NAME_PATTERN = r"^[a-z0-9][a-z0-9_.-]*$"
VIEW_NAME_PATTERN = r"^[a-z0-9][a-z0-9_-]*$"
RESERVED_VIEW_NAMES = frozenset({"overview"})
TaskKind = Literal["generic", "training", "agent_eval", "agent_iteration", "system_bench"]
```

Replace the `TaskSpec` class

```python
class TaskSpec(_Strict):
    """Dataset + metrics + primary metric: the unit of comparison."""

    dataset: str
    split: str | None = None
    metrics: list[str] = Field(min_length=1)
    primary: str
    description: str = ""
```

with

```python
class TaskSpec(_Strict):
    """
    Dataset + metrics + primary metric: the unit of comparison.

    ``kind`` picks the preset task view and run-detail layout; it never
    changes storage or evaluation. ``views`` holds inline view bodies
    (validated by ``hypothex.core.views``). ``baseline`` is a seed-group
    selector (``tag:<tag>`` or a group id) that ``system_bench`` compares
    against. ``version_param`` names the run param that orders
    ``agent_iteration`` groups.
    """

    dataset: str
    split: str | None = None
    metrics: list[str] = Field(min_length=1)
    primary: str
    description: str = ""
    kind: TaskKind = "generic"
    views: dict[str, dict[str, Any]] = Field(default_factory=dict)
    baseline: str | None = None
    version_param: str = Field(default="version", min_length=1)
```

In `ProjectConfig._check_references`, replace

```python
            primary_metric, _ = parse_metric_key(task.primary)
            if primary_metric not in task.metrics:
                errors.append(f"task {name!r}: primary {task.primary!r} is not one of its metrics")
```

with

```python
            primary_metric, _ = parse_metric_key(task.primary)
            if primary_metric not in task.metrics:
                errors.append(f"task {name!r}: primary {task.primary!r} is not one of its metrics")
            for view in task.views:
                if not re.match(VIEW_NAME_PATTERN, view):
                    errors.append(
                        f"task {name!r}: view name {view!r} must match {VIEW_NAME_PATTERN}"
                    )
                elif view in RESERVED_VIEW_NAMES:
                    errors.append(f"task {name!r}: view name {view!r} is reserved for the preset")
```

In `starter_config`, replace

```text
    metrics: [accuracy]
    primary: accuracy

stages:
```

with

```text
    metrics: [accuracy]
    primary: accuracy
    kind: generic                    # or training, agent_eval, agent_iteration, system_bench

stages:
```

Replace the whole `load_project_config` function

```python
def load_project_config(repo: Path) -> ProjectConfig:
    """
    Load and validate ``<repo>/hypothex.yaml``.

    Parameters
    ----------
    repo : Path
        Repository root directory.

    Returns
    -------
    ProjectConfig
        The parsed and validated project config.

    Raises
    ------
    ConfigError
        If the file is missing or invalid.
    """
    path = repo / CONFIG_FILENAME
    if not path.is_file():
        raise ConfigError(f"no {CONFIG_FILENAME} in {repo}; run `hx init` first")
    try:
        return ProjectConfig.model_validate(read_yaml(path))
    except (ValidationError, ValueError, yaml.YAMLError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc
```

with

```python
YAML_MAX_DEPTH = 64
YAML_MAX_EVENTS = 100_000
NO_VIEW_ANCHORS = "YAML anchors and aliases are not allowed in views"
YAML_CYCLE = "YAML aliases must not form a cycle"


class YamlScan(NamedTuple):
    """
    What ``scan_yaml`` found in a YAML text; lines are 1-based, None when absent.

    Attributes
    ----------
    problem : tuple of (str, int) or None
        ``(message, line)`` when the text nests deeper than ``YAML_MAX_DEPTH``
        or has more than ``YAML_MAX_EVENTS`` parser events; the scan stopped there.
    first_anchor : int or None
        Line of the first anchor or alias anywhere.
    views_anchor : int or None
        Line of the first anchor or alias at or under ``tasks.<task>.views``, with
        alias keys resolved to the scalar their anchor names.
    cycle : int or None
        Line of the first alias to a collection that is still open (one of its own
        ancestors), so the loaded value would contain itself.
    """

    problem: tuple[str, int] | None
    first_anchor: int | None
    views_anchor: int | None
    cycle: int | None


def _in_views(path: tuple[Any, ...]) -> bool:
    """Tell whether a key path is ``tasks.<task>.views`` or below it."""
    return len(path) >= 3 and path[0] == "tasks" and path[2] == "views"


def scan_yaml(text: str) -> YamlScan:
    """
    Pre-scan YAML text as a stream of parser events, before anything is built.

    ``yaml.compose`` and ``yaml.safe_load`` recurse once per nesting level, so a
    few hundred nested ``[`` raise ``RecursionError``. This scan keeps a depth
    counter instead and stops at the first collection deeper than
    ``YAML_MAX_DEPTH`` or the first event past ``YAML_MAX_EVENTS``. On the way it
    finds anchors and aliases: the first anywhere (view files allow none), the
    first at or under ``tasks.<task>.views`` (inline views allow none; a key
    written as an alias, ``*vk:``, is resolved to the scalar its anchor names),
    and the first alias to a collection that is still open (a cycle).

    Parameters
    ----------
    text : str
        YAML text.

    Returns
    -------
    YamlScan
        The first problem and the lines of interest.

    Raises
    ------
    yaml.YAMLError
        If the text is not valid YAML (up to where the scan stopped).

    Examples
    --------
    >>> scan_yaml("a: " + "[" * 70 + "]" * 70).problem
    ('YAML nested too deeply (over 64 levels)', 1)
    >>> scan_yaml("n: &k views\\ntasks:\\n  t:\\n    *k: {v: {title: x}}\\n").views_anchor
    4
    >>> scan_yaml("a: &a [1, *a]\\n").cycle
    1
    >>> scan_yaml("a: &a [1]\\nb: *a\\n")
    YamlScan(problem=None, first_anchor=1, views_anchor=None, cycle=None)
    """
    first_anchor: int | None = None
    views_anchor: int | None = None
    cycle: int | None = None
    scalars: dict[str, str] = {}  # anchor -> scalar value, to resolve alias keys
    # one frame per open collection: its key path, its anchor, and for a mapping
    # whether the next node is a key and the last key read
    frames: list[dict[str, Any]] = []
    for count, event in enumerate(yaml.parse(text, Loader=yaml.SafeLoader), start=1):
        line = event.start_mark.line + 1
        if count > YAML_MAX_EVENTS:
            too_large = (f"YAML too large (over {YAML_MAX_EVENTS} events)", line)
            return YamlScan(too_large, first_anchor, views_anchor, cycle)
        if isinstance(event, yaml.CollectionEndEvent):
            frames.pop()
            continue
        if not isinstance(event, yaml.NodeEvent):
            continue
        path: tuple[Any, ...] = ()
        if frames:
            top = frames[-1]
            if not top["mapping"]:
                path = (*top["path"], None)
            else:
                if top["key_next"]:
                    if isinstance(event, yaml.ScalarEvent):
                        top["key"] = event.value
                    elif isinstance(event, yaml.AliasEvent):
                        top["key"] = scalars.get(event.anchor or "")
                    else:
                        top["key"] = None
                top["key_next"] = not top["key_next"]
                path = (*top["path"], top["key"])
        if event.anchor is not None:
            if first_anchor is None:
                first_anchor = line
            if views_anchor is None and _in_views(path):
                views_anchor = line
            if isinstance(event, yaml.AliasEvent):
                if cycle is None and any(f["anchor"] == event.anchor for f in frames):
                    cycle = line
            elif isinstance(event, yaml.ScalarEvent):
                scalars[event.anchor] = event.value
        if isinstance(event, yaml.CollectionStartEvent):
            if len(frames) >= YAML_MAX_DEPTH:
                too_deep = (f"YAML nested too deeply (over {YAML_MAX_DEPTH} levels)", line)
                return YamlScan(too_deep, first_anchor, views_anchor, cycle)
            frames.append(
                {
                    "path": path,
                    "anchor": event.anchor,
                    "mapping": isinstance(event, yaml.MappingStartEvent),
                    "key_next": True,
                    "key": None,
                }
            )
    return YamlScan(None, first_anchor, views_anchor, cycle)


def has_cycle(data: Any) -> bool:
    """
    Tell whether a loaded YAML value contains itself (a cycle made by aliases).

    An iterative depth-first walk, so depth never costs Python stack: a dict or
    list met again while it is still on the current path is a cycle. Containers
    already finished are not walked twice, so shared (non-cyclic) aliases cost
    linear time.

    Parameters
    ----------
    data : Any
        A value from ``yaml.safe_load``.

    Returns
    -------
    bool
        True if some dict or list contains itself.

    Examples
    --------
    >>> loop = {"a": 1}
    >>> loop["self"] = [loop]
    >>> shared = [1]
    >>> has_cycle(loop), has_cycle({"x": shared, "y": {"z": shared}})
    (True, False)
    """
    on_path: set[int] = set()
    done: set[int] = set()
    stack: list[tuple[Any, bool]] = [(data, False)]
    while stack:
        node, leaving = stack.pop()
        if leaving:
            on_path.discard(id(node))
            done.add(id(node))
            continue
        if not isinstance(node, dict | list) or id(node) in done:
            continue
        if id(node) in on_path:
            return True
        on_path.add(id(node))
        stack.append((node, True))
        children = node.values() if isinstance(node, dict) else node
        stack.extend((child, False) for child in children)
    return False


def load_project_config(repo: Path) -> ProjectConfig:
    """
    Load and validate ``<repo>/hypothex.yaml``.

    The text is pre-scanned first (``scan_yaml``): nesting deeper than
    ``YAML_MAX_DEPTH`` or more than ``YAML_MAX_EVENTS`` events, and any anchor or
    alias at or under ``tasks.<task>.views``, are errors with their line. After
    loading, a value that contains itself (``has_cycle``) is an error too.
    Anchors elsewhere stay allowed.

    Parameters
    ----------
    repo : Path
        Repository root directory.

    Returns
    -------
    ProjectConfig
        The parsed and validated project config.

    Raises
    ------
    ConfigError
        If the file is missing or invalid, too deep or too large, uses an anchor
        or alias in an inline view, or has aliases that form a cycle.
    """
    path = repo / CONFIG_FILENAME
    if not path.is_file():
        raise ConfigError(f"no {CONFIG_FILENAME} in {repo}; run `hx init` first")
    try:
        scan = scan_yaml(path.read_text(encoding="utf-8"))
        blocked = scan.problem is not None or scan.views_anchor is not None
        data = None if blocked else read_yaml(path)
    except (ValueError, yaml.YAMLError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    line: int | None
    if scan.problem is not None:
        message, line = scan.problem
    elif scan.views_anchor is not None:
        message, line = NO_VIEW_ANCHORS, scan.views_anchor
    elif has_cycle(data):
        message, line = YAML_CYCLE, scan.cycle
    else:
        try:
            return ProjectConfig.model_validate(data)
        except (ValidationError, ValueError) as exc:
            raise ConfigError(f"{path}: {exc}") from exc
    where = "" if line is None else f" (line {line})"
    raise ConfigError(f"{path}: {message}{where}")
```

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest tests/core/test_config.py -q`
Expected: `24 passed`.

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check src`
Expected: every test passes (0 failed), then `All checks passed!`, `... files already formatted`, `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/config.py tests/core/test_config.py
git commit -m "feat(config): add task kind, inline views, baseline, and version param"
```

## Part 2: SDK additions and usage finalisation (Tasks 6–8)

This part adds the phase 1b SDK calls (`log_trace`, `log_usage`, `log_samples`,
`log_checkpoint`), the store readers the query engine uses (`read_usage`, `list_traces`,
`read_trace`, `read_samples`), and sums `usage.jsonl` into `RunRecord.usage` when a run
ends. Contract: section 1.10. Spec: section 8.7.

**Consumes (from Task 3, `hypothex.core.records`, contract 1.2):**
- `Artifact` with new fields `step: int | None = None` and `metrics: dict[str, float] = {}`.
- `UsageTotals(tokens_in: int = 0, tokens_out: int = 0, usd: float = 0.0, seconds: float = 0.0, calls: int = 0)`.
- `RunRecord.usage: UsageTotals | None = None`.

**Produces (used by `core.sources`, `core.panels`, `core.leaderboard`, the API, and `hypothex.demo`):**
- `hypothex.core.store.safe_stem(name: str) -> str` — `[^A-Za-z0-9_.-]` → `_`; `-` + the first 8 hex digits of `sha1(name)` are appended when that changes the name OR when the name already ends in `-[0-9a-f]{8}` (`a/b` → `a_b-3ec69c85`, `a_b-3ec69c85` → `a_b-3ec69c85-d64fa8bc`, `a_b` stays `a_b`); `ValueError` on `""`. Two distinct names share a stem only when they sanitise alike and their sha1 digests share 8 hex digits; `check_stem_owner` catches that.
- `hypothex.core.store.check_stem_owner(path: Path, key: str, original: str) -> None` — called by every trace/sample writer before it writes `path`; when the file exists and its first line stores a different string under `key` (`example_id` for traces, `name` for samples), raises `StoreError("id collision: <file> already holds <key> '<stored>', not '<original>'")`. A missing file, an empty file, or a first line without that key passes.
- `hypothex.core.store.UsageRow(BaseModel)`: `example_id: str | None = None`, `tokens_in: int = 0`, `tokens_out: int = 0`, `usd: float = 0.0`, `seconds: float = 0.0` (all `>= 0`; floats must be finite, so `inf` is rejected like `nan`).
- `hypothex.core.store.TraceStep(BaseModel)`: `turn: int`, `tool: str | None = None`, `args: Any = None`, `result: Any = None`, `tokens_in: int = 0`, `tokens_out: int = 0`, `seconds: float = 0.0` (finite), `error: str | None = None`.
- `hypothex.core.store.sum_usage(rows: Iterable[UsageRow]) -> UsageTotals | None` (None when no rows; `calls` = row count).
- `RunStore.read_usage(project: str, run_id: str) -> list[UsageRow]`.
- `RunStore.list_traces(project: str, run_id: str) -> list[dict[str, Any]]` — rows `{"example_id": str, "turns": int, "failed": bool}`, sorted by `example_id`; `example_id` is the original id stored in the file, also for an empty trace (the body of `GET /runs/{id}/traces`, Task 32; also used by `core.sources` and the trace panel).
- `RunStore.read_trace(project: str, run_id: str, example_id: str) -> list[TraceStep]` (`[]` when the example has no trace).
- `RunStore.read_samples(project: str, run_id: str) -> dict[str, list[float]]` (series name = the original name stored in the rows; the file stem only for files written without it).
- `hypothex.sdk.Run` / `NoopRun`: `log_trace`, `log_usage`, `log_samples`, `log_checkpoint` with the exact contract 1.10 signatures.
- File formats (every line is one JSON object):
  - `traces/<safe_stem(example_id)>.jsonl`: `{"example_id", "turn", "tool", "args", "result", "tokens_in", "tokens_out", "seconds", "error"}`; replaced on each `log_trace`. An empty trace is one marker line `{"example_id": <id>}`, so the file exists and keeps the original id; readers skip marker lines.
  - `usage.jsonl`: `{"example_id", "tokens_in", "tokens_out", "usd", "seconds"}`; appended.
  - `samples/<safe_stem(name)>.jsonl`: `{"name": str, "value": float}` (the original series name in every row); appended.
  - `artifacts.jsonl` checkpoint row: `{"kind": "checkpoint", "path", "host", "size", "step", "metrics"}`.

Known limit, owned outside this part: a run marked `lost` by `core.control` does not get `usage` totals (only `execute_run` finalises). File names: `safe_stem` adds a hash of the original name whenever it has to replace a character or the name already looks hashed, so a stem is shared only on an 8-hex-digit sha1 prefix collision; every row stores the original id or name, and `log_trace` / `log_samples` refuse (`StoreError`, nothing written) to write a file that stores a different original.

---

### Task 6: Store readers for usage, traces, and samples

**Files:**
- Modify: `src/hypothex/core/store.py` (imports at the top; new module-level helpers after `RUN_SUBDIRS`; new `RunStore` methods after `read_artifacts`; new `_parse_steps` at the end)
- Test: `tests/core/test_store.py`

**Interfaces:**
- Consumes: `hypothex.core.records.UsageTotals` (Task 3); existing `read_jsonl`, `_parse_rows`, `Layout.run_dir`.
- Produces: `safe_stem`, `check_stem_owner`, `UsageRow`, `TraceStep`, `sum_usage`, `RunStore.read_usage`, `RunStore.list_traces`, `RunStore.read_trace`, `RunStore.read_samples` (signatures in the Part 2 notes above). These are the only readers of `usage.jsonl`, `traces/`, and `samples/`: `core.sources`, `core.panels`, the API, and `hypothex.demo` all call them.

- [ ] **Step 1: Write the failing tests**

In `tests/core/test_store.py`, replace the two import lines

```python
from hypothex.core.records import ScoreRecord
from hypothex.core.store import RunStore
```

with

```python
from hypothex.core.records import ScoreRecord, UsageTotals
from hypothex.core.store import (
    RunStore,
    TraceStep,
    UsageRow,
    check_stem_owner,
    safe_stem,
    sum_usage,
)
```

and replace the first four lines

```python
import fcntl
from pathlib import Path

import pytest
```

with

```python
import fcntl
import math
from pathlib import Path

import pytest
from pydantic import ValidationError
```

Then append these tests at the end of the file:

```python
def test_safe_stem_replaces_unsafe_characters_and_adds_a_hash() -> None:
    # sha1("route 7/b:ü")[:8] = b85600fe, sha1("../x")[:8] = 72e4d01d
    assert safe_stem("route 7/b:ü") == "route_7_b__-b85600fe"
    assert safe_stem("a-b_c.d") == "a-b_c.d"  # already safe: unchanged, no hash
    assert safe_stem("../x") == ".._x-72e4d01d"
    with pytest.raises(ValueError, match="must not be empty"):
        safe_stem("")


def test_safe_stem_never_merges_distinct_names() -> None:
    names = ["a/b", "a_b", "a b", "a:b", "a_b-3ec69c85"]
    stems = [safe_stem(n) for n in names]
    assert stems[:2] == ["a_b-3ec69c85", "a_b"]
    assert len(set(stems)) == len(names)


def test_safe_stem_hashes_names_that_already_look_hashed() -> None:
    # regression: "a_b-3ec69c85" is already safe, but kept as is it would take the
    # file of "a/b"; a name ending in "-" + 8 lowercase hex digits is hashed too
    assert safe_stem("a/b") == "a_b-3ec69c85"
    assert safe_stem("a_b-3ec69c85") == "a_b-3ec69c85-d64fa8bc"  # sha1(...)[:8]
    assert safe_stem("a/b") != safe_stem("a_b-3ec69c85")
    assert safe_stem("run-12345678") == "run-12345678-736848d3"
    assert safe_stem("run-1234567") == "run-1234567"  # 7 digits: not a hash tail
    assert safe_stem("run-ABCDEF12") == "run-ABCDEF12"  # upper case: not a hash tail


def test_check_stem_owner_rejects_a_different_original(tmp_path: Path) -> None:
    path = tmp_path / "a_b-3ec69c85.jsonl"
    check_stem_owner(path, "example_id", "a/b")  # no file yet
    path.write_text("")
    check_stem_owner(path, "example_id", "a/b")  # empty file
    path.write_text('{"example_id": "a/b", "turn": 1}\n')
    check_stem_owner(path, "example_id", "a/b")  # the same original: overwrite is fine
    path.write_text('{"example_id": "x/y", "turn": 1}\n')
    with pytest.raises(
        StoreError,
        match=r"id collision: a_b-3ec69c85\.jsonl already holds example_id 'x/y', not 'a/b'",
    ):
        check_stem_owner(path, "example_id", "a/b")
    samples = tmp_path / "lat.jsonl"
    samples.write_text('{"name": "lat", "value": 1.0}\n')
    check_stem_owner(samples, "name", "lat")
    with pytest.raises(StoreError, match="id collision"):
        check_stem_owner(samples, "name", "lat2")
    samples.write_text('{"value": 1.0}\n')  # written by hand, no stored name: not checked
    check_stem_owner(samples, "name", "lat2")


def test_read_usage_skips_bad_rows_and_sums(store: RunStore) -> None:
    store.create_run(make_record())
    path = store.layout.run_dir("toy", "r1") / "usage.jsonl"
    append_jsonl(
        path, {"example_id": "a", "tokens_in": 100, "tokens_out": 20, "usd": 0.25, "seconds": 1.5}
    )
    append_jsonl(path, {"tokens_in": -1})  # negative: skipped
    append_jsonl(path, {"tokens_in": "many"})  # not a number: skipped
    append_jsonl(path, {"usd": math.inf})  # json writes Infinity and reads it back: skipped
    append_jsonl(path, {"seconds": math.nan})  # NaN: skipped
    append_jsonl(
        path, {"example_id": None, "tokens_in": 50, "tokens_out": 5, "usd": 0.125, "seconds": 0.5}
    )
    assert "Infinity" in path.read_text()
    rows = store.read_usage("toy", "r1")
    assert rows == [
        UsageRow(example_id="a", tokens_in=100, tokens_out=20, usd=0.25, seconds=1.5),
        UsageRow(tokens_in=50, tokens_out=5, usd=0.125, seconds=0.5),
    ]
    # 0.25 + 0.125 and 1.5 + 0.5 are exact in binary floating point.
    assert sum_usage(rows) == UsageTotals(
        tokens_in=150, tokens_out=25, usd=0.375, seconds=2.0, calls=2
    )
    assert sum_usage([]) is None
    assert store.read_usage("toy", "missing") == []


def test_usage_and_trace_floats_must_be_finite() -> None:
    with pytest.raises(ValidationError, match="finite number"):
        UsageRow(usd=math.inf)
    with pytest.raises(ValidationError, match="finite number"):
        TraceStep(turn=1, seconds=math.inf)


def test_list_and_read_traces(store: RunStore) -> None:
    store.create_run(make_record())
    traces = store.layout.run_dir("toy", "r1") / "traces"
    assert store.list_traces("toy", "r1") == []
    ab = traces / f"{safe_stem('a/b')}.jsonl"  # a_b-3ec69c85.jsonl
    append_jsonl(
        ab,
        {
            "example_id": "a/b",
            "turn": 1,
            "tool": "retro_expand",
            "tokens_in": 4410,
            "tokens_out": 512,
            "seconds": 4.82,
        },
    )
    append_jsonl(
        ab, {"example_id": "a/b", "turn": 2, "tool": "check_stock", "error": "timeout 8 s"}
    )
    append_jsonl(ab, {"example_id": "a/b", "turn": 3, "seconds": math.inf})  # not finite: skipped
    append_jsonl(traces / "c.jsonl", {"tool": "score_routes"})  # no turn, no example_id
    append_jsonl(traces / "c.jsonl", {"turn": "x"})  # invalid: skipped
    # an empty trace is one marker line holding the original id
    append_jsonl(traces / f"{safe_stem('e/0')}.jsonl", {"example_id": "e/0"})
    assert store.list_traces("toy", "r1") == [
        {"example_id": "a/b", "turns": 2, "failed": True},
        {"example_id": "c", "turns": 1, "failed": False},
        {"example_id": "e/0", "turns": 0, "failed": False},
    ]
    steps = store.read_trace("toy", "r1", "a/b")
    assert steps == [
        TraceStep(turn=1, tool="retro_expand", tokens_in=4410, tokens_out=512, seconds=4.82),
        TraceStep(turn=2, tool="check_stock", error="timeout 8 s"),
    ]
    assert store.read_trace("toy", "r1", "a_b") == []  # a different id, a different file
    assert store.read_trace("toy", "r1", "c") == [TraceStep(turn=1, tool="score_routes")]
    assert store.read_trace("toy", "r1", "e/0") == []
    assert store.read_trace("toy", "r1", "nope") == []


def test_read_samples(store: RunStore) -> None:
    store.create_run(make_record())
    samples = store.layout.run_dir("toy", "r1") / "samples"
    assert store.read_samples("toy", "r1") == {}
    samples.mkdir()
    (samples / "latency_ms.jsonl").write_text(
        '{"value": 12.5}\n{"value": 15}\n{"value": "slow"}\n{"value": true}\n{"value": NaN}\n'
        '{"value": Infinity}\n'
    )
    (samples / "ttft.jsonl").write_text('{"value": 3.0}\n')
    # the SDK stores the original name in every row; the key is that name, not the stem
    (samples / f"{safe_stem('latency ms')}.jsonl").write_text(
        '{"name": "latency ms", "value": 1.0}\n{"name": "latency ms", "value": 2.0}\n'
    )
    assert store.read_samples("toy", "r1") == {
        "latency ms": [1.0, 2.0],
        "latency_ms": [12.5, 15.0],
        "ttft": [3.0],
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/core/test_store.py -v`
Expected: collection error, `ImportError: cannot import name 'TraceStep' from 'hypothex.core.store'`.

- [ ] **Step 3: Implement the readers**

In `src/hypothex/core/store.py`, replace the import block (from `import fcntl` down to the `from hypothex.core.records import ...` line) with:

```python
import fcntl
import hashlib
import json
import logging
import math
import re
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel, Field, ValidationError

from hypothex.core.config import ProjectConfig
from hypothex.core.errors import RunNotFoundError, StoreError
from hypothex.core.fsutil import (
    append_jsonl,
    append_note_file,
    atomic_write_text,
    read_jsonl,
    read_yaml,
    write_yaml,
)
from hypothex.core.ids import utcnow
from hypothex.core.layout import Layout
from hypothex.core.records import Artifact, MetricPoint, RunRecord, ScoreRecord, UsageTotals
```

Replace the line `RUN_SUBDIRS = ("logs", "predictions", "env")` with this block (it keeps `RUN_SUBDIRS` and adds the helpers; `class ProjectEntry` follows unchanged):

```python
RUN_SUBDIRS = ("logs", "predictions", "env")
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9_.-]")
_HASH_TAIL = re.compile(r"-[0-9a-f]{8}\Z")


def safe_stem(name: str) -> str:
    """
    Turn an example id or sample name into a file name stem.

    Every character outside ``[A-Za-z0-9_.-]`` becomes ``_``, so the name can never
    contain a path separator and leave its folder. ``-`` and the first 8 hex digits
    of ``sha1(name)`` are appended when that changes the name, and also when the
    name already ends in ``-`` plus 8 lowercase hex digits (so ``a_b-3ec69c85``
    cannot take the stem of ``a/b``). Any other name is returned unchanged. So an
    unchanged stem never ends in a hash and a hashed one always does: two distinct
    names share a stem only if they sanitise alike and their sha1 digests share the
    first 8 hex digits, which ``check_stem_owner`` catches before a write.

    Parameters
    ----------
    name : str
        Example id or sample name.

    Returns
    -------
    str
        The file name stem.

    Raises
    ------
    ValueError
        If ``name`` is empty.

    Examples
    --------
    >>> safe_stem("route 7/b")
    'route_7_b-5db86396'
    >>> safe_stem("a_b")
    'a_b'
    >>> safe_stem("a_b-3ec69c85")
    'a_b-3ec69c85-d64fa8bc'
    """
    if not name:
        raise ValueError("name must not be empty")
    stem = _UNSAFE_CHARS.sub("_", name)
    if stem == name and not _HASH_TAIL.search(name):
        return stem
    return f"{stem}-{hashlib.sha1(name.encode('utf-8')).hexdigest()[:8]}"


def check_stem_owner(path: Path, key: str, original: str) -> None:
    """
    Refuse to write a trace or sample file that belongs to a different id or name.

    ``safe_stem`` gives two distinct names one stem only on an 8-hex-digit sha1
    prefix collision. Every row of a trace or sample file stores the original id
    (``example_id``) or name (``name``), so writers call this before they write:
    an existing file whose first line stores a different original is a collision.

    Parameters
    ----------
    path : Path
        The trace or sample file about to be written.
    key : str
        Row key of the original: ``example_id`` for traces, ``name`` for samples.
    original : str
        The id or name about to be written.

    Raises
    ------
    StoreError
        If the file exists and its first line stores a different string under
        ``key``. A missing or empty file, or a first line without that key (a file
        written by hand), passes.

    Examples
    --------
    >>> check_stem_owner(Path("/nonexistent/a_b.jsonl"), "example_id", "a_b")
    """
    if not path.is_file():
        return
    with path.open("rb") as fh:
        first = fh.readline()
    try:
        row = json.loads(first)
    except ValueError:
        return
    stored = row.get(key) if isinstance(row, dict) else None
    if isinstance(stored, str) and stored != original:
        raise StoreError(
            f"id collision: {path.name} already holds {key} {stored!r}, not {original!r}"
        )


class UsageRow(BaseModel):
    """
    One ``log_usage`` call; a line of ``usage.jsonl``.

    Examples
    --------
    >>> UsageRow(tokens_in=100, usd=0.25).tokens_out
    0
    """

    example_id: str | None = None
    tokens_in: int = Field(0, ge=0)
    tokens_out: int = Field(0, ge=0)
    # allow_inf_nan=False: ge=0 alone lets +inf through, and an inf in the run
    # totals would break JSON responses later
    usd: float = Field(0.0, ge=0, allow_inf_nan=False)
    seconds: float = Field(0.0, ge=0, allow_inf_nan=False)


class TraceStep(BaseModel):
    """
    One step of an agent trajectory; a line of ``traces/<example_id>.jsonl``.

    Unknown keys are dropped. A non-empty ``error`` marks the step as failed.
    ``seconds`` must be finite.

    Examples
    --------
    >>> TraceStep(turn=1, tool="check_stock", error="timeout").error
    'timeout'
    """

    turn: int
    tool: str | None = None
    args: Any = None
    result: Any = None
    tokens_in: int = Field(0, ge=0)
    tokens_out: int = Field(0, ge=0)
    seconds: float = Field(0.0, ge=0, allow_inf_nan=False)
    error: str | None = None


def sum_usage(rows: Iterable[UsageRow]) -> UsageTotals | None:
    """
    Add up usage rows into run totals.

    Parameters
    ----------
    rows : iterable of UsageRow
        Rows from ``RunStore.read_usage``.

    Returns
    -------
    UsageTotals or None
        Sums of every field and ``calls`` = number of rows; None if there are no rows.

    Examples
    --------
    >>> sum_usage([UsageRow(tokens_in=3, usd=0.25), UsageRow(tokens_in=4, usd=0.5)])
    UsageTotals(tokens_in=7, tokens_out=0, usd=0.75, seconds=0.0, calls=2)
    >>> sum_usage([]) is None
    True
    """
    items = list(rows)
    if not items:
        return None
    return UsageTotals(
        tokens_in=sum(r.tokens_in for r in items),
        tokens_out=sum(r.tokens_out for r in items),
        usd=math.fsum(r.usd for r in items),
        seconds=math.fsum(r.seconds for r in items),
        calls=len(items),
    )
```

Insert these methods in `class RunStore` directly after `read_artifacts` (before `append_note`):

```python
    def read_usage(self, project: str, run_id: str) -> list[UsageRow]:
        """
        Read the usage rows logged by the SDK for a run.

        Parameters
        ----------
        project : str
            Project name.
        run_id : str
            Run id.

        Returns
        -------
        list of UsageRow
            Rows of ``usage.jsonl`` in the order written; malformed rows (for example a
            negative token count) are skipped.
        """
        return _parse_rows(UsageRow, self.layout.run_dir(project, run_id) / "usage.jsonl")

    def list_traces(self, project: str, run_id: str) -> list[dict[str, Any]]:
        """
        Summarise every trace logged for a run.

        Parameters
        ----------
        project : str
            Project name.
        run_id : str
            Run id.

        Returns
        -------
        list of dict
            One ``{"example_id": str, "turns": int, "failed": bool}`` per trace file,
            sorted by example id. ``example_id`` is the original id written by
            ``log_trace`` (also for an empty trace, whose file holds one marker line);
            the file stem only for files written without it. ``failed`` is True when
            any step has a non-empty ``error``.
        """
        folder = self.layout.run_dir(project, run_id) / "traces"
        if not folder.is_dir():
            return []
        found: list[dict[str, Any]] = []
        for path in sorted(folder.glob("*.jsonl")):
            raw = read_jsonl(path)
            steps = _parse_steps(raw)
            original = next((r["example_id"] for r in raw if "example_id" in r), None)
            found.append(
                {
                    "example_id": original if isinstance(original, str) else path.stem,
                    "turns": len(steps),
                    "failed": any(step.error for step in steps),
                }
            )
        return sorted(found, key=lambda row: row["example_id"])

    def read_trace(self, project: str, run_id: str, example_id: str) -> list[TraceStep]:
        """
        Read one example's trace.

        Parameters
        ----------
        project : str
            Project name.
        run_id : str
            Run id.
        example_id : str
            Example id as given to ``log_trace`` (sanitised here the same way).

        Returns
        -------
        list of TraceStep
            Steps in file order; ``[]`` if the example has no trace. A step without
            ``turn`` gets its 1-based position; malformed steps are skipped.

        Raises
        ------
        ValueError
            If ``example_id`` is empty.
        """
        path = self.layout.run_dir(project, run_id) / "traces" / f"{safe_stem(example_id)}.jsonl"
        return _parse_steps(read_jsonl(path))

    def read_samples(self, project: str, run_id: str) -> dict[str, list[float]]:
        """
        Read every raw sample series logged for a run.

        Parameters
        ----------
        project : str
            Project name.
        run_id : str
            Run id.

        Returns
        -------
        dict of str to list of float
            Series name to values in the order written, sorted by name. The name is
            the original one ``log_samples`` stores in each row (the file stem only
            for files written without it). Rows whose ``value`` is not a finite
            number are skipped.
        """
        folder = self.layout.run_dir(project, run_id) / "samples"
        if not folder.is_dir():
            return {}
        series: dict[str, list[float]] = {}
        for path in sorted(folder.glob("*.jsonl")):
            rows = read_jsonl(path)
            name = next((r["name"] for r in rows if isinstance(r.get("name"), str)), path.stem)
            values: list[float] = []
            for raw in rows:
                value = raw.get("value")
                if isinstance(value, bool) or not isinstance(value, int | float):
                    continue
                if math.isfinite(value):
                    values.append(float(value))
            series.setdefault(name, []).extend(values)
        return dict(sorted(series.items()))
```

Append this helper at the very end of the file (after `_parse_rows`):

```python
def _parse_steps(raws: list[dict[str, Any]]) -> list[TraceStep]:
    """
    Parse trace rows, giving a row without ``turn`` its 1-based position.

    Parameters
    ----------
    raws : list of dict
        Rows read from a trace file.

    Returns
    -------
    list of TraceStep
        Valid steps in file order; invalid rows and the empty-trace marker line
        (``{"example_id": ...}`` alone) are skipped.
    """
    steps: list[TraceStep] = []
    for position, raw in enumerate(raws, start=1):
        if raw.keys() == {"example_id"}:
            continue
        try:
            steps.append(TraceStep.model_validate({"turn": position, **raw}))
        except ValidationError:
            continue
    return steps
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/core/test_store.py -v`
Expected: `17 passed`.

- [ ] **Step 5: Lint, format, type-check**

Run: `uv run ruff format src/hypothex/core/store.py tests/core/test_store.py && uv run ruff check src tests && uv run ty check src`
Expected: `All checks passed!` from both checkers.

- [ ] **Step 6: Commit**

```bash
git add src/hypothex/core/store.py tests/core/test_store.py
git commit -m "feat: store readers for usage, traces, and raw samples"
```

---

### Task 7: SDK calls `log_trace`, `log_usage`, `log_samples`, `log_checkpoint`

**Files:**
- Modify: `src/hypothex/sdk.py` (whole file shown below)
- Test: `tests/test_sdk.py`

**Interfaces:**
- Consumes: `safe_stem`, `check_stem_owner`, `TraceStep`, `UsageRow` from `hypothex.core.store` (Task 6); `Artifact.step` / `Artifact.metrics` (Task 3); `atomic_write_text`, `append_jsonl`, `open_jsonl_append` from `hypothex.core.fsutil`.
- Produces (contract 1.10, on both `Run` and `NoopRun`):
  - `log_trace(self, example_id: str, steps: Iterable[Mapping[str, Any]]) -> None`
  - `log_usage(self, tokens_in: int = 0, tokens_out: int = 0, usd: float = 0.0, seconds: float = 0.0, example_id: str | None = None) -> None`
  - `log_samples(self, name: str, values: Iterable[float]) -> None`
  - `log_checkpoint(self, path: str | os.PathLike[str], step: int, metrics: Mapping[str, float] | None = None, host: str = "local") -> None`

- [ ] **Step 1: Write the failing tests**

In `tests/test_sdk.py`, add these imports after `from hypothex import sdk`:

```python
from hypothex.core.errors import StoreError
from hypothex.core.records import Artifact
```

In `test_noop_outside_a_run`, insert these four lines directly before the final line `assert hx.seed() is None and hx.seed(3) == 3`:

```python
    assert run.log_checkpoint("/x.pt", step=1, metrics={"val": 0.5}) is None
    assert run.log_trace("ex-1", [{"tool": "t"}]) is None
    assert run.log_usage(tokens_in=1, usd=0.5, example_id="ex-1") is None
    assert run.log_samples("latency_ms", [1.0]) is None
```

Append these tests at the end of the file:

```python
def test_log_trace_writes_sanitised_file_and_overwrites(run_env: Path) -> None:
    run = hx.current()
    run.log_trace(
        "route 7/b",
        [
            {
                "tool": "retro_expand",
                "args": {"top_k": 8},
                "result": "8 precursors",
                "tokens_in": 4410,
                "tokens_out": 512,
                "seconds": 4.82,
                "ms": 4820,  # unknown keys are dropped
            },
            {"tool": "check_stock", "args": "CCO", "error": "timeout 8 s"},
        ],
    )
    path = run_env / "traces" / "route_7_b-5db86396.jsonl"  # sha1("route 7/b")[:8]
    assert _lines(path) == [
        {
            "example_id": "route 7/b",
            "turn": 1,
            "tool": "retro_expand",
            "args": {"top_k": 8},
            "result": "8 precursors",
            "tokens_in": 4410,
            "tokens_out": 512,
            "seconds": 4.82,
            "error": None,
        },
        {
            "example_id": "route 7/b",
            "turn": 2,
            "tool": "check_stock",
            "args": "CCO",
            "result": None,
            "tokens_in": 0,
            "tokens_out": 0,
            "seconds": 0.0,
            "error": "timeout 8 s",
        },
    ]
    run.log_trace("route 7/b", [{"turn": 5, "tool": "score_routes"}])
    assert [(r["turn"], r["tool"]) for r in _lines(path)] == [(5, "score_routes")]


def test_log_trace_keeps_similar_ids_apart_and_empty_traces(run_env: Path) -> None:
    run = hx.current()
    run.log_trace("a/b", [{"tool": "x"}])
    run.log_trace("a_b", [{"tool": "y"}])
    run.log_trace("e/0", [])
    traces = run_env / "traces"
    assert sorted(p.name for p in traces.iterdir()) == [
        "a_b-3ec69c85.jsonl",  # sha1("a/b")[:8]
        "a_b.jsonl",
        "e_0-7569d147.jsonl",  # sha1("e/0")[:8]
    ]
    assert [r["tool"] for r in _lines(traces / "a_b-3ec69c85.jsonl")] == ["x"]
    assert [r["tool"] for r in _lines(traces / "a_b.jsonl")] == ["y"]
    # an empty trace still creates its file, with a marker line that keeps the id
    assert _lines(traces / "e_0-7569d147.jsonl") == [{"example_id": "e/0"}]


def test_trace_and_sample_writers_refuse_a_file_of_another_id(run_env: Path) -> None:
    run = hx.current()
    # regression: "a_b-3ec69c85" looks like the stem of "a/b", so it is hashed too
    run.log_trace("a/b", [{"tool": "x"}])
    run.log_trace("a_b-3ec69c85", [{"tool": "y"}])
    traces = run_env / "traces"
    assert [r["tool"] for r in _lines(traces / "a_b-3ec69c85.jsonl")] == ["x"]
    assert [r["tool"] for r in _lines(traces / "a_b-3ec69c85-d64fa8bc.jsonl")] == ["y"]
    # a sha1 prefix collision cannot be produced on demand: plant a file that stores
    # another id under the stem of "k/1", as a colliding id would have written it
    planted = traces / "k_1-3437d2e8.jsonl"  # sha1("k/1")[:8]
    planted.write_text('{"example_id": "other", "turn": 1}\n')
    with pytest.raises(StoreError, match="id collision: k_1-3437d2e8.jsonl already holds"):
        run.log_trace("k/1", [{"tool": "z"}])
    assert planted.read_text() == '{"example_id": "other", "turn": 1}\n'  # untouched
    samples = run_env / "samples"
    samples.mkdir()
    (samples / "lat_ms-94293541.jsonl").write_text('{"name": "other", "value": 1.0}\n')
    with pytest.raises(StoreError, match="id collision: lat_ms-94293541.jsonl already holds"):
        run.log_samples("lat ms", [2.0])  # sha1("lat ms")[:8] = 94293541
    assert _lines(samples / "lat_ms-94293541.jsonl") == [{"name": "other", "value": 1.0}]


def test_log_trace_rejects_bad_steps_without_writing(run_env: Path) -> None:
    run = hx.current()
    with pytest.raises(ValueError, match="trace step 2 of 'e1' is invalid: tokens_in"):
        run.log_trace("e1", [{"tool": "a"}, {"tool": "b", "tokens_in": -1}])
    with pytest.raises(
        ValueError, match="trace step 1 of 'e1' is invalid: seconds: Input should be a finite"
    ):
        run.log_trace("e1", [{"tool": "a", "seconds": float("inf")}])
    assert not (run_env / "traces" / "e1.jsonl").exists()
    with pytest.raises(ValueError, match="must not be empty"):
        run.log_trace("", [{"tool": "a"}])


def test_log_usage_appends_rows_and_validates(run_env: Path) -> None:
    run = hx.current()
    run.log_usage(tokens_in=100, tokens_out=20, usd=0.25, seconds=1.5, example_id="a")
    run.log_usage(tokens_in=50)
    path = run_env / "usage.jsonl"
    assert _lines(path) == [
        {"example_id": "a", "tokens_in": 100, "tokens_out": 20, "usd": 0.25, "seconds": 1.5},
        {"example_id": None, "tokens_in": 50, "tokens_out": 0, "usd": 0.0, "seconds": 0.0},
    ]
    with pytest.raises(ValueError, match="invalid usage: usd"):
        run.log_usage(usd=-0.5)
    with pytest.raises(ValueError, match="invalid usage: usd: Input should be a finite number"):
        run.log_usage(usd=float("inf"))
    with pytest.raises(ValueError, match="invalid usage: seconds: Input should be a finite"):
        run.log_usage(seconds=float("inf"))
    assert len(_lines(path)) == 2


def test_log_samples_appends_values(run_env: Path) -> None:
    run = hx.current()
    run.log_samples("latency ms", [12.5, 15])
    run.log_samples("latency ms", iter([20.0]))
    run.log_samples("latency_ms", [1.0])  # a different series, a different file
    path = run_env / "samples" / "latency_ms-136bd8be.jsonl"  # sha1("latency ms")[:8]
    assert _lines(path) == [
        {"name": "latency ms", "value": 12.5},
        {"name": "latency ms", "value": 15.0},
        {"name": "latency ms", "value": 20.0},
    ]
    assert _lines(run_env / "samples" / "latency_ms.jsonl") == [
        {"name": "latency_ms", "value": 1.0}
    ]
    with pytest.raises(ValueError, match="sample of 'latency ms' must be a finite number"):
        run.log_samples("latency ms", [1.0, float("nan")])
    with pytest.raises(ValueError, match="must be a finite number, got 'slow'"):
        run.log_samples("latency ms", ["slow"])
    assert len(_lines(path)) == 3  # a bad batch writes nothing
    run.log_samples("empty", [])
    assert not (run_env / "samples" / "empty.jsonl").exists()


def test_log_checkpoint_records_step_and_metrics(run_env: Path, tmp_path: Path) -> None:
    ckpt = tmp_path / "step_100.pt"
    ckpt.write_bytes(b"12345")
    run = hx.current()
    run.log_checkpoint(ckpt, step=100, metrics={"val_top1": 0.5})
    row = _lines(run_env / "artifacts.jsonl")[0]
    assert row == {
        "kind": "checkpoint",
        "path": str(ckpt.resolve()),
        "host": "local",
        "size": 5,
        "step": 100,
        "metrics": {"val_top1": 0.5},
    }
    artifact = Artifact.model_validate(row)
    assert (artifact.step, artifact.metrics) == (100, {"val_top1": 0.5})
    with pytest.raises(TypeError):
        run.log_checkpoint(ckpt, step=1.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="checkpoint metric 'val' must be a finite number"):
        run.log_checkpoint(ckpt, step=200, metrics={"val": float("inf")})
    assert len(_lines(run_env / "artifacts.jsonl")) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_sdk.py -v`
Expected: 8 failures, each `AttributeError: 'Run' object has no attribute 'log_trace'` (or `log_usage` / `log_samples` / `log_checkpoint`; `'NoopRun' object has no attribute 'log_checkpoint'` for the no-op test). The 5 older tests pass.

- [ ] **Step 3: Implement the SDK calls**

Replace the whole of `src/hypothex/sdk.py` with:

```python
"""SDK used inside a run started by ``hx run`` / ``hx launch``.

Examples
--------
>>> import hypothex as hx
>>> run = hx.current()          # a no-op outside Hypothex, so code runs unchanged
>>> run.log({"loss": 0.41})
>>> run.log_predictions([{"id": "ex-1", "prediction": 1}])
0
>>> run.log_usage(tokens_in=4410, tokens_out=512, usd=0.0131, seconds=4.8, example_id="ex-1")
>>> run.log_trace("ex-1", [{"tool": "check_stock", "args": "CCO", "result": "in stock"}])
>>> run.log_samples("latency_ms", [12.5, 15.0])
>>> run.log_checkpoint("ckpt/step_1000.pt", step=1000, metrics={"val_top1": 0.61})
"""

from __future__ import annotations

import json
import math
import operator
import os
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from hypothex.core.fsutil import (
    append_jsonl,
    append_note_file,
    atomic_write_text,
    open_jsonl_append,
)
from hypothex.core.store import TraceStep, UsageRow, check_stem_owner, safe_stem


def _why(exc: ValidationError) -> str:
    """
    Describe the first validation error as ``field: message``.

    Parameters
    ----------
    exc : ValidationError
        The pydantic error.

    Returns
    -------
    str
        E.g. ``tokens_in: Input should be greater than or equal to 0``.
    """
    err = exc.errors()[0]
    loc = ".".join(str(part) for part in err["loc"])
    return f"{loc}: {err['msg']}" if loc else err["msg"]


def _finite(value: Any, what: str) -> float:
    """
    Convert ``value`` to a finite float.

    Parameters
    ----------
    value : Any
        Number (or numeric string) to convert.
    what : str
        What the value is, for the error message.

    Returns
    -------
    float
        The value as a float.

    Raises
    ------
    ValueError
        If ``value`` is not a number, or is NaN or infinite.

    Examples
    --------
    >>> _finite("1.5", "x")
    1.5
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = math.nan
    if not math.isfinite(number):
        raise ValueError(f"{what} must be a finite number, got {value!r}")
    return number


class Run:
    """
    Handle to the current run's folder.

    Parameters
    ----------
    run_dir : Path
        The run folder (``$HYPOTHEX_RUN_DIR``).
    run_id : str
        Run id.
    project : str
        Project name.
    """

    active = True

    def __init__(self, run_dir: Path, run_id: str, project: str) -> None:
        self.run_dir = run_dir
        self.run_id = run_id
        self.project = project
        self._steps: dict[str, int] = {}

    def log(self, values: Mapping[str, float], step: int | None = None) -> None:
        """
        Log metric values; each name gets its own auto-incrementing step.

        Parameters
        ----------
        values : mapping of str to float
            E.g. ``{"loss": 0.41}``.
        step : int, optional
            Explicit step for all values.
        """
        now = time.time()
        for name, value in values.items():
            s = step if step is not None else self._steps.get(name, -1) + 1
            self._steps[name] = s
            append_jsonl(
                self.run_dir / "metrics.jsonl",
                {"name": name, "step": s, "value": float(value), "t": now},
            )

    def log_predictions(self, rows: Iterable[Mapping[str, Any]]) -> int:
        """
        Append prediction rows to ``predictions/predictions.jsonl``.

        Each row needs ``id`` and ``prediction``; ``reference`` and ``meta`` are optional.

        Returns
        -------
        int
            Number of rows written.

        Raises
        ------
        ValueError
            If a row lacks ``id`` or ``prediction``.
        """
        path = self.run_dir / "predictions" / "predictions.jsonl"
        count = 0
        with open_jsonl_append(path) as fh:
            for row in rows:
                if "id" not in row or "prediction" not in row:
                    raise ValueError("each prediction row needs 'id' and 'prediction'")
                fh.write((json.dumps(dict(row), default=str) + "\n").encode("utf-8"))
                count += 1
        return count

    def log_artifact(
        self, path: str | os.PathLike[str], kind: str = "file", host: str = "local"
    ) -> None:
        """
        Record a large file by path (it is not copied).

        Parameters
        ----------
        path : path-like
            File location.
        kind : str
            E.g. ``checkpoint``; re-infer uses the last ``checkpoint``.
        host : str
            Where the file lives.
        """
        self._append_artifact(path, kind, host, {})

    def log_checkpoint(
        self,
        path: str | os.PathLike[str],
        step: int,
        metrics: Mapping[str, float] | None = None,
        host: str = "local",
    ) -> None:
        """
        Record a checkpoint by path, with the step it was saved at and its metrics.

        Same as ``log_artifact(path, kind="checkpoint")`` plus ``step`` and ``metrics``,
        which the training views use to mark checkpoints on the curves. Logging the
        same path again (e.g. an overwritten ``last.pt``) keeps only the latest entry
        when the run ends.

        Parameters
        ----------
        path : path-like
            Checkpoint file.
        step : int
            Training step the checkpoint was saved at.
        metrics : mapping of str to float, optional
            E.g. ``{"val_top1": 0.61}``.
        host : str
            Where the file lives.

        Raises
        ------
        TypeError
            If ``step`` is not an integer.
        ValueError
            If a metric value is not a finite number; nothing is written then.

        Examples
        --------
        >>> hx.current().log_checkpoint("step_1000.pt", 1000, {"val_top1": 0.61})  # doctest: +SKIP
        """
        checked_step = operator.index(step)
        values = {
            str(k): _finite(v, f"checkpoint metric {k!r}") for k, v in (metrics or {}).items()
        }
        self._append_artifact(path, "checkpoint", host, {"step": checked_step, "metrics": values})

    def _append_artifact(
        self, path: str | os.PathLike[str], kind: str, host: str, extra: dict[str, Any]
    ) -> None:
        """
        Append one row to ``artifacts.jsonl``.

        Parameters
        ----------
        path : path-like
            File location; resolved to an absolute path.
        kind : str
            Artifact kind.
        host : str
            Where the file lives.
        extra : dict
            Extra fields, e.g. ``step`` and ``metrics`` for checkpoints.
        """
        resolved = Path(path).expanduser().resolve()
        size = resolved.stat().st_size if resolved.is_file() else None
        append_jsonl(
            self.run_dir / "artifacts.jsonl",
            {"kind": kind, "path": str(resolved), "host": host, "size": size, **extra},
        )

    def log_trace(self, example_id: str, steps: Iterable[Mapping[str, Any]]) -> None:
        """
        Write one example's agent trajectory to ``traces/<example_id>.jsonl``.

        The file is replaced, so logging the same example again keeps only the new
        trace. A step is ``{turn, tool, args, result, tokens_in, tokens_out, seconds,
        error}``; every key is optional except that ``turn`` defaults to the step's
        1-based position. A non-empty ``error`` marks the step (and the trace) failed.
        The file name is ``store.safe_stem(example_id)`` (unsafe characters become
        ``_`` plus a hash of the id); the original id is stored in each line. An
        empty ``steps`` still writes the file, as one marker line
        ``{"example_id": <id>}``, so the trace list shows it with 0 turns.

        Parameters
        ----------
        example_id : str
            The example the trajectory belongs to (matches the prediction ``id``).
        steps : iterable of mapping
            The steps in order.

        Raises
        ------
        ValueError
            If ``example_id`` is empty or a step is invalid (for example a negative
            token count, an infinite ``seconds``, or a non-integer ``turn``); nothing
            is written then.
        StoreError
            If the trace file of this stem already holds another example id (an id
            collision, ``store.check_stem_owner``); nothing is written then.

        Examples
        --------
        >>> hx.current().log_trace("ex-1", [
        ...     {"tool": "retro_expand", "args": {"top_k": 8}, "result": "8 precursors",
        ...      "tokens_in": 4410, "tokens_out": 512, "seconds": 4.8},
        ...     {"tool": "check_stock", "args": "CCO", "error": "timeout 8 s"},
        ... ])  # doctest: +SKIP
        """
        path = self.run_dir / "traces" / f"{safe_stem(example_id)}.jsonl"
        lines: list[str] = []
        for position, step in enumerate(steps, start=1):
            try:
                parsed = TraceStep.model_validate({"turn": position, **step})
            except ValidationError as exc:
                raise ValueError(
                    f"trace step {position} of {example_id!r} is invalid: {_why(exc)}"
                ) from None
            row = {"example_id": example_id, **parsed.model_dump()}
            lines.append(json.dumps(row, default=str) + "\n")
        if not lines:
            lines.append(json.dumps({"example_id": example_id}) + "\n")
        check_stem_owner(path, "example_id", example_id)
        atomic_write_text(path, "".join(lines))

    def log_usage(
        self,
        tokens_in: int = 0,
        tokens_out: int = 0,
        usd: float = 0.0,
        seconds: float = 0.0,
        example_id: str | None = None,
    ) -> None:
        """
        Append one model call's usage to ``usage.jsonl``.

        When the run ends, all rows are summed into the run's ``usage`` totals
        (``calls`` = number of rows).

        Parameters
        ----------
        tokens_in, tokens_out : int
            Input and output tokens.
        usd : float
            Cost in US dollars.
        seconds : float
            Wall time of the call.
        example_id : str, optional
            The example the call was made for.

        Raises
        ------
        ValueError
            If a value is negative, not a number, or not finite (``nan``, ``inf``);
            nothing is written then.

        Examples
        --------
        >>> hx.current().log_usage(tokens_in=4410, tokens_out=512, usd=0.0131)  # doctest: +SKIP
        """
        try:
            row = UsageRow(
                example_id=example_id,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                usd=usd,
                seconds=seconds,
            )
        except ValidationError as exc:
            raise ValueError(f"invalid usage: {_why(exc)}") from None
        append_jsonl(self.run_dir / "usage.jsonl", row.model_dump(mode="json"))

    def log_samples(self, name: str, values: Iterable[float]) -> None:
        """
        Append raw sample values (e.g. latencies) to ``samples/<name>.jsonl``.

        Each value becomes one ``{"name": name, "value": v}`` line. Percentiles are
        computed from these raw values, so log every sample, not a summary. The file
        name is ``store.safe_stem(name)`` (unsafe characters become ``_`` plus a hash
        of the name); readers use the stored ``name``.

        Parameters
        ----------
        name : str
            Series name, e.g. ``latency_ms``.
        values : iterable of float
            The samples.

        Raises
        ------
        ValueError
            If ``name`` is empty or a value is not a finite number; nothing is
            written then.
        StoreError
            If the sample file of this stem already holds another series name (a
            name collision, ``store.check_stem_owner``); nothing is written then.

        Examples
        --------
        >>> hx.current().log_samples("latency_ms", [12.5, 15.0, 11.2])  # doctest: +SKIP
        """
        path = self.run_dir / "samples" / f"{safe_stem(name)}.jsonl"
        what = f"sample of {name!r}"
        lines = [
            json.dumps({"name": name, "value": _finite(value, what)}) + "\n" for value in values
        ]
        if not lines:
            return
        check_stem_owner(path, "name", name)
        with open_jsonl_append(path) as fh:
            fh.write("".join(lines).encode("utf-8"))

    def note(self, text: str) -> None:
        """Append a note to the run's ``notes.md``."""
        append_note_file(self.run_dir / "notes.md", text, "sdk")


class NoopRun:
    """Stand-in used outside Hypothex: every method does nothing."""

    active = False
    run_dir: Path | None = None
    run_id: str | None = None
    project: str | None = None

    def log(self, values: Mapping[str, float], step: int | None = None) -> None:
        """Do nothing."""

    def log_predictions(self, rows: Iterable[Mapping[str, Any]]) -> int:
        """Do nothing and return 0."""
        return 0

    def log_artifact(
        self, path: str | os.PathLike[str], kind: str = "file", host: str = "local"
    ) -> None:
        """Do nothing."""

    def log_checkpoint(
        self,
        path: str | os.PathLike[str],
        step: int,
        metrics: Mapping[str, float] | None = None,
        host: str = "local",
    ) -> None:
        """Do nothing."""

    def log_trace(self, example_id: str, steps: Iterable[Mapping[str, Any]]) -> None:
        """Do nothing."""

    def log_usage(
        self,
        tokens_in: int = 0,
        tokens_out: int = 0,
        usd: float = 0.0,
        seconds: float = 0.0,
        example_id: str | None = None,
    ) -> None:
        """Do nothing."""

    def log_samples(self, name: str, values: Iterable[float]) -> None:
        """Do nothing."""

    def note(self, text: str) -> None:
        """Do nothing."""


_current: Run | None = None


def current() -> Run | NoopRun:
    """
    Return the run started by Hypothex, or a ``NoopRun`` outside one.

    The same ``Run`` object is returned on repeated calls, so auto steps continue.
    """
    global _current
    run_dir = os.environ.get("HYPOTHEX_RUN_DIR")
    if not run_dir:
        return NoopRun()
    if _current is None or str(_current.run_dir) != run_dir:
        _current = Run(
            Path(run_dir),
            os.environ.get("HYPOTHEX_RUN_ID", ""),
            os.environ.get("HYPOTHEX_PROJECT", ""),
        )
    return _current


def seed(default: int | None = None) -> int | None:
    """
    Return ``--seed`` passed to ``hx run`` (``$HYPOTHEX_SEED``), else ``default``.

    Parameters
    ----------
    default : int, optional
        Value returned when ``$HYPOTHEX_SEED`` is unset or empty.

    Returns
    -------
    int or None
        The seed.

    Raises
    ------
    ValueError
        If ``$HYPOTHEX_SEED`` is set but is not an integer.

    Examples
    --------
    >>> seed(default=0)  # outside a Hypothex run
    0
    """
    raw = os.environ.get("HYPOTHEX_SEED", "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"HYPOTHEX_SEED must be an integer, got {raw!r}") from None
```

Notes for the implementer:
- `log_artifact` keeps writing exactly `{kind, path, host, size}` (the existing `test_log_artifact_and_note` asserts that row); only checkpoints add `step` and `metrics`.
- Every new call validates all input before touching disk, so a bad value never leaves a half-written file.
- `hypothex.sdk` now imports `hypothex.core.store`; that module must never import `hypothex.sdk` or `hypothex` (the package root), or `import hypothex` becomes circular.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_sdk.py -v`
Expected: `13 passed`.

- [ ] **Step 5: Lint, format, type-check**

Run: `uv run ruff format src/hypothex/sdk.py tests/test_sdk.py && uv run ruff check src tests && uv run ty check src`
Expected: `All checks passed!` from both checkers.

- [ ] **Step 6: Commit**

```bash
git add src/hypothex/sdk.py tests/test_sdk.py
git commit -m "feat: sdk log_trace, log_usage, log_samples, log_checkpoint"
```

---

### Task 8: Sum usage into the run record at finalisation

**Files:**
- Modify: `src/hypothex/core/execution.py` (import block; the finalisation block in `execute_run` after the status is decided)
- Test: `tests/core/test_execution.py`

**Interfaces:**
- Consumes: `sum_usage`, `RunStore.read_usage` (Task 6); `RunRecord.usage`, `UsageTotals`, `Artifact.step` / `Artifact.metrics` (Task 3); `Run.log_usage`, `Run.log_checkpoint` (Task 7, called from the child process).
- Produces: after `execute_run` returns, `RunRecord.usage` holds the summed `UsageTotals` of `usage.jsonl` (None when the run logged no usage), for finished, failed, and killed runs alike; `RunRecord.artifacts` carries checkpoint `step` and `metrics`, one entry per `(kind, path)` with the latest logged values. `core.leaderboard` sums `RunRecord.usage` across a seed group; `core.sources` flattens it as `usage.*`.

- [ ] **Step 1: Write the failing tests**

In `tests/core/test_execution.py`, replace

```python
from hypothex.core.records import RunStatus
```

with

```python
from hypothex.core.records import RunStatus, UsageTotals
```

Append at the end of the file:

```python
USAGE = (
    "import sys, hypothex as hx; r = hx.current(); "
    "r.log_usage(tokens_in=100, tokens_out=20, usd=0.25, seconds=1.5, example_id='a'); "
    "r.log_usage(tokens_in=50, tokens_out=5, usd=0.125, seconds=0.5); "
    "sys.exit(int(sys.argv[1]))"
)


def test_usage_is_summed_into_the_record(ctx: Context, toy_repo: Path) -> None:
    done = run_fg(ctx, RunRequest(repo=toy_repo, command=cmd(USAGE, "0")))
    # 0.25 + 0.125 and 1.5 + 0.5 are exact in binary floating point.
    expected = UsageTotals(tokens_in=150, tokens_out=25, usd=0.375, seconds=2.0, calls=2)
    assert done.status == RunStatus.FINISHED and done.usage == expected
    assert ctx.store.read_record("toy", done.run_id).usage == expected


def test_failed_run_still_records_usage(ctx: Context, toy_repo: Path) -> None:
    done = run_fg(ctx, RunRequest(repo=toy_repo, command=cmd(USAGE, "2")))
    assert done.status == RunStatus.FAILED and done.usage is not None
    assert (done.usage.calls, done.usage.usd) == (2, 0.375)


def test_run_without_usage_has_none(ctx: Context, toy_repo: Path) -> None:
    done = run_fg(ctx, RunRequest(repo=toy_repo, command=cmd("print(1)")))
    assert done.usage is None


def test_checkpoints_keep_step_and_metrics(ctx: Context, toy_repo: Path, tmp_path: Path) -> None:
    code = (
        "import sys, hypothex as hx; r = hx.current(); "
        "r.log_checkpoint(sys.argv[1], step=100, metrics={'val_top1': 0.5}); "
        "r.log_checkpoint(sys.argv[2], step=100, metrics={'val_top1': 0.5}); "
        "r.log_checkpoint(sys.argv[2], step=200, metrics={'val_top1': 0.75})"
    )
    step_100, last = tmp_path / "step_100.pt", tmp_path / "last.pt"
    done = run_fg(ctx, RunRequest(repo=toy_repo, command=cmd(code, str(step_100), str(last))))
    assert [(a.kind, a.path, a.step, a.metrics) for a in done.artifacts] == [
        ("checkpoint", str(step_100.resolve()), 100, {"val_top1": 0.5}),
        ("checkpoint", str(last.resolve()), 200, {"val_top1": 0.75}),  # latest entry wins
    ]
```

- [ ] **Step 2: Run the tests to verify the usage tests fail**

Run: `uv run pytest tests/core/test_execution.py -v -k "usage or checkpoints"`
Expected: `test_usage_is_summed_into_the_record` and `test_failed_run_still_records_usage` FAIL (`done.usage` is `None`). `test_run_without_usage_has_none` and `test_checkpoints_keep_step_and_metrics` already PASS: the first pins the default, the second pins that the existing `(kind, path)` merge keeps Task 3's new `step`/`metrics` fields and lets the latest entry win.

- [ ] **Step 3: Implement the finalisation**

In `src/hypothex/core/execution.py`, add this import after `from hypothex.core.seeds import config_hash, run_fingerprint`:

```python
from hypothex.core.store import sum_usage
```

In `execute_run`, replace

```python
    logged = ctx.store.read_artifacts(record.project, record.run_id)
    ctx.index.replace_metric_points(
        record.run_id, ctx.store.read_metric_points(record.project, record.run_id)
    )

    def finish(r: RunRecord) -> RunRecord:
        merged = {(a.kind, a.path): a for a in [*r.artifacts, *logged]}
        return r.model_copy(
            update={
                "status": status,
                "ended_at": utcnow(),
                "exit_code": exit_code,
                "artifacts": list(merged.values()),
            }
        )
```

with

```python
    logged = ctx.store.read_artifacts(record.project, record.run_id)
    usage = sum_usage(ctx.store.read_usage(record.project, record.run_id))
    ctx.index.replace_metric_points(
        record.run_id, ctx.store.read_metric_points(record.project, record.run_id)
    )

    def finish(r: RunRecord) -> RunRecord:
        # A path logged twice (e.g. an overwritten last.pt) keeps its latest step/metrics.
        merged = {(a.kind, a.path): a for a in [*r.artifacts, *logged]}
        return r.model_copy(
            update={
                "status": status,
                "ended_at": utcnow(),
                "exit_code": exit_code,
                "artifacts": list(merged.values()),
                "usage": usage,
            }
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/core/test_execution.py -v`
Expected: `21 passed`.

- [ ] **Step 5: Run the full suite, lint, type-check**

Run: `uv run ruff format --check src tests && uv run ruff check src tests && uv run ty check src && uv run pytest -q`
Expected: `All checks passed!` from both checkers and the full suite green, with no failures.

- [ ] **Step 6: Commit**

```bash
git add src/hypothex/core/execution.py tests/core/test_execution.py
git commit -m "feat: sum logged usage into the run record when a run ends"
```

## Part 3: Leaderboard noise and headlines (Tasks 9–14)

Implements contract sections 1.7 (`hypothex.core.leaderboard` changes) and 1.8 (`hypothex.core.headlines`), plus `queries.get_leaderboard` loading per-example scores. Spec: section 8.5 (statistics), 8.4 (kinds), 8.1 (terse headlines).

**Depends on Parts 1–2 (use exactly these contract names):**
- `hypothex.core.stats` (1.1): `Z95`, `wilson_interval`, `sign_test`, `bootstrap_mean_interval`, `paired_bootstrap_p`, `welch_p`, `examples_needed`.
- `hypothex.core.records` (1.2): `UsageTotals(tokens_in, tokens_out, usd, seconds, calls)`, `RunRecord.usage: UsageTotals | None`.
- `hypothex.core.config` (1.3): `TaskKind`, `TaskSpec.kind`, `TaskSpec.baseline`, `TaskSpec.version_param`.

**Design decisions (read before starting):**
- Every new `LeaderboardRow` and `Leaderboard` field is required (no default), so every producer (`build_leaderboard`, tests, the demo) must set it and the JSON always carries it. This does not reach the generated OpenAPI types: every route, old and new, returns `dict[str, Any]` (no `response_model`), so `/api/openapi.json` has no schemas for `Leaderboard`, `OverviewSummary`, `ViewInfo`, or `PanelResult`. The frontend plan types response bodies with hand-written contract models (`ui/src/api/models.ts`) and uses the generated `types.ts` for paths only. `within_noise_of_best` keeps its default.
- Per-example field choice (`pick_field`): `correct` or `solved` if binary (bools, or 0/1 ints); else any all-bool field (sorted by name); else the primary key if numeric; else any all-numeric field. Binary → Wilson + sign test. Numeric → bootstrap + paired bootstrap. No usable field or no per-example data → Welch over seed values.
- Seeds are pooled per example by mean. Wilson successes = round-half-up of the sum of pooled means, `n` = examples scored. The sign test uses a strict per-example majority (`mean > 0.5` passes; a tie fails).
- `VersusBest` is from the row's side: `delta = row − best`; `fixed` = examples the best passes and the row fails; `broken` = the reverse (the same as `ExampleDiff(a=row, b=best)`).
- Labels: hypothesis first clause (≤ 32 chars), else first sorted tag, else `group <id>` (`group_label`, the one label rule; the panel engine and the Overview reuse it). For `agent_iteration`, the group's `version_param` value (e.g. `v9`) is the label when present.
- `system_bench`: a primary whose metric or key names a percentile (`p50`, `p95`, `p99.9`, …) is always lower-is-better. The baseline comes from `TaskSpec.baseline` (`tag:<name>`, a `group_id`, a `group_id` prefix, or a `config_hash`). Percent changes and their 95% CI use a Welch t on log values over repeats.
- `agent_iteration`: the "first" group is the lowest `version_param` value in natural order (`v9` < `v10`); groups without it sort after, by first-run creation time. Rows stay ranked by score, so `rows[0]` is always the best.
- `task_headline`/`task_stat_strip` take a keyword-only `reference` (the baseline or first-version `group_id`), because the board alone cannot tell which group is the baseline. `build_leaderboard` passes it and stores the results in `board.headline` / `board.stat_strip`. Callers should read those fields.
- `overview_headline(summary)` reads only `summary.running`, `summary.ideas` (`project, task, label, primary, created_at`) and `summary.projects` (`project, task, best`) through a `Protocol`. This lets it be written and tested before `hypothex.core.overview` exists. Pass the keyword `board=` to get the p-value in the line.
- Formatting: metrics in [−1, 1] get 3 decimals. p-values get 2 decimals, 3 decimals below 0.01 (so a value never shows as `0.00`), and `p < 0.001` below that. Negative numbers use U+2212 (`−`).

---

### Task 9: Headline formatting helpers and Welch intervals

**Files:**
- Create: `src/hypothex/core/headlines.py`
- Test: `tests/core/test_headlines.py`

**Interfaces:**
- Consumes: `hypothex.core.seeds.t_critical(df: int) -> float` (phase 1a).
- Produces (in `hypothex.core.headlines`):
  - `MINUS = "−"`, `NO_RUNS = "No scored runs yet"`
  - `fmt_value(x: float) -> str` (3 decimals in [−1, 1], 2 below 10, 1 below 100, else thousands separator; negatives use `−`)
  - `fmt_delta(x: float) -> str` (explicit `+`/`−`; no sign when it rounds to zero)
  - `fmt_p(p: float) -> str` (`p = 0.15`, `p = 0.004`, `p < 0.001`)
  - `fmt_pct(ratio: float) -> str` (`−30%`)
  - `percentile_of(ref: str) -> str | None` (`"latency/p95"` → `"p95"`)
  - `welch_interval(a: Sequence[float], b: Sequence[float], log: bool = False) -> tuple[float, float | None, float | None] | None`: difference `a − b` (or relative change `exp(d) − 1` if `log`) with a Welch 95% interval.

- [ ] **Step 1: Write the failing tests**

Create `tests/core/test_headlines.py`:

```python
import pytest

from hypothex.core.headlines import (
    fmt_delta,
    fmt_p,
    fmt_pct,
    fmt_value,
    percentile_of,
    welch_interval,
)


def test_fmt_value_and_delta() -> None:
    assert fmt_value(0.03712) == "0.037"
    assert fmt_value(-0.4) == "−0.400"
    assert fmt_value(-0.0001) == "0.000"
    assert fmt_value(3.14159) == "3.14"
    assert fmt_value(12.345) == "12.3"
    assert fmt_value(1234.4) == "1,234"
    assert fmt_delta(0.0371) == "+0.037"
    assert fmt_delta(-0.4) == "−0.400"
    assert fmt_delta(0.0001) == "0.000"


def test_fmt_p_and_pct() -> None:
    assert fmt_p(0.1467) == "p = 0.15"
    assert fmt_p(1.0) == "p = 1.00"
    assert fmt_p(0.0042) == "p = 0.004"
    assert fmt_p(0.0004) == "p < 0.001"
    assert fmt_pct(-0.2956) == "−30%"
    assert fmt_pct(0.041) == "+4%"
    assert fmt_pct(0.004) == "0%"


def test_percentile_of() -> None:
    assert percentile_of("latency/p95") == "p95"
    assert percentile_of("p99_ms/value") == "p99"
    assert percentile_of("lat/p99.9") == "p99.9"
    assert percentile_of("top1/value") is None
    assert percentile_of("p100/value") is None


def test_welch_interval() -> None:
    # Reference: scipy.stats.ttest_ind(a, b, equal_var=False).confidence_interval()
    # = (0.0873304206, 0.1326695794) with df = 4. We use the t table value 2.776
    # (seeds.t_critical) instead of 2.7764451, so the bounds differ by < 1e-5.
    res = welch_interval([0.80, 0.82, 0.81], [0.70, 0.71, 0.69])
    assert res is not None
    d, lo, hi = res
    assert d == pytest.approx(0.11)
    assert lo == pytest.approx(0.0873304206, abs=1e-5)
    assert hi == pytest.approx(0.1326695794, abs=1e-5)
    # Log scale: exp(mean log a - mean log b) - 1; Welch df = 3.59, floored to 3 -> t = 3.182.
    # Hand check: d = -0.3503773, se = 0.0227898, exp(d -/+ 3.182 * se) - 1.
    res = welch_interval([300, 310, 320], [440, 430, 450], log=True)
    assert res is not None
    d, lo, hi = res
    assert d == pytest.approx(-0.2955777038, rel=1e-8)
    assert lo == pytest.approx(-0.3448521777, rel=1e-8)
    assert hi == pytest.approx(-0.2425972361, rel=1e-8)
    assert welch_interval([300], [430], log=True) == (pytest.approx(300 / 430 - 1), None, None)
    assert welch_interval([0.5, 0.5], [0.4, 0.4]) == (
        pytest.approx(0.1),
        pytest.approx(0.1),
        pytest.approx(0.1),
    )
    assert welch_interval([], [0.4]) is None
    assert welch_interval([0.0, 1.0], [1.0, 2.0], log=True) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/core/test_headlines.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'hypothex.core.headlines'`.

- [ ] **Step 3: Write the implementation**

Create `src/hypothex/core/headlines.py`:

```python
"""One-line findings and stat strips generated from leaderboard data."""

from __future__ import annotations

import math
import re
import statistics
from collections.abc import Sequence

from hypothex.core.seeds import t_critical

MINUS = "−"
NO_RUNS = "No scored runs yet"
_PERCENTILE = re.compile(r"(?<![A-Za-z0-9])p(\d{1,2}(?:\.\d+)?)(?![0-9])")


# formatting ------------------------------------------------------------------
def fmt_value(x: float) -> str:
    """
    Format a metric value: 3 decimals in [-1, 1], fewer for larger values.

    Parameters
    ----------
    x : float
        Value to format.

    Returns
    -------
    str
        The value; negatives use the Unicode minus sign.

    Examples
    --------
    >>> fmt_value(0.03712)
    '0.037'
    >>> fmt_value(1234.4)
    '1,234'
    """
    a = abs(x)
    if a <= 1:
        body = f"{a:.3f}"
    elif a < 10:
        body = f"{a:.2f}"
    elif a < 100:
        body = f"{a:.1f}"
    else:
        body = f"{a:,.0f}"
    return MINUS + body if x < 0 and body.strip("0.,") else body


def fmt_delta(x: float) -> str:
    """
    Format a signed difference with an explicit ``+`` or ``−``.

    Parameters
    ----------
    x : float
        Difference to format.

    Returns
    -------
    str
        Signed value; a difference that rounds to zero has no sign.

    Examples
    --------
    >>> fmt_delta(0.0371)
    '+0.037'
    """
    body = fmt_value(abs(x))
    if not body.strip("0.,"):
        return body
    return ("+" if x > 0 else MINUS) + body


def fmt_p(p: float) -> str:
    """
    Format a p-value for a headline.

    Parameters
    ----------
    p : float
        The p-value.

    Returns
    -------
    str
        ``p < 0.001`` when tiny, 3 decimals below 0.01, else 2 decimals.

    Examples
    --------
    >>> fmt_p(0.1467)
    'p = 0.15'
    """
    if p < 0.001:
        return "p < 0.001"
    return f"p = {p:.3f}" if p < 0.01 else f"p = {p:.2f}"


def fmt_pct(ratio: float) -> str:
    """
    Format a relative change as a signed whole percent.

    Parameters
    ----------
    ratio : float
        Relative change, e.g. ``-0.2956`` for 29.56 % lower.

    Returns
    -------
    str
        For example ``−30%``.

    Examples
    --------
    >>> fmt_pct(0.041)
    '+4%'
    """
    return _signed_int(ratio * 100) + "%"


def _signed_int(x: float) -> str:
    n = math.floor(abs(x) + 0.5)
    if n == 0:
        return "0"
    return ("+" if x > 0 else MINUS) + str(n)


def _p_value(p: float) -> str:
    if p < 0.001:
        return "<0.001"
    return f"{p:.3f}" if p < 0.01 else f"{p:.2f}"


def percentile_of(ref: str) -> str | None:
    """
    Return the percentile named in a metric reference, if any.

    Parameters
    ----------
    ref : str
        Metric reference such as ``latency/p95`` or ``p99_ms``.

    Returns
    -------
    str or None
        For example ``p95``; the last match wins; ``None`` if there is none.

    Examples
    --------
    >>> percentile_of("latency/p95")
    'p95'
    >>> percentile_of("top1/value") is None
    True
    """
    found = _PERCENTILE.findall(ref)
    return f"p{found[-1]}" if found else None


# intervals from seed values ------------------------------------------------------
def welch_interval(
    a: Sequence[float], b: Sequence[float], log: bool = False
) -> tuple[float, float | None, float | None] | None:
    """
    Difference of means ``a − b`` with a Welch 95% interval over seed values.

    Parameters
    ----------
    a, b : sequence of float
        Seed (or repeat) values of the two groups.
    log : bool
        Compare ``log`` values and return relative changes ``exp(d) − 1``.

    Returns
    -------
    tuple or None
        ``(estimate, lo, hi)``; ``lo``/``hi`` are None when either group has
        fewer than 2 values. None when a group is empty, or ``log`` is set and
        a value is not positive. The t critical value uses the Welch degrees of
        freedom rounded down (conservative).
    """
    if not a or not b or (log and min(*a, *b) <= 0):
        return None
    xa = [math.log(v) for v in a] if log else list(a)
    xb = [math.log(v) for v in b] if log else list(b)
    d = statistics.fmean(xa) - statistics.fmean(xb)

    def out(x: float) -> float:
        return math.exp(x) - 1 if log else x

    if len(xa) < 2 or len(xb) < 2:
        return out(d), None, None
    va = statistics.variance(xa) / len(xa)
    vb = statistics.variance(xb) / len(xb)
    se = math.sqrt(va + vb)
    if se == 0:
        return out(d), out(d), out(d)
    df = (va + vb) ** 2 / (va**2 / (len(xa) - 1) + vb**2 / (len(xb) - 1))
    half = t_critical(max(1, math.floor(df + 1e-9))) * se
    return out(d), out(d - half), out(d + half)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/core/test_headlines.py -v && uv run ruff check src/hypothex/core/headlines.py tests/core/test_headlines.py && uv run ruff format --check src/hypothex/core/headlines.py tests/core/test_headlines.py && uv run ty check src/hypothex/core/headlines.py`
Expected: 4 passed; ruff reports `All checks passed!` and `2 files already formatted`; ty reports `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/headlines.py tests/core/test_headlines.py
git commit -m "feat: headline number formatting and welch intervals"
```

---

### Task 10: Leaderboard rows carry labels, seed values, launchers, usage, and task kind

**Files:**
- Modify: `src/hypothex/core/leaderboard.py` (full rewrite below)
- Test: `tests/core/test_leaderboard.py`

**Interfaces:**
- Consumes: `hypothex.core.headlines.percentile_of` (Task 9). `UsageTotals` and `RunRecord.usage` (contract 1.2). `TaskKind`, `TaskSpec.kind`, `TaskSpec.version_param` (contract 1.3).
- Produces (in `hypothex.core.leaderboard`):
  - `NoiseInterval(lo: float, hi: float, method: Literal["wilson","bootstrap"], n: int)`
  - `VersusBest(delta: float, p: float | None, fixed: int | None, broken: int | None, test: Literal["sign","paired_bootstrap","welch"] | None, examples_needed: int | None)`
  - `LeaderboardRow` adds required fields `label: str`, `seed_values: dict[str, list[float]]` (per `metric/key`, one value per seed in run order), `identical_seeds: bool`, `test_interval: NoiseInterval | None`, `vs_best: VersusBest | None`, `created_by: list[str]` (sorted, unique), `usage: UsageTotals | None` (summed; None if no run has usage).
  - `Leaderboard` adds required fields `headline: str`, `kind: TaskKind`, `stat_strip: list[dict[str, Any]]`. Task 12 fills `headline` and `stat_strip`; until then they are `""` and `[]`.
  - `group_label(hypothesis: str, tags: Iterable[str], group_id: str) -> str`. The one label rule: the panel engine (Task 21) and the Overview (Task 24) reuse it.
  - `group_id_for(run: RunRecord) -> str` = `<config hash hex[:8]>@<commit[:7] or "nogit">`, plus `+<diff hash hex[:4]>` (or `+dirty`) for a dirty run (`leaderboard.diff_key`). The one seed-group id helper: `core.sources` (re-export), `core.panels`, and `core.overview` import it.
  - `system_bench` with a percentile primary → `Leaderboard.higher_is_better is False`.

- [ ] **Step 1: Write the failing tests**

In `tests/core/test_leaderboard.py`, replace the import block at the top of the file (everything from `from datetime import timedelta` down to, but not including, the line `CFG = ProjectConfig.model_validate(`) with:

```python
from datetime import timedelta
from typing import Any

import pytest

from hypothex.core.config import ProjectConfig
from hypothex.core.ids import utcnow
from hypothex.core.leaderboard import build_leaderboard, group_label
from hypothex.core.records import GitInfo, RunRecord, RunStatus, ScoreRecord, UsageTotals
from tests.factories import make_record
```

Then append to the end of the file:

```python
# phase 1b: task kinds, labels, seed values, launchers, usage -----------------------------
KINDS = ProjectConfig.model_validate(
    {
        "project": "toy",
        "datasets": {"d": {"version": "v1", "path": "x"}},
        "metrics": {
            "acc": {"version": "v2", "fn": "m:acc"},
            "lat": {"version": "v1", "fn": "m:lat"},
        },
        "tasks": {
            "t": {"dataset": "d", "metrics": ["acc"], "primary": "acc"},
            "ai": {
                "dataset": "d",
                "metrics": ["acc"],
                "primary": "acc",
                "kind": "agent_iteration",
            },
            "sb": {
                "dataset": "d",
                "metrics": ["lat"],
                "primary": "lat/p95",
                "kind": "system_bench",
                "baseline": "tag:baseline",
            },
        },
    }
)


def krun(rid: str, group: str, *, task: str = "t", minute: int = 0, **extra: Any) -> RunRecord:
    return make_record(
        rid,
        task=task,
        status=RunStatus.FINISHED,
        config_hash=f"sha256:{group}",
        git=GitInfo(commit="c1"),
        created_at=T0 + timedelta(minutes=minute),
        **extra,
    )


def acc(value: float) -> list[ScoreRecord]:
    return [score("acc", value)]


def bench_runs() -> tuple[list[RunRecord], dict[str, list[ScoreRecord]]]:
    """Baseline p95 440/430/450 ms (tagged), candidate 300/310/320 ms; 3 repeats each."""
    runs: list[RunRecord] = []
    scores: dict[str, list[ScoreRecord]] = {}
    groups = {"base": ([440, 430, 450], ["baseline"]), "fast": ([300, 310, 320], [])}
    for g, (values, tags) in groups.items():
        for i, v in enumerate(values):
            rid = f"{g}{i}"
            runs.append(krun(rid, g, task="sb", minute=i, hypothesis=g, tags=tags))
            scores[rid] = [
                ScoreRecord(metric="lat", version="v1", key="p95", value=float(v), created_at=T0)
            ]
    return runs, scores


def test_group_label() -> None:
    assert group_label("RBF-kernel SVM should beat RF because x", [], "g") == "RBF-kernel SVM"
    assert group_label("baseline rf", ["x"], "g") == "baseline rf"
    assert group_label("warmup 500, cosine decay", [], "g") == "warmup 500"
    assert group_label("(ablation) no dropout", [], "g") == "ablation"
    assert group_label("", ["svm", "best"], "g") == "best"
    assert group_label("  ", [], "63c2ec5f@8f4cac4") == "group 63c2ec5f@8f4cac4"
    long = "increase the learning rate warmup schedule length for the larger model"
    assert group_label(long, [], "g") == "increase the learning rate…"


def test_rows_carry_seed_values_launchers_usage_and_labels() -> None:
    runs = [
        krun(
            "a0",
            "a",
            hypothesis="svm wins",
            created_by="human",
            usage=UsageTotals(tokens_in=100, usd=0.5, calls=2),
        ),
        krun(
            "a1",
            "a",
            minute=1,
            hypothesis="svm wins",
            created_by="agent:claude",
            usage=UsageTotals(tokens_in=50, tokens_out=7, usd=0.25, seconds=1.5, calls=1),
        ),
        krun("b0", "b", tags=["rf"]),
    ]
    scores = {"a0": acc(0.9), "a1": acc(0.9), "b0": acc(0.7)}
    board = build_leaderboard("toy", "t", KINDS, runs, scores)
    a, b = board.rows
    assert board.kind == "generic"
    assert a.label == "svm wins" and b.label == "rf"
    assert a.seed_values == {"acc/value": [0.9, 0.9]} and a.identical_seeds
    assert not b.identical_seeds  # n = 1 is never "identical"
    assert a.created_by == ["agent:claude", "human"]
    assert a.usage == UsageTotals(tokens_in=150, tokens_out=7, usd=0.75, seconds=1.5, calls=3)
    assert b.usage is None
    assert a.test_interval is None and a.vs_best is None


def test_system_bench_percentile_is_lower_is_better() -> None:
    runs, scores = bench_runs()
    board = build_leaderboard("toy", "sb", KINDS, runs, scores)
    assert board.kind == "system_bench" and board.higher_is_better is False
    assert board.primary == "lat/p95"
    assert [r.label for r in board.rows] == ["fast", "base"]
    assert board.rows[0].seed_values == {"lat/p95": [300.0, 310.0, 320.0]}


def test_agent_iteration_labels_are_versions() -> None:
    runs = [
        krun("v9", "v9", task="ai", params={"version": "v9"}, hypothesis="add retry"),
        krun("v10", "v10", task="ai", params={"version": "v10"}, hypothesis="add cache"),
        krun("n", "n", task="ai", hypothesis="no version param"),
    ]
    scores = {"v9": acc(0.4), "v10": acc(0.5), "n": acc(0.3)}
    board = build_leaderboard("toy", "ai", KINDS, runs, scores)
    assert [r.label for r in board.rows] == ["v10", "v9", "no version param"]


def test_nan_score_is_ignored_like_an_error() -> None:
    # a metric that divides by zero returns NaN; it must not rank, lead, or reach JSON
    runs = [krun("a0", "a", hypothesis="nan run"), krun("b0", "b", hypothesis="ok run")]
    scores = {"a0": acc(float("nan")), "b0": acc(0.5)}
    board = build_leaderboard("toy", "t", KINDS, runs, scores)
    assert [r.label for r in board.rows] == ["ok run"]
    assert board.unscored == ["a0"]
    assert "nan" not in board.model_dump_json().lower()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/core/test_leaderboard.py -v`
Expected: FAIL at collection with `ImportError: cannot import name 'group_label' from 'hypothex.core.leaderboard'`.

- [ ] **Step 3: Write the implementation**

Replace the whole of `src/hypothex/core/leaderboard.py` with:

```python
"""Rank seed groups of a task by its primary metric, with seed and test-set noise."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Iterable
from typing import Any, Literal

from pydantic import BaseModel

from hypothex.core.config import ProjectConfig, TaskKind, TaskSpec, parse_metric_key
from hypothex.core.headlines import percentile_of
from hypothex.core.records import RunRecord, RunStatus, ScoreRecord, UsageTotals
from hypothex.core.seeds import Stats, intervals_overlap, summarize

LABEL_MAX = 32
_CLAUSE = re.compile(
    r"[,;:()]|\s[-–—]\s|\.(?:\s|$)|\s(?:because|should|so that|since|to see if|in order to)\s",
    re.IGNORECASE,
)


class NoiseInterval(BaseModel):
    """A 95% interval from test-set noise."""

    lo: float
    hi: float
    method: Literal["wilson", "bootstrap"]
    n: int


class VersusBest(BaseModel):
    """How a seed group compares to the best group."""

    delta: float
    p: float | None
    fixed: int | None
    broken: int | None
    test: Literal["sign", "paired_bootstrap", "welch"] | None
    examples_needed: int | None


class LeaderboardRow(BaseModel):
    """One seed group: runs with the same config hash and commit."""

    group_id: str
    run_ids: list[str]
    latest_run_id: str
    hypothesis: str
    commit: str | None
    config_hash: str
    n: int
    scores: dict[str, Stats]
    primary: Stats | None
    single_seed: bool
    within_noise_of_best: bool | None = None
    label: str
    seed_values: dict[str, list[float]]
    identical_seeds: bool
    test_interval: NoiseInterval | None
    vs_best: VersusBest | None
    created_by: list[str]
    usage: UsageTotals | None


class Leaderboard(BaseModel):
    """A task's ranked seed groups plus runs that need attention."""

    project: str
    task: str
    primary: str
    higher_is_better: bool
    metric_versions: dict[str, str]
    rows: list[LeaderboardRow]
    needs_reeval: list[str]
    unscored: list[str]
    headline: str
    kind: TaskKind
    stat_strip: list[dict[str, Any]]


# labels and ordering -------------------------------------------------------------
def group_label(hypothesis: str, tags: Iterable[str], group_id: str) -> str:
    """
    Derive a short name for a seed group.

    Parameters
    ----------
    hypothesis : str
        The group's hypothesis (latest run).
    tags : iterable of str
        Tags of the group's runs.
    group_id : str
        The group id, used when there is nothing else.

    Returns
    -------
    str
        The hypothesis's first clause (cut at ``, ; : ( )``, a dash, a full stop,
        or words like "because"/"should"), at most 32 characters; else the first
        tag in sorted order; else ``"group <id>"``.

    Examples
    --------
    >>> group_label("RBF-kernel SVM should beat RF", [], "g")
    'RBF-kernel SVM'
    >>> group_label("", ["svm"], "g")
    'svm'
    """
    parts = [p.strip() for p in _CLAUSE.split(hypothesis.strip())]
    clause = next((p for p in parts if p), "")
    if clause:
        if len(clause) <= LABEL_MAX:
            return clause
        cut = clause[:LABEL_MAX].rsplit(" ", 1)[0].rstrip() or clause[:LABEL_MAX]
        return cut + "…"
    tag_list = sorted({t for t in tags if t})
    return tag_list[0] if tag_list else f"group {group_id}"


def group_id_for(run: RunRecord) -> str:
    """
    Return the seed-group id of a run.

    Parameters
    ----------
    run : RunRecord
        Any run.

    Returns
    -------
    str
        ``<first 8 hex of the config hash>@<first 7 chars of the commit>``;
        ``nogit`` replaces the commit when the run has no git info.

    Examples
    --------
    >>> group_id_for(make_record(config_hash="sha256:0123456789"))  # doctest: +SKIP
    '01234567@nogit'
    """
    return f"{run.config_hash.removeprefix('sha256:')[:8]}@{(run.git.commit or 'nogit')[:7]}"


def _version_of(members: list[RunRecord], param: str) -> str | None:
    for m in members:
        value = m.params.get(param) or m.vars.get(param)
        if value:
            return value
    return None


def _higher_is_better(config: ProjectConfig, spec: TaskSpec) -> bool:
    metric, key = parse_metric_key(spec.primary)
    if spec.kind == "system_bench" and percentile_of(f"{metric}/{key}"):
        return False
    return config.metrics[metric].higher_is_better


# rows --------------------------------------------------------------------------------
def _sum_usage(members: list[RunRecord]) -> UsageTotals | None:
    used = [m.usage for m in members if m.usage is not None]
    if not used:
        return None
    return UsageTotals(
        tokens_in=sum(u.tokens_in for u in used),
        tokens_out=sum(u.tokens_out for u in used),
        usd=math.fsum(u.usd for u in used),
        seconds=math.fsum(u.seconds for u in used),
        calls=sum(u.calls for u in used),
    )


def _make_row(
    members: list[RunRecord],
    per_run: dict[str, dict[str, float]],
    spec: TaskSpec,
    primary: str,
) -> LeaderboardRow:
    members.sort(key=lambda r: (r.created_at, r.run_id))
    latest = members[-1]
    chash, commit = latest.config_hash, latest.git.commit
    group_id = group_id_for(latest)
    keys = sorted({k for m in members for k in per_run[m.run_id]})
    seed_values = {
        k: [per_run[m.run_id][k] for m in members if k in per_run[m.run_id]] for k in keys
    }
    summary = {k: summarize(v) for k, v in seed_values.items()}
    prim = seed_values.get(primary, [])
    version = _version_of(members, spec.version_param)
    if spec.kind == "agent_iteration" and version:
        label = version
    else:
        label = group_label(latest.hypothesis, (t for m in members for t in m.tags), group_id)
    return LeaderboardRow(
        group_id=group_id,
        run_ids=[m.run_id for m in members],
        latest_run_id=latest.run_id,
        hypothesis=latest.hypothesis,
        commit=commit,
        config_hash=chash,
        n=len(members),
        scores=summary,
        primary=summary.get(primary),
        single_seed=len(members) == 1,
        label=label,
        seed_values=seed_values,
        identical_seeds=len(prim) > 1 and all(v == prim[0] for v in prim),
        test_interval=None,
        vs_best=None,
        created_by=sorted({m.created_by for m in members}),
        usage=_sum_usage(members),
    )


def build_leaderboard(
    project: str,
    task: str,
    config: ProjectConfig,
    runs: list[RunRecord],
    scores: dict[str, list[ScoreRecord]],
    versions: dict[str, str] | None = None,
) -> Leaderboard:
    """
    Build a leaderboard for one task.

    Only finished, unarchived runs of the task count. Scores must match the
    selected metric version and have no error; the newest such score wins.

    Parameters
    ----------
    project : str
        Project name.
    task : str
        Task name.
    config : ProjectConfig
        Current project config (metric versions, direction, task kind).
    runs : list of RunRecord
        Candidate runs.
    scores : dict of str to list of ScoreRecord
        Scores per run id.
    versions : dict of str to str, optional
        Metric version overrides; default is each metric's current version.

    Returns
    -------
    Leaderboard
        Ranked seed groups and runs that need attention.
    """
    spec = config.tasks[task]
    chosen = {m: (versions or {}).get(m, config.metrics[m].version) for m in spec.metrics}
    primary_metric, primary_key = parse_metric_key(spec.primary)
    primary = f"{primary_metric}/{primary_key}"
    higher = _higher_is_better(config, spec)
    eligible = [
        r for r in runs if r.task == task and r.status == RunStatus.FINISHED and not r.archived
    ]

    per_run: dict[str, dict[str, float]] = {}
    needs_reeval: list[str] = []
    unscored: list[str] = []
    for r in eligible:
        run_scores = sorted(scores.get(r.run_id, []), key=lambda s: s.created_at)
        current: dict[tuple[str, str], float] = {}
        for s in run_scores:
            if (
                s.metric in chosen
                and s.version == chosen[s.metric]
                and s.error is None
                and s.value is not None
                and math.isfinite(s.value)
            ):
                current[(s.metric, s.key)] = s.value
        stale = any(s.metric in chosen and s.version != chosen[s.metric] for s in run_scores)
        missing_metric = any(all(m != k[0] for k in current) for m in chosen)
        if stale and missing_metric:
            needs_reeval.append(r.run_id)
        if current:
            per_run[r.run_id] = {f"{m}/{k}": v for (m, k), v in current.items()}
        elif not stale:
            unscored.append(r.run_id)

    groups: dict[tuple[str, str | None], list[RunRecord]] = defaultdict(list)
    for r in eligible:
        if r.run_id in per_run:
            groups[(r.config_hash, r.git.commit)].append(r)

    rows = [_make_row(members, per_run, spec, primary) for members in groups.values()]

    def sort_key(row: LeaderboardRow) -> tuple[int, float]:
        if row.primary is None:
            return (1, 0.0)
        return (0, -row.primary.mean if higher else row.primary.mean)

    rows.sort(key=sort_key)
    if rows and rows[0].primary is not None:
        best = rows[0].primary
        for row in rows[1:]:
            if row.primary is not None:
                row.within_noise_of_best = intervals_overlap(row.primary, best)

    return Leaderboard(
        project=project,
        task=task,
        primary=primary,
        higher_is_better=higher,
        metric_versions=chosen,
        rows=rows,
        needs_reeval=needs_reeval,
        unscored=unscored,
        headline="",
        kind=spec.kind,
        stat_strip=[],
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/core/test_leaderboard.py tests/core/test_queries.py tests/api tests/cli tests/mcp -q && uv run ruff check src/hypothex/core/leaderboard.py tests/core/test_leaderboard.py && uv run ruff format --check src/hypothex/core/leaderboard.py tests/core/test_leaderboard.py && uv run ty check src/hypothex/core/leaderboard.py`
Expected: all pass (the four phase 1a leaderboard tests and the five new ones included); ruff and ty clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/leaderboard.py tests/core/test_leaderboard.py
git commit -m "feat: leaderboard rows carry labels, seed values, launchers, usage, and kind"
```

---

### Task 11: Test-set intervals and paired comparison with the best group

**Files:**
- Modify: `src/hypothex/core/leaderboard.py`
- Test: `tests/core/test_leaderboard.py`

**Interfaces:**
- Consumes: `stats.wilson_interval`, `stats.sign_test`, `stats.examples_needed`, `stats.bootstrap_mean_interval`, `stats.paired_bootstrap_p`, `stats.welch_p` (contract 1.1). `krun`, `acc`, `KINDS` test helpers (Task 10).
- Produces:
  - `build_leaderboard(project, task, config, runs, scores, versions=None, *, per_example: PerExample | None = None) -> Leaderboard`, where `PerExample = dict[str, dict[str, dict[str, Any]]]` (run_id → example_id → per-example fields of the primary metric at the chosen version). Entries for runs that are not eligible (archived, other task, unscored, unknown) are ignored.
  - `pick_field(rows: Iterable[dict[str, Any]], key: str = "value") -> tuple[str, bool] | None`
  - Each scored row gets `test_interval` when per-example data exists. Each non-best scored row gets `vs_best`, with `test` = `"sign"` (binary), `"paired_bootstrap"` (numeric), `"welch"` (no shared examples, n ≥ 2 each, non-zero variance), or `None` (no test possible, `p` is None). `examples_needed` is set only for the sign test.

- [ ] **Step 1: Write the failing tests**

In `tests/core/test_leaderboard.py`, replace the import block (from `from datetime import timedelta` down to, but not including, `CFG = ProjectConfig.model_validate(`) with:

```python
from datetime import timedelta
from typing import Any

import pytest

from hypothex.core import stats
from hypothex.core.config import ProjectConfig
from hypothex.core.ids import utcnow
from hypothex.core.leaderboard import build_leaderboard, group_label, pick_field
from hypothex.core.records import GitInfo, RunRecord, RunStatus, ScoreRecord, UsageTotals
from tests.factories import make_record
```

Append to the end of the file:

```python
# phase 1b: test-set noise and paired tests ---------------------------------------------
def binary(n: int, right: set[int]) -> dict[str, dict[str, Any]]:
    return {f"e{i}": {"correct": i in right} for i in range(n)}


def test_pick_field() -> None:
    assert pick_field([{"correct": True, "loss": 0.2}]) == ("correct", True)
    assert pick_field([{"solved": 1}, {"solved": 0}]) == ("solved", True)
    assert pick_field([{"hit": 1}, {"hit": 0}]) == ("hit", False)
    assert pick_field([{"ok": False, "f1": 0.5}]) == ("ok", True)
    assert pick_field([{"a": 0.1, "f1": 0.5}], key="f1") == ("f1", False)
    assert pick_field([{"a": 0.1, "f1": None}], key="f1") == ("a", False)
    assert pick_field([{"note": "x"}]) is None
    assert pick_field([]) is None


def test_binary_examples_give_wilson_interval_and_sign_test() -> None:
    runs = [krun("a0", "a", hypothesis="svm"), krun("b0", "b", hypothesis="rf")]
    scores = {"a0": acc(0.8), "b0": acc(0.4)}
    per_example = {"a0": binary(10, set(range(8))), "b0": binary(10, {0, 1, 2, 8})}
    board = build_leaderboard("toy", "t", KINDS, runs, scores, per_example=per_example)
    best, other = board.rows
    # Reference: statsmodels proportion_confint(8, 10, method="wilson")
    ti = best.test_interval
    assert ti is not None and (ti.method, ti.n) == ("wilson", 10)
    assert ti.lo == pytest.approx(0.49016247153664183)
    assert ti.hi == pytest.approx(0.9433178485456247)
    # Reference: statsmodels proportion_confint(4, 10, method="wilson")
    assert other.test_interval is not None
    assert other.test_interval.lo == pytest.approx(0.16818032970623614)
    assert other.test_interval.hi == pytest.approx(0.6873262302663417)
    assert best.vs_best is None
    vs = other.vs_best
    assert vs is not None and vs.test == "sign"
    assert vs.delta == pytest.approx(-0.4)
    assert (vs.fixed, vs.broken) == (5, 1)  # e3..e7 only svm; e8 only rf
    assert vs.p == pytest.approx(0.21875)  # scipy.stats.binomtest(1, 6).pvalue = 14/64
    assert vs.examples_needed == stats.examples_needed(5, 1, 10)
    assert vs.examples_needed is not None


def test_seeds_pooled_per_example_by_majority() -> None:
    runs = [krun(f"a{i}", "a", minute=i) for i in range(3)] + [krun("b0", "b")]
    scores = {"a0": acc(0.5), "a1": acc(0.5), "a2": acc(0.5), "b0": acc(0.25)}
    per_example = {
        "a0": binary(4, {0, 1}),
        "a1": binary(4, {0, 2}),
        "a2": binary(4, {0, 1}),
        "b0": binary(4, {2}),
    }
    board = build_leaderboard("toy", "t", KINDS, runs, scores, per_example=per_example)
    best, other = board.rows
    assert best.identical_seeds and best.seed_values == {"acc/value": [0.5, 0.5, 0.5]}
    # pooled per example: 1, 2/3, 1/3, 0 -> 2 of 4; statsmodels wilson(2, 4)
    assert best.test_interval is not None and best.test_interval.n == 4
    assert best.test_interval.lo == pytest.approx(0.15003898915214947)
    assert best.test_interval.hi == pytest.approx(0.8499610108478506)
    vs = other.vs_best
    assert vs is not None and (vs.fixed, vs.broken) == (2, 1)  # majority: a passes e0, e1
    assert vs.p == pytest.approx(1.0)  # scipy.stats.binomtest(1, 3).pvalue


def test_continuous_examples_use_bootstrap() -> None:
    runs = [krun("a0", "a"), krun("b0", "b")]
    scores = {"a0": acc(0.75), "b0": acc(0.5)}
    a_vals, b_vals = [0.9, 0.8, 0.7, 0.6], [0.5, 0.6, 0.4, 0.5]
    per_example = {
        "a0": {f"e{i}": {"score": v} for i, v in enumerate(a_vals)},
        "b0": {f"e{i}": {"score": v} for i, v in enumerate(b_vals)},
    }
    board = build_leaderboard("toy", "t", KINDS, runs, scores, per_example=per_example)
    best, other = board.rows
    ti = best.test_interval
    assert ti is not None and ti.method == "bootstrap" and ti.n == 4
    assert (ti.lo, ti.hi) == stats.bootstrap_mean_interval(a_vals)
    assert 0.6 <= ti.lo <= 0.75 <= ti.hi <= 0.9
    vs = other.vs_best
    assert vs is not None and vs.test == "paired_bootstrap"
    assert vs.p == stats.paired_bootstrap_p(b_vals, a_vals)
    assert vs.fixed is None and vs.broken is None and vs.examples_needed is None


def test_without_examples_seed_groups_use_welch() -> None:
    runs, scores = [], {}
    for g, values in {"a": [0.80, 0.82, 0.81], "b": [0.70, 0.71, 0.69], "c": [0.5]}.items():
        for i, v in enumerate(values):
            runs.append(krun(f"{g}{i}", g, minute=i))
            scores[f"{g}{i}"] = acc(v)
    board = build_leaderboard("toy", "t", KINDS, runs, scores, per_example={})
    _, b, c = board.rows
    assert b.test_interval is None
    assert b.vs_best is not None and b.vs_best.test == "welch"
    # Reference: scipy.stats.ttest_ind(b, a, equal_var=False).pvalue
    assert b.vs_best.p == pytest.approx(0.00017563538261646214, rel=1e-6)
    assert c.vs_best is not None and c.vs_best.test is None and c.vs_best.p is None
    assert c.vs_best.delta == pytest.approx(-0.31)


def test_examples_of_other_runs_are_ignored() -> None:
    runs = [krun("a0", "a"), krun("x", "x", archived=True)]
    # rows of an archived run and of an unknown run would make "correct" non-binary
    per_example = {
        "a0": binary(2, {0}),
        "x": {"e0": {"correct": 0.5}},
        "ghost": {"e1": {"correct": 0.5}},
    }
    board = build_leaderboard("toy", "t", KINDS, runs, {"a0": acc(0.5)}, per_example=per_example)
    ti = board.rows[0].test_interval
    assert ti is not None and (ti.method, ti.n) == ("wilson", 2)


def test_paired_test_uses_only_shared_examples() -> None:
    # b0 was scored on the first 5 examples only (the test split grew between runs)
    runs = [krun("a0", "a", hypothesis="svm"), krun("b0", "b", hypothesis="rf")]
    scores = {"a0": acc(0.8), "b0": acc(0.4)}
    per_example = {"a0": binary(10, set(range(8))), "b0": binary(5, {0, 1})}
    board = build_leaderboard("toy", "t", KINDS, runs, scores, per_example=per_example)
    best, other = board.rows
    assert best.test_interval is not None and best.test_interval.n == 10
    assert other.test_interval is not None and other.test_interval.n == 5
    vs = other.vs_best
    assert vs is not None and vs.test == "sign"
    assert (vs.fixed, vs.broken) == (3, 0)  # e2, e3, e4; e5..e9 are not shared
    assert vs.p == pytest.approx(0.25)  # scipy.stats.binomtest(0, 3).pvalue = 2 / 8
    assert vs.examples_needed == stats.examples_needed(3, 0, 5)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/core/test_leaderboard.py -v`
Expected: FAIL at collection with `ImportError: cannot import name 'pick_field' from 'hypothex.core.leaderboard'`.

- [ ] **Step 3: Write the implementation**

In `src/hypothex/core/leaderboard.py`:

(a) Replace the lines from `from hypothex.core.config import` down to, but not including, `_CLAUSE = re.compile(` with:

```python
from hypothex.core import stats
from hypothex.core.config import ProjectConfig, TaskKind, TaskSpec, parse_metric_key
from hypothex.core.headlines import percentile_of
from hypothex.core.records import RunRecord, RunStatus, ScoreRecord, UsageTotals
from hypothex.core.seeds import Stats, intervals_overlap, summarize

PerExample = dict[str, dict[str, dict[str, Any]]]
"""run_id -> example_id -> per-example fields of the primary metric."""

BINARY_FIELDS = ("correct", "solved")
LABEL_MAX = 32
```

(b) Insert this block directly above the line `# rows --------------------------------------------------------------------------------`:

```python
# test-set noise --------------------------------------------------------------------
def _is_number(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)


def pick_field(rows: Iterable[dict[str, Any]], key: str = "value") -> tuple[str, bool] | None:
    """
    Choose the per-example field used for test-set noise and paired tests.

    Parameters
    ----------
    rows : iterable of dict
        Per-example score dicts (one per example and run).
    key : str
        The primary metric's key, preferred among numeric fields.

    Returns
    -------
    tuple of (str, bool) or None
        Field name and whether it is binary. Order: ``correct`` or ``solved``
        if binary (bools, or 0/1); any all-bool field (sorted by name);
        ``key`` if numeric; any all-numeric field. ``None`` values are ignored.

    Examples
    --------
    >>> pick_field([{"correct": True, "loss": 0.2}])
    ('correct', True)
    >>> pick_field([{"f1": 0.5}], key="f1")
    ('f1', False)
    """
    values: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        for k, v in row.items():
            if v is not None:
                values[k].append(v)

    def binary(k: str) -> bool:
        vs = values[k]
        if all(isinstance(v, bool) for v in vs):
            return True
        return k in BINARY_FIELDS and all(isinstance(v, int) and v in (0, 1) for v in vs)

    for k in BINARY_FIELDS:
        if k in values and binary(k):
            return k, True
    for k in sorted(values):
        if all(isinstance(v, bool) for v in values[k]):
            return k, True
    if key in values and all(_is_number(v) for v in values[key]):
        return key, False
    for k in sorted(values):
        if all(_is_number(v) for v in values[k]):
            return k, False
    return None


def _pool(run_ids: list[str], per_example: PerExample, field: str) -> dict[str, float]:
    seen: dict[str, list[float]] = defaultdict(list)
    for rid in run_ids:
        for ex, fields in per_example.get(rid, {}).items():
            v = fields.get(field)
            if isinstance(v, bool | int | float) and math.isfinite(v):
                seen[ex].append(float(v))
    return {ex: math.fsum(vs) / len(vs) for ex, vs in seen.items()}


def _test_interval(pooled: dict[str, float], binary: bool) -> NoiseInterval | None:
    if not pooled:
        return None
    values = [pooled[k] for k in sorted(pooled)]
    if binary:
        successes = math.floor(math.fsum(values) + 0.5)
        lo, hi = stats.wilson_interval(successes, len(values))
        return NoiseInterval(lo=lo, hi=hi, method="wilson", n=len(values))
    lo, hi = stats.bootstrap_mean_interval(values)
    return NoiseInterval(lo=lo, hi=hi, method="bootstrap", n=len(values))


def _versus(
    row: LeaderboardRow,
    best: LeaderboardRow,
    pooled: dict[str, dict[str, float]],
    binary: bool | None,
    primary: str,
) -> VersusBest:
    assert row.primary is not None and best.primary is not None
    delta = row.primary.mean - best.primary.mean
    mine, theirs = pooled.get(row.group_id, {}), pooled.get(best.group_id, {})
    common = sorted(mine.keys() & theirs.keys())
    if common and binary:
        row_pass = [mine[k] > 0.5 for k in common]
        best_pass = [theirs[k] > 0.5 for k in common]
        fixed = sum(1 for r, b in zip(row_pass, best_pass, strict=True) if b and not r)
        broken = sum(1 for r, b in zip(row_pass, best_pass, strict=True) if r and not b)
        return VersusBest(
            delta=delta,
            p=stats.sign_test(fixed, broken),
            fixed=fixed,
            broken=broken,
            test="sign",
            examples_needed=stats.examples_needed(fixed, broken, len(common)),
        )
    if common and binary is False:
        p = stats.paired_bootstrap_p([mine[k] for k in common], [theirs[k] for k in common])
        return VersusBest(
            delta=delta, p=p, fixed=None, broken=None, test="paired_bootstrap", examples_needed=None
        )
    p = stats.welch_p(row.seed_values.get(primary, []), best.seed_values.get(primary, []))
    return VersusBest(
        delta=delta,
        p=p,
        fixed=None,
        broken=None,
        test="welch" if p is not None else None,
        examples_needed=None,
    )
```

(c) Replace `build_leaderboard` (from `def build_leaderboard(` to the end of the file) with:

```python
def build_leaderboard(
    project: str,
    task: str,
    config: ProjectConfig,
    runs: list[RunRecord],
    scores: dict[str, list[ScoreRecord]],
    versions: dict[str, str] | None = None,
    *,
    per_example: PerExample | None = None,
) -> Leaderboard:
    """
    Build a leaderboard for one task.

    Only finished, unarchived runs of the task count. Scores must match the
    selected metric version and have no error; the newest such score wins.

    Parameters
    ----------
    project : str
        Project name.
    task : str
        Task name.
    config : ProjectConfig
        Current project config (metric versions, direction, task kind).
    runs : list of RunRecord
        Candidate runs.
    scores : dict of str to list of ScoreRecord
        Scores per run id.
    versions : dict of str to str, optional
        Metric version overrides; default is each metric's current version.
    per_example : dict, optional
        run_id -> example_id -> per-example fields of the primary metric at
        the selected version. Enables test-set intervals and paired tests;
        without it rows are compared with a Welch t-test over seed values.

    Returns
    -------
    Leaderboard
        Ranked seed groups and runs that need attention.
    """
    spec = config.tasks[task]
    chosen = {m: (versions or {}).get(m, config.metrics[m].version) for m in spec.metrics}
    primary_metric, primary_key = parse_metric_key(spec.primary)
    primary = f"{primary_metric}/{primary_key}"
    higher = _higher_is_better(config, spec)
    eligible = [
        r for r in runs if r.task == task and r.status == RunStatus.FINISHED and not r.archived
    ]

    per_run: dict[str, dict[str, float]] = {}
    needs_reeval: list[str] = []
    unscored: list[str] = []
    for r in eligible:
        run_scores = sorted(scores.get(r.run_id, []), key=lambda s: s.created_at)
        current: dict[tuple[str, str], float] = {}
        for s in run_scores:
            if (
                s.metric in chosen
                and s.version == chosen[s.metric]
                and s.error is None
                and s.value is not None
                and math.isfinite(s.value)
            ):
                current[(s.metric, s.key)] = s.value
        stale = any(s.metric in chosen and s.version != chosen[s.metric] for s in run_scores)
        missing_metric = any(all(m != k[0] for k in current) for m in chosen)
        if stale and missing_metric:
            needs_reeval.append(r.run_id)
        if current:
            per_run[r.run_id] = {f"{m}/{k}": v for (m, k), v in current.items()}
        elif not stale:
            unscored.append(r.run_id)

    groups: dict[tuple[str, str | None], list[RunRecord]] = defaultdict(list)
    for r in eligible:
        if r.run_id in per_run:
            groups[(r.config_hash, r.git.commit)].append(r)

    examples = {rid: ex for rid, ex in (per_example or {}).items() if rid in per_run}
    picked = pick_field((f for ex in examples.values() for f in ex.values()), primary_key)
    rows: list[LeaderboardRow] = []
    pooled: dict[str, dict[str, float]] = {}
    for members in groups.values():
        row = _make_row(members, per_run, spec, primary)
        if picked is not None:
            pooled[row.group_id] = _pool(row.run_ids, examples, picked[0])
            row.test_interval = _test_interval(pooled[row.group_id], picked[1])
        rows.append(row)

    def sort_key(row: LeaderboardRow) -> tuple[int, float]:
        if row.primary is None:
            return (1, 0.0)
        return (0, -row.primary.mean if higher else row.primary.mean)

    rows.sort(key=sort_key)
    if rows and rows[0].primary is not None:
        best = rows[0]
        for row in rows[1:]:
            if row.primary is not None and best.primary is not None:
                row.within_noise_of_best = intervals_overlap(row.primary, best.primary)
                binary = picked[1] if picked is not None else None
                row.vs_best = _versus(row, best, pooled, binary, primary)

    return Leaderboard(
        project=project,
        task=task,
        primary=primary,
        higher_is_better=higher,
        metric_versions=chosen,
        rows=rows,
        needs_reeval=needs_reeval,
        unscored=unscored,
        headline="",
        kind=spec.kind,
        stat_strip=[],
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/core/test_leaderboard.py tests/core/test_queries.py -v && uv run ruff check src/hypothex/core/leaderboard.py tests/core/test_leaderboard.py && uv run ruff format --check src/hypothex/core/leaderboard.py tests/core/test_leaderboard.py && uv run ty check src/hypothex/core/leaderboard.py`
Expected: all pass; ruff and ty clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/leaderboard.py tests/core/test_leaderboard.py
git commit -m "feat: test-set intervals and paired tests against the best group"
```

---

### Task 12: Task headline, stat strip, baseline and version reference

**Files:**
- Modify: `src/hypothex/core/headlines.py`, `src/hypothex/core/leaderboard.py`
- Test: `tests/core/test_headlines.py`, `tests/core/test_leaderboard.py`

**Interfaces:**
- Consumes: `LeaderboardRow`, `Leaderboard`, `NoiseInterval`, `VersusBest` (Task 10). `vs_best` / `test_interval` (Task 11). `stats.Z95`.
- Produces (in `hypothex.core.headlines`):
  - `task_headline(board: Leaderboard, *, reference: str | None = None, gain_interval: tuple[float, float] | None = None) -> str`. For `generic`/`training`/`agent_eval`: `"SVM +0.037 over rf, p = 0.15"`, or `"SVM 0.922"` with one row. For `agent_iteration`: `"v11 0.700, +0.300 over v9 [0.016, 0.584]"`; the bracket is `gain_interval` when given (the paired interval `build_leaderboard` computes), else a Welch interval over seed values, else nothing.
  - `paired_gain_interval(gain: float, fixed: int, broken: int, n_shared: int) -> tuple[float, float] | None`: `gain ± Z95 × sqrt(var / n)` with `d = (fixed − broken) / n`, `var = (fixed + broken) / n − d²`, `n = n_shared` = the examples both groups were scored on (not either group's own `n`: with 100 examples per group but 10 shared, the interval is `[0.296, 0.904]`, not `[0.553, 0.647]`); `None` when `n_shared <= 0`. `build_leaderboard` counts the shared examples while it still has the per-example ids. For `system_bench`: `"fast p95 −30% vs baseline [−34, −24]"`. With no scored rows: `"No scored runs yet"`.
  - `task_stat_strip(board: Leaderboard, *, reference: str | None = None) -> list[dict[str, Any]]`. Entries are `{label, value, unit, tooltip}`; `value` is the full display string. Per kind:
    - generic: `Δ <metric>`, `paired p` or `p, seeds`, `fixed / broken`, `<best> 95% CI`, `seed σ`, `n for p < 0.05`
    - training: the generic entries plus `runs`
    - agent_eval: the generic entries plus `$ / attempt`
    - agent_iteration: `fixed / broken vs <first>`, `paired p`, `seed σ`, `$ / solved`, `versions`
    - system_bench: `<pXX>`, `Δ p50`/`Δ p95`/… vs baseline, `repeats`, `repeat σ`

    Entries are left out when their data is missing.
  - `build_leaderboard` sets `board.headline` and `board.stat_strip`. For `system_bench` it resolves `TaskSpec.baseline`; for `agent_iteration` it finds the first version.

- [ ] **Step 1: Write the failing tests**

In `tests/core/test_headlines.py`, replace the lines from `import pytest` down to, but not including, `def test_fmt_value_and_delta` with:

```python
import pytest

from hypothex.core.config import TaskKind
from hypothex.core.headlines import (
    fmt_delta,
    fmt_p,
    fmt_pct,
    fmt_value,
    paired_gain_interval,
    percentile_of,
    task_headline,
    task_stat_strip,
    welch_interval,
)
from hypothex.core.leaderboard import Leaderboard, LeaderboardRow, NoiseInterval, VersusBest
from hypothex.core.records import UsageTotals
from hypothex.core.seeds import summarize


def row(
    label: str,
    seeds: list[float],
    *,
    vs: VersusBest | None = None,
    ti: NoiseInterval | None = None,
    usage: UsageTotals | None = None,
    extra: dict[str, list[float]] | None = None,
    primary: str = "acc/value",
) -> LeaderboardRow:
    values = {primary: seeds, **(extra or {})}
    return LeaderboardRow(
        group_id=f"{label}@c1",
        run_ids=[f"{label}-{i}" for i in range(len(seeds))],
        latest_run_id=f"{label}-{len(seeds) - 1}",
        hypothesis=label,
        commit="c1",
        config_hash=f"sha256:{label}",
        n=len(seeds),
        scores={k: summarize(v) for k, v in values.items()},
        primary=summarize(seeds),
        single_seed=len(seeds) == 1,
        label=label,
        seed_values=values,
        identical_seeds=len(seeds) > 1 and len(set(seeds)) == 1,
        test_interval=ti,
        vs_best=vs,
        created_by=["human"],
        usage=usage,
    )


def board(
    kind: TaskKind, rows: list[LeaderboardRow], primary: str = "acc/value", higher: bool = True
) -> Leaderboard:
    return Leaderboard(
        project="toy",
        task="toy-test",
        primary=primary,
        higher_is_better=higher,
        metric_versions={primary.split("/")[0]: "v1"},
        rows=rows,
        needs_reeval=[],
        unscored=[],
        headline="",
        kind=kind,
        stat_strip=[],
    )


def sign(delta: float, fixed: int, broken: int, p: float, needed: int | None = None) -> VersusBest:
    return VersusBest(
        delta=delta, p=p, fixed=fixed, broken=broken, test="sign", examples_needed=needed
    )


def welch(delta: float, p: float | None) -> VersusBest:
    return VersusBest(delta=delta, p=p, fixed=None, broken=None, test="welch", examples_needed=None)


# formatting -----------------------------------------------------------------------
```

Append to the end of `tests/core/test_headlines.py`:

```python
# task headline ----------------------------------------------------------------------
def test_task_headline_generic() -> None:
    svm = row("SVM", [0.922])
    rf = row("rf", [0.885], vs=sign(-0.037, 9, 3, 0.1467))
    assert task_headline(board("generic", [])) == "No scored runs yet"
    assert task_headline(board("generic", [svm])) == "SVM 0.922"
    assert task_headline(board("generic", [svm, rf])) == "SVM +0.037 over rf, p = 0.15"
    rf_no_p = row("rf", [0.885], vs=welch(-0.037, None))
    assert task_headline(board("training", [svm, rf_no_p])) == "SVM +0.037 over rf"


def test_task_headline_lower_is_better() -> None:
    small = row("small", [0.1, 0.1, 0.1])
    big = row("big", [0.2, 0.21, 0.19], vs=welch(0.1, 0.0004))
    text = task_headline(board("training", [small, big], primary="loss/value", higher=False))
    assert text == "small −0.100 over big, p < 0.001"


def test_task_headline_agent_iteration() -> None:
    ti = NoiseInterval(lo=0.0, hi=1.0, method="wilson", n=10)
    best = row("v11", [0.7], ti=ti)
    first = row("v9", [0.4], ti=ti, vs=sign(-0.3, 3, 0, 0.25))
    b = board("agent_iteration", [best, first])
    # paired CI from discordant counts on 10 shared examples:
    # 0.3 +/- 1.959964 * sqrt((0.3 - 0.3**2) / 10)
    paired = paired_gain_interval(0.3, 3, 0, 10)
    text = task_headline(b, reference="v9@c1", gain_interval=paired)
    assert text == "v11 0.700, +0.300 over v9 [0.016, 0.584]"
    # no paired interval given: Welch over seed values, and one seed each gives none
    assert task_headline(b, reference="v9@c1") == "v11 0.700, +0.300 over v9"
    assert task_headline(b) == "v11 0.700"
    assert task_headline(b, reference="v11@c1") == "v11 0.700"
    # no per-example data: Welch interval over seeds (scipy CI 0.0873-0.1327, see above)
    best = row("v2", [0.6, 0.62, 0.61])
    first = row("v1", [0.5, 0.51, 0.49], vs=welch(-0.11, 0.001))
    text = task_headline(board("agent_iteration", [best, first]), reference="v1@c1")
    assert text == "v2 0.610, +0.110 over v1 [0.087, 0.133]"


def test_paired_gain_interval_uses_the_shared_example_count() -> None:
    # 6 fixed, 0 broken on 10 shared examples: 0.6 +/- 1.959964 * sqrt((0.6 - 0.36) / 10)
    assert paired_gain_interval(0.6, 6, 0, 10) == pytest.approx(
        (0.29636368514840156, 0.9036363148515985)
    )
    # the same counts over 100 paired examples: the far narrower interval the old min(n) gave
    assert paired_gain_interval(0.6, 6, 0, 100) == pytest.approx(
        (0.553453434338595, 0.646546565661405)
    )
    assert paired_gain_interval(0.6, 6, 0, 0) is None


def test_task_headline_system_bench() -> None:
    fast = row("batching on", [300, 310, 320], primary="lat/p95")
    base = row("baseline", [440, 430, 450], primary="lat/p95")
    b = board("system_bench", [fast, base], primary="lat/p95", higher=False)
    assert task_headline(b, reference="baseline@c1") == (
        "batching on p95 −30% vs baseline [−34, −24]"
    )
    assert task_headline(b) == "batching on p95 310"
    one = board(
        "system_bench",
        [row("fast", [300], primary="lat/p95"), row("baseline", [430], primary="lat/p95")],
        primary="lat/p95",
        higher=False,
    )
    assert task_headline(one, reference="baseline@c1") == "fast p95 −30% vs baseline"


# stat strip ------------------------------------------------------------------------
def labels(strip: list[dict]) -> list[str]:
    return [s["label"] for s in strip]


def test_stat_strip_generic() -> None:
    ti = NoiseInterval(lo=0.8801, hi=0.9512, method="wilson", n=180)
    svm = row("SVM", [0.922, 0.922, 0.922], ti=ti)
    rf = row("rf", [0.885], vs=sign(-0.037, 9, 3, 0.1461, needed=250))
    strip = task_stat_strip(board("generic", [svm, rf]))
    assert strip == [
        {"label": "Δ acc", "value": "+0.037", "unit": "", "tooltip": "SVM minus rf, mean acc"},
        {
            "label": "paired p",
            "value": "0.15",
            "unit": "",
            "tooltip": "Exact two-sided sign test on 12 changed examples",
        },
        {
            "label": "fixed / broken",
            "value": "9 / 3",
            "unit": "",
            "tooltip": "Examples SVM gets right and rf gets wrong, and the reverse",
        },
        {
            "label": "SVM 95% CI",
            "value": "0.880–0.951",
            "unit": "",
            "tooltip": "Test-set 95% CI (Wilson, n = 180)",
        },
        {
            "label": "seed σ",
            "value": "◇×3",
            "unit": "",
            "tooltip": "SVM: all 3 seeds gave one score",
        },
        {
            "label": "n for p < 0.05",
            "value": "≈250",
            "unit": "",
            "tooltip": "Test examples needed at the same flip rate to reach p < 0.05",
        },
    ]
    assert task_stat_strip(board("generic", [])) == []


def test_stat_strip_training_and_agent_eval() -> None:
    a = row("big lr", [0.80, 0.82, 0.81])
    b = row("small lr", [0.70, 0.71, 0.69], vs=welch(-0.11, 0.00017563538))
    strip = task_stat_strip(board("training", [a, b]))
    assert labels(strip) == ["Δ acc", "p, seeds", "seed σ", "runs"]
    assert strip[1]["value"] == "<0.001" and strip[2]["value"] == "0.0100"
    assert strip[3]["value"] == "6"
    ti = NoiseInterval(lo=0.5, hi=0.7, method="wilson", n=10)
    best = row("opus", [0.6, 0.6, 0.6], ti=ti, usage=UsageTotals(usd=6.0, calls=30))
    strip = task_stat_strip(board("agent_eval", [best]))
    assert labels(strip) == ["opus 95% CI", "seed σ", "$ / attempt"]
    assert strip[2]["value"] == "$0.20"  # $6.00 over 3 seeds x 10 examples


def test_stat_strip_agent_iteration() -> None:
    ti = NoiseInterval(lo=0.0, hi=1.0, method="wilson", n=10)
    best = row("v11", [0.7], ti=ti, usage=UsageTotals(usd=1.4))
    mid = row("v10", [0.5], ti=ti, vs=sign(-0.2, 2, 0, 0.5))
    first = row("v9", [0.4], ti=ti, vs=sign(-0.3, 3, 0, 0.25))
    strip = task_stat_strip(board("agent_iteration", [best, mid, first]), reference="v9@c1")
    assert labels(strip) == ["fixed / broken vs v9", "paired p", "seed σ", "$ / solved", "versions"]
    assert [s["value"] for s in strip] == ["3 / 0", "0.25", "—", "$0.20", "3"]


def test_stat_strip_system_bench() -> None:
    extra_fast = {"lat/p50": [150.0, 150.0, 150.0]}
    extra_base = {"lat/p50": [200.0, 210.0, 205.0]}
    fast = row("batching on", [300, 310, 320], primary="lat/p95", extra=extra_fast)
    base = row("baseline", [440, 430, 450], primary="lat/p95", extra=extra_base)
    b = board("system_bench", [fast, base], primary="lat/p95", higher=False)
    strip = task_stat_strip(b, reference="baseline@c1")
    assert labels(strip) == ["p95", "Δ p50", "Δ p95", "repeats", "repeat σ"]
    # p50: exp(mean log 150 - mean log {200,210,205}) - 1 = -0.2681, Welch df 2 -> t 4.303
    assert [s["value"] for s in strip] == [
        "310 vs 440",
        "−27%",
        "−30%",
        "3",
        "10.0",
    ]
    assert strip[1]["tooltip"] == "p50 change vs baseline, 95% CI −31 to −22%"
    assert labels(task_stat_strip(b)) == ["p95", "repeats", "repeat σ"]
```

Append to the end of `tests/core/test_leaderboard.py`:

```python
# phase 1b: headline, stat strip, baseline, version order ------------------------------
def test_board_headline_and_stat_strip_generic() -> None:
    runs = [krun("a0", "a", hypothesis="svm"), krun("b0", "b", hypothesis="rf")]
    scores = {"a0": acc(0.8), "b0": acc(0.4)}
    per_example = {"a0": binary(10, set(range(8))), "b0": binary(10, {0, 1, 2, 8})}
    board = build_leaderboard("toy", "t", KINDS, runs, scores, per_example=per_example)
    assert board.headline == "svm +0.400 over rf, p = 0.22"
    assert [s["label"] for s in board.stat_strip] == [
        "Δ acc",
        "paired p",
        "fixed / broken",
        "svm 95% CI",
        "seed σ",
        "n for p < 0.05",
    ]
    assert [s["value"] for s in board.stat_strip][:5] == [
        "+0.400",
        "0.22",
        "5 / 1",
        "0.490–0.943",
        "—",
    ]
    assert build_leaderboard("toy", "t", KINDS, [], {}).headline == "No scored runs yet"


def test_system_bench_headline_vs_baseline() -> None:
    runs, scores = bench_runs()
    board = build_leaderboard("toy", "sb", KINDS, runs, scores)
    # exp(mean log fast - mean log base) - 1 = -29.6 %; Welch CI on log values [-34, -24] %
    # (same numbers as tests/core/test_headlines.py::test_welch_interval)
    assert board.headline == "fast p95 \u221230% vs baseline [\u221234, \u221224]"
    assert [s["label"] for s in board.stat_strip] == ["p95", "Δ p95", "repeats", "repeat σ"]
    by_id = KINDS.model_copy(deep=True)
    by_id.tasks["sb"].baseline = board.rows[1].group_id
    assert build_leaderboard("toy", "sb", by_id, runs, scores).headline == board.headline
    by_id.tasks["sb"].baseline = "tag:nothing"
    assert build_leaderboard("toy", "sb", by_id, runs, scores).headline == "fast p95 310"


def test_agent_iteration_orders_versions_naturally() -> None:
    right = {"v9": set(range(4)), "v10": set(range(5)), "v11": set(range(7))}
    runs = [krun(v, v, task="ai", params={"version": v}, hypothesis=f"try {v}") for v in right]
    scores = {v: acc(len(r) / 10) for v, r in right.items()}
    per_example = {v: binary(10, r) for v, r in right.items()}
    board = build_leaderboard("toy", "ai", KINDS, runs, scores, per_example=per_example)
    assert [r.label for r in board.rows] == ["v11", "v10", "v9"]
    # first version is v9 (natural order), not v10 (string order); CI from 3 fixed, 0 broken
    assert board.headline == "v11 0.700, +0.300 over v9 [0.016, 0.584]"
    assert board.stat_strip[0] == {
        "label": "fixed / broken vs v9",
        "value": "3 / 0",
        "unit": "",
        "tooltip": "Examples v9 missed and v11 solved, and the reverse",
    }


def test_agent_iteration_gain_interval_counts_only_shared_examples() -> None:
    # 100 examples per version, only s0..s9 shared; v2 solves s0..s5, v1 none of them
    v1 = {f"a{i}": {"correct": i < 20} for i in range(90)}
    v1 |= {f"s{i}": {"correct": False} for i in range(10)}
    v2 = {f"b{i}": {"correct": i < 74} for i in range(90)}
    v2 |= {f"s{i}": {"correct": i < 6} for i in range(10)}
    runs = [
        krun(v, v, task="ai", params={"version": v}, minute=i) for i, v in enumerate(["v1", "v2"])
    ]
    scores = {"v1": acc(0.2), "v2": acc(0.8)}
    board = build_leaderboard("toy", "ai", KINDS, runs, scores, per_example={"v1": v1, "v2": v2})
    vs = board.rows[1].vs_best
    assert vs is not None and (vs.fixed, vs.broken) == (6, 0)
    # 0.6 +/- 1.959964 * sqrt((0.6 - 0.36) / 10) = [0.296, 0.904];
    # min(group n) = 100 would give [0.553, 0.647]
    assert board.headline == "v2 0.800, +0.600 over v1 [0.296, 0.904]"


def test_agent_iteration_without_version_uses_creation_time() -> None:
    runs = [
        krun("y", "y", task="ai", minute=5, hypothesis="second try"),
        krun("x", "x", task="ai", minute=0, hypothesis="first try"),
    ]
    board = build_leaderboard("toy", "ai", KINDS, runs, {"x": acc(0.4), "y": acc(0.6)})
    assert board.headline == "second try 0.600, +0.200 over first try"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/core/test_headlines.py tests/core/test_leaderboard.py -v`
Expected: `test_headlines.py` fails at collection with `ImportError: cannot import name 'task_headline'`. The five new `test_leaderboard.py` tests fail with `AssertionError` (headline is `''`).

- [ ] **Step 3: Write the implementation**

In `src/hypothex/core/headlines.py`, replace the import block (from `from __future__ import annotations` down to, but not including, `MINUS = `) with:

```python
from __future__ import annotations

import math
import re
import statistics
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from hypothex.core.seeds import t_critical
from hypothex.core.stats import Z95

if TYPE_CHECKING:
    from hypothex.core.leaderboard import Leaderboard, LeaderboardRow
```

Append to the end of `src/hypothex/core/headlines.py`:

```python
def paired_gain_interval(
    gain: float, fixed: int, broken: int, n_shared: int
) -> tuple[float, float] | None:
    """
    95% interval of a gain from paired binary outcomes on shared examples.

    With ``d = (fixed - broken) / n`` and ``var = (fixed + broken) / n - d**2``
    (the variance of the per-example difference in ``{-1, 0, 1}``), the interval
    is ``gain ± Z95 * sqrt(var / n)``, where ``n`` is the number of examples both
    groups were scored on. Using either group's own example count instead
    understates the width whenever the test sets only partly overlap.

    Parameters
    ----------
    gain : float
        Best mean minus reference mean (the headline's number).
    fixed, broken : int
        Discordant shared examples in favour of and against the best group.
    n_shared : int
        Examples scored for both groups.

    Returns
    -------
    tuple of (float, float) or None
        Lower and upper bound; None when ``n_shared <= 0``.

    Examples
    --------
    >>> lo, hi = paired_gain_interval(0.3, 3, 0, 10)
    >>> round(lo, 3), round(hi, 3)
    (0.016, 0.584)
    """
    if n_shared <= 0:
        return None
    mean_d = (fixed - broken) / n_shared
    var = max((fixed + broken) / n_shared - mean_d**2, 0.0)
    half = Z95 * math.sqrt(var / n_shared)
    return gain - half, gain + half


def _gain_interval(
    best: LeaderboardRow,
    first: LeaderboardRow,
    primary: str,
    paired: tuple[float, float] | None,
) -> tuple[float, float] | None:
    """The paired interval when given, else a Welch interval over seed values."""
    if paired is not None:
        return paired
    w = welch_interval(best.seed_values.get(primary, []), first.seed_values.get(primary, []))
    if w is None or w[1] is None or w[2] is None:
        return None
    return w[1], w[2]


# task headline ---------------------------------------------------------------------
def _scored(board: Leaderboard) -> list[LeaderboardRow]:
    return [r for r in board.rows if r.primary is not None]


def _find(rows: list[LeaderboardRow], group_id: str | None) -> LeaderboardRow | None:
    return next((r for r in rows if r.group_id == group_id), None)


def _mean(row: LeaderboardRow) -> float:
    assert row.primary is not None
    return row.primary.mean


def task_headline(
    board: Leaderboard,
    *,
    reference: str | None = None,
    gain_interval: tuple[float, float] | None = None,
) -> str:
    """
    Return a task's one-line finding.

    Parameters
    ----------
    board : Leaderboard
        The task's leaderboard (rows ranked best first).
    reference : str, optional
        Group id to compare against: the baseline for ``system_bench``, the
        first version for ``agent_iteration``. ``build_leaderboard`` passes it.
    gain_interval : tuple of (float, float), optional
        ``agent_iteration`` only: the paired interval of the gain over the
        first version (``paired_gain_interval`` on the shared examples, which
        ``build_leaderboard`` computes). Without it the bracket is a Welch
        interval over seed values, or absent.

    Returns
    -------
    str
        ``generic``/``training``/``agent_eval``: ``"SVM +0.037 over rf, p = 0.15"``;
        ``system_bench``: ``"<best> p95 −30% vs baseline [−34, −24]"``;
        ``agent_iteration``: ``"v9 0.663, +0.263 over v1 [0.206, 0.321]"``;
        ``"No scored runs yet"`` without scored rows.
    """
    rows = _scored(board)
    if not rows:
        return NO_RUNS
    best = rows[0]
    ref = _find(rows, reference)
    if board.kind == "system_bench":
        return _bench_headline(board, best, ref)
    if board.kind == "agent_iteration":
        head = f"{best.label} {fmt_value(_mean(best))}"
        if ref is None or ref.group_id == best.group_id:
            return head
        text = f"{head}, {fmt_delta(_mean(best) - _mean(ref))} over {ref.label}"
        ci = _gain_interval(best, ref, board.primary, gain_interval)
        if ci is not None:
            text += f" [{fmt_value(ci[0])}, {fmt_value(ci[1])}]"
        return text
    if len(rows) == 1:
        return f"{best.label} {fmt_value(_mean(best))}"
    runner = rows[1]
    text = f"{best.label} {fmt_delta(_mean(best) - _mean(runner))} over {runner.label}"
    if runner.vs_best is not None and runner.vs_best.p is not None:
        text += f", {fmt_p(runner.vs_best.p)}"
    return text


def _bench_headline(board: Leaderboard, best: LeaderboardRow, base: LeaderboardRow | None) -> str:
    pct = percentile_of(board.primary) or board.primary.split("/")[0]
    plain = f"{best.label} {pct} {fmt_value(_mean(best))}"
    if base is None or base.group_id == best.group_id:
        return plain
    change = welch_interval(
        best.seed_values.get(board.primary, []), base.seed_values.get(board.primary, []), log=True
    )
    if change is None:
        return plain
    r, lo, hi = change
    text = f"{best.label} {pct} {fmt_pct(r)} vs baseline"
    if lo is not None and hi is not None:
        text += f" [{_signed_int(lo * 100)}, {_signed_int(hi * 100)}]"
    return text


# stat strip ------------------------------------------------------------------------
def _stat(label: str, value: str, tooltip: str, unit: str = "") -> dict[str, Any]:
    return {"label": label, "value": value, "unit": unit, "tooltip": tooltip}


def _seed_sigma(row: LeaderboardRow, word: str = "seed") -> dict[str, Any]:
    assert row.primary is not None
    if row.n < 2:
        return _stat(f"{word} σ", "—", f"{row.label}: single {word}")
    if row.identical_seeds:
        return _stat(f"{word} σ", f"◇×{row.n}", f"{row.label}: all {row.n} {word}s gave one score")
    std = row.primary.std
    text = f"{std:.4f}" if std < 1 else fmt_value(std)
    return _stat(f"{word} σ", text, f"Std of {row.label} over {row.n} {word}s")


def _p_stat(best: LeaderboardRow, other: LeaderboardRow) -> dict[str, Any] | None:
    vs = other.vs_best
    if vs is None or vs.p is None or vs.test is None:
        return None
    if vs.test == "welch":
        tip = f"Welch t-test over seed values, {best.n} vs {other.n} seeds"
        return _stat("p, seeds", _p_value(vs.p), tip)
    if vs.test == "sign":
        tip = f"Exact two-sided sign test on {(vs.fixed or 0) + (vs.broken or 0)} changed examples"
    else:
        tip = "Paired bootstrap of the mean difference over examples, 1,000 resamples"
    return _stat("paired p", _p_value(vs.p), tip)


def task_stat_strip(board: Leaderboard, *, reference: str | None = None) -> list[dict[str, Any]]:
    """
    Return the stat strip for a task: ``{label, value, unit, tooltip}`` entries.

    Parameters
    ----------
    board : Leaderboard
        The task's leaderboard (rows ranked best first).
    reference : str, optional
        Group id of the baseline (``system_bench``) or first version
        (``agent_iteration``).

    Returns
    -------
    list of dict
        Entries in display order; empty without scored rows. ``value`` is the
        full display string; ``unit`` is a small suffix such as ``ms``.
    """
    rows = _scored(board)
    if not rows:
        return []
    best, ref = rows[0], _find(rows, reference)
    if board.kind == "system_bench":
        return _bench_strip(board, best, ref)
    if board.kind == "agent_iteration":
        return _iteration_strip(board, best, ref)
    return _compare_strip(board, best, rows[1] if len(rows) > 1 else None)


def _compare_strip(
    board: Leaderboard, best: LeaderboardRow, runner: LeaderboardRow | None
) -> list[dict[str, Any]]:
    name = board.primary.removesuffix("/value")
    out: list[dict[str, Any]] = []
    vs = runner.vs_best if runner is not None else None
    if runner is not None:
        tip = f"{best.label} minus {runner.label}, mean {name}"
        out.append(_stat(f"Δ {name}", fmt_delta(_mean(best) - _mean(runner)), tip))
        p = _p_stat(best, runner)
        if p is not None:
            out.append(p)
        if vs is not None and vs.fixed is not None and vs.broken is not None:
            tip = f"Examples {best.label} gets right and {runner.label} gets wrong, and the reverse"
            out.append(_stat("fixed / broken", f"{vs.fixed} / {vs.broken}", tip))
    if best.test_interval is not None:
        ti = best.test_interval
        method = "Wilson" if ti.method == "wilson" else "bootstrap"
        out.append(
            _stat(
                f"{best.label} 95% CI",
                f"{fmt_value(ti.lo)}–{fmt_value(ti.hi)}",
                f"Test-set 95% CI ({method}, n = {ti.n})",
            )
        )
    out.append(_seed_sigma(best))
    if board.kind == "agent_eval" and best.usage is not None:
        attempts = best.n * (best.test_interval.n if best.test_interval else 1)
        tip = f"{best.label}: ${best.usage.usd:.2f} over {attempts} attempts"
        out.append(_stat("$ / attempt", f"${best.usage.usd / attempts:.2f}", tip))
    if vs is not None and vs.examples_needed is not None:
        tip = "Test examples needed at the same flip rate to reach p < 0.05"
        out.append(_stat("n for p < 0.05", f"≈{vs.examples_needed}", tip))
    if board.kind == "training":
        out.append(_stat("runs", str(sum(r.n for r in board.rows)), "Finished, scored runs"))
    return out


def _iteration_strip(
    board: Leaderboard, best: LeaderboardRow, first: LeaderboardRow | None
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if first is not None and first.group_id != best.group_id:
        vs = first.vs_best
        if vs is not None and vs.fixed is not None and vs.broken is not None:
            tip = f"Examples {first.label} missed and {best.label} solved, and the reverse"
            out.append(_stat(f"fixed / broken vs {first.label}", f"{vs.fixed} / {vs.broken}", tip))
        p = _p_stat(best, first)
        if p is not None:
            out.append(p)
    out.append(_seed_sigma(best))
    if best.usage is not None and best.test_interval is not None:
        solved = _mean(best) * best.test_interval.n * best.n
        if solved > 0:
            tip = f"{best.label}: ${best.usage.usd:.2f} over {solved:g} solved examples"
            out.append(_stat("$ / solved", f"${best.usage.usd / solved:.2f}", tip))
    out.append(_stat("versions", str(len(board.rows)), "Seed groups in this task"))
    return out


def _bench_strip(
    board: Leaderboard, best: LeaderboardRow, base: LeaderboardRow | None
) -> list[dict[str, Any]]:
    metric = board.primary.split("/")[0]
    pct = percentile_of(board.primary) or metric
    unit = "ms" if "ms" in board.primary else ""
    out: list[dict[str, Any]] = []
    if base is not None and base.group_id != best.group_id:
        value = f"{fmt_value(_mean(best))} vs {fmt_value(_mean(base))}"
        tip = f"{best.label} vs baseline {base.label}, mean of repeats"
        out.append(_stat(pct, value, tip, unit))
        keys = [
            k
            for k in best.seed_values
            if k.split("/")[0] == metric and percentile_of(k) and k in base.seed_values
        ]
        for key in sorted(keys, key=lambda k: float(str(percentile_of(k))[1:])):
            change = welch_interval(best.seed_values[key], base.seed_values[key], log=True)
            if change is None:
                continue
            r, lo, hi = change
            tip = f"{percentile_of(key)} change vs baseline"
            if lo is not None and hi is not None:
                tip += f", 95% CI {_signed_int(lo * 100)} to {_signed_int(hi * 100)}%"
            out.append(_stat(f"Δ {percentile_of(key)}", fmt_pct(r), tip))
    else:
        out.append(_stat(pct, fmt_value(_mean(best)), f"{best.label}, mean of repeats", unit))
    out.append(_stat("repeats", str(best.n), f"Repeats of {best.label}"))
    out.append(_seed_sigma(best, word="repeat"))
    return out
```

In `src/hypothex/core/leaderboard.py`:

(a) Replace the lines from `from collections.abc import Iterable` down to, but not including, `from hypothex.core.records import` with:

```python
from collections.abc import Iterable
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from hypothex.core import stats
from hypothex.core.config import ProjectConfig, TaskKind, TaskSpec, parse_metric_key
from hypothex.core.headlines import (
    paired_gain_interval,
    percentile_of,
    task_headline,
    task_stat_strip,
)
```

(b) Insert this block directly above `def _higher_is_better(`:

```python
def _natural_key(text: str) -> tuple[tuple[int, int | str], ...]:
    return tuple(
        (0, int(tok)) if tok.isdigit() else (1, tok.lower()) for tok in re.findall(r"\d+|\D+", text)
    )


def _first_version(
    rows: list[LeaderboardRow], members_of: dict[str, list[RunRecord]], param: str
) -> str | None:
    def key(row: LeaderboardRow) -> tuple[int, tuple[tuple[int, int | str], ...], datetime]:
        members = members_of[row.group_id]
        version = _version_of(members, param)
        created = members[0].created_at
        return (0, _natural_key(version), created) if version else (1, (), created)

    scored = [r for r in rows if r.primary is not None]
    return min(scored, key=key).group_id if scored else None


def _paired_gain(
    best: LeaderboardRow, first: LeaderboardRow, pooled: dict[str, dict[str, float]]
) -> tuple[float, float] | None:
    """
    Paired 95% interval of ``best - first`` over the examples both were scored on.

    Uses the sign-test counts of ``first.vs_best`` (computed on those same shared
    examples) and counts the shared ids here, where they are still known.
    """
    vs = first.vs_best
    if (
        vs is None
        or vs.test != "sign"
        or vs.fixed is None
        or vs.broken is None
        or best.primary is None
        or first.primary is None
    ):
        return None
    shared = pooled.get(best.group_id, {}).keys() & pooled.get(first.group_id, {}).keys()
    gain = best.primary.mean - first.primary.mean
    return paired_gain_interval(gain, vs.fixed, vs.broken, len(shared))


def _select_group(
    selector: str | None, rows: list[LeaderboardRow], members_of: dict[str, list[RunRecord]]
) -> str | None:
    if not selector:
        return None
    if selector.startswith("tag:"):
        tag = selector.removeprefix("tag:")
        for row in rows:
            if any(tag in m.tags for m in members_of[row.group_id]):
                return row.group_id
        return None
    for row in rows:
        if selector in (row.group_id, row.config_hash) or row.group_id.startswith(selector):
            return row.group_id
    return None
```

(c) Replace `build_leaderboard` (from `def build_leaderboard(` to the end of the file) with:

```python
def build_leaderboard(
    project: str,
    task: str,
    config: ProjectConfig,
    runs: list[RunRecord],
    scores: dict[str, list[ScoreRecord]],
    versions: dict[str, str] | None = None,
    *,
    per_example: PerExample | None = None,
) -> Leaderboard:
    """
    Build a leaderboard for one task.

    Only finished, unarchived runs of the task count. Scores must match the
    selected metric version and have no error; the newest such score wins.

    Parameters
    ----------
    project : str
        Project name.
    task : str
        Task name.
    config : ProjectConfig
        Current project config (metric versions, direction, task kind).
    runs : list of RunRecord
        Candidate runs.
    scores : dict of str to list of ScoreRecord
        Scores per run id.
    versions : dict of str to str, optional
        Metric version overrides; default is each metric's current version.
    per_example : dict, optional
        run_id -> example_id -> per-example fields of the primary metric at
        the selected version. Enables test-set intervals and paired tests;
        without it rows are compared with a Welch t-test over seed values.

    Returns
    -------
    Leaderboard
        Ranked seed groups, runs that need attention, headline and stat strip.
    """
    spec = config.tasks[task]
    chosen = {m: (versions or {}).get(m, config.metrics[m].version) for m in spec.metrics}
    primary_metric, primary_key = parse_metric_key(spec.primary)
    primary = f"{primary_metric}/{primary_key}"
    higher = _higher_is_better(config, spec)
    eligible = [
        r for r in runs if r.task == task and r.status == RunStatus.FINISHED and not r.archived
    ]

    per_run: dict[str, dict[str, float]] = {}
    needs_reeval: list[str] = []
    unscored: list[str] = []
    for r in eligible:
        run_scores = sorted(scores.get(r.run_id, []), key=lambda s: s.created_at)
        current: dict[tuple[str, str], float] = {}
        for s in run_scores:
            if (
                s.metric in chosen
                and s.version == chosen[s.metric]
                and s.error is None
                and s.value is not None
                and math.isfinite(s.value)
            ):
                current[(s.metric, s.key)] = s.value
        stale = any(s.metric in chosen and s.version != chosen[s.metric] for s in run_scores)
        missing_metric = any(all(m != k[0] for k in current) for m in chosen)
        if stale and missing_metric:
            needs_reeval.append(r.run_id)
        if current:
            per_run[r.run_id] = {f"{m}/{k}": v for (m, k), v in current.items()}
        elif not stale:
            unscored.append(r.run_id)

    groups: dict[tuple[str, str | None], list[RunRecord]] = defaultdict(list)
    for r in eligible:
        if r.run_id in per_run:
            groups[(r.config_hash, r.git.commit)].append(r)

    examples = {rid: ex for rid, ex in (per_example or {}).items() if rid in per_run}
    picked = pick_field((f for ex in examples.values() for f in ex.values()), primary_key)
    rows: list[LeaderboardRow] = []
    pooled: dict[str, dict[str, float]] = {}
    for members in groups.values():
        row = _make_row(members, per_run, spec, primary)
        if picked is not None:
            pooled[row.group_id] = _pool(row.run_ids, examples, picked[0])
            row.test_interval = _test_interval(pooled[row.group_id], picked[1])
        rows.append(row)

    def sort_key(row: LeaderboardRow) -> tuple[int, float]:
        if row.primary is None:
            return (1, 0.0)
        return (0, -row.primary.mean if higher else row.primary.mean)

    rows.sort(key=sort_key)
    if rows and rows[0].primary is not None:
        best = rows[0]
        for row in rows[1:]:
            if row.primary is not None and best.primary is not None:
                row.within_noise_of_best = intervals_overlap(row.primary, best.primary)
                binary = picked[1] if picked is not None else None
                row.vs_best = _versus(row, best, pooled, binary, primary)

    by_id = {r.run_id: r for r in eligible}
    members_of = {row.group_id: [by_id[i] for i in row.run_ids] for row in rows}
    reference = None
    gain_interval = None
    if spec.kind == "system_bench":
        reference = _select_group(spec.baseline, rows, members_of)
    elif spec.kind == "agent_iteration":
        reference = _first_version(rows, members_of, spec.version_param)
        first = next((row for row in rows if row.group_id == reference), None)
        if first is not None and first is not rows[0]:
            gain_interval = _paired_gain(rows[0], first, pooled)

    board = Leaderboard(
        project=project,
        task=task,
        primary=primary,
        higher_is_better=higher,
        metric_versions=chosen,
        rows=rows,
        needs_reeval=needs_reeval,
        unscored=unscored,
        headline="",
        kind=spec.kind,
        stat_strip=[],
    )
    board.headline = task_headline(board, reference=reference, gain_interval=gain_interval)
    board.stat_strip = task_stat_strip(board, reference=reference)
    return board
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/core/test_headlines.py tests/core/test_leaderboard.py tests/core/test_queries.py tests/api tests/cli tests/mcp -q && uv run ruff check src/hypothex/core tests/core && uv run ruff format --check src/hypothex/core/headlines.py src/hypothex/core/leaderboard.py tests/core && uv run ty check src/hypothex/core/headlines.py src/hypothex/core/leaderboard.py`
Expected: all pass; ruff and ty clean. (headlines.py imports leaderboard types only under `TYPE_CHECKING`, so there is no import cycle.)

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/headlines.py src/hypothex/core/leaderboard.py tests/core/test_headlines.py tests/core/test_leaderboard.py
git commit -m "feat: task headline and stat strip per kind, with baseline and version reference"
```

---

### Task 13: Overview headline

**Files:**
- Modify: `src/hypothex/core/headlines.py`
- Test: `tests/core/test_headlines.py`

**Interfaces:**
- Consumes: `Leaderboard` (Task 10), `_scored`, `_mean`, `fmt_value`, `fmt_p` (Tasks 9 and 12). `hypothex.core.seeds.Stats`.
- Produces: `overview_headline(summary: SummaryLike, *, board: Leaderboard | None = None) -> str`, and the protocols `IdeaLike`, `ProjectLike`, `SummaryLike`. `overview.OverviewSummary`, `IdeaRow` and `ProjectRow` (contract 1.9) satisfy them structurally. Results:
  - `"Idle. SVM leads toy-test by 0.037, p = 0.15"` with `board=`
  - `"2 running. SVM leads toy-test by 0.037"` without `board=`. The line uses the task of the newest scored idea, and the gap to the closest other idea in that task.
  - `"Idle. No scored runs yet"` when there are no scored ideas.

- [ ] **Step 1: Write the failing tests**

In `tests/core/test_headlines.py`, replace the lines from `import pytest` down to, but not including, `def row(` with:

```python
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pytest

from hypothex.core.config import TaskKind
from hypothex.core.headlines import (
    fmt_delta,
    fmt_p,
    fmt_pct,
    fmt_value,
    overview_headline,
    paired_gain_interval,
    percentile_of,
    task_headline,
    task_stat_strip,
    welch_interval,
)
from hypothex.core.ids import utcnow
from hypothex.core.leaderboard import Leaderboard, LeaderboardRow, NoiseInterval, VersusBest
from hypothex.core.records import UsageTotals
from hypothex.core.seeds import Stats, summarize
```

Append to the end of the file:

```python
# overview headline ----------------------------------------------------------------
T0 = utcnow()


@dataclass
class Idea:
    project: str
    task: str | None
    label: str
    primary: Stats | None
    created_at: datetime


@dataclass
class Proj:
    project: str
    task: str
    best: float | None


@dataclass
class Summary:
    running: list[object] = field(default_factory=list)
    ideas: list[Idea] = field(default_factory=list)
    projects: list[Proj] = field(default_factory=list)


def test_overview_headline_from_board() -> None:
    svm = row("SVM", [0.922])
    rf = row("rf", [0.885], vs=sign(-0.037, 9, 3, 0.1467))
    b = board("generic", [svm, rf])
    assert overview_headline(Summary(), board=b) == "Idle. SVM leads toy-test by 0.037, p = 0.15"
    busy = Summary(running=[object(), object()])
    assert overview_headline(busy, board=b) == "2 running. SVM leads toy-test by 0.037, p = 0.15"
    assert overview_headline(Summary(), board=board("generic", [svm])) == (
        "Idle. SVM leads toy-test at 0.922"
    )


def test_overview_headline_from_summary() -> None:
    assert overview_headline(Summary()) == "Idle. No scored runs yet"
    ideas = [
        Idea("toy", "toy-test", "rf", summarize([0.885]), T0),
        Idea("toy", "toy-test", "SVM", summarize([0.922]), T0 + timedelta(minutes=5)),
        Idea("toy", "toy-test", "knn", summarize([0.867]), T0 + timedelta(minutes=1)),
        Idea("other", "old", "x", summarize([0.1]), T0 - timedelta(days=1)),
    ]
    projects = [Proj("toy", "toy-test", 0.922), Proj("other", "old", 0.5)]
    summary = Summary(running=[object()], ideas=ideas, projects=projects)
    assert overview_headline(summary) == "1 running. SVM leads toy-test by 0.037"
    lone = Summary(ideas=[ideas[1]], projects=projects)
    assert overview_headline(lone) == "Idle. SVM leads toy-test at 0.922"
    moved = Summary(ideas=[ideas[0]], projects=projects)
    assert overview_headline(moved) == "Idle. toy-test best 0.922"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/core/test_headlines.py -v`
Expected: FAIL at collection with `ImportError: cannot import name 'overview_headline'`.

- [ ] **Step 3: Write the implementation**

In `src/hypothex/core/headlines.py`, replace the import block (from `from __future__ import annotations` down to, but not including, `MINUS = `) with:

```python
from __future__ import annotations

import math
import re
import statistics
from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

from hypothex.core.seeds import Stats, t_critical
from hypothex.core.stats import Z95

if TYPE_CHECKING:
    from hypothex.core.leaderboard import Leaderboard, LeaderboardRow
```

Append to the end of the file:

```python
# overview headline --------------------------------------------------------------------
class IdeaLike(Protocol):
    """What ``overview_headline`` reads from an idea row (``overview.IdeaRow``)."""

    @property
    def project(self) -> str: ...
    @property
    def task(self) -> str | None: ...
    @property
    def label(self) -> str: ...
    @property
    def primary(self) -> Stats | None: ...
    @property
    def created_at(self) -> datetime: ...


class ProjectLike(Protocol):
    """What ``overview_headline`` reads from a project row (``overview.ProjectRow``)."""

    @property
    def project(self) -> str: ...
    @property
    def task(self) -> str | None: ...
    @property
    def best(self) -> float | None: ...


class SummaryLike(Protocol):
    """What ``overview_headline`` reads from ``overview.OverviewSummary``."""

    @property
    def running(self) -> Sequence[object]: ...
    @property
    def ideas(self) -> Sequence[IdeaLike]: ...
    @property
    def projects(self) -> Sequence[ProjectLike]: ...


def overview_headline(summary: SummaryLike, *, board: Leaderboard | None = None) -> str:
    """
    Return the Overview page's one-line status.

    Parameters
    ----------
    summary : OverviewSummary
        The overview (any object with ``running``, ``ideas``, ``projects``).
    board : Leaderboard, optional
        Leaderboard of the task to lead with. With it, the line carries the
        paired p-value; without it, the task of the newest scored idea is used.

    Returns
    -------
    str
        For example ``"Idle. SVM leads toy-test by 0.037, p = 0.15"`` or
        ``"2 running. SVM leads toy-test by 0.037"``.
    """
    n = len(summary.running)
    prefix = "Idle." if n == 0 else f"{n} running."
    lead = _board_lead(board) if board is not None else _summary_lead(summary)
    return f"{prefix} {lead}"


def _board_lead(board: Leaderboard) -> str:
    rows = _scored(board)
    if not rows:
        return NO_RUNS
    best = rows[0]
    if len(rows) == 1:
        return f"{best.label} leads {board.task} at {fmt_value(_mean(best))}"
    runner = rows[1]
    text = f"{best.label} leads {board.task} by {fmt_value(abs(_mean(best) - _mean(runner)))}"
    if runner.vs_best is not None and runner.vs_best.p is not None:
        text += f", {fmt_p(runner.vs_best.p)}"
    return text


def _summary_lead(summary: SummaryLike) -> str:
    scored = [i for i in summary.ideas if i.primary is not None and i.task is not None]
    if not scored:
        return NO_RUNS
    focus = max(scored, key=lambda i: i.created_at)
    same = [i for i in scored if (i.project, i.task) == (focus.project, focus.task)]
    best = next(
        (p.best for p in summary.projects if (p.project, p.task) == (focus.project, focus.task)),
        None,
    )
    task = str(focus.task)
    if best is None:
        return f"{task} has no best yet"
    leader = next((i for i in same if i.primary and math.isclose(i.primary.mean, best)), None)
    if leader is None:
        return f"{task} best {fmt_value(best)}"
    others = [i for i in same if i is not leader and i.primary is not None]
    if not others:
        return f"{leader.label} leads {task} at {fmt_value(best)}"
    gap = min(abs(best - i.primary.mean) for i in others if i.primary is not None)
    return f"{leader.label} leads {task} by {fmt_value(gap)}"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/core/test_headlines.py -v && uv run ruff check src/hypothex/core/headlines.py tests/core/test_headlines.py && uv run ruff format --check src/hypothex/core/headlines.py tests/core/test_headlines.py && uv run ty check src/hypothex/core/headlines.py tests/core/test_headlines.py`
Expected: 14 passed; ruff and ty clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/headlines.py tests/core/test_headlines.py
git commit -m "feat: overview status headline"
```

---

### Task 14: `get_leaderboard` loads per-example scores of the primary metric

**Files:**
- Modify: `src/hypothex/core/queries.py` (imports, `get_leaderboard`, first lines of `_summary`)
- Test: `tests/core/test_queries.py`

**Interfaces:**
- Consumes: `build_leaderboard(..., *, per_example=...)` (Task 11). The eval worker's per-example file `predictions/scores.<metric>@<version>.jsonl`, with rows `{"id": ..., <field>: ...}` (phase 1a).
- Produces: `primary_examples(ctx, config, task, runs, versions) -> dict[str, dict[str, dict[str, Any]]]` (public; the panel engine, Task 20, reuses it instead of reading the files itself) and `get_leaderboard(ctx, ref, project=None, versions=None, *, examples: bool = True) -> Leaderboard`. The API, CLI and MCP keep calling it unchanged and now get intervals, `vs_best`, `headline` and `stat_strip`. `_summary` (used by `list_tasks`/`get_task`) passes `examples=False` so the task list does not read every per-example file.

- [ ] **Step 1: Write the failing tests**

Append to the end of `tests/core/test_queries.py`:

```python
def test_leaderboard_uses_per_example_scores(ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "a", predictions=PREDS_075)
    seed_finished_run(ctx, toy_repo, "b", predictions=ALL_RIGHT, config_hash="sha256:bbbb")
    evaluate_run(ctx, "a")
    evaluate_run(ctx, "b")
    board = q.get_leaderboard(ctx, "toy-acc")
    best, other = board.rows
    assert best.run_ids == ["b"] and board.kind == "generic"
    # Reference: statsmodels proportion_confint(4, 4, method="wilson")
    assert best.test_interval is not None and best.test_interval.n == 4
    assert best.test_interval.lo == pytest.approx(0.5101091635454027)
    assert best.test_interval.hi == pytest.approx(1.0)
    vs = other.vs_best
    assert vs is not None and (vs.test, vs.fixed, vs.broken) == ("sign", 1, 0)
    assert vs.p == pytest.approx(1.0)  # scipy.stats.binomtest(0, 1).pvalue
    assert board.headline == f"group {best.group_id} +0.250 over group {other.group_id}, p = 1.00"
    plain = q.get_leaderboard(ctx, "toy-acc", examples=False)
    assert plain.rows[0].test_interval is None
    assert plain.rows[1].vs_best is not None and plain.rows[1].vs_best.test is None


def test_leaderboard_examples_follow_version_override(ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "a", predictions=PREDS_075)
    evaluate_run(ctx, "a")
    write_toy_project(toy_repo, accuracy_version="v2")
    evaluate_run(ctx, "a")
    (ctx.run_dir(ctx.find_record("a")) / "predictions" / "scores.accuracy@v2.jsonl").unlink()
    assert q.get_leaderboard(ctx, "toy-acc").rows[0].test_interval is None
    old = q.get_leaderboard(ctx, "toy-acc", versions={"accuracy": "v1"})
    assert old.rows[0].test_interval is not None and old.rows[0].test_interval.n == 4
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/core/test_queries.py -v -k "per_example or version_override"`
Expected: FAIL. `test_leaderboard_uses_per_example_scores` fails on `assert best.test_interval is not None`, and `test_leaderboard_examples_follow_version_override` fails on `old.rows[0].test_interval is not None`.

- [ ] **Step 3: Write the implementation**

In `src/hypothex/core/queries.py`, replace the line `from hypothex.core.config import load_project_config, parse_metric_version` with:

```python
from hypothex.core.config import (
    ProjectConfig,
    load_project_config,
    parse_metric_key,
    parse_metric_version,
)
```

Then replace everything from `def get_leaderboard(` down to, but not including, the line `    n_runs = len(` inside `_summary` with:

```python
def primary_examples(
    ctx: Context,
    config: ProjectConfig,
    task: str,
    runs: list[RunRecord],
    versions: dict[str, str] | None,
) -> dict[str, dict[str, dict[str, Any]]]:
    """
    Load the per-example scores of a task's primary metric for its leaderboard runs.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    config : ProjectConfig
        The project's config.
    task : str
        Task name.
    runs : list of RunRecord
        Candidate runs; only finished, unarchived runs of ``task`` are read.
    versions : dict of str to str or None
        Metric version overrides; default is each metric's current version.

    Returns
    -------
    dict
        run_id -> example_id -> per-example fields (without ``id``), read from
        ``predictions/scores.<metric>@<version>.jsonl``. Runs without that file
        are left out.
    """
    metric, _ = parse_metric_key(config.tasks[task].primary)
    version = (versions or {}).get(metric, config.metrics[metric].version)
    name = f"scores.{metric}@{version}.jsonl"
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for r in runs:
        if r.task != task or r.status != RunStatus.FINISHED or r.archived:
            continue
        path = ctx.run_dir(r) / "predictions" / name
        if path.is_file():
            out[r.run_id] = {
                str(row["id"]): {k: v for k, v in row.items() if k != "id"}
                for row in read_jsonl(path)
                if "id" in row
            }
    return out


def get_leaderboard(
    ctx: Context,
    ref: str,
    project: str | None = None,
    versions: dict[str, str] | None = None,
    *,
    examples: bool = True,
) -> Leaderboard:
    """
    Build the leaderboard of a task from indexed runs, scores, and per-example scores.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    ref : str
        Task name, or ``project/task``.
    project : str, optional
        Project to restrict the search to.
    versions : dict of str to str, optional
        Metric version overrides; default is each metric's current version.
    examples : bool
        Read each run's per-example scores of the primary metric
        (``predictions/scores.<metric>@<version>.jsonl``) for test-set
        intervals and paired tests. ``False`` skips the file reads.

    Returns
    -------
    Leaderboard
    """
    entry, task = resolve_task(ctx, ref, project)
    runs = ctx.index.list_runs(project=entry.project, task=task, include_archived=True, limit=None)
    scores = ctx.index.scores_for(r.run_id for r in runs)
    per_example = primary_examples(ctx, entry.config, task, runs, versions) if examples else None
    return build_leaderboard(
        entry.project, task, entry.config, runs, scores, versions, per_example=per_example
    )


def _summary(ctx: Context, entry: ProjectEntry, name: str) -> TaskSummary:
    spec = entry.config.tasks[name]
    board = get_leaderboard(ctx, name, entry.project, examples=False)
    best = board.rows[0].primary.mean if board.rows and board.rows[0].primary else None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q && uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check src/hypothex/core/queries.py`
Expected: the whole suite passes; ruff and ty clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/queries.py tests/core/test_queries.py
git commit -m "feat: leaderboard reads per-example scores for noise and paired tests"
```

## Part 4: Views module and kind presets (Tasks 15–17)

Builds `hypothex.core.views` (contract 1.4): the view models, one preset YAML per task kind,
`resolve_view`, file and inline view storage, `validate_view_text`, and `view_context` (Task 19,
placed in Part 5 because it needs `sources.iter_rows`).

Decisions this part makes inside the contract (later parts rely on them):

- `validate_view_text` returns `(None, issues)` for schema errors (bad YAML, unknown key, wrong
  type or literal) and `(view, issues)` for semantic problems (unknown metric or field, missing
  `data.source` / `text` / `spec`, duplicate titles). A view is valid only when `issues == []`.
  The editor preview can render a view that has semantic issues; Save must stay disabled.
- Metric checks are skipped when `known_metrics` is empty; field checks for a source are skipped
  when `known_fields[source]` is empty or missing. A task with no runs can still get views.
- A panel reference is a field, not a metric, when it is `step`, starts with `usage.`, `params.`,
  or `vars.`, or is a known `runs` field. Metric references are `name[@version][/key]`; only
  `name` is checked. The suggestion is the whole reference with the name corrected.
- `RunFilter` and `PanelLayout` also use `extra="forbid"` so typos like `stauts:` are reported.
  `RunFilter.status` and `.tags` accept one string (`status: finished`) or a list.
- `ViewSpec` validates by name or alias and serialises by alias, so `model_dump()` and API JSON
  use the key `from`. The `ConfigDict` keys `validate_by_name`, `validate_by_alias`, and
  `serialize_by_alias` exist only in pydantic 2.11 and later; older versions ignore them
  silently (`ViewSpec(from_=...)` fails and `model_dump()` emits `from_`). Task 15 raises the
  floor from `pydantic>=2.8` to `pydantic>=2.11`.
- `resolve_view` returns a view with `from_ = None` (resolving twice is a no-op).
- Errors: unknown view or missing view file → `StoreError` (API 404); bad name, reserved
  `overview`, unknown task, invalid stored view → `ConfigError` (API 400).
- Inline or file views named `overview` or with names outside `^[a-z0-9][a-z0-9_-]*$` are skipped
  by `list_views` and `get_view`.
- Presets ship as package data in `src/hypothex/views/presets/`. Hatch already puts every file
  under `src/hypothex` in the wheel, so the wheel section of `pyproject.toml` does not change
  (Task 15 checks the wheel). Only the pydantic floor changes.

---

### Task 15: View models and task-kind presets

**Files:**
- Create: `src/hypothex/core/views.py`
- Create: `src/hypothex/views/presets/generic.yaml`, `training.yaml`, `agent_eval.yaml`,
  `agent_iteration.yaml`, `system_bench.yaml`
- Modify: `pyproject.toml`, `uv.lock` (`pydantic>=2.11`, via `uv add`)
- Test: `tests/core/test_views.py`

**Interfaces:**
- Consumes: `hypothex.core.config.TaskKind` (contract 1.3,
  `Literal["generic", "training", "agent_eval", "agent_iteration", "system_bench"]`);
  `hypothex.core.errors.ConfigError`; `hypothex.core.records.RunStatus`.
- Produces (`hypothex.core.views`):
  - `PanelType`, `Source`, `Noise = Literal["seed", "test_set"]` type aliases.
  - `PRESET_DIR: Path` = `<package>/views/presets`.
  - `RunFilter(status: list[str] | None, tags: list[str] | None, created_by: str | None,
    since: datetime | None)`; a single string for `status`/`tags` becomes a one-item list;
    unknown statuses raise.
  - `PanelLayout(span: int = 12 (1..12), row: int | None (>= 1))`.
  - `PanelData`, `PanelSpec`, `ViewSpec` (`from_` alias `from`), `ValidationIssue`, `ViewInfo`
    exactly as contract 1.4.
  - `load_preset(kind: TaskKind) -> ViewSpec` (raises `ConfigError` for an unknown kind).
  - `resolve_view(view: ViewSpec) -> ViewSpec`.
  - Every preset has `title: overview` and titled panels. Panel titles per kind:
    generic `Summary, Leaderboard`; training `Summary, Configs, Curves, Runs, GPU, Checkpoints`;
    agent_eval `Summary, Leaderboard, Cost vs solved, Failures, Per target, Attempt`;
    agent_iteration `Summary, Solved by version, $ per solved, Changes, Flips, Leaderboard`;
    system_bench `Summary, Leaderboard, Latency, Throughput vs concurrency, Percentiles, Error rate,
    Utilisation, Repeat spread` (names match `hx demo`: samples `latency_ms`, history `sweep/rps`
    (step = concurrency), scores `latency/p50|p95|p99` and `errors/rate`, history
    `gpu_pct`/`cpu_pct`; training history `sys/gpu_util`, checkpoint metric `val/top1`).
  - `PanelSpec.render: Literal["chart", "table"] = "chart"` (contract 1.4); the system_bench
    `Percentiles` panel is a `distribution` panel with `render: table`.
  - Spec 8.4 coverage: every preset item has a panel. agent_iteration "regressions marked" is the
    `regression` flag on the rows of the ordinal `Solved by version` scatter (Task 22), and the
    system_bench percentile table's Δ and CI vs baseline are the `vs_baseline` values of the
    `Percentiles` distribution rows (Task 23), both contract 1.6.
  - Preset data conventions the panel engine must honour (contract 1.5/1.6 only): scatter `x`
    may be a `runs` field such as `usage.usd` or `params.<p>`, or `version` (the task's version
    ordering key, spec 8.4: the run param `TaskSpec.version_param` names, else the creation time
    of the group's first run; Tasks 16, 20, 22), which the agent_iteration preset uses so a task
    with `version_param: prompt_version` works unchanged; `curves` with no `metrics`
    means every logged step metric; `vega_lite` fields with dots are escaped in the spec
    (`meta\.category`) because rows are flat.

- [ ] **Step 1: Write the failing tests**

Create `tests/core/test_views.py`:

```python
from typing import get_args

import pytest
from pydantic import ValidationError

from hypothex.core.config import TaskKind
from hypothex.core.errors import ConfigError
from hypothex.core.views import (
    PRESET_DIR,
    PanelData,
    PanelLayout,
    PanelSpec,
    RunFilter,
    ViewSpec,
    load_preset,
    resolve_view,
)

PRESET_TYPES = {
    "generic": ["stat_strip", "leaderboard"],
    "training": ["stat_strip", "leaderboard", "curves", "table", "vega_lite", "curves"],
    "agent_eval": ["stat_strip", "leaderboard", "scatter", "vega_lite", "grid", "trace"],
    "agent_iteration": ["stat_strip", "scatter", "scatter", "table", "grid", "leaderboard"],
    "system_bench": [
        "stat_strip",
        "leaderboard",
        "distribution",
        "curves",
        "distribution",
        "vega_lite",
        "curves",
        "vega_lite",
    ],
}


# ---- models, presets, resolve ----


def test_every_kind_has_a_preset_with_the_spec_panels() -> None:
    assert sorted(p.stem for p in PRESET_DIR.glob("*.yaml")) == sorted(get_args(TaskKind))
    for kind in get_args(TaskKind):
        view = load_preset(kind)
        assert view.title == "overview"
        assert view.from_ is None
        assert [p.type for p in view.panels] == PRESET_TYPES[kind]
        assert all(p.title for p in view.panels)
        assert all(1 <= p.layout.span <= 12 for p in view.panels)


def test_preset_details_match_spec() -> None:
    agent = {p.title: p for p in load_preset("agent_eval").panels}
    assert agent["Cost vs solved"].data.x == "usage.usd"
    assert agent["Cost vs solved"].pareto == {"x": "min", "y": "max"}
    assert agent["Failures"].data.source == "predictions"
    bench = {p.title: p for p in load_preset("system_bench").panels}
    assert bench["Latency"].scale == "log"
    assert bench["Latency"].data.source == "samples"
    assert bench["Latency"].data.metrics == ["latency_ms"]
    assert bench["Throughput vs concurrency"].data.metrics == ["sweep/rps"]
    assert bench["Utilisation"].data.metrics == ["gpu_pct", "cpu_pct"]
    training = {p.title: p for p in load_preset("training").panels}
    assert training["Curves"].data.step_metric == "step"
    assert training["Runs"].data.source == "runs"


def test_presets_cover_the_spec_items() -> None:
    # spec 8.4 items beyond the basics: GPU sparklines and checkpoints (training),
    # cost per success (agent_iteration), percentile table and repeat spread (system_bench)
    training = {p.title: p for p in load_preset("training").panels}
    gpu = training["GPU"]
    assert (gpu.data.source, gpu.data.filter) == ("metrics", {"name": "sys/gpu_util"})
    assert gpu.spec is not None and gpu.spec["encoding"]["row"]["field"] == "run_id"
    assert (training["Runs"].layout.row, gpu.layout.row) == (4, 4)  # sparklines beside the table
    assert training["Checkpoints"].type == "curves"
    assert training["Checkpoints"].data.metrics == ["val/top1"]
    assert training["Checkpoints"].data.group_by == "run"
    iteration = {p.title: p for p in load_preset("agent_iteration").panels}
    assert "Cost by version" not in iteration
    cost = iteration["$ per solved"]
    assert (cost.data.x, cost.data.y) == ("version", "usage.usd/solved")
    assert iteration["Changes"].data.fields == ["group_id", "version", "created_by", "created_at"]
    bench = {p.title: p for p in load_preset("system_bench").panels}
    percentiles = bench["Percentiles"]
    assert (percentiles.type, percentiles.render) == ("distribution", "table")
    assert percentiles.data.metrics == ["latency_ms"]
    assert bench["Latency"].render == "chart"
    solved = iteration["Solved by version"]
    assert (solved.type, solved.data.x) == ("scatter", "version")  # ordinal: regressions
    spread = bench["Repeat spread"]
    assert spread.data.filter == {"metric": "latency", "key": "p95"}
    assert spread.spec is not None
    assert {"calculate": "datum.vs_median > 0.1", "as": "flagged"} in spread.spec["transform"]


def test_load_preset_rejects_unknown_kind() -> None:
    with pytest.raises(ConfigError, match="no preset view for kind 'nope'"):
        load_preset("nope")  # ty: ignore[invalid-argument-type]


def test_view_spec_reads_and_writes_from_alias() -> None:
    view = ViewSpec.model_validate({"title": "mine", "from": "training"})
    assert view.from_ == "training"
    assert view.model_dump()["from"] == "training"
    assert ViewSpec(title="x", from_="generic").from_ == "generic"


def test_model_defaults_and_limits() -> None:
    panel = PanelSpec(type="leaderboard")
    assert panel.noise == ["seed", "test_set"]
    assert panel.layout == PanelLayout(span=12, row=None)
    assert panel.data == PanelData()
    assert panel.scale == "linear"
    assert panel.render == "chart"
    with pytest.raises(ValidationError):
        PanelSpec(type="distribution", render="pie")  # ty: ignore[invalid-argument-type]
    with pytest.raises(ValidationError):
        PanelLayout(span=13)
    with pytest.raises(ValidationError):
        PanelData.model_validate({"metrcs": ["acc"]})
    with pytest.raises(ValidationError):
        RunFilter.model_validate({"stauts": "finished"})


def test_run_filter_accepts_one_status_and_rejects_unknown() -> None:
    assert RunFilter.model_validate({"status": "finished"}).status == ["finished"]
    assert RunFilter.model_validate({"tags": "baseline"}).tags == ["baseline"]
    with pytest.raises(ValidationError, match="unknown status done"):
        RunFilter.model_validate({"status": ["finished", "done"]})


def test_resolve_view_replaces_same_title_and_appends_new() -> None:
    view = ViewSpec(
        title="mine",
        from_="generic",
        runs=RunFilter(status=["finished"]),
        panels=[
            PanelSpec(type="markdown", title="Note", text="hi"),
            PanelSpec(type="leaderboard", title="Leaderboard", noise=["seed"]),
        ],
    )
    resolved = resolve_view(view)
    assert [p.title for p in resolved.panels] == ["Summary", "Leaderboard", "Note"]
    assert resolved.panels[1].noise == ["seed"]
    assert resolved.title == "mine"
    assert resolved.from_ is None
    assert resolved.runs.status == ["finished"]
    assert resolve_view(resolved) == resolved


def test_resolve_view_without_from_is_unchanged() -> None:
    view = ViewSpec(title="plain", panels=[PanelSpec(type="markdown", title="a", text="x")])
    assert resolve_view(view) is view


def test_resolve_view_appends_untitled_panels() -> None:
    view = ViewSpec(title="m", from_="generic", panels=[PanelSpec(type="markdown", text="x")])
    assert [p.type for p in resolve_view(view).panels] == ["stat_strip", "leaderboard", "markdown"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/core/test_views.py -q`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'hypothex.core.views'`.

- [ ] **Step 3: Write the five preset files**

These follow spec 8.4 and the approved mockups in `docs/mockups/kinds/*/index.html` (panel
letters a, b, c … map to the panel order). Every spec 8.4 item has a panel built from the
contract's panel types and sources: agent_iteration "regressions marked" comes from the scatter
rows' `regression` flag on the ordinal version axis, and the system_bench percentile table is a
`distribution` panel with `render: table` whose rows carry Δ and 95% CI vs the task's baseline.
Task-level checkpoints are a `curves` panel: `meta.checkpoints` lists every run's checkpoints
with each run's best marked.

`src/hypothex/views/presets/generic.yaml`:

```yaml
# Preset view for task kind "generic" (spec 8.4): stat strip and leaderboard.
title: overview
panels:
  - type: stat_strip
    title: Summary
    layout: {span: 12, row: 1}
  - type: leaderboard
    title: Leaderboard
    noise: [seed, test_set]
    layout: {span: 12, row: 2}
```

`src/hypothex/views/presets/training.yaml`:

```yaml
# Preset view for task kind "training" (spec 8.4, mockup docs/mockups/kinds/training).
# Curves with no metrics list show every logged step metric as small multiples.
title: overview
panels:
  - type: stat_strip
    title: Summary
    layout: {span: 12, row: 1}
  - type: leaderboard
    title: Configs
    noise: [seed, test_set]
    layout: {span: 12, row: 2}
  - type: curves
    title: Curves
    data: {group_by: group, step_metric: step}
    layout: {span: 12, row: 3}
  - type: table
    title: Runs
    data:
      source: runs
      fields: [run_id, group_id, seed, status, created_by, usage.seconds]
    layout: {span: 8, row: 4}
  # GPU sparklines beside the runs table: one small line per run of the history metric
  # sys/gpu_util (the name `hx demo` writes; rename it to match your task).
  - type: vega_lite
    title: GPU
    data:
      source: metrics
      filter: {name: sys/gpu_util}
      fields: [name, step, value]
    spec:
      height: 18
      mark: {type: line, strokeWidth: 1}
      encoding:
        row: {field: run_id, type: nominal, title: null, header: {labelAngle: 0, labelAlign: left}}
        x: {field: step, type: quantitative, title: null, axis: null}
        y: {field: value, type: quantitative, title: null, axis: null, scale: {domain: [0, 100]}}
    layout: {span: 4, row: 4}
  # Task-level checkpoints: val/top1 per run; meta.checkpoints marks every checkpoint and
  # each run's best (curves panel, contract 1.6).
  - type: curves
    title: Checkpoints
    data: {metrics: [val/top1], group_by: run, step_metric: step}
    layout: {span: 12, row: 5}
```

`src/hypothex/views/presets/agent_eval.yaml`:

```yaml
# Preset view for task kind "agent_eval" (spec 8.4, mockup docs/mockups/kinds/agent_eval).
# Failure categories come from the per-example prediction field meta.category.
title: overview
panels:
  - type: stat_strip
    title: Summary
    layout: {span: 12, row: 1}
  - type: leaderboard
    title: Leaderboard
    noise: [seed, test_set]
    layout: {span: 12, row: 2}
  - type: scatter
    title: Cost vs solved
    data: {x: usage.usd, group_by: group}
    pareto: {x: min, y: max}
    layout: {span: 7, row: 3}
  - type: vega_lite
    title: Failures
    data:
      source: predictions
      fields: [group_id, meta.category]
    spec:
      transform:
        - filter: "isValid(datum['meta.category'])"
      mark: bar
      encoding:
        y: {field: group_id, type: nominal, title: null}
        x: {aggregate: count, type: quantitative, title: failed}
        color: {field: meta\.category, type: nominal, title: null}
    layout: {span: 5, row: 3}
  - type: grid
    title: Per target
    data: {group_by: group}
    layout: {span: 12, row: 4}
  - type: trace
    title: Attempt
    layout: {span: 12, row: 5}
```

`src/hypothex/views/presets/agent_iteration.yaml`:

```yaml
# Preset view for task kind "agent_iteration" (spec 8.4, mockup docs/mockups/kinds/agent_iteration).
# `version` is the task's version ordering key: the run param TaskSpec.version_param names
# ("version" by default, e.g. prompt_version), or, for a group whose runs lack that param, the
# creation time of the group's first run (spec 8.4). So this view works for any version_param.
# "$ per solved" is each run's usage.usd divided by the examples it solved on the primary
# metric (usage.<field>/solved), averaged over seeds. Both scatters have an ordinal x (version
# text), so each row carries `regression`: worse than the best earlier version by more than
# that version's 95% CI (spec 8.4 "regressions marked"; the UI draws it in the failure colour).
title: overview
panels:
  - type: stat_strip
    title: Summary
    layout: {span: 12, row: 1}
  - type: scatter
    title: Solved by version
    data: {x: version, group_by: group}
    layout: {span: 12, row: 2}
  - type: scatter
    title: $ per solved
    data: {x: version, y: usage.usd/solved, group_by: group}
    layout: {span: 6, row: 3}
  - type: table
    title: Changes
    data:
      source: runs
      fields: [group_id, version, created_by, created_at]
    layout: {span: 6, row: 3}
  - type: grid
    title: Flips
    data: {group_by: group}
    layout: {span: 12, row: 4}
  - type: leaderboard
    title: Leaderboard
    noise: [seed, test_set]
    layout: {span: 12, row: 5}
```

`src/hypothex/views/presets/system_bench.yaml`:

```yaml
# Preset view for task kind "system_bench" (spec 8.4, mockup docs/mockups/kinds/system_bench).
# Latency comes from raw samples named latency_ms (run.log_samples). The throughput sweep is the
# history metric sweep/rps logged with step = concurrency; the error rate is the score
# errors/rate; utilisation is the history metrics gpu_pct and cpu_pct; the repeat spread reads
# the score latency/p95. These are the names `hx demo` writes; copy this view and rename them
# to match your task. The percentile table is the latency_ms distribution drawn as a table
# (render: table): pooled p50/p95/p99 per group, with the change vs the task's baseline group
# (TaskSpec.baseline, e.g. tag:baseline) and a 95% bootstrap CI over repeats.
title: overview
panels:
  - type: stat_strip
    title: Summary
    layout: {span: 12, row: 1}
  - type: leaderboard
    title: Leaderboard
    noise: [seed, test_set]
    layout: {span: 12, row: 2}
  - type: distribution
    title: Latency
    data: {source: samples, metrics: [latency_ms], group_by: group}
    scale: log
    layout: {span: 7, row: 3}
  - type: curves
    title: Throughput vs concurrency
    data: {metrics: [sweep/rps], group_by: group}
    layout: {span: 5, row: 3}
  # Percentile table: one row per group, p50/p95/p99 columns, each with Δ and 95% CI vs the
  # baseline group (distribution rows' vs_baseline; the baseline row shows "ref").
  - type: distribution
    title: Percentiles
    data: {source: samples, metrics: [latency_ms], group_by: group}
    render: table
    layout: {span: 6, row: 4}
  - type: vega_lite
    title: Error rate
    data:
      source: scores
      fields: [group_id, metric, key, value]
    spec:
      transform:
        - filter: "datum.metric == 'errors' && datum.key == 'rate'"
      mark: bar
      encoding:
        y: {field: group_id, type: nominal, title: null}
        x: {aggregate: mean, field: value, type: quantitative, title: error rate}
    layout: {span: 6, row: 4}
  - type: curves
    title: Utilisation
    data: {metrics: [gpu_pct, cpu_pct], group_by: run}
    layout: {span: 8, row: 5}
  # Repeat spread: each repeat's p95 vs the median repeat of its group; over +10% is flagged
  # (the mockup's outlier rule, e.g. a noisy neighbour).
  - type: vega_lite
    title: Repeat spread
    data:
      source: scores
      filter: {metric: latency, key: p95}
      fields: [metric, key, value]
    spec:
      transform:
        - joinaggregate: [{op: median, field: value, as: median}]
          groupby: [group_id]
        - calculate: "datum.value / datum.median - 1"
          as: vs_median
        - calculate: "datum.vs_median > 0.1"
          as: flagged
      mark: {type: point, filled: true}
      encoding:
        y: {field: group_id, type: nominal, title: null}
        x: {field: vs_median, type: quantitative, title: p95 vs median repeat, axis: {format: "+%"}}
        color: {field: flagged, type: nominal, title: "over +10%"}
        tooltip:
          - {field: run_id, type: nominal}
          - {field: seed, type: quantitative, title: repeat}
          - {field: value, type: quantitative, title: p95 ms, format: ".1f"}
    layout: {span: 4, row: 5}
```

- [ ] **Step 4: Raise the pydantic floor, then write the models, `load_preset`, and `resolve_view`**

`ViewSpec` uses the `ConfigDict` keys `validate_by_name`, `validate_by_alias`, and
`serialize_by_alias`. Pydantic added them in 2.11; 2.8 to 2.10 ignore them without an error, so
`ViewSpec(title="x", from_="generic")` fails and `model_dump()` emits `from_` instead of `from`.
`test_view_spec_reads_and_writes_from_alias` pins both behaviours. Raise the floor first:

Run: `uv add 'pydantic>=2.11' && grep -n '"pydantic' pyproject.toml`
Expected: one line, `"pydantic>=2.11",` (it was `"pydantic>=2.8",`), and `uv.lock` updated.

Create `src/hypothex/core/views.py`:

```python
"""Views: YAML dashboards of panels, the preset view of each task kind, and validation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal, get_args

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from hypothex.core.config import TaskKind
from hypothex.core.errors import ConfigError
from hypothex.core.records import RunStatus

PanelType = Literal[
    "stat_strip",
    "leaderboard",
    "curves",
    "scatter",
    "distribution",
    "grid",
    "table",
    "trace",
    "markdown",
    "vega_lite",
]
Source = Literal["runs", "scores", "metrics", "predictions", "samples", "usage", "traces"]
Noise = Literal["seed", "test_set"]

PRESET_DIR = Path(__file__).resolve().parent.parent / "views" / "presets"


class RunFilter(BaseModel):
    """
    Which runs a view shows; ``None`` means no filter on that field.

    ``status`` and ``tags`` accept one string or a list of strings.

    Examples
    --------
    >>> RunFilter.model_validate({"status": "finished"}).status
    ['finished']
    """

    model_config = ConfigDict(extra="forbid")

    status: list[str] | None = None
    tags: list[str] | None = None
    created_by: str | None = None
    since: datetime | None = None

    @field_validator("status", "tags", mode="before")
    @classmethod
    def _one_or_many(cls, value: Any) -> Any:
        """Wrap a single string into a one-item list."""
        return [value] if isinstance(value, str) else value

    @field_validator("status")
    @classmethod
    def _known_status(cls, value: list[str] | None) -> list[str] | None:
        """Reject statuses that are not a ``RunStatus`` value."""
        allowed = [s.value for s in RunStatus]
        for item in value or []:
            if item not in allowed:
                raise ValueError(f"unknown status {item}; expected one of {', '.join(allowed)}")
        return value


class PanelLayout(BaseModel):
    """Where a panel sits on the 12-column grid."""

    model_config = ConfigDict(extra="forbid")

    span: int = Field(12, ge=1, le=12)
    row: int | None = Field(None, ge=1)


class PanelData(BaseModel):
    """What a panel reads; which keys matter depends on the panel type."""

    model_config = ConfigDict(extra="forbid")

    metrics: list[str] | None = None
    x: str | None = None
    y: str | None = None
    group_by: Literal["group", "config", "run", "seed"] | None = None
    filter: dict[str, Any] | None = None
    pick: Literal["best", "latest", "all"] | None = None
    source: Source | None = None
    fields: list[str] | None = None
    run_id: str | None = None
    example_id: str | None = None
    step_metric: str | None = None


def _default_noise() -> list[Noise]:
    """Return the default leaderboard noise kinds: both seed and test-set noise."""
    return ["seed", "test_set"]


class PanelSpec(BaseModel):
    """One panel of a view."""

    model_config = ConfigDict(extra="forbid")

    type: PanelType
    title: str = ""
    data: PanelData = Field(default_factory=PanelData)
    layout: PanelLayout = Field(default_factory=PanelLayout)
    noise: list[Noise] = Field(default_factory=_default_noise)
    pareto: dict[str, Literal["min", "max"]] | None = None
    spec: dict[str, Any] | None = None
    text: str | None = None
    scale: Literal["linear", "log"] = "linear"
    render: Literal["chart", "table"] = "chart"


class ViewSpec(BaseModel):
    """
    A view: a title, an optional preset to start from, a run filter, and panels.

    The YAML key ``from`` maps to the attribute ``from_``.

    Examples
    --------
    >>> ViewSpec.model_validate({"title": "mine", "from": "training"}).from_
    'training'
    """

    model_config = ConfigDict(
        extra="forbid", validate_by_name=True, validate_by_alias=True, serialize_by_alias=True
    )

    title: str
    from_: TaskKind | None = Field(None, alias="from")
    runs: RunFilter = Field(default_factory=RunFilter)
    panels: list[PanelSpec] = Field(default_factory=list)


class ValidationIssue(BaseModel):
    """One problem in a view's YAML, with its 1-based line when known."""

    line: int | None
    path: str
    message: str
    suggestion: str | None = None


class ViewInfo(BaseModel):
    """A view as listed for a task."""

    name: str
    title: str
    origin: Literal["preset", "inline", "file"]
    path: str | None
    kind: TaskKind | None


def load_preset(kind: TaskKind) -> ViewSpec:
    """
    Load the preset view that ships with the package for a task kind.

    Parameters
    ----------
    kind : TaskKind
        Task kind, e.g. ``"training"``.

    Returns
    -------
    ViewSpec
        The preset view (it has no ``from``).

    Raises
    ------
    ConfigError
        If ``kind`` is not a task kind.

    Examples
    --------
    >>> [p.type for p in load_preset("generic").panels]
    ['stat_strip', 'leaderboard']
    """
    if kind not in get_args(TaskKind):
        raise ConfigError(f"no preset view for kind {kind!r}")
    text = (PRESET_DIR / f"{kind}.yaml").read_text(encoding="utf-8")
    return ViewSpec.model_validate(yaml.safe_load(text))


def resolve_view(view: ViewSpec) -> ViewSpec:
    """
    Apply ``from``: start from the preset panels, then merge the view's panels.

    A view panel whose non-empty title equals a preset panel's title replaces that
    panel in place; every other view panel is appended in order. The view's run
    filter wins unless it is empty, then the preset's is used. The result has no
    ``from``, so resolving twice gives the same view.

    Parameters
    ----------
    view : ViewSpec
        View as written.

    Returns
    -------
    ViewSpec
        The expanded view.

    Examples
    --------
    >>> note = PanelSpec(type="markdown", title="Note", text="hi")
    >>> [p.title for p in resolve_view(ViewSpec(title="m", from_="generic", panels=[note])).panels]
    ['Summary', 'Leaderboard', 'Note']
    """
    if view.from_ is None:
        return view
    base = load_preset(view.from_)
    panels = list(base.panels)
    position = {p.title: i for i, p in enumerate(panels) if p.title}
    for panel in view.panels:
        if panel.title and panel.title in position:
            panels[position[panel.title]] = panel
        else:
            panels.append(panel)
    runs = view.runs if view.runs != RunFilter() else base.runs
    return view.model_copy(update={"from_": None, "runs": runs, "panels": panels})
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/core/test_views.py -q`
Expected: `10 passed`.

Run: `uv run ruff format --check src/hypothex/core/views.py tests/core/test_views.py && uv run ruff check src/hypothex/core/views.py tests/core/test_views.py && uv run ty check src/hypothex/core/views.py tests/core/test_views.py`
Expected: `2 files already formatted`, `All checks passed!`, `All checks passed!`.

- [ ] **Step 6: Check the presets ship in the wheel**

Run: `uv build --wheel -o /tmp/hx-wheel && unzip -l /tmp/hx-wheel/hypothex-*.whl | grep views/presets`
Expected: five lines, `hypothex/views/presets/agent_eval.yaml`, `agent_iteration.yaml`,
`generic.yaml`, `system_bench.yaml`, `training.yaml`. No wheel change in `pyproject.toml` is needed
(hatch includes every non-ignored file under `src/hypothex`). If the list is empty, add to
`pyproject.toml` under `[tool.hatch.build.targets.wheel]`: `artifacts = ["src/hypothex/views/presets/*.yaml"]`
and rerun.

- [ ] **Step 7: Commit**

```bash
git add src/hypothex/core/views.py src/hypothex/views/presets tests/core/test_views.py pyproject.toml uv.lock
git commit -m "feat: add view models and task-kind preset views"
```

---

### Task 16: Validate view YAML with line numbers and suggestions

**Files:**
- Modify: `src/hypothex/core/views.py` (import block, constants after `PRESET_DIR`, append functions)
- Test: `tests/core/test_views.py` (import block, append tests)

**Interfaces:**
- Consumes: Task 15 models, `load_preset`, `PRESET_DIR`; `config.scan_yaml`, `config.has_cycle`, `config.YAML_CYCLE` (Task 5).
- Produces:
  - `validate_view_text(text: str, known_metrics: set[str], known_fields: dict[str, set[str]]) -> tuple[ViewSpec | None, list[ValidationIssue]]`.
  - Constants `ROW_KEYS = frozenset({"run_id", "group_id", "seed"})` (always valid fields),
    `FIELD_PREFIXES = ("usage.", "params.", "vars.")`, `VEGA_ROOT_KEYS`,
    `VERSION_REF = "version"` (the task's version ordering key, spec 8.4: a valid scatter
    `data.x` and a valid `runs` table field; the panel engine resolves it, Tasks 20 and 22),
    `VEGA_BLOCKED_KEYS = frozenset({"url", "href", "embedOptions"})`.
  - `vega_spec_problems(spec: Any, at: tuple[str | int, ...] = ()) -> list[tuple[tuple[str | int, ...], str]]`
    (public; the panel engine calls it too, Task 20): every `url`, `href`, or `embedOptions` key
    at any depth (inline data only: no data URLs, lookup sources, image URLs, links, or embed
    options that could swap the loader) and every `image` mark. The walk is bounded
    (`VEGA_MAX_DEPTH = 64` nested mappings/lists, `VEGA_MAX_NODES = 10_000` values): past a
    bound it returns only `[(at, "vega_lite spec is too deep (over 64 levels)")]` or
    `[(at, "vega_lite spec is too large (over 10000 values)")]`, so a spec that reaches the
    panel engine without YAML (a JSON query body, a self-referencing dict) is a panel error,
    never a `RecursionError`.
  - `validate_view_text` runs the Task 5 guards first: `config.scan_yaml(text)` before
    `yaml.compose` (its `problem`, e.g. `YAML nested too deeply (over 64 levels)` for 600
    nested lists, and then `YAML anchors and aliases are not allowed` for its
    `first_anchor`, each `(None, [issue])` with the 1-based line and path `""`), then
    `config.has_cycle` on the loaded value (`YAML aliases must not form a cycle`). A
    self-referencing view (`spec: &s {mark: point, layer: [*s]}`) or a deep one never
    reaches the composer, the models, or `vega_spec_problems`.
  - Metric references: a reference that is exactly a known metric name (history names keep
    their `/`, e.g. `val/top1`) is valid before it is split into `name[@version][/key]`.
    A `grid` panel's `data.y` is a per-example field (`partial` in
    `accuracy@v1.partial`), checked against the `predictions` fields, not the metrics.
  - Issue messages (exact, used by the UI and CLI): `unknown key <k>`, `unknown <field> <value>`
    (plus `; expected one of a, b` when no near match), `missing <field>`,
    `unknown metric <name>`, `unknown field <f> in <source>`,
    `unknown per-example field <f>`, `<type> needs data.source`,
    `scatter needs data.x`, `markdown needs text`,
    `vega_lite spec needs mark, layer, or a composition`,
    `vega_lite spec must not load external resources (<key>)`,
    `vega_lite image marks are not allowed`, `pareto keys are x and y`,
    `duplicate panel title <t>`, `a view is a mapping with title and panels`, `YAML: <problem>`,
    `YAML anchors and aliases are not allowed`, `YAML nested too deeply (over 64 levels)`,
    `YAML too large (over 100000 events)`, `YAML aliases must not form a cycle`,
    `vega_lite spec is too deep (over 64 levels)`, `vega_lite spec is too large (over 10000 values)`.
  - `ValidationIssue.path` looks like `panels[1].data.y`; `line` is 1-based, from the key's
    `yaml.compose` mark (or the nearest existing parent when the key is missing).

- [ ] **Step 1: Write the failing tests**

In `tests/core/test_views.py`, replace the import block (from the first line through the closing
`)` of `from hypothex.core.views import (`) with:

```python
import json
from typing import get_args

import pytest
from pydantic import ValidationError

from hypothex.core.config import TaskKind
from hypothex.core.errors import ConfigError
from hypothex.core.views import (
    PRESET_DIR,
    PanelData,
    PanelLayout,
    PanelSpec,
    RunFilter,
    ViewSpec,
    load_preset,
    resolve_view,
    validate_view_text,
)
```

Append to the end of `tests/core/test_views.py`:

```python
# ---- validate_view_text ----

KNOWN_METRICS = {"solved", "route_len", "solve_time", "tokens"}
KNOWN_FIELDS = {
    "predictions": {"id", "prediction", "reference", "meta.category", "solved@v2.solved"},
    "runs": {"status", "created_by", "params.depth", "usage.usd"},
}

# The route-quality view from docs/mockups/kinds/custom_view/data.js, minus its
# made-up "config" field. Line numbers below refer to this text.
ROUTE_QUALITY = """\
title: route quality
runs: {status: finished}
panels:
  - type: stat_strip
    title: Best config
    data:
      metrics:
        - solved@v2
        - route_len@v1/median
      pick: best
    layout: {span: 12, row: 1}
  - type: scatter
    title: Length vs time
    data:
      x: solve_time@v1/median
      y: route_len@v1/median
      group_by: config
    pareto: {x: min, y: min}
    layout: {span: 5, row: 2}
  - type: vega_lite
    title: Solved by depth
    data:
      source: predictions
      fields: [group_id, solved@v2.solved]
    spec:
      mark: rect
      encoding:
        x: {field: group_id}
    layout: {span: 8, row: 3}
  - type: markdown
    title: Note
    text: Critic gain is largest on 5+ step targets.
    layout: {span: 4, row: 3}
"""


def _check(text: str) -> tuple[ViewSpec | None, list[tuple[int | None, str, str, str | None]]]:
    view, issues = validate_view_text(text, KNOWN_METRICS, KNOWN_FIELDS)
    return view, [(i.line, i.path, i.message, i.suggestion) for i in issues]


def test_valid_view_has_no_issues() -> None:
    view, issues = _check(ROUTE_QUALITY)
    assert issues == []
    assert view is not None
    assert view.runs.status == ["finished"]
    assert [p.type for p in view.panels] == ["stat_strip", "scatter", "vega_lite", "markdown"]


def test_unknown_metric_names_line_and_suggests_nearest() -> None:
    text = ROUTE_QUALITY.replace("y: route_len@v1/median", "y: route_length@v1/median")
    view, issues = _check(text)
    assert view is not None
    assert issues == [
        (16, "panels[1].data.y", "unknown metric route_length", "route_len@v1/median")
    ]


def test_unknown_metric_in_list_and_without_near_match() -> None:
    text = ROUTE_QUALITY.replace("- solved@v2", "- zzz@v2")
    _, issues = _check(text)
    assert issues == [(8, "panels[0].data.metrics[0]", "unknown metric zzz", None)]


def test_field_refs_and_step_are_not_metrics() -> None:
    text = """\
title: t
panels:
  - type: scatter
    data: {x: usage.usd, y: params.depth}
  - type: curves
    data: {x: step, step_metric: step}
"""
    assert _check(text)[1] == []


def test_metric_checks_skip_when_nothing_is_known() -> None:
    text = "title: t\npanels:\n  - type: leaderboard\n    data: {y: anything@v9/p95}\n"
    view, issues = validate_view_text(text, set(), {})
    assert view is not None
    assert issues == []


def test_yaml_syntax_error_has_line() -> None:
    view, issues = _check("title: t\npanels:\n  - type: [leaderboard\n")
    assert view is None
    assert len(issues) == 1
    assert issues[0][0] == 4
    assert issues[0][2].startswith("YAML: ")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", (1, "", "a view is a mapping with title and panels", None)),
        ("- a\n- b\n", (1, "", "a view is a mapping with title and panels", None)),
        ("panels: []\n", (1, "title", "missing title", None)),
        (
            "title: t\npanels:\n  - type: leaderbord\n",
            (3, "panels[0].type", "unknown type leaderbord", "leaderboard"),
        ),
        (
            "title: t\npanels:\n  - type: leaderboard\n    data:\n      metrcs: [solved]\n",
            (5, "panels[0].data.metrcs", "unknown key metrcs", "metrics"),
        ),
        (
            "title: t\nruns: {stauts: finished}\n",
            (2, "runs.stauts", "unknown key stauts", "status"),
        ),
        (
            "title: t\nfrom: trainng\n",
            (2, "from", "unknown from trainng", "training"),
        ),
        (
            "title: t\npanels:\n  - type: grid\n    layout: {span: 20}\n",
            (
                4,
                "panels[0].layout.span",
                "span: Input should be less than or equal to 12",
                None,
            ),
        ),
        (
            "title: t\nruns: {status: done}\n",
            (
                2,
                "runs.status",
                "status: unknown status done; expected one of queued, running, finished, "
                "failed, killed, lost",
                None,
            ),
        ),
        ("title: t\npanels:\n  - title: no type\n", (3, "panels[0].type", "missing type", None)),
    ],
)
def test_schema_errors_have_line_path_and_suggestion(
    text: str, expected: tuple[int | None, str, str, str | None]
) -> None:
    view, issues = _check(text)
    assert view is None
    assert issues == [expected]


def test_literal_without_near_match_lists_choices() -> None:
    _, issues = _check("title: t\npanels:\n  - type: leaderboard\n    scale: zzz\n")
    assert issues == [
        (4, "panels[0].scale", "unknown scale zzz; expected one of linear, log", None)
    ]


@pytest.mark.parametrize(
    ("panel", "expected"),
    [
        ("  - type: table\n", (3, "panels[0].data", "table needs data.source", None)),
        (
            "  - type: table\n    data: {source: runs, fields: [stauts]}\n",
            (4, "panels[0].data.fields[0]", "unknown field stauts in runs", "status"),
        ),
        ("  - type: markdown\n", (3, "panels[0].text", "markdown needs text", None)),
        (
            "  - type: vega_lite\n    data: {source: runs}\n    spec: {encoding: {}}\n",
            (5, "panels[0].spec", "vega_lite spec needs mark, layer, or a composition", None),
        ),
        ("  - type: scatter\n", (3, "panels[0].data", "scatter needs data.x", None)),
        (
            "  - type: scatter\n    data: {x: usage.usd}\n    pareto: {z: min}\n",
            (5, "panels[0].pareto", "pareto keys are x and y", None),
        ),
    ],
)
def test_panel_requirements(panel: str, expected: tuple[int, str, str, str | None]) -> None:
    view, issues = _check("title: t\npanels:\n" + panel)
    assert view is not None
    assert issues == [expected]


def test_fields_accept_row_keys_and_skip_unknown_sources() -> None:
    text = """\
title: t
panels:
  - type: table
    data: {source: runs, fields: [run_id, group_id, seed, usage.usd]}
  - type: table
    data: {source: traces, fields: [anything]}
"""
    assert _check(text)[1] == []


def test_duplicate_panel_titles() -> None:
    text = """\
title: t
panels:
  - type: leaderboard
    title: A
  - type: grid
    title: A
"""
    assert _check(text)[1] == [(6, "panels[1].title", "duplicate panel title A", None)]


def test_every_preset_file_validates_clean() -> None:
    for kind in get_args(TaskKind):
        text = (PRESET_DIR / f"{kind}.yaml").read_text(encoding="utf-8")
        view, issues = validate_view_text(text, set(), {})
        assert issues == [], kind
        assert view == load_preset(kind)


def test_issues_serialise_for_the_api() -> None:
    _, issues = validate_view_text("title: t\npanels:\n  - type: pie\n", set(), {})
    dumped = json.loads(issues[0].model_dump_json())
    assert dumped["line"] == 3
    assert dumped["path"] == "panels[0].type"
    assert dumped["message"].startswith("unknown type pie; expected one of stat_strip")
    assert dumped["suggestion"] is None


def test_known_metric_names_with_slashes_are_not_split() -> None:
    # history metrics keep their "/" (records.MetricPoint.name): val/top1 is not metric "val"
    metrics = {"accuracy", "val/top1", "sys/gpu_util"}
    fields = {"runs": {"status", "created_by"}}
    text = """\
title: t
panels:
  - type: curves
    data: {metrics: [val/top1, sys/gpu_util], y: val/top1}
  - type: scatter
    data: {x: version, y: val/top1}
  - type: table
    data: {source: runs, fields: [group_id, version, status]}
"""
    view, issues = validate_view_text(text, metrics, fields)
    assert view is not None and issues == []
    typo = text.replace("y: val/top1}", "y: val/topp1}", 1)  # the curves panel's y
    _, issues = validate_view_text(typo, metrics, fields)
    assert [(i.line, i.path, i.message, i.suggestion) for i in issues] == [
        (4, "panels[0].data.y", "unknown metric val/topp1", "val/top1")
    ]


def test_grid_y_is_a_per_example_field() -> None:
    fields = {"predictions": {"id", "accuracy@v1.correct", "accuracy@v1.partial", "meta.category"}}
    text = "title: t\npanels:\n  - type: grid\n    data: {metrics: [accuracy@v1], y: partial}\n"
    assert validate_view_text(text, {"accuracy"}, fields)[1] == []
    typo = text.replace("partial", "partal")
    _, issues = validate_view_text(typo, {"accuracy"}, fields)
    assert [(i.line, i.path, i.message, i.suggestion) for i in issues] == [
        (4, "panels[0].data.y", "unknown per-example field partal", "partial")
    ]
    assert validate_view_text(typo, {"accuracy"}, {})[1] == []  # nothing known: skipped


def test_vega_lite_external_resources_are_rejected_at_any_depth() -> None:
    text = """\
title: t
panels:
  - type: vega_lite
    data: {source: runs}
    spec:
      layer:
        - mark: point
          data: {url: "https://example.com/x.json"}
        - mark: {type: image}
          encoding:
            url: {field: run_id}
            href: {field: run_id}
      transform:
        - lookup: run_id
          from: {data: {url: data/other.csv}, key: run_id, fields: [x]}
      usermeta: {embedOptions: {loader: {baseURL: "https://example.com/"}}}
"""
    view, issues = validate_view_text(text, set(), {})
    assert view is not None  # a semantic problem: the preview may render, Save may not
    external = "vega_lite spec must not load external resources"
    assert [(i.line, i.path, i.message) for i in issues] == [
        (8, "panels[0].spec.layer[0].data.url", f"{external} (url)"),
        (9, "panels[0].spec.layer[1].mark", "vega_lite image marks are not allowed"),
        (11, "panels[0].spec.layer[1].encoding.url", f"{external} (url)"),
        (12, "panels[0].spec.layer[1].encoding.href", f"{external} (href)"),
        (15, "panels[0].spec.transform[0].from.data.url", f"{external} (url)"),
        (16, "panels[0].spec.usermeta.embedOptions", f"{external} (embedOptions)"),
    ]


NO_ANCHORS = "YAML anchors and aliases are not allowed"
# regression: the spec refers to itself; loading it used to raise RecursionError
RECURSIVE_VIEW = """\
title: t
panels:
  - type: vega_lite
    data: {source: runs}
    spec: &s {mark: point, layer: [*s]}
"""


def test_yaml_anchors_and_aliases_are_rejected_with_their_line() -> None:
    assert _check(RECURSIVE_VIEW) == (None, [(5, "", NO_ANCHORS, None)])
    shared = """\
title: t
panels:
  - type: markdown
    title: A
    text: &note shared text
  - type: markdown
    title: B
    text: *note
"""
    assert _check(shared) == (None, [(5, "", NO_ANCHORS, None)])
    merge = "title: t\npanels:\n  - type: grid\n    layout:\n      <<: *wide\n"
    assert _check(merge) == (None, [(5, "", NO_ANCHORS, None)])  # alias with no anchor


def _vega_view(spec: str) -> str:
    return (
        "title: t\npanels:\n  - type: vega_lite\n    data: {source: runs}\n"
        f"    spec: {{mark: point, extra: {spec}}}\n"
    )


def test_deep_or_huge_yaml_is_rejected_before_it_is_loaded() -> None:
    # regression: 600 nested lists (no alias) raised RecursionError inside yaml.compose
    deep = (None, [(5, "", "YAML nested too deeply (over 64 levels)", None)])
    assert _check(_vega_view("[" * 600 + "]" * 600)) == deep
    # 60 nested mappings under the spec: 64 levels in the whole document, the limit
    view, issues = validate_view_text(_vega_view("{a: " * 60 + "1" + "}" * 60), set(), {})
    assert view is not None and issues == []
    assert _check(_vega_view("{a: " * 61 + "1" + "}" * 61)) == deep
    huge = _vega_view("[" + ", ".join(["0"] * 100_000) + "]")
    assert _check(huge) == (None, [(5, "", "YAML too large (over 100000 events)", None)])


def test_vega_lite_spec_size_is_bounded() -> None:
    wide = _vega_view("[" + ", ".join(["0"] * 10_000) + "]")
    view, issues = validate_view_text(wide, set(), {})
    assert view is not None
    assert [(i.line, i.path, i.message) for i in issues] == [
        (5, "panels[0].spec", "vega_lite spec is too large (over 10000 values)")
    ]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/core/test_views.py -q`
Expected: FAIL at collection with `ImportError: cannot import name 'validate_view_text' from 'hypothex.core.views'`.

- [ ] **Step 3: Implement validation**

In `src/hypothex/core/views.py`, replace the import block (from the module docstring through
the last import, ending just above `PanelType = Literal[`) with:

```python
"""Views: YAML dashboards of panels, the preset view of each task kind, and validation."""

from __future__ import annotations

import difflib
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, get_args

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from hypothex.core.config import YAML_CYCLE, TaskKind, has_cycle, scan_yaml
from hypothex.core.errors import ConfigError
from hypothex.core.records import RunStatus

if TYPE_CHECKING:
    from pydantic_core import ErrorDetails
```

Insert directly after the line `PRESET_DIR = Path(__file__).resolve().parent.parent / "views" / "presets"`:

```python
ROW_KEYS = frozenset({"run_id", "group_id", "seed"})
FIELD_PREFIXES = ("usage.", "params.", "vars.")
VEGA_ROOT_KEYS = frozenset({"mark", "layer", "concat", "hconcat", "vconcat", "facet", "repeat"})
VEGA_BLOCKED_KEYS = frozenset({"url", "href", "embedOptions"})
VERSION_REF = "version"
VEGA_MAX_DEPTH = 64
VEGA_MAX_NODES = 10_000
NO_ANCHORS = "YAML anchors and aliases are not allowed"

Loc = tuple[str | int, ...]
```

Append to the end of `src/hypothex/core/views.py`:

```python
def _path(loc: Loc) -> str:
    """Format a location as ``panels[0].data.metrics[1]``."""
    out = ""
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += f".{part}" if out else part
    return out


def _node_at(root: yaml.Node, loc: Loc) -> yaml.Node:
    """
    Return the YAML node for ``loc``, or its deepest existing ancestor.

    For a mapping step the key node is returned, so an error points at the key's line.
    """
    node, found = root, root
    for part in loc:
        child: yaml.Node | None = None
        mark: yaml.Node | None = None
        if isinstance(node, yaml.MappingNode):
            for key, value in node.value:
                if isinstance(key, yaml.ScalarNode) and key.value == str(part):
                    child, mark = value, key
                    break
        elif (
            isinstance(node, yaml.SequenceNode)
            and isinstance(part, int)
            and 0 <= part < len(node.value)
        ):
            child = mark = node.value[part]
        if child is None or mark is None:
            break
        node, found = child, mark
    return found


def _line(root: yaml.Node, loc: Loc) -> int:
    """Return the 1-based line of ``loc`` in the composed YAML."""
    return _node_at(root, loc).start_mark.line + 1


def _allowed_keys(loc: Loc) -> list[str]:
    """Return the keys a mapping at ``loc`` may have, or ``[]`` if unknown."""
    shape = tuple("#" if isinstance(p, int) else p for p in loc)
    models: dict[tuple[str, ...], type[BaseModel]] = {
        (): ViewSpec,
        ("runs",): RunFilter,
        ("panels", "#"): PanelSpec,
        ("panels", "#", "data"): PanelData,
        ("panels", "#", "layout"): PanelLayout,
    }
    model = models.get(shape)
    if model is None:
        return []
    return [field.alias or name for name, field in model.model_fields.items()]


def _closest(word: str, choices: list[str] | set[str]) -> str | None:
    """Return the closest choice to ``word`` (difflib), or None."""
    near = difflib.get_close_matches(word, sorted(choices), n=1)
    return near[0] if near else None


def _schema_issue(root: yaml.Node, err: ErrorDetails) -> ValidationIssue:
    """Turn one pydantic error into a ``ValidationIssue`` with line and suggestion."""
    loc: Loc = tuple(err["loc"])
    field = next((p for p in reversed(loc) if isinstance(p, str)), "value")
    suggestion: str | None = None
    if err["type"] == "extra_forbidden":
        message = f"unknown key {loc[-1]}"
        suggestion = _closest(str(loc[-1]), _allowed_keys(loc[:-1]))
    elif err["type"] == "literal_error":
        expected = re.findall(r"'([^']*)'", str(err.get("ctx", {}).get("expected", "")))
        suggestion = _closest(str(err["input"]), expected)
        message = f"unknown {field} {err['input']}"
        if suggestion is None:
            message += f"; expected one of {', '.join(expected)}"
    elif err["type"] == "missing":
        message = f"missing {field}"
    else:
        message = f"{field}: {err['msg'].removeprefix('Value error, ')}"
    return ValidationIssue(
        line=_line(root, loc), path=_path(loc), message=message, suggestion=suggestion
    )


def _metric_problem(
    ref: str, known_metrics: set[str], known_fields: dict[str, set[str]]
) -> tuple[str, str | None] | None:
    """
    Return ``(message, suggestion)`` if ``ref`` names an unknown metric, else None.

    A reference that is exactly a known name is valid before any split, so history
    metrics keep their ``/`` (``val/top1`` is not metric ``val`` with key ``top1``).
    """
    if ref in ("step", VERSION_REF) or ref.startswith(FIELD_PREFIXES):
        return None
    if ref in known_fields.get("runs", set()) or not known_metrics or ref in known_metrics:
        return None
    base = re.split(r"[@/]", ref, maxsplit=1)[0]
    if base in known_metrics:
        return None
    if "/" in ref and "@" not in ref:
        whole = _closest(ref, {m for m in known_metrics if "/" in m})
        if whole is not None:
            return f"unknown metric {ref}", whole
    near = _closest(base, known_metrics)
    return f"unknown metric {base}", (near + ref[len(base) :] if near else None)


def _example_field_problem(
    name: str, known_fields: dict[str, set[str]]
) -> tuple[str, str | None] | None:
    """
    Return ``(message, suggestion)`` if ``name`` is not a known per-example field.

    Per-example fields are the ``<field>`` of ``predictions`` keys
    ``<metric>@<version>.<field>``. Skipped when no such key is known.
    """
    fields = {
        key.rsplit(".", 1)[1]
        for key in known_fields.get("predictions", set())
        if "." in key and "@" in key.rsplit(".", 1)[0]
    }
    if not fields or name in fields:
        return None
    return f"unknown per-example field {name}", _closest(name, fields)


class _SpecTooBig(Exception):
    """Raised inside ``vega_spec_problems`` when a spec passes a size bound."""


def vega_spec_problems(spec: Any, at: Loc = ()) -> list[tuple[Loc, str]]:
    """
    Find what a Vega-Lite spec may not contain: external resources and images.

    Rows reach a ``vega_lite`` panel only inline, so every ``url`` (data, lookup
    sources, image marks), ``href`` (links), and ``embedOptions`` (vega-embed
    options, which can swap the loader) key is rejected at any depth, and so is
    every ``image`` mark. The walk is bounded: more than ``VEGA_MAX_DEPTH`` nested
    mappings and lists, or more than ``VEGA_MAX_NODES`` values, gives the single
    problem "too deep" or "too large" at ``at`` instead. A spec that contains
    itself (YAML aliases in ``hypothex.yaml``) is "too deep", not a
    ``RecursionError``.

    Parameters
    ----------
    spec : Any
        The spec, or a part of it.
    at : tuple of (str or int)
        Location of ``spec``; prefixed to every returned location.

    Returns
    -------
    list of tuple of (tuple, str)
        ``(location, message)`` per problem, in document order.

    Examples
    --------
    >>> vega_spec_problems({"layer": [{"mark": "point", "data": {"url": "x.csv"}}]})
    [(('layer', 0, 'data', 'url'), 'vega_lite spec must not load external resources (url)')]
    >>> vega_spec_problems({"mark": {"type": "image"}})
    [(('mark',), 'vega_lite image marks are not allowed')]
    >>> loop = {"mark": "point"}
    >>> loop["layer"] = [loop]
    >>> vega_spec_problems(loop, ("spec",))
    [(('spec',), 'vega_lite spec is too deep (over 64 levels)')]
    """
    found: list[tuple[Loc, str]] = []
    seen = 0

    def walk(node: Any, loc: Loc, level: int) -> None:
        nonlocal seen
        seen += 1
        if seen > VEGA_MAX_NODES:
            raise _SpecTooBig(f"vega_lite spec is too large (over {VEGA_MAX_NODES} values)")
        if isinstance(node, dict | list) and level > VEGA_MAX_DEPTH:
            raise _SpecTooBig(f"vega_lite spec is too deep (over {VEGA_MAX_DEPTH} levels)")
        if isinstance(node, dict):
            for key, value in node.items():
                here: Loc = (*loc, str(key))
                if key in VEGA_BLOCKED_KEYS:
                    found.append((here, f"vega_lite spec must not load external resources ({key})"))
                elif key == "mark" and (
                    value == "image" or (isinstance(value, dict) and value.get("type") == "image")
                ):
                    found.append((here, "vega_lite image marks are not allowed"))
                else:
                    walk(value, here, level + 1)
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, (*loc, i), level + 1)

    try:
        walk(spec, at, 1)
    except _SpecTooBig as exc:
        return [(at, str(exc))]
    return found


def _panel_issues(
    panel: PanelSpec,
    at: Loc,
    known_metrics: set[str],
    known_fields: dict[str, set[str]],
) -> list[tuple[Loc, str, str | None]]:
    """Return ``(loc, message, suggestion)`` for one panel's semantic problems."""
    out: list[tuple[Loc, str, str | None]] = []
    data = panel.data
    refs: list[tuple[Loc, str]] = [
        ((*at, "data", "metrics", j), ref) for j, ref in enumerate(data.metrics or [])
    ]
    # a grid's data.y is a per-example field, checked below
    axes = ("x", "step_metric") if panel.type == "grid" else ("x", "y", "step_metric")
    refs += [((*at, "data", k), v) for k in axes if (v := getattr(data, k))]
    for loc, ref in refs:
        problem = _metric_problem(ref, known_metrics, known_fields)
        if problem is not None:
            out.append((loc, *problem))
    if panel.type == "grid" and data.y:
        problem = _example_field_problem(data.y, known_fields)
        if problem is not None:
            out.append(((*at, "data", "y"), *problem))
    if panel.type in ("table", "vega_lite") and data.source is None:
        out.append(((*at, "data"), f"{panel.type} needs data.source", None))
    known = known_fields.get(data.source, set()) if data.source else set()
    if known:
        allowed = known | ROW_KEYS | ({VERSION_REF} if data.source == "runs" else set())
        for j, name in enumerate(data.fields or []):
            if name not in allowed:
                out.append(
                    (
                        (*at, "data", "fields", j),
                        f"unknown field {name} in {data.source}",
                        _closest(name, allowed),
                    )
                )
    if panel.type == "scatter" and not data.x:
        out.append(((*at, "data"), "scatter needs data.x", None))
    if panel.type == "markdown" and not panel.text:
        out.append(((*at, "text"), "markdown needs text", None))
    if panel.type == "vega_lite" and not VEGA_ROOT_KEYS & set(panel.spec or {}):
        out.append(((*at, "spec"), "vega_lite spec needs mark, layer, or a composition", None))
    if panel.type == "vega_lite" and panel.spec:
        out += [(loc, msg, None) for loc, msg in vega_spec_problems(panel.spec, (*at, "spec"))]
    if panel.pareto and set(panel.pareto) - {"x", "y"}:
        out.append(((*at, "pareto"), "pareto keys are x and y", None))
    return out


def _semantic_issues(
    view: ViewSpec,
    root: yaml.Node,
    known_metrics: set[str],
    known_fields: dict[str, set[str]],
) -> list[ValidationIssue]:
    """Check metric names, sources, fields, and per-type requirements of a parsed view."""
    found: list[tuple[Loc, str, str | None]] = []
    titles: set[str] = set()
    for i, panel in enumerate(view.panels):
        found += _panel_issues(panel, ("panels", i), known_metrics, known_fields)
        if panel.title in titles:
            found.append((("panels", i, "title"), f"duplicate panel title {panel.title}", None))
        if panel.title:
            titles.add(panel.title)
    return [
        ValidationIssue(line=_line(root, loc), path=_path(loc), message=msg, suggestion=fix)
        for loc, msg, fix in found
    ]


def validate_view_text(
    text: str, known_metrics: set[str], known_fields: dict[str, set[str]]
) -> tuple[ViewSpec | None, list[ValidationIssue]]:
    """
    Parse and check a view's YAML text.

    The text is pre-scanned before it is loaded (``config.scan_yaml``): nesting
    deeper than 64 levels, more than 100,000 parser events, and any YAML anchor
    or alias (a view could refer to itself) are schema errors with their line; a
    loaded value that contains itself (``config.has_cycle``) is one too. Schema
    errors (bad YAML, those guards, unknown keys, wrong types) return no view. Semantic
    problems (unknown metric or field, missing ``source``/``text``/``spec``,
    duplicate titles) return the parsed view plus issues, so a preview can still
    render; the view is valid only when the issue list is empty. Metric and field
    checks are skipped when the matching known set is empty (a task with no runs).

    Parameters
    ----------
    text : str
        View YAML.
    known_metrics : set of str
        Metric base names seen for the task (``view_context``).
    known_fields : dict of str to set of str
        Row fields per source seen for the task (``view_context``).

    Returns
    -------
    tuple of (ViewSpec or None, list of ValidationIssue)

    Examples
    --------
    >>> view, issues = validate_view_text("title: t\\npanels:\\n  - type: leaderbord\\n", set(), {})
    >>> view is None, issues[0].line, issues[0].suggestion
    (True, 3, 'leaderboard')
    """
    try:
        scan = scan_yaml(text)
        if scan.problem is not None:
            message, line = scan.problem
            return None, [ValidationIssue(line=line, path="", message=message)]
        if scan.first_anchor is not None:
            return None, [ValidationIssue(line=scan.first_anchor, path="", message=NO_ANCHORS)]
        root = yaml.compose(text, Loader=yaml.SafeLoader)
        data = yaml.safe_load(text)
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark or exc.context_mark
        line = mark.line + 1 if mark is not None else None
        return None, [ValidationIssue(line=line, path="", message=f"YAML: {exc.problem or exc}")]
    except yaml.YAMLError as exc:
        return None, [ValidationIssue(line=None, path="", message=f"YAML: {exc}")]
    if has_cycle(data):  # the shared guard; without aliases no cycle can form
        return None, [ValidationIssue(line=scan.cycle, path="", message=YAML_CYCLE)]
    if not isinstance(root, yaml.MappingNode):
        line = root.start_mark.line + 1 if root is not None else 1
        message = "a view is a mapping with title and panels"
        return None, [ValidationIssue(line=line, path="", message=message)]
    try:
        view = ViewSpec.model_validate(data)
    except ValidationError as exc:
        return None, [_schema_issue(root, err) for err in exc.errors()]
    return view, _semantic_issues(view, root, known_metrics, known_fields)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/core/test_views.py -q`
Expected: `43 passed`.

Run: `uv run ruff format --check src/hypothex/core/views.py tests/core/test_views.py && uv run ruff check src/hypothex/core/views.py tests/core/test_views.py && uv run ty check src/hypothex/core/views.py tests/core/test_views.py`
Expected: `2 files already formatted`, `All checks passed!`, `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/views.py tests/core/test_views.py
git commit -m "feat: validate view YAML with line numbers and suggestions"
```

---

### Task 17: List, get, save, and delete views

**Files:**
- Modify: `src/hypothex/core/views.py` (import block, constants after `PRESET_DIR`, append functions)
- Test: `tests/core/test_views.py` (import block, append tests)

**Interfaces:**
- Consumes: Task 15 (`load_preset`, `resolve_view`, models), Task 16 (`validate_view_text`);
  `hypothex.core.config.ProjectConfig`, `TaskSpec` with `kind` and `views` (contract 1.3);
  `hypothex.core.fsutil.atomic_write_text`; `hypothex.core.errors.StoreError`.
- Produces:
  - `RESERVED_VIEW` (`"overview"`), derived as `(RESERVED_VIEW,) = RESERVED_VIEW_NAMES`. `VIEW_NAME_PATTERN` and `RESERVED_VIEW_NAMES` are imported from `hypothex.core.config` (Task 5), not redefined, so config loading and view storage share one source of truth.
  - `check_view_name(name: str) -> None` (public): raises `ConfigError` for `overview` or a name outside the pattern. The API/CLI/MCP helpers (Task 30) call it; it is the only view-name check outside config loading.
  - `views_dir(repo: Path, task: str) -> Path` = `<repo>/.hypothex/views/<task>`.
  - `list_views(repo: Path, config: ProjectConfig, task: str) -> list[ViewInfo]`: `overview`
    (origin `preset`, `path=None`, `kind` = task kind) first, then inline views (origin `inline`,
    `path` = `<repo>/hypothex.yaml`) in config order, then file views (origin `file`, sorted by
    name). A file hides the inline view of the same name. `ViewInfo.kind` of a custom view is its
    `from` (or `None`).
  - `get_view(repo, config, task, name) -> ViewSpec` (resolved; file before inline).
  - `save_view(repo, task, name, text) -> Path` (atomic, text stored exactly).
  - `delete_view(repo, task, name) -> None`.
  - Errors as listed in the group notes: `StoreError` for a missing view, `ConfigError` for bad
    or reserved names, unknown tasks, and invalid stored views.

- [ ] **Step 1: Write the failing tests**

In `tests/core/test_views.py`, replace the import block with:

```python
import json
from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from hypothex.core import config as core_config
from hypothex.core import views as core_views
from hypothex.core.config import ProjectConfig, TaskKind
from hypothex.core.errors import ConfigError, StoreError
from hypothex.core.views import (
    PRESET_DIR,
    PanelData,
    PanelLayout,
    PanelSpec,
    RunFilter,
    ViewSpec,
    delete_view,
    get_view,
    list_views,
    load_preset,
    resolve_view,
    save_view,
    validate_view_text,
    views_dir,
)
```

Append to the end of `tests/core/test_views.py`:

```python
# ---- list / get / save / delete ----

FILE_VIEW = """\
title: route quality
from: agent_eval
panels:
  - type: markdown
    title: Note
    text: critic helps on deep targets
"""


def _config(views: dict[str, dict[str, Any]] | None = None) -> ProjectConfig:
    return ProjectConfig.model_validate(
        {
            "project": "toy",
            "datasets": {"d": {"version": "v1", "path": "d.jsonl"}},
            "metrics": {"solved": {"version": "v2", "fn": "m:solved"}},
            "tasks": {
                "bench": {
                    "dataset": "d",
                    "metrics": ["solved"],
                    "primary": "solved",
                    "kind": "agent_eval",
                    "views": views or {},
                }
            },
        }
    )


def test_views_dir_is_under_repo(tmp_path: Path) -> None:
    assert views_dir(tmp_path, "bench") == tmp_path / ".hypothex" / "views" / "bench"


def test_list_views_orders_preset_inline_files_and_file_wins(tmp_path: Path) -> None:
    config = _config(
        {
            "costs": {"title": "Costs", "panels": []},
            "shared": {"title": "inline shared", "panels": []},
        }
    )
    # Config validation rejects reserved and bad names, so set them after
    # validation to exercise the skip path in list_views.
    config.tasks["bench"].views["overview"] = {"title": "ignored", "panels": []}
    config.tasks["bench"].views["Bad Name"] = {"title": "ignored", "panels": []}
    save_view(tmp_path, "bench", "shared", "title: file shared\npanels: []\n")
    save_view(tmp_path, "bench", "route", FILE_VIEW)
    infos = list_views(tmp_path, config, "bench")
    assert [(i.name, i.origin, i.title, i.kind) for i in infos] == [
        ("overview", "preset", "overview", "agent_eval"),
        ("costs", "inline", "Costs", None),
        ("route", "file", "route quality", "agent_eval"),
        ("shared", "file", "file shared", None),
    ]
    assert infos[0].path is None
    assert infos[1].path == str(tmp_path / "hypothex.yaml")
    assert infos[2].path == str(views_dir(tmp_path, "bench") / "route.yaml")


def test_list_views_keeps_unparseable_file_with_name_as_title(tmp_path: Path) -> None:
    save_view(tmp_path, "bench", "broken", "title: [unclosed\n")
    names = [(i.name, i.title) for i in list_views(tmp_path, _config(), "bench")]
    assert names == [("overview", "overview"), ("broken", "broken")]


def test_list_views_unknown_task(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="unknown task 'nope'"):
        list_views(tmp_path, _config(), "nope")


def test_get_view_overview_file_and_inline(tmp_path: Path) -> None:
    config = _config({"costs": {"title": "Costs", "from": "generic", "panels": []}})
    save_view(tmp_path, "bench", "route", FILE_VIEW)
    assert get_view(tmp_path, config, "bench", "overview") == load_preset("agent_eval")
    route = get_view(tmp_path, config, "bench", "route")
    assert route.title == "route quality"
    assert route.from_ is None
    assert [p.title for p in route.panels] == [
        "Summary",
        "Leaderboard",
        "Cost vs solved",
        "Failures",
        "Per target",
        "Attempt",
        "Note",
    ]
    costs = get_view(tmp_path, config, "bench", "costs")
    assert [p.type for p in costs.panels] == ["stat_strip", "leaderboard"]


def test_get_view_missing_and_invalid(tmp_path: Path) -> None:
    config = _config({"bad": {"title": "b", "panels": [{"type": "pie"}]}})
    with pytest.raises(StoreError, match="no view 'nope' for task 'bench'"):
        get_view(tmp_path, config, "bench", "nope")
    with pytest.raises(StoreError):
        get_view(tmp_path, config, "bench", "../escape")
    with pytest.raises(ConfigError, match=r"tasks\.bench\.views\.bad"):
        get_view(tmp_path, config, "bench", "bad")
    save_view(tmp_path, "bench", "typo", "title: t\npanels:\n  - type: leaderbord\n")
    with pytest.raises(ConfigError, match="typo.yaml: line 3: unknown type leaderbord"):
        get_view(tmp_path, config, "bench", "typo")


def test_save_view_writes_text_exactly_and_atomically(tmp_path: Path) -> None:
    path = save_view(tmp_path, "bench", "route", FILE_VIEW)
    assert path == tmp_path / ".hypothex" / "views" / "bench" / "route.yaml"
    assert path.read_text(encoding="utf-8") == FILE_VIEW
    save_view(tmp_path, "bench", "route", "title: café v2\n")
    assert path.read_text(encoding="utf-8") == "title: café v2\n"
    assert sorted(p.name for p in path.parent.iterdir()) == ["route.yaml"]


@pytest.mark.parametrize("name", ["Bad", "a/b", "../x", "", "-lead", "a.b", "ok\n"])
def test_save_view_rejects_bad_names(tmp_path: Path, name: str) -> None:
    with pytest.raises(ConfigError, match="must match"):
        save_view(tmp_path, "bench", name, "title: t\n")
    assert not views_dir(tmp_path, "bench").exists()


def test_overview_is_reserved(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="'overview' is the preset view"):
        save_view(tmp_path, "bench", "overview", "title: t\n")
    with pytest.raises(ConfigError, match="'overview' is the preset view"):
        delete_view(tmp_path, "bench", "overview")


def test_reserved_view_name_comes_from_config() -> None:
    # one source of truth: views uses config's set, it does not define its own
    assert core_views.RESERVED_VIEW_NAMES is core_config.RESERVED_VIEW_NAMES
    assert frozenset({core_views.RESERVED_VIEW}) == core_config.RESERVED_VIEW_NAMES
    assert core_views.RESERVED_VIEW == "overview"


def test_delete_view(tmp_path: Path) -> None:
    path = save_view(tmp_path, "bench", "route", FILE_VIEW)
    delete_view(tmp_path, "bench", "route")
    assert not path.exists()
    with pytest.raises(StoreError, match="no view file 'route' for task 'bench'"):
        delete_view(tmp_path, "bench", "route")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/core/test_views.py -q`
Expected: FAIL at collection with `ImportError: cannot import name 'delete_view' from 'hypothex.core.views'`.

- [ ] **Step 3: Implement storage**

In `src/hypothex/core/views.py`, replace the import block (ending just above `PanelType = Literal[`) with:

```python
"""Views: YAML dashboards of panels, the preset view of each task kind, and validation."""

from __future__ import annotations

import difflib
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, get_args

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from hypothex.core.config import (
    CONFIG_FILENAME,
    RESERVED_VIEW_NAMES,
    VIEW_NAME_PATTERN,
    YAML_CYCLE,
    ProjectConfig,
    TaskKind,
    TaskSpec,
    has_cycle,
    scan_yaml,
)
from hypothex.core.errors import ConfigError, StoreError
from hypothex.core.fsutil import atomic_write_text
from hypothex.core.records import RunStatus

if TYPE_CHECKING:
    from pydantic_core import ErrorDetails
```

Insert directly after the line `PRESET_DIR = Path(__file__).resolve().parent.parent / "views" / "presets"`:

```python
# The preset's name, derived from config (Task 5): one source of truth for reserved names.
# The unpacking fails at import if config ever reserves more than one name.
(RESERVED_VIEW,) = RESERVED_VIEW_NAMES
```

Append to the end of `src/hypothex/core/views.py`:

```python
def views_dir(repo: Path, task: str) -> Path:
    """
    Return the folder holding a task's view files.

    Parameters
    ----------
    repo : Path
        Project repository root.
    task : str
        Task name.

    Returns
    -------
    Path
        ``<repo>/.hypothex/views/<task>/``.

    Examples
    --------
    >>> views_dir(Path("/r"), "t").as_posix()
    '/r/.hypothex/views/t'
    """
    return repo / ".hypothex" / "views" / task


def _valid_name(name: str) -> bool:
    """Return True if ``name`` is a usable, non-reserved view name."""
    return name not in RESERVED_VIEW_NAMES and re.fullmatch(VIEW_NAME_PATTERN, name) is not None


def check_view_name(name: str) -> None:
    """
    Raise ``ConfigError`` unless ``name`` can name a view file.

    Parameters
    ----------
    name : str
        Proposed view name.

    Raises
    ------
    ConfigError
        If ``name`` is ``overview`` (the preset) or does not match ``VIEW_NAME_PATTERN``.

    Examples
    --------
    >>> check_view_name("route-quality")
    """
    if name in RESERVED_VIEW_NAMES:
        raise ConfigError(f"{name!r} is the preset view of the task kind; pick another name")
    if not _valid_name(name):
        raise ConfigError(f"view name {name!r} must match {VIEW_NAME_PATTERN}")


def _task_spec(config: ProjectConfig, task: str) -> TaskSpec:
    """Return a task's spec or raise ``ConfigError``."""
    if task not in config.tasks:
        raise ConfigError(f"unknown task {task!r} in project {config.project!r}")
    return config.tasks[task]


def _mapping(text: str) -> dict[str, Any]:
    """Parse YAML text leniently: ``{}`` for invalid YAML or a non-mapping."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _info(
    name: str, body: dict[str, Any], origin: Literal["inline", "file"], path: Path
) -> ViewInfo:
    """Build a ``ViewInfo`` from a raw view body."""
    title = body.get("title")
    kind = body.get("from")
    return ViewInfo(
        name=name,
        title=title if isinstance(title, str) else name,
        origin=origin,
        path=str(path),
        kind=kind if kind in get_args(TaskKind) else None,
    )


def list_views(repo: Path, config: ProjectConfig, task: str) -> list[ViewInfo]:
    """
    List a task's views: the kind's preset as ``overview``, then inline, then files.

    A file view and an inline view with the same name are listed once, as the file.
    Names that are reserved or do not match ``VIEW_NAME_PATTERN`` are skipped.

    Parameters
    ----------
    repo : Path
        Project repository root.
    config : ProjectConfig
        Parsed ``hypothex.yaml``.
    task : str
        Task name.

    Returns
    -------
    list of ViewInfo

    Raises
    ------
    ConfigError
        If the task is unknown.
    """
    spec = _task_spec(config, task)
    infos = [
        ViewInfo(
            name=RESERVED_VIEW,
            title=load_preset(spec.kind).title,
            origin="preset",
            path=None,
            kind=spec.kind,
        )
    ]
    files: dict[str, ViewInfo] = {}
    directory = views_dir(repo, task)
    if directory.is_dir():
        for path in sorted(directory.glob("*.yaml")):
            if _valid_name(path.stem):
                body = _mapping(path.read_text(encoding="utf-8"))
                files[path.stem] = _info(path.stem, body, "file", path)
    infos.extend(
        _info(name, body, "inline", repo / CONFIG_FILENAME)
        for name, body in spec.views.items()
        if _valid_name(name) and name not in files
    )
    infos.extend(files.values())
    return infos


def get_view(repo: Path, config: ProjectConfig, task: str, name: str) -> ViewSpec:
    """
    Load one view of a task and resolve its ``from``.

    Parameters
    ----------
    repo : Path
        Project repository root.
    config : ProjectConfig
        Parsed ``hypothex.yaml``.
    task : str
        Task name.
    name : str
        View name; ``overview`` is the preset of the task's kind.

    Returns
    -------
    ViewSpec
        The resolved view.

    Raises
    ------
    ConfigError
        If the task is unknown or the stored view is invalid.
    StoreError
        If the task has no view with this name.
    """
    spec = _task_spec(config, task)
    if name == RESERVED_VIEW:
        return load_preset(spec.kind)
    if _valid_name(name):
        path = views_dir(repo, task) / f"{name}.yaml"
        if path.is_file():
            view, issues = validate_view_text(path.read_text(encoding="utf-8"), set(), {})
            if view is None:
                first = issues[0]
                where = f"line {first.line}: " if first.line is not None else ""
                raise ConfigError(f"{path}: {where}{first.message}")
            return resolve_view(view)
        if name in spec.views:
            try:
                view = ViewSpec.model_validate(spec.views[name])
            except ValidationError as exc:
                raise ConfigError(
                    f"{repo / CONFIG_FILENAME}: tasks.{task}.views.{name}: {exc}"
                ) from exc
            return resolve_view(view)
    raise StoreError(f"no view {name!r} for task {task!r}")


def save_view(repo: Path, task: str, name: str, text: str) -> Path:
    """
    Write a view's YAML text to ``<repo>/.hypothex/views/<task>/<name>.yaml`` atomically.

    The caller validates ``text`` first (``validate_view_text``); this only checks the name.

    Parameters
    ----------
    repo : Path
        Project repository root.
    task : str
        Task name.
    name : str
        View name matching ``VIEW_NAME_PATTERN``, not ``overview``.
    text : str
        View YAML, stored exactly as given.

    Returns
    -------
    Path
        The written file.

    Raises
    ------
    ConfigError
        If the name is invalid or reserved.
    """
    check_view_name(name)
    path = views_dir(repo, task) / f"{name}.yaml"
    atomic_write_text(path, text)
    return path


def delete_view(repo: Path, task: str, name: str) -> None:
    """
    Delete a view file.

    Parameters
    ----------
    repo : Path
        Project repository root.
    task : str
        Task name.
    name : str
        View name.

    Raises
    ------
    ConfigError
        If the name is invalid or is the reserved ``overview``.
    StoreError
        If there is no view file with this name (inline views live in ``hypothex.yaml``).
    """
    check_view_name(name)
    path = views_dir(repo, task) / f"{name}.yaml"
    if not path.is_file():
        raise StoreError(f"no view file {name!r} for task {task!r}")
    path.unlink()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/core/test_views.py -q`
Expected: `60 passed`.

Run: `uv run ruff format --check src/hypothex/core/views.py tests/core/test_views.py && uv run ruff check src/hypothex/core/views.py tests/core/test_views.py && uv run ty check src/hypothex/core/views.py tests/core/test_views.py`
Expected: `2 files already formatted`, `All checks passed!`, `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/views.py tests/core/test_views.py
git commit -m "feat: list, load, save, and delete task views"
```

## Part 5: Data sources, view context, and the panel engine (Tasks 18–23)

Implements contract sections 1.5 (`hypothex.core.sources`) and 1.6 (`hypothex.core.panels`).

**Depends on (earlier parts, used exactly as the contract names them):**
- `hypothex.core.records`: `UsageTotals`, `RunRecord.usage`, `Artifact.step`, `Artifact.metrics` (contract 1.2).
- `hypothex.core.config`: `TaskSpec.kind` etc. (contract 1.3; only read indirectly).
- `hypothex.core.views`: `Source`, `PanelType`, `RunFilter`, `PanelData`, `PanelSpec`, `ViewSpec` (contract 1.4).
- `hypothex.core.stats`: `quantile` (numpy "linear"), `ecdf_points(values, max_points=200)` (contract 1.1).
- `hypothex.core.leaderboard`: `LeaderboardRow.label`, `LeaderboardRow.test_interval: NoiseInterval | None` (`.lo`, `.hi`), `Leaderboard.headline`, `Leaderboard.stat_strip`, and `build_leaderboard(..., per_example=...)` returning a fully populated `Leaderboard` (headline and stat strip filled), exactly like `queries.get_leaderboard` (contract 1.7).

**Design decisions (apply to every task in this part):**
- Rows are read from run-folder files (not the downsampled index), so spike detection and quantiles see full data.
- `group_id` everywhere is the leaderboard seed-group id `<hash8>@<commit7>[+<diff4>]` (`nogit` without a commit), computed by `leaderboard.group_id_for` (Task 10; `sources` re-exports it).
- `sources` imports `views.Source` only under `TYPE_CHECKING`: `views.view_context` imports `sources`, so a runtime import would be circular.
- Run selection for a panel: the task's unarchived runs, oldest first; then the view's `RunFilter` (`status` any-of, `tags` all-of, `created_by` equal, `since` inclusive, naive datetimes read as UTC); then `data.filter` (equality, or membership when the wanted value is a list) against the flattened `runs` row (for `table`/`vega_lite` it filters each source row instead); then `data.pick` (`latest` = newest run per seed group, `best` = runs of the leaderboard's top group, `all`/unset = everything).
- `data.group_by`: `group` (default, leaderboard seed group, labelled with the leaderboard label when the group is on the board), `config` (config hash only), `run`, `seed`. Fallback label: `leaderboard.group_label` (Task 10) of the newest non-empty hypothesis and the group's tags.
- `query_view` isolates failures: a panel that raises a `HypothexError` becomes `{rows: [], meta: {error}}`; the other panels still render.
- `table`/`vega_lite` cap rows at `MAX_TABLE_ROWS = 5000` and report `meta.total` plus a warning.
- `vega_lite` `meta.spec` replaces the root `data` with `{"values": []}`; any other external resource (`url`/`href`/`embedOptions` at any depth, `image` marks) makes the panel fail with a `ConfigError` (`views.vega_spec_problems`, the same check view validation runs), so the server never hands the browser a spec that fetches. The stored spec is not mutated. The UI also renders with a deny-all loader (frontend plan).
- `table`/`vega_lite` filter full source rows before projecting to `data.fields`.

Task 19 is the last views task (`view_context`, contract 1.4). It sits here because it reads rows through `sources.iter_rows` (Task 18).

---

### Task 18: Row sources over run folders (`hypothex.core.sources`)

**Files:**
- Create: `src/hypothex/core/sources.py`
- Test: `tests/core/test_sources.py`

**Interfaces:**
- Consumes: `Context` (`ctx.store.read_scores`, `ctx.store.read_metric_points`, `ctx.store.load_project`, `ctx.run_dir`), the run-folder readers `RunStore.read_samples`, `read_usage`, `list_traces`, `read_trace` (Task 6), `leaderboard.group_id_for` (Task 10), `config.load_project_config`, `datasets.resolve_dataset_path`, `fsutil.read_jsonl`, `records.RunRecord` with `usage: UsageTotals | None` (contract 1.2), `views.Source` (type only, contract 1.4).
- Produces (`hypothex.core.sources`):
  - `iter_rows(ctx: Context, runs: list[RunRecord], source: Source, fields: list[str] | None = None) -> Iterator[dict[str, Any]]` — contract 1.5. Every row has `run_id`, `group_id`, `seed`. With `fields`, rows hold only those three plus the listed keys (missing keys → `None`); listing `run_id`, `group_id`, or `seed` keeps their real values. Unknown source → `ConfigError("unknown source ...")`.
  - `select_fields(row: dict[str, Any], fields: list[str] | None) -> dict[str, Any]` — the projection `iter_rows` applies: `run_id`, `group_id`, `seed` from the row, then each listed field (`None` when missing); `fields=None` returns the row unchanged. The panel engine (Task 20) filters full rows first and projects after, with this helper.
  - `SOURCES: tuple[str, ...]` = `("runs", "scores", "metrics", "predictions", "samples", "usage", "traces")`.
  - `group_id_for` is re-exported from `hypothex.core.leaderboard` (defined in Task 10), so `from hypothex.core.sources import group_id_for` works.
  - File names, sample parsing, usage parsing, and trace parsing are not redefined here: `samples`, `usage`, and `traces` rows come from the `RunStore` readers of Task 6 (bad rows skipped the same way everywhere).
  - Row keys per source: `runs` → `status, created_at (ISO str), created_by, hypothesis, tags, host, exit_code, params.*, vars.*, usage.*` (usage keys only when the run has totals); `scores` → `metric, version, key, value` (errored or valueless scores skipped); `metrics` → `name, step, value, t`; `predictions` → `id, prediction, reference, meta.*, <metric>@<version>.<field>` (reference joined from the task dataset when the row has none); `samples` → `name, value` (non-finite or non-numeric values skipped); `usage` → `example_id, tokens_in, tokens_out, usd, seconds` (invalid rows skipped); `traces` → `example_id` (the id given to `log_trace`, else the file stem) + the eight `TraceStep` keys `turn, tool, args, result, tokens_in, tokens_out, seconds, error`.

- [ ] **Step 1: Write the failing tests**

`tests/core/test_sources.py`:

```python
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from hypothex.core.context import Context
from hypothex.core.errors import ConfigError
from hypothex.core.ids import utcnow
from hypothex.core.records import GitInfo, RunRecord, RunStatus, ScoreRecord, UsageTotals
from hypothex.core.sources import group_id_for, iter_rows, select_fields
from tests.factories import make_record

T0 = utcnow()


def _run(ctx: Context, repo: Path, run_id: str, *, minute: int = 0, **kw: Any) -> RunRecord:
    """Register the toy project and create a finished toy-acc run in group ``aaaa@c1``."""
    ctx.register_project(repo)
    fields: dict[str, Any] = {
        "task": "toy-acc",
        "status": RunStatus.FINISHED,
        "config_hash": "sha256:aaaa",
        "git": GitInfo(commit="c1"),
        "created_at": T0 + timedelta(minutes=minute),
        "cwd": str(repo),
        "environment_id": ctx.descriptor.environment_id,
    }
    fields.update(kw)
    return ctx.create_run(make_record(run_id, project="toy", **fields))


def _jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_group_id_matches_leaderboard_format() -> None:
    rec = make_record(config_hash="sha256:0123456789abcdef", git=GitInfo(commit="9f3c2e1abc"))
    assert group_id_for(rec) == "01234567@9f3c2e1"
    assert group_id_for(make_record(config_hash="sha256:ab")) == "ab@nogit"


def test_runs_source_flattens_record(ctx: Context, toy_repo: Path) -> None:
    rec = _run(
        ctx,
        toy_repo,
        "r1",
        seed=3,
        params={"model": "svm"},
        vars={"lr": "0.1"},
        tags=["baseline"],
        created_by="agent:claude",
        hypothesis="svm",
        usage=UsageTotals(tokens_in=10, tokens_out=4, usd=0.5, seconds=2.0, calls=1),
    )
    rows = list(iter_rows(ctx, [rec], "runs"))
    assert rows == [
        {
            "run_id": "r1",
            "group_id": "aaaa@c1",
            "seed": 3,
            "status": "finished",
            "created_at": rec.created_at.isoformat(),
            "created_by": "agent:claude",
            "hypothesis": "svm",
            "tags": ["baseline"],
            "host": "mac",
            "exit_code": None,
            "params.model": "svm",
            "vars.lr": "0.1",
            "usage.tokens_in": 10,
            "usage.tokens_out": 4,
            "usage.usd": 0.5,
            "usage.seconds": 2.0,
            "usage.calls": 1,
        }
    ]


def test_runs_source_omits_usage_when_absent(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "r1")
    (row,) = iter_rows(ctx, [rec], "runs")
    assert not any(k.startswith("usage.") for k in row)


def test_scores_source_skips_errors(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "r1", seed=1)
    ctx.add_score(
        rec, ScoreRecord(metric="accuracy", version="v1", key="value", value=0.75, created_at=T0)
    )
    ctx.add_score(
        rec, ScoreRecord(metric="accuracy", version="v2", key="value", error="boom", created_at=T0)
    )
    assert list(iter_rows(ctx, [rec], "scores")) == [
        {
            "run_id": "r1",
            "group_id": "aaaa@c1",
            "seed": 1,
            "metric": "accuracy",
            "version": "v1",
            "key": "value",
            "value": 0.75,
        }
    ]


def test_metrics_source_reads_full_history(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "r1")
    _jsonl(
        ctx.run_dir(rec) / "metrics.jsonl",
        [{"name": "loss", "step": s, "value": 1.0 / (s + 1), "t": 100.0 + s} for s in range(3)],
    )
    rows = list(iter_rows(ctx, [rec], "metrics", fields=["step", "value"]))
    assert rows == [
        {"run_id": "r1", "group_id": "aaaa@c1", "seed": None, "step": 0, "value": 1.0},
        {"run_id": "r1", "group_id": "aaaa@c1", "seed": None, "step": 1, "value": 0.5},
        {"run_id": "r1", "group_id": "aaaa@c1", "seed": None, "step": 2, "value": 1.0 / 3},
    ]


def test_predictions_source_joins_references_meta_and_scores(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "r1")
    pred = ctx.run_dir(rec) / "predictions"
    _jsonl(
        pred / "predictions.jsonl",
        [
            {"id": "ex-0", "prediction": 0, "meta": {"category": "ok", "difficulty": 1}},
            {"id": "ex-1", "prediction": 0, "reference": 7},
        ],
    )
    _jsonl(pred / "scores.accuracy@v1.jsonl", [{"id": "ex-0", "correct": True}])
    rows = list(iter_rows(ctx, [rec], "predictions"))
    # toy dataset references are [0, 1, 0, 0]; ex-1 keeps its own reference 7
    assert rows == [
        {
            "run_id": "r1",
            "group_id": "aaaa@c1",
            "seed": None,
            "id": "ex-0",
            "prediction": 0,
            "reference": 0,
            "meta.category": "ok",
            "meta.difficulty": 1,
            "accuracy@v1.correct": True,
        },
        {
            "run_id": "r1",
            "group_id": "aaaa@c1",
            "seed": None,
            "id": "ex-1",
            "prediction": 0,
            "reference": 7,
        },
    ]


def test_samples_usage_and_traces_sources(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "r1", seed=2)
    run_dir = ctx.run_dir(rec)
    _jsonl(run_dir / "samples" / "latency_ms.jsonl", [{"value": 12}, {"value": 15.5}, {}])
    _jsonl(
        run_dir / "usage.jsonl",
        [{"example_id": "ex-0", "tokens_in": 100, "tokens_out": 20, "usd": 0.01, "seconds": 1.5}],
    )
    _jsonl(
        run_dir / "traces" / "ex_0.jsonl",
        [
            {"turn": 1, "tool": "search", "args": {"q": "a"}, "result": "hit", "tokens_in": 9},
            {"turn": 2, "tool": "edit", "error": "patch failed"},
        ],
    )
    base = {"run_id": "r1", "group_id": "aaaa@c1", "seed": 2}
    assert list(iter_rows(ctx, [rec], "samples")) == [
        {**base, "name": "latency_ms", "value": 12.0},
        {**base, "name": "latency_ms", "value": 15.5},
    ]
    assert list(iter_rows(ctx, [rec], "usage")) == [
        {
            **base,
            "example_id": "ex-0",
            "tokens_in": 100,
            "tokens_out": 20,
            "usd": 0.01,
            "seconds": 1.5,
        }
    ]
    traces = list(iter_rows(ctx, [rec], "traces", fields=["example_id", "turn", "tool", "error"]))
    assert traces == [
        {**base, "example_id": "ex_0", "turn": 1, "tool": "search", "error": None},
        {**base, "example_id": "ex_0", "turn": 2, "tool": "edit", "error": "patch failed"},
    ]


def test_missing_files_yield_no_rows(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "r1")
    for source in ("scores", "metrics", "predictions", "samples", "usage", "traces"):
        assert list(iter_rows(ctx, [rec], source)) == []


def test_fields_that_name_row_keys_keep_their_values(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "r1", seed=7)
    ctx.add_score(
        rec, ScoreRecord(metric="accuracy", version="v1", key="value", value=0.75, created_at=T0)
    )
    fields = ["run_id", "group_id", "seed", "value"]
    assert list(iter_rows(ctx, [rec], "scores", fields=fields)) == [
        {"run_id": "r1", "group_id": "aaaa@c1", "seed": 7, "value": 0.75}
    ]
    row = {"run_id": "r1", "group_id": "g", "seed": 1, "metric": "m", "value": 2.0}
    assert select_fields(row, ["seed", "value", "nope"]) == {
        "run_id": "r1",
        "group_id": "g",
        "seed": 1,
        "value": 2.0,
        "nope": None,
    }
    assert select_fields(row, None) is row


def test_fields_restriction_fills_missing_with_none(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "r1", params={"model": "rf"})
    rows = list(iter_rows(ctx, [rec], "runs", fields=["params.model", "params.nope"]))
    assert rows == [
        {
            "run_id": "r1",
            "group_id": "aaaa@c1",
            "seed": None,
            "params.model": "rf",
            "params.nope": None,
        }
    ]


def test_rows_follow_run_order(ctx: Context, toy_repo: Path) -> None:
    a = _run(ctx, toy_repo, "a", minute=0)
    b = _run(ctx, toy_repo, "b", minute=1, config_hash="sha256:bbbb")
    rows = list(iter_rows(ctx, [b, a], "runs", fields=[]))
    assert [(r["run_id"], r["group_id"]) for r in rows] == [("b", "bbbb@c1"), ("a", "aaaa@c1")]


def test_unknown_source_raises(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "r1")
    with pytest.raises(ConfigError, match="unknown source 'nope'"):
        list(iter_rows(ctx, [rec], "nope"))  # ty: ignore[invalid-argument-type]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_sources.py -v`
Expected: collection ERROR with `ModuleNotFoundError: No module named 'hypothex.core.sources'`.

- [ ] **Step 3: Implement `sources.py`**

`src/hypothex/core/sources.py`:

```python
"""Flat row iterators over the files in run folders, one per view data source."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hypothex.core.config import load_project_config
from hypothex.core.context import Context
from hypothex.core.datasets import resolve_dataset_path
from hypothex.core.errors import ConfigError, StoreError
from hypothex.core.fsutil import read_jsonl
from hypothex.core.leaderboard import group_id_for
from hypothex.core.records import RunRecord

if TYPE_CHECKING:
    from hypothex.core.views import Source

SOURCES: tuple[str, ...] = (
    "runs",
    "scores",
    "metrics",
    "predictions",
    "samples",
    "usage",
    "traces",
)

_Refs = dict[tuple[str, str | None], dict[str, Any]]


def iter_rows(
    ctx: Context,
    runs: list[RunRecord],
    source: Source,
    fields: list[str] | None = None,
) -> Iterator[dict[str, Any]]:
    """
    Yield flat rows of one data source across runs.

    Every row carries ``run_id``, ``group_id``, and ``seed``. Other keys per
    source:

    - ``runs``: ``status``, ``created_at`` (ISO string), ``created_by``,
      ``hypothesis``, ``tags``, ``host``, ``exit_code``, ``params.*``,
      ``vars.*``, ``usage.*`` (only when the run has usage totals).
    - ``scores``: ``metric``, ``version``, ``key``, ``value`` (errored scores skipped).
    - ``metrics``: ``name``, ``step``, ``value``, ``t`` (full history from
      ``metrics.jsonl``).
    - ``predictions``: ``id``, ``prediction``, ``reference`` (joined from the
      task dataset when the row has none), ``meta.*``, and every per-example
      score field as ``<metric>@<version>.<field>``.
    - ``samples``: ``name``, ``value`` (``RunStore.read_samples``).
    - ``usage``: ``example_id``, ``tokens_in``, ``tokens_out``, ``usd``, ``seconds``
      (``RunStore.read_usage``).
    - ``traces``: ``example_id`` plus the eight ``TraceStep`` fields
      (``RunStore.list_traces`` and ``RunStore.read_trace``).

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    runs : list of RunRecord
        Runs to read, in the order rows should appear.
    source : {"runs", "scores", "metrics", "predictions", "samples", "usage", "traces"}
        Which data source to read.
    fields : list of str, optional
        Keep only these keys (plus ``run_id``, ``group_id``, ``seed``);
        missing keys become ``None``.

    Yields
    ------
    dict
        One flat row.

    Raises
    ------
    ConfigError
        If ``source`` is not a known source.

    Examples
    --------
    >>> rows = list(iter_rows(ctx, runs, "scores", fields=["value"]))  # doctest: +SKIP
    >>> rows[0]  # doctest: +SKIP
    {'run_id': 'r1', 'group_id': 'aaaa@c1', 'seed': 1, 'value': 0.75}
    """
    if source not in SOURCES:
        raise ConfigError(f"unknown source {source!r}; use one of {', '.join(SOURCES)}")
    reader = _READERS[source]
    refs: _Refs = {}
    for run in runs:
        base = {"run_id": run.run_id, "group_id": group_id_for(run), "seed": run.seed}
        for row in reader(ctx, run, refs):
            yield select_fields({**base, **row}, fields)


def select_fields(row: dict[str, Any], fields: list[str] | None) -> dict[str, Any]:
    """
    Keep ``run_id``, ``group_id``, ``seed`` and the listed fields of a full row.

    The projection is taken from the full row, so listing ``run_id``,
    ``group_id``, or ``seed`` keeps their values instead of blanking them.

    Parameters
    ----------
    row : dict
        A full row from a source (with ``run_id``, ``group_id``, ``seed``).
    fields : list of str or None
        Fields to keep; ``None`` keeps the whole row.

    Returns
    -------
    dict
        The projected row; a listed field the row lacks is ``None``.

    Examples
    --------
    >>> select_fields({"run_id": "r1", "group_id": "g", "seed": 1, "v": 2}, ["seed", "x"])
    {'run_id': 'r1', 'group_id': 'g', 'seed': 1, 'x': None}
    """
    if fields is None:
        return row
    out = {key: row.get(key) for key in ("run_id", "group_id", "seed")}
    out.update({f: row.get(f) for f in fields})
    return out


def _flat(prefix: str, value: dict[str, Any]) -> dict[str, Any]:
    return {f"{prefix}.{k}": v for k, v in value.items()}


def _runs(ctx: Context, run: RunRecord, _refs: _Refs) -> Iterator[dict[str, Any]]:
    row: dict[str, Any] = {
        "status": run.status.value,
        "created_at": run.created_at.isoformat(),
        "created_by": run.created_by,
        "hypothesis": run.hypothesis,
        "tags": list(run.tags),
        "host": run.host,
        "exit_code": run.exit_code,
        **_flat("params", run.params),
        **_flat("vars", run.vars),
    }
    if run.usage is not None:
        row.update(_flat("usage", run.usage.model_dump()))
    yield row


def _scores(ctx: Context, run: RunRecord, _refs: _Refs) -> Iterator[dict[str, Any]]:
    for s in ctx.store.read_scores(run.project, run.run_id):
        if s.error is None and s.value is not None:
            yield {"metric": s.metric, "version": s.version, "key": s.key, "value": s.value}


def _metrics(ctx: Context, run: RunRecord, _refs: _Refs) -> Iterator[dict[str, Any]]:
    for p in ctx.store.read_metric_points(run.project, run.run_id):
        yield {"name": p.name, "step": p.step, "value": p.value, "t": p.t}


def _dataset_references(ctx: Context, project: str, task: str | None) -> dict[str, Any]:
    if task is None:
        return {}
    try:
        repo = Path(ctx.store.load_project(project).repo)
        config = load_project_config(repo)
        spec = config.tasks[task]
        ds = config.datasets[spec.dataset]
        path = resolve_dataset_path(repo, ds.path_for(spec.split))
    except (StoreError, ConfigError, KeyError):
        return {}
    return {
        str(r[ds.id_field]): r.get(ds.reference_field) for r in read_jsonl(path) if ds.id_field in r
    }


def _predictions(ctx: Context, run: RunRecord, refs: _Refs) -> Iterator[dict[str, Any]]:
    pred_dir = ctx.run_dir(run) / "predictions"
    rows = [r for r in read_jsonl(pred_dir / "predictions.jsonl") if "id" in r]
    if not rows:
        return
    per_example: dict[str, dict[str, dict[str, Any]]] = {}
    for path in sorted(pred_dir.glob("scores.*.jsonl")):
        ref = path.name[len("scores.") : -len(".jsonl")]
        per_example[ref] = {
            str(r["id"]): {k: v for k, v in r.items() if k != "id"}
            for r in read_jsonl(path)
            if "id" in r
        }
    key = (run.project, run.task)
    if any("reference" not in r for r in rows) and key not in refs:
        refs[key] = _dataset_references(ctx, run.project, run.task)
    for r in rows:
        ex_id = str(r["id"])
        row: dict[str, Any] = {
            "id": ex_id,
            "prediction": r.get("prediction"),
            "reference": r["reference"] if "reference" in r else refs[key].get(ex_id),
        }
        meta = r.get("meta")
        if isinstance(meta, dict):
            row.update(_flat("meta", meta))
        for ref, per in per_example.items():
            for field, value in per.get(ex_id, {}).items():
                row[f"{ref}.{field}"] = value
        yield row


def _samples(ctx: Context, run: RunRecord, _refs: _Refs) -> Iterator[dict[str, Any]]:
    for name, values in ctx.store.read_samples(run.project, run.run_id).items():
        for value in values:
            yield {"name": name, "value": value}


def _usage(ctx: Context, run: RunRecord, _refs: _Refs) -> Iterator[dict[str, Any]]:
    for row in ctx.store.read_usage(run.project, run.run_id):
        yield row.model_dump()


def _traces(ctx: Context, run: RunRecord, _refs: _Refs) -> Iterator[dict[str, Any]]:
    for summary in ctx.store.list_traces(run.project, run.run_id):
        example_id = summary["example_id"]
        for step in ctx.store.read_trace(run.project, run.run_id, example_id):
            yield {"example_id": example_id, **step.model_dump()}


_READERS: dict[str, Callable[[Context, RunRecord, _Refs], Iterator[dict[str, Any]]]] = {
    "runs": _runs,
    "scores": _scores,
    "metrics": _metrics,
    "predictions": _predictions,
    "samples": _samples,
    "usage": _usage,
    "traces": _traces,
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_sources.py -v`
Expected: `12 passed`.

Run: `uv run ruff check src/hypothex/core/sources.py tests/core/test_sources.py && uv run ruff format --check src/hypothex/core/sources.py tests/core/test_sources.py && uv run ty check src/hypothex/core/sources.py tests/core/test_sources.py`
Expected: `All checks passed!`, `2 files already formatted`, and `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/sources.py tests/core/test_sources.py
git commit -m "feat: flat row sources over run folders for views"
```

---

### Task 19: View context (known metrics and fields for validation)

**Files:**
- Modify: `src/hypothex/core/views.py` (import block, constants after `VEGA_ROOT_KEYS`, append function)
- Test: `tests/core/test_views.py` (import block, append tests)

**Interfaces:**
- Consumes: `hypothex.core.sources.iter_rows(ctx, runs, source, fields=None)` (contract 1.5;
  every row has `run_id`, `group_id`, `seed`); `Context.store.load_project`,
  `Context.index.list_runs`, `.scores_for`, `.metric_points`, `Context.run_dir`;
  `tests.factories.seed_finished_run`; the `ctx` and `toy_repo` fixtures in `tests/conftest.py`.
  `sources` imports `Source` from this module, so `iter_rows` is imported inside the function
  to avoid an import cycle. This task runs after Task 18 because it needs `iter_rows`.
- Produces: `view_context(ctx: Context, project: str, task: str) -> tuple[set[str], dict[str, set[str]]]`.
  Metrics = the task's configured metrics ∪ scored metric names ∪ indexed step-metric names ∪
  sample series names (`RunStore.read_samples`, the original names, not the hashed file stems),
  over the newest `CONTEXT_RUNS = 20` runs (archived included).
  Fields = for every `Source`, the union of row keys over the first `CONTEXT_ROWS_PER_RUN = 500`
  rows per run (every source is a key, empty set if unseen). The API (`views/validate`, `PUT
  views/{name}`), CLI `hx view validate`/`add`, and MCP `add_view` pass these two values to
  `validate_view_text`.

- [ ] **Step 1: Write the failing tests**

In `tests/core/test_views.py`, replace the import block with:

```python
import json
from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from hypothex.core import config as core_config
from hypothex.core import views as core_views
from hypothex.core.config import ProjectConfig, TaskKind
from hypothex.core.context import Context
from hypothex.core.errors import ConfigError, StoreError
from hypothex.core.ids import utcnow
from hypothex.core.index import index_run
from hypothex.core.records import ScoreRecord
from hypothex.core.views import (
    PRESET_DIR,
    PanelData,
    PanelLayout,
    PanelSpec,
    RunFilter,
    ViewSpec,
    delete_view,
    get_view,
    list_views,
    load_preset,
    resolve_view,
    save_view,
    validate_view_text,
    view_context,
    views_dir,
)
from tests.factories import seed_finished_run
```

Append to the end of `tests/core/test_views.py`:

```python
# ---- view_context ----


def test_view_context_collects_metrics_and_fields(ctx: Context, toy_repo: Path) -> None:
    preds = [{"id": "ex-0", "prediction": 0}, {"id": "ex-1", "prediction": 1}]
    record = seed_finished_run(ctx, toy_repo, "r1", predictions=preds, seed=1)
    ctx.add_score(
        record,
        ScoreRecord(metric="accuracy", version="v1", key="value", value=0.5, created_at=utcnow()),
    )
    run_dir = ctx.run_dir(record)
    (run_dir / "metrics.jsonl").write_text(
        "".join(
            json.dumps({"name": "train_loss", "step": s, "value": 1.0 / s}) + "\n" for s in (1, 2)
        )
    )
    index_run(ctx.index, ctx.store, record)
    (run_dir / "samples").mkdir()
    (run_dir / "samples" / "latency_ms.jsonl").write_text('{"value": 12.5}\n')

    metrics, fields = view_context(ctx, "toy", "toy-acc")

    assert metrics == {"accuracy", "train_loss", "latency_ms"}
    assert set(fields) == {"runs", "scores", "metrics", "predictions", "samples", "usage", "traces"}
    assert {"run_id", "group_id", "seed", "metric", "version", "key", "value"} <= fields["scores"]
    assert {"run_id", "group_id", "seed", "name", "step", "value"} <= fields["metrics"]
    assert {"run_id", "id", "prediction"} <= fields["predictions"]
    assert {"run_id", "name", "value"} <= fields["samples"]
    assert {"run_id", "status", "created_by"} <= fields["runs"]
    assert fields["traces"] == set()


def test_view_context_without_runs_has_config_metrics_only(ctx: Context, toy_repo: Path) -> None:
    ctx.register_project(toy_repo)
    metrics, fields = view_context(ctx, "toy", "toy-acc")
    assert metrics == {"accuracy"}
    assert all(seen == set() for seen in fields.values())
```

The field assertions use `<=` (subset) because contract 1.5 fixes these keys but the sources
module may add more; the metric set is exact: `accuracy` (task config and score), `train_loss`
(`metrics.jsonl`, indexed by `index_run`), `latency_ms` (`samples/latency_ms.jsonl`). The toy
project's other metric, `broken`, is not in task `toy-acc`, so it is absent.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/core/test_views.py -q`
Expected: FAIL at collection with `ImportError: cannot import name 'view_context' from 'hypothex.core.views'`.

- [ ] **Step 3: Implement `view_context`**

In `src/hypothex/core/views.py`, replace the import block (ending just above `PanelType = Literal[`) with:

```python
"""Views: YAML dashboards of panels, the preset view of each task kind, and validation."""

from __future__ import annotations

import difflib
import re
from datetime import datetime
from itertools import islice
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, get_args

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from hypothex.core.config import (
    CONFIG_FILENAME,
    RESERVED_VIEW_NAMES,
    VIEW_NAME_PATTERN,
    YAML_CYCLE,
    ProjectConfig,
    TaskKind,
    TaskSpec,
    has_cycle,
    scan_yaml,
)
from hypothex.core.errors import ConfigError, StoreError
from hypothex.core.fsutil import atomic_write_text
from hypothex.core.records import RunStatus

if TYPE_CHECKING:
    from pydantic_core import ErrorDetails

    from hypothex.core.context import Context
```

Insert directly after the line `VEGA_ROOT_KEYS = frozenset({"mark", "layer", "concat", "hconcat", "vconcat", "facet", "repeat"})`:

```python
CONTEXT_RUNS = 20
CONTEXT_ROWS_PER_RUN = 500
```

Append to the end of `src/hypothex/core/views.py`:

```python
def view_context(ctx: Context, project: str, task: str) -> tuple[set[str], dict[str, set[str]]]:
    """
    Collect the metric names and per-source row fields a task's runs have.

    Reads the task's newest ``CONTEXT_RUNS`` runs (archived included). Metric names
    are the task's configured metrics plus every scored metric, logged step metric,
    and sample series name (``RunStore.read_samples``). Fields are the keys of the first
    ``CONTEXT_ROWS_PER_RUN`` rows per run of each source (``sources.iter_rows``).

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    project : str
        Project name.
    task : str
        Task name.

    Returns
    -------
    tuple of (set of str, dict of str to set of str)
        Known metric names, and field names per source (every source is a key).
    """
    from hypothex.core.sources import iter_rows  # sources imports this module

    config = ctx.store.load_project(project).config
    metrics: set[str] = set(config.tasks[task].metrics) if task in config.tasks else set()
    runs = ctx.index.list_runs(
        project=project, task=task, include_archived=True, limit=CONTEXT_RUNS
    )
    for scores in ctx.index.scores_for(r.run_id for r in runs).values():
        metrics.update(s.metric for s in scores)
    for record in runs:
        metrics.update(p.name for p in ctx.index.metric_points(record.run_id))
        metrics.update(ctx.store.read_samples(record.project, record.run_id))
    fields: dict[str, set[str]] = {}
    for source in get_args(Source):
        seen: set[str] = set()
        for record in runs:
            for row in islice(iter_rows(ctx, [record], source), CONTEXT_ROWS_PER_RUN):
                seen.update(row)
        fields[source] = seen
    return metrics, fields
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/core/test_views.py -q`
Expected: `62 passed`.

Run: `uv run ruff format --check src/hypothex/core/views.py tests/core/test_views.py && uv run ruff check src/hypothex/core/views.py tests/core/test_views.py && uv run ty check src/hypothex/core/views.py tests/core/test_views.py && uv run python -m doctest src/hypothex/core/views.py && echo doctest-ok`
Expected: `2 files already formatted`, `All checks passed!`, `All checks passed!`, `doctest-ok`.

Run the whole suite: `uv run pytest -q`
Expected: all tests pass (no failures).

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/views.py tests/core/test_views.py
git commit -m "feat: collect known metrics and fields for view validation"
```

---

### Task 20: Panel engine core: run selection, leaderboard, stat strip, table, vega-lite, trace, markdown

**Files:**
- Create: `src/hypothex/core/panels.py`
- Test: `tests/core/test_panels.py`

**Interfaces:**
- Consumes: Task 18 (`iter_rows`, `select_fields`); `views.VERSION_REF`, `views.vega_spec_problems` (Task 16); `leaderboard.group_id_for` (Task 10); `RunStore.list_traces`, `RunStore.read_trace` (Task 6); `queries.refresh_project(ctx, project) -> ProjectEntry` and `queries.primary_examples` (Task 14); `leaderboard.build_leaderboard(project, task, config, runs, scores, versions=None, *, per_example=None) -> Leaderboard` with `headline`, `stat_strip`, rows with `label` (contract 1.7); `views.PanelSpec`, `PanelType`, `RunFilter`, `ViewSpec`, `PanelData` (contract 1.4); `ctx.index.list_runs`, `ctx.index.scores_for`, `ctx.find_record`.
- Produces (`hypothex.core.panels`):
  - `class PanelResult(BaseModel)`: `type: PanelType`, `title: str`, `rows: list[dict[str, Any]]`, `meta: dict[str, Any] = {}`.
  - `query_panel(ctx: Context, project: str, task: str, panel: PanelSpec, runs_filter: RunFilter | None = None) -> PanelResult` — `markdown` and `trace` with `data.run_id` never touch the task (the run-trace API route can call it for exploratory runs); unknown task → `ConfigError("unknown task ...")`.
  - `query_view(ctx: Context, project: str, task: str, view: ViewSpec) -> list[PanelResult]` — view must already be resolved; `view.runs` applies to every panel; per-panel `HypothexError` → `meta.error`.
  - `MAX_TABLE_ROWS = 5000`.
  - Row shapes in this task: `stat_strip` rows = `Leaderboard.stat_strip`, `meta.headline`; `leaderboard` rows = `LeaderboardRow.model_dump(mode="json")`, `meta` = `headline, primary, higher_is_better, metric_versions, noise, needs_reeval, unscored`; `table`/`vega_lite` rows = `iter_rows(..., source or "runs")` filtered by `data.filter` on the full row, then projected to `fields` with `sources.select_fields` (so a filter may use a field the table does not show), `meta` = `source, total[, warnings]` (+ `spec` for vega-lite); every `runs` row carries the synthetic field `version` (`views.VERSION_REF`, spec 8.4), set on the full row before `data.filter` runs and whatever `fields` lists, so `filter: {version: p10}` works on a table that does not show `version`: the run's `TaskSpec.version_param` param, else the creation time (`YYYY-MM-DD HH:MM:SS`, UTC) of the first selected run of its seed group; `vega_lite` replaces the root `data` with `{"values": []}` and raises `ConfigError("<problem> at spec.<path>")` when `views.vega_spec_problems` finds any other external resource or image mark (a panel error in `query_view`); `trace` rows = eight trace keys, `meta` = `run_id, example_id, failed_turn[, warnings]` (no `data.run_id`: newest selected run with traces, first failing example else first example); `markdown` rows `[]`, `meta.text`.
  - Private helpers later tasks use: `_Scope` (`ctx`, `entry`, `task`, `runs`, `board()`, `board_labels()`), `_HANDLERS: dict[str, Callable[[_Scope, PanelSpec], PanelResult]]`, `_row_matches`, `_build_board`, `_run_versions(scope) -> dict[str, tuple[bool, str]]` (run id → (whether the value is the version param, version text); Task 22's ordinal x uses it).

- [ ] **Step 1: Write the failing tests**

`tests/core/test_panels.py`:

```python
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from hypothex.core import panels
from hypothex.core import queries as q
from hypothex.core.context import Context
from hypothex.core.errors import ConfigError
from hypothex.core.ids import utcnow
from hypothex.core.panels import PanelResult, query_panel, query_view
from hypothex.core.records import GitInfo, RunRecord, RunStatus, ScoreRecord
from hypothex.core.store import safe_stem
from hypothex.core.views import PanelData, PanelSpec, RunFilter, ViewSpec
from tests.factories import make_record

T0 = utcnow()


def _run(
    ctx: Context, repo: Path, run_id: str, group: str = "aaaa", *, minute: int = 0, **kw: Any
) -> RunRecord:
    """Create a finished toy-acc run in seed group ``<group>@c1``."""
    ctx.register_project(repo)
    fields: dict[str, Any] = {
        "task": "toy-acc",
        "status": RunStatus.FINISHED,
        "config_hash": f"sha256:{group}",
        "git": GitInfo(commit="c1"),
        "created_at": T0 + timedelta(minutes=minute),
        "cwd": str(repo),
        "environment_id": ctx.descriptor.environment_id,
    }
    fields.update(kw)
    return ctx.create_run(make_record(run_id, project="toy", **fields))


def _score(ctx: Context, rec: RunRecord, value: float) -> None:
    ctx.add_score(
        rec, ScoreRecord(metric="accuracy", version="v1", key="value", value=value, created_at=T0)
    )


def _jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def _panel(type_: str, **kw: Any) -> PanelSpec:
    data = kw.pop("data", {})
    return PanelSpec.model_validate({"type": type_, "title": "p", "data": data, **kw})


def _ids(result: PanelResult) -> list[str]:
    return [row["run_id"] for row in result.rows]


def _set_task(repo: Path, **fields: Any) -> None:
    """Change toy-acc's entry in ``hypothex.yaml``; every query re-reads the config."""
    path = repo / "hypothex.yaml"
    config = yaml.safe_load(path.read_text())
    config["tasks"]["toy-acc"].update(fields)
    path.write_text(yaml.safe_dump(config, sort_keys=False))


# markdown, stat strip, leaderboard ----------------------------------------------
def test_markdown_panel(ctx: Context) -> None:
    result = query_panel(ctx, "nope", "nope", _panel("markdown", text="**hi**"))
    assert result == PanelResult(type="markdown", title="p", rows=[], meta={"text": "**hi**"})


def _two_groups(ctx: Context, repo: Path) -> None:
    for rid, group, seed, value, minute in [
        ("s1", "aaaa", 1, 0.8, 0),
        ("s2", "aaaa", 2, 0.9, 1),
        ("f1", "bbbb", 1, 0.6, 2),
    ]:
        rec = _run(
            ctx,
            repo,
            rid,
            group,
            seed=seed,
            minute=minute,
            hypothesis="svm" if group == "aaaa" else "rf",
            params={"model": "svm" if group == "aaaa" else "rf"},
        )
        _score(ctx, rec, value)


def test_leaderboard_and_stat_strip_match_task_leaderboard(ctx: Context, toy_repo: Path) -> None:
    _two_groups(ctx, toy_repo)
    board = q.get_leaderboard(ctx, "toy/toy-acc")

    lb = query_panel(ctx, "toy", "toy-acc", _panel("leaderboard", noise=["seed"]))
    assert [r["group_id"] for r in lb.rows] == ["aaaa@c1", "bbbb@c1"]
    assert lb.rows == [row.model_dump(mode="json") for row in board.rows]
    assert lb.rows[0]["primary"]["mean"] == pytest.approx(0.85)
    assert lb.rows[0]["label"] == "svm"
    assert lb.meta["primary"] == "accuracy/value"
    assert lb.meta["noise"] == ["seed"]
    assert lb.meta["headline"] == board.headline

    strip = query_panel(ctx, "toy", "toy-acc", _panel("stat_strip"))
    assert strip.rows == board.stat_strip
    assert strip.meta == {"headline": board.headline}


def test_data_filter_selects_runs_by_flattened_fields(ctx: Context, toy_repo: Path) -> None:
    _two_groups(ctx, toy_repo)
    panel = _panel("leaderboard", data={"filter": {"params.model": "rf"}})
    result = query_panel(ctx, "toy", "toy-acc", panel)
    assert [r["group_id"] for r in result.rows] == ["bbbb@c1"]


# run selection -------------------------------------------------------------------
def test_run_filter_status_tags_created_by_since(ctx: Context, toy_repo: Path) -> None:
    _run(ctx, toy_repo, "a", minute=0, tags=["baseline", "x"])
    _run(ctx, toy_repo, "b", minute=1, status=RunStatus.FAILED, created_by="agent:claude")
    _run(ctx, toy_repo, "c", minute=2, created_by="agent:claude", tags=["x"])
    _run(ctx, toy_repo, "d", minute=3, archived=True)
    table = _panel("table", data={"source": "runs", "fields": []})

    def ids(flt: RunFilter | None) -> list[str]:
        return _ids(query_panel(ctx, "toy", "toy-acc", table, flt))

    assert ids(None) == ["a", "b", "c"]  # oldest first, archived hidden
    assert ids(RunFilter(status=["finished"])) == ["a", "c"]
    assert ids(RunFilter(tags=["x"])) == ["a", "c"]
    assert ids(RunFilter(tags=["baseline", "x"])) == ["a"]
    assert ids(RunFilter(created_by="agent:claude")) == ["b", "c"]
    since_naive = (T0 + timedelta(minutes=1)).replace(tzinfo=None)
    assert ids(RunFilter(since=since_naive)) == ["b", "c"]


def test_pick_latest_and_best(ctx: Context, toy_repo: Path) -> None:
    _two_groups(ctx, toy_repo)
    table = {"source": "runs", "fields": []}
    latest = query_panel(ctx, "toy", "toy-acc", _panel("table", data={**table, "pick": "latest"}))
    assert _ids(latest) == ["s2", "f1"]
    best = query_panel(ctx, "toy", "toy-acc", _panel("table", data={**table, "pick": "best"}))
    assert _ids(best) == ["s1", "s2"]
    everything = query_panel(ctx, "toy", "toy-acc", _panel("table", data={**table, "pick": "all"}))
    assert _ids(everything) == ["s1", "s2", "f1"]


def test_unknown_task_raises(ctx: Context, toy_repo: Path) -> None:
    ctx.register_project(toy_repo)
    with pytest.raises(ConfigError, match="unknown task 'nope'"):
        query_panel(ctx, "toy", "nope", _panel("leaderboard"))


# table and vega-lite --------------------------------------------------------------
def test_table_source_fields_and_row_filter(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "u1", seed=4)
    _jsonl(
        ctx.run_dir(rec) / "usage.jsonl",
        [{"example_id": "ex-0", "usd": 0.5}, {"example_id": "ex-1", "usd": 0.25}],
    )
    panel = _panel(
        "table",
        data={"source": "usage", "fields": ["example_id", "usd"], "filter": {"example_id": "ex-1"}},
    )
    result = query_panel(ctx, "toy", "toy-acc", panel)
    assert result.rows == [
        {"run_id": "u1", "group_id": "aaaa@c1", "seed": 4, "example_id": "ex-1", "usd": 0.25}
    ]
    assert result.meta == {"source": "usage", "total": 1}


def test_table_filters_full_rows_before_projecting(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "r1", seed=2)
    _score(ctx, rec, 0.75)
    ctx.add_score(
        rec, ScoreRecord(metric="broken", version="v1", key="value", value=0.5, created_at=T0)
    )
    # the filter reads "metric", which the table does not show
    panel = _panel(
        "table",
        data={"source": "scores", "fields": ["value"], "filter": {"metric": "accuracy"}},
    )
    result = query_panel(ctx, "toy", "toy-acc", panel)
    assert result.rows == [{"run_id": "r1", "group_id": "aaaa@c1", "seed": 2, "value": 0.75}]
    assert result.meta == {"source": "scores", "total": 1}


def test_runs_table_version_field(ctx: Context, toy_repo: Path) -> None:
    _run(ctx, toy_repo, "a", minute=0, params={"version": "v2", "prompt_version": "p7"})
    _run(ctx, toy_repo, "b", "bbbb", minute=1)  # no version param: its group's first run time
    _run(ctx, toy_repo, "c", "bbbb", minute=2)
    panel = _panel("table", data={"source": "runs", "fields": ["version"]})
    first_b = (T0 + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    rows = query_panel(ctx, "toy", "toy-acc", panel).rows
    assert [(r["run_id"], r["version"]) for r in rows] == [
        ("a", "v2"),
        ("b", first_b),
        ("c", first_b),
    ]
    _set_task(toy_repo, version_param="prompt_version")
    rows = query_panel(ctx, "toy", "toy-acc", panel).rows
    assert [r["version"] for r in rows] == ["p7", first_b, first_b]


def test_runs_table_filters_on_version_it_does_not_show(ctx: Context, toy_repo: Path) -> None:
    # regression: `version` was added only when `fields` listed it, so this matched nothing
    _run(ctx, toy_repo, "a", minute=0, seed=1, params={"version": "p10"})
    _run(ctx, toy_repo, "b", "bbbb", minute=1, seed=1, params={"version": "p9"})
    _run(ctx, toy_repo, "c", "cccc", minute=2, seed=1)  # no param: a creation time
    panel = _panel(
        "table", data={"source": "runs", "fields": ["status"], "filter": {"version": "p10"}}
    )
    result = query_panel(ctx, "toy", "toy-acc", panel)
    assert result.rows == [{"run_id": "a", "group_id": "aaaa@c1", "seed": 1, "status": "finished"}]
    assert result.meta == {"source": "runs", "total": 1}
    everything = query_panel(ctx, "toy", "toy-acc", _panel("table", data={"source": "runs"}))
    assert [r["version"] for r in everything.rows][:2] == ["p10", "p9"]  # no fields: shown


def test_table_truncates_large_sources(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(panels, "MAX_TABLE_ROWS", 2)
    rec = _run(ctx, toy_repo, "u1")
    _jsonl(ctx.run_dir(rec) / "samples" / "lat.jsonl", [{"value": v} for v in range(5)])
    result = query_panel(ctx, "toy", "toy-acc", _panel("table", data={"source": "samples"}))
    assert [r["value"] for r in result.rows] == [0.0, 1.0]
    assert result.meta["total"] == 5
    assert result.meta["warnings"] == ["showing the first 2 of 5 rows"]


def test_vega_lite_spec_has_empty_values(ctx: Context, toy_repo: Path) -> None:
    _run(ctx, toy_repo, "r1", params={"lr": "0.1"})
    spec = {
        "mark": "point",
        "data": {"url": "https://example.com/x.json"},
        "encoding": {"x": {"field": "params.lr", "type": "quantitative"}},
    }
    panel = _panel("vega_lite", spec=spec, data={"source": "runs", "fields": ["params.lr"]})
    result = query_panel(ctx, "toy", "toy-acc", panel)
    assert result.meta["spec"] == {
        "mark": "point",
        "data": {"values": []},
        "encoding": {"x": {"field": "params.lr", "type": "quantitative"}},
    }
    assert panel.spec is not None and panel.spec["data"] == {"url": "https://example.com/x.json"}
    assert result.rows == [
        {"run_id": "r1", "group_id": "aaaa@c1", "seed": None, "params.lr": "0.1"}
    ]


def test_vega_lite_nested_external_data_is_a_panel_error(ctx: Context, toy_repo: Path) -> None:
    _run(ctx, toy_repo, "r1")
    spec = {
        "layer": [
            {"mark": "point"},
            {"mark": "line", "data": {"url": "https://example.com/x.json"}},
        ]
    }
    panel = _panel("vega_lite", spec=spec, data={"source": "runs"})
    with pytest.raises(ConfigError, match=r"resources \(url\) at spec\.layer\.1\.data\.url"):
        query_panel(ctx, "toy", "toy-acc", panel)
    # views that were never validated (inline, editor preview): one panel error, not a 500
    (result,) = query_view(ctx, "toy", "toy-acc", ViewSpec(title="v", panels=[panel]))
    assert result.rows == []
    assert result.meta["error"].startswith("vega_lite spec must not load external resources")


# trace --------------------------------------------------------------------------
def _write_trace(ctx: Context, rec: RunRecord, example_id: str, fail: bool) -> None:
    steps = [
        {
            "turn": 1,
            "tool": "search",
            "args": {"q": "x"},
            "result": "ok",
            "tokens_in": 10,
            "tokens_out": 5,
            "seconds": 0.5,
        },
        {
            "turn": 2,
            "tool": "edit",
            "args": {},
            "result": None,
            "tokens_in": 3,
            "tokens_out": 1,
            "seconds": 0.25,
            "error": "patch failed" if fail else None,
        },
    ]
    _jsonl(ctx.run_dir(rec) / "traces" / f"{safe_stem(example_id)}.jsonl", steps)


def test_trace_panel_for_explicit_run_and_example(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "t1")
    _write_trace(ctx, rec, "ex/1", fail=True)
    panel = _panel("trace", data={"run_id": "t1", "example_id": "ex/1"})
    result = query_panel(ctx, "toy", "any-task", panel)
    assert result.rows == [
        {
            "turn": 1,
            "tool": "search",
            "args": {"q": "x"},
            "result": "ok",
            "tokens_in": 10,
            "tokens_out": 5,
            "seconds": 0.5,
            "error": None,
        },
        {
            "turn": 2,
            "tool": "edit",
            "args": {},
            "result": None,
            "tokens_in": 3,
            "tokens_out": 1,
            "seconds": 0.25,
            "error": "patch failed",
        },
    ]
    assert result.meta == {"run_id": "t1", "example_id": "ex/1", "failed_turn": 2}


def test_trace_panel_missing_example_warns(ctx: Context, toy_repo: Path) -> None:
    _run(ctx, toy_repo, "t1")
    panel = _panel("trace", data={"run_id": "t1", "example_id": "nope"})
    result = query_panel(ctx, "toy", "toy-acc", panel)
    assert result.rows == []
    assert result.meta["failed_turn"] is None
    assert result.meta["warnings"] == ["no trace for example 'nope' in run t1"]


def test_trace_panel_picks_latest_run_and_failing_example(ctx: Context, toy_repo: Path) -> None:
    old = _run(ctx, toy_repo, "t1", minute=0)
    new = _run(ctx, toy_repo, "t2", minute=1)
    _run(ctx, toy_repo, "t3", minute=2)  # no traces
    _write_trace(ctx, old, "ex-9", fail=True)
    _write_trace(ctx, new, "ex-a", fail=False)
    _write_trace(ctx, new, "ex-b", fail=True)
    result = query_panel(ctx, "toy", "toy-acc", _panel("trace"))
    assert result.meta == {"run_id": "t2", "example_id": "ex-b", "failed_turn": 2}


def test_trace_panel_without_traces(ctx: Context, toy_repo: Path) -> None:
    _run(ctx, toy_repo, "t1")
    result = query_panel(ctx, "toy", "toy-acc", _panel("trace"))
    assert result.rows == []
    assert result.meta["warnings"] == ["no run in this view has traces"]


# views ------------------------------------------------------------------------------
def test_query_view_applies_run_filter_and_isolates_errors(ctx: Context, toy_repo: Path) -> None:
    _run(ctx, toy_repo, "a", minute=0)
    _run(ctx, toy_repo, "b", minute=1, status=RunStatus.FAILED)
    view = ViewSpec(
        title="v",
        runs=RunFilter(status=["finished"]),
        panels=[
            PanelSpec(type="markdown", title="notes", text="hi"),
            PanelSpec(type="trace", title="bad", data=PanelData(run_id="missing")),
            PanelSpec(type="table", title="runs", data=PanelData(source="runs", fields=[])),
        ],
    )
    notes, bad, runs = query_view(ctx, "toy", "toy-acc", view)
    assert notes.meta == {"text": "hi"}
    assert (bad.type, bad.title, bad.rows) == ("trace", "bad", [])
    assert "missing" in bad.meta["error"]
    assert _ids(runs) == ["a"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_panels.py -v`
Expected: collection ERROR with `ModuleNotFoundError: No module named 'hypothex.core.panels'`.

- [ ] **Step 3: Implement the engine core**

`src/hypothex/core/panels.py`:

```python
"""Panel query engine: turn a view panel into rows the UI can draw."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import UTC
from typing import Any

from pydantic import BaseModel, Field

from hypothex.core.context import Context
from hypothex.core.errors import ConfigError, HypothexError
from hypothex.core.leaderboard import Leaderboard, build_leaderboard, group_id_for
from hypothex.core.queries import primary_examples, refresh_project
from hypothex.core.records import RunRecord
from hypothex.core.sources import iter_rows, select_fields
from hypothex.core.store import ProjectEntry
from hypothex.core.views import (
    VERSION_REF,
    PanelSpec,
    PanelType,
    RunFilter,
    ViewSpec,
    vega_spec_problems,
)

MAX_TABLE_ROWS = 5000


class PanelResult(BaseModel):
    """
    Computed data of one panel.

    Attributes
    ----------
    type : str
        Panel type, copied from the panel spec.
    title : str
        Panel title, copied from the panel spec.
    rows : list of dict
        Rows whose shape depends on ``type``.
    meta : dict
        Axis names, headline, groups, events, warnings, and other extras.
    """

    type: PanelType
    title: str
    rows: list[dict[str, Any]]
    meta: dict[str, Any] = Field(default_factory=dict)


@dataclass
class _Scope:
    """The runs a panel sees plus lazily built task-level data."""

    ctx: Context
    entry: ProjectEntry
    task: str
    runs: list[RunRecord]
    _board: Leaderboard | None = None

    def board(self) -> Leaderboard:
        """Leaderboard over this scope's runs (built once)."""
        if self._board is None:
            self._board = _build_board(self.ctx, self.entry, self.task, self.runs)
        return self._board

    def board_labels(self) -> dict[str, str]:
        """Leaderboard label per seed-group id."""
        return {row.group_id: row.label for row in self.board().rows}


def query_panel(
    ctx: Context,
    project: str,
    task: str,
    panel: PanelSpec,
    runs_filter: RunFilter | None = None,
) -> PanelResult:
    """
    Compute one panel's rows.

    ``markdown`` panels and ``trace`` panels with ``data.run_id`` need no task
    config; every other panel reads the task's runs (unarchived, oldest first),
    narrowed by ``runs_filter``, ``data.filter`` (matched against the flattened
    ``runs`` row; for ``table``/``vega_lite`` matched against each source row
    instead), and ``data.pick``.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    project : str
        Project name.
    task : str
        Task name.
    panel : PanelSpec
        The panel to compute.
    runs_filter : RunFilter, optional
        The view's run filter.

    Returns
    -------
    PanelResult
        Rows shaped per panel type (see the phase 1b contract, section 1.6).

    Raises
    ------
    ConfigError
        If the task does not exist or the panel lacks a required field.

    Examples
    --------
    >>> panel = PanelSpec(type="markdown", text="hello")
    >>> query_panel(ctx, "toy", "toy-acc", panel).meta  # doctest: +SKIP
    {'text': 'hello'}
    """
    return _panel(ctx, project, task, panel, runs_filter, {})


def query_view(ctx: Context, project: str, task: str, view: ViewSpec) -> list[PanelResult]:
    """
    Compute every panel of a view, in order.

    The view must already be resolved (``views.get_view`` returns resolved
    views). A panel that fails with a Hypothex error yields an empty result
    whose ``meta.error`` holds the message, so one bad panel never hides the
    others.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    project : str
        Project name.
    task : str
        Task name.
    view : ViewSpec
        Resolved view; its ``runs`` filter applies to every panel.

    Returns
    -------
    list of PanelResult
        One result per panel.

    Examples
    --------
    >>> [r.type for r in query_view(ctx, "toy", "toy-acc", view)]  # doctest: +SKIP
    ['stat_strip', 'leaderboard']
    """
    entries: dict[str, ProjectEntry] = {}
    out: list[PanelResult] = []
    for panel in view.panels:
        try:
            out.append(_panel(ctx, project, task, panel, view.runs, entries))
        except HypothexError as exc:
            out.append(
                PanelResult(type=panel.type, title=panel.title, rows=[], meta={"error": str(exc)})
            )
    return out


def _panel(
    ctx: Context,
    project: str,
    task: str,
    panel: PanelSpec,
    runs_filter: RunFilter | None,
    entries: dict[str, ProjectEntry],
) -> PanelResult:
    """Dispatch one panel; ``entries`` caches refreshed projects across a view."""
    if panel.type == "markdown":
        return _markdown(panel)
    if panel.type == "trace" and panel.data.run_id:
        return _trace_for(ctx, panel, panel.data.run_id, panel.data.example_id)
    if project not in entries:
        entries[project] = refresh_project(ctx, project)
    return _query(ctx, entries[project], task, panel, runs_filter)


def _query(
    ctx: Context,
    entry: ProjectEntry,
    task: str,
    panel: PanelSpec,
    runs_filter: RunFilter | None,
) -> PanelResult:
    if task not in entry.config.tasks:
        raise ConfigError(f"unknown task {task!r} in project {entry.project!r}")
    runs = ctx.index.list_runs(project=entry.project, task=task, limit=None)
    runs.sort(key=lambda r: (r.created_at, r.run_id))
    if runs_filter is not None:
        runs = [r for r in runs if _run_matches(r, runs_filter)]
    if panel.data.filter and panel.type not in ("table", "vega_lite"):
        keep = {
            row["run_id"]
            for row in iter_rows(ctx, runs, "runs")
            if _row_matches(row, panel.data.filter)
        }
        runs = [r for r in runs if r.run_id in keep]
    if panel.data.pick == "latest":
        latest = {group_id_for(r): r.run_id for r in runs}
        runs = [r for r in runs if r.run_id in set(latest.values())]
    elif panel.data.pick == "best":
        board_rows = _build_board(ctx, entry, task, runs).rows
        best = set(board_rows[0].run_ids) if board_rows else set()
        runs = [r for r in runs if r.run_id in best]
    scope = _Scope(ctx=ctx, entry=entry, task=task, runs=runs)
    return _HANDLERS[panel.type](scope, panel)


def _run_matches(run: RunRecord, f: RunFilter) -> bool:
    if f.status is not None and run.status.value not in f.status:
        return False
    if f.tags is not None and not set(f.tags) <= set(run.tags):
        return False
    if f.created_by is not None and run.created_by != f.created_by:
        return False
    if f.since is not None:
        since = f.since if f.since.tzinfo else f.since.replace(tzinfo=UTC)
        if run.created_at < since:
            return False
    return True


def _row_matches(row: dict[str, Any], flt: dict[str, Any]) -> bool:
    for key, want in flt.items():
        have = row.get(key)
        if isinstance(want, list):
            if have not in want:
                return False
        elif have != want:
            return False
    return True


def _build_board(
    ctx: Context, entry: ProjectEntry, task: str, runs: list[RunRecord]
) -> Leaderboard:
    per_example = primary_examples(ctx, entry.config, task, runs, None)
    scores = ctx.index.scores_for(r.run_id for r in runs)
    return build_leaderboard(
        entry.project, task, entry.config, runs, scores, per_example=per_example or None
    )


def _markdown(panel: PanelSpec) -> PanelResult:
    return PanelResult(type="markdown", title=panel.title, rows=[], meta={"text": panel.text or ""})


def _stat_strip(scope: _Scope, panel: PanelSpec) -> PanelResult:
    board = scope.board()
    return PanelResult(
        type="stat_strip",
        title=panel.title,
        rows=[dict(item) for item in board.stat_strip],
        meta={"headline": board.headline},
    )


def _leaderboard(scope: _Scope, panel: PanelSpec) -> PanelResult:
    board = scope.board()
    return PanelResult(
        type="leaderboard",
        title=panel.title,
        rows=[row.model_dump(mode="json") for row in board.rows],
        meta={
            "headline": board.headline,
            "primary": board.primary,
            "higher_is_better": board.higher_is_better,
            "metric_versions": board.metric_versions,
            "noise": list(panel.noise),
            "needs_reeval": board.needs_reeval,
            "unscored": board.unscored,
        },
    )


def _run_versions(scope: _Scope) -> dict[str, tuple[bool, str]]:
    """
    Run id -> (from the version param, version text) for every selected run.

    The text is the run param ``TaskSpec.version_param`` names; a run without
    it gets the creation time (UTC, ``YYYY-MM-DD HH:MM:SS``) of the first
    selected run of its seed group (spec 8.4). ``scope.runs`` is oldest first.
    """
    param = scope.entry.config.tasks[scope.task].version_param
    first: dict[str, RunRecord] = {}
    for r in scope.runs:
        first.setdefault(group_id_for(r), r)
    out: dict[str, tuple[bool, str]] = {}
    for r in scope.runs:
        value = r.params.get(param)
        if value is not None:
            out[r.run_id] = (True, value)
            continue
        created = first[group_id_for(r)].created_at
        created = created if created.tzinfo else created.replace(tzinfo=UTC)
        out[r.run_id] = (False, created.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"))
    return out


def _table_rows(scope: _Scope, panel: PanelSpec) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Source rows filtered on the full row, then projected to ``data.fields``.

    Filtering first lets ``data.filter`` use a field the table does not show. The
    synthetic ``version`` field (``VERSION_REF``) is set on every full ``runs`` row
    before the filter, whatever ``fields`` lists, so ``filter: {version: p10}``
    works on a table that shows only ``status``.
    """
    source = panel.data.source or "runs"
    fields = panel.data.fields
    versions = _run_versions(scope) if source == "runs" else {}
    rows: list[dict[str, Any]] = []
    total = 0
    for row in iter_rows(scope.ctx, scope.runs, source):
        if versions:
            row[VERSION_REF] = versions[row["run_id"]][1]
        if panel.data.filter and not _row_matches(row, panel.data.filter):
            continue
        total += 1
        if len(rows) < MAX_TABLE_ROWS:
            rows.append(select_fields(row, fields))
    meta: dict[str, Any] = {"source": source, "total": total}
    if total > MAX_TABLE_ROWS:
        meta["warnings"] = [f"showing the first {MAX_TABLE_ROWS} of {total} rows"]
    return rows, meta


def _table(scope: _Scope, panel: PanelSpec) -> PanelResult:
    rows, meta = _table_rows(scope, panel)
    return PanelResult(type="table", title=panel.title, rows=rows, meta=meta)


def _vega_lite(scope: _Scope, panel: PanelSpec) -> PanelResult:
    """
    Rows plus the spec with its root ``data`` replaced by ``{"values": []}``.

    Any other external resource (nested ``data.url``, lookup sources, image
    marks, ``href``, ``embedOptions``) raises: views that were never validated
    (inline in ``hypothex.yaml``, editor previews) reach this point too.
    """
    spec = copy.deepcopy(panel.spec or {})
    spec["data"] = {"values": []}
    problems = vega_spec_problems(spec)
    if problems:
        loc, message = problems[0]
        raise ConfigError(f"{message} at spec.{'.'.join(str(p) for p in loc)}")
    rows, meta = _table_rows(scope, panel)
    return PanelResult(type="vega_lite", title=panel.title, rows=rows, meta={**meta, "spec": spec})


def _trace_for(ctx: Context, panel: PanelSpec, run_id: str, example_id: str | None) -> PanelResult:
    record = ctx.find_record(run_id)
    if example_id is None:
        traces = ctx.store.list_traces(record.project, run_id)
        if not traces:
            return _empty_trace(panel, run_id, None, f"run {run_id} has no traces")
        failing = [t for t in traces if t["failed"]]
        example_id = str((failing or traces)[0]["example_id"])
    steps = ctx.store.read_trace(record.project, run_id, example_id)
    rows = [step.model_dump() for step in steps]
    meta: dict[str, Any] = {
        "run_id": run_id,
        "example_id": example_id,
        "failed_turn": next((r["turn"] for r in rows if r["error"]), None),
    }
    if not rows:
        meta["warnings"] = [f"no trace for example {example_id!r} in run {run_id}"]
    return PanelResult(type="trace", title=panel.title, rows=rows, meta=meta)


def _trace(scope: _Scope, panel: PanelSpec) -> PanelResult:
    for run in reversed(scope.runs):
        if any((scope.ctx.run_dir(run) / "traces").glob("*.jsonl")):
            return _trace_for(scope.ctx, panel, run.run_id, panel.data.example_id)
    return _empty_trace(panel, None, panel.data.example_id, "no run in this view has traces")


def _empty_trace(
    panel: PanelSpec, run_id: str | None, example_id: str | None, warning: str
) -> PanelResult:
    return PanelResult(
        type="trace",
        title=panel.title,
        rows=[],
        meta={
            "run_id": run_id,
            "example_id": example_id,
            "failed_turn": None,
            "warnings": [warning],
        },
    )


_HANDLERS = {
    "stat_strip": _stat_strip,
    "leaderboard": _leaderboard,
    "table": _table,
    "vega_lite": _vega_lite,
    "trace": _trace,
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_panels.py -v`
Expected: `18 passed`.

Run: `uv run ruff check src/hypothex/core/panels.py tests/core/test_panels.py && uv run ruff format --check src/hypothex/core/panels.py tests/core/test_panels.py && uv run ty check src/hypothex/core/panels.py`
Expected: `All checks passed!`, `2 files already formatted`, `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/panels.py tests/core/test_panels.py
git commit -m "feat: panel query engine with run selection, leaderboard, table, trace"
```

---

### Task 21: Curves panel: seed curves, spikes, kills, checkpoints

**Files:**
- Modify: `src/hypothex/core/panels.py` (imports/constants block, new functions above `_HANDLERS`, `_HANDLERS`)
- Test: `tests/core/test_panels.py` (records import line, append tests)

**Interfaces:**
- Consumes: Task 20 (`_Scope`, `PanelResult`, `_HANDLERS`); `records.Artifact` with `step: int | None`, `metrics: dict[str, float]` (contract 1.2); `ctx.store.read_metric_points`, `ctx.store.read_artifacts`.
- Produces:
  - `curves` rows `{run_id, group_id, seed, name, step, value}` (one per logged point of `data.metrics`, default all names except the x metric; x is `step` or the value of `data.step_metric` logged at the same step, points without it dropped); `meta` = `x, metrics, checkpoints: [{run_id, step, value, best}], events: [{run_id, step, kind}], groups: [{group_id, label}]`.
  - Spike rule (contract 1.6, exactly): for names containing `loss`, point `i ≥ 1` is a spike when `value > 5 × median(previous ≤ 20 values)`. There is no exemption for a zero median: `[0, 3]` spikes at the second point. `killed`/`failed` runs get an event at their last plotted x.
  - Checkpoints use the same x as the curves: with `data.step_metric`, a checkpoint's `step` is that metric's value logged at the checkpoint's training step, and a checkpoint without one is dropped (as curve points are).
  - Checkpoint value = `data.y` if set, else the first `data.metrics` name found in the checkpoint metrics, else the alphabetically first checkpoint metric; per run the best is the min for names containing `loss`/`error`, else the max.
  - `_groups(scope, panel) -> list[tuple[str, str, list[RunRecord]]]` and `_own_label(members, key) -> str` (used by Tasks 22 and 23; `_own_label` applies `leaderboard.group_label`, the one label rule); `_spikes(points: list[MetricPoint]) -> list[int]`; constants `SPIKE_WINDOW = 20`, `SPIKE_FACTOR = 5.0`.

- [ ] **Step 1: Write the failing tests**

In `tests/core/test_panels.py` replace the import line

```python
from hypothex.core.records import GitInfo, RunRecord, RunStatus, ScoreRecord
```

with

```python
from hypothex.core.records import GitInfo, MetricPoint, RunRecord, RunStatus, ScoreRecord
```

Append to the end of `tests/core/test_panels.py`:

```python
# curves --------------------------------------------------------------------------
def test_curves_rows_spikes_kills_and_checkpoints(ctx: Context, toy_repo: Path) -> None:
    c1 = _run(ctx, toy_repo, "c1", seed=1, hypothesis="baseline")
    c2 = _run(ctx, toy_repo, "c2", seed=2, minute=1, status=RunStatus.KILLED)
    loss = [{"name": "train/loss", "step": s, "value": 6.0 if s == 22 else 1.0} for s in range(25)]
    acc = [{"name": "val/acc", "step": s, "value": 100.0 if s == 10 else 0.5} for s in range(25)]
    _jsonl(ctx.run_dir(c1) / "metrics.jsonl", loss + acc)
    _jsonl(
        ctx.run_dir(c2) / "metrics.jsonl",
        [{"name": "train/loss", "step": s, "value": 1.0} for s in range(5)],
    )
    _jsonl(
        ctx.run_dir(c1) / "artifacts.jsonl",
        [
            {"kind": "checkpoint", "path": "/ck/10.pt", "step": 10, "metrics": {"val/acc": 0.5}},
            {"kind": "checkpoint", "path": "/ck/20.pt", "step": 20, "metrics": {"val/acc": 0.7}},
            {"kind": "model", "path": "/final.pt"},
        ],
    )
    panel = _panel("curves", data={"metrics": ["train/loss", "val/acc"]})
    result = query_panel(ctx, "toy", "toy-acc", panel)

    assert len(result.rows) == 55  # c1: 25 + 25 points, c2: 5 points
    assert result.rows[22] == {
        "run_id": "c1",
        "group_id": "aaaa@c1",
        "seed": 1,
        "name": "train/loss",
        "step": 22,
        "value": 6.0,
    }
    # step 22: 6.0 > 5 x median(previous 20 values = 1.0); val/acc jumps are ignored (no "loss")
    assert result.meta["events"] == [
        {"run_id": "c1", "step": 22, "kind": "spike"},
        {"run_id": "c2", "step": 4, "kind": "killed"},
    ]
    assert result.meta["checkpoints"] == [
        {"run_id": "c1", "step": 10, "value": 0.5, "best": False},
        {"run_id": "c1", "step": 20, "value": 0.7, "best": True},
    ]
    assert result.meta["groups"] == [{"group_id": "aaaa@c1", "label": "baseline"}]
    assert result.meta["metrics"] == ["train/loss", "val/acc"]
    assert result.meta["x"] == "step"


def test_curves_loss_checkpoint_best_is_minimum(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "c1")
    _jsonl(
        ctx.run_dir(rec) / "artifacts.jsonl",
        [
            {"kind": "checkpoint", "path": "/a", "step": 1, "metrics": {"val/loss": 0.9}},
            {"kind": "checkpoint", "path": "/b", "step": 2, "metrics": {"val/loss": 0.4}},
            {"kind": "checkpoint", "path": "/c", "step": 3, "metrics": {"val/loss": 0.6}},
        ],
    )
    result = query_panel(ctx, "toy", "toy-acc", _panel("curves"))
    assert [c["best"] for c in result.meta["checkpoints"]] == [False, True, False]


def test_curves_step_metric_and_group_by_run(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "c1", seed=1)
    _jsonl(
        ctx.run_dir(rec) / "metrics.jsonl",
        [{"name": "epoch", "step": s, "value": s // 2} for s in range(4)]
        + [{"name": "val/acc", "step": s, "value": 0.1 * s} for s in (0, 2, 3, 9)],
    )
    panel = _panel(
        "curves", data={"metrics": ["val/acc"], "step_metric": "epoch", "group_by": "run"}
    )
    result = query_panel(ctx, "toy", "toy-acc", panel)
    # step 9 has no epoch value, so it is dropped
    assert [(r["step"], r["value"]) for r in result.rows] == [
        (0, 0.0),
        (1, pytest.approx(0.2)),
        (1, pytest.approx(0.30000000000000004)),
    ]
    assert {r["group_id"] for r in result.rows} == {"c1"}
    assert result.meta["x"] == "epoch"


def test_checkpoints_use_the_step_metric_x(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "c1")
    _jsonl(
        ctx.run_dir(rec) / "metrics.jsonl",
        [{"name": "epoch", "step": s, "value": s // 100} for s in (0, 100, 200, 300)]
        + [{"name": "val/acc", "step": s, "value": 0.1 * s / 100} for s in (100, 200, 300)],
    )
    _jsonl(
        ctx.run_dir(rec) / "artifacts.jsonl",
        [
            {"kind": "checkpoint", "path": "/a", "step": 100, "metrics": {"val/acc": 0.1}},
            {"kind": "checkpoint", "path": "/b", "step": 300, "metrics": {"val/acc": 0.3}},
            {"kind": "checkpoint", "path": "/c", "step": 250, "metrics": {"val/acc": 0.9}},
        ],
    )
    panel = _panel("curves", data={"metrics": ["val/acc"], "step_metric": "epoch"})
    result = query_panel(ctx, "toy", "toy-acc", panel)
    assert [r["step"] for r in result.rows] == [1, 2, 3]
    # training steps 100 and 300 are epochs 1 and 3; step 250 has no epoch value: dropped
    assert result.meta["checkpoints"] == [
        {"run_id": "c1", "step": 1, "value": 0.1, "best": False},
        {"run_id": "c1", "step": 3, "value": 0.3, "best": True},
    ]


def test_spike_detection_rules() -> None:
    def pts(values: list[float]) -> list[MetricPoint]:
        return [MetricPoint(name="loss", step=i, value=v) for i, v in enumerate(values)]

    assert panels._spikes(pts([1.0, 5.0, 5.1])) == []  # median(1, 5) = 3 -> 5.1 < 15
    assert panels._spikes(pts([1.0, 5.1])) == [1]
    assert panels._spikes(pts([1.0, 5.0])) == []  # not strictly greater than 5x
    assert panels._spikes(pts([0.0, 3.0])) == [1]  # 3 > 5 x median(0) = 0 (contract rule)
    assert panels._spikes(pts([0.0, 0.0, 0.0])) == []  # 0 > 0 is false
    # only the previous 20 values count: median(20 x 3.0) = 3 -> 16 > 15 is a spike,
    # although the median of the whole history (21 x 10.0, 20 x 3.0) would be 10
    assert panels._spikes(pts([10.0] * 21 + [3.0] * 20 + [16.0])) == [41]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_panels.py -v`
Expected: `5 failed, 18 passed`; the curves tests fail with `KeyError: 'curves'` and `test_spike_detection_rules` with `AttributeError: module 'hypothex.core.panels' has no attribute '_spikes'`.

- [ ] **Step 3: Implement curves**

In `src/hypothex/core/panels.py`: Replace everything from the line `import copy` down to and including the last module-level constant (the line just before the two blank lines above `class PanelResult`) with:

```python
import copy
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC
from typing import Any

from pydantic import BaseModel, Field

from hypothex.core.context import Context
from hypothex.core.errors import ConfigError, HypothexError
from hypothex.core.leaderboard import Leaderboard, build_leaderboard, group_id_for, group_label
from hypothex.core.queries import primary_examples, refresh_project
from hypothex.core.records import Artifact, MetricPoint, RunRecord, RunStatus
from hypothex.core.sources import iter_rows, select_fields
from hypothex.core.store import ProjectEntry
from hypothex.core.views import (
    VERSION_REF,
    PanelSpec,
    PanelType,
    RunFilter,
    ViewSpec,
    vega_spec_problems,
)

MAX_TABLE_ROWS = 5000
SPIKE_WINDOW = 20
SPIKE_FACTOR = 5.0
```

Insert the following functions immediately above the line `_HANDLERS = {`:

```python
def _own_label(members: list[RunRecord], key: str) -> str:
    """``group_label`` of the newest non-empty hypothesis and the group's tags."""
    hypothesis = next((r.hypothesis for r in reversed(members) if r.hypothesis.strip()), "")
    return group_label(hypothesis, (t for r in members for t in r.tags), key)


def _groups(scope: _Scope, panel: PanelSpec) -> list[tuple[str, str, list[RunRecord]]]:
    """Return ``(key, label, members)`` per group, in order of first run."""
    by = panel.data.group_by or "group"
    members: dict[str, list[RunRecord]] = defaultdict(list)
    for r in scope.runs:
        if by == "config":
            key = r.config_hash.removeprefix("sha256:")[:8]
        elif by == "run":
            key = r.run_id
        elif by == "seed":
            key = f"seed={r.seed}"
        else:
            key = group_id_for(r)
        members[key].append(r)
    labels = scope.board_labels() if by == "group" else {}
    out: list[tuple[str, str, list[RunRecord]]] = []
    for key, runs in members.items():
        label = f"seed {runs[0].seed}" if by == "seed" else labels.get(key)
        out.append((key, label or _own_label(runs, key), runs))
    return out


def _lower_is_better(name: str) -> bool:
    lowered = name.lower()
    return "loss" in lowered or "error" in lowered


def _spikes(points: list[MetricPoint]) -> list[int]:
    """
    Steps whose value exceeds 5x the median of the previous 20 values.

    Exactly the contract rule ``value > 5 × median(previous 20 values)``: a zero
    median makes any positive value a spike (a loss leaving a flat zero).
    """
    steps: list[int] = []
    values = [p.value for p in points]
    for i in range(1, len(points)):
        window = values[max(0, i - SPIKE_WINDOW) : i]
        if values[i] > SPIKE_FACTOR * statistics.median(window):
            steps.append(points[i].step)
    return steps


def _checkpoints(scope: _Scope, run: RunRecord) -> list[Artifact]:
    logged = scope.ctx.store.read_artifacts(run.project, run.run_id)
    merged = {(a.kind, a.path): a for a in [*run.artifacts, *logged]}
    return sorted(
        (a for a in merged.values() if a.kind == "checkpoint" and a.step is not None),
        key=lambda a: a.step or 0,
    )


def _curves(scope: _Scope, panel: PanelSpec) -> PanelResult:
    wanted = panel.data.metrics
    x_name = panel.data.step_metric or "step"
    rows: list[dict[str, Any]] = []
    checkpoints: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    groups: list[dict[str, str]] = []
    group_of: dict[str, str] = {}
    for key, label, members in _groups(scope, panel):
        groups.append({"group_id": key, "label": label})
        for r in members:
            group_of[r.run_id] = key
    names_seen: list[str] = []
    for run in scope.runs:
        points = scope.ctx.store.read_metric_points(run.project, run.run_id)
        by_name: dict[str, list[MetricPoint]] = defaultdict(list)
        for p in points:
            by_name[p.name].append(p)
        x_of: dict[int, float] | None = None
        if x_name != "step":
            x_of = {p.step: p.value for p in by_name.get(x_name, [])}
        names = wanted if wanted is not None else sorted(n for n in by_name if n != x_name)
        run_events: list[dict[str, Any]] = []
        last_x: float | None = None
        for name in names:
            series = sorted(by_name.get(name, []), key=lambda p: p.step)
            if series and name not in names_seen:
                names_seen.append(name)
            for p in series:
                x = p.step if x_of is None else x_of.get(p.step)
                if x is None:
                    continue
                last_x = x if last_x is None else max(last_x, x)
                rows.append(
                    {
                        "run_id": run.run_id,
                        "group_id": group_of[run.run_id],
                        "seed": run.seed,
                        "name": name,
                        "step": x,
                        "value": p.value,
                    }
                )
            if "loss" in name.lower():
                for step in _spikes(series):
                    x = step if x_of is None else x_of.get(step)
                    if x is not None:
                        run_events.append({"run_id": run.run_id, "step": x, "kind": "spike"})
        if run.status in (RunStatus.KILLED, RunStatus.FAILED) and last_x is not None:
            run_events.append({"run_id": run.run_id, "step": last_x, "kind": run.status.value})
        events.extend(sorted(run_events, key=lambda e: e["step"]))
        checkpoints.extend(_checkpoint_rows(scope, run, panel, x_of))
    return PanelResult(
        type="curves",
        title=panel.title,
        rows=rows,
        meta={
            "x": x_name,
            "metrics": names_seen,
            "checkpoints": checkpoints,
            "events": events,
            "groups": groups,
        },
    )


def _checkpoint_rows(
    scope: _Scope, run: RunRecord, panel: PanelSpec, x_of: dict[int, float] | None
) -> list[dict[str, Any]]:
    """
    Checkpoint marks of one run, at the curves' x.

    ``x_of`` maps a training step to the ``data.step_metric`` value logged at
    that step (``None`` when x is the step itself); a checkpoint whose step has
    no such value is dropped, like a curve point.
    """
    arts = [
        a
        for a in _checkpoints(scope, run)
        if x_of is None or (a.step is not None and a.step in x_of)
    ]
    if not arts:
        return []
    name = panel.data.y
    if name is None:
        present = [m for m in (panel.data.metrics or []) if any(m in a.metrics for a in arts)]
        keys = sorted({k for a in arts for k in a.metrics})
        name = present[0] if present else (keys[0] if keys else None)
    out = [
        {
            "run_id": run.run_id,
            "step": a.step if x_of is None or a.step is None else x_of[a.step],
            "value": a.metrics.get(name) if name else None,
            "best": False,
        }
        for a in arts
    ]
    scored = [c for c in out if c["value"] is not None]
    if scored and name is not None:
        pick = min if _lower_is_better(name) else max
        best = pick(scored, key=lambda c: c["value"])
        best["best"] = True
    return out
```

Replace the whole `_HANDLERS = { ... }` dict at the end of the file with:

```python
_HANDLERS = {
    "stat_strip": _stat_strip,
    "leaderboard": _leaderboard,
    "curves": _curves,
    "table": _table,
    "vega_lite": _vega_lite,
    "trace": _trace,
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_panels.py -v`
Expected: `23 passed`.

Run: `uv run ruff check src/hypothex/core/panels.py tests/core/test_panels.py && uv run ruff format --check src/hypothex/core/panels.py tests/core/test_panels.py && uv run ty check src/hypothex/core/panels.py`
Expected: all clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/panels.py tests/core/test_panels.py
git commit -m "feat: curves panel with spikes, kills, and best checkpoints"
```

---

### Task 22: Scatter panel (per-group means, noise intervals, Pareto front, ordinal x) and metric stat strips

**Files:**
- Modify: `src/hypothex/core/panels.py` (imports/constants block, `_stat_strip`, new functions above `_HANDLERS`, `_HANDLERS`)
- Test: `tests/core/test_panels.py` (records import line, append tests)

**Interfaces:**
- Consumes: Tasks 20–21 (`_Scope`, `_groups`, `_stat_strip`); `seeds.summarize(values) -> Stats` (t-interval, `ci_low`/`ci_high` None for n=1); `stats.quantile`; `RunStore.read_samples` (Task 6; series keyed by their original names); `_run_versions` (Task 20) and `views.VERSION_REF` (Task 16); `LeaderboardRow.test_interval` (contract 1.7); `leaderboard.pick_field` (Task 11) and `leaderboard._natural_key` (Task 12); `headlines.fmt_value` (Task 9); `fsutil.read_jsonl`; `RunRecord.usage` (contract 1.2); `_lower_is_better` (Task 21) and `Leaderboard.higher_is_better` for the regression direction.
- Produces:
  - `scatter` rows `{group_id, label, x, x_lo, x_hi, y, y_lo, y_hi, seeds: [{x, y}], pareto, regression}`; `meta` = `x, y, x_type, scale, pareto, y_higher_is_better, best_group` (contract 1.6: `y_higher_is_better` is the y direction below, `best_group` the `group_id` of the row with the best mean y in that direction, first row on a tie, `None` without rows; both are sent whatever `pareto` says, so the UI never assumes higher is better for a loss or a cost). Missing `data.x` → `ConfigError("scatter panel needs data.x")` and a `pareto` key other than `x`/`y` → `ConfigError("pareto keys are x and y")` (the same rules as view validation; the editor preview queries views that were not validated, and `query_view` turns a `ConfigError` into that panel's `meta.error` instead of a 500). Missing `data.y` → the task's primary metric (`Leaderboard.primary`, e.g. `solved/value`; `meta.y` holds the resolved reference). Groups with no run having both values are dropped.
  - Ordinal x (spec 8.4, versions in order): when `data.x` is `params.<p>`/`vars.<p>` or `version` and any selected run has a value that `float()` rejects (e.g. `v9`), x is the raw text, rows are sorted with `leaderboard._natural_key` (`v9` before `v10`), `x_lo`/`x_hi` are `None`, no row is on a Pareto front, and `meta.x_type = "ordinal"`. Otherwise `meta.x_type = "quantitative"`.
  - `data.x: version` (`views.VERSION_REF`, spec 8.4) reads the run param `TaskSpec.version_param` names; a group whose runs lack it gets the creation time of its first run (`_run_versions`, Task 20), so a task without version params still gets a version axis. Groups with a param value come first (natural order), then the others by time.
  - Intervals: seed t-interval (`seeds.summarize`) on both axes; when `y` is the task's primary metric at the leaderboard's metric version (no `@version`, or the one in `Leaderboard.metric_versions`) and grouping is by seed group, `y_lo`/`y_hi` come from the leaderboard row's test-set interval if it has one (spec 8.1, "two kinds of noise"). An explicit other version (`accuracy@v0` while the board uses `v1`) keeps its own seed interval, never the board version's.
  - `pareto`: with `panel.pareto` (e.g. `{x: min, y: max}`) a row is on the front when no other row is at least as good on every axis and strictly better on one; without `panel.pareto` every row is `False`.
  - `regression` (contract 1.6, spec 8.4 "regressions marked"): only on an ordinal x. Walking the rows in natural order, a row regresses when it is worse than the best earlier row by more than that row's interval allows: higher-is-better `y_hi < best.y_lo`, lower-is-better `y_lo > best.y_hi`; a `None` bound on either side flags nothing; ties keep the earlier row as best. Direction (`_y_higher_is_better`): `usage.*` is lower-is-better; the task primary uses `Leaderboard.higher_is_better`; another configured metric uses its `higher_is_better`; any other name uses `not _lower_is_better(name)` (Task 21: `loss`/`error` names). Quantitative x → every row `False`.
  - `_run_value(scope, run, ref) -> float | None` resolves, in order: `usage.<field>` (run totals) or `usage.<field>/solved` (the run total divided by the number of examples the run solved on the task's primary metric: its binary per-example field, chosen by `pick_field`, true or 1; `None` when that field is not binary or nothing was solved; spec 8.4 "cost per success"; any other `/` suffix → `ConfigError("usage references are usage.<field> or usage.<field>/solved")`), `params.<p>` / `vars.<p>` (float cast), configured metric `name[@version][/key]` (newest good score, default current version and key `value`; spec 8.6: when no score has that key and `key` is in `AGGREGATES`, the aggregate of the per-example values in `predictions/scores.<name>@<version>.jsonl`, field chosen by `pick_field(rows, name)`), samples `name` (mean) or `name/<agg>` with `agg` in `AGGREGATES = ("mean", "median", "min", "max", "p50", "p90", "p95", "p99")`, then the last logged value of the history metric named exactly `ref`. A value that is not finite (NaN or ±inf, e.g. a NaN score or loss) counts as no value: `None`, so it never becomes a null point or breaks a Pareto comparison.
  - `stat_strip` with `data.metrics` (spec 8.6, "Best config"): one `{label, value, unit, tooltip}` row per reference, `value = fmt_value(mean of _run_value over the selected runs that have one)` (after `data.filter`/`data.pick`), `"—"` when no run has a value; `tooltip` = `Mean of <n> runs[ of <group label>]`. Without `data.metrics` the rows stay `Leaderboard.stat_strip`. `meta.headline` either way.
  - `_samples(scope, run, name) -> list[float]` (used by Task 23).

- [ ] **Step 1: Write the failing tests**

In `tests/core/test_panels.py` add `import math` on the line after `import json`, then replace the import line

```python
from hypothex.core.records import GitInfo, MetricPoint, RunRecord, RunStatus, ScoreRecord
```

with

```python
from hypothex.core.records import (
    GitInfo,
    MetricPoint,
    RunRecord,
    RunStatus,
    ScoreRecord,
    UsageTotals,
)
```

Append to the end of `tests/core/test_panels.py`:

```python
# scatter --------------------------------------------------------------------------
def test_scatter_groups_intervals_and_pareto(ctx: Context, toy_repo: Path) -> None:
    for rid, group, hyp, usd, acc, minute in [
        ("s1", "aaaa", "svm", 0.1, 0.8, 0),
        ("s2", "aaaa", "svm", 0.3, 0.9, 1),
        ("f1", "bbbb", "rf", 0.05, 0.6, 2),
        ("g1", "cccc", "gbm", 0.5, 0.7, 3),
    ]:
        rec = _run(
            ctx, toy_repo, rid, group, minute=minute, hypothesis=hyp, usage=UsageTotals(usd=usd)
        )
        _score(ctx, rec, acc)
    panel = _panel(
        "scatter", data={"x": "usage.usd", "y": "accuracy"}, pareto={"x": "min", "y": "max"}
    )
    result = query_panel(ctx, "toy", "toy-acc", panel)
    by_label = {r["label"]: r for r in result.rows}
    svm = by_label["svm"]
    # 95% t-interval, df=1: t = 12.706 (seeds._T_975); stdev([0.1, 0.3]) / sqrt(2) = 0.1
    assert svm["x"] == pytest.approx(0.2)
    assert svm["x_lo"] == pytest.approx(0.2 - 1.2706)
    assert svm["x_hi"] == pytest.approx(0.2 + 1.2706)
    # stdev([0.8, 0.9]) / sqrt(2) = 0.05 -> half-width 0.6353
    assert svm["y"] == pytest.approx(0.85)
    assert svm["y_lo"] == pytest.approx(0.85 - 0.6353)
    assert svm["y_hi"] == pytest.approx(0.85 + 0.6353)
    assert svm["seeds"] == [{"x": 0.1, "y": 0.8}, {"x": 0.3, "y": 0.9}]
    assert by_label["rf"]["x_lo"] is None and by_label["rf"]["y_hi"] is None
    # gbm (0.5, 0.7) is dominated by svm (0.2, 0.85): costlier and worse
    assert {r["label"]: r["pareto"] for r in result.rows} == {
        "svm": True,
        "rf": True,
        "gbm": False,
    }
    assert not any(r["regression"] for r in result.rows)  # quantitative x never regresses
    assert result.meta == {
        "x": "usage.usd",
        "y": "accuracy",
        "x_type": "quantitative",
        "scale": "linear",
        "pareto": {"x": "min", "y": "max"},
        "y_higher_is_better": True,
        "best_group": "aaaa@c1",  # svm, mean accuracy 0.85
    }


def test_scatter_without_pareto_marks_nothing_and_skips_missing(
    ctx: Context, toy_repo: Path
) -> None:
    rec = _run(ctx, toy_repo, "s1", params={"lr": "0.1"})
    _score(ctx, rec, 0.5)
    _run(ctx, toy_repo, "s2", "bbbb", params={"lr": "0.2"})  # no score -> no y -> dropped
    panel = _panel("scatter", data={"x": "params.lr", "y": "accuracy"})
    result = query_panel(ctx, "toy", "toy-acc", panel)
    assert [(r["x"], r["y"], r["pareto"]) for r in result.rows] == [(0.1, 0.5, False)]


def test_scatter_reads_samples_aggregates_and_history(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "s1")
    _jsonl(ctx.run_dir(rec) / "samples" / "lat.jsonl", [{"value": v} for v in (1, 2, 3, 4)])
    _jsonl(
        ctx.run_dir(rec) / "metrics.jsonl",
        [
            {"name": "val/loss", "step": 1, "value": 0.9},
            {"name": "val/loss", "step": 5, "value": 0.3},
        ],
    )
    panel = _panel("scatter", data={"x": "lat/p50", "y": "val/loss", "group_by": "run"})
    (row,) = query_panel(ctx, "toy", "toy-acc", panel).rows
    # numpy-linear p50 of [1, 2, 3, 4] = 2.5; history value = last step's value
    assert (row["group_id"], row["x"], row["y"]) == ("s1", 2.5, 0.3)
    mean_panel = _panel("scatter", data={"x": "lat", "y": "lat/max", "group_by": "run"})
    (row,) = query_panel(ctx, "toy", "toy-acc", mean_panel).rows
    assert (row["x"], row["y"]) == (2.5, 4.0)


def test_scatter_requires_x_and_defaults_y_to_primary(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "s1", usage=UsageTotals(usd=0.2))
    _score(ctx, rec, 0.5)
    with pytest.raises(ConfigError, match="needs data.x"):
        query_panel(ctx, "toy", "toy-acc", _panel("scatter", data={"y": "accuracy"}))
    result = query_panel(ctx, "toy", "toy-acc", _panel("scatter", data={"x": "usage.usd"}))
    assert [(r["x"], r["y"]) for r in result.rows] == [(0.2, 0.5)]
    assert (result.meta["y"], result.meta["x_type"]) == ("accuracy/value", "quantitative")


def test_scatter_bad_pareto_key_is_a_panel_error(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "s1", usage=UsageTotals(usd=0.2))
    _score(ctx, rec, 0.5)
    bad = _panel("scatter", data={"x": "usage.usd"}, pareto={"z": "min"})
    with pytest.raises(ConfigError, match="pareto keys are x and y"):
        query_panel(ctx, "toy", "toy-acc", bad)
    # the editor preview sends views that were not validated: one panel error, not a 500
    view = ViewSpec(title="v", panels=[bad, _panel("markdown", text="ok")])
    broken, notes = query_view(ctx, "toy", "toy-acc", view)
    assert (broken.rows, broken.meta) == ([], {"error": "pareto keys are x and y"})
    assert notes.meta == {"text": "ok"}


def test_non_finite_values_count_as_missing(ctx: Context, toy_repo: Path) -> None:
    a = _run(ctx, toy_repo, "s1", usage=UsageTotals(usd=0.1))
    nan_score = ScoreRecord(metric="accuracy", version="v1", key="value", value=0.0, created_at=T0)
    # json.dumps writes NaN; json.loads and pydantic read it back as float("nan")
    _jsonl(
        ctx.run_dir(a) / "scores.jsonl", [{**nan_score.model_dump(mode="json"), "value": math.nan}]
    )
    b = _run(ctx, toy_repo, "s2", "bbbb", minute=1, usage=UsageTotals(usd=0.2))
    _score(ctx, b, 0.5)
    _jsonl(
        ctx.run_dir(b) / "metrics.jsonl",
        [
            {"name": "val/loss", "step": 1, "value": 0.4},
            {"name": "val/loss", "step": 2, "value": math.nan},
        ],
    )
    panel = _panel(
        "scatter",
        data={"x": "usage.usd", "y": "accuracy", "group_by": "run"},
        pareto={"x": "min", "y": "max"},
    )
    result = query_panel(ctx, "toy", "toy-acc", panel)
    # s1's NaN score is no value, so s1 is dropped instead of a null point on the front
    assert [(r["group_id"], r["x"], r["y"], r["pareto"]) for r in result.rows] == [
        ("s2", 0.2, 0.5, True)
    ]
    loss = _panel("scatter", data={"x": "usage.usd", "y": "val/loss", "group_by": "run"})
    assert query_panel(ctx, "toy", "toy-acc", loss).rows == []  # last val/loss point is NaN


def test_scatter_categorical_x_is_ordinal_in_natural_order(ctx: Context, toy_repo: Path) -> None:
    for rid, group, version, acc, minute in [
        ("a1", "aaaa", "v10", 0.9, 0),
        ("b1", "bbbb", "v9", 0.7, 1),
        ("b2", "bbbb", "v9", 0.8, 2),
    ]:
        rec = _run(ctx, toy_repo, rid, group, minute=minute, params={"version": version})
        _score(ctx, rec, acc)
    panel = _panel(
        "scatter", data={"x": "params.version", "y": "accuracy"}, pareto={"x": "min", "y": "max"}
    )
    result = query_panel(ctx, "toy", "toy-acc", panel)
    # float("v9") fails, so x keeps the text; v9 sorts before v10 (natural order)
    assert [(r["x"], r["x_lo"], r["x_hi"]) for r in result.rows] == [
        ("v9", None, None),
        ("v10", None, None),
    ]
    assert [r["y"] for r in result.rows] == pytest.approx([0.75, 0.9])
    assert result.rows[0]["seeds"] == [{"x": "v9", "y": 0.7}, {"x": "v9", "y": 0.8}]
    assert not any(r["pareto"] for r in result.rows)  # no Pareto front on an ordinal axis
    assert result.meta["x_type"] == "ordinal"


def _version_series(ctx: Context, repo: Path, xs: list[str]) -> None:
    """
    Five seed groups in order, one per ``params.version`` value in ``xs``.

    Each group has 3 seeds whose accuracy and ``usage.usd`` are ``mean - 0.01``,
    ``mean``, ``mean + 0.01`` for means 0.50, 0.60, 0.70, 0.60, 0.68.
    """
    means = [0.50, 0.60, 0.70, 0.60, 0.68]
    for i, (x, mean) in enumerate(zip(xs, means, strict=True)):
        for j, step in enumerate((-0.01, 0.0, 0.01)):
            value = mean + step
            rec = _run(
                ctx,
                repo,
                f"r{i}{j}",
                f"aaa{i}",
                minute=3 * i + j,
                seed=j + 1,
                params={"version": x},
                usage=UsageTotals(usd=value),
            )
            _score(ctx, rec, value)


def test_scatter_flags_regressions_on_ordinal_x(ctx: Context, toy_repo: Path) -> None:
    _version_series(ctx, toy_repo, ["v1", "v2", "v3", "v4", "v5"])
    solved = query_panel(ctx, "toy", "toy-acc", _panel("scatter", data={"x": "params.version"}))
    assert solved.meta["x_type"] == "ordinal"
    # 3 seeds, stdev 0.01: 95% t half-width = 4.303 * 0.01 / sqrt(3) = 0.0248 (no test-set
    # interval: the runs have no per-example scores). Accuracy is higher-is-better.
    # v4: y_hi 0.6248 < best earlier (v3) y_lo 0.6752 -> regression.
    # v5: 0.68 is below v3 but its y_hi 0.7048 >= 0.6752 -> within noise, not flagged.
    assert [(r["x"], r["regression"]) for r in solved.rows] == [
        ("v1", False),
        ("v2", False),
        ("v3", False),
        ("v4", True),
        ("v5", False),
    ]
    assert solved.rows[3]["y_hi"] == pytest.approx(0.60 + 4.303 * 0.01 / math.sqrt(3))
    cost = _panel("scatter", data={"x": "params.version", "y": "usage.usd"})
    # usage is lower-is-better: v1 (0.50, y_hi 0.5248) stays the best; every later y_lo
    # (0.5752, 0.6752, 0.5752, 0.6552) is above it
    assert [r["regression"] for r in query_panel(ctx, "toy", "toy-acc", cost).rows] == [
        False,
        True,
        True,
        True,
        True,
    ]


def test_scatter_quantitative_x_never_flags_regressions(ctx: Context, toy_repo: Path) -> None:
    # the same values as the ordinal series, but versions 1..5 are numbers
    _version_series(ctx, toy_repo, ["1", "2", "3", "4", "5"])
    result = query_panel(ctx, "toy", "toy-acc", _panel("scatter", data={"x": "params.version"}))
    assert result.meta["x_type"] == "quantitative"
    assert [r["x"] for r in result.rows] == [1.0, 2.0, 3.0, 4.0, 5.0]
    assert [r["regression"] for r in result.rows] == [False] * 5


def test_usage_per_solved_divides_by_solved_examples(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "s1", usage=UsageTotals(usd=3.0))
    _score(ctx, rec, 0.75)
    _jsonl(
        ctx.run_dir(rec) / "predictions" / "scores.accuracy@v1.jsonl",
        [{"id": f"ex-{i}", "correct": ok} for i, ok in enumerate([True, True, True, False])],
    )
    none = _run(ctx, toy_repo, "s2", "bbbb", minute=1, usage=UsageTotals(usd=2.0))
    _score(ctx, none, 0.0)
    _jsonl(
        ctx.run_dir(none) / "predictions" / "scores.accuracy@v1.jsonl",
        [{"id": "ex-0", "correct": False}],
    )
    panel = _panel("scatter", data={"x": "usage.usd", "y": "usage.usd/solved", "group_by": "run"})
    rows = query_panel(ctx, "toy", "toy-acc", panel).rows
    # s1: $3.00 over 3 solved examples = 1.0; s2 solved nothing, so it has no value (dropped)
    assert [(r["group_id"], r["x"], r["y"]) for r in rows] == [("s1", 3.0, 1.0)]
    bad = _panel("scatter", data={"x": "usage.usd/attempt"})
    with pytest.raises(ConfigError, match=r"usage\.<field>/solved"):
        query_panel(ctx, "toy", "toy-acc", bad)


def test_metric_aggregate_keys_read_per_example_scores(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "s1")
    _jsonl(
        ctx.run_dir(rec) / "predictions" / "scores.accuracy@v1.jsonl",
        [{"id": f"ex-{i}", "len": v} for i, v in enumerate((4, 1, 3, 10))],
    )
    ctx.add_score(
        rec, ScoreRecord(metric="accuracy", version="v1", key="p95", value=7.0, created_at=T0)
    )
    panel = _panel(
        "scatter", data={"x": "accuracy@v1/median", "y": "accuracy/max", "group_by": "run"}
    )
    (row,) = query_panel(ctx, "toy", "toy-acc", panel).rows
    # no "median"/"max" score: aggregate the per-example field (median 3.5, max 10)
    assert (row["x"], row["y"]) == (3.5, 10.0)
    stored = _panel(
        "scatter", data={"x": "accuracy/p95", "y": "accuracy@v1/mean", "group_by": "run"}
    )
    (row,) = query_panel(ctx, "toy", "toy-acc", stored).rows
    assert (row["x"], row["y"]) == (7.0, 4.5)  # a stored "p95" score wins


def test_stat_strip_with_metrics_summarises_selected_runs(ctx: Context, toy_repo: Path) -> None:
    _two_groups(ctx, toy_repo)
    panel = _panel("stat_strip", data={"metrics": ["accuracy@v1", "usage.usd"], "pick": "best"})
    result = query_panel(ctx, "toy", "toy-acc", panel)
    assert result.rows == [
        {"label": "accuracy@v1", "value": "0.850", "unit": "", "tooltip": "Mean of 2 runs of svm"},
        {
            "label": "usage.usd",
            "value": "—",
            "unit": "",
            "tooltip": "No value in the 2 selected runs",
        },
    ]
    assert set(result.meta) == {"headline"}


def test_scatter_meta_carries_y_direction_and_best_group(ctx: Context, toy_repo: Path) -> None:
    for rid, group, usd, acc, minute in [("a1", "aaaa", 0.1, 0.8, 0), ("b1", "bbbb", 0.3, 0.9, 1)]:
        rec = _run(ctx, toy_repo, rid, group, minute=minute, usage=UsageTotals(usd=usd))
        _score(ctx, rec, acc)
        _jsonl(
            ctx.run_dir(rec) / "metrics.jsonl", [{"name": "val/loss", "step": 1, "value": 1 - acc}]
        )

    def meta(data: dict[str, str]) -> tuple[bool, str | None]:
        result = query_panel(ctx, "toy", "toy-acc", _panel("scatter", data=data))
        return result.meta["y_higher_is_better"], result.meta["best_group"]

    # no pareto settings anywhere: the best group still follows the y direction
    assert meta({"x": "usage.usd"}) == (True, "bbbb@c1")  # primary accuracy: 0.9 wins
    assert meta({"x": "accuracy", "y": "usage.usd"}) == (False, "aaaa@c1")  # $0.1 wins
    assert meta({"x": "usage.usd", "y": "val/loss"}) == (False, "bbbb@c1")  # loss 0.1 wins
    assert meta({"x": "usage.usd", "y": "nothing"}) == (True, None)  # no rows


def test_scatter_uses_the_test_interval_only_at_the_board_version(
    ctx: Context, toy_repo: Path
) -> None:
    for rid, seed, usd, old in [("s1", 1, 0.1, 0.4), ("s2", 2, 0.3, 0.6)]:
        rec = _run(ctx, toy_repo, rid, seed=seed, minute=seed, usage=UsageTotals(usd=usd))
        _score(ctx, rec, 0.75)  # accuracy@v1: the board's version
        ctx.add_score(
            rec, ScoreRecord(metric="accuracy", version="v0", key="value", value=old, created_at=T0)
        )
        _jsonl(
            ctx.run_dir(rec) / "predictions" / "scores.accuracy@v1.jsonl",
            [{"id": f"ex-{i}", "correct": ok} for i, ok in enumerate([True, True, True, False])],
        )
    for y in ("accuracy", "accuracy@v1"):
        (row,) = query_panel(
            ctx, "toy", "toy-acc", _panel("scatter", data={"x": "usage.usd", "y": y})
        ).rows
        # pooled 3 of 4 correct: statsmodels proportion_confint(3, 4, method="wilson")
        assert (row["y_lo"], row["y_hi"]) == pytest.approx(
            (0.30064184258240184, 0.9544127391902995)
        )
    old = _panel("scatter", data={"x": "usage.usd", "y": "accuracy@v0"})
    (row,) = query_panel(ctx, "toy", "toy-acc", old).rows
    # v0 is not the board's version: its own seed t-interval, 0.5 +- 12.706 * 0.1
    assert row["y"] == pytest.approx(0.5)
    assert (row["y_lo"], row["y_hi"]) == pytest.approx((0.5 - 1.2706, 0.5 + 1.2706))


def test_scatter_version_x_follows_version_param_then_creation_time(
    ctx: Context, toy_repo: Path
) -> None:
    for rid, group, params, acc, minute in [
        ("a", "aaaa", {"prompt_version": "p10"}, 0.7, 0),
        ("b", "bbbb", {"prompt_version": "p9"}, 0.6, 1),
        ("c", "cccc", {}, 0.5, 2),
        ("d", "dddd", {}, 0.4, 3),
    ]:
        rec = _run(ctx, toy_repo, rid, group, minute=minute, params=params)
        _score(ctx, rec, acc)
    t0, t1, t2, t3 = ((T0 + timedelta(minutes=m)).strftime("%Y-%m-%d %H:%M:%S") for m in range(4))
    panel = _panel("scatter", data={"x": "version"})
    # default version_param "version": no run has it, so every group falls back to the
    # creation time of its first run (spec 8.4) instead of vanishing from the plot
    result = query_panel(ctx, "toy", "toy-acc", panel)
    assert result.meta["x_type"] == "ordinal"
    assert [r["x"] for r in result.rows] == [t0, t1, t2, t3]
    _set_task(toy_repo, version_param="prompt_version")
    result = query_panel(ctx, "toy", "toy-acc", panel)
    # params first in natural order (p9 before p10), then the fallback groups by time
    assert [(r["x"], r["y"]) for r in result.rows] == [
        ("p9", 0.6),
        ("p10", 0.7),
        (t2, 0.5),
        (t3, 0.4),
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_panels.py -v`
Expected: `15 failed, 23 passed`; the fourteen scatter tests (including `test_scatter_bad_pareto_key_is_a_panel_error`, `test_non_finite_values_count_as_missing`, `test_usage_per_solved_divides_by_solved_examples`, `test_scatter_flags_regressions_on_ordinal_x`, `test_scatter_quantitative_x_never_flags_regressions`, `test_scatter_meta_carries_y_direction_and_best_group`, `test_scatter_uses_the_test_interval_only_at_the_board_version`, and `test_scatter_version_x_follows_version_param_then_creation_time`) fail with `KeyError: 'scatter'` and `test_stat_strip_with_metrics_summarises_selected_runs` with `AssertionError` (the strip is still the task's generic strip).

- [ ] **Step 3: Implement scatter**

In `src/hypothex/core/panels.py`: Replace everything from the line `import copy` down to and including the last module-level constant (the line just before the two blank lines above `class PanelResult`) with:

```python
import copy
import math
import statistics
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC
from typing import Any

from pydantic import BaseModel, Field

from hypothex.core.config import parse_metric_version
from hypothex.core.context import Context
from hypothex.core.errors import ConfigError, HypothexError
from hypothex.core.fsutil import read_jsonl
from hypothex.core.headlines import fmt_value
from hypothex.core.leaderboard import (
    Leaderboard,
    _natural_key,
    build_leaderboard,
    group_id_for,
    group_label,
    pick_field,
)
from hypothex.core.queries import primary_examples, refresh_project
from hypothex.core.records import Artifact, MetricPoint, RunRecord, RunStatus
from hypothex.core.seeds import summarize
from hypothex.core.sources import iter_rows, select_fields
from hypothex.core.stats import quantile
from hypothex.core.store import ProjectEntry
from hypothex.core.views import (
    VERSION_REF,
    PanelSpec,
    PanelType,
    RunFilter,
    ViewSpec,
    vega_spec_problems,
)

MAX_TABLE_ROWS = 5000
SPIKE_WINDOW = 20
SPIKE_FACTOR = 5.0
AGGREGATES = ("mean", "median", "min", "max", "p50", "p90", "p95", "p99")
```

Replace the whole `_stat_strip` function (Task 20) with:

```python
def _stat_strip(scope: _Scope, panel: PanelSpec) -> PanelResult:
    """
    The task's stat strip, or one item per ``data.metrics`` reference.

    With ``data.metrics`` each item is the mean of ``_run_value`` over the
    selected runs (after ``data.filter`` and ``data.pick``) that have a value.
    """
    board = scope.board()
    rows: list[dict[str, Any]] = []
    if not panel.data.metrics:
        rows = [dict(item) for item in board.stat_strip]
    else:
        groups = _groups(scope, panel)
        only = f" of {groups[0][1]}" if len(groups) == 1 else ""
        for ref in panel.data.metrics:
            values = [v for r in scope.runs if (v := _run_value(scope, r, ref)) is not None]
            if not values:
                tooltip = f"No value in the {len(scope.runs)} selected runs"
                rows.append({"label": ref, "value": "—", "unit": "", "tooltip": tooltip})
                continue
            n = len(values)
            rows.append(
                {
                    "label": ref,
                    "value": fmt_value(math.fsum(values) / n),
                    "unit": "",
                    "tooltip": f"Mean of {n} run{'s' if n != 1 else ''}{only}",
                }
            )
    return PanelResult(
        type="stat_strip",
        title=panel.title,
        rows=rows,
        meta={"headline": board.headline},
    )
```

Insert the following functions immediately above the line `_HANDLERS = {`:

```python
def _aggregate(values: list[float], agg: str) -> float | None:
    if not values:
        return None
    if agg == "mean":
        return math.fsum(values) / len(values)
    if agg == "median":
        return statistics.median(values)
    if agg == "min":
        return min(values)
    if agg == "max":
        return max(values)
    return quantile(values, int(agg[1:]) / 100)


def _samples(scope: _Scope, run: RunRecord, name: str) -> list[float]:
    """A run's raw samples of series ``name`` (the name given to ``log_samples``)."""
    if not name:
        return []
    return scope.ctx.store.read_samples(run.project, run.run_id).get(name, [])


def _example_values(scope: _Scope, run: RunRecord, name: str, version: str) -> list[float]:
    """Per-example values of a metric: the field ``pick_field`` chooses, one per example."""
    path = scope.ctx.run_dir(run) / "predictions" / f"scores.{name}@{version}.jsonl"
    if not path.is_file():
        return []
    rows = [{k: v for k, v in row.items() if k != "id"} for row in read_jsonl(path)]
    picked = pick_field(rows, name)
    if picked is None:
        return []
    field = picked[0]
    return [float(row[field]) for row in rows if row.get(field) is not None]


def _solved(scope: _Scope, run: RunRecord) -> int | None:
    """
    Count the examples a run solved on the task's primary metric.

    ``None`` when the run has no per-example file or its field (chosen by
    ``pick_field``, as for test-set noise) is not binary.
    """
    name = scope.board().primary.partition("/")[0]
    spec = scope.entry.config.metrics.get(name)
    if spec is None:
        return None
    path = scope.ctx.run_dir(run) / "predictions" / f"scores.{name}@{spec.version}.jsonl"
    rows = [{k: v for k, v in row.items() if k != "id"} for row in read_jsonl(path)]
    picked = pick_field(rows, name)
    if picked is None or not picked[1]:
        return None
    field = picked[0]
    return sum(1 for row in rows if row.get(field) in (True, 1))


def _param_raw(run: RunRecord, ref: str) -> str | None:
    """The raw ``params.<p>`` / ``vars.<p>`` value as text, or ``None``."""
    for prefix, values in (("params.", run.params), ("vars.", run.vars)):
        if ref.startswith(prefix):
            return values.get(ref.removeprefix(prefix))
    return None


def _as_float(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def _run_value(scope: _Scope, run: RunRecord, ref: str) -> float | None:
    """
    Resolve a reference to one finite number for one run.

    Order: ``usage.<field>`` (run totals) or ``usage.<field>/solved`` (the total
    per example solved on the primary metric), ``params.<p>``/``vars.<p>`` (cast to
    float), a configured metric ``name[@version][/key]`` (newest good score;
    when no score has that key and the key is an aggregate such as ``median``,
    the aggregate of the metric's per-example values), samples ``name[/agg]``,
    then the last logged value of a history metric named exactly ``ref``.
    NaN and ±inf count as no value (``None``): they would become null points
    in JSON and make every Pareto comparison false.
    """
    value = _resolve_value(scope, run, ref)
    return value if value is not None and math.isfinite(value) else None


def _resolve_value(scope: _Scope, run: RunRecord, ref: str) -> float | None:
    """The raw value behind ``_run_value``; may be NaN or ±inf."""
    if ref.startswith("usage."):
        field, _, per = ref.removeprefix("usage.").partition("/")
        if per not in ("", "solved"):
            raise ConfigError("usage references are usage.<field> or usage.<field>/solved")
        value = getattr(run.usage, field, None) if run.usage is not None else None
        if not isinstance(value, int | float):
            return None
        if not per:
            return float(value)
        solved = _solved(scope, run)
        return float(value) / solved if solved else None
    if ref.startswith(("params.", "vars.")):
        raw = _param_raw(run, ref)
        return None if raw is None else _as_float(raw)
    head, _, key = ref.partition("/")
    name, version = parse_metric_version(head)
    metrics = scope.entry.config.metrics
    if name in metrics:
        version = version or metrics[name].version
        key = key or "value"
        found: float | None = None
        for s in scope.ctx.store.read_scores(run.project, run.run_id):
            if (s.metric, s.version, s.key) == (name, version, key) and s.error is None:
                found = s.value
        if found is None and key in AGGREGATES:
            return _aggregate(_example_values(scope, run, name, version), key)
        return found
    whole = _samples(scope, run, ref)
    if whole:
        return _aggregate(whole, "mean")
    if key in AGGREGATES:
        return _aggregate(_samples(scope, run, head), key)
    history = scope.ctx.store.read_metric_points(run.project, run.run_id)
    points = [p for p in history if p.name == ref]
    return max(points, key=lambda p: p.step).value if points else None


def _interval(values: list[float]) -> tuple[float | None, float | None]:
    stats = summarize(values)
    return stats.ci_low, stats.ci_high


def _is_ordinal(
    groups: list[tuple[str, str, list[RunRecord]]],
    x_ref: str,
    text_of: Callable[[RunRecord], str | None],
) -> bool:
    """Whether ``x_ref`` is a params/vars field or ``version`` with a non-numeric value."""
    if x_ref != VERSION_REF and not x_ref.startswith(("params.", "vars.")):
        return False
    for _, _, members in groups:
        for r in members:
            raw = text_of(r)
            if raw is not None and _as_float(raw) is None:
                return True
    return False


def _scatter(scope: _Scope, panel: PanelSpec) -> PanelResult:
    """
    One point per group: mean x and y over its runs, with seed intervals.

    ``data.y`` defaults to the task's primary metric. A ``params``/``vars`` x
    with a value that is not a number (e.g. ``version: v9``) makes an ordinal
    axis: x is the raw text, rows are in natural order (``v9`` before ``v10``),
    there are no x intervals and no Pareto front, and ``meta.x_type`` is
    ``"ordinal"`` (else ``"quantitative"``). Only an ordinal axis sets
    ``regression`` (``_mark_regressions``); otherwise every row has ``False``.
    ``x: version`` reads the task's version param, else the group's first-run
    creation time (``_run_versions``). ``meta.y_higher_is_better`` and
    ``meta.best_group`` (best mean y in that direction) are always set.
    """
    x_ref = panel.data.x
    if not x_ref:
        raise ConfigError("scatter panel needs data.x")
    if panel.pareto and set(panel.pareto) - {"x", "y"}:
        # the same rule as view validation; unvalidated previews reach this point
        raise ConfigError("pareto keys are x and y")
    board = scope.board()
    primary = board.primary
    y_ref = panel.data.y or primary
    board_rows = {row.group_id: row for row in board.rows}
    y_name, y_version = parse_metric_version(y_ref.partition("/")[0])
    y_key = y_ref.partition("/")[2] or "value"
    # the board's test-set interval belongs to the primary at the board's metric version;
    # an explicit other version (accuracy@v0 while the board uses v1) keeps seed intervals
    board_version = y_version is None or y_version == board.metric_versions.get(y_name)
    y_is_primary = (
        (panel.data.group_by or "group") == "group"
        and f"{y_name}/{y_key}" == primary
        and board_version
    )
    higher = _y_higher_is_better(scope, y_ref)
    groups = _groups(scope, panel)
    versions = _run_versions(scope) if x_ref == VERSION_REF else {}

    def text_of(r: RunRecord) -> str | None:
        return versions[r.run_id][1] if x_ref == VERSION_REF else _param_raw(r, x_ref)

    ordinal = _is_ordinal(groups, x_ref, text_of)
    rows: list[dict[str, Any]] = []
    for key, label, members in groups:
        seeds: list[dict[str, Any]] = []
        for r in members:
            if ordinal:
                x: float | str | None = text_of(r)
            elif x_ref == VERSION_REF:
                x = _as_float(versions[r.run_id][1])
            else:
                x = _run_value(scope, r, x_ref)
            y = _run_value(scope, r, y_ref)
            if x is not None and y is not None:
                seeds.append({"x": x, "y": y})
        if not seeds:
            continue
        ys = [s["y"] for s in seeds]
        x_lo: float | None = None
        x_hi: float | None = None
        if ordinal:
            x_mid: float | str = ", ".join(sorted({s["x"] for s in seeds}, key=_natural_key))
        else:
            xs = [s["x"] for s in seeds]
            x_mid = math.fsum(xs) / len(xs)
            x_lo, x_hi = _interval(xs)
        y_lo, y_hi = _interval(ys)
        board_row = board_rows.get(key)
        test = board_row.test_interval if y_is_primary and board_row is not None else None
        if test is not None:
            y_lo, y_hi = test.lo, test.hi
        rows.append(
            {
                "group_id": key,
                "label": label,
                "x": x_mid,
                "x_lo": x_lo,
                "x_hi": x_hi,
                "y": math.fsum(ys) / len(ys),
                "y_lo": y_lo,
                "y_hi": y_hi,
                "seeds": seeds,
                "pareto": False,
                "regression": False,
            }
        )
    if ordinal:
        # version axis: groups with a version param value first, then fallback times
        from_param = {
            key: any(versions[r.run_id][0] for r in members) if versions else True
            for key, _, members in groups
        }
        rows.sort(key=lambda row: (not from_param[row["group_id"]], _natural_key(row["x"])))
        _mark_regressions(rows, higher)
    elif panel.pareto:
        _mark_pareto(rows, panel.pareto)
    best = (max if higher else min)(rows, key=lambda row: row["y"]) if rows else None
    return PanelResult(
        type="scatter",
        title=panel.title,
        rows=rows,
        meta={
            "x": x_ref,
            "y": y_ref,
            "x_type": "ordinal" if ordinal else "quantitative",
            "scale": panel.scale,
            "pareto": panel.pareto,
            "y_higher_is_better": higher,
            "best_group": best["group_id"] if best is not None else None,
        },
    )


def _mark_pareto(rows: list[dict[str, Any]], directions: Mapping[str, str]) -> None:
    """Set ``pareto`` on rows that no other row dominates."""
    axes = [(axis, 1.0 if d == "max" else -1.0) for axis, d in directions.items()]

    def better_or_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
        return all(sign * a[axis] >= sign * b[axis] for axis, sign in axes)

    def strictly_better(a: dict[str, Any], b: dict[str, Any]) -> bool:
        return any(sign * a[axis] > sign * b[axis] for axis, sign in axes)

    for row in rows:
        row["pareto"] = not any(
            other is not row and better_or_equal(other, row) and strictly_better(other, row)
            for other in rows
        )


def _y_higher_is_better(scope: _Scope, y_ref: str) -> bool:
    """
    Direction of a scatter y reference.

    ``usage.*`` (cost, tokens, time) is lower-is-better; the task's primary
    uses the leaderboard's direction; another configured metric uses its
    ``higher_is_better``; any other name is lower-is-better when it names a
    loss or an error.
    """
    if y_ref.startswith("usage."):
        return False
    board = scope.board()
    head, _, key = y_ref.partition("/")
    name, _ = parse_metric_version(head)
    if f"{name}/{key or 'value'}" == board.primary:
        return board.higher_is_better
    metrics = scope.entry.config.metrics
    if name in metrics:
        return metrics[name].higher_is_better
    return not _lower_is_better(y_ref)


def _mark_regressions(rows: list[dict[str, Any]], higher: bool) -> None:
    """
    Flag rows worse than the best earlier row by more than its interval allows.

    ``rows`` are in axis order. Higher-is-better: a row regresses when its
    ``y_hi`` is below the best earlier row's ``y_lo``; lower-is-better: when
    its ``y_lo`` is above the best earlier row's ``y_hi``. A ``None`` bound on
    either side flags nothing. Ties keep the earlier row as best.
    """
    best: dict[str, Any] | None = None
    for row in rows:
        if best is not None:
            mine = row["y_hi"] if higher else row["y_lo"]
            bound = best["y_lo"] if higher else best["y_hi"]
            if mine is not None and bound is not None:
                row["regression"] = mine < bound if higher else mine > bound
        if best is None or (row["y"] > best["y"] if higher else row["y"] < best["y"]):
            best = row
```

Replace the whole `_HANDLERS = { ... }` dict at the end of the file with:

```python
_HANDLERS = {
    "stat_strip": _stat_strip,
    "leaderboard": _leaderboard,
    "curves": _curves,
    "scatter": _scatter,
    "table": _table,
    "vega_lite": _vega_lite,
    "trace": _trace,
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_panels.py -v`
Expected: `38 passed`.

Run: `uv run ruff check src/hypothex/core/panels.py tests/core/test_panels.py && uv run ruff format --check src/hypothex/core/panels.py tests/core/test_panels.py && uv run ty check src/hypothex/core/panels.py`
Expected: all clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/panels.py tests/core/test_panels.py
git commit -m "feat: scatter panel with seed intervals, pareto front, ordinal x; metric stat strips"
```

---

### Task 23: Distribution and grid panels

**Files:**
- Modify: `src/hypothex/core/panels.py` (imports/constants block, new functions above `_HANDLERS`, `_HANDLERS`)
- Test: `tests/core/test_panels.py` (append tests)

**Interfaces:**
- Consumes: Tasks 20–22 (`_Scope`, `_groups`, `_samples`); `stats.quantile`, `stats.ecdf_points(values, max_points=200)` (contract 1.1); `sources.iter_rows(..., "predictions")`; `TaskSpec.baseline` (Task 5); `PanelSpec.render` (Task 15).
- Produces:
  - `distribution` rows `{group_id, label, n, p50, p95, p99, ecdf: [[x, y], ...], seeds: [{run_id, p50, p95, p99}]}`; values are the samples named `data.metrics[0]` (or `data.x`), or per-example `usage.jsonl` values for `usage.<field>`; seeds pooled for the group numbers; `ecdf` is `ecdf_points(pooled, max_points=200)` (≤ 200 points); `meta` = `name, scale, render, baseline`. Neither `data.metrics` nor `data.x` → `ConfigError`.
  - `vs_baseline` on every distribution row (contract 1.6): `{p50: [delta_rel, lo, hi], p95: [...], p99: [...]}` or `None`. `_baseline_key(selector, groups)` picks the baseline among the panel's groups with the leaderboard's `_select_group` rules: `tag:<t>` → the first group with a member tagged `<t>`; else the first group whose key starts with the selector (a full or prefix `group_id`) or has a member with that `config_hash`. `meta.baseline` is that row's `group_id` (`None` when no baseline is configured, none matches, or the match has no samples). `delta_rel = (row.pXX - base.pXX) / base.pXX` on pooled percentiles; `lo`/`hi` from `_rel_change_interval(row_seed_values, base_seed_values)`: 1000 resamples with a fresh `random.Random(0)` per percentile, each resample draws the row's per-seed values with replacement (`rng.choices`, k = n), then the baseline's, and records `(mean_row - mean_base) / mean_base` (skipped when `mean_base == 0`); `lo`, `hi` = `stats.quantile` 0.025 / 0.975 of those; both `None` when either side has fewer than 2 seeds. The baseline row gets `None`; so does every row when a baseline percentile is 0.
  - `grid` rows `{item_id, group_id, value}` with `value` = solved seeds / seeds scored for that item; metric = `data.metrics[0]` or the task's primary metric (current version unless `name@version`); field = `data.y`, else `correct`, else `solved`, else the first boolean per-example field; solved means not `False` and not `0`. `meta.items` sorted by mean value ascending (hardest first, ties by id); `meta.groups` `[{group_id, label}]` sorted by mean value descending (ties by id); `meta.field` = the column used, e.g. `accuracy@v1.correct`. Unknown metric → `ConfigError("grid panel: unknown metric ...")`.

- [ ] **Step 1: Write the failing tests**

Append to the end of `tests/core/test_panels.py` (`_set_task` and `import yaml` come from Task 20):

```python
# distribution ----------------------------------------------------------------------
def test_distribution_quantiles_seeds_and_ecdf(ctx: Context, toy_repo: Path) -> None:
    d1 = _run(ctx, toy_repo, "d1", hypothesis="fast", minute=0)
    d2 = _run(ctx, toy_repo, "d2", hypothesis="fast", minute=1)
    e1 = _run(ctx, toy_repo, "e1", "bbbb", hypothesis="slow", minute=2)
    _jsonl(ctx.run_dir(d1) / "samples" / "latency_ms.jsonl", [{"value": v} for v in range(1, 101)])
    _jsonl(
        ctx.run_dir(d2) / "samples" / "latency_ms.jsonl", [{"value": v} for v in range(101, 201)]
    )
    _jsonl(ctx.run_dir(e1) / "samples" / "latency_ms.jsonl", [{"value": v} for v in range(1, 1001)])
    panel = _panel("distribution", data={"metrics": ["latency_ms"]}, scale="log")
    result = query_panel(ctx, "toy", "toy-acc", panel)
    fast, slow = result.rows
    # numpy "linear" quantile of 1..200: 1 + q * 199
    assert (fast["group_id"], fast["label"], fast["n"]) == ("aaaa@c1", "fast", 200)
    assert fast["p50"] == pytest.approx(100.5)
    assert fast["p95"] == pytest.approx(190.05)
    assert fast["p99"] == pytest.approx(198.01)
    # per seed: 1..100 -> 1 + q * 99; 101..200 -> 101 + q * 99
    assert fast["seeds"] == [
        {
            "run_id": "d1",
            "p50": pytest.approx(50.5),
            "p95": pytest.approx(95.05),
            "p99": pytest.approx(99.01),
        },
        {
            "run_id": "d2",
            "p50": pytest.approx(150.5),
            "p95": pytest.approx(195.05),
            "p99": pytest.approx(199.01),
        },
    ]
    assert slow["n"] == 1000
    assert len(slow["ecdf"]) <= 200  # downsampled
    assert slow["ecdf"][-1] == [1000.0, 1.0]
    xs = [p[0] for p in slow["ecdf"]]
    assert xs == sorted(xs)
    assert [r["vs_baseline"] for r in result.rows] == [None, None]  # no baseline configured
    assert result.meta == {
        "name": "latency_ms",
        "scale": "log",
        "render": "chart",
        "baseline": None,
    }


def _latency_groups(ctx: Context, repo: Path) -> None:
    """base: 3 repeats tagged baseline; fast: the same samples halved; one: a single repeat."""
    runs = [
        ("b1", "aaaa", "base", ["baseline"], [float(v) for v in range(1, 101)]),
        ("b2", "aaaa", "base", ["baseline"], [float(v) for v in range(11, 111)]),
        ("b3", "aaaa", "base", ["baseline"], [float(v) for v in range(21, 121)]),
        ("f1", "bbbb", "fast", [], [v / 2 for v in range(1, 101)]),
        ("f2", "bbbb", "fast", [], [v / 2 for v in range(11, 111)]),
        ("f3", "bbbb", "fast", [], [v / 2 for v in range(21, 121)]),
        ("c1", "cccc", "one", [], [0.8 * v for v in range(11, 111)]),
    ]
    for minute, (rid, group, hyp, tags, values) in enumerate(runs):
        rec = _run(ctx, repo, rid, group, minute=minute, hypothesis=hyp, tags=tags)
        _jsonl(ctx.run_dir(rec) / "samples" / "latency_ms.jsonl", [{"value": v} for v in values])


def test_distribution_vs_baseline_with_repeat_bootstrap(ctx: Context, toy_repo: Path) -> None:
    _latency_groups(ctx, toy_repo)
    _set_task(toy_repo, baseline="tag:baseline")
    panel = _panel("distribution", data={"metrics": ["latency_ms"]}, render="table")
    result = query_panel(ctx, "toy", "toy-acc", panel)
    assert result.meta == {
        "name": "latency_ms",
        "scale": "linear",
        "render": "table",
        "baseline": "aaaa@c1",
    }
    base, fast, one = result.rows
    assert base["vs_baseline"] is None  # the baseline row itself
    # pooled: base p50 60.5, p95 108.0, p99 117.01; fast is every sample halved -> -50%
    # per-seed p50: base [50.5, 60.5, 70.5], fast [25.25, 30.25, 35.25]; 1000 resamples
    # with random.Random(0) per percentile, 2.5th/97.5th percentile of
    # (mean(fast draw) - mean(base draw)) / mean(base draw)
    delta = fast["vs_baseline"]
    assert list(delta) == ["p50", "p95", "p99"]
    assert delta["p50"] == pytest.approx([-0.5, -0.5992555831265508, -0.38320140086109644])
    assert delta["p95"] == pytest.approx([-0.5, -0.5596747724899299, -0.43440294760377146])
    assert delta["p99"] == pytest.approx([-0.5, -0.5576319050226204, -0.43686312004044475])
    # one repeat: the change is known, the interval is not
    # pooled p50 48.4, p95 84.04, p99 87.208 vs 60.5, 108.0, 117.01
    assert one["vs_baseline"]["p50"][0] == pytest.approx(-0.2)
    assert one["vs_baseline"]["p95"][0] == pytest.approx(84.04 / 108.0 - 1)
    assert one["vs_baseline"]["p99"][0] == pytest.approx(87.208 / 117.01 - 1)
    assert [v[1:] for v in one["vs_baseline"].values()] == [[None, None]] * 3


def test_distribution_baseline_selectors(ctx: Context, toy_repo: Path) -> None:
    _latency_groups(ctx, toy_repo)
    panel = _panel("distribution", data={"metrics": ["latency_ms"]})

    def rows() -> list[dict[str, Any]]:
        return query_panel(ctx, "toy", "toy-acc", panel).rows

    assert [r["vs_baseline"] for r in rows()] == [None, None, None]  # no baseline
    _set_task(toy_repo, baseline="tag:nothing")
    assert [r["vs_baseline"] for r in rows()] == [None, None, None]  # no group matches
    _set_task(toy_repo, baseline="bbbb")  # a group_id prefix: fast is the baseline
    base, fast, one = rows()
    assert fast["vs_baseline"] is None
    assert base["vs_baseline"]["p50"][0] == pytest.approx(1.0)  # 60.5 vs 30.25
    assert one["vs_baseline"]["p99"][0] == pytest.approx(87.208 / 58.505 - 1)
    assert one["vs_baseline"]["p99"][1:] == [None, None]
    _set_task(toy_repo, baseline="sha256:cccc")  # a config hash: one is the baseline
    base, fast, one = rows()
    assert one["vs_baseline"] is None
    assert base["vs_baseline"]["p50"] == [pytest.approx(60.5 / 48.4 - 1), None, None]


def test_distribution_over_usage_field(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "u1")
    _jsonl(ctx.run_dir(rec) / "usage.jsonl", [{"seconds": s} for s in (1.0, 2.0, 3.0)])
    (row,) = query_panel(
        ctx, "toy", "toy-acc", _panel("distribution", data={"x": "usage.seconds"})
    ).rows
    assert (row["n"], row["p50"]) == (3, 2.0)


# grid ------------------------------------------------------------------------------
def test_grid_fraction_solved_and_difficulty_order(ctx: Context, toy_repo: Path) -> None:
    outcomes = {
        "a1": ("aaaa", "alpha", [True, False, True]),
        "a2": ("aaaa", "alpha", [True, False, False]),
        "b1": ("bbbb", "beta", [True, True, False]),
    }
    for minute, (rid, (group, hyp, solved)) in enumerate(outcomes.items()):
        rec = _run(ctx, toy_repo, rid, group, hypothesis=hyp, minute=minute)
        pred = ctx.run_dir(rec) / "predictions"
        _jsonl(pred / "predictions.jsonl", [{"id": f"ex-{i}", "prediction": 0} for i in range(3)])
        _jsonl(
            pred / "scores.accuracy@v1.jsonl",
            [{"id": f"ex-{i}", "correct": ok} for i, ok in enumerate(solved)],
        )
    result = query_panel(ctx, "toy", "toy-acc", _panel("grid"))
    # alpha: ex-0 2/2, ex-1 0/2, ex-2 1/2; beta: ex-0 1, ex-1 1, ex-2 0
    # item means: ex-0 1.0, ex-1 0.5, ex-2 0.25 -> hardest first
    assert result.meta["items"] == ["ex-2", "ex-1", "ex-0"]
    # group means: beta 2/3 > alpha 1/2
    assert result.meta["groups"] == [
        {"group_id": "bbbb@c1", "label": "beta"},
        {"group_id": "aaaa@c1", "label": "alpha"},
    ]
    assert result.meta["field"] == "accuracy@v1.correct"
    assert result.rows == [
        {"item_id": "ex-2", "group_id": "bbbb@c1", "value": 0.0},
        {"item_id": "ex-2", "group_id": "aaaa@c1", "value": 0.5},
        {"item_id": "ex-1", "group_id": "bbbb@c1", "value": 1.0},
        {"item_id": "ex-1", "group_id": "aaaa@c1", "value": 0.0},
        {"item_id": "ex-0", "group_id": "bbbb@c1", "value": 1.0},
        {"item_id": "ex-0", "group_id": "aaaa@c1", "value": 1.0},
    ]


def test_grid_uses_explicit_field_and_rejects_unknown_metric(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "a1")
    pred = ctx.run_dir(rec) / "predictions"
    _jsonl(pred / "predictions.jsonl", [{"id": "ex-0", "prediction": 0}])
    _jsonl(pred / "scores.accuracy@v1.jsonl", [{"id": "ex-0", "correct": True, "partial": 0}])
    panel = _panel("grid", data={"metrics": ["accuracy@v1"], "y": "partial"})
    assert query_panel(ctx, "toy", "toy-acc", panel).rows == [
        {"item_id": "ex-0", "group_id": "aaaa@c1", "value": 0.0}
    ]
    with pytest.raises(ConfigError, match="unknown metric 'nope'"):
        query_panel(ctx, "toy", "toy-acc", _panel("grid", data={"metrics": ["nope"]}))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_panels.py -v`
Expected: `6 failed, 38 passed`; the tests fail with `KeyError: 'distribution'` or `KeyError: 'grid'`.

- [ ] **Step 3: Implement distribution and grid**

In `src/hypothex/core/panels.py`: Replace everything from the line `import copy` down to and including the last module-level constant (the line just before the two blank lines above `class PanelResult`) with:

```python
import copy
import math
import random
import statistics
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC
from typing import Any

from pydantic import BaseModel, Field

from hypothex.core.config import parse_metric_key, parse_metric_version
from hypothex.core.context import Context
from hypothex.core.errors import ConfigError, HypothexError
from hypothex.core.fsutil import read_jsonl
from hypothex.core.headlines import fmt_value
from hypothex.core.leaderboard import (
    Leaderboard,
    _natural_key,
    build_leaderboard,
    group_id_for,
    group_label,
    pick_field,
)
from hypothex.core.queries import primary_examples, refresh_project
from hypothex.core.records import Artifact, MetricPoint, RunRecord, RunStatus
from hypothex.core.seeds import summarize
from hypothex.core.sources import iter_rows, select_fields
from hypothex.core.stats import ecdf_points, quantile
from hypothex.core.store import ProjectEntry
from hypothex.core.views import (
    VERSION_REF,
    PanelSpec,
    PanelType,
    RunFilter,
    ViewSpec,
    vega_spec_problems,
)

MAX_TABLE_ROWS = 5000
SPIKE_WINDOW = 20
SPIKE_FACTOR = 5.0
AGGREGATES = ("mean", "median", "min", "max", "p50", "p90", "p95", "p99")
PERCENTILES = (("p50", 0.50), ("p95", 0.95), ("p99", 0.99))
BOOTSTRAP_RESAMPLES = 1000
```

Insert the following functions immediately above the line `_HANDLERS = {`:

```python
def _usage_values(scope: _Scope, run: RunRecord, field_name: str) -> list[float]:
    rows = scope.ctx.store.read_usage(run.project, run.run_id)
    values = [getattr(row, field_name, None) for row in rows]
    return [float(v) for v in values if isinstance(v, int | float) and not isinstance(v, bool)]


def _distribution_values(scope: _Scope, run: RunRecord, name: str) -> list[float]:
    if name.startswith("usage."):
        return _usage_values(scope, run, name.removeprefix("usage."))
    return _samples(scope, run, name)


def _baseline_key(
    selector: str | None, groups: list[tuple[str, str, list[RunRecord]]]
) -> str | None:
    """
    The key of the group ``TaskSpec.baseline`` selects, or ``None``.

    Same rules as the leaderboard's ``_select_group``: ``tag:<t>`` is the first
    group with a run tagged ``<t>``; anything else is a full or prefix
    ``group_id`` or a ``config_hash``.
    """
    if not selector:
        return None
    if selector.startswith("tag:"):
        tag = selector.removeprefix("tag:")
        return next((k for k, _, members in groups if any(tag in m.tags for m in members)), None)
    for key, _, members in groups:
        if key.startswith(selector) or any(m.config_hash == selector for m in members):
            return key
    return None


def _rel_change_interval(
    values: list[float], base: list[float], resamples: int = BOOTSTRAP_RESAMPLES, seed: int = 0
) -> tuple[float | None, float | None]:
    """
    Percentile bootstrap 95% interval of ``mean(values) / mean(base) - 1``.

    Each resample draws ``values`` then ``base`` with replacement from one
    ``random.Random(seed)``; resamples whose base mean is 0 are skipped.
    ``(None, None)`` when either side has fewer than 2 values.
    """
    if len(values) < 2 or len(base) < 2:
        return None, None
    rng = random.Random(seed)
    deltas: list[float] = []
    for _ in range(resamples):
        drawn = rng.choices(values, k=len(values))
        drawn_base = rng.choices(base, k=len(base))
        base_mean = math.fsum(drawn_base) / len(drawn_base)
        if base_mean != 0:
            deltas.append((math.fsum(drawn) / len(drawn) - base_mean) / base_mean)
    if not deltas:
        return None, None
    return quantile(deltas, 0.025), quantile(deltas, 0.975)


def _vs_baseline(row: dict[str, Any], base: dict[str, Any]) -> dict[str, list[float | None]] | None:
    """Relative change of each percentile vs the baseline row, with a repeat-bootstrap CI."""
    if row is base or any(base[p] == 0 for p, _ in PERCENTILES):
        return None
    out: dict[str, list[float | None]] = {}
    for p, _ in PERCENTILES:
        lo, hi = _rel_change_interval([s[p] for s in row["seeds"]], [s[p] for s in base["seeds"]])
        out[p] = [(row[p] - base[p]) / base[p], lo, hi]
    return out


def _distribution(scope: _Scope, panel: PanelSpec) -> PanelResult:
    """
    Pooled percentiles and ECDF per group, per-seed percentiles, and the change
    of each percentile vs the task's baseline group (``vs_baseline``).
    """
    name = panel.data.metrics[0] if panel.data.metrics else panel.data.x
    if not name:
        raise ConfigError("distribution panel needs data.metrics or data.x")
    groups = _groups(scope, panel)
    rows: list[dict[str, Any]] = []
    for key, label, members in groups:
        pooled: list[float] = []
        seeds: list[dict[str, Any]] = []
        for r in members:
            values = _distribution_values(scope, r, name)
            if not values:
                continue
            pooled.extend(values)
            seeds.append({"run_id": r.run_id, **{p: quantile(values, q) for p, q in PERCENTILES}})
        if not pooled:
            continue
        rows.append(
            {
                "group_id": key,
                "label": label,
                "n": len(pooled),
                **{p: quantile(pooled, q) for p, q in PERCENTILES},
                "ecdf": [[x, y] for x, y in ecdf_points(pooled, max_points=200)],
                "seeds": seeds,
                "vs_baseline": None,
            }
        )
    base_key = _baseline_key(scope.entry.config.tasks[scope.task].baseline, groups)
    base = next((row for row in rows if row["group_id"] == base_key), None)
    if base is not None:
        for row in rows:
            row["vs_baseline"] = _vs_baseline(row, base)
    return PanelResult(
        type="distribution",
        title=panel.title,
        rows=rows,
        meta={
            "name": name,
            "scale": panel.scale,
            "render": panel.render,
            "baseline": base["group_id"] if base is not None else None,
        },
    )


def _is_solved(value: Any) -> bool:
    return not (value is False or (isinstance(value, int | float) and value == 0))


def _grid(scope: _Scope, panel: PanelSpec) -> PanelResult:
    config = scope.entry.config
    if panel.data.metrics:
        ref = panel.data.metrics[0]
    else:
        ref = parse_metric_key(config.tasks[scope.task].primary)[0]
    name, version = parse_metric_version(ref.partition("/")[0])
    if name not in config.metrics:
        raise ConfigError(f"grid panel: unknown metric {name!r}")
    prefix = f"{name}@{version or config.metrics[name].version}."
    groups = _groups(scope, panel)
    group_of = {r.run_id: key for key, _, members in groups for r in members}
    pred_rows = list(iter_rows(scope.ctx, scope.runs, "predictions"))
    column = f"{prefix}{panel.data.y}" if panel.data.y else _solved_column(pred_rows, prefix)
    solved: dict[tuple[str, str], list[bool]] = defaultdict(list)
    for row in pred_rows:
        if column is not None and row.get(column) is not None:
            solved[(row["id"], group_of[row["run_id"]])].append(_is_solved(row[column]))
    cells = {k: sum(v) / len(v) for k, v in solved.items()}
    by_item: dict[str, list[float]] = defaultdict(list)
    by_group: dict[str, list[float]] = defaultdict(list)
    for (item, gid), value in cells.items():
        by_item[item].append(value)
        by_group[gid].append(value)
    items = sorted(by_item, key=lambda i: (math.fsum(by_item[i]) / len(by_item[i]), i))
    labels = {key: label for key, label, _ in groups}
    gids = sorted(by_group, key=lambda g: (-math.fsum(by_group[g]) / len(by_group[g]), g))
    rows = [
        {"item_id": item, "group_id": gid, "value": cells[(item, gid)]}
        for item in items
        for gid in gids
        if (item, gid) in cells
    ]
    return PanelResult(
        type="grid",
        title=panel.title,
        rows=rows,
        meta={
            "items": items,
            "groups": [{"group_id": g, "label": labels[g]} for g in gids],
            "field": column,
        },
    )


def _solved_column(rows: list[dict[str, Any]], prefix: str) -> str | None:
    columns = {k for row in rows for k in row if k.startswith(prefix)}
    for preferred in ("correct", "solved"):
        if f"{prefix}{preferred}" in columns:
            return f"{prefix}{preferred}"
    for row in rows:
        for k, v in row.items():
            if k.startswith(prefix) and isinstance(v, bool):
                return k
    return None
```

Replace the whole `_HANDLERS = { ... }` dict at the end of the file with:

```python
_HANDLERS = {
    "stat_strip": _stat_strip,
    "leaderboard": _leaderboard,
    "curves": _curves,
    "scatter": _scatter,
    "distribution": _distribution,
    "grid": _grid,
    "table": _table,
    "vega_lite": _vega_lite,
    "trace": _trace,
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_panels.py -v tests/core/test_sources.py`
Expected: `56 passed`.

Run: `uv run ruff check src/hypothex/core/panels.py tests/core/test_panels.py && uv run ruff format --check src/hypothex/core/panels.py tests/core/test_panels.py && uv run ty check src/hypothex/core/panels.py`
Expected: all clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/panels.py tests/core/test_panels.py
git commit -m "feat: distribution and grid panels"
```

## Part 6: Overview and demo seed (Tasks 24–29)

Contract sections 1.9 (`hypothex.core.overview`) and 1.11 (`hypothex.demo`). This part runs after the parts that add stats, records, config, views, leaderboard, headlines, and the SDK additions; it uses their contract names as they are.

**Files (this part only):**
- Create: `src/hypothex/core/overview.py`, `tests/core/test_overview.py`
- Create: `src/hypothex/demo.py`, `tests/test_demo.py`

**How the demo stays faithful to the mockups.** The mockups' generators (`mulberry32`, Box-Muller, `Math.round`, `toFixed`, `Float32Array`) are ported bit for bit. Every expected value in `tests/test_demo.py` was printed by `bun` from `docs/mockups/kinds/*/data.js` (or `docs/mockups/ui-v4/data.js` for the generic kind) and matched by the port before this plan was written. Seeding all five kinds takes about 2.5 s.

**Decisions this part makes (the contract leaves them open):**
- `seed_demo` keeps the fixed signature. It moves every mockup timestamp so that `DEMO_EPOCH` (2026-09-27T12:00Z) falls on the current UTC hour. Reason: the Overview's default 24-hour window must show runs whenever the demo is seeded. Numbers never change; the same hour gives the same run ids. Tests use the private `_seed_demo(home, kinds, anchor)` with `anchor=DEMO_EPOCH`, which is fully deterministic.
- Demo runs use `environment_id = "demo:<host>"`, so `repair_runs` on `hx serve` start-up never marks the demo's running run as lost.
- The training kind adds one run that is still running (not in the mockup), so the Overview's "Running" panel has content. The other kinds add nothing that is not in their mockup, except one failed first attempt before cache repeat 3 (the mockup shows it as attempt 1 inside that run).
- `seed_demo` refuses to write into a home that already has one of the requested demo projects (`StoreError`, nothing written). An unknown kind raises `ValueError` before the home is touched.
- Overview: `ideas` leave out archived runs (the timeline still shows them). `failures` include archived runs (the ui-v4 mockup shows archived failures with "retry ok"). `counts["running"]` and `counts["queued"]` count current active runs; the other counts are for runs created in the window. A failure counts as retried when a later finished run in the same task has it as `parent`, is in the same seed group, or has the same non-empty hypothesis.
- Labels for runs whose group is not on a leaderboard use `leaderboard.group_label` (Task 10): the first clause of the hypothesis (a `.` only ends a clause when a space or the end follows, so `Opus 5.5` stays whole), else a tag, else `group <id>`.

---

### Task 24: Cross-project overview (`hypothex.core.overview`)

**Files:**
- Create: `src/hypothex/core/overview.py`
- Test: `tests/core/test_overview.py`

**Interfaces:**
- Consumes:
  - `hypothex.core.queries.list_projects(ctx) -> list[ProjectEntry]`, `get_leaderboard(ctx, ref, project=None, versions=None) -> Leaderboard` (loads per-example data, contract 1.7).
  - `hypothex.core.leaderboard.Leaderboard`, `LeaderboardRow` (`group_id`, `run_ids`, `label`, `primary`, `test_interval`, `identical_seeds`), `NoiseInterval` (contract 1.7), and the shared helpers `group_id_for`, `group_label` (Task 10).
  - `hypothex.core.headlines.overview_headline(summary: OverviewSummary, *, board: Leaderboard | None = None) -> str` (contract 1.8, Task 13). `build_overview` passes `board=` the leaderboard of the newest scored idea's task (the same focus rule as Task 13's `_summary_lead`), so the headline carries the p-value: `"Idle. SVM leads toy-test by 0.037, p = 0.15"`.
  - `hypothex.core.config.TaskKind`, `TaskSpec.kind` (contract 1.3); `hypothex.core.seeds.Stats`; `hypothex.core.records.ACTIVE_STATUSES`, `RunRecord`, `RunStatus`.
- Produces (contract 1.9, exact):
  - `TimelineItem(run_id, project, task: str | None, created_at, created_by, status: RunStatus, archived, group_id: str | None, is_best, label)`
  - `IdeaRow(project, task: str | None, group_id, label, created_by, created_at, statuses: list[RunStatus], primary: Stats | None, test_interval: NoiseInterval | None, identical_seeds, best_band: NoiseInterval | None)`
  - `FailureRow(run_id, label, exit_code: int | None, created_at, stderr_path, retried_ok)`
  - `ProjectRow(project, task: str | None, runs: int, best: float | None, kind: TaskKind)`
  - `OverviewSummary(headline, counts: dict[str, int], timeline, ideas, running: list[RunRecord], failures, projects)`
  - `build_overview(ctx: Context, since: datetime | None = None) -> OverviewSummary` (default window: 24 h).
  - Module constants `DEFAULT_WINDOW = timedelta(hours=24)`, `FAILED_STATUSES = {failed, lost}`.
  - `counts` keys: `total`, `queued`, `running`, `finished`, `failed`, `killed`, `lost`, `archived`, `agent`, `human`.

- [ ] **Step 1: Write the failing tests**

`tests/core/test_overview.py`:

```python
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from hypothex.core import queries as q
from hypothex.core.context import Context
from hypothex.core.headlines import overview_headline
from hypothex.core.ids import utcnow
from hypothex.core.overview import build_overview
from hypothex.core.records import GitInfo, RunRecord, RunStatus, ScoreRecord
from tests.factories import make_record

# Wilson 95% interval for 4/4 successes: lower = n / (n + z^2) = 4 / (4 + 1.959964^2)
# = 0.510109 (closed form of the Wilson score interval at p_hat = 1; Wilson 1927).
WILSON_4_OF_4_LO = 0.510109


def _run(
    ctx: Context,
    repo: Path,
    run_id: str,
    *,
    ago: timedelta,
    now: datetime,
    status: RunStatus = RunStatus.FINISHED,
    config_hash: str = "sha256:aaaa",
    commit: str = "c1",
    correct: list[bool] | None = None,
    task: str | None = "toy-acc",
    **overrides: object,
) -> RunRecord:
    """Create a run; with ``correct``, also write per-example and run scores."""
    ctx.register_project(repo)
    record = make_record(
        run_id,
        project="toy",
        task=task,
        status=status,
        config_hash=config_hash,
        git=GitInfo(commit=commit),
        created_at=now - ago,
        cwd=str(repo),
        **overrides,
    )
    ctx.create_run(record)
    if correct is not None:
        per_example = ctx.run_dir(record) / "predictions" / "scores.accuracy@v1.jsonl"
        per_example.write_text(
            "".join(
                json.dumps({"id": f"ex-{i}", "correct": ok}) + "\n" for i, ok in enumerate(correct)
            )
        )
        value = sum(correct) / len(correct)
        ctx.add_score(
            record,
            ScoreRecord(
                metric="accuracy", version="v1", key="value", value=value, created_at=now - ago
            ),
        )
    return record


@pytest.fixture
def scene(ctx: Context, toy_repo: Path) -> datetime:
    """
    Runs of project ``toy`` relative to ``now`` (returned):

    a1, a2   group aaaa@c1, 0.75 each (identical seeds), human, 120/119 min ago
    f1       group bbbb@c0, failed exit 2, agent, 90 min ago, same hypothesis as b1
    b1       group bbbb@c1, 1.0, agent, 60 min ago (current best)
    f2       group eeee@c1, failed exit 1, human, 30 min ago, never retried
    x1       group ffff@c1, finished but archived, 20 min ago
    e1       exploratory (no task), finished, 15 min ago
    r1       group cccc@c1, running, 10 min ago
    o1       group dddd@c1, 0.5, 3 days ago (outside the default window)
    """
    now = utcnow()
    three_of_four = [True, True, True, False]
    _run(
        ctx,
        toy_repo,
        "a1",
        ago=timedelta(minutes=120),
        now=now,
        correct=three_of_four,
        seed=1,
        hypothesis="baseline logreg",
    )
    _run(
        ctx,
        toy_repo,
        "a2",
        ago=timedelta(minutes=119),
        now=now,
        correct=three_of_four,
        seed=2,
        hypothesis="baseline logreg",
    )
    _run(
        ctx,
        toy_repo,
        "f1",
        ago=timedelta(minutes=90),
        now=now,
        status=RunStatus.FAILED,
        config_hash="sha256:bbbb",
        commit="c0",
        exit_code=2,
        created_by="agent:x",
        hypothesis="SVM, tuned",
    )
    _run(
        ctx,
        toy_repo,
        "b1",
        ago=timedelta(minutes=60),
        now=now,
        config_hash="sha256:bbbb",
        correct=[True, True, True, True],
        seed=1,
        created_by="agent:x",
        hypothesis="SVM, tuned",
    )
    _run(
        ctx,
        toy_repo,
        "f2",
        ago=timedelta(minutes=30),
        now=now,
        status=RunStatus.FAILED,
        config_hash="sha256:eeee",
        exit_code=1,
        hypothesis="doomed idea",
    )
    _run(
        ctx,
        toy_repo,
        "x1",
        ago=timedelta(minutes=20),
        now=now,
        config_hash="sha256:ffff",
        archived=True,
        hypothesis="debug",
    )
    _run(
        ctx,
        toy_repo,
        "e1",
        ago=timedelta(minutes=15),
        now=now,
        task=None,
        config_hash="sha256:9999",
        hypothesis="",
        tags=["poke"],
    )
    _run(
        ctx,
        toy_repo,
        "r1",
        ago=timedelta(minutes=10),
        now=now,
        status=RunStatus.RUNNING,
        config_hash="sha256:cccc",
        hypothesis="",
    )
    _run(
        ctx,
        toy_repo,
        "o1",
        ago=timedelta(days=3),
        now=now,
        config_hash="sha256:dddd",
        correct=[True, True, False, False],
        hypothesis="old idea",
    )
    return now


def test_timeline_is_window_oldest_first_with_best_and_archived(
    ctx: Context, scene: datetime
) -> None:
    summary = build_overview(ctx)
    assert [t.run_id for t in summary.timeline] == ["a1", "a2", "f1", "b1", "f2", "x1", "e1", "r1"]
    by_id = {t.run_id: t for t in summary.timeline}
    assert [t.run_id for t in summary.timeline if t.is_best] == ["b1"]
    assert by_id["x1"].archived and not by_id["a1"].archived
    assert by_id["a1"].group_id == "aaaa@c1" and by_id["f1"].group_id == "bbbb@c0"
    board = q.get_leaderboard(ctx, "toy-acc", "toy")
    labels = {row.group_id: row.label for row in board.rows}
    assert by_id["a1"].label == labels["aaaa@c1"]
    assert by_id["b1"].label == labels["bbbb@c1"]
    assert by_id["f1"].label == "SVM"  # failed group is not on the board: first clause
    assert by_id["r1"].label == "group cccc@c1"  # no hypothesis, no tags
    assert by_id["e1"].label == "poke" and by_id["e1"].task is None


def test_ideas_one_per_unarchived_group_newest_first(ctx: Context, scene: datetime) -> None:
    summary = build_overview(ctx)
    assert [(i.task, i.group_id) for i in summary.ideas] == [
        ("toy-acc", "cccc@c1"),
        (None, "9999@c1"),
        ("toy-acc", "eeee@c1"),
        ("toy-acc", "bbbb@c1"),
        ("toy-acc", "bbbb@c0"),
        ("toy-acc", "aaaa@c1"),
    ]
    ideas = {i.group_id: i for i in summary.ideas}
    logreg = ideas["aaaa@c1"]
    assert logreg.statuses == [RunStatus.FINISHED, RunStatus.FINISHED]
    assert logreg.primary is not None
    assert logreg.primary.mean == 0.75 and logreg.primary.n == 2
    assert logreg.identical_seeds is True
    assert logreg.created_by == "human" and logreg.created_at == scene - timedelta(minutes=120)
    best = ideas["bbbb@c1"]
    assert best.best_band is not None and best.best_band == best.test_interval
    assert best.best_band.lo == pytest.approx(WILSON_4_OF_4_LO, abs=1e-6)
    assert best.best_band.hi == pytest.approx(1.0)
    assert logreg.best_band == best.test_interval
    assert ideas["cccc@c1"].statuses == [RunStatus.RUNNING] and ideas["cccc@c1"].primary is None
    assert ideas["9999@c1"].best_band is None  # exploratory runs have no leaderboard
    assert ideas["eeee@c1"].identical_seeds is False and ideas["eeee@c1"].test_interval is None


def test_running_failures_counts_and_headline(ctx: Context, scene: datetime) -> None:
    summary = build_overview(ctx)
    assert [r.run_id for r in summary.running] == ["r1"]
    assert [(f.run_id, f.exit_code, f.retried_ok) for f in summary.failures] == [
        ("f2", 1, False),
        ("f1", 2, True),
    ]
    assert summary.failures[1].label == "SVM"
    assert summary.failures[0].stderr_path == str(
        ctx.layout.run_dir("toy", "f2") / "logs" / "stderr.log"
    )
    assert summary.counts == {
        "total": 8,
        "queued": 0,
        "running": 1,
        "finished": 5,
        "failed": 2,
        "killed": 0,
        "lost": 0,
        "archived": 1,
        "agent": 2,
        "human": 6,
    }
    # The newest scored idea is bbbb@c1 (SVM, 1.0), so the focus task is toy-acc and its
    # leaderboard goes in as board=. Runner-up aaaa@c1 (0.75) has 1 discordant example
    # (ex-3: SVM right, logreg wrong): sign_test(1, 0) = 1.0 -> "p = 1.00".
    board = q.get_leaderboard(ctx, "toy-acc", "toy")
    assert summary.headline == overview_headline(summary, board=board)
    assert summary.headline == "1 running. SVM leads toy-acc by 0.250, p = 1.00"


def test_headline_without_scored_ideas_has_no_board(ctx: Context, toy_repo: Path) -> None:
    now = utcnow()
    _run(ctx, toy_repo, "r1", ago=timedelta(minutes=5), now=now, status=RunStatus.RUNNING)
    summary = build_overview(ctx)
    assert summary.headline == overview_headline(summary) == "1 running. No scored runs yet"


def test_projects_table_counts_finished_runs_and_best(ctx: Context, scene: datetime) -> None:
    rows = [(p.project, p.task, p.runs, p.best, p.kind) for p in build_overview(ctx).projects]
    # finished, unarchived runs of toy-acc: a1, a2, b1, o1
    assert rows == [
        ("toy", "toy-acc", 4, 1.0, "generic"),
        ("toy", "toy-broken", 0, None, "generic"),
    ]


def test_since_widens_window_and_naive_since_is_utc(ctx: Context, scene: datetime) -> None:
    wide = build_overview(ctx, since=scene - timedelta(days=4))
    assert wide.timeline[0].run_id == "o1" and wide.counts["total"] == 9
    naive = (scene - timedelta(minutes=25)).replace(tzinfo=None)
    narrow = build_overview(ctx, since=naive)
    assert [t.run_id for t in narrow.timeline] == ["x1", "e1", "r1"]
    assert narrow.failures == []


def test_retry_by_parent_counts_as_retried(ctx: Context, toy_repo: Path) -> None:
    now = utcnow()
    _run(
        ctx,
        toy_repo,
        "p1",
        ago=timedelta(minutes=50),
        now=now,
        status=RunStatus.FAILED,
        config_hash="sha256:1111",
        exit_code=137,
        hypothesis="first try",
    )
    _run(
        ctx,
        toy_repo,
        "p2",
        ago=timedelta(minutes=40),
        now=now,
        config_hash="sha256:2222",
        hypothesis="second try",
        parent="p1",
    )
    _run(
        ctx,
        toy_repo,
        "l1",
        ago=timedelta(minutes=30),
        now=now,
        status=RunStatus.LOST,
        config_hash="sha256:3333",
        hypothesis="lost one",
    )
    failures = build_overview(ctx).failures
    assert [(f.run_id, f.retried_ok) for f in failures] == [("l1", False), ("p1", True)]


def test_empty_home(ctx: Context) -> None:
    summary = build_overview(ctx)
    assert summary.timeline == [] and summary.ideas == [] and summary.projects == []
    assert summary.counts["total"] == 0 and summary.running == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/core/test_overview.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'hypothex.core.overview'`.

- [ ] **Step 3: Write the implementation**

`src/hypothex/core/overview.py`:

```python
"""Cross-project overview: timeline, recent ideas, running runs, failures, projects."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel

from hypothex.core import queries as q
from hypothex.core.config import TaskKind
from hypothex.core.context import Context
from hypothex.core.errors import ConfigError
from hypothex.core.headlines import overview_headline
from hypothex.core.ids import utcnow
from hypothex.core.leaderboard import (
    Leaderboard,
    LeaderboardRow,
    NoiseInterval,
    group_id_for,
    group_label,
)
from hypothex.core.records import ACTIVE_STATUSES, RunRecord, RunStatus
from hypothex.core.seeds import Stats

DEFAULT_WINDOW = timedelta(hours=24)
FAILED_STATUSES = frozenset({RunStatus.FAILED, RunStatus.LOST})


class TimelineItem(BaseModel):
    """One run on the overview timeline."""

    run_id: str
    project: str
    task: str | None
    created_at: datetime
    created_by: str
    status: RunStatus
    archived: bool
    group_id: str | None
    is_best: bool
    label: str


class IdeaRow(BaseModel):
    """One seed group with at least one unarchived run in the window."""

    project: str
    task: str | None
    group_id: str
    label: str
    created_by: str
    created_at: datetime
    statuses: list[RunStatus]
    primary: Stats | None
    test_interval: NoiseInterval | None
    identical_seeds: bool
    best_band: NoiseInterval | None


class FailureRow(BaseModel):
    """A failed or lost run, with where to read its error."""

    run_id: str
    label: str
    exit_code: int | None
    created_at: datetime
    stderr_path: str
    retried_ok: bool


class ProjectRow(BaseModel):
    """One task (or a project without tasks) with its run count and best value."""

    project: str
    task: str | None
    runs: int
    best: float | None
    kind: TaskKind


class OverviewSummary(BaseModel):
    """Everything the Overview screen shows."""

    headline: str
    counts: dict[str, int]
    timeline: list[TimelineItem]
    ideas: list[IdeaRow]
    running: list[RunRecord]
    failures: list[FailureRow]
    projects: list[ProjectRow]


def _short_label(record: RunRecord) -> str:
    """
    Return a short name for a run whose group is not on any leaderboard.

    Parameters
    ----------
    record : RunRecord
        Any run.

    Returns
    -------
    str
        ``leaderboard.group_label`` of the run: the first clause of the
        hypothesis, else the first tag, else ``group <group id>``. For example
        ``"SVM, tuned C"`` gives ``"SVM"``; ``"Opus 5.5 with tools"`` stays whole.
    """
    return group_label(record.hypothesis, record.tags, group_id_for(record))


def _as_utc(moment: datetime) -> datetime:
    """
    Treat a naive datetime as UTC.

    Parameters
    ----------
    moment : datetime
        Aware or naive datetime.

    Returns
    -------
    datetime
        An aware datetime.
    """
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _boards(ctx: Context) -> tuple[dict[tuple[str, str], Leaderboard], list[ProjectRow]]:
    """
    Build every task's leaderboard and the projects table.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.

    Returns
    -------
    boards : dict
        Leaderboard keyed by ``(project, task)``.
    projects : list of ProjectRow
        Sorted by project, then task; projects without tasks get one row
        with ``task=None``.
    """
    boards: dict[tuple[str, str], Leaderboard] = {}
    rows: list[ProjectRow] = []
    for entry in q.list_projects(ctx):
        if not entry.config.tasks:
            finished = ctx.index.list_runs(
                project=entry.project, status=RunStatus.FINISHED, limit=None
            )
            rows.append(
                ProjectRow(
                    project=entry.project, task=None, runs=len(finished), best=None, kind="generic"
                )
            )
            continue
        for task in sorted(entry.config.tasks):
            try:
                board = q.get_leaderboard(ctx, task, entry.project)
            except ConfigError:  # the task vanished between listing and building
                continue
            boards[(entry.project, task)] = board
            best = board.rows[0].primary if board.rows else None
            finished = ctx.index.list_runs(
                project=entry.project, task=task, status=RunStatus.FINISHED, limit=None
            )
            rows.append(
                ProjectRow(
                    project=entry.project,
                    task=task,
                    runs=len(finished),
                    best=best.mean if best is not None else None,
                    kind=entry.config.tasks[task].kind,
                )
            )
    return boards, rows


def _retried_ok(failed: RunRecord, later: list[RunRecord]) -> bool:
    """
    Return whether a later finished run retried a failed one.

    A retry is a run created after the failure, in the same project and task,
    that finished and either has the failed run as ``parent``, is in the same
    seed group, or has the same non-empty hypothesis.

    Parameters
    ----------
    failed : RunRecord
        The failed or lost run.
    later : list of RunRecord
        Candidate runs (any order).

    Returns
    -------
    bool
    """
    gid = group_id_for(failed)
    for run in later:
        if run.status != RunStatus.FINISHED or run.created_at <= failed.created_at:
            continue
        if run.project != failed.project or run.task != failed.task:
            continue
        if (
            run.parent == failed.run_id
            or group_id_for(run) == gid
            or (failed.hypothesis and run.hypothesis == failed.hypothesis)
        ):
            return True
    return False


def build_overview(ctx: Context, since: datetime | None = None) -> OverviewSummary:
    """
    Summarise recent activity across all projects.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    since : datetime, optional
        Start of the window; default 24 hours ago. A naive datetime is read
        as UTC.

    Returns
    -------
    OverviewSummary
        ``timeline`` holds every run created in the window (archived ones too),
        oldest first. ``ideas`` holds one row per seed group with an unarchived
        run in the window, newest group first. ``running`` holds every queued or
        running run regardless of the window, newest first. ``failures`` holds
        failed and lost runs created in the window (archived too), newest first.
        ``counts`` has ``total``, one key per status, ``archived``, ``agent``,
        and ``human`` for runs in the window, except ``running`` and ``queued``,
        which count the current active runs.

    Examples
    --------
    >>> import pathlib, tempfile
    >>> summary = build_overview(Context.open(pathlib.Path(tempfile.mkdtemp())))
    >>> summary.counts["total"], summary.ideas
    (0, [])
    """
    start = _as_utc(since) if since is not None else utcnow() - DEFAULT_WINDOW
    boards, projects = _boards(ctx)
    row_of: dict[tuple[str, str, str], LeaderboardRow] = {}
    best_of: dict[tuple[str, str], LeaderboardRow] = {}
    for (project, task), board in boards.items():
        for row in board.rows:
            row_of[(project, task, row.group_id)] = row
        if board.rows and board.rows[0].primary is not None:
            best_of[(project, task)] = board.rows[0]

    everything = ctx.index.list_runs(include_archived=True, limit=None)
    window = sorted(
        (r for r in everything if r.created_at >= start), key=lambda r: (r.created_at, r.run_id)
    )

    def board_row(run: RunRecord) -> LeaderboardRow | None:
        if run.task is None:
            return None
        return row_of.get((run.project, run.task, group_id_for(run)))

    def label(run: RunRecord) -> str:
        row = board_row(run)
        return row.label if row is not None else _short_label(run)

    timeline: list[TimelineItem] = []
    for run in window:
        best = best_of.get((run.project, run.task)) if run.task is not None else None
        timeline.append(
            TimelineItem(
                run_id=run.run_id,
                project=run.project,
                task=run.task,
                created_at=run.created_at,
                created_by=run.created_by,
                status=run.status,
                archived=run.archived,
                group_id=group_id_for(run),
                is_best=best is not None and run.run_id in best.run_ids,
                label=label(run),
            )
        )

    groups: dict[tuple[str, str | None, str], list[RunRecord]] = {}
    for run in window:
        if not run.archived:
            groups.setdefault((run.project, run.task, group_id_for(run)), []).append(run)
    ideas: list[IdeaRow] = []
    for (project, task, gid), members in groups.items():
        row = board_row(members[0])
        best = best_of.get((project, task)) if task is not None else None
        ideas.append(
            IdeaRow(
                project=project,
                task=task,
                group_id=gid,
                label=row.label if row is not None else _short_label(members[-1]),
                created_by=members[0].created_by,
                created_at=members[0].created_at,
                statuses=[m.status for m in members],
                primary=row.primary if row is not None else None,
                test_interval=row.test_interval if row is not None else None,
                identical_seeds=row.identical_seeds if row is not None else False,
                best_band=best.test_interval if best is not None else None,
            )
        )
    ideas.sort(key=lambda i: (i.created_at, i.group_id), reverse=True)

    running = [r for r in everything if r.status in ACTIVE_STATUSES and not r.archived]
    failures = [
        FailureRow(
            run_id=run.run_id,
            label=label(run),
            exit_code=run.exit_code,
            created_at=run.created_at,
            stderr_path=str(ctx.run_dir(run) / "logs" / "stderr.log"),
            retried_ok=_retried_ok(run, everything),
        )
        for run in reversed(window)
        if run.status in FAILED_STATUSES
    ]

    counts = {"total": len(window)}
    for status in RunStatus:
        counts[status.value] = sum(1 for r in window if r.status == status)
    counts["running"] = sum(1 for r in running if r.status == RunStatus.RUNNING)
    counts["queued"] = sum(1 for r in running if r.status == RunStatus.QUEUED)
    counts["archived"] = sum(1 for r in window if r.archived)
    counts["agent"] = sum(1 for r in window if r.created_by.startswith("agent"))
    counts["human"] = counts["total"] - counts["agent"]

    summary = OverviewSummary(
        headline="",
        counts=counts,
        timeline=timeline,
        ideas=ideas,
        running=running,
        failures=failures,
        projects=projects,
    )
    summary.headline = overview_headline(summary, board=_focus_board(ideas, boards))
    return summary


def _focus_board(
    ideas: list[IdeaRow], boards: dict[tuple[str, str], Leaderboard]
) -> Leaderboard | None:
    """
    Return the leaderboard of the newest scored idea's task, for the headline.

    The focus rule matches ``headlines._summary_lead``; with the board the
    headline also carries the runner-up's p-value.

    Parameters
    ----------
    ideas : list of IdeaRow
        The overview's ideas.
    boards : dict
        Leaderboards keyed by ``(project, task)``.

    Returns
    -------
    Leaderboard or None
        ``None`` when no idea with a task has a primary score.
    """
    scored = [i for i in ideas if i.primary is not None and i.task is not None]
    if not scored:
        return None
    focus = max(scored, key=lambda i: i.created_at)
    return boards.get((focus.project, str(focus.task)))
```

- [ ] **Step 4: Run the tests and checks to verify they pass**

Run: `uv run pytest tests/core/test_overview.py -v`
Expected: `8 passed`.

Run: `uv run ruff check src/hypothex/core/overview.py tests/core/test_overview.py && uv run ruff format --check src/hypothex/core/overview.py tests/core/test_overview.py && uv run ty check src/hypothex/core/overview.py tests/core/test_overview.py`
Expected: `All checks passed!`, `2 files already formatted`, `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/overview.py tests/core/test_overview.py
git commit -m "feat: cross-project overview summary"
```

---

### Task 25: Demo seed core and the generic kind (`hypothex.demo`)

**Files:**
- Create: `src/hypothex/demo.py`
- Test: `tests/test_demo.py`

**Interfaces:**
- Consumes:
  - `hypothex.core.config.TaskKind` and `TaskSpec.kind`, `TaskSpec.baseline`, `TaskSpec.version_param` (contract 1.3).
  - `hypothex.core.records.UsageTotals`, `RunRecord.usage`, `Artifact.step`, `Artifact.metrics` (contract 1.2).
  - `hypothex.sdk.Run.log_trace`, `log_usage`, `log_samples`, `log_checkpoint` (contract 1.10).
  - `hypothex.core.queries.get_leaderboard(ctx, ref, project=None, versions=None) -> Leaderboard` with `Leaderboard.kind` and the 1.7 row fields (used by tests).
  - `hypothex.core.seeds.run_fingerprint`, `config_hash`; `hypothex.core.ids.new_run_id`, `utcnow`; `hypothex.core.fsutil.atomic_write_text`; `hypothex.core.store.sum_usage` and `RunStore.read_usage` (Task 6); `Context.create_run`, `update_run`, `add_score`, `register_project`, `index.replace_metric_points`.
- Produces:
  - `seed_demo(home: Path, kinds: Iterable[TaskKind] = KINDS) -> dict[str, str]` (contract 1.11; returns `{kind: "project/task"}`).
  - `KINDS: tuple[TaskKind, ...]` (all five), `DEMO_EPOCH = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)`, `DEMO_TASKS: dict[str, tuple[str, str]]` (kind to `(project, task)`).
  - Private, used by Tasks 26–29: `_seed_demo(home, kinds, anchor) -> dict[str, str]`, `_SEEDERS: dict[str, Callable[[_Seeder], None]]`, `_Seeder` (`at`, `project`, `start`, `per_example`, `index_progress`, `finish`; `finish` sums usage with `store.sum_usage`, Task 6), `_RunSpec`, `_task_config`, `_jsonl`, and the parity helpers `_mulberry32`, `_gauss`, `_js_round`, `_fixed`, `_clamp`.
  - Demo repos live at `<home>/demo-repos/<project>/` with `hypothex.yaml`, `demo_metrics.py`, and data files.
  - The generic kind: project `toy-classifier`, task `toy-test` (4 seed groups x 3 seeds, 3 archived failed runs with exit 2, 4 archived debug runs), numbers from `docs/mockups/ui-v4/data.js`.

- [ ] **Step 1: Write the failing tests**

`tests/test_demo.py`:

```python
from pathlib import Path
from typing import Any

import pytest

from hypothex.core import queries as q
from hypothex.core.context import Context
from hypothex.core.errors import StoreError
from hypothex.core.records import RunRecord, RunStatus
from hypothex.demo import (
    _SEEDERS,
    DEMO_EPOCH,
    DEMO_TASKS,
    _fixed,
    _js_round,
    _mulberry32,
    _seed_demo,
    seed_demo,
)

REFS = {
    "generic": "toy-classifier/toy-test",
    "training": "rxn-forward/uspto-forward-top1",
    "agent_eval": "retro-agents/retro-bench-200",
    "agent_iteration": "retro-agent/retro-bench-200",
    "system_bench": "route-search/route-api-latency",
}


@pytest.fixture(scope="module")
def demo_home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One home seeded with every kind implemented so far (fixed anchor)."""
    home = tmp_path_factory.mktemp("demo")
    _seed_demo(home, list(_SEEDERS), DEMO_EPOCH)
    return home


@pytest.fixture
def dctx(demo_home: Path) -> Context:
    return Context.open(demo_home)


def _runs(ctx: Context, project: str) -> list[RunRecord]:
    """All runs of a project, oldest first."""
    runs = ctx.index.list_runs(project=project, include_archived=True, limit=None)
    return sorted(runs, key=lambda r: (r.created_at, r.run_id))


def _find(runs: list[RunRecord], seed: int | None = None, **params: str) -> RunRecord:
    """The one run with this seed and these params."""
    hits = [
        r
        for r in runs
        if (seed is None or r.seed == seed) and all(r.params.get(k) == v for k, v in params.items())
    ]
    assert len(hits) == 1, [r.run_id for r in hits]
    return hits[0]


def test_js_parity_helpers() -> None:
    # first three draws of mulberry32(20260927), printed by bun from the mockup's function
    draw = _mulberry32(20260927)
    assert [draw(), draw(), draw()] == [0.5817536343820393, 0.3177114331629127, 0.3009456454310566]
    assert _fixed(12.25, 1) == 12.3  # JS (12.25).toFixed(1) === "12.3"
    assert _js_round(-2.5) == -2 and _js_round(2.5) == 3  # JS Math.round


def test_generic_mirrors_ui_v4(dctx: Context) -> None:
    board = q.get_leaderboard(dctx, REFS["generic"])
    assert board.kind == "generic"
    # ui-v4/data.js: SVM 166/180, rf 158/160/160 of 180, knn 156/180, logreg 149/180
    assert [row.primary.mean for row in board.rows if row.primary] == pytest.approx(
        [166 / 180, 478 / 540, 156 / 180, 149 / 180]
    )
    assert board.rows[1].primary is not None
    assert board.rows[1].primary.std == pytest.approx(0.006415002990995819)  # ui-v4 rf std
    assert [row.n for row in board.rows] == [3, 3, 3, 3]
    assert board.rows[0].identical_seeds and not board.rows[1].identical_seeds
    rf3, svm3 = board.rows[1].run_ids[2], board.rows[0].run_ids[2]
    diff = q.compare_examples(dctx, rf3, svm3, "accuracy")
    assert diff.fixed == [
        "test-0", "test-110", "test-116", "test-12", "test-156", "test-177", "test-21",
        "test-63", "test-83",
    ]  # fmt: skip
    assert diff.broken == ["test-137", "test-167", "test-30"]
    assert (diff.both_pass, diff.both_fail) == (157, 11)
    failed = [r for r in _runs(dctx, "toy-classifier") if r.status == RunStatus.FAILED]
    assert [(r.seed, r.exit_code, r.archived) for r in failed] == [
        (1, 2, True),
        (2, 2, True),
        (3, 2, True),
    ]
    stderr = q.read_log(dctx, failed[0].run_id, "stderr").text
    assert "invalid choice: 'svm'" in stderr
    assert "net +6/180" in q.show_run(dctx, svm3).notes


def test_same_anchor_gives_same_data(demo_home: Path, tmp_path: Path) -> None:
    _seed_demo(tmp_path / "again", list(_SEEDERS), DEMO_EPOCH)
    first, second = Context.open(demo_home), Context.open(tmp_path / "again")
    for kind in _SEEDERS:
        project = DEMO_TASKS[kind][0]
        a, b = _runs(first, project), _runs(second, project)
        assert [r.run_id for r in a] == [r.run_id for r in b]
        for ra, rb in zip(a, b, strict=True):
            assert ra.usage == rb.usage
            assert ra.artifacts == rb.artifacts
            da, db = first.run_dir(ra), second.run_dir(rb)
            written = ["scores.jsonl", "predictions/*.jsonl", "samples/*.jsonl", "traces/*.jsonl"]
            files = sorted(p.relative_to(da) for pattern in written for p in da.glob(pattern))
            assert files == sorted(
                p.relative_to(db) for pattern in written for p in db.glob(pattern)
            )
            for rel in files:
                assert (da / rel).read_bytes() == (db / rel).read_bytes(), rel
            pa = first.store.read_metric_points(project, ra.run_id)
            pb = second.store.read_metric_points(project, rb.run_id)
            assert [(p.name, p.step, p.value) for p in pa] == [
                (p.name, p.step, p.value) for p in pb
            ]


def test_refuses_existing_project_and_unknown_kind(tmp_path: Path) -> None:
    home = tmp_path / "home"
    bad: list[Any] = ["generic", "nope"]
    with pytest.raises(ValueError, match="unknown demo kinds"):
        seed_demo(home, bad)
    assert not home.exists()
    assert seed_demo(home, ["generic", "generic"]) == {"generic": REFS["generic"]}
    ctx = Context.open(home)
    before = len(ctx.index.list_runs(include_archived=True, limit=None))
    with pytest.raises(StoreError, match="already exists"):
        seed_demo(home, ["generic"])
    assert len(ctx.index.list_runs(include_archived=True, limit=None)) == before
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_demo.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'hypothex.demo'`.

- [ ] **Step 3: Write the implementation**

`src/hypothex/demo.py` (Tasks 26–29 insert one section each above the `entry point` marker line and add one entry to `_SEEDERS`):

```python
"""Seed a Hypothex home with demo projects, one per task kind.

The demo mirrors the approved mockups in ``docs/mockups/kinds/*/data.js`` (and
``docs/mockups/ui-v4/data.js`` for the generic kind): the same seeded generators,
ported to Python, produce the same numbers. Every file is written through the
public store, ``Context``, and SDK APIs, so the demo home has the production
layout. Nothing is executed: no training, no metric worker, no git.

Used by UI tests, Playwright, and docs screenshots.

Examples
--------
>>> import pathlib, tempfile
>>> from hypothex.demo import seed_demo
>>> seed_demo(pathlib.Path(tempfile.mkdtemp()), kinds=["generic"])
{'generic': 'toy-classifier/toy-test'}
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import yaml

from hypothex.core.config import TaskKind
from hypothex.core.context import Context
from hypothex.core.errors import StoreError
from hypothex.core.fsutil import atomic_write_text
from hypothex.core.ids import new_run_id, utcnow
from hypothex.core.records import DatasetRef, GitInfo, RunRecord, RunStatus, ScoreRecord
from hypothex.core.seeds import config_hash, run_fingerprint
from hypothex.core.store import sum_usage
from hypothex.sdk import Run

KINDS: tuple[TaskKind, ...] = (
    "generic",
    "training",
    "agent_eval",
    "agent_iteration",
    "system_bench",
)
DEMO_EPOCH = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
"""The "now" of the mockups; demo timestamps keep their distance to it."""

DEMO_TASKS: dict[str, tuple[str, str]] = {
    "generic": ("toy-classifier", "toy-test"),
    "training": ("rxn-forward", "uspto-forward-top1"),
    "agent_eval": ("retro-agents", "retro-bench-200"),
    "agent_iteration": ("retro-agent", "retro-bench-200"),
    "system_bench": ("route-search", "route-api-latency"),
}

_M32 = 0xFFFFFFFF

_METRICS_PY = '''"""Metrics for the Hypothex demo projects."""

from hypothex.metrics import MetricResult


def accuracy(examples):
    per = {e.id: {"correct": e.prediction == e.reference} for e in examples}
    value = sum(v["correct"] for v in per.values()) / max(len(per), 1)
    return MetricResult(values={"value": value}, per_example=per)


def solved(examples):
    per = {e.id: {"solved": e.prediction is not None} for e in examples}
    value = sum(v["solved"] for v in per.values()) / max(len(per), 1)
    return MetricResult(values={"value": value}, per_example=per)


def harness(examples):
    raise RuntimeError("written by the benchmark harness; not computed from predictions")
'''


# --------------------------------------------------------------------- JS parity
def _mulberry32(seed: int) -> Callable[[], float]:
    """
    Return the mockups' seeded uniform generator (mulberry32).

    Parameters
    ----------
    seed : int
        32-bit seed.

    Returns
    -------
    callable
        Each call returns the next float in ``[0, 1)``, bit-identical to the
        JavaScript ``mulberry32`` in the mockups.

    Examples
    --------
    >>> round(_mulberry32(20260927)(), 6)
    0.581754
    """
    state = seed & _M32

    def draw() -> float:
        nonlocal state
        state = (state + 0x6D2B79F5) & _M32
        t = ((state ^ (state >> 15)) * (state | 1)) & _M32
        t = ((t + (((t ^ (t >> 7)) * (t | 61)) & _M32)) & _M32) ^ t
        return ((t ^ (t >> 14)) & _M32) / 4294967296

    return draw


def _gauss(draw: Callable[[], float]) -> float:
    """
    Draw a standard normal value with the Box-Muller transform, as the mockups do.

    Parameters
    ----------
    draw : callable
        Uniform generator from ``_mulberry32``.

    Returns
    -------
    float
    """
    u = 0.0
    while u == 0.0:
        u = draw()
    v = 0.0
    while v == 0.0:
        v = draw()
    return math.sqrt(-2 * math.log(u)) * math.cos(2 * math.pi * v)


def _js_round(x: float) -> int:
    """
    Round half up, like JavaScript ``Math.round``.

    Parameters
    ----------
    x : float
        Value to round.

    Returns
    -------
    int

    Examples
    --------
    >>> _js_round(2.5), _js_round(-2.5)
    (3, -2)
    """
    return math.floor(x + 0.5)


def _fixed(x: float, digits: int) -> float:
    """
    Round like JavaScript ``Number(x.toFixed(digits))``.

    Parameters
    ----------
    x : float
        Value to round.
    digits : int
        Decimal places.

    Returns
    -------
    float

    Examples
    --------
    >>> _fixed(12.25, 1)
    12.3
    """
    exact = Decimal(x).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    return float(exact)


def _clamp(x: float, lo: float, hi: float) -> float:
    """
    Clamp ``x`` to ``[lo, hi]``.

    Parameters
    ----------
    x, lo, hi : float
        Value and bounds.

    Returns
    -------
    float
    """
    return max(lo, min(hi, x))


# --------------------------------------------------------------------- seeding helpers
@dataclass
class _RunSpec:
    """Everything needed to create one demo run record."""

    project: str
    task: str | None
    repo: Path
    hypothesis: str
    command_template: list[str]
    params: dict[str, str]
    seed: int | None
    created_at: datetime
    created_by: str
    host: str
    commit: str
    key: str
    branch: str = "main"
    tags: list[str] = field(default_factory=list)
    archived: bool = False
    datasets: list[DatasetRef] = field(default_factory=list)


class _Seeder:
    """
    Write demo projects and runs into one home.

    Parameters
    ----------
    ctx : Context
        Open context of the demo home.
    anchor : datetime
        Where ``DEMO_EPOCH`` lands; every mockup timestamp keeps its offset.
    """

    def __init__(self, ctx: Context, anchor: datetime) -> None:
        self.ctx = ctx
        self.shift = anchor - DEMO_EPOCH
        self.repos = ctx.layout.home / "demo-repos"

    def at(self, stamp: str) -> datetime:
        """
        Shift a mockup timestamp by the anchor offset.

        Parameters
        ----------
        stamp : str
            ISO timestamp, e.g. ``2026-09-26T14:02:11Z``.

        Returns
        -------
        datetime
            Aware UTC datetime.
        """
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")) + self.shift

    def project(self, config: dict[str, Any], files: dict[str, str]) -> Path:
        """
        Write a demo repo (``hypothex.yaml`` plus files) and register it.

        Parameters
        ----------
        config : dict
            Contents of ``hypothex.yaml``.
        files : dict of str to str
            Extra files, keyed by path relative to the repo.

        Returns
        -------
        Path
            The repo directory, ``<home>/demo-repos/<project>``.
        """
        repo = self.repos / config["project"]
        repo.mkdir(parents=True, exist_ok=True)
        atomic_write_text(repo / "hypothex.yaml", yaml.safe_dump(config, sort_keys=False))
        atomic_write_text(repo / "demo_metrics.py", _METRICS_PY)
        for rel, text in files.items():
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(repo / rel, text)
        self.ctx.register_project(repo)
        return repo

    def start(self, spec: _RunSpec) -> tuple[RunRecord, Run]:
        """
        Create a running run and return it with an SDK handle to its folder.

        Parameters
        ----------
        spec : _RunSpec
            The run to create.

        Returns
        -------
        record : RunRecord
            The created record (status ``running``).
        run : Run
            SDK handle used to log metrics, predictions, samples, and traces.
        """
        seed = "" if spec.seed is None else str(spec.seed)
        digest = hashlib.sha256(f"{spec.project}|{spec.key}".encode()).hexdigest()[:4]
        run_id = new_run_id(spec.task, now=spec.created_at).rsplit("-", 1)[0] + f"-{digest}"
        fingerprint = run_fingerprint(
            command_template=spec.command_template,
            stage=None,
            user_config=None,
            params=spec.params,
            vars={},
        )
        record = RunRecord(
            run_id=run_id,
            project=spec.project,
            task=spec.task,
            hypothesis=spec.hypothesis,
            command=[arg.replace("{seed}", seed) for arg in spec.command_template],
            command_template=spec.command_template,
            params=spec.params,
            cwd=str(spec.repo),
            environment_id=f"demo:{spec.host}",
            host=spec.host,
            git=GitInfo(commit=spec.commit, branch=spec.branch),
            datasets=spec.datasets,
            seed=spec.seed,
            config_hash=config_hash(fingerprint),
            status=RunStatus.RUNNING,
            created_at=spec.created_at,
            started_at=spec.created_at,
            tags=spec.tags,
            archived=spec.archived,
            created_by=spec.created_by,
        )
        self.ctx.create_run(record)
        return record, Run(self.ctx.run_dir(record), run_id, spec.project)

    def per_example(self, record: RunRecord, ref: str, rows: dict[str, dict[str, Any]]) -> None:
        """
        Write per-example scores in the metric worker's format.

        Parameters
        ----------
        record : RunRecord
            Run the scores belong to.
        ref : str
            ``metric@version``.
        rows : dict
            Per-example fields keyed by example id.
        """
        path = self.ctx.run_dir(record) / "predictions" / f"scores.{ref}.jsonl"
        atomic_write_text(path, "".join(json.dumps({"id": k, **v}) + "\n" for k, v in rows.items()))

    def index_progress(self, record: RunRecord) -> None:
        """
        Index a still-running run's logged metric history.

        Parameters
        ----------
        record : RunRecord
            The running run.
        """
        points = self.ctx.store.read_metric_points(record.project, record.run_id)
        self.ctx.index.replace_metric_points(record.run_id, points)

    def finish(
        self,
        record: RunRecord,
        *,
        status: RunStatus,
        ended_at: datetime,
        exit_code: int,
        scores: Sequence[tuple[str, str, str, float]] = (),
        stderr: str = "",
    ) -> RunRecord:
        """
        Finalise a run the way ``execute_run`` does, then add its scores.

        Parameters
        ----------
        record : RunRecord
            The running run.
        status : RunStatus
            Final status.
        ended_at : datetime
            End time; also the scores' creation time.
        exit_code : int
            Process exit code.
        scores : sequence of (metric, version, key, value)
            Final scores to append.
        stderr : str
            Text for ``logs/stderr.log``.

        Returns
        -------
        RunRecord
            The final record.
        """
        run_dir = self.ctx.run_dir(record)
        if stderr:
            atomic_write_text(run_dir / "logs" / "stderr.log", stderr)
        self.index_progress(record)
        logged = self.ctx.store.read_artifacts(record.project, record.run_id)
        usage = sum_usage(self.ctx.store.read_usage(record.project, record.run_id))

        def mutate(r: RunRecord) -> RunRecord:
            return r.model_copy(
                update={
                    "status": status,
                    "ended_at": ended_at,
                    "exit_code": exit_code,
                    "artifacts": [*r.artifacts, *logged],
                    "usage": usage,
                }
            )

        final = self.ctx.update_run(
            record.run_id, f"run.{status.value}", mutate, {"exit_code": exit_code}
        )
        for metric, version, key, value in scores:
            self.ctx.add_score(
                final,
                ScoreRecord(
                    metric=metric, version=version, key=key, value=value, created_at=ended_at
                ),
            )
        return final


def _jsonl(rows: Iterable[dict[str, Any]]) -> str:
    """
    Serialise rows as JSON lines.

    Parameters
    ----------
    rows : iterable of dict
        Rows to write.

    Returns
    -------
    str
    """
    return "".join(json.dumps(r) + "\n" for r in rows)


def _task_config(
    project: str,
    task: str,
    *,
    kind: TaskKind,
    dataset: dict[str, Any],
    metrics: dict[str, dict[str, Any]],
    primary: str,
    description: str,
    **extra: Any,
) -> dict[str, Any]:
    """
    Build a one-task ``hypothex.yaml`` body.

    Parameters
    ----------
    project, task : str
        Project and task names.
    kind : TaskKind
        Task kind.
    dataset : dict
        The dataset spec; it is named after the task.
    metrics : dict
        Metric specs by name.
    primary : str
        Primary metric reference.
    description : str
        Task description.
    **extra
        Additional task fields (``baseline``, ``version_param``).

    Returns
    -------
    dict
    """
    return {
        "project": project,
        "datasets": {task: dataset},
        "metrics": metrics,
        "tasks": {
            task: {
                "dataset": task,
                "split": "test",
                "metrics": list(metrics),
                "primary": primary,
                "description": description,
                "kind": kind,
                **extra,
            }
        },
    }


# --------------------------------------------------------------------- generic
# ui-v4/data.js: 180 test examples; rf seed 3 vs SVM: 9 fixed, 3 broken, 157 both
# pass, 11 both fail. Accuracies: logreg 149, knn 156, rf 158/160/160, SVM 166 of 180.
_GEN_FIXED = ("test-0", "test-110", "test-116", "test-12", "test-156", "test-177", "test-21")
_GEN_FIXED += ("test-63", "test-83")
_GEN_BROKEN = ("test-137", "test-167", "test-30")
_GEN_BOTH_FAIL = ("test-7", "test-14", "test-54", "test-62", "test-79", "test-81", "test-84")
_GEN_BOTH_FAIL += ("test-101", "test-122", "test-143", "test-171")
_GEN_RF = _GEN_BOTH_FAIL + _GEN_FIXED
_GEN_RF1 = _GEN_RF + ("test-40", "test-41")
_GEN_KNN = _GEN_BOTH_FAIL + _GEN_FIXED[:5]
_GEN_KNN += ("test-2", "test-5", "test-9", "test-17", "test-25", "test-33", "test-48", "test-66")
_GEN_LOGREG = _GEN_KNN + ("test-70", "test-88", "test-95", "test-104", "test-119", "test-133")
_GEN_LOGREG += ("test-150",)
_GEN_SVM_HYPOTHESIS = (
    "RBF-kernel SVM should beat RF/KNN/logreg because make_classification with "
    "n_clusters_per_class=1 makes smooth, roughly circular class clusters that a "
    "margin-based kernel model separates better than axis-aligned trees or a linear boundary"
)
_GEN_OLD, _GEN_NEW = (
    "2bbf5a3c81bfc657dea6d28bf0b3f057409602ad",
    "8f4cac43877b75953f18ff1daf7e6fc54a5d8f37",
)
_GEN_ARGPARSE = (
    "usage: train_eval.py [-h] --model {logreg,rf,knn} [--seed SEED]\n"
    "train_eval.py: error: argument --model: invalid choice: 'svm' "
    "(choose from 'logreg', 'rf', 'knn')\n"
)
_GEN_NOTE = (
    "RBF SVM (C=10, gamma=scale) beats prior best (rf): accuracy 0.9222 (n=3) vs rf "
    "0.8852 +/- 0.0064 (n=3). Fixed 9 test examples rf got wrong, broke 3, net +6/180. "
    "SVM is deterministic here, so identical seeds are expected."
)


def _seed_generic(sd: _Seeder) -> None:
    """
    Seed ``toy-classifier/toy-test`` (kind ``generic``) from ``ui-v4/data.js``.

    Parameters
    ----------
    sd : _Seeder
        Target home.
    """
    project, task = DEMO_TASKS["generic"]
    ids = [f"test-{i}" for i in range(180)]
    refs = {ex: i % 3 for i, ex in enumerate(ids)}
    dataset = {"version": "v1", "path": "data/test.jsonl", "splits": {"test": "data/test.jsonl"}}
    repo = sd.project(
        _task_config(
            project,
            task,
            kind="generic",
            dataset=dataset,
            metrics={"accuracy": {"version": "v1", "fn": "demo_metrics:accuracy"}},
            primary="accuracy",
            description="Classify the held-out test split.",
        ),
        {"data/test.jsonl": _jsonl({"id": ex, "reference": refs[ex]} for ex in ids)},
    )
    ref = DatasetRef(name=task, version="v1", split="test", path=str(repo / "data/test.jsonl"))

    def launch(
        model: str,
        seed: int,
        stamp: str,
        *,
        hypothesis: str,
        commit: str,
        by: str,
        key: str,
        tags: Sequence[str] = (),
        archived: bool = False,
    ) -> tuple[RunRecord, Run]:
        return sd.start(
            _RunSpec(
                project=project,
                task=task,
                repo=repo,
                hypothesis=hypothesis,
                command_template=["python", "train_eval.py", "--model", model, "--seed", "{seed}"],
                params={"model": model},
                seed=seed,
                created_at=sd.at(stamp),
                created_by=by,
                host="laptop",
                commit=commit,
                key=key,
                tags=list(tags),
                archived=archived,
                datasets=[ref],
            )
        )

    def scored(record: RunRecord, run: Run, wrong: Sequence[str]) -> RunRecord:
        miss = set(wrong)
        run.log_predictions(
            {
                "id": ex,
                "prediction": (refs[ex] + 1) % 3 if ex in miss else refs[ex],
                "reference": refs[ex],
            }
            for ex in ids
        )
        run.log({"train_accuracy": 1.0 - len(miss) / 360}, step=0)
        sd.per_example(record, "accuracy@v1", {ex: {"correct": ex not in miss} for ex in ids})
        return sd.finish(
            record,
            status=RunStatus.FINISHED,
            ended_at=record.created_at + timedelta(seconds=2),
            exit_code=0,
            scores=[("accuracy", "v1", "value", 1.0 - len(miss) / len(ids))],
        )

    baselines = (
        ("logreg", ("21:00:21", "21:00:23", "21:00:25"), (_GEN_LOGREG,) * 3),
        ("rf", ("21:00:28", "21:00:30", "21:00:32"), (_GEN_RF1, _GEN_RF, _GEN_RF)),
        ("knn", ("21:00:34", "21:00:36", "21:00:38"), (_GEN_KNN,) * 3),
    )
    for model, times, wrongs in baselines:
        for seed, (clock, wrong) in enumerate(zip(times, wrongs, strict=True), start=1):
            record, run = launch(
                model,
                seed,
                f"2026-09-26T{clock}Z",
                hypothesis=f"baseline {model}",
                commit=_GEN_OLD,
                by="human",
                key=f"{model}-{seed}",
            )
            scored(record, run, wrong)
    for seed, clock in enumerate(("21:01:58", "21:02:01", "21:02:02"), start=1):
        record, _ = launch(
            "svm",
            seed,
            f"2026-09-26T{clock}Z",
            hypothesis=_GEN_SVM_HYPOTHESIS,
            commit=_GEN_OLD,
            by="agent:acceptance",
            key=f"svm-failed-{seed}",
            archived=True,
        )
        sd.finish(
            record,
            status=RunStatus.FAILED,
            ended_at=record.created_at + timedelta(seconds=1),
            exit_code=2,
            stderr=_GEN_ARGPARSE,
        )
    for name, clock in (
        ("A", "21:02:41"),
        ("B", "21:02:43"),
        ("A2", "21:02:48"),
        ("B2", "21:02:50"),
    ):
        record, _ = launch(
            "rf",
            1,
            f"2026-09-26T{clock}Z",
            hypothesis=f"debug test {name}",
            commit=_GEN_NEW,
            by="agent:acceptance",
            key=f"debug-{name}",
            archived=True,
        )
        sd.finish(
            record,
            status=RunStatus.FINISHED,
            ended_at=record.created_at + timedelta(seconds=1),
            exit_code=0,
        )
    for seed, clock in enumerate(("21:03:02", "21:03:04", "21:03:06"), start=1):
        record, run = launch(
            "svm",
            seed,
            f"2026-09-26T{clock}Z",
            hypothesis=_GEN_SVM_HYPOTHESIS,
            commit=_GEN_NEW,
            by="agent:acceptance",
            key=f"svm-{seed}",
            tags=["best", "svm"] if seed == 3 else ["svm"],
        )
        final = scored(record, run, _GEN_BOTH_FAIL + _GEN_BROKEN)
        if seed == 3:
            sd.ctx.store.append_note(project, final.run_id, _GEN_NOTE, "agent:acceptance")


# --------------------------------------------------------------------- entry point
_SEEDERS: dict[str, Callable[[_Seeder], None]] = {
    "generic": _seed_generic,
}


def _seed_demo(home: Path, kinds: Iterable[str], anchor: datetime) -> dict[str, str]:
    """
    Seed the demo with every timestamp placed relative to ``anchor``.

    Parameters
    ----------
    home : Path
        Hypothex home to write into.
    kinds : iterable of str
        Task kinds to seed.
    anchor : datetime
        Where ``DEMO_EPOCH`` lands. The same anchor gives the same run ids and data.

    Returns
    -------
    dict of str to str
        ``{kind: "project/task"}`` in the order given.

    Raises
    ------
    ValueError
        For an unknown kind.
    StoreError
        If a demo project already exists in ``home`` (nothing is written).
    """
    wanted = list(dict.fromkeys(kinds))
    unknown = [k for k in wanted if k not in _SEEDERS]
    if unknown:
        raise ValueError(f"unknown demo kinds {unknown}; choose from {list(KINDS)}")
    ctx = Context.open(home)
    for kind in wanted:
        project = DEMO_TASKS[kind][0]
        if ctx.layout.project_dir(project).exists():
            raise StoreError(
                f"demo project {project!r} already exists in {ctx.layout.home}; "
                "seed the demo into an empty HYPOTHEX_HOME"
            )
    seeder = _Seeder(ctx, anchor)
    for kind in wanted:
        _SEEDERS[kind](seeder)
    return {kind: "/".join(DEMO_TASKS[kind]) for kind in wanted}


def seed_demo(home: Path, kinds: Iterable[TaskKind] = KINDS) -> dict[str, str]:
    """
    Write demo projects and runs for the given task kinds into ``home``.

    Timestamps keep the mockups' distance to ``DEMO_EPOCH`` but are moved so
    that ``DEMO_EPOCH`` falls on the current hour; the Overview's default 24-hour
    window therefore always shows recent runs. Within one hour the output is
    identical; the numbers never change.

    Parameters
    ----------
    home : Path
        Hypothex home (created if missing). Demo repos go to ``<home>/demo-repos/``.
    kinds : iterable of TaskKind
        Which kinds to seed; default all five.

    Returns
    -------
    dict of str to str
        ``{kind: "project/task"}``.

    Raises
    ------
    ValueError
        For an unknown kind.
    StoreError
        If a demo project already exists in ``home``.

    Examples
    --------
    >>> import pathlib, tempfile
    >>> seed_demo(pathlib.Path(tempfile.mkdtemp()), kinds=["generic"])
    {'generic': 'toy-classifier/toy-test'}
    """
    anchor = utcnow().replace(minute=0, second=0, microsecond=0)
    return _seed_demo(home, kinds, anchor)
```

- [ ] **Step 4: Run the tests and checks to verify they pass**

Run: `uv run pytest tests/test_demo.py -v`
Expected: `4 passed`.

Run: `uv run ruff check src/hypothex/demo.py tests/test_demo.py && uv run ruff format --check src/hypothex/demo.py tests/test_demo.py && uv run ty check src/hypothex/demo.py tests/test_demo.py`
Expected: `All checks passed!`, `2 files already formatted`, `All checks passed!`.

Run: `uv run python -m doctest src/hypothex/demo.py`
Expected: no output (the module and `seed_demo` examples pass).

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/demo.py tests/test_demo.py
git commit -m "feat: demo seed with the generic kind"
```

---

### Task 26: Demo training kind

**Files:**
- Modify: `src/hypothex/demo.py` (new `training` section; `_SEEDERS` entry)
- Test: `tests/test_demo.py` (one import; two tests appended)

**Interfaces:**
- Consumes: Task 25 (`_Seeder`, `_RunSpec`, `_task_config`, `_mulberry32`, `_gauss`, `_js_round`, `_clamp`, `DEMO_TASKS`, `_SEEDERS`); `Run.log_checkpoint(path, step, metrics, host)`; `Artifact.step`, `Artifact.metrics`; `hypothex.core.control.repair_runs(ctx) -> list[RunRecord]` (test).
- Produces: project `rxn-forward`, task `uspto-forward-top1` (kind `training`): 9 runs from `kinds/training/data.js` (base seed 2 diverges at step 9,000; +aug seed 3 is killed at step 14,000 with exit 137) plus one running run (`params["config"] == "lr2e-4"`, host `gpu-a04`, 2,350 steps logged). Metrics: `train/loss`, `val/top1`, `val/loss`, `lr`, `sys/gpu_util`, `sys/gpu_mem_gb`. Scores `top1@v1` keys `value` (best checkpoint, the primary) and `final`. Checkpoints every 2,000 steps with `val/top1` and `val/loss`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_demo.py`, replace

```python
from hypothex.core.context import Context
```

with

```python
from hypothex.core.context import Context
from hypothex.core.control import repair_runs
```

Then append to the end of `tests/test_demo.py` (two blank lines before it):

```python
def test_training_mirrors_mockup(dctx: Context) -> None:
    board = q.get_leaderboard(dctx, REFS["training"])
    assert board.kind == "training"
    # best-checkpoint test top-1 per run, from kinds/training/data.js (runs[i].best_top1)
    expected = {
        "aug": [0.909175, 0.906025],
        "lr1e-4": [0.893875, 0.8907, 0.889975],
        "base": [0.887675, 0.880425, 0.894],
    }
    runs = _runs(dctx, "rxn-forward")
    assert [dctx.find_record(row.run_ids[0]).params["config"] for row in board.rows] == [
        "aug",
        "lr1e-4",
        "base",
    ]
    for row, values in zip(board.rows, expected.values(), strict=True):
        assert row.n == len(values)
        assert row.primary is not None
        assert row.primary.mean == pytest.approx(sum(values) / len(values))
    base1 = _find(runs, 1, config="base")
    assert {(s.key, s.value) for s in dctx.store.read_scores("rxn-forward", base1.run_id)} == {
        ("value", 0.887675),
        ("final", 0.884575),
    }
    ckpts = [a for a in base1.artifacts if a.kind == "checkpoint"]
    assert [a.step for a in ckpts] == list(range(2000, 20001, 2000))
    best = max(ckpts, key=lambda a: a.metrics["val/top1"])
    assert (best.step, best.metrics["val/top1"]) == (12000, 0.8909)
    assert best.host == "gpu-a01" and best.path.endswith("/ckpt/step_012000.pt")
    spiky = _find(runs, 2, config="base")
    points = dctx.store.read_metric_points("rxn-forward", spiky.run_id)
    peak = max(p.value for p in points if p.name == "train/loss" and 9000 <= p.step < 9400)
    assert peak == 2.9667  # mockup event.peak of the diverged run
    killed = _find(runs, 3, config="aug")
    assert (killed.status, killed.exit_code) == (RunStatus.KILLED, 137)
    assert dctx.store.read_scores("rxn-forward", killed.run_id) == []
    names = {p.name for p in dctx.index.metric_points(base1.run_id)}
    assert names == {"train/loss", "val/top1", "val/loss", "lr", "sys/gpu_util", "sys/gpu_mem_gb"}
    live = _find(runs, config="lr2e-4")
    assert live.status == RunStatus.RUNNING and live.ended_at is None
    steps = [p.step for p in dctx.index.metric_points(live.run_id) if p.name == "train/loss"]
    assert max(steps) == 2350
    assert [a.step for a in dctx.store.read_artifacts("rxn-forward", live.run_id)] == [2000]


def test_running_demo_run_survives_repair(dctx: Context) -> None:
    assert repair_runs(dctx) == []
    live = dctx.index.list_runs(status=RunStatus.RUNNING, limit=None)
    assert len(live) == 1 and live[0].environment_id == "demo:gpu-a04"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_demo.py -k "training or repair" -v`
Expected: `2 failed`: `test_training_mirrors_mockup` with `hypothex.core.errors.StoreError: unknown project 'rxn-forward'`, and `test_running_demo_run_survives_repair` with `AssertionError` on `len(live) == 1`.

- [ ] **Step 3: Add the training section and register it**

In `src/hypothex/demo.py`, insert this block immediately above the line `# --------------------------------------------------------------------- entry point`, with two blank lines between the block's last line and that marker line:

```python
# --------------------------------------------------------------------- training
@dataclass(frozen=True)
class _TrainConfig:
    """One training config of the ``training`` mockup."""

    id: str
    name: str
    hypothesis: str
    lr: float
    sec_per_step: float
    created_by: str
    v: tuple[float, float, float, float]  # val top-1: inf, v0, tau, overfit
    vl: tuple[float, float, float, float]  # val loss: inf, l0, tau, overfit
    tl: tuple[float, float, float]  # train loss: inf, l0, tau
    util: float
    mem: float
    host: str
    commit: str


_TRAIN_CONFIGS = (
    _TrainConfig(
        "base", "base", "base recipe", 3e-4, 0.94, "shreyas",
        (0.8958, 0.62, 2500, 0.0060), (0.140, 0.46, 2300, 0.020), (0.074, 0.58, 2600),
        95, 61.4, "gpu-a01", "3d9e1a7",
    ),
    _TrainConfig(
        "lr1e-4", "lr 1e-4", "lr 1e-4 converges higher", 1e-4, 0.94, "agent:tuner",
        (0.8966, 0.62, 4300, 0.0), (0.143, 0.46, 4200, 0.0), (0.101, 0.58, 4600),
        95, 61.4, "gpu-a02", "b82f04c",
    ),
    _TrainConfig(
        "aug", "+aug", "+aug (SMILES randomisation) lifts top-1", 3e-4, 1.02, "agent:tuner",
        (0.9098, 0.60, 3100, 0.0), (0.121, 0.47, 3000, 0.0), (0.129, 0.61, 3200),
        86, 64.2, "gpu-a03", "b82f04c",
    ),
)  # fmt: skip
# Not in the mockup: one run still in progress, so the Overview has something running.
_TRAIN_RUNNING = _TrainConfig(
    "lr2e-4", "lr 2e-4", "+aug with lr 2e-4", 2e-4, 1.02, "agent:tuner",
    (0.9120, 0.60, 2800, 0.0), (0.118, 0.47, 2700, 0.0), (0.125, 0.61, 2900),
    86, 64.2, "gpu-a04", "b82f04c",
)  # fmt: skip
_STEPS, _VAL_EVERY, _CKPT_EVERY, _LOG_EVERY, _SYS_EVERY, _WARMUP = 20000, 500, 2000, 50, 100, 1000
_N_TEST, _SPIKE = 40000, 9000
_TRAIN_COMMAND = "python train.py --config configs/{config}.yaml --seed {{seed}}"


@dataclass
class _Curves:
    """Logged history of one training run."""

    train: list[tuple[int, float]]
    val: list[tuple[int, float, float]]
    lr: list[tuple[int, float]]
    sys: list[tuple[int, int, float]]
    ckpts: list[tuple[int, float, float]]
    best_step: int
    best_test: float
    final_test: float | None


def _lr_at(peak: float, step: int) -> float:
    """
    Learning rate with linear warmup, then cosine decay to 10% of peak.

    Parameters
    ----------
    peak : float
        Peak learning rate.
    step : int
        Optimiser step.

    Returns
    -------
    float
    """
    if step < _WARMUP:
        return peak * step / _WARMUP
    p = (step - _WARMUP) / (_STEPS - _WARMUP)
    return peak * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * p)))


def _training_curves(ci: int, c: _TrainConfig, seed: int, stop: int, diverged: bool) -> _Curves:
    """
    Port of the ``training`` mockup's per-run generator.

    Parameters
    ----------
    ci : int
        Config index (part of the RNG seed).
    c : _TrainConfig
        The config.
    seed : int
        Run seed (part of the RNG seed).
    stop : int
        Last step reached.
    diverged : bool
        Add the loss spike at step 9,000 and its lasting penalty.

    Returns
    -------
    _Curves
    """
    r = _mulberry32(1000 * (ci + 1) + seed * 41)
    off_v, off_vl, off_tl = _gauss(r) * 0.0014, _gauss(r) * 0.003, _gauss(r) * 0.003

    def pen(s: int) -> float:
        return math.exp(-(s - _SPIKE) / 520) if diverged and s >= _SPIKE else 0.0

    def pen_long(s: int) -> float:
        return 1 - math.exp(-(s - _SPIKE) / 900) if diverged and s >= _SPIKE else 0.0

    def r4(x: float) -> float:
        return _js_round(x * 1e4) / 1e4

    train = []
    for s in range(_LOG_EVERY, stop + 1, _LOG_EVERY):
        base = c.tl[0] + off_tl + (c.tl[1] - c.tl[0]) * math.exp(-s / c.tl[2])
        base += 2.75 * pen(s) + 0.052 * pen_long(s)
        train.append((s, r4(base * math.exp(_gauss(r) * 0.075))))
    val = []
    for s in range(_VAL_EVERY, stop + 1, _VAL_EVERY):
        x = s / _STEPS
        top1 = c.v[0] + off_v - (c.v[0] - c.v[1]) * math.exp(-s / c.v[2]) - c.v[3] * x * x * x
        loss = c.vl[0] + off_vl + (c.vl[1] - c.vl[0]) * math.exp(-s / c.vl[2]) + c.vl[3] * x * x * x
        top1 -= 0.45 * pen(s) + 0.029 * pen_long(s)
        loss += 0.95 * pen(s) + 0.058 * pen_long(s)
        val.append((s, r4(top1 + _gauss(r) * 0.0009), r4(loss * math.exp(_gauss(r) * 0.012))))
    lr = [(s, float(f"{_lr_at(c.lr, s):.3e}")) for s in range(0, stop + 1, _SYS_EVERY)]
    sys = []
    for s in range(_SYS_EVERY, stop + 1, _SYS_EVERY):
        eval_dip, ckpt_dip = s % _VAL_EVERY == 0, s % _CKPT_EVERY == 0
        u = c.util + _gauss(r) * 1.6
        if eval_dip:
            u = 38 + _gauss(r) * 4
        if ckpt_dip:
            u = 22 + _gauss(r) * 3
        m = c.mem * (s / 300) if s < 300 else c.mem + _gauss(r) * 0.15 + (1.8 if eval_dip else 0)
        sys.append((s, int(_clamp(_js_round(u), 0, 100)), _js_round(m * 10) / 10))
    gap = 0.0026 + _gauss(r) * 0.0006
    by_step = {s: (top1, loss) for s, top1, loss in val}
    ckpts = [(s, *by_step[s]) for s in range(_CKPT_EVERY, stop + 1, _CKPT_EVERY)]
    best = ckpts[0]
    for ck in ckpts[1:]:
        if ck[1] > best[1]:
            best = ck

    def test_of(v: float) -> float:
        return _js_round((v - gap) * _N_TEST) / _N_TEST

    final = test_of(val[-1][1]) if stop == _STEPS else None
    return _Curves(train, val, lr, sys, ckpts, best[0], test_of(best[1]), final)


def _seed_training(sd: _Seeder) -> None:
    """
    Seed ``rxn-forward/uspto-forward-top1`` (kind ``training``).

    Nine runs mirror ``kinds/training/data.js``: base seed 2 diverges at step
    9,000, +aug seed 3 is killed at step 14,000. One extra run is still running.

    Parameters
    ----------
    sd : _Seeder
        Target home.
    """
    project, task = DEMO_TASKS["training"]
    dataset = {
        "version": "v2",
        "host": "nfs-01",
        "path": "/data/uspto-mit/v2",
        "splits": {"test": "/data/uspto-mit/v2/test.jsonl"},
    }
    repo = sd.project(
        _task_config(
            project,
            task,
            kind="training",
            dataset=dataset,
            metrics={
                "top1": {
                    "version": "v1",
                    "fn": "demo_metrics:harness",
                    "changelog": {"v1": "exact-match top-1 on the 40,000-reaction test split"},
                }
            },
            primary="top1",
            description="Forward reaction prediction on USPTO-MIT; top-1 exact match.",
        ),
        {},
    )
    ref = DatasetRef(
        name=task, version="v2", split="test", host="nfs-01", path=dataset["splits"]["test"]
    )
    t0 = sd.at("2026-09-24T23:15:02Z")
    plan = [(ci, c, seed) for ci, c in enumerate(_TRAIN_CONFIGS) for seed in (1, 2, 3)]
    for k, (ci, c, seed) in enumerate([*plan, (3, _TRAIN_RUNNING, 1)]):
        running = c is _TRAIN_RUNNING
        killed = c.id == "aug" and seed == 3
        created = sd.at("2026-09-27T11:20:00Z") if running else t0 + timedelta(seconds=2 * k)
        stop = 2350 if running else 14000 if killed else _STEPS
        curves = _training_curves(ci, c, seed, stop, diverged=c.id == "base" and seed == 2)
        record, run = sd.start(
            _RunSpec(
                project=project,
                task=task,
                repo=repo,
                hypothesis=c.hypothesis,
                command_template=_TRAIN_COMMAND.format(config=c.id).split(),
                params={"config": c.id, "lr": f"{c.lr:g}"},
                seed=seed,
                created_at=created,
                created_by=c.created_by,
                host=c.host,
                commit=c.commit,
                key=f"{c.id}-{seed}",
                datasets=[ref],
            )
        )
        for s, value in curves.train:
            run.log({"train/loss": value}, step=s)
        for s, top1, loss in curves.val:
            run.log({"val/top1": top1, "val/loss": loss}, step=s)
        for s, value in curves.lr:
            run.log({"lr": value}, step=s)
        for s, util, mem in curves.sys:
            run.log({"sys/gpu_util": util, "sys/gpu_mem_gb": mem}, step=s)
        ckpt_dir = f"/scratch/shreyas/hx/{project}/runs/{record.run_id}/ckpt"
        for s, top1, loss in curves.ckpts:
            run.log_checkpoint(
                f"{ckpt_dir}/step_{s:06d}.pt",
                step=s,
                metrics={"val/top1": top1, "val/loss": loss},
                host=c.host,
            )
        if running:
            sd.index_progress(record)
            continue
        scores = [("top1", "v1", "value", curves.best_test)]
        if curves.final_test is not None:
            scores.append(("top1", "v1", "final", curves.final_test))
        sd.finish(
            record,
            status=RunStatus.KILLED if killed else RunStatus.FINISHED,
            ended_at=created + timedelta(seconds=stop * c.sec_per_step),
            exit_code=137 if killed else 0,
            scores=[] if killed else scores,
            stderr="preempted, SIGKILL\n" if killed else "",
        )
```

Then, in `_SEEDERS` at the bottom of `src/hypothex/demo.py`, replace

```python
    "generic": _seed_generic,
}
```

with

```python
    "generic": _seed_generic,
    "training": _seed_training,
}
```

- [ ] **Step 4: Run the tests and checks to verify they pass**

Run: `uv run pytest tests/test_demo.py -v`
Expected: `6 passed`.

Run: `uv run ruff check src/hypothex/demo.py tests/test_demo.py && uv run ruff format --check src/hypothex/demo.py tests/test_demo.py && uv run ty check src/hypothex/demo.py tests/test_demo.py`
Expected: `All checks passed!`, `2 files already formatted`, `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/demo.py tests/test_demo.py
git commit -m "feat: demo training runs mirroring the training mockup"
```

---

### Task 27: Demo agent_eval kind

**Files:**
- Modify: `src/hypothex/demo.py` (one import; new `agent_eval` section; `_SEEDERS` entry)
- Test: `tests/test_demo.py` (two imports; one test appended)

**Interfaces:**
- Consumes: Task 25 helpers; `Run.log_predictions`, `Run.log_usage(tokens_in, tokens_out, usd, seconds, example_id)`, `Run.log_trace(example_id, steps)`; `hypothex.core.views.save_view(repo, task, name, text) -> Path` and `get_view(repo, config, task, name) -> ViewSpec` (contract 1.4; `get_view` in the test).
- Produces: project `retro-agents`, task `retro-bench-200` (kind `agent_eval`): 4 configs x 3 seeds x 200 targets from `kinds/agent_eval/data.js`. Predictions carry `meta.category` (failure type or null), `meta.difficulty`, `meta.class`. Per-example scores `solved@v2` with `solved`, `turns`, `tool_calls`, `usd`, `seconds`. One `usage.jsonl` row per attempt, so `RunRecord.usage.calls == 200`. The trajectory of the selected failed attempt (Sonnet 5 + scorer, seed 2, target `T-014`, 13 steps, the last one with `error`). A custom view `cost-notes` in `<repo>/.hypothex/views/retro-bench-200/cost-notes.yaml`.

- [ ] **Step 1: Write the failing test**

In `tests/test_demo.py`, replace

```python
from hypothex.core.errors import StoreError
```

with

```python
from hypothex.core.errors import StoreError
from hypothex.core.fsutil import read_jsonl
```

and replace

```python
from hypothex.core.records import RunRecord, RunStatus
```

with

```python
from hypothex.core.records import RunRecord, RunStatus
from hypothex.core.views import get_view
```

Then append to the end of `tests/test_demo.py` (two blank lines before it):

```python
def test_agent_eval_mirrors_mockup(dctx: Context) -> None:
    board = q.get_leaderboard(dctx, REFS["agent_eval"])
    assert board.kind == "agent_eval"
    runs = _runs(dctx, "retro-agents")
    # solved targets and summed $ per config and seed, from kinds/agent_eval/data.js
    solved = {"mini": [84, 80, 80], "sonnet": [108, 120, 111], "scorer": [148, 141, 146]}
    solved["opus"] = [152, 147, 146]
    usd = {"mini": [3.0867, 3.0367, 3.6488], "sonnet": [44.257, 49.6265, 47.7672]}
    usd |= {"scorer": [33.5957, 38.1796, 33.5293], "opus": [108.2754, 106.1396, 117.8305]}
    loops = {"mini": [14, 16, 15], "sonnet": [30, 22, 34], "scorer": [8, 8, 5], "opus": [2, 7, 8]}
    for config, counts in solved.items():
        for seed, count in enumerate(counts, start=1):
            run = _find(runs, seed, config=config)
            scores = dctx.store.read_scores("retro-agents", run.run_id)
            assert [(s.metric, s.version, s.value) for s in scores] == [
                ("solved", "v2", count / 200)
            ]
            assert run.usage is not None
            assert run.usage.usd == pytest.approx(usd[config][seed - 1], abs=1e-6)
            assert run.usage.calls == 200
            rows = read_jsonl(dctx.run_dir(run) / "predictions" / "predictions.jsonl")
            categories = [r["meta"]["category"] for r in rows]
            assert categories.count("loop") == loops[config][seed - 1]
            assert categories.count(None) == count
    selected = _find(runs, 2, config="scorer")
    steps = read_jsonl(dctx.run_dir(selected) / "traces" / "T-014.jsonl")
    assert [s["turn"] for s in steps] == list(range(1, 14))
    assert steps[-1]["error"] == "loop: 3rd identical call"
    assert sum(s["tokens_in"] for s in steps) == 152670
    entry, task = q.resolve_task(dctx, REFS["agent_eval"])
    assert get_view(Path(entry.repo), entry.config, task, "cost-notes").title == "cost notes"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_demo.py -k agent_eval -v`
Expected: `1 failed` with `hypothex.core.errors.StoreError: unknown project 'retro-agents'`.

- [ ] **Step 3: Add the import**

In `src/hypothex/demo.py`, replace

```python
from hypothex.core.store import sum_usage
```

with

```python
from hypothex.core.store import sum_usage
from hypothex.core.views import save_view
```

- [ ] **Step 4: Add the agent_eval section and register it**

In `src/hypothex/demo.py`, insert this block immediately above the line `# --------------------------------------------------------------------- entry point`, with two blank lines between the block's last line and that marker line:

```python
# --------------------------------------------------------------------- agent_eval
@dataclass(frozen=True)
class _AgentConfig:
    """One agent config of the ``agent_eval`` mockup."""

    id: str
    short: str
    model: str
    tools: str
    a: float  # skill
    pin: float  # $ per 1M input tokens
    pout: float  # $ per 1M output tokens
    c0: int  # base context per turn
    g: int  # context growth per turn
    out: int  # output tokens per turn
    lat: float  # model seconds per turn
    tc: float  # tool calls per turn
    fw: tuple[float, float, float, float, float]  # failure weights, in _FAILS order
    turn_k: float
    commit: str
    created_by: str


_AGENT_CONFIGS = (
    _AgentConfig("mini", "gpt-5-mini", "gpt-5-mini", "base", -0.75, 0.10, 1.6, 3100, 1150,
                 360, 1.9, 1.05, (0.10, 0.14, 0.34, 0.12, 0.30), 1.0, "4be19c2", "agent:sweep-7"),
    _AgentConfig("sonnet", "Sonnet 5", "claude-sonnet-5", "base", 0.25, 1.2, 15, 3300, 1000,
                 420, 3.4, 1.25, (0.26, 0.30, 0.10, 0.12, 0.22), 1.0, "4be19c2", "agent:sweep-7"),
    _AgentConfig("scorer", "Sonnet 5 + scorer", "claude-sonnet-5", "base + score_routes", 1.30,
                 1.2, 15, 3600, 820, 380, 3.3, 1.35, (0.30, 0.14, 0.08, 0.24, 0.24), 0.8,
                 "91ad07e", "mira"),
    _AgentConfig("opus", "Opus 5.5", "claude-opus-5-5", "base", 1.30, 2.0, 25, 3300, 1000, 880,
                 6.6, 1.3, (0.52, 0.12, 0.04, 0.10, 0.22), 1.0, "4be19c2", "agent:sweep-7"),
)  # fmt: skip
_FAILS = ("timeout", "loop", "invalid SMILES", "tool error", "gave up")
_AGENT_COMMAND = ["python", "-m", "retro_agents.bench", "--model"]
_CLASSES = (
    "kinase inhibitor", "macrolide", "peptidomimetic", "biaryl amide", "spiro-oxindole",
    "steroid", "nucleoside", "β-lactam", "sulfonamide", "indole alkaloid", "PROTAC linker",
    "fluoroquinolone",
)  # fmt: skip
# The trajectory of the selected attempt: tool, args, result, tokens in, tokens out, ms.
_AGENT_TRACE = (
    ("retro_expand", "target, top_k=8", "8 precursors, amide p .62", 4410, 512, 4820),
    ("check_stock", "ClC(=O)c1ccc(CN2CCN(C)CC2)cc1", "in stock", 5480, 188, 2710),
    ("check_stock", "Cc1ccc(N)cc1Nc1nccc(-c2cccnc2)n1", "not in stock", 6320, 204, 2640),
    ("retro_expand", "Cc1ccc(N)cc1Nc1nccc(…)n1", "6 precursors, nitro red. p .71", 7690, 466,
     4960),
    ("retro_expand", "Cc1ccc([N+](=O)[O-])cc1Nc1nccc(…)n1", "5 precursors, SNAr p .48", 9310,
     431, 5130),
    ("score_routes", "3 routes, depth 3", "best .71, route B", 10840, 352, 8870),
    ("check_stock", "Cc1ccc([N+](=O)[O-])cc1N", "in stock", 11720, 176, 2580),
    ("check_stock", "CN(C)/C=C/C(=O)c1cccnc1", "not in stock", 12460, 198, 2690),
    ("retro_expand", "CN(C)/C=C/C(=O)c1cccnc1", "4 precursors, DMF-DMA p .80", 13950, 402,
     4710),
    ("score_routes", "2 routes, depth 4", "tool error: timeout 8 s", 15210, 318, 11240),
    ("retro_expand", "Cc1ccc([N+](=O)[O-])cc1Nc1nccc(…)n1", "5 precursors, SNAr p .48", 16930,
     455, 5080),
    ("score_routes", "3 routes, depth 3", "best .71, route B", 18380, 341, 8790),
    ("retro_expand", "Cc1ccc([N+](=O)[O-])cc1Nc1nccc(…)n1", "loop: 3rd identical call", 19970,
     473, 4210),
)  # fmt: skip


@dataclass
class _Target:
    """One benchmark target."""

    id: str
    b: float  # difficulty
    depth: int
    cls: str


@dataclass
class _Attempt:
    """One attempt of one config and seed on one target."""

    solved: bool
    fail: str | None
    turns: int
    tool_calls: int
    tok_in: int
    tok_out: int
    cost: float
    wall: float


def _agent_eval_data() -> tuple[list[_Target], dict[tuple[str, int], list[_Attempt]], int]:
    """
    Port of the ``agent_eval`` mockup generator.

    Returns
    -------
    targets : list of _Target
        200 targets.
    attempts : dict
        Attempts keyed by ``(config id, seed)``, one per target.
    selected : int
        Index of the attempt whose trajectory is logged (Sonnet 5 + scorer, seed 2).
    """
    rnd = _mulberry32(20260927)

    def gauss() -> float:
        return _gauss(rnd)

    def pick(weights: list[float]) -> int:
        total = 0.0
        for w in weights:  # plain left-to-right sum, like Array.reduce
            total += w
        left = rnd() * total
        for i, w in enumerate(weights):
            left -= w
            if left <= 0:
                return i
        return len(weights) - 1

    targets = []
    for i in range(200):
        b = gauss() * 1.55
        depth = int(_clamp(_js_round(4.2 + b * 1.25 + gauss() * 0.9), 2, 11))
        cls = _CLASSES[math.floor(rnd() * len(_CLASSES))]
        targets.append(_Target(f"T-{i + 1:03d}", b, depth, cls))
    attempts: dict[tuple[str, int], list[_Attempt]] = {}
    for c in _AGENT_CONFIGS:
        for seed in (1, 2, 3):
            e = gauss() * 0.04
            rows = []
            for t in targets:
                p = 1 / (1 + math.exp(-(c.a + e - t.b)))
                solved = rnd() < p
                fail = None
                if solved:
                    turns = _js_round(
                        _clamp((3.5 + t.depth * 1.35) * c.turn_k + gauss() * 2.2, 3, 28)
                    )
                else:
                    w = list(c.fw)
                    if t.b > 1:
                        w[0] *= 1.6
                    fail = _FAILS[pick(w)]
                    if fail == "timeout":
                        turns = 30
                    elif fail == "loop":
                        turns = _js_round(_clamp(11 + gauss() * 3.5, 7, 26))
                    elif fail == "invalid SMILES":
                        turns = _js_round(_clamp(7 + gauss() * 2.5, 3, 16))
                    elif fail == "tool error":
                        turns = _js_round(_clamp(8 + gauss() * 3, 2, 20))
                    else:
                        turns = _js_round(_clamp(9 + gauss() * 3, 4, 20))
                noise = math.exp(gauss() * 0.12)
                tok_in = _js_round((turns * c.c0 + c.g * turns * (turns + 1) / 2) * noise)
                tok_out = _js_round(turns * c.out * math.exp(gauss() * 0.18))
                tool_calls = max(1, _js_round(turns * c.tc + gauss()))
                score_calls = _js_round(turns / 3) if c.id == "scorer" else 0
                wall = turns * c.lat * math.exp(gauss() * 0.15) + tool_calls * 0.55
                wall += score_calls * 6.8
                if fail == "timeout":
                    wall = min(300, max(wall, 150 + rnd() * 150))
                wall = min(wall, 300)
                cost = tok_in / 1e6 * c.pin + tok_out / 1e6 * c.pout
                cost, wall = _fixed(cost, 4), _fixed(wall, 1)
                rows.append(_Attempt(solved, fail, turns, tool_calls, tok_in, tok_out, cost, wall))
            attempts[(c.id, seed)] = rows
    selected = next(
        (
            i
            for i, t in enumerate(targets)
            if not attempts[("scorer", 2)][i].solved
            and attempts[("opus", 1)][i].solved
            and attempts[("opus", 2)][i].solved
            and 5 <= t.depth <= 7
        ),
        136,
    )
    scorer = next(c for c in _AGENT_CONFIGS if c.id == "scorer")
    tok_in = sum(step[3] for step in _AGENT_TRACE)
    tok_out = sum(step[4] for step in _AGENT_TRACE)
    attempts[("scorer", 2)][selected] = _Attempt(
        solved=False,
        fail="loop",
        turns=len(_AGENT_TRACE),
        tool_calls=len(_AGENT_TRACE),
        tok_in=tok_in,
        tok_out=tok_out,
        cost=_fixed((tok_in / 1e6) * scorer.pin + (tok_out / 1e6) * scorer.pout, 4),
        wall=_fixed(sum(step[5] for step in _AGENT_TRACE) / 1000, 1),
    )
    return targets, attempts, selected


_AGENT_EVAL_VIEW = """title: cost notes
from: agent_eval
panels:
  - type: markdown
    title: Note
    text: |
      Sonnet 5 + scorer: 0.725 solved@v2 vs 0.742 for Opus 5.5, at a third of the cost.
    layout: {span: 12}
"""


def _seed_agent_eval(sd: _Seeder) -> None:
    """
    Seed ``retro-agents/retro-bench-200`` (kind ``agent_eval``).

    Four configs x three seeds x 200 targets, from ``kinds/agent_eval/data.js``:
    per-example outcomes with failure categories, per-attempt usage, the
    trajectory of one failed attempt, and a custom view.

    Parameters
    ----------
    sd : _Seeder
        Target home.
    """
    project, task = DEMO_TASKS["agent_eval"]
    targets, attempts, selected = _agent_eval_data()
    dataset = {
        "version": "v2",
        "path": "data/targets.jsonl",
        "splits": {"test": "data/targets.jsonl"},
    }
    repo = sd.project(
        _task_config(
            project,
            task,
            kind="agent_eval",
            dataset=dataset,
            metrics={
                "solved": {
                    "version": "v2",
                    "fn": "demo_metrics:solved",
                    "changelog": {"v2": "route must end in purchasable building blocks"},
                }
            },
            primary="solved",
            description="Valid route to purchasable stock within 30 turns and 300 s.",
        ),
        {
            "data/targets.jsonl": _jsonl(
                {"id": t.id, "reference": None, "depth": t.depth, "class": t.cls} for t in targets
            )
        },
    )
    save_view(repo, task, "cost-notes", _AGENT_EVAL_VIEW)
    ref = DatasetRef(name=task, version="v2", split="test", path=str(repo / dataset["path"]))
    for index, c in enumerate(_AGENT_CONFIGS):
        for seed in (1, 2, 3):
            clock = ("14:02", "14:19", "14:33")[seed - 1]
            created = sd.at(f"2026-09-26T{clock}:{index * 7 + 11:02d}Z")
            command = [*_AGENT_COMMAND, c.model, "--tools", c.tools, "--seed", "{seed}"]
            record, run = sd.start(
                _RunSpec(
                    project=project,
                    task=task,
                    repo=repo,
                    hypothesis=f"{c.short}, tools: {c.tools}",
                    command_template=command,
                    params={"config": c.id, "model": c.model, "tools": c.tools},
                    seed=seed,
                    created_at=created,
                    created_by=c.created_by,
                    host="evalbox-2",
                    commit=c.commit,
                    key=f"{c.id}-{seed}",
                    datasets=[ref],
                )
            )
            rows = attempts[(c.id, seed)]
            run.log_predictions(
                {
                    "id": t.id,
                    "prediction": "route" if a.solved else None,
                    "meta": {"category": a.fail, "difficulty": t.depth, "class": t.cls},
                }
                for t, a in zip(targets, rows, strict=True)
            )
            for t, a in zip(targets, rows, strict=True):
                run.log_usage(
                    tokens_in=a.tok_in,
                    tokens_out=a.tok_out,
                    usd=a.cost,
                    seconds=a.wall,
                    example_id=t.id,
                )
            if c.id == "scorer" and seed == 2:
                run.log_trace(
                    targets[selected].id,
                    (
                        {
                            "turn": turn,
                            "tool": tool,
                            "args": args,
                            "result": result,
                            "tokens_in": tok_in,
                            "tokens_out": tok_out,
                            "seconds": ms / 1000,
                            "error": result if turn == len(_AGENT_TRACE) else None,
                        }
                        for turn, (tool, args, result, tok_in, tok_out, ms) in enumerate(
                            _AGENT_TRACE, start=1
                        )
                    ),
                )
            sd.per_example(
                record,
                "solved@v2",
                {
                    t.id: {
                        "solved": a.solved,
                        "turns": a.turns,
                        "tool_calls": a.tool_calls,
                        "usd": a.cost,
                        "seconds": a.wall,
                    }
                    for t, a in zip(targets, rows, strict=True)
                },
            )
            wall = math.fsum(a.wall for a in rows)
            sd.finish(
                record,
                status=RunStatus.FINISHED,
                ended_at=created + timedelta(seconds=wall / 8),  # eight attempts in parallel
                exit_code=0,
                scores=[("solved", "v2", "value", sum(a.solved for a in rows) / len(rows))],
            )
```

Then, in `_SEEDERS` at the bottom of `src/hypothex/demo.py`, replace

```python
    "training": _seed_training,
}
```

with

```python
    "training": _seed_training,
    "agent_eval": _seed_agent_eval,
}
```

- [ ] **Step 5: Run the tests and checks to verify they pass**

Run: `uv run pytest tests/test_demo.py -v`
Expected: `7 passed`.

Run: `uv run ruff check src/hypothex/demo.py tests/test_demo.py && uv run ruff format --check src/hypothex/demo.py tests/test_demo.py && uv run ty check src/hypothex/demo.py tests/test_demo.py`
Expected: `All checks passed!`, `2 files already formatted`, `All checks passed!`.

- [ ] **Step 6: Commit**

```bash
git add src/hypothex/demo.py tests/test_demo.py
git commit -m "feat: demo agent_eval runs with traces, usage, and a custom view"
```

---

### Task 28: Demo agent_iteration kind

**Files:**
- Modify: `src/hypothex/demo.py` (new `agent_iteration` section; `_SEEDERS` entry)
- Test: `tests/test_demo.py` (one test appended)

**Interfaces:**
- Consumes: Task 25 helpers; `TaskSpec.version_param`; `Run.log_predictions`, `Run.log_usage`, `Run.log_trace`.
- Produces: project `retro-agent`, task `retro-bench-200` (kind `agent_iteration`, `version_param: version`): 9 versions x 3 seeds with the exact per-target outcomes of `kinds/agent_iteration/data.js` (stored as 50 hex digits per run). Run params carry `version`, `model`, `prompt`, `tools`, `temperature`, `depth`, `budget`, `retries`; the hypothesis is the version's change label. One run-level usage row per run (`usd = cost_usd`, `tokens_in = tokens_m x 1e6`, `seconds` = wall time). The v8 seed 2 run also has `meta.category` and `meta.steps` per target and the 11-step trajectory of `T-035`.

- [ ] **Step 1: Write the failing test**

Append to the end of `tests/test_demo.py` (two blank lines before it):

```python
def test_agent_iteration_mirrors_mockup(dctx: Context) -> None:
    board = q.get_leaderboard(dctx, REFS["agent_iteration"])
    assert board.kind == "agent_iteration"
    # solved targets per version (seeds 1-3), counted from the bitstrings in data.js
    counts = {
        "v1": [80, 80, 80], "v2": [85, 85, 85], "v3": [107, 107, 102], "v4": [111, 105, 115],
        "v5": [116, 126, 122], "v6": [110, 115, 110], "v7": [121, 120, 127],
        "v8": [129, 135, 134], "v9": [128, 136, 129],
    }  # fmt: skip
    runs = _runs(dctx, "retro-agent")
    means = {}
    for row in board.rows:
        version = dctx.find_record(row.run_ids[0]).params["version"]
        assert row.primary is not None
        means[version] = row.primary.mean
    assert means == pytest.approx({v: sum(c) / 600 for v, c in counts.items()})
    assert board.rows[0].label == "v8"  # agent_iteration labels are the version_param value
    detail = _find(runs, 2, version="v8")
    assert detail.usage is not None
    assert (detail.usage.usd, detail.usage.tokens_in) == (177.12, 61_100_000)
    assert detail.usage.seconds == 3 * 3600 - 2 * 60  # 15:06 to 18:04
    rows = {
        r["id"]: r for r in read_jsonl(dctx.run_dir(detail) / "predictions" / "predictions.jsonl")
    }
    assert rows["T-003"]["meta"] == {"category": "timeout", "steps": 29}
    assert rows["T-001"]["meta"] == {"category": None, "steps": 15}
    trace = read_jsonl(dctx.run_dir(detail) / "traces" / "T-035.jsonl")
    assert len(trace) == 11 and trace[-1]["tool"] == "submit" and trace[-1]["result"] == "solved"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_demo.py -k agent_iteration -v`
Expected: `1 failed` with `hypothex.core.errors.StoreError: unknown project 'retro-agent'`.

- [ ] **Step 3: Add the agent_iteration section and register it**

In `src/hypothex/demo.py`, insert this block immediately above the line `# --------------------------------------------------------------------- entry point`, with two blank lines between the block's last line and that marker line:

```python
# --------------------------------------------------------------------- agent_iteration
@dataclass(frozen=True)
class _Version:
    """One agent version of the ``agent_iteration`` mockup."""

    v: str
    at: str
    by: str
    change: str
    commit: str
    prompt: str
    model: str
    temperature: float
    depth: int
    budget: int
    retries: int
    tools: str  # comma-separated


@dataclass(frozen=True)
class _IterRun:
    """One run of the ``agent_iteration`` mockup; ``solved`` is 200 bits as hex."""

    v: str
    seed: int
    started_at: str
    ended_at: str
    cost_usd: float
    tokens_m: float
    tool_calls: int
    solved: str


_ITER_VERSIONS = (
    _Version("v1", "2026-09-13T10:12:00Z", "human:shreyas", "baseline",
             "a031a64b9cbd2a8e81ebf150c9ab0804a710a6a6", "react-1", "gpt-4.1-mini", 0, 4, 40, 1,
             "template_search,route_score,smiles_validate"),
    _Version("v2", "2026-09-14T16:40:00Z", "human:shreyas", "retries 3",
             "6fa2cfdf2f93d4bd34398d373139b5abcfc9acc8", "react-1", "gpt-4.1-mini", 0, 4, 40, 3,
             "template_search,route_score,smiles_validate"),
    _Version("v3", "2026-09-16T11:05:00Z", "agent:iterate", "+stock_check",
             "13c824cb0b7b7d816c843bd761ddc1a4f19a7612", "react-1", "gpt-4.1-mini", 0.6, 4, 40, 3,
             "template_search,route_score,smiles_validate,stock_check"),
    _Version("v4", "2026-09-17T19:22:00Z", "agent:iterate", "depth 6",
             "50cc29f312390a273e41162f8591d2d98004702a", "react-1", "gpt-4.1-mini", 0.6, 6, 40, 3,
             "template_search,route_score,smiles_validate,stock_check"),
    _Version("v5", "2026-09-19T09:48:00Z", "human:shreyas", "gpt-4.1",
             "356483f8954521d87436e67efa04c7e31fc6cc58", "react-1", "gpt-4.1", 0.6, 6, 40, 3,
             "template_search,route_score,smiles_validate,stock_check"),
    _Version("v6", "2026-09-21T14:15:00Z", "agent:iterate", "prompt rewrite",
             "e058f3e5a888d5352ee90a3b16e8c5980450b9b9", "concise-2", "gpt-4.1", 0.6, 6, 40, 3,
             "template_search,route_score,smiles_validate,stock_check"),
    _Version("v7", "2026-09-22T10:31:00Z", "human:shreyas", "revert prompt",
             "8c02d161c42ce427c0eeb79c9a3956fae5a037f3", "react-1", "gpt-4.1", 0.6, 6, 40, 3,
             "template_search,route_score,smiles_validate,stock_check"),
    _Version("v8", "2026-09-24T15:02:00Z", "agent:iterate", "+conditions",
             "1d191070a618a3666e85659d92caba648413e751", "react-1", "gpt-4.1", 0.6, 6, 40, 3,
             "template_search,route_score,smiles_validate,stock_check,condition_predict"),
    _Version("v9", "2026-09-26T13:37:00Z", "agent:iterate", "budget 25",
             "bd4d8132a7bf094731e43e59dc7d747f440a8af3", "react-1", "gpt-4.1", 0.6, 6, 25, 3,
             "template_search,route_score,smiles_validate,stock_check,condition_predict"),
)  # fmt: skip
_ITER_RUNS = (
    _IterRun("v1", 1, "2026-09-13T10:12:00Z", "2026-09-13T12:37:00Z",
             74.28, 119.8, 2780, "50c977ef1695348448c90d5a48c0c50104245a18f4b9b0404e"),
    _IterRun("v1", 2, "2026-09-13T10:17:00Z", "2026-09-13T12:48:00Z",
             79.57, 128.3, 2820, "50c977ef1695348448c90d5a48c0c50104245a18f4b9b0404e"),
    _IterRun("v1", 3, "2026-09-13T10:22:00Z", "2026-09-13T13:11:00Z",
             75.7, 122.1, 2660, "50c977ef1695348448c90d5a48c0c50104245a18f4b9b0404e"),
    _IterRun("v2", 1, "2026-09-14T16:40:00Z", "2026-09-14T19:09:00Z",
             86.68, 139.8, 2640, "5ae177ee1794a48448690d5a40c0c409c425183854fdb4644e"),
    _IterRun("v2", 2, "2026-09-14T16:45:00Z", "2026-09-14T19:36:00Z",
             84.58, 136.4, 2720, "5ae177ee1794a48448690d5a40c0c409c425183854fdb4644e"),
    _IterRun("v2", 3, "2026-09-14T16:52:00Z", "2026-09-14T19:49:00Z",
             82.7, 133.4, 2800, "5ae177ee1794a48448690d5a40c0c409c425183854fdb4644e"),
    _IterRun("v3", 1, "2026-09-16T11:05:00Z", "2026-09-16T13:37:00Z",
             99.34, 160.2, 2820, "dcad77efc695f4c588d989da5cc0d509c6245a3f34ffb45c4e"),
    _IterRun("v3", 2, "2026-09-16T11:11:00Z", "2026-09-16T14:13:00Z",
             94.11, 151.8, 2800, "5cc9f7efc5f5f4c549c9185accc3950bd4241b7d74b7b0761e"),
    _IterRun("v3", 3, "2026-09-16T11:13:00Z", "2026-09-16T14:03:00Z",
             96.53, 155.7, 2780, "56c177efc4f5e4c548f9995a58c09209c6245a3c74bfb556ce"),
    _IterRun("v4", 1, "2026-09-17T19:22:00Z", "2026-09-17T22:09:00Z",
             126.26, 203.6, 3360, "dce977fdd4fcf1e549d9195a4ccadd0b94251a3d74bfb454ce"),
    _IterRun("v4", 2, "2026-09-17T19:26:00Z", "2026-09-17T21:33:00Z",
             119.08, 192.1, 3380, "588f77edc6f4e4e549c99a5a48c0d10b47241b7fb4bbb556ce"),
    _IterRun("v4", 3, "2026-09-17T19:34:00Z", "2026-09-17T22:38:00Z",
             130.13, 209.9, 3480, "dcfb77efd6f7f1e549e99b5a5cc8c50997249bbd34e3b4568e"),
    _IterRun("v5", 1, "2026-09-19T09:48:00Z", "2026-09-19T13:21:00Z",
             160.31, 55.3, 3380, "dcc377ef74f575e549f11bded8d0c50bd4241b3d34ffb57ece"),
    _IterRun("v5", 2, "2026-09-19T09:54:00Z", "2026-09-19T13:19:00Z",
             186.12, 64.2, 3320, "dceff7efc2f5fcc5c9e98d5e5cd6d58bc7249bfff4bf355676"),
    _IterRun("v5", 3, "2026-09-19T10:00:00Z", "2026-09-19T13:11:00Z",
             177.98, 61.4, 3420, "5cabffef74f5fcc549fd185a58d3d40bc7259bbe76bfb574fe"),
    _IterRun("v6", 1, "2026-09-21T14:15:00Z", "2026-09-21T17:35:00Z",
             178.2, 61.4, 3380, "dced77ef44f4e5c549f98dca48805509d6249a3f74fbb574fe"),
    _IterRun("v6", 2, "2026-09-21T14:21:00Z", "2026-09-21T18:02:00Z",
             180.95, 62.4, 3440, "dee9ffefc4d5f5c549d9195a4ccad50b67259a3ef4adb474ee"),
    _IterRun("v6", 3, "2026-09-21T14:25:00Z", "2026-09-21T17:53:00Z",
             181.19, 62.5, 3440, "dce9ffefe0d5a7c558fd9f5a4cc0841b46641a3ef4bdb07c4e"),
    _IterRun("v7", 1, "2026-09-22T10:31:00Z", "2026-09-22T13:11:00Z",
             168.62, 58.1, 3480, "5de7ffefc6f5f5e549c98b5e4cd8d48be4245b3eb4bfb57ece"),
    _IterRun("v7", 2, "2026-09-22T10:35:00Z", "2026-09-22T14:08:00Z",
             178.66, 61.6, 3420, "dcaf77efc6f5f5c5c9f91f5e58c8d58bd4259b3f94ef3176ce"),
    _IterRun("v7", 3, "2026-09-22T10:39:00Z", "2026-09-22T13:33:00Z",
             185.94, 64.1, 3300, "dceb7ffff6f5e7c549e91b5e5cd0d61bc620da7cf4ffb17ffe"),
    _IterRun("v8", 1, "2026-09-24T15:02:00Z", "2026-09-24T18:28:00Z",
             167.77, 57.9, 3260, "dcc377eff6bff5e549f99b5e58dbd58bf425db7e74bfb576ce"),
    _IterRun("v8", 2, "2026-09-24T15:06:00Z", "2026-09-24T18:04:00Z",
             177.12, 61.1, 3300, "dccd7ffff6f5fce549f91f5e58cbd58bd7259afffcffb576ee"),
    _IterRun("v8", 3, "2026-09-24T15:10:00Z", "2026-09-24T18:29:00Z",
             188.06, 64.8, 3280, "5efd7feff6f5e7e748e19f5e4c96d72bf5249b7ef4fffd76ee"),
    _IterRun("v9", 1, "2026-09-26T13:37:00Z", "2026-09-26T16:16:00Z",
             137.35, 47.4, 2260, "dcef7fefb7f5adc5c8f99fda58c5d58bf4259aff14bfb576ee"),
    _IterRun("v9", 2, "2026-09-26T13:41:00Z", "2026-09-26T16:51:00Z",
             148.21, 51.1, 2280, "d8efffefe6bde5e549f99f5a5cdadde9d424dbfff4bfbd76fe"),
    _IterRun("v9", 3, "2026-09-26T13:47:00Z", "2026-09-26T17:20:00Z",
             141.58, 48.8, 2320, "58cf7feff69de4e548f99b5e5cdad789d4a5dbfdf4ffb576ee"),
)  # fmt: skip
_ITER_DETAIL_FAILS = (
    "2T 6N 7B 10S 11B 14B 16S 36S 39N 44N 46N 54B 55N 59I 60N 62B 64B 66N 67S 69I 70S "
    "77S 78I 80N 81N 82S 88N 90S 95N 96N 98N 101N 102N 103N 106B 107N 109S 114N 116B "
    "118B 121S 122N 123N 125B 130N 132I 136N 137N 139I 140B 142B 145S 146N 149N 151I "
    "166N 167I 177N 180S 182S 184S 188B 191N 195N 199N"
)
_ITER_DETAIL_STEPS = (
    "15 14 29 8 17 10 19 40 15 14 11 40 10 12 40 12 21 7 7 14 9 19 10 7 7 8 13 14 16 "
    "19 16 11 7 8 11 15 24 15 10 12 7 10 9 9 23 23 14 14 8 10 12 19 14 16 40 17 22 11 "
    "15 8 11 23 40 16 40 15 22 13 21 4 12 17 16 17 9 9 8 12 8 17 18 21 17 9 11 8 15 9 "
    "19 20 10 13 8 16 15 18 15 10 15 18 13 19 18 13 17 12 40 10 9 20 22 16 9 13 10 13 "
    "40 19 40 11 8 19 19 22 17 40 10 8 15 14 12 9 9 13 18 12 17 15 8 7 40 16 40 17 7 "
    "22 21 15 10 19 8 5 17 17 16 12 14 10 13 15 14 14 16 15 14 10 14 6 11 14 8 13 14 "
    "8 14 14 11 15 17 21 17 13 13 11 13 12 18 18 40 11 5 12 10 14 12 14 10 14 14 14"
)
_ITER_TRACE: tuple[tuple[str, str, str, float, float], ...] = (
    ("template_search", "target", "12 templates", 12.4, 1.8),
    ("route_score", "amide disconnection", "0.81", 14.1, 0.9),
    ("stock_check", "OC(=O)c1ccc(F)cc1", "in stock", 15, 0.3),
    ("stock_check", "NC1CCN(Cc2ccc(OC)cc2)CC1", "not in stock", 15.9, 0.3),
    ("template_search", "NC1CCN(Cc2ccc(OC)cc2)CC1", "9 templates", 17.6, 1.6),
    ("route_score", "reductive amination", "0.77", 19, 0.8),
    ("stock_check", "COc1ccc(C=O)cc1", "in stock", 19.9, 0.3),
    ("stock_check", "CC(C)(C)OC(=O)NC1CCNCC1", "in stock", 20.8, 0.3),
    ("condition_predict", "reductive amination", "NaBH(OAc)3, DCE", 22.5, 1.2),
    ("condition_predict", "amide coupling", "HATU, DIPEA, DMF", 24.1, 1.1),
    ("submit", "route, depth 3", "solved", 25.3, 0.6),
)
_ITER_DETAIL = ("v8", 2)  # the run shown on the run page
_ITER_FAIL_CODES = {
    "T": "timeout",
    "N": "no route",
    "B": "budget hit",
    "S": "not in stock",
    "I": "invalid SMILES",
}


def _bits(solved_hex: str) -> list[bool]:
    """
    Decode 200 per-target outcomes from hex.

    Parameters
    ----------
    solved_hex : str
        50 hex digits; the most significant bit is target 1.

    Returns
    -------
    list of bool

    Examples
    --------
    >>> _bits("8" + "0" * 49)[:2]
    [True, False]
    """
    return [bit == "1" for bit in f"{int(solved_hex, 16):0200b}"]


def _seed_agent_iteration(sd: _Seeder) -> None:
    """
    Seed ``retro-agent/retro-bench-200`` (kind ``agent_iteration``).

    Nine versions x three seeds with the exact per-target outcomes, costs, and
    tokens of ``kinds/agent_iteration/data.js``; the v8 seed 2 run also has
    failure categories, step counts, and one trajectory.

    Parameters
    ----------
    sd : _Seeder
        Target home.
    """
    project, task = DEMO_TASKS["agent_iteration"]
    ids = [f"T-{i + 1:03d}" for i in range(200)]
    dataset = {
        "version": "v2",
        "host": "gpu-07",
        "path": "/data/retro-bench-200/targets.jsonl",
        "splits": {"test": "/data/retro-bench-200/targets.jsonl"},
    }
    repo = sd.project(
        _task_config(
            project,
            task,
            kind="agent_iteration",
            dataset=dataset,
            metrics={"solved": {"version": "v2", "fn": "demo_metrics:solved"}},
            primary="solved",
            description="Route found and verified for each of 200 targets.",
            version_param="version",
        ),
        {},
    )
    ref = DatasetRef(
        name=task, version="v2", split="test", host="gpu-07", path=dataset["splits"]["test"]
    )
    fails = {
        ids[int(item[:-1])]: _ITER_FAIL_CODES[item[-1]]
        for item in "".join(_ITER_DETAIL_FAILS).split()
    }
    steps = [int(n) for n in "".join(_ITER_DETAIL_STEPS).split()]
    versions = {v.v: v for v in _ITER_VERSIONS}
    for spec in _ITER_RUNS:
        v = versions[spec.v]
        created = sd.at(spec.started_at)
        ended = sd.at(spec.ended_at)
        record, run = sd.start(
            _RunSpec(
                project=project,
                task=task,
                repo=repo,
                hypothesis=v.change,
                command_template=["python", "-m", "retro_agent.run", "--seed", "{seed}"],
                params={
                    "version": v.v,
                    "model": v.model,
                    "prompt": v.prompt,
                    "tools": v.tools,
                    "temperature": str(v.temperature),
                    "depth": str(v.depth),
                    "budget": str(v.budget),
                    "retries": str(v.retries),
                },
                seed=spec.seed,
                created_at=created,
                created_by=v.by,
                host="gpu-07",
                commit=v.commit,
                key=f"{v.v}-{spec.seed}",
                datasets=[ref],
            )
        )
        solved = _bits(spec.solved)
        detail = (spec.v, spec.seed) == _ITER_DETAIL
        run.log_predictions(
            {
                "id": ex,
                "prediction": "route" if ok else None,
                "meta": {"category": fails.get(ex), "steps": steps[i]} if detail else {},
            }
            for i, (ex, ok) in enumerate(zip(ids, solved, strict=True))
        )
        run.log_usage(
            tokens_in=round(spec.tokens_m * 1e6),
            usd=spec.cost_usd,
            seconds=(ended - created).total_seconds(),
        )
        run.log({"tool_calls": spec.tool_calls}, step=0)
        if detail:
            run.log_trace(
                ids[34],
                (
                    {
                        "turn": turn,
                        "tool": tool,
                        "args": args,
                        "result": result,
                        "tokens_in": round(k_tokens * 1000),
                        "tokens_out": 0,
                        "seconds": seconds,
                        "error": None,
                    }
                    for turn, (tool, args, result, k_tokens, seconds) in enumerate(
                        _ITER_TRACE, start=1
                    )
                ),
            )
        sd.per_example(
            record, "solved@v2", {ex: {"solved": ok} for ex, ok in zip(ids, solved, strict=True)}
        )
        sd.finish(
            record,
            status=RunStatus.FINISHED,
            ended_at=ended,
            exit_code=0,
            scores=[("solved", "v2", "value", sum(solved) / len(solved))],
        )
```

Then, in `_SEEDERS` at the bottom of `src/hypothex/demo.py`, replace

```python
    "agent_eval": _seed_agent_eval,
}
```

with

```python
    "agent_eval": _seed_agent_eval,
    "agent_iteration": _seed_agent_iteration,
}
```

- [ ] **Step 4: Run the tests and checks to verify they pass**

Run: `uv run pytest tests/test_demo.py -v`
Expected: `8 passed`.

Run: `uv run ruff check src/hypothex/demo.py tests/test_demo.py && uv run ruff format --check src/hypothex/demo.py tests/test_demo.py && uv run ty check src/hypothex/demo.py tests/test_demo.py`
Expected: `All checks passed!`, `2 files already formatted`, `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/demo.py tests/test_demo.py
git commit -m "feat: demo agent_iteration runs across nine versions"
```

---

### Task 29: Demo system_bench kind, all-kinds checks, and the Overview on the demo

**Files:**
- Modify: `src/hypothex/demo.py` (three imports; new `system_bench` section; `_SEEDERS` entry)
- Test: `tests/test_demo.py` (four imports; five tests appended)

**Interfaces:**
- Consumes: Task 24 (`build_overview`), Task 25 helpers; Tasks 15, 17, and 20–23 (`load_preset` via `get_view`, `query_view`); `hypothex.core.stats.quantile(values, q) -> float` (contract 1.1, linear interpolation); `Run.log_samples(name, values)`; `TaskSpec.baseline`.
- Produces: project `route-search`, task `route-api-latency` (kind `system_bench`, `baseline: tag:baseline`, primary `latency/p95`, lower is better): 3 versions x 3 repeats of 5,000 requests from `kinds/system_bench/data.js`. Raw latencies in `samples/latency_ms.jsonl`; 1 Hz metrics `cpu_pct`, `gpu_pct`, `mem_gb`, `steal_pct`, and `latency_p95_ms` (step = second); a concurrency sweep `sweep/rps` (step = concurrency) on each third repeat; scores `latency@v1` (`p50`, `p95`, `p99`), `errors@v1` (`rate`), `throughput@v1` (`rps`). Baseline runs are tagged `baseline`. One failed first attempt (exit 1) 10 s before cache repeat 3, in the same seed group. After this task `seed_demo(home)` with the default `kinds` seeds all five kinds.

- [ ] **Step 1: Write the failing tests**

In `tests/test_demo.py`, replace

```python
from pathlib import Path
```

with

```python
import time
from datetime import timedelta
from pathlib import Path
```

and replace

```python
from hypothex.core.fsutil import read_jsonl
```

with

```python
from hypothex.core.fsutil import read_jsonl
from hypothex.core.ids import utcnow
from hypothex.core.overview import build_overview
from hypothex.core.panels import query_view
```

Then append to the end of `tests/test_demo.py` (two blank lines before it):

```python
def test_system_bench_mirrors_mockup(dctx: Context) -> None:
    board = q.get_leaderboard(dctx, REFS["system_bench"])
    assert board.kind == "system_bench" and not board.higher_is_better
    runs = [r for r in _runs(dctx, "route-search") if r.status == RunStatus.FINISHED]
    # p95 (linear interpolation) over each run's Float32 latencies, computed by bun
    # from kinds/system_bench/data.js
    p95 = {
        ("baseline", 1): 234.31702575683593, ("baseline", 2): 230.59684829711915,
        ("baseline", 3): 234.89067153930665, ("cache", 1): 194.79916763305684,
        ("cache", 2): 197.24704971313494, ("cache", 3): 239.69444732666022,
        ("async", 1): 163.21131973266603, ("async", 2): 168.6949531555176,
        ("async", 3): 164.95999679565435,
    }  # fmt: skip
    errors = {("cache", 3): 4, ("async", 1): 3, ("async", 3): 1}
    for (version, rep), value in p95.items():
        run = _find(runs, rep, version=version)
        scores = {s.key: s.value for s in dctx.store.read_scores("route-search", run.run_id)}
        assert scores["p95"] == pytest.approx(value, abs=1e-9)
        assert scores["rate"] == errors.get((version, rep), 0) / 5000
        samples = read_jsonl(dctx.run_dir(run) / "samples" / "latency_ms.jsonl")
        assert len(samples) == 5000
        assert run.tags == (["baseline"] if version == "baseline" else [])
    # concurrency sweep on each third repeat (data.js SWEEP)
    cache3 = _find(runs, 3, version="cache")
    sweep = {
        p.step: p.value
        for p in dctx.store.read_metric_points("route-search", cache3.run_id)
        if p.name == "sweep/rps"
    }
    assert sweep == {
        1: 16.8,
        2: 34.4,
        4: 69.2,
        8: 137.2,
        16: 265.3,
        32: 429.2,
        64: 514.8,
        128: 522.9,
    }
    failed = [r for r in _runs(dctx, "route-search") if r.status == RunStatus.FAILED]
    assert len(failed) == 1 and failed[0].exit_code == 1
    assert failed[0].config_hash == cache3.config_hash
    assert cache3.created_at - failed[0].created_at == timedelta(seconds=10)


def test_seed_demo_is_fast_and_registers_every_kind(tmp_path: Path) -> None:
    start = time.perf_counter()
    refs = seed_demo(tmp_path / "home")
    assert time.perf_counter() - start < 10.0
    assert refs == REFS
    ctx = Context.open(tmp_path / "home")
    for kind, ref in refs.items():
        entry, task = q.resolve_task(ctx, ref)
        assert entry.config.tasks[task].kind == kind
        assert Path(entry.repo) == (tmp_path / "home" / "demo-repos" / entry.project).resolve()
    # the newest run (the one still training) starts 40 min before the current hour
    newest = max(r.created_at for r in ctx.index.list_runs(include_archived=True, limit=None))
    assert utcnow() - timedelta(minutes=101) <= newest <= utcnow()


def test_overview_of_demo(dctx: Context) -> None:
    summary = build_overview(dctx, since=DEMO_EPOCH - timedelta(hours=24))
    assert summary.counts == {
        "total": 45,
        "queued": 0,
        "running": 1,
        "finished": 40,
        "failed": 4,
        "killed": 0,
        "lost": 0,
        "archived": 7,
        "agent": 30,
        "human": 15,
    }
    assert [r.params["config"] for r in summary.running] == ["lr2e-4"]
    assert len(summary.failures) == 4 and all(f.retried_ok for f in summary.failures)
    assert [(p.project, p.runs, p.kind) for p in summary.projects] == [
        ("retro-agent", 27, "agent_iteration"),
        ("retro-agents", 12, "agent_eval"),
        ("route-search", 9, "system_bench"),
        ("rxn-forward", 8, "training"),
        ("toy-classifier", 12, "generic"),
    ]


def test_every_kind_overview_queries_cleanly(dctx: Context) -> None:
    # The preset names must match what the demo writes; the UI tests and screenshots use it.
    for kind, ref in REFS.items():
        entry, task = q.resolve_task(dctx, ref)
        view = get_view(Path(entry.repo), entry.config, task, "overview")
        results = {r.title: r for r in query_view(dctx, entry.project, task, view)}
        for title, result in results.items():
            assert "error" not in result.meta, (kind, title, result.meta.get("error"))
            if result.type != "markdown":
                assert result.rows, (kind, title)
        if kind == "training":
            assert {row["name"] for row in results["GPU"].rows} == {"sys/gpu_util"}
            assert results["Checkpoints"].meta["checkpoints"]
        if kind == "agent_iteration":
            solved = results["Solved by version"]
            assert solved.meta["x_type"] == "ordinal"
            assert [row["x"] for row in solved.rows] == [f"v{i}" for i in range(1, 10)]
            cost = results["$ per solved"]
            assert [row["x"] for row in cost.rows] == [f"v{i}" for i in range(1, 10)]
            # v1 (data.js): $74.28, $79.57, $75.70 for 80 solved targets in each seed
            assert cost.rows[0]["y"] == pytest.approx((74.28 + 79.57 + 75.70) / 240)
            # regressions (contract 1.6). Solved: no drop is outside the best earlier
            # version's CI (the largest, v6 0.558 vs v5 0.607, is inside v5's interval).
            assert not any(row["regression"] for row in solved.rows)
            # $ per solved is lower-is-better (usage.*), seed t-intervals over 3 seeds:
            # v3 is the cheapest (0.918, hi 1.004); v4..v9 all have y_lo above 1.004
            # (v4 1.127, v9 1.056), so each is flagged
            assert [row["regression"] for row in cost.rows] == [False] * 3 + [True] * 6
        if kind == "system_bench":
            assert results["Latency"].rows[0]["n"] == 15_000  # 3 repeats x 5,000 requests
            errors = results["Error rate"].rows
            assert any(row["metric"] == "errors" and row["key"] == "rate" for row in errors)
            # percentile table: one distribution row per version, Δ vs the tag:baseline group
            table = results["Percentiles"]
            assert (table.type, table.meta["render"]) == ("distribution", "table")
            assert len(table.rows) == 3
            baseline = {row["group_id"]: row for row in table.rows}[table.meta["baseline"]]
            assert baseline["vs_baseline"] is None
            deltas = [row["vs_baseline"] for row in table.rows if row is not baseline]
            # 3 repeats on each side, so every percentile has a bootstrap interval
            assert all(lo is not None and lo <= hi for d in deltas for _, lo, hi in d.values())
            # async: repeat p95s 163-169 ms vs baseline 231-235 ms, about -29%
            assert min(d["p95"][0] for d in deltas) < -0.25
            # 9 finished runs: p95 for the spread
            assert len(results["Repeat spread"].rows) == 9


def test_existing_project_blocks_every_kind(tmp_path: Path) -> None:
    home = tmp_path / "home"
    seed_demo(home, ["generic"])
    with pytest.raises(StoreError, match="toy-classifier"):
        seed_demo(home, ["system_bench", "generic"])
    assert not Context.open(home).layout.project_dir("route-search").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_demo.py -v`
Expected: `5 failed, 8 passed`. The failures: `test_system_bench_mirrors_mockup` and `test_every_kind_overview_queries_cleanly` (`StoreError: unknown project 'route-search'`; the four other kinds query cleanly first), `test_seed_demo_is_fast_and_registers_every_kind` and `test_existing_project_blocks_every_kind` (`ValueError: unknown demo kinds ['system_bench']`), `test_overview_of_demo` (`AssertionError`: `total` is 35, not 45).

- [ ] **Step 3: Add the imports**

In `src/hypothex/demo.py`, replace

```python
import math
```

with

```python
import math
import struct
```

replace

```python
from dataclasses import dataclass, field
```

with

```python
from dataclasses import dataclass, field, replace
```

and replace

```python
from hypothex.core.seeds import config_hash, run_fingerprint
```

with

```python
from hypothex.core.seeds import config_hash, run_fingerprint
from hypothex.core.stats import quantile
```

- [ ] **Step 4: Add the system_bench section and register it**

In `src/hypothex/demo.py`, insert this block immediately above the line `# --------------------------------------------------------------------- entry point`, with two blank lines between the block's last line and that marker line:

```python
# --------------------------------------------------------------------- system_bench
def _f32(x: float) -> float:
    """
    Round to single precision, like storing into a JavaScript ``Float32Array``.

    Parameters
    ----------
    x : float
        Value to round.

    Returns
    -------
    float
    """
    return struct.unpack("f", struct.pack("f", x))[0]


_SB_REQUESTS, _SB_WARMUP, _SB_CONCURRENCY, _SB_TIMEOUT_MS = 5000, 200, 16, 1000
_SB_VERSIONS = {
    "baseline": ("baseline", "main", "a1b2c3d9e8f70615", "human", "main@a1b2"),
    "cache": ("cache-enabled", "feat/route-cache", "c7e41f02b6a95d38", "agent:bench", "LRU 50k"),
    "async": (
        "async-worker", "feat/async-worker", "9d03b5e4417ac2f0", "agent:bench",
        "4 workers, batch 8",
    ),
}  # fmt: skip
_SB_SERVER = {
    "baseline": "uvicorn app:app --workers 1",
    "cache": "uvicorn app:app --workers 1 --route-cache 50000",
    "async": "uvicorn app:app --workers 4 --batch 8",
}
_SB_ERR503 = {"baseline": 0.0, "cache": 0.0, "async": 0.0008}
_SB_GPU_PER_RPS = {"baseline": 0.372, "cache": 0.372, "async": 0.452}
_SB_CPU_BASE = {"baseline": 23, "cache": 16, "async": 31}
_SB_CPU_PER_RPS = {"baseline": 0.145, "cache": 0.062, "async": 0.178}
_SB_XMAX = {"baseline": 196, "cache": 520, "async": 312}
_SB_CONC = (1, 2, 4, 8, 16, 32, 64, 128)
_SB_COMMAND: str = (
    "python bench/load.py --url http://127.0.0.1:8080/v2/route -n 5000 -c 16 --warmup 200 "
    "--seed {seed}"
)
# version, repeat, created_at, drift, noisy neighbour (t0, t1, cpu steal %, slowdown)
_SB_RUNS: tuple[tuple[str, int, str, float, tuple[float, float, float, float] | None], ...] = (
    ("baseline", 1, "2026-09-27T09:12:04Z", 1.004, None),
    ("baseline", 2, "2026-09-27T09:14:12Z", 0.991, None),
    ("baseline", 3, "2026-09-27T09:16:20Z", 1.009, None),
    ("cache", 1, "2026-09-27T09:30:45Z", 0.996, None),
    ("cache", 2, "2026-09-27T09:32:33Z", 1.007, None),
    ("cache", 3, "2026-09-27T09:34:21Z", 1.002, (5.5, 12.0, 23, 2.1)),
    ("async", 1, "2026-09-27T09:50:10Z", 0.998, None),
    ("async", 2, "2026-09-27T09:51:58Z", 1.006, None),
    ("async", 3, "2026-09-27T09:53:46Z", 0.993, None),
)


@dataclass
class _Bench:
    """Raw samples and 1 Hz utilisation of one benchmark run."""

    t: list[float]
    lat: list[float]
    err: list[int]
    hit: list[bool]
    duration: float
    cpu: list[float]
    gpu: list[float]
    mem: list[float]
    steal: list[float]


def _lognormal(draw: Callable[[], float], median: float, sigma: float) -> float:
    """
    Draw a log-normal value with the given median.

    Parameters
    ----------
    draw : callable
        Uniform generator.
    median, sigma : float
        Median and log-scale spread.

    Returns
    -------
    float
    """
    return median * math.exp(sigma * _gauss(draw))


def _latency(vid: str, draw: Callable[[], float], t: float) -> tuple[float, bool]:
    """
    Draw one request latency (ms) and whether the route cache was hit.

    Parameters
    ----------
    vid : str
        Version id.
    draw : callable
        Uniform generator.
    t : float
        Seconds since measurement start (the cache warms up).

    Returns
    -------
    tuple of (float, bool)
    """
    if vid == "cache":
        if draw() < 0.66 - 0.28 * math.exp(-t / 2.5):
            return _lognormal(draw, 14, 0.35), True
        extra = 80 + 140 * draw() if draw() < 0.006 else 0
        return extra + _lognormal(draw, 124, 0.40), False
    if vid == "async":
        extra = 60 + 90 * draw() if draw() < 0.003 else 0
        return extra + _lognormal(draw, 104, 0.28), False
    extra = 80 + 140 * draw() if draw() < 0.006 else 0
    return extra + _lognormal(draw, 118, 0.40), False


def _simulate(
    vid: str, seed: int, drift: float, noisy: tuple[float, float, float, float] | None
) -> _Bench:
    """
    Port of the ``system_bench`` mockup's closed-loop load simulation.

    Parameters
    ----------
    vid : str
        Version id.
    seed : int
        RNG seed.
    drift : float
        Multiplier on every latency (run-to-run drift).
    noisy : tuple or None
        Noisy-neighbour window ``(t0, t1, steal, slowdown)``.

    Returns
    -------
    _Bench
    """
    r = _mulberry32(seed)
    free = [0.0] * _SB_CONCURRENCY
    t: list[float] = []
    lat: list[float] = []
    err: list[int] = []
    hit: list[bool] = []
    t_start = 0.0
    for i in range(_SB_REQUESTS + _SB_WARMUP):
        w = 0
        for j in range(1, _SB_CONCURRENCY):
            if free[j] < free[w]:
                w = j
        s = free[w]
        if i == _SB_WARMUP:
            t_start = s
        tm = s - t_start if i >= _SB_WARMUP else 0.0
        ms, h = _latency(vid, r, tm)
        ms *= drift
        if noisy is not None and noisy[0] <= tm <= noisy[1]:
            ms *= 1 + (noisy[3] - 1) * 0.55 if h else noisy[3] * (0.85 + 0.3 * r())
            if r() < 0.015:
                ms += 600 + 300 * r()
        e = 0
        if ms > _SB_TIMEOUT_MS:
            ms, e = float(_SB_TIMEOUT_MS), 1
        elif r() < _SB_ERR503[vid]:
            ms, e = 2 + 3 * r(), 2
        free[w] = s + ms / 1000 + 0.0004
        if i >= _SB_WARMUP:
            t.append(_f32(free[w] - t_start))
            lat.append(_f32(ms))
            err.append(e)
            hit.append(h)
    duration = max(t)
    r = _mulberry32(seed ^ 0x5BD1E995)
    n = math.ceil(duration)
    done, gpu_req = [0] * n, [0] * n
    for ti, h in zip(t, hit, strict=True):
        b = min(n - 1, math.floor(ti))
        done[b] += 1
        if not h:
            gpu_req[b] += 1
    cpu, gpu, mem, steal = [], [], [], []
    cached = 0
    for s in range(n):
        frac = max(0.2, duration - s) if s == n - 1 else 1
        rps, grps = done[s] / frac, gpu_req[s] / frac
        in_nn = noisy is not None and noisy[0] <= s + 0.5 <= noisy[1]
        if noisy is not None and in_nn:
            steal.append(_fixed(noisy[2] + 3 * _gauss(r), 1))
        else:
            steal.append(_fixed(0.3 + 0.25 * r(), 1))
        load = _SB_CPU_BASE[vid] + _SB_CPU_PER_RPS[vid] * rps + 1.6 * _gauss(r)
        cpu.append(_fixed(min(99, load + (9 if in_nn else 0)), 1))
        gpu.append(_fixed(min(99, _SB_GPU_PER_RPS[vid] * grps + 1.8 * _gauss(r)), 1))
        if vid == "cache":
            cached += gpu_req[s]
        base = 7.0 if vid == "async" else 6.1
        grown = cached * 0.00082 if vid == "cache" else 0
        mem.append(_fixed(base + grown + 0.04 * _gauss(r), 2))
    return _Bench(t, lat, err, hit, duration, cpu, gpu, mem, steal)


def _sweep(vid: str, vi: int, clean: list[_Bench]) -> list[tuple[int, float]]:
    """
    Port of the mockup's concurrency sweep: throughput (req/s) per concurrency.

    Parameters
    ----------
    vid : str
        Version id.
    vi : int
        Version index (RNG seed offset).
    clean : list of _Bench
        The version's repeats without a noisy neighbour; the curve passes
        through their mean throughput at concurrency 16.

    Returns
    -------
    list of (int, float)
    """
    r = _mulberry32(777 + vi)
    k = 3.2

    def throughput(c: int, r0: float) -> float:
        return 1 / math.pow(math.pow(r0 / c, k) + math.pow(1 / _SB_XMAX[vid], k), 1 / k)

    x16 = 0.0
    for b in clean:
        x16 += sum(1 for e in b.err if not e) / _fixed(b.duration, 2)
    x16 /= len(clean)
    lo, hi = 0.001, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if throughput(16, mid) > x16:
            lo = mid
        else:
            hi = mid
    r0 = (lo + hi) / 2
    return [
        (c, _fixed(x16 if c == 16 else throughput(c, r0) * (1 + 0.012 * _gauss(r)), 1))
        for c in _SB_CONC
    ]


def _seed_system_bench(sd: _Seeder) -> None:
    """
    Seed ``route-search/route-api-latency`` (kind ``system_bench``).

    Three versions x three repeats of 5,000 requests from
    ``kinds/system_bench/data.js``: raw latency samples, 1 Hz utilisation, a
    concurrency sweep on each third repeat, and one failed first attempt
    (server not ready) before cache repeat 3.

    Parameters
    ----------
    sd : _Seeder
        Target home.
    """
    project, task = DEMO_TASKS["system_bench"]
    dataset = {
        "version": "v1",
        "path": "bench/requests.jsonl",
        "splits": {"test": "bench/requests.jsonl"},
    }
    lower = {"higher_is_better": False, "fn": "demo_metrics:harness", "version": "v1"}
    repo = sd.project(
        _task_config(
            project,
            task,
            kind="system_bench",
            dataset=dataset,
            metrics={
                "latency": lower,
                "errors": lower,
                "throughput": {"version": "v1", "fn": "demo_metrics:harness"},
            },
            primary="latency/p95",
            description="POST /v2/route, 5,000 requests after 200 warm-up, concurrency 16.",
            baseline="tag:baseline",
        ),
        {"bench/requests.jsonl": _jsonl({"id": f"q{i}", "reference": None} for i in range(3))},
    )
    ref = DatasetRef(name=task, version="v1", split="test", path=str(repo / dataset["path"]))
    clean: dict[str, list[_Bench]] = {}  # repeats without a noisy neighbour
    for i, (vid, rep, stamp, drift, noisy) in enumerate(_SB_RUNS):
        bench = _simulate(vid, 9001 + i * 7919, drift, noisy)
        if noisy is None:
            clean.setdefault(vid, []).append(bench)
        name, branch, commit, by, note = _SB_VERSIONS[vid]
        created = sd.at(stamp)
        spec = _RunSpec(
            project=project,
            task=task,
            repo=repo,
            hypothesis=f"{name}: {note}",
            command_template=_SB_COMMAND.split(),
            params={"version": vid, "server": _SB_SERVER[vid], "concurrency": "16"},
            seed=rep,
            created_at=created,
            created_by=by,
            host="gpu-box-1",
            commit=commit,
            branch=branch,
            key=f"{vid}-{rep}",
            tags=["baseline"] if vid == "baseline" else [],
            datasets=[ref],
        )
        if noisy is not None:  # the first attempt died before the server came up
            first_try = replace(
                spec, created_at=created - timedelta(seconds=10), key=f"{vid}-{rep}-1"
            )
            failed, _ = sd.start(first_try)
            sd.finish(
                failed,
                status=RunStatus.FAILED,
                ended_at=failed.created_at + timedelta(seconds=2.1),
                exit_code=1,
                stderr="server not ready: connect :8080 refused\n",
            )
        record, run = sd.start(spec)
        run.log_samples("latency_ms", bench.lat)
        for s, values in enumerate(zip(bench.cpu, bench.gpu, bench.mem, bench.steal, strict=True)):
            cpu, gpu, mem, steal = values
            run.log({"cpu_pct": cpu, "gpu_pct": gpu, "mem_gb": mem, "steal_pct": steal}, step=s)
        per_second: dict[int, list[float]] = {}
        for ti, ms in zip(bench.t, bench.lat, strict=True):
            per_second.setdefault(math.floor(ti), []).append(ms)
        for s in sorted(per_second):
            run.log({"latency_p95_ms": quantile(per_second[s], 0.95)}, step=s)
        if rep == 3:  # the sweep ran after the third repeat
            for c, rps in _sweep(vid, list(_SB_VERSIONS).index(vid), clean[vid]):
                run.log({"sweep/rps": rps}, step=c)
        ok = sum(1 for e in bench.err if not e)
        duration = _fixed(bench.duration, 2)
        sd.finish(
            record,
            status=RunStatus.FINISHED,
            ended_at=created + timedelta(seconds=duration + 6.4),
            exit_code=0,
            scores=[
                ("latency", "v1", "p50", quantile(bench.lat, 0.50)),
                ("latency", "v1", "p95", quantile(bench.lat, 0.95)),
                ("latency", "v1", "p99", quantile(bench.lat, 0.99)),
                ("errors", "v1", "rate", (len(bench.err) - ok) / len(bench.err)),
                ("throughput", "v1", "rps", ok / duration),
            ],
        )
```

Then, in `_SEEDERS` at the bottom of `src/hypothex/demo.py`, replace

```python
    "agent_iteration": _seed_agent_iteration,
}
```

with

```python
    "agent_iteration": _seed_agent_iteration,
    "system_bench": _seed_system_bench,
}
```

- [ ] **Step 5: Run the tests and checks to verify they pass**

Run: `uv run pytest tests/test_demo.py tests/core/test_overview.py -v`
Expected: `21 passed` (about 10 s).

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check src/hypothex/demo.py src/hypothex/core/overview.py tests/test_demo.py tests/core/test_overview.py`
Expected: `All checks passed!`, all files already formatted, `All checks passed!`.

Run: `uv run python -m doctest src/hypothex/demo.py src/hypothex/core/overview.py && uv run pytest -q`
Expected: no doctest output; the whole suite passes.

- [ ] **Step 6: Commit**

```bash
git add src/hypothex/demo.py tests/test_demo.py
git commit -m "feat: demo system_bench runs with latency samples and sweep"
```

## Part 7: API, CLI, MCP, serving the UI, skill, and docs (Tasks 30–35)

This part adds the interface layer for phase 1b: contract sections 2 and 3. It uses
the core modules from the earlier parts only through the contract names
(`hypothex.core.views`, `hypothex.core.panels`, `RunStore.list_traces`,
`hypothex.core.overview`, `hypothex.demo`, `hypothex.sdk.Run.log_trace`,
`TaskSpec.kind`).

**Files owned by this part:** `src/hypothex/mcp/server.py`, `src/hypothex/api/app.py`,
`src/hypothex/cli/main.py`, `skills/hypothex/SKILL.md`, `docs/views.rst`,
`docs/index.rst`, `docs/cli.rst`, `pyproject.toml`, `tests/mcp/test_server.py`,
`tests/api/test_app.py`, `tests/cli/test_cli.py`, `tests/test_skill.py`.

**Shared view helpers.** The API, the CLI, and MCP need the same five view operations
(list, read with stored text, validate, save, delete, query). They live once, as public
functions in `hypothex.mcp.server` (the API already imports that module; the CLI imports
it lazily inside the `hx view` commands, because importing the MCP SDK costs about
0.4 s). `ViewValidationError(ConfigError)` carries the `issues` list so every layer can
return it: HTTP 400 `{error, type, issues}`, CLI `--json` error `{error, type, issues}`,
MCP `add_view` `{ok: false, issues}`. View names are checked only by
`core.views.check_view_name` (Task 17), so every interface gives the same error.

**Packaging note.** The contract says `ui_dist` goes in the wheel "via
`[tool.hatch.build.targets.wheel.force-include]` only when present". Hatchling's
`force-include` fails the build when the path is missing (verified: `FileNotFoundError:
Forced include not found`). Hatchling's `artifacts` option includes the folder when it
exists (even if git-ignored) and is silent when it does not. Task 33 uses
`artifacts`, which is the only static setting that meets the binding part ("only when
present").

---

### Task 30: Shared view helpers and MCP view tools

**Files:**
- Modify: `src/hypothex/mcp/server.py`
- Test: `tests/mcp/test_server.py`

**Interfaces:**
- Consumes (contract 1.3, 1.4, 1.6): `TaskSpec.kind`, `TaskSpec.views`;
  `hypothex.core.views`: `ViewSpec`, `PanelSpec`, `ViewInfo`, `ValidationIssue`,
  `load_preset(kind) -> ViewSpec`, `resolve_view(view) -> ViewSpec`,
  `list_views(repo, config, task) -> list[ViewInfo]`,
  `get_view(repo, config, task, name) -> ViewSpec`,
  `validate_view_text(text, known_metrics, known_fields) -> tuple[ViewSpec | None, list[ValidationIssue]]`,
  `save_view(repo, task, name, text) -> Path`, `delete_view(repo, task, name) -> None`,
  `check_view_name(name) -> None`, `RESERVED_VIEW`,
  `view_context(ctx, project, task) -> tuple[set[str], dict[str, set[str]]]`;
  `hypothex.core.panels`: `query_panel(ctx, project, task, panel, runs_filter=None) -> PanelResult`,
  `query_view(ctx, project, task, view) -> list[PanelResult]`;
  `hypothex.core.queries.resolve_task(ctx, ref, project=None) -> tuple[ProjectEntry, str]`.
- Produces (module `hypothex.mcp.server`, used by Task 31, Task 32, Task 34):
  - `PRESET_VIEW = core_views.RESERVED_VIEW` (`"overview"`); names are checked with `core_views.check_view_name` (Task 17), not a second pattern
  - `class ViewValidationError(ConfigError)` with attribute `issues: list[ValidationIssue]`
  - `dump_view(view: ViewSpec) -> dict[str, Any]` (JSON, key `from`, not `from_`)
  - `list_task_views(ctx: Context, task: str, project: str | None = None) -> list[ViewInfo]`
  - `view_document(ctx, task, name, project=None) -> dict[str, Any]` = `{info, text, view}`; unknown name raises `StoreError`
  - `validate_view(ctx, task, text, project=None) -> dict[str, Any]` = `{ok, issues, view?}`; `view` is the RESOLVED view (`resolve_view` applied, then `dump_view`), so a `from:` view comes back with the preset's panels (with their layouts) first. `resolve_view` loads the preset named by `from`, whatever the task's own kind is. `issues` still refer to the lines of the text as written.
  - `put_view(ctx, task, name, text, project=None) -> dict[str, Any]` = `{info, view}`; raises `ViewValidationError`
  - `remove_view(ctx, task, name, project=None) -> dict[str, bool]` = `{"ok": True}`
  - `query_task_view(ctx, task, *, project=None, name=None, view=None, panel=None) -> dict[str, Any]` = `{panels: [PanelResult JSON]}`
  - MCP tools `list_views(task, project=None)`, `get_view(task, name, project=None)`,
    `add_view(task, name, yaml_text, project=None)`, `query_view(task, name, project=None)`.

- [ ] **Step 1: Write the failing tests**

In `tests/mcp/test_server.py`, replace the `EXPECTED_TOOLS` set with:

```python
EXPECTED_TOOLS = {
    "list_projects",
    "list_tasks",
    "get_task",
    "get_leaderboard",
    "list_runs",
    "get_run",
    "compare_runs",
    "launch_run",
    "rerun",
    "reinfer",
    "reevaluate",
    "stop_run",
    "add_note",
    "tag_run",
    "get_predictions",
    "list_views",
    "get_view",
    "add_view",
    "query_view",
}

GOOD_VIEW = """\
title: acc only
panels:
  - type: leaderboard
    title: board
    data: {metrics: [accuracy]}
"""
# "acuracy" is one letter off; difflib.get_close_matches("acuracy", ["accuracy"]) ->
# ["accuracy"]. The bad name sits on line 5 (1-based) of the text.
BAD_VIEW = GOOD_VIEW.replace("[accuracy]", "[acuracy]")
```

Append this test at the end of the file:

```python
def test_view_tools(home: Path, ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    evaluate_run(ctx, "r1")
    path = toy_repo.resolve() / ".hypothex" / "views" / "toy-acc" / "acc.yaml"

    err, listed = call(home, "list_views", {"task": "toy-acc"})
    assert not err
    assert [(v["name"], v["origin"]) for v in listed["views"]] == [("overview", "preset")]

    err, bad = call(home, "add_view", {"task": "toy-acc", "name": "acc", "yaml_text": BAD_VIEW})
    assert not err and bad["ok"] is False
    assert (bad["issues"][0]["line"], bad["issues"][0]["suggestion"]) == (5, "accuracy")
    assert not path.exists()

    err, good = call(home, "add_view", {"task": "toy-acc", "name": "acc", "yaml_text": GOOD_VIEW})
    assert not err and good["ok"] is True
    assert (good["info"]["name"], good["info"]["path"]) == ("acc", str(path))
    assert path.read_text() == GOOD_VIEW

    err, doc = call(home, "get_view", {"task": "toy-acc", "name": "acc"})
    assert not err and doc["text"] == GOOD_VIEW and doc["view"]["title"] == "acc only"
    assert "from_" not in doc["view"]

    err, result = call(home, "query_view", {"task": "toy-acc", "name": "acc"})
    assert not err
    assert [p["type"] for p in result["panels"]] == ["leaderboard"]
    assert [r["run_ids"] for r in result["panels"][0]["rows"]] == [["r1"]]

    err, message = call(home, "get_view", {"task": "toy-acc", "name": "nope"})
    assert err and "unknown view 'nope'" in message
    err, message = call(home, "add_view", {"task": "toy-acc", "name": "overview", "yaml_text": GOOD_VIEW})
    assert err and "preset view" in message
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/mcp/test_server.py -v`
Expected: FAIL. `test_all_tools_are_listed` fails with a set difference naming
`list_views`, `get_view`, `add_view`, `query_view`; `test_view_tools` fails because the
tool `list_views` is unknown (`err` is `True`).

- [ ] **Step 3: Add the shared helpers and the tools**

In `src/hypothex/mcp/server.py`, replace the import block (from `import functools` to
`from hypothex.core.records import RunStatus`) with:

```python
import functools
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from hypothex.core import control
from hypothex.core import panels as core_panels
from hypothex.core import queries as q
from hypothex.core import views as core_views
from hypothex.core.config import load_project_config
from hypothex.core.context import Context
from hypothex.core.errors import ConfigError, HypothexError, StoreError
from hypothex.core.evaluation import reeval
from hypothex.core.execution import RunRequest
from hypothex.core.jsonutil import to_jsonable
from hypothex.core.records import RunStatus
from hypothex.core.store import ProjectEntry
from hypothex.core.views import PanelSpec, ValidationIssue, ViewInfo, ViewSpec
```

Replace the `INSTRUCTIONS` string with:

```python
INSTRUCTIONS = """\
Hypothex tracks ML/AI experiments across projects. Each run belongs to a task
(dataset + versioned metrics) and records its hypothesis, exact command, git commit,
dataset fingerprints, config, environment, logs, predictions, and scores.

Loop for a new iteration:
1. list_tasks -> pick the task. 2. get_leaderboard -> see what is best and what was tried.
3. get_run on the top rows -> read hypotheses and notes; do not repeat work.
4. launch_run with a one-sentence hypothesis; use seeds (>= 3) before claiming a win.
5. compare_runs against the best; add_note with what you learned.
Never delete runs. Never change a metric's code without bumping its version in
hypothex.yaml; then call reevaluate for the task.

Dashboards: list_views, get_view, add_view (YAML; validated, never saved while invalid;
fix the returned issues and call again), query_view (panel data as rows).
"""
```

Insert this block directly after `INSTRUCTIONS` (before `def _expose_errors`):

```python
PRESET_VIEW = core_views.RESERVED_VIEW


class ViewValidationError(ConfigError):
    """
    A view's YAML failed validation; nothing was saved.

    Parameters
    ----------
    message : str
        One-line summary (the first issue).
    issues : list of ValidationIssue
        Every problem found, with line, path, message, and suggested fix.
    """

    def __init__(self, message: str, issues: list[ValidationIssue]) -> None:
        super().__init__(message)
        self.issues = issues


def dump_view(view: ViewSpec) -> dict[str, Any]:
    """
    Convert a view to JSON with the YAML key names (``from``, not ``from_``).

    Parameters
    ----------
    view : ViewSpec
        The view.

    Returns
    -------
    dict
        JSON-ready view.
    """
    return view.model_dump(mode="json", by_alias=True)


def list_task_views(ctx: Context, task: str, project: str | None = None) -> list[ViewInfo]:
    """
    List a task's views: ``overview`` first, then inline views, then view files.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    task : str
        Task name, or ``project/task``.
    project : str, optional
        Project to restrict the search to.

    Returns
    -------
    list of ViewInfo
    """
    entry, name = q.resolve_task(ctx, task, project)
    return core_views.list_views(Path(entry.repo), entry.config, name)


def _find_view(
    ctx: Context, task: str, name: str, project: str | None
) -> tuple[ProjectEntry, str, ViewInfo]:
    entry, task_name = q.resolve_task(ctx, task, project)
    for info in core_views.list_views(Path(entry.repo), entry.config, task_name):
        if info.name == name:
            return entry, task_name, info
    # refresh_project keeps the last good config when hypothex.yaml is invalid, so
    # a view that exists only in the broken file would be "unknown": report why
    load_project_config(Path(entry.repo))  # raises ConfigError if the file is invalid
    raise StoreError(f"unknown view {name!r} for task {entry.project}/{task_name}")


def _yaml(data: Any) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def view_document(
    ctx: Context, task: str, name: str, project: str | None = None
) -> dict[str, Any]:
    """
    Read one view: its info, its YAML text as stored, and the resolved view.

    File views return the file's text unchanged; inline views and the preset are
    serialised to YAML.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    task : str
        Task name, or ``project/task``.
    name : str
        View name (``overview`` is the kind's preset).
    project : str, optional
        Project to restrict the search to.

    Returns
    -------
    dict
        ``{"info": ViewInfo, "text": str, "view": ViewSpec}`` as JSON.

    Raises
    ------
    StoreError
        The task has no view with this name.
    ConfigError
        The view is not in the last good config and ``hypothex.yaml`` is invalid
        now (for example an inline view with YAML anchors).
    """
    entry, task_name, info = _find_view(ctx, task, name, project)
    spec = entry.config.tasks[task_name]
    if info.origin == "file" and info.path is not None:
        text = Path(info.path).read_text(encoding="utf-8")
    elif info.origin == "inline":
        text = _yaml(spec.views[name])
    else:
        preset = core_views.load_preset(spec.kind)
        text = _yaml(preset.model_dump(mode="json", by_alias=True, exclude_defaults=True))
    view = core_views.get_view(Path(entry.repo), entry.config, task_name, name)
    return {"info": to_jsonable(info), "text": text, "view": dump_view(view)}


def _check(
    ctx: Context, entry: ProjectEntry, task: str, text: str
) -> tuple[ViewSpec | None, list[ValidationIssue]]:
    metrics, fields = core_views.view_context(ctx, entry.project, task)
    return core_views.validate_view_text(text, metrics, fields)


def validate_view(ctx: Context, task: str, text: str, project: str | None = None) -> dict[str, Any]:
    """
    Validate view YAML against the task's known metrics and fields; save nothing.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    task : str
        Task name, or ``project/task``.
    text : str
        View YAML.
    project : str, optional
        Project to restrict the search to.

    Returns
    -------
    dict
        ``{"ok": bool, "issues": [ValidationIssue], "view": ViewSpec}``; ``view`` is
        present only when the YAML parsed into a view. It is the resolved view: a
        ``from:`` view comes back with the preset's panels (and their layouts) first,
        so the editor can preview and count every panel. The preset is the one
        ``from`` names, even when it is not the task's own kind.
    """
    entry, task_name = q.resolve_task(ctx, task, project)
    view, issues = _check(ctx, entry, task_name, text)
    out: dict[str, Any] = {"ok": view is not None and not issues, "issues": to_jsonable(issues)}
    if view is not None:
        out["view"] = dump_view(core_views.resolve_view(view))
    return out


def put_view(
    ctx: Context, task: str, name: str, text: str, project: str | None = None
) -> dict[str, Any]:
    """
    Validate view YAML and save it to ``<repo>/.hypothex/views/<task>/<name>.yaml``.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    task : str
        Task name, or ``project/task``.
    name : str
        View name.
    text : str
        View YAML; saved byte for byte when valid.
    project : str, optional
        Project to restrict the search to.

    Returns
    -------
    dict
        ``{"info": ViewInfo, "view": ViewSpec}`` (resolved) as JSON.

    Raises
    ------
    ConfigError
        Bad or reserved name.
    ViewValidationError
        The YAML is invalid; nothing was written.
    """
    core_views.check_view_name(name)
    entry, task_name = q.resolve_task(ctx, task, project)
    view, issues = _check(ctx, entry, task_name, text)
    if view is None or issues:
        first = issues[0].message if issues else "not a view"
        raise ViewValidationError(f"invalid view {name!r}: {first}", issues)
    core_views.save_view(Path(entry.repo), task_name, name, text)
    entry, task_name, info = _find_view(ctx, task_name, name, entry.project)
    resolved = core_views.get_view(Path(entry.repo), entry.config, task_name, name)
    return {"info": to_jsonable(info), "view": dump_view(resolved)}


def remove_view(
    ctx: Context, task: str, name: str, project: str | None = None
) -> dict[str, bool]:
    """
    Delete a view file.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    task : str
        Task name, or ``project/task``.
    name : str
        View name.
    project : str, optional
        Project to restrict the search to.

    Returns
    -------
    dict
        ``{"ok": True}``.

    Raises
    ------
    ConfigError
        ``overview`` or an inline view (edit ``hypothex.yaml`` instead).
    StoreError
        No such view.
    """
    if name == PRESET_VIEW:
        raise ConfigError(f"{PRESET_VIEW!r} is the task's preset view and cannot be deleted")
    entry, task_name, info = _find_view(ctx, task, name, project)
    if info.origin != "file":
        raise ConfigError(f"view {name!r} is declared in hypothex.yaml; remove it there")
    core_views.delete_view(Path(entry.repo), task_name, name)
    return {"ok": True}


def query_task_view(
    ctx: Context,
    task: str,
    *,
    project: str | None = None,
    name: str | None = None,
    view: ViewSpec | None = None,
    panel: PanelSpec | None = None,
) -> dict[str, Any]:
    """
    Compute panel data server-side.

    Priority: ``panel`` (one panel, filtered by ``view.runs`` when a view is also
    given), then ``view`` (resolved first), then the saved view ``name``
    (default ``overview``).

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    task : str
        Task name, or ``project/task``.
    project : str, optional
        Project to restrict the search to.
    name : str, optional
        Saved view name.
    view : ViewSpec, optional
        An unsaved view (e.g. the editor's preview).
    panel : PanelSpec, optional
        A single panel.

    Returns
    -------
    dict
        ``{"panels": [PanelResult]}`` as JSON.
    """
    entry, task_name = q.resolve_task(ctx, task, project)
    if panel is not None:
        runs = view.runs if view is not None else None
        results = [core_panels.query_panel(ctx, entry.project, task_name, panel, runs)]
    else:
        if view is not None:
            chosen = core_views.resolve_view(view)
        else:
            entry, task_name, info = _find_view(ctx, task_name, name or PRESET_VIEW, entry.project)
            chosen = core_views.get_view(Path(entry.repo), entry.config, task_name, info.name)
        results = core_panels.query_view(ctx, entry.project, task_name, chosen)
    return {"panels": to_jsonable(results)}
```

Inside `build_server`, directly before the final `return mcp`, add:

```python
    @mcp.tool()
    @_expose_errors
    def list_views(task: str, project: str | None = None) -> dict[str, Any]:
        """List a task's views (dashboards): preset `overview`, inline views, view files."""
        return {"views": [dump(v) for v in list_task_views(ctx(), task, project)]}

    @mcp.tool()
    @_expose_errors
    def get_view(task: str, name: str, project: str | None = None) -> dict[str, Any]:
        """Read one view: info (origin, path), its YAML text, and the resolved view."""
        return view_document(ctx(), task, name, project)

    @mcp.tool()
    @_expose_errors
    def add_view(task: str, name: str, yaml_text: str, project: str | None = None) -> dict[str, Any]:
        """
        Validate a view's YAML and save it as .hypothex/views/<task>/<name>.yaml in the
        repo. If invalid, nothing is saved and ok=false comes back with issues (line,
        path, message, suggestion); fix them and call again.
        """
        try:
            return {"ok": True, **put_view(ctx(), task, name, yaml_text, project)}
        except ViewValidationError as exc:
            return {"ok": False, "error": str(exc), "issues": to_jsonable(exc.issues)}

    @mcp.tool()
    @_expose_errors
    def query_view(task: str, name: str, project: str | None = None) -> dict[str, Any]:
        """Compute a saved view's panels as rows (the same data the UI draws)."""
        return query_task_view(ctx(), task, project=project, name=name)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/mcp/test_server.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Lint, format, type-check**

Run: `uv run ruff format src/hypothex/mcp/server.py tests/mcp/test_server.py && uv run ruff check src/hypothex/mcp/server.py tests/mcp/test_server.py && uv run ty check src`
Expected: `All checks passed!` and no ty errors.

- [ ] **Step 6: Commit**

```bash
git add src/hypothex/mcp/server.py tests/mcp/test_server.py
git commit -m "feat(mcp): add view tools and shared view helpers"
```

---

### Task 31: HTTP view routes (list, read, save, delete, validate, query)

**Files:**
- Modify: `src/hypothex/api/app.py`
- Test: `tests/api/test_app.py`

**Interfaces:**
- Consumes: Task 30 helpers (`ViewValidationError`, `list_task_views`, `view_document`,
  `validate_view`, `put_view`, `remove_view`, `query_task_view`); `ViewSpec`,
  `PanelSpec` (contract 1.4); `EventLog.run_once` via the existing `once()`.
- Produces (contract section 2):
  - `GET /api/v1/tasks/{project}/{task}/views` → `list[ViewInfo]`
  - `GET /api/v1/tasks/{project}/{task}/views/{name}` → `{info, text, view}`; unknown name 404
  - `PUT /api/v1/tasks/{project}/{task}/views/{name}` body `{text, command_id?}` → `{info, view}`; invalid → 400 `{error, type: "ViewValidationError", issues}`; bad/reserved name → 400
  - `DELETE /api/v1/tasks/{project}/{task}/views/{name}` → `{ok: true}`; `overview` or inline → 400
  - `POST /api/v1/tasks/{project}/{task}/views/validate` body `{text}` → `{ok, issues, view?}` (`view` resolved: `from:` preset panels with layouts first)
  - `POST /api/v1/tasks/{project}/{task}/views/query` body `{view?, name?, panel?}` → `{panels}`
  - Every `HypothexError` answer keeps `{error, type}`; `ViewValidationError` adds `issues`.

- [ ] **Step 1: Write the failing tests**

In `tests/api/test_app.py`, add to the imports:

```python
import yaml

from hypothex.core.views import get_view, load_preset
```

Add below `WS_URL`:

```python
VIEWS = "/api/v1/tasks/toy/toy-acc/views"
GOOD_VIEW = """\
title: acc only
panels:
  - type: leaderboard
    title: board
    data: {metrics: [accuracy]}
"""
# "acuracy" is one letter off; difflib.get_close_matches("acuracy", ["accuracy"]) ->
# ["accuracy"]. The bad name sits on line 5 (1-based) of the text.
BAD_VIEW = GOOD_VIEW.replace("[accuracy]", "[acuracy]")


def _scored(ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    evaluate_run(ctx, "r1")


def _view_path(toy_repo: Path, name: str) -> Path:
    return toy_repo.resolve() / ".hypothex" / "views" / "toy-acc" / f"{name}.yaml"
```

Append these tests at the end of the file:

```python
def test_view_list_put_get_delete(client: TestClient, ctx: Context, toy_repo: Path) -> None:
    _scored(ctx, toy_repo)
    listed = client.get(VIEWS).json()
    assert [(v["name"], v["origin"], v["kind"]) for v in listed] == [
        ("overview", "preset", "generic")
    ]
    put = client.put(f"{VIEWS}/acc", json={"text": GOOD_VIEW})
    assert put.status_code == 200
    info = put.json()["info"]
    path = _view_path(toy_repo, "acc")
    assert (info["name"], info["title"], info["origin"], info["path"]) == (
        "acc",
        "acc only",
        "file",
        str(path),
    )
    assert path.read_text() == GOOD_VIEW
    assert put.json()["view"]["panels"][0]["data"]["metrics"] == ["accuracy"]
    got = client.get(f"{VIEWS}/acc").json()
    assert got["text"] == GOOD_VIEW and got["info"]["name"] == "acc"
    assert "from_" not in got["view"]
    assert [v["name"] for v in client.get(VIEWS).json()] == ["overview", "acc"]
    assert client.delete(f"{VIEWS}/acc").json() == {"ok": True}
    assert not path.exists()
    assert [v["name"] for v in client.get(VIEWS).json()] == ["overview"]
    missing = client.get(f"{VIEWS}/acc")
    assert missing.status_code == 404 and missing.json()["type"] == "StoreError"


def test_put_invalid_view_is_400_with_issues_and_not_saved(
    client: TestClient, ctx: Context, toy_repo: Path
) -> None:
    _scored(ctx, toy_repo)
    resp = client.put(f"{VIEWS}/acc", json={"text": BAD_VIEW})
    assert resp.status_code == 400
    body = resp.json()
    assert body["type"] == "ViewValidationError" and "acc" in body["error"]
    assert (body["issues"][0]["line"], body["issues"][0]["suggestion"]) == (5, "accuracy")
    assert not _view_path(toy_repo, "acc").exists()
    for bad_name in ("overview", "Bad Name", "-x"):
        resp = client.put(f"{VIEWS}/{bad_name}", json={"text": GOOD_VIEW})
        assert resp.status_code == 400 and resp.json()["type"] == "ConfigError"
    assert client.delete(f"{VIEWS}/overview").status_code == 400
    assert client.put("/api/v1/tasks/toy/nope/views/x", json={"text": GOOD_VIEW}).status_code == 400


def test_put_view_is_idempotent_by_command_id(
    client: TestClient, ctx: Context, toy_repo: Path
) -> None:
    _scored(ctx, toy_repo)
    changed = GOOD_VIEW.replace("acc only", "changed")
    first = client.put(f"{VIEWS}/acc", json={"text": GOOD_VIEW, "command_id": "view-1"}).json()
    second = client.put(f"{VIEWS}/acc", json={"text": changed, "command_id": "view-1"}).json()
    assert second == first
    assert _view_path(toy_repo, "acc").read_text() == GOOD_VIEW
    third = client.put(f"{VIEWS}/acc", json={"text": changed, "command_id": "view-2"}).json()
    assert third["info"]["title"] == "changed"
    assert _view_path(toy_repo, "acc").read_text() == changed


def test_validate_view_endpoint(client: TestClient, ctx: Context, toy_repo: Path) -> None:
    _scored(ctx, toy_repo)
    ok = client.post(f"{VIEWS}/validate", json={"text": GOOD_VIEW}).json()
    assert ok["ok"] is True and ok["issues"] == [] and ok["view"]["title"] == "acc only"
    bad = client.post(f"{VIEWS}/validate", json={"text": BAD_VIEW}).json()
    assert bad["ok"] is False and bad["issues"][0]["suggestion"] == "accuracy"
    broken = client.post(f"{VIEWS}/validate", json={"text": "title: [unclosed\n"}).json()
    assert broken["ok"] is False and broken["issues"] != [] and "view" not in broken
    assert not _view_path(toy_repo, "acc").exists()


def test_validate_returns_the_resolved_view(
    client: TestClient, ctx: Context, toy_repo: Path
) -> None:
    _scored(ctx, toy_repo)
    # toy-acc is a generic task; `from: agent_eval` must still resolve the agent_eval preset
    text = (
        "title: mine\nfrom: agent_eval\n"
        "panels:\n  - type: markdown\n    title: Note\n    text: hi\n"
    )
    body = client.post(f"{VIEWS}/validate", json={"text": text}).json()
    assert body["ok"] is True and body["issues"] == []
    view = body["view"]
    preset = load_preset("agent_eval")
    assert [p["title"] for p in view["panels"]] == [p.title for p in preset.panels] + ["Note"]
    assert [p["layout"] for p in view["panels"][:-1]] == [
        p.layout.model_dump() for p in preset.panels
    ]
    assert view["title"] == "mine" and view["from"] is None  # resolved: `from` is applied


def test_inline_and_preset_views(client: TestClient, ctx: Context, toy_repo: Path) -> None:
    config_path = toy_repo / "hypothex.yaml"
    cfg = yaml.safe_load(config_path.read_text())
    inline = {"title": "Inline", "panels": [{"type": "markdown", "text": "hi"}]}
    cfg["tasks"]["toy-acc"]["views"] = {"inl": inline}
    config_path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    _scored(ctx, toy_repo)
    listed = client.get(VIEWS).json()
    assert [(v["name"], v["origin"]) for v in listed] == [("overview", "preset"), ("inl", "inline")]
    assert yaml.safe_load(client.get(f"{VIEWS}/inl").json()["text"]) == inline
    assert client.delete(f"{VIEWS}/inl").status_code == 400
    preset = client.get(f"{VIEWS}/overview").json()
    expected = load_preset("generic")
    assert yaml.safe_load(preset["text"])["title"] == expected.title
    assert [p["type"] for p in preset["view"]["panels"]] == [p.type for p in expected.panels]


def test_query_views(client: TestClient, ctx: Context, toy_repo: Path) -> None:
    _scored(ctx, toy_repo)
    config = ctx.register_project(toy_repo).config
    preset = get_view(toy_repo.resolve(), config, "toy-acc", "overview")
    by_name = client.post(f"{VIEWS}/query", json={"name": "overview"}).json()["panels"]
    assert [(p["type"], p["title"]) for p in by_name] == [(p.type, p.title) for p in preset.panels]
    default = client.post(f"{VIEWS}/query", json={}).json()["panels"]
    assert [p["type"] for p in default] == [p.type for p in preset.panels]
    one = client.post(f"{VIEWS}/query", json={"panel": {"type": "markdown", "text": "hi"}})
    (panel,) = one.json()["panels"]
    assert (panel["type"], panel["rows"], panel["meta"]["text"]) == ("markdown", [], "hi")
    view = yaml.safe_load(GOOD_VIEW)
    rows = client.post(f"{VIEWS}/query", json={"view": view}).json()["panels"][0]["rows"]
    assert [r["run_ids"] for r in rows] == [["r1"]]
    assert client.post(f"{VIEWS}/query", json={"name": "nope"}).status_code == 404
    bad_panel = client.post(f"{VIEWS}/query", json={"panel": {"type": "pie"}})
    assert bad_panel.status_code == 422


def test_view_anchors_and_huge_specs_are_issues_never_500(
    client: TestClient, ctx: Context, toy_repo: Path
) -> None:
    _scored(ctx, toy_repo)
    # regression: this spec refers to itself; validating it raised RecursionError (a 500)
    looped = (
        "title: loop\npanels:\n  - type: vega_lite\n    data: {source: runs}\n"
        "    spec: &s {mark: point, layer: [*s]}\n"
    )
    anchors = {
        "line": 5,
        "path": "",
        "message": "YAML anchors and aliases are not allowed",
        "suggestion": None,
    }
    put = client.put(f"{VIEWS}/loop", json={"text": looped})
    assert put.status_code == 400
    assert put.json()["type"] == "ViewValidationError" and put.json()["issues"] == [anchors]
    checked = client.post(f"{VIEWS}/validate", json={"text": looped})
    assert checked.status_code == 200 and checked.json() == {"ok": False, "issues": [anchors]}
    # regression: 600 nested lists (no alias) raised RecursionError inside yaml.compose
    deep = looped.replace(
        "&s {mark: point, layer: [*s]}", "{mark: point, x: " + "[" * 600 + "]" * 600 + "}"
    )
    too_deep = {
        "line": 5,
        "path": "",
        "message": "YAML nested too deeply (over 64 levels)",
        "suggestion": None,
    }
    put = client.put(f"{VIEWS}/loop", json={"text": deep})
    assert put.status_code == 400 and put.json()["type"] == "ViewValidationError"
    assert put.json()["issues"] == [too_deep]
    checked = client.post(f"{VIEWS}/validate", json={"text": deep})
    assert checked.status_code == 200 and checked.json() == {"ok": False, "issues": [too_deep]}
    assert not _view_path(toy_repo, "loop").exists()


def test_inline_view_with_anchors_is_a_config_error_not_500(
    client: TestClient, ctx: Context, toy_repo: Path
) -> None:
    _scored(ctx, toy_repo)
    config_path = toy_repo / "hypothex.yaml"
    cfg = yaml.safe_load(config_path.read_text())
    spec: dict = {"mark": "point"}
    spec["layer"] = [spec]  # safe_dump writes the loop as &id001 ... *id001
    cfg["tasks"]["toy-acc"]["views"] = {
        "loop": {"title": "loop", "panels": [{"type": "vega_lite", "spec": spec}]}
    }
    text = yaml.safe_dump(cfg, sort_keys=False)
    config_path.write_text(text)
    line = next(i for i, row in enumerate(text.splitlines(), 1) if "&id001" in row)
    resp = client.get(f"{VIEWS}/loop")
    assert resp.status_code == 400 and resp.json()["type"] == "ConfigError"
    assert (
        f"YAML anchors and aliases are not allowed in views (line {line})" in resp.json()["error"]
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/api/test_app.py -v -k "view"`
Expected: FAIL. The GET/PUT/POST view calls answer 404 or 405 because no view routes
exist (for example `assert 404 == 200` in `test_view_list_put_get_delete`).

- [ ] **Step 3: Add the routes**

In `src/hypothex/api/app.py`, replace the import line
`from hypothex.mcp.server import build_server` with:

```python
from hypothex.core.views import PanelSpec, ViewSpec
from hypothex.mcp.server import (
    ViewValidationError,
    build_server,
    list_task_views,
    put_view,
    query_task_view,
    remove_view,
    validate_view,
    view_document,
)
```

Add these body models after `class NoteBody`:

```python
class ViewTextBody(BaseModel):
    """Body of ``POST /api/v1/tasks/{project}/{task}/views/validate``."""

    text: str


class ViewPutBody(ActionBody):
    """Body of ``PUT /api/v1/tasks/{project}/{task}/views/{name}``."""

    text: str


class ViewQueryBody(BaseModel):
    """Body of ``POST .../views/query``: one panel, an unsaved view, or a saved view's name."""

    view: ViewSpec | None = None
    name: str | None = None
    panel: PanelSpec | None = None
```

Replace the `hypothex_error` handler inside `create_app` with:

```python
    @app.exception_handler(HypothexError)
    async def hypothex_error(_: Request, exc: HypothexError) -> JSONResponse:
        status = 404 if isinstance(exc, StoreError) else 400
        content: dict[str, Any] = {"error": str(exc), "type": type(exc).__name__}
        if isinstance(exc, ViewValidationError):
            content["issues"] = to_jsonable(exc.issues)
        return JSONResponse(status_code=status, content=content)
```

Insert this block directly before the line `# runs ---...` inside `create_app`
(after `task_reeval`). The `validate` and `query` routes come before `{name}` so the
path reads naturally; they use POST, which `{name}` never does.

```python
    # views -------------------------------------------------------------------------
    @app.get("/api/v1/tasks/{project}/{task}/views")
    def views(project: str, task: str) -> list[dict[str, Any]]:
        return to_jsonable(list_task_views(ctx, task, project))

    @app.post("/api/v1/tasks/{project}/{task}/views/validate")
    def views_validate(project: str, task: str, body: ViewTextBody) -> dict[str, Any]:
        return validate_view(ctx, task, body.text, project)

    @app.post("/api/v1/tasks/{project}/{task}/views/query")
    def views_query(project: str, task: str, body: ViewQueryBody) -> dict[str, Any]:
        return query_task_view(
            ctx, task, project=project, name=body.name, view=body.view, panel=body.panel
        )

    @app.get("/api/v1/tasks/{project}/{task}/views/{name}")
    def view_get(project: str, task: str, name: str) -> dict[str, Any]:
        return view_document(ctx, task, name, project)

    @app.put("/api/v1/tasks/{project}/{task}/views/{name}")
    def view_put(project: str, task: str, name: str, body: ViewPutBody) -> dict[str, Any]:
        return once(body, lambda: put_view(ctx, task, name, body.text, project))

    @app.delete("/api/v1/tasks/{project}/{task}/views/{name}")
    def view_delete(project: str, task: str, name: str) -> dict[str, Any]:
        return remove_view(ctx, task, name, project)
```

`once()` releases the `command_id` claim when `put_view` raises, so a corrected retry
with the same id is accepted; a repeat after success returns the stored first result.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/api/test_app.py -v`
Expected: PASS (all old tests plus the 9 new view tests).

- [ ] **Step 5: Lint, format, type-check**

Run: `uv run ruff format src/hypothex/api/app.py tests/api/test_app.py && uv run ruff check src/hypothex/api/app.py tests/api/test_app.py && uv run ty check src`
Expected: `All checks passed!` and no ty errors.

- [ ] **Step 6: Commit**

```bash
git add src/hypothex/api/app.py tests/api/test_app.py
git commit -m "feat(api): add view CRUD, validate, and query routes"
```

---

### Task 32: HTTP overview, traces, and task kind routes

**Files:**
- Modify: `src/hypothex/api/app.py`
- Test: `tests/api/test_app.py`, `tests/test_demo.py` (two import lines; one test appended)

**Interfaces:**
- Consumes: `hypothex.core.overview.build_overview(ctx, since=None) -> OverviewSummary`;
  `RunStore.list_traces(project, run_id)` (Task 6; already returns
  `[{example_id, turns, failed}]` sorted by `example_id`); `hypothex.core.panels.query_panel`;
  `PanelSpec`, `PanelData` (contract 1.4); `hypothex.sdk.Run.log_trace` (tests only);
  `TaskSpec.kind`.
- Produces (contract section 2):
  - `GET /api/v1/overview?since=<ISO>` → `OverviewSummary`; a naive `since` is UTC.
  - `GET /api/v1/runs/{id}/traces` → `[{example_id, turns, failed}]` sorted by `example_id`.
  - `GET /api/v1/runs/{id}/traces/{example_id}` → `PanelResult` of type `trace`; unknown example 404. The route uses `{example_id:path}` so ids with `/` (`HumanEval/0`) work raw or `%2F`-encoded.
  - `GET /api/v1/tasks/{project}/{task}/kind` → `{kind, run_view: [PanelSpec]}`.
  - Private `_run_view(kind: str) -> list[PanelSpec]` (run-detail panels per spec 8.4):
    generic `[curves "metrics"]`; training `[curves "curves"]`; agent_eval and
    agent_iteration `[trace "steps", grid "same item across configs", table "tokens per turn" (source traces)]`;
    system_bench `[curves "over time", distribution "latency" (log, `data.metrics: [latency_ms]`, the samples `hx demo` writes)]`.
    Every non-trace panel queries without `meta.error` on the demo when scoped to one run the way the UI does (`data.filter.run_id`).

- [ ] **Step 1: Write the failing tests**

In `tests/api/test_app.py`, add to the imports:

```python
from hypothex.sdk import Run
```

Append:

```python
def test_overview_route(client: TestClient, ctx: Context, toy_repo: Path) -> None:
    _scored(ctx, toy_repo)
    body = client.get("/api/v1/overview").json()
    assert [t["run_id"] for t in body["timeline"]] == ["r1"]
    assert body["headline"].startswith("Idle")
    assert ("toy", "toy-acc") in {(p["project"], p["task"]) for p in body["projects"]}
    # a naive timestamp is read as UTC instead of failing an aware/naive comparison
    later = client.get("/api/v1/overview", params={"since": "2999-01-01T00:00:00"})
    assert later.status_code == 200 and later.json()["timeline"] == []
    earlier = client.get("/api/v1/overview", params={"since": "2000-01-01T00:00:00+00:00"})
    assert [t["run_id"] for t in earlier.json()["timeline"]] == ["r1"]
    assert client.get("/api/v1/overview", params={"since": "yesterday"}).status_code == 422


def test_run_traces(client: TestClient, ctx: Context, toy_repo: Path) -> None:
    rec = seed_finished_run(ctx, toy_repo, "r1")
    run = Run(ctx.run_dir(rec), "r1", rec.project)
    step = {
        "tool": "bash",
        "args": {"cmd": "ls"},
        "result": "ok",
        "tokens_in": 10,
        "tokens_out": 5,
        "seconds": 0.5,
    }
    run.log_trace("ex-2", [{"turn": 1, **step}, {"turn": 2, **step, "error": "boom"}])
    run.log_trace("ex-1", [{"turn": 1, **step}, {"turn": 2, **step}, {"turn": 3, **step}])
    assert client.get("/api/v1/runs/r1/traces").json() == [
        {"example_id": "ex-1", "turns": 3, "failed": False},
        {"example_id": "ex-2", "turns": 2, "failed": True},
    ]
    trace = client.get("/api/v1/runs/r1/traces/ex-2").json()
    assert trace["type"] == "trace"
    assert [(r["turn"], r["tool"]) for r in trace["rows"]] == [(1, "bash"), (2, "bash")]
    assert (trace["meta"]["run_id"], trace["meta"]["example_id"]) == ("r1", "ex-2")
    assert trace["meta"]["failed_turn"] == 2
    unknown = client.get("/api/v1/runs/r1/traces/ex-9")
    assert unknown.status_code == 404 and "ex-9" in unknown.json()["error"]
    assert client.get("/api/v1/runs/nope/traces").status_code == 404


def test_trace_ids_with_slashes(client: TestClient, ctx: Context, toy_repo: Path) -> None:
    rec = seed_finished_run(ctx, toy_repo, "r1")
    run = Run(ctx.run_dir(rec), "r1", rec.project)
    run.log_trace("HumanEval/0", [{"tool": "bash", "error": "boom"}])
    assert client.get("/api/v1/runs/r1/traces").json() == [
        {"example_id": "HumanEval/0", "turns": 1, "failed": True}
    ]
    for path in ("HumanEval/0", "HumanEval%2F0"):
        resp = client.get(f"/api/v1/runs/r1/traces/{path}")
        assert resp.status_code == 200, path
        assert resp.json()["meta"]["example_id"] == "HumanEval/0"
        assert resp.json()["meta"]["failed_turn"] == 1


def test_task_kind_and_run_view(client: TestClient, ctx: Context, toy_repo: Path) -> None:
    ctx.register_project(toy_repo)
    generic = client.get("/api/v1/tasks/toy/toy-acc/kind").json()
    assert generic["kind"] == "generic"
    assert [(p["type"], p["title"]) for p in generic["run_view"]] == [("curves", "metrics")]
    config_path = toy_repo / "hypothex.yaml"
    cfg = yaml.safe_load(config_path.read_text())
    cfg["tasks"]["toy-acc"]["kind"] = "agent_eval"
    config_path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    agent = client.get("/api/v1/tasks/toy/toy-acc/kind").json()
    assert agent["kind"] == "agent_eval"
    assert [p["type"] for p in agent["run_view"]] == ["trace", "grid", "table"]
    assert agent["run_view"][2]["data"]["source"] == "traces"
    assert client.get("/api/v1/tasks/toy/nope/kind").status_code == 400
```

In `tests/test_demo.py`, replace

```python
from hypothex.core import queries as q
```

with

```python
from hypothex.api.app import _run_view
from hypothex.core import queries as q
```

and replace

```python
from hypothex.core.views import get_view
```

with

```python
from hypothex.core.views import ViewSpec, get_view
```

Then append to the end of `tests/test_demo.py` (two blank lines before it):

```python
def test_every_kind_run_view_queries_cleanly(dctx: Context) -> None:
    for kind, ref in REFS.items():
        entry, task = q.resolve_task(dctx, ref)
        finished = [
            r
            for r in _runs(dctx, entry.project)
            if r.status == RunStatus.FINISHED and not r.archived
        ]
        run_id = finished[-1].run_id
        # scoped to one run the way the UI's scopeToRun does; traces have their own section
        panels = [
            p.model_copy(update={"data": p.data.model_copy(update={"filter": {"run_id": run_id}})})
            for p in _run_view(kind)
            if p.type != "trace"
        ]
        results = query_view(dctx, entry.project, task, ViewSpec(title="run", panels=panels))
        for result in results:
            assert "error" not in result.meta, (kind, result.title, result.meta.get("error"))
        if kind == "system_bench":
            (latency,) = [r for r in results if r.type == "distribution"]
            assert [row["n"] for row in latency.rows] == [5000]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/api/test_app.py -v -k "overview_route or traces or kind"`
Expected: FAIL with 404 responses (`KeyError: 'timeline'` in `test_overview_route`,
`assert {'detail': 'Not Found'} == [...]` in `test_run_traces` and
`test_trace_ids_with_slashes`).

Run: `uv run pytest tests/test_demo.py -v -k run_view`
Expected: FAIL at collection with `ImportError: cannot import name '_run_view' from 'hypothex.api.app'`.

- [ ] **Step 3: Add the routes**

In `src/hypothex/api/app.py`, add to the imports (keep them sorted; ruff fixes order):

```python
from datetime import UTC, datetime

from hypothex.core.overview import build_overview
from hypothex.core.panels import query_panel
from hypothex.core.views import PanelData, PanelSpec, ViewSpec
```

(The last line replaces the existing `from hypothex.core.views import PanelSpec, ViewSpec`
line from Task 31.)

Add this module-level helper after `_repair_loop`:

```python
def _run_view(kind: str) -> list[PanelSpec]:
    """
    Run-detail panels for a task kind (spec section 8.4); the UI fills in the run.

    Parameters
    ----------
    kind : str
        Task kind.

    Returns
    -------
    list of PanelSpec
        Fresh panel specs, in display order.
    """
    if kind == "training":
        return [PanelSpec(type="curves", title="curves", data=PanelData(step_metric="step"))]
    if kind in ("agent_eval", "agent_iteration"):
        return [
            PanelSpec(type="trace", title="steps"),
            PanelSpec(type="grid", title="same item across configs"),
            PanelSpec(
                type="table",
                title="tokens per turn",
                data=PanelData(
                    source="traces", fields=["example_id", "turn", "tokens_in", "tokens_out"]
                ),
            ),
        ]
    if kind == "system_bench":
        return [
            PanelSpec(type="curves", title="over time"),
            PanelSpec(
                type="distribution",
                title="latency",
                scale="log",
                data=PanelData(metrics=["latency_ms"]),
            ),
        ]
    return [PanelSpec(type="curves", title="metrics")]
```

Inside `create_app`, insert after the `# environment` route (`environment()`):

```python
    # overview ----------------------------------------------------------------------
    @app.get("/api/v1/overview")
    def overview(since: datetime | None = None) -> dict[str, Any]:
        if since is not None and since.tzinfo is None:
            since = since.replace(tzinfo=UTC)
        return to_jsonable(build_overview(ctx, since))
```

Insert after `task_reeval` (before the `# views` block from Task 31):

```python
    @app.get("/api/v1/tasks/{project}/{task}/kind")
    def task_kind(project: str, task: str) -> dict[str, Any]:
        entry, name = q.resolve_task(ctx, task, project)
        kind = entry.config.tasks[name].kind
        return {"kind": kind, "run_view": to_jsonable(_run_view(kind))}
```

Insert after `run_metrics`:

```python
    @app.get("/api/v1/runs/{run_id}/traces")
    def run_traces(run_id: str) -> list[dict[str, Any]]:
        record = ctx.find_record(run_id)
        return ctx.store.list_traces(record.project, record.run_id)

    # `:path` keeps example ids such as "HumanEval/0" in one parameter.
    @app.get("/api/v1/runs/{run_id}/traces/{example_id:path}")
    def run_trace(run_id: str, example_id: str) -> dict[str, Any]:
        record = ctx.find_record(run_id)
        known = {t["example_id"] for t in ctx.store.list_traces(record.project, record.run_id)}
        if example_id not in known:
            raise StoreError(f"run {run_id} has no trace for example {example_id!r}")
        panel = PanelSpec(
            type="trace",
            title=example_id,
            data=PanelData(run_id=run_id, example_id=example_id),
        )
        return to_jsonable(query_panel(ctx, record.project, record.task or "", panel))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/api/test_app.py -v`
Expected: PASS (all tests, including the 4 new ones).

Run: `uv run pytest tests/test_demo.py -v`
Expected: `14 passed`.

- [ ] **Step 5: Lint, format, type-check**

Run: `uv run ruff format src/hypothex/api/app.py tests/api/test_app.py tests/test_demo.py && uv run ruff check src/hypothex/api/app.py tests/api/test_app.py tests/test_demo.py && uv run ty check src`
Expected: `All checks passed!` and no ty errors.

- [ ] **Step 6: Commit**

```bash
git add src/hypothex/api/app.py tests/api/test_app.py tests/test_demo.py
git commit -m "feat(api): add overview, run traces, and task kind routes"
```

---

### Task 33: Serve the built UI with SPA fallback; ship `ui_dist` in the wheel

**Files:**
- Modify: `src/hypothex/api/app.py`
- Modify: `pyproject.toml`
- Modify: `.gitignore` (append `src/hypothex/ui_dist/` unless already there)
- Modify: `docs/cli.rst` (the `hx serve` paragraph)
- Test: `tests/api/test_app.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `create_app(home=None, *, background_repair=True, host=None, ui_dir: Path | None = None) -> FastAPI`
    (`ui_dir` defaults to `UI_DIST` = `src/hypothex/ui_dist`; tests pass a temp dir).
  - `class SpaStaticFiles(StaticFiles)`: unknown paths return `index.html` except those
    whose first segment is in `NO_UI_FALLBACK = frozenset({"api", "mcp", ".well-known", "assets"})`.
  - Wheel contains `hypothex/ui_dist/**` when the folder exists; the build still
    succeeds when it does not.
  - `src/hypothex/ui_dist/` is git-ignored (Global Constraints). The backend adds the line
    itself so it does not depend on frontend Task 1; the append is idempotent, so frontend
    Task 1 appending it again only leaves a harmless duplicate line.

- [ ] **Step 1: Write the failing tests**

Append to `tests/api/test_app.py`:

```python
INDEX_HTML = "<!doctype html><div id=root></div>"


@pytest.fixture
def ui_dir(tmp_path: Path) -> Path:
    d = tmp_path / "ui_dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text(INDEX_HTML)
    (d / "assets" / "app.js").write_text("console.log(1)")
    return d


def test_serves_ui_with_spa_fallback(home: Path, ui_dir: Path) -> None:
    app = create_app(home, background_repair=False, ui_dir=ui_dir)
    with TestClient(app, base_url="http://127.0.0.1:7777") as c:
        assert c.get("/").text == INDEX_HTML
        for route in ("/t/toy/toy-acc?view=acc", "/r/20260927-120000-toy-acc-ab12", "/x/a/b"):
            resp = c.get(route)
            assert resp.status_code == 200 and resp.text == INDEX_HTML, route
        assert c.get("/assets/app.js").text == "console.log(1)"
        assert c.get("/assets/missing.js").status_code == 404
        api = c.get("/api/v1/nope")
        assert api.status_code == 404
        assert api.headers["content-type"].startswith("application/json")
        assert c.get("/api/v1/runs").json() == []


def test_no_ui_build_means_api_only(home: Path, tmp_path: Path) -> None:
    app = create_app(home, background_repair=False, ui_dir=tmp_path / "missing")
    with TestClient(app, base_url="http://127.0.0.1:7777") as c:
        assert c.get("/").status_code == 404
        assert c.get("/api/v1/runs").json() == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/api/test_app.py -v -k "ui"`
Expected: FAIL with `TypeError: create_app() got an unexpected keyword argument 'ui_dir'`.

- [ ] **Step 3: Implement SPA serving**

In `src/hypothex/api/app.py`, add to the imports:

```python
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.types import Scope
```

Below `UI_DIST = ...`, add:

```python
NO_UI_FALLBACK = frozenset({"api", "mcp", ".well-known", "assets"})


class SpaStaticFiles(StaticFiles):
    """
    Serve the built UI; unknown client-side routes get ``index.html``.

    The UI routes (``/t/...``, ``/r/...``, ``/x/...``) exist only in the browser, so a
    reload must still load the app. Paths under ``api``, ``mcp``, ``.well-known``, and
    ``assets`` keep their 404, so a missing API route stays a JSON error and a missing
    script is not answered with HTML.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        """
        Return the file at ``path``, or ``index.html`` for unknown UI routes.

        Parameters
        ----------
        path : str
            Path relative to the UI folder.
        scope : Scope
            ASGI scope.

        Returns
        -------
        Response
        """
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            parts = Path(path).parts
            if exc.status_code != 404 or (parts and parts[0] in NO_UI_FALLBACK):
                raise
            return await super().get_response("index.html", scope)
```

Change the `create_app` signature and docstring to:

```python
def create_app(
    home: Path | None = None,
    *,
    background_repair: bool = True,
    host: str | None = None,
    ui_dir: Path | None = None,
) -> FastAPI:
    """
    Build the FastAPI application.

    Only local requests are served: the ``Host`` header must name a loopback
    address (or ``host``), else the answer is ``400``; a state-changing request
    or WebSocket handshake with a foreign ``Origin`` is rejected with ``403``.
    This blocks DNS-rebinding and cross-site attacks from a browser page.

    When ``ui_dir`` holds ``index.html`` the UI is served at ``/``; unknown
    non-API paths return ``index.html`` so browser routes survive a reload.

    Parameters
    ----------
    home : Path, optional
        Hypothex home; defaults to ``$HYPOTHEX_HOME`` or ``~/.hypothex``.
    background_repair : bool
        Mark orphaned runs lost every 30 s (disable in tests).
    host : str, optional
        The address the server binds to; also accepted as ``Host`` unless it is
        a wildcard such as ``0.0.0.0``.
    ui_dir : Path, optional
        Built UI folder; defaults to the packaged ``hypothex/ui_dist``.

    Returns
    -------
    FastAPI
        The application; consumers use only this API.
    """
```

Replace the final UI block of `create_app`:

```python
    if (UI_DIST / "index.html").is_file():
        app.mount("/", StaticFiles(directory=UI_DIST, html=True), name="ui")
    return app
```

with:

```python
    ui = ui_dir or UI_DIST
    if (ui / "index.html").is_file():
        app.mount("/", SpaStaticFiles(directory=ui, html=True), name="ui")
    return app
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/api/test_app.py tests/mcp/test_server.py -v`
Expected: PASS (all tests; `test_mcp_is_served_over_http` still passes because `/mcp`
is mounted before `/`).

- [ ] **Step 5: Ship `ui_dist` in the wheel only when present**

Git-ignore the build output (once, even if frontend Task 1 already added it):

```bash
cd "$(git rev-parse --show-toplevel)"
grep -qxF 'src/hypothex/ui_dist/' .gitignore || echo 'src/hypothex/ui_dist/' >> .gitignore
grep -cxF 'src/hypothex/ui_dist/' .gitignore
```

Expected: `1`.

In `pyproject.toml`, change the wheel target section to:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/hypothex"]
# The built UI (bun run build -> src/hypothex/ui_dist) is git-ignored. `artifacts`
# includes it when present and is a no-op when absent; `force-include` would fail
# the build ("Forced include not found") on a checkout without a UI build.
artifacts = ["src/hypothex/ui_dist/**"]
```

In `docs/cli.rst`, replace the paragraph under `hx serve`
(`Serve the HTTP/WebSocket API (and the UI once built) on ``127.0.0.1:7777``.`) with:

```rst
Serve the HTTP/WebSocket API on ``127.0.0.1:7777``, and the UI at
``http://127.0.0.1:7777/`` when the package contains a UI build
(``src/hypothex/ui_dist``; ``cd ui && bun run build`` makes one).
```

- [ ] **Step 6: Verify the wheel both ways**

Run from the checkout you are working in (a worktree when executed by subagents; the
`git rev-parse` line makes sure the build never touches another checkout). It only creates and
removes `ui_dist` if it did not exist before:

```bash
cd "$(git rev-parse --show-toplevel)"
test ! -e src/hypothex/ui_dist && mkdir -p src/hypothex/ui_dist/assets \
  && echo '<!doctype html>' > src/hypothex/ui_dist/index.html \
  && echo 'x' > src/hypothex/ui_dist/assets/app.js && echo CREATED
git check-ignore src/hypothex/ui_dist/index.html
rm -rf /tmp/hx-wheel && uv build --wheel -o /tmp/hx-wheel 2>&1 | tail -1
unzip -l /tmp/hx-wheel/*.whl | grep ui_dist
```

Expected: `CREATED`, `src/hypothex/ui_dist/index.html` (git ignores the build output),
`Successfully built /tmp/hx-wheel/hypothex-0.1.0.dev0-py3-none-any.whl`,
and two lines listing `hypothex/ui_dist/index.html` and `hypothex/ui_dist/assets/app.js`
(`artifacts` ships the files even though git ignores them).

Then (only if the previous command printed `CREATED`):

```bash
cd "$(git rev-parse --show-toplevel)"
rm -rf src/hypothex/ui_dist /tmp/hx-wheel
uv build --wheel -o /tmp/hx-wheel 2>&1 | tail -1
unzip -l /tmp/hx-wheel/*.whl | grep -c ui_dist
```

Expected: `Successfully built ...whl` and `0`.

- [ ] **Step 7: Lint, format, type-check, docs**

Run: `uv run ruff format src/hypothex/api/app.py tests/api/test_app.py && uv run ruff check . && uv run ty check src && uv run sphinx-build -b html docs docs/_build/html 2>&1 | grep -c "cli.rst.*WARNING"`
Expected: `All checks passed!`, no ty errors, and `0`.

- [ ] **Step 8: Commit**

```bash
git add src/hypothex/api/app.py tests/api/test_app.py pyproject.toml .gitignore docs/cli.rst
git commit -m "feat(api): serve the built UI with SPA fallback and ship ui_dist in the wheel"
```

---

### Task 34: `hx view ...` commands, hidden `hx demo`, and issues in CLI errors

**Files:**
- Modify: `src/hypothex/cli/main.py`
- Test: `tests/cli/test_cli.py`

**Interfaces:**
- Consumes: Task 30 helpers (`list_task_views`, `view_document`, `validate_view`,
  `put_view`, `remove_view`); `hypothex.demo.seed_demo(home, kinds) -> dict[str, str]` and
  `DEMO_TASKS`; `hypothex.core.gitinfo.git_state_label` (Task 4);
  `TaskKind` from `hypothex.core.config`; `default_home` from `hypothex.core.layout`;
  `load_preset` (tests only).
- Produces (contract section 3; `--json` on every command):
  - `hx view list <task> [-p P]` → `list[ViewInfo]`
  - `hx view show <task> <name> [-p P]` → `{info, text, view}` (text mode prints the YAML)
  - `hx view init <task> --from <kind> --name <name> [-p P]` → `{info, view}`; writes
    `title: <name>`, `from: <kind>`, `panels: []`; refuses an existing name
  - `hx view add <task> --file <path> [--name N] [-p P]` → `{info, view}` (name defaults to the file stem)
  - `hx view validate <task> <file> [-p P]` → `{ok, issues, view?}`; exit 1 when not ok
  - `hx view rm <task> <name> [-p P]` → `{ok: true}`
  - hidden `hx demo [--kinds k1,k2 | --kinds k1 --kinds k2]` → `{kind: "project/task"}`
  - `hx show` prints the git line with `git_state_label` (Task 4): `untracked files only (N)` instead of `(dirty)` when only untracked files exist (spec 8.8).
  - `hx demo` refuses a home that already holds non-demo projects (`ConfigError` naming them and `hx --home /tmp/hx-demo demo`), so demo runs never mix into real work.
  - `cli()` errors with `issues` (a `ViewValidationError`) print
    `{"error", "type", "issues"}` with `--json`, else one `  line N: path: message (did you mean X?)`
    line per issue on stderr.

- [ ] **Step 1: Write the failing tests**

In `tests/cli/test_cli.py`, add to the imports:

```python
import yaml

from hypothex.core.errors import ConfigError
from hypothex.core.views import load_preset
```

Add below `WRITE_PREDS`:

```python
GOOD_VIEW = """\
title: acc only
panels:
  - type: leaderboard
    title: board
    data: {metrics: [accuracy]}
"""
# "acuracy" is one letter off; difflib.get_close_matches("acuracy", ["accuracy"]) ->
# ["accuracy"]. The bad name sits on line 5 (1-based) of the text.
BAD_VIEW = GOOD_VIEW.replace("[accuracy]", "[acuracy]")
```

Append:

```python
def test_view_commands(in_repo: Path) -> None:
    _run()
    views_dir = in_repo.resolve() / ".hypothex" / "views" / "toy-acc"
    assert [(v["name"], v["origin"]) for v in hx("view", "list", "toy-acc")] == [
        ("overview", "preset")
    ]

    made = hx("view", "init", "toy-acc", "--from", "generic", "--name", "mine")
    assert made["info"]["path"] == str(views_dir / "mine.yaml")
    shown = hx("view", "show", "toy-acc", "mine")
    assert yaml.safe_load(shown["text"]) == {"title": "mine", "from": "generic", "panels": []}
    assert [p["type"] for p in shown["view"]["panels"]] == [
        p.type for p in load_preset("generic").panels
    ]
    with pytest.raises(ConfigError, match="exists"):
        runner.invoke(
            app,
            ["view", "init", "toy-acc", "--from", "generic", "--name", "mine"],
            catch_exceptions=False,
        )

    good = in_repo / "acc.yaml"
    good.write_text(GOOD_VIEW)
    assert hx("view", "validate", "toy-acc", str(good))["ok"] is True
    added = hx("view", "add", "toy-acc", "--file", str(good))
    assert (added["info"]["name"], added["info"]["title"]) == ("acc", "acc only")
    assert (views_dir / "acc.yaml").read_text() == GOOD_VIEW
    assert hx("view", "add", "toy-acc", "--file", str(good), "--name", "other")["info"][
        "path"
    ] == str(views_dir / "other.yaml")
    assert hx("view", "show", "toy-acc", "acc")["text"] == GOOD_VIEW
    assert [v["name"] for v in hx("view", "list", "toy-acc")] == ["overview", "acc", "mine", "other"]

    assert hx("view", "rm", "toy-acc", "acc") == {"ok": True}
    assert not (views_dir / "acc.yaml").exists()
    text = runner.invoke(app, ["view", "show", "toy-acc", "other"], catch_exceptions=False)
    assert text.exit_code == 0 and text.stdout == GOOD_VIEW


def test_view_validate_reports_issues_and_exits_1(in_repo: Path) -> None:
    _run()
    bad = in_repo / "bad.yaml"
    bad.write_text(BAD_VIEW)
    result = runner.invoke(app, ["view", "validate", "toy-acc", str(bad), "--json"])
    assert result.exit_code == 1
    report = json.loads(result.stdout)
    assert report["ok"] is False
    assert (report["issues"][0]["line"], report["issues"][0]["suggestion"]) == (5, "accuracy")
    human = runner.invoke(app, ["view", "validate", "toy-acc", str(bad)])
    assert human.exit_code == 1 and "line 5" in human.stdout and "did you mean accuracy" in human.stdout


def test_view_show_reports_an_inline_view_with_anchors_cleanly(
    in_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run()
    config_path = in_repo / "hypothex.yaml"
    cfg = yaml.safe_load(config_path.read_text())
    spec: dict = {"mark": "point"}
    spec["layer"] = [spec]  # safe_dump writes the loop as &id001 ... *id001
    cfg["tasks"]["toy-acc"]["views"] = {
        "loop": {"title": "loop", "panels": [{"type": "vega_lite", "spec": spec}]}
    }
    text = yaml.safe_dump(cfg, sort_keys=False)
    config_path.write_text(text)
    line = next(i for i, row in enumerate(text.splitlines(), 1) if "&id001" in row)
    monkeypatch.setattr(sys, "argv", ["hx", "view", "show", "toy-acc", "loop", "--json"])
    with pytest.raises(SystemExit) as exc:
        cli()
    assert exc.value.code == 1
    err = json.loads(capsys.readouterr().out)
    assert err["type"] == "ConfigError"
    assert f"YAML anchors and aliases are not allowed in views (line {line})" in err["error"]


def test_view_add_invalid_is_not_saved_and_reports_issues(
    in_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run()
    bad = in_repo / "bad.yaml"
    bad.write_text(BAD_VIEW)
    monkeypatch.setattr(sys, "argv", ["hx", "view", "add", "toy-acc", "--file", str(bad), "--json"])
    with pytest.raises(SystemExit) as exc:
        cli()
    assert exc.value.code == 1
    err = json.loads(capsys.readouterr().out)
    assert err["type"] == "ViewValidationError"
    assert err["issues"][0]["suggestion"] == "accuracy"
    assert not (in_repo / ".hypothex" / "views" / "toy-acc" / "bad.yaml").exists()
    with pytest.raises(ConfigError, match="invalid view"):
        runner.invoke(
            app,
            ["view", "init", "toy-acc", "--from", "nope", "--name", "x"],
            catch_exceptions=False,
        )
    assert not (in_repo / ".hypothex" / "views" / "toy-acc" / "x.yaml").exists()


def test_demo_is_hidden_and_seeds(home: Path) -> None:
    assert "demo" not in runner.invoke(app, ["--help"]).stdout
    out = hx("demo", "--kinds", "generic")
    assert isinstance(out, dict) and list(out) == ["generic"]
    refs = {f"{t['project']}/{t['name']}" for t in hx("tasks")}
    assert out["generic"] in refs
    with pytest.raises(ConfigError, match="nope"):
        runner.invoke(app, ["demo", "--kinds", "generic,nope"], catch_exceptions=False)


def test_demo_refuses_a_home_with_real_projects(in_repo: Path) -> None:
    _run()
    with pytest.raises(ConfigError, match=r"already has projects \(toy\)"):
        runner.invoke(app, ["demo", "--kinds", "generic"], catch_exceptions=False)
    assert [p["project"] for p in hx("projects")] == ["toy"]


def test_show_says_untracked_files_only(in_repo: Path) -> None:
    (in_repo / "scratch notes.txt").write_text("x\n")
    run_id = _run()["run_id"]
    shown = hx("show", run_id)
    assert shown["record"]["git"]["dirty"] is False
    assert shown["record"]["git"]["untracked_count"] >= 1
    text = runner.invoke(app, ["show", run_id], catch_exceptions=False).stdout
    git_line = next(line for line in text.splitlines() if line.startswith("git:"))
    assert "untracked files only (" in git_line and "dirty" not in git_line
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/cli/test_cli.py -v -k "view or demo or show_says"`
Expected: FAIL; typer reports `No such command 'view'` / `No such command 'demo'`
(exit code 2, so `hx()` asserts `2 == 0`); `test_demo_refuses_a_home_with_real_projects`
fails with `DID NOT RAISE`; `test_show_says_untracked_files_only` fails its last assert
(the phase 1a line prints only the commit when `dirty` is False).

- [ ] **Step 3: Implement the commands**

In `src/hypothex/cli/main.py`, change the typing import to:

```python
from typing import Annotated, Any, cast, get_args
```

Change the config and errors imports to:

```python
from hypothex.core.config import (
    CONFIG_FILENAME,
    TaskKind,
    find_repo_root,
    parse_metric_version,
    starter_config,
)
from hypothex.core.errors import ConfigError, HypothexError, RunError
```

Add `from hypothex.core.gitinfo import git_state_label` directly after the
`from hypothex.core.execution import ...` line, and `from hypothex.core.layout import default_home`
directly after `from hypothex.core.jsonutil import to_jsonable` (`show` and `demo` below use them):

```python
from hypothex.core.gitinfo import git_state_label
```

```python
from hypothex.core.layout import default_home
```

In `show`, replace

```python
    typer.echo(f"git:        {r.git.commit or '—'}{' (dirty)' if r.git.dirty else ''}")
```

with

```python
    typer.echo(f"git:        {r.git.commit or '—'}  {git_state_label(r.git)}")
```

After `app.add_typer(datasets_app, name="datasets")`, add:

```python
view_app = typer.Typer(no_args_is_help=True, help="Task views: dashboards written as YAML.")
app.add_typer(view_app, name="view")
```

After `_warn_seed`, add:

```python
def _issue_text(issue: dict[str, Any]) -> str:
    where = f"line {issue['line']}: " if issue.get("line") else ""
    hint = f" (did you mean {issue['suggestion']}?)" if issue.get("suggestion") else ""
    return f"{where}{issue['path']}: {issue['message']}{hint}"
```

Insert this section after the `note` command (before `# datasets & maintenance`):

```python
# views ----------------------------------------------------------------------------
# The helpers live in hypothex.mcp.server (shared with the API and MCP); importing it
# loads the MCP SDK, so each command imports it lazily to keep `hx` startup fast.
@view_app.command("list")
def view_list(task: str, project: ProjectOpt = None, as_json: JsonFlag = False) -> None:
    """List a task's views: preset `overview`, inline views, view files."""
    from hypothex.mcp.server import list_task_views

    views = list_task_views(_ctx(), task, project)
    if as_json:
        _print_json(views)
        return
    _table(
        ["name", "title", "origin", "path"], [[v.name, v.title, v.origin, v.path] for v in views]
    )


@view_app.command("show")
def view_show(task: str, name: str, project: ProjectOpt = None, as_json: JsonFlag = False) -> None:
    """Print a view's YAML."""
    from hypothex.mcp.server import view_document

    doc = view_document(_ctx(), task, name, project)
    if as_json:
        _print_json(doc)
    else:
        typer.echo(doc["text"], nl=not doc["text"].endswith("\n"))


@view_app.command("init")
def view_init(
    task: str,
    from_kind: Annotated[str, typer.Option("--from", help="Preset kind to start from.")],
    name: Annotated[str, typer.Option("--name", help="View name.")],
    project: ProjectOpt = None,
    as_json: JsonFlag = False,
) -> None:
    """Create a view file that starts from a kind's preset panels."""
    from hypothex.mcp.server import list_task_views, put_view

    c = _ctx()
    if name in {v.name for v in list_task_views(c, task, project)}:
        raise ConfigError(f"view {name!r} exists; edit it, or replace it with `hx view add`")
    text = yaml.safe_dump({"title": name, "from": from_kind, "panels": []}, sort_keys=False)
    out = put_view(c, task, name, text, project)
    _emit(out, as_json, f"wrote {out['info']['path']}")


@view_app.command("add")
def view_add(
    task: str,
    file: Annotated[
        Path, typer.Option("--file", exists=True, dir_okay=False, help="View YAML file.")
    ],
    name: Annotated[str | None, typer.Option("--name", help="View name (default: stem).")] = None,
    project: ProjectOpt = None,
    as_json: JsonFlag = False,
) -> None:
    """Validate a view file and save it under .hypothex/views/<task>/."""
    from hypothex.mcp.server import put_view

    out = put_view(_ctx(), task, name or file.stem, file.read_text(encoding="utf-8"), project)
    _emit(out, as_json, f"wrote {out['info']['path']}")


@view_app.command("validate")
def view_validate(
    task: str,
    file: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="View YAML file.")],
    project: ProjectOpt = None,
    as_json: JsonFlag = False,
) -> None:
    """Check a view file against the task's metrics and fields; save nothing."""
    from hypothex.mcp.server import validate_view

    report = validate_view(_ctx(), task, file.read_text(encoding="utf-8"), project)
    if as_json:
        _print_json(report)
    else:
        for issue in report["issues"]:
            typer.secho(f"{file}: {_issue_text(issue)}", fg="red")
        if report["ok"]:
            typer.secho("ok", fg="green")
    if not report["ok"]:
        raise typer.Exit(1)


@view_app.command("rm")
def view_rm(task: str, name: str, project: ProjectOpt = None, as_json: JsonFlag = False) -> None:
    """Delete a view file."""
    from hypothex.mcp.server import remove_view

    _emit(remove_view(_ctx(), task, name, project), as_json, f"removed {name}")
```

Insert after the `mcp` command (before `def cli()`):

```python
@app.command(hidden=True)
def demo(
    kinds: Annotated[
        list[str] | None,
        typer.Option("--kinds", help="Kinds to seed (repeat or comma-separate; default: all)."),
    ] = None,
    as_json: JsonFlag = False,
) -> None:
    """Seed demo projects and runs into an empty home (UI tests, docs screenshots)."""
    from hypothex.demo import DEMO_TASKS, seed_demo

    known = get_args(TaskKind)
    chosen = [k.strip() for item in kinds or [] for k in item.split(",") if k.strip()]
    unknown = sorted(set(chosen) - set(known))
    if unknown:
        raise ConfigError(f"unknown kind(s) {', '.join(unknown)}; choose from {', '.join(known)}")
    home = (_state.home or default_home()).expanduser().resolve()
    demo_projects = {project for project, _ in DEMO_TASKS.values()}
    theirs = sorted(
        e.project for e in _ctx().store.list_projects() if e.project not in demo_projects
    )
    if theirs:
        raise ConfigError(
            f"{home} already has projects ({', '.join(theirs)}); seed the demo into an "
            "empty home instead: hx --home /tmp/hx-demo demo"
        )
    made = seed_demo(home, cast("list[TaskKind]", chosen or list(known)))
    _emit(made, as_json, "\n".join(f"{kind}: {ref}" for kind, ref in made.items()))
```

Replace `cli()` with:

```python
def cli() -> None:
    """Console entry point: expected errors print cleanly (JSON with --json)."""
    try:
        app()
    except HypothexError as exc:
        issues = [to_jsonable(i) for i in getattr(exc, "issues", [])]
        if "--json" in sys.argv:
            payload: dict[str, Any] = {"error": str(exc), "type": type(exc).__name__}
            if issues:
                payload["issues"] = issues
            print(json.dumps(payload))
        else:
            print(f"error: {exc}", file=sys.stderr)
            for issue in issues:
                print(f"  {_issue_text(issue)}", file=sys.stderr)
        raise SystemExit(1) from None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/cli/test_cli.py tests/test_skill.py -v`
Expected: PASS (all old tests plus the 7 new ones; `test_every_hx_command_in_skill_exists`
still passes).

- [ ] **Step 5: Lint, format, type-check**

Run: `uv run ruff format src/hypothex/cli/main.py tests/cli/test_cli.py && uv run ruff check src/hypothex/cli/main.py tests/cli/test_cli.py && uv run ty check src`
Expected: `All checks passed!` and no ty errors.

- [ ] **Step 6: Commit**

```bash
git add src/hypothex/cli/main.py tests/cli/test_cli.py
git commit -m "feat(cli): add hx view commands and hidden hx demo"
```

---

### Task 35: Skill section and docs page for views

**Files:**
- Modify: `skills/hypothex/SKILL.md`
- Create: `docs/views.rst`
- Modify: `docs/index.rst`, `docs/cli.rst`
- Test: `tests/test_skill.py`

**Interfaces:**
- Consumes: Task 30 MCP tool names; Task 34 `hx view` subcommands.
- Produces: skill text that names only existing `hx view` subcommands and all four MCP
  view tools; a `Views` docs page in the toctree.

- [ ] **Step 1: Write the failing tests**

In `tests/test_skill.py`, replace the import block (everything above `SKILL = `) with:

```python
import re
import textwrap
from pathlib import Path

import typer

from hypothex.cli.main import app
from hypothex.core.views import validate_view_text
```

Append to `tests/test_skill.py`:

```python
def test_every_hx_view_subcommand_in_skill_exists() -> None:
    group = typer.main.get_command(app)
    view_group = group.commands["view"]  # ty: ignore[unresolved-attribute]
    known = set(view_group.commands)  # ty: ignore[unresolved-attribute]
    used = set(re.findall(r"\bhx view ([a-z]+)", SKILL.read_text()))
    assert used == {"list", "show", "init", "validate", "add"}
    assert used <= known, f"unknown view commands in SKILL.md: {used - known}"


def test_skill_names_mcp_view_tools() -> None:
    text = SKILL.read_text()
    for tool in ("list_views", "get_view", "add_view", "query_view"):
        assert f"`{tool}`" in text, tool
    assert ".hypothex/views/<task>/<name>.yaml" in text


def test_views_docs_page_is_in_toctree() -> None:
    docs = SKILL.parents[2] / "docs"
    assert "   views\n" in (docs / "index.rst").read_text()
    page = (docs / "views.rst").read_text()
    for command in ("hx view list", "hx view init", "hx view add", "hx view validate"):
        assert command in page, command


def test_views_docs_example_validates() -> None:
    # The page's own example must pass `hx view validate` for a task whose metric is solved.
    page = (SKILL.parents[2] / "docs" / "views.rst").read_text()
    example = page.split("Example\n-------\n", 1)[1]
    block = example.split(".. code-block:: yaml\n\n", 1)[1].split("\n\n", 1)[0]
    view, issues = validate_view_text(textwrap.dedent(block), {"solved"}, {})
    assert view is not None and view.title == "route quality"
    assert issues == []  # e.g. `x: cost` would report "unknown metric cost"
    scatter = next(p for p in view.panels if p.type == "scatter")
    assert (scatter.data.x, scatter.data.y) == ("usage.usd", "solved")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_skill.py -v`
Expected: FAIL: `assert set() == {...}` in the first new test, `AssertionError: list_views`
in the second, and `FileNotFoundError` / assertion in the third and fourth.

- [ ] **Step 3: Add the skill section**

In `skills/hypothex/SKILL.md`, insert before `## Where things are`:

```markdown
## Views (task dashboards)

A view is YAML: `title`, optional `from: <kind>` (start from a preset), optional
`runs:` filter, and `panels` (`stat_strip`, `leaderboard`, `curves`, `scatter`,
`distribution`, `grid`, `table`, `trace`, `markdown`, `vega_lite`). Files live in
`.hypothex/views/<task>/<name>.yaml` in the repo; commit them.

- See: `hx view list <task> --json`, `hx view show <task> <name> --json`.
- Start: `hx view init <task> --from <kind> --name <name> --json`.
- Check, then save: `hx view validate <task> view.yaml --json`, then
  `hx view add <task> --file view.yaml --json`. Fix every issue (`line`, `message`,
  `suggestion`) first; invalid views are never saved.
- MCP: `list_views`, `get_view`, `add_view` (returns `issues` on failure),
  `query_view` (panel rows).
```

- [ ] **Step 4: Add the docs page**

Create `docs/views.rst`:

```rst
Views
=====

A view is a dashboard for one task, written as YAML: a title, an optional run filter,
and a list of panels. Each task kind ships a preset view named ``overview``; you add
your own views next to your code. Panel data is computed by the server; the UI and
agents only read rows.

Task kinds
----------

Set a task's kind in ``hypothex.yaml``. The kind picks the preset view and the run
page layout; it never changes storage or evaluation.

.. code-block:: yaml

   tasks:
     route-eval:
       dataset: routes
       metrics: [solved]
       primary: solved
       kind: agent_eval      # generic | training | agent_eval | agent_iteration | system_bench

Where views live
----------------

- **Preset**: ``overview``, from the package, one per kind.
- **Inline**: ``views:`` under a task in ``hypothex.yaml``.
- **File**: ``<repo>/.hypothex/views/<task>/<name>.yaml``. Commit these with the code.
  A file wins over an inline view with the same name. The UI editor saves files.

View names use ``a-z``, ``0-9``, ``-``, and ``_``, and start with a letter or digit.
``overview`` is reserved.

Example
-------

.. code-block:: yaml

   title: route quality
   from: agent_eval             # optional: preset panels first
   runs: {status: [finished]}   # also: tags, created_by, since
   panels:
     - type: leaderboard
       title: Best config
       data: {metrics: [solved@v2]}
       noise: [seed, test_set]
       layout: {span: 8}
     - type: scatter
       title: Cost vs score
       data: {x: usage.usd, y: solved}   # usage.usd: the run's total cost
       pareto: {x: min, y: max}
       layout: {span: 4}
     - type: markdown
       text: "Test split only; seeds 1-3."

With ``from``, the preset's panels come first; a panel whose ``title`` matches a preset
panel replaces it, and other panels are appended.

Metric references use ``name@version/key`` (version and key are optional). The
aggregates ``/mean``, ``/median``, and ``/p95`` apply to samples and per-example values.
Run usage totals are ``usage.usd``, ``usage.seconds``, ``usage.tokens_in``,
``usage.tokens_out``, and ``usage.calls``; ``usage.usd/solved`` divides a run's total by the
examples it solved on the task's primary metric (cost per success). A logged history
metric is named in full (``val/top1``). ``version`` is the task's version ordering key: the
run param ``version_param`` names (``version`` by default), or the creation time of the
group's first run when that param is missing; it works as a scatter ``x``, as a
``runs`` table field, and in a ``runs`` ``data.filter`` (``filter: {version: p10}``), also
when ``fields`` does not list it. A ``grid`` panel's ``data.y`` is a per-example field (``partial``).

Panels
------

============== ==========================================================================
Type           Shows
============== ==========================================================================
stat_strip     A row of headline numbers.
leaderboard    Seed groups ranked by the primary metric, with seed and test-set noise.
curves         Metric history by step; seeds faint, mean bold, checkpoints and spikes.
scatter        One metric against another per group, with an optional Pareto front. A
               non-numeric ``params.``/``vars.`` x (e.g. ``v9``) is an ordinal axis in
               natural order; rows worse than the best earlier version by more than its
               95% CI are marked as regressions.
distribution   Sample distributions (ECDF) with p50, p95, p99; ``scale: log`` for latency.
               ``render: table`` draws the percentile table, with the change vs the task's
               ``baseline`` group and a 95% bootstrap CI over repeats.
grid           Items by groups; each cell is the fraction of seeds that solved the item.
table          Raw rows from a ``source`` restricted to ``fields``.
trace          The steps of one agent attempt (``data.run_id``, ``data.example_id``).
markdown       Static ``text``.
vega_lite      A Vega-Lite ``spec`` drawn over rows from a ``source``. Rows arrive inline
               only: ``url``, ``href``, ``embedOptions`` (at any depth) and ``image``
               marks are rejected.
============== ==========================================================================

Sources for ``table`` and ``vega_lite``: ``runs``, ``scores``, ``metrics``,
``predictions``, ``samples``, ``usage``, ``traces``. Every row has ``run_id``,
``group_id``, and ``seed``.

Validation
----------

A view is checked before it is saved: the schema, metric names (with a nearest-name
suggestion), sources, fields, and the Vega-Lite spec shape. Every issue has a line
number. An invalid view is never saved. YAML anchors and aliases (``&name``, ``*name``,
``<<: *name``) are not allowed, YAML may nest at most 64 levels (and hold at most 100,000
parser events), and a Vega-Lite spec may hold at most 10,000 values. Inline views in
``hypothex.yaml`` follow the same rule: an anchor or alias under ``tasks.<task>.views`` is a
config error; anchors elsewhere in the file are fine as long as they form no cycle.

.. code-block:: bash

   hx view validate route-eval view.yaml --json

.. code-block:: json

   {"ok": false, "issues": [{"line": 5, "path": "panels[0].data.metrics[0]",
     "message": "unknown metric slved", "suggestion": "solved@v2"}]}

Commands
--------

.. code-block:: bash

   hx view list TASK --json                          # overview, inline, files
   hx view show TASK NAME --json                     # info, YAML text, resolved view
   hx view init TASK --from agent_eval --name mine   # new file starting from a preset
   hx view validate TASK view.yaml --json            # check only; exit 1 if invalid
   hx view add TASK --file view.yaml --json          # check, then save as <stem>.yaml
   hx view rm TASK NAME --json                       # delete a view file

MCP tools: ``list_views``, ``get_view``, ``add_view`` (returns ``issues`` when invalid),
``query_view``.

HTTP (all under ``/api/v1/tasks/{project}/{task}``): ``GET views``,
``GET|PUT|DELETE views/{name}`` (``PUT`` body ``{text, command_id?}``; a repeated
``command_id`` returns the first result), ``POST views/validate`` (``{text}``; the
answer's ``view`` is resolved, so ``from:`` preset panels are included), and
``POST views/query`` (``{name}``, ``{view}``, or ``{panel}``).
```

In `docs/index.rst`, change the toctree to:

```rst
.. toctree::
   :maxdepth: 2

   quickstart
   project_file
   cli
   views
   sdk
   agents
   architecture
```

In `docs/cli.rst`, insert before the `Datasets` section:

```rst
Views
-----

.. code-block:: bash

   hx view list TASK --json
   hx view add TASK --file view.yaml --json

List a task's dashboards, or validate and save one. See :doc:`views` for the YAML
format and the other ``hx view`` commands.
```

- [ ] **Step 5: Run the tests and build the docs**

Run: `uv run pytest tests/test_skill.py -v`
Expected: PASS (6 tests).

Run: `uv run sphinx-build -b html docs docs/_build/html 2>&1 | grep -E "(views|cli|index)\.rst.*(WARNING|ERROR)" | wc -l`
Expected: `0`.

- [ ] **Step 6: Full suite and checks**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src && uv run pytest -q`
Expected: `All checks passed!`, all files formatted, no ty errors, and every test passes.

- [ ] **Step 7: Commit**

```bash
git add skills/hypothex/SKILL.md docs/views.rst docs/index.rst docs/cli.rst tests/test_skill.py
git commit -m "docs: add views page and skill section on views"
```

---

## Assembly notes

Inputs: part files B1–B7 (`.superpowers/plan-parts/`), the contract, and spec section 8. Tasks are renumbered in part order: B1.1–B1.5 → Tasks 1–5, B2 → 6–8, B3 → 9–14, B4.1–B4.3 → 15–17, B5.1 → 18, B4.4 → 19, B5.2–B5.5 → 20–23, B6 → 24–29, B7 → 30–35. All cross-references use the new numbers.

**Order change.** B4.4 (`view_context`) imports `sources.iter_rows`, which B5.1 creates. In part order its test fails with `ModuleNotFoundError`. It is Task 19, directly after Task 18.

**Duplication removed** (one copy kept, the others now call it):

- File-name sanitising: `store.safe_stem` (B2.1) kept. `sources.safe_name` and `sources.trace_path` (B5.1) removed; `panels._samples` (B5.4) reads `RunStore.read_samples`, keyed by the original series names.
- Trace parsing and summaries: `store.TraceStep`, `RunStore.list_traces`, `RunStore.read_trace` (B2.1) kept. B2.1 already named `list_traces` as the body of `GET /runs/{id}/traces`. Removed: `sources.trace_step` (B5.1), the file reads in `panels._trace_for` (B5.2), and `api._trace_summaries` (B7.3).
- Samples and usage parsing: `RunStore.read_samples`, `read_usage`, `sum_usage` (B2.1) kept. Removed: the file reads in `sources._samples` and `sources._usage` (B5.1), `panels._samples` and `panels._usage_values` (B5.4, B5.5), and `demo._usage_totals` (B6.2). Side effect: every reader now skips NaN, bool, and invalid rows the same way.
- Seed-group id: it was computed in `leaderboard._make_row` (B3.2), `sources.group_id_for` (B5.1), and `overview._group_id` (B6.1). There is now one public `leaderboard.group_id_for` (Task 10). `sources` re-exports it, so the Task 18 test still imports it from there.
- Group labels: there were three rules. `leaderboard.group_label` (B3.2) caps at 32 characters with `…`, `panels._own_label` (B5.3) had no cap and used the newest tag, and `overview._short_label` (B6.1) capped at 40 and used the first tag. Contract 1.7 defines one rule, and B3.2 asked the Overview to reuse `group_label`. Now every label comes from `group_label`. `_own_label` still picks the newest non-empty hypothesis (Task 21's curves test needs it), and `_short_label` is a thin wrapper.
- Per-example scores of the primary metric: `queries._primary_examples` (B3.6) and `panels._build_board` (B5.2) both read the files. Now there is one public `queries.primary_examples` (Task 14), and the panel engine calls it.
- View-name rule: it was in `config.VIEW_NAME_PATTERN` (B1.5, which said views should import it), `views.VIEW_NAME_PATTERN` (B4.3), and `mcp.server.VIEW_NAME` with `check_view_name` (B7.1). Now the pattern lives only in config. `views.check_view_name` (the old private `_check_name`, now public, Task 17) is the only name check, and `mcp.server.PRESET_VIEW` is `views.RESERVED_VIEW`. Name errors now use the views wording. Task 30's MCP test (`"preset view" in message`) and Task 31's API test (400, `ConfigError`) match it.
- The per-part review-focus lists are dropped. The tests they named stay in their tasks, and the plan-level Review Focus replaces the lists. The per-part design notes are kept once, at the top of each Part.

**Disagreements resolved:**

- `ProjectRow.task` is `str | None` in B6.1 (projects with no tasks) but `str` in B3.5's `ProjectLike` protocol. Contract 1.9 gives no type. Kept `str | None` and widened `ProjectLike.task` (Task 13), so `overview_headline(summary)` type-checks against `OverviewSummary`.
- `hx show` wording (spec 8.8): B1.4 left it to "the CLI/UI groups", but B7 never did it. It is now in Task 34 (Review Focus 4).
- Wheel packaging: contract section 4 says `force-include` "only when present". Task 33 uses hatch `artifacts` instead, because `force-include` fails the build when the folder is missing (B7 verified this). This keeps the binding part, "only when present". It is the one place this plan departs from the contract's wording.
- p-value format: contract 1.8 shows `p = 0.15` and `p < 0.001`. B3 also shows three decimals for 0.001 ≤ p < 0.01 (`p = 0.004`), so a value never reads `p = 0.00`. Kept, because it refines the contract examples and does not contradict them.
- `docs/views.rst` (B7.6) showed the issue message `unknown metric 'slved'`. B4.2's exact message is `unknown metric slved`, and its suggestion is the whole reference (`solved@v2`). The docs example now matches B4.2.

**Added for the Review Focus:**

- Task 10: the `math.isfinite` score filter and its test. The same filter line is kept in the `build_leaderboard` rewrites of Tasks 11 and 12.
- Task 11: the shared-examples test.
- Task 32: the `{example_id:path}` route and its test.
- Task 34: the `hx show` git wording, the `hx demo` guard for non-demo homes, and one test for each.

**Not re-run.** The part authors ran their own code blocks. The edits above were made during assembly. They were checked only for Python syntax, plus two behaviour checks in this repo's environment: FastAPI's router with `{example_id:path}` and `%2F`, and the 500 that a NaN in a JSON response causes. The edited tasks are 10–14, 17, 18, 20–25, 27, 30, 32, and 34. Run each task's test step as written. The expected counts are updated: Task 32 has 4 new tests in `tests/api/test_app.py` and 1 in `tests/test_demo.py` (`14 passed`), Task 34 has 6 new tests, and Task 29 `21 passed`. The counts of Tasks 1–23 are the review-round-2 counts at the end.

**Review round 1 (Codex review items 2–13, controller item C1, rulings R1–R3).**

- Item 2, Task 18: `iter_rows` projects from the merged row with the new public `sources.select_fields`, so listing `run_id`/`group_id`/`seed` keeps their values.
- Item 3, Task 16: a reference that is exactly a known metric name is valid before any `@`/`/` split (`val/top1`); a grid's `data.y` is checked against per-example fields (`unknown per-example field <f>`).
- Item 4, Task 20: `table`/`vega_lite` filter full rows, then project with `select_fields`.
- Item 5, Task 1: `examples_needed` scans every `n` (O(1) tail update per count change, exact confirmation), so it returns the true minimum: `(51, 49, 1000)` → 96,500, not 96,677; tests pin the scipy p-values and a full scan.
- Item 6, Task 12: `headlines.paired_gain_interval(gain, fixed, broken, n_shared)`; `build_leaderboard` counts the shared example ids (`_paired_gain`) and passes `gain_interval` to `task_headline`.
- Item 7, Task 22: the leaderboard's test interval is reused only when `y` is the primary at the board's metric version.
- Item 8, Tasks 15/16/20/22: the reference `version` (`views.VERSION_REF`) resolves `TaskSpec.version_param`, else the group's first-run creation time; the agent_iteration preset uses it for both scatters and the Changes table.
- Item 9 backend and R3, Task 22 and contract 1.6: scatter `meta.y_higher_is_better` and `meta.best_group`, sent whatever `pareto` says.
- Item 10 and R1, Tasks 6/7/19/22 and contract 1.10: `safe_stem` appends `-<sha1[:8]>` when it changes a name; traces and samples store the original id/name in every row; an empty trace writes a marker line; `read_samples` keys series by original name.
- Item 11 backend and C1, Tasks 16/20: `views.vega_spec_problems` rejects `url`/`href`/`embedOptions` at any depth and `image` marks, in validation and in the panel engine (a panel error for unvalidated views).
- Item 12, Tasks 6/7: `UsageRow.usd/seconds` and `TraceStep.seconds` use `allow_inf_nan=False`; the SDK rejects `inf`, the readers skip it.
- Item 13 and R2, Task 21 and contract 1.6: the zero-median exemption is gone (`[0, 3]` spikes).
- Non-blocking note, Task 21: checkpoints use the curves' `step_metric` x and are dropped without one.

Verification: Tasks 1–23 were applied to a scratch worktree of `phase-1b` at `f7e7fd0` by a script that follows each step's replace/insert/append instructions. Full suite `441 passed`; `ruff format --check`, `ruff check`, and `ty check src` clean; the doctests of `stats`, `store`, `headlines`, `leaderboard`, `views`, `sources`, and `panels` pass. Per-task counts after the fixes: Task 1 `32`, Task 2 `54`, Task 6 `15`, Task 7 `12`, Task 16 `40`, Task 17 `57`, Task 18 `12`, Task 19 `59`, Task 20 `17`, Task 21 `22`, Task 22 `37`, Task 23 `55` (panels + sources). Tasks 24–35 were not re-run; they use the changed code only through `log_trace`, `log_samples`, `list_traces`, and the presets, whose demo assertions are unchanged (all demo runs carry `params.version`).

**Review round 2 (three findings and the inline-view follow-up, rulings as given).**

- Stem collision, Tasks 6/7 and contract 1.10: `safe_stem("a/b") == safe_stem("a_b-3ec69c85")` before. `safe_stem` now also hashes a name that already ends in `-[0-9a-f]{8}` (`a_b-3ec69c85` → `a_b-3ec69c85-d64fa8bc`), so only an 8-hex-digit sha1 prefix collision can share a stem; the new `store.check_stem_owner` makes `log_trace` / `log_samples` raise `StoreError("id collision: ...")` and write nothing when the file stores a different original. The contract no longer claims that stems never collide. Tests: `test_safe_stem_hashes_names_that_already_look_hashed`, `test_check_stem_owner_rejects_a_different_original` (Task 6), `test_trace_and_sample_writers_refuse_a_file_of_another_id` (Task 7); `test_safe_stem_never_merges_distinct_names` gains the pair.
- Recursive view YAML, Tasks 16/31/35 and contract 1.4: `spec: &s {mark: point, layer: [*s]}` raised `RecursionError`. `validate_view_text` rejects the first anchor or alias (`YAML anchors and aliases are not allowed`, its line, from the `yaml.parse` events), and `vega_spec_problems` is bounded (64 levels, 10,000 values; `too deep` / `too large`), so an aliased spec in `hypothex.yaml` is a panel error. Tests: `test_yaml_anchors_and_aliases_are_rejected_with_their_line`, `test_vega_lite_spec_size_is_bounded` (Task 16), `test_view_anchors_and_huge_specs_are_issues_never_500` (Task 31: PUT 400 with issues, validate 200 `{ok: false, issues}`), doctest of `vega_spec_problems` (a self-referencing dict). Round 3 replaced the anchor check with the Task 5 guards (next items).
- Inline views with anchors, Tasks 5/30/31/34 and contract 1.3: `load_project_config` rejects any YAML anchor or alias under `tasks.<task>.views` (`ConfigError`: `YAML anchors and aliases are not allowed in views (line N)`, found by `scan_yaml`); anchors elsewhere in `hypothex.yaml` stay allowed. `refresh_project` keeps the last good config, so `mcp.server._find_view` re-loads `hypothex.yaml` before it answers "unknown view" and raises that `ConfigError` instead: `GET .../views/{name}` answers 400 and `hx view show` exits 1 with the error, never a 500. The `validate` route is unchanged (200, `{ok: false, issues}`). Task 34 also gains the two imports it used without adding (`git_state_label`, `default_home`). Tests: `test_inline_view_anchors_and_aliases_are_rejected_with_their_line`, `test_anchors_outside_views_stay_allowed` (Task 5), `test_inline_view_with_anchors_is_a_config_error_not_500` (Task 31), `test_view_show_reports_an_inline_view_with_anchors_cleanly` (Task 34).
- Round 3 (Codex), Tasks 5/16/31/34/35 and contracts 1.3/1.4: two holes remained. An alias used as a mapping key (`&vk views` elsewhere, `*vk:` under `tasks.t`) hid a cyclic inline view from the key-only check; 600 nested lists with no alias raised `RecursionError` inside `yaml.compose`. The targeted anchor helpers (`_views_anchor_line`, `_first_anchor_line`) are replaced by two general guards in `hypothex.core.config`, used by both `load_project_config` and `validate_view_text`: `scan_yaml` (a streaming pre-scan of the `yaml.parse` events before compose or load: depth > 64 → `YAML nested too deeply (over 64 levels)`, > 100,000 events → `YAML too large (over 100000 events)`, each with its line; it also reports the first anchor/alias, the first one at or under `tasks.<task>.views` with alias keys resolved to their anchored scalar, and the first alias to a still-open collection) and `has_cycle` (an iterative walk of the loaded value; `YAML aliases must not form a cycle`). View files still allow no anchors at all; `hypothex.yaml` allows them outside views unless they form a cycle. The YAML depth guard now fires before the 64-level bound of `vega_spec_problems`, which stays for specs that arrive without YAML. Task 34's duplicated import paragraph is removed. Tests: `test_views_key_written_as_an_alias_is_resolved` (the exact aliased-key example, cyclic and not), `test_deep_or_cyclic_yaml_is_a_config_error` (600 nested lists; a cycle outside views), `test_anchors_outside_views_stay_allowed` (legit anchors load; a shared mapping passes the guards) (Task 5); `test_deep_or_huge_yaml_is_rejected_before_it_is_loaded` (600 nested lists, the 64-level edge, 100,000 events) (Task 16); the 600-nested-lists case in `test_view_anchors_and_huge_specs_are_issues_never_500` (Task 31: PUT 400, validate 200 `{ok: false}`); doctests of `scan_yaml` and `has_cycle`.
- Version filter, Tasks 20/35 and contract 1.6: `{source: runs, fields: [status], filter: {version: p10}}` returned nothing because `version` was added only when `fields` listed it. `_table_rows` now sets `version` on every full `runs` row before the filter. Test: `test_runs_table_filters_on_version_it_does_not_show` (Task 20).

Verification (round 2): Tasks 1–23, 30, 31, and 34 were applied by the same script to a scratch worktree of `phase-1b` at `a4baa19` (Tasks 24–29, 32, and 33 skipped: they touch none of the files of Tasks 30, 31, and 34 that were checked). Full suite `468 passed` (after round 3) plus the 2 `hx demo` tests of Task 34, which need `hypothex.demo` (Task 25, skipped) and fail with `ModuleNotFoundError` only for that reason; `ruff check` clean after each task's own `ruff format` step; `ty check src` clean except the same unresolved `hypothex.demo` import; the doctests of `stats`, `store`, `headlines`, `leaderboard`, `views`, `sources`, and `panels` pass. The regressions were confirmed on the unfixed code (equal stems, `RecursionError`, `[]` rows, a 404 instead of the config error when `_find_view` does not re-load, `RecursionError` from `yaml.compose` on 600 nested lists, and the aliased `*vk:` key invisible to the round-2 check). Per-task counts: Task 5 `24` (`10 failed, 14 passed` at Step 2), Task 6 `17`, Task 7 `13`, Task 16 `43`, Task 17 `60`, Task 19 `62`, Task 20 `18`, Task 21 `23`, Task 22 `38`, Task 23 `56` (panels + sources); Task 31 adds 9 view tests, Task 34 adds 7 tests. Other counts are unchanged.
