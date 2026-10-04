# Hypothex — Design Spec

- **Date:** 2026-09-26
- **Status:** Draft, awaiting review
- **Package:** `hypothex` (PyPI), `hypothex` (npm, UI only). CLI: `hx`.
- **License:** open source (license to pick before first public release; Apache-2.0 suggested).

## 1. Purpose

Hypothex is an experiment tracker and control panel for AI researchers who run many
experiments across many projects, on a laptop, SSH boxes, and SLURM clusters, and who
work alongside coding agents (Claude Code, Codex, etc.).

It answers, for every run, in one place:

- Which project, which task, which hypothesis?
- Which exact dataset (host, path, content hash) and which exact metric (name + version)?
- Where are the code (repo + commit + diff), the results, the checkpoints, the logs?
- How do I rerun it, re-run only inference, or re-score it with a new metric version?

And it makes the most common research loop trivial for a human or an agent:
**"same dataset + same metric, new model → run → compare on the leaderboard."**

### Success criteria

1. A new project can adopt Hypothex by adding one file (`hypothex.yaml`) and prefixing
   its command with `hx run --`.
2. An agent with only shell access can, from zero context, find a task, read its
   leaderboard, launch a new iteration with a hypothesis, and compare the result — using
   only `hx ... --json` and the shipped skill file.
3. Bumping a metric version and clicking "re-evaluate all" re-scores every past run of a
   task from saved predictions, without rerunning inference, and without losing old scores.
4. Deleting the SQLite index loses nothing: `hx reindex` rebuilds it from files.
5. A remote run whose host goes down is shown as `lost`, never as `finished`.

### Non-goals (all phases)

- Not a training framework, config system, or model registry. Hypothex wraps whatever
  command the project already has.
- Not a data versioning system. It fingerprints datasets; it does not store copies.
- Not a hosted SaaS. Self-hosted only.

### Prior art and what we borrow

Researched 2026-09-26: MLflow 3, W&B/Weave, Aim, DVC, ClearML, Opik, Langfuse, Inspect AI,
lm-eval-harness, Trackio, Guild, Sacred. No single tool covers cross-project view +
explicit paths + launch on SSH/SLURM + versioned re-eval + agent-first interfaces.

Borrowed ideas:
- **MLflow:** project/run model, step-wise metric history, run compare view.
- **DVC:** stage split (train / infer / eval) so only the changed stage reruns.
- **Inspect AI:** re-score saved outputs without re-running the model.
- **Trackio:** local-first storage in plain files agents can read.

We do not run the MLflow server or depend on MLflow.

## 2. Core concepts

| Concept | Definition | Identity |
|---|---|---|
| **Project** | A code repo with a `hypothex.yaml`. | `project` name, unique |
| **Dataset** | A named, versioned pointer to data on a host. | `name@version` |
| **Metric** | A named, versioned scoring function in project code. | `name@version` |
| **Task** | Dataset(s) + metric(s) + eval protocol. The unit of comparison. | `task` name, unique in project |
| **Run** | One execution of a command, linked to a project and (usually) a task. | `run_id` |
| **Score** | A value for (run, metric@version). A run can hold many versions of one metric. | (run_id, metric, version) |
| **Seed group** | Runs of one task whose config differs only in `seed`. | derived |
| **Sweep** | A set of runs launched together from a config grid/random search. (Phase 2) | `sweep_id` |
| **Host** | A place runs execute: `local`, `ssh`, or `slurm`. | host name |

Rules:
- Every run has a **hypothesis** (one sentence: why this run exists). Required for runs
  started by agents (`--hypothesis`); for humans, the CLI prompts if missing and a TTY
  is attached, else stores `""` and flags it in the UI.
- A run without a task is **exploratory**. It appears in project views but on no leaderboard.
- Runs are immutable after they end, except: tags, star, archive, notes, and added scores.

## 3. Source of truth: files first

Files are the source of truth. The database is a rebuildable index.

### 3.1 Project file: `hypothex.yaml` (in the project repo root)

```yaml
project: deepretro
description: Multi-step retrosynthesis with LLM-guided search.

datasets:
  uspto50k:
    version: v1
    host: gpu-box-1            # where the canonical copy lives
    path: /data/uspto50k/test.jsonl
    description: USPTO-50k test split (Schneider 2016 split)
    splits: {train: /data/uspto50k/train.jsonl, test: /data/uspto50k/test.jsonl}

metrics:
  topk:
    version: v2
    fn: deepretro.eval.metrics:topk_accuracy   # module:function in this repo
    higher_is_better: true
    params: {k: [1, 5, 10]}
    changelog:
      v1: initial
      v2: canonicalize SMILES before matching

tasks:
  uspto50k-topk:
    dataset: uspto50k
    split: test
    metrics: [topk]
    primary: topk/k=1           # metric/key the leaderboard sorts by (`@` is reserved for versions)

stages:                         # command templates; {vars} are filled by hx
  train: python -m deepretro.train --config {config} --out {run_dir}/artifacts
  infer: python -m deepretro.infer --ckpt {checkpoint} --data {dataset.path} --out {run_dir}/predictions
  eval:  hx eval --run {run_id}   # default: built-in metric runner

env:
  setup: uv sync                # optional, run before stages on a fresh host
```

Validation: `hx validate` checks schema, that every `fn` imports, and that every task's
dataset/metric exists. Built-in template variables are `run_id, run_dir, repo, task, seed,
config, checkpoint, dataset.name, dataset.version, dataset.path`; any other `{name}` must be
passed with `--var name=value` (validate warns; launch fails before creating a run if a
value is missing).

### 3.2 Run folder

```
<store>/<project>/runs/<run_id>/
  run.yaml            # all facts about the run (below)
  config.yaml         # resolved config passed to the command (if any)
  metrics.jsonl       # step-wise metric history: {"step":1,"name":"loss","value":0.4,"t":...}
  scores.jsonl        # final scores, append-only: {"metric":"topk","version":"v2","key":"k=1","value":0.61,...}
  predictions/        # per-example outputs: predictions.jsonl (or .parquet)
  logs/stdout.log, logs/stderr.log
  env/                # pip freeze / uv.lock copy, nvidia-smi, system info
  git.diff            # uncommitted changes at launch
  notes.md            # human/agent notes
```

