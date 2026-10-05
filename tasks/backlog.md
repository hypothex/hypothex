# Post-handover backlog

Planning baseline: `1381662` in `backlog-polish`, inherited from the fully checked
combined token candidate. Merge final `origin/main` before publication. This plan
is prepared during CI waiting; implementation begins after the ordered queue is
published and the Phase 3 draft is ready. No Phase 3 implementation is authorized.

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

- [ ] Launch correctness and recovery: original rows 27/28/30/35/37/41/42/48
  (46/53 duplicates). Preserve direct argv semantics; warn about attached shell
  operators, remove quoted backslash-newline, quote leading equals, handle the
  maximum seed, surface real resource errors, keep selected host visible, preserve
  partial-success feedback and make opening errors dismissible/retryable.
- [ ] Sweep correctness and presentation: rows 59/60/61/63/68/71/74/75/78/82/83
  (64 duplicate). Use deterministic numeric/text ordering; authoritative counts
  with partial rows; accurate legends/accessibility, bounded labels, known-zero
  versus pending/missing values, dismissible action errors, valid seed defaults,
  proper loading state and safe rerun template recovery.
- [ ] Host accessibility/terse state rows: 18/21, plus meaningful missing coverage.
- [ ] Pricing completeness: row 94. Establish explicit member/backend evidence,
  preserve known charges and mark incomplete valuation without zero-value guesses.
- [ ] Related test/doc gaps: realistic fixtures/default options/disabled queries,
  bounded deterministic clocks, missing sweep renderer cases and async test settling;
  correct supported-format comments and outdated historical instructions precisely.
- [ ] Task Metric and Seeds/Repeats controls with coherent API ranking/panel state;
  retain existing secondary-score support and defer Export CSV.
- [ ] Shared selected-run detail panel for training, agent evaluation, agent iteration
  and system benchmark tasks, with exact recorded paths/checkpoints and clear routing.
- [ ] Training task/run tables for recorded steps, best/final metrics, resources,
  host and checkpoint metrics; best-config accent and recorded parameter subtitle.
- [ ] Agent evaluation: comparable cost-aware headline, selected-target comparison
  and highlight, and trajectory first. Do not compare mismatched populations.
- [ ] Agent iteration: compatible example flip comparison with version selectors
  and measured fixed/broken counts.
- [ ] System benchmark: bounded raw samples, repeat flags computed from comparable
  recorded samples, and intentional baseline colors matching the accepted mockup.
- [ ] Run charts: terminal empty wording and legends reflecting actual contributors.
- [ ] Recheck every original triage row and UI-F17 row against final source; record
  evidence for implemented, already satisfied, intentional and Phase 3 deferred cases.
- [ ] Run actual merged-main CLI/SDK/MCP new-iteration harness and UI/Docker dogfood;
  fix discovered issues, retain raw logs/provenance and update the top-level handover.

## Verification ledger

Pending implementation. The candidate smoke harness is already independently
prepared and validated under `/tmp/hx-handoff-evidence/final-dogfood/`; it must be
rerun against the final merged main. No production backlog edit has been made.
