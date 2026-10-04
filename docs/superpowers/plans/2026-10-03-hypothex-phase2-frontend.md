# Hypothex Phase 2 Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show phase 2 in the web UI: the Overview "Hosts" panel, the Launch dialog (any host, GPUs, queue, SLURM fields, seeds, `{seed}` template, required hypothesis, preview, Copy as CLI), the Sweep page `/s/:project/:id`, and the run-page states of remote runs (queued with position, running on a host, stale since, lost reason) with cost, all kept live by `mirror.run_updated` and `host.*` events.

**Architecture:** The phase 1b API layer stays the only data layer: Tasks 1–4 add the contract shapes to `models.ts`, one `api.*` function per phase 2 route to `client.ts`, keys, hooks and invalidation lists to `queries.ts`, and the mirror and host event mapping to `events.ts`; every later task calls those functions and lists. Each screen keeps its arithmetic in small pure modules with unit tests on concrete numbers (`HostsPanel` helpers, `ui/src/launch/*.ts`, `SweepModel.ts`, `remote.ts`, `remoteStats.ts`) and draws with small prop-driven components that inject their own scoped CSS. Stale is derived from `HostState` / `RunDetail.host_state`, never stored. Playwright runs against a second demo hub seeded by the backend plan's `hx demo --with-hosts` (fake hosts on this machine).

**Tech Stack:** Bun 1.3, Vite 8, React 19, TypeScript 5.9 (strict), TanStack Router and TanStack Query 5, d3-scale (chart math only, through the phase 1b `charts/` primitives), happy-dom + Testing Library (`bun test`), Playwright 1.63, openapi-typescript 7; `uv` for every Python command (`uv run hx ...`, `uv run pytest`, `uv run sphinx-build`).

**Spec:** `docs/superpowers/specs/2026-09-26-hypothex-design.md` sections 5.2–5.7 and 8A (8A.1, 8A.3–8A.9); sections 8 and 8.1 for the UI rules.

**Contract:** `docs/superpowers/plans/2026-10-03-hypothex-phase2-contract.md`. Section 4 is this plan's scope; sections 1.5–1.7 are the shapes, section 2 the routes, section 5 the demo it consumes. Every name, field and route in it is exact.

**Mockups:** `docs/mockups/phase2/` (`index.html`, `shot-overview-*`, `shot-launch-*`, `shot-sweep-*`, `shot-run-{queued,running,stale,lost}-*`).

**Depends on:** phases 1a and 1b on `main`, and the backend plan `docs/superpowers/plans/2026-10-03-hypothex-phase2-backend.md` merged: the section 2 routes in `/api/openapi.json`, `RunDetail.host_state`, `mirror.run_updated` and `host.*` events (a mirrored `run.lost` carries the original `reason` in its payload), `SweepSummary.run_ids` derived from the sweep's member tag `SweepSummary.tag` = `sweep:<owner8>:<id>` (ruling S8; owner namespace: backend review round 3), the demo cleanup in the hub's ASGI lifespan shutdown (ruling S9), `hx demo --with-hosts`, and `docs/remote.rst`.

## Global Constraints

- Tooling: Bun only for JavaScript (`bun test`, `bun run typecheck`, `bun run build`, `bun run dev`, `bunx`); never npm, yarn or pnpm. `uv` only for Python (`uv run hx ...`, `uv run pytest`, `uv run sphinx-build`); never pip.
- Paths: commands run from `ui/` unless the step says "repo root" (`/Users/shreyasv/Desktop/code/research_dash`). Unit and component tests live in `ui/test/`, mirroring `ui/src/`; Playwright specs in `ui/e2e/`.
- Generated file: `ui/src/api/types.ts` comes from `bunx openapi-typescript` against a running hub, is checked in, and is never edited by hand. Response bodies are typed by `ui/src/api/models.ts`, the only hand-written copy of the contract shapes.
- Contract names (exact): `HostKind`, `ConnState` (`connecting | bootstrapping | connected | stale | upgrade | error | disabled`), `HostState`, `HostRow`, `GpuInfo`, `CostTotals`, `SlurmDefaults`, `SweepParam`, `SweepSpec`, `SweepSummary`; executor additions `host`, `gpus`, `slurm_job_id`, `node`, `queue_position`; `RunRecord.cost`, `RunRecord.sweep_id`, `RunRecord.gpus_requested`; `RunDetail.host_state` (`null` = a hub run); event type `mirror.run_updated`, event prefix `host.`. Phase 2 fields are optional in the models, so phase 1 records still type-check.
- Routes (exact): UI route `/s/$project/$id` (contract `/s/:project/:id`). API the UI calls: `GET /api/v1/hosts`, `POST /api/v1/hosts/{host}/connect`, `POST /api/v1/hosts/{host}/runs`, `GET /api/v1/gpus`, `GET /api/v1/queue`, `GET /api/v1/sweeps/{project}/{id}`, `GET /api/v1/projects/{project}/sweeps`, `POST /api/v1/sweeps/{project}/{id}/cancel_queued`, `POST /api/v1/sweeps/{project}/{id}/extend`, `POST /api/v1/runs/{id}/pull`. `POST /api/v1/sweeps` and `POST /api/v1/hosts/{host}/disconnect` exist on the hub (Task 2's `types.ts` test checks them) but no screen uses them, so the client has no function for them. Sweep runs carry the tag `sweep:<owner8>:<id>` (`owner8`: the first 8 characters of the hub's environment id); the UI never builds it and reads `SweepSummary.tag`.
- Which host a run is on: the `GET /api/v1/hosts` row whose `state.environment_id` equals the run's `environment_id` (`hostRowForRun`, Task 5), the same match as the backend's `host_for_environment`. `executor.host` is never used for this: the backend writes the env server's own `socket.gethostname()` there for every run (hub runs too), not the hub's name for the host. A run detail with `host_state: null` is a hub run. When no row matches (the hosts list is not loaded or failed), texts fall back to the machine's hostname (`record.host`) and Reconnect is disabled.
- One data layer: every request goes through `api.*` in `ui/src/api/client.ts`; no module builds its own `fetch` or route table.
- Actions: every POST carries `command_id` and `created_by: "human"` (the `action()` helper inside `api.*`). A retry after a dropped connection reuses the same `command_id`; a launch uses `<attempt>.s<seed>` per seed, and the attempt changes only when the form changes. After a partial launch the dialog remembers the seeds that started and never sends them again, even after an edit (a new attempt id would make the backend start them twice).
- Live data: `useHosts` polls every `HOSTS_REFETCH_MS = 10_000` ms (GPU use changes with no event, spec 8A.7). The hub sends GPUs and queue length only for a `connected` host (`gpus: []`, `queue: 0` otherwise), so `useHosts` keeps a stale host's last connected GPUs and queue on the client (`keepLastKnown`, Task 3) to draw them greyed. `run.*` events invalidate `RUN_EVENT_INVALIDATES`; `mirror.run_updated` invalidates `REMOTE_RUN_INVALIDATES` (the run families plus `["hosts"]`); `host.*` invalidates `HOST_EVENT_INVALIDATES` (`["hosts"]`, `["overview"]`, `["runs"]`, `["run"]`, `["sweeps"]`). Remote writes (launch on a host, sweep actions) use `REMOTE_RUN_INVALIDATES`; connect (Reconnect) uses `HOST_EVENT_INVALIDATES`.
- Stale (contract 1.5, spec 5.6): derived from the hub's host state and never written; a queued or running run on a host that is not `connected` shows `stale` with the time since, never `lost`. Only the env server decides `lost`.
- Copy (spec 8.1, terse UI): numbers and glyphs, short labels; explanations only in `title` tooltips; every state has its own glyph, never colour alone; monospace only for commands and paths; times in UTC; a missing value is `—` (a not-yet-known cell is `·`).
- CSS: each new component injects its own `<style data-hx="…">`; every selector is scoped (`.page …`, `.hx-launch …`); colours only through the theme tokens (`var(--ink)`, `var(--fail)`, …), so light and dark both work. `ui/src/pages/components/styles.ts` is not edited.
- HARD RULE, never touch the user's real hosts: no test or step connects to a real SSH or SLURM host or reads `~/.hypothex`. Unit tests stub `fetch` (`mockApi`, `mockFetch`). Every `hx` a step starts uses a fresh temp home given on its own command line (`uv run hx --home "$H" ...`) and runs with `HYPOTHEX_SSH=false HYPOTHEX_SCP=false` set inline on that same command line, never by an earlier `export`: agent shells do not keep variables from one call to the next, so a separate `export` line can leave `hx serve` on the real `~/.hypothex`, where a phase 2 hub bootstraps the user's real hosts over real ssh. A step block that starts a server is one shell command; run it as one call. Waits are bounded (`for i in $(seq 60)`), never `until` loops. No step runs `ssh`, `scp`, `hx hosts add` or `hx hosts connect`. Playwright never reuses a server it did not start, for either demo hub (`reuseExistingServer: false`), and every test first checks that the hub answers with the identity `serve-demo.ts` wrote into its fresh home (Task 28), so no spec can post to another server. Every port a step or check serves a hub on is asked from the OS for that run, never fixed (controller ruling S1): `freePort()` in `ui/e2e/paths.ts`, or `uv run python -c` binding port 0 in a shell step. Before any host route or mutation, the caller checks that the hub on that port answers `GET /.well-known/hypothex/environment` with the `environment_id` of the fresh home it started, and a child that fails to start (or exits) aborts the step at once instead of waiting it out.
- Build output: `bun run build` writes `src/hypothex/ui_dist/` (git-ignored); never commit it.
- Docs: Task 29 updates `docs/ui.rst` and its test (spec rule: every feature ships with docs).
- Commits: plain conventional commits (`feat(ui): …`, `test(ui): …`, `docs: …`). No `Co-Authored-By` lines and no AI mention in commits or PR text.

## Review Focus

Five failure modes the spec implies that no part's tests covered; each test is in its owning task.

1. **The tunnel to a host dies mid-mirror.** The run detail already says `host_state: "stale"`, but `GET /api/v1/hosts` answers 503 while the hub reconnects. The run page must still say stale, never lost, and must not crash without the hosts list. An open page keeps the last hosts list it loaded (TanStack keeps `data` when a refetch fails), so it still names `dgx` (`dgx unreachable 5m` bar, `Reconnect` posts to `dgx`). A page opened during the outage has no hosts list: it names the machine's hostname (`lr 1e-3 with beam 10: dgx-h100-07 unreachable`) and disables `Reconnect` (it cannot know the hub's name for the host). Tests: `the tunnel dies mid-mirror: the hosts list fails, the page still says stale` and `opened while the hosts list fails: stale, the machine's hostname, Reconnect disabled` in Task 27.
2. **Host clock ahead of the hub.** The host stamps `started_at` / `created_at` later than the hub's now. GPU hours and waiting time must read `0.00` and `0s`, never negative. Test: `host clock ahead of the hub: GPU hours and waiting read 0, never negative` in Task 24.
3. **Two hubs bootstrapping one host.** The second hub finds the install lock taken. The backend's `_open_route` sets `bootstrapping` with an empty `HostState.message` while it waits, and a lock held too long ends in a `BootstrapError`: state `error` with the message (`lock /home/sv/.hypothex/runtime/.lock is held by hub2:4411; waited 300s`). The Launch dialog must disable that host in both states, show the reason (`installing hx on gpu1` while it waits, the error message after), and never pick it. Test: `two hubs bootstrapping one host: the second waits, then shows the lock error, and never launches there` in Task 9.
4. **A run finishes while the hub is offline for hours.** On reconnect the hub replays hundreds of `mirror.run_updated` events at once. The UI must invalidate each query key once (one hosts refetch, one per run), not once per event. Test: `a burst of mirror events after hours offline invalidates each key once` in Task 4.
5. **A sweep is extended while runs are still queued.** After `Add seeds` the page must show the new totals (`5 / 16`), `Cancel queued` must cover the new queued runs (`Cancel the 9 queued runs`), and the next `Add seeds` must propose later seeds (`5, 6`), not resend the used ones. Test: `Add seeds while runs are still queued: new totals, Cancel covers them, later seeds next` in Task 21.

---

## File Structure

```
ui/
  src/
    api/models.ts                 phase 2 shapes: hosts, GPUs, sweeps, cost, queue, launch bodies   (Task 1)
    api/types.ts                  GENERATED OpenAPI paths, regenerated with the phase 2 routes     (Task 2)
    api/client.ts                 ROUTES + api.* for hosts, gpus, queue, launch, sweeps, pull     (Task 2)
    api/queries.ts                keys, useHosts (keepLastKnown)/useSweep/useProjectSweeps, fetchAllRuns/useAllRuns, invalidation lists (Tasks 3, 4)
    api/events.ts                 mirror.run_updated and host.* → query keys                      (Task 4)
    api/lostReasons.ts            run.lost reasons seen on the event stream, by run               (Task 4)
    pages/components/HostsPanel.tsx  host helpers (hostRowForRun, remoteRows, longStale) and the Hosts panel (own CSS) (Tasks 5, 6)
    pages/Overview.tsx            Hosts as panel a; host-aware headline and metaline; stale banner after stale_banner_hours (Task 7)
    launch/seeds.ts command.ts    seed lists; sh-like command split, {seed} slots                  (Task 8)
    launch/plan.ts                launch hosts, availability, GPU plan, SLURM fields               (Task 9)
    launch/cli.ts draft.ts        hx launch lines, sbatch line; form defaults and checks           (Task 10)
    launch/launchApi.ts           launch hosts query, per-seed launches over api.*                 (Task 11)
    launch/styles.ts LaunchDialog.tsx  the dialog                                                  (Task 12)
    pages/Task.tsx                New run button, launched-runs line (13); project sweeps list (21) (Tasks 13, 21)
    pages/components/SweepModel.ts   sweep arithmetic: cells, states, axes, CLI, ETA, cost, sort   (Tasks 14, 15)
    pages/components/SweepGlyphs.tsx SweepStyles.tsx SweepHeat.tsx  glyphs, CSS, heat table       (Task 16)
    pages/components/SweepTable.tsx  sortable params table                                         (Task 17)
    pages/components/SweepForest.tsx seeds forest                                                  (Task 18)
    pages/components/SweepRuns.tsx   runs on hosts                                                 (Task 19)
    pages/components/SweepActions.tsx Copy as CLI, Cancel queued, Add seeds, Rerun sweep button    (Tasks 20, 22)
    pages/components/SweepRerun.tsx  Rerun sweep defaults and dialog                               (Task 22)
    pages/Sweep.tsx router.tsx    the Sweep page and `/s/$project/$id`                             (Tasks 21, 22)
    pages/components/links.tsx    isAppPath accepts /s/                                            (Task 21)
    pages/components/remote.ts    run phase and its texts                                          (Task 23)
    pages/components/remoteStats.ts runStats.ts  stat strip per phase; run cost                    (Task 24)
    panels/Leaderboard.tsx        each group's cost (dollars, GPU hours) in its meta line           (Task 24)
    pages/components/Placement.tsx QueuePanel.tsx StateBanner.tsx StatusLine.tsx remoteStyles.ts  (Task 25)
    pages/components/RunActions.tsx  actions by phase (Cancel, Reconnect, Rerun first when lost)    (Task 26)
    pages/Run.tsx                 the run page wired for remote runs                               (Task 27)
  test/
    api/phase2-fixtures.ts client.test.ts types.test.ts queries.test.tsx events.test.ts lostReasons.test.ts  (Tasks 1–4)
    pages/hostFixtures.ts hostsPanel.test.tsx hostsPanelView.test.tsx Overview.test.tsx            (Tasks 5–7)
    launch/fixtures.ts seeds|command|plan|cli|draft|launchApi .test.ts LaunchDialog.test.tsx       (Tasks 8–12)
    pages/Task.test.tsx                                                                            (Tasks 13, 21)
    pages/sweepFixtures.ts sweep{Model,Stats}.test.ts sweep{Glyphs,Heat,Table,Forest,Runs,Actions,Rerun}.test.tsx Sweep.test.tsx  (Tasks 14–22)
    router.test.tsx pages/links.test.tsx                                                           (Task 21)
    pages/remoteFixtures.ts remote.test.ts remoteStats.test.ts remoteParts.test.tsx remoteActions.test.tsx RunRemote.test.tsx  (Tasks 23–27)
    panels/Leaderboard.test.tsx                                                                    (Task 24)
  e2e/paths.ts serve-demo.ts .gitignore fixtures.ts hosts-fixtures.ts hosts.spec.ts launch.spec.ts shutdown-check.ts  (Task 28)
  playwright.config.ts README.md                                                                   (Task 28)
docs/ui.rst  tests/test_docs_ui.py                                                                 (Task 29)
```

Each file has one job: `api/` talks to the server, `launch/` owns the Launch dialog, `pages/components/` builds page sections (pure `.ts` modules hold the arithmetic, `.tsx` files draw), `pages/` composes one screen, `router.tsx` maps URLs to screens.


---

## Group 1: Models, client, queries, live events (Tasks 1–4)

Gives the UI typed access to every phase 2 hub route and keeps hosts, runs, overview and sweeps live. `models.ts` gets the contract shapes (hand-written like phase 1b: the new routes return plain dicts, so `types.ts` knows only their paths). `client.ts` adds the routes to `ROUTES` (checked against the regenerated OpenAPI `paths`) and one `api.*` function per route, including the hub's own `GET /api/v1/gpus` and `GET /api/v1/queue` for the Launch dialog. `queries.ts` adds keys, read hooks (`useHosts` polls) and three invalidation lists; `events.ts` maps `run.*`, `mirror.run_updated` and `host.*` events to them. Write actions stay on the existing `useAction` hook (`ui/src/pages/components/useAction.ts`); later tasks pass it `api.*` functions and these lists. The backend plan must be merged before Task 2 Step 3 (the phase 2 routes must be in `/api/openapi.json`).

### Task 1: Phase 2 models and typed fixtures

**Files:**
- Modify: `ui/src/api/models.ts` (header comment lines 4-7; `ExecutorInfo` lines 58-63; end of `RunRecord` after `usage` line 103; end of `RunDetail` after `children` line 168; `RunsQuery` lines 204-211; end of `LeaderboardRow` after `usage` line 264; end of `OverviewSummary` after `projects` line 341; append at end of file)
- Create: `ui/test/api/phase2-fixtures.ts`

**Interfaces:**
- Consumes: nothing new.
- Produces (in `ui/src/api/models.ts`, re-exported by `ui/src/api/client.ts` through `export type * from "./models"`):
  - `type HostKind = "ssh" | "slurm"`
  - `type ConnState = "connecting" | "bootstrapping" | "connected" | "stale" | "upgrade" | "error" | "disabled"`
  - `interface CostTotals { gpu_hours: number; gpu_usd: number; api_usd: number; total_usd: number }`
  - `interface SlurmDefaults { partition: string | null; account: string | null; time: string; gpus: number; extra: string[] }`
  - `interface GpuInfo { index: number; name: string; util: number; mem_used_mb: number; mem_total_mb: number; external: boolean; run_id: string | null }`
  - `interface HostState { name; kind: HostKind | "local"; state: ConnState; since: string; message: string; environment_id: string | null; hx_version: string | null; last_sequence: number; local_port: number | null }`
  - `interface HostRow { name: string; kind: HostKind | "local"; state: HostState; gpus: GpuInfo[]; queue: number; slurm: { pending: number; running: number; comment_accounting?: boolean | null } | null; cost_today_usd: number; usd_per_gpu_hour?: number | null; stale_banner_hours?: number; projects: string[] }` (`comment_accounting` false: the cluster cannot settle an unknown SLURM submission; no screen uses it yet; the backend's `host_rows` always lists the hub itself first as `{name: "local", kind: "local"}`; contract `HostKind` stays `"ssh" | "slurm"`; `usd_per_gpu_hour` is the contract's host rate; `stale_banner_hours` is the hub's `environments.yaml` setting, the same on every row, controller ruling R1)
  - `interface RunFields { task?; stage?; command?: string[] | null; hypothesis?; seed?; tags?; params?; vars?; gpus?: number; queue?: boolean; slurm?: Partial<SlurmDefaults> | null; commit?: string | null; diff?: string | null }` (the backend's `RunFields`, without the action fields)
  - `interface LaunchRequest extends RunFields { repo: string }` (`POST /api/v1/runs`: the hub's own checkout)
  - `interface HostLaunchRequest extends RunFields { project: string }` (`POST /api/v1/hosts/{host}/runs`: the project by name, never a path on this machine; the hub finds its own checkout and the host's mapped one)
  - Additive contract fields: `LeaderboardRow.cost?: CostTotals | null`, `OverviewSummary.cost_usd?: number`, `OverviewSummary.cost_today_usd?: number`, `RunsQuery.environment_id?: string` (the queue panel's filter, Task 27).
  - `interface SweepParam { name: string; values: string[] | null; low: number | null; high: number | null; log: boolean }`
  - `interface SweepSpec { id; project; task: string | null; host: string | null; grid: SweepParam[]; random: number | null; seeds: number[]; command_template: string[]; created_by: string; created_at: string; commit?: string | null; diff?: string | null }` (the definition only: no `run_ids`, controller ruling S8; `commit` / `diff` are the code the sweep was launched with, which every extend runs again, `null` when nothing was pinned; `diff` can be up to 5 MB and comes in every `SweepSummary`, never in the `list_sweeps` rows)
  - `interface SweepCell { params: Record<string, string>; group_id: string; n: number; mean: number | null; lo: number | null; hi: number | null; run_ids: string[] }`
  - `interface SweepSummary { spec: SweepSpec; run_ids: string[]; tag: string; counts: Record<string, number>; cells: SweepCell[]; best: SweepCell | null; headline: string; total_usd: number }` (`run_ids`: the sweep's membership, derived by the backend from the runs tagged `tag`, oldest first; ruling S8; `tag` is `sweep:<owner8>:<id>`, the filter for `GET /api/v1/runs?tag=`)
  - `interface SweepListItem { id: string; created_at: string; n_runs: number; best: SweepCell | null }`
  - `interface PullResult { local_path: string }`
  - `interface QueueEntry { run_id: string; position: number; gpus_requested: number }` (`GET /api/v1/queue`)
  - Optional additions (absent from phase 1 servers, so old fixtures and old records still type-check): `ExecutorInfo.host?/gpus?/slurm_job_id?/node?/queue_position?`, `RunRecord.cost?/sweep_id?/gpus_requested?`, `RunDetail.host_state?: ConnState | null`.
  - Test fixtures in `ui/test/api/phase2-fixtures.ts`: `GPU1_STATE`, `DGX_STATE`, `LOCAL_ROW`, `HOSTS` (as the hub sends them: `local` first; a stale host has `gpus: []` and `queue: 0`; every row carries `stale_banner_hours: 24`), `REMOTE_EXECUTOR`, `PHASE1_EXECUTOR`, `COST`, `BEST_CELL`, `SWEEP`, `SWEEP_LIST`, `HOST_LAUNCH`, `OVERVIEW_COST`, `BOARD_ROW_COST`.

The test for this task is the type checker: the fixtures are typed against the models, so `bun run typecheck` fails while a model is missing or misshaped.

- [ ] **Step 1: Write the typed fixtures (the failing test)**

Create `ui/test/api/phase2-fixtures.ts`:

```ts
/**
 * Phase 2 API bodies for the api tests (phase 2 contract sections 1.5-1.7 and 2).
 *
 * Typed against `src/api/models.ts`, so `bun run typecheck` fails when a model drifts
 * from the contract. Numbers are invented but consistent: gpu1 has 3 GPUs (one held by
 * run r-6b0e, one by a process outside hx, one free); the sweep is 2 lr values x 1 beam x
 * 3 seeds = 6 runs. `HOSTS` is shaped like the backend's `host_rows`: the hub's own
 * `local` row first, and no GPUs or queue for a host that is not connected (dgx is stale).
 * Every row carries the hub's `stale_banner_hours` (default 24, controller ruling R1).
 */
import type {
  CostTotals,
  ExecutorInfo,
  HostLaunchRequest,
  HostRow,
  HostState,
  LeaderboardRow,
  OverviewSummary,
  SweepCell,
  SweepListItem,
  SweepSummary,
} from "../../src/api/models";

export const GPU1_STATE: HostState = {
  name: "gpu1",
  kind: "ssh",
  state: "connected",
  since: "2026-10-03T14:00:00Z",
  message: "",
  environment_id: "env-gpu1",
  hx_version: "0.5.0",
  last_sequence: 412,
  local_port: 51234,
};

export const DGX_STATE: HostState = {
  name: "dgx",
  kind: "ssh",
  state: "stale",
  since: "2026-10-03T14:28:02Z",
  message: "no ping for 60 s",
  environment_id: "env-dgx",
  hx_version: "0.5.0",
  last_sequence: 97,
  local_port: 51240,
};

const A100 = "NVIDIA A100 80GB PCIe";

/** The hub's own row: `host_rows` always lists it first, `kind: "local"`, always connected. */
export const LOCAL_ROW: HostRow = {
  name: "local",
  kind: "local",
  state: {
    name: "local",
    kind: "local",
    state: "connected",
    since: "2026-10-03T08:00:00Z",
    message: "",
    environment_id: "env-hub",
    hx_version: "0.5.0",
    last_sequence: 1022,
    local_port: null,
  },
  gpus: [],
  queue: 0,
  slurm: null,
  cost_today_usd: 0,
  usd_per_gpu_hour: null,
  stale_banner_hours: 24,
  projects: ["toy"],
};

export const HOSTS: HostRow[] = [
  LOCAL_ROW,
  {
    name: "gpu1",
    kind: "ssh",
    state: GPU1_STATE,
    gpus: [
      { index: 0, name: A100, util: 92, mem_used_mb: 58_112, mem_total_mb: 81_920, external: false, run_id: "r-6b0e" },
      { index: 1, name: A100, util: 63, mem_used_mb: 33_587, mem_total_mb: 81_920, external: true, run_id: null },
      { index: 2, name: A100, util: 0, mem_used_mb: 4, mem_total_mb: 81_920, external: false, run_id: null },
    ],
    queue: 3,
    slurm: null,
    cost_today_usd: 106.04,
    usd_per_gpu_hour: 1.1,
    stale_banner_hours: 24,
    projects: ["toy"],
  },
  {
    name: "mccleary",
    kind: "slurm",
    state: {
      ...GPU1_STATE,
      name: "mccleary",
      kind: "slurm",
      environment_id: "env-mccleary",
      last_sequence: 230,
      local_port: 51236,
    },
    gpus: [],
    queue: 0,
    slurm: { pending: 6, running: 4 },
    cost_today_usd: 19,
    usd_per_gpu_hour: 0.5,
    stale_banner_hours: 24,
    projects: ["toy"],
  },
  {
    // stale: the hub asks a host for GPUs and queue only while it is connected
    name: "dgx",
    kind: "ssh",
    state: DGX_STATE,
    gpus: [],
    queue: 0,
    slurm: null,
    cost_today_usd: 206.48,
    usd_per_gpu_hour: 2.9,
    stale_banner_hours: 24,
    projects: [],
  },
];

/**
 * A launch on a host: the project by name and the pinned commit, never a path on this
 * machine (the hub finds its own checkout and the host's mapped one).
 */
export const HOST_LAUNCH: HostLaunchRequest = {
  project: "toy",
  task: "acc",
  command: ["python", "train.py", "--seed", "{seed}"],
  hypothesis: "seed noise of the baseline",
  seed: 4,
  gpus: 1,
  queue: true,
  commit: "8f4cac43877b75953f18ff1daf7e6fc54a5d8f37",
};

/** The Overview's cost fields (contract section 2, spec 8A.7). */
export const OVERVIEW_COST: Pick<OverviewSummary, "cost_usd" | "cost_today_usd"> = {
  cost_usd: 512.3,
  cost_today_usd: 402.75,
};

/** A leaderboard row's cost: the sum over the group's runs. */
export const BOARD_ROW_COST: Pick<LeaderboardRow, "cost"> = {
  cost: { gpu_hours: 10.5, gpu_usd: 5.25, api_usd: 1.26, total_usd: 6.51 },
};

/**
 * A SLURM run's executor with every phase 2 field set. `host` is the env server's own
 * hostname (`socket.gethostname()` on the login node), not the hub's name for the host.
 */
export const REMOTE_EXECUTOR: ExecutorInfo = {
  type: "slurm",
  pid: null,
  pid_create_time: null,
  child_pid: null,
  host: "mccleary-login1",
  gpus: [0, 1],
  slurm_job_id: "4471023",
  node: "r814u05n01",
  queue_position: null,
};

/** A phase 1 record's executor: the phase 2 fields are absent, and that still type-checks. */
export const PHASE1_EXECUTOR: ExecutorInfo = {
  type: "local",
  pid: 4242,
  pid_create_time: 1_759_500_000.5,
  child_pid: 4243,
};

export const COST: CostTotals = { gpu_hours: 3.5, gpu_usd: 1.75, api_usd: 0.42, total_usd: 2.17 };

export const BEST_CELL: SweepCell = {
  params: { lr: "3e-4", beam: "10" },
  group_id: "g-7e3f",
  n: 3,
  mean: 0.9121,
  lo: 0.9109,
  hi: 0.9133,
  run_ids: ["r-7e3f", "r-f0a1", "r-66cd"],
};

export const SWEEP: SweepSummary = {
  spec: {
    id: "s-7f3a",
    project: "toy",
    task: "acc",
    host: "gpu1",
    grid: [
      { name: "lr", values: ["1e-4", "3e-4"], low: null, high: null, log: false },
      { name: "beam", values: ["10"], low: null, high: null, log: false },
    ],
    random: null,
    seeds: [1, 2, 3],
    command_template: ["python", "train.py", "--lr", "{lr}", "--beam", "{beam}", "--seed", "{seed}"],
    created_by: "agent:tuner",
    created_at: "2026-10-03T09:12:00Z",
  },
  run_ids: ["r-7e3f", "r-f0a1", "r-66cd", "r-71f2", "r-1d77", "r-c2b9"],
  tag: "sweep:0a1b2c3d:s-7f3a",
  counts: { finished: 4, running: 1, queued: 1 },
  cells: [
    BEST_CELL,
    {
      params: { lr: "1e-4", beam: "10" },
      group_id: "g-71f2",
      n: 1,
      mean: 0.8979,
      lo: null,
      hi: null,
      run_ids: ["r-71f2", "r-1d77", "r-c2b9"],
    },
  ],
  best: BEST_CELL,
  headline: "lr 3e-4, beam 10: 0.912 [0.911, 0.913], n = 3",
  total_usd: 312.4,
};

export const SWEEP_LIST: SweepListItem[] = [
  { id: "s-7f3a", created_at: "2026-10-03T09:12:00Z", n_runs: 6, best: BEST_CELL },
];
```

- [ ] **Step 2: Run the type checker to verify it fails**

Run: `bun run typecheck`
Expected: FAIL, starting with
```
test/api/phase2-fixtures.ts(12,3): error TS2305: Module '"../../src/api/models"' has no exported member 'CostTotals'.
test/api/phase2-fixtures.ts(14,3): error TS2305: Module '"../../src/api/models"' has no exported member 'HostLaunchRequest'.
```

- [ ] **Step 3: Add the models**

In `ui/src/api/models.ts`, replace the header lines

```ts
 * Hand-written from the phase 1b interface contract
 * (docs/superpowers/plans/2026-09-27-hypothex-phase1b-contract.md, sections 1-2) and the
 * phase 1a pydantic models. Most routes return `dict[str, Any]`, so the generated
 * `types.ts` knows their paths but not their bodies; these types fill that gap.
```

with

```ts
 * Hand-written from the phase 1b interface contract
 * (docs/superpowers/plans/2026-09-27-hypothex-phase1b-contract.md, sections 1-2), the
 * phase 2 contract (docs/superpowers/plans/2026-10-03-hypothex-phase2-contract.md, sections
 * 1.5-1.7 and 2) and the phase 1a pydantic models. Most routes return `dict[str, Any]`, so
 * the generated `types.ts` knows their paths but not their bodies; these types fill that gap.
```

Replace `ExecutorInfo`

```ts
export interface ExecutorInfo {
  type: string;
  pid: number | null;
  pid_create_time: number | null;
  child_pid: number | null;
}
```

with

```ts
export interface ExecutorInfo {
  type: string;
  pid: number | null;
  pid_create_time: number | null;
  child_pid: number | null;
  /**
   * Phase 2 fields; a phase 1 server omits them. The env server's own hostname
   * (`socket.gethostname()`), set on every run; NOT the hub's name for the host (match runs
   * to hosts by `environment_id`, `hostRowForRun`).
   */
  host?: string | null;
  /** GPU indices the run holds (`CUDA_VISIBLE_DEVICES`). */
  gpus?: number[];
  slurm_job_id?: string | null;
  /** SLURM compute node. */
  node?: string | null;
  /** 1-based position in the host queue while `queued`. */
  queue_position?: number | null;
}
```

In `RunRecord`, replace

```ts
  created_by: string;
  usage: UsageTotals | null;
}

export interface ScoreRecord {
```

with

```ts
  created_by: string;
  usage: UsageTotals | null;
  /** Phase 2 fields; a phase 1 server omits them. Filled when the run ends. */
  cost?: CostTotals | null;
  sweep_id?: string | null;
  gpus_requested?: number;
}

export interface ScoreRecord {
```

In `RunDetail`, replace

```ts
  metric_names: string[];
  children: string[];
}
```

with

```ts
  metric_names: string[];
  children: string[];
  /** Connection state of the owning host; null for a hub run (phase 2; absent before). */
  host_state?: ConnState | null;
}
```

In `RunsQuery`, replace

```ts
  archived?: boolean;
  limit?: number;
}
```

with

```ts
  archived?: boolean;
  limit?: number;
  /** Phase 2: runs of one environment (one host), e.g. a host's queue (Task 27). */
  environment_id?: string;
}
```

In `LeaderboardRow`, replace

```ts
  created_by: string[];
  usage: UsageTotals | null;
}

export interface Leaderboard {
```

with

```ts
  created_by: string[];
  usage: UsageTotals | null;
  /** Phase 2 (spec 8A.7): cost summed over the group's runs; a phase 1 server omits it. */
  cost?: CostTotals | null;
}

export interface Leaderboard {
```

In `OverviewSummary`, replace

```ts
  failures: FailureRow[];
  projects: ProjectRow[];
}
```

with

```ts
  failures: FailureRow[];
  projects: ProjectRow[];
  /** Phase 2 (spec 8A.7): cost of the runs in the window, and of the runs today. */
  cost_usd?: number;
  cost_today_usd?: number;
}
```

Append at the end of the file (after `EvalReport`):

```ts

// phase 2: hosts, launch, sweeps, cost (phase 2 contract 1.5-1.7, 2) ---------------------
/** How a host runs jobs: a plain SSH box or a SLURM login node. */
export type HostKind = "ssh" | "slurm";

/** The hub's connection state for one host (`hypothex.remote.hub.ConnState`). */
export type ConnState =
  | "connecting"
  | "bootstrapping"
  | "connected"
  | "stale"
  | "upgrade"
  | "error"
  | "disabled";

/** `RunRecord.cost`: `gpu_hours = wall x len(executor.gpus)`, `total_usd = gpu_usd + api_usd`. */
export interface CostTotals {
  gpu_hours: number;
  gpu_usd: number;
  api_usd: number;
  total_usd: number;
}

/** Default `sbatch` resources of a SLURM host. */
export interface SlurmDefaults {
  partition: string | null;
  account: string | null;
  /** `HH:MM:SS`. */
  time: string;
  gpus: number;
  extra: string[];
}

/** One GPU on a host (`hypothex.core.gpus.GpuInfo`, from `nvidia-smi`). */
export interface GpuInfo {
  index: number;
  name: string;
  /** Utilization in percent, 0-100, as `nvidia-smi` reports it. */
  util: number;
  mem_used_mb: number;
  mem_total_mb: number;
  /** A process outside hx holds this GPU. */
  external: boolean;
  /** The hx run holding this GPU, if any. */
  run_id: string | null;
}

/** `hypothex.remote.hub.HostState`: one host's connection, as the hub sees it. */
export interface HostState {
  name: string;
  /** `"local"` only on the hub's own row of `GET /api/v1/hosts`. */
  kind: HostKind | "local";
  state: ConnState;
  /** When `state` last changed (ISO 8601). */
  since: string;
  message: string;
  environment_id: string | null;
  hx_version: string | null;
  last_sequence: number;
  local_port: number | null;
}

/**
 * One row of `GET /api/v1/hosts`. The hub's own row comes first (`name: "local"`,
 * `kind: "local"`). GPUs and queue are filled only while the host is `connected`.
 */
export interface HostRow {
  name: string;
  kind: HostKind | "local";
  state: HostState;
  gpus: GpuInfo[];
  /** Runs waiting in the host queue (SSH hosts); 0 while the host is not connected. */
  queue: number;
  /**
   * SLURM job counts; null on SSH hosts. `comment_accounting` false: the cluster's accounting
   * keeps no job comments, so an unknown submission stays unknown; null: not known yet.
   */
  slurm: { pending: number; running: number; comment_accounting?: boolean | null } | null;
  cost_today_usd: number;
  /** `$/GPU-h` from `environments.yaml`; null when no rate is set (contract section 2). */
  usd_per_gpu_hour?: number | null;
  /**
   * Hours a host may stay unreachable before the Overview banner (spec 5.6). The hub's
   * `environments.yaml` setting (default 24), the same on every row (controller ruling R1).
   */
  stale_banner_hours?: number;
  /** Projects mapped to a repo path on this host. */
  projects: string[];
}

/** Run fields both launch routes take (the backend's `RunFields`, without the action fields). */
export interface RunFields {
  task?: string | null;
  stage?: string | null;
  command?: string[] | null;
  hypothesis?: string;
  seed?: number | null;
  tags?: string[];
  params?: Record<string, string>;
  vars?: Record<string, string>;
  gpus?: number;
  queue?: boolean;
  /** SLURM hosts: overrides of the host's `SlurmDefaults`. */
  slurm?: Partial<SlurmDefaults> | null;
  /** Pinned commit (spec 8A.4); absent: the hub pins its own checkout's HEAD and diff. */
  commit?: string | null;
  /** Uncommitted diff applied on `commit` in a worktree; only sent together with `commit`. */
  diff?: string | null;
}

/** Body of `POST /api/v1/runs`: a run on the hub itself, from the hub's own checkout. */
export interface LaunchRequest extends RunFields {
  repo: string;
}

/**
 * Body of `POST /api/v1/hosts/{host}/runs`. The project goes by name, never as a path on
 * this machine: a project copied from a host has no checkout on the hub, and the hub finds
 * the host's mapped checkout itself.
 */
export interface HostLaunchRequest extends RunFields {
  project: string;
}

/** One swept parameter: a list of values, or a `low`..`high` range for random samples. */
export interface SweepParam {
  name: string;
  values: string[] | null;
  low: number | null;
  high: number | null;
  log: boolean;
}

/**
 * `<store>/<project>/sweeps/<id>.yaml`: the sweep's definition only. Which runs belong to
 * the sweep is derived by the backend from the runs tagged `SweepSummary.tag`
 * (`SweepSummary.run_ids`), never stored here.
 */
export interface SweepSpec {
  id: string;
  project: string;
  task: string | null;
  host: string | null;
  grid: SweepParam[];
  random: number | null;
  seeds: number[];
  command_template: string[];
  created_by: string;
  created_at: string;
  /** The commit the sweep was launched with; every extend runs it again. */
  commit?: string | null;
  /** The uncommitted diff on top of `commit` (up to 5 MB); null when none. */
  diff?: string | null;
}

/** One parameter combination of a sweep: primary-metric mean and 95% CI over its seeds. */
export interface SweepCell {
  params: Record<string, string>;
  group_id: string;
  /** Scored runs in the cell. */
  n: number;
  /** null while no run of the cell is scored. */
  mean: number | null;
  lo: number | null;
  hi: number | null;
  run_ids: string[];
}

/** `GET /api/v1/sweeps/{project}/{id}` and every sweep action. */
export interface SweepSummary {
  spec: SweepSpec;
  /**
   * The sweep's runs, derived by the backend from the runs tagged `tag`, oldest
   * first (launch order). A run launched by a retry or an extend shows up here as soon as
   * the hub has it, whether or not the request that started it got its answer.
   */
  run_ids: string[];
  /**
   * The sweep's member tag, `sweep:<owner8>:<id>` (`owner8`: the hub's environment id, so
   * two hubs' sweeps with one id never mix). The UI filters runs by it and never builds it.
   */
  tag: string;
  /** Runs per status, e.g. `{finished: 4, running: 1, queued: 1}`. */
  counts: Record<string, number>;
  cells: SweepCell[];
  best: SweepCell | null;
  headline: string;
  total_usd: number;
}

/** One row of `GET /api/v1/projects/{project}/sweeps`. */
export interface SweepListItem {
  id: string;
  created_at: string;
  n_runs: number;
  best: SweepCell | null;
}

/** `POST /api/v1/runs/{id}/pull`: where the artifact landed on the hub. */
export interface PullResult {
  local_path: string;
}

/** One row of `GET /api/v1/queue` (an env route; the hub serves its own queue). */
export interface QueueEntry {
  run_id: string;
  /** 1-based. */
  position: number;
  gpus_requested: number;
}
```

- [ ] **Step 4: Run the type checker and the api tests to verify they pass**

Run: `bun run typecheck && bun test test/api`
Expected: `tsc --noEmit` prints no errors; `bun test` ends with `0 fail` (the phase 1 api tests are unchanged; the fixtures file has no tests of its own).

- [ ] **Step 5: Commit**

```bash
git add ui/src/api/models.ts ui/test/api/phase2-fixtures.ts
git commit -m "feat(ui): phase 2 api models for hosts, sweeps and cost"
```

---

### Task 2: Client routes for hosts, launch, sweeps and pull

**Files:**
- Modify: `ui/src/api/types.ts` (regenerated)
- Modify: `ui/src/api/client.ts` (`ROUTES` lines 14-44; end of the `api` object)
- Test: `ui/test/api/client.test.ts`, `ui/test/api/types.test.ts`

**Interfaces:**
- Consumes: the Task 1 models; `action()`, `get`, `post` and `ApiError` already in `client.ts`; fixtures `GPU1_STATE`, `HOSTS`, `SWEEP`, `SWEEP_LIST`.
- Produces (in `ui/src/api/client.ts`):
  - `ROUTES.hosts | hostConnect | hostRuns | sweep | sweepCancelQueued | sweepExtend | projectSweeps | runPull | gpus | queue`. (No client function for `POST /api/v1/sweeps` or `POST /api/v1/hosts/{host}/disconnect`: no screen uses them. The `types.ts` test still checks both exist.)
  - `api.hosts(signal?) => Promise<HostRow[]>`
  - `api.gpus(signal?) => Promise<GpuInfo[]>`, `api.queue(signal?) => Promise<QueueEntry[]>` (the hub's own GPUs and queue; env routes)
  - `api.connectHost(host: string, opts?: ActionOptions) => Promise<HostState>`
  - `api.launch(body: LaunchRequest, opts?: ActionOptions) => Promise<RunRecord>` (hub run, `POST /api/v1/runs`)
  - `api.launchOnHost(host: string, body: HostLaunchRequest, opts?: ActionOptions) => Promise<RunRecord>`
  - `api.sweep(project: string, sweepId: string, signal?) => Promise<SweepSummary>`
  - `api.projectSweeps(project: string, signal?) => Promise<SweepListItem[]>`
  - `api.cancelQueued(project: string, sweepId: string, opts?: ActionOptions) => Promise<SweepSummary>`
  - `api.extendSweep(project: string, sweepId: string, seeds: readonly number[], opts?: ActionOptions) => Promise<SweepSummary>`
  - `api.pull(runId: string, artifact: string, opts?: ActionOptions) => Promise<PullResult>`
  - Every write sends `{command_id, created_by}` plus its own fields; `opts.command_id` is reused when given (so `useAction` retries are idempotent).

- [ ] **Step 1: Write the failing tests**

In `ui/test/api/types.test.ts`, replace

```ts
  "/api/v1/tasks/{project}/{task}/kind",
];
```

with

```ts
  "/api/v1/tasks/{project}/{task}/kind",
];

/** Hub routes added in phase 2 (phase 2 contract section 2) that the UI calls. */
const PHASE_2_ROUTES = [
  "/api/v1/hosts",
  "/api/v1/hosts/{host}/connect",
  "/api/v1/hosts/{host}/disconnect",
  "/api/v1/hosts/{host}/runs",
  "/api/v1/sweeps",
  "/api/v1/sweeps/{project}/{sweep_id}",
  "/api/v1/sweeps/{project}/{sweep_id}/cancel_queued",
  "/api/v1/sweeps/{project}/{sweep_id}/extend",
  "/api/v1/projects/{project}/sweeps",
  "/api/v1/runs/{run_id}/pull",
  "/api/v1/gpus",
  "/api/v1/queue",
];
```

and replace `[...PHASE_1B_ROUTES, ...Object.values(ROUTES)]` with `[...PHASE_1B_ROUTES, ...PHASE_2_ROUTES, ...Object.values(ROUTES)]`.

In `ui/test/api/client.test.ts`, replace

```ts
import { mockFetch } from "./fetch-mock";
```

with

```ts
import { mockFetch } from "./fetch-mock";
import { GPU1_STATE, HOSTS, SWEEP, SWEEP_LIST } from "./phase2-fixtures";
```

and insert this block directly above the last test (`test("wsUrl points at the event stream on the page origin", ...)`):

```ts
describe("phase 2 api", () => {
  test("hosts GETs the hub's own row and every host with its state, GPUs and queue", async () => {
    const calls = mockFetch(HOSTS);
    const rows = await api.hosts();
    expect(rows.map((r) => [r.name, r.kind, r.state.state, r.gpus.length, r.queue, r.slurm?.pending ?? null])).toEqual([
      ["local", "local", "connected", 0, 0, null],
      ["gpu1", "ssh", "connected", 3, 3, null],
      ["mccleary", "slurm", "connected", 0, 0, 6],
      ["dgx", "ssh", "stale", 0, 0, null],
    ]);
    expect(calls).toEqual([{ url: "/api/v1/hosts", method: "GET", body: undefined }]);
  });

  test("connectHost POSTs the given command id", async () => {
    const calls = mockFetch(GPU1_STATE);
    const state = await api.connectHost("gpu1", { command_id: "c-1" });
    expect([state.state, state.local_port]).toEqual(["connected", 51234]);
    expect(calls).toEqual([
      { url: "/api/v1/hosts/gpu1/connect", method: "POST", body: { command_id: "c-1", created_by: "human" } },
    ]);
  });

  test("launch POSTs a hub run to /api/v1/runs", async () => {
    const calls = mockFetch({ run_id: "r-1", status: "running" });
    const run = await api.launch(
      { repo: "/Users/sv/code/toy", task: "acc", stage: "train", hypothesis: "baseline", seed: 1 },
      { command_id: "l-0" },
    );
    expect(run.run_id).toBe("r-1");
    expect(calls[0]).toEqual({
      url: "/api/v1/runs",
      method: "POST",
      body: {
        command_id: "l-0",
        created_by: "human",
        repo: "/Users/sv/code/toy",
        task: "acc",
        stage: "train",
        hypothesis: "baseline",
        seed: 1,
      },
    });
  });

  test("launchOnHost sends the project by name with gpus, queue, slurm, commit and diff", async () => {
    const calls = mockFetch({ run_id: "r-9", status: "queued", executor: { type: "slurm", queue_position: 2 } });
    const run = await api.launchOnHost(
      "mccleary",
      {
        project: "toy",
        task: "acc",
        command: ["python", "train.py", "--lr", "3e-4"],
        hypothesis: "lr 3e-4 converges faster",
        gpus: 2,
        queue: true,
        slurm: { partition: "gpu", time: "04:00:00" },
        commit: "8f4cac43877b75953f18ff1daf7e6fc54a5d8f37",
        diff: "diff --git a/train.py b/train.py\n",
      },
      { command_id: "l-1" },
    );
    expect([run.status, run.executor.queue_position]).toEqual(["queued", 2]);
    expect(calls[0]).toEqual({
      url: "/api/v1/hosts/mccleary/runs",
      method: "POST",
      body: {
        command_id: "l-1",
        created_by: "human",
        project: "toy",
        task: "acc",
        command: ["python", "train.py", "--lr", "3e-4"],
        hypothesis: "lr 3e-4 converges faster",
        gpus: 2,
        queue: true,
        slurm: { partition: "gpu", time: "04:00:00" },
        commit: "8f4cac43877b75953f18ff1daf7e6fc54a5d8f37",
        diff: "diff --git a/train.py b/train.py\n",
      },
    });
    // a host launch never carries a path on this machine
    expect("repo" in (calls[0]?.body as Record<string, unknown>)).toBe(false);
  });

  test("a host that is down surfaces the hub's error type and message", async () => {
    mockFetch({ error: "host dgx is stale", type: "HostUnavailableError" }, 503);
    const err = (await api.launchOnHost("dgx", { project: "toy" }).catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect([err.status, err.type, err.message]).toEqual([503, "HostUnavailableError", "host dgx is stale"]);
  });

  test("sweep and projectSweeps encode the project and sweep id", async () => {
    const first = mockFetch(SWEEP);
    const one = await api.sweep("my proj", "s-7f3a");
    const second = mockFetch(SWEEP_LIST);
    const list = await api.projectSweeps("my proj");
    expect(one.best?.params).toEqual({ lr: "3e-4", beam: "10" });
    expect(list.map((s) => [s.id, s.n_runs, s.best?.mean])).toEqual([["s-7f3a", 6, 0.9121]]);
    expect([...first, ...second].map((c) => c.url)).toEqual([
      "/api/v1/sweeps/my%20proj/s-7f3a",
      "/api/v1/projects/my%20proj/sweeps",
    ]);
  });

  test("cancelQueued and extendSweep POST to the sweep's action routes", async () => {
    const calls = mockFetch(SWEEP);
    await api.cancelQueued("toy", "s-7f3a", { command_id: "k-1" });
    await api.extendSweep("toy", "s-7f3a", [4, 5], { command_id: "e-1" });
    expect(calls).toEqual([
      {
        url: "/api/v1/sweeps/toy/s-7f3a/cancel_queued",
        method: "POST",
        body: { command_id: "k-1", created_by: "human" },
      },
      {
        url: "/api/v1/sweeps/toy/s-7f3a/extend",
        method: "POST",
        body: { command_id: "e-1", created_by: "human", seeds: [4, 5] },
      },
    ]);
  });

  test("gpus and queue GET the hub's own GPUs and queue", async () => {
    // gpu1's three GPUs as the body (HOSTS[0] is the hub's own row, which has none)
    const first = mockFetch(HOSTS[1]?.gpus ?? []);
    const gpus = await api.gpus();
    const second = mockFetch([{ run_id: "r-1", position: 1, gpus_requested: 2 }]);
    const queue = await api.queue();
    expect([gpus.length, queue[0]?.position]).toEqual([3, 1]);
    expect([...first, ...second].map((c) => [c.url, c.method])).toEqual([
      ["/api/v1/gpus", "GET"],
      ["/api/v1/queue", "GET"],
    ]);
  });

  test("pull POSTs the artifact and returns the hub path", async () => {
    const calls = mockFetch({ local_path: "/Users/sv/.hypothex/store/toy/runs/r-9/pulled/model.pt" });
    const out = await api.pull("r-9", "checkpoint", { command_id: "p-1" });
    expect(out.local_path).toBe("/Users/sv/.hypothex/store/toy/runs/r-9/pulled/model.pt");
    expect(calls[0]).toEqual({
      url: "/api/v1/runs/r-9/pull",
      method: "POST",
      body: { command_id: "p-1", created_by: "human", artifact: "checkpoint" },
    });
  });
});

```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bun test test/api/client.test.ts test/api/types.test.ts`
Expected: FAIL. The `phase 2 api` tests fail with `TypeError: api.hosts is not a function` (and the same for `connectHost`, `launch`, ...); `types.ts is generated ...` fails with `expect(received).toContain(expected)` for `"/api/v1/hosts": {`.

- [ ] **Step 3: Regenerate `types.ts` from a hub with no hosts**

From the repo root (`/Users/shreyasv/Desktop/code/research_dash`). The hub gets a port the OS reports free (never a fixed one: a fixed port can belong to an `hx serve` the user left running, and the step would then read, and finally `pkill`, the user's server) and a fresh temp home whose identity the step writes first; it reads `openapi.json` only after the hub on that port answers `/.well-known/hypothex/environment` with that identity. The empty temp home has no `environments.yaml`, so the hub connects to no host, and `HYPOTHEX_SSH=false` makes any SSH attempt fail at once.

Run the whole block as ONE shell command (one Bash call). The temp home is passed with `--home` and the SSH variables are set inline on the `hx serve` line itself, never with a separate `export`: a shell that does not keep variables between calls would otherwise start `hx serve` on the real `~/.hypothex`, and a phase 2 hub there bootstraps the user's real hosts over real ssh. The wait is bounded (30 s), it stops at once when `hx serve` exits, and the block stops its own server (by its unique home) on every path:

```bash
H="$(mktemp -d)"
ID="$(uuidgen | tr -d '-' | tr 'A-Z' 'a-z')"
P="$(uv run python -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')"
if [ -d "$H" ] && [ -n "$ID" ] && [ -n "$P" ]; then
  printf '{"environment_id": "%s", "label": "hx-types"}\n' "$ID" > "$H/environment.json"
  HYPOTHEX_SSH=false HYPOTHEX_SCP=false uv run hx --home "$H" serve --port "$P" > /tmp/hx-serve-types.log 2>&1 &
  SERVER=$!
  ok=""
  for i in $(seq 60); do
    kill -0 "$SERVER" 2>/dev/null || { echo "hx serve exited at start"; break; }
    if curl -sf "http://127.0.0.1:$P/.well-known/hypothex/environment" | grep -Fq "\"$ID\""; then ok=1; break; fi
    sleep 0.5
  done
  if [ -n "$ok" ]; then
    (cd ui && bunx openapi-typescript "http://127.0.0.1:$P/api/openapi.json" -o src/api/types.ts)
  else
    echo "no hx serve with the identity of $H on port $P"; tail -20 /tmp/hx-serve-types.log
  fi
  kill "$SERVER" 2>/dev/null
  pkill -f -- "--home $H serve"
else
  echo "no temp home, id or free port"
fi
head -4 ui/src/api/types.ts
grep -oE '"/api/v1/(hosts|sweeps|gpus|queue|projects/\{project\}/sweeps|runs/\{run_id\}/pull)[^"]*"' ui/src/api/types.ts | LC_ALL=C sort -u
```

(`pkill -f -- "--home $H serve"` matches only the `uv run` wrapper and the `hx` process of this block's own temp home: their command lines are `uv run hx --home <H> serve --port <P>` and `…/hx --home <H> serve --port <P>`. The shell running the block holds the text `$H` unexpanded, so it never matches itself.)

Expected: the header contains `This file was auto-generated by openapi-typescript.`, and the `grep` prints exactly

```
"/api/v1/gpus"
"/api/v1/hosts"
"/api/v1/hosts/{host}/connect"
"/api/v1/hosts/{host}/disconnect"
"/api/v1/hosts/{host}/runs"
"/api/v1/projects/{project}/sweeps"
"/api/v1/queue"
"/api/v1/runs/{run_id}/pull"
"/api/v1/sweeps"
"/api/v1/sweeps/{project}/{sweep_id}"
"/api/v1/sweeps/{project}/{sweep_id}/cancel_queued"
"/api/v1/sweeps/{project}/{sweep_id}/extend"
```

If a path is missing, stop: the backend plan is not merged. If a path exists with another placeholder name (for example `{id}` where this plan has `{sweep_id}`, or `{name}` where it has `{host}`), the backend spelling wins: use it in `PHASE_2_ROUTES` (Step 1), in `ROUTES` and in the matching `params` keys (Step 4). `bun run typecheck` fails until they agree.

- [ ] **Step 4: Add the routes and the api functions**

In `ui/src/api/client.ts`, replace

```ts
  compareExamples: "/api/v1/compare/examples",
} as const satisfies Record<string, keyof paths>;
```

with

```ts
  compareExamples: "/api/v1/compare/examples",
  hosts: "/api/v1/hosts",
  hostConnect: "/api/v1/hosts/{host}/connect",
  hostRuns: "/api/v1/hosts/{host}/runs",
  sweep: "/api/v1/sweeps/{project}/{sweep_id}",
  sweepCancelQueued: "/api/v1/sweeps/{project}/{sweep_id}/cancel_queued",
  sweepExtend: "/api/v1/sweeps/{project}/{sweep_id}/extend",
  projectSweeps: "/api/v1/projects/{project}/sweeps",
  runPull: "/api/v1/runs/{run_id}/pull",
  gpus: "/api/v1/gpus",
  queue: "/api/v1/queue",
} as const satisfies Record<string, keyof paths>;
```

At the end of the `api` object, replace

```ts
      body: { ...action(opts), text, author: opts?.created_by ?? "human" },
    }),
};
```

with

```ts
      body: { ...action(opts), text, author: opts?.created_by ?? "human" },
    }),
  // phase 2: hosts, launch, sweeps, pull ---------------------------------------------------
  hosts: (signal?: AbortSignal) => get<M.HostRow[]>(ROUTES.hosts, { signal }),
  /** The hub's own GPUs (an env route: the hub is the env server of its own runs). */
  gpus: (signal?: AbortSignal) => get<M.GpuInfo[]>(ROUTES.gpus, { signal }),
  /** The hub's own run queue, in order. */
  queue: (signal?: AbortSignal) => get<M.QueueEntry[]>(ROUTES.queue, { signal }),
  connectHost: (host: string, opts?: M.ActionOptions) =>
    post<M.HostState>(ROUTES.hostConnect, { params: { host }, body: action(opts) }),
  /** Start a run on the hub itself. */
  launch: (body: M.LaunchRequest, opts?: M.ActionOptions) =>
    post<M.RunRecord>(ROUTES.runs, { body: { ...action(opts), ...body } }),
  /** Start or queue a run on a remote host; the hub forwards it and returns the host's record. */
  launchOnHost: (host: string, body: M.HostLaunchRequest, opts?: M.ActionOptions) =>
    post<M.RunRecord>(ROUTES.hostRuns, { params: { host }, body: { ...action(opts), ...body } }),
  sweep: (project: string, sweepId: string, signal?: AbortSignal) =>
    get<M.SweepSummary>(ROUTES.sweep, { params: { project, sweep_id: sweepId }, signal }),
  projectSweeps: (project: string, signal?: AbortSignal) =>
    get<M.SweepListItem[]>(ROUTES.projectSweeps, { params: { project }, signal }),
  /** Stop the sweep's queued runs (recorded as `killed`); running runs keep going. */
  cancelQueued: (project: string, sweepId: string, opts?: M.ActionOptions) =>
    post<M.SweepSummary>(ROUTES.sweepCancelQueued, {
      params: { project, sweep_id: sweepId },
      body: action(opts),
    }),
  /** Add runs for every parameter combination x each new seed. */
  extendSweep: (project: string, sweepId: string, seeds: readonly number[], opts?: M.ActionOptions) =>
    post<M.SweepSummary>(ROUTES.sweepExtend, {
      params: { project, sweep_id: sweepId },
      body: { ...action(opts), seeds: [...seeds] },
    }),
  /** Copy one remote artifact (a kind such as `checkpoint`, or a run-relative path) to the hub. */
  pull: (runId: string, artifact: string, opts?: M.ActionOptions) =>
    post<M.PullResult>(ROUTES.runPull, { params: { run_id: runId }, body: { ...action(opts), artifact } }),
};
```

- [ ] **Step 5: Run the tests and the type checker to verify they pass**

Run: `bun test test/api/client.test.ts test/api/types.test.ts && bun run typecheck`
Expected: `27 pass`, `0 fail`; `tsc --noEmit` prints no errors.

- [ ] **Step 6: Commit**

```bash
git add ui/src/api/types.ts ui/src/api/client.ts ui/test/api/client.test.ts ui/test/api/types.test.ts
git commit -m "feat(ui): api client for hosts, launch on host, sweeps and pull"
```

---

### Task 3: Query keys, read hooks and host invalidation lists

**Files:**
- Modify: `ui/src/api/queries.ts` (header lines 1-7; `queryKeys` end at line 42; after `RUN_EVENT_INVALIDATES` at line 59; before `// writes` at line 165)
- Test: `ui/test/api/queries.test.tsx`

**Interfaces:**
- Consumes: `api.hosts`, `api.sweep`, `api.projectSweeps` (Task 2); fixtures `HOSTS`, `SWEEP`, `SWEEP_LIST`.
- Produces (in `ui/src/api/queries.ts`):
  - `queryKeys.hosts() => ["hosts"]`, `queryKeys.sweep(project, sweepId) => ["sweeps", project, "detail", sweepId]`, `queryKeys.projectSweeps(project) => ["sweeps", project, "list"]`.
  - `REMOTE_RUN_INVALIDATES: readonly QueryKey[]` = `[...RUN_EVENT_INVALIDATES, ["hosts"]]`. Use it as `invalidate` for `useAction` on `api.launchOnHost`, `api.cancelQueued`, `api.extendSweep`.
  - `HOST_EVENT_INVALIDATES: readonly QueryKey[]` = `[["hosts"], ["overview"], ["runs"], ["run"], ["sweeps"]]`. Use it as `invalidate` for `api.connectHost`.
  - `HOSTS_REFETCH_MS = 10_000`.
  - `keepLastKnown(prev: readonly HostRow[] | undefined, next: HostRow[]): HostRow[]` (a `stale` host keeps the GPUs and queue of the previous list, same name and `environment_id`; the hub sends `gpus: []`, `queue: 0` for every host that is not connected) and `fetchHosts(qc: QueryClient, signal?): Promise<HostRow[]>` (`api.hosts` through `keepLastKnown` against the cached `["hosts"]` data; Task 11's launch hosts query reuses it).
  - `useHosts(refetchMs = HOSTS_REFETCH_MS, enabled = true)`, `useSweep(project, sweepId)`, `useProjectSweeps(project)` (TanStack `UseQueryResult` of `HostRow[]`, `SweepSummary`, `SweepListItem[]`). Every reader of `["hosts"]` uses `useHosts` (the run page passes `enabled`), so there is one query function per key.
  - Complete run lists: `ALL_RUNS_FIRST = 1000`, `ALL_RUNS_MAX = 64_000`, `interface AllRuns { runs: RunRecord[]; complete: boolean }`, `fetchAllRuns(query: Omit<RunsQuery, "limit">, signal?): Promise<AllRuns>` (asks `GET /api/v1/runs` with `limit` 1000, then 4× more while a page comes back full; the route has no offset, so a bigger limit is the next page; `complete: false` only past `ALL_RUNS_MAX`), `queryKeys.allRuns(query) => ["runs", "all", query]` (under `["runs"]`, so run events refresh it), `useAllRuns(query, enabled = true)`. The host queue (Task 27) and the sweep page (Task 21) read through it, so a 1,000-run sweep or a long queue is never cut to the newest page.

- [ ] **Step 1: Write the failing tests**

In `ui/test/api/queries.test.tsx`, replace the imports

```ts
import {
  RUN_EVENT_INVALIDATES,
  createQueryClient,
  queryKeys,
  shouldRetry,
  useLeaderboard,
  useSaveView,
  useView,
} from "../../src/api/queries";
import { mockRoutes } from "./fetch-mock";
```

with

```ts
import {
  ALL_RUNS_FIRST,
  ALL_RUNS_MAX,
  HOST_EVENT_INVALIDATES,
  HOSTS_REFETCH_MS,
  REMOTE_RUN_INVALIDATES,
  RUN_EVENT_INVALIDATES,
  createQueryClient,
  fetchAllRuns,
  keepLastKnown,
  queryKeys,
  shouldRetry,
  useHosts,
  useLeaderboard,
  useProjectSweeps,
  useSaveView,
  useSweep,
  useView,
} from "../../src/api/queries";
import type { ConnState, HostRow, HostState, RunRecord } from "../../src/api/models";
import { mockRoutes } from "./fetch-mock";
import { HOSTS, SWEEP, SWEEP_LIST } from "./phase2-fixtures";

/** `n` minimal run rows; `fetchAllRuns` only counts them. */
const rows = (n: number): RunRecord[] =>
  Array.from({ length: n }, (_, i) => ({ run_id: `r${i}` }) as unknown as RunRecord);

/** A host row as the hub sends it once the host is not connected: no GPUs, queue 0. */
const gone = (row: HostRow, conn: ConnState, over: Partial<HostState> = {}): HostRow => ({
  ...row,
  gpus: [],
  queue: 0,
  state: { ...row.state, state: conn, since: "2026-10-03T14:31:00Z", ...over },
});
```

At the end of `describe("queryKeys", ...)`, after the test `RUN_EVENT_INVALIDATES hits run data and panel queries but not view documents`, add:

```ts
  test("phase 2 keys: one hosts list, sweeps under their project", () => {
    expect(queryKeys.hosts()).toEqual(["hosts"]);
    expect(queryKeys.sweep("toy", "s-7f3a")).toEqual(["sweeps", "toy", "detail", "s-7f3a"]);
    expect(queryKeys.projectSweeps("toy")).toEqual(["sweeps", "toy", "list"]);
  });

  test("REMOTE_RUN_INVALIDATES is the run families plus the hosts list", () => {
    expect(REMOTE_RUN_INVALIDATES).toEqual([...RUN_EVENT_INVALIDATES, ["hosts"]]);
  });

  test("keepLastKnown keeps a stale host's last connected GPUs and queue, nothing else", () => {
    const [local, gpu1, mccleary] = HOSTS as [HostRow, HostRow, HostRow, HostRow];
    const next = keepLastKnown([local, gpu1, mccleary], [local, gone(gpu1, "stale"), mccleary]);
    expect(next[1]?.state.state).toBe("stale");
    expect([next[1]?.gpus, next[1]?.queue]).toEqual([gpu1.gpus, 3]);
    expect(next[0]).toBe(local);
    // still stale on the next poll: the same last known cells stay
    expect(keepLastKnown(next, [local, gone(gpu1, "stale"), mccleary])[1]?.gpus).toEqual(gpu1.gpus);
    // other states, no earlier list, or another environment keep the empty row
    expect(keepLastKnown([gpu1], [gone(gpu1, "error")])[0]?.gpus).toEqual([]);
    expect(keepLastKnown(undefined, [gone(gpu1, "stale")])[0]?.gpus).toEqual([]);
    expect(keepLastKnown([gpu1], [gone(gpu1, "stale", { environment_id: "env-new" })])[0]?.queue).toBe(0);
  });

  test("HOST_EVENT_INVALIDATES hits hosts and host-state readers, not scores or views", async () => {
    const { qc } = setup();
    const hit = [
      queryKeys.hosts(),
      queryKeys.overview(),
      queryKeys.runs({ project: "toy" }),
      queryKeys.run("r1"),
      queryKeys.sweep("toy", "s-7f3a"),
      queryKeys.projectSweeps("toy"),
    ];
    const miss = [
      queryKeys.leaderboard("toy", "acc"),
      queryKeys.tasks(),
      queryKeys.task("toy", "acc"),
      queryKeys.viewQuery("toy", "acc", { name: "overview" }),
      queryKeys.views("toy", "acc"),
      queryKeys.projects(),
    ];
    for (const key of [...hit, ...miss]) qc.setQueryData(key, { seeded: true });
    await Promise.all(HOST_EVENT_INVALIDATES.map((queryKey) => qc.invalidateQueries({ queryKey })));
    expect(hit.map((k) => invalidated(qc, k))).toEqual(hit.map(() => true));
    expect(miss.map((k) => invalidated(qc, k))).toEqual(miss.map(() => false));
  });
```

In `describe("hooks", ...)`, directly above the test `useView stays idle while name is null`, add:

```ts
  test("useHosts polls every 10 s by default", () => {
    expect(HOSTS_REFETCH_MS).toBe(10_000);
  });

  test("useHosts loads the hosts and keeps polling them", async () => {
    const calls = mockRoutes({ "/api/v1/hosts": HOSTS });
    const { wrapper } = setup();
    const { result } = renderHook(() => useHosts(25), { wrapper });
    await waitFor(() =>
      expect(result.current.data?.map((h) => h.name)).toEqual(["local", "gpu1", "mccleary", "dgx"]),
    );
    await waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(3), { timeout: 1_000 });
    expect(new Set(calls.map((c) => c.url))).toEqual(new Set(["/api/v1/hosts"]));
  });

  test("useHosts keeps polling after the hub answers an error", async () => {
    const calls = mockRoutes({ "/api/v1/hosts": null });
    const { wrapper } = setup();
    const { result } = renderHook(() => useHosts(25), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
    await waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(3), { timeout: 1_000 });
    mockRoutes({ "/api/v1/hosts": HOSTS });
    await waitFor(() => expect(result.current.data?.length).toBe(4), { timeout: 1_000 });
  });

  test("useHosts keeps a stale host's last GPUs and queue between polls", async () => {
    const [local, gpu1] = HOSTS as [HostRow, HostRow];
    mockRoutes({ "/api/v1/hosts": [local, gpu1] });
    const { wrapper } = setup();
    const { result } = renderHook(() => useHosts(25), { wrapper });
    await waitFor(() => expect(result.current.data?.[1]?.gpus.length).toBe(3));
    mockRoutes({ "/api/v1/hosts": [local, gone(gpu1, "stale")] });
    await waitFor(() => expect(result.current.data?.[1]?.state.state).toBe("stale"), { timeout: 1_000 });
    expect([result.current.data?.[1]?.gpus.length, result.current.data?.[1]?.queue]).toEqual([3, 3]);
  });

  test("useSweep loads one sweep under its project key", async () => {
    const calls = mockRoutes({ "/api/v1/sweeps/toy/s-7f3a": SWEEP });
    const { qc, wrapper } = setup();
    const { result } = renderHook(() => useSweep("toy", "s-7f3a"), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.headline).toBe("lr 3e-4, beam 10: 0.912 [0.911, 0.913], n = 3");
    expect(qc.getQueryData<typeof SWEEP>(queryKeys.sweep("toy", "s-7f3a"))).toEqual(SWEEP);
    expect(calls.map((c) => c.url)).toEqual(["/api/v1/sweeps/toy/s-7f3a"]);
  });

  test("useProjectSweeps lists a project's sweeps", async () => {
    mockRoutes({ "/api/v1/projects/toy/sweeps": SWEEP_LIST });
    const { wrapper } = setup();
    const { result } = renderHook(() => useProjectSweeps("toy"), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.map((s) => [s.id, s.n_runs])).toEqual([["s-7f3a", 6]]);
  });

  test("fetchAllRuns asks for 4x more while a page comes back full, so no run is cut", async () => {
    const q = "/api/v1/runs?status=queued&environment_id=env-gpu1&limit=";
    // 1,500 queued runs on one host: the first page (1,000) is full, the second is not
    const calls = mockRoutes({ [`${q}1000`]: rows(1000), [`${q}4000`]: rows(1500) });
    const out = await fetchAllRuns({ status: "queued", environment_id: "env-gpu1" });
    expect([out.runs.length, out.complete]).toEqual([1500, true]);
    expect(calls.map((c) => c.url)).toEqual([`${q}1000`, `${q}4000`]);
    expect(queryKeys.allRuns({ status: "queued" })).toEqual(["runs", "all", { status: "queued" }]);
  });

  test("fetchAllRuns stops at ALL_RUNS_MAX and says the list is cut", async () => {
    expect([ALL_RUNS_FIRST, ALL_RUNS_MAX]).toEqual([1000, 64_000]);
    const q = "/api/v1/runs?tag=sweep%3As-1&limit=";
    const calls = mockRoutes({
      [`${q}1000`]: rows(1000),
      [`${q}4000`]: rows(4000),
      [`${q}16000`]: rows(16000),
      [`${q}64000`]: rows(64000),
    });
    const out = await fetchAllRuns({ tag: "sweep:s-1" });
    expect([out.runs.length, out.complete]).toEqual([64000, false]);
    expect(calls).toHaveLength(4);
  });

```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bun test test/api/queries.test.tsx`
Expected: FAIL: the file does not load (`SyntaxError: Export named 'fetchAllRuns' not found in module`; bun names one of the missing new exports).

- [ ] **Step 3: Add keys, lists and hooks**

In `ui/src/api/queries.ts`, replace the header lines

```ts
 * per-run query, `["views", "query"]` every panel query. `RUN_EVENT_INVALIDATES` is the
 * list the live event stream invalidates on any `run.*` event.
 */
```

with

```ts
 * per-run query, `["views", "query"]` every panel query, `["sweeps", project]` every sweep
 * query of a project. `RUN_EVENT_INVALIDATES` is the list the live event stream invalidates
 * on any `run.*` event; `REMOTE_RUN_INVALIDATES` on `mirror.run_updated`;
 * `HOST_EVENT_INVALIDATES` on `host.*`.
 */
```

Replace the end of `queryKeys`

```ts
  viewQuery: (project: string, task: string, body: M.ViewQueryBody) =>
    ["views", "query", project, task, body] as const,
};
```

with

```ts
  viewQuery: (project: string, task: string, body: M.ViewQueryBody) =>
    ["views", "query", project, task, body] as const,
  hosts: () => ["hosts"] as const,
  sweep: (project: string, sweepId: string) => ["sweeps", project, "detail", sweepId] as const,
  projectSweeps: (project: string) => ["sweeps", project, "list"] as const,
  allRuns: (query: Omit<M.RunsQuery, "limit">) => ["runs", "all", query] as const,
};
```

Directly after the closing `];` of `RUN_EVENT_INVALIDATES` (before `/** Retry transient failures twice ...`), insert:

```ts

/**
 * Families a remote run change can touch: a `mirror.run_updated` event, a launch on a host,
 * or a sweep action. The run families plus the hosts list (queue length, GPUs, cost today).
 */
export const REMOTE_RUN_INVALIDATES: readonly QueryKey[] = [...RUN_EVENT_INVALIDATES, ["hosts"]];

/**
 * Families a `host.*` event (or a connect/disconnect) can change (phase 2 contract 4): the
 * hosts list, and everything that shows a host's state (overview, run lists, run pages with
 * `host_state`, sweeps). Scores do not change, so leaderboards and panels are left alone.
 */
export const HOST_EVENT_INVALIDATES: readonly QueryKey[] = [
  ["hosts"],
  ["overview"],
  ["runs"],
  ["run"],
  ["sweeps"],
];

/** The hosts list refetches this often: GPU use changes every 10 s with no event (spec 8A.7). */
export const HOSTS_REFETCH_MS = 10_000;

/**
 * Keep a stale host's last known GPUs and queue length.
 *
 * The hub asks a host for its GPUs and queue only while the host is `connected`; for every
 * other state its row has `gpus: []` and `queue: 0`. The Hosts panel and the Launch dialog
 * draw a stale host's last known cells greyed, so a row that is `stale`, has no GPUs of its
 * own, and serves the same environment as in `prev` takes `prev`'s GPUs and queue. Rows in
 * any other state are kept as the hub sent them.
 */
export function keepLastKnown(prev: readonly M.HostRow[] | undefined, next: M.HostRow[]): M.HostRow[] {
  if (prev === undefined) return next;
  const before = new Map(prev.map((row) => [row.name, row]));
  return next.map((row) => {
    const old = before.get(row.name);
    if (old === undefined || row.state.state !== "stale" || row.gpus.length > 0) return row;
    if (old.state.environment_id !== row.state.environment_id) return row;
    return { ...row, gpus: old.gpus, queue: old.queue };
  });
}

/** `GET /api/v1/hosts` through `keepLastKnown` against the cached `["hosts"]` list. */
export async function fetchHosts(qc: QueryClient, signal?: AbortSignal): Promise<M.HostRow[]> {
  const rows = await api.hosts(signal);
  return keepLastKnown(qc.getQueryData<M.HostRow[]>(queryKeys.hosts()), rows);
}
```

Directly above the line `// writes -----------------------------------------------------------------------------------`, insert:

```ts
/**
 * Every host (the hub's `local` row first) with its state, GPUs, queue and cost today; polls
 * every `refetchMs`; a stale host keeps its last known GPUs and queue (`keepLastKnown`).
 * `enabled: false` keeps it idle (the run page of a hub run).
 */
export function useHosts(refetchMs: number = HOSTS_REFETCH_MS, enabled = true) {
  const qc = useQueryClient();
  return useQuery({
    queryKey: queryKeys.hosts(),
    queryFn: ({ signal }) => fetchHosts(qc, signal),
    refetchInterval: refetchMs,
    enabled,
  });
}

export const useSweep = (project: string, sweepId: string) =>
  useQuery({
    queryKey: queryKeys.sweep(project, sweepId),
    queryFn: ({ signal }) => api.sweep(project, sweepId, signal),
  });

export const useProjectSweeps = (project: string) =>
  useQuery({
    queryKey: queryKeys.projectSweeps(project),
    queryFn: ({ signal }) => api.projectSweeps(project, signal),
  });

/** First `limit` of `fetchAllRuns`; each next request asks for 4× as many. */
export const ALL_RUNS_FIRST = 1000;
/** `fetchAllRuns` stops growing here and marks the list cut. */
export const ALL_RUNS_MAX = 64_000;

/** Every run a query matches, and whether the list is whole. */
export interface AllRuns {
  runs: M.RunRecord[];
  /** False only when more than `ALL_RUNS_MAX` runs match. */
  complete: boolean;
}

/**
 * Every run that matches `query`, not only the newest page.
 *
 * `GET /api/v1/runs` has a `limit` and no offset, so the next page is a bigger limit: start
 * at `ALL_RUNS_FIRST` and ask for 4× more while a page comes back full. A host queue or a
 * 1,000-run sweep then never loses its oldest runs (the queue head) to the page size.
 */
export async function fetchAllRuns(query: Omit<M.RunsQuery, "limit">, signal?: AbortSignal): Promise<AllRuns> {
  for (let limit = ALL_RUNS_FIRST; ; limit *= 4) {
    const runs = await api.runs({ ...query, limit }, signal);
    if (runs.length < limit) return { runs, complete: true };
    if (limit >= ALL_RUNS_MAX) return { runs, complete: false };
  }
}

/** `fetchAllRuns` as a query under `["runs"]`, so every run event refreshes it. */
export const useAllRuns = (query: Omit<M.RunsQuery, "limit">, enabled = true) =>
  useQuery({
    queryKey: queryKeys.allRuns(query),
    queryFn: ({ signal }) => fetchAllRuns(query, signal),
    enabled,
  });

```

`refetchInterval` refetches whatever the 5 s `staleTime` says, and keeps running after a failed fetch, so the Hosts panel recovers when a host comes back. A failed refetch keeps the last `data` (TanStack Query), so a page that loaded the hosts list once still names each host while the hub answers 503.

- [ ] **Step 4: Run the tests and the type checker to verify they pass**

Run: `bun test test/api/queries.test.tsx && bun run typecheck`
Expected: `18 pass`, `0 fail`; `tsc --noEmit` prints no errors.

- [ ] **Step 5: Commit**

```bash
git add ui/src/api/queries.ts ui/test/api/queries.test.tsx
git commit -m "feat(ui): queries for hosts and sweeps"
```

---

### Task 4: Live invalidation for mirror, host and sweep data

**Files:**
- Modify: `ui/src/api/queries.ts` (`RUN_EVENT_INVALIDATES` and its doc comment, lines 44-59)
- Modify: `ui/src/api/events.ts` (import line 15; `BY_PROJECT` lines 110-111; `keysForEvent` lines 126-147; `onEvents` in `useEventStream`)
- Create: `ui/src/api/lostReasons.ts`
- Test: `ui/test/api/events.test.ts`, `ui/test/api/queries.test.tsx`, `ui/test/api/lostReasons.test.ts`

**Interfaces:**
- Consumes: `RUN_EVENT_INVALIDATES`, `REMOTE_RUN_INVALIDATES`, `HOST_EVENT_INVALIDATES`, `queryKeys.hosts/sweep/projectSweeps` (Task 3).
- Produces:
  - `RUN_EVENT_INVALIDATES` gains `["sweeps"]` (last), so every `run.*` event and every `useAction` that uses it refreshes sweep pages.
  - `MIRROR_RUN_UPDATED = "mirror.run_updated"` exported from `ui/src/api/events.ts`.
  - `keysForEvent(event)`: `run.*` → `RUN_EVENT_INVALIDATES` narrowed (`["run", runId]`, `["task" | "leaderboard" | "sweeps", project]`, `["views", "query", project]`); `mirror.run_updated` → `REMOTE_RUN_INVALIDATES` narrowed the same way (ends with `["hosts"]`); `host.*` → `HOST_EVENT_INVALIDATES` unchanged; other types → `[]`.
  - `ui/src/api/lostReasons.ts`: `lostReasonOf(event: HxEvent): string | null` (the trimmed `payload.reason` of `run.lost`, or of `mirror.run_updated` with `original_type: "run.lost"`), `noteLostReasons(events)`, `lostReasonFor(runId): string | null`, `useLostReason(runId): string | null`, `clearLostReasons()` (tests). `useEventStream` passes every batch to `noteLostReasons` before invalidating.

- [ ] **Step 1: Write the failing tests**

In `ui/test/api/queries.test.tsx`, in the test `RUN_EVENT_INVALIDATES hits run data and panel queries but not view documents`, replace

```ts
      queryKeys.compareExamples("r1", "r2", "accuracy"),
    ];
    const miss = [queryKeys.views("toy", "acc"), queryKeys.view("toy", "acc", "route"), queryKeys.projects()];
```

with

```ts
      queryKeys.compareExamples("r1", "r2", "accuracy"),
      queryKeys.sweep("toy", "s-7f3a"),
      queryKeys.projectSweeps("toy"),
    ];
    const miss = [
      queryKeys.views("toy", "acc"),
      queryKeys.view("toy", "acc", "route"),
      queryKeys.projects(),
      queryKeys.hosts(),
    ];
```

In `ui/test/api/events.test.ts`, add `MIRROR_RUN_UPDATED` to the import from `../../src/api/events`: replace

```ts
  keysForEvents,
  readSequence,
```

with

```ts
  keysForEvents,
  MIRROR_RUN_UPDATED,
  readSequence,
```

In `describe("keysForEvent", ...)`, replace the first two tests' expectations and add three tests. Replace

```ts
      ["views", "query", "toy"],
      ["compareExamples"],
    ]);
  });

  test("a run event without project or run id invalidates the families", () => {
    expect(keysForEvent(ev(1, "run.lost", null, null))).toEqual([
      ["overview"],
      ["tasks"],
      ["task"],
      ["runs"],
      ["leaderboard"],
      ["views", "query"],
      ["compareExamples"],
    ]);
  });
```

with

```ts
      ["views", "query", "toy"],
      ["compareExamples"],
      ["sweeps", "toy"],
    ]);
  });

  test("a run event without project or run id invalidates the families", () => {
    expect(keysForEvent(ev(1, "run.lost", null, null))).toEqual([
      ["overview"],
      ["tasks"],
      ["task"],
      ["runs"],
      ["leaderboard"],
      ["views", "query"],
      ["compareExamples"],
      ["sweeps"],
    ]);
  });

  test("a mirrored remote run event refreshes that run, its project, and the hosts list", () => {
    expect(keysForEvent(ev(1, MIRROR_RUN_UPDATED, "toy", "r9"))).toEqual([
      ["overview"],
      ["tasks"],
      ["task", "toy"],
      ["runs"],
      ["run", "r9"],
      ["leaderboard", "toy"],
      ["views", "query", "toy"],
      ["compareExamples"],
      ["sweeps", "toy"],
      ["hosts"],
    ]);
  });

  test("a host event refreshes hosts and every page that shows host state", () => {
    expect(keysForEvent(ev(1, "host.state", null, null))).toEqual([
      ["hosts"],
      ["overview"],
      ["runs"],
      ["run"],
      ["sweeps"],
    ]);
  });

  test("other mirror events invalidate nothing", () => {
    expect(MIRROR_RUN_UPDATED).toBe("mirror.run_updated");
    expect(keysForEvent(ev(1, "mirror.cursor_saved", null, null))).toEqual([]);
  });

  test("a burst of mirror events after hours offline invalidates each key once", () => {
    // Runs finished while the hub was offline; on reconnect it replays 300 mirror events for 3 runs.
    const burst = Array.from({ length: 300 }, (_, i) => ev(i + 1, MIRROR_RUN_UPDATED, "toy", `r${i % 3}`));
    const keys = keysForEvents(burst);
    expect(keys).toHaveLength(12);
    expect(keys.filter((k) => k[0] === "hosts")).toEqual([["hosts"]]);
    expect(keys.filter((k) => k[0] === "run")).toEqual([
      ["run", "r0"],
      ["run", "r1"],
      ["run", "r2"],
    ]);
  });
```

In the test `keysForEvents drops duplicate keys and keeps first-seen order`, replace

```ts
      ["views", "query", "toy"],
      ["compareExamples"],
      ["run", "r2"],
    ]);
```

with

```ts
      ["views", "query", "toy"],
      ["compareExamples"],
      ["sweeps", "toy"],
      ["run", "r2"],
    ]);
```

In the test `a run event refreshes every page query of that run and project, and no view text`, replace

```ts
      queryKeys.compareExamples("r0", "r1", "accuracy"),
    ];
    const miss = [
      queryKeys.run("r2"),
      queryKeys.leaderboard("other", "acc"),
```

with

```ts
      queryKeys.compareExamples("r0", "r1", "accuracy"),
      queryKeys.sweep("toy", "s-7f3a"),
      queryKeys.projectSweeps("toy"),
    ];
    const miss = [
      queryKeys.run("r2"),
      queryKeys.leaderboard("other", "acc"),
      queryKeys.sweep("other", "s-1"),
      queryKeys.hosts(),
```

and directly after that test (still inside `describe("keysForEvent", ...)`) add:

```ts

  test("mirror and host events refresh remote run pages and hosts, not scores of other projects", async () => {
    const client = new QueryClient();
    const hit = [
      queryKeys.hosts(),
      queryKeys.overview(),
      queryKeys.runs({ project: "toy" }),
      queryKeys.run("r9"),
      queryKeys.run("r2"),
      queryKeys.leaderboard("toy", "acc"),
      queryKeys.sweep("toy", "s-7f3a"),
      queryKeys.sweep("other", "s-1"),
    ];
    const miss = [
      queryKeys.leaderboard("other", "acc"),
      queryKeys.views("toy", "acc"),
      queryKeys.view("toy", "acc", "route"),
      queryKeys.projects(),
    ];
    for (const key of [...hit, ...miss]) client.setQueryData(key, { seeded: true });
    invalidateForEvents(client, [
      ev(1, MIRROR_RUN_UPDATED, "toy", "r9"),
      ev(2, "host.state", null, null),
    ]);
    await new Promise((resolve) => setTimeout(resolve, 0));
    const invalidated = (key: readonly unknown[]) => client.getQueryState(key)?.isInvalidated;
    expect(hit.map(invalidated)).toEqual(hit.map(() => true));
    expect(miss.map(invalidated)).toEqual(miss.map(() => false));
  });
```

In `describe("useEventStream", ...)`, test `invalidates the mapped keys, reports status, and closes on unmount`, replace

```ts
      { queryKey: ["views", "query", "toy"] },
      { queryKey: ["compareExamples"] },
    ]);
```

with

```ts
      { queryKey: ["views", "query", "toy"] },
      { queryKey: ["compareExamples"] },
      { queryKey: ["sweeps", "toy"] },
    ]);
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bun test test/api/events.test.ts test/api/queries.test.tsx`
Expected: FAIL. `events.test.ts` does not load (`SyntaxError: Export named 'MIRROR_RUN_UPDATED' not found in module`); in `queries.test.tsx`, `RUN_EVENT_INVALIDATES hits run data ...` fails because the two sweep keys are not invalidated (`[..., false, false]` vs `[..., true, true]`).

- [ ] **Step 3: Add sweeps to the run families**

In `ui/src/api/queries.ts`, replace

```ts
/**
 * Key families a `run.*` event or a run action can change (contract section 4: runs,
 * leaderboard, overview, views/query; plus the task summary, run detail and example
 * comparisons that read the same runs). View lists, view documents and `/kind` are never
 * in this list, so an open editor is not reloaded under the user.
 */
export const RUN_EVENT_INVALIDATES: readonly QueryKey[] = [
  ["overview"],
  ["tasks"],
  ["task"],
  ["runs"],
  ["run"],
  ["leaderboard"],
  ["views", "query"],
  ["compareExamples"],
];
```

with

```ts
/**
 * Key families a `run.*` event or a run action can change (contract section 4: runs,
 * leaderboard, overview, views/query; plus the task summary, run detail, example
 * comparisons and sweeps that read the same runs). View lists, view documents and `/kind`
 * are never in this list, so an open editor is not reloaded under the user. The hosts list
 * is not either: a hub run does not change a remote host.
 */
export const RUN_EVENT_INVALIDATES: readonly QueryKey[] = [
  ["overview"],
  ["tasks"],
  ["task"],
  ["runs"],
  ["run"],
  ["leaderboard"],
  ["views", "query"],
  ["compareExamples"],
  ["sweeps"],
];
```

- [ ] **Step 4: Map mirror and host events in `events.ts`**

In `ui/src/api/events.ts`, replace

```ts
import { RUN_EVENT_INVALIDATES } from "./queries";
```

with

```ts
import { HOST_EVENT_INVALIDATES, REMOTE_RUN_INVALIDATES, RUN_EVENT_INVALIDATES } from "./queries";
```

Replace

```ts
/** `RUN_EVENT_INVALIDATES` families whose next key segment is the project. */
const BY_PROJECT = new Set(["task", "leaderboard", "views/query"]);
```

with

```ts
/** Run families whose next key segment is the project. */
const BY_PROJECT = new Set(["task", "leaderboard", "views/query", "sweeps"]);

/** Event type the hub emits after mirroring a remote run's event (phase 2 contract 1.5). */
export const MIRROR_RUN_UPDATED = "mirror.run_updated";
```

Replace

```ts
/**
 * Query keys to invalidate for one event. Only `run.*` events change query data.
 *
 * The families are `RUN_EVENT_INVALIDATES` (Task 4), narrowed where the key allows:
 * `["task" | "leaderboard", project]`, `["views", "query", project]`, `["run", runId]`
 * (prefix match, so `["run", id]` covers its metrics, logs, predictions and traces).
 */
export function keysForEvent(event: HxEvent): QueryKey[] {
  if (!event.type.startsWith("run.")) return [];
  const keys: QueryKey[] = [];
  for (const family of RUN_EVENT_INVALIDATES) {
```

with

```ts
/**
 * Query keys to invalidate for one event.
 *
 * - `run.*`: `RUN_EVENT_INVALIDATES`, narrowed to the event's run and project.
 * - `mirror.run_updated` (a remote run changed): `REMOTE_RUN_INVALIDATES`, narrowed the
 *   same way, so it also refreshes the hosts list.
 * - `host.*`: `HOST_EVENT_INVALIDATES` as is (a host change touches all its runs).
 * - anything else: nothing.
 */
export function keysForEvent(event: HxEvent): QueryKey[] {
  if (event.type.startsWith("host.")) return HOST_EVENT_INVALIDATES.map((family) => [...family]);
  if (event.type === MIRROR_RUN_UPDATED) return narrow(REMOTE_RUN_INVALIDATES, event);
  if (event.type.startsWith("run.")) return narrow(RUN_EVENT_INVALIDATES, event);
  return [];
}

/**
 * Narrow key families to one run event where the key allows: `["run", runId]` (prefix
 * match, so it covers the run's metrics, logs, predictions and traces), and
 * `["task" | "leaderboard" | "sweeps", project]`, `["views", "query", project]`.
 */
function narrow(families: readonly QueryKey[], event: HxEvent): QueryKey[] {
  const keys: QueryKey[] = [];
  for (const family of families) {
```

The rest of the old loop body (`const id = family.join("/"); ... return keys; }`) stays as it is; it is now the body of `narrow`.

- [ ] **Step 5: Write the failing lost-reason tests**

The env server puts the cause of a lost run in its `run.lost` event (`payload.reason`, e.g. `SLURM ended job 4471023 with NODE_FAIL on r814u05n01; no exit record`); the run detail has no field for it. The app's one event stream hands every batch to a small store, and the run page reads the reason from it (Tasks 23, 25, 27). A hub run's own `run.lost` carries the reason itself; a mirrored one arrives as `mirror.run_updated` with `original_type: "run.lost"` and the same `reason` in its payload. When no such event was seen in this tab (the tab resumed after it, or the payload has no reason), the page keeps the neutral words.

Create `ui/test/api/lostReasons.test.ts`:

```ts
import { afterEach, describe, expect, test } from "bun:test";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";

import { type Clock, type SocketLike, useEventStream } from "../../src/api/events";
import { clearLostReasons, lostReasonFor, lostReasonOf, noteLostReasons, useLostReason } from "../../src/api/lostReasons";
import type { HxEvent } from "../../src/api/models";

const NODE_FAIL = "SLURM ended job 4471023 with NODE_FAIL on r814u05n01; no exit record";

function ev(sequence: number, type: string, payload: Record<string, unknown>, run_id: string | null = "r1"): HxEvent {
  return { sequence, type, project: "toy", run_id, payload, created_at: "2026-10-03T02:14:37Z" };
}

afterEach(clearLostReasons);

describe("lost reasons", () => {
  test("lostReasonOf reads run.lost and a mirrored run.lost, nothing else", () => {
    expect(lostReasonOf(ev(1, "run.lost", { reason: NODE_FAIL, slurm_job_id: "4471023" }))).toBe(NODE_FAIL);
    expect(
      lostReasonOf(ev(2, "mirror.run_updated", { original_type: "run.lost", status: "lost", reason: ` ${NODE_FAIL} ` })),
    ).toBe(NODE_FAIL);
    // a mirrored event about something else, a reasonless one, a blank one, no run id
    expect(lostReasonOf(ev(3, "mirror.run_updated", { original_type: "run.finished", reason: "x" }))).toBeNull();
    expect(lostReasonOf(ev(4, "mirror.run_updated", { original_type: "run.lost", status: "lost" }))).toBeNull();
    expect(lostReasonOf(ev(5, "run.lost", { reason: "   " }))).toBeNull();
    expect(lostReasonOf(ev(6, "run.lost", { reason: 7 }))).toBeNull();
    expect(lostReasonOf(ev(7, "run.lost", { reason: NODE_FAIL }, null))).toBeNull();
    expect(lostReasonOf(ev(8, "run.failed", { reason: NODE_FAIL }))).toBeNull();
  });

  test("noteLostReasons keeps one reason per run and useLostReason follows it", () => {
    const { result } = renderHook(() => useLostReason("r1"));
    expect(result.current).toBeNull();
    act(() => noteLostReasons([ev(1, "run.started", {}), ev(2, "run.lost", { reason: NODE_FAIL })]));
    expect(result.current).toBe(NODE_FAIL);
    expect(lostReasonFor("r2")).toBeNull();
    // a later event without a reason does not erase it
    act(() => noteLostReasons([ev(3, "mirror.run_updated", { original_type: "run.lost" })]));
    expect(result.current).toBe(NODE_FAIL);
  });

  test("the app's event stream records the reason of a mirrored run.lost", () => {
    const sockets: StubSocket[] = [];
    const timers: (() => void)[] = [];
    const clock: Clock = {
      setTimeout: (fn) => timers.push(fn),
      clearTimeout: () => {},
    };
    const client = new QueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children);
    const { unmount } = renderHook(
      () =>
        useEventStream({
          url: "ws://127.0.0.1:1/api/v1/ws",
          clock,
          storage: null,
          createSocket: () => {
            const socket = new StubSocket();
            sockets.push(socket);
            return socket;
          },
        }),
      { wrapper },
    );
    const socket = sockets[0];
    if (!socket) throw new Error("the hook opened no socket");
    act(() => {
      socket.readyState = 1;
      socket.onopen?.(new Event("open"));
      socket.push({ type: "ready", last_sequence: 0 });
      socket.push({
        type: "event",
        event: ev(1, "mirror.run_updated", { original_type: "run.lost", status: "lost", reason: NODE_FAIL }, "r9"),
      });
      // the stream delivers live events in batches after FLUSH_MS: run the pending timers
      for (const fire of timers.splice(0)) fire();
    });
    expect(lostReasonFor("r9")).toBe(NODE_FAIL);
    unmount();
  });
});

/** The part of a WebSocket the stream uses; `push` delivers one server message. */
class StubSocket implements SocketLike {
  readyState = 0;
  onopen: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  send(): void {}
  close(): void {
    this.readyState = 3;
  }
  push(message: unknown): void {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(message) }));
  }
}
```

- [ ] **Step 6: Run them to verify they fail**

Run: `bun test test/api/lostReasons.test.ts`
Expected: FAIL with `Cannot find module '../../src/api/lostReasons'`.

- [ ] **Step 7: Keep the reasons of lost runs from the event stream**

Create `ui/src/api/lostReasons.ts`:

```ts
/**
 * Why runs were lost, read from the event stream (spec 5.6, 8A.8).
 *
 * The env server writes the cause of a lost run into its `run.lost` event
 * (`payload.reason`); the run detail has no field for it. A hub run's own `run.lost`
 * carries it; a remote run's arrives as `mirror.run_updated` with
 * `original_type: "run.lost"` and the same `reason`. `useEventStream` passes every batch to
 * `noteLostReasons`; the run page reads one run's reason with `useLostReason`. A tab that
 * resumed after the event never sees it, so callers fall back to neutral words.
 */
import { useSyncExternalStore } from "react";

import type { HxEvent } from "./models";

const reasons = new Map<string, string>();
const listeners = new Set<() => void>();

function changed(): void {
  for (const listener of listeners) listener();
}

/**
 * The reason a `run.lost` event (or a `mirror.run_updated` of one) gives, trimmed; null
 * for any other event, a missing or blank reason, or an event without a run id. For
 * `{type: "run.lost", payload: {reason: "SLURM ended job 7 with NODE_FAIL on n2; no exit record"}}`
 * it is that text.
 */
export function lostReasonOf(event: HxEvent): string | null {
  const payload = event.payload ?? {};
  const lost =
    event.type === "run.lost" || (event.type === "mirror.run_updated" && payload.original_type === "run.lost");
  if (!lost || event.run_id === null) return null;
  const reason = typeof payload.reason === "string" ? payload.reason.trim() : "";
  return reason === "" ? null : reason;
}

/** Remember the reason of every lost-run event in `events`; later reasonless events keep it. */
export function noteLostReasons(events: readonly HxEvent[]): void {
  let any = false;
  for (const event of events) {
    const reason = lostReasonOf(event);
    if (reason === null || event.run_id === null || reasons.get(event.run_id) === reason) continue;
    reasons.set(event.run_id, reason);
    any = true;
  }
  if (any) changed();
}

/** The reason seen for `runId`, or null. */
export function lostReasonFor(runId: string): string | null {
  return reasons.get(runId) ?? null;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** `lostReasonFor(runId)`, re-rendering when a reason for any run arrives. */
export function useLostReason(runId: string): string | null {
  return useSyncExternalStore(
    subscribe,
    () => lostReasonFor(runId),
    () => null,
  );
}

/** Forget every reason (tests). */
export function clearLostReasons(): void {
  reasons.clear();
  changed();
}
```

In `ui/src/api/events.ts`, replace

```ts
import { HOST_EVENT_INVALIDATES, REMOTE_RUN_INVALIDATES, RUN_EVENT_INVALIDATES } from "./queries";
```

with

```ts
import { noteLostReasons } from "./lostReasons";
import { HOST_EVENT_INVALIDATES, REMOTE_RUN_INVALIDATES, RUN_EVENT_INVALIDATES } from "./queries";
```

and replace

```ts
      onEvents: (events) => invalidateForEvents(client, events),
```

with

```ts
      onEvents: (events) => {
        noteLostReasons(events);
        invalidateForEvents(client, events);
      },
```

- [ ] **Step 8: Run the api tests, the full suite and the type checker**

Run: `bun test test/api && bun test && bun run typecheck`
Expected: `bun test test/api` ends with `77 pass`, `0 fail` (client and types 27, events 24 + 5 = 29, queries 18, lostReasons 3); the full `bun test` ends with `0 fail` (the run actions and Task page use `RUN_EVENT_INVALIDATES` by reference, so their tests are unchanged); `tsc --noEmit` prints no errors.

- [ ] **Step 9: Commit**

```bash
git add ui/src/api/queries.ts ui/src/api/events.ts ui/src/api/lostReasons.ts ui/test/api/events.test.ts ui/test/api/queries.test.tsx ui/test/api/lostReasons.test.ts
git commit -m "feat(ui): live invalidation for mirror and host events; lost-run reasons"
```

---

## Group 2: Hosts panel on the Overview (Tasks 5–7)

The Overview "Hosts" panel is panel a: one row per host with state, hx version (a mismatch marked `≠`), GPU cells (agent run, human run, free, not hx; a stale host's last cells greyed), SLURM running/pending, queue, $/GPU-h and cost today. With hosts, the headline and metaline read `12 running, 11 waiting. dgx stale 4m` / `1 GPU free  $332 today  hub hx 0.5.0  4 hosts`. The existing panels stay below it and move down one letter (contract 4): a Hosts, b Runs by launcher, c Ideas, d Running, e Failures, f Projects. `HostsPanel.tsx` holds pure exported helpers and the presentational component with its own CSS (`HOSTS_CSS`, every selector under `.page .hosts` / `.page .hosts-key`); `Overview.tsx` reads `useHosts()` and the hub descriptor (`api.environment()`) and passes rows, `summary.running`, the hub version and a ticking `now`.

Backend gaps, handled client-side (not in the contract):

- Stale count: the overview has no stale field (stale is derived on the hub, never stored). The headline computes stale hosts and their age from `HostRow.state` (`state === "stale"`, `now − since`).
- Running / waiting come from `counts.running` and `counts.queued`; when a key is missing, `hostsHeadline` falls back to the hosts (distinct `run_id`s on GPUs + `slurm.running`; `queue` + `slurm.pending`).
- `$/GPU-h`: `HostRow.usd_per_gpu_hour` (contract section 2); `·` when the host has no rate.
- Not drawn (not in the contract): SLURM "oldest pending" and "fair-share", the bootstrap step bar, the user name on not-hx GPUs. A host that is not connected yet shows `HostState.message` (for example `3/5 uv, hx 0.5.0`); foreign GPUs show `not hx`.
- The hub's own row: the backend's `host_rows` always lists it first (`{name: "local", kind: "local"}`). The panel draws it with the `hub` chip, but the Overview's switch to the hosts headline, and the metaline host count, use only the other rows (`remoteRows`). A user with no remote hosts keeps the phase 1 headline (`SVM leads toy-test by 0.037, p = 0.15`).
- A stale host's cells: the hub sends `gpus: []` and `queue: 0` for every host that is not connected. `useHosts` keeps the last connected GPUs and queue of a stale host (`keepLastKnown`, Task 3), so the panel can grey them with `as of HH:MM`. A page opened while the host is already stale has nothing to keep and shows `·`.
- Long outages (spec 5.6): a host stale for more than `stale_banner_hours` (the hub's `environments.yaml` setting, sent on every `GET /api/v1/hosts` row, default 24; controller ruling R1) gets a banner above the panels (`role="status"`), still not lost.

### Task 5: Host helpers (cells, totals, headline, formatters)

**Files:**
- Create: `ui/src/pages/components/HostsPanel.tsx`
- Create: `ui/test/pages/hostFixtures.ts`
- Test: `ui/test/pages/hostsPanel.test.tsx`

**Interfaces:**
- Consumes: `HostRow`, `GpuInfo`, `RunRecord` (types, Task 1 / phase 1b); `firstClause`, `fmtClock`, `isAgent`, `parseTime`, `shortId` from `./format` (existing).
- Produces (Tasks 6 and 7 use these exact names):
  - Rows are the Task 1 `HostRow` (it carries `usd_per_gpu_hour` and `stale_banner_hours`); `ConnState` is the Task 1 model; Task 6 imports it, nothing redeclares it.
  - `fmtMoney(usd: number): string` (`$106`, `$1,235`, `$0.50`); `fmtAgeMs(ms: number): string` (`4m`); `shortGpuName(name: string): string`; `gpuSpec(gpus: GpuInfo[]): string` (`5×A100 80GB`).
  - `type CellKind = "agent" | "human" | "run" | "free" | "other"`; `interface GpuCell { kind; index; span; runId: string | null; utils: number[]; memUsedMb: number }`.
  - `gpuCells(gpus: GpuInfo[], runs: ReadonlyMap<string, RunRecord>): GpuCell[]`; `meanUtil(cell: GpuCell): number`; `gpuRange(cell: GpuCell): string`; `cellTitle(host: string, cell: GpuCell, run: RunRecord | undefined, asOf: string | null): string`; `gpuColumns(hosts: HostRow[]): number`.
  - `interface HostTotals { running; waiting; freeGpus; usdToday; stale: { name: string; age: string }[] }`; `hostTotals(hosts: HostRow[], now: number): HostTotals`; `hostsHeadline(counts: Record<string, number>, totals: HostTotals): string`; `hostsMetaline(totals: HostTotals, hubVersion: string | null, nHosts: number): string[]`; `useNow(intervalMs?: number): number`.
  - `LOCAL_HOST = "local"`; `remoteRows(rows)` (every row but the hub's own); `hostRowForRun(record: Pick<RunRecord, "environment_id">, hosts: readonly HostRow[] | undefined): HostRow | null` (match by `state.environment_id`, never `executor.host`; Tasks 14, 23 and 27 use it); `DEFAULT_STALE_BANNER_HOURS = 24`; `staleBannerHours(hosts: readonly HostRow[]): number` (the first row's positive `stale_banner_hours`, else 24); `longStale(hosts, now, hours = DEFAULT_STALE_BANNER_HOURS): { name: string; age: string }[]` (Task 7's banner).
  - Test fixtures `ui/test/pages/hostFixtures.ts`: `NOW`, `RUN_AGENT`, `RUN_HUMAN`, `RUN_STALE`, `gpu(index, over?)`, `makeHosts(now?)` (the rows the panel draws, after `keepLastKnown`), `localRow(over?)`, `asSent(rows)` (the same rows as the hub sends them), `makeHostRuns()`.

- [ ] **Step 1: Check the API types and hook exist**

Run: `cd ui && grep -nE "interface (HostRow|GpuInfo|HostState)" src/api/models.ts && grep -n "useHosts" src/api/queries.ts`
Expected: three `interface` lines and at least one `useHosts` line. If any is missing, Tasks 1-4 are not done: stop and finish them first.

- [ ] **Step 2: Write the fixtures**

Create `ui/test/pages/hostFixtures.ts`:

```ts
/** Hosts fixtures for the Hosts panel and Overview tests (mockup `shot-overview-*`). */
import type { GpuInfo, HostRow, RunRecord } from "../../src/pages/components/types";
import { makeRecord } from "./fixtures";

/** 2026-10-03 14:32 UTC, the mockup's "now". */
export const NOW = Date.parse("2026-10-03T14:32:00Z");
export const RUN_AGENT = "20261003-140102-uspto-6b0e";
export const RUN_HUMAN = "20261003-131500-uspto-52c9";
/** On the stale host; not in the overview's running list. */
export const RUN_STALE = "20261003-120000-uspto-8e41";

const A100 = "NVIDIA A100-SXM4-80GB";
const H100 = "NVIDIA H100 80GB HBM3";

export function gpu(index: number, over: Partial<GpuInfo> = {}): GpuInfo {
  return {
    index,
    name: A100,
    util: 0,
    mem_used_mb: 0,
    mem_total_mb: 81920,
    external: false,
    run_id: null,
    ...over,
  };
}

function state(
  name: string,
  kind: HostRow["kind"],
  conn: HostRow["state"]["state"],
  since: string,
  over: Partial<HostRow["state"]> = {},
): HostRow["state"] {
  return {
    name,
    kind,
    state: conn,
    since,
    message: "",
    environment_id: `env-${name}`,
    hx_version: "0.5.0",
    last_sequence: 0,
    local_port: null,
    ...over,
  };
}

/** The hub's own row: `GET /api/v1/hosts` always lists it first. */
export function localRow(over: Partial<HostRow> = {}): HostRow {
  return {
    name: "local",
    kind: "local",
    state: state("local", "local", "connected", "2026-10-03T08:00:00Z"),
    gpus: [],
    queue: 0,
    slurm: null,
    cost_today_usd: 0,
    projects: ["rxn-forward"],
    ...over,
  };
}

/** `rows` as the hub sends them: a host that is not connected has no GPUs and queue 0. */
export function asSent(rows: HostRow[]): HostRow[] {
  return rows.map((r) => (r.state.state === "connected" ? r : { ...r, gpus: [], queue: 0 }));
}

/**
 * Four hosts, as the panel draws them (`useHosts` has kept dgx's last known cells): gpu1
 * (connected, hx 0.4.1, agent run on GPUs 0-1, not-hx GPU 2, human run on GPU 3, GPU 4
 * free, queue 3), dgx (stale since `now` − 4 min, last known: one run, one free GPU, queue
 * 2), mccleary (SLURM, 4 running, 6 pending), gpu2 (bootstrapping, no GPUs yet).
 */
export function makeHosts(now: number = NOW): HostRow[] {
  const staleSince = new Date(now - 4 * 60_000 - 5_000).toISOString();
  return [
    {
      name: "gpu1",
      kind: "ssh",
      state: state("gpu1", "ssh", "connected", "2026-10-03T09:00:00Z", { hx_version: "0.4.1" }),
      gpus: [
        gpu(0, { run_id: RUN_AGENT, util: 92, mem_used_mb: 30720 }),
        gpu(1, { run_id: RUN_AGENT, util: 91, mem_used_mb: 30720 }),
        gpu(2, { external: true, util: 63, mem_used_mb: 40960 }),
        gpu(3, { run_id: RUN_HUMAN, util: 77, mem_used_mb: 20480 }),
        gpu(4),
      ],
      queue: 3,
      slurm: null,
      cost_today_usd: 106.2,
      projects: ["rxn-forward"],
      usd_per_gpu_hour: 1.1,
    },
    {
      name: "dgx",
      kind: "ssh",
      state: state("dgx", "ssh", "stale", staleSince),
      gpus: [gpu(0, { name: H100, run_id: RUN_STALE, util: 95 }), gpu(1, { name: H100 })],
      queue: 2,
      slurm: null,
      cost_today_usd: 206,
      projects: [],
      usd_per_gpu_hour: 2.9,
    },
    {
      name: "mccleary",
      kind: "slurm",
      state: state("mccleary", "slurm", "connected", "2026-10-03T08:00:00Z"),
      gpus: [],
      queue: 0,
      slurm: { pending: 6, running: 4 },
      cost_today_usd: 19.4,
      projects: [],
      usd_per_gpu_hour: 0.5,
    },
    {
      name: "gpu2",
      kind: "ssh",
      state: state("gpu2", "ssh", "bootstrapping", "2026-10-03T14:31:00Z", {
        hx_version: null,
        environment_id: null,
        message: "3/5 uv, hx 0.5.0",
      }),
      gpus: [],
      queue: 0,
      slurm: null,
      cost_today_usd: 0,
      projects: [],
    },
  ];
}

/** The active runs the overview lists for the cells on gpu1. */
export function makeHostRuns(): RunRecord[] {
  return [
    makeRecord({ run_id: RUN_AGENT, created_by: "agent:tuner", hypothesis: "lr 3e-4, beam 10", status: "running" }),
    makeRecord({ run_id: RUN_HUMAN, created_by: "human:shreyas", hypothesis: "+aug long, 40k steps", status: "running" }),
  ];
}
```

- [ ] **Step 3: Write the failing test**

Create `ui/test/pages/hostsPanel.test.tsx`:

```tsx
import { describe, expect, test } from "bun:test";
import { renderHook, waitFor } from "@testing-library/react";
import {
  DEFAULT_STALE_BANNER_HOURS,
  cellTitle,
  fmtAgeMs,
  fmtMoney,
  gpuCells,
  gpuColumns,
  gpuSpec,
  hostRowForRun,
  hostTotals,
  hostsHeadline,
  hostsMetaline,
  longStale,
  meanUtil,
  remoteRows,
  shortGpuName,
  staleBannerHours,
  useNow,
} from "../../src/pages/components/HostsPanel";
import type { HostRow } from "../../src/pages/components/types";
import { makeRecord } from "./fixtures";
import { NOW, RUN_AGENT, RUN_HUMAN, RUN_STALE, gpu, localRow, makeHostRuns, makeHosts } from "./hostFixtures";

const runs = new Map(makeHostRuns().map((r) => [r.run_id, r]));
const [gpu1, dgx, mccleary] = makeHosts() as [HostRow, HostRow, HostRow, HostRow];

describe("formatting", () => {
  test("fmtMoney: whole dollars with commas from $10, cents below", () => {
    expect([fmtMoney(106.2), fmtMoney(1234.5), fmtMoney(0.5), fmtMoney(9.999), fmtMoney(0)]).toEqual([
      "$106",
      "$1,235",
      "$0.50",
      "$10.00",
      "$0.00",
    ]);
  });

  test("fmtAgeMs picks the largest whole unit and clamps clock skew to 0s", () => {
    expect([fmtAgeMs(59_000), fmtAgeMs(240_000), fmtAgeMs(7_200_000), fmtAgeMs(172_800_000), fmtAgeMs(-5_000)]).toEqual([
      "59s",
      "4m",
      "2h",
      "2d",
      "0s",
    ]);
  });

  test("shortGpuName drops vendor, form factor and memory tokens", () => {
    expect(shortGpuName("NVIDIA A100-SXM4-80GB")).toBe("A100");
    expect(shortGpuName("NVIDIA H100 80GB HBM3")).toBe("H100");
    expect(shortGpuName("NVIDIA RTX A6000")).toBe("RTX A6000");
    expect(shortGpuName("Tesla V100-SXM2-32GB")).toBe("V100");
    expect(shortGpuName("Fake GPU")).toBe("Fake GPU");
  });

  test("gpuSpec: count × model and size, or a count when GPUs differ", () => {
    expect(gpuSpec(gpu1.gpus)).toBe("5×A100 80GB");
    expect(gpuSpec(dgx.gpus)).toBe("2×H100 80GB");
    expect(gpuSpec([gpu(0), gpu(1, { name: "NVIDIA H100 80GB HBM3" })])).toBe("2 GPUs");
    expect(gpuSpec([])).toBe("");
  });
});

describe("gpuCells", () => {
  test("one run on adjacent GPUs is one wide cell; launchers decide agent or human", () => {
    const cells = gpuCells(gpu1.gpus, runs);
    expect(cells.map((c) => [c.kind, c.index, c.span, c.runId])).toEqual([
      ["agent", 0, 2, RUN_AGENT],
      ["other", 2, 1, null],
      ["human", 3, 1, RUN_HUMAN],
      ["free", 4, 1, null],
    ]);
    expect(cells[0]?.utils).toEqual([92, 91]);
    expect(cells[0]?.memUsedMb).toBe(61440);
    expect(meanUtil(cells[0]!)).toBe(92);
  });

  test("a run the overview does not list is kind 'run'; input order does not matter", () => {
    const cells = gpuCells([...dgx.gpus].reverse(), runs);
    expect(cells.map((c) => [c.kind, c.index, c.runId])).toEqual([
      ["run", 0, RUN_STALE],
      ["free", 1, null],
    ]);
  });

  test("the same run on GPUs that are not adjacent stays two cells", () => {
    const cells = gpuCells([gpu(0, { run_id: RUN_AGENT }), gpu(2, { run_id: RUN_AGENT })], runs);
    expect(cells.map((c) => [c.index, c.span])).toEqual([
      [0, 1],
      [2, 1],
    ]);
  });

  test("an hx run wins over the external flag", () => {
    const [cell] = gpuCells([gpu(0, { run_id: RUN_HUMAN, external: true })], runs);
    expect(cell?.kind).toBe("human");
  });

  test("cellTitle lists where, run, label, launcher, per-GPU use, and staleness", () => {
    const [agent, other, , free] = gpuCells(gpu1.gpus, runs);
    expect(cellTitle("gpu1", agent!, runs.get(RUN_AGENT), null)).toBe(
      "gpu1 GPU 0–1: 6b0e\nlr 3e-4\nagent:tuner\nGPU 0 92%, GPU 1 91%, 60.0 GB",
    );
    expect(cellTitle("gpu1", other!, undefined, null)).toBe("gpu1 GPU 2: not hx\n63%, 40.0 GB");
    expect(cellTitle("gpu1", free!, undefined, null)).toBe("gpu1 GPU 4: free");
    const [stale] = gpuCells(dgx.gpus, runs);
    expect(cellTitle("dgx", stale!, undefined, "14:27")).toBe("dgx GPU 0: 8e41\nGPU 0 95%, 0.0 GB\nas of 14:27");
  });

  test("gpuColumns is 8 unless a host has a higher GPU index", () => {
    expect(gpuColumns(makeHosts())).toBe(8);
    expect(gpuColumns([{ ...mccleary, gpus: [] }])).toBe(8);
    expect(gpuColumns([{ ...gpu1, gpus: [gpu(11)] }])).toBe(12);
  });
});

describe("totals and headline", () => {
  const totals = hostTotals(makeHosts(), NOW);

  test("hostTotals counts runs, waiting, free GPUs on connected hosts, cost and stale hosts", () => {
    // runs: 6b0e, 52c9, 8e41 (3 distinct) + 4 SLURM; waiting: 3 + 2 + 6 pending
    const { usdToday, ...rest } = totals;
    expect(rest).toEqual({ running: 7, waiting: 11, freeGpus: 1, stale: [{ name: "dgx", age: "4m" }] });
    expect(usdToday).toBeCloseTo(331.6, 9);
  });

  test("hostsHeadline prefers backend counts and falls back to host totals", () => {
    expect(hostsHeadline({ running: 12, queued: 11 }, totals)).toBe("12 running, 11 waiting. dgx stale 4m");
    expect(hostsHeadline({ "runs today": 19 }, totals)).toBe("7 running, 11 waiting. dgx stale 4m");
    expect(hostsHeadline({ running: 2, queued: 0 }, { ...totals, stale: [] })).toBe("2 running.");
    expect(hostsHeadline({ running: 0, queued: 5 }, { ...totals, stale: [] })).toBe("5 waiting.");
    expect(hostsHeadline({ running: 0, queued: 0 }, { ...totals, stale: [] })).toBe("Idle.");
  });

  test("two stale hosts are listed in host order", () => {
    const hosts = makeHosts();
    const gpu2 = hosts[3]!;
    hosts[3] = { ...gpu2, state: { ...gpu2.state, state: "stale", since: "2026-10-03T12:32:00Z" } };
    expect(hostsHeadline({ running: 1, queued: 0 }, hostTotals(hosts, NOW))).toBe(
      "1 running. dgx stale 4m, gpu2 stale 2h",
    );
  });

  test("hostsMetaline: free GPUs, cost today, hub version, host count", () => {
    expect(hostsMetaline(totals, "0.5.0", 4)).toEqual(["1 GPU free", "$332 today", "hub hx 0.5.0", "4 hosts"]);
    expect(hostsMetaline({ ...totals, freeGpus: 0, usdToday: 0 }, null, 1)).toEqual([
      "0 GPUs free",
      "$0.00 today",
      "1 host",
    ]);
  });
});

describe("hosts and runs", () => {
  test("hostRowForRun matches the run's environment, never executor.host", () => {
    const hosts = [localRow(), ...makeHosts()];
    const base = makeRecord();
    // the backend writes the box's own hostname into executor.host, not the hub's host name
    const run = { ...base, environment_id: "env-dgx", host: "dgx-h100-07", executor: { ...base.executor, host: "dgx-h100-07" } };
    expect(hostRowForRun(run, hosts)?.name).toBe("dgx");
    expect(hostRowForRun({ ...run, environment_id: "env-local" }, hosts)?.name).toBe("local");
    expect(hostRowForRun({ ...run, environment_id: "env-elsewhere" }, hosts)).toBeNull();
    expect(hostRowForRun(run, undefined)).toBeNull();
    // an empty environment id never matches (gpu2 has never connected and has none)
    expect(hostRowForRun({ ...run, environment_id: "" }, hosts)).toBeNull();
  });

  test("remoteRows drops the hub's own row", () => {
    expect(remoteRows([localRow(), ...makeHosts()]).map((h) => h.name)).toEqual(["gpu1", "dgx", "mccleary", "gpu2"]);
  });

  test("longStale lists the hosts stale for longer than the banner threshold", () => {
    expect(DEFAULT_STALE_BANNER_HOURS).toBe(24);
    expect(longStale(makeHosts(), NOW)).toEqual([]);
    const hosts = makeHosts();
    const dgx = hosts[1]!;
    // stale for 25 h: past the default 24 h, not past a threshold of 48 h
    const since = new Date(NOW - 25 * 3_600_000).toISOString();
    hosts[1] = { ...dgx, state: { ...dgx.state, since } };
    expect(longStale(hosts, NOW)).toEqual([{ name: "dgx", age: "1d" }]);
    expect(longStale(hosts, NOW, 48)).toEqual([]);
    // stale for 4 min: past a threshold of 0.05 h (3 min)
    expect(longStale(makeHosts(), NOW, 0.05)).toEqual([{ name: "dgx", age: "4m" }]);
  });

  test("staleBannerHours reads the hub's setting from the hosts list, else 24", () => {
    expect(staleBannerHours([])).toBe(24);
    expect(staleBannerHours(makeHosts())).toBe(24);
    expect(staleBannerHours([localRow({ stale_banner_hours: 6 }), ...makeHosts()])).toBe(6);
    // a missing, zero, negative or non-finite value keeps the default
    for (const bad of [0, -1, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(staleBannerHours([localRow({ stale_banner_hours: bad })])).toBe(24);
    }
  });
});

test("useNow re-renders with a later time every interval", async () => {
  const { result, unmount } = renderHook(() => useNow(20));
  const first = result.current;
  expect(Math.abs(first - Date.now())).toBeLessThan(1000);
  await waitFor(() => expect(result.current).toBeGreaterThan(first));
  unmount();
});
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `cd ui && bun test test/pages/hostsPanel.test.tsx`
Expected: FAIL with `Cannot find module '../../src/pages/components/HostsPanel'`.

- [ ] **Step 5: Write the helpers**

Create `ui/src/pages/components/HostsPanel.tsx`:

```tsx
/**
 * Overview panel "Hosts" (spec 8A.7, 8A.8; mockup `docs/mockups/phase2/shot-overview-*`).
 *
 * One row per host: name and kind, connection state with the host's hx version (a `≠`
 * marks a version that differs from the hub's), one cell per GPU (agent run, human run,
 * free, not hx; a run on adjacent GPUs is one wide cell), SLURM running/pending counts,
 * queue length, $/GPU-h and cost today. A stale host keeps its last known cells, greyed.
 *
 * The pure helpers below (`gpuCells`, `hostTotals`, `hostsHeadline`, ...) are exported
 * for tests and for the Overview headline and metaline.
 */
import { useEffect, useState } from "react";
import { firstClause, fmtClock, isAgent, parseTime, shortId } from "./format";
import type { GpuInfo, HostRow, RunRecord } from "./types";

// formatting ---------------------------------------------------------------------------------

/** Dollars as in the mockup: whole dollars with commas from $10 (`$1,235`), else cents (`$0.50`). */
export function fmtMoney(usd: number): string {
  return usd >= 10 ? `$${Math.round(usd).toLocaleString("en-US")}` : `$${usd.toFixed(2)}`;
}

/** A short age: `59s`, `4m`, `2h`, `3d`; negative ages (clock skew) read `0s`. */
export function fmtAgeMs(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

const GPU_NOISE = /^(\d+GB|SXM\d*|PCIE|HBM\d*E?|NVL)$/i;

/** `NVIDIA A100-SXM4-80GB` → `A100`; `NVIDIA RTX A6000` → `RTX A6000`. */
export function shortGpuName(name: string): string {
  const parts = name
    .replace(/^(NVIDIA|Tesla)\s+/i, "")
    .split(/[-\s]+/)
    .filter((p) => p !== "" && !GPU_NOISE.test(p));
  return parts.length > 0 ? parts.join(" ") : name;
}

/** `5×A100 80GB` when every GPU is the same model and size, `3 GPUs` otherwise, `""` for none. */
export function gpuSpec(gpus: GpuInfo[]): string {
  if (gpus.length === 0) return "";
  const kinds = new Set(gpus.map((g) => `${shortGpuName(g.name)} ${Math.round(g.mem_total_mb / 1024)}GB`));
  const [only] = [...kinds];
  return kinds.size === 1 && only ? `${gpus.length}×${only}` : `${gpus.length} GPUs`;
}

// GPU cells ----------------------------------------------------------------------------------

/** What a GPU cell shows: an hx run by an agent, by a human, by an unknown launcher; free; not hx. */
export type CellKind = "agent" | "human" | "run" | "free" | "other";

export interface GpuCell {
  kind: CellKind;
  /** First GPU index the cell covers. */
  index: number;
  /** Adjacent GPUs covered (one hx run on several GPUs is one cell). */
  span: number;
  /** The hx run on these GPUs; null for free and not-hx cells. */
  runId: string | null;
  /** Utilisation in percent of each covered GPU, in index order. */
  utils: number[];
  /** Memory used on the covered GPUs, summed. */
  memUsedMb: number;
}

function cellKind(gpu: GpuInfo, runs: ReadonlyMap<string, RunRecord>): CellKind {
  const runId = gpu.run_id ?? null;
  if (runId === null) return gpu.external ? "other" : "free";
  const run = runs.get(runId);
  if (!run) return "run";
  return isAgent(run.created_by) ? "agent" : "human";
}

/**
 * The cells of one host, in GPU index order.
 *
 * A run on adjacent GPUs becomes one cell spanning them (mockup `6b0e 92% ×2`). An hx run
 * wins over `external` (the env server clears it on hx GPUs, but never trust that here).
 */
export function gpuCells(gpus: GpuInfo[], runs: ReadonlyMap<string, RunRecord>): GpuCell[] {
  const out: GpuCell[] = [];
  for (const gpu of [...gpus].sort((a, b) => a.index - b.index)) {
    const runId = gpu.run_id ?? null;
    const last = out[out.length - 1];
    if (runId !== null && last && last.runId === runId && last.index + last.span === gpu.index) {
      last.span += 1;
      last.utils.push(gpu.util);
      last.memUsedMb += gpu.mem_used_mb;
      continue;
    }
    out.push({
      kind: cellKind(gpu, runs),
      index: gpu.index,
      span: 1,
      runId,
      utils: [gpu.util],
      memUsedMb: gpu.mem_used_mb,
    });
  }
  return out;
}

/** Mean utilisation of a cell, rounded to a whole percent. */
export function meanUtil(cell: GpuCell): number {
  return Math.round(cell.utils.reduce((a, b) => a + b, 0) / cell.utils.length);
}

/** `GPU 3` or `GPU 0–1`. */
export function gpuRange(cell: GpuCell): string {
  return cell.span === 1 ? `GPU ${cell.index}` : `GPU ${cell.index}–${cell.index + cell.span - 1}`;
}

const gb = (mb: number): string => `${(mb / 1024).toFixed(1)} GB`;

/**
 * Tooltip of a cell, one fact per line: where, which run, its label and launcher,
 * per-GPU utilisation and memory, and `as of HH:MM` on a stale host.
 */
export function cellTitle(host: string, cell: GpuCell, run: RunRecord | undefined, asOf: string | null): string {
  const where = `${host} ${gpuRange(cell)}`;
  if (cell.kind === "free") return `${where}: free`;
  const usage = `${gb(cell.memUsedMb)}`;
  const lines =
    cell.kind === "other"
      ? [`${where}: not hx`, `${meanUtil(cell)}%, ${usage}`]
      : [
          `${where}: ${shortId(cell.runId ?? "")}`,
          ...(run ? [firstClause(run.hypothesis, `run ${shortId(run.run_id)}`), run.created_by] : []),
          `${cell.utils.map((u, k) => `GPU ${cell.index + k} ${Math.round(u)}%`).join(", ")}, ${usage}`,
        ];
  if (asOf !== null) lines.push(`as of ${asOf}`);
  return lines.join("\n");
}

/** GPU columns of the panel: 8, or more when a host has a higher GPU index. */
export function gpuColumns(hosts: HostRow[]): number {
  return Math.max(8, ...hosts.flatMap((h) => h.gpus.map((g) => g.index + 1)));
}

// hosts and runs -----------------------------------------------------------------------------

/** Name of the hub's own row in `GET /api/v1/hosts` (reserved in `environments.yaml`). */
export const LOCAL_HOST = "local";

/** Every row but the hub's own (`host_rows` always lists `local` first). */
export function remoteRows<R extends HostRow>(rows: readonly R[]): R[] {
  return rows.filter((r) => r.name !== LOCAL_HOST);
}

/**
 * The hosts row that serves a run: the row whose `state.environment_id` is the run's
 * `environment_id`, the match the backend's `host_for_environment` makes. Null when no row
 * does (the list is not loaded, or no host serves that environment). Never `executor.host`:
 * the backend writes the env server's own hostname there (`socket.gethostname()`), which is
 * not the hub's name for the host, and it sets it on hub runs too.
 */
export function hostRowForRun<R extends HostRow>(
  record: Pick<RunRecord, "environment_id">,
  hosts: readonly R[] | undefined,
): R | null {
  const env = record.environment_id;
  if (!env || hosts === undefined) return null;
  return hosts.find((h) => h.state.environment_id === env) ?? null;
}

/** Hours a host may stay unreachable before the Overview banner when the hub sends none. */
export const DEFAULT_STALE_BANNER_HOURS = 24;

/**
 * The banner threshold in hours: `stale_banner_hours` of the hosts list (the hub's
 * `environments.yaml` setting, the same on every row; controller ruling R1), else 24.
 */
export function staleBannerHours(hosts: readonly HostRow[]): number {
  const hours = hosts.find((h) => h.stale_banner_hours !== undefined)?.stale_banner_hours;
  return typeof hours === "number" && Number.isFinite(hours) && hours > 0 ? hours : DEFAULT_STALE_BANNER_HOURS;
}

/**
 * Hosts stale for more than `hours` at `now`, in host order, with how long (spec 5.6: a
 * banner, and the runs stay stale, never lost).
 */
export function longStale(
  hosts: readonly HostRow[],
  now: number,
  hours: number = DEFAULT_STALE_BANNER_HOURS,
): { name: string; age: string }[] {
  const limit = hours * 3_600_000;
  return hosts
    .filter((h) => h.state.state === "stale" && now - parseTime(h.state.since) > limit)
    .map((h) => ({ name: h.name, age: fmtAgeMs(now - parseTime(h.state.since)) }));
}

// totals, headline, metaline -----------------------------------------------------------------

export interface HostTotals {
  /** hx runs on host GPUs (distinct run ids) plus SLURM running jobs. */
  running: number;
  /** Host queue lengths plus SLURM pending jobs. */
  waiting: number;
  /** GPUs on connected hosts with no hx run and no other process. */
  freeGpus: number;
  /** Sum of `cost_today_usd`. */
  usdToday: number;
  /** Stale hosts with how long they have been stale (`4m`). */
  stale: { name: string; age: string }[];
}

/** Totals over all hosts at time `now` (ms since the epoch). */
export function hostTotals(hosts: HostRow[], now: number): HostTotals {
  const runIds = new Set<string>();
  let slurmRunning = 0;
  let waiting = 0;
  let freeGpus = 0;
  let usdToday = 0;
  const stale: HostTotals["stale"] = [];
  for (const h of hosts) {
    for (const g of h.gpus) {
      if (g.run_id) runIds.add(g.run_id);
      else if (!g.external && h.state.state === "connected") freeGpus += 1;
    }
    slurmRunning += h.slurm?.running ?? 0;
    waiting += h.queue + (h.slurm?.pending ?? 0);
    usdToday += h.cost_today_usd;
    if (h.state.state === "stale") stale.push({ name: h.name, age: fmtAgeMs(now - parseTime(h.state.since)) });
  }
  return { running: runIds.size + slurmRunning, waiting, freeGpus, usdToday, stale };
}

function count(counts: Record<string, number>, key: string): number | undefined {
  const v = (counts as Partial<Record<string, number>>)[key];
  return typeof v === "number" ? v : undefined;
}

/**
 * The Overview headline with hosts: `12 running, 11 waiting. dgx stale 4m`.
 *
 * Running and waiting come from the backend overview (`counts.running`,
 * `counts.queued`, which include mirrored remote runs); when a count is missing it is
 * computed from the hosts. Staleness is derived on the hub and never stored, so it always
 * comes from the hosts.
 */
export function hostsHeadline(counts: Record<string, number>, totals: HostTotals): string {
  const running = count(counts, "running") ?? totals.running;
  const waiting = count(counts, "queued") ?? totals.waiting;
  const parts = [running > 0 ? `${running} running` : "", waiting > 0 ? `${waiting} waiting` : ""];
  const said = parts.filter((p) => p !== "");
  const head = said.length > 0 ? `${said.join(", ")}.` : "Idle.";
  const stale = totals.stale.map((s) => `${s.name} stale ${s.age}`).join(", ");
  return stale ? `${head} ${stale}` : head;
}

const plural = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`;

/** Metaline under the headline: `1 GPU free`, `$332 today`, `hub hx 0.5.0`, `4 hosts`. */
export function hostsMetaline(totals: HostTotals, hubVersion: string | null, nHosts: number): string[] {
  return [
    `${plural(totals.freeGpus, "GPU", "GPUs")} free`,
    `${fmtMoney(totals.usdToday)} today`,
    ...(hubVersion ? [`hub hx ${hubVersion}`] : []),
    plural(nHosts, "host", "hosts"),
  ];
}

/** The current time, refreshed every `intervalMs` (stale ages tick without a refetch). */
export function useNow(intervalMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}
```

- [ ] **Step 6: Run the tests and the typecheck**

Run: `cd ui && bun test test/pages/hostsPanel.test.tsx && bun run typecheck`
Expected: `19 pass`, `0 fail`; `tsc --noEmit` prints no errors.

- [ ] **Step 7: Commit**

```bash
git add ui/src/pages/components/HostsPanel.tsx ui/test/pages/hostFixtures.ts ui/test/pages/hostsPanel.test.tsx
git commit -m "feat(ui): host cell, totals and headline helpers for the hosts panel"
```

---

### Task 6: `HostsPanel` component

**Files:**
- Modify: `ui/src/pages/components/HostsPanel.tsx` (imports at the top; append the component section at the end)
- Test: `ui/test/pages/hostsPanelView.test.tsx`

**Interfaces:**
- Consumes: everything Task 5 produces; `ConnState` from `./types` (Task 1); `AppLink`, `hrefs` from `./links` (existing; `hrefs.run(id)` is `/r/<id>`).
- Produces (Task 7 uses it):
  - `HOSTS_CSS: string`; `StateGlyph({ state }: { state: ConnState })`.
  - `interface HostsPanelProps { hosts: HostRow[]; runs: RunRecord[]; hubVersion: string | null; now: number }`.
  - `HostsPanel(props: HostsPanelProps)`: `none` for an empty list; otherwise a header row, one `role="group"` row per host with `aria-label` = host name (class `hrow`, plus `stale` when stale), and the key (`aria-label="Key"`).
  - Row columns, in order: name + kind chip + GPU spec; state glyph + word (`stale 4m` in bold) + `hx X.Y.Z` (`≠` when it differs from `hubVersion`, title `hub runs hx 0.5.0. Update: hx hosts upgrade <host>`) + `as of HH:MM` when stale; cells (`gc busy agent|human|run` links to the run, `gc other` "not hx", `gc free`) or SLURM counts (`.slurm`) or a message (`.msg`); queue; $/GPU-h; today.

- [ ] **Step 1: Write the failing test**

Create `ui/test/pages/hostsPanelView.test.tsx`:

```tsx
import { expect, test } from "bun:test";
import { render, screen, within } from "@testing-library/react";
import { HOSTS_CSS, HostsPanel } from "../../src/pages/components/HostsPanel";
import { NOW, RUN_AGENT, gpu, makeHostRuns, makeHosts } from "./hostFixtures";

function renderPanel(hosts = makeHosts(), hubVersion: string | null = "0.5.0") {
  return render(<HostsPanel hosts={hosts} runs={makeHostRuns()} hubVersion={hubVersion} now={NOW} />);
}

test("one row per host, in API order, under a header with GPU indices 0-7", () => {
  const { container } = renderPanel();
  expect(screen.getAllByRole("group").map((g) => g.getAttribute("aria-label"))).toEqual([
    "gpu1",
    "dgx",
    "mccleary",
    "gpu2",
  ]);
  const idx = [...container.querySelectorAll(".hrow.head .gidx span")].map((s) => s.textContent);
  expect(idx).toEqual(["0", "1", "2", "3", "4", "5", "6", "7"]);
  expect(container.querySelector("style[data-hx='hosts']")?.textContent).toBe(HOSTS_CSS);
});

test("gpu1: agent, not-hx, human and free cells; version mismatch; queue, rate, cost", () => {
  const { container } = renderPanel();
  const row = within(screen.getByRole("group", { name: "gpu1" }));
  expect(row.getByText("ssh")).toBeTruthy();
  expect(row.getByText("5×A100 80GB")).toBeTruthy();
  expect(row.getByText("connected")).toBeTruthy();

  const [agent, human] = row.getAllByRole("link") as [HTMLElement, HTMLElement];
  expect(agent.getAttribute("href")).toBe(`/r/${RUN_AGENT}`);
  expect(agent.className).toBe("gc busy agent");
  expect(agent.style.gridColumn).toBe("1 / span 2");
  expect(agent.textContent).toBe("6b0e92% ×2");
  expect(agent.getAttribute("title")).toBe("gpu1 GPU 0–1: 6b0e\nlr 3e-4\nagent:tuner\nGPU 0 92%, GPU 1 91%, 60.0 GB");
  expect(human.className).toBe("gc busy human");
  expect(human.getAttribute("title")).toBe("gpu1 GPU 3: 52c9\n+aug long\nhuman:shreyas\nGPU 3 77%, 20.0 GB");

  const cells = [...container.querySelectorAll("[aria-label='gpu1'] .cells > *")];
  expect(cells.map((c) => c.className)).toEqual(["gc busy agent", "gc other", "gc busy human", "gc free"]);
  expect(cells[1]?.textContent).toBe("not hx63%");
  expect(cells[3]?.getAttribute("title")).toBe("gpu1 GPU 4: free");

  const ver = row.getByTitle("hub runs hx 0.5.0. Update: hx hosts upgrade gpu1");
  expect(ver.textContent).toBe("hx 0.4.1≠");
  const [queue, rate, today] = [...container.querySelectorAll("[aria-label='gpu1'] > .r")];
  expect([queue?.textContent, rate?.textContent, today?.textContent]).toEqual(["3", "$1.10", "$106"]);
});

test("dgx: stale for 4m, greyed last-known cells with 'as of' in tooltips", () => {
  renderPanel();
  const group = screen.getByRole("group", { name: "dgx" });
  expect(group.className).toBe("hrow stale");
  const row = within(group);
  expect(row.getByText("stale 4m").tagName).toBe("B");
  expect(row.getByText("hx 0.5.0").getAttribute("title")).toBe("hx 0.5.0");
  expect(group.querySelector(".hs .meta")?.textContent).toBe("hx 0.5.0  as of 14:27");
  const cell = row.getByRole("link");
  expect(cell.className).toBe("gc busy run");
  expect(cell.getAttribute("title")).toBe("dgx GPU 0: 8e41\nGPU 0 95%, 0.0 GB\nas of 14:27");
});

test("mccleary: SLURM running and pending counts instead of GPU cells", () => {
  renderPanel();
  const group = screen.getByRole("group", { name: "mccleary" });
  expect(group.querySelector(".cells")).toBeNull();
  expect(group.querySelector(".slurm")?.textContent).toBe("4running6pending");
  const [queue, rate, today] = [...group.querySelectorAll(":scope > .r")];
  expect([queue?.textContent, queue?.className, rate?.textContent, today?.textContent]).toEqual([
    "0",
    "r q z",
    "$0.50",
    "$19",
  ]);
});

test("gpu2: bootstrapping shows the step message, unknown version and no rate", () => {
  renderPanel();
  const group = screen.getByRole("group", { name: "gpu2" });
  const row = within(group);
  expect(row.getByText("bootstrapping")).toBeTruthy();
  expect(group.querySelector(".msg")?.textContent).toBe("3/5 uv, hx 0.5.0");
  expect(row.getByText("hx ·")).toBeTruthy();
  const [, rate, today] = [...group.querySelectorAll(":scope > .r")];
  expect([rate?.textContent, today?.textContent]).toEqual(["·", "·"]);
});

test("no hub version: no mismatch mark", () => {
  renderPanel(makeHosts(), null);
  const row = screen.getByRole("group", { name: "gpu1" });
  expect(row.querySelector(".ne")).toBeNull();
  expect(row.querySelector(".ver")?.textContent).toBe("hx 0.4.1");
});

test("a 12-GPU host widens every row to 12 columns", () => {
  const hosts = makeHosts();
  hosts[0] = { ...hosts[0]!, gpus: [gpu(0), gpu(11, { run_id: RUN_AGENT, util: 50 })] };
  const { container } = renderPanel(hosts);
  expect(container.querySelectorAll(".hrow.head .gidx span")).toHaveLength(12);
  const cells = container.querySelector("[aria-label='gpu1'] .cells") as HTMLElement;
  expect(cells.style.gridTemplateColumns).toBe("repeat(12, minmax(0, 1fr))");
  expect((cells.lastElementChild as HTMLElement).style.gridColumn).toBe("12 / span 1");
});

test("a connected host with no GPUs says so; an empty list says none", () => {
  const hosts = makeHosts();
  hosts[0] = { ...hosts[0]!, gpus: [] };
  renderPanel(hosts);
  expect(screen.getByRole("group", { name: "gpu1" }).querySelector(".msg")?.textContent).toBe("no GPUs");
  const { container } = render(<HostsPanel hosts={[]} runs={[]} hubVersion="0.5.0" now={NOW} />);
  expect(container.textContent).toBe("none");
});

test("the key names every cell kind and mark", () => {
  renderPanel();
  const key = screen.getByLabelText("Key");
  expect(key.textContent).toBe("agent runhuman runfreenot hxstalehx≠version mismatch");
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ui && bun test test/pages/hostsPanelView.test.tsx`
Expected: FAIL with `SyntaxError: Export named 'HOSTS_CSS' not found in module '.../src/pages/components/HostsPanel.tsx'`.

- [ ] **Step 3: Update the imports**

In `ui/src/pages/components/HostsPanel.tsx` replace

```tsx
import { useEffect, useState } from "react";
import { firstClause, fmtClock, isAgent, parseTime, shortId } from "./format";
import type { GpuInfo, HostRow, RunRecord } from "./types";
```

with

```tsx
import { type CSSProperties, createElement, useEffect, useState } from "react";
import { firstClause, fmtClock, isAgent, parseTime, shortId } from "./format";
import { AppLink, hrefs } from "./links";
import type { ConnState, GpuInfo, HostRow, RunRecord } from "./types";
```

- [ ] **Step 4: Append the component section**

Append to the end of `ui/src/pages/components/HostsPanel.tsx` (after `useNow`):

```tsx
// component ----------------------------------------------------------------------------------

/** Panel CSS, scoped under `.page .hosts`, `.page .hosts-key` and `.page .hosts-banner` (values from the mockup). */
export const HOSTS_CSS = `
.page .hosts { font-variant-numeric: tabular-nums; }
.page .hosts .hrow { display: grid; grid-template-columns: 168px 132px minmax(0, 1fr) 52px 70px 70px; gap: 0 18px; align-items: center; padding: 14px 0; border-top: 1px solid var(--rule-2); }
.page .hosts .hrow.head { padding: 0 0 8px; border-top: 0; border-bottom: 1px solid var(--rule); font-size: 12.5px; color: var(--ink-3); align-items: end; }
.page .hosts .hrow.head + .hrow { border-top: 0; }
.page .hosts .r { text-align: right; }
.page .hosts .hn b { font-weight: 600; font-size: 15px; margin-right: 8px; }
.page .hosts .kind { font-size: 11.5px; color: var(--ink-2); border: 1px solid var(--rule); border-radius: 9px; padding: 0 7px; }
.page .hosts .meta { font-size: 12.5px; color: var(--ink-3); margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.page .hosts .hs { font-size: 13.5px; color: var(--ink-2); }
.page .hosts .hs .st { font-weight: 400; color: var(--ink-2); gap: 7px; }
.page .hosts .hs b { color: var(--ink); font-weight: 600; }
.page .hosts .q { font-size: 15px; }
.page .hosts .money { font-size: 14px; }
.page .hosts .z { color: var(--ink-3); }
.page .hosts .ver { display: inline-flex; gap: 5px; align-items: center; cursor: help; }
.page .hosts .ver .ne { color: var(--fail); font-weight: 650; }
.page .hosts .ver.bad { color: var(--ink); }
.page .hosts .cells, .page .hosts .gidx { display: grid; gap: 4px; }
.page .hosts .gidx span { font-size: 11.5px; color: var(--ink-3); padding-left: 2px; }
.page .hosts .gc { position: relative; height: 44px; border-radius: 4px; padding: 5px 7px 0 9px; font-size: 13px; line-height: 1.25; overflow: hidden; white-space: nowrap; text-decoration: none; color: var(--ink); }
.page .hosts .gc .id { font-weight: 550; }
.page .hosts .gc .u { display: block; font-size: 12px; color: var(--ink-3); }
.page .hosts .gc.busy { background: var(--paper-2); }
.page .hosts .gc.busy::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--ink-3); }
.page .hosts .gc.agent::before { background: var(--agent); }
.page .hosts .gc.human::before { background: var(--human); }
.page .hosts .gc .ub { position: absolute; left: 9px; right: 7px; bottom: 6px; height: 2px; background: var(--rule); border-radius: 1px; }
.page .hosts .gc .ub i { position: absolute; left: 0; top: 0; bottom: 0; background: var(--ink-2); border-radius: 1px; }
.page .hosts .gc.free { border: 1px dashed var(--rule); color: var(--ink-3); padding-left: 8px; }
.page .hosts .gc.other { border: 1px solid var(--rule); color: var(--ink-2); padding-left: 8px; background: repeating-linear-gradient(135deg, color-mix(in srgb, var(--ink-3) 22%, transparent) 0 1px, transparent 1px 6px); }
.page .hosts .gc.other .id { font-weight: 450; }
.page .hosts .hrow.stale .cells { opacity: .42; filter: grayscale(1); }
.page .hosts .hrow.stale .hn b { color: var(--ink-2); }
.page .hosts .msg { font-size: 13px; color: var(--ink-2); }
.page .hosts .slurm { display: flex; align-items: baseline; }
.page .hosts .slurm > div { padding: 0 22px; border-left: 1px solid var(--rule-2); cursor: help; }
.page .hosts .slurm > div:first-child { padding-left: 2px; border-left: 0; }
.page .hosts .slurm b { font: 400 21px/1 var(--sans); letter-spacing: -.01em; color: var(--ink); margin-right: 6px; }
.page .hosts .slurm span { font-size: 12.5px; color: var(--ink-3); }
.page .hosts-key .gk { display: inline-block; width: 18px; height: 12px; border-radius: 2px; }
.page .hosts-key .gk.agent { background: var(--paper-2); box-shadow: inset 3px 0 0 var(--agent); }
.page .hosts-key .gk.human { background: var(--paper-2); box-shadow: inset 3px 0 0 var(--human); }
.page .hosts-key .gk.free { border: 1px dashed var(--ink-3); }
.page .hosts-key .gk.other { border: 1px solid var(--rule); background: repeating-linear-gradient(135deg, color-mix(in srgb, var(--ink-3) 40%, transparent) 0 1px, transparent 1px 4px); }
.page .hosts-key .ne { color: var(--fail); font-weight: 650; }
.page .hosts-banner { margin: 12px 0 0; padding: 10px 0; border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); font-size: 14px; color: var(--ink-2); }
.page .hosts-banner b { color: var(--ink); font-weight: 600; }
`;

/** One glyph per state, never colour alone (mockup `GL`). */
export function StateGlyph({ state }: { state: ConnState }) {
  const ring = (dash?: string) => (
    <circle cx="5" cy="5" r="4" style={{ fill: "none", stroke: "var(--ink-2)", strokeWidth: 1.4, strokeDasharray: dash }} />
  );
  let body;
  if (state === "connected") body = <circle cx="5" cy="5" r="4" style={{ fill: "var(--ink-2)" }} />;
  else if (state === "stale")
    body = (
      <>
        <circle cx="5" cy="5" r="4" style={{ fill: "none", stroke: "var(--ink)", strokeWidth: 1.4 }} />
        <path d="M5 1a4 4 0 0 1 0 8z" style={{ fill: "var(--ink)" }} />
      </>
    );
  else if (state === "connecting" || state === "bootstrapping") body = ring("1.6 1.6");
  else if (state === "error" || state === "upgrade")
    body = <path d="M1.4 1.4L8.6 8.6M8.6 1.4L1.4 8.6" style={{ stroke: "var(--fail)", strokeWidth: 1.4 }} />;
  else body = ring();
  return (
    <svg width="10" height="10" aria-hidden="true" data-state={state}>
      {body}
    </svg>
  );
}

function Version({ host, version, hub }: { host: string; version: string | null; hub: string | null }) {
  if (!version) return <span>hx ·</span>;
  const bad = hub !== null && version !== hub;
  return (
    <span
      className={bad ? "ver bad" : "ver"}
      title={bad ? `hub runs hx ${hub}. Update: hx hosts upgrade ${host}` : `hx ${version}`}
    >
      {`hx ${version}`}
      {bad ? <span className="ne">≠</span> : null}
    </span>
  );
}

function stateTitle(row: HostRow): string {
  const st = row.state;
  if (st.state === "stale") return `No heartbeat since ${fmtClock(st.since)}. Cells show the last known state.`;
  if (st.state === "upgrade") return st.message || `hx hosts upgrade ${row.name}`;
  return st.message || `${st.state} since ${fmtClock(st.since)}`;
}

function StateCell({ row, hub, now }: { row: HostRow; hub: string | null; now: number }) {
  const st = row.state;
  const stale = st.state === "stale";
  const word = stale ? `stale ${fmtAgeMs(now - parseTime(st.since))}` : st.state;
  return (
    <div className="hs">
      <span className="st" title={stateTitle(row)}>
        <StateGlyph state={st.state} />
        {stale ? <b>{word}</b> : word}
      </span>
      <div className="meta">
        <Version host={row.name} version={st.hx_version ?? null} hub={hub} />
        {stale ? `  as of ${fmtClock(st.since)}` : null}
      </div>
    </div>
  );
}

interface CellProps {
  host: string;
  cell: GpuCell;
  run: RunRecord | undefined;
  asOf: string | null;
}

function Cell({ host, cell, run, asOf }: CellProps) {
  const style: CSSProperties = { gridColumn: `${cell.index + 1} / span ${cell.span}` };
  const title = cellTitle(host, cell, run, asOf);
  if (cell.kind === "free") {
    return (
      <div className="gc free" style={style} title={title}>
        free
      </div>
    );
  }
  const util = meanUtil(cell);
  if (cell.kind === "other") {
    return (
      <div className="gc other" style={style} title={title}>
        <span className="id">not hx</span>
        <span className="u">{`${util}%`}</span>
      </div>
    );
  }
  const runId = cell.runId ?? "";
  return (
    <AppLink className={`gc busy ${cell.kind}`} style={style} title={title} href={hrefs.run(runId)}>
      <span className="id">{shortId(runId)}</span>
      <span className="u">{cell.span > 1 ? `${util}% ×${cell.span}` : `${util}%`}</span>
      <span className="ub">
        <i style={{ width: `${Math.min(100, Math.max(0, util))}%` }} />
      </span>
    </AppLink>
  );
}

function Cells({ row, runs, columns }: { row: HostRow; runs: ReadonlyMap<string, RunRecord>; columns: number }) {
  if (row.slurm) {
    return (
      <div className="slurm">
        <div title={`hx jobs running on ${row.name}`}>
          <b>{row.slurm.running}</b>
          <span>running</span>
        </div>
        <div title={`hx jobs pending on ${row.name}`}>
          <b>{row.slurm.pending}</b>
          <span>pending</span>
        </div>
      </div>
    );
  }
  if (row.gpus.length === 0) {
    const text = row.state.state === "connected" ? (row.kind === "slurm" ? "·" : "no GPUs") : row.state.message || "·";
    return <div className="msg">{text}</div>;
  }
  const asOf = row.state.state === "stale" ? fmtClock(row.state.since) : null;
  return (
    <div className="cells" style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}>
      {gpuCells(row.gpus, runs).map((cell) => (
        <Cell
          key={cell.index}
          host={row.name}
          cell={cell}
          run={cell.runId ? runs.get(cell.runId) : undefined}
          asOf={asOf}
        />
      ))}
    </div>
  );
}

function HostLine(props: { row: HostRow; runs: ReadonlyMap<string, RunRecord>; hub: string | null; now: number; columns: number }) {
  const { row, runs, hub, now, columns } = props;
  const rate = row.usd_per_gpu_hour ?? null;
  const cost = row.cost_today_usd;
  return (
    <div className={row.state.state === "stale" ? "hrow stale" : "hrow"} role="group" aria-label={row.name}>
      <div className="hn">
        <div>
          <b>{row.name}</b>
          <span className="kind">{row.name === "local" ? "hub" : row.kind}</span>
        </div>
        <div className="meta" title={row.projects.join(", ")}>
          {gpuSpec(row.gpus) || "·"}
        </div>
      </div>
      <StateCell row={row} hub={hub} now={now} />
      <Cells row={row} runs={runs} columns={columns} />
      <div className={row.queue > 0 ? "r q" : "r q z"} title={row.queue > 0 ? `${row.queue} hx runs waiting for GPUs` : "Queue empty"}>
        {row.queue}
      </div>
      <div className={rate !== null ? "r money" : "r money z"} title={rate !== null ? "$/GPU-h from environments.yaml" : "No rate set"}>
        {rate !== null ? `$${rate.toFixed(2)}` : "·"}
      </div>
      <div className={cost > 0 ? "r money" : "r money z"} title="GPU and API cost of runs today">
        {cost > 0 ? fmtMoney(cost) : "·"}
      </div>
    </div>
  );
}

export interface HostsPanelProps {
  /** `GET /api/v1/hosts`. */
  hosts: HostRow[];
  /** Active runs (`OverviewSummary.running`), for each cell's launcher and label. */
  runs: RunRecord[];
  /** hx version of the hub; null while unknown (then no `≠` marks). */
  hubVersion: string | null;
  /** Current time in ms, for stale ages. */
  now: number;
}

/** The Hosts panel body: header, one row per host, and the key. */
export function HostsPanel({ hosts, runs, hubVersion, now }: HostsPanelProps) {
  if (hosts.length === 0) return <p className="small">none</p>;
  const byId = new Map(runs.map((r) => [r.run_id, r]));
  const columns = gpuColumns(hosts);
  return (
    <>
      {createElement("style", { "data-hx": "hosts" }, HOSTS_CSS)}
      <div className="hosts">
        <div className="hrow head">
          <div>host</div>
          <div>state</div>
          <div className="gidx" style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}>
            {Array.from({ length: columns }, (_, i) => (
              <span key={i}>{i}</span>
            ))}
          </div>
          <div className="r">queue</div>
          <div className="r">$/GPU‑h</div>
          <div className="r">today</div>
        </div>
        {hosts.map((row) => (
          <HostLine key={row.name} row={row} runs={byId} hub={hubVersion} now={now} columns={columns} />
        ))}
      </div>
      <div className="key hosts-key" aria-label="Key">
        <span><span className="gk agent" />agent run</span>
        <span><span className="gk human" />human run</span>
        <span><span className="gk free" />free</span>
        <span><span className="gk other" />not hx</span>
        <span><StateGlyph state="stale" />stale</span>
        <span><span>hx<span className="ne">≠</span></span>version mismatch</span>
      </div>
    </>
  );
}
```

- [ ] **Step 5: Run the tests and the typecheck**

Run: `cd ui && bun test test/pages/hostsPanelView.test.tsx test/pages/hostsPanel.test.tsx && bun run typecheck`
Expected: `28 pass`, `0 fail`; `tsc --noEmit` prints no errors.

- [ ] **Step 6: Commit**

```bash
git add ui/src/pages/components/HostsPanel.tsx ui/test/pages/hostsPanelView.test.tsx
git commit -m "feat(ui): hosts panel with GPU cells, SLURM counts, state and cost"
```

---

### Task 7: Hosts as Overview panel a; host-aware headline and metaline

**Files:**
- Modify: `ui/src/pages/Overview.tsx` (whole file below)
- Test: `ui/test/pages/Overview.test.tsx` (whole file below)

**Interfaces:**
- Consumes: `useHosts()` (Task 3), `useOverview()` and `api.environment()` (existing), `HostsPanel`, `hostTotals`, `hostsHeadline`, `hostsMetaline`, `fmtMoney`, `useNow`, `remoteRows`, `longStale`, `staleBannerHours` (Tasks 5-6); `OverviewSummary.cost_today_usd` (Task 1, contract section 2).
- Produces: Overview regions in order `a Hosts`, `b Runs by launcher`, `c Ideas`, `d Running`, `e Failures`, `f Projects`. With at least one host other than the hub's own `local` row (`remoteRows`): headline `hostsHeadline(summary.counts, totals)`, metaline `hostsMetaline(totals, hubVersion, remote.length)` (the host count leaves out the hub), panel a aside `$N today` when cost > 0. With only the `local` row (the backend always sends it), while hosts load, or on a hosts error: the backend headline and counts as in phase 1. A host stale for more than `staleBannerHours(rows)` (the hub's `stale_banner_hours` from `GET /api/v1/hosts`, default 24; controller ruling R1) adds `p.hosts-banner` (`role="status"`, `dgx unreachable 1d`) under the metaline (spec 5.6). Cost today is `summary.cost_today_usd` when the overview sends it (every run, the hub's own too), else the sum of the hosts' `cost_today_usd`; without remote hosts a positive `cost_today_usd` adds `$N today` to the phase 1 metaline. Query key `["environment"]` (hub descriptor, cached forever).

- [ ] **Step 1: Write the failing test**

Replace `ui/test/pages/Overview.test.tsx` with:

```tsx
import { afterEach, expect, test } from "bun:test";
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import { OverviewPage } from "../../src/pages/Overview";
import { makeOverview } from "./fixtures";
import { HttpReply, mockApi, renderWithClient, restoreFetch } from "./helpers";
import { RUN_AGENT, asSent, localRow, makeHostRuns, makeHosts } from "./hostFixtures";
import { OVERVIEW_COST } from "../api/phase2-fixtures";

const ENV = "GET /.well-known/hypothex/environment";

afterEach(() => {
  cleanup();
  restoreFetch();
});

test("only the hub's own row: backend headline and counts, panels a-f", async () => {
  // the backend's host_rows always sends the hub itself; with no other host nothing changes
  mockApi({ "GET /api/v1/overview": makeOverview(), "GET /api/v1/hosts": [localRow()], [ENV]: { hx_version: "0.5.0" } });
  renderWithClient(<OverviewPage />);
  const h1 = await screen.findByRole("heading", { level: 1 });
  const hostsPanel = screen.getByRole("region", { name: "a Hosts" });
  const hub = await within(hostsPanel).findByRole("group", { name: "local" });
  expect(hub.querySelector(".kind")?.textContent).toBe("hub");
  expect(h1.textContent).toBe("Idle. SVM leads toy-test by 0.037, p = 0.15");
  for (const text of ["19 runs today", "3 failed", "1 task"]) expect(screen.getByText(text)).toBeTruthy();
  expect(document.querySelector(".hosts-banner")).toBeNull();
  const names = screen.getAllByRole("region").map((r) => r.getAttribute("aria-label"));
  expect(names).toEqual(["a Hosts", "b Runs by launcher", "c Ideas", "d Running", "e Failures", "f Projects"]);
  expect(within(screen.getByRole("region", { name: "d Running" })).getByText("none")).toBeTruthy();
  expect(within(screen.getByRole("region", { name: "f Projects" })).getByText("0.9222")).toBeTruthy();
});

test("with hosts: running/waiting from the backend, stale from hosts; metaline and cells", async () => {
  const summary = { ...makeOverview(), counts: { running: 12, queued: 11 }, running: makeHostRuns() };
  mockApi({
    "GET /api/v1/overview": summary,
    "GET /api/v1/hosts": [localRow(), ...asSent(makeHosts(Date.now()))],
    [ENV]: { hx_version: "0.5.0" },
  });
  renderWithClient(<OverviewPage />);
  const h1 = await screen.findByRole("heading", { level: 1 });
  await waitFor(() => expect(h1.textContent).toBe("12 running, 11 waiting. dgx stale 4m"));
  expect(await screen.findByText("hub hx 0.5.0")).toBeTruthy();
  const meta = [...document.querySelectorAll(".metaline span")].map((s) => s.textContent);
  // 4 hosts: the hub's own row is not counted
  expect(meta).toEqual(["1 GPU free", "$332 today", "hub hx 0.5.0", "4 hosts"]);
  const panel = screen.getByRole("region", { name: "a Hosts" });
  expect(panel.querySelector(".aside")?.textContent).toBe("$332 today");
  expect(within(panel).getAllByRole("group").map((g) => g.getAttribute("aria-label"))).toEqual([
    "local",
    "gpu1",
    "dgx",
    "mccleary",
    "gpu2",
  ]);
  const gpu1 = within(panel).getByRole("group", { name: "gpu1" });
  expect(within(gpu1).getAllByRole("link")[0]?.getAttribute("href")).toBe(`/r/${RUN_AGENT}`);
  expect(within(gpu1).getByTitle("hub runs hx 0.5.0. Update: hx hosts upgrade gpu1")).toBeTruthy();
  expect(document.querySelector(".hosts-banner")).toBeNull();
});

test("a host stale for more than 24 h gets a banner; it is still stale, not lost", async () => {
  const now = Date.now();
  const hosts = asSent(makeHosts(now)).map((h) =>
    h.name === "dgx" ? { ...h, state: { ...h.state, since: new Date(now - 26 * 3_600_000).toISOString() } } : h,
  );
  mockApi({
    "GET /api/v1/overview": { ...makeOverview(), counts: { running: 1, queued: 0 } },
    "GET /api/v1/hosts": [localRow(), ...hosts],
    [ENV]: { hx_version: "0.5.0" },
  });
  renderWithClient(<OverviewPage />);
  await waitFor(() => expect(document.querySelector(".hosts-banner")?.textContent).toBe("dgx unreachable 1d"));
  const banner = document.querySelector(".hosts-banner") as HTMLElement;
  expect(banner.getAttribute("role")).toBe("status");
  expect(banner.getAttribute("title")).toBe(
    "No answer for more than 24 h. Its runs stay stale, not lost: only the host marks a run lost.",
  );
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("1 running. dgx stale 1d");
});

test("the banner threshold is the hub's stale_banner_hours", async () => {
  const now = Date.now();
  // dgx stale for 7 h: no banner at the default 24 h, a banner with stale_banner_hours 6
  const hosts = asSent(makeHosts(now)).map((h) =>
    h.name === "dgx" ? { ...h, state: { ...h.state, since: new Date(now - 7 * 3_600_000).toISOString() } } : h,
  );
  const six = [localRow({ stale_banner_hours: 6 }), ...hosts.map((h) => ({ ...h, stale_banner_hours: 6 }))];
  mockApi({
    "GET /api/v1/overview": { ...makeOverview(), counts: { running: 1, queued: 0 } },
    "GET /api/v1/hosts": six,
    [ENV]: { hx_version: "0.5.0" },
  });
  renderWithClient(<OverviewPage />);
  await waitFor(() => expect(document.querySelector(".hosts-banner")?.textContent).toBe("dgx unreachable 7h"));
  expect(document.querySelector(".hosts-banner")?.getAttribute("title")).toBe(
    "No answer for more than 6 h. Its runs stay stale, not lost: only the host marks a run lost.",
  );
  cleanup();
  restoreFetch();
  mockApi({
    "GET /api/v1/overview": { ...makeOverview(), counts: { running: 1, queued: 0 } },
    "GET /api/v1/hosts": [localRow(), ...hosts],
    [ENV]: { hx_version: "0.5.0" },
  });
  renderWithClient(<OverviewPage />);
  await waitFor(() => expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("1 running. dgx stale 7h"));
  expect(document.querySelector(".hosts-banner")).toBeNull();
});

test("cost today comes from the overview when it sends it; the hub-only metaline shows it too", async () => {
  mockApi({
    "GET /api/v1/overview": { ...makeOverview(), ...OVERVIEW_COST, counts: { running: 12, queued: 11 } },
    "GET /api/v1/hosts": [localRow(), ...asSent(makeHosts(Date.now()))],
    [ENV]: { hx_version: "0.5.0" },
  });
  renderWithClient(<OverviewPage />);
  // $402.75 of every run today, hub runs included (the hosts alone sum to $331.60)
  await waitFor(() =>
    expect([...document.querySelectorAll(".metaline span")].map((s) => s.textContent)).toEqual([
      "1 GPU free",
      "$403 today",
      "hub hx 0.5.0",
      "4 hosts",
    ]),
  );
  expect(screen.getByRole("region", { name: "a Hosts" }).querySelector(".aside")?.textContent).toBe("$403 today");
  cleanup();
  restoreFetch();
  mockApi({
    "GET /api/v1/overview": { ...makeOverview(), cost_today_usd: 12.25 },
    "GET /api/v1/hosts": [localRow()],
    [ENV]: { hx_version: "0.5.0" },
  });
  renderWithClient(<OverviewPage />);
  await screen.findByRole("heading", { level: 1 });
  const meta = () => [...document.querySelectorAll(".metaline span")].map((s) => s.textContent);
  // the phase 1 counts, then the cost of today's runs (also the Hosts panel's aside)
  await waitFor(() => expect(meta()).toContain("$12 today"));
  expect(meta()).toContain("19 runs today");
  expect(meta().at(-1)).toBe("$12 today");
});

test("hosts endpoint fails: error inside the Hosts panel, the rest of the page stays", async () => {
  mockApi({
    "GET /api/v1/overview": makeOverview(),
    "GET /api/v1/hosts": new HttpReply(500, { error: "hub offline", type: "HostUnavailableError" }),
    [ENV]: { hx_version: "0.5.0" },
  });
  renderWithClient(<OverviewPage />);
  const panel = await screen.findByRole("region", { name: "a Hosts" });
  expect((await within(panel).findByRole("alert")).textContent).toBe("hub offline");
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Idle. SVM leads toy-test by 0.037, p = 0.15");
  expect(screen.getByRole("region", { name: "c Ideas" })).toBeTruthy();
});

test("shows the server error", async () => {
  mockApi({ "GET /api/v1/overview": new HttpReply(500, { error: "index locked", type: "StoreError" }) });
  renderWithClient(<OverviewPage />);
  expect((await screen.findByRole("alert")).textContent).toBe("index locked");
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ui && bun test test/pages/Overview.test.tsx`
Expected: FAIL in six tests: tests 1 and 6 (`hosts endpoint fails`) with `Unable to find ... role "region" and name "a Hosts"`, tests 2 to 5 in `waitFor` (the headline stays the backend's `Idle. SVM leads ...`; no `.hosts-banner`, no `$12 today`). The last, `shows the server error`, passes.

- [ ] **Step 3: Write the Overview**

Replace `ui/src/pages/Overview.tsx` with:

```tsx
/**
 * Overview screen (spec 8.3.1, 8A.8): status headline; hosts (GPUs, SLURM, queue, cost);
 * runs by launcher; recent ideas; running; failures with a link to stderr; projects table.
 *
 * With hosts configured, the headline reads `12 running, 11 waiting. dgx stale 4m` and the
 * metaline shows free GPUs, cost today, the hub's hx version and the host count (mockup
 * `docs/mockups/phase2/shot-overview-*`). The hosts list always has the hub's own `local`
 * row; with no other host both stay as in phase 1 (plus `$N today` once runs cost money). A
 * host stale for longer than the hub's `stale_banner_hours` (default 24) gets a banner (spec
 * 5.6); its runs stay stale, never lost.
 */
import { useQuery } from "@tanstack/react-query";
import { Fragment } from "react";
import { api } from "../api/client";
import { useHosts, useOverview } from "../api/queries";
import { Figure } from "./components/Figure";
import { Unbroken } from "./components/Headline";
import {
  HostsPanel,
  fmtMoney,
  hostTotals,
  hostsHeadline,
  hostsMetaline,
  longStale,
  remoteRows,
  staleBannerHours,
  useNow,
} from "./components/HostsPanel";
import { IdeaList } from "./components/IdeaList";
import { FailureList, ProjectsTable, RunningList } from "./components/OverviewLists";
import { ErrorBox, Loading } from "./components/QueryState";
import { RunTimeline } from "./components/RunTimeline";
import { PageStyles } from "./components/styles";
import type { OverviewSummary } from "./components/types";

/** The hub's hx version from its environment descriptor; null until known or on error. */
function useHubVersion(): string | null {
  const env = useQuery({
    queryKey: ["environment"],
    queryFn: ({ signal }) => api.environment(signal),
    staleTime: Number.POSITIVE_INFINITY,
  });
  const version = env.data?.hx_version;
  return typeof version === "string" ? version : null;
}

function OverviewBody({ summary }: { summary: OverviewSummary }) {
  const hosts = useHosts();
  const hubVersion = useHubVersion();
  const now = useNow();
  const rows = hosts.data ?? [];
  const remote = remoteRows(rows);
  // the overview's cost today covers every run (hub runs too); the hosts' sum is the fallback
  const hostSums = hostTotals(rows, now);
  const totals = { ...hostSums, usdToday: summary.cost_today_usd ?? hostSums.usdToday };
  const withHosts = remote.length > 0;
  const hours = staleBannerHours(rows);
  const gone = hosts.error ? [] : longStale(remote, now, hours);
  const hubCost = summary.cost_today_usd ?? 0;
  return (
    <>
      <h1 className="headline">
        <Unbroken text={withHosts ? hostsHeadline(summary.counts, totals) : summary.headline} />
      </h1>
      <p className="metaline">
        {withHosts
          ? hostsMetaline(totals, hubVersion, remote.length).map((text) => <span key={text}>{text}</span>)
          : [
              ...Object.entries(summary.counts).map(([key, value]) => <span key={key}>{`${value} ${key}`}</span>),
              ...(hubCost > 0 ? [<span key="cost today">{`${fmtMoney(hubCost)} today`}</span>] : []),
            ]}
      </p>
      {gone.length > 0 ? (
        <p
          className="hosts-banner"
          role="status"
          title={`No answer for more than ${hours} h. Its runs stay stale, not lost: only the host marks a run lost.`}
        >
          {gone.map((h, i) => (
            <Fragment key={h.name}>
              {i > 0 ? ", " : null}
              <b>{h.name}</b>
              {` unreachable ${h.age}`}
            </Fragment>
          ))}
        </p>
      ) : null}
      <Figure
        letter="a"
        title="Hosts"
        aside={totals.usdToday > 0 ? `${fmtMoney(totals.usdToday)} today` : undefined}
      >
        {hosts.error ? (
          <ErrorBox error={hosts.error} />
        ) : hosts.data ? (
          <HostsPanel hosts={hosts.data} runs={summary.running} hubVersion={hubVersion} now={now} />
        ) : (
          <Loading />
        )}
      </Figure>
      <Figure letter="b" title="Runs by launcher">
        <RunTimeline items={summary.timeline} />
      </Figure>
      <div className="ov-grid">
        <div>
          <Figure letter="c" title="Ideas">
            <IdeaList ideas={summary.ideas} />
          </Figure>
        </div>
        <div className="side">
          <Figure letter="d" title="Running">
            <RunningList runs={summary.running} />
          </Figure>
          <Figure letter="e" title="Failures">
            <FailureList failures={summary.failures} />
          </Figure>
          <Figure letter="f" title="Projects">
            <ProjectsTable projects={summary.projects} />
          </Figure>
        </div>
      </div>
    </>
  );
}

export function OverviewPage() {
  const overview = useOverview();
  return (
    <div className="page">
      <PageStyles />
      <p className="crumb">All projects</p>
      {overview.error ? <ErrorBox error={overview.error} /> : null}
      {overview.data ? (
        <OverviewBody summary={overview.data} />
      ) : overview.error ? null : (
        <Loading />
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run the Overview tests, the whole UI suite and the typecheck**

Run: `cd ui && bun test test/pages/Overview.test.tsx && bun test && bun run typecheck`
Expected: Overview `7 pass`, `0 fail`; the whole suite `0 fail`; `tsc --noEmit` prints no errors. (`test/router.test.tsx` renders the Overview with unmocked hosts; the 404 only shows inside panel a, so it still passes.)

- [ ] **Step 5: Look at it against the mockup**

Run, from the repo root, in a first terminal (a fresh temp home with its own identity, a port the OS reports free, and SSH disabled, so the hub can never reach a real host; never run this against `~/.hypothex`, never on a fixed port). It is one shell command: `--home` and the SSH variables sit on each `hx` command line, never in a separate `export`; it prints the hub's port and identity, then serves:

```bash
H=/tmp/hx-f2; rm -rf "$H" && mkdir -p "$H" && ID="$(uuidgen | tr -d '-' | tr 'A-Z' 'a-z')" && \
printf '{"environment_id": "%s", "label": "hx-visual"}\n' "$ID" > "$H/environment.json" && \
HYPOTHEX_SSH=false HYPOTHEX_SCP=false uv run hx --home "$H" demo --with-hosts --json > /dev/null && \
P="$(uv run python -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')" && echo "hub port $P, id $ID" && \
HYPOTHEX_SSH=false HYPOTHEX_SCP=false uv run hx --home "$H" serve --port "$P"
```

In a second terminal, from the repo root, start the dev UI only after the hub on that port proved it is the `/tmp/hx-f2` hub (the dev UI's first page reads `/api/v1/hosts`, a host route):

```bash
P=<the port the first terminal printed>; ID="$(sed -n 's/.*"environment_id": *"\([^"]*\)".*/\1/p' /tmp/hx-f2/environment.json)"; \
if [ -n "$ID" ] && curl -sf "http://127.0.0.1:$P/.well-known/hypothex/environment" | grep -Fq "\"$ID\""; then (cd ui && HX_API="http://127.0.0.1:$P" bun run dev); else echo "port $P is not the /tmp/hx-f2 hub: stop"; fi
```

Open the URL the dev server prints and compare `/` with `docs/mockups/phase2/shot-overview-light.png` and, after the theme toggle, `shot-overview-dark.png`: column widths, cell height 44 px, stripe colours, dashed free cells, hatched not-hx cells, greyed stale row, `≠` in red.
Expected: same layout as the mockup minus the documented gaps (no SLURM oldest/fair-share; `·` for $/GPU-h on a host without a rate). Fix CSS in `HOSTS_CSS` only.

- [ ] **Step 6: Commit**

```bash
git add ui/src/pages/Overview.tsx ui/test/pages/Overview.test.tsx
git commit -m "feat(ui): hosts panel first on overview; headline counts running, waiting, stale"
```

---

## Group 3: Launch dialog (Tasks 8–13)

The Launch dialog (`ui/src/launch/LaunchDialog.tsx`) and the Task page "New run" button: host picker with free GPUs, queue and state; GPUs stepper; queue toggle; SLURM fields on SLURM hosts; seeds; command template with a `{seed}` highlight and the quoting hint as a tooltip; required hypothesis; resolved-command preview; Copy as CLI (exact `hx launch` lines); Launch N with `command_id` idempotency (spec 5.3, 8A.4, 8A.5, 8A.8). Pure logic lives in small `.ts` modules under `ui/src/launch/` (seed lists, shell-like command splitting, host availability and GPU plan, CLI text, draft checks, API calls), each with its own unit tests; `LaunchDialog.tsx` only holds form state and renders. One launch posts one run per seed, in seed order, each with `command_id = <attempt>.s<seed>`. The hub is always the first host (`local`, reserved in `environments.yaml`); it launches through `api.launch` (`POST /api/v1/runs`, with `repo`, the hub's own checkout from `TaskDetail.repo`), every other host through `api.launchOnHost` (`POST /api/v1/hosts/{host}/runs`, with `project` by name and never a path: a project copied from a host has a host path as its `repo`, and the hub finds its own checkout and the host's mapped one). Code provenance (spec 8A.4): a launch either pins `commit` (Rerun sweep: the template run's commit, when that run had no uncommitted changes) or sends none, and then the hub pins its own checkout's HEAD and diff; the dialog never sends a `diff` of its own (it has no checkout to diff). CLI flags are the contract's: `hx launch --host H --gpus N --queue [--partition P --time T --account A]`, plus the existing `--repo`, `-t`, `--seed`, `--param`, `--var`, `-H`, `--`.

Backend behaviour this group relies on (backend plan, contract section 2): `POST /api/v1/runs` (with `repo`) and `POST /api/v1/hosts/{host}/runs` (with `project`, no `repo`) accept `gpus`, `queue`, `slurm` and `commit`; without `commit` the hub pins its own checkout's HEAD and diff (backend `launch_on_host`); with `queue: false` and too few free GPUs they refuse with `"N GPUs requested; F of T free; add --queue to wait for them"`; the hub runs no scheduler loop, so the dialog never sends `queue: true` to the hub (a queued hub run would wait forever).

### Task 8: Seed lists and command templates

**Files:**
- Create: `ui/src/launch/seeds.ts`
- Create: `ui/src/launch/command.ts`
- Test: `ui/test/launch/seeds.test.ts`, `ui/test/launch/command.test.ts`

**Interfaces:**
- Consumes: `shellJoin(argv: string[]): string` from `ui/src/pages/components/format.ts` (tests only).
- Produces (`ui/src/launch/seeds.ts`):
  - `MAX_SEEDS = 64`
  - `interface SeedParse { seeds: number[]; error: string | null }`
  - `parseSeeds(text: string): SeedParse` — errors: `"none"`, `"bad seed <t>"`, `"bad range <t>"`, `"seed too large: <t>"`, `"at most 64 seeds"`.
  - `nextSeeds(used: readonly (number | null)[], n?: number): number[]`
- Produces (`ui/src/launch/command.ts`):
  - `SEED_SLOT = "{seed}"`, `SEED_HINT: string`
  - `interface SplitResult { argv: string[]; error: string | null; operators: string[] }`
  - `splitCommand(text: string): SplitResult` — errors: `"unclosed ' quote"`, `'unclosed " quote'`, `"trailing \\"`.
  - `interface Segment { text: string; seed: boolean }`, `templateSegments(text: string): Segment[]`
  - `hasSeedSlot(argv: readonly string[]): boolean`, `fillSeed(argv: readonly string[], seed: number): string[]`

- [ ] **Step 1: Write the failing tests**

Create `ui/test/launch/seeds.test.ts`:

```ts
import { describe, expect, test } from "bun:test";

import { MAX_SEEDS, nextSeeds, parseSeeds } from "../../src/launch/seeds";

describe("parseSeeds", () => {
  test("reads integers separated by commas or spaces, in order", () => {
    expect(parseSeeds("4, 5, 6")).toEqual({ seeds: [4, 5, 6], error: null });
    expect(parseSeeds(" 9 1,2 ")).toEqual({ seeds: [9, 1, 2], error: null });
  });

  test("expands inclusive ranges and drops repeats", () => {
    expect(parseSeeds("1-3 7")).toEqual({ seeds: [1, 2, 3, 7], error: null });
    expect(parseSeeds("3, 3, 1-3")).toEqual({ seeds: [3, 1, 2], error: null });
  });

  test("names the first bad token", () => {
    expect(parseSeeds("")).toEqual({ seeds: [], error: "none" });
    expect(parseSeeds("4, x")).toEqual({ seeds: [], error: "bad seed x" });
    expect(parseSeeds("-1")).toEqual({ seeds: [], error: "bad seed -1" });
    expect(parseSeeds("5-2")).toEqual({ seeds: [], error: "bad range 5-2" });
    expect(parseSeeds("2147483648")).toEqual({ seeds: [], error: "seed too large: 2147483648" });
  });

  test(`allows at most ${MAX_SEEDS} seeds`, () => {
    expect(parseSeeds("0-63").seeds).toHaveLength(64);
    expect(parseSeeds("0-63 64").error).toBe("at most 64 seeds");
    expect(parseSeeds("1-1000000000").error).toBe("at most 64 seeds");
  });
});

describe("nextSeeds", () => {
  test("continues after the largest seed used", () => {
    expect(nextSeeds([1, 2, 3, null])).toEqual([4, 5, 6]);
    expect(nextSeeds([9], 2)).toEqual([10, 11]);
  });

  test("starts at 1 when no seed was used", () => {
    expect(nextSeeds([])).toEqual([1, 2, 3]);
    expect(nextSeeds([null])).toEqual([1, 2, 3]);
  });
});
```

Create `ui/test/launch/command.test.ts`:

```ts
import { describe, expect, test } from "bun:test";

import {
  SEED_HINT,
  fillSeed,
  hasSeedSlot,
  splitCommand,
  templateSegments,
} from "../../src/launch/command";
import { shellJoin } from "../../src/pages/components/format";

describe("splitCommand", () => {
  test("splits on whitespace", () => {
    expect(splitCommand("python train.py  --lr 3e-4\t--seed {seed}")).toEqual({
      argv: ["python", "train.py", "--lr", "3e-4", "--seed", "{seed}"],
      error: null,
      operators: [],
    });
  });

  test("honours single quotes, double quotes and backslashes like sh", () => {
    expect(splitCommand(`python -c 'print("a b")' --name "x y" a\\ b`).argv).toEqual([
      "python",
      "-c",
      'print("a b")',
      "--name",
      "x y",
      "a b",
    ]);
    expect(splitCommand(`echo "say \\"hi\\" \\$HOME \\n"`).argv).toEqual(["echo", 'say "hi" $HOME \\n']);
    expect(splitCommand("echo '' x").argv).toEqual(["echo", "", "x"]);
    expect(splitCommand("python a.py \\\n  --x 1").argv).toEqual(["python", "a.py", "--x", "1"]);
  });

  test("reports unclosed quotes and a trailing backslash", () => {
    expect(splitCommand("python 'oops")).toEqual({ argv: [], error: "unclosed ' quote", operators: [] });
    expect(splitCommand('python "oops')).toEqual({ argv: [], error: 'unclosed " quote', operators: [] });
    expect(splitCommand("python oops\\")).toEqual({ argv: [], error: "trailing \\", operators: [] });
  });

  test("keeps an empty text empty", () => {
    expect(splitCommand("  \n ")).toEqual({ argv: [], error: null, operators: [] });
  });

  test("flags unquoted shell operators, not quoted ones", () => {
    expect(splitCommand("python a.py && python b.py").operators).toEqual(["&&"]);
    expect(splitCommand("python a.py '&&' x > out.txt").operators).toEqual([">"]);
  });

  test("round-trips shellJoin", () => {
    const argv = ["python", "it's", "", "a b", "--seed={seed}", 'say "x"'];
    expect(splitCommand(shellJoin(argv)).argv).toEqual(argv);
  });
});

test("templateSegments marks every {seed}", () => {
  expect(templateSegments("python t.py --seed {seed} --out r{seed}")).toEqual([
    { text: "python t.py --seed ", seed: false },
    { text: "{seed}", seed: true },
    { text: " --out r", seed: false },
    { text: "{seed}", seed: true },
  ]);
  expect(templateSegments("")).toEqual([]);
  expect(templateSegments("no slot")).toEqual([{ text: "no slot", seed: false }]);
});

test("fillSeed and hasSeedSlot", () => {
  expect(fillSeed(["python", "--seed={seed}", "{seed}{seed}"], 7)).toEqual(["python", "--seed=7", "77"]);
  expect(hasSeedSlot(["python", "--seed={seed}"])).toBe(true);
  expect(hasSeedSlot(["python", "--seed", "3"])).toBe(false);
});

test("the hint tells the user to quote {seed} in a shell", () => {
  expect(SEED_HINT).toBe("{seed} is filled with each seed. In a shell, quote it: '{seed}'");
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/shreyasv/Desktop/code/research_dash/ui && bun test test/launch/seeds.test.ts test/launch/command.test.ts`
Expected: FAIL with `Cannot find module '../../src/launch/seeds'` (and the same for `command`).

- [ ] **Step 3: Write the implementation**

Create `ui/src/launch/seeds.ts`:

```ts
/** Seed lists for the Launch dialog: `"4, 5, 6"`, `"1-3 7"`. */

/** Most seeds one launch may start. */
export const MAX_SEEDS = 64;
const MAX_SEED = 2 ** 31 - 1;

export interface SeedParse {
  seeds: number[];
  /** `null` when the text is valid; else a short reason naming the first bad token. */
  error: string | null;
}

/**
 * Parse a seed list: non-negative integers and inclusive ranges `a-b`, separated by commas
 * or whitespace. Repeats are dropped; the first occurrence keeps its place.
 */
export function parseSeeds(text: string): SeedParse {
  const tokens = text.split(/[\s,]+/).filter(Boolean);
  if (tokens.length === 0) return { seeds: [], error: "none" };
  const out: number[] = [];
  const seen = new Set<number>();
  for (const token of tokens) {
    const m = /^(\d+)(?:-(\d+))?$/.exec(token);
    if (m === null) return { seeds: [], error: `bad seed ${token}` };
    const lo = Number(m[1]);
    const hi = m[2] === undefined ? lo : Number(m[2]);
    if (hi > MAX_SEED || lo > MAX_SEED) return { seeds: [], error: `seed too large: ${token}` };
    if (hi < lo) return { seeds: [], error: `bad range ${token}` };
    if (hi - lo >= MAX_SEEDS) return { seeds: [], error: `at most ${MAX_SEEDS} seeds` };
    for (let seed = lo; seed <= hi; seed += 1) {
      if (!seen.has(seed)) {
        seen.add(seed);
        out.push(seed);
      }
    }
    if (out.length > MAX_SEEDS) return { seeds: [], error: `at most ${MAX_SEEDS} seeds` };
  }
  return { seeds: out, error: null };
}

/** `n` seeds after the largest one used (`null` seeds ignored); `1..n` when none was used. */
export function nextSeeds(used: readonly (number | null)[], n = 3): number[] {
  const nums = used.filter((s): s is number => typeof s === "number");
  const start = nums.length > 0 ? Math.max(...nums) + 1 : 1;
  return Array.from({ length: n }, (_, i) => start + i);
}
```

Create `ui/src/launch/command.ts`:

```ts
/**
 * Command templates for the Launch dialog. The user types one line; it is split into argv
 * the way `sh` would (quotes, backslashes), because runs execute argv directly, not through
 * a shell. `{seed}` stays in the template; hx fills it from each run's seed.
 */

export const SEED_SLOT = "{seed}";

/** Tooltip on the command field and on each `{seed}` mark. */
export const SEED_HINT = "{seed} is filled with each seed. In a shell, quote it: '{seed}'";

/** Words a shell would treat as syntax; as argv they reach the program as plain text. */
const OPERATORS = new Set(["|", "||", "&", "&&", ";", ">", ">>", "<", "2>", "2>&1"]);

export interface SplitResult {
  argv: string[];
  /** `null` when the text splits cleanly. */
  error: string | null;
  /** Unquoted words that are shell operators, in order. */
  operators: string[];
}

/** Split a command line into argv like POSIX `sh` (no expansion of `$`, globs or `~`). */
export function splitCommand(text: string): SplitResult {
  const argv: string[] = [];
  const operators: string[] = [];
  let word = "";
  let inWord = false;
  let quoted = false;
  const endWord = (): void => {
    if (!inWord) return;
    if (!quoted && OPERATORS.has(word)) operators.push(word);
    argv.push(word);
    word = "";
    inWord = false;
    quoted = false;
  };
  let i = 0;
  while (i < text.length) {
    const c = text.charAt(i);
    if (c === "'") {
      const close = text.indexOf("'", i + 1);
      if (close < 0) return { argv: [], error: "unclosed ' quote", operators: [] };
      word += text.slice(i + 1, close);
      inWord = true;
      quoted = true;
      i = close + 1;
    } else if (c === '"') {
      let j = i + 1;
      for (;;) {
        if (j >= text.length) return { argv: [], error: 'unclosed " quote', operators: [] };
        const d = text.charAt(j);
        if (d === '"') break;
        if (d === "\\" && j + 1 < text.length && '"\\$`'.includes(text.charAt(j + 1))) {
          word += text.charAt(j + 1);
          j += 2;
        } else {
          word += d;
          j += 1;
        }
      }
      inWord = true;
      quoted = true;
      i = j + 1;
    } else if (c === "\\") {
      if (i + 1 >= text.length) return { argv: [], error: "trailing \\", operators: [] };
      const next = text.charAt(i + 1);
      if (next !== "\n") {
        word += next;
        inWord = true;
        quoted = true;
      }
      i += 2;
    } else if (/\s/.test(c)) {
      endWord();
      i += 1;
    } else {
      word += c;
      inWord = true;
      i += 1;
    }
  }
  endWord();
  return { argv, error: null, operators };
}

export interface Segment {
  text: string;
  /** True for a `{seed}` slot. */
  seed: boolean;
}

/** Cut text into plain runs and `{seed}` slots, for highlighting. */
export function templateSegments(text: string): Segment[] {
  const out: Segment[] = [];
  text.split(SEED_SLOT).forEach((part, i) => {
    if (i > 0) out.push({ text: SEED_SLOT, seed: true });
    if (part) out.push({ text: part, seed: false });
  });
  return out;
}

/** True when any argument contains `{seed}`. */
export function hasSeedSlot(argv: readonly string[]): boolean {
  return argv.some((a) => a.includes(SEED_SLOT));
}

/** The argv with every `{seed}` replaced by `seed`. */
export function fillSeed(argv: readonly string[], seed: number): string[] {
  return argv.map((a) => a.replaceAll(SEED_SLOT, String(seed)));
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/shreyasv/Desktop/code/research_dash/ui && bun test test/launch/seeds.test.ts test/launch/command.test.ts`
Expected: PASS, `15 pass`, `0 fail`.

- [ ] **Step 5: Commit**

```bash
git -C /Users/shreyasv/Desktop/code/research_dash add ui/src/launch/seeds.ts ui/src/launch/command.ts ui/test/launch/seeds.test.ts ui/test/launch/command.test.ts
git -C /Users/shreyasv/Desktop/code/research_dash commit -m "feat(ui): seed lists and command templates for the launch dialog"
```

---

### Task 9: Launch hosts, availability and the GPU plan

**Files:**
- Create: `ui/src/launch/plan.ts`
- Create: `ui/test/launch/fixtures.ts`
- Test: `ui/test/launch/plan.test.ts`

**Interfaces:**
- Consumes: `ConnState`, `GpuInfo`, `HostRow`, `HostState` from `ui/src/api/models.ts` (Task 1, contract section 4).
- Produces (`ui/src/launch/plan.ts`):
  - `type LaunchHostKind = "hub" | "ssh" | "slurm"`, `HUB = "local"`, `SLURM_MAX_GPUS = 8` (host states use the Task 1 `ConnState`)
  - `interface LaunchHost { name; kind: LaunchHostKind; state: ConnState; since: string | null; message: string; gpus: GpuInfo[]; queue: number; slurm: {pending: number; running: number} | null; projects: string[] | null }` (`projects: null` = every project, the hub)
  - `interface HubLoad { gpus: GpuInfo[]; queue: number }`
  - `interface SlurmFields { partition: string; account: string; time: string }`
  - `interface LaunchSpec { host: LaunchHost; project: string; repo: string; commit: string | null; task: string | null; argv: string[]; hypothesis: string; gpus: number; queue: boolean; slurm: SlurmFields | null; params: Record<string, string>; vars: Record<string, string> }` (`repo` is only sent to the hub; `commit` null lets the hub pin its checkout's HEAD)
  - `interface Availability { ok: boolean; reason: string }`
  - `interface LaunchPlan { now: number; queued: number; blocked: number; cvd: number[]; firstPos: number | null }`
  - `type GpuCell = "busy" | "free" | "other" | "stale" | "none"`
  - `toLaunchHosts(rows: readonly HostRow[], hub: HubLoad): LaunchHost[]`
  - `ago(since: string | null, now: number): string`, `stateLabel(host, now): string`, `stateReason(host, now): string`
  - `availability(host: LaunchHost, project: string, now?: number): Availability`
  - `freeGpus(host): number[]`, `gpuCells(host): GpuCell[]`, `gpuLimit(host): number`, `gpusForHost(prev: number, host): number`
  - `pickHost(hosts: readonly LaunchHost[], project: string, preferred: string | null, now?: number): string | null`
  - `planLaunch(host, gpus: number, n: number, queue: boolean): LaunchPlan`, `posRange(plan): string`
  - `launchSummary(host, gpus: number, n: number, time: string): string`, `hostTitle(host): string`
  - `SLURM_TIME: RegExp`, `validSlurmTime(time: string): boolean`, `slurmBody(f: SlurmFields, gpus: number): Partial<SlurmDefaults>` (only the fields the user filled in, plus `gpus`; never `extra`. The backend merges the body over the host's `SlurmDefaults` with `exclude_unset`, so any field sent, even `null`, would replace the host's value: a blank field must be left out to keep the host's partition, account, time and extra `#SBATCH` lines)
- Produces (`ui/test/launch/fixtures.ts`): `PROJECT`, `TASK`, `REPO_PATH`, `CMD`, `minutesAgo`, `gpu`, `hostRow`, `launchHost`, `GPU1`, `DGX`, `MCCLEARY`, `GPU2` (used by every later launch test). `DGX` (stale) and `GPU2` (bootstrapping) are shaped as the hub sends them: no GPUs, queue 0.

- [ ] **Step 1: Check the API models exist**

Run: `grep -nE "export (interface|type) (HostRow|GpuInfo|HostState)\b" /Users/shreyasv/Desktop/code/research_dash/ui/src/api/models.ts`
Expected: three lines (`HostState`, `GpuInfo`, `HostRow`). If any is missing, stop: Task 1 is not done.

- [ ] **Step 2: Write the test fixtures**

Create `ui/test/launch/fixtures.ts`:

```ts
/** Hosts as `GET /api/v1/hosts` returns them, shaped like the phase 2 mockup. */
import type { GpuInfo, HostRow, HostState } from "../../src/api/models";
import type { LaunchHost } from "../../src/launch/plan";

export const PROJECT = "rxn-forward";
export const TASK = "uspto-forward-top1";
export const REPO_PATH = "/Users/sv/code/rxn-forward";
export const CMD = "python train.py --lr 3e-4 --seed {seed}";

export function minutesAgo(minutes: number): string {
  return new Date(Date.now() - minutes * 60_000).toISOString();
}

export function gpu(index: number, over: Partial<GpuInfo> = {}): GpuInfo {
  return {
    index,
    name: "A100 80GB",
    util: 0,
    mem_used_mb: 0,
    mem_total_mb: 81920,
    external: false,
    run_id: null,
    ...over,
  };
}

/** One `GET /api/v1/hosts` row; `state` overrides fields of its `HostState`. */
export function hostRow(name: string, over: Partial<HostRow> = {}, state: Partial<HostState> = {}): HostRow {
  const kind = over.kind ?? "ssh";
  return {
    name,
    kind,
    state: {
      name,
      kind,
      state: "connected",
      since: minutesAgo(0),
      message: "",
      environment_id: `env-${name}`,
      hx_version: "0.5.0",
      last_sequence: 0,
      local_port: 41000,
      ...state,
    },
    gpus: [],
    queue: 0,
    slurm: null,
    cost_today_usd: 0,
    projects: [PROJECT],
    ...over,
  };
}

/** A `LaunchHost` for pure-function tests. */
export function launchHost(over: Partial<LaunchHost> = {}): LaunchHost {
  return {
    name: "gpu1",
    kind: "ssh",
    state: "connected",
    since: null,
    message: "",
    gpus: [],
    queue: 0,
    slurm: null,
    projects: [PROJECT],
    ...over,
  };
}

const busy = (index: number, runId: string, name = "A100 80GB"): GpuInfo =>
  gpu(index, { name, run_id: runId, util: 90, mem_used_mb: 60000 });

/** 8 GPUs: hx runs on 0-2, 4, 6; another user on 3 and 7; GPU 5 free. 3 runs queued. */
export const GPU1 = hostRow("gpu1", {
  queue: 3,
  gpus: [
    busy(0, "r-6b0e"),
    busy(1, "r-6b0e"),
    busy(2, "r-1d77"),
    gpu(3, { external: true, util: 63 }),
    busy(4, "r-52c9"),
    gpu(5),
    busy(6, "r-3fa2"),
    gpu(7, { external: true, util: 9 }),
  ],
});

/** Stale for 4 minutes. The hub sends no GPUs and queue 0 for a host that is not connected. */
export const DGX = hostRow("dgx", {}, { state: "stale", since: minutesAgo(4) });

export const MCCLEARY = hostRow("mccleary", { kind: "slurm", slurm: { pending: 6, running: 4 } });

/** Still installing hx (as the hub sends it: no GPUs yet). */
export const GPU2 = hostRow("gpu2", {}, { state: "bootstrapping" });
```

- [ ] **Step 3: Write the failing tests**

Create `ui/test/launch/plan.test.ts`:

```ts
import { describe, expect, test } from "bun:test";

import {
  availability,
  freeGpus,
  gpuCells,
  gpuLimit,
  gpusForHost,
  hostTitle,
  launchSummary,
  pickHost,
  planLaunch,
  posRange,
  slurmBody,
  stateLabel,
  stateReason,
  toLaunchHosts,
  validSlurmTime,
} from "../../src/launch/plan";
import { DGX, GPU1, GPU2, MCCLEARY, PROJECT, gpu, hostRow, launchHost } from "./fixtures";

const NOW = Date.parse("2026-10-03T14:32:00Z");
const HOSTS = toLaunchHosts([GPU1, DGX, MCCLEARY, GPU2], { gpus: [], queue: 0 });
const [HUB_HOST, G1, DGX_HOST, SLURM_HOST, BOOT_HOST] = HOSTS;
const hub = launchHost({ name: "local", kind: "hub", projects: null });

describe("toLaunchHosts", () => {
  test("puts the hub first with its own GPUs and queue", () => {
    const hosts = toLaunchHosts([GPU1], { gpus: [gpu(0, { name: "RTX 4090" })], queue: 1 });
    expect(hosts.map((h) => [h.name, h.kind, h.state, h.queue])).toEqual([
      ["local", "hub", "connected", 1],
      ["gpu1", "ssh", "connected", 3],
    ]);
    expect(hosts[0]?.projects).toBeNull();
    expect(hosts[0]?.gpus.map((g) => g.name)).toEqual(["RTX 4090"]);
    expect(hosts[1]?.projects).toEqual([PROJECT]);
  });

  test("uses the hub's own row when the hosts list has one", () => {
    const hosts = toLaunchHosts([GPU1, hostRow("local", { queue: 2 })], { gpus: [], queue: 0 });
    expect(hosts.map((h) => h.name)).toEqual(["local", "gpu1"]);
    expect(hosts[0]).toMatchObject({ kind: "hub", queue: 2, projects: null });
  });
});

describe("availability", () => {
  test("a connected host with this project mapped can take the run; so can the hub", () => {
    expect(availability(launchHost(), PROJECT, NOW)).toEqual({ ok: true, reason: "" });
    expect(availability(hub, "any-project", NOW)).toEqual({ ok: true, reason: "" });
  });

  test("every other state names what is wrong and the fix", () => {
    const at = (over: Parameters<typeof launchHost>[0]) => stateReason(launchHost(over), NOW);
    expect(at({ state: "stale", since: "2026-10-03T14:28:00Z" })).toBe("gpu1 stale 4m: no heartbeat");
    expect(at({ state: "connecting" })).toBe("connecting to gpu1");
    expect(at({ state: "bootstrapping" })).toBe("installing hx on gpu1");
    expect(at({ state: "bootstrapping", message: "3/5 uv" })).toBe("installing hx on gpu1: 3/5 uv");
    expect(at({ state: "upgrade" })).toBe("hx on gpu1 needs an upgrade: hx hosts upgrade gpu1");
    expect(at({ state: "error", message: "ssh: connect to host gpu1 port 22: Connection refused" })).toBe(
      "ssh: connect to host gpu1 port 22: Connection refused",
    );
    expect(at({ state: "error" })).toBe("gpu1: connection error");
    expect(at({ state: "disabled" })).toBe("gpu1 disconnected: hx hosts connect gpu1");
    expect(availability(launchHost({ state: "disabled" }), PROJECT, NOW).ok).toBe(false);
  });

  test("a host without this project's repo mapped names hx hosts map", () => {
    expect(availability(launchHost({ name: "gpu3", projects: ["other"] }), PROJECT, NOW)).toEqual({
      ok: false,
      reason: "no path for rxn-forward on gpu3: hx hosts map rxn-forward gpu3 <path>",
    });
  });
});

test("two hubs bootstrapping one host: the second waits, then shows the lock error, and never launches there", () => {
  // while it waits on the install lock, the backend says bootstrapping with an empty message
  const waiting = launchHost({ state: "bootstrapping" });
  expect(availability(waiting, PROJECT, NOW)).toEqual({ ok: false, reason: "installing hx on gpu1" });
  expect(stateLabel(waiting, NOW)).toBe("boot");
  // a lock held too long ends the bootstrap: state error with the BootstrapError message
  const lock = "lock /home/sv/.hypothex/runtime/.lock is held by hub2:4411; waited 300s";
  const locked = launchHost({ state: "error", message: lock });
  expect(availability(locked, PROJECT, NOW)).toEqual({ ok: false, reason: lock });
  expect(stateLabel(locked, NOW)).toBe("error");
  expect(pickHost([waiting], PROJECT, "gpu1", NOW)).toBeNull();
  expect(pickHost([locked, launchHost({ name: "gpu3" })], PROJECT, "gpu1", NOW)).toBe("gpu3");
});

test("stateLabel is short", () => {
  const label = (over: Parameters<typeof launchHost>[0]) => stateLabel(launchHost(over), NOW);
  expect(label({ state: "stale", since: "2026-10-03T14:28:00Z" })).toBe("stale 4m");
  expect(label({ state: "stale", since: "2026-10-03T13:02:00Z" })).toBe("stale 1h");
  expect(label({ state: "stale", since: "2026-09-30T14:32:00Z" })).toBe("stale 3d");
  expect(label({ state: "stale", since: null })).toBe("stale");
  expect(label({ state: "bootstrapping" })).toBe("boot");
  expect(label({ state: "disabled" })).toBe("off");
  expect(label({ state: "connecting" })).toBe("connecting");
  expect(label({ state: "upgrade" })).toBe("upgrade");
  expect(label({ state: "error" })).toBe("error");
});

test("freeGpus and gpuCells read nvidia-smi rows in index order", () => {
  expect(freeGpus(G1)).toEqual([5]);
  expect(gpuCells(G1)).toEqual(["busy", "busy", "busy", "other", "busy", "free", "busy", "other"]);
  // the hub sends no GPUs for a host that is not connected
  expect(gpuCells(DGX_HOST)).toEqual([]);
  expect(gpuCells(BOOT_HOST)).toEqual([]);
  // a stale host's last known GPUs (kept by useHosts / the launch hosts query) are drawn stale
  expect(gpuCells({ ...DGX_HOST, gpus: [gpu(0, { run_id: "r-d0" }), gpu(1)] })).toEqual(["stale", "stale"]);
  expect(gpuCells({ ...BOOT_HOST, gpus: [gpu(0), gpu(1)] })).toEqual(["none", "none"]);
  expect(freeGpus(launchHost({ gpus: [gpu(3), gpu(1, { run_id: "r" }), gpu(0)] }))).toEqual([0, 3]);
  expect(freeGpus(SLURM_HOST)).toEqual([]);
});

test("gpuLimit and gpusForHost keep the stepper inside the host", () => {
  expect(gpuLimit(G1)).toBe(8);
  expect(gpuLimit(HUB_HOST)).toBe(0);
  expect(gpuLimit(SLURM_HOST)).toBe(8);
  expect(gpusForHost(0, G1)).toBe(1);
  expect(gpusForHost(5, launchHost({ gpus: [gpu(0), gpu(1)] }))).toBe(2);
  expect(gpusForHost(3, HUB_HOST)).toBe(0);
  expect(gpusForHost(4, SLURM_HOST)).toBe(4);
});

describe("planLaunch", () => {
  test("ssh host with the queue on: seeds that do not fit wait behind the queue", () => {
    expect(planLaunch(G1, 1, 3, true)).toEqual({ now: 1, queued: 2, blocked: 0, cvd: [5], firstPos: 4 });
    expect(planLaunch(G1, 2, 3, true)).toEqual({ now: 0, queued: 3, blocked: 0, cvd: [], firstPos: 4 });
    expect(planLaunch(G1, 1, 1, true)).toEqual({ now: 1, queued: 0, blocked: 0, cvd: [5], firstPos: null });
  });

  test("queue off, no GPUs, SLURM, and the hub", () => {
    expect(planLaunch(G1, 1, 3, false)).toEqual({ now: 1, queued: 0, blocked: 2, cvd: [5], firstPos: null });
    expect(planLaunch(G1, 0, 3, true)).toEqual({ now: 3, queued: 0, blocked: 0, cvd: [], firstPos: null });
    expect(planLaunch(SLURM_HOST, 2, 3, true)).toEqual({ now: 0, queued: 3, blocked: 0, cvd: [], firstPos: null });
    const gpuHub = launchHost({ name: "local", kind: "hub", projects: null, gpus: [gpu(0), gpu(1)] });
    expect(planLaunch(gpuHub, 1, 3, true)).toEqual({ now: 2, queued: 0, blocked: 1, cvd: [0], firstPos: null });
  });
});

test("posRange", () => {
  expect(posRange({ now: 1, queued: 2, blocked: 0, cvd: [5], firstPos: 4 })).toBe("pos 4–5");
  expect(posRange({ now: 0, queued: 1, blocked: 0, cvd: [], firstPos: 4 })).toBe("pos 4");
  expect(posRange({ now: 3, queued: 0, blocked: 0, cvd: [], firstPos: null })).toBe("");
});

test("pickHost: the preferred host if it can take the run, else the most free GPUs", () => {
  expect(pickHost(HOSTS, PROJECT, null)).toBe("gpu1");
  expect(pickHost(HOSTS, PROJECT, "mccleary")).toBe("mccleary");
  expect(pickHost(HOSTS, PROJECT, "dgx")).toBe("gpu1");
  expect(pickHost(HOSTS, "other-project", null)).toBe("local");
  expect(pickHost([], PROJECT, null)).toBeNull();
});

test("launchSummary", () => {
  expect(launchSummary(G1, 1, 3, "02:00:00")).toBe("3 × 1 GPU on gpu1");
  expect(launchSummary(SLURM_HOST, 2, 1, " 08:00:00 ")).toBe("1 job × 2 GPU, ≤ 08:00:00");
  expect(launchSummary(SLURM_HOST, 2, 3, "08:00:00")).toBe("3 jobs × 2 GPU, ≤ 08:00:00");
  // time left blank: the host's default time applies
  expect(launchSummary(SLURM_HOST, 2, 3, " ")).toBe("3 jobs × 2 GPU");
  expect(launchSummary(HUB_HOST, 0, 3, "02:00:00")).toBe("3 runs on local, no GPU");
  expect(launchSummary(HUB_HOST, 0, 1, "02:00:00")).toBe("1 run on local, no GPU");
});

test("validSlurmTime accepts every sbatch --time form; slurmBody sends only the fields filled in", () => {
  for (const ok of ["08:00:00", "1-12:00:00", "30", "90:00", "2-0", "2-04:30"]) {
    expect(validSlurmTime(ok)).toBe(true);
  }
  for (const bad of ["8h", "", "1:2:3:4", "08:00:0", "-1"]) expect(validSlurmTime(bad)).toBe(false);
  expect(slurmBody({ partition: " gpu ", account: "", time: " 08:00:00 " }, 2)).toEqual({
    partition: "gpu",
    time: "08:00:00",
    gpus: 2,
  });
  // blank means the host's default: the key is left out, so the backend keeps the host's value
  const blank = slurmBody({ partition: "", account: " ", time: "" }, 2);
  expect(blank).toEqual({ gpus: 2 });
  expect(["partition", "account", "time", "extra"].filter((k) => k in blank)).toEqual([]);
});

test("hostTitle", () => {
  expect(hostTitle(G1)).toBe("gpu1: 8 GPU (A100 80GB), 1 free, 3 queued");
  expect(hostTitle(SLURM_HOST)).toBe("mccleary: 4 running, 6 pending in SLURM");
  expect(hostTitle(HUB_HOST)).toBe("local: 0 GPU, 0 free, 0 queued");
});
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `cd /Users/shreyasv/Desktop/code/research_dash/ui && bun test test/launch/plan.test.ts`
Expected: FAIL with `Cannot find module '../../src/launch/plan'`.

- [ ] **Step 5: Write the implementation**

Create `ui/src/launch/plan.ts`:

```ts
/**
 * Launch targets for the dialog: the hub plus every host from `GET /api/v1/hosts`, whether
 * each can take a run of this project, and how many seeds start now, wait in the hx queue,
 * or cannot start (spec 8A.5).
 */
import type { ConnState, GpuInfo, HostRow, SlurmDefaults } from "../api/models";

export type LaunchHostKind = "hub" | "ssh" | "slurm";

/** Name of the hub's own row; reserved in `environments.yaml`. */
export const HUB = "local";
/** Most GPUs one SLURM job may ask for in the dialog. */
export const SLURM_MAX_GPUS = 8;

export interface LaunchHost {
  name: string;
  kind: LaunchHostKind;
  state: ConnState;
  since: string | null;
  message: string;
  gpus: GpuInfo[];
  /** hx runs waiting for GPUs on this host. */
  queue: number;
  slurm: { pending: number; running: number } | null;
  /** Projects with a repo mapped on the host; `null` means every project (the hub). */
  projects: string[] | null;
}

/** The hub's own GPUs (`GET /api/v1/gpus`) and queue length (`GET /api/v1/queue`). */
export interface HubLoad {
  gpus: GpuInfo[];
  queue: number;
}

export interface SlurmFields {
  partition: string;
  account: string;
  time: string;
}

/** Everything one launch needs except the seed. */
export interface LaunchSpec {
  host: LaunchHost;
  /** Sent by name to a host launch (`POST /api/v1/hosts/{host}/runs`). */
  project: string;
  /** The hub's checkout (`TaskDetail.repo`): sent only to the hub, and the CLI's `--repo`. */
  repo: string;
  /** Pinned commit (spec 8A.4); null: the hub pins its own checkout's HEAD and diff. */
  commit: string | null;
  task: string | null;
  argv: string[];
  hypothesis: string;
  gpus: number;
  queue: boolean;
  slurm: SlurmFields | null;
  params: Record<string, string>;
  vars: Record<string, string>;
}

export interface Availability {
  ok: boolean;
  /** Why the host cannot take the run, with the fix; `""` when it can. */
  reason: string;
}

export interface LaunchPlan {
  /** Seeds that start at once. */
  now: number;
  /** Seeds that wait in the hx queue (SSH, queue on) or in SLURM. */
  queued: number;
  /** Seeds that would be refused (queue off or the hub, too few free GPUs). */
  blocked: number;
  /** GPU indices the first seed gets. */
  cvd: number[];
  /** Queue position of the first waiting seed. */
  firstPos: number | null;
}

export type GpuCell = "busy" | "free" | "other" | "stale" | "none";

function fromRow(row: HostRow): LaunchHost {
  return {
    name: row.name,
    kind: row.kind === "local" ? "hub" : row.kind,
    state: row.state.state,
    since: row.state.since,
    message: row.state.message,
    gpus: row.gpus,
    queue: row.queue,
    slurm: row.slurm,
    projects: row.projects,
  };
}

/** The hub first (its own row if listed, else built from `hub`), then the other hosts in order. */
export function toLaunchHosts(rows: readonly HostRow[], hub: HubLoad): LaunchHost[] {
  const own = rows.find((r) => r.name === HUB);
  const first: LaunchHost = own
    ? { ...fromRow(own), kind: "hub", projects: null }
    : {
        name: HUB,
        kind: "hub",
        state: "connected",
        since: null,
        message: "",
        gpus: hub.gpus,
        queue: hub.queue,
        slurm: null,
        projects: null,
      };
  return [first, ...rows.filter((r) => r.name !== HUB).map(fromRow)];
}

/** `4m`, `1h`, `3d` since an ISO time; `""` when unknown. */
export function ago(since: string | null, now: number): string {
  if (since === null) return "";
  const t = Date.parse(since);
  if (Number.isNaN(t)) return "";
  const minutes = Math.max(0, Math.round((now - t) / 60_000));
  if (minutes < 60) return `${minutes}m`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)}h`;
  return `${Math.floor(minutes / 1440)}d`;
}

const STATE_LABEL: Record<ConnState, string> = {
  connecting: "connecting",
  bootstrapping: "boot",
  connected: "connected",
  stale: "stale",
  upgrade: "upgrade",
  error: "error",
  disabled: "off",
};

/** The short state text for a host row. */
export function stateLabel(host: LaunchHost, now: number): string {
  if (host.state === "stale") {
    const age = ago(host.since, now);
    return age ? `stale ${age}` : "stale";
  }
  return STATE_LABEL[host.state];
}

/** Why a host in this state cannot take a run, with the fix. */
export function stateReason(host: LaunchHost, now: number): string {
  const name = host.name;
  switch (host.state) {
    case "connected":
      return "";
    case "stale": {
      const age = ago(host.since, now);
      return age ? `${name} stale ${age}: no heartbeat` : `${name} stale: no heartbeat`;
    }
    case "connecting":
      return `connecting to ${name}`;
    case "bootstrapping":
      return host.message ? `installing hx on ${name}: ${host.message}` : `installing hx on ${name}`;
    case "upgrade":
      return `hx on ${name} needs an upgrade: hx hosts upgrade ${name}`;
    case "error":
      return host.message || `${name}: connection error`;
    case "disabled":
      return `${name} disconnected: hx hosts connect ${name}`;
  }
}

/** A host can take the run when it is connected and has this project's repo mapped (8A.4). */
export function availability(host: LaunchHost, project: string, now: number = Date.now()): Availability {
  if (host.state !== "connected") return { ok: false, reason: stateReason(host, now) };
  if (host.projects !== null && !host.projects.includes(project)) {
    return {
      ok: false,
      reason: `no path for ${project} on ${host.name}: hx hosts map ${project} ${host.name} <path>`,
    };
  }
  return { ok: true, reason: "" };
}

function byIndex(host: LaunchHost): GpuInfo[] {
  return [...host.gpus].sort((a, b) => a.index - b.index);
}

/** Indices of GPUs no hx run holds and no other process uses (spec 8A.5). SLURM: none. */
export function freeGpus(host: LaunchHost): number[] {
  if (host.kind === "slurm") return [];
  return byIndex(host)
    .filter((g) => !g.external && g.run_id == null)
    .map((g) => g.index);
}

/** One cell per GPU for the mini map in a host row. */
export function gpuCells(host: LaunchHost): GpuCell[] {
  return byIndex(host).map((g) => {
    if (host.state === "stale") return "stale";
    if (host.state !== "connected") return "none";
    if (g.external) return "other";
    return g.run_id == null ? "free" : "busy";
  });
}

/** Most GPUs one run may ask for: the host's GPU count, or `SLURM_MAX_GPUS` on SLURM. */
export function gpuLimit(host: LaunchHost): number {
  return host.kind === "slurm" ? SLURM_MAX_GPUS : host.gpus.length;
}

/** GPUs per run after picking `host`: 0 on a host without GPUs, else `prev` within 1..limit. */
export function gpusForHost(prev: number, host: LaunchHost): number {
  const limit = gpuLimit(host);
  if (limit === 0) return 0;
  return Math.min(Math.max(prev, 1), limit);
}

/** The preferred host when it can take the run, else the available host with most free GPUs. */
export function pickHost(
  hosts: readonly LaunchHost[],
  project: string,
  preferred: string | null,
  now: number = Date.now(),
): string | null {
  const ok = hosts.filter((h) => availability(h, project, now).ok);
  if (preferred !== null && ok.some((h) => h.name === preferred)) return preferred;
  let best: LaunchHost | null = null;
  for (const h of ok) {
    if (best === null || freeGpus(h).length > freeGpus(best).length) best = h;
  }
  return best === null ? null : best.name;
}

/**
 * How `n` seeds of `gpus` GPUs each land on `host` right now. SLURM queues every job itself.
 * Only SSH hosts run the hx queue; on the hub `queue` is ignored (it runs no scheduler).
 */
export function planLaunch(host: LaunchHost, gpus: number, n: number, queue: boolean): LaunchPlan {
  if (host.kind === "slurm") return { now: 0, queued: n, blocked: 0, cvd: [], firstPos: null };
  if (gpus <= 0) return { now: n, queued: 0, blocked: 0, cvd: [], firstPos: null };
  const free = freeGpus(host);
  const now = Math.min(n, Math.floor(free.length / gpus));
  const rest = n - now;
  const cvd = now > 0 ? free.slice(0, gpus) : [];
  if (host.kind === "ssh" && queue) {
    return { now, queued: rest, blocked: 0, cvd, firstPos: rest > 0 ? host.queue + 1 : null };
  }
  return { now, queued: 0, blocked: rest, cvd, firstPos: null };
}

/** `pos 4–5` for the waiting seeds; `""` when none waits in the hx queue. */
export function posRange(plan: LaunchPlan): string {
  if (plan.queued === 0 || plan.firstPos === null) return "";
  if (plan.queued === 1) return `pos ${plan.firstPos}`;
  return `pos ${plan.firstPos}–${plan.firstPos + plan.queued - 1}`;
}

/**
 * The footer line: `3 × 1 GPU on gpu1`, `3 jobs × 2 GPU, ≤ 08:00:00` (no `≤` part when the
 * time is left to the host's default), `3 runs on local, no GPU`.
 */
export function launchSummary(host: LaunchHost, gpus: number, n: number, time: string): string {
  if (host.kind === "slurm") {
    const t = time.trim();
    return `${n} ${n === 1 ? "job" : "jobs"} × ${gpus} GPU${t ? `, ≤ ${t}` : ""}`;
  }
  if (gpus === 0) return `${n} ${n === 1 ? "run" : "runs"} on ${host.name}, no GPU`;
  return `${n} × ${gpus} GPU on ${host.name}`;
}

/** Tooltip of a host row that can take the run. */
export function hostTitle(host: LaunchHost): string {
  if (host.kind === "slurm") {
    const s = host.slurm;
    return s ? `${host.name}: ${s.running} running, ${s.pending} pending in SLURM` : `${host.name}: SLURM`;
  }
  const names = [...new Set(host.gpus.map((g) => g.name))].join(", ");
  const kinds = names ? ` (${names})` : "";
  return `${host.name}: ${host.gpus.length} GPU${kinds}, ${freeGpus(host).length} free, ${host.queue} queued`;
}

/** Every `sbatch --time` form: `m`, `m:s`, `h:m:s`, `d-h`, `d-h:m`, `d-h:m:s`. */
export const SLURM_TIME = /^(\d+|\d+:\d{2}|\d+:\d{2}:\d{2}|\d+-\d+|\d+-\d+:\d{2}|\d+-\d+:\d{2}:\d{2})$/;

export function validSlurmTime(time: string): boolean {
  return SLURM_TIME.test(time.trim());
}

/**
 * The `slurm` launch field: only the fields the user filled in, plus GPUs per job.
 *
 * The backend merges it over the host's `SlurmDefaults` with `exclude_unset`, so every key
 * sent counts, even `null`: a blank field is left out to keep the host's partition, account
 * and time, and `extra` is never sent, so the host's extra `#SBATCH` lines stay.
 */
export function slurmBody(fields: SlurmFields, gpus: number): Partial<SlurmDefaults> {
  const body: Partial<SlurmDefaults> = {};
  const partition = fields.partition.trim();
  const account = fields.account.trim();
  const time = fields.time.trim();
  if (partition) body.partition = partition;
  if (account) body.account = account;
  if (time) body.time = time;
  body.gpus = gpus;
  return body;
}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd /Users/shreyasv/Desktop/code/research_dash/ui && bun test test/launch/plan.test.ts`
Expected: PASS, `16 pass`, `0 fail`.

- [ ] **Step 7: Typecheck**

Run: `cd /Users/shreyasv/Desktop/code/research_dash/ui && bun run typecheck`
Expected: exit 0, no output from `tsc`.

- [ ] **Step 8: Commit**

```bash
git -C /Users/shreyasv/Desktop/code/research_dash add ui/src/launch/plan.ts ui/test/launch/fixtures.ts ui/test/launch/plan.test.ts
git -C /Users/shreyasv/Desktop/code/research_dash commit -m "feat(ui): launch hosts, availability and GPU plan"
```

---

### Task 10: CLI text, sbatch line, form defaults and checks

**Files:**
- Create: `ui/src/launch/cli.ts`
- Create: `ui/src/launch/draft.ts`
- Test: `ui/test/launch/cli.test.ts`, `ui/test/launch/draft.test.ts`

**Interfaces:**
- Consumes: `LaunchSpec`, `LaunchHost`, `LaunchPlan`, `SlurmFields`, `availability`, `freeGpus`, `planLaunch`, `validSlurmTime` (Task 9); `parseSeeds`, `nextSeeds` (Task 8); `splitCommand`, `hasSeedSlot` (Task 8); `shellJoin` from `ui/src/pages/components/format.ts`; `RunRecord` from `ui/src/api/models.ts`.
- Produces (`ui/src/launch/cli.ts`):
  - `cliQuote(arg: string): string` (quotes anything outside `[A-Za-z0-9_\-+=/.,:@%]`, so `{seed}` becomes `'{seed}'`)
  - `launchCliLine(spec: LaunchSpec, seed: number): string`, `launchCli(spec: LaunchSpec, seeds: readonly number[]): string` (one line per seed, `\n`-joined; `--partition`, `--time`, `--account` only when filled in, so the host's defaults apply as in the API body; with a pinned `commit`, a first comment line `# code: commit <sha>; hx launch runs the checkout as it is`, since `hx launch` has no commit flag)
  - `sbatchLine(slurm: SlurmFields, gpus: number): string` (the same rule)
- Produces (`ui/src/launch/draft.ts`):
  - `interface LaunchDraft { host: string | null; gpus: number; queue: boolean; seeds: string; command: string; hypothesis: string; partition: string; account: string; time: string }`, `DEFAULT_DRAFT: LaunchDraft` (partition, account and time start blank: blank means the host's `SlurmDefaults`)
  - `interface Carry { params: Record<string, string>; vars: Record<string, string> }`, `NO_CARRY: Carry`
  - `pinnedCommit(template: RunRecord | null): string | null` (the template's `git.commit` when it had no uncommitted changes, else null: the dialog cannot send that run's diff, so the hub pins its own checkout instead)
  - `interface LaunchDefaults { draft: Partial<LaunchDraft>; carry: Carry }`, `launchDefaults(template: RunRecord | null, runs: readonly RunRecord[]): LaunchDefaults`
  - `NO_SEED_WARNING`, `TIME_ERROR`, `SLURM_VALUE` (`/^[A-Za-z0-9_.:+@\/,-]*$/`, the backend's `_SAFE_VALUE` characters), `slurmValueError(field: "partition" | "account"): string`
  - `interface DraftCheck { seeds: number[]; pending: number[]; argv: string[]; plan: LaunchPlan | null; blockers: string[]; warnings: string[]; seedsError: string | null; commandError: string | null; timeError: string | null; partitionError: string | null; accountError: string | null }` (`pending`: the seeds not started yet; `plan` and the GPU blocker count only those, so a retry after a partial launch is not blocked by GPUs the started seeds now hold) (on a SLURM host a filled partition or account with whitespace or shell characters blocks Launch: the backend's `validate_defaults` would refuse it only when it renders sbatch, so every seed would be created and then fail)
  - `checkDraft(draft: LaunchDraft, host: LaunchHost | null, project: string, now?: number, started?: readonly number[]): DraftCheck`

- [ ] **Step 1: Write the failing tests**

Create `ui/test/launch/cli.test.ts`:

```ts
import { expect, test } from "bun:test";

import { cliQuote, launchCli, launchCliLine, sbatchLine } from "../../src/launch/cli";
import type { LaunchSpec } from "../../src/launch/plan";
import { launchHost } from "./fixtures";

const SPEC: LaunchSpec = {
  host: launchHost({ name: "gpu1", kind: "ssh" }),
  project: "rxn-forward",
  repo: "/Users/sv/code/rxn-forward",
  commit: null,
  task: "uspto-forward-top1",
  argv: ["python", "train.py", "--lr", "3e-4", "--seed", "{seed}"],
  hypothesis: "beam 10 at lr 3e-4 holds",
  gpus: 1,
  queue: true,
  slurm: null,
  params: {},
  vars: {},
};
const TAIL = "-H 'beam 10 at lr 3e-4 holds' -- python train.py --lr 3e-4 --seed '{seed}'";

test("cliQuote leaves plain words alone and quotes braces, spaces, quotes and $", () => {
  expect(cliQuote("train.py")).toBe("train.py");
  expect(cliQuote("3e-4")).toBe("3e-4");
  expect(cliQuote("{seed}")).toBe("'{seed}'");
  expect(cliQuote("--seed={seed}")).toBe("'--seed={seed}'");
  expect(cliQuote("a b")).toBe("'a b'");
  expect(cliQuote("it's")).toBe(`'it'"'"'s'`);
  expect(cliQuote("")).toBe("''");
  expect(cliQuote("$HOME")).toBe("'$HOME'");
});

test("one hx launch line per seed on an ssh host, with --queue", () => {
  expect(launchCli(SPEC, [4, 5])).toBe(
    [
      `hx launch --repo /Users/sv/code/rxn-forward -t uspto-forward-top1 --host gpu1 --gpus 1 --queue --seed 4 ${TAIL}`,
      `hx launch --repo /Users/sv/code/rxn-forward -t uspto-forward-top1 --host gpu1 --gpus 1 --queue --seed 5 ${TAIL}`,
    ].join("\n"),
  );
  expect(launchCliLine({ ...SPEC, queue: false }, 4)).toBe(
    `hx launch --repo /Users/sv/code/rxn-forward -t uspto-forward-top1 --host gpu1 --gpus 1 --seed 4 ${TAIL}`,
  );
});

test("a SLURM host gets --partition, --time and --account only when filled in, never --queue", () => {
  const spec: LaunchSpec = {
    ...SPEC,
    host: launchHost({ name: "mccleary", kind: "slurm" }),
    gpus: 2,
    slurm: { partition: "gpu", account: "", time: "08:00:00" },
  };
  expect(launchCliLine(spec, 4)).toBe(
    `hx launch --repo /Users/sv/code/rxn-forward -t uspto-forward-top1 --host mccleary --gpus 2 --partition gpu --time 08:00:00 --seed 4 ${TAIL}`,
  );
  const account: LaunchSpec = { ...spec, slurm: { partition: "", account: "lab one", time: "1-00:00:00" } };
  expect(launchCliLine(account, 4)).toBe(
    `hx launch --repo /Users/sv/code/rxn-forward -t uspto-forward-top1 --host mccleary --gpus 2 --time 1-00:00:00 --account 'lab one' --seed 4 ${TAIL}`,
  );
  // all blank: the host's partition, account and time apply, so no flag is sent
  const blank: LaunchSpec = { ...spec, slurm: { partition: "", account: "", time: " " } };
  expect(launchCliLine(blank, 4)).toBe(
    `hx launch --repo /Users/sv/code/rxn-forward -t uspto-forward-top1 --host mccleary --gpus 2 --seed 4 ${TAIL}`,
  );
});

test("the hub has no --host; params and vars carry over; quotes in the hypothesis survive", () => {
  const spec: LaunchSpec = {
    ...SPEC,
    host: launchHost({ name: "local", kind: "hub", projects: null }),
    task: null,
    gpus: 0,
    hypothesis: `it's "fast" `,
    params: { lr: "3e-4" },
    vars: { config: "configs/aug.yaml" },
  };
  expect(launchCliLine(spec, 7)).toBe(
    `hx launch --repo /Users/sv/code/rxn-forward --seed 7 --param lr=3e-4 --var config=configs/aug.yaml -H 'it'"'"'s "fast"' -- python train.py --lr 3e-4 --seed '{seed}'`,
  );
});

test("a pinned commit is named in a comment line: hx launch has no commit flag", () => {
  const sha = "8f4cac43877b75953f18ff1daf7e6fc54a5d8f37";
  expect(launchCli({ ...SPEC, commit: sha }, [4]).split("\n")).toEqual([
    `# code: commit ${sha}; hx launch runs the checkout as it is`,
    `hx launch --repo /Users/sv/code/rxn-forward -t uspto-forward-top1 --host gpu1 --gpus 1 --queue --seed 4 ${TAIL}`,
  ]);
  expect(launchCli(SPEC, [4]).startsWith("hx launch ")).toBe(true);
});

test("sbatchLine shows the flags hx passes to sbatch", () => {
  expect(sbatchLine({ partition: "gpu", account: "", time: "08:00:00" }, 2)).toBe(
    "sbatch --partition gpu --time 08:00:00 --gpus 2",
  );
  expect(sbatchLine({ partition: "", account: "lab", time: " 30 " }, 0)).toBe("sbatch --time 30 --account lab");
  expect(sbatchLine({ partition: "", account: "", time: "" }, 2)).toBe("sbatch --gpus 2");
});
```

Create `ui/test/launch/draft.test.ts`:

```ts
import { describe, expect, test } from "bun:test";

import {
  DEFAULT_DRAFT,
  type LaunchDraft,
  NO_SEED_WARNING,
  TIME_ERROR,
  checkDraft,
  launchDefaults,
  pinnedCommit,
  slurmValueError,
} from "../../src/launch/draft";
import { toLaunchHosts } from "../../src/launch/plan";
import { makeRecord } from "../pages/fixtures";
import { CMD, GPU1, PROJECT, gpu, launchHost } from "./fixtures";

const G1 = toLaunchHosts([GPU1], { gpus: [], queue: 0 })[1] ?? launchHost();
const OK: LaunchDraft = {
  ...DEFAULT_DRAFT,
  host: "gpu1",
  seeds: "4, 5, 6",
  command: CMD,
  hypothesis: "beam 10 holds",
};

describe("launchDefaults", () => {
  test("no template: seeds 1, 2, 3 and nothing carried", () => {
    expect(launchDefaults(null, [])).toEqual({
      draft: { seeds: "1, 2, 3" },
      carry: { params: {}, vars: {} },
    });
  });

  test("the template's command, its params and vars, and the next unused seeds of its config", () => {
    const template = makeRecord({
      run_id: "r3",
      command_template: ["python", "train.py", "--lr", "3e-4", "--seed", "{seed}"],
      seed: 3,
      config_hash: "sha256:aaaa",
      params: { lr: "3e-4" },
      vars: { config: "configs/aug.yaml" },
    });
    const runs = [
      makeRecord({ run_id: "r1", seed: 1, config_hash: "sha256:aaaa" }),
      makeRecord({ run_id: "r2", seed: 2, config_hash: "sha256:aaaa" }),
      makeRecord({ run_id: "r9", seed: 9, config_hash: "sha256:bbbb" }),
    ];
    expect(launchDefaults(template, runs)).toEqual({
      draft: { command: "python train.py --lr 3e-4 --seed {seed}", seeds: "4, 5, 6" },
      carry: { params: { lr: "3e-4" }, vars: { config: "configs/aug.yaml" } },
    });
  });

  test("falls back to the rendered command when the template is empty", () => {
    const template = makeRecord({ command_template: [], command: ["python", "x.py", "--seed=3"], seed: null });
    expect(launchDefaults(template, []).draft).toEqual({ command: "python x.py --seed=3", seeds: "1, 2, 3" });
  });

  test("pinnedCommit: the template's commit when it was clean, else none (the hub pins its own)", () => {
    const clean = makeRecord();
    expect(pinnedCommit(clean)).toBe("8f4cac43877b75953f18ff1daf7e6fc54a5d8f37");
    // a dirty run's diff is not available to the dialog: pinning the bare commit would drop it
    expect(pinnedCommit(makeRecord({ git: { ...clean.git, dirty: true } }))).toBeNull();
    expect(pinnedCommit(makeRecord({ git: { ...clean.git, commit: null } }))).toBeNull();
    expect(pinnedCommit(null)).toBeNull();
  });
});

describe("checkDraft", () => {
  test("a complete draft has no blockers", () => {
    const c = checkDraft(OK, G1, PROJECT);
    expect(c.blockers).toEqual([]);
    expect(c.warnings).toEqual([]);
    expect(c.seeds).toEqual([4, 5, 6]);
    expect(c.argv).toEqual(["python", "train.py", "--lr", "3e-4", "--seed", "{seed}"]);
    expect(c.plan).toEqual({ now: 1, queued: 2, blocked: 0, cvd: [5], firstPos: 4 });
  });

  test("blockers come in field order", () => {
    const c = checkDraft({ ...OK, seeds: "x", command: "python 'oops", hypothesis: "  " }, null, PROJECT);
    expect(c.blockers).toEqual([
      "pick a host",
      "seeds: bad seed x",
      "command: unclosed ' quote",
      "hypothesis required",
    ]);
    expect(c.seedsError).toBe("bad seed x");
    expect(c.commandError).toBe("unclosed ' quote");
    expect(c.plan).toBeNull();
  });

  test("an empty command is a blocker", () => {
    expect(checkDraft({ ...OK, command: "   " }, G1, PROJECT).blockers).toEqual(["command: empty"]);
  });

  test("a host that cannot take the run blocks with its reason", () => {
    expect(checkDraft(OK, { ...G1, projects: [] }, PROJECT).blockers).toEqual([
      "no path for rxn-forward on gpu1: hx hosts map rxn-forward gpu1 <path>",
    ]);
  });

  test("a SLURM host needs a valid --time, or none (the host's default)", () => {
    const slurm = launchHost({ name: "mccleary", kind: "slurm" });
    const bad = checkDraft({ ...OK, host: "mccleary", time: "8h" }, slurm, PROJECT);
    expect(bad.blockers).toEqual([TIME_ERROR]);
    expect(bad.timeError).toBe(TIME_ERROR);
    expect(checkDraft({ ...OK, host: "mccleary", time: "08:00:00" }, slurm, PROJECT).blockers).toEqual([]);
    expect(DEFAULT_DRAFT.time).toBe("");
    expect(checkDraft({ ...OK, host: "mccleary" }, slurm, PROJECT).blockers).toEqual([]);
  });

  test("a SLURM partition or account with spaces or shell characters blocks Launch", () => {
    const slurm = launchHost({ name: "mccleary", kind: "slurm" });
    const c = checkDraft({ ...OK, host: "mccleary", partition: "gpu a100", account: "lab;rm" }, slurm, PROJECT);
    expect(c.blockers).toEqual([slurmValueError("partition"), slurmValueError("account")]);
    expect(slurmValueError("partition")).toBe("partition: use letters, digits and _ . : + @ / , - only");
    expect([c.partitionError, c.accountError]).toEqual([slurmValueError("partition"), slurmValueError("account")]);
    const ok = checkDraft({ ...OK, host: "mccleary", partition: "gpu,scavenge", account: "pi_lab" }, slurm, PROJECT);
    expect(ok.blockers).toEqual([]);
    // the fields only matter on SLURM hosts
    expect(checkDraft({ ...OK, partition: "gpu a100" }, G1, PROJECT).blockers).toEqual([]);
  });

  test("queue off: seeds that cannot start block Launch", () => {
    expect(checkDraft({ ...OK, queue: false }, G1, PROJECT).blockers).toEqual([
      "2 won't start: 1 GPU free; turn on Queue",
    ]);
  });

  test("the hub never queues: seeds beyond its free GPUs block Launch", () => {
    const hub = launchHost({ name: "local", kind: "hub", projects: null, gpus: [gpu(0), gpu(1)] });
    expect(checkDraft({ ...OK, host: "local" }, hub, PROJECT).blockers).toEqual([
      "1 won't start: 2 GPU free on local",
    ]);
  });

  test("after a partial launch, only the seeds not started need free GPUs", () => {
    // seed 4 started on the hub and now holds GPU 0; seed 5 was refused and is sent again
    const hub = launchHost({ name: "local", kind: "hub", projects: null, gpus: [gpu(0, { run_id: "r-s4" }), gpu(1)] });
    const draft = { ...OK, host: "local", seeds: "4, 5" };
    expect(checkDraft(draft, hub, PROJECT).blockers).toEqual(["1 won't start: 1 GPU free on local"]);
    const retry = checkDraft(draft, hub, PROJECT, Date.now(), [4]);
    expect(retry.blockers).toEqual([]);
    expect([retry.seeds, retry.pending]).toEqual([[4, 5], [5]]);
    expect(retry.plan).toEqual({ now: 1, queued: 0, blocked: 0, cvd: [1], firstPos: null });
  });

  test("warnings: no {seed} with several seeds, and shell operators", () => {
    expect(checkDraft({ ...OK, command: "python train.py" }, G1, PROJECT).warnings).toEqual([NO_SEED_WARNING]);
    expect(checkDraft({ ...OK, seeds: "4", command: "python train.py" }, G1, PROJECT).warnings).toEqual([]);
    expect(
      checkDraft({ ...OK, command: "python a.py --seed {seed} && echo done" }, G1, PROJECT).warnings,
    ).toEqual(["&& is passed to the program as text; use sh -c '…' for shell syntax"]);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/shreyasv/Desktop/code/research_dash/ui && bun test test/launch/cli.test.ts test/launch/draft.test.ts`
Expected: FAIL with `Cannot find module '../../src/launch/cli'` (and `draft`).

- [ ] **Step 3: Write the implementation**

Create `ui/src/launch/cli.ts`:

```ts
/**
 * "Copy as CLI": the exact `hx launch` lines the dialog would run, one per seed, quoted for
 * `sh`/`bash`/`zsh`. `{seed}` is always quoted (a shell can drop or expand a bare one).
 */
import type { LaunchSpec, SlurmFields } from "./plan";

const CLI_SAFE = /^[A-Za-z0-9_\-+=/.,:@%]+$/;

/** Quote one argument for a POSIX shell; plain words stay bare. */
export function cliQuote(arg: string): string {
  if (arg === "") return "''";
  return CLI_SAFE.test(arg) ? arg : `'${arg.replace(/'/g, `'"'"'`)}'`;
}

/** One `hx launch` command for one seed. */
export function launchCliLine(spec: LaunchSpec, seed: number): string {
  const parts = ["hx", "launch", "--repo", cliQuote(spec.repo)];
  if (spec.task !== null) parts.push("-t", cliQuote(spec.task));
  if (spec.host.kind !== "hub") parts.push("--host", cliQuote(spec.host.name));
  if (spec.gpus > 0) parts.push("--gpus", String(spec.gpus));
  if (spec.host.kind === "ssh" && spec.queue) parts.push("--queue");
  if (spec.host.kind === "slurm" && spec.slurm !== null) {
    // blank fields keep the host's defaults, as in the API body (`slurmBody`)
    const partition = spec.slurm.partition.trim();
    const time = spec.slurm.time.trim();
    const account = spec.slurm.account.trim();
    if (partition) parts.push("--partition", cliQuote(partition));
    if (time) parts.push("--time", cliQuote(time));
    if (account) parts.push("--account", cliQuote(account));
  }
  parts.push("--seed", String(seed));
  for (const [key, value] of Object.entries(spec.params)) parts.push("--param", cliQuote(`${key}=${value}`));
  for (const [key, value] of Object.entries(spec.vars)) parts.push("--var", cliQuote(`${key}=${value}`));
  parts.push("-H", cliQuote(spec.hypothesis.trim()), "--", ...spec.argv.map(cliQuote));
  return parts.join(" ");
}

/**
 * One `hx launch` line per seed, newline-separated. `hx launch` has no commit flag, so a
 * pinned commit (Rerun sweep) is named in a first comment line, harmless when pasted.
 */
export function launchCli(spec: LaunchSpec, seeds: readonly number[]): string {
  const lines = seeds.map((seed) => launchCliLine(spec, seed));
  if (spec.commit !== null) lines.unshift(`# code: commit ${spec.commit}; hx launch runs the checkout as it is`);
  return lines.join("\n");
}

/** The sbatch flags the dialog sets for a SLURM run (spec 8A.5); the host's defaults fill the rest. */
export function sbatchLine(slurm: SlurmFields, gpus: number): string {
  const parts = ["sbatch"];
  const partition = slurm.partition.trim();
  const time = slurm.time.trim();
  const account = slurm.account.trim();
  if (partition) parts.push("--partition", cliQuote(partition));
  if (time) parts.push("--time", cliQuote(time));
  if (gpus > 0) parts.push("--gpus", String(gpus));
  if (account) parts.push("--account", cliQuote(account));
  return parts.join(" ");
}
```

Create `ui/src/launch/draft.ts`:

```ts
/**
 * The Launch dialog's form: its fields, the defaults taken from a template run, and the
 * checks that decide whether Launch is enabled (blockers) or only advised against (warnings).
 */
import type { RunRecord } from "../api/models";
import { shellJoin } from "../pages/components/format";
import { hasSeedSlot, splitCommand } from "./command";
import { type LaunchHost, type LaunchPlan, availability, freeGpus, planLaunch, validSlurmTime } from "./plan";
import { nextSeeds, parseSeeds } from "./seeds";

export interface LaunchDraft {
  host: string | null;
  /** GPUs per run (per job on SLURM). */
  gpus: number;
  /** Wait for GPUs in the hx queue (SSH hosts only). */
  queue: boolean;
  seeds: string;
  command: string;
  hypothesis: string;
  /** SLURM fields; blank means the host's `SlurmDefaults` value (nothing is sent). */
  partition: string;
  account: string;
  time: string;
}

export const DEFAULT_DRAFT: LaunchDraft = {
  host: null,
  gpus: 1,
  queue: true,
  seeds: "1, 2, 3",
  command: "",
  hypothesis: "",
  partition: "",
  account: "",
  time: "",
};

/** Template params and vars sent with every launch, so `{config}`-style slots still fill. */
export interface Carry {
  params: Record<string, string>;
  vars: Record<string, string>;
}

export const NO_CARRY: Carry = { params: {}, vars: {} };

/**
 * The commit a launch from `template` pins (spec 8A.4): the template's commit when it had no
 * uncommitted changes. A dirty run's diff is not available here, and a bare commit would
 * drop it, so then nothing is pinned and the hub pins its own checkout's HEAD and diff.
 */
export function pinnedCommit(template: RunRecord | null): string | null {
  if (template === null || template.git.dirty) return null;
  return template.git.commit ?? null;
}

export interface LaunchDefaults {
  draft: Partial<LaunchDraft>;
  carry: Carry;
}

export const NO_SEED_WARNING = "no {seed} in the command: every seed runs the same command";
export const TIME_ERROR = "time: use h:mm:ss or d-hh:mm:ss";

/** Characters an `#SBATCH` value may hold (the backend's `_SAFE_VALUE`, checked in `validate_defaults`). */
export const SLURM_VALUE = /^[A-Za-z0-9_.:+@\/,-]*$/;

/** The blocker for a partition or account the backend would refuse. */
export function slurmValueError(field: "partition" | "account"): string {
  return `${field}: use letters, digits and _ . : + @ / , - only`;
}

/**
 * Defaults from a template run (the best config's latest run): its command template, its
 * params and vars, and the next three seeds after every seed used by runs of the same config.
 */
export function launchDefaults(template: RunRecord | null, runs: readonly RunRecord[]): LaunchDefaults {
  if (template === null) return { draft: { seeds: nextSeeds([]).join(", ") }, carry: NO_CARRY };
  const argv = template.command_template.length > 0 ? template.command_template : template.command;
  const used = runs.filter((r) => r.config_hash === template.config_hash).map((r) => r.seed);
  used.push(template.seed);
  return {
    draft: { command: shellJoin(argv), seeds: nextSeeds(used).join(", ") },
    carry: { params: { ...template.params }, vars: { ...template.vars } },
  };
}

export interface DraftCheck {
  seeds: number[];
  /** Seeds not started yet by this dialog: the ones Launch sends, and the GPU plan counts. */
  pending: number[];
  argv: string[];
  plan: LaunchPlan | null;
  /** Reasons Launch is disabled, in field order; empty when it may launch. */
  blockers: string[];
  warnings: string[];
  seedsError: string | null;
  commandError: string | null;
  timeError: string | null;
  partitionError: string | null;
  accountError: string | null;
}

/**
 * Validate the form against the chosen host. `started` are the seeds this dialog launched
 * already: they are never sent again, so the GPU plan (and its blocker) counts only the rest.
 */
export function checkDraft(
  draft: LaunchDraft,
  host: LaunchHost | null,
  project: string,
  now: number = Date.now(),
  started: readonly number[] = [],
): DraftCheck {
  const blockers: string[] = [];
  const warnings: string[] = [];
  if (host === null) {
    blockers.push("pick a host");
  } else {
    const av = availability(host, project, now);
    if (!av.ok) blockers.push(av.reason);
  }
  const parsed = parseSeeds(draft.seeds);
  if (parsed.error !== null) blockers.push(`seeds: ${parsed.error}`);
  const split = splitCommand(draft.command);
  const commandError = split.error ?? (split.argv.length === 0 ? "empty" : null);
  if (commandError !== null) blockers.push(`command: ${commandError}`);
  if (!draft.hypothesis.trim()) blockers.push("hypothesis required");
  const slurm = host?.kind === "slurm";
  const timeError = slurm && draft.time.trim() !== "" && !validSlurmTime(draft.time) ? TIME_ERROR : null;
  if (timeError !== null) blockers.push(timeError);
  const partitionError = slurm && !SLURM_VALUE.test(draft.partition.trim()) ? slurmValueError("partition") : null;
  if (partitionError !== null) blockers.push(partitionError);
  const accountError = slurm && !SLURM_VALUE.test(draft.account.trim()) ? slurmValueError("account") : null;
  if (accountError !== null) blockers.push(accountError);
  const pending = parsed.seeds.filter((seed) => !started.includes(seed));
  const plan = host === null ? null : planLaunch(host, draft.gpus, pending.length, draft.queue);
  if (host !== null && plan !== null && plan.blocked > 0) {
    const free = freeGpus(host).length;
    blockers.push(
      host.kind === "ssh"
        ? `${plan.blocked} won't start: ${free} GPU free; turn on Queue`
        : `${plan.blocked} won't start: ${free} GPU free on ${host.name}`,
    );
  }
  if (parsed.seeds.length > 1 && split.argv.length > 0 && !hasSeedSlot(split.argv)) {
    warnings.push(NO_SEED_WARNING);
  }
  const op = split.operators[0];
  if (op !== undefined) warnings.push(`${op} is passed to the program as text; use sh -c '…' for shell syntax`);
  return {
    seeds: parsed.seeds,
    pending,
    argv: split.argv,
    plan,
    blockers,
    warnings,
    seedsError: parsed.error,
    commandError,
    timeError,
    partitionError,
    accountError,
  };
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/shreyasv/Desktop/code/research_dash/ui && bun test test/launch/cli.test.ts test/launch/draft.test.ts`
Expected: PASS, `20 pass`, `0 fail`.

- [ ] **Step 5: Typecheck**

Run: `cd /Users/shreyasv/Desktop/code/research_dash/ui && bun run typecheck`
Expected: exit 0.

- [ ] **Step 6: Commit**

```bash
git -C /Users/shreyasv/Desktop/code/research_dash add ui/src/launch/cli.ts ui/src/launch/draft.ts ui/test/launch/cli.test.ts ui/test/launch/draft.test.ts
git -C /Users/shreyasv/Desktop/code/research_dash commit -m "feat(ui): launch CLI text, defaults and form checks"
```

---

### Task 11: Launch API calls with per-seed command ids

**Files:**
- Create: `ui/src/launch/launchApi.ts`
- Test: `ui/test/launch/launchApi.test.ts`

**Interfaces:**
- Consumes: `api.hosts`, `api.gpus`, `api.queue`, `api.launch`, `api.launchOnHost` from `ui/src/api/client.ts` (Task 2; every write adds `command_id` and `created_by: "human"`); `HOSTS_REFETCH_MS`, `fetchHosts`, `queryKeys` from `ui/src/api/queries.ts` (Task 3); `GpuInfo`, `HostLaunchRequest`, `LaunchRequest`, `QueueEntry`, `RunFields`, `RunRecord` from `ui/src/api/models.ts` (Task 1); `shouldRetry`, `ACTION_RETRY_DELAY_MS` from `ui/src/pages/components/useAction.ts`; `LaunchHost`, `LaunchSpec`, `slurmBody`, `toLaunchHosts` (Task 9).
- Produces (`ui/src/launch/launchApi.ts`):
  - `fetchLaunchHosts(signal?: AbortSignal, qc?: QueryClient): Promise<LaunchHost[]>` (hub `gpus`/`queue` failures count as none; with `qc` the hosts list goes through the shared `["hosts"]` query (`fetchHosts`, Task 3), so a stale host keeps its last known GPUs and queue, as on the Overview)
  - `LAUNCH_HOSTS_KEY = ["hosts", "launch"]` (under the `["hosts"]` family the event stream invalidates; its own key because the data is `LaunchHost[]`, not `HostRow[]`), `useLaunchHosts()` (polls every `HOSTS_REFETCH_MS`, passes its query client)
  - `launchRequest(spec: LaunchSpec, seed: number): LaunchRequest | HostLaunchRequest` (the body without the action fields: the hub gets `repo`; any other host gets `project` and never a path; both get `commit` when the spec pins one)
  - `seedCommandId(base: string, seed: number): string` → `"<base>.s<seed>"`
  - `postLaunch(spec, seed, commandId): Promise<RunRecord>` (hub: `api.launch`; any other host: `api.launchOnHost`)
  - `interface LaunchOutcome { records: RunRecord[]; failed: { seed: number; error: Error } | null }`
  - `launchSeeds(spec, seeds: readonly number[], base: string, opts?: { onProgress?: (done: number) => void; delayMs?: number }): Promise<LaunchOutcome>` — sequential, stops at the first refused seed, retries only unanswered requests (twice) with the same id.

- [ ] **Step 1: Check the client has the launch functions**

Run: `grep -cE '^  (hosts|gpus|queue|launch|launchOnHost): \(' /Users/shreyasv/Desktop/code/research_dash/ui/src/api/client.ts`
Expected: `5`. If lower, stop: Task 2 is not done.

- [ ] **Step 2: Write the failing tests**

Create `ui/test/launch/launchApi.test.ts`:

```ts
import { afterEach, describe, expect, test } from "bun:test";
import { QueryClient } from "@tanstack/react-query";

import type { RunRecord } from "../../src/api/models";
import { fetchLaunchHosts, launchRequest, launchSeeds, seedCommandId } from "../../src/launch/launchApi";
import { type LaunchSpec, gpuCells } from "../../src/launch/plan";
import { makeRecord } from "../pages/fixtures";
import { type Call, HttpReply, mockApi, restoreFetch } from "../pages/helpers";
import { GPU1, gpu, hostRow, launchHost } from "./fixtures";

afterEach(restoreFetch);

const SPEC: LaunchSpec = {
  host: launchHost(),
  project: "rxn-forward",
  repo: "/Users/sv/code/rxn-forward",
  commit: null,
  task: "uspto-forward-top1",
  argv: ["python", "train.py", "--seed", "{seed}"],
  hypothesis: " beam 10 holds ",
  gpus: 1,
  queue: true,
  slurm: null,
  params: { lr: "3e-4" },
  vars: {},
};
const rec = (seed: number): RunRecord =>
  makeRecord({ run_id: `20261003-120000-uspto-forward-top1-s${seed}`, seed, status: "queued" });
const seedOf = (call: Call): number => (call.body as { seed: number }).seed;
const idOf = (call: Call): string => (call.body as { command_id: string }).command_id;

describe("fetchLaunchHosts", () => {
  test("puts the hub first with its own GPUs and queue", async () => {
    mockApi({
      "GET /api/v1/hosts": [GPU1],
      "GET /api/v1/gpus": [gpu(0, { name: "RTX 4090" })],
      "GET /api/v1/queue": [{ run_id: "r1", position: 1, gpus_requested: 1 }],
    });
    const hosts = await fetchLaunchHosts();
    expect(hosts.map((h) => [h.name, h.kind, h.queue])).toEqual([
      ["local", "hub", 1],
      ["gpu1", "ssh", 3],
    ]);
    expect(hosts[0]?.gpus.map((g) => g.name)).toEqual(["RTX 4090"]);
  });

  test("a hub without the env routes still lists itself, with no GPUs", async () => {
    mockApi({ "GET /api/v1/hosts": [] });
    expect(await fetchLaunchHosts()).toEqual([
      {
        name: "local",
        kind: "hub",
        state: "connected",
        since: null,
        message: "",
        gpus: [],
        queue: 0,
        slurm: null,
        projects: null,
      },
    ]);
  });

  test("uses the hub's own row when the hosts list has one", async () => {
    mockApi({
      "GET /api/v1/hosts": [hostRow("local", { queue: 2 }), GPU1],
      "GET /api/v1/gpus": [],
      "GET /api/v1/queue": [],
    });
    const hosts = await fetchLaunchHosts();
    expect(hosts.map((h) => h.name)).toEqual(["local", "gpu1"]);
    expect(hosts[0]).toMatchObject({ kind: "hub", queue: 2, projects: null });
  });

  test("a failing hosts list is an error", async () => {
    mockApi({ "GET /api/v1/hosts": new HttpReply(500, { error: "hub index locked", type: "IndexError" }) });
    await expect(fetchLaunchHosts()).rejects.toThrow("hub index locked");
  });

  test("with the query client, a stale host keeps the GPUs and queue it had while connected", async () => {
    const qc = new QueryClient();
    const hub = { "GET /api/v1/gpus": [], "GET /api/v1/queue": [] };
    mockApi({ ...hub, "GET /api/v1/hosts": [GPU1] });
    expect((await fetchLaunchHosts(undefined, qc))[1]?.gpus).toHaveLength(8);
    // the hub sends no GPUs and queue 0 once the host is stale
    const stale = { ...GPU1, gpus: [], queue: 0, state: { ...GPU1.state, state: "stale" as const } };
    mockApi({ ...hub, "GET /api/v1/hosts": [stale] });
    const hosts = await fetchLaunchHosts(undefined, qc);
    expect([hosts[1]?.state, hosts[1]?.gpus.length, hosts[1]?.queue]).toEqual(["stale", 8, 3]);
    expect(gpuCells(hosts[1] ?? launchHost())).toEqual(Array(8).fill("stale"));
  });
});

test("launchRequest: a host launch names the project, never a path; the hub gets its repo", () => {
  expect(launchRequest(SPEC, 4)).toEqual({
    project: "rxn-forward",
    task: "uspto-forward-top1",
    command: ["python", "train.py", "--seed", "{seed}"],
    hypothesis: "beam 10 holds",
    seed: 4,
    tags: [],
    params: { lr: "3e-4" },
    vars: {},
    gpus: 1,
    queue: true,
  });
  const slurm = launchRequest(
    {
      ...SPEC,
      host: launchHost({ name: "mccleary", kind: "slurm" }),
      gpus: 2,
      slurm: { partition: "", account: "lab", time: "08:00:00" },
    },
    4,
  );
  expect(slurm.queue).toBe(false);
  expect(slurm.slurm).toEqual({ account: "lab", time: "08:00:00", gpus: 2 });
  const hub = launchRequest({ ...SPEC, host: launchHost({ name: "local", kind: "hub", projects: null }), gpus: 0 }, 4);
  expect(hub.queue).toBe(false);
  expect("slurm" in hub).toBe(false);
  expect(["repo" in hub, "project" in hub]).toEqual([true, false]);
  expect((hub as { repo: string }).repo).toBe("/Users/sv/code/rxn-forward");
  // the hub pins its own checkout unless the spec pins a commit; the dialog never sends a diff
  expect(["commit" in hub, "diff" in hub]).toEqual([false, false]);
  const sha = "8f4cac43877b75953f18ff1daf7e6fc54a5d8f37";
  const pinned = launchRequest({ ...SPEC, commit: sha }, 4);
  expect([pinned.commit, "repo" in pinned, "diff" in pinned]).toEqual([sha, false, false]);
});

test("a blank-field SLURM launch body has no partition, account, time or extra keys", () => {
  // the backend merges the body over the host's SlurmDefaults (exclude_unset): any key sent,
  // even null, would wipe the host's partition, account, time or extra #SBATCH lines
  const body = launchRequest(
    {
      ...SPEC,
      host: launchHost({ name: "mccleary", kind: "slurm" }),
      gpus: 2,
      slurm: { partition: "", account: "", time: "" },
    },
    4,
  );
  expect(body.slurm).toEqual({ gpus: 2 });
  expect(Object.keys(body.slurm ?? {})).toEqual(["gpus"]);
});

describe("launchSeeds", () => {
  test("posts one run per seed, in order, each with its own stable command_id", async () => {
    const calls = mockApi({ "POST /api/v1/hosts/gpu1/runs": (call: Call) => rec(seedOf(call)) });
    const progress: number[] = [];
    const out = await launchSeeds(SPEC, [4, 5, 6], "base", { onProgress: (done) => progress.push(done) });
    expect(out.failed).toBeNull();
    expect(out.records.map((r) => r.seed)).toEqual([4, 5, 6]);
    expect(calls.map(idOf)).toEqual(["base.s4", "base.s5", "base.s6"]);
    expect((calls[0]?.body as { created_by: string }).created_by).toBe("human");
    expect(progress).toEqual([1, 2, 3]);
    expect(seedCommandId("base", 4)).toBe("base.s4");
  });

  test("the hub launches through POST /api/v1/runs", async () => {
    const calls = mockApi({ "POST /api/v1/runs": (call: Call) => rec(seedOf(call)) });
    const hub = { ...SPEC, host: launchHost({ name: "local", kind: "hub", projects: null }) };
    await launchSeeds(hub, [1], "base");
    expect(calls.map((c) => c.url)).toEqual(["/api/v1/runs"]);
  });

  test("stops at the first refused seed and reports it; a 4xx is not retried", async () => {
    const calls = mockApi({
      "POST /api/v1/hosts/gpu1/runs": (call: Call) =>
        seedOf(call) === 5
          ? new HttpReply(400, { error: "asked for 2 GPUs; this host has 1", type: "RunError" })
          : rec(seedOf(call)),
    });
    const out = await launchSeeds(SPEC, [4, 5, 6], "base", { delayMs: 0 });
    expect(out.records.map((r) => r.seed)).toEqual([4]);
    expect(out.failed?.seed).toBe(5);
    expect(out.failed?.error.message).toBe("asked for 2 GPUs; this host has 1");
    expect(calls.map(idOf)).toEqual(["base.s4", "base.s5"]);
  });

  test("retries a dropped request with the same command_id", async () => {
    let drops = 1;
    const calls = mockApi({
      "POST /api/v1/hosts/gpu1/runs": (call: Call) => {
        if (drops > 0) {
          drops -= 1;
          throw new Error("socket closed");
        }
        return rec(seedOf(call));
      },
    });
    const out = await launchSeeds(SPEC, [4], "base", { delayMs: 0 });
    expect(out.failed).toBeNull();
    expect(calls.map(idOf)).toEqual(["base.s4", "base.s4"]);
  });

  test("gives up after three unanswered tries", async () => {
    const calls = mockApi({
      "POST /api/v1/hosts/gpu1/runs": () => {
        throw new Error("socket closed");
      },
    });
    const out = await launchSeeds(SPEC, [4, 5], "base", { delayMs: 0 });
    expect(calls).toHaveLength(3);
    expect(out.records).toEqual([]);
    expect(out.failed?.seed).toBe(4);
    expect(out.failed?.error.message).toBe("Cannot reach hx serve");
  });
});
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd /Users/shreyasv/Desktop/code/research_dash/ui && bun test test/launch/launchApi.test.ts`
Expected: FAIL with `Cannot find module '../../src/launch/launchApi'`.

- [ ] **Step 4: Write the implementation**

Create `ui/src/launch/launchApi.ts`:

```ts
/**
 * HTTP calls of the Launch dialog, through the shared client (`api.*`). The hub launches
 * with `POST /api/v1/runs`; every other host with `POST /api/v1/hosts/{host}/runs`
 * (contract section 2), which the hub forwards with the same `command_id`. One launch is
 * one POST per seed, in seed order (so queue positions follow seed order), each with
 * `command_id = <base>.s<seed>`.
 */
import { type QueryClient, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type {
  GpuInfo,
  HostLaunchRequest,
  HostRow,
  LaunchRequest,
  QueueEntry,
  RunFields,
  RunRecord,
} from "../api/models";
import { HOSTS_REFETCH_MS, fetchHosts, queryKeys } from "../api/queries";
import { ACTION_RETRY_DELAY_MS, shouldRetry } from "../pages/components/useAction";
import { type LaunchHost, type LaunchSpec, slurmBody, toLaunchHosts } from "./plan";

/**
 * Hosts for the picker: the hub (with its GPUs and queue) first, then `GET /api/v1/hosts`.
 *
 * With `qc`, the hosts list is fetched through the shared `["hosts"]` query (`fetchHosts`),
 * so a stale host keeps the GPUs and queue it had while connected (`keepLastKnown`), as on
 * the Overview; the hub itself sends none for a host that is not connected.
 */
export async function fetchLaunchHosts(signal?: AbortSignal, qc?: QueryClient): Promise<LaunchHost[]> {
  const rows: Promise<HostRow[]> = qc
    ? qc.fetchQuery({
        queryKey: queryKeys.hosts(),
        queryFn: ({ signal: s }) => fetchHosts(qc, s),
        staleTime: 0,
      })
    : api.hosts(signal);
  const [hostRows, gpus, queue] = await Promise.all([
    rows,
    api.gpus(signal).catch((): GpuInfo[] => []),
    api.queue(signal).catch((): QueueEntry[] => []),
  ]);
  return toLaunchHosts(hostRows, { gpus, queue: queue.length });
}

/** Under `["hosts"]`, which `host.*` events and launches invalidate. */
export const LAUNCH_HOSTS_KEY = ["hosts", "launch"] as const;

/** Polls at the hosts list's rate: GPU use changes every 10 s with no event (spec 8A.7). */
export function useLaunchHosts() {
  const qc = useQueryClient();
  return useQuery({
    queryKey: LAUNCH_HOSTS_KEY,
    queryFn: ({ signal }) => fetchLaunchHosts(signal, qc),
    refetchInterval: HOSTS_REFETCH_MS,
  });
}

/**
 * The launch body for one seed, without the action fields (`api.*` adds `command_id` and
 * `created_by`): the phase 1 launch fields plus `gpus`, `queue`, on SLURM `slurm`, and the
 * pinned `commit` when there is one.
 *
 * The hub's own launch (`POST /api/v1/runs`) takes `repo`, the hub's checkout. A host launch
 * takes `project` by name and no path: `TaskDetail.repo` of a project copied from a host is
 * a path on that host, and the hub resolves its own checkout and the host's mapped one. No
 * `diff` is ever sent: without `commit` the hub pins its checkout's HEAD and diff itself.
 */
export function launchRequest(spec: LaunchSpec, seed: number): LaunchRequest | HostLaunchRequest {
  const fields: RunFields = {
    task: spec.task,
    command: spec.argv,
    hypothesis: spec.hypothesis.trim(),
    seed,
    tags: [],
    params: spec.params,
    vars: spec.vars,
    gpus: spec.gpus,
    queue: spec.host.kind === "ssh" && spec.queue,
  };
  if (spec.host.kind === "slurm" && spec.slurm !== null) fields.slurm = slurmBody(spec.slurm, spec.gpus);
  if (spec.commit !== null) fields.commit = spec.commit;
  return spec.host.kind === "hub" ? { repo: spec.repo, ...fields } : { project: spec.project, ...fields };
}

/** The idempotency key of one seed of one launch attempt. */
export const seedCommandId = (base: string, seed: number): string => `${base}.s${seed}`;

/** Launch one seed on the spec's host. */
export function postLaunch(spec: LaunchSpec, seed: number, commandId: string): Promise<RunRecord> {
  const body = launchRequest(spec, seed);
  const opts = { command_id: commandId };
  return "repo" in body ? api.launch(body, opts) : api.launchOnHost(spec.host.name, body, opts);
}

export interface LaunchOutcome {
  /** Runs started (or already started under the same `command_id`), in seed order. */
  records: RunRecord[];
  /** The first seed the server refused or never answered; later seeds were not sent. */
  failed: { seed: number; error: Error } | null;
}

export interface LaunchSeedsOptions {
  onProgress?: (done: number) => void;
  /** Wait before retrying an unanswered request; default `ACTION_RETRY_DELAY_MS`. */
  delayMs?: number;
}

/**
 * Launch every seed in order. An unanswered request (the server may not have seen it) is
 * retried twice with the same `command_id`; any answered failure stops the launch.
 */
export async function launchSeeds(
  spec: LaunchSpec,
  seeds: readonly number[],
  base: string,
  opts: LaunchSeedsOptions = {},
): Promise<LaunchOutcome> {
  const delay = opts.delayMs ?? ACTION_RETRY_DELAY_MS;
  const records: RunRecord[] = [];
  for (const seed of seeds) {
    const commandId = seedCommandId(base, seed);
    for (let attempt = 0; ; attempt += 1) {
      try {
        records.push(await postLaunch(spec, seed, commandId));
        break;
      } catch (err) {
        const error = err instanceof Error ? err : new Error(String(err));
        if (!shouldRetry(attempt, error)) return { records, failed: { seed, error } };
        await new Promise((resolve) => setTimeout(resolve, delay));
      }
    }
    opts.onProgress?.(records.length);
  }
  return { records, failed: null };
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /Users/shreyasv/Desktop/code/research_dash/ui && bun test test/launch/launchApi.test.ts`
Expected: PASS, `12 pass`, `0 fail`.

- [ ] **Step 6: Typecheck**

Run: `cd /Users/shreyasv/Desktop/code/research_dash/ui && bun run typecheck`
Expected: exit 0.

- [ ] **Step 7: Commit**

```bash
git -C /Users/shreyasv/Desktop/code/research_dash add ui/src/launch/launchApi.ts ui/test/launch/launchApi.test.ts
git -C /Users/shreyasv/Desktop/code/research_dash commit -m "feat(ui): launch API calls with per-seed command ids"
```

---

### Task 12: The Launch dialog

**Files:**
- Create: `ui/src/launch/styles.ts`
- Create: `ui/src/launch/LaunchDialog.tsx`
- Test: `ui/test/launch/LaunchDialog.test.tsx`

**Interfaces:**
- Consumes: everything above; `newCommandId` from `ui/src/api/client.ts`; `REMOTE_RUN_INVALIDATES` from `ui/src/api/queries.ts` (Task 3); `ErrorBox`, `Loading` from `ui/src/pages/components/QueryState.tsx`; `shellJoin` from `ui/src/pages/components/format.ts`; test helpers `mockApi`, `mockClipboard`, `renderWithClient`, `restoreFetch`, `HttpReply`, `Call` from `ui/test/pages/helpers.tsx`.
- Produces:
  - `ui/src/launch/styles.ts`: `LAUNCH_CSS: string` (every selector under `.hx-launch`), `LaunchStyles(): ReactElement`.
  - `ui/src/launch/LaunchDialog.tsx`: `interface LaunchDialogProps { project: string; task: string | null; repo: string; commit?: string | null; title?: string; initial?: Partial<LaunchDraft>; carry?: Carry; onClose: () => void; onLaunched: (records: RunRecord[], host: string) => void }`, `LaunchDialog(props)`. The sweep page group opens the same component for "Rerun sweep" with `initial`, `carry` and the template's `commit` (`pinnedCommit`). A pinned commit shows as `@ <short sha>` after the code location under the command.
  - Accessible handles tests and later groups rely on: dialog name = `title`; radiogroup "Host" with one radio per host (`aria-label` = host name); stepper buttons "Fewer GPUs per run"/"More GPUs per run" (SLURM: "... per job") and `<output aria-label="GPUs per run">`; checkbox "wait for GPUs"; textboxes "partition", "time", "account" (all blank by default: blank keeps the host's `SlurmDefaults`), "Seeds", "Command" (textarea), "Hypothesis"; `aria-label="Preview"` code; buttons "Copy as CLI", "Cancel", "Close", "Launch N" (N = seeds not launched yet by this dialog).
  - Partial launch: when seed 5 of 4, 5, 6 is refused, the dialog keeps seed 4's record, and the next Launch (with the same attempt id, or a new one after an edit) sends only 5 and 6; `onLaunched` gets all three records. The GPU plan and its blocker count only the seeds not started (`checkDraft(..., started)`), so GPUs the started seeds now hold never block the retry. The preview, its `×N`, the summary and `Copy as CLI` also cover only the seeds not started (the first of them in the preview): pasting the copied lines after a partial launch never starts a seed twice.

- [ ] **Step 1: Write the failing tests**

Create `ui/test/launch/LaunchDialog.test.tsx`:

```tsx
import { afterEach, describe, expect, mock, test } from "bun:test";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { RunRecord } from "../../src/api/models";
import { SEED_HINT } from "../../src/launch/command";
import { LaunchDialog, type LaunchDialogProps } from "../../src/launch/LaunchDialog";
import { makeRecord } from "../pages/fixtures";
import { type Call, HttpReply, mockApi, mockClipboard, renderWithClient, restoreFetch } from "../pages/helpers";
import { CMD, DGX, GPU1, GPU2, MCCLEARY, PROJECT, REPO_PATH, TASK, gpu, hostRow } from "./fixtures";

afterEach(restoreFetch);

const HOSTS = {
  "GET /api/v1/hosts": [GPU1, DGX, MCCLEARY, GPU2],
  "GET /api/v1/gpus": [],
  "GET /api/v1/queue": [],
};
const rec = (seed: number): RunRecord =>
  makeRecord({ run_id: `20261003-120000-${TASK}-s${seed}`, seed, status: "queued" });
const seedOf = (call: Call): number => (call.body as { seed: number }).seed;
const idOf = (call: Call): string => (call.body as { command_id: string }).command_id;
const posts = (calls: Call[]): Call[] => calls.filter((c) => c.method === "POST");

function renderDialog(over: Partial<LaunchDialogProps> = {}) {
  const onClose = mock(() => {});
  const onLaunched = mock((_records: RunRecord[], _host: string) => {});
  renderWithClient(
    <LaunchDialog
      project={PROJECT}
      task={TASK}
      repo={REPO_PATH}
      initial={{ command: CMD, seeds: "4, 5, 6" }}
      onClose={onClose}
      onLaunched={onLaunched}
      {...over}
    />,
  );
  return { onClose, onLaunched };
}

const radio = (name: string): HTMLInputElement => screen.getByRole("radio", { name }) as HTMLInputElement;
const rowOf = (name: string): HTMLLabelElement => radio(name).closest("label") as HTMLLabelElement;
const gpuLine = (): HTMLElement => screen.getByTitle("Seeds that start now, and seeds that wait in the hx queue");
const launchButton = (n: number): HTMLButtonElement =>
  screen.getByRole("button", { name: `Launch ${n}` }) as HTMLButtonElement;
const typeHypothesis = (text: string): void => {
  fireEvent.change(screen.getByLabelText("Hypothesis"), { target: { value: text } });
};

async function ready(host = "gpu1"): Promise<void> {
  const input = (await screen.findByRole("radio", { name: host })) as HTMLInputElement;
  await waitFor(() => expect(input.checked).toBe(true));
}

describe("host picker", () => {
  test("lists the hub and every host and picks the one with the most free GPUs", async () => {
    mockApi(HOSTS);
    renderDialog();
    await ready("gpu1");
    expect(screen.getByRole("dialog", { name: "New run" })).toBeTruthy();
    expect(screen.getByText(`${PROJECT} / ${TASK}`)).toBeTruthy();
    const group = screen.getByRole("radiogroup", { name: "Host" });
    expect(within(group).getAllByRole("radio").map((r) => r.getAttribute("aria-label"))).toEqual([
      "local",
      "gpu1",
      "dgx",
      "mccleary",
      "gpu2",
    ]);
    expect(rowOf("gpu1").textContent).toContain("1 free");
    expect(rowOf("gpu1").textContent).toContain("q 3");
    expect(rowOf("gpu1").title).toBe("gpu1: 8 GPU (A100 80GB), 1 free, 3 queued");
    expect(rowOf("gpu1").querySelectorAll(".mini i.free")).toHaveLength(1);
    expect(rowOf("gpu1").querySelectorAll(".mini i.other")).toHaveLength(2);
    expect(rowOf("local").textContent).toContain("no GPU");
    expect(rowOf("mccleary").textContent).toContain("4 run, 6 pend");
    expect(radio("dgx").disabled).toBe(true);
    expect(rowOf("dgx").textContent).toContain("stale 4m");
    expect(rowOf("dgx").title).toBe("dgx stale 4m: no heartbeat");
    expect(radio("gpu2").disabled).toBe(true);
    expect(rowOf("gpu2").title).toBe("installing hx on gpu2");
  });

  test("a host without this project is disabled with the fix", async () => {
    mockApi({ ...HOSTS, "GET /api/v1/hosts": [GPU1, hostRow("gpu3", { projects: ["other"], gpus: [gpu(0)] })] });
    renderDialog();
    await ready("gpu1");
    expect(radio("gpu3").disabled).toBe(true);
    expect(rowOf("gpu3").textContent).toContain("no path");
    expect(rowOf("gpu3").title).toBe("no path for rxn-forward on gpu3: hx hosts map rxn-forward gpu3 <path>");
  });

  test("keeps the initial host when it can take the run", async () => {
    mockApi(HOSTS);
    renderDialog({ initial: { command: CMD, seeds: "4, 5, 6", host: "mccleary" } });
    await ready("mccleary");
  });

  test("a failing hosts list shows the error and nothing can launch", async () => {
    mockApi({ "GET /api/v1/hosts": new HttpReply(500, { error: "hub index locked", type: "IndexError" }) });
    renderDialog();
    expect((await screen.findByRole("alert")).textContent).toBe("hub index locked");
    typeHypothesis("x");
    expect(launchButton(3).disabled).toBe(true);
    expect(launchButton(3).title).toBe("pick a host");
    expect((screen.getByRole("button", { name: "Copy as CLI" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("GPUs and queue", () => {
  test("shows the GPU plan, the queue position, the preview and the summary", async () => {
    mockApi(HOSTS);
    renderDialog();
    await ready();
    expect(screen.getByLabelText("GPUs per run").textContent).toBe("1");
    expect(gpuLine().textContent).toBe("1 now, CUDA_VISIBLE_DEVICES=5, 2 queued");
    expect(screen.getByText("pos 4–5")).toBeTruthy();
    expect(screen.getByLabelText("Preview").textContent).toBe(
      "gpu1: CUDA_VISIBLE_DEVICES=5 python train.py --lr 3e-4 --seed 4",
    );
    expect(screen.getAllByText("×3")).toHaveLength(2);
    expect(screen.getByText("3 × 1 GPU on gpu1")).toBeTruthy();
    expect(launchButton(3).disabled).toBe(true);
    expect(launchButton(3).title).toBe("hypothesis required");
    typeHypothesis("beam 10 holds on 3 new seeds");
    expect(launchButton(3).disabled).toBe(false);
    expect(launchButton(3).title).toBe("Launch 3 on gpu1");
  });

  test("the stepper moves seeds into the queue and stops at the host's GPU count", async () => {
    mockApi(HOSTS);
    renderDialog();
    await ready();
    const more = screen.getByRole("button", { name: "More GPUs per run" }) as HTMLButtonElement;
    fireEvent.click(more);
    expect(screen.getByLabelText("GPUs per run").textContent).toBe("2");
    expect(gpuLine().textContent).toBe("0 now, 3 queued");
    expect(screen.getByText("pos 4–6")).toBeTruthy();
    expect(screen.getByLabelText("Preview").textContent).toBe("gpu1: python train.py --lr 3e-4 --seed 4");
    for (let i = 0; i < 10; i += 1) fireEvent.click(more);
    expect(screen.getByLabelText("GPUs per run").textContent).toBe("8");
    expect(more.disabled).toBe(true);
  });

  test("queue off: seeds that cannot start block Launch", async () => {
    mockApi(HOSTS);
    renderDialog();
    await ready();
    typeHypothesis("x");
    fireEvent.click(screen.getByRole("checkbox", { name: "wait for GPUs" }));
    expect(gpuLine().textContent).toBe("1 now, CUDA_VISIBLE_DEVICES=5, 2 won't start");
    expect(launchButton(3).disabled).toBe(true);
    expect(launchButton(3).title).toBe("2 won't start: 1 GPU free; turn on Queue");
    expect(screen.queryByText(/^pos /)).toBeNull();
  });

  test("a SLURM host swaps GPUs and Queue for sbatch fields", async () => {
    mockApi(HOSTS);
    renderDialog();
    await ready();
    fireEvent.click(radio("mccleary"));
    await waitFor(() => expect(radio("mccleary").checked).toBe(true));
    expect(screen.queryByRole("checkbox", { name: "wait for GPUs" })).toBeNull();
    expect(screen.queryByLabelText("GPUs per run")).toBeNull();
    fireEvent.change(screen.getByLabelText("partition"), { target: { value: "gpu" } });
    fireEvent.change(screen.getByLabelText("time"), { target: { value: "08:00:00" } });
    fireEvent.click(screen.getByRole("button", { name: "More GPUs per job" }));
    expect(screen.getByLabelText("GPUs per job").textContent).toBe("2");
    expect(screen.getByText("sbatch --partition gpu --time 08:00:00 --gpus 2")).toBeTruthy();
    expect(screen.getByText("3 jobs × 2 GPU, ≤ 08:00:00")).toBeTruthy();
    expect(screen.getByLabelText("Preview").textContent).toBe("mccleary: python train.py --lr 3e-4 --seed 4");
    fireEvent.change(screen.getByLabelText("time"), { target: { value: "8h" } });
    expect(screen.getByText("time: use h:mm:ss or d-hh:mm:ss")).toBeTruthy();
    typeHypothesis("x");
    expect(launchButton(3).title).toBe("time: use h:mm:ss or d-hh:mm:ss");
  });

  test("the hub: no queue, GPUs from its own nvidia-smi, launches through /api/v1/runs", async () => {
    const calls = mockApi({ ...HOSTS, "POST /api/v1/runs": (c: Call) => rec(seedOf(c)) });
    const { onLaunched } = renderDialog();
    await ready();
    fireEvent.click(radio("local"));
    await waitFor(() => expect(radio("local").checked).toBe(true));
    expect(screen.queryByRole("checkbox", { name: "wait for GPUs" })).toBeNull();
    expect(screen.getByLabelText("GPUs per run").textContent).toBe("0");
    expect((screen.getByRole("button", { name: "More GPUs per run" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByLabelText("Preview").textContent).toBe("local: python train.py --lr 3e-4 --seed 4");
    expect(screen.getByText("3 runs on local, no GPU")).toBeTruthy();
    typeHypothesis("cpu smoke test");
    fireEvent.click(launchButton(3));
    await waitFor(() => expect(onLaunched).toHaveBeenCalledTimes(1));
    expect(
      posts(calls).map((c) => {
        const body = c.body as { gpus: number; queue: boolean };
        return [c.url, body.gpus, body.queue];
      }),
    ).toEqual([
      ["/api/v1/runs", 0, false],
      ["/api/v1/runs", 0, false],
      ["/api/v1/runs", 0, false],
    ]);
    expect(onLaunched.mock.calls[0]?.[1]).toBe("local");
  });
});

describe("seeds and command", () => {
  test("the template marks {seed} and carries the quoting hint as a tooltip", async () => {
    mockApi(HOSTS);
    renderDialog();
    await ready();
    const marks = screen.getByTestId("template-highlight").querySelectorAll("mark.tok");
    expect(marks).toHaveLength(1);
    expect(marks[0]?.textContent).toBe("{seed}");
    expect(marks[0]?.getAttribute("title")).toBe(SEED_HINT);
    const box = screen.getByLabelText("Command") as HTMLTextAreaElement;
    expect(box.value).toBe(CMD);
    expect(box.closest(".tmpl")?.getAttribute("title")).toBe(SEED_HINT);
    fireEvent.change(box, { target: { value: "python train.py --lr 3e-4" } });
    expect(screen.getByText("no {seed} in the command: every seed runs the same command")).toBeTruthy();
    expect(screen.getByTestId("template-highlight").querySelectorAll("mark.tok")).toHaveLength(0);
    fireEvent.change(box, { target: { value: "python 'oops" } });
    expect(screen.getByText("command: unclosed ' quote")).toBeTruthy();
    expect(screen.getByLabelText("Preview").textContent).toBe("·");
  });

  test("seeds: the count follows the list and a bad seed is named", async () => {
    mockApi(HOSTS);
    renderDialog();
    await ready();
    const seeds = screen.getByLabelText("Seeds");
    fireEvent.change(seeds, { target: { value: "1-5" } });
    expect(launchButton(5)).toBeTruthy();
    expect(screen.getAllByText("×5")).toHaveLength(2);
    fireEvent.change(seeds, { target: { value: "4, x" } });
    expect(screen.getByText("bad seed x")).toBeTruthy();
    expect(launchButton(0).disabled).toBe(true);
  });
});

describe("Copy as CLI", () => {
  test("copies the exact hx launch lines, one per seed", async () => {
    const written = mockClipboard();
    mockApi(HOSTS);
    renderDialog();
    await ready();
    typeHypothesis("beam 10 holds");
    fireEvent.click(screen.getByRole("button", { name: "Copy as CLI" }));
    await waitFor(() => expect(written).toHaveLength(1));
    expect(written[0]).toBe(
      [4, 5, 6]
        .map(
          (s) =>
            `hx launch --repo ${REPO_PATH} -t ${TASK} --host gpu1 --gpus 1 --queue --seed ${s} -H 'beam 10 holds' -- python train.py --lr 3e-4 --seed '{seed}'`,
        )
        .join("\n"),
    );
    expect(await screen.findByRole("button", { name: "Copied" })).toBeTruthy();
  });

  test("after a refused seed, the preview and Copy as CLI cover only the seeds not launched", async () => {
    const written = mockClipboard();
    let refuse = true;
    mockApi({
      ...HOSTS,
      "POST /api/v1/hosts/gpu1/runs": (c: Call) => {
        if (seedOf(c) === 5 && refuse) {
          refuse = false;
          return new HttpReply(400, { error: "runner busy", type: "RunError" });
        }
        return rec(seedOf(c));
      },
    });
    renderDialog();
    await ready();
    typeHypothesis("beam 10 holds");
    expect(screen.getByLabelText("Preview").textContent).toBe(
      "gpu1: CUDA_VISIBLE_DEVICES=5 python train.py --lr 3e-4 --seed 4",
    );
    fireEvent.click(launchButton(3));
    await screen.findByRole("alert");
    // seed 4 started: the preview shows seed 5, and the count and the copied lines skip seed 4
    expect(screen.getByLabelText("Preview").textContent).toBe(
      "gpu1: CUDA_VISIBLE_DEVICES=5 python train.py --lr 3e-4 --seed 5",
    );
    expect(document.querySelector(".hx-launch .prev .xn")?.textContent).toBe("×2");
    fireEvent.click(screen.getByRole("button", { name: "Copy as CLI" }));
    await waitFor(() => expect(written).toHaveLength(1));
    expect(written[0]).toBe(
      [5, 6]
        .map(
          (s) =>
            `hx launch --repo ${REPO_PATH} -t ${TASK} --host gpu1 --gpus 1 --queue --seed ${s} -H 'beam 10 holds' -- python train.py --lr 3e-4 --seed '{seed}'`,
        )
        .join("\n"),
    );
    expect(launchButton(2).disabled).toBe(false);
  });

  test("a blocked clipboard says so", async () => {
    mockClipboard(true);
    mockApi(HOSTS);
    renderDialog();
    await ready();
    fireEvent.click(screen.getByRole("button", { name: "Copy as CLI" }));
    expect(await screen.findByRole("button", { name: "Clipboard blocked" })).toBeTruthy();
  });
});

describe("Launch", () => {
  test("sends one POST per seed with ids from one attempt; a double click launches once", async () => {
    const calls = mockApi({ ...HOSTS, "POST /api/v1/hosts/gpu1/runs": (c: Call) => rec(seedOf(c)) });
    const { onLaunched } = renderDialog();
    await ready();
    typeHypothesis("beam 10 holds");
    const launch = launchButton(3);
    fireEvent.click(launch);
    fireEvent.click(launch);
    await waitFor(() => expect(onLaunched).toHaveBeenCalledTimes(1));
    const sent = posts(calls);
    expect(sent.map(seedOf)).toEqual([4, 5, 6]);
    const base = idOf(sent[0] as Call).replace(/\.s4$/, "");
    expect(sent.map(idOf)).toEqual([`${base}.s4`, `${base}.s5`, `${base}.s6`]);
    expect(sent[0]?.body).toEqual({
      command_id: `${base}.s4`,
      created_by: "human",
      project: PROJECT,
      task: TASK,
      command: ["python", "train.py", "--lr", "3e-4", "--seed", "{seed}"],
      hypothesis: "beam 10 holds",
      seed: 4,
      tags: [],
      params: {},
      vars: {},
      gpus: 1,
      queue: true,
    });
    const [records, host] = onLaunched.mock.calls[0] as [RunRecord[], string];
    expect(records.map((r) => r.seed)).toEqual([4, 5, 6]);
    expect(host).toBe("gpu1");
    // a host launch names the project; the hub's repo path never leaves this machine
    expect(sent.every((c) => !("repo" in (c.body as Record<string, unknown>)))).toBe(true);
    expect(sent.every((c) => !("commit" in (c.body as Record<string, unknown>)))).toBe(true);
  });

  test("a partial launch on the hub: the retry needs GPUs only for the seeds not started", async () => {
    let held = false;
    let refuse = true;
    const calls = mockApi({
      ...HOSTS,
      // after seed 4 starts, it holds GPU 0 of the hub's two
      "GET /api/v1/gpus": () => (held ? [gpu(0, { run_id: "r-s4" }), gpu(1)] : [gpu(0), gpu(1)]),
      "POST /api/v1/runs": (c: Call) => {
        if (seedOf(c) === 4) held = true;
        if (seedOf(c) === 5 && refuse) {
          refuse = false;
          return new HttpReply(503, { error: "index busy", type: "IndexError" });
        }
        return rec(seedOf(c));
      },
    });
    const { onLaunched } = renderDialog({ initial: { command: CMD, seeds: "4, 5", host: "local" } });
    await ready("local");
    typeHypothesis("two seeds on the hub");
    fireEvent.click(launchButton(2));
    expect((await screen.findByRole("alert")).textContent).toBe(
      "seed 5: index busy. 1 of 2 launched; Launch sends the other 1.",
    );
    // the hub now has 1 free GPU and 1 seed to send: Launch stays enabled
    await waitFor(() => expect(gpuLine().textContent).toBe("1 now, CUDA_VISIBLE_DEVICES=1"));
    expect(launchButton(1).disabled).toBe(false);
    fireEvent.click(launchButton(1));
    await waitFor(() => expect(onLaunched).toHaveBeenCalledTimes(1));
    const seeds = posts(calls).map(seedOf);
    expect(seeds).toEqual([4, 5, 5]);
    expect((onLaunched.mock.calls[0] as [RunRecord[], string])[0].map((r) => r.seed)).toEqual([4, 5]);
  });

  test("after a refused seed, Launch sends only the seeds not launched, with the same command ids", async () => {
    let refuse = true;
    const calls = mockApi({
      ...HOSTS,
      "POST /api/v1/hosts/gpu1/runs": (c: Call) => {
        if (seedOf(c) === 5 && refuse) {
          refuse = false;
          return new HttpReply(400, { error: "runner busy", type: "RunError" });
        }
        return rec(seedOf(c));
      },
    });
    const { onLaunched } = renderDialog();
    await ready();
    typeHypothesis("beam 10 holds");
    fireEvent.click(launchButton(3));
    expect((await screen.findByRole("alert")).textContent).toBe(
      "seed 5: runner busy. 1 of 3 launched; Launch sends the other 2.",
    );
    expect(onLaunched).not.toHaveBeenCalled();
    const first = posts(calls).map(idOf);
    expect(first).toHaveLength(2);
    fireEvent.click(launchButton(2));
    await waitFor(() => expect(onLaunched).toHaveBeenCalledTimes(1));
    const second = posts(calls).slice(2);
    expect(second.map(seedOf)).toEqual([5, 6]);
    expect(idOf(second[0] as Call)).toBe(first[1]);
    const [records] = onLaunched.mock.calls[0] as [RunRecord[], string];
    expect(records.map((r) => r.seed)).toEqual([4, 5, 6]);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  test("a partial launch, then an edit: Launch sends only the seeds not launched, under a new attempt", async () => {
    let refuse = true;
    const calls = mockApi({
      ...HOSTS,
      "POST /api/v1/hosts/gpu1/runs": (c: Call) => {
        if (seedOf(c) === 5 && refuse) {
          refuse = false;
          return new HttpReply(400, { error: "runner busy", type: "RunError" });
        }
        return rec(seedOf(c));
      },
    });
    const { onLaunched } = renderDialog();
    await ready();
    typeHypothesis("beam 10 holds");
    fireEvent.click(launchButton(3));
    await screen.findByRole("alert");
    const first = posts(calls);
    expect(first.map(seedOf)).toEqual([4, 5]);
    typeHypothesis("beam 10 holds, take 2");
    expect(screen.queryByRole("alert")).toBeNull();
    fireEvent.click(launchButton(2));
    await waitFor(() => expect(onLaunched).toHaveBeenCalledTimes(1));
    const second = posts(calls).slice(2);
    // seed 4 started already: a new attempt id must not start it twice
    expect(second.map(seedOf)).toEqual([5, 6]);
    expect(idOf(second[0] as Call)).not.toBe(idOf(first[1] as Call));
    const [records] = onLaunched.mock.calls[0] as [RunRecord[], string];
    expect(records.map((r) => r.seed)).toEqual([4, 5, 6]);
  });

  test("editing the form after a failure starts a new attempt id", async () => {
    let refuse = true;
    const calls = mockApi({
      ...HOSTS,
      "POST /api/v1/hosts/gpu1/runs": (c: Call) => {
        if (refuse) {
          refuse = false;
          return new HttpReply(400, { error: "runner busy", type: "RunError" });
        }
        return rec(seedOf(c));
      },
    });
    const { onLaunched } = renderDialog();
    await ready();
    typeHypothesis("beam 10 holds");
    fireEvent.click(launchButton(3));
    await screen.findByRole("alert");
    typeHypothesis("beam 10 holds, take 2");
    expect(screen.queryByRole("alert")).toBeNull();
    fireEvent.click(launchButton(3));
    await waitFor(() => expect(onLaunched).toHaveBeenCalledTimes(1));
    const ids = posts(calls).map(idOf);
    expect(ids).toHaveLength(4);
    expect(ids[0]?.endsWith(".s4")).toBe(true);
    expect(ids[1]?.endsWith(".s4")).toBe(true);
    expect(ids[1]).not.toBe(ids[0]);
  });

  test("Escape, Close and Cancel call onClose", async () => {
    mockApi(HOSTS);
    const { onClose } = renderDialog();
    await ready();
    fireEvent.keyDown(screen.getByLabelText("Hypothesis"), { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalledTimes(3);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/shreyasv/Desktop/code/research_dash/ui && bun test test/launch/LaunchDialog.test.tsx`
Expected: FAIL with `Cannot find module '../../src/launch/LaunchDialog'`.

- [ ] **Step 3: Write the styles**

Create `ui/src/launch/styles.ts`:

```ts
/** Launch dialog CSS, from the phase 2 mockup. Every selector starts with `.hx-launch`. */
import { type ReactElement, createElement } from "react";

export const LAUNCH_CSS = `
.hx-launch { position: fixed; inset: 0; z-index: 30; display: flex; justify-content: center; align-items: flex-start; padding: 84px 16px 0; overflow: auto; background: color-mix(in srgb, var(--ink) 24%, transparent); }
[data-theme="dark"] .hx-launch { background: rgba(0, 0, 0, .55); }
.hx-launch .dlg { width: 840px; max-width: 100%; background: var(--paper); border: 1px solid var(--rule); border-radius: 10px; box-shadow: 0 24px 60px -20px rgba(10, 14, 20, .35); margin-bottom: 60px; }
.hx-launch .dlg-h { display: flex; align-items: baseline; gap: 14px; padding: 18px 24px 14px; border-bottom: 1px solid var(--rule); }
.hx-launch .dlg-h h2 { margin: 0; font: 500 24px/1.1 var(--serif); letter-spacing: -.01em; }
.hx-launch .dlg-h .x { margin-left: auto; border: 0; background: transparent; color: var(--ink-3); font-size: 20px; line-height: 1; cursor: pointer; padding: 2px 6px; border-radius: 4px; }
.hx-launch .dlg-h .x:hover { color: var(--ink); background: var(--paper-2); }
.hx-launch .dlg-b { padding: 8px 24px 4px; }
.hx-launch .fr { display: grid; grid-template-columns: 104px minmax(0, 1fr); gap: 0 16px; align-items: baseline; padding: 14px 0; border-top: 1px solid var(--rule-2); }
.hx-launch .fr:first-child { border-top: 0; }
.hx-launch .fr > label, .hx-launch .fr > .lb { font-weight: 550; font-size: 14px; color: var(--ink); }
.hx-launch .row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.hx-launch .pair { display: inline-flex; align-items: center; gap: 6px; }
.hx-launch .r { margin-left: auto; }
.hx-launch .bad { color: var(--fail); }
.hx-launch .warn { color: var(--ink-2); }
.hx-launch p.bad, .hx-launch p.warn { margin: 6px 0 0; }
.hx-launch .err { color: var(--fail); font-size: 14px; margin: 4px 24px 8px; }
.hx-launch .in { height: 32px; box-sizing: border-box; border: 1px solid var(--rule); border-radius: 6px; background: transparent; padding: 0 10px; font-size: 14px; color: var(--ink); }
.hx-launch .in:focus { outline: 2px solid var(--agent); outline-offset: 0; border-color: transparent; }
.hx-launch .in[aria-invalid="true"] { border-color: var(--fail); }
.hx-launch .in.mono { font-family: var(--mono); font-size: 13px; }
.hx-launch .in.w-s { width: 160px; }
.hx-launch .in.w-m { width: 112px; font-variant-numeric: tabular-nums; }
.hx-launch .in.w-l { width: 100%; }
.hx-launch .lbl-x { font-size: 12.5px; color: var(--ink-3); font-weight: 400; }
.hx-launch .stp { display: inline-flex; align-items: center; border: 1px solid var(--rule); border-radius: 6px; height: 32px; box-sizing: border-box; }
.hx-launch .stp button { width: 30px; height: 30px; border: 0; background: transparent; color: var(--ink-2); cursor: pointer; font-size: 16px; }
.hx-launch .stp button:hover:not(:disabled) { color: var(--ink); }
.hx-launch .stp button:disabled { color: var(--rule); cursor: not-allowed; }
.hx-launch .stp output { min-width: 26px; text-align: center; font-variant-numeric: tabular-nums; font-size: 14px; }
.hx-launch .sw { position: relative; display: inline-flex; align-items: center; gap: 9px; cursor: pointer; font-size: 14px; color: var(--ink-2); }
.hx-launch .sw input { position: absolute; opacity: 0; }
.hx-launch .sw .tr { width: 30px; height: 18px; border-radius: 9px; background: var(--rule); position: relative; transition: background .12s; flex: none; }
.hx-launch .sw .tr::after { content: ""; position: absolute; left: 2px; top: 2px; width: 14px; height: 14px; border-radius: 50%; background: var(--paper); transition: transform .12s; }
.hx-launch .sw input:checked + .tr { background: var(--ink); }
.hx-launch .sw input:checked + .tr::after { transform: translateX(12px); }
.hx-launch .sw input:focus-visible + .tr { outline: 2px solid var(--agent); outline-offset: 2px; }
.hx-launch .hp { display: grid; border: 1px solid var(--rule); border-radius: 7px; overflow: hidden; }
.hx-launch .hp label { display: grid; grid-template-columns: 18px 92px 56px minmax(0, 1fr) 84px 52px; gap: 0 12px; align-items: center; padding: 8px 12px; cursor: pointer; font-size: 14px; border-top: 1px solid var(--rule-2); font-variant-numeric: tabular-nums; }
.hx-launch .hp label:first-child { border-top: 0; }
.hx-launch .hp label:hover { background: color-mix(in srgb, var(--paper-2) 55%, transparent); }
.hx-launch .hp label.on { background: var(--paper-2); box-shadow: inset 2px 0 0 var(--ink); }
.hx-launch .hp label.off { color: var(--ink-3); cursor: not-allowed; }
.hx-launch .hp input { appearance: none; -webkit-appearance: none; margin: 0; width: 14px; height: 14px; border-radius: 50%; border: 1.4px solid var(--ink-3); display: grid; place-content: center; }
.hx-launch .hp input:checked { border-color: var(--ink); }
.hx-launch .hp input:checked::after { content: ""; width: 6px; height: 6px; border-radius: 50%; background: var(--ink); }
.hx-launch .hp input:disabled { border-color: var(--rule); }
.hx-launch .hp .nm { font-weight: 550; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hx-launch .hp .tag { justify-self: start; }
.hx-launch .hp .fr-n { text-align: right; color: var(--ink-2); white-space: nowrap; }
.hx-launch .hp .fr-n b { color: var(--ink); font-weight: 600; }
.hx-launch .hp .qq { text-align: right; color: var(--ink-3); font-size: 13px; }
.hx-launch .mini { display: flex; gap: 2px; align-items: center; }
.hx-launch .mini i { width: 9px; height: 12px; border-radius: 1.5px; display: block; }
.hx-launch .mini i.busy { background: var(--ink-2); }
.hx-launch .mini i.free { box-shadow: inset 0 0 0 1px var(--ink-3); }
.hx-launch .mini i.other { box-shadow: inset 0 0 0 1px var(--rule); background: repeating-linear-gradient(135deg, var(--ink-3) 0 1px, transparent 1px 3px); }
.hx-launch .mini i.stale { background: var(--ink-3); opacity: .35; }
.hx-launch .mini i.none { box-shadow: inset 0 0 0 1px var(--rule-2); }
.hx-launch .tmpl { position: relative; border: 1px solid var(--rule); border-radius: 6px; font: 400 13px/1.6 var(--mono); }
.hx-launch .tmpl:focus-within { outline: 2px solid var(--agent); border-color: transparent; }
.hx-launch .tmpl-hl, .hx-launch .tmpl textarea { margin: 0; padding: 6px 10px; box-sizing: border-box; font: inherit; letter-spacing: normal; white-space: pre-wrap; overflow-wrap: anywhere; }
.hx-launch .tmpl-hl { color: var(--ink); min-height: 32px; }
.hx-launch .tmpl textarea { position: absolute; inset: 0; width: 100%; height: 100%; border: 0; background: transparent; color: transparent; caret-color: var(--ink); resize: none; overflow: hidden; outline: none; }
.hx-launch .tmpl textarea::placeholder { color: var(--ink-3); }
.hx-launch .tok { background: var(--best-wash); color: var(--ink); border-radius: 3px; box-shadow: inset 0 0 0 1px var(--best-edge); font-weight: inherit; }
.hx-launch .where { margin-top: 6px; }
.hx-launch .sb { flex-basis: 100%; font-size: 12px; color: var(--ink-3); }
.hx-launch .prev { display: flex; align-items: center; gap: 10px; }
.hx-launch .prev .cmd { flex: 1; min-width: 0; padding: 8px 12px; }
.hx-launch .hostp { color: var(--ink-3); }
.hx-launch .xn { font-size: 12.5px; color: var(--ink-3); }
.hx-launch .dlg-f { display: flex; align-items: center; gap: 8px; padding: 14px 24px; border-top: 1px solid var(--rule); }
.hx-launch .dlg-f .sum { margin-left: auto; margin-right: 4px; }
`;

/** Inject the dialog CSS while the dialog is mounted. */
export function LaunchStyles(): ReactElement {
  return createElement("style", { "data-hx": "launch" }, LAUNCH_CSS);
}
```

- [ ] **Step 4: Write the dialog**

Create `ui/src/launch/LaunchDialog.tsx`:

```tsx
/**
 * Launch dialog (spec 8A.5, 8A.8; mockups docs/mockups/phase2/shot-launch*.png).
 *
 * Pick a host (the hub first, then every host with its free GPUs, queue and state), GPUs per
 * run and the queue (SSH hosts) or sbatch fields (SLURM hosts), seeds, a command template
 * with `{seed}`, and a required hypothesis. The preview shows the first seed's command as it
 * will run. Launch posts one run per seed; every POST carries `<attempt>.s<seed>` as its
 * `command_id`, and the attempt id changes only when the form changes, so a double click or
 * a retry after a refused seed never starts a seed twice (spec 5.3). The seeds that did
 * start are remembered and never sent again, even after an edit gives a new attempt id.
 */
import { useQueryClient } from "@tanstack/react-query";
import {
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
  useEffect,
  useRef,
  useState,
} from "react";

import { newCommandId } from "../api/client";
import type { RunRecord } from "../api/models";
import { REMOTE_RUN_INVALIDATES } from "../api/queries";
import { shellJoin } from "../pages/components/format";
import { ErrorBox, Loading } from "../pages/components/QueryState";
import { launchCli, sbatchLine } from "./cli";
import { SEED_HINT, templateSegments } from "./command";
import { type Carry, DEFAULT_DRAFT, type DraftCheck, type LaunchDraft, NO_CARRY, checkDraft } from "./draft";
import { launchSeeds, useLaunchHosts } from "./launchApi";
import {
  type Availability,
  type LaunchHost,
  type LaunchPlan,
  type LaunchSpec,
  SLURM_MAX_GPUS,
  availability,
  freeGpus,
  gpuCells,
  gpuLimit,
  gpusForHost,
  hostTitle,
  launchSummary,
  pickHost,
  posRange,
  stateLabel,
} from "./plan";
import { LaunchStyles } from "./styles";

export interface LaunchDialogProps {
  project: string;
  task: string | null;
  /** The project repo on the hub (`TaskDetail.repo`): sent only with a launch on the hub. */
  repo: string;
  /** Pinned commit (Rerun sweep: `pinnedCommit(template)`); absent: the hub pins its checkout. */
  commit?: string | null;
  title?: string;
  initial?: Partial<LaunchDraft>;
  /** Params and vars of the template run, sent with every seed. */
  carry?: Carry;
  onClose: () => void;
  onLaunched: (records: RunRecord[], host: string) => void;
}

type CopyState = "idle" | "copied" | "failed";

const COPY_TEXT: Record<CopyState, string> = {
  idle: "Copy as CLI",
  copied: "Copied",
  failed: "Clipboard blocked",
};

interface Failure {
  seed: number;
  message: string;
  /** Seeds started by this dialog so far, and seeds still to send. */
  done: number;
  left: number;
}

/** Seeds this dialog has started, in launch order, with their records. */
interface Launched {
  seeds: number[];
  records: RunRecord[];
}

const NOTHING_LAUNCHED: Launched = { seeds: [], records: [] };

type Update = (patch: Partial<LaunchDraft>) => void;

interface RowProps {
  draft: LaunchDraft;
  check: DraftCheck;
  update: Update;
}

function Stepper({
  label,
  value,
  max,
  onChange,
}: {
  label: string;
  value: number;
  max: number;
  onChange: (n: number) => void;
}) {
  return (
    <span className="stp">
      <button
        type="button"
        aria-label={`Fewer ${label}`}
        disabled={value <= 0}
        onClick={() => onChange(Math.max(0, value - 1))}
      >
        −
      </button>
      <output aria-label={label}>{value}</output>
      <button
        type="button"
        aria-label={`More ${label}`}
        disabled={value >= max}
        onClick={() => onChange(Math.min(max, value + 1))}
      >
        +
      </button>
    </span>
  );
}

function HostLoad({ host }: { host: LaunchHost }) {
  if (host.kind === "slurm") {
    return (
      <span className="small">{host.slurm ? `${host.slurm.running} run, ${host.slurm.pending} pend` : "·"}</span>
    );
  }
  if (host.gpus.length === 0) return <span className="small">no GPU</span>;
  return (
    <span className="mini" aria-hidden="true">
      {gpuCells(host).map((cell, i) => (
        <i key={i} className={cell} />
      ))}
    </span>
  );
}

function hostRight(host: LaunchHost, av: Availability, now: number): ReactNode {
  if (host.state !== "connected") return stateLabel(host, now);
  if (!av.ok) return "no path";
  if (host.kind === "slurm") return "";
  return (
    <>
      <b>{freeGpus(host).length}</b> free
    </>
  );
}

function HostPicker({
  hosts,
  selected,
  project,
  now,
  onPick,
}: {
  hosts: LaunchHost[];
  selected: string | null;
  project: string;
  now: number;
  onPick: (host: LaunchHost) => void;
}) {
  return (
    <div className="hp" role="radiogroup" aria-label="Host">
      {hosts.map((h) => {
        const av = availability(h, project, now);
        const on = h.name === selected;
        const cls = [on ? "on" : "", av.ok ? "" : "off"].filter(Boolean).join(" ");
        return (
          <label key={h.name} className={cls || undefined} title={av.ok ? hostTitle(h) : av.reason}>
            <input
              type="radio"
              name="hx-launch-host"
              value={h.name}
              aria-label={h.name}
              checked={on}
              disabled={!av.ok}
              onChange={() => onPick(h)}
            />
            <span className="nm">{h.name}</span>
            <span className="tag">{h.kind}</span>
            <HostLoad host={h} />
            <span className="fr-n">{hostRight(h, av, now)}</span>
            <span className="qq">{h.kind === "slurm" ? "" : `q ${h.queue}`}</span>
          </label>
        );
      })}
    </div>
  );
}

function GpuLine({ plan }: { plan: LaunchPlan }) {
  return (
    <span className="small r" title="Seeds that start now, and seeds that wait in the hx queue">
      {plan.now} now
      {plan.cvd.length > 0 ? (
        <>
          , <code>CUDA_VISIBLE_DEVICES={plan.cvd.join(",")}</code>
        </>
      ) : null}
      {plan.queued > 0 ? `, ${plan.queued} queued` : null}
      {plan.blocked > 0 ? <span className="bad">, {plan.blocked} won't start</span> : null}
    </span>
  );
}

function GpuRows({ host, draft, check, update }: RowProps & { host: LaunchHost }) {
  const plan = check.plan;
  return (
    <>
      <div className="fr">
        <span className="lb">GPUs</span>
        <div className="row">
          <Stepper label="GPUs per run" value={draft.gpus} max={gpuLimit(host)} onChange={(gpus) => update({ gpus })} />
          <span className="lbl-x">per run</span>
          {plan ? <GpuLine plan={plan} /> : null}
        </div>
      </div>
      {host.kind === "ssh" ? (
        <div className="fr">
          <span className="lb">Queue</span>
          <div className="row">
            <label className="sw">
              <input type="checkbox" checked={draft.queue} onChange={(e) => update({ queue: e.target.checked })} />
              <span className="tr" />
              wait for GPUs
            </label>
            {draft.queue && plan && plan.queued > 0 ? (
              <span className="small r" title={`Position in the ${host.name} queue after ${host.queue} waiting runs`}>
                {posRange(plan)}
              </span>
            ) : null}
          </div>
        </div>
      ) : null}
    </>
  );
}

function SlurmRow({ draft, check, update }: RowProps) {
  const slurm = { partition: draft.partition, account: draft.account, time: draft.time };
  return (
    <div className="fr">
      <span className="lb" title="sbatch options; a blank field keeps the host's default from environments.yaml">
        SLURM
      </span>
      <div className="row">
        <span className="pair">
          <label className="lbl-x" htmlFor="hx-launch-part">
            partition
          </label>
          <input
            id="hx-launch-part"
            className="in mono w-m"
            value={draft.partition}
            placeholder="default"
            spellCheck={false}
            aria-invalid={check.partitionError ? true : undefined}
            onChange={(e) => update({ partition: e.target.value })}
          />
        </span>
        <span className="pair">
          <label className="lbl-x" htmlFor="hx-launch-time">
            time
          </label>
          <input
            id="hx-launch-time"
            className="in mono w-m"
            value={draft.time}
            placeholder="default"
            spellCheck={false}
            title="--time: h:mm:ss or d-hh:mm:ss; blank keeps the host's default"
            aria-invalid={check.timeError ? true : undefined}
            onChange={(e) => update({ time: e.target.value })}
          />
        </span>
        <span className="pair">
          <label className="lbl-x" htmlFor="hx-launch-acct">
            account
          </label>
          <input
            id="hx-launch-acct"
            className="in mono w-m"
            value={draft.account}
            placeholder="default"
            spellCheck={false}
            aria-invalid={check.accountError ? true : undefined}
            onChange={(e) => update({ account: e.target.value })}
          />
        </span>
        <span className="pair">
          <span className="lbl-x">gpus</span>
          <Stepper label="GPUs per job" value={draft.gpus} max={SLURM_MAX_GPUS} onChange={(gpus) => update({ gpus })} />
        </span>
        <code className="p sb" title="sbatch flags hx will use">
          {sbatchLine(slurm, draft.gpus)}
        </code>
        {[check.timeError, check.partitionError, check.accountError].map((err) =>
          err ? (
            <span key={err} className="small bad">
              {err}
            </span>
          ) : null,
        )}
      </div>
    </div>
  );
}

function CommandRow({ draft, check, update, where }: RowProps & { where: string }) {
  return (
    <div className="fr">
      <label htmlFor="hx-launch-cmd">Command</label>
      <div>
        <div className="tmpl" title={SEED_HINT}>
          <div className="tmpl-hl" aria-hidden="true" data-testid="template-highlight">
            {templateSegments(draft.command).map((s, i) =>
              s.seed ? (
                <mark key={i} className="tok" title={SEED_HINT}>
                  {s.text}
                </mark>
              ) : (
                <span key={i}>{s.text}</span>
              ),
            )}
            {"​"}
          </div>
          <textarea
            id="hx-launch-cmd"
            rows={1}
            spellCheck={false}
            autoComplete="off"
            value={draft.command}
            placeholder="python train.py --seed {seed}"
            aria-invalid={check.commandError ? true : undefined}
            onChange={(e) => update({ command: e.target.value })}
          />
        </div>
        {where ? <div className="lbl-x where">{where}</div> : null}
        {check.commandError ? <p className="small bad">command: {check.commandError}</p> : null}
        {check.warnings.map((w) => (
          <p key={w} className="small warn">
            {w}
          </p>
        ))}
      </div>
    </div>
  );
}

/** The first seed still to launch, as it will run (after a partial launch: the next one not started). */
function Preview({ host, check }: { host: LaunchHost | null; check: DraftCheck }) {
  const seed = check.pending[0];
  if (host === null || check.argv.length === 0 || seed === undefined) {
    return (
      <code className="cmd" aria-label="Preview">
        ·
      </code>
    );
  }
  const cvd =
    host.kind !== "slurm" && check.plan !== null && check.plan.cvd.length > 0
      ? `CUDA_VISIBLE_DEVICES=${check.plan.cvd.join(",")} `
      : "";
  return (
    <code className="cmd" aria-label="Preview" title={`Seed ${seed}, as it will run on ${host.name}`}>
      <span className="hostp">{host.name}:</span> {cvd}
      {templateSegments(shellJoin(check.argv)).map((s, i) =>
        s.seed ? (
          <b key={i} className="tok">
            {seed}
          </b>
        ) : (
          <span key={i}>{s.text}</span>
        ),
      )}
    </code>
  );
}

export function LaunchDialog({
  project,
  task,
  repo,
  commit = null,
  title = "New run",
  initial,
  carry = NO_CARRY,
  onClose,
  onLaunched,
}: LaunchDialogProps) {
  const client = useQueryClient();
  const hosts = useLaunchHosts();
  const [draft, setDraft] = useState<LaunchDraft>(() => ({ ...DEFAULT_DRAFT, ...initial }));
  const [attempt, setAttempt] = useState<string>(() => newCommandId());
  const [progress, setProgress] = useState<number | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [launched, setLaunched] = useState<Launched>(NOTHING_LAUNCHED);
  const [copy, setCopy] = useState<CopyState>("idle");
  const inFlight = useRef(false);
  const picked = useRef(false);

  useEffect(() => {
    if (picked.current || hosts.data === undefined) return;
    picked.current = true;
    const name = pickHost(hosts.data, project, draft.host);
    const chosen = hosts.data.find((h) => h.name === name);
    setDraft((d) => ({ ...d, host: name, gpus: chosen ? gpusForHost(d.gpus, chosen) : d.gpus }));
  }, [hosts.data, project, draft.host]);

  useEffect(() => {
    if (copy === "idle") return;
    const timer = setTimeout(() => setCopy("idle"), 1500);
    return () => clearTimeout(timer);
  }, [copy]);

  const now = Date.now();
  const host = hosts.data?.find((h) => h.name === draft.host) ?? null;
  // seeds this dialog started already are never sent again, even under a new attempt id, and
  // the GPU plan counts only the rest (the started seeds hold GPUs of their own by now)
  const check = checkDraft(draft, host, project, now, launched.seeds);
  const n = check.seeds.length;
  const pending = check.pending;
  const busy = progress !== null;
  const blocked = check.blockers.length > 0;
  const spec: LaunchSpec | null =
    host === null || check.argv.length === 0
      ? null
      : {
          host,
          project,
          repo,
          commit,
          task,
          argv: check.argv,
          hypothesis: draft.hypothesis,
          gpus: draft.gpus,
          queue: draft.queue,
          slurm: host.kind === "slurm" ? { partition: draft.partition, account: draft.account, time: draft.time } : null,
          params: carry.params,
          vars: carry.vars,
        };
  // the preview, Copy as CLI and the summary cover only the seeds Launch would send: after a
  // partial launch, pasting the started seeds' lines would start them a second time
  const cli = spec !== null && pending.length > 0 ? launchCli(spec, pending) : "";
  const pin = commit === null ? "" : ` @ ${commit.slice(0, 7)}`;
  const where = host === null ? "" : `${host.kind === "hub" ? repo : `${project} @ ${host.name}`}${pin}`;

  const update: Update = (patch) => {
    setDraft((d) => ({ ...d, ...patch }));
    setAttempt(newCommandId());
    setFailure(null);
  };

  const copyCli = async (): Promise<void> => {
    try {
      await navigator.clipboard.writeText(cli);
      setCopy("copied");
    } catch {
      setCopy("failed");
    }
  };

  const launch = async (): Promise<void> => {
    if (inFlight.current || spec === null || blocked || pending.length === 0) return;
    inFlight.current = true;
    setFailure(null);
    setProgress(0);
    const out = await launchSeeds(spec, pending, attempt, { onProgress: setProgress });
    inFlight.current = false;
    setProgress(null);
    for (const queryKey of REMOTE_RUN_INVALIDATES) void client.invalidateQueries({ queryKey });
    const done: Launched = {
      seeds: [...launched.seeds, ...pending.slice(0, out.records.length)],
      records: [...launched.records, ...out.records],
    };
    setLaunched(done);
    if (out.failed !== null) {
      setFailure({
        seed: out.failed.seed,
        message: out.failed.error.message,
        done: done.seeds.length,
        left: pending.length - out.records.length,
      });
      return;
    }
    onLaunched(done.records, spec.host.name);
  };

  const onKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>): void => {
    if (e.key === "Escape" && !busy) {
      e.stopPropagation();
      onClose();
    }
  };
  const onBackdrop = (e: ReactMouseEvent<HTMLDivElement>): void => {
    if (e.target === e.currentTarget && !busy) onClose();
  };

  return (
    <div className="hx-launch" onKeyDown={onKeyDown} onMouseDown={onBackdrop}>
      <LaunchStyles />
      <div className="dlg" role="dialog" aria-modal="true" aria-labelledby="hx-launch-h">
        <div className="dlg-h">
          <h2 id="hx-launch-h">{title}</h2>
          <span className="small">{task ? `${project} / ${task}` : project}</span>
          <button type="button" className="x" aria-label="Close" disabled={busy} onClick={onClose}>
            ×
          </button>
        </div>
        <div className="dlg-b">
          <div className="fr">
            <span className="lb">Host</span>
            {hosts.error ? (
              <ErrorBox error={hosts.error} />
            ) : hosts.data === undefined ? (
              <Loading />
            ) : (
              <HostPicker
                hosts={hosts.data}
                selected={draft.host}
                project={project}
                now={now}
                onPick={(h) => update({ host: h.name, gpus: gpusForHost(draft.gpus, h) })}
              />
            )}
          </div>
          {host?.kind === "slurm" ? (
            <SlurmRow draft={draft} check={check} update={update} />
          ) : host !== null ? (
            <GpuRows host={host} draft={draft} check={check} update={update} />
          ) : null}
          <div className="fr">
            <label htmlFor="hx-launch-seeds">Seeds</label>
            <div className="row">
              <input
                id="hx-launch-seeds"
                className="in mono w-s"
                value={draft.seeds}
                spellCheck={false}
                title="Integers or ranges: 4, 5, 6 or 1-3"
                aria-invalid={check.seedsError ? true : undefined}
                onChange={(e) => update({ seeds: e.target.value })}
              />
              <span className="lbl-x">×{n}</span>
              {check.seedsError ? <span className="small bad">{check.seedsError}</span> : null}
            </div>
          </div>
          <CommandRow draft={draft} check={check} update={update} where={where} />
          <div className="fr">
            <label htmlFor="hx-launch-hyp">Hypothesis</label>
            <input
              id="hx-launch-hyp"
              className="in w-l"
              value={draft.hypothesis}
              placeholder="why this run exists"
              aria-required="true"
              autoFocus
              onChange={(e) => update({ hypothesis: e.target.value })}
            />
          </div>
          <div className="fr">
            <span className="lb">Preview</span>
            <div className="prev">
              <Preview host={host} check={check} />
              <span className="xn">×{pending.length}</span>
            </div>
          </div>
        </div>
        {failure ? (
          <p className="err" role="alert">
            seed {failure.seed}: {failure.message}. {failure.done} of {failure.done + failure.left} launched; Launch
            sends the other {failure.left}.
          </p>
        ) : null}
        <div className="dlg-f">
          <button
            type="button"
            className="btn"
            disabled={cli === ""}
            title={cli || "Needs a host, seeds and a command"}
            onClick={() => void copyCli()}
          >
            {COPY_TEXT[copy]}
          </button>
          <span className="sum small">
            {host !== null && pending.length > 0 ? launchSummary(host, draft.gpus, pending.length, draft.time) : ""}
          </span>
          <button type="button" className="btn" disabled={busy} onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={busy || blocked || pending.length === 0}
            title={blocked ? check.blockers.join("; ") : `Launch ${pending.length} on ${host?.name ?? ""}`}
            onClick={() => void launch()}
          >
            {progress !== null ? `Launching ${progress}/${pending.length}` : `Launch ${pending.length}`}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /Users/shreyasv/Desktop/code/research_dash/ui && bun test test/launch/LaunchDialog.test.tsx`
Expected: PASS, `20 pass`, `0 fail`.

- [ ] **Step 6: Run every launch test and typecheck**

Run: `cd /Users/shreyasv/Desktop/code/research_dash/ui && bun test test/launch && bun run typecheck`
Expected: `83 pass`, `0 fail` (seeds and command 15, plan 16, cli and draft 20, launchApi 12, dialog 20); `tsc` exits 0.

- [ ] **Step 7: Commit**

```bash
git -C /Users/shreyasv/Desktop/code/research_dash add ui/src/launch/styles.ts ui/src/launch/LaunchDialog.tsx ui/test/launch/LaunchDialog.test.tsx
git -C /Users/shreyasv/Desktop/code/research_dash commit -m "feat(ui): launch dialog with host picker, preview and idempotent launch"
```

---

### Task 13: "New run" on the Task page

**Files:**
- Modify: `ui/src/pages/Task.tsx` (whole file below)
- Test: `ui/test/pages/Task.test.tsx` (imports and one new test)

**Interfaces:**
- Consumes: `LaunchDialog` (Task 12); `launchDefaults` (Task 10); `useTask`, `useRuns`, `queryKeys` from `ui/src/api/queries.ts`; `api.run` from `ui/src/api/client.ts`; `shortId` from `ui/src/pages/components/format.ts`; `hrefs`, `AppLink` from `ui/src/pages/components/links.tsx`.
- Produces: the Task page "New run" button (`btn primary`; "Re-evaluate all" becomes a plain `btn`, as in the mockup), and after a launch a `p.launched` line `Launched N on HOST[, Q queued]: <short id links>`. `TASK_RUNS_LIMIT = 1000`: the dialog's defaults read the task's runs with this limit (the API default of 200 would miss used seeds on a big task and propose seeds that exist; the sweep page uses the same 1000).

- [ ] **Step 1: Write the failing test**

In `ui/test/pages/Task.test.tsx`, replace the fixtures import line

```ts
import { makeBoard } from "./fixtures";
```

with

```ts
import { REPO, RUN_RF, RUN_SVM, makeBoard, makeDetail, makeRecord } from "./fixtures";
```

Then add this test inside `describe("TaskPage", ...)`, after the "Re-evaluate all" test:

```tsx
  test("New run opens the launch dialog from the best config and links the launched runs", async () => {
    const calls = mockApi({
      ...routes("overview"),
      [`GET ${BASE}`]: {
        summary: { project: "toy-classifier", name: "toy-test" },
        repo: REPO,
        dataset: { name: "toyset" },
        metrics: {},
        stages: {},
      },
      [`GET /api/v1/runs/${RUN_SVM}`]: makeDetail(),
      "GET /api/v1/runs?project=toy-classifier&task=toy-test&limit=1000": [
        makeRecord({ run_id: "20260926-200000-toy-test-aa01", seed: 1 }),
        makeRecord({ run_id: "20260926-200100-toy-test-aa02", seed: 2 }),
        makeRecord({ run_id: RUN_RF, seed: 9, config_hash: "sha256:5a810ddb4e0c2f19" }),
      ],
      "GET /api/v1/hosts": [],
      "GET /api/v1/gpus": [],
      "GET /api/v1/queue": [],
      "POST /api/v1/runs": (call: Call) => {
        const seed = (call.body as { seed: number }).seed;
        return makeRecord({ run_id: `20261003-120000-toy-test-s${seed}`, seed, status: "running" });
      },
    });
    renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
    await screen.findByRole("region", { name: "a Best" });
    fireEvent.click(screen.getByRole("button", { name: "New run" }));

    const dialog = await screen.findByRole("dialog", { name: "New run" });
    expect(within(dialog).getByText("toy-classifier / toy-test")).toBeTruthy();
    expect((within(dialog).getByLabelText("Command") as HTMLTextAreaElement).value).toBe(
      "python train_eval.py --model svm --seed={seed}",
    );
    expect((within(dialog).getByLabelText("Seeds") as HTMLInputElement).value).toBe("4, 5, 6");
    await waitFor(() =>
      expect((within(dialog).getByRole("radio", { name: "local" }) as HTMLInputElement).checked).toBe(true),
    );
    fireEvent.change(within(dialog).getByLabelText("Hypothesis"), { target: { value: "svm holds on new seeds" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Launch 3" }));

    const line = await waitFor(() => {
      const el = document.querySelector("p.launched");
      expect(el).not.toBeNull();
      return el as HTMLElement;
    });
    expect(line.textContent).toBe("Launched 3 on local: s4 s5 s6");
    expect(within(line).getByRole("link", { name: "s4" }).getAttribute("href")).toBe(
      "/r/20261003-120000-toy-test-s4",
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    const sent = calls.filter((c) => c.method === "POST" && c.url === "/api/v1/runs");
    expect(sent.map((c) => (c.body as { seed: number }).seed)).toEqual([4, 5, 6]);
    expect(sent[0]?.body).toMatchObject({
      repo: REPO,
      task: "toy-test",
      command: ["python", "train_eval.py", "--model", "svm", "--seed={seed}"],
      hypothesis: "svm holds on new seeds",
      gpus: 0,
      queue: false,
    });
  });
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/shreyasv/Desktop/code/research_dash/ui && bun test test/pages/Task.test.tsx`
Expected: FAIL in the new test with `Unable to find an accessible element with the role "button" and name "New run"`; the 5 old tests pass.

- [ ] **Step 3: Write the implementation**

Replace the whole of `ui/src/pages/Task.tsx` with:

```tsx
/**
 * Task screen (spec 8.3.2): the leaderboard's one-line headline, view tabs (the kind's
 * preset, custom views, `+ view`), and the active view's panels on a 12-column grid.
 * "New run" opens the Launch dialog (spec 8A.8), prefilled from the best config's latest
 * run: its command template, params and vars, and the next unused seeds of that config.
 */
import { useQuery } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { api } from "../api/client";
import type { RunRecord } from "../api/models";
import {
  RUN_EVENT_INVALIDATES,
  queryKeys,
  useLeaderboard,
  useRuns,
  useTask,
  useView,
  useViewQuery,
  useViews,
} from "../api/queries";
import { launchDefaults } from "../launch/draft";
import { LaunchDialog } from "../launch/LaunchDialog";
import { shortId } from "./components/format";
import { AppLink, hrefs } from "./components/links";
import { PanelGrid } from "./components/PanelGrid";
import { ErrorBox, Loading } from "./components/QueryState";
import { PageStyles } from "./components/styles";
import type { Leaderboard } from "./components/types";
import { useAction } from "./components/useAction";
import { Unbroken } from "./components/Headline";

export interface TaskPageProps {
  project: string;
  task: string;
  view?: string;
}

const plural = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`;

/**
 * Runs read for the Launch dialog's defaults (used seeds of the template's config). The API
 * default of 200 would miss seeds on a big task and propose seeds that already exist.
 */
export const TASK_RUNS_LIMIT = 1000;

/** The line under the headline: configs and runs, metric versions, re-eval backlog. */
export function boardMeta(board: Leaderboard): string[] {
  const runs = board.rows.reduce((n, row) => n + row.run_ids.length, 0);
  const out = [
    `${plural(board.rows.length, "config", "configs")}, ${plural(runs, "run", "runs")}`,
    ...Object.entries(board.metric_versions).map(([metric, version]) => `${metric} ${version}`),
  ];
  if (board.needs_reeval.length > 0) out.push(`${board.needs_reeval.length} need re-eval`);
  return out;
}

interface LaunchedRuns {
  host: string;
  records: RunRecord[];
}

interface NewRunProps {
  project: string;
  task: string;
  templateRunId: string | null;
  onClose: () => void;
  onLaunched: (records: RunRecord[], host: string) => void;
}

/** Loads the repo path, the template run and the task's runs, then shows the dialog. */
function NewRun({ project, task, templateRunId, onClose, onLaunched }: NewRunProps) {
  const detail = useTask(project, task);
  const runs = useRuns({ project, task, limit: TASK_RUNS_LIMIT });
  const template = useQuery({
    queryKey: queryKeys.run(templateRunId ?? ""),
    queryFn: ({ signal }) => api.run(templateRunId ?? "", signal),
    enabled: templateRunId !== null,
  });
  if (detail.error) return <ErrorBox error={detail.error} />;
  if (detail.data === undefined || runs.isPending || (templateRunId !== null && template.isPending)) {
    return <Loading />;
  }
  const defaults = launchDefaults(template.data?.record ?? null, runs.data ?? []);
  return (
    <LaunchDialog
      project={project}
      task={task}
      repo={detail.data.repo}
      initial={defaults.draft}
      carry={defaults.carry}
      onClose={onClose}
      onLaunched={onLaunched}
    />
  );
}

/** `Launched 3 on gpu1, 2 queued: f2c8 93e7 c2b9`, each id a link to its run. */
function LaunchedLine({ launched }: { launched: LaunchedRuns }) {
  const queued = launched.records.filter((r) => r.status === "queued").length;
  return (
    <p className="small launched" role="status">
      Launched {launched.records.length} on {launched.host}
      {queued > 0 ? `, ${queued} queued` : ""}:{" "}
      {launched.records.map((r, i) => (
        <Fragment key={r.run_id}>
          {i > 0 ? " " : ""}
          <AppLink href={hrefs.run(r.run_id)}>{shortId(r.run_id)}</AppLink>
        </Fragment>
      ))}
    </p>
  );
}

export function TaskPage({ project, task, view }: TaskPageProps) {
  const active = view ? String(view) : "overview";
  const board = useLeaderboard(project, task);
  const views = useViews(project, task);
  const detail = useView(project, task, active);
  const panels = useViewQuery(project, task, { name: active });
  const reeval = useAction({
    send: (_: void, opts) => api.reevalTask(project, task, {}, opts),
    invalidate: RUN_EVENT_INVALIDATES,
  });
  const [launching, setLaunching] = useState(false);
  const [launched, setLaunched] = useState<LaunchedRuns | null>(null);

  const info = views.data?.find((v) => v.name === active) ?? detail.data?.info;
  const editable = info !== undefined && info.origin !== "preset";
  const viewError = detail.error ?? panels.error;
  const ready = panels.data !== undefined && !detail.isPending;
  const templateRunId = board.data?.rows[0]?.latest_run_id ?? null;

  return (
    <div className="page">
      <PageStyles />
      <p className="crumb">
        <AppLink href={hrefs.overview()}>All projects</AppLink>
        <span className="sep">/</span>
        {project}
        <span className="sep">/</span>
        {task}
        {board.data ? (
          <span className="tag" title="task kind">
            {board.data.kind}
          </span>
        ) : null}
      </p>
      <h1 className="headline">
        <Unbroken text={board.data?.headline ?? task} />
      </h1>
      {board.error ? <ErrorBox error={board.error} /> : null}
      {board.data ? (
        <p className="metaline">
          {boardMeta(board.data).map((text) => (
            <span key={text}>{text}</span>
          ))}
        </p>
      ) : null}

      <nav className="view-tabs" aria-label="Views">
        {(views.data ?? []).map((v) => (
          <AppLink
            key={v.name}
            href={hrefs.task(project, task, v.name)}
            aria-current={v.name === active ? "page" : undefined}
            title={v.path ?? `${v.origin} view`}
          >
            {v.title || v.name}
            {v.origin === "preset" ? (
              <>
                {" "}
                <small>preset</small>
              </>
            ) : null}
          </AppLink>
        ))}
        <AppLink href={hrefs.edit(project, task, "new")} title="New view">
          + view
        </AppLink>
        <span className="r">
          {detail.data ? (
            <span className="small">{plural((detail.data.view.panels ?? []).length, "panel", "panels")}</span>
          ) : null}
          {editable ? (
            <AppLink className="btn" href={hrefs.edit(project, task, active)}>
              Edit
            </AppLink>
          ) : null}
          <button
            type="button"
            className="btn"
            onClick={() => reeval.run()}
            disabled={reeval.pending}
            title="Re-score every run's saved predictions with the current metric versions"
          >
            Re-evaluate all
          </button>
          <button
            type="button"
            className="btn primary"
            onClick={() => setLaunching(true)}
            title="Launch runs of this task on any host"
          >
            New run
          </button>
        </span>
      </nav>
      {views.error ? <ErrorBox error={views.error} /> : null}
      {reeval.error ? <ErrorBox error={reeval.error} /> : null}
      {launched ? <LaunchedLine launched={launched} /> : null}

      {viewError ? (
        <ErrorBox error={viewError} />
      ) : ready && panels.data ? (
        <PanelGrid results={panels.data.panels} specs={detail.data?.view.panels} />
      ) : (
        <Loading />
      )}

      {launching ? (
        <NewRun
          project={project}
          task={task}
          templateRunId={templateRunId}
          onClose={() => setLaunching(false)}
          onLaunched={(records, host) => {
            setLaunching(false);
            setLaunched({ host, records });
          }}
        />
      ) : null}
    </div>
  );
}
```

- [ ] **Step 4: Run the Task tests to verify they pass**

Run: `cd /Users/shreyasv/Desktop/code/research_dash/ui && bun test test/pages/Task.test.tsx`
Expected: PASS, `6 pass`, `0 fail`.

- [ ] **Step 5: Run the whole UI suite and the typecheck**

Run: `cd /Users/shreyasv/Desktop/code/research_dash/ui && bun test && bun run typecheck`
Expected: every test passes (`0 fail`); `tsc` exits 0.

- [ ] **Step 6: Commit**

```bash
git -C /Users/shreyasv/Desktop/code/research_dash add ui/src/pages/Task.tsx ui/test/pages/Task.test.tsx
git -C /Users/shreyasv/Desktop/code/research_dash commit -m "feat(ui): New run button on the task page opens the launch dialog"
```

---

## Group 4: Sweep page `/s/:project/:id` (Tasks 14–22)

The Sweep page from `docs/mockups/phase2/shot-sweep-{light,dark}.png` (spec 5.7, 8A.6): one-line headline with the best cell, meta line, stat strip with cost and ETA, progress strip, (a) a params heat table for two list params (a sortable table otherwise), (b) a seeds forest with 95% intervals, (c) runs on hosts, and the actions Copy as CLI, Cancel queued, Add seeds and Rerun sweep. All arithmetic lives in one pure module (`SweepModel.ts`: parse `summarize_sweep` cells, derive `stale`, heat axes and levels, labels, tooltips, the `hx sweep` command, ETA, GPU-hours, progress, sorting, stat items). Small presentational components (`SweepGlyphs`, `SweepHeat`, `SweepTable`, `SweepForest`, `SweepRuns`, `SweepActions`, `SweepStyles`, `SweepRerun`) take plain props. `pages/Sweep.tsx` loads four queries: the summary (`useSweep`), every run of the sweep once the summary is in (`useAllRuns`, Task 3: `GET /api/v1/runs?project=&tag=<summary.tag>&archived=true&limit=1000`, then larger limits while a page is full), the hosts (stale derivation), and the task leaderboard when the sweep has a task (metric name, direction, unit, version, and seed values: a cell gets dots only when its group's row holds no run outside the cell, so dots and the cell's mean and 95% CI cover the same runs). A run's host is the `GET /api/v1/hosts` row whose `state.environment_id` is the run's `environment_id` (`hostRowForRun`, Task 5), never `executor.host` (the box's own hostname). A queued or running run whose host is not `connected` is drawn stale, as on its run page; nothing is written. Summary cells are read through `parseCells`, so a server that omits the optional `std` and `runs` still renders.

### Task 14: Sweep model, part 1 (cells, run state, axes, labels)

**Files:**
- Create: `ui/src/pages/components/SweepModel.ts`
- Create: `ui/test/pages/sweepFixtures.ts`
- Test: `ui/test/pages/sweepModel.test.ts`

**Interfaces:**
- Consumes: Task 1 models (`HostRow`, `Leaderboard`, `RunRecord`, `RunStatus`, `SweepSpec`, `SweepSummary`), `hostRowForRun` from `./HostsPanel` (Task 5), `format.ts` (`DASH`, `fmtScore`, `isNum`, `parseTime`), test `fixtures.ts` (`makeRecord`, `makeBoard`).
- Produces (later tasks rely on these exact names):
  - `interface SweepCellRun { run_id: string; status: RunStatus | null; seed: number | null }`
  - `interface SweepCellRow { params: Record<string, string>; group_id: string | null; n: number; mean: number | null; lo: number | null; hi: number | null; std: number | null; run_ids: string[]; runs: SweepCellRun[] }`
  - `type RunGlyphState = RunStatus | "stale"`
  - `parseCell(raw: unknown): SweepCellRow | null`, `parseCells(cells: readonly unknown[]): SweepCellRow[]`, `sameParams(a, b): boolean`
  - `hostOf(record: RunRecord, hosts: readonly HostRow[] | undefined): string` (the matched row's name; the machine's hostname `record.host` when no row matches), `staleHosts(hosts: readonly HostRow[] | undefined): Map<string, string>` (environment id → since, for every host that is not `connected`), `runState(record: RunRecord | undefined, fallback: RunStatus | null, stale: ReadonlyMap<string, string>): RunGlyphState` (`stale` for a queued or running run whose environment is in `stale`), `fmtAge(seconds: number): string`, `stateText(record, state, stale, now): string`
  - `interface HeatAxes { row: string; col: string; rows: string[]; cols: string[] }`, `heatAxes(spec: SweepSpec): HeatAxes | null`, `rankCells(cells, higherIsBetter): SweepCellRow[]`, `heatLevel(mean, lo, hi, higherIsBetter): number`, `heatPercent(level): number`
  - `cellLabel(params, names): string`, `paramsText(params, names): string`, `gridLabel(spec): string`, `cellTip(cell, names, seeds): string`, `meanOf(values): number | null`, `seedValues(cell, board?): number[]` (the cell's own runs only: the group row's values when all its runs are the cell's, else none)
  - `orderRuns(runs, order): RunRecord[]`, `hostsOf(runs, hosts): string[]`, `sweepHref(project, sweepId): string`
  - Test fixtures: `PROJECT`, `TASK`, `SWEEP_ID`, `NOW`, `TEMPLATE`, `rid`, `RUNS`, `run`, `CELL_A..CELL_D`, `RAW_CELLS`, `makeSummary`, `makeSweepBoard`, `HOSTS`, `STALE`.

- [ ] **Step 1: Write the fixtures**

Create `ui/test/pages/sweepFixtures.ts`:

```ts
/**
 * Sweep page fixtures: lr {1e-4, 3e-4} × beam {5, 10} × seeds {1, 2} = 8 runs on gpu1
 * and dgx. dgx is stale. Status: 5 finished, b2 running (on dgx, so drawn stale),
 * a2 queued at position 2, c2 failed with exit 1. "Now" is 2026-10-03 12:00 UTC.
 *
 * As the backend writes them, `executor.host` and `host` hold each machine's own hostname
 * (`sv-a100-01`, `dgx-h100-07`), not the hub's host names; runs match their host by
 * `environment_id` (`env-gpu1`, `env-dgx`).
 */
import type { HostRow, Leaderboard, LeaderboardRow, RunRecord, RunStatus, SweepSummary } from "../../src/api/models";
import { makeBoard, makeRecord } from "./fixtures";

export const PROJECT = "rxn";
export const TASK = "fwd";
export const SWEEP_ID = "s-7f3a";
/** The member tag the backend sends as `SweepSummary.tag` (the hub's id prefix, then the id). */
export const SWEEP_TAG = `sweep:0a1b2c3d:${SWEEP_ID}`;
export const NOW = Date.parse("2026-10-03T12:00:00Z");
export const TEMPLATE = ["python", "train.py", "--lr", "{lr}", "--beam", "{beam}", "--seed", "{seed}"];

/** Full run id for a short tail: `rid("a1")` → `20261003-091200-fwd-a1` (`shortId` gives `a1`). */
export const rid = (tail: string): string => `20261003-091200-fwd-${tail}`;

interface RunSpec {
  tail: string;
  lr: string;
  beam: string;
  seed: number;
  status: RunStatus;
  host: string;
  started?: string;
  ended?: string;
  gpuHours?: number;
  usd?: number;
  queuePos?: number;
  exit?: number;
}

const DONE = { started: "2026-10-03T09:00:00Z", ended: "2026-10-03T10:00:00Z", gpuHours: 2, usd: 2.4 };

/** Each fake host's own hostname (`socket.gethostname()`), what the backend puts in `executor.host`. */
export const HOSTNAME: Record<string, string> = { gpu1: "sv-a100-01", dgx: "dgx-h100-07" };

const RUN_SPECS: RunSpec[] = [
  { tail: "a1", lr: "1e-4", beam: "5", seed: 1, status: "finished", host: "gpu1", ...DONE },
  { tail: "b1", lr: "1e-4", beam: "10", seed: 1, status: "finished", host: "gpu1", ...DONE },
  { tail: "c1", lr: "3e-4", beam: "5", seed: 1, status: "finished", host: "gpu1", ...DONE },
  { tail: "d1", lr: "3e-4", beam: "10", seed: 1, status: "finished", host: "dgx", ...DONE },
  { tail: "a2", lr: "1e-4", beam: "5", seed: 2, status: "queued", host: "gpu1", queuePos: 2 },
  { tail: "b2", lr: "1e-4", beam: "10", seed: 2, status: "running", host: "dgx", started: "2026-10-03T11:30:00Z" },
  {
    tail: "c2",
    lr: "3e-4",
    beam: "5",
    seed: 2,
    status: "failed",
    host: "gpu1",
    started: "2026-10-03T10:00:00Z",
    ended: "2026-10-03T10:06:00Z",
    gpuHours: 0.2,
    usd: 0.42,
    exit: 1,
  },
  { tail: "d2", lr: "3e-4", beam: "10", seed: 2, status: "finished", host: "dgx", ...DONE },
];

/** One sweep run; spreads `makeRecord` first so every other required field is present. */
function sweepRun(s: RunSpec): RunRecord {
  const base = makeRecord({ run_id: rid(s.tail) });
  const ran = s.started !== undefined;
  return {
    ...base,
    project: PROJECT,
    task: TASK,
    environment_id: `env-${s.host}`,
    host: HOSTNAME[s.host] ?? s.host,
    hypothesis: "tune lr and beam",
    command: ["python", "train.py", "--lr", s.lr, "--beam", s.beam, "--seed", String(s.seed)],
    command_template: TEMPLATE,
    params: { lr: s.lr, beam: s.beam },
    vars: { lr: s.lr, beam: s.beam },
    seed: s.seed,
    status: s.status,
    created_at: "2026-10-03T09:00:00Z",
    started_at: s.started ?? null,
    ended_at: s.ended ?? null,
    exit_code: s.exit ?? (s.status === "finished" ? 0 : null),
    artifacts: [],
    tags: [SWEEP_TAG],
    created_by: "agent:tuner",
    executor: {
      ...base.executor,
      host: HOSTNAME[s.host] ?? s.host,
      gpus: ran ? [0, 1] : [],
      slurm_job_id: null,
      node: null,
      queue_position: s.queuePos ?? null,
    },
    cost:
      s.gpuHours !== undefined
        ? { gpu_hours: s.gpuHours, gpu_usd: s.usd ?? 0, api_usd: 0, total_usd: s.usd ?? 0 }
        : null,
    sweep_id: SWEEP_ID,
    gpus_requested: 2,
  };
}

/** The 8 runs in launch (`SweepSummary.run_ids`) order. */
export const RUNS: RunRecord[] = RUN_SPECS.map(sweepRun);

export function run(tail: string): RunRecord {
  return RUNS.find((r) => r.run_id === rid(tail)) as RunRecord;
}

type RawRun = [tail: string, status: RunStatus, seed: number];

function rawCell(
  lr: string,
  beam: string,
  n: number,
  mean: number | null,
  lo: number | null,
  hi: number | null,
  std: number | null,
  runs: RawRun[],
): Record<string, unknown> {
  return {
    params: { lr, beam },
    group_id: n > 0 ? `g-${lr}-${beam}` : null,
    n,
    mean,
    lo,
    hi,
    std,
    run_ids: runs.map(([tail]) => rid(tail)),
    runs: runs.map(([tail, status, seed]) => ({ run_id: rid(tail), status, seed })),
  };
}

/** `summarize_sweep` cells as JSON (contract 1.7 plus the backend plan's optional `std` and `runs`). */
export const CELL_A = rawCell("1e-4", "5", 1, 0.89, 0.885, 0.895, null, [
  ["a1", "finished", 1],
  ["a2", "queued", 2],
]);
export const CELL_B = rawCell("1e-4", "10", 1, 0.9, 0.895, 0.905, null, [
  ["b1", "finished", 1],
  ["b2", "running", 2],
]);
export const CELL_C = rawCell("3e-4", "5", 1, 0.904, 0.899, 0.909, null, [
  ["c1", "finished", 1],
  ["c2", "failed", 2],
]);
export const CELL_D = rawCell("3e-4", "10", 2, 0.912, 0.908, 0.916, 0.0014, [
  ["d1", "finished", 1],
  ["d2", "finished", 2],
]);
export const RAW_CELLS: Record<string, unknown>[] = [CELL_A, CELL_B, CELL_C, CELL_D];

/** `GET /api/v1/sweeps/rxn/s-7f3a`; `over` replaces summary fields, `specOver` spec fields. */
export function makeSummary(
  over: Record<string, unknown> = {},
  specOver: Record<string, unknown> = {},
): SweepSummary {
  return {
    spec: {
      id: SWEEP_ID,
      project: PROJECT,
      task: TASK,
      host: null,
      grid: [
        { name: "lr", values: ["1e-4", "3e-4"], low: null, high: null, log: false },
        { name: "beam", values: ["5", "10"], low: null, high: null, log: false },
      ],
      random: null,
      seeds: [1, 2],
      command_template: TEMPLATE,
      created_by: "agent:tuner",
      created_at: "2026-10-03T09:12:00Z",
      ...specOver,
    },
    // membership is derived by the backend from the runs tagged `tag` (ruling S8)
    run_ids: ["a1", "b1", "c1", "d1", "a2", "b2", "c2", "d2"].map(rid),
    tag: SWEEP_TAG,
    counts: { queued: 1, running: 1, finished: 5, failed: 1, killed: 0, lost: 0, total: 8 },
    cells: RAW_CELLS,
    best: CELL_D,
    headline: "lr 3e-4, beam 10: 0.912 top1, +0.008 over beam 5",
    total_usd: 12.5,
    ...over,
  } as unknown as SweepSummary;
}

function boardRow(group: string, ids: string[], values: number[], mean: number): LeaderboardRow {
  const base = makeBoard().rows[1] as LeaderboardRow;
  return {
    ...base,
    group_id: group,
    run_ids: ids,
    latest_run_id: ids.at(-1) ?? "",
    n: values.length,
    primary: { mean, std: 0, n: values.length, ci_low: null, ci_high: null },
    seed_values: { "top1/value": values },
    identical_seeds: false,
    test_interval: null,
    vs_best: null,
  };
}

/** The task leaderboard: one row per scored cell, keyed by the cells' group ids. */
export function makeSweepBoard(): Leaderboard {
  return {
    ...makeBoard(),
    project: PROJECT,
    task: TASK,
    primary: "top1/value",
    higher_is_better: true,
    metric_versions: { top1: "v1" },
    unit: "",
    rows: [
      boardRow("g-3e-4-10", [rid("d1"), rid("d2")], [0.911, 0.913], 0.912),
      boardRow("g-3e-4-5", [rid("c1")], [0.904], 0.904),
      boardRow("g-1e-4-10", [rid("b1")], [0.9], 0.9),
      boardRow("g-1e-4-5", [rid("a1")], [0.89], 0.89),
    ],
    headline: "top1 0.912",
    stat_strip: [],
  };
}

function hostRow(name: string, state: string, since: string): HostRow {
  return {
    name,
    kind: "ssh",
    state: {
      name,
      kind: "ssh",
      state,
      since,
      message: "",
      environment_id: `env-${name}`,
      hx_version: "0.2.0",
      last_sequence: 0,
      local_port: null,
    },
    gpus: [],
    queue: 0,
    slurm: null,
    cost_today_usd: 0,
    projects: [PROJECT],
  } as unknown as HostRow;
}

/** `GET /api/v1/hosts`: gpu1 connected, dgx stale since 11:56 (4 minutes before NOW). */
export const HOSTS: HostRow[] = [
  hostRow("gpu1", "connected", "2026-10-03T08:00:00Z"),
  hostRow("dgx", "stale", "2026-10-03T11:56:00Z"),
];

/** `staleHosts(HOSTS)`: environment id → since, for every host that is not connected. */
export const STALE: ReadonlyMap<string, string> = new Map([["env-dgx", "2026-10-03T11:56:00Z"]]);
```

- [ ] **Step 2: Write the failing tests**

Create `ui/test/pages/sweepModel.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import type { HostRow, RunRecord, SweepParam, SweepSpec } from "../../src/api/models";
import {
  type SweepCellRow,
  cellLabel,
  cellTip,
  fmtAge,
  gridLabel,
  heatAxes,
  heatLevel,
  heatPercent,
  hostOf,
  hostsOf,
  meanOf,
  orderRuns,
  paramsText,
  parseCell,
  parseCells,
  rankCells,
  runState,
  sameParams,
  seedValues,
  staleHosts,
  stateText,
  sweepHref,
} from "../../src/pages/components/SweepModel";
import { CELL_D, HOSTS, NOW, RAW_CELLS, RUNS, STALE, makeSummary, makeSweepBoard, rid, run } from "./sweepFixtures";

const SPEC: SweepSpec = makeSummary().spec;
const NAMES = ["lr", "beam"];
const cells = (): SweepCellRow[] => parseCells(RAW_CELLS);
const param = (
  name: string,
  values: string[] | null,
  low: number | null = null,
  high: number | null = null,
  log = false,
): SweepParam => ({ name, values, low, high, log });

describe("parseCells", () => {
  test("turns summary cells into typed rows", () => {
    expect(cells()).toHaveLength(4);
    expect(cells()[0]).toEqual({
      params: { lr: "1e-4", beam: "5" },
      group_id: "g-1e-4-5",
      n: 1,
      mean: 0.89,
      lo: 0.885,
      hi: 0.895,
      std: null,
      run_ids: [rid("a1"), rid("a2")],
      runs: [
        { run_id: rid("a1"), status: "finished", seed: 1 },
        { run_id: rid("a2"), status: "queued", seed: 2 },
      ],
    });
    expect(sameParams(cells()[3]?.params ?? {}, { beam: "10", lr: "3e-4" })).toBe(true);
    expect(sameParams({ lr: "3e-4" }, { lr: "3e-4", beam: "10" })).toBe(false);
  });

  test("keeps a cell without runs or stats and drops junk", () => {
    expect(parseCell(null)).toBeNull();
    expect(parseCell({})).toBeNull();
    expect(parseCell([1, 2])).toBeNull();
    expect(parseCell({ params: { lr: 0.001 }, run_ids: ["x"] })).toEqual({
      params: { lr: "0.001" },
      group_id: null,
      n: 0,
      mean: null,
      lo: null,
      hi: null,
      std: null,
      run_ids: ["x"],
      runs: [{ run_id: "x", status: null, seed: null }],
    });
    expect(parseCells([null, RAW_CELLS[0], "junk"])).toHaveLength(1);
  });

  test("an unknown run status becomes null and a run without id is dropped", () => {
    const parsed = parseCell({ params: {}, runs: [{ run_id: "x", status: "paused", seed: 3 }, { status: "queued" }] });
    expect(parsed?.runs).toEqual([{ run_id: "x", status: null, seed: 3 }]);
    expect(parsed?.run_ids).toEqual(["x"]);
  });
});

describe("run state", () => {
  test("a queued or running run on a host that is not connected is stale; other states pass through", () => {
    expect(staleHosts(HOSTS)).toEqual(new Map([["env-dgx", "2026-10-03T11:56:00Z"]]));
    expect(staleHosts(undefined).size).toBe(0);
    // every state but connected counts; a host that never connected has no environment yet
    const [gpu1] = HOSTS as [HostRow];
    const off: HostRow = {
      ...gpu1,
      name: "gpu3",
      state: { ...gpu1.state, name: "gpu3", state: "disabled", since: "2026-10-03T10:00:00Z", environment_id: "env-gpu3" },
    };
    const fresh: HostRow = { ...gpu1, name: "gpu4", state: { ...gpu1.state, name: "gpu4", state: "connecting", environment_id: null } };
    expect(staleHosts([...HOSTS, off, fresh])).toEqual(
      new Map([
        ["env-dgx", "2026-10-03T11:56:00Z"],
        ["env-gpu3", "2026-10-03T10:00:00Z"],
      ]),
    );
    expect(runState(run("b2"), null, STALE)).toBe("stale");
    expect(runState(run("b2"), null, new Map())).toBe("running");
    expect(runState(run("d1"), null, STALE)).toBe("finished");
    expect(runState(run("a2"), "finished", STALE)).toBe("queued");
    // a queued run on a host that is not connected is stale too, as its run page says
    expect(runState({ ...run("a2"), environment_id: "env-dgx" }, null, STALE)).toBe("stale");
    // matched by environment, not by executor.host (the box's own hostname)
    expect(runState({ ...run("b2"), environment_id: "env-gpu1" }, null, STALE)).toBe("running");
    // listed by the summary but not mirrored yet: the cell's status, else queued
    expect(runState(undefined, "running", STALE)).toBe("running");
    expect(runState(undefined, null, STALE)).toBe("queued");
  });

  test("stateText names the stale age, queue position, SLURM job, node and exit code", () => {
    expect(stateText(run("b2"), "stale", STALE, NOW)).toBe("stale 4m");
    expect(stateText(run("a2"), "queued", STALE, NOW)).toBe("queued, pos 2");
    expect(stateText(run("c2"), "failed", STALE, NOW)).toBe("failed, exit 1");
    expect(stateText(run("d1"), "finished", STALE, NOW)).toBe("finished");
    const b2 = run("b2");
    const slurm: RunRecord = {
      ...b2,
      executor: { ...b2.executor, slurm_job_id: "48211", node: "c0412", queue_position: null },
    };
    expect(stateText(slurm, "running", STALE, NOW)).toBe("running, c0412");
    expect(stateText({ ...slurm, status: "queued" }, "queued", STALE, NOW)).toBe("queued, job 48211");
    expect(stateText(run("b2"), "stale", new Map(), NOW)).toBe("stale");
    expect(stateText({ ...run("a2"), environment_id: "env-dgx" }, "stale", STALE, NOW)).toBe("stale 4m");
  });

  test("fmtAge", () => {
    expect([fmtAge(42), fmtAge(240), fmtAge(5400), fmtAge(-5)]).toEqual(["42s", "4m", "1h 30m", "0s"]);
  });
});

describe("axes, ranking and heat", () => {
  test("two list params give heat axes in grid order", () => {
    expect(heatAxes(SPEC)).toEqual({ row: "lr", col: "beam", rows: ["1e-4", "3e-4"], cols: ["5", "10"] });
  });

  test("one, three, or sampled params fall back to the table", () => {
    expect(heatAxes({ ...SPEC, grid: [param("lr", ["1e-4"])] })).toBeNull();
    expect(heatAxes({ ...SPEC, grid: [param("lr", ["1e-4"]), param("beam", ["5"]), param("wd", ["0"])] })).toBeNull();
    expect(heatAxes({ ...SPEC, grid: [param("lr", null, 1e-5, 1e-2, true), param("beam", ["5"])] })).toBeNull();
  });

  test("rankCells puts the best scored cell first in the metric's direction", () => {
    const labels = (cs: SweepCellRow[]): string[] => cs.map((c) => cellLabel(c.params, NAMES));
    const withEmpty = [...cells(), parseCell({ params: { lr: "1e-3", beam: "5" }, run_ids: [] }) as SweepCellRow];
    expect(labels(rankCells(withEmpty, true))).toEqual(["3e-4, 10", "3e-4, 5", "1e-4, 10", "1e-4, 5"]);
    expect(labels(rankCells(withEmpty, false))).toEqual(["1e-4, 5", "1e-4, 10", "3e-4, 5", "3e-4, 10"]);
  });

  test("heatLevel is 1 at the best end; heatPercent maps 0..1 to 4..34", () => {
    expect(heatLevel(0.912, 0.89, 0.912, true)).toBe(1);
    expect(heatLevel(0.89, 0.89, 0.912, true)).toBe(0);
    expect(heatLevel(0.89, 0.89, 0.912, false)).toBe(1);
    expect(heatLevel(0.5, 0.5, 0.5, true)).toBe(1);
    expect([heatPercent(0), heatPercent(0.5), heatPercent(1)]).toEqual([4, 19, 34]);
  });
});

describe("labels", () => {
  test("cell, params and grid labels", () => {
    const d = parseCell(CELL_D) as SweepCellRow;
    expect(cellLabel(d.params, NAMES)).toBe("3e-4, 10");
    expect(cellLabel({ lr: "3e-4" }, NAMES)).toBe("3e-4, —");
    expect(paramsText(d.params, NAMES)).toBe("lr 3e-4, beam 10");
    expect(gridLabel(SPEC)).toBe("lr 2 × beam 2 × 2 seeds");
  });

  test("gridLabel shows sampled ranges and the sample count", () => {
    const spec: SweepSpec = {
      ...SPEC,
      grid: [param("lr", null, 0.00001, 0.01, true), param("beam", ["5", "10"])],
      random: 8,
      seeds: [1],
    };
    expect(gridLabel(spec)).toBe("lr 0.00001–0.01 log × beam 2 × 8 samples × 1 seed");
  });

  test("cellTip lists mean, seeds, interval and seed spread", () => {
    const d = parseCell(CELL_D) as SweepCellRow;
    expect(cellTip(d, NAMES, [0.911, 0.913])).toBe(
      "lr 3e-4, beam 10\nmean 0.9120 over 2 seeds\nseeds 0.9110, 0.9130\n95% CI 0.9080–0.9160\nseed σ 0.0014",
    );
    const a = cells()[0] as SweepCellRow;
    expect(cellTip(a, NAMES, [])).toBe("lr 1e-4, beam 5\nmean 0.8900 over 1 seed\n95% CI 0.8850–0.8950");
    const empty = parseCell({ params: { lr: "1e-3", beam: "5" }, run_ids: ["x"] }) as SweepCellRow;
    expect(cellTip(empty, NAMES, [])).toBe("lr 1e-3, beam 5\nno scored runs yet");
  });

  test("meanOf skips gaps; seedValues reads the cell's leaderboard row", () => {
    expect(meanOf([0.89, null, 0.9])).toBeCloseTo(0.895, 10);
    expect(meanOf([null])).toBeNull();
    const board = makeSweepBoard();
    const d = parseCell(CELL_D) as SweepCellRow;
    expect(seedValues(d, board)).toEqual([0.911, 0.913]);
    expect(seedValues(d, undefined)).toEqual([]);
    expect(seedValues(parseCell({ params: {}, run_ids: [] }) as SweepCellRow, board)).toEqual([]);
    // cell A has a1 and a2; its group's row holds a1 only: those are the cell's own runs
    expect(seedValues(parseCell(RAW_CELLS[0]) as SweepCellRow, board)).toEqual([0.89]);
  });

  test("seedValues gives no dots when the task's group also holds runs outside the cell", () => {
    // the same config ran before the sweep: the task leaderboard row mixes those seeds in,
    // while the cell's mean and 95% CI cover the sweep's runs only
    const board = makeSweepBoard();
    const d = parseCell(CELL_D) as SweepCellRow;
    const mixed = {
      ...board,
      rows: board.rows.map((r) =>
        r.group_id === d.group_id
          ? { ...r, run_ids: [...r.run_ids, "20261001-000000-fwd-zz"], seed_values: { "top1/value": [0.911, 0.913, 0.95] } }
          : r,
      ),
    };
    expect(seedValues(d, mixed)).toEqual([]);
  });
});

describe("runs and links", () => {
  test("orderRuns follows the sweep's run ids; hostsOf lists hosts once, in that order", () => {
    const ids = makeSummary().run_ids;
    const ordered = orderRuns([...RUNS].reverse(), ids);
    expect(ordered.map((r) => r.run_id)).toEqual(ids);
    const extra: RunRecord = { ...run("a1"), run_id: "zz-extra" };
    expect(orderRuns([extra, ...RUNS], ids).at(-1)?.run_id).toBe("zz-extra");
    expect(hostsOf(ordered, HOSTS)).toEqual(["gpu1", "dgx"]);
    // without the hosts list: the machines' own hostnames
    expect(hostsOf(ordered, undefined)).toEqual(["sv-a100-01", "dgx-h100-07"]);
  });

  test("hostOf names the hub's host serving the run's environment, never executor.host", () => {
    const b2 = run("b2");
    expect([b2.executor.host, b2.environment_id]).toEqual(["dgx-h100-07", "env-dgx"]);
    expect(hostOf(b2, HOSTS)).toBe("dgx");
    expect(hostOf(b2, undefined)).toBe("dgx-h100-07");
    expect(hostOf({ ...b2, environment_id: "env-elsewhere" }, HOSTS)).toBe("dgx-h100-07");
  });

  test("sweepHref encodes both parts", () => {
    expect(sweepHref("rxn", "s-7f3a")).toBe("/s/rxn/s-7f3a");
    expect(sweepHref("a b", "s/1")).toBe("/s/a%20b/s%2F1");
  });
});
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd ui && bun test test/pages/sweepModel.test.ts`
Expected: FAIL with `error: Cannot find module '../../src/pages/components/SweepModel'` (0 pass).

- [ ] **Step 4: Write the model**

Create `ui/src/pages/components/SweepModel.ts`:

```ts
/**
 * Pure helpers for the Sweep page (spec 8A.6, contract 1.7).
 *
 * `summarize_sweep` cells arrive as JSON objects; `parseCells` turns them into typed rows
 * and tolerates missing fields (a server without `std`/`runs` still renders). A queued or
 * running run on a host that is not connected is shown `stale`: derived here, never stored.
 * Runs are matched to hosts by `environment_id` (`hostRowForRun`), never `executor.host`.
 */
import type { HostRow, Leaderboard, RunRecord, RunStatus, SweepSpec } from "../../api/models";
import { DASH, fmtScore, isNum, parseTime } from "./format";
import { hostRowForRun } from "./HostsPanel";

// ------------------------------------------------------------------------------- cells
/** A run of a cell, as the summary lists it. `status` is null when the server sent none. */
export interface SweepCellRun {
  run_id: string;
  status: RunStatus | null;
  seed: number | null;
}

/** One param combination of a sweep (a `summarize_sweep` cell). */
export interface SweepCellRow {
  params: Record<string, string>;
  group_id: string | null;
  /** Scored seeds. */
  n: number;
  mean: number | null;
  lo: number | null;
  hi: number | null;
  std: number | null;
  run_ids: string[];
  runs: SweepCellRun[];
}

/** What a run glyph shows: a run status, or `stale` for a queued or running run on a host that is not connected. */
export type RunGlyphState = RunStatus | "stale";

const STATUSES: ReadonlySet<string> = new Set(["queued", "running", "finished", "failed", "killed", "lost"]);

const numOrNull = (v: unknown): number | null => (isNum(v) ? v : null);

function asRecord(v: unknown): Record<string, unknown> | null {
  return v !== null && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}

function cellRun(v: unknown): SweepCellRun | null {
  const r = asRecord(v);
  if (r === null || typeof r.run_id !== "string") return null;
  const status = typeof r.status === "string" && STATUSES.has(r.status) ? (r.status as RunStatus) : null;
  return { run_id: r.run_id, status, seed: numOrNull(r.seed) };
}

/**
 * Read one summary cell; null when it has no `params` object.
 *
 * Param values become strings; without a `runs` list the run ids are listed with an
 * unknown status.
 */
export function parseCell(raw: unknown): SweepCellRow | null {
  const r = asRecord(raw);
  const p = asRecord(r?.params);
  if (r === null || p === null) return null;
  const params = Object.fromEntries(Object.entries(p).map(([k, v]) => [k, String(v)]));
  const ids = Array.isArray(r.run_ids) ? r.run_ids.filter((x): x is string => typeof x === "string") : [];
  const listed = Array.isArray(r.runs) ? r.runs.map(cellRun).filter((x): x is SweepCellRun => x !== null) : [];
  const runs = listed.length > 0 ? listed : ids.map((run_id) => ({ run_id, status: null, seed: null }));
  return {
    params,
    group_id: typeof r.group_id === "string" ? r.group_id : null,
    n: isNum(r.n) ? r.n : 0,
    mean: numOrNull(r.mean),
    lo: numOrNull(r.lo),
    hi: numOrNull(r.hi),
    std: numOrNull(r.std),
    run_ids: ids.length > 0 ? ids : runs.map((x) => x.run_id),
    runs,
  };
}

/** Every readable cell, in the server's (expansion) order. */
export function parseCells(cells: readonly unknown[]): SweepCellRow[] {
  return cells.map(parseCell).filter((c): c is SweepCellRow => c !== null);
}

/** Same keys with the same values. */
export function sameParams(a: Record<string, string>, b: Record<string, string>): boolean {
  const keys = Object.keys(a);
  return keys.length === Object.keys(b).length && keys.every((k) => a[k] === b[k]);
}

// ---------------------------------------------------------------------------- run state
/**
 * The hub's name for the host a run executes on: the `GET /api/v1/hosts` row that serves
 * the run's environment (`local` for a hub run). Without a matching row (the list is not
 * loaded, or it failed) the machine's own hostname, `record.host`. Never `executor.host`:
 * the backend writes that same machine hostname there, not the hub's name.
 */
export function hostOf(record: RunRecord, hosts: readonly HostRow[] | undefined): string {
  return hostRowForRun(record, hosts)?.name ?? record.host;
}

/**
 * Environment id → ISO time its host left `connected`, for every host that is not connected
 * (stale, error, disabled, ...; contract 1.5, spec 5.6). Keyed by environment, the way the
 * backend matches runs to hosts.
 */
export function staleHosts(hosts: readonly HostRow[] | undefined): Map<string, string> {
  const out = new Map<string, string>();
  for (const h of hosts ?? []) {
    const env = h.state.environment_id;
    if (env && h.state.state !== "connected") out.set(env, h.state.since);
  }
  return out;
}

/**
 * The state a run is drawn with.
 *
 * The record's status wins; a run not indexed yet uses the cell's status (else `queued`).
 * A queued or running run whose environment is in `stale` is `stale` (the run page shows
 * the same run as stale).
 */
export function runState(
  record: RunRecord | undefined,
  fallback: RunStatus | null,
  stale: ReadonlyMap<string, string>,
): RunGlyphState {
  const status = record?.status ?? fallback ?? "queued";
  const active = status === "queued" || status === "running";
  if (active && record !== undefined && stale.has(record.environment_id)) return "stale";
  return status;
}

/** A short age: `42s`, `4m`, `1h 30m`. Negative ages are 0. */
export function fmtAge(seconds: number): string {
  const s = Math.max(0, seconds);
  if (s < 60) return `${Math.floor(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

/** The runs table's state text: `stale 4m`, `queued, pos 2`, `queued, job 48211`, `running, c0412`, `failed, exit 1`. */
export function stateText(
  record: RunRecord,
  state: RunGlyphState,
  stale: ReadonlyMap<string, string>,
  now: number,
): string {
  const ex = record.executor;
  switch (state) {
    case "stale": {
      const since = stale.get(record.environment_id);
      const t = since === undefined ? Number.NaN : parseTime(since);
      return Number.isNaN(t) ? "stale" : `stale ${fmtAge((now - t) / 1000)}`;
    }
    case "queued":
      if (ex.queue_position != null) return `queued, pos ${ex.queue_position}`;
      if (ex.slurm_job_id != null) return `queued, job ${ex.slurm_job_id}`;
      return "queued";
    case "running":
      return ex.node != null ? `running, ${ex.node}` : "running";
    case "failed":
      return record.exit_code !== null ? `failed, exit ${record.exit_code}` : "failed";
    default:
      return state;
  }
}

// ---------------------------------------------------------------------- axes and ranking
/** Rows and columns of the heat table. */
export interface HeatAxes {
  row: string;
  col: string;
  rows: string[];
  cols: string[];
}

/** Heat axes for exactly two listed params (first = rows); null otherwise (use the table). */
export function heatAxes(spec: SweepSpec): HeatAxes | null {
  if (spec.grid.length !== 2) return null;
  const [a, b] = spec.grid;
  if (!a?.values || !b?.values) return null;
  return { row: a.name, col: b.name, rows: a.values.map(String), cols: b.values.map(String) };
}

/** Scored cells, best first in the metric's direction (ties keep expansion order). */
export function rankCells(cells: readonly SweepCellRow[], higherIsBetter: boolean): SweepCellRow[] {
  const sign = higherIsBetter ? -1 : 1;
  return cells.filter((c) => c.mean !== null).sort((a, b) => sign * ((a.mean ?? 0) - (b.mean ?? 0)));
}

/** 0 at the worst mean, 1 at the best; 1 when every mean is equal. */
export function heatLevel(mean: number, lo: number, hi: number, higherIsBetter: boolean): number {
  if (hi === lo) return 1;
  const t = (mean - lo) / (hi - lo);
  return higherIsBetter ? t : 1 - t;
}

/** Ink share of a heat cell in percent: 4 % (worst) to 34 % (best), as in the mockup. */
export function heatPercent(level: number): number {
  return Math.round(4 + level * 30);
}

// ---------------------------------------------------------------------------- labels
/** `3e-4, 10`: the cell's values in param order. */
export function cellLabel(params: Record<string, string>, names: readonly string[]): string {
  return names.map((n) => params[n] ?? DASH).join(", ");
}

/** `lr 3e-4, beam 10`. */
export function paramsText(params: Record<string, string>, names: readonly string[]): string {
  return names.map((n) => `${n} ${params[n] ?? DASH}`).join(", ");
}

/** `lr 3 × beam 3 × 3 seeds`; sampled params show their range, `N samples` follows. */
export function gridLabel(spec: SweepSpec): string {
  const parts = spec.grid.map((p) =>
    p.values ? `${p.name} ${p.values.length}` : `${p.name} ${p.low ?? DASH}–${p.high ?? DASH}${p.log ? " log" : ""}`,
  );
  if (spec.random != null) parts.push(`${spec.random} samples`);
  parts.push(`${spec.seeds.length} seed${spec.seeds.length === 1 ? "" : "s"}`);
  return parts.join(" × ");
}

/** Mean of the finite values, null without any. */
export function meanOf(values: readonly (number | null)[]): number | null {
  const xs = values.filter(isNum);
  return xs.length > 0 ? xs.reduce((s, v) => s + v, 0) / xs.length : null;
}

/**
 * Per-seed primary values of a cell's own runs, for the seed dots.
 *
 * The values come from the task leaderboard row of the cell's group, but only when every run
 * of that row is one of the cell's runs: then they are exactly the population of the cell's
 * mean and 95% CI (the backend scores the cell on the sweep's runs only). When the group also
 * holds runs outside the cell (the same config ran before the sweep), the row's seed values
 * mix them in and cannot be split per run, so the cell shows no dots. Empty without a row.
 */
export function seedValues(cell: SweepCellRow, board: Leaderboard | undefined): number[] {
  if (board === undefined || cell.group_id === null) return [];
  const row = board.rows.find((r) => r.group_id === cell.group_id);
  if (row === undefined) return [];
  const own = new Set(cell.run_ids);
  if (!row.run_ids.every((id) => own.has(id))) return [];
  return row.seed_values[board.primary] ?? [];
}

/** Hover text of a cell: params, mean over seeds, seed values, 95% interval, seed σ. */
export function cellTip(cell: SweepCellRow, names: readonly string[], seeds: readonly number[]): string {
  const lines = [paramsText(cell.params, names)];
  if (cell.mean === null) {
    lines.push("no scored runs yet");
    return lines.join("\n");
  }
  lines.push(`mean ${fmtScore(cell.mean)} over ${cell.n} seed${cell.n === 1 ? "" : "s"}`);
  if (seeds.length > 0) lines.push(`seeds ${seeds.map((v) => fmtScore(v)).join(", ")}`);
  if (cell.lo !== null && cell.hi !== null) lines.push(`95% CI ${fmtScore(cell.lo)}–${fmtScore(cell.hi)}`);
  if (cell.std !== null) lines.push(`seed σ ${fmtScore(cell.std)}`);
  return lines.join("\n");
}

// ------------------------------------------------------------------------- runs, links
/** Runs in the sweep's launch order (`SweepSummary.run_ids`); others last, oldest first. */
export function orderRuns(runs: readonly RunRecord[], order: readonly string[]): RunRecord[] {
  const at = new Map(order.map((id, i) => [id, i]));
  const pos = (r: RunRecord): number => at.get(r.run_id) ?? order.length;
  return [...runs].sort(
    (a, b) =>
      pos(a) - pos(b) || parseTime(a.created_at) - parseTime(b.created_at) || a.run_id.localeCompare(b.run_id),
  );
}

/** Hosts the runs execute on (`hostOf`), each once, in run order. */
export function hostsOf(runs: readonly RunRecord[], hosts: readonly HostRow[] | undefined): string[] {
  return [...new Set(runs.map((r) => hostOf(r, hosts)))];
}

/** In-app link to a sweep page. */
export function sweepHref(project: string, sweepId: string): string {
  return `/s/${encodeURIComponent(project)}/${encodeURIComponent(sweepId)}`;
}
```

- [ ] **Step 5: Run the tests and the type check**

Run: `cd ui && bun test test/pages/sweepModel.test.ts`
Expected: `18 pass`, `0 fail`.

Run: `cd ui && bun run typecheck`
Expected: exits 0 with no errors.

- [ ] **Step 6: Commit**

```bash
git add ui/src/pages/components/SweepModel.ts ui/test/pages/sweepFixtures.ts ui/test/pages/sweepModel.test.ts
git commit -m "feat(ui): sweep model for cells, run states, heat axes and labels"
```

---

### Task 15: Sweep model, part 2 (CLI, seeds, ETA, cost, progress, sort, stats)

**Files:**
- Modify: `ui/src/pages/components/SweepModel.ts` (import block; append a section)
- Test: `ui/test/pages/sweepStats.test.ts`

**Interfaces:**
- Consumes: Task 14 (`SweepCellRow`, `paramsText`, `hostOf`, `orderRuns`, `parseCell`, `parseCells`); `nextSeeds` from `ui/src/launch/seeds.ts` (Task 8); `cliQuote` from `ui/src/launch/cli.ts` (Task 10, the Launch dialog's quoting); `format.ts` (`DASH`, `fmtDuration`, `fmtInterval`, `fmtScoreUnit`, `fmtUsd`, `isNum`, `runSeconds`, `shortId`); models `HostRow`, `StatItem`.
- Produces:
  - `MAX_NEW_SEEDS = 20`; `sweepCli(spec: SweepSpec, runs: readonly RunRecord[]): string`; `nextSeeds` (re-exported from `ui/src/launch/seeds.ts`, Task 8: `nextSeeds(used, n)` gives `n` seeds after the largest one used); `parseSeedCount(text: string): number | null`
  - `etaSeconds(runs, now): number | null`; `gpuHours(record, now): number`; `gpuHoursByHost(runs, now, hosts): Map<string, number>` (keyed by `hostOf`); `fmtGpuHours(hours): string`; `runUsd(record): number | null`
  - `type ProgressKind = "f" | "r" | "q" | "x" | "k" | "n"`; `progressSegments(counts): ProgressKind[]`; `progressLabel(counts): string`
  - `interface SortState { key: string; dir: "asc" | "desc" }`; `defaultSort(higherIsBetter): SortState`; `nextSort(prev, key, higherIsBetter): SortState`; `sortCells(cells, sort): SweepCellRow[]`
  - `interface SweepStatsInput { counts; totalUsd; best; names; metric; unit; runs; hosts; now }`; `sweepStats(input): StatItem[]`

The `hx sweep` flags follow spec 8A.6 and the mockup: `-t T --grid k=v1,v2 [--random N --param k=lo:hi[:log]] --seeds 1,2,3 [--host H] [--gpus N] [--queue] [-H hypothesis] -- <template>`. `--queue` is added when any sweep run is or was in a host queue (`status queued` or a `queue_position`); `--gpus` is the runs' `gpus_requested`; `-H` is the runs' hypothesis. `--seeds` with one number is a count (`parse_seeds`: `--seeds 5` means seeds 1 to 5), so a sweep with the single seed 5 is written `--seeds 5,` (the backend reads any text with a comma as a list; no backend change); a single seed 1 stays `--seeds 1`. Every argument goes through `cliQuote`, so `{lr}` and a template argument like `--x={1,2}` are quoted and bash cannot brace-expand them.

- [ ] **Step 1: Write the failing tests**

Create `ui/test/pages/sweepStats.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import type { SweepParam, SweepSpec } from "../../src/api/models";
import {
  type SweepCellRow,
  defaultSort,
  etaSeconds,
  fmtGpuHours,
  gpuHours,
  gpuHoursByHost,
  nextSeeds,
  nextSort,
  orderRuns,
  parseCell,
  parseCells,
  parseSeedCount,
  progressLabel,
  progressSegments,
  runUsd,
  sortCells,
  sweepCli,
  sweepStats,
} from "../../src/pages/components/SweepModel";
import { CELL_D, HOSTS, NOW, RUNS, makeSummary, rid, run } from "./sweepFixtures";

const SPEC: SweepSpec = makeSummary().spec;
const COUNTS = makeSummary().counts;
const ORDERED = orderRuns(RUNS, makeSummary().run_ids);
const param = (
  name: string,
  values: string[] | null,
  low: number | null = null,
  high: number | null = null,
  log = false,
): SweepParam => ({ name, values, low, high, log });

describe("sweepCli", () => {
  test("rebuilds the hx sweep command of a grid sweep", () => {
    expect(sweepCli(SPEC, RUNS)).toBe(
      "hx sweep -t fwd --grid lr=1e-4,3e-4 --grid beam=5,10 --seeds 1,2 --gpus 2 --queue " +
        "-H 'tune lr and beam' -- python train.py --lr '{lr}' --beam '{beam}' --seed '{seed}'",
    );
  });

  test("random samples, a host, and no runs yet", () => {
    const spec: SweepSpec = {
      ...SPEC,
      task: null,
      host: "gpu1",
      random: 8,
      seeds: [1, 2, 3],
      grid: [param("lr", null, 0.00001, 0.01, true), param("beam", ["5", "10"])],
      command_template: ["python", "train.py", "--lr", "{lr}", "--note", "a b"],
    };
    expect(sweepCli(spec, [])).toBe(
      "hx sweep --grid beam=5,10 --random 8 --param lr=0.00001:0.01:log --seeds 1,2,3 --host gpu1 " +
        "-- python train.py --lr '{lr}' --note 'a b'",
    );
  });

  test("quotes param values a shell would split", () => {
    const spec: SweepSpec = { ...SPEC, grid: [param("tag", ["a b", "c"])], seeds: [1], command_template: ["run"] };
    expect(sweepCli(spec, [])).toBe("hx sweep -t fwd --grid 'tag=a b,c' --seeds 1 -- run");
  });

  test("one seed other than 1 is a one-element list; braces are quoted, so bash cannot expand them", () => {
    const one: SweepSpec = {
      ...SPEC,
      grid: [param("x", ["1"])],
      seeds: [5],
      command_template: ["run", "--x={1,2}", "{seed}"],
    };
    // `--seeds 5` would be a count (seeds 1 to 5); `5,` is the list with seed 5
    expect(sweepCli(one, [])).toBe("hx sweep -t fwd --grid x=1 --seeds 5, -- run '--x={1,2}' '{seed}'");
    expect(sweepCli({ ...one, seeds: [1] }, [])).toContain(" --seeds 1 -- ");
    expect(sweepCli({ ...one, seeds: [3, 1] }, [])).toContain(" --seeds 3,1 -- ");
  });
});

describe("seeds to add", () => {
  test("nextSeeds continues after the largest seed; parseSeedCount accepts 1..20", () => {
    expect(nextSeeds([1, 2], 2)).toEqual([3, 4]);
    expect(nextSeeds([5, 1], 1)).toEqual([6]);
    expect(nextSeeds([], 3)).toEqual([1, 2, 3]);
    expect(["3", " 4 ", "0", "21", "2.5", "", "x"].map((t) => parseSeedCount(t))).toEqual([
      3,
      4,
      null,
      null,
      null,
      null,
      null,
    ]);
  });
});

describe("ETA, GPU-hours and cost", () => {
  test("etaSeconds: median run time × work left ÷ runs running", () => {
    // finished runs took 1 h; b2 has run 30 min (30 min left); a2 waits (1 h)
    expect(etaSeconds(RUNS, NOW)).toBe(5400);
    const early = { ...run("b2"), run_id: rid("x9"), started_at: "2026-10-03T11:00:00Z" };
    // two running: (30 min + 0 + 1 h) ÷ 2
    expect(etaSeconds([...RUNS, early], NOW)).toBe(2700);
  });

  test("etaSeconds is null without a finished run or with nothing left", () => {
    expect(etaSeconds(RUNS.filter((r) => r.status !== "finished"), NOW)).toBeNull();
    expect(etaSeconds(RUNS.filter((r) => r.status === "finished"), NOW)).toBeNull();
  });

  test("gpuHours uses the final cost, else wall time × GPUs", () => {
    expect(gpuHours(run("d1"), NOW)).toBe(2);
    expect(gpuHours(run("b2"), NOW)).toBe(1);
    expect(gpuHours(run("a2"), NOW)).toBe(0);
    expect(gpuHours({ ...run("d1"), cost: null }, NOW)).toBe(2);
    const byHost = gpuHoursByHost(ORDERED, NOW, HOSTS);
    expect([...byHost.keys()]).toEqual(["gpu1", "dgx"]);
    expect(byHost.get("gpu1")).toBeCloseTo(6.2, 10);
    expect(byHost.get("dgx")).toBeCloseTo(5, 10);
    expect([fmtGpuHours(11.2), fmtGpuHours(6.2), fmtGpuHours(0)]).toEqual(["11", "6.2", "0.0"]);
  });

  test("runUsd: final cost, else API spend so far, else nothing", () => {
    expect(runUsd(run("c2"))).toBe(0.42);
    expect(runUsd(run("a2"))).toBeNull();
    const usage = { tokens_in: 0, tokens_out: 0, usd: 0.31, seconds: 0, calls: 1 };
    expect(runUsd({ ...run("a2"), usage })).toBe(0.31);
  });
});

describe("progress", () => {
  test("one segment per run: finished, running, queued, failed or lost, killed, pending", () => {
    expect(progressSegments(COUNTS)).toEqual(["f", "f", "f", "f", "f", "r", "q", "x"]);
    const more = { ...COUNTS, killed: 1, lost: 1, total: 11 };
    expect(progressSegments(more)).toEqual(["f", "f", "f", "f", "f", "r", "q", "x", "x", "k", "n"]);
    expect(progressLabel(COUNTS)).toBe("5 finished, 1 running, 1 queued, 1 failed");
    expect(progressLabel(more)).toBe("5 finished, 1 running, 1 queued, 2 failed, 1 killed, 1 pending");
  });
});

function raw(id: string, lr: string, beam: string, warmup: string, n: number, mean: number | null): unknown {
  return {
    params: { lr, beam, warmup },
    group_id: n > 0 ? `g-${id}` : null,
    n,
    mean,
    lo: mean === null ? null : mean - 0.02,
    hi: mean === null ? null : mean + 0.02,
    std: null,
    run_ids: [`20261003-${id}`],
    runs: [{ run_id: `20261003-${id}`, status: mean === null ? "queued" : "finished", seed: 1 }],
  };
}

const TABLE = parseCells([
  raw("t1", "1e-4", "5", "100", 2, 0.8),
  raw("t2", "3e-4", "5", "100", 2, 0.85),
  raw("t3", "1e-3", "10", "0", 0, null),
  raw("t4", "3e-5", "10", "0", 1, 0.82),
]);
const lrs = (cs: SweepCellRow[]): (string | undefined)[] => cs.map((c) => c.params.lr);

describe("table sort", () => {
  test("by mean (best first, unscored last), by a numeric param, by n", () => {
    expect(lrs(sortCells(TABLE, defaultSort(true)))).toEqual(["3e-4", "3e-5", "1e-4", "1e-3"]);
    expect(lrs(sortCells(TABLE, defaultSort(false)))).toEqual(["1e-4", "3e-5", "3e-4", "1e-3"]);
    expect(lrs(sortCells(TABLE, { key: "lr", dir: "asc" }))).toEqual(["3e-5", "1e-4", "3e-4", "1e-3"]);
    expect(lrs(sortCells(TABLE, { key: "lr", dir: "desc" }))).toEqual(["1e-3", "3e-4", "1e-4", "3e-5"]);
    expect(lrs(sortCells(TABLE, { key: "n", dir: "asc" }))).toEqual(["1e-3", "3e-5", "1e-4", "3e-4"]);
    expect(lrs(sortCells(TABLE, { key: "warmup", dir: "asc" }))).toEqual(["1e-3", "3e-5", "1e-4", "3e-4"]);
  });

  test("nextSort flips the active column and starts others ascending", () => {
    expect(defaultSort(true)).toEqual({ key: "mean", dir: "desc" });
    expect(nextSort(defaultSort(true), "mean", true)).toEqual({ key: "mean", dir: "asc" });
    expect(nextSort(defaultSort(true), "lr", true)).toEqual({ key: "lr", dir: "asc" });
    expect(nextSort({ key: "lr", dir: "asc" }, "lr", true)).toEqual({ key: "lr", dir: "desc" });
    expect(nextSort({ key: "lr", dir: "asc" }, "mean", false)).toEqual({ key: "mean", dir: "asc" });
  });
});

describe("sweepStats", () => {
  test("best, interval, counts, cost with GPU-hours, ETA", () => {
    const items = sweepStats({
      counts: COUNTS,
      totalUsd: 12.5,
      best: parseCell(CELL_D),
      names: ["lr", "beam"],
      metric: "top1",
      unit: "",
      runs: ORDERED,
      hosts: HOSTS,
      now: NOW,
    });
    expect(items).toEqual([
      { label: "best top1", value: "0.9120", tooltip: "Mean top1 of lr 3e-4, beam 10 over 2 seeds" },
      {
        label: "95% CI",
        value: "0.908–0.916",
        tooltip: "Best cell: test-set 95% interval, or over seeds without per-example scores",
      },
      { label: "finished", value: "5", unit: "/ 8", tooltip: "Runs finished" },
      { label: "running", value: "1", tooltip: "Runs running now" },
      { label: "queued", value: "1", tooltip: "Runs waiting in a host queue" },
      { label: "failed", value: "1", tooltip: "c2 failed, exit 1" },
      { label: "cost, 11 GPU-h", value: "$12.50", tooltip: "gpu1 6.2 GPU-h\ndgx 5.0 GPU-h" },
      { label: "ETA", value: "1h 30m", tooltip: "Median finished run time × runs left ÷ runs running" },
    ]);
  });

  test("an empty sweep shows dashes", () => {
    const counts = { queued: 0, running: 0, finished: 0, failed: 0, killed: 0, lost: 0, total: 0 };
    const items = sweepStats({
      counts,
      totalUsd: 0,
      best: null,
      names: ["lr"],
      metric: "score",
      unit: "",
      runs: [],
      hosts: undefined,
      now: NOW,
    });
    expect(items.map((i) => [i.label, i.value])).toEqual([
      ["best score", "—"],
      ["95% CI", "—"],
      ["finished", "0"],
      ["running", "0"],
      ["queued", "0"],
      ["failed", "0"],
      ["cost, 0.0 GPU-h", "$0"],
      ["ETA", "—"],
    ]);
    expect(items[0]?.tooltip).toBe("No scored runs yet");
    expect(items[6]?.tooltip).toBe("No GPU time yet");
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && bun test test/pages/sweepStats.test.ts`
Expected: FAIL with `SyntaxError: Export named 'defaultSort' not found in module '.../SweepModel.ts'` (0 pass).

- [ ] **Step 3: Replace the import block of `SweepModel.ts`**

In `ui/src/pages/components/SweepModel.ts`, replace these three lines:

```ts
import type { HostRow, Leaderboard, RunRecord, RunStatus, SweepSpec } from "../../api/models";
import { DASH, fmtScore, isNum, parseTime } from "./format";
import { hostRowForRun } from "./HostsPanel";
```

with:

```ts
import type { HostRow, Leaderboard, RunRecord, RunStatus, StatItem, SweepSpec } from "../../api/models";
import { cliQuote } from "../../launch/cli";
import {
  DASH,
  fmtDuration,
  fmtInterval,
  fmtScore,
  fmtScoreUnit,
  fmtUsd,
  isNum,
  parseTime,
  runSeconds,
  shortId,
} from "./format";
import { hostRowForRun } from "./HostsPanel";
```

- [ ] **Step 4: Append the second section to `SweepModel.ts`**

Append at the end of `ui/src/pages/components/SweepModel.ts`:

```ts
// ---------------------------------------------------------------------- actions
/** Most seeds one Add seeds click may add per cell. */
export const MAX_NEW_SEEDS = 20;

/**
 * `--seeds` text. A single number is a count to the CLI (`--seeds 5` means 1 to 5), so one
 * seed other than 1 is written as the one-element list `5,`.
 */
function seedsArg(seeds: readonly number[]): string {
  const [only] = seeds;
  return seeds.length === 1 && only !== 1 ? `${only},` : seeds.join(",");
}

/**
 * The `hx sweep` command that launches the same sweep (spec 8A.6).
 *
 * `--gpus` and `-H` come from the sweep's runs; `--queue` is added when any run is or was
 * queued on a host. Every argument goes through `cliQuote` (as in the Launch dialog), so
 * `{lr}` or `--x={1,2}` is quoted and the shell neither drops nor brace-expands it.
 */
export function sweepCli(spec: SweepSpec, runs: readonly RunRecord[]): string {
  const argv = ["hx", "sweep"];
  if (spec.task) argv.push("-t", spec.task);
  for (const p of spec.grid) if (p.values) argv.push("--grid", `${p.name}=${p.values.join(",")}`);
  if (spec.random != null) {
    argv.push("--random", String(spec.random));
    for (const p of spec.grid) {
      if (!p.values) argv.push("--param", `${p.name}=${p.low ?? ""}:${p.high ?? ""}${p.log ? ":log" : ""}`);
    }
  }
  argv.push("--seeds", seedsArg(spec.seeds));
  if (spec.host) argv.push("--host", spec.host);
  const gpus = runs.find((r) => (r.gpus_requested ?? 0) > 0)?.gpus_requested ?? 0;
  if (gpus > 0) argv.push("--gpus", String(gpus));
  if (runs.some((r) => r.status === "queued" || r.executor.queue_position != null)) argv.push("--queue");
  const hypothesis = runs.map((r) => r.hypothesis.trim()).find((h) => h !== "");
  if (hypothesis) argv.push("-H", hypothesis);
  return `${argv.map(cliQuote).join(" ")} -- ${spec.command_template.map(cliQuote).join(" ")}`;
}

/** `count` new seeds after the largest seed in use (`[1, 2]`, 2 → `[3, 4]`): the Launch dialog's helper. */
export { nextSeeds } from "../../launch/seeds";

/** A whole number from 1 to `MAX_NEW_SEEDS`, else null. */
export function parseSeedCount(text: string): number | null {
  const t = text.trim();
  if (!/^\d+$/.test(t)) return null;
  const n = Number(t);
  return n >= 1 && n <= MAX_NEW_SEEDS ? n : null;
}

// ------------------------------------------------------------------ time and cost
function median(xs: readonly number[]): number {
  const s = [...xs].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 === 1 ? (s[mid] ?? 0) : ((s[mid - 1] ?? 0) + (s[mid] ?? 0)) / 2;
}

/**
 * Seconds until the sweep is done: median finished run time × (queued runs + time left
 * of running runs) ÷ runs running now. Null without a finished run or with nothing left.
 */
export function etaSeconds(runs: readonly RunRecord[], now: number): number | null {
  const done = runs
    .filter((r) => r.status === "finished")
    .map((r) => runSeconds(r, now))
    .filter(isNum);
  const running = runs.filter((r) => r.status === "running");
  const queued = runs.filter((r) => r.status === "queued").length;
  if (done.length === 0 || running.length + queued === 0) return null;
  const typical = median(done);
  const left =
    queued * typical + running.reduce((s, r) => s + Math.max(0, typical - (runSeconds(r, now) ?? 0)), 0);
  return left / Math.max(running.length, 1);
}

/** GPU-hours of a run: its final `cost.gpu_hours`, else wall time so far × GPUs held. */
export function gpuHours(record: RunRecord, now: number): number {
  if (record.cost) return record.cost.gpu_hours;
  const seconds = runSeconds(record, now) ?? 0;
  return (seconds * (record.executor.gpus ?? []).length) / 3600;
}

/** GPU-hours per host (`hostOf`), in run order; hosts with no GPU time are left out. */
export function gpuHoursByHost(
  runs: readonly RunRecord[],
  now: number,
  hosts: readonly HostRow[] | undefined,
): Map<string, number> {
  const out = new Map<string, number>();
  for (const r of runs) {
    const h = gpuHours(r, now);
    const host = hostOf(r, hosts);
    if (h > 0) out.set(host, (out.get(host) ?? 0) + h);
  }
  return out;
}

/** `6.2` below 10, `102` from 10. */
export function fmtGpuHours(hours: number): string {
  return hours < 10 ? hours.toFixed(1) : hours.toFixed(0);
}

/** A run's dollars: final `cost.total_usd`, else API spend so far, else null. */
export function runUsd(record: RunRecord): number | null {
  if (record.cost) return record.cost.total_usd;
  return record.usage && record.usage.usd > 0 ? record.usage.usd : null;
}

// ----------------------------------------------------------------------- progress
/** Progress segment: finished, running, queued, failed or lost, killed, not indexed yet. */
export type ProgressKind = "f" | "r" | "q" | "x" | "k" | "n";

function progressParts(counts: Readonly<Record<string, number>>): [ProgressKind, number][] {
  const c = (k: string): number => counts[k] ?? 0;
  const parts: [ProgressKind, number][] = [
    ["f", c("finished")],
    ["r", c("running")],
    ["q", c("queued")],
    ["x", c("failed") + c("lost")],
    ["k", c("killed")],
  ];
  const known = parts.reduce((s, [, n]) => s + n, 0);
  parts.push(["n", Math.max(0, c("total") - known)]);
  return parts;
}

/** One segment per run, in the order finished, running, queued, failed, killed, pending. */
export function progressSegments(counts: Readonly<Record<string, number>>): ProgressKind[] {
  return progressParts(counts).flatMap(([kind, n]) => Array.from({ length: n }, () => kind));
}

const PROGRESS_WORD: Record<ProgressKind, string> = {
  f: "finished",
  r: "running",
  q: "queued",
  x: "failed",
  k: "killed",
  n: "pending",
};

/** `5 finished, 1 running, 1 queued, 1 failed` (+ killed and pending when present). */
export function progressLabel(counts: Readonly<Record<string, number>>): string {
  return progressParts(counts)
    .filter(([kind, n]) => n > 0 || kind === "f" || kind === "r" || kind === "q" || kind === "x")
    .map(([kind, n]) => `${n} ${PROGRESS_WORD[kind]}`)
    .join(", ");
}

// --------------------------------------------------------------------------- sort
/** Sort column (a param name, `n` or `mean`) and direction. */
export interface SortState {
  key: string;
  dir: "asc" | "desc";
}

/** Best cell first: by mean, descending when higher is better. */
export function defaultSort(higherIsBetter: boolean): SortState {
  return { key: "mean", dir: higherIsBetter ? "desc" : "asc" };
}

/** Clicking the active column flips it; another column starts ascending (`mean`: best first). */
export function nextSort(prev: SortState, key: string, higherIsBetter: boolean): SortState {
  if (prev.key === key) return { key, dir: prev.dir === "asc" ? "desc" : "asc" };
  return key === "mean" ? defaultSort(higherIsBetter) : { key, dir: "asc" };
}

const NUMERIC = /^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i;

function sortValue(cell: SweepCellRow, key: string): number | string | null {
  if (key === "mean") return cell.mean;
  if (key === "n") return cell.n;
  const v = cell.params[key];
  if (v === undefined) return null;
  return NUMERIC.test(v.trim()) ? Number(v) : v;
}

/** Cells sorted by `sort`; numbers (also `1e-4`-style params) compare as numbers, gaps last. */
export function sortCells(cells: readonly SweepCellRow[], sort: SortState): SweepCellRow[] {
  const sign = sort.dir === "asc" ? 1 : -1;
  return cells
    .map((cell, i) => ({ cell, i, v: sortValue(cell, sort.key) }))
    .sort((a, b) => {
      if (a.v === null || b.v === null) return a.v === b.v ? a.i - b.i : a.v === null ? 1 : -1;
      const d =
        typeof a.v === "number" && typeof b.v === "number" ? a.v - b.v : String(a.v).localeCompare(String(b.v));
      return d !== 0 ? sign * d : a.i - b.i;
    })
    .map((x) => x.cell);
}

// -------------------------------------------------------------------------- stats
/** Inputs of the sweep stat strip. */
export interface SweepStatsInput {
  counts: Readonly<Record<string, number>>;
  totalUsd: number;
  best: SweepCellRow | null;
  names: readonly string[];
  metric: string;
  unit: string;
  /** The sweep's runs, in launch order. */
  runs: readonly RunRecord[];
  /** `GET /api/v1/hosts`, to name each run's host (undefined while it loads or fails). */
  hosts: readonly HostRow[] | undefined;
  now: number;
}

const failLine = (r: RunRecord): string =>
  `${shortId(r.run_id)} ${r.status}${r.exit_code !== null ? `, exit ${r.exit_code}` : ""}`;

/** Stat strip: best, 95% CI, finished / total, running, queued, failed, cost with GPU-h, ETA. */
export function sweepStats(input: SweepStatsInput): StatItem[] {
  const { counts, names, metric, unit, runs, hosts, now } = input;
  const c = (k: string): number => counts[k] ?? 0;
  const hours = gpuHoursByHost(runs, now, hosts);
  const total = [...hours.values()].reduce((s, h) => s + h, 0);
  const failed = runs.filter((r) => r.status === "failed" || r.status === "lost");
  const eta = etaSeconds(runs, now);
  const best = input.best !== null && input.best.mean !== null ? input.best : null;
  const seeds = (n: number): string => `${n} seed${n === 1 ? "" : "s"}`;
  return [
    {
      label: `best ${metric}`,
      value: best ? fmtScoreUnit(best.mean, unit) : DASH,
      tooltip: best
        ? `Mean ${metric} of ${paramsText(best.params, names)} over ${seeds(best.n)}`
        : "No scored runs yet",
    },
    {
      label: "95% CI",
      value: best && best.lo !== null && best.hi !== null ? fmtInterval(best.lo, best.hi) : DASH,
      tooltip: "Best cell: test-set 95% interval, or over seeds without per-example scores",
    },
    { label: "finished", value: String(c("finished")), unit: `/ ${c("total")}`, tooltip: "Runs finished" },
    { label: "running", value: String(c("running")), tooltip: "Runs running now" },
    { label: "queued", value: String(c("queued")), tooltip: "Runs waiting in a host queue" },
    {
      label: "failed",
      value: String(c("failed") + c("lost")),
      tooltip: failed.length > 0 ? failed.map(failLine).join("\n") : "No failed runs",
    },
    {
      label: `cost, ${fmtGpuHours(total)} GPU-h`,
      value: input.totalUsd > 0 ? fmtUsd(input.totalUsd) : "$0",
      tooltip:
        hours.size > 0
          ? [...hours].map(([host, h]) => `${host} ${fmtGpuHours(h)} GPU-h`).join("\n")
          : "No GPU time yet",
    },
    {
      label: "ETA",
      value: eta === null ? DASH : fmtDuration(eta),
      tooltip: "Median finished run time × runs left ÷ runs running",
    },
  ];
}
```

- [ ] **Step 5: Run the tests and the type check**

Run: `cd ui && bun test test/pages/sweepStats.test.ts test/pages/sweepModel.test.ts`
Expected: `32 pass`, `0 fail` (sweepStats 14, sweepModel 18).

Run: `cd ui && bun run typecheck`
Expected: exits 0 with no errors.

- [ ] **Step 6: Commit**

```bash
git add ui/src/pages/components/SweepModel.ts ui/test/pages/sweepStats.test.ts
git commit -m "feat(ui): sweep CLI command, seeds, ETA, GPU-hours, progress, sort and stats"
```

---

### Task 16: Run glyphs, progress strip, sweep CSS, heat table (panel a, two params)

**Files:**
- Create: `ui/src/pages/components/SweepGlyphs.tsx`
- Create: `ui/src/pages/components/SweepStyles.tsx`
- Create: `ui/src/pages/components/SweepHeat.tsx`
- Test: `ui/test/pages/sweepGlyphs.test.tsx`
- Test: `ui/test/pages/sweepHeat.test.tsx`

**Interfaces:**
- Consumes: Tasks 14–15 (`RunGlyphState`, `SweepCellRun`, `SweepCellRow`, `HeatAxes`, `cellTip`, `heatLevel`, `heatPercent`, `meanOf`, `sameParams`, `progressLabel`, `progressSegments`); `format.ts` (`fmtInterval`, `fmtScore`, `isNum`, `shortId`); `links.tsx` (`AppLink`, `hrefs`).
- Produces:
  - `RUN_LIST_MAX = 6`; `RunGlyph({ state }: { state: RunGlyphState })` (svg `.rg` with `data-glyph`); `SweepRunLink({ runId, state, title? })`; `SweepRunList({ runs, stateOf })`; `SweepProgress({ counts })`
  - `SWEEP_CSS: string`; `SweepStyles()` (one `<style data-hx="sweep">`)
  - `interface SweepHeatProps { axes: HeatAxes; cells: readonly SweepCellRow[]; best: SweepCellRow | null; metric: string; higherIsBetter: boolean; maxSeeds: number; stateOf: (runId: string, fallback: RunStatus | null) => RunGlyphState; seedsOf: (cell: SweepCellRow) => number[] }`; `SweepHeat(props)`; cells carry `data-testid="cell-<row>|<col>"` and `data-heat="<percent>"`.

- [ ] **Step 1: Write the failing tests**

Create `ui/test/pages/sweepGlyphs.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import { RUN_LIST_MAX, RunGlyph, SweepProgress, SweepRunList } from "../../src/pages/components/SweepGlyphs";
import type { RunGlyphState, SweepCellRun } from "../../src/pages/components/SweepModel";
import { SWEEP_CSS, SweepStyles } from "../../src/pages/components/SweepStyles";
import { makeSummary } from "./sweepFixtures";

afterEach(cleanup);

describe("sweep glyphs", () => {
  test("one glyph per run state", () => {
    const states: RunGlyphState[] = ["finished", "running", "queued", "stale", "failed", "lost", "killed"];
    const { container } = render(
      <>
        {states.map((s) => (
          <RunGlyph key={s} state={s} />
        ))}
      </>,
    );
    const svgs = [...container.querySelectorAll("svg.rg")];
    expect(svgs.map((s) => s.getAttribute("data-glyph"))).toEqual(states);
    expect(svgs.every((s) => s.getAttribute("aria-hidden") === "true")).toBe(true);
    expect(container.querySelectorAll("path.x")).toHaveLength(3);
    expect(container.querySelector('[data-glyph="stale"] path.half')).not.toBeNull();
  });

  test("a cell's run list shows six runs and counts the rest", () => {
    const runs: SweepCellRun[] = Array.from({ length: 8 }, (_, i) => ({
      run_id: `20261003-x-r${i}`,
      status: "finished",
      seed: i + 1,
    }));
    render(<SweepRunList runs={runs} stateOf={(_id, fallback) => fallback ?? "queued"} />);
    const links = screen.getAllByRole("link");
    expect(RUN_LIST_MAX).toBe(6);
    expect(links.map((a) => a.textContent)).toEqual(["r0", "r1", "r2", "r3", "r4", "r5"]);
    expect(links[0]?.getAttribute("href")).toBe("/r/20261003-x-r0");
    expect(links[0]?.getAttribute("title")).toBe("r0, seed 1, finished");
    expect(screen.getByText("+2").getAttribute("title")).toBe("2 more runs");
  });

  test("the progress strip has one segment per run", () => {
    render(<SweepProgress counts={makeSummary().counts} />);
    const strip = screen.getByRole("img", { name: "5 finished, 1 running, 1 queued, 1 failed" });
    expect([...strip.querySelectorAll("i")].map((i) => i.className)).toEqual([
      "f",
      "f",
      "f",
      "f",
      "f",
      "r",
      "q",
      "x",
    ]);
  });

  test("SweepStyles injects the sweep CSS", () => {
    const { container } = render(<SweepStyles />);
    expect(container.querySelector('style[data-hx="sweep"]')?.textContent).toBe(SWEEP_CSS);
    expect(SWEEP_CSS).toContain(".page .heat td.c.best");
    expect(SWEEP_CSS).toContain(".page .prog i.x");
  });
});
```

Create `ui/test/pages/sweepHeat.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, screen, within } from "@testing-library/react";
import type { RunStatus } from "../../src/api/models";
import { SweepHeat, type SweepHeatProps } from "../../src/pages/components/SweepHeat";
import {
  type HeatAxes,
  type SweepCellRow,
  cellTip,
  heatAxes,
  parseCell,
  parseCells,
  runState,
  seedValues,
} from "../../src/pages/components/SweepModel";
import { renderWithClient } from "./helpers";
import { CELL_A, CELL_B, CELL_D, RAW_CELLS, RUNS, STALE, makeSummary, makeSweepBoard, rid } from "./sweepFixtures";

afterEach(cleanup);

const AXES = heatAxes(makeSummary().spec) as HeatAxes;
const BOARD = makeSweepBoard();
const BY_ID = new Map(RUNS.map((r) => [r.run_id, r]));
const stateOf = (id: string, fallback: RunStatus | null) => runState(BY_ID.get(id), fallback, STALE);

function renderHeat(over: Partial<SweepHeatProps> = {}) {
  return renderWithClient(
    <SweepHeat
      axes={AXES}
      cells={parseCells(RAW_CELLS)}
      best={parseCell(CELL_D)}
      metric="top1"
      higherIsBetter
      maxSeeds={2}
      stateOf={stateOf}
      seedsOf={(c) => seedValues(c, BOARD)}
      {...over}
    />,
  );
}

const cell = (key: string): HTMLElement => screen.getByTestId(`cell-${key}`);
const texts = (els: Iterable<Element>): (string | null)[] => [...els].map((e) => e.textContent);

describe("SweepHeat", () => {
  test("rows and columns are the two params, with row and column means", () => {
    const { container } = renderHeat();
    const table = screen.getByRole("table", { name: "Mean top1 by lr and beam" });
    expect(texts(within(table).getAllByRole("columnheader"))).toEqual(["lr \\ beam", "5", "10", "mean"]);
    expect(texts(within(table).getAllByRole("rowheader"))).toEqual(["1e-4", "3e-4", "mean"]);
    expect(texts(container.querySelectorAll("td.m.rm"))).toEqual(["0.8950", "0.9080"]);
    expect(texts(container.querySelectorAll("td.m:not(.rm)"))).toEqual(["0.8970", "0.9060"]);
  });

  test("each cell shows its mean, n when seeds are missing, the best mark and its heat", () => {
    renderHeat();
    const best = cell("3e-4|10");
    expect(best.className).toBe("c best");
    expect(within(best).getByText("◆ best")).toBeTruthy();
    expect(best.querySelector(".v")?.textContent).toBe("0.9120");
    expect(best.getAttribute("data-heat")).toBe("34");
    expect(best.querySelector(".v")?.getAttribute("title")).toBe(
      cellTip(parseCell(CELL_D) as SweepCellRow, ["lr", "beam"], [0.911, 0.913]),
    );
    const low = cell("1e-4|5");
    expect(low.className).toBe("c");
    expect(low.querySelector(".v")?.textContent).toBe("0.8900n=1");
    expect(low.getAttribute("data-heat")).toBe("4");
  });

  test("each cell links its runs with a state glyph; a running run on a stale host is stale", () => {
    renderHeat();
    const glyph = (key: string, tail: string): string | null | undefined =>
      within(cell(key)).getByRole("link", { name: tail }).querySelector("svg")?.getAttribute("data-glyph");
    expect(within(cell("3e-4|10")).getByRole("link", { name: "d1" }).getAttribute("href")).toBe(`/r/${rid("d1")}`);
    expect([glyph("1e-4|5", "a1"), glyph("1e-4|5", "a2"), glyph("1e-4|10", "b2"), glyph("3e-4|5", "c2")]).toEqual([
      "finished",
      "queued",
      "stale",
      "failed",
    ]);
  });

  test("the key shows the value range, the best cell's seeds and the glyphs in use", () => {
    renderHeat();
    const key = screen.getByLabelText("Key");
    expect(within(key).getByText("0.890–0.912")).toBeTruthy();
    expect(within(key).getByText("best, 2 seeds")).toBeTruthy();
    expect(texts(key.querySelectorAll("span.st-k"))).toEqual(["finished", "running", "queued", "failed", "stale"]);
  });

  test("a missing combination is an empty cell; long run lists are cut", () => {
    const many = {
      ...CELL_A,
      run_ids: [],
      runs: Array.from({ length: 8 }, (_, i) => ({ run_id: rid(`m${i}`), status: "queued", seed: i + 1 })),
    };
    renderHeat({ cells: parseCells([many, CELL_B, CELL_D]) });
    const empty = cell("3e-4|5");
    expect(empty.className).toBe("c empty");
    expect(empty.querySelector(".v")?.textContent).toBe("·");
    expect(empty.getAttribute("data-heat")).toBeNull();
    expect(within(cell("1e-4|5")).getAllByRole("link")).toHaveLength(6);
    expect(within(cell("1e-4|5")).getByText("+2")).toBeTruthy();
  });

  test("for a lower-is-better metric the lowest mean is darkest", () => {
    renderHeat({ higherIsBetter: false, best: parseCell(CELL_A) });
    expect(cell("1e-4|5").getAttribute("data-heat")).toBe("34");
    expect(cell("3e-4|10").getAttribute("data-heat")).toBe("4");
    expect(cell("1e-4|5").className).toBe("c best");
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && bun test test/pages/sweepGlyphs.test.tsx test/pages/sweepHeat.test.tsx`
Expected: FAIL with `error: Cannot find module '../../src/pages/components/SweepGlyphs'` and `... '../../src/pages/components/SweepHeat'` (0 pass).

- [ ] **Step 3: Write the glyphs**

Create `ui/src/pages/components/SweepGlyphs.tsx`:

```tsx
/**
 * Run-state glyphs from the phase 2 mockup (filled dot = finished, ringed dot = running,
 * ring = queued, half-filled ring = stale, red cross = failed or lost, grey cross =
 * killed), a cell's run list, and the sweep progress strip.
 */
import type { ReactElement } from "react";
import type { RunStatus } from "../../api/models";
import { shortId } from "./format";
import { AppLink, hrefs } from "./links";
import { type RunGlyphState, type SweepCellRun, progressLabel, progressSegments } from "./SweepModel";

/** Runs listed in one cell before the rest collapse into `+n`. */
export const RUN_LIST_MAX = 6;

const CROSS = "M1.4 1.4L8.6 8.6M8.6 1.4L1.4 8.6";

/** The glyph of one run state, as a small inline SVG (decorative: the text says the state). */
export function RunGlyph({ state }: { state: RunGlyphState }): ReactElement {
  const box = (size: number, body: ReactElement): ReactElement => (
    <svg
      className="rg"
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      aria-hidden="true"
      data-glyph={state}
    >
      {body}
    </svg>
  );
  switch (state) {
    case "finished":
      return box(10, <circle className="fin" cx={5} cy={5} r={4} />);
    case "running":
      return box(
        12,
        <>
          <circle className="ring" cx={6} cy={6} r={5.2} />
          <circle className="dot" cx={6} cy={6} r={3} />
        </>,
      );
    case "queued":
      return box(10, <circle className="hollow" cx={5} cy={5} r={4} />);
    case "stale":
      return box(
        10,
        <>
          <circle className="stale-ring" cx={5} cy={5} r={4} />
          <path className="half" d="M5 1a4 4 0 0 1 0 8z" />
        </>,
      );
    case "killed":
      return box(10, <path className="x killed" d={CROSS} />);
    case "failed":
    case "lost":
      return box(10, <path className="x" d={CROSS} />);
  }
}

export interface SweepRunLinkProps {
  runId: string;
  state: RunGlyphState;
  title?: string;
}

/** Glyph plus short id, linking to the run page. */
export function SweepRunLink({ runId, state, title }: SweepRunLinkProps): ReactElement {
  return (
    <AppLink href={hrefs.run(runId)} title={title}>
      <RunGlyph state={state} />
      {shortId(runId)}
    </AppLink>
  );
}

export interface SweepRunListProps {
  runs: readonly SweepCellRun[];
  /** Shown state of a run, given the summary's status as fallback. */
  stateOf: (runId: string, fallback: RunStatus | null) => RunGlyphState;
}

/** A cell's runs: up to `RUN_LIST_MAX` links, then `+n`. */
export function SweepRunList({ runs, stateOf }: SweepRunListProps): ReactElement {
  const shown = runs.slice(0, RUN_LIST_MAX);
  const more = runs.length - shown.length;
  return (
    <span className="rl">
      {shown.map((r) => {
        const state = stateOf(r.run_id, r.status);
        const seed = r.seed !== null ? `, seed ${r.seed}` : "";
        return (
          <SweepRunLink
            key={r.run_id}
            runId={r.run_id}
            state={state}
            title={`${shortId(r.run_id)}${seed}, ${state}`}
          />
        );
      })}
      {more > 0 ? (
        <span className="more" title={`${more} more runs`}>
          {`+${more}`}
        </span>
      ) : null}
    </span>
  );
}

/** One segment per run of the sweep; the label reads the counts. */
export function SweepProgress({ counts }: { counts: Readonly<Record<string, number>> }): ReactElement {
  return (
    <div className="prog" role="img" aria-label={progressLabel(counts)}>
      {progressSegments(counts).map((kind, i) => (
        <i key={i} className={kind} />
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Write the sweep CSS**

Create `ui/src/pages/components/SweepStyles.tsx`:

```tsx
/** Sweep page CSS (mockup `docs/mockups/phase2/index.html`, block "phase 2: sweep"). Every selector starts with `.page`. */
import { type ReactElement, createElement } from "react";

export const SWEEP_CSS = `
.page .sweep-stats { margin-top: 36px; }
.page .prog { display: flex; gap: 2px; margin-top: 18px; }
.page .prog i { flex: 1; min-width: 1px; height: 10px; border-radius: 1.5px; display: block; }
.page .prog i.f { background: var(--ink-2); }
.page .prog i.r { background: var(--ink-2); opacity: .45; }
.page .prog i.q { box-shadow: inset 0 0 0 1px var(--ink-3); }
.page .prog i.x { background: var(--fail); }
.page .prog i.k { background: var(--ink-3); opacity: .3; }
.page .prog i.n { box-shadow: inset 0 0 0 1px var(--rule-2); }
.page .sw-grid { display: grid; grid-template-columns: minmax(0, 1fr) 380px; gap: 72px; margin-top: 64px; align-items: start; }
.page .sw-grid .fig { margin-top: 0; min-width: 0; }
.page .sw-actions { display: flex; flex-direction: column; align-items: flex-end; gap: 10px; }
.page .add-seeds { display: flex; gap: 10px; align-items: center; font-size: 13.5px; color: var(--ink-2); }
.page .add-seeds label { display: inline-flex; gap: 8px; align-items: center; }
.page .add-seeds input { width: 64px; height: 30px; padding: 0 8px; border: 1px solid var(--rule); border-radius: 6px; background: transparent; color: var(--ink); font: inherit; font-variant-numeric: tabular-nums; }
.page .heat { border-collapse: separate; border-spacing: 4px; margin: -4px; font-variant-numeric: tabular-nums; }
.page .heat th { font: 500 12.5px/1.3 var(--sans); color: var(--ink-3); text-align: center; padding: 0 0 6px; }
.page .heat th.rh { text-align: right; padding: 0 12px 0 0; white-space: nowrap; width: 72px; }
.page .heat th.cor { text-align: right; padding: 0 12px 6px 0; white-space: nowrap; }
.page .heat td.c { background: color-mix(in srgb, var(--ink) var(--heat, 0%), transparent); box-shadow: inset 0 0 0 1px var(--rule-2); width: 168px; height: 112px; vertical-align: top; padding: 12px 14px 10px; border-radius: 5px; position: relative; }
.page .heat td.c.empty { background: transparent; box-shadow: inset 0 0 0 1px var(--rule); }
.page .heat td.c.best { box-shadow: inset 0 0 0 2px var(--best), inset 0 0 0 4px var(--paper); }
.page .heat td.c .v { font: 400 26px/1 var(--sans); letter-spacing: -.015em; display: block; cursor: help; }
.page .heat td.c .v small { font-size: 12.5px; color: var(--ink-3); letter-spacing: 0; margin-left: 6px; }
.page .heat td.c .bm { position: absolute; top: 12px; right: 12px; font-size: 12.5px; font-weight: 600; color: var(--best); }
.page .heat td.m { font-size: 13.5px; color: var(--ink-2); text-align: center; vertical-align: middle; cursor: help; }
.page .heat td.m.rm { text-align: left; padding-left: 10px; }
.page .heat .mh { font-size: 12px; color: var(--ink-3); }
.page .rl { display: flex; flex-wrap: wrap; gap: 4px 10px; margin-top: 14px; font-size: 12.5px; }
.page .rl a { display: inline-flex; align-items: center; gap: 4px; text-decoration-color: color-mix(in srgb, currentColor 35%, transparent); }
.page .rl .more { color: var(--ink-3); cursor: help; }
.page .ramp { display: inline-flex; gap: 2px; vertical-align: middle; }
.page .ramp i { width: 18px; height: 10px; display: block; border-radius: 1px; background: color-mix(in srgb, var(--ink) var(--heat, 0%), transparent); }
.page .best-k b { color: var(--best); font-weight: 600; }
.page .rg { display: inline-block; vertical-align: middle; overflow: visible; flex: none; }
.page .rg .fin { fill: var(--ink-2); }
.page .rg .ring { fill: none; stroke: var(--ink-3); stroke-width: 1; }
.page .rg .dot { fill: var(--ink); }
.page .rg .hollow { fill: none; stroke: var(--ink-2); stroke-width: 1.4; }
.page .rg .stale-ring { fill: none; stroke: var(--ink); stroke-width: 1.4; }
.page .rg .half { fill: var(--ink); }
.page .rg .x { fill: none; stroke: var(--fail); stroke-width: 1.8; stroke-linecap: round; }
.page .rg .x.killed { stroke: var(--ink-3); }
.page .sw-table, .page .sw-runs { width: 100%; border-collapse: collapse; font-size: 14px; font-variant-numeric: tabular-nums; }
.page .sw-runs { max-width: 860px; }
.page .sw-table th, .page .sw-runs th { text-align: left; font-weight: 500; color: var(--ink-3); font-size: 12.5px; padding: 0 14px 8px 0; border-bottom: 1px solid var(--rule); white-space: nowrap; }
.page .sw-table td, .page .sw-runs td { padding: 8px 14px 8px 0; border-bottom: 1px solid var(--rule-2); vertical-align: middle; white-space: nowrap; }
.page .sw-table th:first-child, .page .sw-table td:first-child, .page .sw-runs th:first-child, .page .sw-runs td:first-child { padding-left: 8px; }
.page .sw-table .r, .page .sw-runs .r { text-align: right; }
.page .sw-table th button { all: unset; cursor: pointer; }
.page .sw-table th button:focus-visible { outline: 2px solid var(--agent); outline-offset: 2px; border-radius: 3px; }
.page .sw-table th[aria-sort] button { color: var(--ink); }
.page .sw-table tr.best td { background: color-mix(in srgb, var(--best-wash) 60%, transparent); }
.page .sw-table .bm { color: var(--best); }
.page .sw-table .rl { margin-top: 0; }
.page .sw-runs td a { display: inline-flex; align-items: center; gap: 6px; }
.page .more-runs { margin-top: 12px; font-size: 13.5px; }
.page .forest { width: 100%; }
@media (max-width: 1100px) { .page .sw-grid { grid-template-columns: 1fr; gap: 48px; } }
`;

/** Inject the sweep CSS (one `<style>` per mounted Sweep page). */
export function SweepStyles(): ReactElement {
  return createElement("style", { "data-hx": "sweep" }, SWEEP_CSS);
}
```

- [ ] **Step 5: Write the heat table**

Create `ui/src/pages/components/SweepHeat.tsx`:

```tsx
/**
 * Panel a for a two-param sweep (spec 8A.6): mean primary metric per row × column param.
 * Darker = better (in the metric's direction); the best cell is ringed and marked. The
 * exact numbers (seeds, 95% interval, seed σ) live in each value's tooltip.
 */
import type { CSSProperties, ReactElement } from "react";
import type { RunStatus } from "../../api/models";
import { fmtInterval, fmtScore, isNum } from "./format";
import { RunGlyph, SweepRunList } from "./SweepGlyphs";
import {
  type HeatAxes,
  type RunGlyphState,
  type SweepCellRow,
  cellTip,
  heatLevel,
  heatPercent,
  meanOf,
  sameParams,
} from "./SweepModel";

export interface SweepHeatProps {
  axes: HeatAxes;
  cells: readonly SweepCellRow[];
  best: SweepCellRow | null;
  /** Short metric name, e.g. `top1`. */
  metric: string;
  higherIsBetter: boolean;
  /** Seeds per cell in the sweep; cells with fewer scored seeds show `n=k`. */
  maxSeeds: number;
  stateOf: (runId: string, fallback: RunStatus | null) => RunGlyphState;
  seedsOf: (cell: SweepCellRow) => number[];
}

const KEY_STATES: readonly RunGlyphState[] = ["finished", "running", "queued", "failed"];
const RAMP: readonly number[] = [0, 0.25, 0.5, 0.75, 1];

const heatStyle = (pct: number): CSSProperties => ({ "--heat": `${pct}%` }) as CSSProperties;

interface HeatCellProps {
  id: string;
  cell: SweepCellRow | undefined;
  isBest: boolean;
  level: number;
  maxSeeds: number;
  names: readonly string[];
  seeds: number[];
  stateOf: SweepHeatProps["stateOf"];
}

function HeatCell({ id, cell, isBest, level, maxSeeds, names, seeds, stateOf }: HeatCellProps): ReactElement {
  if (cell === undefined) {
    return (
      <td className="c empty" data-testid={`cell-${id}`}>
        <span className="v">·</span>
      </td>
    );
  }
  const scored = cell.mean !== null;
  const pct = heatPercent(level);
  return (
    <td
      className={`c${scored ? "" : " empty"}${isBest ? " best" : ""}`}
      style={scored ? heatStyle(pct) : undefined}
      data-heat={scored ? pct : undefined}
      data-testid={`cell-${id}`}
    >
      {isBest ? <span className="bm">◆ best</span> : null}
      <span className="v" title={cellTip(cell, names, seeds)}>
        {scored ? fmtScore(cell.mean) : "·"}
        {scored && cell.n < maxSeeds ? <small>{`n=${cell.n}`}</small> : null}
      </span>
      <SweepRunList runs={cell.runs} stateOf={stateOf} />
    </td>
  );
}

export function SweepHeat({
  axes,
  cells,
  best,
  metric,
  higherIsBetter,
  maxSeeds,
  stateOf,
  seedsOf,
}: SweepHeatProps): ReactElement {
  const names = [axes.row, axes.col];
  const at = (r: string, c: string): SweepCellRow | undefined =>
    cells.find((x) => x.params[axes.row] === r && x.params[axes.col] === c);
  const means = cells.map((x) => x.mean).filter(isNum);
  const lo = means.length > 0 ? Math.min(...means) : null;
  const hi = means.length > 0 ? Math.max(...means) : null;
  const level = (cell: SweepCellRow | undefined): number => {
    const mean = cell?.mean ?? null;
    return mean !== null && lo !== null && hi !== null ? heatLevel(mean, lo, hi, higherIsBetter) : 0;
  };
  const anyStale = cells.some((x) => x.runs.some((r) => stateOf(r.run_id, r.status) === "stale"));
  return (
    <>
      <table className="heat" aria-label={`Mean ${metric} by ${axes.row} and ${axes.col}`}>
        <thead>
          <tr>
            <th className="cor" scope="col">{`${axes.row} \\ ${axes.col}`}</th>
            {axes.cols.map((c) => (
              <th key={c} scope="col">
                {c}
              </th>
            ))}
            <th className="mh" scope="col" title={`Mean over ${axes.col}`}>
              mean
            </th>
          </tr>
        </thead>
        <tbody>
          {axes.rows.map((r) => (
            <tr key={r}>
              <th className="rh" scope="row">
                {r}
              </th>
              {axes.cols.map((c) => {
                const cell = at(r, c);
                return (
                  <HeatCell
                    key={c}
                    id={`${r}|${c}`}
                    cell={cell}
                    isBest={cell !== undefined && best !== null && sameParams(cell.params, best.params)}
                    level={level(cell)}
                    maxSeeds={maxSeeds}
                    names={names}
                    seeds={cell ? seedsOf(cell) : []}
                    stateOf={stateOf}
                  />
                );
              })}
              <td className="m rm" title={`Mean over ${axes.col} at ${axes.row} ${r}`}>
                {fmtScore(meanOf(axes.cols.map((c) => at(r, c)?.mean ?? null)))}
              </td>
            </tr>
          ))}
          <tr>
            <th className="rh mh" scope="row" title={`Mean over ${axes.row}`}>
              mean
            </th>
            {axes.cols.map((c) => (
              <td key={c} className="m" title={`Mean over ${axes.row} at ${axes.col} ${c}`}>
                {fmtScore(meanOf(axes.rows.map((r) => at(r, c)?.mean ?? null)))}
              </td>
            ))}
            <td />
          </tr>
        </tbody>
      </table>
      <div className="key" aria-label="Key">
        {lo !== null && hi !== null ? (
          <span title="Darker is better">
            <span className="ramp">
              {RAMP.map((t) => (
                <i key={t} style={heatStyle(heatPercent(t))} />
              ))}
            </span>
            {fmtInterval(lo, hi)}
          </span>
        ) : null}
        {best !== null ? (
          <span className="best-k">
            <b aria-hidden="true">◆</b>
            <span>{`best, ${best.n} seed${best.n === 1 ? "" : "s"}`}</span>
          </span>
        ) : null}
        {KEY_STATES.map((s) => (
          <span key={s} className="st-k">
            <RunGlyph state={s} />
            {s}
          </span>
        ))}
        {anyStale ? (
          <span className="st-k" title="Host not reachable; the run may still be going">
            <RunGlyph state="stale" />
            stale
          </span>
        ) : null}
      </div>
    </>
  );
}
```

- [ ] **Step 6: Run the tests and the type check**

Run: `cd ui && bun test test/pages/sweepGlyphs.test.tsx test/pages/sweepHeat.test.tsx`
Expected: `10 pass`, `0 fail`.

Run: `cd ui && bun run typecheck`
Expected: exits 0 with no errors.

- [ ] **Step 7: Commit**

```bash
git add ui/src/pages/components/SweepGlyphs.tsx ui/src/pages/components/SweepStyles.tsx ui/src/pages/components/SweepHeat.tsx ui/test/pages/sweepGlyphs.test.tsx ui/test/pages/sweepHeat.test.tsx
git commit -m "feat(ui): sweep heat table, run glyphs and progress strip"
```

---

### Task 17: Sortable params table (panel a, one or more than two params)

**Files:**
- Create: `ui/src/pages/components/SweepTable.tsx`
- Test: `ui/test/pages/sweepTable.test.tsx`

**Interfaces:**
- Consumes: Tasks 14–15 (`SweepCellRow`, `RunGlyphState`, `SortState`, `defaultSort`, `nextSort`, `sortCells`, `sameParams`), Task 16 (`SweepRunList`), `format.ts` (`DASH`, `fmtInterval`, `fmtScore`).
- Produces: `interface SweepTableProps { names: readonly string[]; cells: readonly SweepCellRow[]; best: SweepCellRow | null; metric: string; higherIsBetter: boolean; maxSeeds: number; stateOf: (runId: string, fallback: RunStatus | null) => RunGlyphState }`; `SweepTable(props)` — table `aria-label="Mean <metric> by <names joined ', '>"`, one sort button per param, `n` and the metric; `aria-sort` on the active header. Until the user clicks a header the order follows `defaultSort(higherIsBetter)` on every render, so a metric direction that arrives with the leaderboard after the first render (the sweep page starts with `higherIsBetter = true`) still sorts best first.

- [ ] **Step 1: Write the failing tests**

Create `ui/test/pages/sweepTable.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { parseCell, parseCells } from "../../src/pages/components/SweepModel";
import { SweepTable, type SweepTableProps } from "../../src/pages/components/SweepTable";
import { renderWithClient } from "./helpers";

afterEach(cleanup);

function raw(id: string, lr: string, beam: string, warmup: string, n: number, mean: number | null): unknown {
  return {
    params: { lr, beam, warmup },
    group_id: n > 0 ? `g-${id}` : null,
    n,
    mean,
    lo: mean === null ? null : mean - 0.02,
    hi: mean === null ? null : mean + 0.02,
    std: null,
    run_ids: [`20261003-${id}`],
    runs: [{ run_id: `20261003-${id}`, status: mean === null ? "queued" : "finished", seed: 1 }],
  };
}

const CELLS = [
  raw("t1", "1e-4", "5", "100", 2, 0.8),
  raw("t2", "3e-4", "5", "100", 2, 0.85),
  raw("t3", "1e-3", "10", "0", 0, null),
  raw("t4", "3e-5", "10", "0", 1, 0.82),
];

function renderTable(over: Partial<SweepTableProps> = {}) {
  return renderWithClient(
    <SweepTable
      names={["lr", "beam", "warmup"]}
      cells={parseCells(CELLS)}
      best={parseCell(CELLS[1])}
      metric="top1"
      higherIsBetter
      maxSeeds={2}
      stateOf={(_id, fallback) => fallback ?? "queued"}
      {...over}
    />,
  );
}

const firstColumn = (): (string | null)[] =>
  screen
    .getAllByRole("row")
    .slice(1)
    .map((r) => r.querySelector("td")?.textContent ?? null);
const header = (name: RegExp): HTMLElement => screen.getByRole("button", { name }).closest("th") as HTMLElement;

describe("SweepTable", () => {
  test("sorts by mean, best first, and marks the best row", () => {
    renderTable();
    expect(screen.getByRole("table", { name: "Mean top1 by lr, beam, warmup" })).toBeTruthy();
    expect(firstColumn()).toEqual(["3e-4", "3e-5", "1e-4", "1e-3"]);
    expect(header(/^top1/).getAttribute("aria-sort")).toBe("descending");
    const bestRow = screen.getAllByRole("row")[1] as HTMLElement;
    expect(bestRow.className).toBe("best");
    expect(bestRow.textContent).toContain("◆");
  });

  test("a param header sorts numerically, a second click reverses", () => {
    renderTable();
    fireEvent.click(screen.getByRole("button", { name: /^lr/ }));
    expect(firstColumn()).toEqual(["3e-5", "1e-4", "3e-4", "1e-3"]);
    expect(header(/^lr/).getAttribute("aria-sort")).toBe("ascending");
    expect(header(/^top1/).getAttribute("aria-sort")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /^lr/ }));
    expect(firstColumn()).toEqual(["1e-3", "3e-4", "1e-4", "3e-5"]);
    expect(header(/^lr/).getAttribute("aria-sort")).toBe("descending");
  });

  test("the n header sorts by scored seeds", () => {
    renderTable();
    fireEvent.click(screen.getByRole("button", { name: /^n\b/ }));
    expect(firstColumn()).toEqual(["1e-3", "3e-5", "1e-4", "3e-4"]);
  });

  test("a lower-is-better metric sorts ascending by default", () => {
    renderTable({ higherIsBetter: false, best: parseCell(CELLS[0]) });
    expect(firstColumn()).toEqual(["1e-4", "3e-5", "3e-4", "1e-3"]);
    expect(header(/^top1/).getAttribute("aria-sort")).toBe("ascending");
  });

  test("lower-is-better arriving after the first render still sorts best first; a click then sticks", () => {
    // the sweep page renders before the leaderboard says the metric's direction
    const props: SweepTableProps = {
      names: ["lr", "beam", "warmup"],
      cells: parseCells(CELLS),
      best: parseCell(CELLS[1]),
      metric: "top1",
      higherIsBetter: true,
      maxSeeds: 2,
      stateOf: (_id, fallback) => fallback ?? "queued",
    };
    const { rerender } = render(<SweepTable {...props} />);
    expect(firstColumn()).toEqual(["3e-4", "3e-5", "1e-4", "1e-3"]);
    rerender(<SweepTable {...props} higherIsBetter={false} best={parseCell(CELLS[0])} />);
    expect(firstColumn()).toEqual(["1e-4", "3e-5", "3e-4", "1e-3"]);
    expect(header(/^top1/).getAttribute("aria-sort")).toBe("ascending");
    // once the user picks a column, a later prop change keeps that choice
    fireEvent.click(screen.getByRole("button", { name: /^lr/ }));
    rerender(<SweepTable {...props} higherIsBetter />);
    expect(firstColumn()).toEqual(["3e-5", "1e-4", "3e-4", "1e-3"]);
  });

  test("an unscored cell shows dashes and its queued run", () => {
    renderTable();
    const row = screen.getAllByRole("row")[4] as HTMLElement;
    expect([...row.querySelectorAll("td")].map((td) => td.textContent)).toEqual([
      "1e-3",
      "10",
      "0",
      "0",
      "—",
      "—",
      "t3",
    ]);
    expect(row.querySelector("svg")?.getAttribute("data-glyph")).toBe("queued");
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && bun test test/pages/sweepTable.test.tsx`
Expected: FAIL with `error: Cannot find module '../../src/pages/components/SweepTable'` (0 pass).

- [ ] **Step 3: Write the table**

Create `ui/src/pages/components/SweepTable.tsx`:

```tsx
/**
 * Panel a when the heat table does not fit (one param, more than two, or sampled ranges):
 * one row per param combination, sortable by any param, `n` or the metric. Default order
 * is best first in the metric's direction; unscored cells stay last.
 */
import { type ReactElement, useState } from "react";
import type { RunStatus } from "../../api/models";
import { DASH, fmtInterval, fmtScore } from "./format";
import { SweepRunList } from "./SweepGlyphs";
import {
  type RunGlyphState,
  type SortState,
  type SweepCellRow,
  defaultSort,
  nextSort,
  sameParams,
  sortCells,
} from "./SweepModel";

export interface SweepTableProps {
  names: readonly string[];
  cells: readonly SweepCellRow[];
  best: SweepCellRow | null;
  metric: string;
  higherIsBetter: boolean;
  maxSeeds: number;
  stateOf: (runId: string, fallback: RunStatus | null) => RunGlyphState;
}

export function SweepTable({
  names,
  cells,
  best,
  metric,
  higherIsBetter,
  maxSeeds,
  stateOf,
}: SweepTableProps): ReactElement {
  // null until the user clicks a header: the default then follows `higherIsBetter`, which
  // the sweep page only learns when the task leaderboard arrives after the first render
  const [chosen, setChosen] = useState<SortState | null>(null);
  const sort = chosen ?? defaultSort(higherIsBetter);
  const rows = sortCells(cells, sort);
  const header = (key: string, label: string, numeric: boolean): ReactElement => {
    const active = sort.key === key;
    return (
      <th
        key={key}
        className={numeric ? "r" : undefined}
        aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : undefined}
      >
        <button
          type="button"
          title={`Sort by ${label}`}
          onClick={() => setChosen(nextSort(sort, key, higherIsBetter))}
        >
          {label}
          {active ? (sort.dir === "asc" ? " ↑" : " ↓") : ""}
        </button>
      </th>
    );
  };
  return (
    <table className="sw-table" aria-label={`Mean ${metric} by ${names.join(", ")}`}>
      <thead>
        <tr>
          {names.map((n) => header(n, n, false))}
          {header("n", "n", true)}
          {header("mean", metric, true)}
          <th className="r">95% CI</th>
          <th>runs</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((cell) => {
          const isBest = best !== null && sameParams(cell.params, best.params);
          return (
            <tr key={names.map((n) => cell.params[n] ?? "").join("\u0000")} className={isBest ? "best" : undefined}>
              {names.map((n) => (
                <td key={n}>{cell.params[n] ?? DASH}</td>
              ))}
              <td className="r" title={cell.n < maxSeeds ? `${cell.n} of ${maxSeeds} seeds scored` : undefined}>
                {cell.n}
              </td>
              <td className="r">
                {isBest ? (
                  <span className="bm" title="best">
                    ◆{" "}
                  </span>
                ) : null}
                {fmtScore(cell.mean)}
              </td>
              <td className="r">{cell.lo !== null && cell.hi !== null ? fmtInterval(cell.lo, cell.hi) : DASH}</td>
              <td>
                <SweepRunList runs={cell.runs} stateOf={stateOf} />
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 4: Run the tests and the type check**

Run: `cd ui && bun test test/pages/sweepTable.test.tsx`
Expected: `6 pass`, `0 fail`.

Run: `cd ui && bun run typecheck`
Expected: exits 0 with no errors.

- [ ] **Step 5: Commit**

```bash
git add ui/src/pages/components/SweepTable.tsx ui/test/pages/sweepTable.test.tsx
git commit -m "feat(ui): sortable sweep params table for one or more than two params"
```

---

### Task 18: Seeds forest (panel b)

**Files:**
- Create: `ui/src/pages/components/SweepForest.tsx`
- Test: `ui/test/pages/sweepForest.test.tsx`

**Interfaces:**
- Consumes: Task 14 (`SweepCellRow`, `cellLabel`, `cellTip`, `rankCells`, `sameParams`); `charts/Axis` (`AxisBottom`, `GridX`), `charts/Glyphs` (`BestBand`, `MeanMark`, `SeedDots`, `Whisker`), `charts/Scale` (`linear`, `niceDomain`, `tickFormat`, `useElementWidth`), `charts/Tooltip` (`useTooltip`); `format.ts` (`isNum`).
- Produces: `interface SweepForestProps { cells: readonly SweepCellRow[]; best: SweepCellRow | null; names: readonly string[]; metric: string; axisLabel: string; higherIsBetter: boolean; maxSeeds: number; seedsOf: (cell: SweepCellRow) => number[] }`; `SweepForest(props)` — one `g.frow[data-label]` per scored cell, best first; the best cell's interval as a band behind all rows.

- [ ] **Step 1: Write the failing tests**

Create `ui/test/pages/sweepForest.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { SweepForest, type SweepForestProps } from "../../src/pages/components/SweepForest";
import { type SweepCellRow, cellTip, parseCell, parseCells, seedValues } from "../../src/pages/components/SweepModel";
import { renderWithClient } from "./helpers";
import { CELL_D, RAW_CELLS, makeSweepBoard } from "./sweepFixtures";

afterEach(cleanup);

const BOARD = makeSweepBoard();
const NAMES = ["lr", "beam"];

function renderForest(over: Partial<SweepForestProps> = {}) {
  return renderWithClient(
    <SweepForest
      cells={parseCells(RAW_CELLS)}
      best={parseCell(CELL_D)}
      names={NAMES}
      metric="top1"
      axisLabel="top1 v1"
      higherIsBetter
      maxSeeds={2}
      seedsOf={(c) => seedValues(c, BOARD)}
      {...over}
    />,
  );
}

describe("SweepForest", () => {
  test("one row per scored cell, best first, best label bold", () => {
    const { container } = renderForest();
    const rows = [...container.querySelectorAll("g.frow")];
    expect(rows.map((g) => g.getAttribute("data-label"))).toEqual(["3e-4, 10", "3e-4, 5", "1e-4, 10", "1e-4, 5"]);
    expect(rows[0]?.querySelector("text")?.getAttribute("class")).toBe("lbl-b");
    expect(rows[1]?.querySelector("text")?.getAttribute("class")).toBe("lbl");
    expect(screen.getByText("lr, beam")).toBeTruthy();
    expect(screen.getByText("top1 v1")).toBeTruthy();
  });

  test("seed dots, means, whiskers, the best band and n= for short cells", () => {
    const { container } = renderForest();
    expect(container.querySelectorAll("circle.seed")).toHaveLength(5);
    expect(container.querySelectorAll("rect.mean")).toHaveLength(4);
    expect(container.querySelectorAll("rect.mean.best")).toHaveLength(1);
    expect(container.querySelectorAll("path.whisk")).toHaveLength(4);
    expect(container.querySelectorAll("g.best-band")).toHaveLength(1);
    expect(screen.getAllByText("n=1")).toHaveLength(3);
  });

  test("hovering a row shows the cell's numbers", () => {
    const { container } = renderForest();
    fireEvent.mouseEnter(container.querySelector("g.frow rect.hit") as Element);
    expect(screen.getByRole("tooltip").textContent).toBe(
      cellTip(parseCell(CELL_D) as SweepCellRow, NAMES, [0.911, 0.913]),
    );
  });

  test("no scored cell: a short note instead of a chart", () => {
    const { container } = renderForest({
      cells: parseCells([{ params: { lr: "1e-4", beam: "5" }, run_ids: ["x"] }]),
      best: null,
    });
    expect(screen.getByText("No scored runs yet")).toBeTruthy();
    expect(container.querySelector("svg")).toBeNull();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && bun test test/pages/sweepForest.test.tsx`
Expected: FAIL with `error: Cannot find module '../../src/pages/components/SweepForest'` (0 pass).

- [ ] **Step 3: Write the forest**

Create `ui/src/pages/components/SweepForest.tsx`:

```tsx
/**
 * Panel b (mockup `drawSweepForest`): one row per scored cell, best first. Each row has
 * its seed dots, mean square, and 95% interval whisker; the best cell's interval is a
 * band behind every row, so a row inside the band is within noise of the best.
 */
import type { ReactElement } from "react";
import { AxisBottom, GridX } from "../../charts/Axis";
import { BestBand, MeanMark, SeedDots, Whisker } from "../../charts/Glyphs";
import { linear, niceDomain, tickFormat, useElementWidth } from "../../charts/Scale";
import { useTooltip } from "../../charts/Tooltip";
import { isNum } from "./format";
import { type SweepCellRow, cellLabel, cellTip, rankCells, sameParams } from "./SweepModel";

export interface SweepForestProps {
  cells: readonly SweepCellRow[];
  best: SweepCellRow | null;
  names: readonly string[];
  metric: string;
  /** Caption under the axis, e.g. `top1 v1`. */
  axisLabel: string;
  higherIsBetter: boolean;
  maxSeeds: number;
  seedsOf: (cell: SweepCellRow) => number[];
}

/** Label column width, row height, and top margin in px (mockup values). */
const LW = 96;
const ROW = 34;
const TOP = 22;

export function SweepForest({
  cells,
  best,
  names,
  metric,
  axisLabel,
  higherIsBetter,
  maxSeeds,
  seedsOf,
}: SweepForestProps): ReactElement {
  const [ref, width] = useElementWidth<HTMLDivElement>(380);
  const tip = useTooltip();
  const rows = rankCells(cells, higherIsBetter);
  if (rows.length === 0) return <p className="panel-empty">No scored runs yet</p>;
  const values = rows.flatMap((c) => [c.mean, c.lo, c.hi, ...seedsOf(c)]).filter(isNum);
  const x = linear(niceDomain(values), LW, Math.max(LW + 40, width - 8), 4);
  const fmt = tickFormat(x.ticks);
  const yAx = TOP + rows.length * ROW + 4;
  const isBest = (c: SweepCellRow): boolean => best !== null && sameParams(c.params, best.params);
  return (
    <div ref={ref} className="forest">
      <svg
        className="hx-chart"
        width={width}
        height={yAx + 42}
        role="img"
        aria-label={`Cells sorted by mean ${metric}, with seed dots and 95% intervals`}
      >
        <text className="lbl-s" x={LW - 12} y={10} textAnchor="end">
          {names.join(", ")}
        </text>
        <GridX x={x.at} ticks={x.ticks} y0={TOP} y1={yAx} />
        {best !== null && best.lo !== null && best.hi !== null ? (
          <BestBand x1={x.at(best.lo)} x2={x.at(best.hi)} y0={TOP} y1={yAx} />
        ) : null}
        {rows.map((c, i) => {
          const y = TOP + i * ROW + ROW / 2;
          const b = isBest(c);
          const seeds = seedsOf(c);
          const label = cellLabel(c.params, names);
          return (
            <g key={label} className="frow" data-label={label}>
              <text className={b ? "lbl-b" : "lbl"} x={LW - 12} y={y + 4} textAnchor="end">
                {label}
              </text>
              {c.lo !== null && c.hi !== null ? <Whisker x1={x.at(c.lo)} x2={x.at(c.hi)} y={y} best={b} /> : null}
              <SeedDots x={x.at} values={seeds} y={y - 9} r={3} />
              <MeanMark cx={x.at(c.mean ?? 0)} cy={y} r={4.2} best={b} />
              {c.n < maxSeeds ? (
                <text className="lbl-s" x={x.at(c.hi ?? c.mean ?? 0) + 8} y={y + 4}>
                  {`n=${c.n}`}
                </text>
              ) : null}
              <rect
                className="hit"
                x={LW}
                y={y - ROW / 2}
                width={Math.max(0, width - LW)}
                height={ROW}
                tabIndex={0}
                {...tip.bind(cellTip(c, names, seeds))}
              />
            </g>
          );
        })}
        <AxisBottom x={x.at} ticks={x.ticks} y={yAx} x0={LW} x1={width} format={fmt} label={axisLabel} />
      </svg>
      {tip.node}
    </div>
  );
}
```

- [ ] **Step 4: Run the tests and the type check**

Run: `cd ui && bun test test/pages/sweepForest.test.tsx`
Expected: `4 pass`, `0 fail`.

Run: `cd ui && bun run typecheck`
Expected: exits 0 with no errors.

- [ ] **Step 5: Commit**

```bash
git add ui/src/pages/components/SweepForest.tsx ui/test/pages/sweepForest.test.tsx
git commit -m "feat(ui): sweep seeds forest with 95% intervals and best band"
```

---

### Task 19: Runs on hosts (panel c)

**Files:**
- Create: `ui/src/pages/components/SweepRuns.tsx`
- Test: `ui/test/pages/sweepRuns.test.tsx`

**Interfaces:**
- Consumes: Tasks 14–15 (`RunGlyphState`, `gpuHours`, `hostOf`, `runState`, `runUsd`, `stateText`), Task 16 (`SweepRunLink`), `format.ts` (`DASH`, `fmtUsd`).
- Produces: `interface SweepRunsProps { runs: readonly RunRecord[]; names: readonly string[]; stale: ReadonlyMap<string, string>; hosts: readonly HostRow[] | undefined; now: number }`; `SweepRuns(props)` (the host column is `hostOf(record, hosts)`: the hub's host name, matched by environment); `runsForHosts(runs, stale): { record: RunRecord; state: RunGlyphState }[]` (running and stale first, then queued by position, then failed/lost, killed, finished; ties keep input order).

- [ ] **Step 1: Write the failing tests**

Create `ui/test/pages/sweepRuns.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, fireEvent, screen } from "@testing-library/react";
import type { RunRecord } from "../../src/api/models";
import { SweepRuns } from "../../src/pages/components/SweepRuns";
import { renderWithClient } from "./helpers";
import { HOSTS, NOW, RUNS, STALE, rid, run } from "./sweepFixtures";

afterEach(cleanup);

const NAMES = ["lr", "beam"];
const cellsOf = (row: Element): (string | null)[] => [...row.querySelectorAll("td")].map((td) => td.textContent);
const bodyRows = (): HTMLElement[] => screen.getAllByRole("row").slice(1);
const firstCells = (): (string | null | undefined)[] => bodyRows().map((r) => r.querySelector("td")?.textContent);

describe("SweepRuns", () => {
  test("lists unfinished runs: running and stale first, then queued, then failed", () => {
    renderWithClient(<SweepRuns runs={RUNS} names={NAMES} stale={STALE} hosts={HOSTS} now={NOW} />);
    expect(screen.getAllByRole("columnheader").map((th) => th.textContent)).toEqual([
      "run",
      "lr",
      "beam",
      "seed",
      "state",
      "host",
      "GPU-h",
      "cost",
    ]);
    expect(bodyRows().map(cellsOf)).toEqual([
      ["b2", "1e-4", "10", "2", "stale 4m", "dgx", "1.0", "·"],
      ["a2", "1e-4", "5", "2", "queued, pos 2", "gpu1", "·", "·"],
      ["c2", "3e-4", "5", "2", "failed, exit 1", "gpu1", "0.2", "$0.42"],
    ]);
    expect(screen.getByRole("link", { name: "b2" }).querySelector("svg")?.getAttribute("data-glyph")).toBe("stale");
    expect(screen.getByRole("link", { name: "b2" }).getAttribute("href")).toBe(`/r/${rid("b2")}`);
  });

  test("the finished runs open from one row", () => {
    renderWithClient(<SweepRuns runs={RUNS} names={NAMES} stale={STALE} hosts={HOSTS} now={NOW} />);
    const more = screen.getByRole("button", { name: "+ 5 finished" });
    expect(more.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(more);
    expect(firstCells()).toEqual(["b2", "a2", "c2", "a1", "b1", "c1", "d1", "d2"]);
    expect(cellsOf(bodyRows()[6] as HTMLElement)).toEqual(["d1", "3e-4", "10", "1", "finished", "dgx", "2.0", "$2.40"]);
    expect(screen.getByRole("button", { name: "hide finished" }).getAttribute("aria-expanded")).toBe("true");
  });

  test("queued runs follow their queue position", () => {
    const a2 = run("a2");
    const first: RunRecord = { ...a2, run_id: rid("q1"), seed: 3, executor: { ...a2.executor, queue_position: 1 } };
    renderWithClient(<SweepRuns runs={[a2, first]} names={NAMES} stale={STALE} hosts={HOSTS} now={NOW} />);
    expect(firstCells()).toEqual(["q1", "a2"]);
    expect(screen.queryByRole("button", { name: /finished/ })).toBeNull();
  });

  test("a queued run on a host that is not connected is stale; hosts are named by environment", () => {
    // a2 waits in the dgx queue; dgx is stale, so it shows stale like b2 (and like its run page)
    const a2: RunRecord = { ...run("a2"), environment_id: "env-dgx" };
    renderWithClient(<SweepRuns runs={[a2]} names={NAMES} stale={STALE} hosts={HOSTS} now={NOW} />);
    expect(cellsOf(bodyRows()[0] as HTMLElement)).toEqual(["a2", "1e-4", "5", "2", "stale 4m", "dgx", "·", "·"]);
    cleanup();
    // without the hosts list the column shows the machine's own hostname (executor.host is never the hub's name)
    renderWithClient(<SweepRuns runs={[run("b2")]} names={NAMES} stale={new Map()} hosts={undefined} now={NOW} />);
    expect(cellsOf(bodyRows()[0] as HTMLElement)[5]).toBe("dgx-h100-07");
  });

  test("no runs yet", () => {
    renderWithClient(<SweepRuns runs={[]} names={NAMES} stale={STALE} hosts={HOSTS} now={NOW} />);
    expect(screen.getByText("No runs indexed yet")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && bun test test/pages/sweepRuns.test.tsx`
Expected: FAIL with `error: Cannot find module '../../src/pages/components/SweepRuns'` (0 pass).

- [ ] **Step 3: Write the runs table**

Create `ui/src/pages/components/SweepRuns.tsx`:

```tsx
/**
 * Panel c (mockup "Runs on hosts"): the sweep's unfinished runs with params, seed, state
 * (`stale 4m`, `queued, pos 2`, `failed, exit 1`), host, GPU-hours and cost. Finished
 * runs collapse into one `+ N finished` row.
 */
import { type ReactElement, useState } from "react";
import type { HostRow, RunRecord } from "../../api/models";
import { DASH, fmtUsd } from "./format";
import { SweepRunLink } from "./SweepGlyphs";
import { type RunGlyphState, gpuHours, hostOf, runState, runUsd, stateText } from "./SweepModel";

export interface SweepRunsProps {
  /** The sweep's runs, in launch order. */
  runs: readonly RunRecord[];
  /** Param columns, in grid order. */
  names: readonly string[];
  /** `staleHosts(hosts)`: environment id → since, for hosts that are not connected. */
  stale: ReadonlyMap<string, string>;
  /** `GET /api/v1/hosts`, to name each run's host; undefined while it loads or fails. */
  hosts: readonly HostRow[] | undefined;
  now: number;
}

const RANK: Record<RunGlyphState, number> = {
  running: 0,
  stale: 0,
  queued: 1,
  failed: 2,
  lost: 2,
  killed: 3,
  finished: 4,
};

/** Runs with their shown state: running and stale, queued by position, failed, killed, finished. */
export function runsForHosts(
  runs: readonly RunRecord[],
  stale: ReadonlyMap<string, string>,
): { record: RunRecord; state: RunGlyphState }[] {
  const pos = (r: RunRecord): number => r.executor.queue_position ?? Number.MAX_SAFE_INTEGER;
  return runs
    .map((record, i) => ({ record, state: runState(record, null, stale), i }))
    .sort((a, b) => RANK[a.state] - RANK[b.state] || pos(a.record) - pos(b.record) || a.i - b.i)
    .map(({ record, state }) => ({ record, state }));
}

export function SweepRuns({ runs, names, stale, hosts, now }: SweepRunsProps): ReactElement {
  const [showDone, setShowDone] = useState(false);
  if (runs.length === 0) return <p className="small">No runs indexed yet</p>;
  const rows = runsForHosts(runs, stale);
  const done = rows.filter((x) => x.state === "finished").length;
  const shown = showDone ? rows : rows.filter((x) => x.state !== "finished");
  return (
    <>
      <table className="sw-runs">
        <thead>
          <tr>
            <th>run</th>
            {names.map((n) => (
              <th key={n}>{n}</th>
            ))}
            <th className="r">seed</th>
            <th>state</th>
            <th>host</th>
            <th className="r" title="GPU-hours: wall time × GPUs">
              GPU-h
            </th>
            <th className="r">cost</th>
          </tr>
        </thead>
        <tbody>
          {shown.map(({ record, state }) => {
            const hours = gpuHours(record, now);
            const usd = runUsd(record);
            return (
              <tr key={record.run_id}>
                <td>
                  <SweepRunLink runId={record.run_id} state={state} title={record.run_id} />
                </td>
                {names.map((n) => (
                  <td key={n}>{record.params[n] ?? DASH}</td>
                ))}
                <td className="r">{record.seed ?? DASH}</td>
                <td>{stateText(record, state, stale, now)}</td>
                <td>{hostOf(record, hosts)}</td>
                <td className="r">{hours > 0 ? hours.toFixed(1) : "·"}</td>
                <td className="r">{usd !== null ? fmtUsd(usd) : "·"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {done > 0 ? (
        <button
          type="button"
          className="btn link more-runs"
          aria-expanded={showDone}
          onClick={() => setShowDone((v) => !v)}
        >
          {showDone ? "hide finished" : `+ ${done} finished`}
        </button>
      ) : null}
    </>
  );
}
```

- [ ] **Step 4: Run the tests and the type check**

Run: `cd ui && bun test test/pages/sweepRuns.test.tsx`
Expected: `5 pass`, `0 fail`.

Run: `cd ui && bun run typecheck`
Expected: exits 0 with no errors.

- [ ] **Step 5: Commit**

```bash
git add ui/src/pages/components/SweepRuns.tsx ui/test/pages/sweepRuns.test.tsx
git commit -m "feat(ui): sweep runs-on-hosts table with state, GPU-hours and cost"
```

---

### Task 20: Actions (Copy as CLI, Cancel queued, Add seeds)

**Files:**
- Create: `ui/src/pages/components/SweepActions.tsx`
- Test: `ui/test/pages/sweepActions.test.tsx`

**Interfaces:**
- Consumes: `api.cancelQueued(project, sweepId, opts)`, `api.extendSweep(project, sweepId, seeds, opts)` (Task 2), `REMOTE_RUN_INVALIDATES` (Task 3: the run families, sweeps and hosts), `SweepSpec`; phase 1b `useAction`, `ErrorBox`; Task 15 (`MAX_NEW_SEEDS`, `nextSeeds`, `parseSeedCount`, `sweepCli`).
- Produces: `interface SweepActionsProps { project: string; sweepId: string; spec: SweepSpec; queued: number; cellCount: number; runs: readonly RunRecord[] }`; `SweepActions(props)`.

Add seeds follows contract section 2: `extend` adds runs for every param combination × the new seeds. The form asks how many seeds per cell (default: the sweep's seed count), shows the seeds and the run count, and sends the next seeds after the largest one in use.

- [ ] **Step 1: Write the failing tests**

Create `ui/test/pages/sweepActions.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { SweepActions } from "../../src/pages/components/SweepActions";
import { sweepCli } from "../../src/pages/components/SweepModel";
import { HttpReply, mockApi, mockClipboard, renderWithClient, restoreFetch } from "./helpers";
import { PROJECT, RUNS, SWEEP_ID, makeSummary } from "./sweepFixtures";

afterEach(() => {
  cleanup();
  restoreFetch();
});

const SPEC = makeSummary().spec;
const BASE = `/api/v1/sweeps/${PROJECT}/${SWEEP_ID}`;

function renderActions(queued = 1) {
  return renderWithClient(
    <SweepActions project={PROJECT} sweepId={SWEEP_ID} spec={SPEC} queued={queued} cellCount={4} runs={RUNS} />,
  );
}

const seedInput = (): HTMLInputElement =>
  screen.getByRole("spinbutton", { name: "New seeds per cell" }) as HTMLInputElement;

describe("SweepActions", () => {
  test("Copy as CLI copies the hx sweep command", async () => {
    const written = mockClipboard();
    renderActions();
    fireEvent.click(screen.getByRole("button", { name: "Copy as CLI" }));
    await screen.findByRole("button", { name: "Copied" });
    expect(written).toEqual([sweepCli(SPEC, RUNS)]);
    expect(written[0]).toStartWith("hx sweep -t fwd --grid lr=1e-4,3e-4");
  });

  test("a blocked clipboard says so", async () => {
    mockClipboard(true);
    renderActions();
    fireEvent.click(screen.getByRole("button", { name: "Copy as CLI" }));
    expect(await screen.findByRole("button", { name: "Clipboard blocked" })).toBeTruthy();
  });

  test("Cancel queued is off with nothing queued", () => {
    mockApi({});
    renderActions(0);
    const cancel = screen.getByRole("button", { name: "Cancel queued" });
    expect(cancel.hasAttribute("disabled")).toBe(true);
    expect(cancel.getAttribute("title")).toBe("No queued runs");
  });

  test("Cancel queued posts once with a command id", async () => {
    const calls = mockApi({ [`POST ${BASE}/cancel_queued`]: makeSummary() });
    renderActions(3);
    const cancel = screen.getByRole("button", { name: "Cancel queued" });
    expect(cancel.getAttribute("title")).toBe("Cancel the 3 queued runs");
    fireEvent.click(cancel);
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]?.method).toBe("POST");
    expect(calls[0]?.url).toBe(`${BASE}/cancel_queued`);
    expect(typeof (calls[0]?.body as { command_id?: unknown }).command_id).toBe("string");
  });

  test("Add seeds adds the next seeds to every cell", async () => {
    const calls = mockApi({ [`POST ${BASE}/extend`]: makeSummary() });
    renderActions();
    fireEvent.click(screen.getByRole("button", { name: "Add seeds" }));
    expect(seedInput().value).toBe("2");
    expect(screen.getByText("3, 4 × 4 cells = 8 runs")).toBeTruthy();
    fireEvent.change(seedInput(), { target: { value: "1" } });
    expect(screen.getByText("3 × 4 cells = 4 runs")).toBeTruthy();
    fireEvent.change(seedInput(), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Add 8 runs" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]?.url).toBe(`${BASE}/extend`);
    expect(calls[0]?.body).toMatchObject({ seeds: [3, 4] });
    expect(typeof (calls[0]?.body as { command_id?: unknown }).command_id).toBe("string");
    await waitFor(() => expect(screen.queryByRole("form", { name: "Add seeds" })).toBeNull());
  });

  test("an invalid seed count disables Add", () => {
    mockApi({});
    renderActions();
    fireEvent.click(screen.getByRole("button", { name: "Add seeds" }));
    fireEvent.change(seedInput(), { target: { value: "0" } });
    expect(screen.getByRole("button", { name: "Add 0 runs" }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByText("1–20")).toBeTruthy();
  });

  test("a refused extend shows the server's reason", async () => {
    mockApi({
      [`POST ${BASE}/extend`]: new HttpReply(400, { error: "seeds already in sweep s-7f3a: 3", type: "SweepError" }),
    });
    renderActions();
    fireEvent.click(screen.getByRole("button", { name: "Add seeds" }));
    fireEvent.click(screen.getByRole("button", { name: "Add 8 runs" }));
    expect((await screen.findByRole("alert")).textContent).toBe("seeds already in sweep s-7f3a: 3");
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && bun test test/pages/sweepActions.test.tsx`
Expected: FAIL with `error: Cannot find module '../../src/pages/components/SweepActions'` (0 pass).

- [ ] **Step 3: Write the actions**

Create `ui/src/pages/components/SweepActions.tsx`:

```tsx
/**
 * Sweep actions (contract section 4): Copy as CLI (the same `hx sweep` command), Cancel
 * queued (`POST .../cancel_queued`), Add seeds (`POST .../extend`: every cell × the next
 * seeds). Each POST carries one `command_id` per click, so a retry is not a second action.
 */
import { type ReactElement, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { RunRecord, SweepSpec } from "../../api/models";
import { REMOTE_RUN_INVALIDATES } from "../../api/queries";
import { ErrorBox } from "./QueryState";
import { MAX_NEW_SEEDS, nextSeeds, parseSeedCount, sweepCli } from "./SweepModel";
import { useAction } from "./useAction";

export interface SweepActionsProps {
  project: string;
  sweepId: string;
  spec: SweepSpec;
  /** Queued runs of the sweep now (summary counts). */
  queued: number;
  /** Param combinations; Add seeds adds this many runs per new seed. */
  cellCount: number;
  /** The sweep's runs, for `--gpus`, `--queue` and `-H` in Copy as CLI. */
  runs: readonly RunRecord[];
}

type CopyState = "idle" | "copied" | "failed";

const COPY_TEXT: Record<CopyState, string> = { idle: "Copy as CLI", copied: "Copied", failed: "Clipboard blocked" };

export function SweepActions({ project, sweepId, spec, queued, cellCount, runs }: SweepActionsProps): ReactElement {
  const [copy, setCopy] = useState<CopyState>("idle");
  const [open, setOpen] = useState(false);
  const [count, setCount] = useState(String(Math.max(1, spec.seeds.length)));
  useEffect(() => {
    if (copy === "idle") return;
    const timer = setTimeout(() => setCopy("idle"), 1500);
    return () => clearTimeout(timer);
  }, [copy]);
  const cancel = useAction({
    send: (_: void, opts) => api.cancelQueued(project, sweepId, opts),
    invalidate: REMOTE_RUN_INVALIDATES,
  });
  const extend = useAction({
    send: (seeds: number[], opts) => api.extendSweep(project, sweepId, seeds, opts),
    invalidate: REMOTE_RUN_INVALIDATES,
    onSuccess: () => setOpen(false),
  });
  const cli = sweepCli(spec, runs);
  const n = parseSeedCount(count);
  const seeds = n === null ? [] : nextSeeds(spec.seeds, n);
  const doCopy = async (): Promise<void> => {
    try {
      await navigator.clipboard.writeText(cli);
      setCopy("copied");
    } catch {
      setCopy("failed");
    }
  };
  return (
    <div className="sw-actions">
      <div className="actions">
        <button type="button" className="btn" title={cli} onClick={() => void doCopy()}>
          {COPY_TEXT[copy]}
        </button>
        <button
          type="button"
          className="btn"
          disabled={queued === 0 || cancel.pending}
          title={queued === 0 ? "No queued runs" : `Cancel the ${queued} queued run${queued === 1 ? "" : "s"}`}
          onClick={() => cancel.run()}
        >
          Cancel queued
        </button>
        <button
          type="button"
          className="btn primary"
          aria-expanded={open}
          title="Add seeds to every cell"
          onClick={() => setOpen((v) => !v)}
        >
          Add seeds
        </button>
      </div>
      {open ? (
        <form
          className="add-seeds"
          aria-label="Add seeds"
          onSubmit={(e) => {
            e.preventDefault();
            if (seeds.length > 0) extend.run(seeds);
          }}
        >
          <label>
            new seeds
            <input
              type="number"
              min={1}
              max={MAX_NEW_SEEDS}
              value={count}
              aria-label="New seeds per cell"
              onChange={(e) => setCount(e.target.value)}
            />
          </label>
          <span className="small">
            {seeds.length > 0
              ? `${seeds.join(", ")} × ${cellCount} cells = ${seeds.length * cellCount} runs`
              : `1–${MAX_NEW_SEEDS}`}
          </span>
          <button type="submit" className="btn primary" disabled={seeds.length === 0 || extend.pending}>
            {`Add ${seeds.length * cellCount} runs`}
          </button>
        </form>
      ) : null}
      {cancel.error ? <ErrorBox error={cancel.error} /> : null}
      {extend.error ? <ErrorBox error={extend.error} /> : null}
    </div>
  );
}
```

- [ ] **Step 4: Run the tests and the type check**

Run: `cd ui && bun test test/pages/sweepActions.test.tsx`
Expected: `7 pass`, `0 fail`.

Run: `cd ui && bun run typecheck`
Expected: exits 0 with no errors.

- [ ] **Step 5: Commit**

```bash
git add ui/src/pages/components/SweepActions.tsx ui/test/pages/sweepActions.test.tsx
git commit -m "feat(ui): sweep actions copy as CLI, cancel queued and add seeds"
```

---

### Task 21: Sweep page and route `/s/$project/$id`

**Files:**
- Create: `ui/src/pages/Sweep.tsx`
- Modify: `ui/src/router.tsx` (doc comment, import, screen, route, route tree)
- Test: `ui/test/pages/Sweep.test.tsx`
- Modify: `ui/test/router.test.tsx`
- Modify: `ui/src/pages/components/links.tsx` (`isAppPath`), `ui/test/pages/links.test.tsx` (its route list)
- Modify: `ui/src/pages/Task.tsx` (imports; `SweepsLine`), `ui/test/pages/Task.test.tsx` (`routes`; one new test)

**Interfaces:**
- Consumes: `useSweep(project, sweepId)` (key `["sweeps", project, "detail", sweepId]`), `useProjectSweeps(project)`, `useHosts()`, `useAllRuns` (Task 3), `HostRow`, `SweepSummary`, `SweepListItem` (Task 1); phase 1b `api.leaderboard`, `queryKeys.leaderboard`, `RunsQuery`, `Figure`, `Unbroken`, `AppLink`, `hrefs`, `ErrorBox`, `Loading`, `StatStrip`, `PageStyles`, `fmtClock`, `isAgent`, `primaryMetricName`; every export of Tasks 14–20.
- Produces: `sweepRunsQuery(project: string, tag: string): Omit<RunsQuery, "limit">` (`tag` is `SweepSummary.tag`; read through `useAllRuns` once the summary is loaded, so a sweep extended past 1,000 runs is still whole); `interface SweepPageProps { project: string; sweepId: string; now?: number }`; `SweepPage(props)`; router `sweepRoute` (id `/s/$project/$id`, params `{ project, id }`); `isAppPath` accepts `/s/…`, so plain sweep links inside panels navigate in-app. On the Task page, `SweepsLine` (`p.sweeps`, `aria-label="Sweeps"`) lists the project's sweeps from `GET /api/v1/projects/{project}/sweeps` (id linking `sweepHref`, runs, best config and its mean), so a sweep page is reachable without a run's crumb (spec 5.7: the UI shows each sweep as a group with its best config).

The page loads four queries: the summary (`useSweep`), every run of the sweep by its member tag (`summary.tag`, so the runs query starts when the summary is in) with archived runs (`useAllRuns`: `limit=1000` first, then larger limits while a page is full; the backend default of 200, or any one fixed limit, would cut large sweeps), the hosts (host names by environment and stale derivation), and the task leaderboard only when the sweep has a task (metric name, direction, unit, version, and the forest's seed values, restricted to each cell's own runs by `seedValues`). Hosts and leaderboard errors are ignored: the page still draws without seed dots or stale marks, and names hosts by the machines' own hostnames.

- [ ] **Step 1: Write the failing page tests**

Create `ui/test/pages/Sweep.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { SweepPage, sweepRunsQuery } from "../../src/pages/Sweep";
import { HttpReply, mockApi, renderWithClient, restoreFetch } from "./helpers";
import {
  HOSTS,
  NOW,
  PROJECT,
  RUNS,
  SWEEP_ID,
  SWEEP_TAG,
  TASK,
  makeSummary,
  makeSweepBoard,
  rid,
} from "./sweepFixtures";

afterEach(() => {
  cleanup();
  restoreFetch();
});

const SWEEP = `/api/v1/sweeps/${PROJECT}/${SWEEP_ID}`;
const RUNS_URL = "/api/v1/runs?project=rxn&tag=sweep%3A0a1b2c3d%3As-7f3a&archived=true&limit=1000";
const HEADLINE = "lr 3e-4, beam 10: 0.912 top1, +0.008 over beam 5";

function routes(summary = makeSummary(), runs: unknown = RUNS): Record<string, unknown> {
  return {
    [`GET ${SWEEP}`]: summary,
    [`GET ${RUNS_URL}`]: runs,
    "GET /api/v1/hosts": HOSTS,
    [`GET /api/v1/tasks/${PROJECT}/${TASK}/leaderboard`]: makeSweepBoard(),
    [`POST ${SWEEP}/cancel_queued`]: summary,
    [`POST ${SWEEP}/extend`]: summary,
  };
}

function statValue(label: string): string | null | undefined {
  const stats = document.querySelector(".sweep-stats dl.stats") as HTMLElement;
  return within(stats).getByText(label).parentElement?.querySelector("dd")?.textContent;
}

function renderPage(sweepId = SWEEP_ID) {
  return renderWithClient(<SweepPage project={PROJECT} sweepId={sweepId} now={NOW} />);
}

describe("SweepPage", () => {
  test("sweepRunsQuery asks for every run with the sweep's member tag, archived included", () => {
    // no limit: useAllRuns pages through 1000, 4000, ... until a page is not full
    expect(sweepRunsQuery("rxn", SWEEP_TAG)).toEqual({
      project: "rxn",
      tag: "sweep:0a1b2c3d:s-7f3a",
      archived: true,
    });
  });

  test("headline, meta line, stats, progress and the three panels", async () => {
    mockApi(routes());
    renderPage();
    expect(await screen.findByRole("heading", { level: 1, name: HEADLINE })).toBeTruthy();
    await waitFor(() => expect(statValue("best top1")).toBe("0.9120"));
    await waitFor(() => expect(statValue("cost, 11 GPU-h")).toBe("$12.50"));
    expect(statValue("95% CI")).toBe("0.908–0.916");
    expect(statValue("finished")).toBe("5 / 8");
    expect(statValue("ETA")).toBe("1h 30m");

    expect(screen.getByRole("link", { name: "rxn" }).getAttribute("href")).toBe("/");
    expect(screen.getByRole("link", { name: "fwd" }).getAttribute("href")).toBe("/t/rxn/fwd");
    expect(screen.getByText("sweep s-7f3a")).toBeTruthy();
    expect(screen.getByText("lr 2 × beam 2 × 2 seeds").parentElement?.textContent).toBe(
      "lr 2 × beam 2 × 2 seeds = 8",
    );
    // the hub's host names (matched by environment), not the runs' executor.host hostnames
    expect(await screen.findByText("gpu1, dgx")).toBeTruthy();
    for (const text of ["2 GPU / run", "agent:tuner", "09:12 UTC", "s-7f3a"]) {
      expect(screen.getByText(text)).toBeTruthy();
    }
    expect(screen.getByRole("img", { name: "5 finished, 1 running, 1 queued, 1 failed" })).toBeTruthy();

    const a = screen.getByRole("region", { name: "a top1 by lr × beam" });
    expect(within(a).getByRole("table", { name: "Mean top1 by lr and beam" })).toBeTruthy();
    expect(within(a).getByRole("link", { name: "d1" }).getAttribute("href")).toBe(`/r/${rid("d1")}`);
    expect(screen.getByRole("region", { name: "b Seeds, 95% CI" })).toBeTruthy();
    const c = screen.getByRole("region", { name: "c Runs on hosts" });
    expect(await within(c).findByText("stale 4m")).toBeTruthy();
    expect(within(c).getByText("1 running, 1 queued")).toBeTruthy();
  });

  test("a one-param sweep without a task uses the table and asks for no leaderboard", async () => {
    const cellRaw = (lr: string, tail: string) => ({
      params: { lr },
      group_id: null,
      n: 0,
      mean: null,
      lo: null,
      hi: null,
      std: null,
      run_ids: [rid(tail)],
      runs: [{ run_id: rid(tail), status: "queued", seed: 1 }],
    });
    const summary = makeSummary(
      {
        cells: [cellRaw("1e-4", "a1"), cellRaw("3e-4", "c1")],
        best: null,
        headline: "No scored runs yet",
        total_usd: 0,
        counts: { queued: 2, running: 0, finished: 0, failed: 0, killed: 0, lost: 0, total: 2 },
        run_ids: [rid("a1"), rid("c1")],
      },
      {
        task: null,
        grid: [{ name: "lr", values: ["1e-4", "3e-4"], low: null, high: null, log: false }],
        seeds: [1],
      },
    );
    const calls = mockApi(routes(summary, []));
    renderPage();
    expect(await screen.findByRole("heading", { level: 1, name: "No scored runs yet" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "a score by lr" })).toBeTruthy();
    expect(screen.getByRole("table", { name: "Mean score by lr" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: TASK })).toBeNull();
    expect(screen.getByText("No scored runs yet", { selector: "p" })).toBeTruthy();
    await waitFor(() => expect(screen.getByText("No runs indexed yet")).toBeTruthy());
    expect(calls.some((call) => call.url.includes("/leaderboard"))).toBe(false);
  });

  test("an unknown sweep shows the server's error", async () => {
    mockApi({
      [`GET /api/v1/sweeps/${PROJECT}/nope`]: new HttpReply(404, {
        error: "sweep not found: rxn/nope",
        type: "StoreError",
      }),
      "GET /api/v1/hosts": HOSTS,
    });
    renderPage("nope");
    expect((await screen.findByRole("alert")).textContent).toBe("sweep not found: rxn/nope");
    expect(screen.getByText("sweep nope")).toBeTruthy();
  });

  test("Cancel queued refreshes the sweep", async () => {
    const calls = mockApi(routes());
    renderPage();
    await screen.findByRole("heading", { level: 1, name: HEADLINE });
    const gets = (): number => calls.filter((call) => call.method === "GET" && call.url === SWEEP).length;
    expect(gets()).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "Cancel queued" }));
    await waitFor(() => expect(gets()).toBe(2));
    expect(calls.filter((call) => call.method === "POST").map((call) => call.url)).toEqual([
      `${SWEEP}/cancel_queued`,
    ]);
  });

  test("Add seeds while runs are still queued: new totals, Cancel covers them, later seeds next", async () => {
    let current = makeSummary();
    const added = ["a3", "b3", "c3", "d3", "a4", "b4", "c4", "d4"].map(rid);
    const extended = makeSummary(
      {
        counts: { queued: 9, running: 1, finished: 5, failed: 1, killed: 0, lost: 0, total: 16 },
        run_ids: [...makeSummary().run_ids, ...added],
      },
      { seeds: [1, 2, 3, 4] },
    );
    const calls = mockApi({
      ...routes(),
      [`GET ${SWEEP}`]: () => current,
      [`POST ${SWEEP}/extend`]: () => {
        current = extended;
        return extended;
      },
    });
    renderPage();
    await screen.findByRole("heading", { level: 1, name: HEADLINE });
    fireEvent.click(screen.getByRole("button", { name: "Add seeds" }));
    fireEvent.click(screen.getByRole("button", { name: "Add 8 runs" }));
    await waitFor(() => expect(statValue("finished")).toBe("5 / 16"));
    expect(screen.getByRole("button", { name: "Cancel queued" }).getAttribute("title")).toBe(
      "Cancel the 9 queued runs",
    );
    expect(calls.find((call) => call.method === "POST")?.body).toMatchObject({ seeds: [3, 4] });
    fireEvent.click(screen.getByRole("button", { name: "Add seeds" }));
    // 2 new seeds (the count stays 2) × 4 cells
    expect(screen.getByText("5, 6 × 4 cells = 8 runs")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Add the failing router tests**

In `ui/test/router.test.tsx`, insert after the test `"/x/:a/:b reads ?metric"` (inside `describe("routes", ...)`):

```tsx
  test("/s/:project/:id is the sweep page", async () => {
    const { router } = renderApp("/s/rxn/s-7f3a");
    await settled(router, "/s/$project/$id");
    expect(leaf(router)?.params).toEqual({ project: "rxn", id: "s-7f3a" });
  });
```

In the same file, in the test `"every route renders its own screen, not the placeholder"`, replace:

```tsx
  for (const path of ["/", "/t/toy/acc", "/t/toy/acc/edit/new", "/r/r1", "/x/r1/r2?metric=accuracy"]) {
```

with:

```tsx
  for (const path of ["/", "/t/toy/acc", "/t/toy/acc/edit/new", "/r/r1", "/x/r1/r2?metric=accuracy", "/s/rxn/s-7f3a"]) {
```

In `ui/test/pages/links.test.tsx`, test `routes plain clicks on app links in-app and leaves the rest to the browser`, replace:

```tsx
    expect(["/", "/t/p/t", "/r/r1", "/x/a/b", "/api/v1/runs", "/mcp", "/rx"].map(isAppPath)).toEqual([
      true,
      true,
      true,
      true,
      false,
      false,
      false,
    ]);
```

with:

```tsx
    expect(["/", "/t/p/t", "/r/r1", "/x/a/b", "/s/p/s-1", "/api/v1/runs", "/mcp", "/rx"].map(isAppPath)).toEqual([
      true,
      true,
      true,
      true,
      true,
      false,
      false,
      false,
    ]);
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd ui && bun test test/pages/Sweep.test.tsx test/router.test.tsx test/pages/links.test.tsx`
Expected: FAIL: `error: Cannot find module '../../src/pages/Sweep'` for the page file; in the router file the new test fails (the unknown path renders Not found, so the leaf route is not `/s/$project/$id`), and `bun run typecheck` would also reject `"/s/$project/$id"` as a route id until the route exists; in the links file the `isAppPath` test fails on `/s/p/s-1` (`false`, expected `true`).

- [ ] **Step 4: Write the page**

Create `ui/src/pages/Sweep.tsx`:

```tsx
/**
 * Sweep screen (spec 8A.6, contract section 4, mockup shot-sweep-*): one-line headline
 * with the best cell, meta line, stat strip and progress strip; (a) params heat table
 * for two listed params, a sortable table otherwise; (b) seeds forest; (c) runs on hosts.
 * Actions: Copy as CLI, Cancel queued, Add seeds.
 */
import { useQuery } from "@tanstack/react-query";
import type { ReactElement } from "react";
import { api } from "../api/client";
import type { HostRow, Leaderboard, RunRecord, RunStatus, RunsQuery, SweepSummary } from "../api/models";
import { queryKeys, useAllRuns, useHosts, useSweep } from "../api/queries";
import { Figure } from "./components/Figure";
import { fmtClock, isAgent, primaryMetricName } from "./components/format";
import { Unbroken } from "./components/Headline";
import { AppLink, hrefs } from "./components/links";
import { ErrorBox, Loading } from "./components/QueryState";
import { StatStrip } from "./components/StatStrip";
import { PageStyles } from "./components/styles";
import { SweepActions } from "./components/SweepActions";
import { SweepForest } from "./components/SweepForest";
import { SweepProgress } from "./components/SweepGlyphs";
import { SweepHeat } from "./components/SweepHeat";
import {
  type SweepCellRow,
  gridLabel,
  heatAxes,
  hostsOf,
  orderRuns,
  parseCell,
  parseCells,
  runState,
  seedValues,
  staleHosts,
  sweepStats,
} from "./components/SweepModel";
import { SweepRuns } from "./components/SweepRuns";
import { SweepStyles } from "./components/SweepStyles";
import { SweepTable } from "./components/SweepTable";

/**
 * `GET /api/v1/runs` query for every run of a sweep (its member tag `SweepSummary.tag`,
 * `sweep:<owner8>:<id>`, archived included). The UI never builds the tag: the owner part is
 * the hub's environment id. No limit: `useAllRuns` pages until it has them all.
 */
export function sweepRunsQuery(project: string, tag: string): Omit<RunsQuery, "limit"> {
  return { project, tag, archived: true };
}

export interface SweepPageProps {
  project: string;
  sweepId: string;
  /** Clock for ages, GPU-hours and ETA (tests pass a fixed time). */
  now?: number;
}

export function SweepPage({ project, sweepId, now }: SweepPageProps): ReactElement {
  const summary = useSweep(project, sweepId);
  const memberTag = summary.data?.tag; // the runs query waits for the summary's member tag
  const runs = useAllRuns(sweepRunsQuery(project, memberTag ?? ""), memberTag !== undefined);
  const hosts = useHosts();
  const task = summary.data?.spec.task ?? null;
  const board = useQuery({
    queryKey: queryKeys.leaderboard(project, task ?? "", []),
    queryFn: ({ signal }) => api.leaderboard(project, task ?? "", [], signal),
    enabled: task !== null,
  });
  return (
    <div className="page">
      <PageStyles />
      <SweepStyles />
      <p className="crumb">
        <AppLink href={hrefs.overview()}>{project}</AppLink>
        <span className="sep">/</span>
        {task !== null ? (
          <>
            <AppLink href={hrefs.task(project, task)}>{task}</AppLink>
            <span className="sep">/</span>
          </>
        ) : null}
        {`sweep ${sweepId}`}
      </p>
      {summary.error ? (
        <ErrorBox error={summary.error} />
      ) : summary.data ? (
        <SweepBody
          project={project}
          sweepId={sweepId}
          summary={summary.data}
          runs={runs.data?.runs ?? []}
          hosts={hosts.data}
          board={board.data}
          now={now ?? Date.now()}
        />
      ) : (
        <Loading />
      )}
      {runs.error && !summary.error ? <ErrorBox error={runs.error} /> : null}
    </div>
  );
}

interface SweepBodyProps {
  project: string;
  sweepId: string;
  summary: SweepSummary;
  runs: readonly RunRecord[];
  hosts: readonly HostRow[] | undefined;
  board: Leaderboard | undefined;
  now: number;
}

function SweepBody({ project, sweepId, summary, runs, hosts, board, now }: SweepBodyProps): ReactElement {
  const { spec, counts } = summary;
  const names = spec.grid.map((p) => p.name);
  const cells = parseCells(summary.cells);
  const best = parseCell(summary.best);
  const higherIsBetter = board?.higher_is_better ?? true;
  const metric = board ? primaryMetricName(board.primary) : "score";
  const version = board?.metric_versions[metric];
  const stale = staleHosts(hosts);
  // membership comes from the backend (`summary.run_ids`, derived from the runs tagged `summary.tag`)
  const ordered = orderRuns(runs, summary.run_ids);
  const byId = new Map(ordered.map((r) => [r.run_id, r]));
  const stateOf = (id: string, fallback: RunStatus | null) => runState(byId.get(id), fallback, stale);
  const seedsOf = (c: SweepCellRow): number[] => seedValues(c, board);
  const axes = heatAxes(spec);
  const gpus = ordered.find((r) => (r.gpus_requested ?? 0) > 0)?.gpus_requested ?? 0;
  const hostList = ordered.length > 0 ? hostsOf(ordered, hosts) : spec.host ? [spec.host] : [];
  const states = ordered.map((r) => runState(r, null, stale));
  const running = states.filter((s) => s === "running" || s === "stale").length;
  const queued = states.filter((s) => s === "queued").length;
  const maxSeeds = spec.seeds.length;
  return (
    <>
      <div className="run-top">
        <div>
          <h1 className="headline">
            <Unbroken text={summary.headline} />
          </h1>
          <p className="metaline">
            <span title={`${cells.length} param combinations × ${maxSeeds} seeds`}>
              <b>{gridLabel(spec)}</b>
              {` = ${counts.total ?? 0}`}
            </span>
            {gpus > 0 ? <span>{`${gpus} GPU / run`}</span> : null}
            {hostList.length > 0 ? <span title="Hosts">{hostList.join(", ")}</span> : null}
            <span className={`who ${isAgent(spec.created_by) ? "agent" : "human"}`}>
              <i />
              {spec.created_by}
            </span>
            <span title={spec.created_at}>{`${fmtClock(spec.created_at)} UTC`}</span>
            <span className="tag" title="Sweep id">
              {spec.id}
            </span>
          </p>
        </div>
        <SweepActions
          project={project}
          sweepId={sweepId}
          spec={spec}
          queued={counts.queued ?? 0}
          cellCount={cells.length}
          runs={ordered}
        />
      </div>
      <div className="sweep-stats">
        <StatStrip
          items={sweepStats({
            counts,
            totalUsd: summary.total_usd,
            best,
            names,
            metric,
            unit: board?.unit ?? "",
            runs: ordered,
            hosts,
            now,
          })}
        />
        <SweepProgress counts={counts} />
      </div>
      <div className="sw-grid">
        <Figure
          letter="a"
          title={`${metric} by ${(axes ? [axes.row, axes.col] : names).join(" × ")}`}
          aside="mean over seeds"
        >
          {axes ? (
            <SweepHeat
              axes={axes}
              cells={cells}
              best={best}
              metric={metric}
              higherIsBetter={higherIsBetter}
              maxSeeds={maxSeeds}
              stateOf={stateOf}
              seedsOf={seedsOf}
            />
          ) : (
            <SweepTable
              names={names}
              cells={cells}
              best={best}
              metric={metric}
              higherIsBetter={higherIsBetter}
              maxSeeds={maxSeeds}
              stateOf={stateOf}
            />
          )}
        </Figure>
        <Figure letter="b" title="Seeds, 95% CI" aside={metric}>
          <SweepForest
            cells={cells}
            best={best}
            names={names}
            metric={metric}
            axisLabel={version ? `${metric} ${version}` : metric}
            higherIsBetter={higherIsBetter}
            maxSeeds={maxSeeds}
            seedsOf={seedsOf}
          />
        </Figure>
      </div>
      <Figure letter="c" title="Runs on hosts" aside={`${running} running, ${queued} queued`}>
        <SweepRuns runs={ordered} names={names} stale={stale} hosts={hosts} now={now} />
      </Figure>
    </>
  );
}
```

- [ ] **Step 5: Wire the route and the in-app link check**

In `ui/src/router.tsx`:

1. In the top doc comment, replace the line

```tsx
 * `/r/$runId` Run, `/x/$a/$b?metric=` Examples.
```

with

```tsx
 * `/r/$runId` Run, `/x/$a/$b?metric=` Examples, `/s/$project/$id` Sweep.
```

2. After `import { RunPage } from "./pages/Run";` add:

```tsx
import { SweepPage } from "./pages/Sweep";
```

3. After the `ExamplesScreen` function add:

```tsx
/** `/s/$project/$id`: the Sweep page; keyed so a new sweep starts with fresh UI state. */
function SweepScreen(): ReactElement {
  const { project, id } = sweepRoute.useParams();
  return <SweepPage key={`${project}/${id}`} project={project} sweepId={id} />;
}
```

4. After the `examplesRoute` definition add:

```tsx
export const sweepRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/s/$project/$id",
  component: SweepScreen,
});
```

5. Replace the route tree

```tsx
export const routeTree = rootRoute.addChildren([
  overviewRoute,
  taskRoute,
  viewEditorRoute,
  runRoute,
  examplesRoute,
]);
```

with

```tsx
export const routeTree = rootRoute.addChildren([
  overviewRoute,
  taskRoute,
  viewEditorRoute,
  runRoute,
  examplesRoute,
  sweepRoute,
]);
```

6. In `ui/src/pages/components/links.tsx`, replace

```tsx
/** True for a path the SPA routes (Overview, Task, Run, Examples); `/api/…` is left to the browser. */
export function isAppPath(pathname: string): boolean {
  return /^\/($|[trx]\/)/.test(pathname);
}
```

with

```tsx
/** True for a path the SPA routes (Overview, Task, Run, Examples, Sweep); `/api/…` is left to the browser. */
export function isAppPath(pathname: string): boolean {
  return /^\/($|[trsx]\/)/.test(pathname);
}
```

- [ ] **Step 6: List the project's sweeps on the Task page**

In `ui/test/pages/Task.test.tsx`, in `routes(view)`, replace

```ts
    [`POST ${BASE}/reeval`]: { evaluated: 12 },
  };
}
```

with

```ts
    [`POST ${BASE}/reeval`]: { evaluated: 12 },
    "GET /api/v1/projects/toy-classifier/sweeps": [],
  };
}
```

and add this test inside `describe("TaskPage", ...)`, after the `New run` test:

```tsx
  test("lists the project's sweeps with their best config, each linking its sweep page", async () => {
    mockApi({
      ...routes("overview"),
      "GET /api/v1/projects/toy-classifier/sweeps": [
        {
          id: "s-7f3a",
          created_at: "2026-10-03T09:12:00Z",
          n_runs: 6,
          best: { params: { lr: "3e-4", beam: "10" }, group_id: "g-7e3f", n: 3, mean: 0.9121, lo: 0.9109, hi: 0.9133, run_ids: [] },
        },
        { id: "s-1b2c", created_at: "2026-10-02T09:00:00Z", n_runs: 4, best: null },
      ],
    });
    renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
    const line = await screen.findByLabelText("Sweeps");
    expect(line.textContent).toBe("sweeps: s-7f3a ×6 lr 3e-4, beam 10 0.9121 · s-1b2c ×4");
    expect(within(line).getByRole("link", { name: "s-7f3a" }).getAttribute("href")).toBe("/s/toy-classifier/s-7f3a");
  });
```

Run: `cd ui && bun test test/pages/Task.test.tsx`
Expected: FAIL in the new test (`Unable to find a label with the text of: Sweeps`); the other 6 pass.

In `ui/src/pages/Task.tsx`, replace

```tsx
  useLeaderboard,
  useRuns,
```

with

```tsx
  useLeaderboard,
  useProjectSweeps,
  useRuns,
```

replace

```tsx
import { shortId } from "./components/format";
```

with

```tsx
import { fmtScore, shortId } from "./components/format";
```

replace

```tsx
import { PageStyles } from "./components/styles";
```

with

```tsx
import { PageStyles } from "./components/styles";
import { paramsText, sweepHref } from "./components/SweepModel";
```

replace

```tsx
export function TaskPage({ project, task, view }: TaskPageProps) {
```

with

```tsx
/**
 * The project's sweeps (spec 5.7: each sweep as a group with its best config): id linking
 * the sweep page, run count, best params and mean. Nothing while there are none, or when
 * the list fails (the rest of the page does not depend on it).
 */
function SweepsLine({ project }: { project: string }) {
  const sweeps = useProjectSweeps(project);
  const items = sweeps.data ?? [];
  if (items.length === 0) return null;
  return (
    <p className="small sweeps" aria-label="Sweeps" title={`Sweeps of project ${project}`}>
      sweeps:{" "}
      {items.map((s, i) => (
        <Fragment key={s.id}>
          {i > 0 ? " · " : ""}
          <AppLink href={sweepHref(project, s.id)} title={`${s.n_runs} runs, created ${s.created_at}`}>
            {s.id}
          </AppLink>
          {` ×${s.n_runs}`}
          {s.best && s.best.mean !== null
            ? ` ${paramsText(s.best.params, Object.keys(s.best.params))} ${fmtScore(s.best.mean)}`
            : ""}
        </Fragment>
      ))}
    </p>
  );
}

export function TaskPage({ project, task, view }: TaskPageProps) {
```

and replace

```tsx
      {launched ? <LaunchedLine launched={launched} /> : null}
```

with

```tsx
      {launched ? <LaunchedLine launched={launched} /> : null}
      <SweepsLine project={project} />
```

- [ ] **Step 7: Run the page, router, links and Task tests**

Run: `cd ui && bun test test/pages/Sweep.test.tsx test/router.test.tsx test/pages/links.test.tsx test/pages/Task.test.tsx`
Expected: `31 pass`, `0 fail` (6 page tests, 12 router tests, 6 links tests, 7 Task tests).

- [ ] **Step 8: Run the whole UI suite, the type check and the build**

Run: `cd ui && bun test`
Expected: every test passes, `0 fail` (Tasks 14-21 add 70 tests in new files: 18 + 14 + 4 + 6 + 6 + 4 + 5 + 7 + 6, plus 1 router test and 1 Task page test).

Run: `cd ui && bun run typecheck`
Expected: exits 0 with no errors.

Run: `cd ui && bun run build`
Expected: `tsc --noEmit` passes and Vite prints `✓ built in ...`, writing `src/hypothex/ui_dist/` (git-ignored; do not commit it).

- [ ] **Step 9: Commit**

```bash
git add ui/src/pages/Sweep.tsx ui/src/router.tsx ui/src/pages/components/links.tsx ui/src/pages/Task.tsx ui/test/pages/Sweep.test.tsx ui/test/router.test.tsx ui/test/pages/links.test.tsx ui/test/pages/Task.test.tsx
git commit -m "feat(ui): sweep page at /s/:project/:id; project sweeps on the task page"
```

---

### Task 22: "Rerun sweep" opens the Launch dialog

Contract section 4 opens the Launch dialog from the Task page "New run" (Task 13) and from a sweep page "Rerun sweep". The dialog launches one command over several seeds, so "Rerun sweep" reruns the sweep's best cell: the template is the best cell's latest run (its command template with the `{param}` and `{seed}` slots, its params and vars, its GPUs per run), on the sweep's host, with the next seeds after every seed that config used, on the template's code: its commit is pinned (`pinnedCommit`, Task 10) when that run had no uncommitted changes, else the hub pins its own checkout (the dialog cannot send that run's diff). Without a scored cell it uses the sweep's latest run.

**Files:**
- Create: `ui/src/pages/components/SweepRerun.tsx`
- Modify: `ui/src/pages/components/SweepActions.tsx` (props, signature, the action row)
- Modify: `ui/src/pages/Sweep.tsx` (imports, `SweepBody`)
- Test: `ui/test/pages/sweepRerun.test.tsx`

**Interfaces:**
- Consumes: `LaunchDialog`, `LaunchDialogProps` (Task 12); `launchDefaults`, `pinnedCommit`, `Carry`, `LaunchDraft` (Task 10); `useProjects` (phase 1b, `ProjectInfo.repo` is the repo path on the hub); `SweepCellRow` (Task 14); `SweepActions` (Task 20); `SweepPage` (Task 21); `parseTime` from `./format`; `ErrorBox`, `Loading`.
- Produces:
  - `interface RerunDefaults { template: RunRecord | null; initial: Partial<LaunchDraft>; carry: Carry; commit: string | null }`
  - `rerunDefaults(spec: SweepSpec, best: SweepCellRow | null, runs: readonly RunRecord[]): RerunDefaults`
  - `interface SweepRerunProps { project: string; spec: SweepSpec; best: SweepCellRow | null; runs: readonly RunRecord[]; onClose: () => void; onLaunched: (records: RunRecord[], host: string) => void }`; `SweepRerun(props)` (loads the repo path, then shows `LaunchDialog` titled `Rerun sweep`)
  - `SweepActionsProps.onRerun?: () => void` (a `Rerun sweep` button first in the action row when set)
  - Sweep page: `Rerun sweep` opens the dialog; after a launch, `p.launched` (`role="status"`) reads `Launched N on HOST`.

- [ ] **Step 1: Write the failing tests**

Create `ui/test/pages/sweepRerun.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { parseCell } from "../../src/pages/components/SweepModel";
import { rerunDefaults } from "../../src/pages/components/SweepRerun";
import { SweepPage } from "../../src/pages/Sweep";
import { makeRecord } from "./fixtures";
import { type Call, mockApi, renderWithClient, restoreFetch } from "./helpers";
import {
  CELL_D,
  HOSTS,
  NOW,
  PROJECT,
  RUNS,
  SWEEP_ID,
  TASK,
  TEMPLATE,
  makeSummary,
  makeSweepBoard,
  rid,
  run,
} from "./sweepFixtures";

afterEach(() => {
  cleanup();
  restoreFetch();
});

const SWEEP = `/api/v1/sweeps/${PROJECT}/${SWEEP_ID}`;
const RUNS_URL = "/api/v1/runs?project=rxn&tag=sweep%3A0a1b2c3d%3As-7f3a&archived=true&limit=1000";
const REPO = "/Users/sv/code/rxn";

describe("rerunDefaults", () => {
  test("the best cell's latest run: its template, params and vars, the next seeds, the sweep's host", () => {
    const spec = { ...makeSummary().spec, host: "gpu1" };
    const d = rerunDefaults(spec, parseCell(CELL_D), RUNS);
    expect(d.template?.run_id).toBe(rid("d1"));
    expect(d.initial).toEqual({
      command: "python train.py --lr {lr} --beam {beam} --seed {seed}",
      seeds: "3, 4, 5",
      host: "gpu1",
      gpus: 2,
    });
    expect(d.carry).toEqual({ params: { lr: "3e-4", beam: "10" }, vars: { lr: "3e-4", beam: "10" } });
    // the template ran clean: its commit is pinned; a dirty template pins nothing
    expect(d.commit).toBe("8f4cac43877b75953f18ff1daf7e6fc54a5d8f37");
    const dirty = RUNS.map((r) => (r.run_id === rid("d1") ? { ...r, git: { ...r.git, dirty: true } } : r));
    expect(rerunDefaults(spec, parseCell(CELL_D), dirty).commit).toBeNull();
  });

  test("no scored cell: the sweep's latest run; no runs: seeds 1, 2, 3 and nothing carried", () => {
    const late = { ...run("a1"), run_id: rid("z9"), created_at: "2026-10-03T11:00:00Z" };
    expect(rerunDefaults(makeSummary().spec, null, [...RUNS, late]).template?.run_id).toBe(rid("z9"));
    expect(rerunDefaults(makeSummary().spec, null, [])).toEqual({
      template: null,
      initial: { seeds: "1, 2, 3", host: null },
      carry: { params: {}, vars: {} },
      commit: null,
    });
  });
});

describe("Rerun sweep", () => {
  test("opens the Launch dialog from the best cell and launches its next seeds", async () => {
    const calls = mockApi({
      [`GET ${SWEEP}`]: makeSummary(),
      [`GET ${RUNS_URL}`]: RUNS,
      "GET /api/v1/hosts": HOSTS,
      "GET /api/v1/gpus": [],
      "GET /api/v1/queue": [],
      [`GET /api/v1/tasks/${PROJECT}/${TASK}/leaderboard`]: makeSweepBoard(),
      "GET /api/v1/projects": [{ project: PROJECT, repo: REPO, description: "", tasks: [TASK] }],
      "POST /api/v1/runs": (call: Call) => {
        const seed = (call.body as { seed: number }).seed;
        return makeRecord({ run_id: `20261003-120000-fwd-r${seed}`, seed, status: "running" });
      },
    });
    renderWithClient(<SweepPage project={PROJECT} sweepId={SWEEP_ID} now={NOW} />);
    fireEvent.click(await screen.findByRole("button", { name: "Rerun sweep" }));

    const dialog = await screen.findByRole("dialog", { name: "Rerun sweep" });
    expect(within(dialog).getByText(`${PROJECT} / ${TASK}`)).toBeTruthy();
    expect((within(dialog).getByLabelText("Command") as HTMLTextAreaElement).value).toBe(TEMPLATE.join(" "));
    expect((within(dialog).getByLabelText("Seeds") as HTMLInputElement).value).toBe("3, 4, 5");
    await waitFor(() =>
      expect((within(dialog).getByRole("radio", { name: "local" }) as HTMLInputElement).checked).toBe(true),
    );
    // the template's commit is pinned and shown with the code location
    expect(within(dialog).getByText(`${REPO} @ 8f4cac4`)).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText("Hypothesis"), {
      target: { value: "best cell holds on new seeds" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Launch 3" }));

    // the dialog's `<output>` (GPUs per run) is also a status role: wait for the dialog to
    // close. Poll a boolean: a failed `toBeNull()` on a DOM node prints the whole page tree
    await waitFor(() => expect(document.querySelector('[role="dialog"]') === null).toBe(true));
    const line = document.querySelector("p.launched");
    expect([line?.getAttribute("role"), line?.textContent]).toEqual(["status", "Launched 3 on local"]);
    const sent = calls.filter((c) => c.method === "POST" && c.url === "/api/v1/runs");
    expect(sent.map((c) => (c.body as { seed: number }).seed)).toEqual([3, 4, 5]);
    expect(sent[0]?.body).toMatchObject({
      repo: REPO,
      task: TASK,
      command: TEMPLATE,
      params: { lr: "3e-4", beam: "10" },
      vars: { lr: "3e-4", beam: "10" },
      hypothesis: "best cell holds on new seeds",
      gpus: 0,
      queue: false,
      commit: "8f4cac43877b75953f18ff1daf7e6fc54a5d8f37",
    });
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && bun test test/pages/sweepRerun.test.tsx`
Expected: FAIL with `error: Cannot find module '../../src/pages/components/SweepRerun'` (0 pass).

- [ ] **Step 3: Write `SweepRerun.tsx`**

Create `ui/src/pages/components/SweepRerun.tsx`:

```tsx
/**
 * "Rerun sweep" (contract section 4): the Launch dialog, prefilled from the sweep's best
 * cell. The template is the cell's latest run: its command template (with the `{param}`
 * and `{seed}` slots), its params and vars (sent with every seed, so the slots fill), its
 * GPUs per run, the sweep's host, and the next seeds after every seed that config used.
 */
import type { ReactElement } from "react";
import type { RunRecord, SweepSpec } from "../../api/models";
import { useProjects } from "../../api/queries";
import { type Carry, type LaunchDraft, launchDefaults, pinnedCommit } from "../../launch/draft";
import { LaunchDialog } from "../../launch/LaunchDialog";
import { parseTime } from "./format";
import { ErrorBox, Loading } from "./QueryState";
import type { SweepCellRow } from "./SweepModel";

export interface RerunDefaults {
  /** The run the dialog copies; null when the sweep has no run yet. */
  template: RunRecord | null;
  initial: Partial<LaunchDraft>;
  carry: Carry;
  /** The template's commit when it ran clean (`pinnedCommit`); null: the hub pins its own. */
  commit: string | null;
}

/** The best cell's latest run (else the sweep's latest run) and the dialog defaults it gives. */
export function rerunDefaults(spec: SweepSpec, best: SweepCellRow | null, runs: readonly RunRecord[]): RerunDefaults {
  const pool = best ? runs.filter((r) => best.run_ids.includes(r.run_id)) : [...runs];
  const template = [...pool].sort((a, b) => parseTime(b.created_at) - parseTime(a.created_at))[0] ?? null;
  const defaults = launchDefaults(template, runs);
  const gpus = template?.gpus_requested ?? 0;
  return {
    template,
    initial: { ...defaults.draft, host: spec.host, ...(gpus > 0 ? { gpus } : {}) },
    carry: defaults.carry,
    commit: pinnedCommit(template),
  };
}

export interface SweepRerunProps {
  project: string;
  spec: SweepSpec;
  best: SweepCellRow | null;
  /** The sweep's runs, in launch order. */
  runs: readonly RunRecord[];
  onClose: () => void;
  onLaunched: (records: RunRecord[], host: string) => void;
}

/** Loads the project's repo path on the hub, then shows the Launch dialog. */
export function SweepRerun({ project, spec, best, runs, onClose, onLaunched }: SweepRerunProps): ReactElement {
  const projects = useProjects();
  if (projects.error) return <ErrorBox error={projects.error} />;
  if (projects.data === undefined) return <Loading />;
  const repo = projects.data.find((p) => p.project === project)?.repo;
  if (repo === undefined) return <ErrorBox error={new Error(`no repo for ${project} on the hub`)} />;
  const d = rerunDefaults(spec, best, runs);
  return (
    <LaunchDialog
      project={project}
      task={spec.task}
      repo={repo}
      commit={d.commit}
      title="Rerun sweep"
      initial={d.initial}
      carry={d.carry}
      onClose={onClose}
      onLaunched={onLaunched}
    />
  );
}
```

- [ ] **Step 4: Add the `Rerun sweep` button to `SweepActions.tsx`**

In `ui/src/pages/components/SweepActions.tsx`, replace

```tsx
  /** The sweep's runs, for `--gpus`, `--queue` and `-H` in Copy as CLI. */
  runs: readonly RunRecord[];
}
```

with

```tsx
  /** The sweep's runs, for `--gpus`, `--queue` and `-H` in Copy as CLI. */
  runs: readonly RunRecord[];
  /** Opens the Launch dialog for "Rerun sweep"; no button without it. */
  onRerun?: () => void;
}
```

Replace

```tsx
export function SweepActions({ project, sweepId, spec, queued, cellCount, runs }: SweepActionsProps): ReactElement {
```

with

```tsx
export function SweepActions({
  project,
  sweepId,
  spec,
  queued,
  cellCount,
  runs,
  onRerun,
}: SweepActionsProps): ReactElement {
```

Replace

```tsx
      <div className="actions">
        <button type="button" className="btn" title={cli} onClick={() => void doCopy()}>
```

with

```tsx
      <div className="actions">
        {onRerun ? (
          <button
            type="button"
            className="btn"
            title="Launch the best cell again on new seeds, on any host"
            onClick={onRerun}
          >
            Rerun sweep
          </button>
        ) : null}
        <button type="button" className="btn" title={cli} onClick={() => void doCopy()}>
```

- [ ] **Step 5: Wire the dialog into the Sweep page**

In `ui/src/pages/Sweep.tsx`, replace

```tsx
import type { ReactElement } from "react";
```

with

```tsx
import { type ReactElement, useState } from "react";
```

Replace

```tsx
import { SweepRuns } from "./components/SweepRuns";
```

with

```tsx
import { SweepRerun } from "./components/SweepRerun";
import { SweepRuns } from "./components/SweepRuns";
```

Replace

```tsx
  const maxSeeds = spec.seeds.length;
```

with

```tsx
  const maxSeeds = spec.seeds.length;
  const [rerun, setRerun] = useState(false);
  const [launched, setLaunched] = useState<{ host: string; n: number } | null>(null);
```

Replace

```tsx
          cellCount={cells.length}
          runs={ordered}
        />
      </div>
      <div className="sweep-stats">
```

with

```tsx
          cellCount={cells.length}
          runs={ordered}
          onRerun={() => setRerun(true)}
        />
      </div>
      {launched ? (
        <p className="small launched" role="status">{`Launched ${launched.n} on ${launched.host}`}</p>
      ) : null}
      <div className="sweep-stats">
```

Replace

```tsx
      <Figure letter="c" title="Runs on hosts" aside={`${running} running, ${queued} queued`}>
        <SweepRuns runs={ordered} names={names} stale={stale} hosts={hosts} now={now} />
      </Figure>
    </>
```

with

```tsx
      <Figure letter="c" title="Runs on hosts" aside={`${running} running, ${queued} queued`}>
        <SweepRuns runs={ordered} names={names} stale={stale} hosts={hosts} now={now} />
      </Figure>
      {rerun ? (
        <SweepRerun
          project={project}
          spec={spec}
          best={best}
          runs={ordered}
          onClose={() => setRerun(false)}
          onLaunched={(records, host) => {
            setRerun(false);
            setLaunched({ host, n: records.length });
          }}
        />
      ) : null}
    </>
```

- [ ] **Step 6: Run the sweep tests and the type check**

Run: `cd ui && bun test test/pages/sweepRerun.test.tsx test/pages/sweepActions.test.tsx test/pages/Sweep.test.tsx`
Expected: `16 pass` (3 + 7 + 6), `0 fail`.

Run: `cd ui && bun run typecheck`
Expected: exits 0 with no errors.

- [ ] **Step 7: Run the whole UI suite**

Run: `cd ui && bun test`
Expected: `0 fail`.

- [ ] **Step 8: Commit**

```bash
git add ui/src/pages/components/SweepRerun.tsx ui/src/pages/components/SweepActions.tsx ui/src/pages/Sweep.tsx ui/test/pages/sweepRerun.test.tsx
git commit -m "feat(ui): rerun sweep opens the launch dialog from the best cell"
```

---

## Group 5: Run page states, cost, end-to-end, docs (Tasks 23–29)

The run page shows where a remote run is and what state it is in: queued (position, GPUs it waits for, the host queue), running on a host (host, `CUDA_VISIBLE_DEVICES`, SLURM job and node, pid), stale (host unreachable since), lost (reason), and the run's cost (spec 5.6, 8A.5, 8A.7, 8A.8). One pure module (`remote.ts`) derives a display phase from the run detail (`record.status`, `executor.*`, `host_state`; `host_state: null` is a hub run, whatever `executor.host` says) plus the short texts for each phase, and finds the run's host row by `environment_id` (`runHostRow`, never `executor.host`, which is the box's own hostname); `remoteStats.ts` gives the stat strip items per phase. `Placement`, `QueuePanel`, `StateBanner` and the extended `StatusLine` draw the parts; `RunActions` picks its buttons by phase; `Run.tsx` wires them, reading `GET /api/v1/hosts` only for remote runs and, only for queued runs, the whole queue of the run's host (`useAllRuns` of `{status: "queued", environment_id}`: `limit=1000`, then larger limits while a page is full; never the newest page of every host's queued runs, which cut long queues off at their head and could leave another host's runs only). Hub runs render exactly as in phase 1b. The `run.lost` reason is in the event payload, not in `RunDetail`: when this tab's event stream carried it (`useLostReason`, Task 4), the lost bar shows it first (`SLURM ended job 4471023 with NODE_FAIL on r814u05n01; no exit record`); otherwise the bar names only what the record says (the SLURM job, node, end time, exit code) in neutral words (`SLURM job 4471023 lost`), never a guessed cause such as "left squeue and sacct": a job lost to `NODE_FAIL` is still in accounting. Playwright gets a second demo server (`bun e2e/serve-demo.ts --with-hosts`, on a random port like the first) and four projects (`hosts-light`, `hosts-dark`, `hosts-light-edit`, `hosts-dark-edit`); Task 29 documents the new screens.

What Task 28's specs rely on:

- The backend plan's demo (contract 5): `uv run hx --home H demo --with-hosts --json` exits 0 after seeding H, and `uv run hx --home H serve --port P` then serves a hub whose `GET /api/v1/hosts` lists fake hosts (reached by `route: url`) that reach `connected`: at least one ssh host with GPUs and at least one project mapped, one slurm host, at least one queued run with `executor.queue_position`, at least one running run with non-empty `executor.gpus`, and at least one sweep.
- Accessible names from Tasks 5–22: the Overview region `a Hosts` with one row per host named by the host; the Task page button `New run` opening a dialog named `New run` with host radios named by host, inputs labelled `Seeds`, `Command`, `Hypothesis`, the toggle `wait for GPUs`, and a button whose name starts with `Launch`; the Sweep page showing `SweepSummary.headline` and the buttons `Copy as CLI`, `Cancel queued`, `Add seeds`.

### Task 23: Remote run phase and texts

**Files:**
- Create: `ui/src/pages/components/remote.ts`
- Create: `ui/test/pages/remoteFixtures.ts`
- Test: `ui/test/pages/remote.test.ts`

**Interfaces:**
- Consumes: `RunDetail`, `RunRecord`, `HostRow`, `GpuInfo`, `CostTotals`, `ConnState`, `ExecutorInfo` types (Task 1); `hostRowForRun` from `./HostsPanel` (Task 5); `fmtClock`, `fmtTime`, `fmtUsd`, `parseTime` from `ui/src/pages/components/format.ts` (exist); `makeRecord`, `makeDetail` from `ui/test/pages/fixtures.ts` (exist); `HOSTS`, `REMOTE_EXECUTOR`, `COST` from `ui/test/api/phase2-fixtures.ts` (Task 1); `fmtAge`, `sweepHref` from `./SweepModel` (Task 14).
- Produces (in `ui/src/pages/components/remote.ts`):
  - `type RunPhase = "local" | "queued" | "pending" | "running" | "stale" | "lost" | "ended"`
  - `runPhase(detail: RunDetail): RunPhase` (`host_state` null or absent: `local`, a hub run, even though the backend sets `executor.host` on every run; `lost` still wins)
  - `runHostRow(detail: RunDetail, hosts: readonly HostRow[] | undefined): HostRow | null` (the row serving the run's environment; null for a hub run or without the hosts list)
  - `hostLabel(record: RunRecord, host: HostRow | null): string` (`host.name`, the hub's name; else the machine's own hostname `record.host`, for texts only: Reconnect needs `host.name`)
  - `ordinal(n: number): string`, `fmtWait(seconds: number): string` (re-export of the sweep page's `fmtAge`: `45s`, `12m`, `1h 52m`), `secondsSince(iso: string, now: number): number | null`
  - `visibleDevices(gpus: readonly number[]): string`, `shortGpuName(name: string): string`, `gpuLabel(count: number, host: HostRow | null, indices?: readonly number[]): string`, `freeGpus(host: HostRow): number`
  - `interface LostReason { title: string; tooltip: string; parts: string[] }`, `lostReason(record: RunRecord, reason?: string | null): LostReason` (`reason`: the `run.lost` event's reason when the tab saw it, `useLostReason` from Task 4; it comes first in `parts`; without it the words stay neutral)
  - `stateTitle(label: string, phase: RunPhase, record: RunRecord, host: HostRow | null): string | null`
  - `sweepHref(project: string, sweepId: string): string` (re-export from `SweepModel`), `costNote(cost: CostTotals): string`
  - `interface SweepCrumb { id: string; href: string | null; why: string | null }`, `SWEEP_OWNER_CHARS = 8`, `sweepCrumb(record: Pick<RunRecord, "project" | "sweep_id" | "tags">, hubEnvironmentId: string | null): SweepCrumb | null` (the run page's sweep crumb: a link only when the run's owner-qualified tag `sweep:<owner8>:<sweep_id>` names this hub, `owner8` = the first 8 characters of the hub's environment id; a run of another hub's sweep (a shared host) or without the tag gets the id as plain text with `why` for the tooltip; while the hub's id is unknown, plain text and `why` null; null for a run outside a sweep)
- Produces (in `ui/test/pages/remoteFixtures.ts`, used by Tasks 24-27): `NOW`, `GPU1`, `MCCLEARY`, `DGX`, `QUEUED_ID`, `RUNNING_ID`, `STALE_ID`, `LOST_ID`, `PENDING_ID`, `queuedRecord`, `runningRecord`, `staleRecord`, `lostRecord`, `pendingRecord`, `remoteDetail`.

- [ ] **Step 1: Write the shared test fixtures**

Create `ui/test/pages/remoteFixtures.ts`:

```ts
/**
 * Remote run records for the run page tests, matching the phase 2 mockups.
 *
 * Hosts come from `../api/phase2-fixtures` (the hub's `local` row, gpu1 ssh with 3 GPUs and
 * queue 3, mccleary slurm, dgx stale since 14:28:02). Every test runs its clock at `NOW`.
 * As the backend writes them, `host` and `executor.host` are each machine's own hostname
 * (`sv-a100-01`, `dgx-h100-07`, `mccleary-login1`), not the hub's host names; the run page
 * finds the host by `environment_id` (`env-gpu1`, `env-dgx`, `env-mccleary`).
 */
import type { ConnState, ExecutorInfo, HostRow, RunDetail, RunRecord } from "../../src/pages/components/types";
import { COST, HOSTS, REMOTE_EXECUTOR } from "../api/phase2-fixtures";
import { makeDetail, makeRecord } from "./fixtures";

/** 2026-10-03 14:34:00 UTC. */
export const NOW = Date.parse("2026-10-03T14:34:00Z");

function host(name: string): HostRow {
  const row = HOSTS.find((h) => h.name === name);
  if (!row) throw new Error(`no fixture host ${name}`);
  return row;
}

export const GPU1 = host("gpu1");
export const MCCLEARY = host("mccleary");
export const DGX = host("dgx");

export const QUEUED_ID = "20261003-142104-toy-test-f2c8";
export const RUNNING_ID = "20261003-124150-toy-test-c90b";
export const STALE_ID = "20261003-110355-toy-test-a9d3";
export const LOST_ID = "20261003-012210-toy-test-5e9a";
export const PENDING_ID = "20261003-143000-toy-test-77aa";

const NO_EXECUTOR: ExecutorInfo = {
  type: "local",
  pid: null,
  pid_create_time: null,
  child_pid: null,
  host: null,
  gpus: [],
  slurm_job_id: null,
  node: null,
  queue_position: null,
};

const REMOTE_BASE: Partial<RunRecord> = {
  task: null,
  started_at: null,
  ended_at: null,
  exit_code: null,
  artifacts: [],
  tags: [],
  cost: null,
  sweep_id: null,
  gpus_requested: 0,
};

/** gpu1's machine: what the backend writes into `host` and `executor.host` of its runs. */
const ON_GPU1: Partial<RunRecord> = { environment_id: "env-gpu1", host: "sv-a100-01" };
const ON_DGX: Partial<RunRecord> = { environment_id: "env-dgx", host: "dgx-h100-07" };
const ON_MCCLEARY: Partial<RunRecord> = { environment_id: "env-mccleary", host: "mccleary-login1" };

/** Queued 2nd of 3 on gpu1, needs 2 GPUs, waiting since 14:21:04. */
export function queuedRecord(over: Partial<RunRecord> = {}): RunRecord {
  return makeRecord({
    ...REMOTE_BASE,
    ...ON_GPU1,
    run_id: QUEUED_ID,
    hypothesis: "lr 1e-3 with beam 1",
    status: "queued",
    created_at: "2026-10-03T14:21:04Z",
    created_by: "agent:tuner",
    gpus_requested: 2,
    executor: { ...NO_EXECUTOR, host: "sv-a100-01", queue_position: 2 },
    ...over,
  });
}

/** Running on gpu1 GPU 0 since 12:42:00, child pid 2291045. */
export function runningRecord(over: Partial<RunRecord> = {}): RunRecord {
  return makeRecord({
    ...REMOTE_BASE,
    ...ON_GPU1,
    run_id: RUNNING_ID,
    hypothesis: "aug long run seed 1",
    status: "running",
    created_at: "2026-10-03T12:41:50Z",
    started_at: "2026-10-03T12:42:00Z",
    gpus_requested: 1,
    executor: { ...NO_EXECUTOR, pid: 2291040, child_pid: 2291045, host: "sv-a100-01", gpus: [0] },
    ...over,
  });
}

/** Running on dgx GPUs 4 and 5 since 11:04:00; dgx is stale. */
export function staleRecord(over: Partial<RunRecord> = {}): RunRecord {
  return makeRecord({
    ...REMOTE_BASE,
    ...ON_DGX,
    run_id: STALE_ID,
    hypothesis: "lr 1e-3 with beam 10",
    status: "running",
    created_at: "2026-10-03T11:03:55Z",
    started_at: "2026-10-03T11:04:00Z",
    gpus_requested: 2,
    executor: { ...NO_EXECUTOR, pid: 118730, child_pid: 118734, host: "dgx-h100-07", gpus: [4, 5] },
    ...over,
  });
}

/** SLURM job 4471023 on mccleary, lost at 02:14:37, part of sweep s-7f3a, cost $2.17. */
export function lostRecord(over: Partial<RunRecord> = {}): RunRecord {
  return makeRecord({
    ...REMOTE_BASE,
    ...ON_MCCLEARY,
    run_id: LOST_ID,
    hypothesis: "aug long run seed 2",
    status: "lost",
    created_at: "2026-10-03T01:22:10Z",
    started_at: "2026-10-03T01:22:10Z",
    ended_at: "2026-10-03T02:14:37Z",
    gpus_requested: 2,
    cost: COST,
    sweep_id: "s-7f3a",
    executor: { ...REMOTE_EXECUTOR },
    ...over,
  });
}

/** SLURM job 4471031 on mccleary, pending since 14:30:00, needs 2 GPUs. */
export function pendingRecord(over: Partial<RunRecord> = {}): RunRecord {
  return makeRecord({
    ...REMOTE_BASE,
    ...ON_MCCLEARY,
    run_id: PENDING_ID,
    hypothesis: "aug long run seed 3",
    status: "queued",
    created_at: "2026-10-03T14:30:00Z",
    gpus_requested: 2,
    executor: { ...NO_EXECUTOR, type: "slurm", host: "mccleary-login1", slurm_job_id: "4471031" },
    ...over,
  });
}

/** A run detail as the hub returns it, with the host's connection state. */
export function remoteDetail(record: RunRecord, hostState: ConnState | null = "connected"): RunDetail {
  return makeDetail(record, { host_state: hostState, scores: [] });
}
```

- [ ] **Step 2: Write the failing tests**

Create `ui/test/pages/remote.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import {
  costNote,
  fmtWait,
  freeGpus,
  gpuLabel,
  hostLabel,
  lostReason,
  ordinal,
  runHostRow,
  runPhase,
  secondsSince,
  shortGpuName,
  stateTitle,
  sweepCrumb,
  sweepHref,
  visibleDevices,
} from "../../src/pages/components/remote";
import type { HostRow } from "../../src/pages/components/types";
import { COST, HOSTS } from "../api/phase2-fixtures";
import { makeDetail, makeRecord } from "./fixtures";
import {
  DGX,
  GPU1,
  MCCLEARY,
  NOW,
  lostRecord,
  pendingRecord,
  queuedRecord,
  remoteDetail,
  runningRecord,
  staleRecord,
} from "./remoteFixtures";

describe("runPhase", () => {
  test("hub runs keep the phase 1 layout; remote runs get a phase", () => {
    expect(runPhase(makeDetail())).toBe("local");
    expect(runPhase(makeDetail({ status: "queued" }))).toBe("local");
    expect(runPhase(remoteDetail(queuedRecord()))).toBe("queued");
    expect(runPhase(remoteDetail(pendingRecord()))).toBe("pending");
    expect(runPhase(remoteDetail(runningRecord()))).toBe("running");
    expect(runPhase(remoteDetail(lostRecord()))).toBe("lost");
    expect(runPhase(remoteDetail(runningRecord({ status: "finished" })))).toBe("ended");
  });

  test("an active run on a host the hub cannot reach is stale, never lost", () => {
    expect(runPhase(remoteDetail(staleRecord(), "stale"))).toBe("stale");
    expect(runPhase(remoteDetail(staleRecord(), "error"))).toBe("stale");
    expect(runPhase(remoteDetail(staleRecord(), "disabled"))).toBe("stale");
    expect(runPhase(remoteDetail(queuedRecord(), "connecting"))).toBe("stale");
    // a finished run stays finished on a stale host
    expect(runPhase(remoteDetail(staleRecord({ status: "finished" }), "stale"))).toBe("ended");
    // the env server decided lost: lost wins even on a hub run
    expect(runPhase(makeDetail({ status: "lost" }))).toBe("lost");
  });

  test("host_state null is a hub run, although the backend sets executor.host on every run", () => {
    const hubRun = makeRecord({ status: "running", executor: { ...makeRecord().executor, host: "mbp.local" } });
    expect(runPhase(makeDetail(hubRun, { host_state: null }))).toBe("local");
    expect(runPhase(remoteDetail(runningRecord(), null))).toBe("local");
  });
});

test("runHostRow matches the run's environment, never executor.host", () => {
  const queued = queuedRecord();
  expect(queued.executor.host).toBe("sv-a100-01");
  expect(runHostRow(remoteDetail(queued), HOSTS)).toBe(GPU1);
  expect(runHostRow(remoteDetail(staleRecord(), "stale"), HOSTS)).toBe(DGX);
  expect(runHostRow(remoteDetail(queued), undefined)).toBeNull();
  expect(runHostRow(remoteDetail(queuedRecord({ environment_id: "env-gone" })), HOSTS)).toBeNull();
  // a hub run has no host row, even though its environment is the hub's `local` row
  expect(runHostRow(makeDetail({ environment_id: "env-hub" }, { host_state: null }), HOSTS)).toBeNull();
  expect(hostLabel(queued, GPU1)).toBe("gpu1");
  expect(hostLabel(queued, null)).toBe("sv-a100-01");
});

test("ordinal uses st, nd, rd, except for 11 to 13", () => {
  expect([1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 101, 111, 112].map(ordinal)).toEqual([
    "1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "23rd", "101st", "111th", "112th",
  ]);
});

test("fmtWait shows seconds, then minutes, then hours and minutes", () => {
  expect([-5, 0, 59.9, 60, 3599, 3600, 6720].map(fmtWait)).toEqual([
    "0s", "0s", "59s", "1m", "59m", "1h 0m", "1h 52m",
  ]);
  expect(secondsSince("2026-10-03T14:21:04Z", NOW)).toBe(776);
  expect(secondsSince("2026-10-03T15:00:00Z", NOW)).toBe(0);
  expect(secondsSince("not a time", NOW)).toBeNull();
});

test("GPU texts: devices, model names, free count", () => {
  expect(visibleDevices([0, 1])).toBe("CUDA_VISIBLE_DEVICES=0,1");
  expect(shortGpuName("NVIDIA A100 80GB PCIe")).toBe("A100 80GB PCIe");
  expect(shortGpuName("H100")).toBe("H100");
  expect(gpuLabel(2, GPU1)).toBe("2× A100 80GB PCIe");
  expect(gpuLabel(1, GPU1, [0])).toBe("1× A100 80GB PCIe");
  expect(gpuLabel(2, MCCLEARY, [0, 1])).toBe("2 GPU");
  expect(gpuLabel(2, null)).toBe("2 GPU");
  const mixed: HostRow = {
    ...GPU1,
    gpus: GPU1.gpus.map((g) => (g.index === 1 ? { ...g, name: "NVIDIA H100" } : g)),
  };
  expect(gpuLabel(2, mixed, [0, 1])).toBe("2 GPU");
  expect(gpuLabel(1, mixed, [1])).toBe("1× H100");
  expect(freeGpus(GPU1)).toBe(1);
  expect(freeGpus(DGX)).toBe(0);
});

describe("stateTitle", () => {
  test("names the state after the label", () => {
    expect(stateTitle("lr 1e-3", "queued", queuedRecord(), GPU1)).toBe("lr 1e-3: queued 2nd on gpu1");
    expect(stateTitle("seed 3", "pending", pendingRecord(), MCCLEARY)).toBe("seed 3: pending on mccleary");
    expect(stateTitle("beam 10", "stale", staleRecord(), DGX)).toBe("beam 10: stale since 14:28");
    expect(stateTitle("seed 2", "lost", lostRecord(), MCCLEARY)).toBe("seed 2: lost at 02:14");
    expect(stateTitle("seed 2", "lost", lostRecord({ ended_at: null }), null)).toBe("seed 2: lost");
  });

  test("running, ended and hub runs keep their title", () => {
    expect(stateTitle("x", "running", runningRecord(), GPU1)).toBeNull();
    expect(stateTitle("x", "ended", runningRecord({ status: "finished" }), GPU1)).toBeNull();
    expect(stateTitle("x", "local", makeRecord(), null)).toBeNull();
  });

  test("without the hosts list or a queue position", () => {
    // no hosts list: the machine's own hostname, never a guess at the hub's name
    expect(stateTitle("beam 10", "stale", staleRecord(), null)).toBe("beam 10: dgx-h100-07 unreachable");
    expect(stateTitle("lr 1e-3", "queued", queuedRecord(), null)).toBe("lr 1e-3: queued 2nd on sv-a100-01");
    const unplaced = queuedRecord({ executor: { ...queuedRecord().executor, queue_position: null } });
    expect(stateTitle("lr 1e-3", "queued", unplaced, GPU1)).toBe("lr 1e-3: queued on gpu1");
  });
});

test("lostReason names what the record says, in neutral words, never a guessed cause", () => {
  // a SLURM job can be lost to NODE_FAIL while still in sacct: no "left squeue and sacct"
  expect(lostReason(lostRecord())).toEqual({
    title: "SLURM job 4471023 lost",
    tooltip: "The env server marked this run lost. Its run.lost event has the reason.",
    parts: ["r814u05n01", "02:14:37 UTC", "no exit code"],
  });
  const local = makeRecord({ status: "lost", ended_at: "2026-10-03T09:00:05Z", exit_code: null });
  expect(lostReason(local)).toEqual({
    title: "run lost",
    tooltip: "The env server marked this run lost. Its run.lost event has the reason.",
    parts: ["09:00:05 UTC", "no exit code"],
  });
  expect(lostReason(makeRecord({ status: "lost", ended_at: null, exit_code: 137 })).parts).toEqual(["exit 137"]);
});

test("lostReason shows the env server's run.lost reason first when it is known", () => {
  const why = "SLURM ended job 4471023 with NODE_FAIL on r814u05n01; no exit record";
  expect(lostReason(lostRecord(), why)).toEqual({
    title: "SLURM job 4471023 lost",
    tooltip: "Reason from the run's run.lost event.",
    parts: [why, "r814u05n01", "02:14:37 UTC", "no exit code"],
  });
  // a blank or missing reason keeps the neutral words
  expect(lostReason(lostRecord(), "  ")).toEqual(lostReason(lostRecord()));
  expect(lostReason(lostRecord(), null)).toEqual(lostReason(lostRecord()));
});

test("sweepHref encodes; costNote shows GPU hours and API dollars", () => {
  expect(sweepHref("my proj", "s-7f3a")).toBe("/s/my%20proj/s-7f3a");
  expect(costNote(COST)).toBe("3.50 GPU h, API $0.42");
});

test("sweepCrumb links only a sweep this hub owns (its owner-qualified tag)", () => {
  const hub = "0a1b2c3d4e5f60718293a4b5c6d7e8f9";
  const mine = lostRecord({ tags: ["best", "sweep:0a1b2c3d:s-7f3a"] });
  expect(sweepCrumb(mine, hub)).toEqual({ id: "s-7f3a", href: "/s/toy-classifier/s-7f3a", why: null });
  // a shared host: another hub launched this sweep, so this hub has no page for it
  expect(sweepCrumb(lostRecord({ tags: ["sweep:ffffffff:s-7f3a"] }), hub)).toEqual({
    id: "s-7f3a",
    href: null,
    why: "sweep of another hub (ffffffff)",
  });
  // only the tag of the run's own sweep id counts; none at all is plain text too
  const other = { id: "s-7f3a", href: null, why: "no sweep tag on this run" };
  expect(sweepCrumb(lostRecord({ tags: ["sweep:0a1b2c3d:s-0000"] }), hub)).toEqual(other);
  expect(sweepCrumb(lostRecord({ tags: [] }), hub)).toEqual(other);
  // the hub's id not known yet (descriptor loading or failed): plain text, no reason
  expect(sweepCrumb(mine, null)).toEqual({ id: "s-7f3a", href: null, why: null });
  expect(sweepCrumb(runningRecord(), hub)).toBeNull();
});
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `bun test test/pages/remote.test.ts`
Expected: FAIL with `error: Cannot find module '../../src/pages/components/remote'` (0 pass).

- [ ] **Step 4: Write the module**

Create `ui/src/pages/components/remote.ts`:

```ts
/**
 * Remote run state for the run page (spec 5.6, 8A.5, 8A.8): the phase a run is shown in,
 * the hosts row that serves it, and the short texts each phase needs. Pure functions; the
 * page does the fetching. A run is remote when its detail has a `host_state`; its host is
 * found by `environment_id`, never by `executor.host` (the backend writes the machine's own
 * hostname there, on every run).
 */
import { fmtClock, fmtTime, fmtUsd, parseTime } from "./format";
import { hostRowForRun } from "./HostsPanel";
import { sweepHref } from "./SweepModel";
import type { CostTotals, GpuInfo, HostRow, RunDetail, RunRecord } from "./types";

/**
 * How the run page shows a run.
 *
 * `local`: a hub run (the phase 1b layout). `queued`: waiting in an SSH host's hx queue.
 * `pending`: submitted to SLURM, not started. `running`: running on a host that answers.
 * `stale`: queued or running on a host the hub cannot reach now (derived, never stored).
 * `lost`: the env server gave the run up. `ended`: a finished, failed or killed remote run.
 */
export type RunPhase = "local" | "queued" | "pending" | "running" | "stale" | "lost" | "ended";

/**
 * The phase of a run. `host_state` null (or missing, on a phase 1 server) is a hub run: the
 * backend sets it only for runs of a host's environment. `executor.host` says nothing here,
 * since the backend fills it on every run, hub runs too.
 */
export function runPhase(detail: RunDetail): RunPhase {
  const record = detail.record;
  if (record.status === "lost") return "lost";
  const conn = detail.host_state ?? null;
  if (conn === null) return "local";
  const active = record.status === "queued" || record.status === "running";
  if (active && conn !== "connected") return "stale";
  if (record.status === "queued") return record.executor.slurm_job_id ? "pending" : "queued";
  if (record.status === "running") return "running";
  return "ended";
}

/**
 * The `GET /api/v1/hosts` row of a remote run's host (`hostRowForRun`: matched by
 * `environment_id`); null for a hub run, or while the hosts list is not loaded or failed.
 */
export function runHostRow(detail: RunDetail, hosts: readonly HostRow[] | undefined): HostRow | null {
  if ((detail.host_state ?? null) === null) return null;
  return hostRowForRun(detail.record, hosts);
}

/**
 * How texts name a remote run's host: the hub's name for it (`host.name`), else, without the
 * hosts list, the machine's own hostname (`record.host`). Only for display: Reconnect needs
 * `host.name`.
 */
export function hostLabel(record: RunRecord, host: HostRow | null): string {
  return host?.name ?? record.host;
}

const SUFFIX: Record<number, string> = { 1: "st", 2: "nd", 3: "rd" };

/** `1st`, `2nd`, `3rd`, `4th`, `11th`, `21st`. */
export function ordinal(n: number): string {
  const tens = n % 100;
  if (tens >= 11 && tens <= 13) return `${n}th`;
  return `${n}${SUFFIX[n % 10] ?? "th"}`;
}

/** A waiting time, `45s`, `12m`, `1h 52m`: the sweep page's age format. */
export { fmtAge as fmtWait } from "./SweepModel";

/** Seconds from `iso` to `now` (0 for a future time); null for an unreadable time. */
export function secondsSince(iso: string, now: number): number | null {
  const t = parseTime(iso);
  return Number.isNaN(t) ? null : Math.max(0, (now - t) / 1000);
}

/** `CUDA_VISIBLE_DEVICES=0,1`. */
export function visibleDevices(gpus: readonly number[]): string {
  return `CUDA_VISIBLE_DEVICES=${gpus.join(",")}`;
}

/** `NVIDIA A100 80GB PCIe` → `A100 80GB PCIe`. */
export function shortGpuName(name: string): string {
  return name.replace(/^NVIDIA\s+/, "");
}

/**
 * `2× A100 80GB PCIe` when the GPUs (the given indices, else all of the host's) share one
 * model; `2 GPU` when the models differ or are unknown.
 */
export function gpuLabel(count: number, host: HostRow | null, indices: readonly number[] = []): string {
  const pool: GpuInfo[] = host?.gpus ?? [];
  const picked = indices.length > 0 ? pool.filter((g) => indices.includes(g.index)) : pool;
  const names = new Set(picked.map((g) => g.name));
  const [only] = names;
  return names.size === 1 && only ? `${count}× ${shortGpuName(only)}` : `${count} GPU`;
}

/** GPUs no hx run holds and no outside process uses (spec 8A.5). */
export function freeGpus(host: HostRow): number {
  return host.gpus.filter((g) => g.run_id === null && !g.external).length;
}

export interface LostReason {
  title: string;
  tooltip: string;
  parts: string[];
}

/** Where the cause of a lost run is when this tab has not seen it: in its `run.lost` event. */
const LOST_TIP = "The env server marked this run lost. Its run.lost event has the reason.";
/** The tooltip when the reason shown came from that event. */
const REASON_TIP = "Reason from the run's run.lost event.";

/**
 * What a lost run's record says: the SLURM job, the node, when, and the exit code. The env
 * server's own reason (`SLURM ended job 4471023 with NODE_FAIL on r814u05n01; no exit
 * record`) is in the `run.lost` event, not in the run detail: pass it as `reason` when the
 * tab saw that event (`useLostReason`), and it comes first. Without it the words stay
 * neutral: a job lost to `NODE_FAIL` is still in `sacct`, and a dead supervisor is only one
 * of the causes, so neither is guessed here.
 */
export function lostReason(record: RunRecord, reason: string | null = null): LostReason {
  const ex = record.executor;
  const parts: string[] = [];
  if (ex.node) parts.push(ex.node);
  if (record.ended_at) parts.push(fmtTime(record.ended_at));
  parts.push(record.exit_code === null ? "no exit code" : `exit ${record.exit_code}`);
  const title = ex.slurm_job_id ? `SLURM job ${ex.slurm_job_id} lost` : "run lost";
  const why = reason?.trim() ?? "";
  return why === "" ? { title, tooltip: LOST_TIP, parts } : { title, tooltip: REASON_TIP, parts: [why, ...parts] };
}

/**
 * The page title for a queued, pending, stale or lost run (`<label>: queued 2nd on gpu1`);
 * null when the run keeps its hypothesis as the title.
 */
export function stateTitle(label: string, phase: RunPhase, record: RunRecord, host: HostRow | null): string | null {
  const name = hostLabel(record, host);
  switch (phase) {
    case "queued": {
      const pos = record.executor.queue_position ?? null;
      return pos === null ? `${label}: queued on ${name}` : `${label}: queued ${ordinal(pos)} on ${name}`;
    }
    case "pending":
      return `${label}: pending on ${name}`;
    case "stale":
      return host ? `${label}: stale since ${fmtClock(host.state.since)}` : `${label}: ${name} unreachable`;
    case "lost":
      return record.ended_at ? `${label}: lost at ${fmtClock(record.ended_at)}` : `${label}: lost`;
    default:
      return null;
  }
}

/** The sweep page of a run's sweep (contract 4, route `/s/:project/:id`). */
export { sweepHref } from "./SweepModel";

/** `3.50 GPU h, API $0.42`: what a cost is made of. */
export function costNote(cost: CostTotals): string {
  return `${cost.gpu_hours.toFixed(2)} GPU h, API ${fmtUsd(cost.api_usd)}`;
}

/** Characters of the hub's environment id a sweep tag names (the backend's `SWEEP_OWNER_CHARS`). */
export const SWEEP_OWNER_CHARS = 8;
const OWNED_SWEEP_TAG = /^sweep:([^:]+):(.+)$/;

/** The run page's sweep crumb. */
export interface SweepCrumb {
  id: string;
  /** `/s/<project>/<id>` when this hub owns the sweep; null: plain text. */
  href: string | null;
  /** Why there is no link (the tooltip); null with a link or while the hub's id is unknown. */
  why: string | null;
}

/**
 * The crumb for a run's sweep. Sweep ids are per hub, and one host can serve two hubs, so
 * the link is made only when the run's owner-qualified tag `sweep:<owner8>:<sweep_id>`
 * names this hub (`owner8`: the first 8 characters of its environment id). A run of another
 * hub's sweep, or one without that tag, shows the id as plain text: this hub has no such
 * sweep page, or a different sweep under the same id.
 */
export function sweepCrumb(
  record: Pick<RunRecord, "project" | "sweep_id" | "tags">,
  hubEnvironmentId: string | null,
): SweepCrumb | null {
  const id = record.sweep_id;
  if (!id) return null;
  if (hubEnvironmentId === null) return { id, href: null, why: null };
  let owner: string | null = null;
  for (const tag of record.tags) {
    const m = OWNED_SWEEP_TAG.exec(tag);
    if (m && m[2] === id) {
      owner = m[1] ?? null;
      break;
    }
  }
  if (owner === null) return { id, href: null, why: "no sweep tag on this run" };
  if (owner !== hubEnvironmentId.slice(0, SWEEP_OWNER_CHARS)) {
    return { id, href: null, why: `sweep of another hub (${owner})` };
  }
  return { id, href: sweepHref(record.project, id), why: null };
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `bun test test/pages/remote.test.ts && bun run typecheck`
Expected: `14 pass`, `0 fail`; `tsc --noEmit` prints nothing.

- [ ] **Step 6: Commit (repo root)**

```bash
git add ui/src/pages/components/remote.ts ui/test/pages/remoteFixtures.ts ui/test/pages/remote.test.ts
git commit -m "feat(ui): derive remote run phase and its texts"
```

---

### Task 24: Stat strip for remote runs, run cost, and leaderboard cost

**Files:**
- Create: `ui/src/pages/components/remoteStats.ts`
- Modify: `ui/src/pages/components/runStats.ts` (the `usage` block at the end)
- Modify: `ui/src/panels/Leaderboard.tsx` (the models import; `fmtDuration`; the `usage` span in the row meta)
- Test: `ui/test/pages/remoteStats.test.ts`, `ui/test/panels/Leaderboard.test.tsx` (imports; one new test)

**Interfaces:**
- Consumes: `RunPhase`, `hostLabel`, `fmtWait`, `freeGpus`, `secondsSince`, `costNote` (Task 23); `StatItem` from `./StatStrip` (exists); `runSeconds`, `fmtUsd` from `./format` (exist); fixtures from Task 23.
- Produces:
  - `remoteStats(record: RunRecord, phase: RunPhase, host: HostRow | null, now?: number): StatItem[]` — queued: `position` (`2` `/ 3`), `needs` (`2` `GPU`), `free on <host>` (`1` `/ 3`), `waiting`; pending: `needs`, `job`, `waiting`; running: `GPU` (`%`), `mem` (`GB`), `GPU h` (until the cost is set); stale: `GPU h`, `unreachable`; others: none.
  - `runStats(...)` (existing signature) now adds `cost` from `record.cost.total_usd` (tooltip `costNote`) and shows the usage-only cost only when the record has no `cost`.
  - In `ui/src/panels/Leaderboard.tsx` (spec 8A.7, contract section 2: leaderboard rows add `cost`, the sum over the group's runs): `costText(cost: CostTotals, usage: UsageTotals | null): string` (`$6.51 · 11 GPU-h · 4m 10s`: dollars, GPU hours when any, agent time when any) and `costTitle(cost: CostTotals, usage: UsageTotals | null): string` (`GPU $5.25 + API $1.26 over the group's runs, 10.50 GPU h`, then the usage calls and tokens). A row with a `cost` shows it in its meta line (`span.cost`) instead of the usage dollars, so API dollars are never counted twice; a row without one (a phase 1 server) keeps the phase 1b usage span.

- [ ] **Step 1: Write the failing tests**

Create `ui/test/pages/remoteStats.test.ts`:

```ts
import { expect, test } from "bun:test";
import { remoteStats } from "../../src/pages/components/remoteStats";
import { runStats } from "../../src/pages/components/runStats";
import type { StatItem } from "../../src/pages/components/StatStrip";
import { COST } from "../api/phase2-fixtures";
import { makeDetail, makeRecord } from "./fixtures";
import {
  DGX,
  GPU1,
  MCCLEARY,
  NOW,
  lostRecord,
  pendingRecord,
  queuedRecord,
  runningRecord,
  staleRecord,
} from "./remoteFixtures";

const show = (items: StatItem[]) => items.map((s) => [s.label, s.value, s.unit ?? null]);

test("remoteStats for a queued run: position, needs, free GPUs, waiting", () => {
  expect(show(remoteStats(queuedRecord(), "queued", GPU1, NOW))).toEqual([
    ["position", "2", "/ 3"],
    ["needs", "2", "GPU"],
    ["free on gpu1", "1", "/ 3"],
    ["waiting", "12m", null],
  ]);
});

test("remoteStats without the hosts list", () => {
  expect(show(remoteStats(queuedRecord(), "queued", null, NOW))).toEqual([
    ["position", "2", null],
    ["needs", "2", "GPU"],
    ["waiting", "12m", null],
  ]);
  expect(show(remoteStats(staleRecord(), "stale", null, NOW))).toEqual([["GPU h", "7.00", null]]);
});

test("remoteStats for a SLURM job still pending", () => {
  expect(show(remoteStats(pendingRecord(), "pending", MCCLEARY, NOW))).toEqual([
    ["needs", "2", "GPU"],
    ["job", "4471031", null],
    ["waiting", "4m", null],
  ]);
});

test("remoteStats for a running run: GPU use, memory, GPU hours so far", () => {
  const items = remoteStats(runningRecord(), "running", GPU1, NOW);
  expect(show(items)).toEqual([
    ["GPU", "92", "%"],
    ["mem", "57", "GB"],
    ["GPU h", "1.87", null],
  ]);
  expect(items[0]?.tooltip).toBe("mean utilization of GPU 0");
  // once the cost is set it is the run's own number; GPU hours are in its tooltip
  expect(show(remoteStats(runningRecord({ cost: COST }), "running", GPU1, NOW))).toEqual([
    ["GPU", "92", "%"],
    ["mem", "57", "GB"],
  ]);
});

test("remoteStats for a stale run: GPU hours and how long the host is gone", () => {
  expect(show(remoteStats(staleRecord(), "stale", DGX, NOW))).toEqual([
    ["GPU h", "7.00", null],
    ["unreachable", "5m", null],
  ]);
});

test("remoteStats is empty for hub and ended runs", () => {
  expect(remoteStats(makeRecord(), "local", null, NOW)).toEqual([]);
  expect(remoteStats(lostRecord(), "lost", MCCLEARY, NOW)).toEqual([]);
  expect(remoteStats(runningRecord({ status: "finished" }), "ended", GPU1, NOW)).toEqual([]);
});

test("host clock ahead of the hub: GPU hours and waiting read 0, never negative", () => {
  // the host stamped started_at / created_at 10 minutes after the hub's now
  const started = runningRecord({ started_at: "2026-10-03T14:44:00Z" });
  expect(show(remoteStats(started, "running", GPU1, NOW))).toEqual([
    ["GPU", "92", "%"],
    ["mem", "57", "GB"],
    ["GPU h", "0.00", null],
  ]);
  const queued = queuedRecord({ created_at: "2026-10-03T14:44:00Z" });
  expect(show(remoteStats(queued, "queued", GPU1, NOW)).at(-1)).toEqual(["waiting", "0s", null]);
});

test("runStats shows the run's cost once, with what it is made of in the tooltip", () => {
  const usage = { tokens_in: 153000, tokens_out: 4500, usd: 0.25, seconds: 68.4, calls: 13 };
  const both = runStats(makeDetail({ usage, cost: COST }), null, null);
  expect(both.map((s) => [s.label, s.value])).toEqual([
    ["wall", "0.8 s"],
    ["tokens in", "153k"],
    ["tokens out", "4.5k"],
    ["cost", "$2.17"],
  ]);
  expect(both.find((s) => s.label === "cost")?.tooltip).toBe("3.50 GPU h, API $0.42");
  const lost = runStats(makeDetail(lostRecord()), null, null, NOW);
  expect(lost.map((s) => [s.label, s.value])).toEqual([
    ["wall", "52m 27s"],
    ["cost", "$2.17"],
  ]);
  // no cost on the record: the usage cost, as in phase 1b
  const old = runStats(makeDetail({ usage }), null, null);
  expect(old.find((s) => s.label === "cost")).toEqual({ label: "cost", value: "$0.25", tooltip: "13 calls" });
});
```

In `ui/test/panels/Leaderboard.test.tsx`, replace

```tsx
import {
  Leaderboard,
  bestBand,
  examplesHref,
  fmtDuration,
```

with

```tsx
import {
  Leaderboard,
  bestBand,
  costText,
  costTitle,
  examplesHref,
  fmtDuration,
```

and add this test at the end of `describe("Leaderboard panel", ...)`, after the test `single seed, missing primary, usage, and the empty state`:

```tsx
  test("a group's cost: dollars, GPU hours and agent time; the parts in the tooltip", () => {
    const cost = { gpu_hours: 10.5, gpu_usd: 5.25, api_usd: 1.26, total_usd: 6.51 };
    const usage = { tokens_in: 1000, tokens_out: 200, usd: 1.26, seconds: 250, calls: 7 };
    expect(costText(cost, usage)).toBe("$6.51 · 11 GPU-h · 4m 10s");
    expect(costText({ ...cost, gpu_hours: 2.25 }, null)).toBe("$6.51 · 2.3 GPU-h");
    expect(costText({ gpu_hours: 0, gpu_usd: 0, api_usd: 1.26, total_usd: 1.26 }, null)).toBe("$1.26");
    expect(costTitle(cost, usage)).toBe(
      "GPU $5.25 + API $1.26 over the group's runs, 10.50 GPU h\n7 calls, 1000 tokens in, 200 out",
    );
    const priced = row({
      group_id: "c1@c1",
      label: "priced",
      scores: { "accuracy/value": stat(0.9, 0, 1) },
      primary: stat(0.9, 0, 1),
      usage,
      cost,
    });
    const free = row({ group_id: "c2@c2", label: "no cost field", usage });
    const { container } = render(<Leaderboard result={board({}, [priced, free])} />);
    const rows = [...container.querySelectorAll<HTMLElement>(".frow[data-row]")];
    const span = rows[0]?.querySelector(".meta .cost");
    expect([span?.textContent, span?.getAttribute("title")]).toEqual([
      "$6.51 · 11 GPU-h · 4m 10s",
      "GPU $5.25 + API $1.26 over the group's runs, 10.50 GPU h\n7 calls, 1000 tokens in, 200 out",
    ]);
    // the usage dollars are part of the cost: never shown twice
    expect(rows[0]?.querySelector(".meta")?.textContent).not.toContain("$1.26 ·");
    // a phase 1 server sends no cost: the usage span as before
    expect(rows[1]?.querySelector(".meta .cost")).toBeNull();
    expect(within(rows[1] as HTMLElement).getByTitle("7 calls, 1000 tokens in, 200 out").textContent).toBe(
      "$1.26 · 4m 10s",
    );
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bun test test/pages/remoteStats.test.ts test/panels/Leaderboard.test.tsx`
Expected: FAIL with `error: Cannot find module '../../src/pages/components/remoteStats'`; in `Leaderboard.test.tsx` the file does not load (`SyntaxError: Export named 'costTitle' not found in module`; bun names one of the two missing exports).

- [ ] **Step 3: Write `remoteStats.ts`**

Create `ui/src/pages/components/remoteStats.ts`:

```ts
/**
 * Stat strip items for a remote run (spec 8A.5, 8A.7, mockups shot-run-*): queue place and
 * GPU need while it waits, GPU use while it runs, how long its host is gone when stale.
 */
import { runSeconds } from "./format";
import { fmtWait, freeGpus, hostLabel, type RunPhase, secondsSince } from "./remote";
import type { StatItem } from "./StatStrip";
import type { HostRow, RunRecord } from "./types";

/** `host` is the run's hosts row (`runHostRow`), or null without the hosts list. */
export function remoteStats(
  record: RunRecord,
  phase: RunPhase,
  host: HostRow | null,
  now: number = Date.now(),
): StatItem[] {
  const name = hostLabel(record, host);
  const ex = record.executor;
  const gpus = ex.gpus ?? [];
  const out: StatItem[] = [];
  if (phase === "queued" || phase === "pending") {
    const pos = ex.queue_position ?? null;
    if (phase === "queued" && pos !== null) {
      out.push({
        label: "position",
        value: String(pos),
        unit: host ? `/ ${host.queue}` : null,
        tooltip: `place in the ${name} queue`,
      });
    }
    out.push({
      label: "needs",
      value: String(record.gpus_requested ?? 0),
      unit: "GPU",
      tooltip: "GPUs this run needs on one host",
    });
    if (phase === "queued" && host && host.gpus.length > 0) {
      out.push({
        label: `free on ${name}`,
        value: String(freeGpus(host)),
        unit: `/ ${host.gpus.length}`,
        tooltip: `GPUs on ${name} no run or outside process uses`,
      });
    }
    if (phase === "pending" && ex.slurm_job_id) {
      out.push({ label: "job", value: ex.slurm_job_id, tooltip: "SLURM job id" });
    }
    const waited = secondsSince(record.created_at, now);
    if (waited !== null) {
      out.push({ label: "waiting", value: fmtWait(waited), tooltip: `queued at ${record.created_at}` });
    }
    return out;
  }
  if (phase === "running" && host && gpus.length > 0) {
    const held = host.gpus.filter((g) => gpus.includes(g.index));
    if (held.length > 0) {
      const util = held.reduce((sum, g) => sum + g.util, 0) / held.length;
      const mem = held.reduce((sum, g) => sum + g.mem_used_mb, 0) / 1024;
      out.push({
        label: "GPU",
        value: String(Math.round(util)),
        unit: "%",
        tooltip: `mean utilization of GPU ${gpus.join(", ")}`,
      });
      out.push({ label: "mem", value: String(Math.round(mem)), unit: "GB", tooltip: "GPU memory in use" });
    }
  }
  if ((phase === "running" || phase === "stale") && gpus.length > 0 && !record.cost) {
    const wall = runSeconds(record, now);
    if (wall !== null) {
      out.push({
        label: "GPU h",
        value: ((wall * gpus.length) / 3600).toFixed(2),
        tooltip: `wall × ${gpus.length} GPU; the cost is set when the run ends`,
      });
    }
  }
  if (phase === "stale" && host) {
    const gone = secondsSince(host.state.since, now);
    if (gone !== null) {
      out.push({
        label: "unreachable",
        value: fmtWait(gone),
        tooltip: `no answer from ${name} since ${host.state.since}`,
      });
    }
  }
  return out;
}
```

- [ ] **Step 4: Show the run's cost in `runStats`**

In `ui/src/pages/components/runStats.ts`, add `import { costNote } from "./remote";` after the `./format` import, and replace

```ts
  const usage = record.usage;
  if (usage) {
    out.push({ label: "tokens in", value: fmtCount(usage.tokens_in) });
    out.push({ label: "tokens out", value: fmtCount(usage.tokens_out) });
    out.push({ label: "cost", value: fmtUsd(usage.usd), tooltip: `${usage.calls} calls` });
  }
```

with

```ts
  const usage = record.usage;
  const cost = record.cost ?? null;
  if (usage) {
    out.push({ label: "tokens in", value: fmtCount(usage.tokens_in) });
    out.push({ label: "tokens out", value: fmtCount(usage.tokens_out) });
    if (!cost) out.push({ label: "cost", value: fmtUsd(usage.usd), tooltip: `${usage.calls} calls` });
  }
  // spec 8A.7: GPU hours × rate + API dollars, set when the run ends
  if (cost) out.push({ label: "cost", value: fmtUsd(cost.total_usd), tooltip: costNote(cost) });
```

- [ ] **Step 5: Show each group's cost on the leaderboard**

In `ui/src/panels/Leaderboard.tsx`, replace

```tsx
import type { LeaderboardRow, NoiseInterval, Stats, UsageTotals, VersusBest } from "../api/models";
```

with

```tsx
import type { CostTotals, LeaderboardRow, NoiseInterval, Stats, UsageTotals, VersusBest } from "../api/models";
```

Directly after the `fmtDuration` function (above `bestBand`), insert:

```tsx

/** GPU hours: one decimal below 10, whole from 10. */
function fmtGpuHours(hours: number): string {
  return hours < 10 ? hours.toFixed(1) : hours.toFixed(0);
}

/**
 * A group's cost in its meta line (spec 8A.7): `$6.51 · 11 GPU-h · 4m 10s`. Dollars always;
 * GPU hours and agent time only when there are any.
 */
export function costText(cost: CostTotals, usage: UsageTotals | null): string {
  const parts = [`$${cost.total_usd.toFixed(2)}`];
  if (cost.gpu_hours > 0) parts.push(`${fmtGpuHours(cost.gpu_hours)} GPU-h`);
  if (usage && usage.seconds > 0) parts.push(fmtDuration(usage.seconds));
  return parts.join(" · ");
}

/** What the cost is made of, then the usage calls and tokens. */
export function costTitle(cost: CostTotals, usage: UsageTotals | null): string {
  const head =
    `GPU $${cost.gpu_usd.toFixed(2)} + API $${cost.api_usd.toFixed(2)} over the group's runs, ` +
    `${cost.gpu_hours.toFixed(2)} GPU h`;
  return usage ? `${head}\n${usage.calls} calls, ${usage.tokens_in} tokens in, ${usage.tokens_out} out` : head;
}
```

Replace

```tsx
          const u = row.usage;
```

with

```tsx
          const u = row.usage;
          const c = row.cost ?? null;
```

and replace

```tsx
                  {u && (u.usd > 0 || u.seconds > 0) ? (
                    <span title={`${u.calls} calls, ${u.tokens_in} tokens in, ${u.tokens_out} out`}>
                      ${u.usd.toFixed(2)} · {fmtDuration(u.seconds)}
                    </span>
                  ) : null}
```

with

```tsx
                  {c && (c.total_usd > 0 || c.gpu_hours > 0) ? (
                    <span className="cost" title={costTitle(c, u)}>
                      {costText(c, u)}
                    </span>
                  ) : u && (u.usd > 0 || u.seconds > 0) ? (
                    <span title={`${u.calls} calls, ${u.tokens_in} tokens in, ${u.tokens_out} out`}>
                      ${u.usd.toFixed(2)} · {fmtDuration(u.seconds)}
                    </span>
                  ) : null}
```

(`LeaderboardRowJson` is `Omit<LeaderboardRow, ...>`, so it has the optional `cost` from Task 1, and the phase 1b fixtures without it still type-check.)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `bun test test/pages/remoteStats.test.ts test/pages/runSummary.test.tsx test/panels/Leaderboard.test.tsx && bun run typecheck`
Expected: `remoteStats.test.ts` 8 pass; `Leaderboard.test.tsx` passes with one more test than before; `runSummary.test.tsx` passes unchanged; `0 fail`; `tsc --noEmit` prints nothing.

- [ ] **Step 7: Commit (repo root)**

```bash
git add ui/src/pages/components/remoteStats.ts ui/src/pages/components/runStats.ts ui/src/panels/Leaderboard.tsx ui/test/pages/remoteStats.test.ts ui/test/panels/Leaderboard.test.tsx
git commit -m "feat(ui): remote run stats; run cost; each leaderboard group's cost"
```

---

### Task 25: Placement, queue, status line, and state bar

**Files:**
- Create: `ui/src/pages/components/Placement.tsx`
- Create: `ui/src/pages/components/QueuePanel.tsx`
- Create: `ui/src/pages/components/StateBanner.tsx`
- Create: `ui/src/pages/components/remoteStyles.ts`
- Modify: `ui/src/pages/components/StatusLine.tsx` (whole file)
- Test: `ui/test/pages/remoteParts.test.tsx`

**Interfaces:**
- Consumes: Task 23 helpers; `CopyButton` (exists, `aria-label="Copy <label>"`); `AppLink`, `hrefs` (exist); `firstClause`, `shortId`, `isAgent`, `fmtClock`, `fmtTime`, `fmtUsd`, `fmtDuration`, `runSeconds`, `DASH` from `./format` (exist); `renderWithClient`, `mockClipboard` from `ui/test/pages/helpers.tsx` (exist).
- Produces:
  - `interface PlaceRow { key: string; value: string; note?: string; copy?: string; mono?: boolean }`; `placementRows(record, phase, host): PlaceRow[]`; `Placement({ rows }: { rows: PlaceRow[] })`.
  - `queuedRunsQuery(environmentId: string): Omit<RunsQuery, "limit">` (`{ status: "queued", environment_id }`, read through `useAllRuns`, Task 3: the whole queue of that host, not the newest page of every host's queued runs); `interface QueueRow { position: number | null; runId: string; label: string; createdBy: string; gpus: number; waiting: string }`; `queueRows(runs, environmentId, now?, current?): QueueRow[]` (the queued runs of the same environment, i.e. the same host, kept by `environment_id` on the client too, so a hub that ignores the filter still gives the right rows; never matched by `executor.host`; `current`, the page's own queued run, is kept when the list lacks it, e.g. fetched just before it was indexed); `interface GpuCell { index: number; label: string; util: number; kind: "run" | "ext" | "free" }`; `gpuCells(host: HostRow): GpuCell[]`; `QueuePanel({ host, hostName, runId, rows })`.
  - `StateBanner({ record, phase, host, conn, now?, reason? })` (`role="status"`; renders nothing unless stale or lost; `reason`: the `run.lost` event's reason, shown first when given).
  - `placeParts(record, phase, host): string[]`; `StatusLine({ record, phase?, host?, now? })` (defaults keep the phase 1b output). Every part names the host with `hostLabel(record, host)` (Task 23): `host` is the run's hosts row, or null without the hosts list.
  - `REMOTE_CSS: string`, `RemoteStyles()`.

- [ ] **Step 1: Write the failing tests**

Create `ui/test/pages/remoteParts.test.tsx`:

```tsx
import { describe, expect, test } from "bun:test";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Placement, placementRows } from "../../src/pages/components/Placement";
import { QueuePanel, gpuCells, queueRows, queuedRunsQuery } from "../../src/pages/components/QueuePanel";
import { REMOTE_CSS } from "../../src/pages/components/remoteStyles";
import { StateBanner } from "../../src/pages/components/StateBanner";
import { StatusLine, placeParts } from "../../src/pages/components/StatusLine";
import { makeRecord } from "./fixtures";
import { mockClipboard, renderWithClient } from "./helpers";
import {
  DGX,
  GPU1,
  MCCLEARY,
  NOW,
  QUEUED_ID,
  lostRecord,
  pendingRecord,
  queuedRecord,
  runningRecord,
  staleRecord,
} from "./remoteFixtures";

describe("placementRows", () => {
  test("queued: host, GPUs to come, queue place", () => {
    expect(placementRows(queuedRecord(), "queued", GPU1)).toEqual([
      { key: "Host", value: "gpu1", note: "ssh", copy: "gpu1" },
      { key: "GPUs", value: "2× A100 80GB PCIe", note: "assigned at start" },
      { key: "Queue", value: "2 of 3", note: "since 14:21" },
    ]);
  });

  test("pending SLURM job", () => {
    expect(placementRows(pendingRecord(), "pending", MCCLEARY)).toEqual([
      { key: "Host", value: "mccleary", note: "slurm", copy: "mccleary" },
      { key: "Job", value: "4471031", note: "pending", copy: "4471031", mono: true },
      { key: "GPUs", value: "2 GPU", note: "assigned at start" },
    ]);
  });

  test("running on an SSH host: CUDA_VISIBLE_DEVICES and pid", () => {
    expect(placementRows(runningRecord(), "running", GPU1)).toEqual([
      { key: "Host", value: "gpu1", note: "ssh", copy: "gpu1" },
      {
        key: "GPUs",
        value: "CUDA_VISIBLE_DEVICES=0",
        note: "1× A100 80GB PCIe",
        copy: "CUDA_VISIBLE_DEVICES=0",
        mono: true,
      },
      { key: "PID", value: "2291045", mono: true },
    ]);
  });

  test("stale: the pid is as of the last answer", () => {
    expect(placementRows(staleRecord(), "stale", DGX).at(-1)).toEqual({
      key: "PID",
      value: "118734",
      note: "as of 14:28",
      mono: true,
    });
  });

  test("lost SLURM run: job, node, GPUs, cost", () => {
    expect(placementRows(lostRecord(), "lost", MCCLEARY)).toEqual([
      { key: "Host", value: "mccleary", note: "slurm", copy: "mccleary" },
      { key: "Job", value: "4471023", copy: "4471023", mono: true },
      { key: "Node", value: "r814u05n01", copy: "r814u05n01", mono: true },
      {
        key: "GPUs",
        value: "CUDA_VISIBLE_DEVICES=0,1",
        note: "2 GPU",
        copy: "CUDA_VISIBLE_DEVICES=0,1",
        mono: true,
      },
      { key: "Cost", value: "$2.17", note: "3.50 GPU h, API $0.42" },
    ]);
  });

  test("Placement draws the rows and copies a value", async () => {
    const written = mockClipboard();
    render(<Placement rows={placementRows(lostRecord(), "lost", MCCLEARY)} />);
    const keys = [...document.querySelectorAll(".place-row .k")].map((k) => k.textContent);
    expect(keys).toEqual(["Host", "Job", "Node", "GPUs", "Cost"]);
    expect(document.querySelector(".place-row .v.mono")?.textContent).toBe("4471023");
    fireEvent.click(screen.getByRole("button", { name: "Copy Job 4471023" }));
    await waitFor(() => expect(written).toEqual(["4471023"]));
  });
});

describe("queue", () => {
  const others = [
    queuedRecord({
      run_id: "20261003-142500-toy-test-93e7",
      hypothesis: "lr 1e-3 with beam 5",
      created_at: "2026-10-03T14:25:00Z",
      executor: { ...queuedRecord().executor, queue_position: 3 },
    }),
    queuedRecord(),
    queuedRecord({
      run_id: "20261003-142000-toy-test-b7e0",
      hypothesis: "aug plus seed 5",
      created_by: "human:shreyas",
      created_at: "2026-10-03T14:20:00Z",
      executor: { ...queuedRecord().executor, queue_position: 1 },
    }),
    queuedRecord({
      run_id: "20261003-140000-toy-test-dd01",
      environment_id: "env-dgx",
      host: "dgx-h100-07",
      executor: { ...queuedRecord().executor, host: "dgx-h100-07", queue_position: 1 },
    }),
    runningRecord(),
  ];

  test("queueRows keeps the queued runs of this run's environment (its host), in queue order", () => {
    expect(queueRows(others, "env-gpu1", NOW)).toEqual([
      {
        position: 1,
        runId: "20261003-142000-toy-test-b7e0",
        label: "aug plus seed 5",
        createdBy: "human:shreyas",
        gpus: 2,
        waiting: "14m",
      },
      { position: 2, runId: QUEUED_ID, label: "lr 1e-3 with beam 1", createdBy: "agent:tuner", gpus: 2, waiting: "12m" },
      {
        position: 3,
        runId: "20261003-142500-toy-test-93e7",
        label: "lr 1e-3 with beam 5",
        createdBy: "agent:tuner",
        gpus: 2,
        waiting: "9m",
      },
    ]);
  });

  test("queueRows keeps the page's own run when the list lacks it; the query names the environment", () => {
    expect(queuedRunsQuery("env-gpu1")).toEqual({ status: "queued", environment_id: "env-gpu1" });
    // the list was read just before this run was indexed: it still shows, at its position
    const without = others.filter((r) => r.run_id !== QUEUED_ID);
    expect(queueRows(without, "env-gpu1", NOW, queuedRecord()).map((r) => [r.position, r.runId])).toEqual([
      [1, "20261003-142000-toy-test-b7e0"],
      [2, QUEUED_ID],
      [3, "20261003-142500-toy-test-93e7"],
    ]);
    // listed once when the list has it; never added when it is not queued or on another host
    expect(queueRows(others, "env-gpu1", NOW, queuedRecord()).filter((r) => r.runId === QUEUED_ID)).toHaveLength(1);
    expect(queueRows(without, "env-gpu1", NOW, runningRecord())).toHaveLength(2);
    expect(queueRows(without, "env-dgx", NOW, queuedRecord()).map((r) => r.runId)).toEqual([
      "20261003-140000-toy-test-dd01",
    ]);
  });

  test("gpuCells: held by a run, used outside hx, free", () => {
    expect(gpuCells(GPU1)).toEqual([
      { index: 0, label: "6b0e", util: 92, kind: "run" },
      { index: 1, label: "ext", util: 63, kind: "ext" },
      { index: 2, label: "free", util: 0, kind: "free" },
    ]);
  });

  test("QueuePanel shows the GPUs and marks this run", () => {
    renderWithClient(
      <QueuePanel host={GPU1} hostName="gpu1" runId={QUEUED_ID} rows={queueRows(others, "env-gpu1", NOW)} />,
    );
    const cells = [...document.querySelectorAll(".gpu-cells li")].map((c) => [c.className, c.textContent]);
    expect(cells).toEqual([
      ["c run", "6b0e92%"],
      ["c ext", "ext63%"],
      ["c free", "free0%"],
    ]);
    const rows = [...document.querySelectorAll(".queue-t tbody tr")];
    expect(rows.map((r) => r.querySelector("td")?.textContent)).toEqual(["1", "2", "3"]);
    const me = document.querySelector('.queue-t tr[aria-current="true"]');
    expect(me?.querySelector("b")?.textContent).toBe("f2c8");
    expect(screen.getByRole("link", { name: "b7e0" }).getAttribute("href")).toBe(
      "/r/20261003-142000-toy-test-b7e0",
    );
  });

  test("QueuePanel with no queued runs and no hosts list", () => {
    renderWithClient(<QueuePanel host={null} hostName="gpu1" runId={QUEUED_ID} rows={[]} />);
    expect(document.querySelector(".gpu-cells")).toBeNull();
    expect(screen.getByText("No queued runs on gpu1")).toBeTruthy();
  });
});

describe("status line and state bar", () => {
  test("placeParts per phase", () => {
    expect(placeParts(makeRecord(), "local", null)).toEqual(["mbp.local"]);
    expect(placeParts(queuedRecord(), "queued", GPU1)).toEqual(["2 of 3 on gpu1", "needs 2 GPU, 1 free"]);
    // without the hosts list: the machine's own hostname
    expect(placeParts(queuedRecord(), "queued", null)).toEqual(["2 in queue on sv-a100-01", "needs 2 GPU"]);
    const unplaced = queuedRecord({ executor: { ...queuedRecord().executor, queue_position: null } });
    expect(placeParts(unplaced, "queued", GPU1)).toEqual(["queued on gpu1", "needs 2 GPU, 1 free"]);
    expect(placeParts(pendingRecord(), "pending", MCCLEARY)).toEqual(["mccleary, job 4471031 pending"]);
    expect(placeParts(runningRecord(), "running", GPU1)).toEqual(["gpu1, pid 2291045"]);
    expect(placeParts(lostRecord(), "lost", MCCLEARY)).toEqual(["mccleary, job 4471023"]);
  });

  test("StatusLine of a stale run: stale chip, time gone, host and pid", () => {
    render(<StatusLine record={staleRecord()} phase="stale" host={DGX} now={NOW} />);
    const parts = [...(document.querySelector(".status")?.children ?? [])].map((c) => c.textContent);
    expect(parts).toEqual(["stale", "5m", "seed 3", "11:03:55 UTC", "agent:acceptance", "dgx, pid 118734"]);
    expect(document.querySelector(".status .st")?.className).toBe("st stale");
  });

  test("StatusLine of a hub run is unchanged", () => {
    render(<StatusLine record={makeRecord()} />);
    const parts = [...(document.querySelector(".status")?.children ?? [])].map((c) => c.textContent);
    expect(parts).toEqual(["finished", "0.8 s", "seed 3", "21:03:06 UTC", "agent:acceptance", "mbp.local", "best", "svm"]);
  });

  test("StateBanner of a stale run", () => {
    render(<StateBanner record={staleRecord()} phase="stale" host={DGX} conn="stale" now={NOW} />);
    const bar = screen.getByRole("status");
    expect(bar.className).toBe("state-bar");
    expect([...bar.children].map((c) => c.textContent)).toEqual([
      "dgx unreachable 5m",
      "since 14:28:02 UTC",
      "no ping for 60 s",
      "stale",
    ]);
  });

  test("StateBanner of a lost run names the reason", () => {
    render(<StateBanner record={lostRecord()} phase="lost" host={MCCLEARY} conn="connected" now={NOW} />);
    const bar = screen.getByRole("status");
    expect(bar.className).toBe("state-bar lost");
    expect([...bar.children].map((c) => c.textContent)).toEqual([
      "SLURM job 4471023 lost",
      "r814u05n01",
      "02:14:37 UTC",
      "no exit code",
    ]);
    expect(bar.querySelector("b")?.getAttribute("title")).toBe(
      "The env server marked this run lost. Its run.lost event has the reason.",
    );
  });

  test("StateBanner of a lost run shows the run.lost reason first when the tab saw it", () => {
    const why = "SLURM ended job 4471023 with NODE_FAIL on r814u05n01; no exit record";
    render(
      <StateBanner record={lostRecord()} phase="lost" host={MCCLEARY} conn="connected" now={NOW} reason={why} />,
    );
    const bar = screen.getByRole("status");
    expect([...bar.children].map((c) => c.textContent)).toEqual([
      "SLURM job 4471023 lost",
      why,
      "r814u05n01",
      "02:14:37 UTC",
      "no exit code",
    ]);
    expect(bar.querySelector("b")?.getAttribute("title")).toBe("Reason from the run's run.lost event.");
  });

  test("StateBanner draws nothing for a running run", () => {
    const { container } = render(
      <StateBanner record={runningRecord()} phase="running" host={GPU1} conn="connected" now={NOW} />,
    );
    expect(container.innerHTML).toBe("");
  });
});

test("remote CSS stays inside .page", () => {
  const rules = REMOTE_CSS.split("\n").filter((line) => line.trim() !== "");
  expect(rules.length).toBeGreaterThan(10);
  expect(rules.filter((line) => !line.startsWith(".page "))).toEqual([]);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bun test test/pages/remoteParts.test.tsx`
Expected: FAIL with `error: Cannot find module '../../src/pages/components/Placement'`.

- [ ] **Step 3: Write `Placement.tsx`**

Create `ui/src/pages/components/Placement.tsx`:

```tsx
/**
 * Run panel "Placement" (spec 8A.5, 8A.7; mockups shot-run-*): host, SLURM job and node,
 * GPUs as `CUDA_VISIBLE_DEVICES`, pid, queue place, and cost. Copy buttons copy the value.
 */
import { CopyButton } from "./CopyButton";
import { fmtClock, fmtUsd } from "./format";
import { costNote, gpuLabel, hostLabel, type RunPhase, visibleDevices } from "./remote";
import type { HostRow, RunRecord } from "./types";

export interface PlaceRow {
  key: string;
  value: string;
  note?: string;
  copy?: string;
  mono?: boolean;
}

/** `host` is the run's hosts row (`runHostRow`), or null without the hosts list. */
export function placementRows(record: RunRecord, phase: RunPhase, host: HostRow | null): PlaceRow[] {
  const ex = record.executor;
  const name = hostLabel(record, host);
  const rows: PlaceRow[] = [
    { key: "Host", value: name, note: host?.kind ?? (ex.slurm_job_id ? "slurm" : "ssh"), copy: name },
  ];
  if (phase === "queued" || phase === "pending") {
    if (ex.slurm_job_id) {
      rows.push({ key: "Job", value: ex.slurm_job_id, note: "pending", copy: ex.slurm_job_id, mono: true });
    }
    const want = record.gpus_requested ?? 0;
    if (want > 0) rows.push({ key: "GPUs", value: gpuLabel(want, host), note: "assigned at start" });
    const pos = ex.queue_position ?? null;
    if (pos !== null) {
      rows.push({
        key: "Queue",
        value: host ? `${pos} of ${host.queue}` : String(pos),
        note: `since ${fmtClock(record.created_at)}`,
      });
    }
    return rows;
  }
  if (ex.slurm_job_id) rows.push({ key: "Job", value: ex.slurm_job_id, copy: ex.slurm_job_id, mono: true });
  if (ex.node) rows.push({ key: "Node", value: ex.node, copy: ex.node, mono: true });
  const gpus = ex.gpus ?? [];
  if (gpus.length > 0) {
    const cvd = visibleDevices(gpus);
    rows.push({ key: "GPUs", value: cvd, note: gpuLabel(gpus.length, host, gpus), copy: cvd, mono: true });
  }
  const pid = ex.child_pid ?? ex.pid;
  if (pid !== null) {
    const row: PlaceRow = { key: "PID", value: String(pid), mono: true };
    if (phase === "stale" && host) row.note = `as of ${fmtClock(host.state.since)}`;
    rows.push(row);
  }
  if (record.cost) rows.push({ key: "Cost", value: fmtUsd(record.cost.total_usd), note: costNote(record.cost) });
  return rows;
}

export function Placement({ rows }: { rows: PlaceRow[] }) {
  return (
    <div className="place">
      {rows.map((row) => (
        <div key={row.key} className="place-row">
          <span className="k">{row.key}</span>
          <span>
            <span className={row.mono ? "v mono" : "v"}>{row.value}</span>
            {row.note ? <small>{row.note}</small> : null}
          </span>
          {row.copy ? <CopyButton text={row.copy} label={`${row.key} ${row.copy}`} /> : <span />}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Write `QueuePanel.tsx`**

Create `ui/src/pages/components/QueuePanel.tsx`:

```tsx
/**
 * Run panel "Queue" for a run waiting on an SSH host (spec 8A.5; mockup shot-run-queued):
 * the host's GPUs (held by a run, used outside hx, or free) and its hx queue in order.
 */
import { DASH, firstClause, isAgent, shortId } from "./format";
import { AppLink, hrefs } from "./links";
import { fmtWait, secondsSince } from "./remote";
import type { HostRow, RunRecord, RunsQuery } from "./types";

/**
 * The runs query the panel reads (through `useAllRuns`, so the queue head is never cut off):
 * the queued runs of one environment, i.e. one host.
 */
export function queuedRunsQuery(environmentId: string): Omit<RunsQuery, "limit"> {
  return { status: "queued", environment_id: environmentId };
}

export interface QueueRow {
  position: number | null;
  runId: string;
  label: string;
  createdBy: string;
  gpus: number;
  waiting: string;
}

const LAST = Number.MAX_SAFE_INTEGER;

/**
 * The queued runs of one host, in queue order. A host serves one environment, so runs are
 * kept by `environment_id` (never `executor.host`, the machine's hostname), also when the
 * hub already filtered them. `current` (the page's own run) is kept when it is queued on
 * this host but missing from `runs`, which were read before it was indexed.
 */
export function queueRows(
  runs: readonly RunRecord[],
  environmentId: string,
  now: number = Date.now(),
  current?: RunRecord,
): QueueRow[] {
  const mine = (r: RunRecord): boolean => r.status === "queued" && r.environment_id === environmentId;
  const listed = runs.filter(mine);
  if (current !== undefined && mine(current) && !listed.some((r) => r.run_id === current.run_id)) {
    listed.push(current);
  }
  return listed
    .map((r) => {
      const waited = secondsSince(r.created_at, now);
      return {
        position: r.executor.queue_position ?? null,
        runId: r.run_id,
        label: firstClause(r.hypothesis, `run ${shortId(r.run_id)}`),
        createdBy: r.created_by,
        gpus: r.gpus_requested ?? 0,
        waiting: waited === null ? DASH : fmtWait(waited),
      };
    })
    .sort((a, b) => (a.position ?? LAST) - (b.position ?? LAST));
}

export interface GpuCell {
  index: number;
  label: string;
  util: number;
  kind: "run" | "ext" | "free";
}

export function gpuCells(host: HostRow): GpuCell[] {
  return [...host.gpus]
    .sort((a, b) => a.index - b.index)
    .map((g) => {
      const kind: GpuCell["kind"] = g.run_id ? "run" : g.external ? "ext" : "free";
      const label = g.run_id ? shortId(g.run_id) : kind;
      return { index: g.index, label, util: Math.round(g.util), kind };
    });
}

const CELL_TIP: Record<GpuCell["kind"], string> = { run: "hx run", ext: "process outside hx", free: "free" };

export interface QueuePanelProps {
  host: HostRow | null;
  hostName: string;
  runId: string;
  rows: QueueRow[];
}

export function QueuePanel({ host, hostName, runId, rows }: QueuePanelProps) {
  const cells = host ? gpuCells(host) : [];
  return (
    <div className="queue">
      {cells.length > 0 ? (
        <ol className="gpu-cells" aria-label={`GPUs on ${hostName}`}>
          {cells.map((c) => (
            <li key={c.index} className={`c ${c.kind}`} title={`GPU ${c.index}: ${CELL_TIP[c.kind]}, ${c.util}% busy`}>
              {c.label}
              <small>{`${c.util}%`}</small>
            </li>
          ))}
        </ol>
      ) : null}
      {rows.length === 0 ? (
        <p className="panel-empty">{`No queued runs on ${hostName}`}</p>
      ) : (
        <table className="tbl queue-t">
          <thead>
            <tr>
              <th>pos</th>
              <th>run</th>
              <th>config</th>
              <th>by</th>
              <th className="r">GPUs</th>
              <th className="r">waiting</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const me = row.runId === runId;
              return (
                <tr key={row.runId} className={me ? "me" : undefined} aria-current={me ? "true" : undefined}>
                  <td>{row.position ?? DASH}</td>
                  <td>
                    {me ? (
                      <b>{shortId(row.runId)}</b>
                    ) : (
                      <AppLink href={hrefs.run(row.runId)}>{shortId(row.runId)}</AppLink>
                    )}
                  </td>
                  <td>{row.label}</td>
                  <td>
                    <span className={`who ${isAgent(row.createdBy) ? "agent" : "human"}`}>
                      <i />
                      {row.createdBy}
                    </span>
                  </td>
                  <td className="r">{row.gpus}</td>
                  <td className="r">{row.waiting}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Write `StateBanner.tsx`**

Create `ui/src/pages/components/StateBanner.tsx`:

```tsx
/**
 * The bar under a run's status line (spec 5.6; mockups shot-run-stale, shot-run-lost):
 * how long its host has been unreachable, or why the run is lost. Nothing otherwise.
 */
import { fmtTime } from "./format";
import { fmtWait, hostLabel, lostReason, type RunPhase, secondsSince } from "./remote";
import type { ConnState, HostRow, RunRecord } from "./types";

export interface StateBannerProps {
  record: RunRecord;
  phase: RunPhase;
  host: HostRow | null;
  conn: ConnState | null;
  now?: number;
  /** The `run.lost` event's reason, when this tab saw it (`useLostReason`). */
  reason?: string | null;
}

export function StateBanner({ record, phase, host, conn, now = Date.now(), reason = null }: StateBannerProps) {
  if (phase === "stale") {
    const name = hostLabel(record, host);
    const gone = host ? secondsSince(host.state.since, now) : null;
    return (
      <div className="state-bar" role="status">
        <b>{gone === null ? `${name} unreachable` : `${name} unreachable ${fmtWait(gone)}`}</b>
        {host ? <span>{`since ${fmtTime(host.state.since)}`}</span> : null}
        {host?.state.message ? <span>{host.state.message}</span> : null}
        <span className="r" title="connection state from the hub">
          {host?.state.state ?? conn ?? "stale"}
        </span>
      </div>
    );
  }
  if (phase === "lost") {
    const why = lostReason(record, reason);
    return (
      <div className="state-bar lost" role="status">
        <b title={why.tooltip}>{why.title}</b>
        {why.parts.map((part) => (
          <span key={part}>{part}</span>
        ))}
      </div>
    );
  }
  return null;
}
```

- [ ] **Step 6: Replace `StatusLine.tsx`**

Replace the whole of `ui/src/pages/components/StatusLine.tsx` with:

```tsx
/** The line under a run's title: status, time, seed, launcher, where it runs, tags. */
import { fmtDuration, fmtTime, isAgent, runSeconds, shortId } from "./format";
import { AppLink, hrefs } from "./links";
import { fmtWait, freeGpus, hostLabel, type RunPhase, secondsSince } from "./remote";
import type { HostRow, RunRecord } from "./types";

/**
 * Where the run is, as short texts after the launcher: the machine's hostname for a hub run
 * (phase `local`); queue place and GPU need for a queued run; host with SLURM job or pid for
 * the rest. A remote host is named by `hostLabel` (the hub's name, else the hostname).
 */
export function placeParts(record: RunRecord, phase: RunPhase, host: HostRow | null): string[] {
  if (phase === "local") return [record.host];
  const name = hostLabel(record, host);
  const ex = record.executor;
  if (phase === "queued") {
    const pos = ex.queue_position ?? null;
    const where =
      pos === null ? `queued on ${name}` : host ? `${pos} of ${host.queue} on ${name}` : `${pos} in queue on ${name}`;
    const want = record.gpus_requested ?? 0;
    const need = host && host.gpus.length > 0 ? `needs ${want} GPU, ${freeGpus(host)} free` : `needs ${want} GPU`;
    return [where, need];
  }
  if (ex.slurm_job_id) return [`${name}, job ${ex.slurm_job_id}${phase === "pending" ? " pending" : ""}`];
  const pid = ex.child_pid ?? ex.pid;
  return pid !== null ? [`${name}, pid ${pid}`] : [name];
}

export interface StatusLineProps {
  record: RunRecord;
  phase?: RunPhase;
  host?: HostRow | null;
  now?: number;
}

export function StatusLine({ record, phase = "local", host = null, now = Date.now() }: StatusLineProps) {
  const stale = phase === "stale";
  const shown = stale ? "stale" : record.status;
  const seconds = runSeconds(record, now);
  const gone = stale && host ? secondsSince(host.state.since, now) : null;
  return (
    <p className="status">
      <span className={`st ${shown}`}>
        <i />
        {shown}
      </span>
      {stale ? (
        gone !== null ? (
          <span title="host unreachable for">{fmtWait(gone)}</span>
        ) : null
      ) : seconds !== null ? (
        <span>{fmtDuration(seconds)}</span>
      ) : null}
      {record.seed !== null ? <span>{`seed ${record.seed}`}</span> : null}
      <span title={record.created_at}>{fmtTime(record.created_at)}</span>
      <span className={`who ${isAgent(record.created_by) ? "agent" : "human"}`}>
        <i />
        {record.created_by}
      </span>
      {placeParts(record, phase, host).map((text) => (
        <span key={text}>{text}</span>
      ))}
      {record.kind === "infer" ? (
        <span className="tag" title="inference-only run">
          infer
        </span>
      ) : null}
      {record.parent ? (
        <AppLink href={hrefs.run(record.parent)}>{`parent ${shortId(record.parent)}`}</AppLink>
      ) : null}
      {record.tags.map((tag) => (
        <span key={tag} className="tag">
          {tag}
        </span>
      ))}
    </p>
  );
}
```

- [ ] **Step 7: Write `remoteStyles.ts`**

Create `ui/src/pages/components/remoteStyles.ts`:

```ts
/**
 * CSS for the run page's remote parts: status glyphs for queued and stale, the state bar,
 * Placement rows, the GPU cells and the queue table. Every selector starts with `.page`;
 * colours come from the theme tokens, so light and dark both work.
 */
import { createElement } from "react";

export const REMOTE_CSS = `
.page .st.queued i { background: transparent; box-shadow: inset 0 0 0 1.4px var(--ink-2); }
.page .st.stale i { background: linear-gradient(90deg, transparent 50%, var(--ink) 50%); box-shadow: inset 0 0 0 1.4px var(--ink); }
.page .state-bar { display: flex; flex-wrap: wrap; gap: 6px 18px; align-items: baseline; margin-top: 28px; padding: 14px 0; border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); font-size: 14px; color: var(--ink-2); }
.page .state-bar b { color: var(--ink); font-weight: 600; }
.page .state-bar.lost b { color: var(--fail); }
.page .state-bar .r { margin-left: auto; font-size: 12.5px; color: var(--ink-3); }
.page .place { font-size: 14px; }
.page .place-row { display: grid; grid-template-columns: 116px minmax(0, 1fr) auto; gap: 0 16px; align-items: baseline; padding: 12px 0; border-top: 1px solid var(--rule-2); }
.page .place-row:first-child { border-top: 0; padding-top: 0; }
.page .place-row .k { color: var(--ink); font-weight: 550; }
.page .place-row .v.mono { font-family: var(--mono); font-size: 13px; }
.page .place-row small { margin-left: 6px; font-size: 12.5px; color: var(--ink-3); }
.page .gpu-cells { list-style: none; display: grid; grid-auto-flow: column; grid-auto-columns: minmax(0, 1fr); gap: 4px; margin: 0 0 24px; padding: 0; }
.page .gpu-cells .c { border: 1px solid var(--rule); border-left-width: 3px; border-radius: 3px; padding: 4px 6px; font-size: 12.5px; font-weight: 550; color: var(--ink); }
.page .gpu-cells .c small { display: block; font-weight: 400; color: var(--ink-3); }
.page .gpu-cells .c.run { border-left-color: var(--ink-2); background: var(--paper-2); }
.page .gpu-cells .c.ext { color: var(--ink-3); background: repeating-linear-gradient(135deg, transparent 0 4px, var(--rule-2) 4px 5px); }
.page .gpu-cells .c.free { border-style: dashed; border-left-width: 1px; color: var(--ink-3); font-weight: 400; }
.page .queue-t tr.me td { background: var(--paper-2); }
.page .queue-t tr.me td:first-child { box-shadow: inset 2px 0 0 var(--ink); padding-left: 8px; }
`;

/** Inject the remote-run CSS (one `<style>` per mounted run page). */
export function RemoteStyles() {
  return createElement("style", { "data-hx": "remote" }, REMOTE_CSS);
}
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `bun test test/pages/remoteParts.test.tsx test/pages/runSummary.test.tsx test/pages/Run.test.tsx && bun run typecheck`
Expected: `remoteParts.test.tsx` 19 pass; the two phase 1b files pass unchanged; `0 fail`; `tsc --noEmit` prints nothing.

- [ ] **Step 9: Commit (repo root)**

```bash
git add ui/src/pages/components/Placement.tsx ui/src/pages/components/QueuePanel.tsx ui/src/pages/components/StateBanner.tsx ui/src/pages/components/StatusLine.tsx ui/src/pages/components/remoteStyles.ts ui/test/pages/remoteParts.test.tsx
git commit -m "feat(ui): placement, host queue, status line and state bar for remote runs"
```

---

### Task 26: Run actions by phase

**Files:**
- Modify: `ui/src/pages/components/RunActions.tsx` (whole file)
- Test: `ui/test/pages/remoteActions.test.tsx`

**Interfaces:**
- Consumes: `RunPhase` (Task 23); `api.connectHost`, `REMOTE_RUN_INVALIDATES`, `HOST_EVENT_INVALIDATES` (Tasks 2-3); `useAction` (exists).
- Produces: `RunActions({ record, phase?, hostName? }: { record: RunRecord; phase?: RunPhase; hostName?: string | null })`. `hostName` is the hub's name for the run's host (`runHostRow(...)?.name`, matched by `environment_id`); null for a hub run or without the hosts list. `queued`/`pending`: one primary `Cancel` (stop). `stale`: primary `Reconnect` (`POST /api/v1/hosts/{hostName}/connect`; disabled while `hostName` is null, since `executor.host` is the machine's hostname and the hub would answer `unknown host`) and a disabled `Stop`. `lost`: `Rerun` is primary. Other phases: the phase 1b buttons. Every phase but `local` invalidates `REMOTE_RUN_INVALIDATES`.

- [ ] **Step 1: Write the failing tests**

Create `ui/test/pages/remoteActions.test.tsx`:

```tsx
import { afterEach, expect, test } from "bun:test";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { RunActions } from "../../src/pages/components/RunActions";
import { DGX_STATE } from "../api/phase2-fixtures";
import { HttpReply, mockApi, renderWithClient, restoreFetch } from "./helpers";
import {
  LOST_ID,
  PENDING_ID,
  QUEUED_ID,
  lostRecord,
  pendingRecord,
  queuedRecord,
  staleRecord,
} from "./remoteFixtures";

afterEach(() => {
  cleanup();
  restoreFetch();
});

const names = () => screen.getAllByRole("button").map((b) => b.textContent);

test("a queued run has one action: Cancel, which stops it", async () => {
  const calls = mockApi({ [`POST /api/v1/runs/${QUEUED_ID}/stop`]: { run_id: QUEUED_ID, status: "killed" } });
  renderWithClient(<RunActions record={queuedRecord()} phase="queued" hostName="gpu1" />);
  expect(names()).toEqual(["Cancel"]);
  const cancel = screen.getByRole("button", { name: "Cancel" });
  expect(cancel.className).toBe("btn primary");
  expect(cancel.getAttribute("title")).toBe("Remove from the gpu1 queue");
  fireEvent.click(cancel);
  await waitFor(() => expect(calls.length).toBe(1));
  const body = calls[0]?.body as Record<string, unknown>;
  expect(typeof body.command_id).toBe("string");
  expect(body.created_by).toBe("human");
});

test("a pending SLURM job is cancelled the same way", () => {
  mockApi({ [`POST /api/v1/runs/${PENDING_ID}/stop`]: { run_id: PENDING_ID, status: "killed" } });
  renderWithClient(<RunActions record={pendingRecord()} phase="pending" hostName="mccleary" />);
  expect(names()).toEqual(["Cancel"]);
  expect(screen.getByRole("button", { name: "Cancel" }).getAttribute("title")).toBe("Cancel SLURM job 4471031");
});

test("a stale run offers Reconnect to the hub's host name, not executor.host; Stop cannot reach the host", async () => {
  const calls = mockApi({ "POST /api/v1/hosts/dgx/connect": { ...DGX_STATE, state: "connecting" } });
  // executor.host is the box's hostname (dgx-h100-07); the hub knows the host as dgx
  renderWithClient(<RunActions record={staleRecord()} phase="stale" hostName="dgx" />);
  expect(names()).toEqual(["Reconnect", "Stop"]);
  const stop = screen.getByRole("button", { name: "Stop" });
  expect(stop.hasAttribute("disabled")).toBe(true);
  expect(stop.getAttribute("title")).toBe("dgx is unreachable");
  fireEvent.click(screen.getByRole("button", { name: "Reconnect" }));
  await waitFor(() => expect(calls.map((c) => c.url)).toEqual(["/api/v1/hosts/dgx/connect"]));
  expect(typeof (calls[0]?.body as Record<string, unknown>).command_id).toBe("string");
});

test("Reconnect shows the hub's error", async () => {
  mockApi({
    "POST /api/v1/hosts/dgx/connect": new HttpReply(503, { error: "dgx: ssh refused", type: "HostUnavailableError" }),
  });
  renderWithClient(<RunActions record={staleRecord()} phase="stale" hostName="dgx" />);
  fireEvent.click(screen.getByRole("button", { name: "Reconnect" }));
  expect((await screen.findByRole("alert")).textContent).toBe("dgx: ssh refused");
});

test("without the hub's host name, Reconnect is disabled and posts nothing", () => {
  const calls = mockApi({});
  renderWithClient(<RunActions record={staleRecord()} phase="stale" hostName={null} />);
  const reconnect = screen.getByRole("button", { name: "Reconnect" });
  expect(reconnect.hasAttribute("disabled")).toBe(true);
  expect(reconnect.getAttribute("title")).toBe("The hosts list is not loaded, so the hub's name for dgx-h100-07 is unknown");
  fireEvent.click(reconnect);
  expect(calls).toEqual([]);
});

test("a lost run makes Rerun the main action", () => {
  mockApi({ [`POST /api/v1/runs/${LOST_ID}/rerun`]: { run_id: "NEW" } });
  renderWithClient(<RunActions record={lostRecord()} phase="lost" hostName="mccleary" />);
  expect(names()).toEqual(["Rerun", "Re-infer", "Re-evaluate", "Stop"]);
  expect(screen.getByRole("button", { name: "Rerun" }).className).toBe("btn primary");
  expect(screen.getByRole("button", { name: "Re-evaluate" }).className).toBe("btn");
  expect(screen.getByRole("button", { name: "Stop" }).hasAttribute("disabled")).toBe(true);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bun test test/pages/remoteActions.test.tsx`
Expected: FAIL, `6 fail`. The queued and pending tests fail on `expect(names()).toEqual(["Cancel"])` (received `["Rerun", "Re-infer", "Re-evaluate", "Stop"]`); the three stale tests fail on the button names (no `Reconnect`); `a lost run` fails on the `btn primary` class of `Rerun`.

- [ ] **Step 3: Rewrite `RunActions.tsx`**

Replace the whole of `ui/src/pages/components/RunActions.tsx` with:

```tsx
/**
 * Run actions (spec 8.3.3, 8A.8): rerun, re-infer, re-evaluate, stop; each with a
 * command_id. A run waiting in a queue can only be cancelled; a run on an unreachable host
 * offers Reconnect; a lost run makes Rerun the main action.
 */
import { api } from "../../api/client";
import { HOST_EVENT_INVALIDATES, REMOTE_RUN_INVALIDATES, RUN_EVENT_INVALIDATES } from "../../api/queries";
import { hrefs, useNavigateHref } from "./links";
import { ErrorBox } from "./QueryState";
import type { RunPhase } from "./remote";
import { ACTIVE_STATUSES, type HostState, type RunRecord, type RunRef } from "./types";
import { useAction } from "./useAction";

export interface RunActionsProps {
  record: RunRecord;
  phase?: RunPhase;
  /**
   * The hub's name for the run's host (`runHostRow(...)?.name`); null for a hub run or while
   * the hosts list is not loaded. Never `executor.host`: that is the machine's hostname, and
   * `POST /api/v1/hosts/<hostname>/connect` names no configured host.
   */
  hostName?: string | null;
}

export function RunActions({ record, phase = "local", hostName = null }: RunActionsProps) {
  const navigate = useNavigateHref();
  const id = record.run_id;
  const label = hostName ?? record.host;
  const refresh = phase === "local" ? RUN_EVENT_INVALIDATES : REMOTE_RUN_INVALIDATES;
  const openNew = (made: RunRef) => navigate(hrefs.run(made.run_id));
  const rerun = useAction<RunRef>({
    send: (_: void, opts) => api.rerun(id, opts),
    invalidate: refresh,
    onSuccess: openNew,
  });
  const reinfer = useAction<RunRef>({
    send: (_: void, opts) => api.reinfer(id, undefined, opts),
    invalidate: refresh,
    onSuccess: openNew,
  });
  const reeval = useAction({ send: (_: void, opts) => api.reevalRun(id, {}, opts), invalidate: refresh });
  const stop = useAction({ send: (_: void, opts) => api.stop(id, opts), invalidate: refresh });
  const reconnect = useAction<HostState>({
    send: (_: void, opts) => api.connectHost(hostName ?? "", opts),
    invalidate: HOST_EVENT_INVALIDATES,
  });
  const active = ACTIVE_STATUSES.has(record.status);
  const error = rerun.error ?? reinfer.error ?? reeval.error ?? stop.error ?? reconnect.error;
  const waiting = phase === "queued" || phase === "pending";
  const lost = phase === "lost";
  return (
    <div>
      <div className="actions">
        {waiting ? (
          <button
            type="button"
            className="btn primary"
            disabled={stop.pending}
            onClick={() => stop.run()}
            title={
              phase === "pending" && record.executor.slurm_job_id
                ? `Cancel SLURM job ${record.executor.slurm_job_id}`
                : `Remove from the ${label} queue`
            }
          >
            Cancel
          </button>
        ) : phase === "stale" ? (
          <>
            <button
              type="button"
              className="btn primary"
              disabled={reconnect.pending || hostName === null}
              onClick={() => {
                if (hostName !== null) reconnect.run();
              }}
              title={
                hostName === null
                  ? `The hosts list is not loaded, so the hub's name for ${record.host} is unknown`
                  : `Try ${hostName} again now`
              }
            >
              Reconnect
            </button>
            <button type="button" className="btn" disabled title={`${label} is unreachable`}>
              Stop
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              className={lost ? "btn primary" : "btn"}
              disabled={rerun.pending}
              onClick={() => rerun.run()}
              title="Run again with the same command, code, and seed"
            >
              Rerun
            </button>
            <button
              type="button"
              className="btn"
              disabled={reinfer.pending}
              onClick={() => reinfer.run()}
              title="Run the infer stage again on this run's checkpoint"
            >
              Re-infer
            </button>
            <button
              type="button"
              className={lost ? "btn" : "btn primary"}
              disabled={reeval.pending}
              onClick={() => reeval.run()}
              title="Re-score saved predictions with the current metric versions"
            >
              Re-evaluate
            </button>
            <button
              type="button"
              className="btn"
              disabled={!active || stop.pending}
              onClick={() => stop.run()}
              title={active ? "Stop this run" : "The run is not active"}
            >
              Stop
            </button>
          </>
        )}
      </div>
      {error ? <ErrorBox error={error} /> : null}
    </div>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `bun test test/pages/remoteActions.test.tsx test/pages/runActions.test.tsx && bun run typecheck`
Expected: `remoteActions.test.tsx` 6 pass; `runActions.test.tsx` passes unchanged; `0 fail`; `tsc --noEmit` prints nothing.

- [ ] **Step 5: Commit (repo root)**

```bash
git add ui/src/pages/components/RunActions.tsx ui/test/pages/remoteActions.test.tsx
git commit -m "feat(ui): run actions for queued, stale and lost remote runs"
```

---

### Task 27: Wire the run page

**Files:**
- Modify: `ui/src/pages/Run.tsx` (whole file)
- Test: `ui/test/pages/RunRemote.test.tsx`

**Interfaces:**
- Consumes: everything from Tasks 23-26 (`runPhase`, `runHostRow`, `hostLabel`, `sweepCrumb`, `queuedRunsQuery`, `queueRows`); `api.environment()` (exists); `useHosts(refetchMs, enabled)`, `useAllRuns(query, enabled)`, `HOSTS_REFETCH_MS` (Task 3); `useLostReason`, and `noteLostReasons`/`clearLostReasons` in the test (Task 4).
- Produces: `RunPage` (same props as phase 1b: `{ runId, log?, example? }`). Regions in order: `[log]`, `Queue` (queued only), kind panels (not while queued or pending), `Where`, `Placement` (remote only: `host_state` not null), `Scores`, `Notes`. Crumb shows the run's sweep (`sweepCrumb`, Task 23): a link `sweep <id>` → `/s/<project>/<id>` only when the run's tag `sweep:<owner8>:<id>` names this hub (`owner8` = the first 8 characters of the hub's environment id, from `api.environment()`, key `["environment"]`, read only for a run with a `sweep_id`); a run of another hub's sweep shows `sweep <id>` as plain text with the reason as its tooltip. `GET /api/v1/hosts` (through `useHosts`, so a failed refetch keeps the last list) only for remote runs; the host row is matched by `environment_id`; the queued runs of the run's environment (`useAllRuns(queuedRunsQuery(environment_id))`, complete, with the page's own run kept by `queueRows`) only for queued runs.

- [ ] **Step 1: Write the failing tests**

Create `ui/test/pages/RunRemote.test.tsx`:

```tsx
import { afterEach, beforeEach, expect, setSystemTime, test } from "bun:test";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { clearLostReasons, noteLostReasons } from "../../src/api/lostReasons";
import { RunPage } from "../../src/pages/Run";
import { DGX_STATE, HOSTS } from "../api/phase2-fixtures";
import { HttpReply, fakeRegistry, mockApi, renderWithClient, restoreFetch } from "./helpers";
import {
  LOST_ID,
  NOW,
  QUEUED_ID,
  RUNNING_ID,
  STALE_ID,
  lostRecord,
  queuedRecord,
  remoteDetail,
  runningRecord,
  staleRecord,
} from "./remoteFixtures";

beforeEach(() => {
  setSystemTime(new Date(NOW));
});

afterEach(() => {
  cleanup();
  restoreFetch();
  setSystemTime();
  clearLostReasons();
});

const registry = fakeRegistry(["curves"]);
const HOSTS_ROUTE = "GET /api/v1/hosts";
const ENV_ROUTE = "GET /.well-known/hypothex/environment";
/** This hub's descriptor: its id starts with `0a1b2c3d`, the owner in `sweep:0a1b2c3d:s-7f3a`. */
const HUB_ENV = { environment_id: "0a1b2c3d4e5f60718293a4b5c6d7e8f9", label: "hub", hx_version: "0.5.0" };
const QUEUE_URL = "/api/v1/runs?status=queued&environment_id=env-gpu1&limit=1000";
const QUEUE_ROUTE = `GET ${QUEUE_URL}`;

const regionNames = () => screen.getAllByRole("region").map((r) => r.getAttribute("aria-label"));
const statValues = () => [...document.querySelectorAll(".stats dd")].map((d) => d.textContent);

test("a queued run: title with its place, the host queue, placement", async () => {
  const behind = queuedRecord({
    run_id: "20261003-142500-toy-test-93e7",
    hypothesis: "lr 1e-3 with beam 5",
    created_at: "2026-10-03T14:25:00Z",
    executor: { ...queuedRecord().executor, queue_position: 3 },
  });
  const calls = mockApi({
    [`GET /api/v1/runs/${QUEUED_ID}`]: remoteDetail(queuedRecord()),
    [HOSTS_ROUTE]: HOSTS,
    [QUEUE_ROUTE]: [behind, queuedRecord()],
  });
  renderWithClient(<RunPage runId={QUEUED_ID} />, { registry });
  // the host is named once the hosts list matches the run's environment (executor.host is sv-a100-01)
  const h1 = await screen.findByRole("heading", { level: 1 });
  await waitFor(() => expect(h1.textContent).toBe("lr 1e-3 with beam 1: queued 2nd on gpu1"));
  await waitFor(() => expect(statValues()).toEqual(["2 / 3", "2 GPU", "1 / 3", "12m"]));
  await waitFor(() => expect(document.querySelectorAll(".queue-t tbody tr").length).toBe(2));
  expect(regionNames()).toEqual(["a Queue", "b Where", "c Placement", "d Scores", "e Notes"]);
  expect(document.querySelector('.queue-t tr[aria-current="true"] b')?.textContent).toBe("f2c8");
  expect(document.querySelector(".status")?.textContent).toContain("2 of 3 on gpu1");
  expect(screen.getAllByRole("button").map((b) => b.textContent)).toContain("Cancel");
  expect(new Set(calls.map((c) => c.url))).toEqual(
    new Set([`/api/v1/runs/${QUEUED_ID}`, "/api/v1/hosts", QUEUE_URL]),
  );
});

test("a long queue: every page is read, the head is kept, and the run shows even if the list lacks it", async () => {
  // 1,200 runs wait on gpu1 ahead of and behind this one; the first page (1,000) is full
  const behind = Array.from({ length: 1200 }, (_, i) =>
    queuedRecord({
      run_id: `20261003-1430${String(i).padStart(4, "0")}-toy-test-q${i}`,
      created_at: "2026-10-03T14:30:00Z",
      executor: { ...queuedRecord().executor, queue_position: i < 1 ? 1 : i + 2 },
    }),
  );
  const calls = mockApi({
    [`GET /api/v1/runs/${QUEUED_ID}`]: remoteDetail(queuedRecord()),
    [HOSTS_ROUTE]: HOSTS,
    // the hub answers newest first, so the head (position 1) is on the second page
    [QUEUE_ROUTE]: behind.slice(200),
    [`GET ${QUEUE_URL.replace("limit=1000", "limit=4000")}`]: behind,
  });
  renderWithClient(<RunPage runId={QUEUED_ID} />, { registry });
  await waitFor(() => expect(document.querySelectorAll(".queue-t tbody tr").length).toBe(1201));
  const positions = [...document.querySelectorAll(".queue-t tbody tr")].slice(0, 3).map((r) => r.querySelector("td")?.textContent);
  expect(positions).toEqual(["1", "2", "3"]);
  // this run is in neither page (read before it was indexed), yet it is listed and marked
  expect(document.querySelector('.queue-t tr[aria-current="true"] b')?.textContent).toBe("f2c8");
  expect(calls.filter((c) => c.url.startsWith("/api/v1/runs?")).map((c) => c.url)).toEqual([
    QUEUE_URL,
    QUEUE_URL.replace("limit=1000", "limit=4000"),
  ]);
});

test("a running remote run: host, pid, GPU use, CUDA_VISIBLE_DEVICES", async () => {
  mockApi({ [`GET /api/v1/runs/${RUNNING_ID}`]: remoteDetail(runningRecord()), [HOSTS_ROUTE]: HOSTS });
  renderWithClient(<RunPage runId={RUNNING_ID} />, { registry });
  expect((await screen.findByRole("heading", { level: 1 })).textContent).toBe("aug long run seed 1");
  await waitFor(() => expect(statValues()).toEqual(["1h 52m", "92 %", "57 GB", "1.87"]));
  expect(regionNames()).toEqual(["a Where", "b Placement", "c Scores", "d Notes"]);
  expect(screen.getByRole("region", { name: "b Placement" }).textContent).toContain("CUDA_VISIBLE_DEVICES=0");
  expect(document.querySelector(".status")?.textContent).toContain("gpu1, pid 2291045");
});

test("a run on an unreachable host: stale since, bar, Reconnect", async () => {
  const calls = mockApi({
    [`GET /api/v1/runs/${STALE_ID}`]: remoteDetail(staleRecord(), "stale"),
    [HOSTS_ROUTE]: HOSTS,
    "POST /api/v1/hosts/dgx/connect": { ...DGX_STATE, state: "connecting" },
  });
  renderWithClient(<RunPage runId={STALE_ID} />, { registry });
  await waitFor(() =>
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("lr 1e-3 with beam 10: stale since 14:28"),
  );
  expect(screen.getByRole("status").querySelector("b")?.textContent).toBe("dgx unreachable 5m");
  expect(statValues()).toEqual(["3h 30m", "7.00", "5m"]);
  expect(document.querySelector(".status .st")?.textContent).toBe("stale");
  fireEvent.click(screen.getByRole("button", { name: "Reconnect" }));
  await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url === "/api/v1/hosts/dgx/connect")).toBe(true));
});

test("the tunnel dies mid-mirror: the hosts list fails, the page still says stale", async () => {
  let up = true;
  const calls = mockApi({
    [`GET /api/v1/runs/${STALE_ID}`]: remoteDetail(staleRecord(), "stale"),
    [HOSTS_ROUTE]: () =>
      up ? HOSTS : new HttpReply(503, { error: "dgx: tunnel closed", type: "HostUnavailableError" }),
    "POST /api/v1/hosts/dgx/connect": { ...DGX_STATE, state: "connecting" },
  });
  const { client } = renderWithClient(<RunPage runId={STALE_ID} />, { registry });
  const h1 = await screen.findByRole("heading", { level: 1 });
  await waitFor(() => expect(h1.textContent).toBe("lr 1e-3 with beam 10: stale since 14:28"));
  up = false;
  await client.refetchQueries({ queryKey: ["hosts"] });
  expect(calls.filter((c) => c.url === "/api/v1/hosts").length).toBeGreaterThanOrEqual(2);
  // the failed refetch keeps the last list: same host, same bar, Reconnect still names dgx
  expect(h1.textContent).toBe("lr 1e-3 with beam 10: stale since 14:28");
  expect(screen.getByRole("status").querySelector("b")?.textContent).toBe("dgx unreachable 5m");
  expect(document.querySelector(".status .st")?.textContent).toBe("stale");
  fireEvent.click(screen.getByRole("button", { name: "Reconnect" }));
  await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url === "/api/v1/hosts/dgx/connect")).toBe(true));
});

test("opened while the hosts list fails: stale, the machine's hostname, Reconnect disabled", async () => {
  mockApi({
    [`GET /api/v1/runs/${STALE_ID}`]: remoteDetail(staleRecord(), "stale"),
    [HOSTS_ROUTE]: new HttpReply(503, { error: "dgx: tunnel closed", type: "HostUnavailableError" }),
  });
  renderWithClient(<RunPage runId={STALE_ID} />, { registry });
  // no hosts list: the run is still stale (host_state), named by its machine's own hostname
  expect((await screen.findByRole("heading", { level: 1 })).textContent).toBe(
    "lr 1e-3 with beam 10: dgx-h100-07 unreachable",
  );
  expect(screen.getByRole("status").querySelector("b")?.textContent).toBe("dgx-h100-07 unreachable");
  expect(statValues()).toEqual(["3h 30m", "7.00"]);
  expect(document.querySelector(".status .st")?.textContent).toBe("stale");
  // the hub's name for the host is unknown, so Reconnect cannot be sent
  expect(screen.getByRole("button", { name: "Reconnect" }).hasAttribute("disabled")).toBe(true);
});

test("a lost SLURM run: reason bar, cost, sweep link, Rerun first", async () => {
  const record = lostRecord({ tags: ["sweep:0a1b2c3d:s-7f3a"] });
  mockApi({ [`GET /api/v1/runs/${LOST_ID}`]: remoteDetail(record), [HOSTS_ROUTE]: HOSTS, [ENV_ROUTE]: HUB_ENV });
  renderWithClient(<RunPage runId={LOST_ID} />, { registry });
  expect((await screen.findByRole("heading", { level: 1 })).textContent).toBe("aug long run seed 2: lost at 02:14");
  expect(screen.getByRole("status").querySelector("b")?.textContent).toBe("SLURM job 4471023 lost");
  expect(statValues()).toEqual(["52m 27s", "$2.17"]);
  expect(regionNames()).toEqual(["a Where", "b Placement", "c Scores", "d Notes"]);
  const link = await screen.findByRole("link", { name: "sweep s-7f3a" });
  expect(link.getAttribute("href")).toBe("/s/toy-classifier/s-7f3a");
  expect(screen.getByRole("button", { name: "Rerun" }).className).toBe("btn primary");
  await waitFor(() =>
    expect(screen.getByRole("region", { name: "b Placement" }).textContent).toContain("r814u05n01"),
  );
});

test("a run of another hub's sweep names the sweep without a link", async () => {
  // a host shared by two hubs: the run's tag names the other hub (ffffffff), whose sweep
  // s-7f3a this hub has no page for (or has a different sweep under that id)
  const record = lostRecord({ tags: ["sweep:ffffffff:s-7f3a"] });
  mockApi({ [`GET /api/v1/runs/${LOST_ID}`]: remoteDetail(record), [HOSTS_ROUTE]: HOSTS, [ENV_ROUTE]: HUB_ENV });
  renderWithClient(<RunPage runId={LOST_ID} />, { registry });
  const crumb = await screen.findByTitle("sweep of another hub (ffffffff)");
  expect(crumb.textContent).toBe("sweep s-7f3a");
  expect(screen.queryByRole("link", { name: "sweep s-7f3a" })).toBeNull();
});

test("a lost run shows the reason its mirrored run.lost event carried", async () => {
  const why = "SLURM ended job 4471023 with NODE_FAIL on r814u05n01; no exit record";
  noteLostReasons([
    {
      sequence: 41,
      type: "mirror.run_updated",
      project: "toy-classifier",
      run_id: LOST_ID,
      payload: { host: "mccleary", original_type: "run.lost", status: "lost", reason: why },
      created_at: "2026-10-03T02:14:40Z",
    },
  ]);
  mockApi({ [`GET /api/v1/runs/${LOST_ID}`]: remoteDetail(lostRecord()), [HOSTS_ROUTE]: HOSTS });
  renderWithClient(<RunPage runId={LOST_ID} />, { registry });
  await screen.findByRole("heading", { level: 1 });
  const bar = screen.getByRole("status");
  expect(bar.querySelector("b")?.textContent).toBe("SLURM job 4471023 lost");
  expect(bar.querySelector("span")?.textContent).toBe(why);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bun test test/pages/RunRemote.test.tsx`
Expected: FAIL, 9 fail. The first queued test reports the h1 as `lr 1e-3 with beam 1` instead of `lr 1e-3 with beam 1: queued 2nd on gpu1`; the long-queue test times out in `waitFor` (no `.queue-t` rows: the phase 1b page has no Queue panel); the running test fails on the stat values (`["1h 52m"]`); the three stale tests and the two lost tests fail on their titles; the other hub's sweep test finds no crumb with that title (the phase 1b page has no sweep crumb).

- [ ] **Step 3: Rewrite `Run.tsx`**

Replace the whole of `ui/src/pages/Run.tsx` with:

```tsx
/**
 * Run screen (spec 8.3.3, 8A.8): hypothesis as title (with the queue, stale or lost state
 * of a remote run), status, stat strip, the host queue of a queued run, the task kind's run
 * panels (spec 8.4), where everything is, placement on a host, scores by metric version,
 * notes, and actions.
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useLostReason } from "../api/lostReasons";
import { HOSTS_REFETCH_MS, queryKeys, useAllRuns, useHosts, useRun, useRunTraces } from "../api/queries";
import { Figure, panelLetter } from "./components/Figure";
import { firstClause, shortId } from "./components/format";
import { Unbroken } from "./components/Headline";
import { KindPanels, kindPanelCount, readsTraces, runViewPanels } from "./components/KindPanels";
import { AppLink, hrefs } from "./components/links";
import { LogView } from "./components/LogView";
import { Notes } from "./components/Notes";
import { Placement, placementRows } from "./components/Placement";
import { ErrorBox, Loading } from "./components/QueryState";
import { QueuePanel, queueRows, queuedRunsQuery } from "./components/QueuePanel";
import { hostLabel, runHostRow, runPhase, stateTitle, sweepCrumb } from "./components/remote";
import { remoteStats } from "./components/remoteStats";
import { RemoteStyles } from "./components/remoteStyles";
import { RunActions } from "./components/RunActions";
import { runStats } from "./components/runStats";
import { ScoresList, primaryRef } from "./components/ScoresList";
import { StateBanner } from "./components/StateBanner";
import { StatStrip } from "./components/StatStrip";
import { StatusLine } from "./components/StatusLine";
import { PageStyles } from "./components/styles";
import { WhereList } from "./components/WhereList";

const LOG_STREAMS = ["stdout", "stderr", "supervisor"] as const;
type LogStream = (typeof LOG_STREAMS)[number];

/** Accept only the log streams the API serves (the value comes from the URL). */
export function asLogStream(value: unknown): LogStream | null {
  return LOG_STREAMS.find((s) => s === value) ?? null;
}

export interface RunPageProps {
  runId: string;
  log?: string;
  example?: string;
}

const LONG_TITLE = 60;

export function RunPage({ runId, log, example }: RunPageProps) {
  const run = useRun(runId);
  const lostWhy = useLostReason(runId);
  const record = run.data?.record;
  const project = record?.project ?? "";
  const task = record?.task ?? "";
  const hasTask = task !== "";
  // The same keys as useTaskKind and useLeaderboard, but idle for a run without a task.
  const kind = useQuery({
    queryKey: queryKeys.taskKind(project, task),
    enabled: hasTask,
    queryFn: ({ signal }) => api.taskKind(project, task, signal),
  });
  const board = useQuery({
    queryKey: queryKeys.leaderboard(project, task),
    enabled: hasTask,
    queryFn: ({ signal }) => api.leaderboard(project, task, [], signal),
  });
  const kindSpecs = kind.data?.run_view ?? [];
  const traces = useRunTraces(runId, kindSpecs.some(readsTraces));
  const phase = run.data ? runPhase(run.data) : "local";
  // A remote run: the hub reports its host's state. Hub runs have host_state null, even
  // though the backend sets executor.host (the machine's hostname) on every run.
  const remote = (run.data?.host_state ?? null) !== null;
  // The shared hosts query (keepLastKnown, one query function per key), idle for a hub run.
  const hosts = useHosts(HOSTS_REFETCH_MS, remote);
  // the whole queue of the run's host (every page), never the newest page of all hosts
  const queued = useAllRuns(queuedRunsQuery(record?.environment_id ?? ""), phase === "queued");
  // the hub's descriptor (the Overview's key): its id says whose sweep a run's tag names
  const hubEnv = useQuery({
    queryKey: ["environment"],
    enabled: Boolean(record?.sweep_id),
    queryFn: ({ signal }) => api.environment(signal),
    staleTime: Number.POSITIVE_INFINITY,
  });
  const hubEnvId = hubEnv.data?.environment_id;

  if (run.error) {
    return (
      <div className="page">
        <PageStyles />
        <ErrorBox error={run.error} />
      </div>
    );
  }
  if (!run.data || !record) {
    return (
      <div className="page">
        <PageStyles />
        <Loading />
      </div>
    );
  }

  const now = Date.now();
  const detail = run.data;
  // matched by environment_id; null without the hosts list (texts then use the hostname)
  const host = runHostRow(detail, hosts.data);
  const where = hostLabel(record, host);
  const waiting = phase === "queued" || phase === "pending";
  const row = board.data?.rows.find((r) => r.run_ids.includes(runId)) ?? null;
  const primary = primaryRef(board.data ?? null, row);
  const specs = runViewPanels(kindSpecs, traces.data?.length);
  const stream = asLogStream(log);
  const label = row?.label ?? firstClause(record.hypothesis, `run ${shortId(runId)}`);
  const title = stateTitle(label, phase, record, host) ?? (record.hypothesis || label);
  const stats = waiting
    ? remoteStats(record, phase, host, now)
    : [...runStats(detail, primary, row, now), ...remoteStats(record, phase, host, now)];
  const showKind = hasTask && !waiting;
  const sweep = sweepCrumb(record, typeof hubEnvId === "string" ? hubEnvId : null);

  let next = 0;
  const logLetter = stream ? panelLetter(next++) : "";
  const queueLetter = phase === "queued" ? panelLetter(next++) : "";
  const kindStart = next;
  if (showKind) next += kindPanelCount(specs);
  const whereLetter = panelLetter(next++);
  const placeLetter = remote ? panelLetter(next++) : "";
  const scoresLetter = panelLetter(next++);
  const notesLetter = panelLetter(next++);

  return (
    <div className="page">
      <PageStyles />
      <RemoteStyles />
      <p className="crumb">
        {project}
        <span className="sep">/</span>
        {hasTask ? (
          <>
            <AppLink href={hrefs.task(project, task)}>{task}</AppLink>
            <span className="sep">/</span>
          </>
        ) : null}
        {sweep ? (
          <>
            {sweep.href ? (
              <AppLink href={sweep.href}>{`sweep ${sweep.id}`}</AppLink>
            ) : (
              <span title={sweep.why ?? undefined}>{`sweep ${sweep.id}`}</span>
            )}
            <span className="sep">/</span>
          </>
        ) : null}
        {label}
        <span className="sep">/</span>
        {runId}
        {kind.data ? (
          <span className="tag" title="task kind">
            {kind.data.kind}
          </span>
        ) : null}
      </p>
      <div className="run-top">
        <h1 className={title.length > LONG_TITLE ? "headline long" : "headline"}>
          <Unbroken text={title} />
        </h1>
        <RunActions record={record} phase={phase} hostName={host?.name ?? null} />
      </div>
      <StatusLine record={record} phase={phase} host={host} now={now} />
      <StateBanner
        record={record}
        phase={phase}
        host={host}
        conn={detail.host_state ?? null}
        now={now}
        reason={lostWhy}
      />
      <StatStrip items={stats} />
      {kind.error ? <ErrorBox error={kind.error} /> : null}
      {stream ? <LogView runId={runId} stream={stream} letter={logLetter} /> : null}
      {phase === "queued" ? (
        <Figure letter={queueLetter} title="Queue" aside={host ? `${host.name}, ${host.queue} waiting` : where}>
          {queued.error ? (
            <ErrorBox error={queued.error} />
          ) : queued.data ? (
            <>
              <QueuePanel
                host={host}
                hostName={where}
                runId={runId}
                rows={queueRows(queued.data.runs, record.environment_id, now, record)}
              />
              {queued.data.complete ? null : (
                <p className="small">{`first ${queued.data.runs.length} queued runs on ${where}`}</p>
              )}
            </>
          ) : (
            <Loading />
          )}
        </Figure>
      ) : null}
      {showKind ? (
        <KindPanels
          project={project}
          task={task}
          runId={runId}
          specs={specs}
          example={example}
          startIndex={kindStart}
        />
      ) : null}
      <div className="run-grid">
        <div>
          <Figure letter={whereLetter} title="Where" aside={<span title="host the run executed on">{record.host}</span>}>
            <WhereList detail={detail} />
          </Figure>
        </div>
        <div className="side">
          {remote ? (
            <Figure letter={placeLetter} title="Placement" aside={host?.kind ?? null}>
              <Placement rows={placementRows(record, phase, host)} />
            </Figure>
          ) : null}
          <Figure letter={scoresLetter} title="Scores">
            <ScoresList scores={detail.scores} metricNames={detail.metric_names} primary={primary} />
          </Figure>
          <Figure letter={notesLetter} title="Notes">
            <Notes runId={runId} notes={detail.notes} />
          </Figure>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `bun test test/pages/RunRemote.test.tsx test/pages/Run.test.tsx && bun run typecheck`
Expected: `RunRemote.test.tsx` 9 pass; `Run.test.tsx` (phase 1b, unchanged) passes; `0 fail`; `tsc --noEmit` prints nothing.

- [ ] **Step 5: Run the whole unit suite**

Run: `bun test`
Expected: `0 fail`. The phase 1b page tests (`Run.test.tsx`, `runActions.test.tsx`, `runSummary.test.tsx`) pass unchanged.

- [ ] **Step 6: Look at the page in both themes (no real hosts)**

Run (repo root, in a second terminal; this is the e2e hosts demo from Task 28 and touches no real host). It is one shell command: `--home` and the SSH variables sit on each `hx` command line, never in a separate `export`:

```bash
H=/tmp/hx-f5; rm -rf "$H" && mkdir -p "$H" && ID="$(uuidgen | tr -d '-' | tr 'A-Z' 'a-z')" && \
printf '{"environment_id": "%s", "label": "hx-visual"}\n' "$ID" > "$H/environment.json" && \
HYPOTHEX_SSH=false HYPOTHEX_SCP=false uv run hx --home "$H" demo --with-hosts --json > /dev/null && (cd ui && bun run build) && \
P="$(uv run python -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')" && echo "hub port $P, id $ID" && \
HYPOTHEX_SSH=false HYPOTHEX_SCP=false uv run hx --home "$H" serve --port "$P"
```

In a third terminal, from the repo root, check that the hub on the printed port is the `/tmp/hx-f5` hub before opening any page:

```bash
P=<the port the second terminal printed>; ID="$(sed -n 's/.*"environment_id": *"\([^"]*\)".*/\1/p' /tmp/hx-f5/environment.json)"; \
if [ -n "$ID" ] && curl -sf "http://127.0.0.1:$P/.well-known/hypothex/environment" | grep -Fq "\"$ID\""; then echo "open http://127.0.0.1:$P/"; else echo "port $P is not the /tmp/hx-f5 hub: stop"; fi
```

Open the URL it prints (only after it printed `open …`), follow a queued run and a running run from the Hosts panel, and toggle the theme. Expected: a queued run shows `… queued Nth on <host>`, the Queue panel with GPU cells, and Placement; a running remote run shows `CUDA_VISIBLE_DEVICES=…` in Placement; nothing is unreadable in dark (state bar, GPU cells, queue row). Stop the server with Ctrl-C.

- [ ] **Step 7: Commit (repo root)**

```bash
git add ui/src/pages/Run.tsx ui/test/pages/RunRemote.test.tsx
git commit -m "feat(ui): run page shows queued, remote, stale and lost states with cost"
```

---

### Task 28: Playwright against fake hosts (`hx demo --with-hosts`)

**Files:**
- Modify: `ui/e2e/paths.ts` (whole file: random ports, hosts demo constants, identity helpers)
- Modify: `ui/e2e/serve-demo.ts` (whole file)
- Modify: `ui/e2e/fixtures.ts` (imports; the `isolatedHub` auto fixture and `expectIsolatedHub`)
- Modify: `ui/e2e/.gitignore` (append three lines)
- Modify: `ui/playwright.config.ts` (whole file)
- Create: `ui/e2e/hosts-fixtures.ts`
- Create: `ui/e2e/hosts.spec.ts`
- Create: `ui/e2e/launch.spec.ts`
- Create: `ui/e2e/shutdown-check.ts`
- Modify: `ui/README.md` (append a section)

**Interfaces:**
- Consumes: `test`, `expect`, `expectTheme`, `getJson` from `ui/e2e/fixtures.ts` (exist); the backend plan's `hx demo --with-hosts` (on SIGTERM, the hub's ASGI lifespan shutdown, run inside uvicorn's signal handling, stops the demo runs through the fake gpu1 server's HTTP API, then the fake hosts; ruling S9) and the accessible names of Tasks 5-21 (both listed in this group's intro); the run page from Task 27 (`a Queue`, `… Placement` regions; `queued Nth on <host>` title; `.status` line); `GET /.well-known/hypothex/environment` (`environment_id`, `label`).
- Produces: `freePort()`, `PORT` and `HOSTS_PORT` (random per run, never fixed: picked by the first process that loads paths.ts and passed on in `HX_E2E_PORT` / `HX_E2E_HOSTS_PORT`), `HOSTS_HOME_DIR` (`HX_E2E_HOSTS_HOME` overrides it), `HOSTS_DEMO_FILE`, `DEMO_LABEL = "hx-e2e-demo"`, `HOSTS_DEMO_LABEL = "hx-e2e-hosts"`, `IDENTITY_FILE = "environment.json"`, `IDENTITY_ROUTE`, `SHUTDOWN_WAIT_MS = 60_000`, `interface Identity`, `readIdentity(home)`, `answersAs(base, identity)` (paths.ts); `expectIsolatedHub(request, baseURL)` and the auto fixture `isolatedHub` (fixtures.ts: before every test body, the hub must answer with the `environment_id` and label of the fresh home `serve-demo.ts` wrote, so no spec, and no POST in `live.spec.ts` or `launch.spec.ts`, ever reaches another server); `connectedHosts(request)`, `remoteHosts(hosts)`, `hostOfRun(hosts, run)` (match by `environment_id`, as the UI does), `firstSweep(request)` and the `*Lite` types (hosts-fixtures.ts); Playwright projects `hosts-light`, `hosts-dark`, `hosts-light-edit`, `hosts-dark-edit`; `bun e2e/shutdown-check.ts` (shutdown-order regression on its own random port; it verifies the hub's identity before any host or run route and fails at once if `serve-demo.ts` cannot start).
- Isolation (controller ruling S1): every port a demo hub uses is random per run (the OS's free port), never fixed, so no check can land on an `hx serve` the user left running on the real `~/.hypothex`. Both web servers use `reuseExistingServer: false`, and `serve-demo.ts` writes the fresh home's identity (`environment.json` with a new `environment_id` and the demo label) before seeding; every Playwright test (`isolatedHub`) and the shutdown check compare the hub's `GET /.well-known/hypothex/environment` with it before any host route or mutation. A child that fails to start ends `serve-demo.ts` at once, which stops Playwright and the check at once.
- Shutdown order (ruling S9): Playwright stops each web server with `gracefulShutdown: { signal: "SIGTERM", timeout: 90_000 }` (without it, Playwright SIGKILLs the process group and `serve-demo.ts` cannot clean up). `serve-demo.ts` runs the venv's `hx` itself (no `uv run` wrapper between it and the signal) in its own process group, forwards SIGTERM to the hub process only, and waits up to `SHUTDOWN_WAIT_MS` for it to exit. Nothing else is needed from the UI side: the hub's ASGI lifespan shutdown, which uvicorn runs on that SIGTERM before it exits, first stops the demo runs over the fake gpu1 server's HTTP API, then terminates the fake hosts. Only after the hub has exited, or the wait ran out, does `serve-demo.ts` SIGKILL whatever is left in the group. Signalling the whole group first would kill the fake env servers before the hub's cleanup and orphan the demo runs' supervisors, which run in their own sessions; `shutdown-check.ts` keeps that ordering regression.

- [ ] **Step 1: Random ports, the hosts demo paths, and the identity helpers**

Every port a demo hub listens on is asked from the OS for each run, never fixed (controller ruling S1): a fixed port (7788, 7789, …) can belong to an `hx serve` the user left running on the real `~/.hypothex`, and a check that talks to it would query, or post to, the user's real hosts. The Playwright runner picks both ports when it loads the config and hands them to its workers and web servers through the environment; `shutdown-check.ts` picks its own.

Replace the whole of `ui/e2e/paths.ts` with:

```ts
/** Paths and constants shared by the Playwright config, the demo server, and the specs. */
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const E2E_DIR = fileURLToPath(new URL(".", import.meta.url));
/** Fresh Hypothex home, wiped and re-seeded on every server start. */
export const HOME_DIR = join(E2E_DIR, ".home");
/** `hx demo --json` output: `{kind: "project/task"}`. */
export const DEMO_FILE = join(E2E_DIR, ".demo.json");
export const REPO_ROOT = resolve(E2E_DIR, "..", "..");
export const UI_DIST_INDEX = join(REPO_ROOT, "src", "hypothex", "ui_dist", "index.html");

/** Run by `node -e` or `bun -e`: bind port 0 on 127.0.0.1, print the port the OS gave, close. */
const FREE_PORT_JS =
  "const s = require('node:net').createServer(); s.listen(0, '127.0.0.1', () => { console.log(s.address().port); s.close(); });";

/**
 * A TCP port the OS reports free on 127.0.0.1. A child process does the bind, so this
 * stays synchronous (the Playwright config cannot await).
 */
export function freePort(): number {
  const out = spawnSync(process.execPath, ["-e", FREE_PORT_JS], { encoding: "utf8" });
  const port = Number(out.stdout?.trim());
  if (out.status !== 0 || !Number.isInteger(port) || port <= 0) {
    throw new Error(`no free port from the OS: ${out.error?.message ?? out.stderr ?? "no output"}`);
  }
  return port;
}

/**
 * This run's port for `name`. The first process that loads this file (the Playwright
 * runner, or `shutdown-check.ts`) asks the OS for a free port and writes it into its own
 * environment; every child inherits it, so Playwright's workers and both `serve-demo.ts`
 * web servers agree on it. Only this file sets these variables; there is no fixed default.
 */
function runPort(name: string): number {
  const given = Number(process.env[name] ?? "");
  if (Number.isInteger(given) && given > 0) return given;
  const port = freePort();
  process.env[name] = String(port);
  return port;
}

/** Port of the `hx demo` hub (projects light, dark, light-edit, dark-edit). */
export const PORT = runPort("HX_E2E_PORT");
/** Port of the `hx demo --with-hosts` hub (projects hosts-*). */
export const HOSTS_PORT = runPort("HX_E2E_HOSTS_PORT");

export const KINDS = [
  "generic",
  "training",
  "agent_eval",
  "agent_iteration",
  "system_bench",
] as const;
export type Kind = (typeof KINDS)[number];

/**
 * Hub home for the `hx demo --with-hosts` server (fake remote hosts), wiped on every start.
 * `HX_E2E_HOSTS_HOME` moves it (the shutdown check uses its own home).
 */
export const HOSTS_HOME_DIR = process.env.HX_E2E_HOSTS_HOME ?? join(E2E_DIR, ".home-hosts");
/** `hx demo --with-hosts --json` output. */
export const HOSTS_DEMO_FILE = join(E2E_DIR, ".demo-hosts.json");
/**
 * Labels `serve-demo.ts` writes into each fresh demo home's `environment.json`, with a new
 * `environment_id`; every check compares both with the hub's answer before it uses the hub.
 */
export const DEMO_LABEL = "hx-e2e-demo";
export const HOSTS_DEMO_LABEL = "hx-e2e-hosts";
/** The environment identity file in a Hypothex home (`Layout.environment_json`). */
export const IDENTITY_FILE = "environment.json";
/** How long `serve-demo.ts` waits for `hx serve` to clean up after SIGTERM before SIGKILL. */
export const SHUTDOWN_WAIT_MS = 60_000;
/** The route every Hypothex server answers without a token: its environment identity. */
export const IDENTITY_ROUTE = "/.well-known/hypothex/environment";

/** A demo home's identity: the two keys `serve-demo.ts` writes and the hub serves. */
export interface Identity {
  environment_id: string;
  label: string;
}

/** The identity `serve-demo.ts` wrote into `home`, or null while there is none. */
export function readIdentity(home: string): Identity | null {
  const file = join(home, IDENTITY_FILE);
  if (!existsSync(file)) return null;
  try {
    const raw = JSON.parse(readFileSync(file, "utf8")) as Partial<Identity>;
    if (typeof raw.environment_id !== "string" || typeof raw.label !== "string") return null;
    return { environment_id: raw.environment_id, label: raw.label };
  } catch {
    return null;
  }
}

/**
 * Whether the server at `base` answers `IDENTITY_ROUTE` with exactly `want`. Any other
 * server (an `hx serve` on the real `~/.hypothex`), no server, or an error gives false.
 */
export async function answersAs(base: string, want: Identity): Promise<boolean> {
  try {
    const response = await fetch(`${base}${IDENTITY_ROUTE}`, { signal: AbortSignal.timeout(2_000) });
    if (!response.ok) return false;
    const got = (await response.json()) as Partial<Identity>;
    return got.environment_id === want.environment_id && got.label === want.label;
  } catch {
    return false;
  }
}
```

Append to `ui/e2e/.gitignore`:

```
.home-hosts/
.home-shutdown/
.demo-hosts.json
```

- [ ] **Step 2: Let `serve-demo.ts` seed, identify and serve the hosts demo, and stop it in order**

Replace the whole of `ui/e2e/serve-demo.ts` with:

```ts
/**
 * Playwright `webServer` command: seed a fresh demo home, then serve it.
 *
 * Without arguments: wipes `e2e/.home`, writes its identity (`environment.json`: a new
 * `environment_id` and the label `DEMO_LABEL`), runs `hx demo --json` into it, writes the
 * kind → "project/task" map to `e2e/.demo.json`, then runs `hx serve` on `PORT`.
 *
 * With `--with-hosts`: the same with `hx demo --with-hosts --json` into `HOSTS_HOME_DIR`,
 * label `HOSTS_DEMO_LABEL`, output in `e2e/.demo-hosts.json`, served on `HOSTS_PORT`. Its
 * hosts are fake (env servers on this machine reached by `route: url`). `HYPOTHEX_SSH` and
 * `HYPOTHEX_SCP` are `false` for both servers, so nothing started here can open a real SSH
 * connection. `PORT` and `HOSTS_PORT` are the run's random ports (`e2e/paths.ts`).
 *
 * A child that cannot start (no `uv`, no venv `hx`, `hx demo` failing, `hx serve` not
 * spawning or exiting, e.g. on a taken port) ends this script at once with exit code 1 or
 * the child's code, so Playwright and `shutdown-check.ts` stop waiting immediately.
 *
 * Shutdown order: Playwright sends SIGTERM to this script's process group
 * (`gracefulShutdown`). `hx serve` runs in its own group (`detached`), so it does not get
 * that signal; this script forwards SIGTERM to the hub process alone and waits for it to
 * exit. The hub's ASGI lifespan shutdown, which uvicorn runs on that SIGTERM before it
 * exits (the backend plan, ruling S9), stops the demo runs over the fake gpu1 server's
 * HTTP API, then the fake hosts. Only then (or after `SHUTDOWN_WAIT_MS`) is the rest of the
 * group SIGKILLed. Killing the group first would take the fake hosts down before that
 * cleanup and orphan the demo runs' supervisors.
 */
import { type ChildProcess, spawn, spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import {
  DEMO_FILE,
  DEMO_LABEL,
  HOME_DIR,
  HOSTS_DEMO_FILE,
  HOSTS_DEMO_LABEL,
  HOSTS_HOME_DIR,
  HOSTS_PORT,
  IDENTITY_FILE,
  PORT,
  REPO_ROOT,
  SHUTDOWN_WAIT_MS,
  UI_DIST_INDEX,
} from "./paths";

const withHosts = process.argv.includes("--with-hosts");
const home = withHosts ? HOSTS_HOME_DIR : HOME_DIR;
const demoFile = withHosts ? HOSTS_DEMO_FILE : DEMO_FILE;
const port = withHosts ? HOSTS_PORT : PORT;
const label = withHosts ? HOSTS_DEMO_LABEL : DEMO_LABEL;
const env = { ...process.env, HYPOTHEX_SSH: "false", HYPOTHEX_SCP: "false" };

if (!existsSync(UI_DIST_INDEX)) {
  console.error(`missing ${UI_DIST_INDEX}: run "bun run build" in ui/ first`);
  process.exit(1);
}

/** The project venv's `hx`, so signals reach `hx serve` itself and not a `uv run` wrapper. */
function venvHx(): string {
  const found = spawnSync(
    "uv",
    ["run", "--project", REPO_ROOT, "python", "-c", "import os, sys; print(os.path.join(os.path.dirname(sys.executable), 'hx'))"],
    { cwd: REPO_ROOT, encoding: "utf8", env, stdio: ["ignore", "pipe", "inherit"] },
  );
  const path = (found.stdout ?? "").trim();
  if (found.status !== 0 || !existsSync(path)) {
    console.error(`cannot find the venv's hx (uv run exited ${found.status}, got "${path}")`);
    process.exit(1);
  }
  return path;
}

rmSync(home, { recursive: true, force: true });
mkdirSync(home, { recursive: true });
// the same two keys `load_descriptor` writes; the specs compare the hub's answer with them
writeFileSync(
  join(home, IDENTITY_FILE),
  JSON.stringify({ environment_id: randomUUID().replace(/-/g, ""), label }, null, 2),
);

const hx = venvHx();
const demoArgs = withHosts ? ["demo", "--with-hosts", "--json"] : ["demo", "--json"];
const seeded = spawnSync(hx, ["--home", home, ...demoArgs], {
  cwd: REPO_ROOT,
  encoding: "utf8",
  env,
  stdio: ["ignore", "pipe", "inherit"],
});
if (seeded.status !== 0) {
  const why = seeded.error ? seeded.error.message : `exit code ${seeded.status}`;
  console.error(`hx ${demoArgs.join(" ")} failed: ${why}`);
  process.exit(1);
}
writeFileSync(demoFile, seeded.stdout);

const server: ChildProcess = spawn(hx, ["--home", home, "serve", "--port", String(port)], {
  cwd: REPO_ROOT,
  env,
  stdio: "inherit",
  detached: true,
});
// the hub could not be spawned at all: stop now, nothing else will ever answer on the port
server.on("error", (err) => {
  console.error(`hx serve did not start: ${err.message}`);
  process.exit(1);
});
let exited = server.exitCode !== null;
server.on("exit", () => {
  exited = true;
});

/** SIGKILL whatever is left in the hub's process group (fake hosts of a hub that died). */
function killGroup(): void {
  if (server.pid === undefined) return;
  try {
    process.kill(-server.pid, "SIGKILL");
  } catch {
    // the group is already gone
  }
}

let stopping = false;
/** SIGTERM the hub alone, wait for its lifespan cleanup and exit, then clear the group. */
async function stop(): Promise<void> {
  if (stopping) return;
  stopping = true;
  if (server.pid !== undefined && !exited) {
    try {
      process.kill(server.pid, "SIGTERM");
    } catch {
      // already gone
    }
    const deadline = Date.now() + SHUTDOWN_WAIT_MS;
    while (!exited && Date.now() < deadline) await new Promise((resolve) => setTimeout(resolve, 200));
    if (!exited) console.error(`hx serve did not exit within ${SHUTDOWN_WAIT_MS} ms; killing its group`);
  }
  killGroup();
  process.exit(0);
}
process.on("SIGINT", () => void stop());
process.on("SIGTERM", () => void stop());
// the hub ended by itself (failed start, crash or Ctrl-C): clear what it left, keep its exit code
server.on("exit", (code) => {
  if (stopping) return;
  killGroup();
  process.exit(code ?? 1);
});
```

- [ ] **Step 3: Check the hub's identity before every test**

In `ui/e2e/fixtures.ts`, replace

```ts
import { readFileSync } from "node:fs";
import { type APIRequestContext, test as base, expect, type Page } from "@playwright/test";
import { DEMO_FILE, type Kind } from "./paths";
```

with

```ts
import { readFileSync } from "node:fs";
import { type APIRequestContext, test as base, expect, type Page } from "@playwright/test";
import {
  DEMO_FILE,
  DEMO_LABEL,
  HOME_DIR,
  HOSTS_DEMO_LABEL,
  HOSTS_HOME_DIR,
  HOSTS_PORT,
  IDENTITY_FILE,
  IDENTITY_ROUTE,
  type Kind,
  PORT,
  readIdentity,
} from "./paths";
```

Replace

```ts
interface Fixtures {
  consoleErrors: string[];
}
```

with

```ts
interface Fixtures {
  consoleErrors: string[];
  isolatedHub: void;
}

/**
 * The hubs this suite starts itself: base URL → the fresh home and the label it wrote.
 * `PORT` and `HOSTS_PORT` are this run's random ports (every worker reads the same ones).
 */
const OWN_HUBS: Record<string, { home: string; label: string }> = {
  [`http://127.0.0.1:${PORT}`]: { home: HOME_DIR, label: DEMO_LABEL },
  [`http://127.0.0.1:${HOSTS_PORT}`]: { home: HOSTS_HOME_DIR, label: HOSTS_DEMO_LABEL },
};

/**
 * Fail unless `baseURL` is a demo hub this run started: it must answer with the
 * `environment_id` and label that `serve-demo.ts` wrote into its fresh home. Any other
 * server (an `hx serve` the user left running, possibly on the real `~/.hypothex`) fails
 * here, before a spec reads a host route, posts a note or launches a run through it.
 */
export async function expectIsolatedHub(request: APIRequestContext, baseURL: string | undefined): Promise<void> {
  const own = baseURL === undefined ? undefined : OWN_HUBS[baseURL];
  if (own === undefined) throw new Error(`${baseURL ?? "no baseURL"} is not a demo hub this run started`);
  const wanted = readIdentity(own.home);
  expect(wanted?.label, `${own.home}/${IDENTITY_FILE} was not written by serve-demo.ts`).toBe(own.label);
  const response = await request.get(IDENTITY_ROUTE);
  expect(response.status(), `GET ${baseURL}${IDENTITY_ROUTE}`).toBe(200);
  const got = (await response.json()) as { environment_id: string; label: string };
  expect([got.environment_id, got.label], `${baseURL} is not the isolated demo hub`).toEqual([
    wanted?.environment_id,
    own.label,
  ]);
}
```

and in `base.extend`, replace

```ts
  consoleErrors: [
    async ({ page }, use) => {
```

with

```ts
  isolatedHub: [
    async ({ request, baseURL }, use) => {
      await expectIsolatedHub(request, baseURL);
      await use();
    },
    { auto: true },
  ],
  consoleErrors: [
    async ({ page }, use) => {
```

- [ ] **Step 4: Add the hosts server and projects to `playwright.config.ts`**

Replace the whole of `ui/playwright.config.ts` with:

```ts
import { defineConfig, devices } from "@playwright/test";
import type { ThemeOptions } from "./e2e/fixtures";
// Loading paths.ts picks this run's two free ports and puts them in process.env, which the
// workers and both web servers inherit (never a fixed port, ruling S1).
import { HOSTS_PORT, IDENTITY_ROUTE, PORT } from "./e2e/paths";

const WRITES = /(editor|live)\.spec\.ts$/;
/** Specs against the `hx demo --with-hosts` hub; `launch` starts runs, so it runs last. */
const HOSTS_READS = /hosts\.spec\.ts$/;
const HOSTS_WRITES = /launch\.spec\.ts$/;
const HOSTS_URL = `http://127.0.0.1:${HOSTS_PORT}`;
/**
 * SIGTERM, then SIGKILL after 90 s: `serve-demo.ts` forwards the SIGTERM to `hx serve`,
 * whose lifespan shutdown stops the demo runs and fake hosts (its own wait is 60 s).
 * Without this Playwright SIGKILLs the group at once.
 */
const GRACEFUL = { signal: "SIGTERM", timeout: 90_000 } as const;

export default defineConfig<ThemeOptions>({
  testDir: "./e2e",
  outputDir: "./e2e/.results",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI
    ? [["list"], ["html", { outputFolder: "./e2e/.report", open: "never" }]]
    : [["list"]],
  expect: { timeout: 10_000 },
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "light",
      testIgnore: [WRITES, HOSTS_READS, HOSTS_WRITES],
      use: { ...devices["Desktop Chrome"], colorScheme: "light", theme: "light" },
    },
    {
      name: "dark",
      testIgnore: [WRITES, HOSTS_READS, HOSTS_WRITES],
      use: { ...devices["Desktop Chrome"], colorScheme: "dark", theme: "dark" },
    },
    {
      name: "light-edit",
      testMatch: WRITES,
      dependencies: ["light", "dark"],
      use: { ...devices["Desktop Chrome"], colorScheme: "light", theme: "light" },
    },
    {
      // Runs after light-edit (not just light/dark): live.spec.ts posts a note to the
      // same shared demo run from both edit projects, and the Notes panel shows only the
      // newest one, so the two projects must not write to it at the same time.
      name: "dark-edit",
      testMatch: WRITES,
      dependencies: ["light", "dark", "light-edit"],
      use: { ...devices["Desktop Chrome"], colorScheme: "dark", theme: "dark" },
    },
    {
      name: "hosts-light",
      testMatch: HOSTS_READS,
      use: { ...devices["Desktop Chrome"], baseURL: HOSTS_URL, colorScheme: "light", theme: "light" },
    },
    {
      name: "hosts-dark",
      testMatch: HOSTS_READS,
      use: { ...devices["Desktop Chrome"], baseURL: HOSTS_URL, colorScheme: "dark", theme: "dark" },
    },
    {
      // Launches add queued runs to a fake host, so they wait for the read-only specs.
      name: "hosts-light-edit",
      testMatch: HOSTS_WRITES,
      dependencies: ["hosts-light", "hosts-dark"],
      use: { ...devices["Desktop Chrome"], baseURL: HOSTS_URL, colorScheme: "light", theme: "light" },
    },
    {
      name: "hosts-dark-edit",
      testMatch: HOSTS_WRITES,
      dependencies: ["hosts-light", "hosts-dark", "hosts-light-edit"],
      use: { ...devices["Desktop Chrome"], baseURL: HOSTS_URL, colorScheme: "dark", theme: "dark" },
    },
  ],
  // Both ports are random per run. Never reuse a server that answers on one anyway: an
  // `hx serve` there may run on the real ~/.hypothex, and live.spec.ts posts notes
  // (forwarded to real hosts in phase 2) and launch.spec.ts starts runs. Playwright fails at
  // start instead, a web server whose command exits stops the run at once, and every test
  // checks the hub's identity first (`isolatedHub` in e2e/fixtures.ts).
  webServer: [
    {
      command: "bun e2e/serve-demo.ts",
      url: `http://127.0.0.1:${PORT}${IDENTITY_ROUTE}`,
      reuseExistingServer: false,
      gracefulShutdown: GRACEFUL,
      timeout: 180_000,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: "bun e2e/serve-demo.ts --with-hosts",
      url: `${HOSTS_URL}${IDENTITY_ROUTE}`,
      reuseExistingServer: false,
      gracefulShutdown: GRACEFUL,
      timeout: 180_000,
      stdout: "pipe",
      stderr: "pipe",
    },
  ],
});
```

- [ ] **Step 5: Write the hosts helpers**

Create `ui/e2e/hosts-fixtures.ts`:

```ts
/** Helpers for the specs that run against the `hx demo --with-hosts` hub (fake hosts). */
import type { APIRequestContext } from "@playwright/test";
import { expect, getJson } from "./fixtures";

export interface GpuLite {
  index: number;
  run_id: string | null;
  external: boolean;
}
export interface HostLite {
  name: string;
  kind: "local" | "ssh" | "slurm";
  state: { state: string; environment_id: string | null };
  gpus: GpuLite[];
  queue: number;
  projects: string[];
}
export interface ExecutorLite {
  host?: string | null;
  gpus?: number[];
  slurm_job_id?: string | null;
  queue_position?: number | null;
}
export interface RecordLite {
  run_id: string;
  project: string;
  environment_id: string;
  hypothesis: string;
  status: string;
  /** `executor.host` is the env server's own hostname, not the hub's name for the host. */
  executor: ExecutorLite;
}
export interface TaskLite {
  name: string;
}
export interface SweepItemLite {
  id: string;
  n_runs: number;
}
export interface SweepLite {
  headline: string;
  /** The sweep's runs, derived by the hub from the runs tagged `tag` (not in the spec). */
  run_ids: string[];
  spec: { id: string; project: string };
}

/** `/api/v1/hosts` once every host is connected (the hub connects to them at start). */
export async function connectedHosts(request: APIRequestContext): Promise<HostLite[]> {
  let hosts: HostLite[] = [];
  await expect
    .poll(
      async () => {
        const response = await request.get("/api/v1/hosts");
        if (!response.ok()) return false;
        hosts = (await response.json()) as HostLite[];
        return hosts.length > 1 && hosts.every((h) => h.state.state === "connected");
      },
      { timeout: 60_000, message: "the demo hosts never all connected" },
    )
    .toBe(true);
  return hosts;
}

/** The fake remote hosts: every row except the hub itself (`local`). */
export function remoteHosts(hosts: HostLite[]): HostLite[] {
  return hosts.filter((h) => h.name !== "local");
}

/**
 * The host a run is on, matched by `environment_id` as the UI matches it (`hostRowForRun`).
 * Never `executor.host`: on a real host it is the machine's hostname (the demo happens to
 * use the host name as its label, so a spec reading it would pass here and fail for real).
 */
export function hostOfRun(hosts: HostLite[], run: RecordLite): HostLite | undefined {
  return hosts.find((h) => h.state.environment_id !== null && h.state.environment_id === run.environment_id);
}

/** The first sweep of the first project that has one. */
export async function firstSweep(request: APIRequestContext): Promise<{ project: string; id: string }> {
  const projects = await getJson<{ project: string }[]>(request, "/api/v1/projects");
  for (const { project } of projects) {
    const sweeps = await getJson<SweepItemLite[]>(
      request,
      `/api/v1/projects/${encodeURIComponent(project)}/sweeps`,
    );
    const first = sweeps[0];
    if (first) return { project, id: first.id };
  }
  throw new Error("hx demo --with-hosts seeded no sweep");
}
```

- [ ] **Step 6: Write the read-only specs**

Create `ui/e2e/hosts.spec.ts`:

```ts
import { expect, expectTheme, getJson, test } from "./fixtures";
import {
  connectedHosts,
  firstSweep,
  hostOfRun,
  type RecordLite,
  remoteHosts,
  type SweepLite,
} from "./hosts-fixtures";

test("the Overview Hosts panel lists every fake host", async ({ page, request, theme }) => {
  const hosts = remoteHosts(await connectedHosts(request));
  expect(hosts.some((h) => h.kind === "slurm")).toBe(true);
  expect(hosts.some((h) => h.kind === "ssh" && h.gpus.length > 0)).toBe(true);

  await page.goto("/");
  await expectTheme(page, theme);
  const panel = page.getByRole("region", { name: "a Hosts" });
  await expect(panel).toBeVisible();
  for (const host of hosts) {
    await expect(panel.getByText(host.name, { exact: true }).first()).toBeVisible();
  }
});

test("the sweep page renders the demo sweep", async ({ page, request, theme }) => {
  await connectedHosts(request);
  const { project, id } = await firstSweep(request);
  const path = `${encodeURIComponent(project)}/${encodeURIComponent(id)}`;
  const summary = await getJson<SweepLite>(request, `/api/v1/sweeps/${path}`);
  expect(summary.spec.id).toBe(id);
  expect(summary.run_ids.length).toBeGreaterThan(0);

  await page.goto(`/s/${path}`);
  await expectTheme(page, theme);
  await expect(page.getByText(summary.headline).first()).toBeVisible();
  for (const name of ["Copy as CLI", "Cancel queued", "Add seeds"]) {
    await expect(page.getByRole("button", { name })).toBeVisible();
  }
});

test("a queued remote run shows its place in the host queue", async ({ page, request, theme }) => {
  const hosts = remoteHosts(await connectedHosts(request));
  const queued = await getJson<RecordLite[]>(request, "/api/v1/runs?status=queued&limit=500");
  const run = queued.find((r) => r.executor.queue_position && hostOfRun(hosts, r));
  const host = run ? hostOfRun(hosts, run)?.name : undefined;
  if (!run || !host) throw new Error("hx demo --with-hosts has no queued run on an ssh host");

  await page.goto(`/r/${run.run_id}`);
  await expectTheme(page, theme);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    new RegExp(`queued \\d+(st|nd|rd|th) on ${host}$`),
  );
  const queue = page.getByRole("region", { name: "a Queue" });
  await expect(queue).toBeVisible();
  await expect(queue.locator('tr[aria-current="true"]')).toContainText(run.run_id.split("-").pop() ?? "");
  await expect(page.getByRole("region", { name: /Placement$/ })).toContainText(host);
});

test("a running remote run shows its host and CUDA_VISIBLE_DEVICES", async ({ page, request, theme }) => {
  const hosts = remoteHosts(await connectedHosts(request));
  const running = await getJson<RecordLite[]>(request, "/api/v1/runs?status=running&limit=500");
  const run = running.find((r) => (r.executor.gpus ?? []).length > 0 && hostOfRun(hosts, r));
  const host = run ? hostOfRun(hosts, run)?.name : undefined;
  if (!run || !host) throw new Error("hx demo --with-hosts has no running run holding GPUs");

  await page.goto(`/r/${run.run_id}`);
  await expectTheme(page, theme);
  const placement = page.getByRole("region", { name: /Placement$/ });
  await expect(placement).toContainText(host);
  await expect(placement).toContainText(`CUDA_VISIBLE_DEVICES=${(run.executor.gpus ?? []).join(",")}`);
  await expect(page.locator(".status")).toContainText(host);
});
```

- [ ] **Step 7: Write the launch spec**

Create `ui/e2e/launch.spec.ts`:

```ts
import { expect, expectTheme, getJson, test } from "./fixtures";
import { connectedHosts, type RecordLite, remoteHosts, type TaskLite } from "./hosts-fixtures";

test("the launch dialog starts a run on a fake host", async ({ page, request, theme }) => {
  const hosts = remoteHosts(await connectedHosts(request));
  const host = hosts.find((h) => h.kind === "ssh" && h.projects.length > 0);
  const project = host?.projects[0];
  if (!host || !project) throw new Error("hx demo --with-hosts has no ssh host with a mapped project");
  const tasks = await getJson<TaskLite[]>(request, `/api/v1/tasks?project=${encodeURIComponent(project)}`);
  const task = tasks[0]?.name;
  if (!task) throw new Error(`demo project ${project} has no task`);
  const hypothesis = `e2e launch ${theme} ${Date.now()}`;

  await page.goto(`/t/${encodeURIComponent(project)}/${encodeURIComponent(task)}`);
  await expectTheme(page, theme);
  await page.getByRole("button", { name: "New run" }).click();
  const dialog = page.getByRole("dialog", { name: /New run/ });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("radio", { name: new RegExp(`^${host.name}\\b`) }).check();
  await dialog.getByLabel(/wait for GPUs/).setChecked(true);
  await dialog.getByLabel("Seeds").fill("7");
  await dialog.getByLabel("Command").fill("echo hx-e2e {seed}");
  await dialog.getByLabel("Hypothesis").fill(hypothesis);
  await dialog.getByRole("button", { name: /^Launch/ }).click();

  // The hub forwards the launch to the host and mirrors the run back. (A holder object,
  // because TypeScript does not see assignments made inside the poll callback.)
  const found: { run?: RecordLite } = {};
  await expect
    .poll(
      async () => {
        const runs = await getJson<RecordLite[]>(
          request,
          `/api/v1/runs?project=${encodeURIComponent(project)}&limit=500`,
        );
        found.run = runs.find((r) => r.hypothesis === hypothesis);
        return found.run?.run_id ?? null;
      },
      { timeout: 30_000, message: "the launched run never reached the hub" },
    )
    .not.toBeNull();
  const made = found.run;
  if (!made) throw new Error("the launched run is missing after the poll");
  const detail = await getJson<{ record: RecordLite }>(request, `/api/v1/runs/${made.run_id}`);
  // the run belongs to the host's environment (executor.host is the machine's hostname)
  expect(detail.record.environment_id).toBe(host.state.environment_id);

  await page.goto(`/r/${made.run_id}`);
  await expectTheme(page, theme);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(hypothesis);
  await expect(page.getByRole("region", { name: /Placement$/ })).toContainText(host.name);

  // leave the fake host's queue as it was
  const stopped = await request.post(`/api/v1/runs/${made.run_id}/stop`, { data: {} });
  expect(stopped.status()).toBe(200);
});
```

- [ ] **Step 8: Write the shutdown-order regression check**

Create `ui/e2e/shutdown-check.ts`:

```ts
/**
 * Regression check for the shutdown order of `serve-demo.ts --with-hosts`. Run it alone,
 * never next to Playwright: `bun e2e/shutdown-check.ts` (from ui/, after `bun run build`).
 *
 * It starts the hosts demo on a port the OS reports free (never a fixed one) and its own
 * home (`e2e/.home-shutdown`, wiped first). Before it reads any host or run route it waits
 * until the hub on that port answers with the identity `serve-demo.ts` wrote into that home,
 * so it can never query another `hx serve` (one on the real `~/.hypothex` would list the
 * user's real hosts). If `serve-demo.ts` cannot start or exits while it waits, it fails at
 * once. Then it waits until the fake hosts are connected and a demo run runs on one, and
 * sends SIGTERM to the web server's process group, as Playwright's `gracefulShutdown` does.
 * `serve-demo.ts` forwards it to the hub alone; the hub's ASGI lifespan shutdown stops the
 * demo runs, then the fake hosts. The check fails if any process of that home is left
 * afterwards: the hub, a fake host's `hx serve`, or a demo run's supervisor (its `--home`
 * lies under the demo home). Killing the fake hosts before the hub's cleanup leaves exactly
 * those supervisors behind.
 */
import { spawn, spawnSync } from "node:child_process";
import { rmSync } from "node:fs";
import { join } from "node:path";
import { answersAs, E2E_DIR, freePort, HOSTS_DEMO_LABEL, type Identity, readIdentity, SHUTDOWN_WAIT_MS } from "./paths";

const PORT = freePort();
const HOME = join(E2E_DIR, ".home-shutdown");
const BASE = `http://127.0.0.1:${PORT}`;

interface HostLite {
  name: string;
  state: { state: string; environment_id: string | null };
}

// a stale identity file of an earlier check must never vouch for another server
rmSync(HOME, { recursive: true, force: true });

const child = spawn("bun", ["e2e/serve-demo.ts", "--with-hosts"], {
  env: { ...process.env, HX_E2E_HOSTS_PORT: String(PORT), HX_E2E_HOSTS_HOME: HOME },
  stdio: "inherit",
  detached: true,
});
let startError: Error | null = null;
child.on("error", (err) => {
  startError = err;
});
const ended = (): boolean => startError !== null || child.exitCode !== null || child.signalCode !== null;

/** Throw at once when `serve-demo.ts` failed to start or has exited: nothing will answer. */
function stillUp(what: string): void {
  if (startError !== null) throw new Error(`serve-demo.ts did not start (${startError.message}); was waiting for ${what}`);
  if (ended()) {
    throw new Error(`serve-demo.ts exited (code ${child.exitCode}, signal ${child.signalCode}); was waiting for ${what}`);
  }
}

/** Poll `ok` every 500 ms until it holds, or throw after `ms`; `live` also requires the demo to run. */
async function waitUntil(what: string, ok: () => Promise<boolean> | boolean, ms: number, live = true): Promise<void> {
  const deadline = Date.now() + ms;
  while (Date.now() < deadline) {
    if (live) stillUp(what);
    if (await ok()) return;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`timed out after ${ms} ms waiting for ${what}`);
}

/** Set once the hub on `PORT` proved it serves `HOME`; no other route is read before. */
let verified: Identity | null = null;

async function getJson<T>(path: string): Promise<T | null> {
  if (verified === null) throw new Error(`refusing GET ${path}: the hub on ${PORT} is not verified yet`);
  try {
    const response = await fetch(`${BASE}${path}`);
    return response.ok ? ((await response.json()) as T) : null;
  } catch {
    return null;
  }
}

/**
 * `pid command` of every process whose command line names the check's home (`ps` gives
 * full command lines on macOS and Linux alike; this script's own command line does not
 * name the home).
 */
function leftovers(): string[] {
  const out = spawnSync("ps", ["-axo", "pid=,command="], { encoding: "utf8" });
  return out.stdout.split("\n").filter((line) => line.includes(HOME));
}

let failure: string | null = null;
try {
  await waitUntil(
    `the hub on ${PORT} to answer with the identity of ${HOME}`,
    async () => {
      const want = readIdentity(HOME);
      if (want === null || want.label !== HOSTS_DEMO_LABEL || !(await answersAs(BASE, want))) return false;
      verified = want;
      return true;
    },
    180_000,
  );
  let remote: HostLite[] = [];
  await waitUntil(
    "the fake hosts to connect",
    async () => {
      const hosts = (await getJson<HostLite[]>("/api/v1/hosts")) ?? [];
      remote = hosts.filter((h) => h.name !== "local");
      return remote.length > 0 && hosts.every((h) => h.state.state === "connected");
    },
    180_000,
  );
  const envs = new Set(remote.map((h) => h.state.environment_id));
  await waitUntil(
    "a demo run running on a fake host",
    async () => {
      const runs = (await getJson<{ environment_id: string }[]>("/api/v1/runs?status=running&limit=50")) ?? [];
      return runs.some((r) => envs.has(r.environment_id));
    },
    60_000,
  );
  const before = leftovers();
  if (!before.some((line) => line.includes("hypothex.core.supervisor"))) {
    throw new Error(`no demo supervisor runs before the stop, so the check would prove nothing:\n${before.join("\n")}`);
  }
  // what Playwright's gracefulShutdown does: SIGTERM to the web server's process group
  process.kill(-(child.pid as number), "SIGTERM");
  await waitUntil("serve-demo.ts to exit", ended, SHUTDOWN_WAIT_MS + 30_000, false);
  // a stopped supervisor writes its record and exits; give it a moment
  await new Promise((resolve) => setTimeout(resolve, 3_000));
  const left = leftovers();
  if (left.length > 0) failure = `left running after the stop:\n${left.join("\n")}`;
} catch (err) {
  failure = err instanceof Error ? err.message : String(err);
} finally {
  if (!ended() && child.pid !== undefined) {
    try {
      process.kill(-child.pid, "SIGKILL");
    } catch {
      // already gone
    }
  }
  spawnSync("pkill", ["-9", "-f", HOME]);
  rmSync(HOME, { recursive: true, force: true });
}
if (failure !== null) {
  console.error(`shutdown-check FAILED: ${failure}`);
  process.exit(1);
}
console.log("shutdown-check ok: the hub stopped its demo runs and fake hosts; nothing of the demo home is left");
```

- [ ] **Step 9: Type-check the e2e sources**

Run: `bunx tsc --noEmit -p e2e/tsconfig.json && bun run typecheck`
Expected: no output from either.

- [ ] **Step 10: Run the hosts projects (they fail until the backend demo and the pages of Tasks 5-21 exist)**

Run: `bun run build && bunx playwright test --project=hosts-light --project=hosts-dark --project=hosts-light-edit --project=hosts-dark-edit`
Expected: `10 passed` (4 read specs × 2 themes, 1 launch spec × 2 themes). Both web servers start, each on a random port (the log shows `hx serve` with `--port <random>`), and no `ssh` process is started (`HYPOTHEX_SSH=false`). If Playwright stops at start because a web server exited, read its log (a failed `hx demo`, a missing build, a port taken between the pick and the bind): it is never retried against another server. If every test fails in the `isolatedHub` fixture with `… is not the isolated demo hub`, the server on that port is not the one `serve-demo.ts` just seeded: find and stop it (never set `reuseExistingServer`, never pin a port).

If a spec fails with `hx demo --with-hosts has no …`, the backend plan's demo is missing that piece of contract section 5; fix the demo, not the spec.

Then check that nothing from the hosts hub outlived the run (the hub, the fake hosts' `hx serve` processes it started, and the demo runs' supervisors all have `e2e/.home-hosts` on their command line):

Run: `pgrep -fl "e2e/[.]home-hosts" || echo none`
Expected: `none`. (The `[.]` keeps the pattern from matching the shell that runs `pgrep`, whose own command line holds the text.) If a pid is listed, the stop order in `serve-demo.ts` is broken; fix `stop()` there and kill the listed processes (do not leave them running).

- [ ] **Step 11: Check the shutdown order on its own**

Run: `bun run build && bun e2e/shutdown-check.ts`
Expected: last line `shutdown-check ok: the hub stopped its demo runs and fake hosts; nothing of the demo home is left`, exit 0. This sends a real SIGTERM to the hub, so it is the regression for the backend's lifespan cleanup too.

To see that it catches the ordering bug, temporarily change `stop()` in `serve-demo.ts` to start with `killGroup()` (the whole group at once, fake hosts included): the check then exits 1 with `left running after the stop:` and a `hypothex.core.supervisor` line. Put `stop()` back.

To see that it aborts at once when a child fails to start, temporarily make `venvHx()` in `serve-demo.ts` return `"/nonexistent/hx"`: the check exits 1 within a few seconds (not after its 180 s wait) with `serve-demo.ts exited (code 1, signal null); was waiting for the hub on <port> to answer with the identity of …`, and it never reads `/api/v1/hosts`. Put `venvHx()` back and run the check again (exit 0).

- [ ] **Step 12: Run the whole e2e suite**

Run: `bun run e2e && (pgrep -fl "e2e/[.]home" || echo none)`
Expected: `42 passed` (the 32 phase 1b tests in `light`, `dark`, `light-edit`, `dark-edit`, plus the 10 hosts tests), `0 failed`, then `none` (no demo server, fake host or demo supervisor left running).

- [ ] **Step 13: Document the e2e servers**

Append to `ui/README.md`:

````markdown

### End-to-end tests

`bun run e2e` builds the UI and runs Playwright against two demo hubs that it starts
itself (`e2e/serve-demo.ts`):

- `hx demo`, every task kind; projects `light`, `dark`, `light-edit`, `dark-edit`.
- `hx demo --with-hosts`, fake remote hosts with GPUs, a queue, a SLURM host and a sweep;
  projects `hosts-light`, `hosts-dark`, `hosts-light-edit`, `hosts-dark-edit`.

Each listens on a port the OS reports free for that run (never a fixed port, so a test can
never land on an `hx serve` you left running on your real `~/.hypothex`). Both run with
`HYPOTHEX_SSH=false` and `HYPOTHEX_SCP=false`, so no test can reach a real host, and
neither is ever reused from a server that already answers. Every test first checks that the
hub answers with the identity `serve-demo.ts` wrote into its fresh home (`environment.json`,
labels `hx-e2e-demo` and `hx-e2e-hosts`), so no host route, note or launch can reach
another server. If a demo server cannot start, the run stops at once. Run one group with
`--project`:

```bash
bun run build && bunx playwright test --project=hosts-light --project=hosts-dark
```

On stop, `serve-demo.ts` sends SIGTERM to the hub alone and waits for it: the hub's
shutdown stops the demo runs on its fake hosts, then the fake hosts. `bun e2e/shutdown-check.ts`
checks that order on its own random port, after it has verified the hub's identity, and
fails if any demo process is left.
````

- [ ] **Step 14: Commit (repo root)**

```bash
git add ui/e2e/paths.ts ui/e2e/serve-demo.ts ui/e2e/fixtures.ts ui/e2e/.gitignore ui/e2e/hosts-fixtures.ts ui/e2e/hosts.spec.ts ui/e2e/launch.spec.ts ui/e2e/shutdown-check.ts ui/playwright.config.ts ui/README.md
git commit -m "test(ui): e2e for hosts, launch, sweep and run states; isolated demo hubs, ordered shutdown"
```

---

---

### Task 29: Docs: the phase 2 screens in `docs/ui.rst`

**Files:**
- Modify: `docs/ui.rst` (Screens: Overview, Task and Run bullets, three new bullets; Test: one paragraph)
- Test: `tests/test_docs_ui.py` (one new test)

**Interfaces:**
- Consumes: the screens of Tasks 5–28 by their visible names; `docs/remote.rst` (the backend plan; hosts, `environments.yaml`, `hx hosts`), referenced as ``:doc:`remote` ``.
- Produces: `docs/ui.rst` names the Hosts panel, the Launch dialog, the Sweep page and the remote run states, and how the `hosts-*` Playwright projects stay away from real hosts.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_docs_ui.py`:

```python


def test_ui_page_covers_phase2_screens() -> None:
    page = (DOCS / "ui.rst").read_text()
    for screen in ("Hosts", "Launch dialog", "Sweep"):
        assert f"**{screen}**" in page, screen
    for text in (
        "/s/<project>/<sweep_id>",
        "Copy as CLI",
        "Cancel queued",
        "Add seeds",
        "Rerun sweep",
        "wait for GPUs",
        "CUDA_VISIBLE_DEVICES",
        "stale",
        "stale_banner_hours",
        "GPU-h",
        ":doc:`remote`",
        "hx demo --with-hosts",
        "free port",
        "HYPOTHEX_SSH=false",
        "environment.json",
        "run.lost",
        "shutdown-check.ts",
    ):
        assert text in page, text
```

- [ ] **Step 2: Run it to verify it fails**

Run (repo root): `uv run pytest tests/test_docs_ui.py -v`
Expected: `test_ui_page_covers_phase2_screens` FAILS with `AssertionError: Hosts`; the two phase 1b tests pass.

- [ ] **Step 3: Document the screens**

In `docs/ui.rst`, replace

```rst
- **Overview** (``/``): one-line status, runs by launcher, ideas, running runs, recent
  failures (with ``Open stderr``), and projects. Ideas are grouped by task, and each task
  has its own x axis, because tasks use different metrics.
- **Task** (``/t/<project>/<task>?view=<name>``): the task's views as tabs. ``overview``
  is the preset for the task kind; every other tab is a saved view (see :doc:`views`).
  ``+ view`` opens the view editor.
- **Run** (``/r/<run_id>``): the hypothesis as title, status, stat strip, the task kind's
  run panels, where everything is (code, data, run folder, logs, predictions,
  checkpoints), scores by metric version, notes, and actions. ``?log=stderr`` opens a log
  tail; ``?example=<id>`` picks a traced example on agent tasks.
```

with

```rst
- **Overview** (``/``): one-line status, hosts, runs by launcher, ideas, running runs,
  recent failures (with ``Open stderr``), and projects. Ideas are grouped by task, and
  each task has its own x axis, because tasks use different metrics. With hosts in
  ``environments.yaml`` (see :doc:`remote`), the headline counts running and waiting runs
  and names stale hosts, for example ``12 running, 11 waiting. dgx stale 4m``. A host
  unreachable for longer than ``stale_banner_hours`` (top level in ``environments.yaml``,
  default 24) gets a banner (``dgx unreachable 1d``); its runs stay ``stale``, never
  ``lost``. Cost today counts every run, the hub's own too.
- **Hosts** (Overview panel a): the hub itself (``local``, chip ``hub``), then one row per
  host with its state, its hx version (``≠`` when it differs from the hub's), one cell per
  GPU (agent run, human run, free, not hx), SLURM running and pending jobs, queue length,
  ``$/GPU-h`` and cost today. GPU use refreshes every 10 s. The hub reports GPUs only for a
  connected host; when a host goes stale the page keeps the cells it last saw, greyed, with
  ``as of HH:MM`` (a page opened after the host went stale has none to show).
- **Task** (``/t/<project>/<task>?view=<name>``): the task's views as tabs. ``overview``
  is the preset for the task kind; every other tab is a saved view (see :doc:`views`).
  ``+ view`` opens the view editor; ``New run`` opens the Launch dialog. The project's
  sweeps are listed under the tabs, each with its run count and best config, linking its
  Sweep page. Each leaderboard group shows its cost: dollars, GPU-h and agent time
  (``$6.51 · 11 GPU-h · 4m 10s``), with GPU and API dollars in the tooltip.
- **Launch dialog** (``New run`` on a Task page, ``Rerun sweep`` on a Sweep page): pick a
  host (the hub first, then every host with its free GPUs, queue and state; a host that is
  stale, still installing hx, or has no path for the project is disabled and says why),
  GPUs per run and ``wait for GPUs`` (SSH hosts) or partition, time and account (SLURM
  hosts; a blank field keeps the host's default from ``environments.yaml``), seeds
  (``4, 5, 6`` or ``1-3``), the command with ``{seed}``, and a required hypothesis. The
  preview shows the first seed's command as it will run. ``Copy as CLI`` copies the same
  ``hx launch`` lines. ``Launch N`` starts one run per seed; a double click still starts
  each seed once, and after a refused seed ``Launch`` sends only the seeds that did not
  start (and needs free GPUs only for those); the preview and ``Copy as CLI`` then show
  only those seeds too, so pasted lines never start a seed twice. A launch on a host names the project; the
  hub pins the code (its checkout's commit and uncommitted diff), and ``Rerun sweep`` pins
  the template run's commit when that run had no uncommitted changes.
- **Sweep** (``/s/<project>/<sweep_id>``): the best cell and its score as the headline,
  progress, cost and ETA, a params × metric heat table (a sortable table for one param,
  more than two, or sampled ranges), seed dots with 95% intervals (dots only from the
  cell's own runs), and the sweep's runs on their hosts. Actions: ``Copy as CLI`` (the same ``hx sweep``), ``Cancel queued``,
  ``Add seeds`` (new seeds for every cell), and ``Rerun sweep`` (the best cell again, in
  the Launch dialog).
- **Run** (``/r/<run_id>``): the hypothesis as title, status, stat strip, the task kind's
  run panels, where everything is (code, data, run folder, logs, predictions,
  checkpoints), scores by metric version, notes, and actions. ``?log=stderr`` opens a log
  tail; ``?example=<id>`` picks a traced example on agent tasks. A run on a host also
  shows where it runs (host, ``CUDA_VISIBLE_DEVICES``, SLURM job and node), its place in
  the host queue while it waits, ``stale`` with the time since the hub last heard from the
  host (never ``lost``: only the host decides that), why it was lost (the reason
  from its ``run.lost`` event when the page saw that event, else what the record says: job,
  node, end time, exit code), and its cost. The Queue panel lists the host's whole queue.
```

Then replace

```rst
``bunx playwright test`` seeds a fresh demo home in ``ui/e2e/.home`` with ``hx demo``
and serves it with ``hx serve`` on port 7788 (``HX_E2E_PORT`` changes it), so it never
touches your own ``~/.hypothex``.
```

with

```rst
``bunx playwright test`` seeds a fresh demo home in ``ui/e2e/.home`` with ``hx demo``
and serves it with ``hx serve`` on a free port the OS picks for that run (never a fixed
port, so it can never meet an ``hx serve`` you left running), so it never touches your own
``~/.hypothex``.

The ``hosts-*`` projects run against a second demo hub, seeded in ``ui/e2e/.home-hosts``
with ``hx demo --with-hosts`` (fake hosts that run on this machine), on its own free port.
Both demo servers run with ``HYPOTHEX_SSH=false`` and ``HYPOTHEX_SCP=false``, so no test
can reach a real host. Playwright never reuses a server that already answers, stops at once
when a demo server cannot start, and every test first checks that the hub answers with the
identity written into its fresh home (``environment.json``), so no host route, note or
launch can reach another server. ``bun e2e/shutdown-check.ts`` stops the hosts demo with
SIGTERM, as Playwright does, and fails if a demo run or fake host is left running.
```

- [ ] **Step 4: Run the docs tests and build the docs**

Run (repo root): `uv run pytest tests/test_docs_ui.py -v`
Expected: `3 passed`.

Run (repo root): `uv run sphinx-build -b html docs docs/_build/html 2>&1 | grep -E "ui\.rst.*(WARNING|ERROR)" | wc -l`
Expected: `0` (``:doc:`remote` `` resolves once the backend plan's `docs/remote.rst` is merged).

- [ ] **Step 5: Commit**

```bash
git add docs/ui.rst tests/test_docs_ui.py
git commit -m "docs: hosts panel, launch dialog, sweep page and remote run states"
```

---

## Assembly notes

This plan was assembled from five group drafts (F1–F5, now Groups 1–5). Where drafts disagreed, the contract decided; where the contract is silent, the owner of the shared piece (Group 1 for the API layer) decided.

1. **One data layer.** Group 3's `launchApi.ts` had its own route table (`LAUNCH_ROUTES`, cast to the client's `Route` type), called `request` directly, and wrote `command_id` / `created_by` into its bodies, next to Group 1's `api.launch` and `api.launchOnHost`. Task 11 now calls `api.hosts`, `api.gpus`, `api.queue`, `api.launch` and `api.launchOnHost`; `launchBody` became `launchRequest` (the body without the action fields, typed `HostLaunchRequest`), and its route-check test was dropped because Task 2's `types.ts` test checks every `ROUTES` entry. For that, `GET /api/v1/gpus` and `GET /api/v1/queue` (contract 2, env routes the hub also serves for its own runs) moved into Task 2 (`ROUTES.gpus|queue`, `api.gpus`, `api.queue`, one new test), and `QueueEntry` into Task 1. Group 3's `HOSTS_REFRESH_MS` is Task 3's `HOSTS_REFETCH_MS`.
2. **Client names.** Group 4 assumed `api.cancelSweepQueued` and the key `["sweeps", project, sweepId]`. The contract names neither; Group 1 owns the client, so `api.cancelQueued` and `queryKeys.sweep(project, id) = ["sweeps", project, "detail", sweepId]` win (Tasks 20, 21).
3. **Invalidation lists.** Group 3's dialog invalidated `[...RUN_EVENT_INVALIDATES, ["hosts"]]` and Group 4 exported `SWEEP_INVALIDATES = [...RUN_EVENT_INVALIDATES, ["sweeps"], ["hosts"]]`. Contract 4 says mirror and host events invalidate hosts, runs, overview and sweeps; Task 3's `REMOTE_RUN_INVALIDATES` (the run families, which Task 4 extends with `["sweeps"]`, plus `["hosts"]`) is exactly that list, so Tasks 12 and 20 use it and `SWEEP_INVALIDATES` is gone.
4. **`ConnState`.** Groups 2 and 3 each declared their own alias (`HostRow["state"]["state"]`, `HostState["state"]`). Contract 1.5 names `ConnState`; Tasks 5 and 9 import it from the models.
5. **Same helper twice.** `nextSeeds` (Groups 3 and 4) gave the same seeds; it lives in `ui/src/launch/seeds.ts` (Task 8) and `SweepModel.ts` re-exports it (Task 15). `sweepHref` (Groups 4 and 5) and the seconds-based age format (`fmtAge` in Group 4, `fmtWait` in Group 5, identical output) live in `SweepModel.ts` (Task 14); `remote.ts` re-exports them (Task 23), so their tests are unchanged.
6. **Name clash.** Group 2's `fmtAge` took milliseconds and printed `2h`; Group 4's takes seconds and prints `1h 30m`. Group 2's is now `fmtAgeMs` (Tasks 5–6).
7. **Kept apart on purpose.** Three GPU-cell derivations with different jobs: `gpuCells` in `HostsPanel.tsx` (one cell per run over adjacent GPUs, coloured by launcher), in `launch/plan.ts` (a per-GPU mini map with `stale` and `none`), and in `QueuePanel.tsx` (per GPU with a short label). Two `freeGpus` (indices for `CUDA_VISIBLE_DEVICES` planning in Task 9; a count for the run page in Task 23), two `shortGpuName` (`A100` for the dense hosts grid in Task 5; `A100 80GB PCIe` on the run page in Task 23), Group 2's `fmtMoney` (whole dollars from $10, for daily totals) next to phase 1b `fmtUsd` (cents, for one run), and `ago` in `launch/plan.ts`. Different outputs, each pinned by its own tests.
8. **Missing contract piece: "Rerun sweep".** Contract 4 opens the Launch dialog from the Task page "New run" and from a sweep page "Rerun sweep"; no draft built the second. Task 22 adds it: `Rerun sweep` in the sweep actions opens the dialog prefilled from the best cell's latest run (its template, params and vars, GPUs per run, the sweep's host, the next seeds).
9. **Sweep links.** Group 4 flagged that `isAppPath` did not accept `/s/`, so plain sweep links inside panel bodies would reload the page. Task 21 adds `s` to it, with its test. A "Sweep" tab in the header (`screenOf`, recent targets) is left out: contract 4 does not list it (follow-up).
10. **Real hosts.** Group 2's visual check ran `uv run hx demo --with-hosts` in the default home and no `hx serve`: it would have written into `~/.hypothex`, and a hub started there would connect to the hosts in the user's own `environments.yaml`. Task 7 Step 5 now uses `/tmp/hx-f2`, `HYPOTHEX_SSH=false HYPOTHEX_SCP=false`, a random port and `HX_API` (after an identity check). Task 2's type generation also sets `HYPOTHEX_SSH=false HYPOTHEX_SCP=false` on its empty temp home. Every such step passes `--home` and the SSH variables inline on the `hx` command line and runs as one shell command (an earlier `export` does not survive between agent shell calls), and waits are bounded. Playwright never reuses a server on either port, every test checks the hub's identity first, and `serve-demo.ts` stops the hub before the rest of its process group (Task 28).
11. **Review Focus tests and counts.** Task 2 `27 pass` (gpus/queue test; `createSweep` test dropped with the function); Task 3 `18 pass` (`keepLastKnown`, `fetchAllRuns`); Task 4 `77 pass` in `test/api` (client and types 27, events 24 + 5 = 29, queries 18, lostReasons 3); Task 5 `19 pass`, Task 6 `28 pass` (host matching, `remoteRows`, `longStale`, `staleBannerHours`); Task 7 `7 pass` (hub-only row, banner, banner threshold, cost today); Task 9 `16 pass` (two hubs test: bootstrapping with no message, then `error` with the lock message; `stateReason` appends `HostState.message` to `installing hx on <host>`); Task 10 `20 pass` (SLURM values, pinned commit, partial retry); Task 11 `12 pass` (blank SLURM body, stale carry, project not path); Task 12 dialog `20 pass` (partial-retry preview and CLI) and `test/launch` total `83`; Tasks 14–21 add 70 sweep tests (sweepModel 18, sweepStats 14, sweepTable 6, sweepRuns 5); Task 21 `31 pass` for page, router, links and Task page; Task 23 `14 pass` (run.lost reason; sweep crumb owner, review round 4); Task 24 `8 pass` (clock test) plus one leaderboard cost test; Task 25 `19 pass` (banner with the reason); Task 26 `6 pass`; Task 27 `9 pass` (two tunnel tests, long queue, lost reason from the event stream, another hub's sweep).
12. **Docs.** No draft updated `docs/ui.rst`; Task 29 documents the Hosts panel, Launch dialog, Sweep page and remote run states, and how the `hosts-*` e2e projects stay away from real hosts, with a test in `tests/test_docs_ui.py`.
13. **Known gaps outside the contract** (follow-ups, not built): the mockup's SLURM "oldest pending" and "fair-share", bootstrap step bar, run-page `est. start`, `Move up`, `Move host`, `Mark lost` and `Resume` have no contract route or field; `api.pull` (Task 2) has no UI because contract 4 lists none; the stale bar shows `HostState.message` instead of the mockup's retry count. `POST /api/v1/sweeps` and `POST /api/v1/hosts/{host}/disconnect` have no client function (no screen uses them; the `types.ts` test still checks the routes). The Launch dialog's SLURM fields start blank (blank = the host's defaults) instead of prefilled from `SlurmDefaults`, which `HostRow` does not carry.
14. **Event names.** Group 1's tests used `host.state_changed`; the backend plan emits `host.state`. The tests now use `host.state`; `keysForEvent` maps every `host.*` type the same way, as contract 4 says.
15. **Host identity and stale data (review fixes).** The backend writes `executor.host = socket.gethostname()` on every run (hub runs too) and the mirror keeps it, so it is neither the hub's host name nor a hub/remote flag. Runs are matched to hosts by `environment_id` (`hostRowForRun`, Task 5; `hostOf` Task 14; `runHostRow` Task 23; `queueRows` Task 25), a run detail with `host_state: null` is a hub run (`runPhase`), Reconnect posts the matched row's name, and every unit fixture gives `executor.host` a machine hostname that differs from the host name, so a regression to `executor.host` fails the tests (the demo uses label = host name, so the e2e could not catch it). The hub's own `local` row is always first in `GET /api/v1/hosts` and is left out of the hosts headline switch and host count. The hub sends no GPUs or queue for a host that is not connected, so `useHosts` and the Launch dialog keep a stale host's last connected cells (`keepLastKnown`); fixtures fed to mocked APIs are shaped as the hub sends them. A queued or running run on any host that is not connected is stale on the sweep page too (`staleHosts` keyed by environment, every state but `connected`). No contract change was needed.
16. **Removed text.** Per-group headers, constraints, review-focus lists, file lists, "consumed from" tables and self-review notes were replaced by the global sections and the group intros; every test they named is still in its task. Group references were rewritten to task numbers and backend group names (`B5`, `B8`, `B9`) to "the backend plan".
17. **Codex review 1 (frontend items).** Item 3 / isolation: both Playwright web servers use `reuseExistingServer: false`; `serve-demo.ts` writes a fresh `environment.json` (new `environment_id`, label `hx-e2e-demo` / `hx-e2e-hosts`) and an auto fixture checks the hub's descriptor against it before every test, so `live.spec.ts` notes and `launch.spec.ts` launches cannot reach another server (Task 28). Shutdown order (non-blocking note): Playwright sends SIGTERM (`gracefulShutdown`); `serve-demo.ts` runs the venv's `hx` directly, signals the hub alone, waits for its HTTP cleanup of demo runs and fake hosts, and only then SIGKILLs the group; `e2e/shutdown-check.ts` is the focused regression (Task 28). Item 10: the gpus/queue client test mocks gpu1's three GPUs (`HOSTS[1]`), not the hub row's none (Task 2). Item 27: host launches send `project` and never a path (`HostLaunchRequest { project }`), the hub launch keeps its own `repo`; `commit` is pinned only by Rerun sweep from a clean template run (`pinnedCommit`), otherwise the hub pins its checkout's HEAD and diff; the dialog never sends a `diff` (Tasks 1, 2, 9–12, 22). Item 31: seed dots come from the cell's own runs only: the group row's values when every run of that row is in the cell, else none (Task 14). Item 32: the queue panel reads the whole queue of the run's environment (`useAllRuns({status: "queued", environment_id})`, limits 1000, 4000, … while a page is full) and keeps the page's own run (`queueRows(..., current)`); the sweep page reads its runs the same way (Tasks 3, 21, 25, 27). The hub's `/api/v1/runs` must accept `environment_id` for the filter to save transfer; the client also filters by environment, so rows are right either way. Item 33: models carry `HostRow.usd_per_gpu_hour`, `HostRow.stale_banner_hours`, `LeaderboardRow.cost`, `OverviewSummary.cost_usd` / `cost_today_usd` (Task 1); the leaderboard shows each group's cost (Task 24), the Overview's cost today prefers `cost_today_usd` (Task 7). Ruling R1: the banner threshold is `stale_banner_hours` from the `GET /api/v1/hosts` rows (`staleBannerHours`, default 24), not a fixed 24 h (Tasks 5, 7). Non-blocking notes: a partial retry needs free GPUs only for the seeds not started (`checkDraft(..., started)`, Tasks 10, 12); the params table's default sort follows a lower-is-better direction that arrives after the first render (Task 17); the lost bar uses neutral words (`SLURM job N lost`, `run lost`) and points to the `run.lost` event (Task 23).
18. **Codex review 2 (frontend items) and coordinator follow-ups.** Item 2 / ruling S1: no step or check uses a fixed port any more. `ui/e2e/paths.ts` asks the OS for a free port per run (`freePort`; the Playwright runner passes both ports to its workers and web servers in `HX_E2E_PORT` / `HX_E2E_HOSTS_PORT`); `shutdown-check.ts` picks its own, wipes its home first, verifies the hub's identity (`readIdentity` + `answersAs`) before it reads `/api/v1/hosts` or `/api/v1/runs` (`getJson` refuses until then), and fails at once when `serve-demo.ts` cannot start or exits (`serve-demo.ts` itself exits on a spawn `error`, a failed `hx demo` or an early hub exit). Task 2's type generation and the visual checks of Tasks 7 and 27 bind port 0 through `uv run python`, write the temp home's identity first, and touch the hub only after `/.well-known/hypothex/environment` answers with it (Task 2 also stops waiting when `hx serve` exits, and kills only its own server by its unique home). Item 15 / ruling S9: the UI side keeps SIGTERM to the hub alone; the hub's ASGI lifespan shutdown (backend) stops the demo runs and fake hosts inside uvicorn's signal handling; `shutdown-check.ts` sends the real SIGTERM and keeps the ordering regression, plus a child-start-failure demonstration (Task 28 Step 11). Ruling S8: `SweepSpec` has no `run_ids`; `SweepSummary.run_ids` is the membership the backend derives from the `sweep:<id>` tags, and the sweep page orders its runs by it (Tasks 1, 14, 15, 21, 28). Coordinator (a): after a partial launch the preview, its `×N`, the summary and `Copy as CLI` cover only the seeds not launched (Task 12). Coordinator (b): `ui/src/api/lostReasons.ts` keeps the `reason` of `run.lost` events (and of `mirror.run_updated` with `original_type: "run.lost"`) seen on the event stream; the lost bar shows it first, else the neutral words (Tasks 4, 23, 25, 27, 29). Backend dependency: the backend plan's `mirror.run_updated` payload is `{host, environment_id, original_type, remote_sequence, status}`; it must also copy the original event's `reason` for a mirrored `run.lost`, or remote lost runs (all SLURM losses) always show the neutral words.
19. **Backend review round 3 (shape changes only).** Sweep runs are tagged `sweep:<owner8>:<id>` (the hub's environment id prefix, so two hubs' sweeps with one id never mix): `SweepSummary.tag` carries the tag, `sweepRunsQuery(project, tag)` takes it, and the sweep page starts its runs query once the summary is loaded (Tasks 1, 14, 21, 22; fixtures `SWEEP_TAG`, mocked run URLs). Host rows add `slurm.comment_accounting?: boolean | null` (Task 1 `HostRow` type only; no screen shows it yet).
20. **Backend review round 4 (note).** The run page's sweep crumb follows the owner-qualified tag: `sweepCrumb` (Task 23) reads `sweep:<owner8>:<sweep_id>` from the record's tags and links `/s/<project>/<id>` only when `owner8` is the first 8 characters of this hub's environment id (`api.environment()`, key `["environment"]`, fetched only for a run with a `sweep_id`, Task 27). A run of another hub's sweep (a host shared by two hubs) or a run without the tag shows `sweep <id>` as plain text with the reason as its tooltip, so the crumb never opens this hub's page of a different sweep with the same id. Tests: Task 23 `sweepCrumb links only a sweep this hub owns`, Task 27 `a run of another hub's sweep names the sweep without a link` (the lost-run link test now gives its record the hub's tag and mocks the descriptor).
