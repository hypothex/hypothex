# Hypothex

Experiment tracker and control panel for AI researchers and their agents.

## Features

- **Every experiment, one place**: task, hypothesis, dataset (host, path, hash), metric (name + version), git commit + diff, environment, logs, predictions, scores, and where checkpoints live.
- **Honest comparisons**: leaderboards rank seed groups (mean ± std); `hx examples` shows what a run fixes and breaks.
- **Re-score, never overwrite**: bump a metric's version and `hx reeval`; old scores stay.
- **Remote hosts**: run on SSH GPU boxes and SLURM clusters from your laptop. Each host keeps its own env server, so runs survive a sleeping laptop or a dropped network.
- **GPU queue**: live GPU status per host and a FIFO first-fit queue (`--gpus N --queue`).
- **SLURM**: `sbatch` with partition, time, account, and extra options; `squeue`/`sacct` tracking; `scancel`; lost-job detection.
- **Sweeps**: a grid (or random search) x seeds in one command, with a params x metric table and the best cell.
- **Cost**: GPU hours at each host's price plus API spend, per run, seed group, sweep, host, and day.
- **Web UI**: Overview with a live Hosts panel, task dashboards, run pages, examples.
- **Built for agents**: `hx --json` CLI, MCP server, HTTP API, and a skill file.
- **Safe by default**: servers bind `127.0.0.1` and require a bearer token; `hx token` unlocks the UI; no secrets in run files.

## Install

Hypothex is not on PyPI yet (the `hypothex` name there is a placeholder with no `hx`).
Install from a checkout. You need [uv](https://docs.astral.sh/uv/) and [Bun](https://bun.sh/)
to build the web UI:

```bash
git clone https://github.com/hypothex/hypothex.git
cd hypothex
cd ui && bun install && bun run build && cd ..   # writes src/hypothex/ui_dist
uv tool install .                                # puts `hx` on your PATH
```

Do not install from a bare `git+https://...` URL: the UI build is not in git, so that
install has no web UI.

## Quickstart

```bash
hx init                                              # write a starter hypothex.yaml
hx validate                                          # check it
hx run -t TASK -H "why this run exists" --seed 1 -- python train.py --seed '{seed}'
hx leaderboard TASK                                  # rank seed groups by the primary metric
hx show <run-id>                                     # every path: code, config, logs, predictions, checkpoint
hx serve                                             # UI and API at http://127.0.0.1:7777/
```

In another terminal, run `hx token` with the same Hypothex home and paste its
output into the UI's Token field.

On a remote GPU box (keep `hx serve` running on your machine):

```bash
hx hosts add gpu-box --ssh gpu-box --usd-per-gpu-hour 2.10
hx hosts map PROJECT gpu-box /home/me/code/project
hx launch --host gpu-box --gpus 1 --queue -t TASK -H "why" -- python train.py --seed '{seed}'
hx sweep -t TASK -H "lr x beam" --grid lr=1e-4,3e-4 --grid beam=5,10 --seeds 3 \
    --host gpu-box --gpus 1 --queue -- python train.py --lr '{lr}' --beam '{beam}' --seed '{seed}'
```

Try it with no setup: `hx --home /tmp/hx-demo demo --with-hosts && hx --home /tmp/hx-demo serve`.

## Documentation

- [Getting started](docs/getting_started.rst) and a runnable example in [`examples/toy-classifier`](examples/toy-classifier)
- [CLI](docs/cli.rst), [project file](docs/project_file.rst), [views](docs/views.rst), [web UI](docs/ui.rst), [SDK](docs/sdk.rst)
- [Remote hosts](docs/remote.rst), [GPU queue](docs/gpus.rst), [SLURM](docs/slurm.rst), [sweeps](docs/sweeps.rst), [cost](docs/cost.rst)
- [Agent guide](docs/agents.rst), [MCP tools](docs/mcp.rst), [HTTP API](docs/http_api.rst)
- [Security model](docs/security.rst), [troubleshooting](docs/troubleshooting.rst), [architecture](docs/architecture.rst)

Build the docs locally: `uv run sphinx-build -b html docs docs/_build/html`.

## For agents

- Copy [`skills/hypothex/`](skills/hypothex/) into `~/.claude/skills/` (Claude Code), or reference it from `AGENTS.md` (Codex). The installed package carries the same file at `hypothex/skills/hypothex/SKILL.md`.
- MCP over stdio: `claude mcp add hypothex -- hx mcp`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache-2.0. See [LICENSE](LICENSE).
