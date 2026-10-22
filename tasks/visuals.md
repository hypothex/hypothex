# Agent-authored tables and charts

Build on existing table/Vega-Lite panels, preserving the completed W&B work in this
checkout. PR publication and independent review requested on 2026-10-22;
see `tasks/pr-wandb-visuals.md` for publication status.

- Public `hypothex.visuals` classes: DataSource, Encoding, Table, Chart, Dashboard.
- Convert typed definitions to existing PanelSpec/ViewSpec and YAML; save validated
  task views from Python. Agents may instead submit YAML/spec via existing CLI/MCP/HTTP.
- Support stored sources plus explicit JSON rows computed by an agent. Inline rows
  work through existing table/chart query/render paths, with bounded finite JSON,
  filter/projection, and no ambiguous source-plus-rows definitions.
- Preserve existing Vega resource restrictions. No new chart engine or JavaScript
  execution path. Generic Vega-Lite specs remain available for advanced charts.
- Tests cover public authoring, validation/save roundtrip, API/MCP queries, inline
  runtime validation, source regressions, and existing table/chart UI rendering.
- Document runnable Python examples and teach the existing agent guide/skill the API.

Ownership: parent public authoring/docs/integration/schema; worker core views/panels
and inline regression tests. Independent review after implementation.

- [x] Typed Python API and public tests.
- [x] Inline backend rows and tests.
- [x] UI types/schema and renderer verification.
- [x] Docs/examples and agent guidance.
- [x] Affected checks and independent review.

## Completed verification

- User explicitly confirmed support for both stored run data and custom rows.
- Fresh TMPDIR affected Python gate: 684 passed in 154.49s (public visuals,
  core inline/views/panels, API, MCP, CLI, and the existing W&B import feature).
- Final literal-backslash guard: public visuals 19 passed after the change.
- Full UI suite: 1,514 passed; Table/Vega focused coverage includes real Vega
  SVG rendering for literal dotted/bracketed fields and arbitrary inline columns.
- Production UI build/typecheck, full repository Ruff and formatting, source ty,
  public-module doctests, Sphinx with warnings as errors, and diff checks passed.
- Isolated browser smoke: saved Python dashboard opened through the actual API/UI;
  two inline rows, exact model/score/group_id/label/run_id columns, no fabricated run
  links, and chart marks carrying score 0.84 and 0.91 verified in the rendered DOM.
  Temporary server stopped after inspection.
- Independent review: LGTM after reproducing/fixing inline metadata-name treatment
  and checking the installed Vega-Lite literal-backslash limitation. Reviewer ran
  133 focused Python tests, 17 table tests, and independent copy/mutation/field probes.

## Behavior and limits

- Typed helpers save local views; to_yaml/to_spec support existing remote submission
  routes. Custom rows are stored snapshots, while named sources query current data.
- Inline data: at most 2,000 rows, 1 MiB compact JSON, depth 64, finite numbers only.
- Existing table renderer shows at most 500 rows (with its count footer).
- Typed chart encodings reject literal backslash field names because the installed
  Vega-Lite compiler drops escaping in some transforms; rename those keys first.
  Dots/brackets work. Advanced raw Vega-Lite specs retain existing semantics.
- Docker, installed-package acceptance, and full browser e2e were not rerun for this
  change; the listed affected tests and isolated live browser check are the evidence.
- Implementation on feat/wandb-logs in /tmp/hx-wandb-logs; now authorized for PR.
  Prior W&B changes remain intact. Durable report and complete combined patch are
  copied under /Users/shreyasv/.codex/reports/hypothex-visuals/.
