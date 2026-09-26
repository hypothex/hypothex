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

## Where things are

`hx show <run_id> --json` → `paths`: `run_dir`, `repo`, `cwd`, `config`,
`stdout`/`stderr`, `predictions`, `env`, `dataset:<name>` (host:path),
`artifact:<kind>:<i>` (host:path). Everything under `run_dir` is plain YAML/JSONL
you can read directly.
