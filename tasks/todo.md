# Backend audit integration (2026-10-05)

Scope: finish handover queue step 2 on `audit-fixes`; parent coordinates merge.

- [x] Read handover, audit summary and original performance method.
- [x] Confirm Wave 3 CLI uv opt-in and SLURM/uv documentation handoffs exist.
- [x] Complete baseline Python/UI/docs checks; test first for integration fixes.
- [x] Review branch implementation and merge origin/main without discarding either side.
- [x] Remeasure the original 19,993-run synthetic store; distinguish cold, warm and semantics.
- [x] Run final required checks and review final diff.
- [x] Commit report and prepare a reviewed PR body; parent owns push/open/link and CI.
- [x] Remove integrated area worktrees only if ordinary removal preserves all data.

Decisions and evidence
----------------------

- Initial ruff lint/format and ty checks pass at `52b25e4`.
- Initial UI: 676 tests pass; type check and production build pass.
- Every area branch B/J2/K/L/O is an ancestor of audit-fixes. All worktrees contain ignored
  files (virtual environments/test caches); preserve these until a safe cleanup is established.
- Whole-branch review uses merge-base until origin/main is merged; direct two-tip diffs
  misleadingly show newer main UI/property-test additions as removals.

- Baseline Python suite: 1 failed, 1639 passed, 3 skipped, 11 deselected (497.97 s).
  The sole failure was the intended `host_state` addition missing from CLI snapshots;
  after updating exactly the two keys, all four snapshot tests pass.
- Review regression: CLI task re-evaluation used 120 seconds while MCP allowed 3600.
  A new test failed at 120 vs 3600, then passed after forwarding the task budget.
- Removed area worktrees and branches B/J2/K/L/O with ordinary Git commands after
  preserving ignored files in `/tmp/hx-handoff-evidence/af-area-archive/`. Terminated
  only ten confirmed orphaned af-O synthetic fixture processes (command/cwd evidence
  retained in `stale-processes.txt`).

- Main merge conflict in bootstrap statistics: retain audit cached resampling and main
  undefined mixed-infinity handling. Main property regressions failed (2 failed,
  6 passed) with the audit-only behavior before retaining the NaN guard.

- Launch-id collision review: reserved each checkout directory exclusively; a deterministic
  competing-worktree test failed before the fix and passes with 143 related tests.
- Unsupported advisory locking review: overlapping rebuilds now use independent staging
  directories and carry run-change markers (including deletion tombstones) across swaps.
  Deterministic update/create/delete cases failed before the marker fix; all 45 affected
  index/context tests pass afterward. Ruff and ty pass.
- First merged-main Python run: 1721 passed, 3 skipped, 11 deselected; the sole failure
  was a property model that did not account for intentional SLURM array refusal.
  Updated the independent option model and added an explicit example; 150 affected tests pass.
- Before performance measurement, found a second stale af-O process tree from
  pytest-1295: five orphaned supervisors and five gate-wait children, all over seven
  hours old. Confirmed command/cwd evidence and terminated only those processes;
  retained `stale-processes-1295.json` beside the earlier cleanup evidence.

- Final code `8e1a1ef` includes main through PR #14. Python: 1727 passed,
  3 skipped, 11 deselected (493.38 s); Docker: 11 passed (200.55 s).
  UI: 848 unit tests, both TypeScript checks, production build, 44 Playwright tests,
  and all three demo shutdown cases pass. Ruff lint/format, ty and Sphinx pass.
- Performance measured in an isolated clone during a quiet window beginning
  2026-10-04 22:00:15 UTC. Full report and raw samples are committed under
  `docs/audits/2026-10-05-backend-performance.{md,json}`. Historical baseline is
  explicitly identified, cold hydration and CLI regressions retained, and the
  original fixture is preserved. New harnesses and complete logs remain under
  `/tmp/hx-af-perf-after`.
- Parent independently reviewed `44a6b58`, `aa5da40`, and `0234e93` with no new issue.
  PR body/title prepared in `/tmp/hx-handoff-evidence/backend-pr-body.md` and
  `backend-pr-title.txt`; parent will inspect, push, open/link, and monitor CI.

# UI leftovers, handover step 8 (2026-10-05)

