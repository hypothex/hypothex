# Selected-run viewport CI regression

Baseline: e73b810 (runtime byte-identical to PR22 1a81663). UI jobs failed intermittently in both themes after the selected heading received focus but remained outside the viewport. Unit/build/type checks passed. Phase 3 plan review remains frozen and separate.

- [x] Capture CI failure and inspect selection/async panel rendering.
- [x] Reproduce with delayed real chart responses in both themes; async siblings move the focused heading outside the viewport.
- [x] Observe layout ancestors until user input or focus movement; add delayed-chart and manual-scroll regressions without weakening the original assertion.
- [x] Verify 12 focused browser cases, 1,414 unit tests, build and both TypeScript checks; inspect independent LGTM and its 15 independently passing unit tests.
- [x] Run the full browser suite (122 passed, all projects) and Sphinx with warnings as errors.
- [ ] Integrate only with appropriate reviewed/green-CI evidence, preserving the Phase 3 gate.

Evidence is retained under the external Phase 3 evidence directory in ui-selection-ci/.

The independent review returned LGTM with no blockers. Its only bookkeeping nit
was to reconcile this tracker. Runtime and test files have not changed since
that review; documentation now explains the user interaction behavior. The
original inline-selection assertion remains intact. No Phase 3 behavior is
introduced by this baseline correction.
