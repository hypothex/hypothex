# Phase 3 pinned-baseline refresh

Status: document-only checkpoint. Current reviewed source baseline: main `1b769f4ce9210096640a7054f5d757f09f4bb4df`; preceding document checkpoint: `5fd089e959ed0c83a8e282919651879dd3f84ccc`. The original checkpoint below reviewed main `5c020378b75bcb2afeba427e85b2f075e8e70804` from starting plan commit `f776156729949645b3da19547ab85b684553a914`. This is the authorized repair of compatibility checklist items 1–7. Pending token/DF-48 interfaces are not treated as implemented, and no formal round 5 has run.

The original eight-item checklist, with its original line references, is preserved at `/tmp/hx-handoff-evidence/phase3-baseline-refresh/compatibility-checklist.md`.

## Document changes

- [x] Backend Task 4 and contract: schema 4, owner in shared `_run_values`, preserved parent, consistent owner list/count filtering and keyset pagination, live/rebuilt ownership regression requirements.
- [x] Backend Tasks 34–36 and contract: preserve SQLite path/store, generation and change markers, staged rebuild/catch-up, stale-score recovery, deferred metric points and `Context.open` ordering. Add an explicit PostgreSQL staged rebuild. Its transaction-local staging permits ordinary writes; final catch-up/publication takes the same exclusive advisory guard that every mutation acquires before live DML. Ordinary readers remain available. Failed publication rolls back, and cursor/stale-score/change tables are retained.
- [x] Alembic explicitly includes parent, carried/deferred tables and the composite point index. Metadata and migration agree on owner and integer widths. PostgreSQL generation SQL qualifies `meta.value` and casts via BIGINT. Steps, cursor sequences and change generations use BigInteger; score/point IDs use BigInteger with an SQLite Integer variant to preserve rowid behavior.
- [x] Backend Task 22 keeps the merged run-ID collision try/except while adding the cleanup lock.
- [x] Backend Tasks 23, 32, 33 and 41 preserve current TokenGuard/HTTP safety behavior, JSON POST test bodies, all current tool scopes, host-state forwarding without token discovery, response provenance, and hub timeout propagation. Task 33 retains Task 32's added `connect_host` scope when expanding its exact launch-tool set.
- [x] Frontend Tasks 4, 7 and 8 retain head lookup/cancellation, single-batch invalidation, stale-ticket rejection across stop/restart, confirmed recent targets, and grouped failure retry text. The preflight now checks eight critical source blobs as well as twelve historical snippet anchors; later baseline changes require re-reading affected sources before updating hashes.

## Supplemental review and evidence

A focused independent review of the current Task 34–36 edits identified PostgreSQL ambiguity in the generation conflict-update expression, accepted integer values exceeding PostgreSQL INTEGER, and the pending guarded-hydration lock-order integration. The SQL qualification and widths are repaired above. The accepted exclusive mutation guard avoids generation-row/pending-row inversions without moving `_touch` before a successful hydration claim. This review is supplemental; it is not formal round 5.

Focused probes are retained under `/tmp/hx-handoff-evidence/phase3-baseline-refresh/`:

- `probe.py`: extracted migration columns/nullability/primary keys/indexes match pinned-main metadata plus the planned owner and int64 adaptations; PostgreSQL generated IDs compile to BIGSERIAL. In-memory extraction of the constructor/shared row builder plus existing SQLite helpers retains owner, parent, generation and deferred metric points, and accepts int64 step/cursor and generation boundaries. A fake PostgreSQL session compiles staging/publication SQL and checks ordering and carried-table preservation. Twelve frontend anchors and eight recorded blob IDs match pinned main.
- `frontend-probe.ts`: the extracted Header TSX parses; the composed EventStream retains the head before ticket acquisition and subscription, and rejects a ticket returned from a stopped generation after restart.
- Complete extracted migration, Docker-test and MCP-test blocks pass Ruff import/undefined-name checks; six extracted Python blocks were formatted. `git diff --check` passes.

Commands: `uv run --no-sync python /tmp/hx-handoff-evidence/phase3-baseline-refresh/probe.py` from `/tmp/hx-af`; `bun run /tmp/hx-handoff-evidence/phase3-baseline-refresh/frontend-probe.ts` from `/tmp/hx-p3-plans`. Both final probes exited 0. The extraction supplies only the planned model/import additions needed by the isolated checks; it is not an assembled phase 3 implementation.

No real PostgreSQL, Docker, full pytest, full UI typecheck/build or application acceptance suite was run for this document change. SQL compilation/fake ordering does not establish PostgreSQL runtime locking, MVCC, sequence behavior or rollback. Task 36 includes real-container boundary, staging-writer, reader, publication rollback, final-guard and overlapping-rebuild acceptance tests for implementation.

