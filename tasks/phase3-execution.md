# Phase 3 implementation and verification

User direction (2026-10-06): obtain a primary review followed by an independent
adversarial review. Start implementation only after both return LGTM on the final
plan. The user expects to test the result later this week; installation and
integrated workflows are acceptance requirements, not just unit-test totals.

## Baseline and scope

- Plan branch: `p3-plans`, initial head `4392c8b90f96a23b6d35477520f86ebf45075bb1`.
- Pre-gate main: `f6f130cfa2669bfcccbadcb36282dd5fea881d1f` (UI v5 with PR26 viewport fix).
- Implementation base: merged plans head `244d55f9c3be775b8c335bb258bbe9d5858ef83e`.
- Plan PR (merged): https://github.com/hypothex/hypothex/pull/22.
- Authoritative scope: the Phase 3 contract, backend/frontend plans and mockups
  under `docs/superpowers/plans/` and `docs/mockups/phase3/`.
- Preserve all 13 contract scope items. Reconcile the later backlog and final
  Examples changes with planned replacements before treating the plan as ready.
- Existing review rounds 4–6 and their bounded fixes are prior evidence, not the
  two approvals requested now. New material plan changes require re-review.

## Gates (cleared 2026-10-17)

- [x] Primary R5 full-plan LGTM on `2ebfc28` against `f6f130c`.
- [x] Independent adversarial R2 full-plan LGTM on the same input.
- [x] Parent inspected reports, coverage and probes; verified all 38 primary and
  26 adversarial artifact hashes and all eight live plan input hashes.
- [x] All six CI checks passed that exact plans head.
- [x] PR22 merged as `244d55f9c3be775b8c335bb258bbe9d5858ef83e`.
- [x] Implementation started in `/tmp/hx-phase3-implementation`, branch
  `phase3-implementation`; the user checkout remains untouched.

These gates approve implementation of every scope item, not runtime completion.
The optional UI documentation paragraph preservation is carried into frontend
implementation. Detailed receipts remain in the durable evidence directory under
`primary-refresh-r5/`, `adversarial-gate-r2/`, and the corresponding parent
verification JSON files. Fresh review probes: primary 73 guard tests plus two
bootstrap child tests; adversarial 67 probes. Reused evidence is hash documented;
assembled, installed-package and Docker acceptance remains required below.

## Active ownership and progress

| Tasks | Owner | State |
| --- | --- | --- |
| Backend 1 | isolation worker | 244 guard + 23 loopback tests pass; parent reviewed guard/source receipt |
| Backend 2–4 | settings/owners worker | 70 focused + 263 regressions pass; source handoffs complete |
| Backend 5–7 | auth foundation worker | 99 focused pass; parent inspected auth contracts/client and found/fixed duplicate test package init |
| Backend 8 | parent | 20 notebook tests pass, including concurrent writes/conflicts; docs complete |
| Backend 9–12 | papers/export worker | 114 focused + 262 regression tests pass; five golden outputs |
| Backend 13–19, 30 providers | notifications worker | 257 scoped tests pass; final notification suite 115 pass after independently verified partial-recipient fix |
| Backend 20–22 | storage worker | Final 273 affected tests and 27 independent probes pass; excluded overlaps, shared ownership, alias races and exact remote confirmation corrected |
| Backend 23–31 | API worker | 385 API/core tests pass; final 138 affected receipt tests pass; independent actual launch retry executes once |
| Backend 32–33, MCP 41 | MCP worker | 197 MCP tests pass; new tools and existing regressions |
| Backend 34–36 | Postgres worker | 13 actual PostgreSQL Docker tests, 305 core/remote and 252 evaluator tests pass |
| Backend 37–44, CLI 35 | CLI/remote worker | 232 CLI tests and 14 lifecycle tests pass; selected-home isolation fixed; pairing leak 15 red/green plus nine independent probes pass |
| Backend 45 | parent + CLI adapter owner | 47 final demo tests pass; actual shared-host launch/stop verified with an independent generated repository |
| Backend 46 | parent + feature docs owners | Pages/skill/index integrated; final Sphinx warnings-as-errors passes; populated additive JSON snapshots verified |
| Backend 47 | parent | Final assembled scan passes with successful API/CLI/channel operations and scrubbed child environment |
| Backend 48 | acceptance worker | Four actual subprocess/HTTP/MCP acceptance scenarios pass, including 30-second WebSocket revocation and restart dedupe |
| Backend 49 | package worker | 21 harness tests and all five final installed checks pass; 20 browser executions; genuine schema-3/4 upgrades; exact wheel/source hashes verified |
| Frontend 1–8, 24–26 | UI integration worker | 1510 Bun tests, typecheck/build pass; 122 existing browser tests plus final 28 affected tests pass; six screenshots verified |
| Frontend 9–23 | UI features worker | Leaf screens complete; export/cleanup accessibility and notebook concurrency regressions pass in final full UI suite |

