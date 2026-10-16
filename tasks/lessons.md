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

## 2026-10-17 — cleanup selection and shared ownership

- Check cleanup selection for every overlapping artifact binding, including other kinds on the same run. Run eligibility alone does not authorize deleting an excluded artifact. Repeat the complete selection check on the owning environment at apply time.
- Deduplicate physical deletion and confirmed byte totals without dropping run associations. Verify cleaned markers and events for every affected run, including mirrored hub records, equal paths, nested paths and aliases.
- Grouped deletion needs checks for every member's filesystem identity. A successful deletion of one representative path does not prove that another alias still points to the deleted object.
- Remote confirmation must match the owning filesystem's deletion roots and group membership in both directions. Aliases can merge lexical groups, split one lexical group, or reverse its ancestor root; checking only one form can understate confirmed bytes.
- Use a real HTTP client for tests aimed at a separate live environment server. An absolute URL passed to an in-process ASGI TestClient still exercises its attached application.

## 2026-10-17 — delayed browser routes

- Drain promises owned by delayed route callbacks before unregistering interception. In the installed Playwright version, `unrouteAll({ behavior: "wait" })` clears the handler list first; completion of one callback can auto-continue another held request before its later `fulfill`.
- Use a staggered two-request reproducer to establish the lifecycle race. Preserve callback failures and the original layout assertions; passing repetitions alone do not establish that an intermittent failure is fixed.
