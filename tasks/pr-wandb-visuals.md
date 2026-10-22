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