Counts are scoped evidence from their recorded revisions; overlapping runs are
not additive totals and do not yet establish final whole-application acceptance.
Parent JSON snapshots exercised populated owner/baseline/cleanup values: observed
only intended additive paths (plus host token_env and sweep cost_complete), with
zero removed baseline keys; final rerun is recorded in implementation evidence.
The parent started the previously stopped Colima default VM for authorized Docker
checks using --activate=false --ssh-config=false --ssh-agent=false --save-config=false.
All Docker commands used its explicit socket. After the 24 passing Docker tests,
no containers remained running and the owned VM was stopped. Both existing
profiles are now stopped; the user's default context and SSH configuration were
not changed.

One writer owns each file. The parent owns shared docs/index, dependency files,
CLI JSON snapshots, this tracker, integration and final review/acceptance.
Implementation evidence is under the durable sibling `implementation/` directory.

## Execution after both review gates

- [x] Refresh the plans against main, preserving the accepted contract and scope.
- [x] Implement dependency-ready backend and frontend increments in isolated
  `/tmp/hx-*` worktrees, with failing tests first and one writer per owned file.
- [ ] Review actual diffs, run affected and required checks, link every PR, and
  merge only after all current-head CI checks pass. Retain PR branches.
- [x] Verify the complete collaborator pairing/shared-host/revocation workflow,
  notebook, baselines/exports, notifications/digest, storage protections,
  Postgres migration/rebuild equivalence, authenticated MCP and SDK cost logging.
- [ ] Verify fresh installation and existing-home upgrade behavior with synthetic
  homes, packaged UI assets, and a reproducible team demo on clean merged main.
- [ ] Run full local/CI acceptance, Docker fakes and light/dark browser checks;
  inspect screenshots and retain raw evidence, then verify owned-resource cleanup.
- [ ] Write a concise testing handoff with setup commands, version/commit,
  supported workflows, expected results and material remaining limitations.

## Final integration status (2026-10-17)

PR27 opened at `96ffd74932038e5ad0ce0789673436911026c0a9`. Its automated
review identified two additional storage defects: excluded overlapping artifacts
could be deleted, and shared-path deduplication omitted other runs' cleanup
bookkeeping. Both were independently reproduced and corrected. Cleanup now
preserves all selected associations, refuses excluded or newly added overlapping
bindings, and counts physical deletion roots once. The focused review additionally
found alias-retarget bookkeeping and remote byte-confirmation defects. Grouped
deletion revalidates member identity; remote preflight refuses mismatched lexical
and physical groups or removal roots. All 27 independent probes pass on storage
source SHA256 `c282d9969fb93667c7f43af42c3f0c27448cbd16cd1056154b33fb928adc1a0f`.
The final affected suite passed 273 tests, including seven real HTTP cases.
The focused independent review is **LGTM**, with all seven reviewed source hashes
and 22 evidence hashes verified by the parent. Its verbatim receipt is
`2026-10-17-hypothex-phase3-storage-review.md`, SHA256
`3419a0c1ad2fbeba4ce3108c30b084450db82283d4cc73eb7e7fa50b2d84b1ad`.
The shared-owner UI regression is included in 23 passing affected UI tests;
TypeScript, production build, Ruff, formatting, ty and Sphinx all pass.
The rebuilt final candidate passed all five installed checks in 181.40 seconds,
including 20 browser executions. Parent verified 108 source/resource hashes,
79 harness hashes, 104 wheel members, the forced skill and both archives.
Its wheel SHA256 is
`152593c58c0c52459e86a16f73ef8508c645b6428360990a34fc65a25140e3c7`.
All 12 owned servers and two tracked descendants were stopped; zero remained.
This candidate records the reviewed dirty source tree above the original PR27
head. It supersedes both older package candidates below. The previous
implementation LGTM below is historical evidence; merge remains pending
new-head CI, followed by the clean merged-main handoff.

