# Phase 3 plan review round 4

Scope: document-only corrections to the contract and backend/frontend implementation plans. No phase-3 source implementation or external service operations. Reviewed baseline: phase-3 plan commit `58f074a`; final main-baseline refresh remains a later queue step.

| Finding | Failure scenario | Resolution | Planned regression |
| --- | --- | --- | --- |
| P1: MCP caller can inherit server token | Middleware accepts a cookie after unusable bearer; the tool forwards no token and `hub_call` discovers the server credential | Preserve middleware-selected credential in private ASGI state; propagate explicit no-discovery through real `hub_call`, including Task 41 replacement | Registered stop/get/cancel/extend tools through `AuthGuard`, inspect actual outbound headers for bad/empty/NBSP bearer plus cookie and no-credential HTTP |
| P1: cleanup misses input aliases | Relative checkpoint or symlinked parent differs textually from the recorded artifact | Normalize against run cwd; resolve reader targets and artifact parent aliases only on owning environment; remote read-only preflight plus locked delete recheck | Local/remote planning and apply, reader added after plan, relative/parent-symlink/leaf-symlink inputs, leaf-only deletion retained |
| P2: task percent export mixes units | Fraction primary scales latency by 100, or number primary leaves accuracy unscaled | Per-column formats supplied by `task_table`, applied to groups, dispersion, intervals, and baselines | Both primary choices plus configured metric-unit integration |
| P2: partial sweep notice is lost | Last existing member ends while issuance lock is held; later launch fails without another terminal event | Atomically persist deferred trigger before cursor advances; retry every scan and across restart | Restart under issuance lock, release without new event, exactly one partial notice and empty pending state |

## Verification

- [x] Update all affected planned call paths and contract shapes.
- [x] Add targeted regression cases to the implementation tasks.
- [x] Validate changed executable snippets and run focused in-memory probes.
- [x] Check document diff; commit the plan changes as the final local step.

Validation used the existing local Python environment with `uv run --no-sync python /tmp/validate-p3-round4.py`; the probe extracts the revised document functions and applies the MCP forwarding edits to the reviewed baseline in memory. All changed Python blocks parse (indented replacement fragments are dedented for this check). Changed Python snippets were formatted with Ruff. The focused probes passed: both export primary choices with group/baseline dispersion, all three input alias forms, remote owner preflight plus unavailable-check refusal, 16 guarded registered-tool/header combinations plus four no-credential calls, and notifier replay after restart/nonterminal events with no new ending. `git diff --check` is the document whitespace check. These probes use temporary files, stubs, and in-process request transports; they do not connect to real hosts or services.

Assembled phase-3 pytest/ruff/type/API/UI suites remain implementation acceptance checks; this review does not claim they ran. The final baseline refresh must use phase-3 schema version 4 after main takes the audit schema version 3. Step-9 default-token interfaces remain pending and must be reconciled from their final implementation.
