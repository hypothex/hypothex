# Hypothex

Experiment tracker and control panel for AI researchers and their agents.

## Why

- See every experiment across every project: task, hypothesis, dataset (host, path, hash), metric (name + version), and where code, results, and checkpoints live.
- Rerun, re-run inference, or re-score saved predictions when a metric changes.
- Launch runs on your laptop, SSH boxes, or SLURM clusters.
- Built for agents too: `hx --json` CLI, MCP server, HTTP API, and a skill file.

## Install

```bash
uv tool install hypothex
```

## Quickstart

```bash
hx init                                              # write a starter hypothex.yaml
hx validate                                          # check it
hx run -t TASK -H "why this run exists" --seed 1 -- python train.py --seed {seed}
hx leaderboard TASK                                  # rank seed groups by the primary metric
hx show <run-id>                                     # every path: code, config, logs, predictions, checkpoint
hx reeval --task TASK                                # re-score after bumping a metric's version
```

See [`docs/quickstart.rst`](docs/quickstart.rst) for the full walkthrough, or
[`examples/toy-classifier`](examples/toy-classifier) for a runnable example.

## For agents

- Copy [`skills/hypothex/`](skills/hypothex/) into `~/.claude/skills/` (Claude Code), or reference it from `AGENTS.md` (Codex).
- MCP over stdio: `claude mcp add hypothex -- uv run --project /path/to/hypothex hx mcp`.

See [`docs/agents.rst`](docs/agents.rst) for the full set of options (CLI, skill, MCP over stdio/HTTP, HTTP API).

## Status

Phase 1a (core backend). UI in progress.

## License

Apache-2.0. See the [design spec](docs/superpowers/specs/2026-09-26-hypothex-design.md) for the full architecture.
