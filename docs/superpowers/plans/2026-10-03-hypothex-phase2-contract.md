# Hypothex Phase 2 — Interface Contract

Binding for the phase 2 plans (backend, frontend). Spec: `docs/superpowers/specs/2026-09-26-hypothex-design.md` sections 5.2–5.7 and **8A**. Mockups: `docs/mockups/phase2/`. Phases 1a/1b are on `main`; read the real code (`src/hypothex/`, `ui/src/`) before planning. Names below are exact; plans may add private helpers but must not rename or reshape these.

Hard rule: no test or step ever connects to the user's real hosts. Tests use in-process env servers, a fake `ssh`/`scp`, fake SLURM commands, and Docker containers (marked `docker`, skipped when Docker is unavailable).

## 1. Python modules

### 1.1 `hypothex.remote.config` — environments file

```python
HostKind = Literal["ssh", "slurm"]
Route = Literal["ssh", "url", "local"]
class SlurmDefaults(BaseModel, extra="forbid"): partition: str | None = None; account: str | None = None; time: str = "02:00:00"; gpus: int = 1; extra: list[str] = []
class HostSpec(BaseModel, extra="forbid"):
    route: Route; kind: HostKind = "ssh"
    ssh_alias: str | None = None          # required for route=ssh
    url: str | None = None                # required for route=url (tests, phase 3)
    home: str = "~/.hypothex"
    usd_per_gpu_hour: float | None = Field(None, ge=0, allow_inf_nan=False)
    slurm: SlurmDefaults | None = None    # required when kind=slurm
    projects: dict[str, str] = {}         # project -> repo path on the host
class EnvironmentsFile(BaseModel, extra="forbid"): environments: dict[str, HostSpec] = {}
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
def copy_from(target: SshTarget, remote_path: str, local: Path, *, timeout: float = 600) -> None: ...
class Tunnel:                          # one `ssh -N -L` subprocess
    def __init__(self, target: SshTarget, remote_port: int, local_port: int | None = None) -> None: ...
    local_port: int
    def start(self) -> None: ...; def alive(self) -> bool: ...; def stop(self) -> None: ...
```
`ssh_bin`/`scp_bin` come from env `HYPOTHEX_SSH` / `HYPOTHEX_SCP` (default `ssh`/`scp`) so tests substitute fakes. Options always include `-o BatchMode=yes`, `-o ExitOnForwardFailure=yes` (tunnels), `-o ServerAliveInterval=15 -o ServerAliveCountMax=3`.

### 1.3 `hypothex.remote.bootstrap`

```python
class ProbeResult(BaseModel): os: str; arch: str; python: str | None; uv: str | None; gpus: int; slurm: str | None; home: str
class ServerInfo(BaseModel): pid: int; port: int; managed: bool; hx_version: str; protocol_version: int
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
    def __init__(self, base_url: str, *, timeout: float = 10) -> None: ...
    def descriptor(self) -> EnvironmentDescriptor: ...
    def get_json(self, path: str, **params: Any) -> Any: ...
    def post_json(self, path: str, body: dict[str, Any]) -> Any: ...
    def fetch_file(self, run_id: str, rel_path: str, dest: Path, *, max_bytes: int) -> bool: ...   # False when skipped (too big / missing)
    async def events(self, after_sequence: int) -> AsyncIterator[Event]: ...   # WS subscribe, yields events, ends on disconnect
```
Uses `httpx` and `websockets` (or `httpx-ws`; plan picks one, adds it with `uv add`).

### 1.5 `hypothex.remote.hub` — supervisors and mirror

