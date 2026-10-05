# Hypothex Phase 3 plans — Claude primary review, round 2

## Reviewed hashes
- Plans: `/tmp/hx-p3-plans` HEAD `9cbe8a3b1d3a6f394773546d334ed799b05417bf` (clean).
- Main: `/tmp/hx-final-main` HEAD `a4441256f39d014d9ad43dea976af1b448f163e3` (clean before and after all probes).
- Plan files: `docs/superpowers/plans/2026-10-04-hypothex-phase3-{contract (674 lines), backend (22792), frontend (10272)}.md`, plus `docs/mockups/phase3/`.

## Coverage
Complete. See [coverage ledger](2026-10-06-hypothex-phase3-primary-round2-coverage.md). Contract, all 48 backend tasks with header/done map/assembly notes/final acceptance, all 26 frontend tasks with preflight/done criteria, mockup HTML/data and 3 PNGs.
Round-1 gaps read this round: AuthStore and settings/secrets (B T2, T3, T6; F T2), notifier replay (B T16-T17), storage safety/TOCTOU (B T20-T22, T31), Postgres staging (B T34-T36), MCP/CLI token transport (B T32-T33, T41-T42), demo startup (B T45), UI async credential and query replacement (F T2, T22-T24).

Probes (all loopback/in-memory, explicit imports from the named tree):
- `probes/protected_alias_probe.py` + `.log`: plan's `_forms/_roots/_linked_below/protected_reason` with a symlinked home.
- `probes/spa_deeplink_probe.py` + `.log`: main `create_app` in token mode, fake UI dir.
- `probes/frontend-preflight-r2.txt`: plan's own frontend preflight run against main, exit 0.

## Not validated (honest list)
- No Phase 3 code exists; no plan test was executed end to end.
- No Docker/Postgres run. Golden export bytes not executed.
- No browser run. Snapshot/recording not done by me.
- The unknown-cost visual is NOT checked: `index.html` has `#notebook/cost-unknown` (lines 547-548) but no PNG exists, and I did not capture one.

## Prior findings
| Finding | Status | Evidence |
|---|---|---|
| P2-1 main refresh drift | FIXED | Preflight passes on main (7 + 12 anchors). All backend anchors I checked match main (ledger). Selected primary flows: F ExportMenu `primary={board.data.primary}`, shown only when `board.data && !board.isError` (alternate query has no placeholder) → HTTP/CLI/MCP `primary` param → `ExportOptions.primary` → `get_leaderboard(primary=)`; `_selected_primary` raises ConfigError → 400 on an unknown key; direction from `board.higher_is_better`; baselines/noise/defaults pass through the same board; compare rejects `primary` with RunError. |
| P2-2 cost completeness | FIXED | `cost_text(total, complete)` used in run notice, sweep notice, digest headline/markdown/notice; `SweepSummary.cost_complete`; digest folds `add_costs(r.cost or compute_cost(r, None))`; empty window = explicit complete zero; tests cover False/None/True × 0/0.25 and missing cost. Visual not checked (see above). |
| P3-1 JSON snapshots | FIXED | Blocks in T4, T9, T22, mention in T14. (Blocks sit after the commit step — ordering nit.) |
| P3-2 cleaned checkpoints | FIXED | F T24: TrainingDetails CheckpointTable, Run, SelectedRun; bounded detail queries. |
| P3-3 stale prose | NOT FIXED (partial) | Headers updated, but backend:11604 and backend:19376 still say "required before formal round 5"; T18 Rules still show `$<usd>`; contract line ~343 stale. |

## New findings (blocking)

