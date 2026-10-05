# Dogfood integration — 2026-10-05

Scope: queue step 6, areas A–G/M/N and packaging, in `/tmp/hx-df-fix`.
Dependencies: do not merge main, push, or open a PR until audit and security branches merge.

- [x] Read handover and dogfood findings; archive inherited staged and unstaged patches.
- [x] Preserve cancellation coverage, integrate a shared queue batch primitive, verify red/green.
- [x] Verify inherited warning deduplication, hint consolidation, and fixture repairs red/green.
- [x] Review DF-1 grouping, DF-3 seed collapse, and DF-7 p-values with independent calculations.
- [x] Run Python/UI checks and inspect the complete dogfood diff.
- [x] Commit locally and report exact counts and remaining integration dependencies.
- [x] Remove only proven-clean, merged, inactive area worktrees, preserving evidence first.

Decisions:
- Retain inherited removal of obsolete queue refresh calls: queue ranks are computed on read.
- Keep a shared cancellation primitive and move the deleted regression to its actual integrated path.
- Test snapshots and command outputs live in `/tmp/hx-handoff-evidence/dogfood-integration`.

Verification and review evidence:
- Cancellation: failing integration regression observed 3 scheduler locks instead of 1; 11 focused tests pass after consolidating batch cancellation.
- Diff capture: two failing real launch/roundtrip tests pass after persisting diff hashes. Removed the test-only GitInfo subclass.
- Dirty group collision: 20 fixed / 0 broken returned p=1.0 when two hashes shared their first four characters. Full recorded hash suffix now gives exact p=2/2**20.
- Independent statistics oracle: 100 randomized unequal-rerun cases match Python sample statistics and SciPy Welch; maximum p error 8.4e-14. 2601 sign tests match exact integer binomial sums with zero error.
- Warning integration: old execution implementation makes both local and fake-SLURM warnings appear twice; updated execution passes both once-only tests. Template hint consolidation also verified against old implementation.
- Read models: failing tests for queue rank, host-qualified mirrored paths, mixed source hashes, and dirty-vs-dirty comparison now pass. Combined query/leaderboard/seed suite: 57 passed.
- Deferred pin: failing test ran changed code after HEAD moved while queued; staging now preserves the explicitly pinned code.
- UI: Bun 676 passed, zero failed, 2878 assertions; TypeScript and build passed.
- Cleanup: eight df-area worktrees/branches removed by ordinary safe commands; manifests in /tmp/hx-handoff-evidence/df-area-archive. Only disposable caches/virtualenvs existed.
- Full Python: 1627 passed, 3 skipped, 9 Docker tests deselected in 486.43s. Sphinx HTML build passed without warnings. Ruff check/format (142 files), ty, and git diff --check passed.
- Cross-layer follow-up list: /tmp/hx-handoff-evidence/dogfood-integration/step7-cross-layer-remainder.md.

Further decisions:
- Keep complete eight-character recorded dirty hash in group IDs to prevent internal comparison-map collisions. Update the spec and plan contract; clean IDs remain unchanged.
- Infer board metric drift only from differing stored hashes at the selected metric version; never execute project code from leaderboard reads.
- Honor explicitly pinned deferred execution even when the repo matches at preparation: the working copy can change before queued execution.
- API queue ranks are derived globally before filtering/pagination; persisted tickets stay unchanged.

Packaging verification:
- Real uv build from the built UI: wheel 1,271,957 bytes; both referenced UI assets exist, skill and license included, internal docs excluded. Artifacts retained under /tmp/hx-handoff-evidence/dogfood-integration/dist.

Integration gate:
- No main merge, push, or PR yet. Wait for queue steps 2/4/5 to merge.
- Current branch predates audit wave 3 (merge-base with 52b25e4 is 70c369c), so later integration must retain both sides: audit LTTB/metric_names, reeval run_ids filtering, security local_repo gates and metric bounds, plus these dogfood semantics.
- Cross-layer step7 remainder is deliberately open; see the external evidence note.

