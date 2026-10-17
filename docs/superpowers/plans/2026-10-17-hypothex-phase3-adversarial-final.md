# Independent adversarial gate R2

**Verdict: LGTM for the full Phase 3 plan at `2ebfc28eeded41e236f5f93c05347a467328ef4b`, against main `f6f130cfa2669bfcccbadcb36282dd5fea881d1f`.** No demonstrated P0, P1 or P2 blocker remains. One previously reported optional P3 documentation note remains nonblocking. This is a plan verdict only, on the same input as primary R5; it is not an implementation, package-readiness or deployment claim. This reviewer stops here.

## Input and integrity

The frozen checkouts are `/tmp/hx-p3-plans` and `/tmp/hx-p3-main-current`. All eight SHA256 values are recorded below and in `review-input.json` and `receipts/inputs-{start,end}.json`. Both trees were clean at start/end; source/runtime/UI/tests/dependencies/workflows have no plan-versus-main diff. The user's root checkout retained its pre-existing `?? .superpowers/` status. No source environment, plan, source file or prior evidence was modified. Writes are confined to this evidence directory and owned disposable temporary paths. No child agent, commit, push, merge, real service or deployment was used.

| Input (paths relative to plan checkout) | SHA256 |
|---|---|
| docs/superpowers/plans/2026-10-04-hypothex-phase3-contract.md | `47e4f718043a115a999e1d446e21a48ac9f39c44170307ac884e23ea72f090c7` |
| docs/superpowers/plans/2026-10-04-hypothex-phase3-backend.md | `402c98af078692e9f465bf0e2668bc0c04dd0f1398e1d6117a4208c09896dd8a` |
| docs/superpowers/plans/2026-10-04-hypothex-phase3-frontend.md | `5c71dfc0e12e2c6f9fbfd1c592ad73826419c7b09110631df841c51c96bba757` |
| docs/superpowers/plans/2026-10-06-hypothex-phase3-package-acceptance.md | `0972c9439b864ba06c3f99a5f87c123a34deb7bf66be9f7fc1cd4a2596747027` |
| docs/superpowers/plans/2026-10-06-hypothex-phase3-main-refresh.md | `b0278eb1dd1869153b7c8550d13d01439317e3473952c7c1209f8edd673bc01f` |
| tasks/phase3-execution.md | `afe961c91bc7d9a5c735d2163524836bfe2e27945e4b0c1dbab2d9ccd38d8bff` |
| tasks/lessons.md | `2bf004304304606935d2a23f17cd2f36f4a8d963e8c515607299e7c7578a9bca` |
| tasks/ui-selection-ci.md | `7cb35a33b450d3e641f139ea9fb4cb9377fb4b0ddbd3367a123f3dbb93c7bcdb` |

## Independent review and fresh evidence

I reviewed the full scope through each task's current interfaces, rules, acceptance and cross-task dependencies, the contract/specifications/package supplement, the history and the actual current-source integration points. I inspected changed code and high-risk excerpts directly and reused unchanged detailed task-body reviews and tests only after checking task/source/dependency provenance. This is not a claim to have independently re-executed every historical test or reread every unchanged code-fence line. The explicit 49-backend/26-frontend/13-scope ledger is in `coverage.md`.

`tests/test_pg_edges.py` is fresh independent pressure on the corrected guard. **67 pytest cases pass** on Python 3.14.7, psycopg 3.3.6 and libpq 18.6. The exact guard fence SHA256 is `eb174c615f865fa5200c01c35c9661e4f1a00c917a3aaacbd355dfdebb5e2d39`. An inert `Connection._connect_gen` interception is installed before loading/calling any old or current guard; DNS and Python socket tripwires provide an additional boundary. Real libpq defaults inspection uses a synthetic HOME/service file and does not connect. Recorded connection I/O is zero.