`run.yaml`:

```yaml
run_id: 01J8Z3K7-uspto-a1b2
project: deepretro
task: uspto50k-topk            # null => exploratory
hypothesis: Beam width 20 improves top-10 without hurting top-1.
kind: full                      # full | infer | eval
parent: 01J8Y...                # set for rerun / re-infer / re-eval
stage: infer
command: python -m deepretro.infer --ckpt ... --out ...
cwd: /home/sv/deepretro
host: gpu-box-1
executor: {type: slurm, job_id: "448213", partition: gpu}
git: {repo: git@github.com:.../deepretro, commit: 9f3c2e1, branch: main, dirty: true}
datasets:
  - {name: uspto50k, version: v1, host: gpu-box-1, path: /data/uspto50k/test.jsonl,
     hash: "xxh3:4be1...", size: 1834201, checked_at: 2026-09-26T14:32:00Z}
seed: 1
config_hash: sha256:...         # hash of config minus seed (for seed groups)
status: finished                # queued | running | finished | failed | killed | lost
started_at: ...
ended_at: ...
exit_code: 0
artifacts:                      # big files: recorded, not copied
  - {kind: checkpoint, host: gpu-box-1, path: /scratch/sv/runs/.../model.pt, size: 4.2e9}
cost: {gpu_hours: 3.1, gpu_type: A100-80GB, api_usd: 0.0}   # phase 2
tags: [ablation]
starred: false
archived: false
```

Writes are atomic (write temp file, then rename). `run.yaml` is rewritten on each status
change; `metrics.jsonl` and `scores.jsonl` are append-only.

### 3.3 Store location

- Default store: `~/.hypothex/store/`. Override with `HYPOTHEX_HOME`.
- Local runs write straight into the store.
- Remote runs write into `<host.workdir>/.hypothex/runs/<run_id>/` and are pulled
  into the hub store (section 5.5).

### 3.4 Index

SQLite (WAL mode) at `~/.hypothex/index.db`. Because the index is disposable, phase 1 stores
a schema version and rebuilds the index from files when it changes; Alembic arrives with
Postgres in phase 3.
Tables: `projects, datasets, metrics, tasks, runs, scores, metric_points, tags, hosts,
queue, sweeps, notes`. `metric_points` stores downsampled history for fast charts; full
history stays in `metrics.jsonl`.

- The index is updated by the same code path that writes files (file first, then row).
- `hx reindex [--project P]` rebuilds from files. A file watcher is not needed: all writes
  go through Hypothex.
- Server mode (phase 3) swaps SQLite for Postgres via the same SQLAlchemy models.

## 4. Datasets and environment capture

### 4.1 Dataset fingerprint

- Files ≤ 2 GB: full content hash (xxh3-128).
- Files > 2 GB or directories: "manifest hash" = xxh3 of sorted (relative path, size,
  mtime, xxh3 of first+last 4 MB of each file). Recorded as `hash_mode: manifest`.
- Hash is computed on the host that holds the data (over SSH for remote hosts), cached by
  (host, path, size, mtime).
- At launch, the run records the current hash. `hx datasets check` re-hashes and flags
  every run whose recorded hash differs from the current one ("data changed since run").
- **Overlap check:** for tasks that declare `splits`, `hx datasets overlap uspto50k`
  hashes each example (by a configurable key field, default whole line) and reports
  train/test overlap count.

### 4.2 Environment capture (at launch, on the executing host)

`uv.lock` or `pip freeze`, Python version, OS, CPU, `nvidia-smi --query-gpu=...`,
CUDA/driver versions, relevant env vars (allow-list; secrets never captured), git commit,
branch, remote, and `git diff HEAD` (capped at 5 MB, else stored as "too large" + stat).

## 5. Execution

### 5.1 Entry points

- `hx run [--task T] [--hypothesis H] [--seed N] [--tag X] -- <command...>`
  Runs **in the foreground** on the current machine: captures env, starts the command,
  streams output to terminal and to `logs/`, records exit status. This is what agents and
  humans use inside a project.
- `hx launch --task T --stage infer --host gpu-box-1 [--var checkpoint=...] ...`
  Starts a stage **in the background** on any host, using the stage template.
- `hx rerun <run_id> [--host H]` — same command, same commit, same config. If the host's
  checkout is at a different commit, Hypothex runs in a clean `git worktree` at the
  recorded commit and applies `git.diff`.
- `hx reinfer <run_id> [--checkpoint PATH]` — runs the `infer` stage with the parent's
  checkpoint; new run with `kind: infer`, `parent: <run_id>`.
- `hx reeval <run_id | --task T> [--metric topk@v2]` — runs metrics on saved predictions;
  appends new scores to the **same** run (does not create a new run). Default: all runs of
  the task that lack a score for the current metric version.

### 5.2 Environments (adapted from T3 Code)

An **environment** is one running `hx serve` process plus the machine, files, and
processes it owns. Execution always happens inside an environment, never in a client
(UI, CLI on another machine, agent). Adapted from T3 Code (MIT, © 2026 T3 Tools Inc.;
`docs/internals/remote.md`, `packages/contracts/src/environment.ts`).

- **Kinds:** the Mac (the **hub**, holds the cross-project index and serves the UI), each
  SSH box (an **env server**), and each SLURM cluster (an env server on the login node,
  which submits to SLURM).
- **Identity is not the route.** Each environment has a stable `environment_id` created once
  and stored in `~/.hypothex/environment.json`. How the hub reaches it (local, SSH tunnel,
  Tailscale, direct URL) can change without changing identity.
- **Descriptor:** `GET /.well-known/hypothex/environment` returns
  `{environment_id, label, os, arch, hostname, hx_version, protocol_version, kind:
  local|ssh|slurm, gpus, capabilities: [...]}`. The hub refuses to talk to an env with an
  incompatible `protocol_version` and shows "upgrade hx on <host>".
