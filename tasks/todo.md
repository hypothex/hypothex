# Backend audit integration (2026-10-05)

Scope: finish handover queue step 2 on `audit-fixes`; parent coordinates merge.

- [x] Read handover, audit summary and original performance method.
- [x] Confirm Wave 3 CLI uv opt-in and SLURM/uv documentation handoffs exist.
- [x] Complete baseline Python/UI/docs checks; test first for integration fixes.
- [ ] Review branch implementation and merge origin/main without discarding either side.
- [ ] Remeasure the original 19,993-run synthetic store; distinguish cold, warm and semantics.
- [ ] Run final required checks and review final diff.
- [ ] Commit, push, open and link backend audit PR; report CI to parent.
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
