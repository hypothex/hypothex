# Phase 3 current-main refresh and ordered review gates

Date: 2026-10-06. This report supersedes the earlier baseline's current-status
claims without rewriting its historical evidence.

## Revisions and authorization

- Historical plans head: `4392c8b90f96a23b6d35477520f86ebf45075bb1`.
- Historical October 6 source baseline: `a4441256f39d014d9ad43dea976af1b448f163e3`.
- Current source baseline: `f6f130cfa2669bfcccbadcb36282dd5fea881d1f` (PR26; see October 17 update below).
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


## 2026-10-16 moved-main refresh (ready for renewed primary review)

Current main e73b810 includes UI v5 and SQLite schema 4. The plan branch was
synchronized at 1987f72; no Phase 3 runtime code was added. Refreshed plans
must use schema 5, retain current run names/search/query interfaces and metric
direction precedence, and cover both pinned schema-3 and schema-4 upgrades.
Backend/frontend writers have completed their owned documents; the parent is
integrating them while an independent adversarial diagnostic uses the immutable
pre-refresh input. Renewed primary and final adversarial approvals are still
required on the completed refresh.

The backend writer reproduced the prior cleanup concern using exact pre-refresh
helpers in disposable homes: after parent replacement with a protected-run
symlink, the policy rejected the new path but the old remover still deleted
run.yaml, metrics and scores. The revised private remover pins no-follow parent
descriptors and never falls back to absolute-path deletion. Its bounded probe
preserved all nine protected metadata cases across before-pin, after-recheck
and syscall-boundary windows. Parent inspected the probe and receipts and
verified all twelve extracted helper hashes still match the current plan.
Directory artifacts, missing capabilities, descriptor cleanup and full plan/apply
regressions remain implementation acceptance requirements, not completed tests.

The exact WebSocket receive-loop probe demonstrated zero receive invocations
with the former zero-second test interval; the positive 0.01-second test interval
consumes subscribe. Production remains thirty seconds; tests require bounded
ASGI/subprocess deadlines. This is an extracted loop test, not an assembled hub.
The alleged USER=alice privilege escalation is not substantiated: mint_local
requires an existing enabled admin, so that collision fails closed.

Current UI ownership DTO additions are RecentRun.owner and TaskRun.owner; group
owners derive from members. Mine uses the runs API with owner=me/status=running.
The contract also records current-main rename scopes, names/search, tri-state
metric direction and PostgreSQL cache/overview portability requirements.

Durable evidence and task receipts:
/Users/shreyasv/Desktop/code/hypothex-phase3-evidence/2026-10-16/.
No final refreshed-plan approval or Phase 3 readiness is claimed yet.


Frontend/backend coordination found that a path-only cleaned marker cannot
distinguish a host source from a same-path pulled copy on the hub. The contract
now adds optional CleanedArtifact.environment_id: new entries always copy the
deleted CleanItem's target environment, including host-response merges. UI
matching uses environment plus raw path; legacy null identity is not inferred.
The plan adds same-path/different-environment and legacy regression coverage
and permits the additive JSON field. This does not change SQL schema 5.

### Parent integration receipt

Both refresh tasks returned completed results with no pending children. Parent
read all26 frontend tasks, the backend refresh diff/all49 task inventory and
Task49 changes. Verified all three submitted plan hashes, all17 backend evidence
hashes, all51 frontend source hashes and all12 final cleanup-helper hashes after
the environment fix. Runtime/source/UI/tests/workflows/dependencies are still
byte-identical to e73b810. The contract's frontend section now uses UI-v5 owners,
accessible labels and current route/DTO behavior; historical mockup geometry,
selectors and illustrative totals no longer override current acceptance.