- **Env servers own their runs.** They start processes, supervise them, write the run
  folder, and keep their own event log. So a run keeps going and keeps being recorded
  even if the Mac sleeps or the network drops. No tmux-polling from the Mac.
- **Bootstrap over SSH** (from T3 Code `packages/ssh/src/tunnel.ts`): `hx hosts add gpu-box-1
  --ssh gpu1` runs a POSIX script over SSH that installs `hx` into `~/.hypothex/runtime`
  (under a lock dir), reuses an already-healthy env server if its pid/port file in
  `~/.hypothex/serve/` says so, else starts `nohup hx serve --host 127.0.0.1 --port 0`,
  probes readiness, and on failure returns the last 80 log lines. The hub then opens
  `ssh -N -L <local>:127.0.0.1:<remote> -o ExitOnForwardFailure=yes -o ServerAliveInterval=15`.
  The hub only stops env servers it started (`managed` vs `external`).
- **Long-lived env servers:** `hx service install` writes a systemd user unit (Linux) or
  launchd agent (macOS) so an env server survives reboots/logouts.
- **Kicking off runs from anywhere:** any client connected to the hub (UI in a browser,
  `hx` CLI on another laptop, an agent via MCP) can launch a run on any environment. A
  user or agent working directly on a remote machine uses `hx run` there; the local env
  server records it, and the hub picks it up on next sync. Offline work is never lost.

### 5.3 Event log, streaming, and reconnect (adapted from T3 Code)

- **Event log is the truth for run state.** Each env server has an append-only event log
  (SQLite, per environment) with a monotonically increasing `sequence`:
  `run.created, run.started, run.log_chunk, run.metric, run.score_added, run.finished,
  run.failed, run.killed, run.lost, ...`. Run folders are written by a reactor from these
  events (file layout in 3.2 is unchanged).
  Phase 1a simplification: every state change is written synchronously under a per-run
  file lock in the order run folder → event → index; the event log is the ordered change
  feed that streams and replay use. A reactor model can replace this later without
  changing the file layout or the event schema.
- **Commands are idempotent.** Every mutating call (`launch`, `rerun`, `stop`, ...) carries a
  client-generated `command_id`. The env server stores a receipt in the same transaction
  as the resulting events; a repeated `command_id` returns the first result. A
  double-clicked "Rerun" starts one run. A command whose server process died before
  its result was stored is never replayed: its outcome is unknown, so a retry with
  that id gets `409 CommandInterruptedError`.
- **Resumable streams.** The hub subscribes to each env with `after_sequence=<last seen>`.
  The env replays missed events, then streams live ones. The hub drops duplicates by
  sequence. The UI subscribes to the hub the same way.
- **Transport:** WebSocket carrying typed JSON messages (Pydantic models, one schema module
  shared by server and a generated TS client) for commands + subscriptions; plain HTTP for
  snapshots, files, and auth.
- **Reconnect:** one connection supervisor per environment in the hub (not per UI
  component). Backoff 3/4/8/16 s, reset after 30 s stable. "Connected" is separate from
  "ready" (ready = descriptor fetched and replay done). Auth failures stop retrying until
  the user re-pairs.
- **Startup repair:** on start, an env server reconciles runs it recorded as `running`:
  supervisor process still alive → keep; supervisor dead but the command still alive → the
  command is terminated and the run marked `lost` (its output pipes are gone, so it cannot be
  re-attached; ruling 2026-10-03); the rest as follows: SLURM job still in `squeue` → keep; exited with an exit record
  → finish/fail; otherwise → `lost`.
- **Bounded log tails:** the live log stream keeps the last 5,000 lines / 8 MiB in memory
  and on disk for fast attach; full logs stay in `logs/`.

### 5.4 Runners (inside an env server)

One interface, used by each env server for its own machine:

```python
class Runner(Protocol):
    def start(self, spec: LaunchSpec) -> ExecutorRef: ...
    def status(self, ref: ExecutorRef) -> RunStatus: ...
    def stop(self, ref: ExecutorRef) -> None: ...
    def pull(self, ref: ExecutorRef, dest: Path) -> None: ...
```

- **Local process:** detached subprocess in its own process group; PID in run dir. Used
  by the Mac and by SSH-box env servers. Survives env-server restarts (startup repair
  re-attaches by PID).
- **SLURM (phase 2):** renders an `sbatch` script (resources from `--gpus`, `--time`,
  `--partition` or env defaults), submits locally on the login node, tracks with
  `squeue`/`sacct`. The job itself runs `hx run --child <run_id>` on the compute node,
  which writes to the shared filesystem run folder; the env server tails it.

Environments file on the hub, `~/.hypothex/environments.yaml`:

```yaml
environments:
  mac: {route: local}
  gpu-box-1: {route: ssh, ssh_alias: gpu1, workdir: /home/sv/hx, gpus: 4}
  cluster: {route: ssh, ssh_alias: login-node, workdir: /scratch/sv/hx, kind: slurm,
            defaults: {partition: gpu, time: "12:00:00", gpus: 1}}
  lab-server: {route: url, url: https://lab.tail1234.ts.net:7777}   # phase 3
```

### 5.5 Sync of results to the hub

Event replay (5.3) keeps run state, metrics, and scores in sync. Files are synced by the
hub over the same route: small files in the run folder are fetched over HTTP from the env
server (`GET /runs/{id}/files/...`), excluding `artifacts/` and any file > 200 MB
(configurable). Big files stay remote and are recorded as `{environment, path, size}`.

### 5.6 Status and lost runs

Env servers know their own run status exactly. The hub marks an environment
`unreachable` when its supervisor cannot reconnect; runs on it show `status (stale)`, not
`lost`. A run is `lost` only when the env server itself decides so (startup repair or
SLURM job vanished without exit record). If an env server is unreachable for > 24 h
(configurable: `stale_banner_hours` at the top of `environments.yaml`, default 24, served
on every `GET /api/v1/hosts` row), the hub shows a banner, still not `lost`.

### 5.7 Queue and sweeps (phase 2)

