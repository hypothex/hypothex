# W&B local logs and exported history — complete

Local implementation on `feat/wandb-logs`, based on main
`a078838ab7f65c1c53b8af29137f98a7b3064b52`. Working tree:
`/tmp/hx-wandb-logs`. PR publication and independent review requested on 2026-10-22.
See `tasks/pr-wandb-visuals.md` for publication status.

## User requirement and behavior

Support both local W&B run logs and exported history. The user explicitly selected
both formats in response to the scope question.

`hx import wandb PATH [--repo PATH] [--task TASK] [--json]` accepts:

- Completed version-0 binary `.wandb` files or a run folder containing one such
  file. Optional `hypothex[wandb]` supplies protobuf definitions; no account/network.
- CSV, JSONL and JSON arrays of history rows, using only the base installation.
  Each export becomes one historical snapshot, with the file stem as its name.
  Finished denotes completed import, not a known original process exit status.

Scalar history enters native metrics storage/index/API/views. Names, steps and
numeric timestamps are retained; binary logs also retain config, tags and source
metadata. Long/multiline names are normalized for display, with originals in
provenance. Text decimal/exponent steps are checked exactly before int64 storage.
Sources are read-only. Identical bytes/format/project/task return the existing run.
Malformed/unfinished binary logs and malformed/empty exports publish no partial run.
Full scalar history remains on disk; initial indexing is bounded. Import publication
and indexing recover through the existing missing-run repair after interruptions.

## Completed work

- [x] Streaming binary framing/CRC validation and genuine W&B fixtures.
- [x] Bounded CSV/JSONL readers and JSON row-array reader.
- [x] Native importer, CLI, project/task associations and provenance.
- [x] Regression, API, duplicate, malformed-input and recovery tests.
- [x] README, CLI/Sphinx guide and optional-dependency CI coverage.
- [x] Independent reviews; all reproduced defects fixed and independently rechecked.

## Verification

- Final affected suite: **268 passed** (importers, CLI, core sources/store/index).
- Separate installation without W&B: **107 export tests passed**; source ty passes.
- Ruff, format, full-source ty with the extra, warning-as-error Sphinx, diff whitespace
  check all pass.
- Broad Python run before the export extension: **3,804 passed, 3 skipped, 29
  deselected**, four offline bootstrap failures because cached psutil registry
  metadata was absent. After the repository's CI cache-warm step, all **four
  bootstrap tests passed** in the earlier 215-test affected run. The broad run
  did not include the subsequently added export cases; unchanged test evidence
  was reused instead of repeating the full suite.
- Real offline SDK **0.31** run imported end-to-end; genuine SDK **0.25** fragmented
  log validated. Typed history fields, nested metrics, failed runs and readonly
  inputs covered.
- Review fixed: long W&B display names, decimal step rounding across all export
  formats, and JSONL BOM followed by a blank first line. Exact-step/BOM regressions
  failed before the reader fix (10 failed / 3 passed), then passed.
- Final independent verdict: **LGTM**. Five original export probes and 21 additional
  signed-int64/alias/fraction/overflow/atomicity boundary probes passed. Earlier
  three name/recovery/rerun probes also passed.

Key commands:

```sh
TMPDIR=$(mktemp -d) uv run --extra wandb pytest -q
TMPDIR=$(mktemp -d) uv run --extra wandb pytest -q tests/importers tests/cli/test_cli.py tests/core/test_sources.py tests/core/test_store.py tests/core/test_index.py
uv run --extra wandb ruff check .
uv run --extra wandb ruff format --check .
uv run --extra wandb ty check src
uv run --extra wandb sphinx-build -q -W -b html docs docs/_build/html
```

## Limits and handoff

No cloud fetching, live tailing, media/artifact import, run-summary-table inference
or multi-run splitting. CSV/JSONL have a 64 MiB logical-row cap; JSON arrays a
64 MiB whole-file cap. Binary logical records have a 64 MiB cap. Exports can only
preserve what was exported; sampled exports remain sampled. Docker/package/UI
suites were not rerun for this Python importer feature.

A recoverable implementation patch and this report are also saved outside the
execution worktree at `/Users/shreyasv/.codex/reports/hypothex-wandb-logs/`.
