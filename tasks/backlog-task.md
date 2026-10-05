# Task controls and selected-run integration

- [x] Preserve NewRun OpeningDialog recovery and existing 22 tests.
- [x] Metric selector derives exact metric/key references from baseline leaderboard scores, restricted to configured task metric versions. Baseline primary remains an option even when no scores exist.
- [x] Selected metric calls useLeaderboard opts.primary and copies the active resolved view with each panel's data.primary override. Default requests remain the original named view. Explicit authored axes/metric histories are preserved.
- [x] Seeds/Repeats toggles group_by=run for curves, scatter, distributions and grids. Turning off restores each authored grouping. It does not merely relabel aggregate statistics.
- [x] Plain unmodified run links open a selected-run pane for training, agent_eval, agent_iteration and system_bench. Query/hash run links, other routes and modified clicks retain their existing navigation contract.
- [x] Training run/checkpoint sections, iteration outcome comparisons and system raw sample sections mounted. Selected system runs scope raw samples through server filtering.
- [x] Project/task scope key resets metric, seed/repeat display and selected-run state. View switching retains task-local choices.
- [x] Hide previous metric panels/headline while selected ranking recomputes; panel placeholder responses are never rendered under a changed scope.

## Verification

Initial red: existing 22 tests passed, five new integration tests failed before implementation. Final dedicated Task and TaskInsights checks pass 40 tests, 145 assertions. Existing NewRun tests remain intact. Added checks cover metric requests and view overrides, supported per-run grouping, inline run selection/closing, modified/query/hash/other-link handling, kind-specific section wiring, raw sample selected scope, recomputation loading and full task-scope reset.

TaskInsights review follow-up rejects unknown/empty/ambiguous metric source fingerprints. Field discovery checks a bounded 100-prediction page, tolerates unscored initial rows, and says when no binary field was found within that bound. Evidence: /tmp/hx-handoff-evidence/backlog-insights/task-red.txt, source-red.txt, task-green.txt.

Parent owns full typecheck/build/browser/integration validation. No commits or publishing from this worker.
