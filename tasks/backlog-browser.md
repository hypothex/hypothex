# Backlog browser regressions

Scope: new `ui/e2e/backlog.spec.ts` only; application changes belong to other workers.

- [x] Read isolated-hub fixtures, browser contracts, and demo source.
- [x] Add four-kind Metric, Seeds/Repeats checkbox glyph visibility, selected-run, close, and full-route checks.
- [x] Compare training checkpoint and evaluated-score values with real API records.
- [x] Discover actual agent traces; verify trajectory order, exact example, and current-group highlight.
- [x] Verify iteration selectors and outcomes or explicit missing fingerprints.
- [x] Verify selected-run raw sample scope against API source rows.
- [x] Capture 1600/800 screenshots and legend geometry under both existing theme projects.
- [x] Static TypeScript check: `bunx tsc --noEmit -p e2e/tsconfig.json` passes.
- [x] Parent-owned browser run and visual inspection after integration: 80 full tests passed, including 18 new light/dark cases. Final selected-run focus/reveal was inspected at immediate click time and checked in both themes.

No browser servers or tests started by this worker; parent reserved execution. No pre-fix browser RED claimed. Ordinary demo has metric-sweep history but no durable long-label sweep fixture. Tests do not manufacture labels or fingerprints; long-label sweep browser coverage requires an existing suitable fixture. Unit geometry tests belong to the chart/sweep workers.

Training selection additionally records immediate click-time pane bounds, viewport height, scroll position, active element, and a viewport screenshot before later interactions. Full-run popup verification performs normal token unlock because `noopener` intentionally creates an independent session.
