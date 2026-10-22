# Independent focused review — packaging oracle compatibility

Verdict: **LGTM**. Actionable reproduced defects: **0**.

PR: https://github.com/hypothex/hypothex/pull/28

Reviewed committed baseline `098156f7baf2b136034082b1bad62033233704cc` plus the complete working diff in:

- `tests/packaging/installed_checks.py`
- `tests/packaging/test_runner.py`
- `docs/package-testing.rst`

Diff size: 39 insertions / 2 deletions. SHA-256 of `git diff --binary`: `b2b3a5e1ccb84f32d9ad739477bb98123487a9f4686921f9b5e6dbbc1026c15c`.

## Assessment

The captured package-job failure in `/tmp/hx-pr28-package.log` identifies the added default `rows` field at `view/spec/panels/0/data`; it is not evidence of changed historical stored-source values. The correction admits only a newly added `rows: null` at an exact saved-view panel-data path. `re.fullmatch` prevents ancestor, child, or unrelated paths from receiving the exception, and the `is None` check excludes empty/populated rows and falsey non-null values.

The allowance applies only when `rows` is absent from the frozen expected dictionary. Existing expected `rows` values still pass through normal recursive comparison. Required-key checks, historical field values, array lengths/order, and rejection of unrelated new fields remain intact. Historical fixtures are unchanged. Documentation describes the actual narrow exception accurately.

No unintended weakening of the historical oracle was reproduced. No production behavior changes are included in this follow-up.

## Independent verification

- `TMPDIR=$(mktemp -d) uv run --extra wandb pytest -q tests/packaging/test_runner.py::test_legacy_view_allows_only_null_inline_rows_default`: **2 passed in 0.10 seconds**, covering schemas 3 and 4.
- **18 additional fresh-temporary-directory probes passed**, across both schemas: nested root comparison with the new null field succeeds; removed existing source, changed panel-list length, changed field ordering, overwritten historical rows, removed historical rows, wrong path prefix/suffix, and `rows: false` each reject.
- `git diff --check`: passed.
- The reviewer inspected the captured CI failure and actual three-file diff. No source edits, fixture edits, commits, GitHub actions/comments, or further delegation were performed.

The parent is separately running the complete installed-wheel acceptance tests and checking CI. Those results are not claimed by this narrow review; the verdict covers the exact correction above and the independent comparison probes. Feature tests from review r1 were not repeated.