- `hx launch --queue` puts the run in `queue`. The daemon starts it when the target host
  has free GPUs (from `nvidia-smi` for SSH hosts; SLURM hosts use SLURM's own queue, so
  Hypothex just submits). A run targets exactly one host: there is no queue across hosts
  (`--hosts a,b` was dropped on 2026-10-03; launch on each host you want to use).
- `hx sweep --task T --grid lr=1e-4,3e-4 --grid beam=10,20 --seeds 3 -- <stage or cmd>`
  creates a sweep and queues its runs. UI shows the sweep as a group with its best config.

## 6. Metrics and re-evaluation

### 6.1 Metric function contract

```python
from hypothex import MetricResult, Example

def topk_accuracy(examples: list[Example], *, k: list[int]) -> MetricResult:
    """examples[i] has .id, .prediction, .reference (from predictions file + dataset)."""
    ...
    return MetricResult(values={"k=1": 0.61, "k=5": 0.83}, per_example={"ex-17": {...}})
```

- Predictions file rows: `{"id": ..., "prediction": ..., "reference"?: ..., "meta"?: {...}}`.
  If `reference` is absent, Hypothex joins it from the task dataset by `id`.
- Hypothex runs the function inside the project's environment
  (`uv run --project <repo> python -m hypothex.eval_worker ...`) so project imports work.
- Per-example results are written to `predictions/scores.<metric>@<version>.jsonl`
  and feed the example browser.

### 6.2 Versioning

- Version string comes from `hypothex.yaml`. Hypothex also stores a hash of the function's
  source. If the source hash changes but the version does not, `hx validate` and the UI
  warn: "metric code changed without a version bump".
- Old scores are never overwritten. Leaderboards default to the current version and show
  a badge with how many runs are on older versions, plus a "re-evaluate N runs" button.

### 6.3 Seed groups and error bars

- `config_hash` excludes `seed`. Runs in one task with the same `config_hash`, git
  commit and uncommitted diff (`git.diff_hash`) form a seed group. A dirty run's group
  id ends in `+<diff hash[:4]>`; clean ids do not change.
- Leaderboard rows are seed groups: `mean ± std (n=3)`. Single runs show `n=1`. `n` counts
  distinct seeds: reruns of one seed are averaged into one sample (runs without a seed
  count one each), so a rerun never narrows the error bar.
- A row whose test against the best row (8.5: sign test, paired bootstrap, or Welch over
  seeds) gives `p ≥ 0.05` is marked "within noise" (`within_noise_of_best`); with no `p`
  (no per-example data and n < 2) it is unknown. Seed t-intervals alone do not decide it:
  wide seeds can hide a clear paired win, and zero-variance seeds can fake one. n=1 rows
  get a "single seed" badge.

## 7. Interfaces

All interfaces call one Python core library (`hypothex.core`). No logic lives only in
the CLI, API, or MCP layers.

### 7.1 Python SDK (in project code; optional)

```python
import hypothex as hx

run = hx.current()                      # the run started by `hx run`, or a no-op stub
run.log({"loss": 0.41}, step=120)       # -> metrics.jsonl
run.log_predictions(rows)               # -> predictions/predictions.jsonl
run.log_artifact("/scratch/.../model.pt", kind="checkpoint")
run.note("Loss spikes at step 9k; LR warmup too short?")
```

Outside `hx run`, `hx.current()` returns a stub that does nothing, so code runs unchanged
without Hypothex.

### 7.2 CLI (`hx`)

Every command supports `--json` (stable schema, documented) for agents.

| Command | Purpose |
|---|---|
| `hx init` | Create `hypothex.yaml` in the current repo (interactive or `--from-template`). |
| `hx validate` | Check project file, imports, metric source hashes. |
| `hx projects` / `hx tasks [-p P]` / `hx task show T` | Discover. |
| `hx leaderboard T [--metric m@v]` | Ranked seed groups for a task. |
| `hx runs [-p P] [--task T] [--status S] [--tag X]` | List/filter runs. |
| `hx show <run_id>` | Everything about a run, incl. all paths. |
| `hx run / launch / rerun / reinfer / reeval / stop` | Execution (section 5). |
| `hx compare <id> <id> ...` | Config diff + score diff. |
| `hx tag / star / archive / note` | Curation. |
| `hx datasets register/check/overlap` | Datasets (section 4.1). |
| `hx hosts list/add/setup/status` | Hosts (phase 2 for remote). |
| `hx sweep` | Phase 2. |
| `hx export T --format latex\|markdown` | Paper tables (phase 3). |
| `hx storage report/clean` | Phase 3. |
| `hx serve` | API + UI + daemon (scheduler, poller, puller, notifier). |
| `hx reindex` | Rebuild index from files. |

### 7.3 HTTP API

FastAPI under `/api/v1`, OpenAPI docs at `/api/docs`. The UI uses only this API.
Resources mirror the CLI: projects, tasks, leaderboards, runs, scores, metric points,
predictions (paged), datasets, environments, queue, sweeps, notes. Actions: `POST
/runs/{id}/rerun|reinfer|reeval|stop`, `POST /tasks/{t}/reeval`; all actions accept a
`command_id` for idempotency (5.3). Live updates (run events, logs, metrics) go over the
WebSocket with `after_sequence` replay (5.3), not SSE. The same API is served by the hub
and by env servers; the hub proxies env-specific calls to the owning environment.
Phase 1–2: bound to `127.0.0.1` (remote envs reached through SSH tunnels), no auth.
Phase 3: auth (section 9).

### 7.4 MCP server

`hx mcp` (stdio) and `/mcp` on the server (streamable HTTP). Tools map 1:1 to core
actions: `list_projects, list_tasks, get_task, get_leaderboard, list_runs, get_run,
compare_runs, launch_run, rerun, reinfer, reevaluate, stop_run, add_note, tag_run,
get_predictions`. Built with the official `mcp` Python SDK.

### 7.5 Agent skill

Shipped as `skills/hypothex/SKILL.md` (installable into Claude Code / Codex / AGENTS.md).
Teaches the loop:

