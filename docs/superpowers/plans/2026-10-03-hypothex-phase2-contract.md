# Hypothex Phase 2 — Interface Contract

Binding for the phase 2 plans (backend, frontend). Spec: `docs/superpowers/specs/2026-09-26-hypothex-design.md` sections 5.2–5.7 and **8A**. Mockups: `docs/mockups/phase2/`. Phases 1a/1b are on `main`; read the real code (`src/hypothex/`, `ui/src/`) before planning. Names below are exact; plans may add private helpers but must not rename or reshape these.

Hard rule: no test or step ever connects to the user's real hosts. Tests use in-process env servers, a fake `ssh`/`scp`, fake SLURM commands, and Docker containers (marked `docker`, skipped when Docker is unavailable).

## 1. Python modules

### 1.1 `hypothex.remote.config` — environments file

```python
HostKind = Literal["ssh", "slurm"]
Route = Literal["ssh", "url", "local"]
class SlurmDefaults(BaseModel, extra="forbid"): partition: str | None = None; account: str | None = None; time: str = "02:00:00"; gpus: int = 1; extra: list[str] = []   # each item exactly one sbatch option token; never job-name/J, comment, output/o, error/e, chdir/D, wrap in any form
class HostSpec(BaseModel, extra="forbid"):
    route: Route; kind: HostKind = "ssh"
    ssh_alias: str | None = None          # required for route=ssh
    url: str | None = None                # required for route=url (tests, phase 3)
    home: str = "~/.hypothex"
    usd_per_gpu_hour: float | None = Field(None, ge=0, allow_inf_nan=False)
    slurm: SlurmDefaults | None = None    # required when kind=slurm
    projects: dict[str, str] = {}         # project -> repo path on the host
class EnvironmentsFile(BaseModel, extra="forbid"): stale_banner_hours: float = 24; environments: dict[str, HostSpec] = {}   # banner after this many hours stale (spec 5.6)
HOST_NAME = r"^[a-z0-9][a-z0-9_-]{0,31}$"     # "local" reserved for the hub
def environments_path(layout: Layout) -> Path: ...          # <home>/environments.yaml
def load_hosts(layout: Layout) -> EnvironmentsFile: ...     # missing file -> empty; uses config.scan_yaml + has_cycle guards
def save_hosts(layout: Layout, hosts: EnvironmentsFile) -> None: ...  # atomic
```

### 1.2 `hypothex.remote.ssh` — transport (subprocess, user's own `ssh`/`scp`)

```python
class SshError(HypothexError): ...
class SshTarget(BaseModel): alias: str; ssh_bin: str = "ssh"; scp_bin: str = "scp"; connect_timeout: int = 10
def run_remote(target: SshTarget, script: str, *, timeout: float = 120, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]: ...  # `ssh -o BatchMode=yes -o ConnectTimeout=N alias sh -s` with script on stdin
def copy_to(target: SshTarget, local: Path, remote_path: str, *, timeout: float = 300) -> None: ...
def copy_from(target: SshTarget, remote_path: str, local: Path, *, work: Path, timeout: float = 600) -> None: ...   # work: <hub home>/pulls (staging + transaction records), see round 4
class Tunnel:                          # one `ssh -N -L` subprocess
    def __init__(self, target: SshTarget, remote_port: int, local_port: int | None = None) -> None: ...
    local_port: int
    def start(self) -> None: ...; def alive(self) -> bool: ...; def stop(self) -> None: ...
```
`ssh_bin`/`scp_bin` come from env `HYPOTHEX_SSH` / `HYPOTHEX_SCP` (default `ssh`/`scp`) so tests substitute fakes. Options always include `-o BatchMode=yes`, `-o ExitOnForwardFailure=yes` (tunnels), `-o ServerAliveInterval=15 -o ServerAliveCountMax=3`.

### 1.3 `hypothex.remote.bootstrap`

```python
class ProbeResult(BaseModel): os: str; arch: str; python: str | None; uv: str | None; gpus: int; slurm: str | None; home: str
class ServerInfo(BaseModel): pid: int; port: int; managed: bool; hx_version: str; protocol_version: int; token: str | None = None  # bearer token of the env server (from server.json, 0600); excluded from dumps
def probe(target: SshTarget, home: str) -> ProbeResult: ...
def build_wheel(cache_dir: Path) -> Path: ...                  # `uv build --wheel` of the running package, cached by version; reuse if present
def install(target: SshTarget, home: str, wheel: Path) -> None: ...   # scp + `uv tool install --force` under <home>/runtime with a lock dir; installs uv into ~/.local/bin if missing
def ensure_server(target: SshTarget, home: str) -> ServerInfo: ...    # reuse healthy <home>/serve/server.json else nohup start; on failure raise BootstrapError with last 80 log lines
class BootstrapError(HypothexError): ...
BOOTSTRAP_SCRIPTS: dict[str, str]   # POSIX sh templates: "probe", "install", "start", "stop", "logs"
```

