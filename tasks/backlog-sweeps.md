# Sweep frontend backlog implementation

Scope: backlog 59/60/61/63/68/71/74/75/78/82/83 (64 duplicates 61), plus focused coverage 62/67/70/72. Only assigned sweep components, optional useAction.reset preserving auth-generation checks, their tests, and this plan. No full Bun suite/build/browser/commit/push.

- [x] Add failing focused regressions for count/detail coherence, transitive mixed sorting, accessible complete heat legend, bounded forest labels, terminal value states, action dismissal/count defaults, loading and recoverable rerun opening.
- [x] Implement scoped behavior changes; preserve frozen launch defaults and auth action generation guards.
- [x] Add component coverage for null means/best/intervals and lost/killed ordering.
- [x] Run affected focused Bun tests and TypeScript checking; record exact evidence under /tmp/hx-handoff-evidence/backlog-sweeps/.
- [x] Report source changes, evidence, and pending browser geometry verification to parent.

Design choices: numeric parameter values sort as a numeric category before text ascending (reverse descending); missing values remain last. Rerun never substitutes another cell if the selected best has no available template. Opening errors/loading must allow close; retries explicitly refresh relevant queries. Forest labels stay within a fixed visible area and retain full text access.

## Final evidence

- First failing batch: 42 passed / 8 failed; second failing batch: 24 passed / 5 failed. Additional terminal-missing-time and initial-run-read-error tests each failed before their fixes.
- Final focused Bun run: **100 passed, 0 failed, 477 assertions**, 10 files (8 affected sweep files plus useAction/authActions). Existing LaunchDialog act warnings remain; they are not suppressed.
- Scoped `git diff --check`: passed.
- TypeScript initially passed. Final check reports only six concurrent Leaderboard `cost_complete` errors awaiting parent-owned model/type integration; no sweep/type errors. Parent notified.
- Browser geometry is explicitly pending the parent's coordinated pass. Forest label slots are tested for fixed bounds, ellipsis and full title text; no browser claim.
- Production ownership frozen after final focused checks; shared OpeningDialog is parent-owned. No full suite, build, commit, push or PR.

Follow-up: own SweepRerun test warnings are now resolved without suppression (77 API/query/rerun tests pass warning-free); final typecheck passes after shared model integration and cache assertion annotations. See `tasks/backlog-tests.md`. Browser geometry remains parent-coordinated.