1. `hx tasks --json` → pick the task.
2. `hx leaderboard <task> --json` → see current best and what was tried.
3. Read top runs' hypotheses + notes to avoid repeating work.
4. `hx run --task <t> --hypothesis "<why>" -- <command>` (seeds ≥ 3 for claims).
5. `hx compare` against the current best; write a note with the finding.
6. Never delete runs; never change a metric without bumping its version.

## 8. UI, task kinds, and views (phase 1b)

Approved mockups (2026-09-27): `docs/mockups/ui-v4/` (base design system and the
Overview, Leaderboard, Run, Examples screens) and `docs/mockups/kinds/{training,
agent_eval, agent_iteration, system_bench, custom_view}/`. The mockups are the visual
reference; where this section and a mockup disagree, this section wins.

### 8.1 Principles

- **Terse.** Numbers, glyphs, short labels. No explanatory sentences on the page;
  explanations live in hover tooltips. Each page's headline is one line with the finding
  and its number (for example `SVM +0.037 over rf, p = 0.15`), generated from the data.
- **Journal-figure style.** Panels are lettered (a, b, c …) with a few-word title. No
  identical bordered cards; panels are separated by space and hairlines.
- **Two kinds of noise, always.** Seed noise (per-seed dots; identical seeds collapse to a
  `◇×3` glyph, never a fake `± 0`) and test-set noise (95% interval, section 8.5). The best
  group's test-set interval is drawn as a band that other rows are compared against.
- **Where everything is.** Every run page lists code, data, run folder, logs, predictions,
  checkpoints as `host:path`; the run folder is shown once and its children relative to it.
- Dark and light mode are equal citizens. `⌘K` palette searches projects, tasks, runs,
  and paths. Monospace only for paths, commands, and YAML.

### 8.2 Stack

React + TypeScript + Vite, built and tested with Bun, in `ui/`. TanStack Router and
Query. Plain CSS with design tokens copied from `ui-v4` (no Tailwind, no component kit).
Charts are React SVG components using `d3-scale`/`d3-shape`/`d3-array` for math only.
`vega-embed` renders `vega_lite` panels. Built assets ship in the wheel at
`src/hypothex/ui_dist/`; `hx serve` serves them. Live updates come from the WebSocket
event stream (section 5.3).

### 8.3 Screens

1. **Overview** — headline status line; runs-by-launcher timeline (agent vs human,
   failed, archived, current best); recent ideas (one line per seed group, one mark per
   seed); running; failures with a link to stderr; projects table.
2. **Task** — view tabs: the kind's preset view, any custom views, `+ view`.
3. **Run** — kind-specific run detail (8.4) plus the common parts: hypothesis as title,
   status, stat strip, scores by metric version, where everything is, notes, actions
   (rerun / re-infer / re-evaluate / stop).
4. **Examples** — two-run per-example comparison: 2×2 outcome table, one-mark-per-example
   strip, sign-test p, failing examples list.
5. **View editor** — YAML on the left with inline validation (red marker, message,
   suggested fix), live preview on the right on a 12-column grid, insert-panel palette,
   Save (disabled while invalid), Discard, Copy as CLI.

### 8.4 Task kinds

`TaskSpec.kind` in `hypothex.yaml`: `generic` (default), `training`, `agent_eval`,
`agent_iteration`, `system_bench`. A kind is only a preset view (8.6) plus a run-detail
layout; it never changes storage or evaluation.

| Kind | Preset task view | Run detail adds |
|---|---|---|
| generic | stat strip, leaderboard | metric charts |
| training | leaderboard (best checkpoint or final), small-multiple curves (train/val loss, val metric, lr; seeds faint, mean bold, best checkpoint marked, spikes and kills marked), runs table with GPU sparklines, checkpoints | stacked curves on one step axis, checkpoints list |
| agent_eval | leaderboard with $ and time, cost-or-time vs score scatter with Pareto front, failure-category bars, items × configs outcome grid, trajectory of a selected attempt | step list (turn, tool, args, result, tokens, seconds; failing step marked), same item across configs, tokens per turn |
| agent_iteration | score over versions with CI ribbon and change labels, regressions marked, cost per success over versions, changes table, flip grid between two versions, leaderboard | same as agent_eval |
| system_bench | leaderboard on a chosen percentile, latency distributions (log scale, p50/p95/p99 ticks), percentile table with Δ and CI vs baseline, throughput vs concurrency, error rate, utilisation strips, repeat spread with outliers flagged | latency over time, utilisation strips, tail vs other repeats |

`agent_iteration` orders seed groups by `version` (a run param, default: creation time of
the group's first run). `system_bench` compares against `baseline:` (a seed-group
selector in the task spec).

### 8.5 Statistics (`hypothex.core.stats`)

- **Test-set interval** per seed group: if the metric's per-example field is binary
  (`correct`/`solved`/any bool), the Wilson 95% interval with `n` = examples scored;
  otherwise a percentile bootstrap over examples (1,000 resamples, fixed seed 0). Seeds are
  pooled by averaging per example first (the runs of one seed are averaged first).
- **Paired comparison vs best**: binary → exact two-sided sign test on discordant examples
  (fixed vs broken); continuous → paired bootstrap of the mean difference. Reported as `p`.
- **Examples needed**: the smallest `n` at which the observed discordant rate would give
  `p < 0.05` (shown as `≈250`).
- **Seed comparison** (training, no per-example data): Welch t-test over seed values.
- Percentiles for `system_bench` use the raw samples (8.7); their CI comes from repeats.
All functions are pure, typed, and unit-tested against known values (scipy is not a
dependency; exact binomial tails are computed directly).

### 8.6 Views: user-defined dashboards

A view is YAML: a list of panels. Presets for each kind ship in the package
(`src/hypothex/views/presets/<kind>.yaml`). Custom views live in the project repo at
`.hypothex/views/<task>/<name>.yaml` (committed with the code); a task may also declare
`views:` inline in `hypothex.yaml`. The UI editor saves to the file form.

