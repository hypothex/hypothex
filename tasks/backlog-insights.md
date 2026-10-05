# Task insights (UI-F17)

- [x] Add independent task insight components, without changing Task wiring.
- [x] Compare latest runs selected from two leaderboard groups through the existing per-example API.
- [x] Reject different tasks, differing/unknown dataset fingerprints or splits, unavailable metric versions, unknown/ambiguous/differing source fingerprints, and latest evaluations without complete evaluator-issued artifact/population bindings.
- [x] Draw actual fixed/broken/shared outcomes; cap individual squares at 400 and use explicitly titled proportional segments above that bound.
- [x] Add raw source=samples table, 100 rendered rows maximum, truthful total/warnings, selected-run server filtering, and hide stale data during scope transitions.
- [x] Export repeatFlags with complete population/fingerprint checks and the documented strictly greater than +10% p95-versus-median rule.
- [x] Focused UI tests. Parent handles full typecheck/build/browser/integration.

## Integration

Import `AgentIterationFlips`, `SystemRawSamples`, and `repeatFlags` from `ui/src/pages/components/TaskInsights.tsx`.

```tsx
<AgentIterationFlips project={project} task={task} board={leaderboard} />
<SystemRawSamples project={project} task={task} selectedRunId={runId} />
```

`board` is optional; the component fetches when absent. Groups are selected by stable group ID. Comparisons use each group's `latest_run_id` and the leaderboard's exact current metric version, not group-aggregated counts. Outcomes are limited to the intersection of scored example IDs, stated in the UI. The default pair follows leaderboard order and remains user-selectable.

Raw samples use `data.filter: {run_id}`; table queries do not honor `data.run_id`. The table shows `meta.total` when present, otherwise `total unknown`. A server-returned panel `meta.error` remains an error. CSV export is deferred.

`repeatFlags(rows, expectedRunIds)` accepts `{run_id, value, fingerprint}` rows where `value` is that run's p95 and `fingerprint` identifies the score definition/source. A caller must supply observations from the same group/population. It returns `{complete, flags: [{runId, relativeDelta}], reason}`; an incomplete/duplicate/nonfinite score population, missing/mixed fingerprints, fewer than two repeats, or a nonpositive median yields `complete: false` and no flags. Do not interpret empty flags with `complete: false` as healthy repeats.

## Verification

Initial red: `bun test test/pages/TaskInsights.test.tsx` in `ui/` failed because TaskInsights did not exist. After implementation, the dedicated file passes 11 tests; combined Task and TaskInsights checks pass 40 tests. Coverage includes measured outcomes, selectors, incompatible dataset fingerprints preventing comparison, bounded binary-field discovery after an unscored first row, unknown metric source fingerprints, API errors, bounded rows, selected filter payload, backend panel errors, unknown totals, and scope changes hiding stale rows. Helper tests verify measured +21% and reject incomplete, duplicate, or unknown-fingerprint coverage.

Backend worker is adding a real two-run table/source=samples/filter.run_id regression to verify server scope and total. Full checks and browser wiring are owned by parent.

## Latest evaluation attempt guard

Independent review reproduced a later wildcard metric error leaving old successful records and a per-example file readable. Compatibility now selects the newest timestamp for the exact metric/version before checking errors, usable scores, and source fingerprints. Any error in that attempt blocks comparison. A later successful attempt recovers without treating older source hashes or failures as current evidence. Focused TaskInsights verification: 14 tests pass / 28 assertions; wildcard-red.txt records the three failing regressions before the fix, wildcard-green.txt the passing final result. Task.tsx was unchanged in this follow-up.


## Authoritative per-example binding follow-up

A successful aggregate-only reevaluation can leave an older per-example file, so a healthy latest score/source alone is insufficient. TaskInsights now requires a consistent nonempty `per_example_hash` and `evaluation_ids_hash`, with positive safe-integer `evaluation_examples`, on the latest healthy metric/version attempt. Unbound latest records block before any predictions probe or comparison. Reevaluate legacy/unbound runs to establish new evidence; missing dataset identity remains a separate incompatibility.

The component requests `require_bound=true`. `api.compareExamples` accepts that opt-in as a sixth argument after its optional signal; `useCompareExamples` exposes `opts.requireBound`, with a distinct cache identity. Default arguments and the legacy Examples request/cache shape remain unchanged. Strict API errors remain visible and never trigger fallback to an unchecked comparison.

The backend strict branch validates current evaluator-issued artifact bytes and full ID/count bindings, requires complete binary outcomes and matching project/task/dataset/source, then compares the exact shared ID intersection of independently complete cohorts. It rechecks file, score and run snapshots to reject observed concurrent changes. The backend worker owns its implementation and tests.

Verification after the follow-up: three new initial regressions failed (`bound-red.txt`); client/query/TaskInsights/legacy Examples focus passes **91 tests, 324 assertions** (`bound-green.txt`). Added cases cover aggregate-only latest success with an old artifact, invalid counts/conflicting output bindings, strict server rejection without fallback, URL opt-in and cache separation. Backend strict focus **16 passed** and affected query/API **105 passed**, with Ruff/format/ty checks green. Earlier browser80/fullUI1081 receipts predate this follow-up; parent owns updated combined schema/build/UI/backend/docs checks and independent strict review.