Final backend delta evidence is 9 failed/11 passed before and20 passed after,
covering SQLite migration metadata/schema5, direction precedence, the PG-shaped
cache key, active-admin mint guards and deletion-target environment. The race
red contains three actual old after-recheck interleavings, not nine distinct
windows; all three delete protected metadata. Green contains nine distinct
before-pin/after-recheck/at-unlink cases preserving protected bytes. The earlier
description of nine green cases is unchanged. These are bounded snippets, not
assembled storage/HTTP/PostgreSQL/package validation.

The parent found one small frontend helper mismatch: the requirement allowed
trailing directory separators, but the proposed matcher missed an exact path
when the marker ended in a slash. Its planned code now strips trailing separators
without resolving aliases and still rejects the root. The original worker freeze
receipt is retained; the parent revision supersedes that frontend hash. A fresh
extracted Bun test passed all12 assertions (the original9 plus trailing-slash,
repeated-slash and root cases). Evidence is `parent-cleaned-marker.test.ts` and
the parent integration receipt in the durable evidence directory. No product
code or repository tests were implemented by this correction.

The independent diagnostic is complete. Its response is recorded below before
freezing/pushing the full review input. Obtain renewed Claude LGTM followed by
independent adversarial LGTM on the same final revision. Neither writer's READY
verdict nor the old-input diagnostic satisfies those gates.

### Response to the 2026-10-16 independent diagnostic

The diagnostic returned NOT LGTM on immutable1987f72 (old plans plus current
main), with two P1 and seven P2 findings. Its full report/coverage/probes are in
`adversarial-diagnostic/` under the durable evidence directory. Parent read the
report, all49/26 coverage ledger, reproduction instructions and integrity receipt.
All findings are accepted as defects in that reviewed input. The responses below
describe authored plan corrections; they are not independent acceptance of the
new revision or claims of implemented behavior.

| Finding | Correction in refreshed input | Evidence and remaining acceptance |
|---|---|---|
| F1 P1: parent-swap metadata deletion | Backend22 pins no-follow parent descriptors, rechecks policy/identity and removes fd-relative without fallback; contract1.9 and backend31 propagate it. | Exact snippets: red3 protected-file deletions; green9 protected-file preservation cases. Planned public apply/env-route, directory/leaf/replacement/capability/leak tests remain mandatory. MCP has dry-run/report only, never destructive apply. |
| F2 P1: schema4 collision/missing name | Backend4/34/35/36 and package49 advance to5, retain name/index and all current fields; separate authentic schema3 and schema4 fixtures. | Exact migration versus extracted current metadata plus intended deltas has no SQLite differences. Real old-home/wheel/restart/reindex and PostgreSQL metadata checks remain mandatory. |
| F3 P2: zero-timeout subscribe starvation | Backend26 uses positive0.01 test interval and bounded ASGI/subprocess completion; production30 seconds unchanged. | Old receive0 versus revised receive1 in bounded loop probes. Full revocation/filter/cursor lifecycle tests remain mandatory. |
| F4 P2: scope inventory/rename forwarding | Backend5/24/27/28/32/33 includes task-runs read and name/rename_run launch; rename passes request to forward and uses caller receipts. | Exact current route/call reviewed; scoped read/launch/admin/host, reset, forwarding and revoked-session cases required by contract9 and task matrices. |
| F5 P2: hosts/queue public shell | Backend23 retains both paths and optional trailing slashes; frontend7 preserves exact path shapes and full-load pair exception. | Current-source route anchors checked. Default-token/scoped GET/HEAD/POST with/without installed UI and reserved-path rejection remain required. |
| F6 P2: q search removed | Backend27 retains search Query(alias=q,max_length=200) and search forwarding alongside owner/status/paging. | Exact replacement inspected; contract9 explicitly requires q-only, combined, no-match, overlong, literal wildcard and rename-refresh cases. |
| F7 P2: obsolete UI integration | All26 frontend tasks reassigned to current shell/Home/task/run owners; FilesTab/FileList/checkpoint table plus retained selected/training surfaces receive cleaned metadata. | 51 source anchors/hashes checked; full v5 browser/component/type/build acceptance and installed UI are still required. Environment+raw-path cleanup matching adds source/pulled disambiguation. |
| F8 P2: conflicting direction helper | Backend12 reuses key_higher_is_better, handles taskless unset as higher and rejects only differing effective directions; current primary_field/config_format2 preserved. | Twelve direction cases in bounded matrix; assembled selected-primary export/goldens/best marks and panel checks remain required. |
| F9 P2: PG cache path access | Backend34 adds secret-free per-Index cache_identity+generation for both names/board caches; SQLite device/inode identity retained; overview JSON query made portable. | PG-shaped key probe passes without a path; backend36 requires real PostgreSQL names/taskRuns/overview/panels/reopen/rebuild/invalidation and concurrent recovery. |

