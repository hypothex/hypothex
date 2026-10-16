# Phase 3 plan review — Claude reviewer, round 1 (read-only)

Date: 2026-10-06

## Reviewed revisions (verified)

- Plans worktree `/tmp/hx-p3-plans`: HEAD `4392c8b90f96a23b6d35477520f86ebf45075bb1` (`p3-plans`). Only `tasks/phase3-execution.md` is untracked. I did not change it.
- Current main `/tmp/hx-final-main`: HEAD `a4441256f39d014d9ad43dea976af1b448f163e3`. The tree is clean.
- Plan pin `54259b0`. Drift `54259b0..a444125`: 119 files; `src/hypothex` has 10 files (+665/−56).

## Verdict: NOT LGTM

This round found no P0 or P1. Two P2 findings remain open, and one of them blocks the start of the work. The plan is not yet ready to implement against current main.

## Findings

### P2-1 — The plan is not refreshed for main `a444125`. The frontend plan's own preflight fails.

Evidence:
- `frontend-preflight-main.txt`: I ran the frontend plan's mandatory preflight (frontend plan lines 22–57) on main. Result: `REFRESH REQUIRED` for 10 of the 19 reviewed sources:
  - `queries.ts`, `client.ts`, `models.ts`
  - `Task.tsx`, `Run.tsx`, `Leaderboard.tsx`
  - `useAction.ts`, `launchApi.ts`, `LaunchDialog.tsx`, `KindPanels.tsx`

  The plan's `assert` stops before Task 1.
- The contract itself still says the work is not refreshed:
  - Contract §2 (line 405) says "Refresh against the actual merged backlog before implementation if it lands later". The backlog has now landed in PR23.
  - Contract line 5 and backend plan line 15 still say "formal rounds 5–6 remain pending".
  - Task 39 (backend line 19164) and Task 2 (frontend line 1545) still say "must be compared/restored ... before Round 5".
- Some replacement blocks no longer match main. Applied as written, they would drop PR23 behavior:
  - Frontend Task 23 (lines ~8925–8948): the `PanelGrid` replacement redefines `PanelGridProps` and `PanelGrid({results, specs, startIndex = 0, aside})`. This drops PR23's `PanelContextProps` passthrough (`...context` → `selectedItemId`, `currentGroupId`, `runStatus`). The Run page passes these props at `Run.tsx:232-233`.
  - The Task 23 anchor `<PanelGrid results={panels.data.panels} specs={detail.data?.view.panels} />` does not exist on main. Main has `specs={customized ? effectiveView?.panels : detail.data?.view.panels}` at `Task.tsx:365`, which carries the Metric selector and the Seeds toggle. Taking the planned replacement text would revert this.
  - The `ExportMenu` and `withBaselines` wiring do not account for the Task page's selected-primary board (`Task.tsx:198-200`). Export always ranks by the configured primary, even when the user selected another metric.
- Backend:
  - Task 12's `_higher_is_better` replacement drops main's new `primary` parameter. This is harmless today but must be reconciled.
  - The Task 23 step 6 anchor `register_env_routes(app, ctx)\n    app.mount("/mcp", ...)` was already stale at the pin, because `BareMcp` sits between those lines.

Impact: implementation cannot start as the plan is written. If someone refreshes it during execution, that refresh happens after both review gates and is never reviewed. The user's gate requires a plan that is ready against current main.

Fix:
1. Refresh the frontend replacement blocks and the blob table against `a444125`.
2. Reconcile Task 23 with `PanelContextProps` and `effectiveView`. Decide whether export follows the selected metric.
3. Refresh the Task 12 and Task 23 backend anchors.
4. Update the stale status text in the contract and the plan headers.
5. Add explicit "preserve" items for PR23/PR24 tests: `Task.test.tsx`, `selectedRun`, `trainingDetails`, `TaskInsights`, `Leaderboard.test.tsx`, `test_backlog_backend.py`, `test_bound_comparison.py`, `backlog.spec.ts`, `examples-layout.spec.ts`.

### P2-2 — Phase 3 notices and the digest show an incomplete cost as a complete dollar total

PR23 added `CostTotals.gpu_pricing_complete` and `LeaderboardRow.cost_complete`. When a GPU rate is missing, the UI shows "Cost unknown · $X recorded" (`Leaderboard.tsx` `costText`). The Phase 3 plan prints `total_usd` without this flag in four places:
- `run_notice`: `cost = record.cost or compute_cost(record, None)` → `f"${cost.total_usd:.2f}"` (backend lines ~6741–6749).
- `sweep_notice`: `· ${summary.total_usd:.2f}`.
- The digest headline: `f"{cost.gpu_hours:.1f} GPU-h ${cost.total_usd:.2f}"` (line ~9122). The notebook and Slack/email copies use the same text.
- The digest mockup and fixtures.

