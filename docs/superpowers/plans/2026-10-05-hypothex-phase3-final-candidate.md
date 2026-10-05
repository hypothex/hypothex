# Phase 3 final local prerequisite candidate

This checkpoint merges local `token-default` at `138166274d46b0a285c28b1106059c6fab715f3f` into Phase 3 plan commit `95be1e843ff9e644220eeadf9a156e321239623d`. It contains step 8 at `acaf680` and the final credential-intent guards. The merge is local, without rebase, and had no conflicts. Runtime, UI, tests, dependency files and task files remain exactly the incoming candidate; only Phase 3 plan documents receive additional changes.

The earlier local checkpoint's pending mutation-intent fix is now included. Formal round 5 remains pending the final `origin/main` after prerequisite PRs #19, #20 and #21. This checkpoint does not push, publish or implement Phase 3.

## Preserved interfaces

- `useAction` captures `Vars.generation` for each click and checks it before/after each send and before invalidation/callbacks. `shouldRetry` rejects `AbortError`. `launchSeeds` captures its generation around every seed request, and `LaunchDialog` checks before progress and post-outcome state/cache/navigation effects. The plan consumes these hooks unchanged and retains the replacement-credential regressions. An old command ID does not authorize a retry as a new principal.
- `queryKeys.environment()` and `useHubEnvironment(opts)` remain the shared descriptor query for Overview, Run and the command palette. The Run query remains disabled without a sweep ID. The always-mounted Phase 3 reset wrapper still clears the full query client and side caches when credentials change. Task 8's Overview import replacement now uses the actual shared-hook baseline.
- `PanelData.max_points` stays nullable, constrained to 2–500, with 500 as the default. Backend curves retain the selected LTTB limit. The Run page passes metric names into `runViewPanels`, which sends explicit displayed metrics, excludes reserved sweep/step histories, splits more than 100 references into chunks and sends an empty list when nothing is displayed. Phase 3 models/type generation must retain those fields and bounds.
- Run actions retain infer-stage availability, run-ID-qualified re-evaluation summaries, served-host routing, conditional queued cancellation and timed two-click running stop. Task and Run share `ReevalSummary`; `SlashPath` stays shared between overview failures and artifact paths. Cleanup rendering preserves slash wrapping and accessible link labels.
- The paper-baseline adapter retains the measured plot-width tick count and endpoint label CSS. Existing Scatter/Vega layout fixes, safe error-envelope presentation, shared billed-GPU calculations and their tests remain inherited; Phase 3 additions do not replace those modules.

## Verification and limits

Evidence directory: `/tmp/hx-handoff-evidence/phase3-final-candidate/`.

The frontend preflight passes 12 historical exact anchors and 19 inspected source blob identities. Additional extraction applies all current replacement pairs in the affected source sections: five for WhereList, two for Overview and eight for Leaderboard. The three composed TSX sources parse, and structural checks confirm the shared hub query, SlashPath accessibility, cleaned-link removal, baseline domain extension and measured-width tick density remain.

The source hashes of the mutation guards, launch dialog, query hooks, run-view metric selector and backend panel cap are recorded. `git diff 1381662 -- src ui tests pyproject.toml uv.lock tasks` is empty; `git diff --check` passes. Evidence logs and hashes are retained with the probe scripts. No runtime source changes were made to obtain these results.

The prerequisite's completed suite evidence belongs to the coordinating run and is not rerun or relabeled here. These local checks are document-adapter verification, not full Phase 3 assembly, UI typechecking, browser acceptance, Docker/PostgreSQL verification or formal round 5. Reconcile any later main-branch delta before consuming that formal round.

## Final PR21 candidate refresh

The next local plan merge takes `token-default` at `a2f06e44a767b103b81a03e69dbd3a85d2053856`, with plan parent `dcfb05f587b4ed467ae666c6736c63143e5637e7`. Relative to the previously reviewed `1381662` candidate, the complete incoming diff is six added verification lines in `tasks/todo.md`. Runtime, UI, tests and dependencies are identical, so the preceding source-adapter evidence remains applicable. The merged task receipt is preserved exactly from the incoming candidate. Evidence for the commit/tree comparison and unchanged 12 anchors/19 source blobs is in `/tmp/hx-handoff-evidence/phase3-pr21-candidate/`.

The three active plan documents now identify the final PR21 candidate. This remains a local candidate: PR20 was reported merged at `7d04fe1`, and PR21 was still open when this refresh was requested. Formal round 5 must run against the real merged main after PR21, not this branch. No push, PR, Phase 3 implementation or formal review round is authorized by this checkpoint.

The pending backlog adds optional score artifact/population bindings, but is not in this candidate. The contract and PostgreSQL adapter now explicitly preserve those fields through the existing full-model score JSON and rebuild paths when that backlog is adopted. No extra score payload format or SQL migration is introduced, and absent historical bindings are not backfilled. This is a compatibility note, not a claim that the backlog has merged.
