# Phase 3 review gates and implementation readiness

User direction (2026-10-06): obtain a primary review followed by an independent
adversarial review. Start implementation only after both return LGTM on the final
plan. The user expects to test the result later this week; installation and
integrated workflows are acceptance requirements, not just unit-test totals.

## Baseline and scope

- Plan branch: `p3-plans`, initial head `4392c8b90f96a23b6d35477520f86ebf45075bb1`.
- Current fetched main: `a4441256f39d014d9ad43dea976af1b448f163e3`.
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

Review receipts and prompts: `/tmp/hx-phase3-evidence/` (outside source trees).
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
