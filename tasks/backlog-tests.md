# Remaining phase 2 test coverage

Scope: original minors 1, 5, 7, 8; API fixture realism, default phase-2 write options, default/disabled host polling, useAllRuns hook cache/refetch/disabled contracts. Also settle SweepRerun act warnings without suppressing console errors. Shared model comments are parent-owned; suggested SLURM accepted-form wording sent.

- [x] Pin complete sweep fixture status counts and total (assertion failed before fixture correction).
- [x] Test all six phase-2 writes without explicit action options, twice each, preserving unique command IDs and human attribution.
- [x] Exercise default host polling through actual scheduled 10-second callback, manually ticking it without waiting 10 seconds; disabled hook remains idle.
- [x] Exercise useAllRuns query key, disabled state and run-family invalidation.
- [x] Diagnose and settle SweepRerun initial host effect via bounded scheduled-task flushing inside act, without warnings or suppression.
- [x] Run affected focused tests and typecheck; report evidence/limits.

No production API behavior changes authorized for this follow-up. No full suite, build, browser, commit or push.

Verification: client/queries/SweepRerun focused files **77 pass, 0 fail, zero act warnings**; latest two changed hook tests **2 pass**. Final `bun run typecheck` and scoped `git diff --check` pass. Evidence: `/tmp/hx-handoff-evidence/backlog-sweeps/followup-tests.log`, `followup-final-hooks.log`, `followup-final-typecheck.log`. Temporary warning-source instrumentation was removed; it preserved original console output and traced the initial-host setDraft passive effect at LaunchDialog.tsx. Parent-owned OpeningDialog focus handoff was independently reviewed and fixed by parent.