The old `96ffd749` UI CI run exposed an intermittent delayed-chart test cleanup
race (`route.fulfill: Route is already handled!`). A staggered two-request probe
reproduced the failure and verified the correction: drain each callback promise
before unregistering interception. The selected-run assertions, retries, worker
count and timeouts are unchanged. The corrected test passed 20 focused executions,
then all 124 browser tests passed with CI's two workers and zero retries.
Application typecheck and diff checks passed. Parent inspected the fix and raw
receipts in `implementation/ci-ui-selected-run/`; all 108 package inputs and
79 package-test inputs still match the accepted candidate, so package validation
is reused. Hosted CI on the next pushed head remains required.

The old macOS Python 3.13 CI run exposed three further failure paths. Generated
host labels exceeded the API limit after adding their prefix; the complete label
now fits 64 characters. The demo webhook and SMTP test fixture implicitly called
reverse DNS during startup; both now use explicit local server identities.
Blocked-resolver probes reproduce the historical timeout mechanisms, though the
old runner did not capture resolver stacks. Failed SMTP fixture startup now also
releases its listener, thread and loop. The Python 3.11 matrix job was cancelled
by fail-fast after the 3.13 failure, as confirmed by its check annotation.
The affected CLI/demo subset passed 81 tests on isolated macOS Python 3.13;
notification/acceptance/secret-leak coverage passed 123 tests on each of Python
3.11 and 3.13. Seven independent guarded probes passed and the focused review is
**LGTM**. Parent verified eight reviewed file hashes and 13 evidence hashes;
the verbatim receipt is `2026-10-17-hypothex-phase3-macos-review.md`, SHA256
`821e8e976fbf3c1bc33f170750b13cc2c8e1124fc77aac228d6a067849897d49`.
Ruff, formatting, ty, Sphinx and the dedicated browser-test typecheck pass.
The fresh installed candidate passed all five checks in 180.85 seconds, including
20 browser executions. Parent verified all 108 build-input and 79 harness hashes,
104 source/resource members in both archives, and the force-included skill.
All 12 owned servers and two tracked descendants were stopped; zero remained.
The wheel SHA256 is
`2ca0042858da4e365e2331e7f2f78bee70f015559e3319cb7683363904e90e24`.
Evidence is `implementation/package/pr27-macos-final/`; the prior storage candidate
is historical evidence for its earlier source. Current-head CI and the clean
merged-main handoff remain required.

All 13 scope items are implemented. The independent whole-source review has no
remaining runtime findings after fixing duplicate execution on completed legacy
receipts and the browser device-name length mismatch. The final independent
verdict is **LGTM**, including the final installed-package artifacts. Parent
verified all 343 reviewed file hashes and all 28 evidence hashes. The verbatim
report is committed as `2026-10-17-hypothex-phase3-implementation-review.md`;
its SHA256 is `53029efdb2a25fdead262ac22e3ed44bf7281a6ce9a23fc94f9f8bc10015cdc1`.
Separate independent reviews
verified fixes for pairing-error secret reflection, protected pulled-copy deletion,
and partial SMTP recipient handling. Historical source hashes and probe limits
are retained in the durable evidence directory; earlier receipts do not silently
cover later source changes.

