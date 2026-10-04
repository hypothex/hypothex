# Contributing to Hypothex

Thanks for helping. This page tells you how to set up, check, and test a change.

## Set up

You need [uv](https://docs.astral.sh/uv/) for Python and [Bun](https://bun.sh/) for the UI.

```bash
git clone https://github.com/hypothex/hypothex.git
cd hypothex
uv sync --all-groups          # Python 3.11+ and the dev tools
cd ui && bun install && cd .. # the web UI
```

Run the CLI from the checkout with `uv run hx ...`. Use a throwaway home so you never touch your own data:

```bash
uv run hx --home /tmp/hx-dev demo --with-hosts
uv run hx --home /tmp/hx-dev serve
```

## Python

- Package management: **uv** only (`uv add`, `uv run`). `pyproject.toml` is the single source of truth.
- Lint and format: **ruff**.
- Types: **ty**. Every function and method has type annotations.
- Tests: **pytest**, in `tests/`, mirroring `src/hypothex/`. Every feature and bug fix comes with tests.
- Docstrings: **numpydoc** style, with an `Examples` section where it helps.

Run these checks before you push (CI runs them too):

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check src
uv run pytest -q
uv run sphinx-build -W -b html docs docs/_build/html
```

## UI

```bash
cd ui
bun test                          # unit and component tests
bun run build                     # typecheck, then build into src/hypothex/ui_dist/
bunx tsc -p e2e/tsconfig.json     # type-check the end-to-end tests
bunx playwright install chromium  # once
bunx playwright test              # smoke tests against a seeded demo home
```

After a backend route change, regenerate `ui/src/api/types.ts` (see [`ui/README.md`](ui/README.md)).

## Test isolation: fakes only

Tests never reach real machines. This is a hard rule.

- No test connects to a real SSH host, SLURM cluster, or GPU. Never read or write `~/.ssh` in a test.
- `tests/conftest.py` installs a fail-closed baseline for the whole session: `HYPOTHEX_HUB_URL` points at a dead address, `ssh`/`scp` are replaced by refusing stubs, and `nvidia-smi`, `sbatch`, `squeue`, `sacct`, `scancel`, `sinfo`, `scontrol`, `srun`, and `salloc` are blocked. `tests/test_isolation.py` checks this.
- Use the fakes in `tests/fakes/`: a fake `ssh`/`scp` (`HYPOTHEX_SSH`, `HYPOTHEX_SCP`), fake SLURM commands, fake GPUs (`HYPOTHEX_FAKE_GPUS`), and in-process env servers.
- Every test gets its own home (`HYPOTHEX_HOME` under `tmp_path`, the `home` fixture).
- Integration tests in `tests/docker/` use throwaway Docker containers (an `sshd` image and a small SLURM cluster). They are marked `docker` and left out of a plain `uv run pytest`. Run them with:

  ```bash
  uv run pytest -m docker -v                            # skips when Docker is not running
  HYPOTHEX_REQUIRE_DOCKER=1 uv run pytest -m docker -v  # fails instead, as CI does
  ```

## Docs

User docs are Sphinx with the Read the Docs theme, in `docs/`. Add or update a page with every user-facing change, with short usage examples. The build must pass with `-W` (warnings are errors). Every `hx` command and flag in the docs must exist (`uv run hx <command> --help`).

## Commits and pull requests

- Conventional commit messages: `feat(scope): ...`, `fix: ...`, `docs: ...`, `test: ...`, `ci: ...`.
- One logical change per commit.
- CI (`.github/workflows/ci.yml`) runs the Python checks on Linux and macOS (Python 3.11 and 3.13), the UI tests and Playwright smoke tests, and the Docker integration tests. Keep it green.
