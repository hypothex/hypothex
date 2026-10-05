# Final Examples outcomes layout

Scope: fix the final-main Examples outcome matrix escaping its Figure at 800px
when hypotheses are long. Preserve labels, real outcome counts, and chart content.
No backend changes, commits, push, or PR from this worker.

- [x] Inspect the reported screenshot, current outcome markup/CSS, and isolated browser fixtures.
- [x] Add and run a real browser regression before changing production CSS.
- [x] Fix the intrinsic table sizing and verify panel/text bounds at 800px and 1600px in both themes.
- [x] Run affected unit tests, full UI tests, TypeScript, production build, and full Playwright suite.
- [x] Record RED/GREEN evidence and review screenshots; return ownership to parent.

Evidence directory: `/tmp/hx-handoff-evidence/final-ui`.

Confirmed root cause: `.ot th.rh` forces a long hypothesis onto one line inside
an automatically sized table; its minimum width exceeds the two-column Figure.
Page overflow remains zero because the table paints into its neighboring chart.

Initial proof: `browser-red.log` has both 800px themes failing at table right
515.625 versus Figure right 368; both 1600px cases passed. The corrected unbroken
fixture also failed all four width/theme cases (`browser-unbroken-red.log`).
`browser-expanded-red.log` includes an interim fixture assertion error because
the first overlong fixture exceeded the existing 40-character label contract;
that fixture was corrected before the unbroken geometry RED run.

The table fix passed all eight focused geometry cases and the first complete
88-test Playwright suite. Full UI units passed 1,088/1,088; affected units 20/20.
The fixed unbroken 800px screenshot additionally exposed existing headline/A-B
summary overflow (full-page screenshot width 1,041px). Parent authorized an
Examples-only extension, with a viewport/text-bounds regression before that fix.

The extension's `summary-red.log` has both 800px themes failing with 241px of
viewport overflow; both 1600px cases passed. The final fix keeps headline tokens
as individual inline blocks: fitting tokens such as `1e-4` stay whole, and only
oversized tokens can wrap. The A/B grid and label flex child can shrink within
their allotted width. Global `Unbroken` behavior and data formatting are unchanged.

## Final verification and ownership receipt

All evidence below is after the final production changes:

- `bun test test/pages/Examples.test.tsx test/pages/exampleCharts.test.tsx`:
  **20 passed**, `unit-focused-final.log`.
- `bun test`: **1,088 passed, 0 failed**, 92 files, 30.66s, no React act warnings;
  `bun-full-final.log`.
- `bun run build`: source/unit TypeScript and production build passed;
  `build-final.log`.
- `bunx tsc --noEmit -p e2e/tsconfig.json`: passed; `e2e-types-final.log`.
- `bunx playwright test --workers=2`: **88 passed**, 1.4m;
  `browser-full-final.log`. This includes all eight new cases: 800/1600px,
  light/dark, words/unbroken labels, actual comparison counts, table/text bounds,
  disjoint outcomes/sign-test rectangles, viewport/summary text bounds, and a
  fitting scientific-token text-range check. Both isolated hubs shut down.
- `uv run sphinx-build -W -b html docs /tmp/hx-handoff-evidence/final-ui/docs`:
  passed; `sphinx-final.log`.
- `git diff --check`: passed. Only the five scoped files below changed.

Final screenshots retained in `browser-final-results/` under the evidence
directory. Visually inspected final word/scientific and unbroken cases at 800px
in light, plus unbroken 800px and word/scientific 1600px in dark. Labels, numeric
scores and outcome counts are visible without the former panel or page overflow.

Files: `ui/src/pages/Examples.tsx`, `ui/src/pages/components/styles.ts`,
`ui/e2e/examples-layout.spec.ts`, `docs/ui.rst`, and this plan receipt.
No backend changes or Python/Docker suite reruns; parent owns reuse of those
unchanged-source results. No commit, push, PR, or publication by this worker.
All files are frozen and ownership is returned to parent for final review and
publication.