Local evidence includes 24 actual Docker tests (including 13 PostgreSQL cases),
1510 UI unit tests, successful TypeScript/production build, 122 existing browser
cases and 28 final affected cases, and passing Ruff/format/ty/Sphinx checks.
The full Python suite passed 3675 tests with 3 macOS-only `flock` skips and
24 deselections. This run excluded package-harness tests; the later legacy-completed-receipt change
has 138 affected tests and six independent probes. Final seven-job CI, merge,
and the clean-merged-main installed-package handoff remain required.
The installed candidate passed all five checks in 191.71 seconds, including 20
light/dark browser executions. All 12 owned servers and two tracked descendants
were stopped; zero remained. Its wheel hash is
`419c184c02562ee6eccd20b624a55060642735f83e4d98d0df35be047f9b345a`.
The candidate records a dirty source tree separately from base HEAD; it is not
a clean build of the base commit. Parent verified all 108 source/resource hashes,
104 packaged source/resource byte identities, the force-included skill, and both
archive hashes. The clean merged-main handoff remains required. Existing branches
and worktrees are retained.

## Boundaries

Both review gates passed as recorded above. Use uv, Ruff, ty, pytest,
Sphinx and Bun. Never edit tracked files or commit in the main checkout. Never
touch `~/.ssh` or connect to real SSH/SLURM hosts, Slack, SMTP, Tailscale or external
Postgres. Use loopback fakes and throwaway Docker containers. Real deployment,
real notifications and first public exposure remain separate user actions.
No attribution trailers or model/tool references in commit messages or PR text.

Historical review receipts and prompts used `/tmp/hx-phase3-evidence/`; that temporary location is not the current evidence source. The October 16 durable receipts are under `/Users/shreyasv/Desktop/code/hypothex-phase3-evidence/2026-10-16/` (outside source trees).
The historical entries below retain their original status at the time. The current
gate status and active work are recorded above; runtime completion is still pending.

## Historical review cycle before the October 16 main refresh

- Primary round 1: NOT LGTM, two P2 findings (stale main-source plan and
  incomplete cost shown as a complete total). The report also lists three P3
  corrections: JSON key snapshots, deleted checkpoint display and stale prose.
- The first review did not cover every backend/frontend task or mockup image.
  Its coverage list is carried into the next review; no historical review
  substitutes for the missing current coverage.
- Current corrections are limited to plans and mockups. The refreshed contract
  makes task export use the selected primary, rejects it for compare export,
  and preserves pricing completeness in run/sweep/digest output.
- At that historical point both approvals were pending against main a444125.
  The October 16 refresh and its renewed review cycle below supersede this status.

## Testing handoff requirements

Use a new synthetic home and a separate synthetic pre-upgrade home. Capture the
built wheel name/hash, merged revision, exact uv install and startup commands,
loopback URLs, pairing/login steps, restart/revocation behavior, artifact paths,
and expected results. Do not put synthetic tokens in committed reports.

Check the installed package outside the repository so imports cannot silently
use source files. Confirm packaged UI assets, Alembic files, help/docs examples,
and the team demo's fake channels/host. On upgrade, compare retained run and
score identities, binding metadata and SQLite rebuild results before/after.
Run browser acceptance for both fresh and upgraded states; record skipped or
unavailable environments explicitly. Stop only the test resources created by
this work and provide a concise user testing guide when implementation passes.

Correction verification complete for primary round 2 input: frontend 19 snippet
anchors and 25 blobs; backend extracted cost 29 failures to zero and export/sweep
nine failures to zero; plan/probe syntax, lint/type and diff checks pass. These
checks do not close either review gate or establish assembled runtime behavior.


Primary round 2 returned NOT LGTM after complete coverage. Prior P2 findings
were fixed; new P2s require protecting resolved run metadata under a symlinked
home, admitting exact new SPA deep links through the credential gate, and an
executable packaged-install/upgrade acceptance task wired into CI. Backend and
frontend plan repairs and the Task 49 supplement are in progress. No runtime
implementation is authorized until both review gates pass.

CI on frozen head 9cbe8a3: Linux, UI and Docker passed. Both macOS jobs were
cancelled without receiving a runner due to GitHub capacity constraints. The
two jobs were rerun on the same head (attempt 2); no code/workflow change was
needed. This is separate from the still-pending plan review gate.