- Thirty host/hostaddr combinations are tested as the second destination of a multihost connection, through both `psycopg.connect` and `Connection.connect`. This catches a guard checking only the first entry; accepted entries reach only the inert boundary with the expected effective parameters.
- Twenty present-variable combinations (ten PG names, empty/nonempty), each through both APIs, are rejected after guard installation. Errors disclose names, not values. The matrix includes service, host, hostaddr, password and other defaults, plus an unknown PG-prefixed name.
- Twelve conninfo/keyword/service precedence cases cover kwargs overriding unsafe conninfo, ignored None, empty URI service, hostaddr multiplicity, malformed/nonliteral destinations and the runtime's IPv4-mapped loopback classification.
- A1 is reproduced on the old guard using synthetic external PGHOSTADDR and blocked by the current guard. The empty-PGSERVICE reproduction uses a synthetic `[]` service section: real libpq defaults resolve its external hostaddr; the old guard reaches the inert boundary, while the current guard rejects it. With PGSERVICE absent the synthetic file contributes no hostaddr.
- The exact Task36 edit is applied in memory to main's real `run_cmd`. Captured final `subprocess.run` env contains no PG-prefixed variables from parent or overrides, retains non-PG fixture settings, and leaves input mappings unchanged.
- Task39's extracted tests are intercepted at their process boundary: all five launches have scrubbed final mappings, including `start()` after its overlay. These are environment-construction observations, not spawned product servers.

The initial probe run had two harness assertion errors, retained in `pg-edges-first.log`: Python 3.14 considers mapped IPv4 loopback local, and an inherited value must be read from libpq defaults rather than only explicit conninfo. Correcting those expectations produced the final pass; no product/plan change was made. `pg-edges.json` records the observations. Ruff check/format and ty pass.

`probes/audit_inputs.py` independently verifies all 51 current source anchors, the five-file main delta, PR26 head-tree equality with merge main, unchanged backend/dependencies/CI, earlier manifests and exact helper/migration/CLI provenance. `receipts/provenance.json` records these checks. The prior R5 73 guard tests and 15 SelectedRun tests with 6/5 mutation failures are inspected and manifest-verified evidence, not new executions here. R5's immutable R4 replay intentionally fails two old-behavior assertions; those are not unresolved current failures.

## Findings and dispositions

References B/F/C mean the current backend/frontend/contract plans; task headings are stable locators.

