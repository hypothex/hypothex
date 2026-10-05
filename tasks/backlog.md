# Post-handover backlog

Planning baseline: `1381662` in `backlog-polish`, inherited from the fully checked
combined token candidate. Merge final `origin/main` before publication. This plan
is prepared during CI waiting; independent implementation proceeds while the
ordered queue waits on CI, with backlog publication after that queue. No Phase 3 implementation is authorized.

The original 95 rows are mapped individually in `backlog-minors-triage.md`.
UI-F17 is decomposed into 22 feature rows in `backlog-ui-f17-triage.md`. Those are
initial evidence snapshots; record final dispositions and source/test proof here.
Already-fixed/nonissue rows require no speculative source rewrite. Duplicate rows
are one fix. Test gaps need meaningful assertions, not implementation mirrors.

## Constraints and acceptance

- Reproduce each behavior fix before editing it. Use Bun for UI and uv/pytest for
  Python. Keep scope/file ownership disjoint and perform independent review.
- Preserve default authentication, credential-generation guards, immutable command
  receipts, uncertain remote outcomes, authoritative serving identity and capped
  metric reads. New controls must not relabel a value or change its provenance.
- Use existing recorded data. Leave unavailable checkpoint test values and demo
  macro F1 absent; validation artifacts are not evaluated ScoreRecords. Unknown
  GPU pricing must remain distinct from a true zero or partial known dollar total.
- UI stays terse: measured values, glyphs and tooltips. Responsive browser checks
  must cover final light/dark screens and useful narrow widths.
- CSV/export is Phase 3 deferred and will not be implemented in this branch.
- Final gates: affected + required full checks, isolated Docker, actual package
  content, independent diff review, current-head CI and authorized merge.

## Work packages

- [x] Launch correctness and recovery: original rows 27/28/30/35/37/41/42/48
  (46/53 duplicates). Preserve direct argv semantics; warn about attached shell
  operators, remove quoted backslash-newline, quote leading equals, handle the
  maximum seed, surface real resource errors, keep selected host visible, preserve
  partial-success feedback and make opening errors dismissible/retryable.
- [x] Sweep correctness and presentation: rows 59/60/61/63/68/71/74/75/78/82/83
  (64 duplicate). Use deterministic numeric/text ordering; authoritative counts
  with partial rows; accurate legends/accessibility, bounded labels, known-zero
  versus pending/missing values, dismissible action errors, valid seed defaults,
  proper loading state and safe rerun template recovery.
- [x] Host accessibility/terse state rows: 18/21, plus meaningful missing coverage.
- [x] Pricing completeness: row 94. Establish explicit member/backend evidence,
  preserve known charges and mark incomplete valuation without zero-value guesses.
- [x] Related test/doc gaps: realistic fixtures/default options/disabled queries,
  bounded deterministic clocks, missing sweep renderer cases and async test settling;
  correct supported-format comments and outdated historical instructions precisely.
- [x] Task Metric and Seeds/Repeats controls with coherent API ranking/panel state;
  retain existing secondary-score support and defer Export CSV.
- [x] Shared selected-run detail panel for training, agent evaluation, agent iteration
  and system benchmark tasks, with exact recorded paths/checkpoints and clear routing.
- [x] Training task/run tables for recorded steps, best/final metrics, resources,
  host and checkpoint metrics; best-config accent and recorded parameter subtitle.
- [x] Agent evaluation: comparable cost-aware headline, selected-target comparison
  and highlight, and trajectory first. Do not compare mismatched populations.
- [x] Agent iteration: compatible example flip comparison with version selectors
  and measured fixed/broken counts.
- [x] System benchmark: bounded raw samples, repeat flags computed from comparable
  recorded samples, and intentional baseline colors matching the accepted mockup.
- [x] Run charts: terminal empty wording and legends reflecting actual contributors.
- [x] Recheck every original triage row and UI-F17 row against final source; record
  evidence for implemented, already satisfied, intentional and Phase 3 deferred cases.
- [ ] Run actual merged-main CLI/SDK/MCP new-iteration harness and UI/Docker dogfood;
  fix discovered issues, retain raw logs/provenance and update the top-level handover.

## Verification ledger

The final integrated UI suite passes **1,088 tests** (4,747 assertions, 92
files) with no act warnings. All **80 browser tests** pass on the final build,
including authenticated Vite/static serving, both themes, editing and fake-host
launch projects. Visual inspection found one immediate-click dark screenshot captured before
paint. A bounded two-frame test-only wait corrected capture timing; both focused
training cases passed, and the light/dark images were inspected with the selected
heading in view. Application source was unchanged. The earlier isolated Docker suite passed **11 tests** and all three
shutdown scenarios passed; host code is unchanged by the final comparison fix.
Ruff/format (200 files), source ty, UI/e2e types, warning-as-error Sphinx and diff
checks pass. Final OpenAPI types were rebuilt from an isolated actual app schema.
The wheel and sdist match ten changed Python modules, all seven compiled UI
assets, and the schema helper/types; internal plans/mockups are excluded.

Final row audits are in `backlog-final-minors-1-48.md`,
`backlog-final-minors-49-95.md` and `backlog-final-ui-f17.md`; they represent all
95 original minors and 22 UI-F17 features exactly once. Their explicit limitations
supersede earlier work-package snapshots. The stale per-example comparison is
closed by UI gating plus strict opt-in server verification; 91 affected frontend,
105 query/API and 16 final strict tests passed, followed by an independent five-case
recheck. Original minor test gaps 25, 33 and 50 are also closed.

The initial full Python run recorded 2,458 passes, three skips and an additive
JSON-key snapshot mismatch; the reviewed update then passed all four snapshot
tests without update mode. The fresh final full Python run passes **2,475 tests**, with **3 skips** and
**11 Docker tests deselected** (602.00s). The actual candidate smoke harness is independently
prepared and validated under `/tmp/hx-handoff-evidence/final-dogfood/`; it must be
rerun against clean merged main. Current-head CI, authorized merge, fresh
CLI/SDK/MCP/browser/Docker dogfood and the handover summary remain pending.