Scope: only named step-8 UI items; `/tmp/hx-ui-leftovers`, branch `ui-leftovers`,
base `3b696f1`. Parent coordinates step-7 merge, backend contract, full-check window,
push/PR/merge. No Phase 3 or all-minors/F17 implementation.

- [x] Read binding handover, Node guide, source-backed step-8/minor triage; verify base.
- [x] Identify PERF-F9c active views/query contract: metrics exists; max_points requires additive backend field.
- [x] Run-page actions: infer capability, re-evaluation counts/reasons, useful 404 state.
- [x] Paths/errors: SlashPath on run paths and readable project/task names; concise ErrorBox.
- [x] Charts: width-derived leaderboard ticks, responsive Failures legend, nonoverlapping scatter labels.
- [ ] Request only displayed run metric names with bounded max_points after backend contract approval.
- [x] Share billed GPU count and useHubEnvironment.
- [ ] Preserve queue switch nowrap from step 7.
- [x] Verify already-fixed row growth and e2e home-path docs; avoid duplicate edits.
- [ ] Merge final step-7 main without rebasing; resolve by preserving both behaviors.
- [x] Scoped frontend checks and independent review in parent-approved window.
- [x] Conventional local commit.
- [ ] Final main integration and full required checks remain parent-coordinated.

Ownership: UI parent owns Run/RunActions/query hooks/stats/KindPanels/models/docs;
chart_layout owns chart panels and their tests; paths_errors owns shared path/ErrorBox
components and tests. No worker commits; shared worktree. Every actual fix gets a
failing regression first and focused green evidence in `/tmp/hx-handoff-evidence/ui-leftovers/`.

Contract proposal sent to parent: optional PanelData.max_points, integer 2..500;
null/default retains 500, curves-only final per-run/name LTTB; explicit empty metrics
means no series. UI additions wait for frozen approval. Python/contract edits belong to parent.

Step-8 implementation evidence (before final step-7 merge)
--------------------------------------------------------

- Run action/not-found regression: 13 pass/4 fail before; 38 focused tests pass after.
  Infer capability comes from successful task-stage read; re-evaluation formatter is
  shared with Task and previous-run feedback is not displayed after navigation.
- Shared environment query + billed GPU-hours: 39 pass/2 fail before; 84 affected
  query/run/overview/sweep tests pass after. No real host access.
- PERF-F9c request regressions: 18 pass/4 fail before; 32 tests pass after. Run history
  names are explicit; >100 names split without loss; explicit [] remains empty;
  explicit sweep/step choices remain untouched. Generated API types refreshed from
  create_app in an isolated /tmp home without starting a server.
- Parent committed backend cap `a5f410e`: six tests failed first; 192 API/core tests,
  Ruff/format/source ty/Sphinx passed. Backend artifacts/logs live under the shared
  handoff evidence directory. UI TypeScript check passes.
- Delegated paths/errors: six expected failing regressions, then 46 tests pass.
  Chart layout: three expected failing regressions, then 64 tests pass; positional
  legend bounds and accessible fallback-key grouping verified in review.
- Existing e2e home-path docs and row-growth CSS verified in source, retained.
- Build/browser window released: production build and 881 UI unit tests pass; e2e
  TypeScript passes. Added actual chart text geometry coverage at spans 5/7/12
  in light/dark with resize; all six browser tests pass (13.4 s).
  The first browser run caught legend row spacing and endpoint tick overflow;
  fixed both root causes, with the failing artifacts preserved before rerun.
- Independent review identified late run re-evaluation feedback and cached infer
  capability after task refresh failure; both regressions failed first, then all
  21 action/run tests passed after fixes.
- Live metric-name lag found in indexed run details; parent owns authoritative
  backend discovery fix. PERF-F9c remains pending that contract and regression.
- Waiting on step-7 hx-sw+nowrap merge; no pushes/PRs/merges performed.
  Full combined checks remain required.

- Final scoped verification: 883 UI unit tests, source/test TypeScript, e2e TypeScript,
  production build, all 50 Playwright tests (35.5 s), and Sphinx with warnings as
  errors pass. Both isolated Playwright servers shut down. Diff whitespace check passes.
- Parent moved the live-name backend fix to the preceding dogfood branch; strict
  metric whitelisting is integration-dependent until that fix lands on main.
  Parent requested local UI commit and ownership handback without push/PR.
