# Bounded launch backlog fixes

Scope: original backlog 27/28/30/35/37/41/42 (46 duplicates 41), plus owned comments/help 29/32/34. Ownership is `ui/src/launch/*`, matching launch tests, and this checkpoint. No parent screens, shared auth, backend, generated types, commits, or publication.

- [x] Add failing regressions for command warning/quoting, seed exhaustion, resource errors, partial-close feedback, and cached host picker. Initial focused run: 14 failed, 95 passed (`red.log`).
- [x] Apply minimal fixes while preserving auth generation guards, unknown-outcome same-ID resend, and host/resource choices.
- [x] Run affected launch tests and UI type checking; report evidence and remaining limitations.

Evidence: `/tmp/hx-handoff-evidence/backlog-launch/`.

Final focused verification: `bun test test/launch` passed 130 tests across 8 files (594 assertions, `focused-final.log`). Scoped `git diff --check` passed. `bunx tsc --noEmit` has no launch errors but is currently blocked by another worker's in-progress TaskInsights `Loading what` props at lines 51/54/57/73/92 (`types-final.log`); earlier PanelGrid context errors have been resolved. Parent owns final assembled type validation. No whole UI suite, build, browser, backend, or Docker checks were run here.

Behavior: attached unquoted operators warn without changing argv; quoted backslash-newline is removed; leading equals is shell-quoted; next seeds stop at the valid upper bound without wrapping, with an explicit exhausted-range note; only missing env routes fall back to empty resources; cached host data remains visible beside refresh errors. Partial close reports only confirmed runs once and only in their credential generation, then closes. Completed batches are not re-reported. Task/Sweep parents need no callback signature changes.

Owned source and tests are ready for parent integration. No commits, staging, push, or PR action taken.