| Finding or objection | Independent disposition and evidence |
|---|---|
| **A1 ambient PostgreSQL defaults** | **Resolved.** B1 rejects every present PG name, explicit service, unsafe host/hostaddr and each unsafe multihost entry; pins aliases/default socket location. B36 filters after the real final merge, B39 after overlays, and B49 prescribes the same stdlib runner rule. Fresh inert red/green and final-env captures above substantiate the correction. Production PG support is unchanged. |
| **Empty PGSERVICE default** | **Resolved.** Presence, including empty values, is checked in the exact guard and C9 matrix. Fresh real-libpq-defaults red/green confirms the formerly missed empty section. |
| **PR26 selected-run seam** | **Preserved.** Main changes only five UI/doc/tracker files; eb503ee tree equals f6f130c. F24:335 and C10 expressly retain ancestor ResizeObserver, user takeover, queued-callback guard, cleanup/focus restoration and delayed-chart/manual-scroll tests. Existing component/test source and R5 mutation evidence support this; adding cleaned metadata does not require replacing that lifecycle. |
| F1 parent-symlink deletion | Resolved in design and bounded evidence. B22 uses no-follow physical-parent descriptors, literal/physical protection, identity checks, fd-relative measurement/removal, and no path fallback. All 12 current helper hashes match five earlier receipts (R2 four non-root environments and adversarial R1); each has 22 observations with protected bytes intact and zero descriptor delta. Full apply/env-route race acceptance remains mandatory. No claim of atomic leaf identity beyond that design. |
| F2 schema collision/missing name | Resolved. Schema5 retains name/index; exact B35 migration and actual model source match the earlier zero-difference SQLite metadata receipt. B49 separately restores immutable schema3=a444125 and schema4=e73b810. Those are historical provenance pins, not stale active-main pins. Actual PostgreSQL and wheel upgrades remain future acceptance. |
| F3 zero WS timeout | Resolved. B26 requires positive .01 tests, outer deadlines/cleanup and before-subscribe revocation; production30s and cursor/filter behavior remain. Earlier primitive probe is bounded evidence, not live ASGI acceptance. |
| F4 missing scope/rename forwarding | Resolved. B24/27/28/32 retain task-runs read and rename launch, request-aware forwarding and caller/route receipts. Prior actual-source inventory covers 56 routes/30 tools; those backend sources and policy bodies are unchanged. Real fixture success/denial/revocation is still required. |
| F5 hosts/queue shell | Resolved. B23/F7 extend the actual route constant, preserve hosts/queue and installed/static containment; pair is intentionally a full-load exception. Unknown/reserved paths remain guarded. |
| F6 q search lost | Resolved. B27 preserves q/max_length/search forwarding, owner/status/pagination and literal wildcard tests. Current CLI merge is preserved separately. |
| F7 obsolete UI owners | Resolved. All26 tasks target current AppShell/TopBar/NavTree/Home/task/run owners, FilesTab/FileList plus retained selected/training views. All51 anchors match actual files. Cleanup identity uses target environment plus raw path, including host/pulled distinction and legacy unknown state. Counts alone were not treated as completeness evidence. |
| F8 direction conflict | Resolved. B12 reuses key_higher_is_better, preserves explicit tri-state/config_format2 and selected primary; taskless omission defaults higher. HTTP/MCP/CLI/UI forwarding and opposing-ranking tests remain assigned. The task_table import correction survives. |
| F9 PG cache path | Resolved. B34 uses opaque per-Index lifetime identity plus generation, preserves SQLite inode/device behavior and makes overview JSON dialect-safe. B36 mandates actual names/board/taskRuns/overview/panels/reindex/reconnect/concurrency tests; a fake key is not claimed to prove SQL. |
| Refresh R1 traversal permissions | Resolved. O_PATH then O_SEARCH then conservative O_RDONLY; enumeration still requires read. Four non-root platform receipts match exact current helpers. Capability/fallback/race/leak/public-route acceptance remains. |
| Refresh R2 CLI merge | Resolved. B42 is three additive edits. Current Task4/42 bytes match R3 aside from active snapshot pin; schema fixture pin intentionally stays historical. Inspected applied diff retains merge, duplicate precedence, sort/limit, host_state/status/local time. Reused R3 logs: baseline7, corrected14 and5 edges; snapshot changes are exactly two owner keys. Real authenticated loopback/login cases remain assigned. |
| USER=alice escalation | Rejected allegation remains rejected. ensure_owner does not promote an existing launch user; mint_local requires an existing enabled admin. No contrary evidence found; deterministic package USER=sv is synthetic-only. |
| Earlier main/cost/alias/SPA/package fixes | Retained: explicit cost completeness, selected primary/bindings/require_bound, trusted home/store alias protection, exact routes, concrete B49, step-level runner.temp, source sync before pytest and team-only USER pin. Historical missing /tmp probes were not treated as inspected evidence. |
| Unknown-cost screenshot | Known nonblocking visual limitation. No fresh screenshot is claimed; false/null/missing completeness and zero/nonzero recorded subtotals remain explicit textual/component acceptance. |
| R3 wording nits | Corrected all49/all26 tracker and historical schema4 wording remain corrected. |

### P3 documentation note

Primary R5 noted that F26's `docs/ui.rst` preservation list does not explicitly name PR26's newly added selected-run reveal paragraph. I agree this is nonblocking: the paragraph exists in the current baseline, F26 calls for additive documentation, and F24/C10 expressly preserve the behavior and regressions. Preserve the paragraph during implementation. No change to this frozen input, extra approval condition or wording-mirroring test is required.

## Limits and remaining implementation acceptance

No assembled Phase3, real PostgreSQL, Docker, installed wheel, browser or live CI was executed by this review. Fresh testing is bounded parsing/default resolution and intercepted environment construction. Historical baseline UI CI/merge receipts were inspected locally, not refreshed from the network. The guard targets the two planned synchronous psycopg APIs; this does not claim arbitrary native connectors or async drivers are sandboxed.

Required future acceptance remains concrete: actual PostgreSQL locking/MVCC/migrations/recovery and SQLite equivalence; public cleanup/host routes with races and locks; authenticated ownership/session/MCP matrices and real loopback CLI login; complete UI v5 and both-theme browser regression suites; fresh wheel and both authentic old-home upgrade/restart/reindex scenarios; packaged assets/migrations and sanitized cleanup evidence. None is waived by this LGTM. The absence of that not-yet-implemented runtime is not itself a defect in this plan.
