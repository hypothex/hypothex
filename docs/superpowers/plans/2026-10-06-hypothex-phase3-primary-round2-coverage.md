# Claude r2 coverage ledger

Inputs: plans 9cbe8a3b1d3a6f394773546d334ed799b05417bf (clean), main a4441256f39d014d9ad43dea976af1b448f163e3 (clean).

## Contract
- Read fully (674 lines).

## Backend
- T1 network guard: read. Anchors (pytest_configure/refuse_host_tools, isolate_remote) exist. P3: "21 passed (12+9)" ok (main collects 12).
- T2 settings: read. write_private same as main + fsync. ok.
- T3 secrets/scrub_env: read. anchor `**os.environ,` in _execute ok.
- T4 owner/schema4: read. Anchors ok (RunRequest.diff, _prepare_in, control x2, sweeps _draft line 1436 + create_sweep 1539, _requests, index _run_values/_filter_runs/count_runs). Snapshot block placed after commit (P3 ordering).
- T5 scopes/ownership: read; ok.
- T6 AuthStore: read fully; ok (hash/compare_digest, BEGIN IMMEDIATE redeem, failures kept, host offer admin).
- T7 tickets/pairing/client: read; api/tickets.py adapter matches main TicketStore; P3: commit omits src/hypothex/api/tickets.py + tests/auth/test_tickets.py.
- T8 notebook: read; anchors ok.
- T9 baselines: read; build_leaderboard single return ok; `from pydantic import BaseModel` anchor already has Field (no-op).
- T10-12 export: read; primary flows to get_leaderboard(primary=) and board direction; compare rejects primary; ConfigError/RunError->400 on main.
- T13 fakes, T14 messages (cost_text), T15 channels, T16 notifier scan + pending sweeps, T17 delivery, T18 digest, T19 digest due/send: read.
- T20-22 storage: read. NEW P2 (probe protected_alias_probe.log): protected_reason compares to unresolved home only; SDK records resolved paths -> run-folder records unprotected when home reached via symlink.
- T22 anchors: `_prepare_in` create_run block matches main; RunDetail anchor says children=sorted(children) but main has children=sorted(ctx.index.child_run_ids(run_id)) (P3).
- T23 AuthGuard/TokenGuard adapter: read; anchors (security.py constants, TokenGuard valid branch, tickets = TicketStore(), environment route, BareMcp) match main.
- NEW P2 (probe spa_deeplink_probe.log on main): server public SPA classifier only gains /pair; /settings, /storage, /n/... reload/deep links return 401 JSON in default token mode (and unpaired scoped mode).
- T24 scope list; T25 auth routes; T26 WS recheck/admin events (anchors in events_ws match); T27 identity/ownership/sweeps (sweep_create prepare/_draft matches main; issuer receipts keyed by command_key); T28 matrix: read.
- T29 team routes incl. export primary (ConfigError on unknown key -> 400); T30 notify routes/thread; T31 storage routes: read.
- T32 MCP scoped/caller credential (main _CallerMCPServer/_caller_token/auth() match); T33 nine tools (export_table primary): read. P3: T33 test lacks the selected-primary MCP case that the final acceptance note requires.
- T34 dialects/upsert/journal/pg staged rebuild: read; main helpers present (_open_schema,_move_aside,_touch(*run_ids),_add_run,_Batch,REBUILD_BATCH,STORE_SCAN_KEY, store.iter_records/list_run_ids/find_project_of).
- T35 alembic 0001 matches main models + owner + BigInteger; T36 docker tests: read; docker conftest helpers exist.
- T37 tailscale fake; T38 host tokens/re-pair (hub.py anchors 1398-1403, 1461 match; test_hub route url); T39 serve --auth (main serve/_server_file anchors match; release() once; set_token under owner lock); T40 log_cost; T41 login/pair/whoami (resolve_hub_token matches main + hub-tokens); T42 client mode/hosts pair; T43 export/note/notebook/digest CLI; T44 notify/storage CLI; T45 demo team (demo.py anchors match; P3: "served()" name stale, it is demo_hosts()); T46 docs; T47 leak scan; T48 acceptance; Done map + final acceptance: read.
- NEW P2: contract done criterion 9 (wheel install outside checkout, packaged UI/demo, synthetic pre-Phase-3 home upgrade/restart; "automated and green in CI") has no owning task/test/CI job; backend Done map renumbers (9 = pytest), frontend Done says bun test = 11.9. Only prose "verification only" paragraph.
- Backend coverage: ALL 48 tasks + header/constraints/review focus/file structure/done map/assembly notes read.

## Frontend
- Header, file map, prerequisite/preflight, Tasks 1-26, Done criteria: read fully.
- Preflight run against main: probes/frontend-preflight-r2.txt ("7 current integration anchors ok / 12 snippet anchors ok / reviewed replacement sources ok", exit 0).
- Main UI anchors checked: auth.ts AuthStore (snapshot/select/accept/lock(generation)/onReset), client.ts 401 -> ApiError(401,"Token required"), useAction, format helpers, HostsPanel LOCAL_HOST/useNow, Figure aside, Markdown safeHref, Task.tsx board (baseline or alternate useLeaderboard primary), TrainingDetails imports.
- T2 auth/client/credentials; T3-T6 pair/gate/settings; T7 links/isAppPath (n/, settings, storage, pair); T8-T12 notebook/digest/cost_text; T13-T17 storage dry-run/apply/confirm; T18-T22 export menu (primary from board.data.primary), baselines; T23 PanelGrid/PanelContextProps; T24 cleaned checkpoints (bounded detail queries); T25-T26 Playwright/acceptance: read.
- Frontend Done criteria line 10248 cites "contract 11.9" for bun test; contract 11.9 is now wheel/upgrade (bun test is 11.10). Part of P2-C.

## Mockups (docs/mockups/phase3)
- index.html + data.js read; 14 screens x light/dark PNG listed.
- PNGs viewed: shot-notebook-light, shot-storage-confirm-dark, shot-task-export-light. They match the plan (digest card priced "$86.5", confirm dialog typed bytes + refusals "used by"/"protected", export LaTeX with direction arrows and baselines).
- index.html has the #notebook/cost-unknown state (lines 547-548). NO PNG exists for it and no new visual was captured by me. Unknown-cost visual: NOT checked.