### 1.4 `hypothex.remote.client` — HTTP/WS client to an env server

```python
class EnvClient:
    def __init__(self, base_url: str, *, timeout: float = 10, token: str | None = None) -> None: ...  # token -> Authorization: Bearer (HTTP and WS)
    def descriptor(self) -> EnvironmentDescriptor: ...
    def get_json(self, path: str, **params: Any) -> Any: ...
    def post_json(self, path: str, body: dict[str, Any]) -> Any: ...
    def fetch_file(self, run_id: str, rel_path: str, dest: Path, *, max_bytes: int, tail: bool = False) -> bool: ...   # False when skipped (too big / missing); tail = last max_bytes (log tails); whole files only
    async def events(self, after_sequence: int) -> AsyncIterator[Event]: ...   # WS subscribe, yields events, ends on disconnect
```
Uses `httpx` and `websockets` (or `httpx-ws`; plan picks one, adds it with `uv add`).

### 1.5 `hypothex.remote.hub` — supervisors and mirror

```python
ConnState = Literal["connecting", "bootstrapping", "connected", "stale", "upgrade", "error", "disabled"]
class HostState(BaseModel):
    name: str; kind: HostKind | Literal["local"]; state: ConnState; since: datetime; message: str = ""   # "local" only for the hub's own row
    environment_id: str | None = None; hx_version: str | None = None; last_sequence: int = 0
    local_port: int | None = None
class Hub:
    def __init__(self, ctx: Context, hosts: EnvironmentsFile) -> None: ...
    async def start(self) -> None: ...       # one supervisor task per host
    async def stop(self) -> None: ...
    def state(self, name: str) -> HostState: ...
    def states(self) -> list[HostState]: ...
    def client(self, name: str) -> EnvClient: ...   # raises HostUnavailableError when not connected
    async def add_host(self, name: str, spec: HostSpec) -> HostState: ...   # one host changes; others keep their sessions
    async def remove_host(self, name: str) -> None: ...
class HostUnavailableError(HypothexError): ...
def mirror_event(ctx: Context, client: EnvClient, host: str, environment_id: str, event: Event) -> None: ...
MIRROR_FILES = ("run.yaml", "scores.jsonl", "metrics.jsonl", "notes.md", "usage.jsonl", "config.yaml", "git.diff", "git.stat")
MIRROR_DIRS = ("predictions", "traces", "samples", "env", "logs")
MIRROR_MAX_BYTES = 200 * 1024 * 1024
```
Backoff 3/4/8/16 s, reset after 30 s connected. Cursor persisted in the hub index table `host_cursors(host, environment_id, last_sequence)`. Mirror writes go through `RunStore` and `index_run`: each changed file is fetched whole into a per-run staging folder, and only when every fetch succeeded is the run id claimed hub-wide (`<store>/.claims/<run_id>.json`) and are the files installed in one pass under the run lock (no appends, no byte offsets). A listed file the host does not serve is listed again once: still missing, its local copy is deleted; too big (or refused twice), its local copy is deleted and its entry (`{reason, size, max_bytes}`) is written to `<run_dir>/.hx/mirror-skips.json`, never next to the file. `.hx/` in a run folder is reserved for Hypothex's own state: the env files route refuses any path whose first component is `.hx` (404) and the mirror never fetches one, so a host file such as `predictions/x.skipped` is mirrored like any other. `.mirror-index-pending` is written before the first change to a run folder and removed last; a replay that finds it re-indexes, and the hub re-indexes such runs when it starts. Mirror events are re-emitted as `mirror.run_updated` with payload `{host, environment_id, original_type, remote_sequence, status, reason?}`: `original_type` is the host's event type, and `reason` is copied from the host's event when it has one (`run.lost`, `run.killed`, `run.failed`, e.g. a SLURM `NODE_FAIL`). Hub marks a host `stale` after 60 s without a successful ping; runs on stale hosts are shown stale (derived, never written as status).

