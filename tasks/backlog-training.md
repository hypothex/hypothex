# Training detail components

- [x] Inspect run, score, checkpoint and live metric contracts.
- [x] Add failing regression coverage for validation/evaluation separation, missing/killed/live records, and bounded pagination.
- [x] Implement reusable TrainingRuns, TrainingCheckpoints, CheckpointTable components.
- [x] Run focused tests and report integration props.

## Integration

Import from `ui/src/pages/components/TrainingDetails.tsx`:

- `<TrainingRuns project={project} task={task} onSelectRun={setSelectedRun} />`
- `<TrainingCheckpoints project={project} task={task} onSelectRun={setSelectedRun} />`
- `<CheckpointTable artifacts={detail.record.artifacts} />`

The optional selection callback handles unmodified clicks only; links retain `/r/<id>` destinations. Components reset their pagination when project/task changes. Components provide tables/content; caller supplies surrounding panel titles/layout.

## Data rules and capacity

Checkpoint best step means maximum recorded checkpoint `val/top1` (first recorded wins ties), never a maximum from thinned histories. `top1/value` and `top1/final` remain run-level current-version evaluations; most recent errored scores remain errors. All checkpoint metrics keep their exact names and values, and absent fields stay missing. No test score is copied onto a checkpoint. GPU and memory are the last recorded `sys/gpu_util` / `sys/gpu_mem_gb`, with their measurement step in tooltips.

Twenty rows per page with a twenty-first lookahead and backend keyset cursors. One curves request per page restricts run IDs before history reads and uses `max_points=2`, retaining last observations. At most twenty run-detail requests per page share existing query keys. Checkpoint tables require only the paged run list. Query keys participate in existing live invalidation.

## Verification

- Initial failing import test preserved in `/tmp/hx-handoff-evidence/backlog-training/red.log`.
- Pagination error regression reproduced before repair; `pagination-red.log`.
- `bun test test/pages/trainingDetails.test.tsx`: 8 passed, 33 assertions; `focused.log`.
- `bun run typecheck`: no TrainingDetails errors; concurrent integration errors in KindPanels/PanelGrid props and not-yet-created TaskInsights recorded in `typecheck.log`.
- `git diff --check`: clean at verification time.
- No full test suite, build, browser, commit, or push performed.

Parent owns Task/Run wiring, user-facing docs and final assembled checks.

## Run page and selected-run integration

- Added training checkpoint Figure to Run.tsx without changing ScoreRecords or generic run layouts.
- Run's KindPanels receives `currentGroupId` from the authoritative leaderboard row matching run ID (RunRecord has no seed_group) and `runStatus` from the record.
- Added `SelectedRun({runId: string, onClose: () => void})`: own region/header; dismissible loading/error states; exact WhereList, stored parameters, status and evaluated score records; checkpoint metrics for training; Open run link opens the full route in a new tab and bypasses task inline-link interception.
- Tests written first: run-selected-red.log captures initial failures.
- Initial focused Run/selectedRun verification: 20 passed, 64 assertions.
- Broadened affected RunRemote + Run + selectedRun + trainingDetails evidence: run-selected-focused.log.
- Parent owns Task wiring and final assembled verification.

## Independent review follow-up

- Reproduced actual reevaluation failures (`ScoreRecord.key="*"`, error set, older value/final rows retained). Newer or equal-time wildcard errors now supersede each selected top1 key in the training table; a later successful reevaluation recovers and other metric versions cannot leak into current scores.
- Added explicit discovered history metric names from existing run-detail reads. All observed names remain eligible for last observed step; >100 names split across panels in a single request with max_points=2, and all panel rows contribute to the result. No unrestricted history request for empty name lists. Metadata failures stay unavailable.
- RED: 9 passed / 4 failed (`wildcard-red.log`); GREEN: 13 passed / 49 assertions (`wildcard-focused.log`). Parent's independent assembled test run also observed precisely those four intentional RED failures while implementation was in progress.
- Checked existing ScoresList semantics read-only: latestScores preserves both wildcard error and old key rows as timestamped records; separate scoreFor helper still returns the prior healthy value. Reported that reproduced broader helper issue to parent, without changing shared behavior here.
