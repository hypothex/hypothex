# Step 7 API and durable sweep issuance

Branch `dogfood-fixes-2`, based on merged main `55ca922`. Implement the frozen
`/tmp/hx-handoff-evidence/dogfood-integration/step7-api-core-readiness-refresh.md`
and complete crash/cancel matrix in `df48-design.md`. Every behavior change starts
with a failing regression. Evidence goes to `/tmp/hx-handoff-evidence/step7-api/`.

Ownership: this worker owns API app, core events/sweeps/queries/errors, new issuance
module and their tests. CLI/MCP/headlines belong to backend_audit; lifecycle
records/control/execution/slurm/demo/scheduler to security_review; UI to ui_audit;
parent owns docs and tasks/todo. No real hosts, Phase 3 work, commits, pushes,
full suites, Docker or browser without parent coordination.

- [x] DF-34/33/37: verified current/offline host identity, served/routing boundary,
  configured SLURM defaults; preserve historical provenance and totals.
- [x] DF-22/49/54: reinfer vars transport, batched conditional queued-stop endpoint
  and forwarding, structured synchronous incomplete-launch error.
- [x] DF-61/65: bare MCP endpoint protocol/auth, failed-pull destination cleanliness.
- [x] Durable store/models: additive guarded events.db table, immutable receipt +
  queued transition + event transaction, typed issuance read models.
- [x] Acceptance and resume: typed recoverable preparation, stable bound definition,
  legacy claim 409, same-key concurrency, exact options/pin, active conflict.
- [x] Single bounded dispatcher: cross-process ownership, interruption/restart,
  mirror settlement without reissue, safe worker error and shutdown ordering.
- [x] Cooperative cancellation: durable intent, zero-run cancellation, drain
  in-flight call, conditional stop newly returned member, ambiguous outcome recovery,
  repeated cancel replay, explicit resume only after the episode completes.
- [x] API lifespan/routes and client contracts integrated; exact frozen fields/event
  shared with UI and CLI/MCP owners; direct core semantics retained.
- [x] Focused regression/static verification and checkpoint review. Parent decides
  when to start whole-repository integration checks.

Required retained regressions: member count includes existing cells after the failing
request; missing dirty patch refuses resume; scheduler tickets remain immutable and
API positions live; local repo identity gate, exclusive host ownership/alias transfer,
and generic run_once interrupted-claim behavior remain intact.

First checkpoint: 8 host-contract failures reproduced, then passed. Action/transport
tests reproduced 11 more failures; staged-pull helper tests reproduced 3 failures.
The composed host/API/SSH subset passes 120 tests. HTTP pulls now use the same
trusted staged/transactional install as SFTP; mid-stream failures leave no final
destination parents. No real hosts were used.

Durable store tests cover original-request preservation/shared receipt namespace,
receipt+queued+event atomic commit, transaction rollback, stale revision CAS, and
unknown schema preservation; all 18 new/existing events tests pass. Typed issuance
summary/list reads have a separate RED/GREEN regression. Acceptance coordinator, worker and async routes are implemented; the initial composed
acceptance/worker/store API subset passes 26 tests. The expanded real process-death,
receipt namespace, pin/resume and HTTP lifecycle matrix remains in progress.

Coordinator evidence includes four metadata crash boundaries, owned empty reservation
recovery with malformed nonempty file refusal, immutable same-key responses, legacy
409, active extension conflict, worker exclusivity, shutdown drain, mirror lag, zero-run
failure, cancellation before dispatch/during launch/queued-to-running/ambiguous outcome,
and two final-transition cancellation races. All scoped evidence files are under
`/tmp/hx-handoff-evidence/step7-api/`; no full suite was run.

Source freeze checkpoint: asynchronous create/extend and lifecycle wiring are complete.
Known pre-request transport failures use a conservative typed outcome flag; ordinary
launch failures are explicitly resumable, and ambiguous cancelled attempts remain
settling. Returned IDs and unresolved admissions survive every explicit episode
handoff. Cancellation of incomplete/interrupted episodes reconciles their retained
outcomes under exact-episode CAS, including zero observed members. Independent
reviewers reproduced and verified both the resume-cancel and direct interrupted-cancel
fixes, plus a three-episode/different-cell/out-of-order mirror probe.

Explicit HTTP folder pulls now require every nested transfer to complete before
transactional installation; mirror transfers retain their best-effort default.
Independent validation covered child 404/413, advertised/streamed oversized files,
nested failures, malformed listing JSON, outside paths and negative sizes.

Scoped Ruff, ty and diff whitespace checks passed at freeze. The composed affected
suite finished with 529 passed and two remaining synchronous-response test
expectations. Those forwarding tests now poll current GET and retain their original
security/GPU assertions; the complete forwarding module then passed all 17 tests.
Two additional focused zero-run restart tests passed for implicit and explicit pins,
nondefault queue=False/GPU/hypothesis/task/agent options, checkout mutation and
immutable receipt replay. Production behavior stayed frozen during these test-only
changes; unchanged composed passing evidence was reused.
No whole-repository tests, Docker, browser, commits, pushes or PRs were run by this
worker. Parent has started its separately coordinated integration checks.

Final atomic admission correction: extension preparation now verifies the latest
previous operation key/revision and terminal state in the same events.db transaction
that inserts the new episode and claims its receipt. A cancellation that wins after
extension's read but before insertion rejects extension with active conflict and no
claimed extension key. Deterministic RED/GREEN test added. Final affected set (core
issuance/store/crashes/events and HTTP acceptance) passes 75 tests in 11.49 s;
Ruff, ty and format checks pass. Runtime refrozen, parent notified for final integration.