```yaml
title: route quality
from: agent_eval            # optional: start from a preset and override panels
runs: {status: finished}    # run filter: status, tags, created_by, since
panels:
  - type: stat_strip | leaderboard | curves | scatter | distribution | grid |
          table | trace | markdown | vega_lite
    title: Best config
    data: {metrics, x, y, group_by, filter, pick, source, fields}   # per type
    layout: {span: 1-12, row: N}
    # type-specific: noise (leaderboard), pareto (scatter), spec (vega_lite), text (markdown)
```

- Metric references use the existing syntax (`name@version/key`, section 6); aggregates
  `/mean`, `/median`, `/p95` apply to samples and per-example values.
- `source` for `table`/`vega_lite`: `runs`, `scores`, `metrics` (step history),
  `predictions` (per-example rows + per-example scores), `samples`, `usage`, `traces`.
- Validation (`hypothex.core.views.validate_view`) checks schema, metric names (with a
  nearest-name suggestion), sources, fields, and Vega-Lite spec shape; errors carry a line
  number. Invalid views are never saved.
- Panel data is computed server-side: `POST /api/v1/views/query` takes a panel and returns
  rows; the UI never reads files.
- CLI: `hx view list <task>`, `hx view show <task> <name>`, `hx view init <task> --from
  <kind> --name N`, `hx view add <task> --file view.yaml`, `hx view validate <file>`.
  MCP: `list_views`, `get_view`, `add_view` (validates first). API: `GET/PUT/DELETE
  /api/v1/tasks/{project}/{task}/views/{name}`, `POST .../views/validate`.

### 8.7 SDK and storage additions

- `run.log_trace(example_id, steps)` → `traces/<example_id>.jsonl`; a step is
  `{turn, tool, args, result, tokens_in, tokens_out, seconds, error?}`.
- `run.log_usage(tokens_in=0, tokens_out=0, usd=0.0, seconds=0.0, example_id=None)` →
  `usage.jsonl`; run totals are indexed.
- `run.log_samples(name, values)` → `samples/<name>.jsonl` (raw values, e.g. latencies).
- Prediction rows may carry `meta.category` (failure type) and `meta.difficulty`.
- `run.log_checkpoint(path, step, metrics)` = `log_artifact(kind="checkpoint")` plus step
  and metrics, used by the training views.

### 8.8 Git state fix

`GitInfo.dirty` counts tracked changes only. Untracked files are recorded separately as
`git.untracked` (count + first 20 names). The run page says "untracked files only" when
there is no tracked diff. This fixes a misleading warning found in the acceptance run.

## 8A. Phase 2 details (approved 2026-10-03)

Builds on 5.2–5.7. Mockups: `docs/mockups/phase2/`. Testing never touches the user's real
hosts: in-process fake hosts, fake `sbatch`/`squeue`/`sacct`, and Docker containers
(sshd, small SLURM cluster) for integration tests.

### 8A.1 Environments file and hosts

`~/.hypothex/environments.yaml` (hub only) holds one entry per host:

```yaml
environments:
  gpu1:
    route: ssh            # ssh | url | local
    ssh_alias: SV-a100-retrollm2   # a Host from ~/.ssh/config
    kind: ssh             # ssh | slurm
    home: ~/.hypothex     # hx home on the host (shared FS required for slurm)
    usd_per_gpu_hour: 2.10   # optional, for cost
    slurm: {partition: gpu, account: null, time: "02:00:00", gpus: 1}   # kind: slurm only
    projects: {deepretro: /home/sv/code/DeepRetro}   # project -> repo path on the host
```

CLI: `hx hosts add <name> --ssh <alias> [--slurm --partition P ...]`, `hx hosts list`,
`hx hosts status [<name>]`, `hx hosts map <project> <host> <path>`, `hx hosts rm <name>`,
`hx hosts upgrade <name>`, `hx service install|uninstall` (on the host itself), and
`hx hosts connect|disconnect <name>`.

### 8A.2 Bootstrap and tunnel

`hx hosts add`/`connect` runs, over the user's own `ssh` binary (agent and config honoured):

1. Probe: `uname`, Python ≥ 3.11 or `uv` available, `nvidia-smi -L`, `sbatch --version`.
2. Install: the hub builds its own wheel (`uv build --wheel`, cached by version) and copies
   it with `scp` to `<home>/runtime/wheels/`. The host installs it with
   `uv tool install --force` into `<home>/runtime/` (if `uv` is missing, the install fails
   before the upload with an error that asks for `uv`, unless the user allowed the official
   installer (`install_uv`), which then puts it into `~/.local/bin`; no network → clear error
   naming the missing piece). Under a lock dir, so two hubs never race.
3. Start: reuse a healthy server recorded in `<home>/serve/server.json` (pid, port,
   managed|external, hx_version); else `nohup hx serve --host 127.0.0.1 --port 0`, wait for
   the descriptor, on failure return the last 80 log lines.
4. Tunnel: `ssh -N -L 127.0.0.1:<free local port>:127.0.0.1:<remote port>
   -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=3`. One
   supervisor per host restarts the tunnel with backoff 3/4/8/16 s (reset after 30 s).
5. Version check: incompatible `protocol_version` → host shown as "upgrade" and
   `hx hosts upgrade` reinstalls.

Env servers bind to 127.0.0.1 only. No new network exposure; auth stays in phase 3.

### 8A.3 Hub mirror

- The hub keeps one subscription per host (`after_sequence` replay, 5.3). For each
  `run.*` event it fetches the run's small files (`run.yaml`, `scores.jsonl`,
  `metrics.jsonl`, `notes.md`, `predictions/` up to 200 MB, `traces/`, `samples/`,
  `usage.jsonl`, `logs/` tails) over `GET /api/v1/runs/{id}/files/{path}` and writes them
  under `<hub store>/<project>/runs/<run_id>/` with `environment_id` = the host's id, then
  re-indexes. The hub re-emits a mirror event so UI streams update.
- Per-host cursor (`last_sequence`) is stored in the hub index; restarts resume.
- Big files stay remote as `host:path` artifacts; `hx pull <run_id> [--artifact KIND|PATH]`
  copies one on demand with `scp` into `<hub store>/.../pulled/`.