## Final-main work still required

- [x] Reconcile merged guarded hydration from `1b769f4`: journal and guard the private `_replace_metric_points` before its DELETE/EXISTS claim; preserve status capture, rowcount, outside-transaction retry and unchanged generation when the claim loses. Task 36 now supplies concrete hydration/deletion, final-swap/status-retry, bounded-join and failed-hydration repair regressions. This checks the plan; PostgreSQL execution remains implementation acceptance.
- [ ] Reconcile final DF-48 durable queued/issuing/settling state, command receipts, attribution, state-change events and notifier deferral/restart/settlement semantics.
- [ ] Reconcile final default-token guard, static shell, credential gate, subprotocol ticket transport, private SSH sockets, identity verification and nullable local port, preserving caller-only forwarding and current timeout/error handling.
- [ ] Re-read every source changed after the pinned baseline, refresh exact replacement snippets/tests and frontend blob checks, then run actual formal rounds 5–6. Preserve round-4 evidence and distinguish document/probe validation from implementation suites.


## Merged security and bounded-metrics refresh

Source pin: `1b769f4ce9210096640a7054f5d757f09f4bb4df`. Changes remain confined to phase 3 documents; previous PostgreSQL, owner/schema, MCP and frontend fixes are retained.

- Correct Task 34's journal target to `_replace_metric_points`, because the merged public method now delegates. Preserve the marker/status CAS, outside-transaction retry and zero generation change on a lost claim.
- Preserve terminal-before-metrics publication across execution, fallback stop, SLURM settlement and mirror/index repair. Keep bounded live histories, full terminal histories, two-dimensional SQL chunking and exact non-metric state parsing.
- Add portable `reset_cursor` upsert-to-zero and preserve `cursor_hosts` and all rebuild-carried reservations, including identities with no runs. Retain claims-lock reservation before awaits, disabled/draining owners, old hostless-claim normalization before new alias writes, and removal/drain ordering. Storage routing uses verified ownership; uncertain input ownership continues to block all possible hosts.
- Retain the centralized local-repository gate and current remote snapshot behavior. The frontend's twelve snippets and eight source blob IDs still match the new source pin; no frontend implementation changed between these two pins.
- Add four concrete Task 36 regressions: cursor reservation/reset/rebuild/reopen; hydration versus deletion; hydration blocked by final swap then rejecting stale status and retrying terminal points; failed hydration journal repair. No formal round 5 has run.

Evidence: `/tmp/hx-handoff-evidence/phase3-merged-baseline/`. `contracts-before.txt` records four missing plan requirements before repair. `probe.py` composes the pinned index with the actual plan snippets in memory. It passes metadata/migration and int64 checks, PostgreSQL SQL compilation/order checks, frontend pin checks, both merged terminal/CAS cases, and the three portable new tests on SQLite. It verifies that the actual private mutation transaction enters the journal and writer guard before claim DML. The final-swap test is AST/Ruff checked only; its PostgreSQL concurrency behavior requires the planned container run. Full phase 3 assembly, Docker/PostgreSQL execution, UI build and acceptance suites were not run. Reuse the preceding frontend runtime evidence: only its baseline-reference text changed, and its source blobs are identical.

A bounded independent read-only review of Task 34's reset/private-mutator snippets and guard/rebuild ordering, plus the four new Task 36 tests, found no actionable P0–P2 issues. It checked the actual `1b769f4` mutator body, the lost-claim `_touch` bypass, and generation observation after the real writer guard. This is supplemental review, not formal round 5 or PostgreSQL runtime evidence.

Step 6 was inspected for future impact only. Its current working integration is not this merged baseline: SQLite corruption recovery (`_open_schema`/`_move_aside`) and gone-run repair may change constructor/recovery anchors; host alias transfer may also repair project ownership before claim labels; metric-name readers/cache file identity may change bounded-read call paths. Re-read final merged versions before adapting these plans. Preserve corruption-vs-operational-error distinctions and metadata/identity retention if that work lands; do not copy speculative bodies or assert it merged. Likewise retain the later overlapping-rebuild regression if present in final main.


## Step-6 and token prerequisite compatibility checkpoint

The subsequent [token compatibility checkpoint](2026-10-05-hypothex-phase3-token-compatibility.md) records the inspected step-6 merge and actual token working interfaces, exact document adapters, supplemental review fixes and executed composed probes. The historical full-plan pin above remains unchanged until the final merged token/DF-48 refresh. Earlier query-ticket, `discover_token` and whole-transport replacement instructions are superseded by those actual adapters; earlier evidence remains provenance for its own revision only. No formal round 5 has run.