### 1.6 Env-server additions (`hypothex.core` on the host)

```python
# records
class ExecutorInfo(...):   # add
    host: str | None = None; gpus: list[int] = []; slurm_job_id: str | None = None; node: str | None = None; queue_position: int | None = None
class CostTotals(BaseModel): gpu_hours: float = 0; gpu_usd: float = 0; api_usd: float = 0; total_usd: float = 0
class RunRecord(...):      # add
    cost: CostTotals | None = None; sweep_id: str | None = None; gpus_requested: int = 0
# hypothex.core.gpus
class GpuInfo(BaseModel): index: int; name: str; util: float; mem_used_mb: int; mem_total_mb: int; external: bool; run_id: str | None = None
def query_gpus() -> list[GpuInfo]: ...     # nvidia-smi --query-gpu / --query-compute-apps; [] when absent; HYPOTHEX_FAKE_GPUS=<json path> overrides for tests
# hypothex.core.scheduler (SSH hosts)
class Scheduler:
    def __init__(self, ctx: Context) -> None: ...
    def enqueue(self, run_id: str) -> int: ...             # returns queue position (1-based)
    def tick(self) -> list[str]: ...                        # starts runs whose GPUs fit (FIFO first-fit), returns started run ids
    def positions(self) -> dict[str, int]: ...
# hypothex.core.slurm
class SlurmJob(BaseModel): job_id: str; state: str; node: str | None = None; exit_code: int | None = None
def render_sbatch(record: RunRecord, defaults: SlurmDefaults, home: Path) -> str: ...
def submit(script: str, cwd: Path, *, comment: str | None = None) -> str: ...   # job id; `sbatch --parsable`; SlurmError only on positive evidence (non-zero exit + recognised rejection on stderr + no job id); anything else (signal, timeout, garbled, unknown error) is SubmitUnknownError
def find_submitted(comment: str) -> tuple[SlurmJob | None, bool]: ...   # by the unique comment only (squeue and sacct); bool = both answered and sacct stores comments
def comment_accounting(*, refresh: bool = False) -> bool: ...   # scontrol show config: AccountingStoreFlags has job_comment; cached per server start
def poll(job_ids: list[str]) -> dict[str, SlurmJob]: ...    # squeue then sacct for finished
def cancel(job_id: str) -> None: ...
# hypothex.core.cost
def compute_cost(record: RunRecord, usd_per_gpu_hour: float | None) -> CostTotals: ...
```
`hx serve --kind slurm|ssh` (default from `environment.json` / probe) enables the scheduler loop (ssh, every 5 s) or the SLURM poll loop (every 30 s). Run-start path: `prepare_run` accepts `gpus: int`, `queue: bool`, `slurm: SlurmDefaults | None`, `commit: str | None` (hex sha, fetched when missing), `diff: str | None` (applied on `commit` in a worktree, 8A.4). The hub always sends `commit` with `diff`.

### 1.7 Sweeps (`hypothex.core.sweeps`)

```python
class SweepParam(BaseModel): name: str; values: list[str] | None = None; low: float | None = None; high: float | None = None; log: bool = False
class SweepSpec(BaseModel, extra="forbid"): id: str; project: str; task: str | None; host: str | None; grid: list[SweepParam]; random: int | None = None; seeds: list[int]; command_template: list[str]; created_by: str; created_at: datetime   # the definition only: no run ids
def expand(spec: SweepSpec, rng_seed: int = 0) -> list[dict[str, str]]: ...   # grid product (+ random samples), each dict = params; seeds applied separately
def save_sweep(layout: Layout, spec: SweepSpec) -> Path: ...    # <store>/<project>/sweeps/<id>.yaml
def load_sweep(layout: Layout, project: str, sweep_id: str) -> SweepSpec: ...
class SweepSummary(BaseModel): spec: SweepSpec; counts: dict[str, int]; cells: list[dict[str, Any]]; best: dict[str, Any] | None; headline: str; total_usd: float; run_ids: list[str] = []; tag: str = ""   # tag = the sweep's member tag sweep:<owner8>:<id>; run_ids derived: indexed runs with that tag, launch order
def summarize_sweep(ctx: Context, project: str, sweep_id: str) -> SweepSummary: ...   # cells: {params, group_id, n, mean, lo, hi, run_ids}
```
Sweep membership is derived from the tag `sweep:<owner8>:<id>`, never stored; `owner8` is the first 8 characters of the environment id that holds the definition (the hub), so two hubs' sweeps with the same id on one host never share runs. Clients read `SweepSummary.tag` instead of building the tag. Each (params, seed) has one deterministic command id (`run_command_id`: 16 hex of a SHA-256 over the owning environment, project, sweep id, sorted params, seed); launch, a retried launch, and extend save the definition and issue every missing (params, seed) with it, and command receipts make a repeat the same run.