Pre-merge composition checks (parent-authorized, no main merge yet):
- [x] Reproduce long Unicode atomic filenames plus umask: both permission cases fail
  with ENAMETOOLONG, then pass with byte-bounded prefixes and existing O_EXCL writes.
- [x] Reproduce delayed execution checkout ownership: an unowned worktree was reused,
  git received an unreserved destination, and a racing creator was not protected.
  Three failing tests now pass with exclusive reservation, recorded completion for
  SLURM reuse, and cleanup refusal for destinations this run never created.
- [x] Focused lifecycle suite: 28 passed, 219 deselected, including pinned local/queued
  and fake-SLURM execution/cleanup. Ruff check/format, scoped ty, Sphinx with warnings
  as errors, and diff whitespace checks passed. Red/green logs remain in the external
  evidence folder; commit only this worker's seven explicit files.
- Gate/staging cleanup and verified host-alias/path-cache composition still wait for
  the authorized main merge after security dependencies land.


# Backend audit integration (2026-10-05)

Scope: finish handover queue step 2 on `audit-fixes`; parent coordinates merge.

- [x] Read handover, audit summary and original performance method.
- [x] Confirm Wave 3 CLI uv opt-in and SLURM/uv documentation handoffs exist.
- [x] Complete baseline Python/UI/docs checks; test first for integration fixes.
- [x] Review branch implementation and merge origin/main without discarding either side.
- [x] Remeasure the original 19,993-run synthetic store; distinguish cold, warm and semantics.
- [x] Run final required checks and review final diff.
- [x] Commit report and prepare a reviewed PR body; parent owns push/open/link and CI.
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
- Before performance measurement, found a second stale af-O process tree from
  pytest-1295: five orphaned supervisors and five gate-wait children, all over seven
  hours old. Confirmed command/cwd evidence and terminated only those processes;
  retained `stale-processes-1295.json` beside the earlier cleanup evidence.

- Final code `8e1a1ef` includes main through PR #14. Python: 1727 passed,
  3 skipped, 11 deselected (493.38 s); Docker: 11 passed (200.55 s).
  UI: 848 unit tests, both TypeScript checks, production build, 44 Playwright tests,
  and all three demo shutdown cases pass. Ruff lint/format, ty and Sphinx pass.
- Performance measured in an isolated clone during a quiet window beginning
  2026-10-04 22:00:15 UTC. Full report and raw samples are committed under
  `docs/audits/2026-10-05-backend-performance.{md,json}`. Historical baseline is
  explicitly identified, cold hydration and CLI regressions retained, and the
  original fixture is preserved. New harnesses and complete logs remain under
  `/tmp/hx-af-perf-after`.
- Parent independently reviewed `44a6b58`, `aa5da40`, and `0234e93` with no new issue.
  PR body/title prepared in `/tmp/hx-handoff-evidence/backend-pr-body.md` and
  `backend-pr-title.txt`; parent will inspect, push, open/link, and monitor CI.

# UI leftovers, handover step 8 (2026-10-05)

Scope: only named step-8 UI items; `/tmp/hx-ui-leftovers`, branch `ui-leftovers`,
base `3b696f1`. Parent coordinates step-7 merge, backend contract, full-check window,
push/PR/merge. No Phase 3 or all-minors/F17 implementation.

