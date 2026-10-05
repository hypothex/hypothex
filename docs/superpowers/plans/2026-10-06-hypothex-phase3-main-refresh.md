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