The diagnostic independently rejected the mint_local escalation allegation;
the existing enabled-admin guard is retained and tested. No change widens it.
Notebook chip labels remain the explicit NotebookDay API hypothesis-clause/id
contract; current RunPage names are preserved separately. The frontend wording
was clarified so it cannot invent a different chip-label policy. No additional
unresolved design choice was assigned to the user.

Reviewers must independently reassess all nine responses and the complete plan,
especially the descriptor-removal boundary and compressed UI-v5 implementation
instructions. Historical probe files that vanished are not current evidence.
The eleven diagnostic tests confirm old defects/disputed claims only; the
writer/parent probes validate limited new snippets, not assembled Phase3.


### Renewed primary refresh R1 response (2026-10-16)

The independent Claude review of ebb06c9 returned NOT LGTM with one blocking
P2-1: `_open_cleanup_parent` requested O_RDONLY on every ancestor and therefore
rejected valid search-only project paths. All F1–F9 responses above were accepted
as plan corrections. Original report/coverage/probes are retained in the durable
`primary-refresh-r1/` evidence directory; this response does not change its verdict.

Accepted P2-1: Task22 now prefers O_PATH, then O_SEARCH, then conservative
O_RDONLY for ancestor pins while retaining O_DIRECTORY/O_NOFOLLOW and every
identity/policy/dir-fd check. Directories actually enumerated remain readable.
Non-root Linux/macOS cases cover file/directory artifacts below mode0100/0300
ancestors, writable search-only immediate parents, conservative fallback and
all existing race/refusal/leak regressions. Copied exact-snippet probes reproduce
four failures before the fix and pass20 tests after it, including19 removal
observations and a receipt writer. All protected bytes survive and descriptor
deltas are zero. Nine additional parent-swap cases pass. MacOS O_SEARCH was
executed; Linux O_PATH was documentation-checked only because Docker is absent.
Full application and real non-root Linux acceptance remain prospective.

Nonblocking P3 dispositions: extend the existing UI_ROUTE constant and retain
its public_static use/comment; retain the already-present Field import; clarify
that the final syscall race requirement concerns a parent swap, without claiming
atomic leaf identity. Existing notebook-label and exact-byte-confirmation
contracts were accepted and are unchanged. Sweep cost source is relabeled to
current e73b810 (code unchanged), and old /tmp evidence is marked historical.
The SPA regex probe still admits current/new known routes and rejects forbidden
ones after moving the definition into the existing constant.

The review coverage ledger used R4 evidence for unchanged tasks. The next
primary round must inspect their full task instructions and cross-task fit in
the current plan as well as rechecking the new correction, and state precisely
what was read, executed or reused. No historical LGTM substitutes for approval
of this final plan. The ordered independent adversarial gate remains pending.


### Renewed primary refresh R2 response (2026-10-17)