- [x] Read binding handover, Node guide, source-backed step-8/minor triage; verify base.
- [x] Identify PERF-F9c active views/query contract: metrics exists; max_points requires additive backend field.
- [x] Run-page actions: infer capability, re-evaluation counts/reasons, useful 404 state.
- [x] Paths/errors: SlashPath on run paths and readable project/task names; concise ErrorBox.
- [x] Charts: width-derived leaderboard ticks, responsive Failures legend, nonoverlapping scatter labels.
- [x] Request only displayed run metric names with bounded max_points; live-name backend dependency integrated.
- [x] Share billed GPU count and useHubEnvironment.
- [x] Preserve queue switch nowrap from step 7.
- [x] Verify already-fixed row growth and e2e home-path docs; avoid duplicate edits.
- [x] Merge finalized local step-7 branch without rebasing; preserve both behaviors.
- [x] Scoped frontend checks and independent review in parent-approved window.
- [x] Conventional local commit.
- [x] Complete local step-7/step-8 integration and authorized checks; parent owns final publication/main integration.

Ownership: UI parent owns Run/RunActions/query hooks/stats/KindPanels/models/docs;
chart_layout owns chart panels and their tests; paths_errors owns shared path/ErrorBox
components and tests. No worker commits; shared worktree. Every actual fix gets a
failing regression first and focused green evidence in `/tmp/hx-handoff-evidence/ui-leftovers/`.

Contract proposal sent to parent: optional PanelData.max_points, integer 2..500;
null/default retains 500, curves-only final per-run/name LTTB; explicit empty metrics
means no series. UI additions wait for frozen approval. Python/contract edits belong to parent.

Step-8 implementation evidence (before final step-7 merge)
--------------------------------------------------------

- Run action/not-found regression: 13 pass/4 fail before; 38 focused tests pass after.
  Infer capability comes from successful task-stage read; re-evaluation formatter is
  shared with Task and previous-run feedback is not displayed after navigation.
- Shared environment query + billed GPU-hours: 39 pass/2 fail before; 84 affected
  query/run/overview/sweep tests pass after. No real host access.
- PERF-F9c request regressions: 18 pass/4 fail before; 32 tests pass after. Run history
  names are explicit; >100 names split without loss; explicit [] remains empty;
  explicit sweep/step choices remain untouched. Generated API types refreshed from
  create_app in an isolated /tmp home without starting a server.
- Parent committed backend cap `a5f410e`: six tests failed first; 192 API/core tests,
  Ruff/format/source ty/Sphinx passed. Backend artifacts/logs live under the shared
  handoff evidence directory. UI TypeScript check passes.
- Delegated paths/errors: six expected failing regressions, then 46 tests pass.
  Chart layout: three expected failing regressions, then 64 tests pass; positional
  legend bounds and accessible fallback-key grouping verified in review.
- Existing e2e home-path docs and row-growth CSS verified in source, retained.
- Build/browser window released: production build and 881 UI unit tests pass; e2e
  TypeScript passes. Added actual chart text geometry coverage at spans 5/7/12
  in light/dark with resize; all six browser tests pass (13.4 s).
  The first browser run caught legend row spacing and endpoint tick overflow;
  fixed both root causes, with the failing artifacts preserved before rerun.
- Independent review identified late run re-evaluation feedback and cached infer
  capability after task refresh failure; both regressions failed first, then all
  21 action/run tests passed after fixes.
- Live metric-name lag found in indexed run details; parent owns authoritative
  backend discovery fix. PERF-F9c remains pending that contract and regression.
- Waiting on step-7 hx-sw+nowrap merge; no pushes/PRs/merges performed.
  Full combined checks remain required.

- Final scoped verification: 883 UI unit tests, source/test TypeScript, e2e TypeScript,
  production build, all 50 Playwright tests (35.5 s), and Sphinx with warnings as
  errors pass. Both isolated Playwright servers shut down. Diff whitespace check passes.
- Parent moved the live-name backend fix to the preceding dogfood branch; strict
  metric whitelisting is integration-dependent until that fix lands on main.
  Parent requested local UI commit and ownership handback without push/PR.

# Bounded view integration (2026-10-05)

Scope: preserve the merged audit behavior while bounding live metric reads and view work.

- [x] Keep exact state readers strict on UTF-8 and compatible with universal newlines and
  surrounding whitespace; only live metric reads apply byte/name/point caps.
