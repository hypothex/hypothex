# Phase 3: final formal round and bounded resolutions

Actual formal round 6 ran with `codex exec -s read-only`, approval policy `never`, against plan commit `c40e830b73d87c2c666140407a9c6edb0ad7c489` and actual merged main `54259b0fbfff70b20f612e3e508da37d65efeff5`. It exited successfully with **three P2 findings and no P0/P1**. This is the sixth and final formal round; no seventh round was run.

The formal reviewer classified the selected MCP credential/sentinel/lazy-import behavior, storage reader aliases and locked apply, mixed-unit exports and authenticated Blob downloads, durable partial-sweep notification retry, and the Task 31 pytest import as FIXED. Eight of nine round-5 findings were FIXED; round-5 configured-agent handling remained partial because `add_note` still dropped agent selection.

## Final findings and plan corrections

1. **Sweep error responses:** Task 23's replacement handler omitted merged behavior. The plan now retains active-issuance and legacy-resume 409 responses, incomplete-sweep 503 with exact `sweep_id`, `project`, `host`, `launched`, `total`, `hint` fields, interrupted-command 409 and view issues. Authentication 401/challenge and scope 403 are additive. A prospective API regression checks all three sweep variants.
2. **MCP note attribution:** Task 32 now derives a scoped writer with `agent_identity(agent)` and forwards `agent=agent`. Unscoped notes preserve the caller's raw `author`. The adjacent `stop_run` replacement also retains the existing optional agent argument. Prospective registered-tool tests cover local/forwarded notes, session/LOCAL_OWNER callers, configured/explicit agent, and a nondefault raw author; existing forwarding coverage now includes stop.
3. **Serve access logging:** Task 39's replacement `uvicorn.Config` retains `access_log=False`. The existing three-kind logging regression remains part of acceptance.

The RST example title is now `Storage cleanup` so `git diff --check origin/main` does not mistake its seven-character heading underline for a conflict marker.

## Bounded verification after formal review

Before/after probes execute exact planned snippets with local fakes and actual baseline exception/response classes. Before correction they reproduce all three findings. After correction, all nine exception-envelope cases pass, all eight note-attribution combinations pass, and captured serve configuration disables access logging. No app, server, real host or external service is started. Added test snippets are Ruff-formatted; combined proposed test modules parse and pass undefined-name checks. These prospective product tests have not been executed against an assembled Phase 3 implementation.

The final static audit retains complete coverage of 54 existing HTTP entries, 29 MCP tools and 17 `once`/`forward` call sites. The formal reviewer independently verified 19 frontend source blobs and 12 historical replacement anchors against actual main. The final branch diff check passes; source, UI, tests, dependency and task trees remain identical to the pinned main baseline.

Formal artifacts: `/tmp/hx-handoff-evidence/phase3-round6/` contains the exact argv, command, prompt, metadata, raw stdout/stderr, final findings and exit code. Post-review probe source and before/after logs are under `/tmp/hx-handoff-evidence/phase3-round6-fixes/`.

All reported final-round P2s are addressed in the plan and verified by the stated bounded checks. This is **not a clean formal-review verdict on the post-review commit**, and it is not Phase 3 implementation or assembled integration evidence. Implementation, full API/MCP/browser suites and planned PostgreSQL/Docker acceptance remain future work under the plan. Hand back the docs-only branch for the authorized draft review; do not start Phase 3 implementation.