Claude read every backend task in full, including previously unchanged tasks,
and returned NOT LGTM on8737bc4 with one P2-A in Task42. The plan's replacement
of `list_runs_cmd` discarded current-main hub merging, `host_state` JSON,
disconnected-host status text and local time display. A bounded partial assembly
of the exact old replacement fails three existing tests that pass on unchanged
main. The parent accepted this concrete regression. Full report, all49/26 scope
ledger, applied diff and test logs remain in durable `primary-refresh-r2/`.

Correction: extend the current function additively. Preserve existing hub-read
credential resolution, merge and hub duplicate precedence, newest-first order,
final limit, JSON status metadata and formatted text. Add the owner option,
resolve `me` through the configured hub only for the local index, and forward
raw owner to the hub. No separate login-only runs branch is needed. Current
contract section4 explicitly preserves these behaviors and requires both the
original regressions and dedicated local/merged owner cases. The Task12 test
also imports its called `task_table`; the tracker labels the old a444125 status
as historical. Exact correction evidence is retained separately in durable
`parent-primary-r2-cli-fix/`. The additive replay passes6 original regression/
snapshot tests with unchanged assertions and expected keys. With actual owner
SQLite plumbing,7 owner cases and3 credential-resolution probes pass. The latter
execute the exact Task41 resolver but fake login persistence and HTTP transport;
real loopback/scoped-login acceptance remains mandatory in `test_auth_cli.py`.
Parent inspected the replay/prerequisite diff, verified all10 evidence hashes
and the exact planned test fence against the executed file. Ruff, formatting and
ty checks pass for the harness; Task12 import correction is static only. The
stale fixed Task42 auth-test count was removed because the test set grew.

R2 independently verified R1's cleanup correction in four non-root environments:
macOS Python3.11/3.14 and Linux Python3.11/3.12. Each passed23 exact-snippet tests
(including a receipt writer), with22 removal observations, intact protected bytes
and zero leaked descriptors. Parent read the added boundary cases and logs and
verified all12 helper hashes in every receipt against the actual plan. This
closes only the prior Linux snippet-execution gap. It does not establish full
storage/API/host integration. The local VM was stopped after the review.

All nine original diagnostic resolutions and the mint_local allegation rejection
remain intact. R2's type-aware migration probe reports zero differences; route,
MCP and frontend inventories remain covered. Full PostgreSQL/wheel/browser and
assembled Phase3 acceptance are still future implementation requirements. The
six CI checks passed on8737bc4, including the previously failing UI job; CI is
not approval of future runtime behavior. A new primary verdict is required on
the corrected frozen input, followed by a new independent adversarial verdict.


### Independent adversarial gate R1 response (2026-10-17)

Claude primary R3 returned LGTM for c9ea398; all six CI checks passed that
revision. The subsequent independent adversarial review returned NOT LGTM
with one P2/A1 in Task 1's PostgreSQL test guard. The guard checked explicit
connection arguments but ignored inherited libpq defaults. An explicit local
host with external PGHOSTADDR, or a hostless connection with external PGHOST,
reached the intercepted psycopg connection boundary. An explicit service also
reached that boundary unresolved. The probe stopped before entering the
connection generator, so no external database was contacted; service-derived
destination resolution was not executed. The finding is accepted.

The complete independent report and all 49/backend, 26/frontend, 13-scope coverage remain in
durable `adversarial-gate-r1/`. Its33 passing diagnostics include five tests
that assert the old guard's behavior, including the bypasses; passing those
tests is evidence of the blocker, not approval. Previous F1–F9, cleanup and
CLI corrections remain satisfactory. The two nonblocking wording nits in the
tracker and historical schema paragraph are corrected in this revision.

The correction is confined to the planned test harness and subprocess
acceptance. Production PostgreSQL configuration support is unchanged. Both
ordered independent review verdicts must be renewed on the corrected final
plan before implementation. Full PostgreSQL, installed-wheel and assembled
application acceptance remain future implementation requirements.