- [x] Prove per-name buffers and long-name memory stay bounded while reading.
- [x] Merge audit SQL/primary-field/group-label behavior without dropping security bounds.
- [x] Consolidate shared LTTB with exact integer buckets and overflow-safe finite axes.
- [x] Reuse primary example data for stat-strip denominators instead of rereading per reference.
- [x] Complete full Python, Docker, UI, e2e, static and Sphinx checks on the integrated branch.
- [ ] Review branch, publish PR, and merge only after all current-head CI checks pass.

Evidence: integration first produced five failures (large finite LTTB values and repeated
primary-file reads); all 340 focused core tests now pass. A separate exact-read Unicode
whitespace regression failed before restoring strip behavior; all 21 filesystem tests pass.
Full validation and review logs are retained under `/tmp/hx-handoff-evidence/sec-integration-*`.

Final integration: 1,813 Python passed / 3 skipped / 11 Docker deselected; separate
final Docker run 11 passed. UI 848 and Playwright 44 passed, as did shutdown, build,
types, Ruff, source ty, and Sphinx. Review regressions additionally cover lazy hydration
after terminal publication and after a rebuild, terminal-before-metrics execution order,
and loss-peak preservation near int64 step limits. Independent review has no remaining
actionable blocker. PR publication and current-head CI merge remain pending.

Merged the repository-path gate from main `3b696f1`: production files merged cleanly;
three appended-test conflicts retain both regression groups. Combined validation:
1,853 Python passed / 3 skipped / 11 Docker deselected; separate Docker 11 passed;
Playwright 44 passed; shutdown, Sphinx, Ruff, source ty, and diff checks pass.
Unchanged UI unit/type/build evidence remains valid. Updated-head CI is required
before the final merge.

# Dogfood lifecycle merge composition (2026-10-05)

- [x] Retain bounded/exact metric-reader behavior, terminal-before-index publication,
  local-project identity checks, deferred staging, and exclusive checkout ownership.
- [x] Gate delayed checkout and staging cleanup before reading stored repo paths or
  performing git operations for a project copied from a remote host.
- [x] Preserve both parents' lifecycle tests; adapt the prior eager-checkout fixture
  to explicitly start its deferred checkout before testing cleanup refusal.
- [x] Verify the composed lifecycle files and document the security boundary.

The new identity/staging regression first reproduced 3 failures and 1 pass, then
passed all 4 combinations after the gate moved ahead of checkout/cleanup. The focused
execution/control/SLURM/filesystem suite passes 263 tests in 68.35 seconds. Owned-file
Ruff lint/format, source ty, and Sphinx with warnings as errors pass. Logs are under
`/tmp/hx-handoff-evidence/dogfood-integration/merge-*`. Full integration validation
belongs to the coordinated parent run; no full suite or Docker was run here.

The merged forwarding sweep test still expected stored queue tickets to renumber.
It now observes live ranks through the public runs API and asserts the fifth
ticket remains 5 on both host and hub while its displayed rank becomes 1. The
original timeout is captured in `parent-merged-api-evaluation-sweeps.log`; the
focused case passes in 5.52 seconds and all 17 forwarding tests pass in 22.43
seconds. No scheduler production change was needed. Eight orphaned processes
from that failed fixture were identified by exact fixture path and terminated;
the inventory is saved in `merge-queue-orphan-cleanup.txt` beside the test logs.

# Dogfood final integration verification (2026-10-05)

- [x] Merge current main `1b769f4` while preserving audit and security behavior.
- [x] Review grouping, repeated-seed weighting, finite means, queue tickets, and API pagination.
- [x] Fix remote dataset resolution and cache identity after corrupt-index recovery.
- [x] Check public queue ranks without changing persistent FIFO tickets.
- [x] Complete alias-transfer ownership/config and live metric-name regressions.
- [x] Complete independent environment recovery/tunnel lifecycle review.
- [x] Run final Python, Docker, UI/browser, static, documentation, and packaging checks.
- [ ] Review final diff; commit, push, open/link PR, and merge only green current-head CI.

