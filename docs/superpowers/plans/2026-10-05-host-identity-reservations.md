# Host identity reservation fixes

Scope: close the concurrent handshake and restart ownership gaps in `sec-eval-gate`.
Use fake clients and temporary stores only. No network hosts or SSH configuration.

## Decisions

- Reuse `host_cursors`; sequence zero is a durable reservation. No new registry or schema.
- Serialize lookup and reservation under the existing `.claims` lock before any session await.
- Include disabled configured names and labelled claim-only owners. Retain past identities while
  their host remains configured, including after connection-setting changes.
- An explicit removal releases ownership only after pending mirrors drain. A new alias updates
  the old environment's claim source labels before accepting data; other direct host writes fail.
- Cursor resets preserve reservations; forwarding ignores historical aliases no longer configured.
- Upgrade claims without a `host` label migrate only from exactly one preexisting cursor owner.
  Missing or ambiguous owners fail closed with documented recovery, before any new reservation.
- Normalize all hostless claims to that original owner before writing a new alias cursor;
  then transfer the labelled claims. Every intermediate durable state is restartable.

## Acceptance and evidence

- [x] Reproduce concurrent handshake acceptance and restarted ownership loss with fake clients.
- [x] Add failing regressions before code changes: `gate-identity-red.log` (11 failures).
- [x] Add failing drain-order regression: `gate-identity-drain-red.log` (1 failure).
- [x] Implement reservations, direct claim protection, alias transfer, and configured-name lookup.
- [x] Verify the 12 identity regressions: `gate-identity-green.log`.
- [x] Remote, API host, and core index tests: 388 passed, 3 skipped (`gate-integration.log`).
- [x] Forwarding, env-route, security, and index-rebuild tests: 79 passed
  (`gate-forwarding-rebuild.log`).
- [x] Ruff check and format, ty on `src`, and Sphinx with warnings as errors passed
  (`gate-ruff.log`, `gate-format.log`, `gate-ty.log`, `gate-docs.log`).
- [x] Review the final diff: reservation precedes awaits, disabled and draining owners remain
  protected, cursor maintenance preserves identity, and alias transfer updates provenance.
- [x] Cover origin/main's older hostless claim shape: five failures before the migration fix
  (`gate-upgrade-red.log`).
- [x] Verify alias-transfer migration can resume after interrupted normalization, cursor,
  and claim writes: three failures before the ordering fix (`gate-upgrade-crash-red.log`),
  then all 20 identity tests pass (`gate-upgrade-green.log`).

Upgrade review rule: use the prior release's actual persisted record shapes, and inject
failures between durable writes as well as checking the completed transition.

Commit locally with these changes; push and main integration remain with the parent task.

Evidence logs live in `/tmp/hx-handoff-evidence/`. The two initial reproductions are
`gate-concurrent-identity-review.json` and `gate-restart-identity-review.json` there.

## Main integration

- [x] Merge backend audit and UI fixes from `origin/main` at `5c02037`, preserving both
  branches' regressions and the unchanged-config refresh optimization.
- [x] Existing dataset-overlap regression fails after the merge, then passes when the shared
  gate supplies its repo (`gate-merge-overlap-red.log`, `gate-merge-overlap-green.log`).
- [x] Preserve historical mirror provenance while preferring configured aliases. The full
  suite reproduced removed-host curation and re-evaluation failures; stale seen-alias coverage
  also failed before the correction (`gate-merge-alias-red.log`). Final targeted routing,
  host, identity, and MCP tests: 80 passed (`gate-merge-routing-green.log`).
- [x] Centralize MCP sweep pin lookup and cover local, host-copy, missing, and explicit repos.
  Query and MCP helper tests: 44 passed (`gate-merge-queries-mcp-green.log`).
- [x] Final complete API subset: 177 passed (`gate-merge-final-api.log`).
- [x] UI unit tests: 848 passed; build, UI and e2e types passed; Playwright: 44 passed;
  demo shutdown check passed (`gate-merge-ui-*.log`, `gate-merge-e2e*.log`,
  `gate-merge-shutdown.log`).
- [x] Mandatory Docker SSH and SLURM suite on the final code: 11 passed in 185.92s
  (`gate-merge-final-docker.log`).
- [x] Ruff check/format, ty, and Sphinx with warnings as errors passed
  (`gate-merge-final-{ruff,format,ty,docs}.log`).
- [x] Review the complete production diff against `origin/main`; no remaining blocker.
- [x] Final full Python suite after integration corrections: 1767 passed, 3 skipped,
  11 Docker tests deselected, in 457.52s (`gate-merge-final-full.log`).

The first integrated full run recorded 1762 passed, 3 skipped, and the three failures
described above (`gate-merge-full.log`). The successful final full run supersedes it.