Round 2 corrections are now frozen for primary round 3. Bounded verification:
90 cleanup and 120 guard assertions; frontend source/semantic probes; genuine
baseline schema-3 fixture with evaluator-issued bindings; concrete Task 49
pytest/CI owner and parsed snippets. Source implementation and installed Phase 3
acceptance remain pending. The native preview still cannot save the new mockup
screenshot; this is recorded as a nonblocking visual limitation.


Primary round 3 returned NOT LGTM on 4cbc5bb. All earlier blockers are fixed;
Task 49 introduced two new failures: runner context in job env and an owner
assertion dependent on inherited USER. Corrections move the env to its step,
pin only team child USER=sv, and document manual owner semantics. The full
before/after workflow was checked with actionlint 1.7.12; five focused tests
pass. Two minor prose/environment-sync issues are also corrected. No source
or workflow implementation changed. The detailed response is in main-refresh;
primary round 4 must approve before independent adversarial review.

The old 9cbe8a3 macOS 3.11 retry was also cancelled before acquiring a runner.
It is superseded by the current plans head; no old-head rerun is needed. PR22
remains watched for current-head results.


## 2026-10-16 recovery and moved-main refresh

Primary R4 approved e10e6ff against a444125; all six CI checks passed that head.
Neither interrupted adversarial attempt returned a final verdict. The planned
T3 restart was interrupted before launch, and temporary evidence later vanished.
No Phase 3 implementation was performed. This is an unfinished review cycle.

Recovered p3-plans in /tmp/hx-p3-plans and merged current main e73b810 without
conflicts at 1987f72. Current source/UI/tests/dependencies/workflows match main.
The immutable diagnostic input is /tmp/hx-p3-review-input at 1987f72. No tracked
file in the user's main checkout was edited.

Durable prompts, task IDs, recovered primary result, drift inventory and new
reports live at /Users/shreyasv/Desktop/code/hypothex-phase3-evidence/2026-10-16/.
Three app-owned tasks were launched: frontend-refresh, backend-refresh and
adversarial-diagnostic; each task.json records its exact taskId. Both refresh
writers have completed and frozen their files. The parent is reconciling the
contract and receipts. The diagnostic completed against immutable1987f72 with
NOT LGTM (2 P1,7 P2); all nine have responses in main-refresh and current plan
corrections. Neither diagnostic nor writer verdict approves implementation.

Main is already SQLite schema 4 with run names, literal search and new query
interfaces. Phase 3 must advance to 5 and retain genuine schema-3 and schema-4
upgrade fixtures. UI-v5 routes/components/tests must replace obsolete anchors.
The cleanup race and zero-timeout WebSocket concerns require fresh reproduction.

The refreshed draft was frozen and pushed at ebb06c9. Renewed Claude R1
returned NOT LGTM; the correction and next gate are recorded below. Only a
renewed Claude LGTM followed by independent adversarial LGTM permits implementation.

Parent integration verified all three worker plan hashes, all17 backend evidence
hashes, 51 frontend source hashes and all12 extracted final cleanup helper hashes.
Read all26 frontend tasks, the backend refresh diff and Task49 changes. The
contract now names current UI-v5 owners/routes, exact-byte confirmation,
environment-aware cleanup markers, Mine's one-section scope and both real
upgrade inputs. Runtime/source/UI/tests/workflows/dependencies remain identical
to e73b810. The parent additionally corrected the planned cleanup-marker helper
to trim trailing directory separators, with a fresh bounded snippet test; this
supersedes the frontend worker's hash and does not constitute runtime validation.


### Renewed primary refresh R1 and correction (2026-10-16)

Claude reviewed frozen ebb06c9 and returned NOT LGTM: one blocking P2 for
search-only ancestor traversal; no P0/P1. It accepted the nine diagnostic
corrections. Its report and coverage are under durable `primary-refresh-r1/`.
The parent accepted P2-1 and corrected the Task22 ancestor descriptor mode,
retaining no-follow/dir-fd/policy/identity safeguards and readable directory
measurement. Backend23 now extends the existing UI_ROUTE constant; redundant
Field-import and stale source/evidence labels were clarified.