The merged pagination fixture must create durable runs because startup repair now removes
index-only records. Its corrected host suite passes 15 tests. The queue forwarding
fixture now checks public rank 1 and raw ticket 5 separately; all 17 forwarding tests
pass. Initial failing and final passing evidence is retained under
`/tmp/hx-handoff-evidence/dogfood-integration/`.

Final reviewed integration evidence: the full Python run finished with 2,041 passed,
3 skipped, 11 Docker deselected and one stale queue-property assertion. Its model
expected ticket renumbering; the corrected model separately verifies stable tickets
and live FIFO ranks, and its targeted rerun passes. Thus all 2,042 covered Python
tests have passing final-state evidence; no production file changed after the full run.
Separate Docker: 11 passed. UI: 848 unit tests, both type checks, build, 44 browser
tests and three shutdown scenarios passed. Ruff/format/source ty/Sphinx passed.
A real uv build produced a wheel and sdist with the compiled UI, skill and license;
the sdist excludes internal plans/mockups. Exact artifacts are under
`/tmp/hx-handoff-evidence/dogfood-integration/`.

Review added failing-before/passing-after regressions for identity recovery excluding
mirrors, PID-safe tunnel ownership, alias-transfer snapshot refresh, bounded live-name
caching, terminal checkout failures, exclusive shared-staging membership, recorded
sweep patches/counts, and nested demo Git isolation. The full branch has been reviewed;
publication and current-head CI remain the final merge gate.

## Remaining dogfood integration (step 7)

