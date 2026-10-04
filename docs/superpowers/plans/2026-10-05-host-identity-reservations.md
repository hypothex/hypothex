# Host identity reservation fixes

Scope: close the concurrent handshake and restart ownership gaps in `sec-eval-gate`.
Use fake clients and temporary stores only. No network hosts or SSH configuration.

## Decisions

- Reuse `host_cursors`; sequence zero is a durable reservation. No new registry or schema.
- Serialize lookup and reservation under the existing `.claims` lock before any session await.
- Include disabled configured names and legacy claim-only owners. Retain past identities while
  their host remains configured, including after connection-setting changes.
- An explicit removal releases ownership only after pending mirrors drain. A new alias updates
  the old environment's claim source labels before accepting data; other direct host writes fail.
- Cursor resets preserve reservations; forwarding ignores historical aliases no longer configured.

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

Commit locally with these changes; push and main integration remain with the parent task.

Evidence logs live in `/tmp/hx-handoff-evidence/`. The two initial reproductions are
`gate-concurrent-identity-review.json` and `gate-restart-identity-review.json` there.
