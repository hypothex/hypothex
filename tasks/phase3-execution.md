# Phase 3 review gates and implementation readiness

User direction (2026-10-06): obtain a primary review followed by an independent
adversarial review. Start implementation only after both return LGTM on the final
plan. The user expects to test the result later this week; installation and
integrated workflows are acceptance requirements, not just unit-test totals.

## Baseline and scope

- Plan branch: `p3-plans`, initial head `4392c8b90f96a23b6d35477520f86ebf45075bb1`.
- Current fetched main: `e73b8105df32a1d2488477c48e680cb5de922771` (UI v5).
- Existing draft PR: https://github.com/hypothex/hypothex/pull/22.
- Authoritative scope: the Phase 3 contract, backend/frontend plans and mockups
  under `docs/superpowers/plans/` and `docs/mockups/phase3/`.
- Preserve all 13 contract scope items. Reconcile the later backlog and final
  Examples changes with planned replacements before treating the plan as ready.
- Existing review rounds 4–6 and their bounded fixes are prior evidence, not the
  two approvals requested now. New material plan changes require re-review.

## Gates

- [ ] Primary review against the spec, all three plan documents and actual main.
- [ ] Reproduce and resolve actionable findings in documents; obtain LGTM.
- [ ] Independent adversarial review of the resulting plan and current main.
- [ ] Resolve findings; obtain adversarial LGTM and reconfirm primary approval
  where the reviewed plan changed materially.
- [ ] Record exact reviewed revisions and both final verdicts before source work.

## Execution after both review gates

- [ ] Refresh the plans against main, preserving the accepted contract and scope.
- [ ] Implement dependency-ready backend and frontend increments in isolated
  `/tmp/hx-*` worktrees, with failing tests first and one writer per owned file.
- [ ] Review actual diffs, run affected and required checks, link every PR, and
  merge only after all current-head CI checks pass. Retain PR branches.
- [ ] Verify the complete collaborator pairing/shared-host/revocation workflow,
  notebook, baselines/exports, notifications/digest, storage protections,
  Postgres migration/rebuild equivalence, authenticated MCP and SDK cost logging.
- [ ] Verify fresh installation and existing-home upgrade behavior with synthetic
  homes, packaged UI assets, and a reproducible team demo on clean merged main.
- [ ] Run full local/CI acceptance, Docker fakes and light/dark browser checks;
  inspect screenshots and retain raw evidence, then verify owned-resource cleanup.
- [ ] Write a concise testing handoff with setup commands, version/commit,
  supported workflows, expected results and material remaining limitations.

## Boundaries

No runtime implementation until both review gates pass. Use uv, Ruff, ty, pytest,
Sphinx and Bun. Never edit tracked files or commit in the main checkout. Never
touch `~/.ssh` or connect to real SSH/SLURM hosts, Slack, SMTP, Tailscale or external
Postgres. Use loopback fakes and throwaway Docker containers. Real deployment,
real notifications and first public exposure remain separate user actions.
No attribution trailers or model/tool references in commit messages or PR text.

Historical review receipts and prompts used `/tmp/hx-phase3-evidence/`; that temporary location is not the current evidence source. The October 16 durable receipts are under `/Users/shreyasv/Desktop/code/hypothex-phase3-evidence/2026-10-16/` (outside source trees).
This plan records authorization and progress; it does not claim either review
gate or any Phase 3 implementation has passed yet.

## Current review cycle

- Primary round 1: NOT LGTM, two P2 findings (stale main-source plan and
  incomplete cost shown as a complete total). The report also lists three P3
  corrections: JSON key snapshots, deleted checkpoint display and stale prose.
- The first review did not cover every backend/frontend task or mockup image.
  Its coverage list is carried into the next review; no historical review
  substitutes for the missing current coverage.
- Current corrections are limited to plans and mockups. The refreshed contract
  makes task export use the selected primary, rejects it for compare export,
  and preserves pricing completeness in run/sweep/digest output.
- Both approvals remain pending. The review baseline is current main a444125;
  subsequent material changes must return to review.

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
