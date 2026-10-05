# Phase 3 current-main refresh and ordered review gates

Date: 2026-10-06. This report supersedes the earlier baseline's current-status
claims without rewriting its historical evidence.

## Revisions and authorization

- Historical plans head: `4392c8b90f96a23b6d35477520f86ebf45075bb1`.
- Current source baseline: `a4441256f39d014d9ad43dea976af1b448f163e3`.
- Plans PR: https://github.com/hypothex/hypothex/pull/22.
- Implementation requires a complete primary review followed by an independent
  adversarial review, both LGTM on the final plan. Earlier rounds 4–6 do not
  satisfy this new gate. The earlier six-round limit is historical.
- The full 13-item contract scope is retained. No Phase 3 runtime source changes
  are made by this refresh. `tasks/phase3-execution.md` tracks the gates and the
  user's fresh-install, upgrade and integrated-testing requirements.

## Primary round 1

Verdict: NOT LGTM. Two P2 findings and three P3 corrections:

| Finding | Required resolution |
| --- | --- |
| P2-1: plan source drift | Refresh source blobs and replacement anchors against current main; retain PanelContextProps, effective Task view, Metric/Seeds controls, selected-run/training/insights behavior and Examples containment. |
| P2-1: export selection | Add `ExportOptions.primary` and carry selected primary through task HTTP, CLI, MCP, UI request and cache; reject it for compare export. Preserve baseline/noise/direction semantics. |
| P2-2: incomplete pricing | Only explicit true completeness displays an unqualified total. Preserve recorded subtotals and legacy unknown flags through run, sweep, digest, Slack/email and notebook paths. |
| P3-1: CLI JSON snapshots | Regenerate and inspect only intended new keys for owner, baselines, cleaned metadata and sweep cost completeness. |
| P3-2: cleaned checkpoints | Feed cleanup metadata to both WhereList and the current Checkpoints panel, retaining existing training details. |
| P3-3: stale status prose | State current baseline and pending gates in all three plan headers; preserve historical reports as historical evidence. |

The round read the whole contract but only part of the plans. Backend Tasks
1–8, 10–11, 13, 15–17, 19–21, 25, 28–38, 40–45 and 47, frontend Tasks
1, 3–21, 25 and 26, and mockup images were not reviewed in detail. The next
primary review must cover these as well as verify the corrections. An incomplete
coverage pass is not the clean approval required for implementation.

The [unchanged primary round 1 report](2026-10-06-hypothex-phase3-primary-round1.md) records the original findings and coverage. Raw probes are in `/tmp/hx-phase3-evidence/claude-r1/`.

## Interface decisions

Task export resolves the same primary-aware board as the UI. Its first default
column, row order, metric direction, test interval and baseline deltas follow the
resolved primary. Omitted primary uses the configured task primary. Compare
export rejects a non-null primary, since it has no single selected task board.

`SweepSummary.cost_complete` is additive and defaults to false. It is true only
for a non-empty sweep whose every member has a cost record with
`gpu_pricing_complete is True`. `total_usd` keeps its existing recorded-subtotal
meaning. A missing record or a false/null flag cannot become complete because
the subtotal is zero.

Runs and digests use recorded cost unchanged, falling back to
`compute_cost(record, None)` only when missing. Digests include every ended run;
only a window with no ended runs uses explicit known-zero totals. `add_costs`
propagates completeness. Incomplete display is `Cost unknown · $X recorded`.
No repricing of legacy data or invention of evidence is authorized.

The digest mockup declares its ordinary fixture fully priced and exposes
`#notebook/cost-unknown` with a $0.25 recorded subtotal. DOM checks cover true,
false and null flags at zero and nonzero subtotals; all six states have no
horizontal overflow at 1280 px. Browser screenshot capture currently returns
`PreviewAutomationExecutionError` after opening and retrying a fresh preview
tab. The new state has not yet had a saved screenshot/visual review; existing
PNG files remain historical visual references. This limitation must remain
visible to reviewers rather than being reported as a successful render check.

## Preserve and rerun during implementation

The following current-main regression suites must remain present and pass:

- `tests/core/test_backlog_backend.py` and `tests/core/test_bound_comparison.py`:
  source bindings, strict comparison, ranking and cost semantics.
- `ui/test/pages/Task.test.tsx`: Metric/Seeds and effective-view behavior.
- `ui/test/pages/selectedRun.test.tsx`, `trainingDetails.test.tsx` and
  `TaskInsights.test.tsx`: selected context, training checkpoints and strict
  evidence-backed insights.
- `ui/test/panels/Leaderboard.test.tsx`: repetition and cost evidence.
- `ui/e2e/backlog.spec.ts` and `ui/e2e/examples-layout.spec.ts`: integrated
  controls and final Examples containment in both colour modes.

Preserve all current HTTP/MCP arguments, including `primary` and
`require_bound`, full `ScoreRecord` serialization through SQL/rebuild/recovery,
durable sweep receipts and owner identity, token discovery and authenticated
transport. These are existing behavior, not new Phase 3 scope.

## Evidence and remaining gates

Bounded plan-snippet probes validate specific corrections; they do not establish
that the complete Phase 3 application has been assembled or tested. Worker
receipts live under `/tmp/hx-phase3-evidence/backend-r1-fixes/` and
`frontend-r1-fixes/`. The next review must independently examine the final frozen
plan and current source. Both final approvals and implementation remain pending.

### Correction checks completed before re-review

