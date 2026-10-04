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

# Bounded view integration (2026-10-05)

Scope: preserve the merged audit behavior while bounding live metric reads and view work.

- [x] Keep exact state readers strict on UTF-8 and compatible with universal newlines and
  surrounding whitespace; only live metric reads apply byte/name/point caps.
- [x] Prove per-name buffers and long-name memory stay bounded while reading.
- [x] Merge audit SQL/primary-field/group-label behavior without dropping security bounds.
- [x] Consolidate shared LTTB with exact integer buckets and overflow-safe finite axes.
- [x] Reuse primary example data for stat-strip denominators instead of rereading per reference.
- [x] Complete full Python, Docker, UI, e2e, static and Sphinx checks on the integrated branch.
- [ ] Review branch, publish PR, and merge only after all current-head CI checks pass.

Evidence: integration first produced five failures (large finite LTTB values and repeated
primary-file reads); all 340 focused core tests now pass. A separate exact-read Unicode
whitespace regression failed before restoring strip behavior; all 21 filesystem tests pass.
Full validation and review logs are retained under `/tmp/hx-handoff-evidence/sec-integration-*`.

Final integration: 1,813 Python passed / 3 skipped / 11 Docker deselected; separate
final Docker run 11 passed. UI 848 and Playwright 44 passed, as did shutdown, build,
types, Ruff, source ty, and Sphinx. Review regressions additionally cover lazy hydration
after terminal publication and after a rebuild, terminal-before-metrics execution order,
and loss-peak preservation near int64 step limits. Independent review has no remaining
actionable blocker. PR publication and current-head CI merge remain pending.

Merged the repository-path gate from main `3b696f1`: production files merged cleanly;
three appended-test conflicts retain both regression groups. Combined validation:
1,853 Python passed / 3 skipped / 11 Docker deselected; separate Docker 11 passed;
Playwright 44 passed; shutdown, Sphinx, Ruff, source ty, and diff checks pass.
Unchanged UI unit/type/build evidence remains valid. Updated-head CI is required
before the final merge.