Correction: Task 1 now scrubs every PG-prefixed default at session/per-test
setup and rejects any nonempty reintroduced default at connection time, exposing
names only. Explicit service selection is refused. Public psycopg parsing
preserves keyword precedence and ignored None values; every host/hostaddr is
validated, localhost names are pinned numeric, and absent/empty hosts use the
deliberate test-only /tmp Unix directory. Explicit absolute socket paths remain
valid. The Task 36 shared run_cmd helper filters after its actual final environment
merge; a sanitized override alone would have reintroduced ambient variables.
Task 39 launchers and Task 49's installed-runner requirements use the same final
filtering rule. Child processes do not inherit the parent's Python guard.

Durable `parent-adversarial-r1-pg-fix/` contains exact old/final guard copies,
reproducible probes and locked dependency/source receipts. The57 passing parent
tests comprise 53 corrected-behavior/proof checks, 3 deliberate old-bypass
reproductions and 1 receipt writer; the bootstrap check also runs 2 passing child
tests. Tests cover every safe multihost attempt, precedence, aliases/Unix paths,
services/defaults, idempotent installation and actual child-environment
construction. All connection probes install an inert driver boundary before
invocation, with DNS/socket tripwires; no database connection occurs. Ruff,
formatting, ty and the evidence project's Sphinx build pass. Parent read the
complete test source, changed snippets and final logs, verified 33 artifact hashes,
and matched old/final guard copies to the exact plan fences. The package runner
regression is prescribed acceptance, not executed here. This closes the bounded
A1 proof obligation; independent approval and full runtime acceptance remain
pending.

### Primary R4 response and baseline UI correction (2026-10-17)

Primary R4 approved 1a81663 against e73b810 with one nonblocking P3. Its
empty-PGSERVICE probe demonstrated that empty values can still select a service
section. The accepted correction rejects every present PG-prefixed variable,
including empty values. The exact final guard passes 26 behavior checks; an
additional old-guard reproduction and receipt test bring the total to 28.
Parent-verified evidence and full limitations are recorded in
`tasks/phase3-execution.md` and durable `parent-r4-verification.json`.

A separate baseline UI patch addresses the reproduced selected-run viewport CI
failure caused by late chart layout growth. Its review and CI are independent
of Phase 3 approval. Once merged, update the baseline and renew the ordered
primary/adversarial reviews on the same final plan revision. R4's LGTM does not
cover the subsequent empty-default correction or a future baseline update.

### PR26 merged; renewed frozen input (2026-10-17)

PR26 merged as f6f130c after all six checks passed exact head eb503ee. Independent
local review returned LGTM and GitHub Codex review completed with no findings.
The baseline delta contains only SelectedRun's initial reveal lifecycle, its unit
and delayed-response browser regressions, user documentation and its tracker.
The parent inspected the complete diff and retained review/CI/merge receipts in
`ui-selection-ci/`. Local evidence is 1,414 unit tests, 122 full browser tests,
12 repeated focused browser cases, build/type checks, Sphinx and all three demo
shutdown modes. This is baseline UI evidence, not Phase 3 runtime acceptance.

The plan checkout merges f6f130c at 86e0336 and retains the accepted empty-PG
correction from b6cc9eb. Contract/frontend Task24 explicitly preserve observer
cleanup, user takeover, focus restoration and delayed-layout regressions when
adding cleaned-artifact markers. All 51 frontend source anchors were rechecked;
only SelectedRun's blob changed. No backend source, dependency, workflow, schema
or API changed. The immutable schema-3 a444125 and schema-4 e73b810 fixture pins
remain unchanged. Runtime/source/UI/tests/dependencies/CI in the plan checkout
are byte-identical to f6f130c; the refreshed plan adds no runtime functionality.
Fresh evidence: durable `post-pr26-refresh/` and `final-review-input.json`.

Freeze and submit this complete input for primary Claude R5, then independent
adversarial R2 on the same hash after LGTM. R4 approved the preceding input only;
no final adversarial approval or implementation authorization is claimed.