- Backend exact-plan probes: cost display/aggregation 29 expected failures before
  the fix and zero after; primary export/sweep completeness nine before and zero
  after. The latter uses current main's leaderboard and models with substituted
  rendering/baseline adapters, so it proves forwarding and selected-board data,
  not the complete renderer or assembled application.
- Frontend: 12 historical snippets, seven current integration snippets and 25
  current-main source hashes match. This establishes replacement compatibility,
  not TypeScript compilation or browser acceptance for future code.
- Plan contract/AST checks, external probe Ruff/ty checks and `git diff --check`
  pass. Mockup scripts bundle with Bun; the six cost DOM checks pass.
- Backend and frontend plans were frozen by their writers before integration.
  Current main stayed clean throughout. No source implementation is included.


## Primary round 2 and next corrections

The [round 2 report](2026-10-06-hypothex-phase3-primary-round2.md) records
complete review coverage and NOT LGTM on `9cbe8a3`. It confirms the first-round
P2 fixes, JSON snapshot coverage and cleaned-checkpoint plan. Three new P2s
remain: trusted home/store aliases in cleanup, exact SPA deep-link routing, and
an executable installed-package acceptance task with CI ownership.

The contract now states those invariants explicitly. Backend Task 49 is owned
by [the packaged acceptance supplement](2026-10-06-hypothex-phase3-package-acceptance.md),
after the backend and frontend implementation tasks; it must exercise the
installed wheel outside the checkout and the synthetic schema-3 upgrade path.
The main implementation plans carry focused regression requirements for the
cleanup and route corrections, plus the review's smaller test/anchor repairs.
These remain proposed implementation steps, not completed application tests.

Snapshot capture was retried in a fresh native preview tab for the unknown-cost
mockup and returned the same `PreviewAutomationExecutionError`. DOM inspection
works; a new saved visual still is not available. The preview and owned loopback
server were closed after the check. This does not change the runtime gate.


### Round 2 correction verification

- Cleanup: 90 bounded assertions against the exact planned storage helpers and
  recheck logic cover literal/resolved home and store, protected metadata,
  allowed artifacts and nested symlinks. No deletion or assembled cleanup was
  claimed by this probe; the plan adds plan/apply regressions for implementation.
- Deep links: 120 guest guard assertions use the planned AuthGuard and current
  TokenGuard, covering GET/HEAD, forbidden methods, protected/unknown paths and
  missing UI. Both modes serve only the exact installed SPA routes publicly.
- Frontend: 19 prior snippets, 27 current-main source hashes and three additional
  sweep replacements match; baseline auth emissions and six cost cases were
  checked. Notebook fixture text now matches the actual planned digest string.
- Task 49: Python/YAML snippets parse, the CI job has a concrete pytest
  entrypoint, and a baseline-only probe built a genuine schema-3 fixture with
  evaluator-issued four-example bindings and a strict comparison oracle.
  Installed Phase 3 acceptance has not been run; it is an implementation task.
- The remaining listed P3 test expectations, anchors, task staging/imports and
  stale current-status prose are corrected. The missing unknown-cost screenshot
  remains an explicit nonblocking visual limitation.

Evidence directories: `/tmp/hx-phase3-evidence/backend-r2-fixes/`,
`frontend-r2-fixes/` and `package-r2-fixes/`. Each writer froze its owned document
before parent integration. Current main remains unchanged. Primary round 3 must
confirm these corrections before adversarial review begins.


## Primary round 3 response

The [round 3 report](2026-10-06-hypothex-phase3-primary-round3.md) returned
NOT LGTM on `4cbc5bb`. It confirmed all round 2 blockers and smaller fixes;
its independent cleanup probe passed 104 assertions. New findings P2-D and
P2-E are confined to Task 49's prospective package harness and CI job.

- P2-D: moved `HX_PACKAGE_ARTIFACTS` to the pytest step's `env`; the upload
  action retains the same `runner.temp` path in `with`. Actionlint 1.7.12 on
  the full current workflow plus the original job reproduces the forbidden
  runner-context failure. The corrected full workflow passes. Shellcheck and
  pyflakes integrations were disabled for this expression-focused check;
  no repository workflow has been changed or run for Task 49 yet.
- P2-E: fresh-team children explicitly use `USER=sv` at seed/start/restart/CLI
  stages; the parent and other scenario environments retain their identity.
  The plan requires a harness regression for inherited CI/local usernames.
  The guide must distinguish this test pin from manual owner discovery and
  the seeded browser logins. Exact planned `owner_name()` probes demonstrate
  the original assertion failing for runner/shreyasv and the override working.
- P3: aligned the storage-helper interface summary with trusted home/store
  aliases. Source `uv sync` stays a pre-pytest prerequisite, removing nested
  synchronization of the active environment from `PackageRun.prepare()`.
- Sweep behavior is intentional: an actual empty sweep has incomplete cost
  and shows unknown; the pure-function complete-empty fixture tests explicit
  completeness metadata. Digest completeness applies to its own window.
  These semantics and differing compact labels are unchanged.
- The unavailable unknown-cost screenshot remains nonblocking and unclaimed.

Evidence: `/tmp/hx-phase3-evidence/package-r3-fixes/` contains the executable
`test_plan_regressions.py`, before/after full workflow files, actionlint logs
and pytest results. Five focused tests pass; Ruff formatting/lint and the
plan diff check pass. The probes test documented snippets/environment rules,
not an implemented PackageRun or installed Phase 3. Prior unchanged source
and frontend evidence is reused. Both approval gates remain pending.
