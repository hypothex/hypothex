# Leaderboard backlog integration

Ownership: ui/src/panels/Leaderboard.tsx and matching unit test only; parent owns API models/adapters and backend owner supplies authoritative metadata. No commit, build/browser, or full suite from this worker.

- [x] Test and display incomplete GPU pricing without presenting recorded subtotal as a known total.
- [x] Agree authoritative per-run p95 observations and expected population; use repeatFlags for comparable complete data only.
- [x] Add measured repeat flag/unknown-state rendering and focused regression tests; preserve generic behavior without extra queries.
- [x] Run focused tests/types and hand off source/docs evidence.


## Contract and behavior

`LeaderboardRow.cost_complete === false` keeps the total unknown, labels a positive recorded subtotal as `$x recorded`, and retains GPU hours/time. Zero is displayed as a total only under the existing complete/legacy contract. Missing cost with explicitly incomplete metadata says `Cost unknown`. Tooltip distinguishes incomplete GPU rates or run cost records from a known complete cost.

`repeat_observations` is an optional array of `{run_id,value,metric,version,key,source_hash,dataset_fingerprint}` (backend defaults `[]`). `run_ids` supplies the exact expected group population. Checks apply only to `meta.kind=system_bench`, primary result key `p95`, `meta.higher_is_better=false`, and `meta.unit=ms|s`. Observation metric/key/version must match the selected primary and `meta.metric_versions`; every provenance field must be known. The full provenance tuple feeds existing `repeatFlags` from TaskInsights. Empty/partial/incompatible observations are unavailable, never an unflagged healthy population. Flags link exact run IDs and show the measured percent above median; exact +10% is not flagged. Generic, throughput, and other-percentile panels retain existing behavior. No data query added.

Backend supplies `meta.kind`; parent must include it, direction, unit, and metric versions in the direct Task board adapter. Parent owns models. Original minor triage rows 1–26 have no remaining source/test/doc changes in this worker's owned panel paths; their concrete gaps belong to API hooks/fixtures, Hosts, Overview, or historical plans.

## Verification

Evidence `/tmp/hx-handoff-evidence/backlog-leaderboard/`:
- `cost-red.log`: 18 pass / 2 fail before implementation; `cost-green.log`: 20 pass.
- `repeat-red.log`: 20 pass / 4 fail before repeat implementation; `repeat-green.log`: 24 pass.
- Added source/dataset/selected-version/seconds/greater-is-better regression. `final-focused.log`: 36 pass / 0 fail across Leaderboard (25) and TaskInsights (11). The earlier in-flight source-fingerprint test fixture was corrected by its owner; final combined focus is green.
- `types.log`: only concurrently added query test at `ui/test/api/queries.test.tsx:213` fails type inference; parent notified. No worker-file errors.
- `git diff --check` clean.

Parent owns final combined verification and documentation. Source frozen and ownership returned; no full suite/build/browser/Python/commit/push by worker.