```python
ConnState = Literal["connecting", "bootstrapping", "connected", "stale", "upgrade", "error", "disabled"]
class HostState(BaseModel):
    name: str; kind: HostKind; state: ConnState; since: datetime; message: str = ""
    environment_id: str | None = None; hx_version: str | None = None; last_sequence: int = 0
    local_port: int | None = None
class Hub:
    def __init__(self, ctx: Context, hosts: EnvironmentsFile) -> None: ...
    async def start(self) -> None: ...       # one supervisor task per host
    async def stop(self) -> None: ...
    def state(self, name: str) -> HostState: ...
    def states(self) -> list[HostState]: ...
    def client(self, name: str) -> EnvClient: ...   # raises HostUnavailableError when not connected
class HostUnavailableError(HypothexError): ...
def mirror_event(ctx: Context, client: EnvClient, host: str, environment_id: str, event: Event) -> None: ...
MIRROR_FILES = ("run.yaml", "scores.jsonl", "metrics.jsonl", "notes.md", "usage.jsonl", "config.yaml", "git.diff", "git.stat")
MIRROR_DIRS = ("predictions", "traces", "samples", "env", "logs")
MIRROR_MAX_BYTES = 200 * 1024 * 1024
```
Backoff 3/4/8/16 s, reset after 30 s connected. Cursor persisted in the hub index table `host_cursors(host, environment_id, last_sequence)`. Mirror writes go through `RunStore` and `index_run`; mirror events re-emitted as `mirror.run_updated` with the original event type in payload. Hub marks a host `stale` after 60 s without a successful ping; runs on stale hosts are shown stale (derived, never written as status).

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
def submit(script: str, cwd: Path) -> str: ...             # job id; uses `sbatch --parsable`
def poll(job_ids: list[str]) -> dict[str, SlurmJob]: ...    # squeue then sacct for finished
def cancel(job_id: str) -> None: ...
# hypothex.core.cost
def compute_cost(record: RunRecord, usd_per_gpu_hour: float | None) -> CostTotals: ...
```
`hx serve --kind slurm|ssh` (default from `environment.json` / probe) enables the scheduler loop (ssh, every 5 s) or the SLURM poll loop (every 30 s). Run-start path: `prepare_run` accepts `gpus: int`, `queue: bool`, `slurm: SlurmDefaults | None`, `diff: str | None` (applied in a worktree, 8A.4).

### 1.7 Sweeps (`hypothex.core.sweeps`)

```python
class SweepParam(BaseModel): name: str; values: list[str] | None = None; low: float | None = None; high: float | None = None; log: bool = False
class SweepSpec(BaseModel, extra="forbid"): id: str; project: str; task: str | None; host: str | None; grid: list[SweepParam]; random: int | None = None; seeds: list[int]; command_template: list[str]; created_by: str; created_at: datetime; run_ids: list[str] = []
def expand(spec: SweepSpec, rng_seed: int = 0) -> list[dict[str, str]]: ...   # grid product (+ random samples), each dict = params; seeds applied separately
def save_sweep(layout: Layout, spec: SweepSpec) -> Path: ...    # <store>/<project>/sweeps/<id>.yaml
def load_sweep(layout: Layout, project: str, sweep_id: str) -> SweepSpec: ...
class SweepSummary(BaseModel): spec: SweepSpec; counts: dict[str, int]; cells: list[dict[str, Any]]; best: dict[str, Any] | None; headline: str; total_usd: float
def summarize_sweep(ctx: Context, project: str, sweep_id: str) -> SweepSummary: ...   # cells: {params, group_id, n, mean, lo, hi, run_ids}
```

## 2. HTTP API additions

Hub (and env servers where marked *env*):

| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | `/api/v1/hosts` | | `list[{name, kind, state: HostState, gpus: list[GpuInfo], queue: int, slurm: {pending, running}|null, cost_today_usd: float, projects: list[str]}]` |
| POST | `/api/v1/hosts/{host}/connect` / `/disconnect` | `{command_id?}` | `HostState` |
| POST | `/api/v1/hosts/{host}/runs` | launch body + `{gpus, queue, slurm?: SlurmDefaults, diff?}` | run record (forwarded) |
| GET | `/api/v1/runs/{id}/files/{path:path}` *env* | `max_bytes` | file bytes; 404 / 413 |
| GET | `/api/v1/gpus` *env* | | `list[GpuInfo]` |
| GET | `/api/v1/queue` *env* | | `[{run_id, position, gpus_requested}]` |
| POST | `/api/v1/sweeps` | `{project, task?, host?, grid, random?, seeds, command, hypothesis, gpus?, queue?, command_id?}` | `SweepSummary` |
| GET | `/api/v1/sweeps/{project}/{id}` | | `SweepSummary` |
| GET | `/api/v1/projects/{project}/sweeps` | | `list[{id, created_at, n_runs, best}]` |
| POST | `/api/v1/sweeps/{project}/{id}/cancel_queued` | `{command_id?}` | `SweepSummary` (queued runs of the sweep stopped as `killed`) |
| POST | `/api/v1/sweeps/{project}/{id}/extend` | `{seeds: list[int], command_id?}` | `SweepSummary` (adds runs for every param combination × new seeds) |
| POST | `/api/v1/runs/{id}/pull` | `{artifact: kind or path, command_id?}` | `{local_path}` |

Run actions on remote runs (stop, rerun, reinfer, reeval, tags, star, archive, notes) keep their routes; the hub forwards to the owning host by `environment_id`. `GET /api/v1/runs/{id}` adds `host_state: ConnState | null` (null = local).

## 3. CLI and MCP additions

CLI (`--json` everywhere): `hx hosts add|list|status|map|rm|upgrade|connect|disconnect`, `hx service install|uninstall`, `hx launch --host H --gpus N --queue [--partition P --time T --account A]`, `hx sweep ...` (spec 8A.6), `hx sweeps [-p P]`, `hx sweep show <id>`, `hx sweep cancel <id>`, `hx sweep extend <id> --seeds 4,5`, `hx pull <run_id> [--artifact X]`, `hx serve --kind ssh|slurm`.
MCP: `list_hosts`, `launch_run(..., host=None, gpus=0, queue=False)`, `launch_sweep(...)`, `get_sweep(project, sweep_id)`, `cancel_sweep(project, sweep_id)`, `extend_sweep(project, sweep_id, seeds)`, `pull_artifact(run_id, artifact)`.

## 4. Frontend

Additions in `ui/` (same stack and rules as phase 1b):
- `ui/src/api/models.ts`: `HostState`, `HostRow`, `GpuInfo`, `SweepSummary`, `CostTotals`, executor additions.
- Overview panel "Hosts" (`ui/src/pages/components/HostsPanel.tsx`) as panel a; the existing "Runs by launcher" timeline, Ideas, Failures and Projects stay below it (the phase 2 mockup dropped the timeline for space; keep it).
- Launch dialog (`ui/src/launch/LaunchDialog.tsx`), opened from the Task page "New run" and from a sweep page "Rerun sweep".
- Sweep page route `/s/:project/:id` (`ui/src/pages/Sweep.tsx`) with actions Copy as CLI, Cancel queued, Add seeds.
- Run page states: queued (position), remote (host, GPUs, SLURM job/node), stale (since), lost (reason); cost line.
- Live updates: `mirror.run_updated` and `host.*` events invalidate hosts, runs, overview, sweeps.
- Mockups: `docs/mockups/phase2/`.

## 5. Plans

- `docs/superpowers/plans/2026-10-03-hypothex-phase2-backend.md` — sections 1–3 + Docker integration harness (`tests/docker/`: sshd image, slurm compose) + docs.
- `docs/superpowers/plans/2026-10-03-hypothex-phase2-frontend.md` — section 4; Playwright smoke needs fake remote hosts: the backend plan provides ONE command (`hx demo --with-hosts`, plan picks the mechanism, e.g. separate demo homes for fake hosts plus `route: url` entries and a helper that serves them) so `hx serve` on the hub shows connected fake hosts with GPUs, a queue, a SLURM host, and a sweep.
