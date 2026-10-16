# Lessons

## 2026-10-16 — review continuity and moving main

- A delegated task without a final report and explicit verdict is unfinished. Never report it as running without current task evidence.
- Keep prompts, task IDs, reports, coverage and probe receipts in durable storage outside `/tmp`; use temporary worktrees only for isolated execution. Commit final review records with their exact reviewed revisions.
- When a reviewer disappears or a session is interrupted, recover its recorded result or restart through an app-owned task and retain the returned task ID before reporting a restart.
- Before restarting a review, fetch main, inspect its diff against the reviewed baseline, and refresh every affected plan/test/source anchor. CI on the old branch and a historical LGTM do not cover a changed baseline.
- Preserve the original two-review implementation gate and test handoff requirements while recovering interrupted work.

## 2026-10-16 — deletion identity and current UI assertions

- Trace environment identity through report → plan → delete → cleaned manifest → UI. A run record's source environment is not necessarily the environment holding a local pulled copy. Local storage rows must use `ctx.descriptor.environment_id`; delete must reject a different target environment. Source artifacts must belong to the local environment, while local pulled copies may belong to mirrored run records. Test this distinction with equal paths in different environments and preserve host-response identity during hub merging.
- Adding an identity field at the final manifest is insufficient if the producer stamps the wrong identity. Review each constructor and forwarding/merge step before claiming the end-to-end contract holds.
- Derive installed-browser heading expectations from the current UI's computed `runTitle`. Use `toContainText` when the heading also includes a rename button; do not reuse old literal run IDs or exact heading text assertions without inspecting the rendered component. Keep this assertion aligned between the frontend plan and Task49.