- Commands for a remote run (stop, rerun, reinfer, reeval, notes, tags) are forwarded to
  the owning host with the same `command_id`; reeval may also run on the hub when the
  predictions are mirrored and the project repo exists locally (default: on the host).

### 8A.4 Code on the host

A run on a host uses the mapped repo path. If the requested commit is not present, the
env server runs `git fetch` in that repo; if the working tree is not at the commit (or the
saved diff differs), it uses a worktree exactly like `hx rerun` (5.1). Launching from the
hub with an uncommitted local diff sends the diff with the request; the host applies it in
the worktree. Missing mapping → clear error naming `hx hosts map`.

### 8A.5 Launch, queue, and GPUs

- `hx launch --host H [--gpus N] [--queue] [--partition P --time T]` (and API `POST
  /api/v1/hosts/{host}/runs`, MCP `launch_run(host=...)`) forwards to the host.
- SSH hosts: a host-level scheduler holds `queued` runs. A GPU is free when no hx run holds
  it and `nvidia-smi --query-compute-apps` shows no process on it. It assigns GPUs, sets
  `CUDA_VISIBLE_DEVICES`, and starts the run FIFO (first fit). Queue position is visible.
- SLURM hosts: render `sbatch` (`--gpus`, `--time`, `--partition`, `--account`,
  `--job-name hx-<run_id>`, `--output <run_dir>/logs/slurm-%j.out`), run `hx run --child`
  on the node; track `squeue`/`sacct` every 30 s; record `executor.slurm_job_id`, node.
  `stop` → `scancel`. A job gone without an exit record → `lost` (5.6).
- Runs record `executor.gpus` (indices) and `executor.host`.

### 8A.6 Sweeps

