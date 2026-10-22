# Independent PR review — Hypothex W&B imports and custom visuals

Verdict: **LGTM**. Actionable reproduced defects: **0**.

PR: https://github.com/hypothex/hypothex/pull/28

## Exact review scope

- Worktree: `/tmp/hx-wandb-logs`, branch `feat/wandb-logs`.
- Base: `a078838ab7f65c1c53b8af29137f98a7b3064b52`.
- Committed head: `665507d6d6c6841f7c5529040db9d85d75a6bd77`.
- Reviewed the combined base-to-head diff, including all new importer/public-authoring modules, backend/query changes, UI changes, schema regeneration, tests, dependency/CI changes, and documentation. No older branch comparison was used.
- Also reviewed the parent-authored, then-uncommitted addendum in `docs/visuals.rst`, `src/hypothex/visuals.py`, and `tests/test_visuals.py`: 27 insertions / 1 deletion. SHA-256 of the complete `git diff --binary` addendum at review: `1f7b4a5bd2fef5644679fa1253a9f4bcbe33d7c8efa741ca42fbbce44c4c6db4`.
- This verdict covers that exact committed diff plus this exact documentation/test addendum. Later changes require proportionate review.

The reviewer made no source changes, commits, pushes, merges, or GitHub comments, and did not delegate further. This report is the only persistent reviewer-authored artifact.

## Checks performed independently

1. Fresh temporary-directory affected gate:

   `TMPDIR=$(mktemp -d) uv run --extra wandb pytest -q tests/importers tests/core/test_inline_panels.py tests/test_visuals.py`

   Result: **197 passed in 13.83 seconds**. This includes genuine offline SDK history, old fragmented binary framing, malformed inputs, step precision, import recovery, typed authoring, inline boundaries, and HTTP/MCP integration tests.

2. Addendum regression:

   `TMPDIR=$(mktemp -d) uv run --extra wandb pytest -q tests/test_visuals.py::test_save_respects_whole_view_budget_without_replacing`

   Result: **1 passed in 2.24 seconds**.

3. Focused UI rendering:

   `bun test test/panels/Table.test.tsx test/panels/VegaLite.render.test.tsx`

   Result: **20 passed, 0 failed; 76 assertions**. Real Vega resource denial and dotted/bracketed literal fields passed. Inline table metadata-like keys, absent synthetic run links, and empty declared schemas passed.

4. `git diff --check`: passed.

5. Additional independent public-API probes, using a fresh temporary home/repository:

   - Four thread-synchronized identical imports into separate contexts produced exactly one `imported=True`, one run identity, one disk run, and the expected two indexed metric points.
   - Injected an exception in event append immediately after the staged folder was renamed into place. Reopening the home recovered the local run and its metric; retry returned `imported=False`; staging was cleaned. This verifies local disk/index recovery, not durable event replay or remote synchronization.
   - Saved and queried one dashboard containing both an inline table and a stored metrics table. The stored table returned all three imported points, inline literal `run_id`/`group_id`/`label` values stayed intact, and mutating returned rows did not mutate authoring data.
   - Independently generated within-panel-budget data exceeding the whole-view YAML event budget: 2,000 rows × 25 scalar columns, 414,001 compact JSON bytes; and two panels of 2,000 × 12 columns, 180,001 bytes per panel. Both rejected explicitly with the YAML event-limit message.

## Review conclusions

The importer snapshots the source before decoding, stages outside run discovery, consumes and validates the complete input before atomic folder publication, and derives duplicate identity from format/project/task/content hash. Initial metric indexing uses the existing bounded thinner. Full histories remain on disk; normal rebuild/recovery policies may read the full ended-run history, as documented. Binary framing limits, source immutability checks, malformed/unfinished rejection, scalar exclusions, and optional dependency isolation are covered by inspection and focused tests.

The typed classes produce existing PanelSpec/ViewSpec structures. Inline rows receive finite-JSON, size, depth, and exclusivity validation and are revalidated at query dispatch. Existing source queries remain on their original path. Inline projection/filtering and table rendering avoid synthetic run metadata semantics; chart encoding escaping and external-resource restrictions have direct render evidence.

The YAML-limit probe was initially a concern, but `docs/views.rst:178-179` explicitly documents the existing whole-view limit. Per-panel row/byte maxima do not override it. This is expected rejection, not a correctness defect. The reviewed addendum accurately explains the combined limits and adds a public-save regression proving that rejection preserves an existing saved view. No guard relaxation was needed.

No actionable regression or unfulfilled scoped contract was reproduced. Existing reported fixes were treated as hypotheses and checked against the actual diff and relevant tests, rather than accepted as proof.

## Evidence limits

This is a focused local review, not a complete deployment or real-service acceptance certification. The parent supplied earlier 684-test Python, 1,514-test UI, build/typecheck, Ruff, ty, doctest, Sphinx, and isolated browser evidence; those broad results were not independently rerun here. The parent also reported final addendum public tests and lint/type/docs checks. Docker, installed-package acceptance, the full browser end-to-end suite, and remote event replay were not exercised by this reviewer. Current GitHub CI status is for the parent to verify separately.