### P2-A — Storage protection misses resolved paths under a symlinked home
- Plan: backend `_forms` 10180, `_roots` 10189, `_linked_below` 10201, `protected_reason` 10211 (`home = ctx.layout.home`; `form.is_relative_to(home)`); reused by `_recheck` 11277 at apply.
- Source: SDK `_append_artifact` records `Path(path).expanduser().resolve()`.
- Failure: home reached via a symlink (common on HPC: `/home/u` → `/gpfs/...`). A run logs its own run dir, or a file in it, as an artifact (e.g. HF Trainer `output_dir=$HYPOTHEX_RUN_DIR`). The recorded path is resolved, so it is not `is_relative_to(home)` and not under a root. Probe: literal `run.yaml` → `protected`; resolved `run.yaml`, `metrics.jsonl`, `artifacts/x.pt` → `None`. After archive + 30 days, apply deletes run.yaml/metrics/scores. Breaks contract 1.9 and §7 ("never deletes a run folder's records").
- Fix: compare each form against both `home` and `home.resolve()` (same for the store root); run `_linked_below` against the base that matched; add plan- and apply-time regressions with a symlinked home for a resolved run-dir artifact and a resolved `run.yaml`.

### P2-B — SPA deep links to new pages return 401 JSON
- Plan: backend 12360 (T23 step 4) adds only `/pair` to the SPA classifier. Main `src/hypothex/api/app.py:1882-1898` matches only `/`, `r/`, `x/`, `s/`, `t/`.
- Failure: default token mode, reload or open `/settings`, `/storage`, `/n/<project>`, `/n/<project>/<day>`, or the digest's own `<base>/n/<project>` link → `401 {"error":"missing or wrong bearer token"}` instead of the SPA/token gate (probe on main). In scoped mode an unpaired browser gets JSON, not the 401 gate.
- Fix: extend the regex to match frontend `isAppPath` (F T7: `n/<p>[/<day>]`, `settings`, `storage`, `pair`); add token-mode and scoped-mode deep-link tests for each route.

### P2-C — Contract done criterion 9 (installed-wheel usability) has no owner
- Contract 597: wheel built and installed with uv outside the checkout; packaged team demo and UI; synthetic pre-Phase-3 SQLite home upgrade and restart; migrations, preserved data, scoped credential discovery; commands kept for the user.
- Plan: backend Done map 22727-22741 has 9 rows and row 9 is pytest/ruff/ty — it drops wheel/upgrade. Only prose at 22788 "Refreshed-main final acceptance (verification only)". Frontend 10248 cites "contract 11.9" for `bun test` (now 11.10). No task, test or CI job builds the wheel, installs it outside the repo, or upgrades a schema-3 home.
- Failure: Phase 3 can pass every listed check while `ui_dist` or Alembic migrations are missing from the wheel, or an existing user home fails to upgrade/restart. The user test handoff is then unverified.
- Fix: add one task with an automated test (marker allowed): `uv build`; fresh `uv venv` outside the repo; install the wheel; assert `hypothex.__file__` is in site-packages and packaged `ui_dist` + migrations exist; `hx demo --with-team` serve → token/login → restart; a synthetic schema-3 home (runs, scores, bound comparisons, `serve/server.json`) upgraded and compared; write the user handoff commands. Wire it into CI. Fix both done maps to the contract numbering (8 = Playwright, 9 = wheel/upgrade, 10 = lint/tests).

No P0 or P1 found.

## Nonblocking P3
Backend
- T7 commit list omits `src/hypothex/api/tickets.py` and `tests/auth/test_tickets.py`.
- T22 RunDetail anchor shows `children=sorted(children)`; main has `children=sorted(ctx.index.child_run_ids(run_id))`.
- T45 says `served()`; main function is `demo_hosts()`.
- T29 HTTP primary test uses the configured primary; the opposite-ranking fixture is only demanded in the final note. Put it in T29.
- T33 lacks the MCP selected-primary test that the final note requires.
- T36 test import order.
- P3-3 leftovers above.

Frontend
- T2 test "export error keeps the API error shape" expects `"no session"`; baseline 401 throws `"Token required"`.
- T2 auth-store test expects `["locked","open"]`; main AuthStore emits duplicates. Plan says adapt helpers; state it in the test.
- Sweep page may still show unqualified `total_usd` (pre-existing on main).
- Fixture `NOTEBOOK_TEXT` uses `$86.5` (declared priced; fine, but add an unknown-cost fixture to match the mockup state).

## Verdict
**NOT LGTM.** Coverage is complete, but P2-A, P2-B and P2-C are unresolved.