`hx sweep -t T --grid k=v1,v2 [--grid ...] [--random N --param k=lo:hi[:log]] --seeds S
--host H [--queue] -- <cmd with {k} and {seed}>` writes `<store>/<project>/sweeps/<id>.yaml`
(grid, seeds, host, created_by: the definition only) and launches all runs with tag
`sweep:<owner8>:<id>` (owner8 = first 8 hex of the creating hub's environment id) and params `k=v`. The sweep's runs are the runs with that tag (derived, never
stored); each (params, seed) has one deterministic command id, so a retried launch or extend
issues only the missing runs and never starts one twice. API `POST /api/v1/sweeps`, `GET /api/v1/sweeps/{id}`; MCP `launch_sweep`,
`get_sweep`. Sweep page `/s/<id>`: headline (best config + score), progress counts,
params × primary-metric heat table (mean; CI in tooltip), best cell marked, cost total.

### 8A.7 Host status and cost

- `GET /api/v1/hosts` (hub) → per host: connection state (connected | stale since | bootstrapping |
  upgrade), descriptor, queue length, GPUs `[ {index, name, util, mem_used, mem_total, run_id?,
  external: bool} ]` (from `nvidia-smi` every 10 s on the host), SLURM pending/running counts,
  cost today.
- Cost: `gpu_hours = wall × len(executor.gpus)`; `usd = gpu_hours × usd_per_gpu_hour +
  usage.usd`. `RunRecord.cost = {gpu_hours, gpu_usd, api_usd, total_usd}` filled at finish.
  Leaderboards, run pages, sweeps, and the Overview show cost.

### 8A.8 UI additions

Overview "Hosts" panel; Launch dialog (host, GPUs, queue, SLURM fields, seeds, command
template, hypothesis, resolved-command preview, Copy as CLI); Sweep page; run-page states
(queued with position, remote host:path + GPUs or SLURM job/node, stale since, lost reason).
Same terse rules as section 8.

### 8A.9 Tests

- Unit and integration tests use in-process env servers on random ports (`route: url`) and
  a fake `ssh`/`scp` that executes locally into temp homes, plus fake SLURM commands on
  `PATH`.
- Docker integration tests (marked `docker`, skipped when Docker is unavailable): a real
  sshd container (bootstrap, tunnel, reconnect after `docker restart`) and a small SLURM
  cluster (submit, status, cancel, lost detection).
- Never against the user's hosts.

## 9. Phase 3 features (design summary)

- **Lab notebook:** `<store>/<project>/notebook/YYYY-MM-DD.md`; `[[run:<id>]]` links render
  as run chips. Editable in UI and via `hx note --project`.
- **Paper baselines:** `baselines:` block in `hypothex.yaml` per task:
  `{name, value per metric key, source (arXiv/DOI), metric_version_equivalent}`.
- **Notifications:** Slack (incoming webhook) and email (SMTP) on finish/fail/lost, per
  project opt-in, configured in `~/.hypothex/config.yaml`. Secrets read from env vars.
- **Weekly summary:** per project: runs started/finished/failed, leaderboard changes, top
  new notes. Sent via Slack/email; also saved to the notebook.
- **Export:** leaderboard/compare → LaTeX (booktabs) or Markdown, best bolded,
  `mean ± std`.
- **Storage:** report bytes per project/run/artifact (local + remote via `du` over SSH);
  `hx storage clean --archived --older-than 30d --dry-run` deletes only artifacts of
  archived, unstarred runs; always dry-run first in UI.
- **Cost (phase 2):** GPU-hours = wall time × GPUs; optional `$/GPU-hour` per host;
  API spend via `run.log_cost(usd=..., tokens=...)` in the SDK.
- **Team/server mode:** the hub can run on an always-on server with Postgres. Runs record
  `created_by` (human user or agent name).
- **Auth and devices (adapted from T3 Code `apps/server/src/auth/`):** `hx pair` prints a
  one-time pairing URL + QR code (secret in the URL `#fragment`, valid 5 min). A client
  exchanges it for a revocable session (cookie for browsers, bearer token for CLI/agents).
  WebSockets authenticate with a short-lived ticket fetched over HTTP, so long-lived
  tokens never appear in socket URLs. Every API/WebSocket method declares a scope
  (`read`, `launch`, `admin`); a method without a scope fails a unit test. Pairing can
  never grant wider scopes than the issuer holds. Remote access from phones/other laptops
  goes through Tailscale (HTTPS via `tailscale serve`); no custom relay.

## 10. Error handling

- File write first, index second. If the index write fails, the next `hx` command
  detects the gap (run dir without row) and repairs it.
- All run-folder writes are atomic (temp + rename).
- Command not found / bad template var → fail before creating a run.
- Metric function raises → score row with `error` and traceback; other metrics continue.
- Pull failure → retry with backoff; run stays `running` until `lost` rule applies.
- `hx rerun` on a commit that no longer exists → clear error with the commit hash.
- Missing predictions for re-eval → skip run with reason, report count.

## 11. Testing

- **Core (pytest):** config parsing/validation, run lifecycle, atomic writes, reindex
  equivalence (index built live == index rebuilt from files), dataset hashing (both
  modes), seed grouping + interval math, metric versioning + source-hash warning,
  re-eval appends and never overwrites.
- **Environments:** event replay with gaps/duplicates, idempotent command receipts,
  startup repair cases, reconnect supervisor state machine (fake clock); two env servers
  in one test process talking to a hub.
- **Runners:** local runner real subprocess tests; SSH bootstrap tested against one
  optional Docker `sshd` integration test; SLURM tested with fake `sbatch/squeue/sacct`
  scripts on PATH.
- **Interfaces:** CLI `--json` snapshot tests; API tests via FastAPI TestClient; MCP tool
  tests via the SDK's in-memory client.
- **UI:** `bun test` for components/utilities; Playwright smoke test of the six screens
  against a seeded store.
- **End-to-end:** `examples/toy-classifier/` (sklearn, tiny dataset, 2 metrics, 3 models ×
  3 seeds): init → run → leaderboard → bump metric version → reeval → compare. Runs in CI.
- **Pilot:** DeepRetro after phase 1 passes E2E.

Tooling: uv, ruff (lint + format), ty, pytest; Bun for UI. Docs: Sphinx + RTD theme,
numpydoc docstrings.

## 12. Repo layout

```
hypothex/
  pyproject.toml
  src/hypothex/
    core/        # models, store (files), index (SQLAlchemy), datasets, metrics, seeds
    runners/     # local.py, slurm.py, base.py
    env/         # descriptor, event log, command receipts, startup repair
    remote/      # ssh bootstrap + tunnel, hub connection supervisors, file sync
    sdk/         # hx.current(), log, log_predictions, ...
    cli/         # Typer app
    api/         # FastAPI app
    mcp/         # MCP server
    daemon/      # poller, puller, queue scheduler, notifier
    eval_worker.py
    ui_dist/     # built UI assets (generated)
  ui/            # React app (Bun)
  skills/hypothex/SKILL.md
  examples/toy-classifier/
  docs/
  tests/
```

## 13. Phases

| Phase | Scope | Done when |
|---|---|---|
| **1a. Core backend** | Sections 2–4, 5.1 (local), 5.2–5.3 for the Mac environment only (descriptor, event log, idempotent commands, resumable WebSocket streams, startup repair), 5.4 local runner, 6, 7 (all interfaces, local actions), 10, 11 for these parts. | Toy E2E green in CI; DeepRetro onboarded with one task and ≥ 3 runs; an agent completes the section 7.5 loop using only the skill file. |
| **1b. UI, kinds, views** | Section 8: stats, views (presets + custom + editor), SDK additions, git fix, all screens for all kinds, WebSocket live updates. | Each kind's preset renders against a seeded store; a custom view round-trips through editor, file, CLI, and MCP; Playwright smoke test green in both modes. |
| **2. Remote + scale** | Remote env servers: SSH bootstrap + tunnel, `hx hosts add`, `hx service install`, hub supervisors + replay from many envs, file sync (5.5), SLURM runner, stale/lost rules (5.6), queue, sweeps, host/GPU status, cost. | A run launched from the UI on the Docker SLURM cluster and on the Docker sshd host is mirrored to the hub, scored, and shown on the leaderboard; a sweep on a fake 8-GPU host queues and allocates GPUs correctly. A first run on the user's real hosts is the user's manual step. |
| **3. Team + output** | Notebook, paper baselines, Slack + email alerts, weekly summary, export, storage cleanup, pairing + scoped auth, Tailscale access, Postgres server mode. | A collaborator pairs a laptop with a server hub, sees the same projects, and launches a run on a shared environment. |

Each phase gets its own implementation plan.

## 14. Decisions log

| Decision | Choice | Why |
|---|---|---|
| Base | Custom, borrow ideas from MLflow/DVC/Inspect | No tool covers all needs; want own UI and agent-first design |
| Truth | Files; SQLite index rebuildable | Stability; agents read plain files |
| Rerun | Really launches (local/SSH/SLURM) | User choice |
| Remote model | One `hx serve` env server per machine; Mac is the hub (from T3 Code) | Runs survive Mac sleep/network loss; exact status; same code for local and server mode |
| Live sync | Event log + `after_sequence` replay + idempotent `command_id` (from T3 Code) | No gaps after reconnect; no double launches |
| Hosting | Mac first, server-ready | User choice |
| Integration | Wrapper (`hx run`) + optional SDK | Works with any project, richer with SDK |
| Metrics | Versioned; re-score on click | Keeps history honest |
| Datasets | host + path + hash, no copies | Big data stays put |
| Agents | CLI `--json`, MCP, HTTP, skill file | User choice: all four |
| Seeds | Seed groups with mean ± std | AI research claims need noise estimates |
| Alerts | Slack + email | User choice |
| UI style | Journal-figure, terse (mockup ui-v4) | User choice after 3 directions + revisions |
| Dashboards | Task kinds as preset views; custom YAML views with a panel library and a Vega-Lite escape hatch | Training, agent evals, agent iteration, and system benchmarks need different views; users add their own |
| Noise | Seed noise and test-set noise shown separately | Seeds alone overstate certainty on small test sets |
| Regressions & baseline | scatter rows flag regressions on ordinal x; distribution rows carry Δ vs baseline with repeat-bootstrap CI | Needed by agent_iteration and system_bench presets |
| Name | Hypothex / `hx` | Free on PyPI + npm (checked 2026-09-26) |
