# W&B import and custom visuals PR

User requested publication and independent review on 2026-10-22.

- [x] Confirm intended combined changes and clean remote base.
- [x] Reuse final-state verification documented in wandb.md and visuals.md.
- [x] Commit intended changes, push feat/wandb-logs, and open PR against main.
- [x] Register PR with the current thread.
- [x] Independently review the exact PR diff and resolve reproduced findings.
- [x] Record review verdict and report PR/check status.

Base: a078838ab7f65c1c53b8af29137f98a7b3064b52 (origin/main, freshly fetched).
Scope: offline W&B binary/export import, typed Python dashboard authoring, inline
row query/render support, documentation and regression tests. Prior implementation
reviews and checks remain valid for unchanged code. No merge is requested.

## Published review

PR: https://github.com/hypothex/hypothex/pull/28
Implementation commit: 665507d6d6c6841f7c5529040db9d85d75a6bd77.
Independent review: LGTM, zero actionable reproduced defects. See
[the exact-scope review report](reviews/wandb-visuals-pr28.md).

Reviewer checked the implementation commit and the exact additional documentation/
test diff recorded in that report. It clarifies the existing whole-view YAML limits
and verifies that a rejected save preserves an existing view. Runtime behavior is
unchanged. Public API tests: 20 passed; Ruff/format, source ty and Sphinx passed.
The review report and this status update are administrative follow-up only.

CI runs on GitHub; local verification and independent review do not imply a green
remote CI verdict. No merge performed.

## Package CI follow-up

The first GitHub package job failed its schema-4 historical comparison because
PanelData now emits the additive default `rows: null`. The focused correction
allows only that null default at exact saved-view panel-data paths; unexpected
values/keys and changed historical data still fail, and frozen fixtures are intact.
The independent follow-up review is LGTM with zero reproduced defects; see
[the packaging review](reviews/wandb-visuals-pr28-packaging.md).

- New regressions: 2 failed before the correction, then passed.
- Package harness tests: 23 passed; packaging Ruff/format/ty and Sphinx passed.
- Full installed-wheel acceptance: 5 passed in 194.53s, including fresh token/team
  behavior, schema-3/schema-4 upgrade, restart and explicit reindex with browser checks.
- Independent reviewer: 2 schema regressions and 18 negative/nested probes passed.
- External sanitized package evidence: `/Users/shreyasv/.codex/reports/hypothex-visuals/pr28-package/`.

The follow-up is committed and pushed for fresh GitHub checks; these local results
do not claim the new remote run has finished. PR remains open and unmerged.

## October 23 correction and merge

User authorized fixes, both review personas again, further fixes, and merge.
Current main `05fd5ab` is integrated, retaining W&B, HF and S3 extras together.

- [x] Preserve exact JSON steps in both binary history encodings, leaving metadata JSON unchanged.
- [x] Skip duplicate history decoding after the immutable snapshot/hash, using persisted point counts; retain concurrent publication and index recovery.
- [x] Bound sparse/declared table rendering with visible truncation counts and regressions.
- [x] Verify and resolve GitHub's seed-invariant config-hash finding.
- [ ] Run affected Python/UI tests, integrated static/build/docs checks, and full CI.
- [ ] Re-review with adversarial and efficiency personas, resolve reproduced defects, push and merge the verified head.

Correction regressions: 13 Python tests failed before the importer fixes; table
SSR regressions failed on the prior unbounded renderer. Final checks and both
independent review verdicts will be recorded in the PR before merging.

The first correction passed 398 affected Python tests and all 1,517 UI tests,
plus repository Ruff/format, source ty, e2e TypeScript, build and Sphinx.
Efficiency review approved `16b9ba0`; the independent adversarial review found
that grouped imports still lacked native seed values. A public `task_runs` probe
reproduced two same-seed reruns counted as two samples. The follow-up retains
integer seeds in `RunRecord.seed`, with a failing-before regression for grouping
and sample counts, plus non-coercion coverage for other seed types.

### CI documentation ordering correction

Final-head Ubuntu/Python 3.13 CI passed 4,110 tests but failed the existing
`test_ui_page_is_in_toctree_after_views` assertion. Reproduced locally: the new
`visuals` entry interrupted the required `views` → `ui` adjacency. Move `visuals`
after `ui`, preserving every guide and the existing navigation contract. This
is a documentation-only change; importer and table review evidence is unchanged.

The first ordering correction missed `tests/test_skill.py`, which requires `ui`
immediately before `remote`. Its failure was reproduced locally. A repository-wide
search for every `index.rst` reader identifies the complete protected sequence:
`views` → `ui` → `remote` → `team` → `notifications` → `export` → `storage`.
Place `visuals` before that sequence and verify all docs-index readers together;
do not relax the existing assertions. Runtime implementation remains unchanged.