Parent evidence is in `parent-primary-r1-fixes/`: before correction, four
file/directory permission cases fail; after correction, 20 tests pass (19
removal cases and a receipt writer), zero descriptor leaks, all protected bytes
intact. Nine additional parent-swap cases also preserve protected bytes. Ruff,
format and ty checks pass for the adapted regression harness. These are bounded
exact-snippet macOS probes; Linux is not executed because Docker is unavailable.
The plan explicitly requires non-root Linux/macOS behavior tests during
implementation. No assembled application acceptance is claimed.

Next: freeze this correction and request a new Claude primary round on its
exact hash, carrying the original brief and every finding/response. Then start
a new independent adversarial gate only if primary approves. No implementation
yet. CI on ebb06c9 had an unchanged UI-v5 viewport failure; the new docs-only
head's CI supersedes that head and must be green before integration.


### Renewed primary refresh R2 result (2026-10-17)

Claude reviewed frozen8737bc4 against e73b810, read all 49 backend and 26 frontend
tasks in full, and returned NOT LGTM: one blocking P2-A in Task42. Its complete
replacement of `hx runs` dropped current-main hub merging, host_state JSON,
disconnected-host status and local-time formatting. Existing main tests pass6
on unchanged main; the old plan's partial assembly fails3. The parent accepted
this defect and corrected Task42 additively, preserving the established CLI
behavior while adding owner filtering. The Task12 missing task_table test import
and historical-baseline label are also corrected.

The cleanup fix passed23 exact-helper tests in each of four non-root runtimes:
macOS Python3.11/3.14 and Linux Python3.11/3.12. Parent read the new cases/logs and
verified all12 helper hashes and22 protected/zero-leak observations in each
receipt. This supersedes the earlier snippet-level Linux execution gap; full
assembled cleanup/API/host acceptance remains prospective. Review evidence is
in durable `primary-refresh-r2/`. All F1–F9 remain accepted plan corrections.

CI on8737bc4 passed all6 checks (four Python jobs, UI, Docker); the earlier UI
viewport failure did not recur. Saved receipt: `ci-8737bc4.json`. No gate is
cleared by CI alone. After the CLI correction is verified and frozen, request a
new Claude primary review, then independent adversarial review on the same hash.


The corrected Task42 probe passes6 original remote/JSON-schema regressions with
unchanged snapshot assertions and data, then10 focused owner/token cases with
real SQLite owner plumbing and explicit fake hub/login/HTTP boundaries. The
parent inspected the replay script and minimal prerequisite diff, verified all10
evidence hashes and exact plan test-fence equality, and confirmed disposable
source cleanup. Evidence: durable `parent-primary-r2-cli-fix/report.md` and
receipts. Full real login/scoped-route acceptance remains mandatory. The parent
also removed Task42's stale fixed auth-test count after adding new integration
requirements; tests must all pass, rather than match an obsolete count.


### Independent adversarial gate R1 result (2026-10-17)

Claude primary R3 approved c9ea398 and all six CI checks passed that head.
The subsequent independent adversarial gate returned NOT LGTM with one new
P2/A1: Task 1 checks explicit psycopg host parameters but inherited PGHOSTADDR
can redirect an explicitly loopback connection, and PGHOST can supply an unseen
external destination. The exact guard reaches the intercepted driver boundary
with those external effective addresses. Service selection also reaches that
boundary unresolved; no service-derived connection was executed. No connection
generator or database was entered in these bounded diagnostics.

Parent read the complete report, coverage, exact guard probe and receipt. The
review independently covered all 49 backend tasks, 26 frontend tasks and 13
scope items; all previous fixes remain satisfactory. Its33 passing diagnostics
include tests that deliberately assert the defective guard behavior and do not
approve it. Evidence remains immutable in durable `adversarial-gate-r1/`.

