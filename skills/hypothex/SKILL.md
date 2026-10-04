---
name: hypothex
description: Use when running, comparing, or iterating on ML/AI experiments in a repo that has a hypothex.yaml, or when asked to track, rerun, re-evaluate, or compare experiments with Hypothex (`hx`).
---

# Hypothex: the experiment loop

Hypothex records every run: task (dataset + versioned metrics), hypothesis, exact
command, git commit + uncommitted diff, config, seed, dataset fingerprints,
environment, logs, predictions, scores. Always use `--json` and parse the output.

Set `HYPOTHEX_AGENT=<your name>` in your environment. Runs then record you as the
author, and Hypothex rejects runs that have no hypothesis.

## Loop for a new iteration

1. Find the task: `hx tasks --json`. Details: `hx task show <task> --json`
   (dataset path + version, metric fns + versions, stages, repo).
2. See the state of the art: `hx leaderboard <task> --json`. Rows are seed groups
   (`mean ± std`, `n`). `within_noise_of_best: true` means "not a real win yet".
3. Read what was tried: `hx show <run_id> --json` for the top rows. Read
   `record.hypothesis` and `notes`. Do not repeat a finished idea.
4. Run the new iteration from the project repo, with a one-sentence hypothesis
   and at least 3 seeds before you claim anything:

   ```bash
   for s in 1 2 3; do
     hx run --json -t <task> -H "<why this should help>" --seed $s -- \
       python train.py --model new --seed '{seed}'
   done
   ```

   `{seed}`, `{run_dir}`, `{dataset.path}`, `{config}` are filled in by Hypothex.
   Use `{seed}` (not a literal number) so runs group into one seed group.
   Quote placeholders (`'{seed}'`) so your shell passes them through unchanged;
   `--seed={seed}` also works.
   Long jobs: `hx launch ... --json` returns at once; check with
   `hx logs <run_id> --follow` or `hx show <run_id> --json`.
5. Compare: `hx compare <new_run> <best_run> --json`, and
   `hx examples <best_run> <new_run> --metric <metric> --json` to see which
   examples got fixed or broken.
6. Write down what you learned: `hx note <run_id> "<finding and next step>"`.
   Tag useful runs: `hx tag <run_id> --add baseline`.

## Rules

- Never delete run folders. To hide a dead end, use `hx archive <run_id>`.
- Never change a metric's code without bumping its `version` in `hypothex.yaml`.
  Then run `hx reeval --task <task> --json`. Old scores stay. The leaderboard
  uses the current version.
- Rerun exactly: `hx rerun <run_id> --json` (same commit, config, and seed; uses
  a git worktree if needed). Re-score only: `hx reeval <run_id> --json`.
  New inference from a checkpoint: `hx reinfer <run_id> --json`.
- If `hx validate --json` shows errors, fix `hypothex.yaml` before you run.
- Your code logs through the SDK: `import hypothex as hx; run = hx.current()`.
  Use `run.log({...})`, `run.log_predictions([{"id": ..., "prediction": ...}])`, and
  `run.log_artifact(path, kind="checkpoint")`. It does nothing outside Hypothex.

## Views (task dashboards)

A view is YAML: `title`, optional `from: <kind>` (start from a preset), optional
`runs:` filter, and `panels` (`stat_strip`, `leaderboard`, `curves`, `scatter`,
`distribution`, `grid`, `table`, `trace`, `markdown`, `vega_lite`). Files live in
`.hypothex/views/<task>/<name>.yaml` in the repo; commit them.

- See: `hx view list <task> --json`, `hx view show <task> <name> --json`.
- Start: `hx view init <task> --from <kind> --name <name> --json`.
- Check, then save: `hx view validate <task> view.yaml --json`, then
  `hx view add <task> --file view.yaml --json`. Fix every issue (`line`, `message`,
  `suggestion`) first; invalid views are never saved.
- MCP: `list_views`, `get_view`, `add_view` (returns `issues` on failure),
  `query_view` (panel rows).

## Remote hosts and sweeps

The hub (`hx serve` on the user's machine) runs work on SSH GPU boxes and SLURM
clusters. Check the hosts first: `hx hosts status --json` (state, GPUs busy, queue,
SLURM jobs, cost today).

- Launch on a host:
  `hx launch --json --host gpu1 --gpus 2 --queue -t <task> -H "<why>" -- python train.py --seed '{seed}'`.
  The host uses its own checkout (set once with `hx hosts map <project> <host> <path>`);
  uncommitted changes are sent along. SLURM hosts also take `--partition`, `--time`,
  `--account`.
- Sweep (a grid x seeds, one command):
  `hx sweep --json -t <task> -H "<why>" --grid lr=1e-4,3e-4 --grid beam=5,10 --seeds 3 --host gpu1 --queue -- python train.py --lr '{lr}' --beam '{beam}' --seed '{seed}'`.
  Every swept name must appear in the command (runs also get `$HYPOTHEX_SEED`). Follow it with
  `hx sweep show <id> --json` (best cell, progress, cost), add seeds with
  `hx sweep extend <id> --seeds 4,5 --json`, stop the queued runs with
  `hx sweep cancel <id> --json`. List sweeps: `hx sweeps --json`.
- Checkpoints stay on the host. Copy one when needed:
  `hx pull <run_id> --artifact checkpoint --json` (prints `local_path`).
- A host that the hub cannot reach shows `stale` or `error` in `hx hosts status`
  (MCP `get_run` and `list_runs` show it as `host_state`; `null` is a hub run).
  Its runs keep going there and are not lost: do not rerun them. Wait, or run
  `hx hosts connect <host>` (MCP: `connect_host`).
- MCP: `list_hosts`, `launch_run(host=..., gpus=..., queue=True)` (SLURM hosts also
  take `partition=`, `time=`, `account=`), `launch_sweep`, `list_sweeps`,
  `get_sweep`, `cancel_sweep`, `extend_sweep`, `pull_artifact`, `connect_host`.

## Where things are

`hx show <run_id> --json` → `paths`: `run_dir`, `repo`, `cwd`, `config`,
`stdout`/`stderr`, `predictions`, `env`, `dataset:<name>` (host:path),
`artifact:<kind>:<i>` (host:path). Everything under `run_dir` is plain YAML/JSONL
you can read directly.