## 2. HTTP API additions

Hub (and env servers where marked *env*):

| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | `/api/v1/hosts` | | `list[{name, kind: "local" \| HostKind, state: HostState, gpus: list[GpuInfo], queue: int, slurm: {pending, running, comment_accounting: bool\|null}\|null, cost_today_usd: float, usd_per_gpu_hour: float\|null, projects: list[str], stale_banner_hours: float}]` (first row: the hub, `name` and `kind` `"local"`; `stale_banner_hours` is the same on every row; `comment_accounting` false: the cluster's accounting keeps no job comments, so an unknown submission can never be settled; null: not known, the host is not connected) |
| POST | `/api/v1/hosts/reload` | `{command_id?}` | the host rows after re-reading `environments.yaml` (`hx hosts map\|rm` call it; `hx hosts add\|upgrade` call `/api/v1/hosts/{host}/connect`, which also re-reads `environments.yaml` and starts the new host) |
| POST | `/api/v1/hosts/{host}/connect` / `/disconnect` | `{command_id?}` | `HostState` |
| POST | `/api/v1/hosts/{host}/runs` | launch body + `{gpus, queue, slurm?: SlurmDefaults, project?, commit?, diff?}`; the project by name (a `repo` path is used only when it is a folder on the hub); without `commit` the hub pins its own checkout's HEAD (and sends its uncommitted diff); with `commit` the body's `diff` (none for a clean run) | run record (forwarded) |
| GET | `/api/v1/runs` | phase 1 filters + `environment_id?`; `limit` is never capped below the request | `list[RunRecord]` |
| GET | `/api/v1/runs/{id}/files/{path:path}` *env* | `max_bytes`, `tail?` | file bytes; 404 / 413; 404 for any path in the reserved `.hx/` folder |
| GET | `/api/v1/projects/{project}/entry` *env* | | the host's `ProjectEntry` (the hub copies a host-only project) |
| GET | `/api/v1/gpus` *env* | | `list[GpuInfo]` |
| GET | `/api/v1/queue` *env* | | `[{run_id, position, gpus_requested}]` |
| GET | `/api/v1/slurm` *env* | | `{comment_accounting: bool \| null}` (null when the server is not `slurm`) |
| POST | `/api/v1/sweeps` | `{project, task?, host?, grid, random?, seeds, command, hypothesis, gpus?, queue?, commit?, diff?, command_id?}` | `SweepSummary` |
| GET | `/api/v1/sweeps/{project}/{id}` | | `SweepSummary` |
| GET | `/api/v1/sweeps/{id}` | | `SweepSummary` (any project; for clients on another machine) |
| GET | `/api/v1/projects/{project}/sweeps` | | `list[{id, created_at, n_runs, best}]` |
| POST | `/api/v1/sweeps/{project}/{id}/cancel_queued` | `{command_id?}` | `SweepSummary` (queued runs of the sweep stopped as `killed`) |
| POST | `/api/v1/sweeps/{project}/{id}/extend` | `{seeds: list[int], command_id?}` | `SweepSummary` (adds runs for every param combination × new seeds, pinned to `spec.commit`/`spec.diff`: the client's commit and diff, else the hub checkout's at create time; audit CONF-1a) |
| POST | `/api/v1/runs/{id}/pull` | `{artifact: kind or path, command_id?}` | `{local_path}`; 400 when the destination name starts with `.hx-` |

Run actions on remote runs (stop, rerun, reinfer, reeval, tags, star, archive, notes) keep their routes; the hub forwards to the owning host by `environment_id`. A run of an environment no configured host serves gets `503` for stop, rerun, reinfer, and reeval; also for tags, star, archive, and notes when the hub mirrored it from a host (it has a `host_cursors` row), since the host's copy replaces the hub's on the next mirror (audit INT-F2a). `GET /api/v1/runs/{id}` adds `host_state: ConnState | null` (null = local); so does each row of `GET /api/v1/runs`, so the CLI and MCP can show a stale host when they list runs through the hub (audit CONF-4a).

Additive fields (spec 8A.7): leaderboard rows add `cost: CostTotals | null` (sum of the group's runs); the Overview adds `cost_usd` (runs in the window) and `cost_today_usd`.

Env servers (`hx serve --kind ssh|slurm`) require `Authorization: Bearer <token>` on every route except `/.well-known/hypothex/environment`; the token is in the host's `<home>/serve/server.json` (0600) and reaches the hub as `ServerInfo.token`. The hub's own server (the UI) needs no token.

## 3. CLI and MCP additions

CLI (`--json` everywhere): `hx hosts add|list|status|map|rm|upgrade|connect|disconnect`, `hx service install|uninstall`, `hx launch --host H --gpus N --queue [--partition P --time T --account A]`, `hx sweep ...` (spec 8A.6), `hx sweeps [-p P]`, `hx sweep show <id>`, `hx sweep cancel <id>`, `hx sweep extend <id> --seeds 4,5`, `hx pull <run_id> [--artifact X]`, `hx serve --kind ssh|slurm`.
MCP: `list_hosts`, `launch_run(..., host=None, gpus=0, queue=False)`, `launch_sweep(...)`, `get_sweep(project, sweep_id)`, `cancel_sweep(project, sweep_id)`, `extend_sweep(project, sweep_id, seeds)`, `pull_artifact(run_id, artifact)`.

## 4. Frontend

Additions in `ui/` (same stack and rules as phase 1b):
- `ui/src/api/models.ts`: `HostState`, `HostRow`, `GpuInfo`, `SweepSummary`, `CostTotals`, executor additions. `HostRow.kind` and `HostState.kind` are `HostKind | "local"`; `HostRow.usd_per_gpu_hour`, `LeaderboardRow.cost`, `OverviewSummary.cost_usd` / `cost_today_usd` are optional.
- Overview panel "Hosts" (`ui/src/pages/components/HostsPanel.tsx`) as panel a; the existing "Runs by launcher" timeline, Ideas, Failures and Projects stay below it (the phase 2 mockup dropped the timeline for space; keep it).
- Launch dialog (`ui/src/launch/LaunchDialog.tsx`), opened from the Task page "New run" and from a sweep page "Rerun sweep".
- Sweep page route `/s/:project/:id` (`ui/src/pages/Sweep.tsx`) with actions Copy as CLI, Cancel queued, Add seeds.
- Run page states: queued (position), remote (host, GPUs, SLURM job/node), stale (since), lost (reason); cost line.
- Live updates: `mirror.run_updated` and `host.*` events invalidate hosts, runs, overview, sweeps.
- Mockups: `docs/mockups/phase2/`.

## 5. Plans

- `docs/superpowers/plans/2026-10-03-hypothex-phase2-backend.md` — sections 1–3 + Docker integration harness (`tests/docker/`: sshd image, slurm compose) + docs.
- `docs/superpowers/plans/2026-10-03-hypothex-phase2-frontend.md` — section 4; Playwright smoke needs fake remote hosts: the backend plan provides ONE command (`hx demo --with-hosts`, plan picks the mechanism, e.g. separate demo homes for fake hosts plus `route: url` entries and a helper that serves them) so `hx serve` on the hub shows connected fake hosts with GPUs, a queue, a SLURM host, and a sweep.

## Changes after the backend plan review (2026-10-03)

All additive; nothing was renamed. `ServerInfo.token` and `EnvClient(token=)` (env-server auth on shared hosts); `EnvClient.fetch_file(tail=, offset=)` and the files route's `tail`/`offset` (log tails, append-only mirroring); `HostState.kind` and host rows accept `"local"` (the hub's own row); host rows add `usd_per_gpu_hour`; leaderboard rows add `cost`, the Overview adds `cost_usd`/`cost_today_usd` (spec 8A.7); `Hub.add_host`/`remove_host`; the host launch and sweep bodies take `commit` (and `project`/`diff`); env route `GET /api/v1/projects/{project}/entry`; `prepare_run` takes `commit`. The frontend plan's "known gaps" for `$/GPU-h` and leaderboard cost are now served by the backend.

## Changes after review round 1 (2026-10-03)

Additive unless noted. `EnvironmentsFile.stale_banner_hours` (default 24) and `stale_banner_hours` on every `GET /api/v1/hosts` row (spec 5.6 banner); `POST /api/v1/hosts/reload`; `GET /api/v1/runs?environment_id=` with no cap below the requested `limit`; `GET /api/v1/runs?before_created_at=&before_run_id=` keyset pages (the last row of the previous page; both or neither, else `400`; audit PERF-F13b); the WebSocket subscribe takes `after_sequence: "latest"` (no replay) and an optional `max_replay: int >= 1`; past it the server sends `{type: "reset", last_sequence}` instead of the replay, then `ready` (clients without `max_replay`, such as the hub mirror, still get every event; audit PERF-F10b); `GET /api/v1/sweeps/{id}`; `POST /api/v1/hosts/{host}/runs` takes the project by name and an optional `commit` (no path, no diff needed from the UI). Spec 5.7: `--hosts a,b` (a queue across hosts) is dropped; a run targets one host (a scope change, not an addition). Backend-only additions the frontend does not use: `submit(..., comment=)`, `find_submitted`, `launch_sweep(..., command_id=)`, `EventLog.append_once`, `Index.list_runs(environment_id=)`. A foreground (`--foreground`) rerun or reinfer on a SLURM host is refused ("SLURM runs are always submitted; drop --foreground"); a SLURM host's home must support `flock` (the env server refuses to start without it).

## Changes after review round 2 (2026-10-03)

Not all additive (marked "changed"). Changed: `SweepSpec.run_ids` is removed; `SweepSummary.run_ids` (derived from the `sweep:<id>` tag) replaces it, so API, CLI, and MCP clients read `summary.run_ids`, not `summary.spec.run_ids`. Changed: `EnvClient.fetch_file` and the files route drop `offset` (the mirror fetches whole files). Changed: `find_submitted(comment)` returns `(job, complete)` and matches the comment only. Additive: `mirror.run_updated` carries `reason` when the host's event had one; `SubmitUnknownError`; event `run.submit_unknown`; `SlurmDefaults.extra` refuses `--job-name`, `--comment`, `--output` (and their abbreviations); a stop of a SLURM run whose job id is not known yet is carried out once the job appears; `create_app(..., lifespan_context=)` (the demo hosts of `hx serve` start and stop in the ASGI lifespan, so SIGTERM stops them); `extend` is idempotent (seeds already in the sweep issue only missing runs, never a 400).

## Changes after review round 3 (2026-10-03)

Additive unless noted. `SweepSummary.tag` (the member tag); changed: sweep runs are tagged `sweep:<owner8>:<id>` instead of `sweep:<id>` (clients use `SweepSummary.tag`, `RunRecord.sweep_id` is unchanged). Host rows: `slurm.comment_accounting: bool | null`; env route `GET /api/v1/slurm`; `comment_accounting()`. Changed: `SlurmDefaults.extra` items must each be exactly one option token, and `--error`, `--chdir`, `--wrap` and the short forms `-J`, `-o`, `-e`, `-D` join the reserved options. Changed: `submit` raises `SlurmError` only on positive evidence of a rejection; everything else is `SubmitUnknownError`. Backend-only: without comment accounting an unknown submission stays `queued` (`run.submit_unknown`, reason "submission outcome unknown; check squeue/sacct"); the mirror deletes stale copies of listed files it could not fetch and writes `<file>.skipped` markers; `copy_from` backups are `.hx-pull-<uuid>.old` with a `.hx-pull-<uuid>.json` record; a sweep definition is never deleted after a launch request was made. The files route table no longer lists `offset` (dropped in round 2).

## Changes after review round 4 (2026-10-03)

Hypothex's own state lives only in reserved locations that remote and artifact paths can never address. Changed: the mirror's skip notes move from `<file>.skipped` markers next to the file to `<run_dir>/.hx/mirror-skips.json` (`{path: {reason, size, max_bytes}}`); the env files route answers 404 for any path whose first component is `.hx`, and the mirror never fetches one (`HX_DIR`, `reserved_run_path` in `hypothex.core.layout`). Changed (backend-only): `copy_from(..., work=)` keeps its staging, transaction records, and backups in `<hub home>/pulls/` (`stage/`, `txn/<uuid>.json`, `backup/<uuid>`) instead of `.hx-pull-*` names next to the destination; recovery reads only `pulls/txn/`. `POST /api/v1/runs/{id}/pull` refuses a destination whose name starts with `.hx-` (400). UI: the run page links a run's sweep only when its `sweep:<owner8>:<id>` tag names this hub; otherwise the id is plain text.
