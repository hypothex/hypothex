# Bounded backlog backend

Base `/tmp/hx-backlog` at `fda761c`. Parent owns UI, generated models/types and
shared docs. This worker owns Python source/tests and this task log; no commits,
pushes, full suite, Docker, real hosts or SSH access.

## Accepted work and planned contract

- [ ] Add `primary` leaderboard query and `PanelData.primary` selection with
  configured metric/recorded key validation. Recompute ranking, direction, unit,
  headline, stat strip and matching per-example evidence. Default remains the
  configured task primary, and cache identity includes the selection.
- [ ] Persist GPU pricing completeness at cost computation, preserving explicit
  zero rates and distinguishing legacy unknown pricing. Propagate conservative
  per-member completeness to seed-group cost metadata while retaining known sums.
- [ ] Emit agent_eval cost-aware comparison only when scored member population,
  success fields, price completeness and comparison denominators are justified.
  Otherwise keep generic headline; never hardcode mock percentages.
- [ ] Establish RED regressions, implement scoped changes, run affected checks and
  uv/Ruff/ty, send exact contract/evidence to parent and independent reviewer.

Key constraint: MetricSpec currently declares no output key registry. Alternate
metric names must belong to task.metrics; explicit output keys can be accepted
from the configured task primary or observed scores at the requested version,
with ordinary `value` supported for an otherwise unscored configured metric.
Unknown arbitrary keys must not silently produce a relabelled primary board.

Evidence directory: `/tmp/hx-handoff-evidence/backlog-backend/`.
# Backend backlog implementation

Scope: additive primary selection, explicit GPU-pricing completeness, conservative agent-evaluation cost comparisons, and recorded identities for curve/grid/repeat UI controls. Python ownership only; no commits, pushes, real hosts or Docker.

- [x] `GET /api/v1/tasks/{project}/{task}/leaderboard?primary=metric/key` recomputes ranking, direction, unit, headline and primary-example statistics. Version pins remain independent. Invalid metric/key selections raise `ConfigError`; cache keys include the selection.
- [x] `PanelData.primary` supports leaderboard/stat-strip ranking, curves best accent and best selection; primary field/unit/direction are returned. Curve groups expose common recorded parameters, member IDs and a uniquely matching scored best group; grids expose member IDs.
- [x] `CostTotals.gpu_pricing_complete` distinguishes known/free rates (`true`), missing GPU rates (`false`), and legacy unknown (`null`). Known cost sums are preserved; row `cost_complete` requires every member explicitly complete.
- [x] Agent-evaluation cost headline and per-attempt stat require actual homogeneous binary evaluation populations, selected score version/source, dataset identity and example-ID identity. Counts include all scored billed repeats, never seed-count times confidence-interval size. Any unscored, failed or active nonarchived same-identity task member suppresses complete-population and complete-cost claims while preserving existing scored-row membership. Generic task wording is unchanged.
- [x] System benchmark p95 time rows expose `repeat_observations` only for complete homogeneous recorded scores at the selected version/key, known dataset identity/source, lower-is-better and unit `ms`/`s`; otherwise the list is empty. More than 128 members returns an empty list rather than sampling.
- [x] Dedicated initial RED: 16 failed / 10 passed; repeat contract RED 6 failed; exact value evidence RED 1 failed. Logs under `/tmp/hx-handoff-evidence/backlog-backend`.
- [x] Persist exact per-example file SHA256, full unique evaluated prediction-ID SHA256 and count on `ScoreRecord`. The worker emits bindings only for current complete output; query hashes the exact parsed bytes. Old unbound records and stale/partial output cannot support population costs; ordinary successful reevaluation remains usable. JSON record/index storage preserves fields with no schema migration.
- [x] Final affected regression suite: 440 passed (45.61s), including real evaluation worker -> score file -> index -> query -> repeated reevaluation -> aggregate-only/partial rejection. Final selector and fake-hub cost checks: 51 passed, 120 deselected (4.75s). No real hosts/Docker/full-suite run by this worker.
- [x] Scoped Ruff lint/format, `ty check` and `git diff --check` pass. Independent reviewer rechecked omitted statuses, latest error, artifact binding, source drift, percentile direction and 128/129 cap; no remaining backend blocker.

UI integration contract: `board.primary` is normalized `metric/key`; `metric_versions` lists configured task metrics and row score keys provide observed current-version choices. `evaluation_population` contains metric, version, source_hash, field, dataset_fingerprint, example_ids_hash, examples, attempts, solved. Repeat observations contain run_id, value, metric (name only), version, key (key only), source_hash and dataset_fingerprint. Panel leaderboard meta includes kind.

Final limitations: legacy score records without evaluator-issued file/population binding omit cost-per-population claims until successful reevaluation. Existing configured system-benchmark percentile direction remains backward-compatible; selecting another metric honors its configured direction. Parent owns documentation, UI integration and full-suite verification.

## Strict opt-in example comparison follow-up

- [x] `GET /api/v1/compare/examples?require_bound=true` opts into current evaluator-bound comparison. The core query gains a keyword-only `require_bound=False`; default Examples behavior stays compatible. Response schema is unchanged.
- [x] Strict mode validates the latest requested metric/version batch, healthy known scorer source, exact artifact-byte SHA256, full unique evaluated ID fingerprint/count, and complete binary outcomes. Pair project/task, dataset and scorer identity must match; independently complete cohorts may differ, and existing output counts refer to their exact shared intersection.
- [x] The hash and comparison map use the same immutable byte snapshot. A second file read plus score/run snapshot checks reject observed concurrent replacement, new evaluation or identity changes. Aggregate-only reevaluation, unbound legacy metadata, tampering, unknown source and mixed datasets return `EvalError` without outcomes.
- [x] Initial strict contract RED: 10 failed (new opt-in absent). Affected query/API regression: 105 passed (23.53s). Final strict regressions: 16 passed (6.01s), including successful real workers/re-evaluation, stale aggregate-only legacy compatibility, full-cohort intersection, file replacement, new evaluation, nonbinary/missing field rejection, task identity and exclusion of the legacy unbound file reader.
- [x] Scoped Ruff lint/format, `ty check` and diff checks pass. No commit. Parent owns generated API types/full checks/user documentation; auth_api owns frontend client/query/gating.