The scoped plan correction is complete for effective PostgreSQL destination
checks and test/subprocess environment hygiene. Runtime implementation remains
gated. The changed final plan needs renewed Claude approval followed by a new
independent adversarial verdict on the same hash. The two prior nonblocking
wording nits are corrected with this material revision.

Task 1 rejects nonempty reintroduced PG defaults and service selection, validates
every host/hostaddr entry and pins local aliases/defaults. Tasks 36/39 and package
acceptance sanitize final child mappings after overrides; Task 36 explicitly
corrects the existing run_cmd helper's second merge. Exact proof: 57 parent tests
pass (53 corrected-behavior/proof, 3 old-bypass diagnostics, 1 receipt writer), plus
2 bootstrap-child tests. No real connection was possible through the intercepted
driver boundary. Parent inspected the complete proof and final logs, checked 33
artifact hashes and exact old/final guard extraction; Ruff/format/ty/Sphinx pass.
Evidence: durable `parent-adversarial-r1-pg-fix/report.md` and
`parent-a1-verification.json`. Package/runtime integration remains prospective.
Fresh origin/main still pins e73b810; runtime/source/UI/tests/dependencies/CI
diff against it is empty. Freeze this input for renewed Claude primary R4,
then a new independent adversarial gate R2 after LGTM.

### Renewed primary R4 and empty-default correction (2026-10-17)

Claude primary R4 returned LGTM for 1a81663 against e73b810, with no P0/P1/P2
findings and one P3. Its 59 fresh guard/subprocess probes passed, with prior
full-plan coverage reused only where hashes were unchanged. The parent inspected
the report, coverage, receipts and probe evidence and verified all 16 artifact
hashes. This approval is historical once the following correction changes its
input; the independent adversarial gate has not yet approved Phase 3.

The P3 is accepted: an empty PGSERVICE introduced after fixture scrubbing can
select an empty service-file section. The old guard admitted it; real libpq
option resolution exposed an external hostaddr at an inert driver boundary,
without connecting. Task 1 now rejects every present PG-prefixed variable,
including empty values, and continues to report names only. The exact corrected
snippet passes 26 behavior checks, plus one old-behavior reproduction and one
receipt test (28 total). The parent read the entire probe, verified 23 new and
33 prior evidence hashes and exact old/new guard extraction. Ruff, format, ty
and the probe's Sphinx build pass. Evidence: durable
`parent-primary-r4-empty-pg-fix/` and `parent-r4-verification.json`.

PR22's UI job independently reproduced the intermittent selected-run viewport
failure already seen on an earlier plan-only head. A separate baseline UI fix
in /tmp/hx-ui-selection-ci keeps the focused heading visible during delayed
chart growth and yields on user interaction. It has independent LGTM and local
regression evidence; integration still requires its full checks and green CI.
After that baseline fix is merged, refresh the plans and source pin together,
freeze the new input, renew Claude primary approval, then launch a new independent
adversarial round. No Phase 3 runtime implementation has started.

### PR26 integration and primary R5 input (2026-10-17)

- [x] PR26 independent local LGTM, GitHub Codex no findings, all six CI checks
  successful on eb503ee, merged as f6f130c; retain isolated worktree and receipts.
- [x] Merge f6f130c into plans at 86e0336; update active pins and SelectedRun blob.
- [x] Preserve schema-3 a444125/schema-4 e73b810 fixture provenance and all scope.
- [x] Check all 51 frontend anchors and absence of runtime diff versus new main.
- [x] Require delayed-chart visibility/user-takeover regressions in Task24.
- [x] Obtain renewed full-plan Claude R5 LGTM on the frozen input.
- [x] Obtain new independent adversarial R2 LGTM on the same input.

The empty-PG correction remains the previously verified exact guard. The UI
baseline fix is fully tested independently; no unchanged application suite was
rerun merely to accompany the plan refresh. New PR22 CI covers the published
plan revision; full Phase 3 implementation/package acceptance remains future
work after both ordered approvals. Durable evidence is `post-pr26-refresh/`,
`ui-selection-ci/` and the prior guard/review directories.