Probe (`cost_probe.py` and `.log`, run on main's code): a finished run with 4 GPUs for 2 h, no GPU rate and $0.25 API usage. The plan's expressions produce `8.0 GPU-h $0.25` with `gpu_pricing_complete: False`. The Slack, email and notebook output would report $0.25 as the run's cost.

Fix: when `gpu_pricing_complete` is not `True`, render the cost as unknown, e.g. `$? (≥$0.25 recorded)`, or the terse glyph form the UI uses. Do this in run, sweep and digest notices and in `render_digest_markdown`. `add_costs` already propagates the flag. Add regression tests for False and for None (legacy).

### P3 (non-blocking)

- **P3-1.** `tests/cli/test_json_snapshots.py` / `snapshots/json_keys.json` covers `runs`, `show`, `leaderboard` and `sweep show`. Task 4 (`owner`), Task 9 (`baselines`) and Task 22 (`cleaned`) add keys. No task regenerates or reviews the snapshot (no mention of `json_keys` in the plan). The suite will fail until someone runs `HYPOTHEX_UPDATE_SNAPSHOTS=1`. Add this to Tasks 4, 9 and 22.
- **P3-2.** PR23 added a Run-page **Checkpoints** panel (`TrainingDetails.CheckpointTable` over `record.artifacts`). Frontend Task 24 marks cleaned artifacts only in `WhereList`. After a cleanup, the Checkpoints panel still lists the deleted checkpoint as a plain path. Pass `detail.cleaned` to the panel or mark the row.
- **P3-3.** Contract line 5 contradicts lines 651–658 about the round status. This is documentation only.

## What I checked and found consistent with main

- HTTP routes: 54 decorators on main. All appear in Task 24's scope list. The new `primary` and `require_bound` query parameters only add decorator dependencies, so their behavior is kept. MCP tool count is 29 and unchanged since the pin. The `once`/`forward` call sites in `app.py` are unchanged (19 matches).
- Frontend `models.ts` insertion anchors (`value_format`, `host_state`, `gpus_requested`, `environment_id`) and `Leaderboard.tsx` baseline anchors all match main. They are insertions, so they keep PR23's `RepeatCheck`, `cost_complete` and `costText` behavior.
- Task 9's `baseline_rows` uses `board.primary` and `board.higher_is_better`, so it follows a selected primary. `cached_leaderboard` variants include `primary`.
- Score binding fields (`per_example_hash`, `evaluation_examples`, `evaluation_ids_hash`) are full-model fields in `record_json`. Contract §2 needs no schema change, and `index.py` has no drift.
- The export cache key `["leaderboard", p, t, "export", opts]` does not collide with main's new `["leaderboard", p, t, metrics, primary]` key. Event prefix invalidation still covers it.
- Playwright: Task 25's whole-file config still routes the new `backlog.spec.ts` and `examples-layout.spec.ts` to the light/dark projects. The `team.spec` and `team-edit.spec` regexes do not overlap.
- Auth design, as read:
  - `AuthGuard` resolution order: an invalid WS bearer never falls back. HTTP may fall back to a cookie, and the selected credential is stored privately.
  - Scoped serve start: `server.json` has no provisional root token, the minted owner session is published under the owner lock, and `release()` runs once.
  - WS revocation re-check runs before the first subscribe and at the loop head.
  - `command_key` binds user, scope, method, path and id. Durable sweep `issuer.accept`/`extend` are keyed per caller and not wrapped in `once`.
  - `identity()` trusts the body only from a host admin.
- Alembic files ship in the wheel (Task 35 checks this with `uv build`). Hatch `packages=["src/hypothex"]` includes them.

## Coverage and limits

- Read fully: contract (659 lines).
- Read in full or in large part:
  - Backend Tasks 9, 23, 24, 26 and 39, plus the plan header and constraints.
  - Excerpts of Tasks 12, 14, 18, 22, 27, 46 and 48.
  - Frontend header and preflight, Task 2 step 5, and Tasks 22, 23 and 24 (head), plus the Task 25 config.
- Checked mechanically on main: all backend and frontend "replace" anchors (`anchors.py`). Seven frontend and nine backend anchors did not match verbatim. Most of these depend on earlier tasks or were mis-attributed by my script. The real stale ones are listed in P2-1.
- Not read in detail:
  - Backend Tasks 1–8, 10–11, 13, 15–17, 19–21, 25, 28–38, 40–45 and 47 (settings and secrets, AuthStore internals, notifier crash and replay, storage plan and apply TOCTOU, Postgres staging, MCP credential transport, CLI client mode, demo).
  - Frontend Tasks 1, 3–21, 25 and 26.
  - Mockup images.

  These areas were the subject of rounds 4–6. I did not verify them again, so treat them as unverified by this round. No product tests were run, because Phase 3 is not implemented.
- I wrote evidence only to this folder. The probes ran main's code in the existing `.venv` without changing `/tmp/hx-final-main` (`git status` clean). There was no network use and no services were started.