Base: merged main `55ca922` (PR #18; six current-head CI checks passed).
Readiness maps under `/tmp/hx-handoff-evidence/` preserve the complete H/I/J/K/L/O
and cross-layer scope. Worktree: `/tmp/hx-df2`, branch `dogfood-fixes-2`.

- [x] API/core: verified current/offline identity, SLURM defaults, served state,
  reinfer vars, exact MCP dispatch, transactional pulls, batch queued cancellation,
  structured errors and durable asynchronous sweep acceptance/issuance/recovery.
- [x] CLI/MCP: all 14 I/J findings plus vars, dirty/diff and statistical provenance,
  terminal reasons and accepted sweep states; preserve uncertain timeout outcomes.
- [x] Lifecycle: nullable evidence-only terminal reasons, race winners, late node
  settlement, rerun reset and retained accounting; regression tests before changes.
- [x] UI: all 12 K/L findings plus stored metric drift, patch provenance, uncounted
  cells, terminal reasons, bounded names and issuance-aware existing sweep actions.
- [x] Recheck O: packaging/license/skill artifacts already verified in step 6;
  remove nonexistent eval command and false setup claims; source-install quickstart;
  current event list and remote architecture prose. Two real documentation examples
  failed the current CLI-command check before repair; five docs tests now pass,
  and warning-as-error Sphinx build passes.
- [x] Integrate response types and public/spec/interface documentation for new behavior.
- [x] Review complete diff, required checks, meaningful runtime/Docker/browser
  acceptance, and actual built artifacts.
- [ ] Publish/link and merge only green current-head CI.

DF-21 release status was checked live at https://pypi.org/project/hypothex/ on
2026-10-05: 0.0.1 is explicitly a name reservation. Source installation remains
required for the working package; build the UI before installing it.

Checkpoints: CLI/MCP 138 changed-contract tests plus retained affected evidence;
lifecycle 365 affected tests; UI 890 unit tests, both type checks/build, and 50
real-browser tests with light/dark geometry at 800/1099/1101/1600 pixels.
Independent UI review corrected queued-cancel races, single-pass template preview,
and over-capacity GPU admission without silently changing requested resources.
Actual OpenAPI regenerated the response types; Sphinx passes. Two documented
configuration examples and all 31 statistics properties pass. The Welch oracle now
normalizes SciPy inputs before its squared-variance calculation; the exact failing
tiny-variance example is retained and production statistics are unchanged.

Independent API review reproduced partial HTTP folder pulls replacing complete
local artifacts; explicit pulls now require every descendant before installation,
and eight failure probes preserve the original destination. Mirrors retain their
best-effort default. Durable issuance has process-death tests at four acceptance
boundaries, worker death, repeated/anonymous acceptance, original pins/options,
and cross-process owner exclusion. Cancellation preserves unresolved outcomes
across resume episodes and atomically excludes a competing extension. The final
independent CAS review passed three regressions and separate stale-revision,
competing-extension and historical-cancellation probes.

Final local evidence: full Python 2,273 passed, 3 skipped, 11 Docker deselected,
with six old synchronous-contract assertions subsequently corrected. All six,
the final issuance/CAS changes, queries and statistics are covered by the final
211-test passing rerun. Docker: 11 passed. UI: 890 full unit tests and 50 browser
tests; the later cancellation follow-up passed all 65 affected tests, types and
build. Ruff/format (172 files), source ty, warning-as-error Sphinx and diff checks
pass. Final wheel contents match the final issuer/events/API/client source bytes;
compiled UI is present and the sdist excludes internal plans/mockups. Evidence is
under `/tmp/hx-handoff-evidence/step7-*`. Publication and CI remain the merge gate.


# Step 8 integration with finalized Step 7 (2026-10-05)

Merged local `dogfood-fixes-2` at `48f8bef` into `ui-leftovers` from `90de44f`
without rebasing. Seven conflicts retain both sets of source, tests, and documentation.
Run actions require serving ownership and infer capability, retain queue-only Cancel,
three-second Stop confirmation, and late-response-safe re-evaluation feedback. Live
metric-name discovery now feeds the explicit, capped views/query requests. Step 7
issuance/launch/queue/responsive behavior remains intact, including terminal issuance
cancellation. The new palette uses the shared environment query too.

- [x] Review complete diff against Step 7; source changes remain the named Step 8 scope.
- [x] Add integration regressions for joint serving/infer gates and the real API flow
  from unindexed live metric names into filtered/capped curves.
- [x] Full Bun suite, source/test/e2e types, production build, all Playwright tests.
- [x] Affected API/core tests, Ruff lint/format, source ty, and warning-as-error Sphinx.
- [x] All three isolated demo shutdown cases; no processes of the demos remain.
- [x] Regenerated current OpenAPI types match the merged tracked file exactly.
- [x] Local conventional merge commit; parent handback after commit.

Evidence is under `/tmp/hx-handoff-evidence/ui-leftovers/integration/`. The affected
backend run passed 247 tests, including live-name discovery and the bounded reader,
curve cap/metadata/step-axis, and view limits. Browser checks pass all 56 tests, adding
both branches' geometry coverage. Full Python/Docker beyond the affected 247 tests
remain parent-coordinated; Step 7 already has its full-suite evidence and no unrelated
backend production code was changed by this integration. No push or PR authorized.

Final Step 8 integration UI evidence: 930 Bun tests pass (84 files, 26.05s), all
56 Playwright tests pass on final source/build (43.8s), and all three shutdown cases
pass. The final API/core run is 247 passing tests. Static/types/build/Sphinx and
schema byte comparison pass. Parent started final full Python and Docker runs after
source freeze; those results and publication/current-head CI remain parent gates.

Parent final Step 8 verification: full Python **2,290 passed, 3 skipped**, with
11 Docker tests deselected; separate Docker **11 passed**. Full UI 930 and browser
56 pass, along with the 247 affected backend tests, three shutdown cases, types,
build, Ruff/format/ty and Sphinx. Final source was unchanged during these checks.
Current-head CI and ordered publication after PR #19 remain the only merge gates.
