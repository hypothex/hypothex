# Hypothex Phase 3 (Backend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make one hub serve a small lab: a hub settings file with secrets kept out of it, run ownership, the lab notebook, paper baselines, LaTeX/Markdown/CSV export with seed and test-set noise, Slack and email notices with a retrying outbox, a weekly digest, storage reports and a plan-then-apply cleanup, pairing-based auth with scopes on every route, WebSocket and MCP tool, an optional Postgres index with Alembic, Tailscale access and paired `route: url` hosts, `run.log_cost`, and the CLI, MCP, demo, and docs for all of it.

**Architecture:** Settings live in `<home>/config.yaml` (`hypothex.core.settings`); secrets are only names of environment variables (plus an optional 0600 `secrets.env`) and travel as `SecretStr`. Auth state lives in `<home>/auth/auth.db` (`hypothex.auth.store`), never in the index. With `server.auth: on`, an outer ASGI guard (`hypothex.api.auth.AuthGuard`) turns a cookie, a bearer token, or a WebSocket ticket into a `Principal`; every route declares its scope with `requires(...)`, and a unit test fails on any route, WebSocket, or MCP tool without one. With auth off every request runs as `LOCAL_OWNER`, so phase 1–2 behaviour is unchanged. The hub alone runs the notifier: a thread in the `hx serve` lifespan reads the event log after a cursor, writes one outbox file per notice and channel, and delivers with retries; the digest uses the same outbox. Storage cleanup always writes a plan file first; apply needs the exact byte total and re-checks every item where the file lives (hub or host env route). Postgres is a second dialect of the same SQLAlchemy models; SQLite keeps its disposable rebuild, Postgres gets Alembic. New HTTP route groups live in their own modules (`api/routes_auth.py`, `api/routes_team.py`, `api/routes_storage.py`) so `api/app.py` only wires them.

**Tech Stack:** Python ≥ 3.11, uv, pydantic 2 (`SecretStr`), PyYAML, FastAPI + uvicorn, httpx, SQLAlchemy 2 (SQLite, Postgres through `psycopg[binary]`), Alembic, `segno` (QR), `smtplib`, Typer, the official `mcp` SDK, pytest, `aiosmtpd` and `trustme` (dev: fake SMTP with TLS), Docker (marker `docker`, `postgres:16-alpine`), ruff, ty, Sphinx + sphinx-rtd-theme + numpydoc. The UI (Bun) is the frontend plan.

**Spec:** `docs/superpowers/specs/2026-09-26-hypothex-design.md`, sections **9** and **13** (phase 3), 3.4 (Postgres + Alembic), 5.3 (auth failures stop retrying until re-pair), 5.4 (`route: url` lab server), 7.2 (`hx export`, `hx storage`), 7.3 (phase 3 auth), 7.4 (`/mcp`), 12 (notifier in the daemon), 14 (decisions log).

**Contract:** `docs/superpowers/plans/2026-10-04-hypothex-phase3-contract.md`, sections 1–9 and 11. Every name, field, route, and file listed there is exact. This plan adds private helpers, a few public helpers (each task's Interfaces lists them), and optional keyword arguments (`AuthStore(session_days=)`, `leaderboard_table(directions=, value_formats=)`, `send_slack(transport=)`, `send_email(ssl_context=)`, `Notifier(ssl_context=)`, `send_digest(since=)`, `upsert(keep_max=)`, `hub_call(text=, discover_token=)`, `create_app(auth=, public_url=, notifier=)`, `control.rerun/reinfer(owner=)`, `launch_sweep(owner=)`); it never renames or reshapes a contract name. The Assembly notes at the end list every place where the contract was ambiguous or silent and how this plan reads it.

**Prerequisite:** `main` at `e27a3a2` (phases 1a, 1b, 2, plus `p2-backend-minors`, `p2-docs-ci` (`6ace21d`), `p2-property-tests`, and the phase 2 frontend so far). Every "replace X with Y" anchor below was re-checked against `e27a3a2`; the drift from the first base `738c711` that touches this plan: `cli/main.py::_write_private` is hardened (Task 2 moves that version into `core.settings`), `launch --gpus` is `LaunchGpusOpt` (no task edits `launch`'s signature), `mcp/server.py` `launch_sweep` sends `sweep_checkout(...)` in its remote body (Task 32 Step 4.6 adds `created_by`/`owner` next to it), `api/app.py`'s lifespan `finally` nests the joins in a second `try/finally` (Task 30 adds the notifier thread before the loop that *starts* the threads), `remote/hub.py` `_SAFE_NAME`/`_halt` changed (no task edits them), and `docs/index.rst`'s User guide toctree ends `remote, gpus, slurm, sweeps, cost` (Task 46). Review round 3: `main` is now `8df4760` (the phase 2 frontend merge, PR #12), and `git diff e27a3a2 8df4760 -- src docs/index.rst` is empty, so every anchor still holds. If `main` has moved on when this plan starts, re-run `git diff 8df4760 main -- src docs/index.rst` and re-check each anchor the diff touches. No frontend code is touched. **Frontend:** `docs/superpowers/plans/2026-10-04-hypothex-phase3-frontend.md` (contract section 10) starts after this plan is merged and uses `hx demo --with-team` for fixtures.

## Global Constraints

- **NEVER touch real services.** No step or test connects to a real Slack workspace, SMTP server, Tailscale tailnet, Postgres server outside Docker, SSH host, or SLURM cluster, and nothing reads or writes `~/.ssh`. Task 1 Step 1 (the first step of the plan) installs a session-wide network guard in `tests/conftest.py`: `socket.socket.connect`, `connect_ex`, `socket.getaddrinfo`, and `psycopg.connect` refuse every address that is not loopback (`NetworkBlockedError`), in `pytest_configure` (session) and again per test. The same hook removes `HYPOTHEX_SLACK_WEBHOOK`, `HYPOTHEX_SMTP_PASSWORD`, `HYPOTHEX_INDEX_PASSWORD`, and `HYPOTHEX_HUB_TOKEN`, and points `HYPOTHEX_TAILSCALE` at a stub that always fails. Tests use `tests/fakes/webhook.py` (`FakeWebhook`), `tests/fakes/smtp.py` (`FakeSmtp`, `aiosmtpd` + `trustme`), `tests/fakes/fake_tailscale.py` (installed with `install_fake_tailscale`), fake clocks (`now=` callables), in-process env servers (`route: url`, `tests/api/envserver.py`), and a throwaway `postgres:16-alpine` container (marker `docker`). Phase 2's `isolate_remote` stays as it is.
- Python `>=3.11`. Package manager **uv** only (`uv add`, `uv run`, `uv sync`); never pip.
- Lint and format with **ruff** (line length 100, rules `E F I B UP SIM`), types with **ty** (`uv run ty check src`), tests with **pytest** in `tests/` mirroring `src/`. Every task ends with its tests green and `ruff check`, `ruff format --check`, `ty check src` clean.
- Every public function has type annotations and a numpydoc docstring (summary, Parameters, Returns, Raises where any, Examples where they help).
- **Secrets** (Slack webhook URL, SMTP password, Postgres password, session tokens, pairing secrets, host tokens) never appear in `config.yaml`, run folders, `env/` captures, the event log, the index, API responses, CLI `--json` output, log lines, exception messages, notices, or the outbox. They are `SecretStr` from the moment they are read; `.get_secret_value()` is called only at the socket (`send_slack`, `send_email`, the Postgres URL, the `Authorization` header). Every error string that leaves `hypothex.notify` goes through `redact()`. Pydantic errors about settings are printed without input values (`errors(include_input=False)`), and exceptions that could carry a secret are raised `from None`.
- Auth is opt-in: with `server.auth: off` (the default) every request runs as `LOCAL_OWNER` (`admin`), `created_by` keeps phase 1–2 values (`human`, `agent:<name>`), `owner` stays `None`, and phase 1–2 tests pass unchanged. With auth on, the server sets `created_by` (`human:<user>`, `agent:<agent>@<user>`) and `owner` from the principal; body values are ignored except from the host principal (a hub forwarding).
- Scopes are ordered `read ⊂ launch ⊂ admin`. Every `APIRoute` and the WebSocket declare a scope with `requires(...)`; every MCP tool carries `@scoped(...)`. Storage, notification settings, users, and other users' sessions need `admin`. No MCP tool applies a cleanup, sends a notification, or manages users or sessions.
- Destructive actions: storage deletion is admin-only, plan-then-apply with `confirm_bytes == plan.total_bytes`, re-validated per item where the file lives, never follows a symlink, never touches a protected path, never rewrites `run.yaml`, and is never reachable through MCP.
- Every mutating HTTP call accepts a `command_id`; `once()` (phase 1) makes it idempotent. Every `hx` command supports `--json`.
- Copy is terse (spec section 8): numbers, glyphs, short labels; CLI text output is one line or a table, never paragraphs. Notice titles start with a status glyph (`✓ ✗ ? ⊘`).
- Commits: one conventional message per task, exactly as given in the task. No `Co-Authored-By` lines and no AI or Claude mentions in commits or PR text.

## Review Focus

Five failure modes the contract implies that are easy to miss, most likely first. Each has a test in the task that owns the code.

1. **A secret leaks through an error path.** A revoked webhook makes httpx raise an error whose text holds the full URL; an SMTP 535 echoes the user name; a bad `config.yaml` makes pydantic print the literal value. Every one must reach the outbox, the event log, the API, the CLI, and the logs as `error_class` only. Test: Task 47 `test_no_secret_reaches_any_file_event_log_or_output` (code: `redact`, `ChannelError`, `_settings_errors`).
2. **The hub crashes between the send and the record.** The outbox entry is left `sending`; it must be sent again after 60 s (at least once), never dropped, and never sent a third time once recorded; a crash after the record but before the outbox file is removed must not resend. Tests: Task 17 `test_entry_left_sending_by_a_crash_is_retried_once`, `test_an_entry_recorded_before_a_crash_is_not_sent_again`.
3. **A collaborator widens their own access.** A `launch` principal asks for an `admin` pairing, posts `created_by: "human:sv"` or `owner: "sv"`, stops the owner's run, or starts a run on the hub's own machine, whose command could read the owner's token in `server.json`. Every case is refused or overwritten. Tests: Task 6 `test_pairing_never_widens_scope`, Task 27 `test_body_identity_is_ignored_with_auth_on`, `test_only_owner_or_admin_may_stop`, `test_launch_scope_never_runs_code_on_the_hub`, Task 32 `test_session_principal_launches_as_agent_at_user`. A command id replayed by another caller or on another route runs as a new command (`command_key`): Task 23 `test_command_key_binds_the_caller_and_the_route`, Task 27 `test_a_command_id_is_bound_to_its_caller_and_route`.
4. **An artifact changes between plan and apply** (a training job rewrote `last.pt`, or someone unarchived the run). It must be skipped, not deleted, and the freed total must say so; so must a path that a run made during the apply reads, or that a run inside the policy's age uses. Tests: Task 22 `test_changed_or_unarchived_items_are_skipped_at_apply`, `test_apply_keeps_the_plan_age_for_runs_made_after_it`, `test_a_run_that_reads_an_input_waits_for_a_cleanup_in_progress`. A folder artifact that holds a kept run's file is refused and skipped: Task 21 `test_a_folder_artifact_holding_a_kept_file_is_refused`, Task 22 `test_apply_skips_a_folder_that_holds_a_kept_file`.
5. **A 200-run sweep finishes.** One notice for the sweep, not 200, counting its failures, and no notice at all while any member is still queued or running, also when the last run ends between two event batches. Tests: Task 16 `test_sweep_gives_one_notice_when_its_last_run_ends`, `test_a_sweep_that_ends_between_scan_batches_still_notifies`. Never `1/1` while launches are still issued, and never folded into another hub's sweep with the same id: Task 16 `test_a_sweep_still_launching_waits_for_its_last_run`, `test_a_foreign_sweep_with_the_same_id_is_not_folded`.

---

## File Structure

```
pyproject.toml                 alembic, segno; extra server = psycopg[binary]; dev aiosmtpd, trustme,
                               psycopg[binary] (Task 1)
src/hypothex/
  core/
    settings.py          NEW   Settings models, load/save config.yaml (2); secrets.env,
                               resolve_secret, secret_env_names, scrub_env (3)
    execution.py               owner on RunRequest (4); secret variables scrubbed from run env (3);
                               a run reading an input is created under cleanup_lock (22)
    records.py                 RunRecord.owner (4)
    sweeps.py                  SweepSpec.owner, launch_sweep(owner=) (4)
    control.py                 rerun/reinfer(owner=) (4)
    index.py                   SCHEMA_VERSION 4, RunRow.owner, list_runs(owner=) (4); dialects,
                               upsert, json_text, open_index, IndexUnavailableError,
                               IndexSchemaError, HEAD_REVISION, Index.pending, repair_pending (34)
    migrations/          NEW   Alembic env + 0001_phase3; alembic_config, upgrade, current (35)
    context.py                 Context.open reads config.yaml for index_url, repair_pending (34)
    notebook.py          NEW   lab notebook (8)
    config.py                  BaselineSpec, TaskSpec.baselines, checks (9)
    leaderboard.py             BaselineRow, Leaderboard.baselines, baseline_url (9);
                               metric_higher_is_better (12)
    export.py            NEW   ExportOptions, tables, render latex/markdown/csv (10-12)
    digest.py            NEW   weekly digest (18-19)
    storage.py           NEW   report, plan, apply, cleaned.json, cleanup_lock (20-22)
    queries.py                 RunDetail.cleaned; star/archive under cleanup_lock (22)
  auth/                  NEW
    __init__.py, scopes.py     Scope, covers, scopes_of (5)
    store.py                   models, errors, LOCAL_OWNER (5); AuthStore (6); tickets (7)
    ownership.py               may_act, require_act, require_local_exec (5)
    pairing.py                 pairing_url, parse_pairing_url, qr_text (7)
    client.py                  hub-tokens.json for the CLI (7)
  notify/                NEW
    __init__.py, messages.py   Notice, run/sweep/test notices, render_slack/email (14)
    channels.py                send_slack, send_email, redact, ChannelError (15)
    notifier.py                Notifier, outbox, scan (16); deliver, recent, loop (17); digests (19)
  remote/
    tailscale.py         NEW   tailscale status/serve/unserve (37)
    config.py                  HostSpec.token_env, HOST_TOKENS_FILE, host_token (38)
    hub.py                     route url sends host_token; re-pair message (38)
  api/
    auth.py              NEW   requires, principal_of, AuthGuard, route_scopes, identity (23)
    security.py                TokenGuard sets the host principal (23)
    app.py                     guard wiring (23); scopes on every route (24); WS tickets (26);
                               identity + ownership (27); route modules, notifier thread (29-31)
    routes_auth.py       NEW   /api/v1/auth/* (25)
    routes_team.py       NEW   notebook, export, digest, notify routes (29, 30)
    routes_storage.py    NEW   storage routes, hub and env (31)
  mcp/server.py                scoped, tool_scopes, acting_as, principal over /mcp (32); 9 tools (33)
  sdk.py                       Run.log_cost, NoopRun.log_cost (40)
  cli/main.py                  hx login/logout/whoami/pair/sessions/users (41); client mode, hosts
                               pair (42); export, note --project, notebook, digest (43); notify,
                               storage (44); db (35); serve --auth/--tailscale/--public-url (39);
                               demo --with-team (45)
  demo_team.py           NEW   seed_demo_team, demo_team_running, loopback receivers (45)
  demo.py                      live sweep runs only with a fake GPU host; a host with token_env
                               starts with that token (45)
skills/hypothex/SKILL.md       export, notebook, never apply cleanup (33)
docs/team.rst, notifications.rst, export.rst, storage.rst  NEW (46); docs/index.rst, docs/cli.rst
tests/
  conftest.py                  network guard, secret vars, tailscale stub (1)
  api/authkit.py         NEW   auth app and token helpers (23); api/envserver.py serve_app(port=) (48)
  remote/test_hub.py           re-pair message (38)
  fakes/network.py       NEW   guard (1); webhook.py, smtp.py NEW (13); fake_tailscale.py NEW (37)
  test_isolation.py            guard tests (1)
  core/test_settings.py (2, 3), test_records_phase3.py (4), test_notebook.py (8),
  test_baselines.py (9), test_export.py + golden/export/ (10-12), test_digest.py (18, 19),
  test_storage.py (20-22), test_index_dialects.py (34), test_migrations.py (35)
  auth/test_scopes.py (5), test_store.py (6), test_pairing.py (7)
  notify/test_fakes.py (13), test_messages.py (14), test_channels.py (15), test_notifier.py (16, 17, 19)
  api/test_auth_guard.py (23), test_route_scopes.py (24, 28), test_auth_routes.py (25),
  test_ws_auth.py (26), test_ownership_api.py (27), test_team_routes.py (29, 30),
  test_storage_routes.py (31)
  mcp/test_scoped_tools.py (32), test_team_tools.py (33)
  remote/test_tailscale.py (37), test_host_pairing.py (38)
  cli/test_serve_auth.py (39), test_auth_cli.py (41, 42), test_team_cli.py (43, 44), test_db_cli.py (35)
  test_sdk_cost.py (40), test_demo_team.py (45), test_docs_phase3.py (46),
  test_secret_leaks.py (47), test_acceptance_phase3.py (48)
  docker/test_postgres_index.py (36)
```

Dependency order: Part 1 → Part 2 → … → Part 13. Inside a part, tasks run in order. Parts 3 (notebook, baselines, export), 4–5 (notify, digest), and 6 (storage) only need Parts 1–2 and can run in parallel; Part 7 (API auth) needs Part 2; Part 8 needs Parts 3–7; Part 10 (Postgres) needs only Parts 1–2.

---

## Part 1: Isolation, settings, and secrets

Contract 1.1, 7 (secrets), 9 (network guard). The guard comes first so every later red step runs under it.

### Task 1: Network guard, secret variables, and new dependencies

**Files:**
- Modify: `pyproject.toml` (through `uv add`)
- Create: `tests/fakes/network.py`
- Modify: `tests/conftest.py`
- Modify: `tests/test_isolation.py`

**Interfaces:**
- Produces (tests only):
  - `tests.fakes.network.SECRET_VARS: tuple[str, ...]` = `("HYPOTHEX_SLACK_WEBHOOK", "HYPOTHEX_SMTP_PASSWORD", "HYPOTHEX_INDEX_PASSWORD", "HYPOTHEX_HUB_TOKEN")`.
  - `class NetworkBlockedError(OSError)`; `allowed_address(host: object) -> bool` (loopback or unspecified IPs, `localhost`, `None`, `""`); `guard_network(monkeypatch) -> None` (patches `socket.socket.connect`, `socket.socket.connect_ex`, `socket.getaddrinfo`, and, when installed, `psycopg.connect` and `psycopg.Connection.connect`); `refuse_tailscale(base: Path, monkeypatch) -> Path` (a stub that prints `blocked` and exits 255, set as `HYPOTHEX_TAILSCALE`).
- Dependencies: main `alembic`, `segno`; optional extra `server = ["psycopg[binary]>=3.2"]`; dev `aiosmtpd`, `trustme`, `psycopg[binary]`.

- [ ] **Step 1: Add the dependencies**

Run:
```bash
uv add "alembic>=1.13" "segno>=1.6"
uv add --optional server "psycopg[binary]>=3.2"
uv add --dev "aiosmtpd>=1.4" "trustme>=1.1" "psycopg[binary]>=3.2"
```
Expected: `pyproject.toml` gains `"alembic>=1.13"` and `"segno>=1.6"` under `dependencies`, a `[project.optional-dependencies]` table with `server = ["psycopg[binary]>=3.2"]`, and the three dev entries; `uv.lock` is updated; the last line of each command is `Installed ... packages` or `Audited ... packages`.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_isolation.py` (and add `import smtplib`, `import socket`, `import threading`, `import httpx`, and `from tests.fakes.network import SECRET_VARS, NetworkBlockedError` to its imports):

```python
@pytest.fixture(scope="module")
def module_connect() -> str:
    """What a module-scoped fixture sees when it opens a socket to the internet."""
    try:
        socket.create_connection(("192.0.2.10", 443), timeout=1)
    except NetworkBlockedError as exc:
        return str(exc)
    return "connected"


def test_module_fixtures_already_run_behind_the_network_guard(module_connect: str) -> None:
    assert "blocked" in module_connect


def test_httpx_cannot_reach_a_public_address() -> None:
    with pytest.raises(httpx.ConnectError, match="blocked"):
        httpx.get("http://203.0.113.7/", timeout=1)


def test_httpx_cannot_resolve_a_public_name() -> None:
    with pytest.raises(httpx.ConnectError, match="blocked"):
        httpx.post("https://hooks.slack.com/services/T0/B0/x", json={}, timeout=1)


def test_smtplib_cannot_reach_a_public_server() -> None:
    with pytest.raises(NetworkBlockedError):
        smtplib.SMTP("smtp.example.org", 587, timeout=1)


def test_raw_socket_connect_is_blocked() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(NetworkBlockedError):
            sock.connect(("198.51.100.1", 80))
        assert sock.connect_ex(("198.51.100.1", 80)) != 0
    finally:
        sock.close()


def test_psycopg_cannot_reach_a_public_server() -> None:
    psycopg = pytest.importorskip("psycopg")
    with pytest.raises(NetworkBlockedError):
        psycopg.connect("host=203.0.113.5 dbname=hx user=hx connect_timeout=1")
    with pytest.raises(NetworkBlockedError):
        psycopg.connect(host="db.example.org", dbname="hx", connect_timeout=1)


def test_loopback_still_works() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    accepted: list[socket.socket] = []
    thread = threading.Thread(target=lambda: accepted.append(server.accept()[0]))
    thread.start()
    try:
        with socket.create_connection(("localhost", port), timeout=5):
            thread.join(5)
        assert accepted
    finally:
        for conn in accepted:
            conn.close()
        server.close()


def test_secret_variables_are_unset() -> None:
    for name in SECRET_VARS:
        assert name not in os.environ, name


def test_tailscale_points_at_a_refusing_stub() -> None:
    stub = os.environ["HYPOTHEX_TAILSCALE"]
    done = subprocess.run([stub, "status", "--json"], capture_output=True, text=True)
    assert done.returncode == 255 and "blocked" in done.stderr
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_isolation.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'tests.fakes.network'`.

- [ ] **Step 4: Write the guard**

Create `tests/fakes/network.py`:

```python
"""
Session-wide network guard: tests reach loopback only (HARD RULE).

``tests/conftest.py`` installs it in ``pytest_configure`` (before any module or
session fixture) and again for every test. A connect, a name lookup, or a
``psycopg`` connection to anything but a loopback address raises
``NetworkBlockedError``, so no test can reach a real Slack workspace, SMTP
server, Postgres server, or tailnet by mistake. ``psycopg`` talks through
libpq (C), so its connect functions are wrapped separately.

Examples
--------
>>> allowed_address("127.0.0.1"), allowed_address("hooks.slack.com")
(True, False)
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

SECRET_VARS = (
    "HYPOTHEX_SLACK_WEBHOOK",
    "HYPOTHEX_SMTP_PASSWORD",
    "HYPOTHEX_INDEX_PASSWORD",
    "HYPOTHEX_HUB_TOKEN",
)
"""Secret variables no test may inherit from the developer's shell."""
LOCAL_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})
_REAL_CONNECT = socket.socket.connect
_REAL_CONNECT_EX = socket.socket.connect_ex
_REAL_GETADDRINFO = socket.getaddrinfo
_PSYCOPG: dict[str, Any] = {}
_TAILSCALE_STUB = "#!/bin/sh\necho 'hypothex tests: real tailscale is blocked' >&2\nexit 255\n"


class NetworkBlockedError(OSError):
    """A test tried to reach an address that is not loopback."""


def allowed_address(host: object) -> bool:
    """
    Tell whether a test may connect to (or look up) ``host``.

    Parameters
    ----------
    host : object
        A host name, an IP literal, ``None`` (a wildcard lookup), or bytes.

    Returns
    -------
    bool
        True for ``None``, ``""``, the loopback names, and loopback or
        unspecified IP addresses; False for every other name and address.

    Examples
    --------
    >>> [allowed_address(h) for h in ("::1", "0.0.0.0", None, "203.0.113.1", "db.lab")]
    [True, True, True, False, False]
    """
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if not isinstance(host, str):
        return False
    name = host.strip().strip("[]").split("%", 1)[0].lower()
    if name == "" or name in LOCAL_NAMES:
        return True
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return False
    return address.is_loopback or address.is_unspecified


def _blocked(host: object) -> NetworkBlockedError:
    return NetworkBlockedError(f"tests never reach the network: {host!r} is blocked")


def _connect(self: socket.socket, address: Any) -> None:
    if self.family in (socket.AF_INET, socket.AF_INET6) and not allowed_address(address[0]):
        raise _blocked(address[0])
    _REAL_CONNECT(self, address)


def _connect_ex(self: socket.socket, address: Any) -> int:
    if self.family in (socket.AF_INET, socket.AF_INET6) and not allowed_address(address[0]):
        return 111  # ECONNREFUSED: connect_ex reports errors as numbers
    return _REAL_CONNECT_EX(self, address)


def _getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
    if not allowed_address(host):
        raise _blocked(host)
    return _REAL_GETADDRINFO(host, *args, **kwargs)


def _psycopg_hosts(conninfo: str, kwargs: dict[str, Any]) -> list[str]:
    from psycopg.conninfo import conninfo_to_dict

    params = conninfo_to_dict(conninfo) if conninfo else {}
    hosts: list[str] = []
    for key in ("host", "hostaddr"):
        raw = kwargs.get(key, params.get(key))
        if raw:
            hosts += [h.strip() for h in str(raw).split(",") if h.strip()]
    return hosts


def _guard_psycopg(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        import psycopg
    except ImportError:
        return
    if not _PSYCOPG:
        _PSYCOPG["connect"] = psycopg.Connection.__dict__["connect"]
    real: Callable[..., Any] = _PSYCOPG["connect"].__func__

    def guarded(cls: type, conninfo: str = "", **kwargs: Any) -> Any:
        for host in _psycopg_hosts(conninfo, kwargs):
            if not host.startswith("/") and not allowed_address(host):  # "/..." is a socket dir
                raise _blocked(host)
        return real(cls, conninfo, **kwargs)

    monkeypatch.setattr(psycopg.Connection, "connect", classmethod(guarded))
    monkeypatch.setattr(
        psycopg, "connect", lambda conninfo="", **kw: psycopg.Connection.connect(conninfo, **kw)
    )


def guard_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Refuse every non-loopback connect, lookup, and Postgres connection.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        The patches are undone with it (a session ``MonkeyPatch`` is never undone).
    """
    monkeypatch.setattr(socket.socket, "connect", _connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", _getaddrinfo)
    _guard_psycopg(monkeypatch)


def refuse_tailscale(base: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """
    Point ``HYPOTHEX_TAILSCALE`` at a stub that always fails.

    Parameters
    ----------
    base : Path
        Directory for the stub (created if missing).
    monkeypatch : pytest.MonkeyPatch
        Used to set the variable.

    Returns
    -------
    Path
        The stub.
    """
    base.mkdir(parents=True, exist_ok=True)
    stub = base / "tailscale-refuse"
    if not stub.exists():
        stub.write_text(_TAILSCALE_STUB)
        stub.chmod(0o755)
    monkeypatch.setenv("HYPOTHEX_TAILSCALE", str(stub))
    return stub
```

- [ ] **Step 5: Install the guard for the session and every test**

In `tests/conftest.py`, add to the imports:

```python
from tests.fakes.network import SECRET_VARS, guard_network, refuse_tailscale
```

In `pytest_configure`, after `refuse_host_tools(base, session)`, add:

```python
    guard_network(session)
    for name in SECRET_VARS:
        session.delenv(name, raising=False)
    refuse_tailscale(base / "no-tailscale", session)
```

In `isolate_remote`, after `refuse_host_tools(_isolation_bin, monkeypatch)`, add:

```python
    guard_network(monkeypatch)
    for name in SECRET_VARS:
        monkeypatch.delenv(name, raising=False)
    refuse_tailscale(_isolation_bin / "no-tailscale", monkeypatch)
```

and extend its docstring's first paragraph with: "Sockets, name lookups, and ``psycopg`` reach loopback only, the secret variables (``SECRET_VARS``) are unset, and ``HYPOTHEX_TAILSCALE`` points at a refusing stub."

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_isolation.py -v`
Expected: `21 passed` (12 phase 2 tests + 9 new).

Run: `uv run pytest -q`
Expected: every test passes (the in-process servers of phases 1–2 bind and connect on `127.0.0.1` only).

Run: `uv run ruff check tests && uv run ruff format --check tests`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock tests/fakes/network.py tests/conftest.py tests/test_isolation.py
git commit -m "test: block non-loopback network access and secret variables in every test"
```

---

### Task 2: Hub settings file (`hypothex.core.settings`)

**Files:**
- Create: `src/hypothex/core/settings.py`
- Modify: `src/hypothex/cli/main.py` (`_write_private` becomes the shared `write_private`)
- Test: `tests/core/test_settings.py`

**Interfaces:**
- Consumes: `scan_yaml`, `has_cycle`, `YAML_CYCLE` (`hypothex.core.config`), `ConfigError`, `Layout`.
- Produces (contract 1.1, exact): `SETTINGS_FILENAME`, `ENV_NAME`, `NotifyEvent`, `Channel`, `Weekday`, `SlackSettings`, `EmailSettings`, `ProjectRule`, `NotifySettings`, `DigestSettings`, `ServerSettings`, `StorageSettings`, `Settings`, `settings_path(layout)`, `load_settings(layout)`, `save_settings(layout, settings)`.
- Produces (public helpers): `is_loopback_host(host: str) -> bool`; `redact_url(url: str) -> str` (password in a URL, as `user:pw@` or a `password`/`sslpassword` query parameter → `***`); `PASSWORD_PARAMS`; `url_holds_password(url: str) -> bool`; `LITERAL_SECRET_KEYS`; `write_private(path: Path, text: str) -> None` (atomic, 0600, parent 0700; main's hardened `cli/main.py::_write_private` moved here: a stale temp file is unlinked and the new one opened `O_EXCL`, the temp file is removed on any error, plus an `fsync`; the CLI then imports it, so there is one copy).
- Rules: a literal secret key under `notify.slack` or `notify.email` (`webhook`, `webhook_url`, `password`, `token`, `secret`, `url`) is refused before pydantic sees it, with the line and the hint `use webhook_env: NAME (the variable holding it)` (Slack) or `use password_env: NAME (...)` (email); the value is never echoed. `server.index_url` with a password (`user:pw@`, or a `password`/`sslpassword` query parameter in any case or percent-encoding, which libpq uses as the password) is refused with the URL redacted. `security: none` with a `username` is refused unless `host` is loopback. Validation errors list `path: message` only (no input values).

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_settings.py`:

```python
import os
import stat
from pathlib import Path

import pytest

from hypothex.core.errors import ConfigError
from hypothex.core.layout import Layout
from hypothex.core.settings import (
    EmailSettings,
    NotifySettings,
    ProjectRule,
    Settings,
    SlackSettings,
    load_settings,
    redact_url,
    save_settings,
    settings_path,
    write_private,
)

FULL = """\
server:
  auth: off
  public_url: null
  session_days: 90
  index_url: null
  index_password_env: HYPOTHEX_INDEX_PASSWORD
notify:
  slack: {webhook_env: HYPOTHEX_SLACK_WEBHOOK}
  email:
    host: smtp.lab.org
    port: 587
    security: starttls
    username: sv
    password_env: HYPOTHEX_SMTP_PASSWORD
    sender: hx@lab.org
    to: [sv@lab.org]
    timeout: 20
  projects:
    deepretro:
      events: [finished, failed, lost]
      channels: [slack, email]
      min_seconds: 300
      fold_sweeps: true
  default: null
  max_age_hours: 24
digest:
  enabled: true
  weekday: mon
  hour: 9
  timezone: Europe/London
  channels: [slack]
  projects: all
  save_to_notebook: true
  top_notes: 5
storage: {older_than_days: 30, kinds: [checkpoint], plan_ttl_minutes: 60}
"""
SECRET = "T0AAAA/B0BBBB/SECRETXYZ"


def write(home: Path, text: str) -> Layout:
    layout = Layout(home)
    home.mkdir(parents=True, exist_ok=True)
    settings_path(layout).write_text(text)
    return layout


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    settings = load_settings(Layout(tmp_path))
    assert settings == Settings()
    assert settings.server.auth == "off" and settings.notify.default is None
    assert settings.digest.enabled is False and settings.storage.kinds == ["checkpoint"]


def test_contract_example_loads(tmp_path: Path) -> None:
    settings = load_settings(write(tmp_path, FULL))
    rule = settings.notify.projects["deepretro"]
    assert rule.channels == ["slack", "email"] and rule.min_seconds == 300
    assert settings.notify.email is not None and settings.notify.email.to == ["sv@lab.org"]
    assert settings.digest.timezone == "Europe/London" and settings.digest.projects == "all"
    assert settings.server.index_password_env == "HYPOTHEX_INDEX_PASSWORD"


@pytest.mark.parametrize("key", ["webhook", "webhook_url", "url", "token", "secret"])
def test_literal_slack_secret_is_refused_without_echo(tmp_path: Path, key: str) -> None:
    text = f"notify:\n  slack:\n    {key}: https://hooks.slack.com/services/{SECRET}\n"
    with pytest.raises(ConfigError) as info:
        load_settings(write(tmp_path, text))
    message = str(info.value)
    assert f"notify.slack.{key}" in message and "line 3" in message
    assert "use webhook_env: NAME" in message
    assert "SECRETXYZ" not in message and "hooks.slack.com" not in message


@pytest.mark.parametrize("key", ["password", "token", "secret"])
def test_literal_smtp_secret_is_refused_without_echo(tmp_path: Path, key: str) -> None:
    text = (
        "notify:\n  email:\n    host: smtp.lab.org\n    sender: a@b.c\n    to: [a@b.c]\n"
        f"    {key}: hunter2-SECRETXYZ\n"
    )
    with pytest.raises(ConfigError) as info:
        load_settings(write(tmp_path, text))
    assert "use password_env: NAME" in str(info.value) and "line 6" in str(info.value)
    assert "SECRETXYZ" not in str(info.value)


def test_index_url_with_a_password_is_refused_redacted(tmp_path: Path) -> None:
    text = "server:\n  index_url: postgresql+psycopg://hx:pw-SECRETXYZ@db.lab:5432/hx\n"
    with pytest.raises(ConfigError) as info:
        load_settings(write(tmp_path, text))
    assert "postgresql+psycopg://hx:***@db.lab:5432/hx" in str(info.value)
    assert "SECRETXYZ" not in str(info.value)


def test_redact_url() -> None:
    assert redact_url("postgresql://u:p@h:5/d") == "postgresql://u:***@h:5/d"
    assert redact_url("postgresql://u@h/d") == "postgresql://u@h/d"
    assert redact_url("postgresql://u@h/d?Password=p&sslmode=require") == (
        "postgresql://u@h/d?Password=***&sslmode=require"
    )


def test_index_url_with_a_password_parameter_is_refused_redacted(tmp_path: Path) -> None:
    # libpq (and so SQLAlchemy) takes ?password= as the connection password
    for key in ("password", "PASSWORD", "sslpassword", "pass%77ord"):
        text = f"server:\n  index_url: postgresql+psycopg://hx@db.lab/hx?{key}=pw-SECRETXYZ\n"
        with pytest.raises(ConfigError) as info:
            load_settings(write(tmp_path, text))
        assert "holds a password" in str(info.value) and "SECRETXYZ" not in str(info.value)


def test_env_names_are_checked(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="notify.slack.webhook_env"):
        load_settings(write(tmp_path, "notify:\n  slack: {webhook_env: lower-case}\n"))


def test_clear_text_smtp_login_is_refused_off_loopback() -> None:
    with pytest.raises(ValueError, match="clear text"):
        EmailSettings(
            host="smtp.lab.org", security="none", username="sv", sender="a@b.c", to=["a@b.c"]
        )
    local = EmailSettings(
        host="127.0.0.1", security="none", username="sv", sender="a@b.c", to=["a@b.c"]
    )
    assert local.security == "none"


def test_unknown_timezone_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="digest.timezone"):
        load_settings(write(tmp_path, "digest: {timezone: Mars/Olympus}\n"))


def test_unknown_key_is_named(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="notifications"):
        load_settings(write(tmp_path, "notifications: {}\n"))


def test_validation_errors_never_echo_values(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as info:
        load_settings(write(tmp_path, "server:\n  session_days: SECRETXYZ\n"))
    assert "server.session_days" in str(info.value) and "SECRETXYZ" not in str(info.value)


def test_too_deep_yaml_names_the_line(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="line 1"):
        load_settings(write(tmp_path, "a: " + "[" * 70 + "]" * 70 + "\n"))


def test_save_round_trips_with_mode_0600(tmp_path: Path) -> None:
    layout = Layout(tmp_path / "home")
    settings = Settings(
        notify=NotifySettings(
            slack=SlackSettings(), projects={"toy": ProjectRule(channels=["slack"])}
        )
    )
    save_settings(layout, settings)
    path = settings_path(layout)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert load_settings(layout) == settings
    assert "storage" not in path.read_text()  # defaults are left out
    assert os.access(path, os.R_OK)


def test_write_private_ignores_a_stale_temp_file(tmp_path: Path) -> None:
    path = tmp_path / "home" / "server.json"
    path.parent.mkdir()
    stale = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    stale.write_text("old")
    stale.chmod(0o644)  # os.replace would carry this mode onto the token file
    write_private(path, "{}")
    assert path.read_text() == "{}" and stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not stale.exists()
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_settings.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'hypothex.core.settings'`.

- [ ] **Step 3: Write the implementation**

Create `src/hypothex/core/settings.py`:

```python
"""The hub's ``<home>/config.yaml``: server, notification, digest, and storage settings.

Secrets never live in this file: it names the environment variables that hold
them (``webhook_env``, ``password_env``, ``index_password_env``). A literal
secret is refused before validation, and validation errors are printed without
input values, so a mistake never echoes a secret.
"""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from hypothex.core.config import YAML_CYCLE, has_cycle, scan_yaml
from hypothex.core.errors import ConfigError
from hypothex.core.layout import Layout

SETTINGS_FILENAME = "config.yaml"
ENV_NAME = r"^[A-Z_][A-Z0-9_]{0,63}$"
NotifyEvent = Literal["finished", "failed", "lost", "killed"]
Channel = Literal["slack", "email"]
Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
LITERAL_SECRET_KEYS = ("webhook", "webhook_url", "password", "token", "secret", "url")
"""Keys under ``notify.slack``/``notify.email`` that would hold a secret value."""
_SECRET_FIELD = {"slack": "webhook_env", "email": "password_env"}


def is_loopback_host(host: str) -> bool:
    """
    Tell whether a host name or address stays on this machine.

    Parameters
    ----------
    host : str
        A name or an IP literal.

    Returns
    -------
    bool
        True for ``localhost`` and loopback addresses.

    Examples
    --------
    >>> is_loopback_host("127.0.0.1"), is_loopback_host("smtp.lab.org")
    (True, False)
    """
    name = host.strip().strip("[]").lower()
    if name == "localhost":
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


PASSWORD_PARAMS = frozenset({"password", "sslpassword"})
"""Query parameters libpq reads as a secret (compared lowercased and percent-decoded)."""


def _param_key(piece: str) -> str:
    return unquote(piece.split("=", 1)[0]).lower()


def url_holds_password(url: str) -> bool:
    """
    Tell whether a URL carries a password, as ``user:pw@`` or a query parameter.

    Parameters
    ----------
    url : str
        Any URL.

    Returns
    -------
    bool
        True for ``user:pw@`` or a ``password``/``sslpassword`` parameter (any
        case, percent-encoded or not); True for a URL that cannot be parsed.

    Examples
    --------
    >>> url_holds_password("postgresql://hx@db/hx?password=x")
    True
    >>> url_holds_password("postgresql://hx@db/hx?sslmode=require")
    False
    """
    try:
        parts = urlsplit(url)
        if parts.password is not None:
            return True
    except ValueError:
        return True  # never echoed, never trusted
    return any(_param_key(p) in PASSWORD_PARAMS for p in parts.query.split("&") if p)


def redact_url(url: str) -> str:
    """
    Replace the password of a URL with ``***``.

    Parameters
    ----------
    url : str
        Any URL.

    Returns
    -------
    str
        The URL with ``user:***@`` and ``<password param>=***`` where it held
        a password, else unchanged; ``***`` when it cannot be parsed.

    Examples
    --------
    >>> redact_url("postgresql+psycopg://hx:pw@db:5432/hx")
    'postgresql+psycopg://hx:***@db:5432/hx'
    >>> redact_url("postgresql://hx@db/hx?password=pw&sslmode=require")
    'postgresql://hx@db/hx?password=***&sslmode=require'
    """
    try:
        parts = urlsplit(url)
        password = parts.password
    except ValueError:
        return "***"
    pieces = parts.query.split("&") if parts.query else []
    hidden = [
        f"{p.split('=', 1)[0]}=***" if _param_key(p) in PASSWORD_PARAMS else p for p in pieces
    ]
    if password is None and hidden == pieces:
        return url
    netloc = parts.netloc
    if password is not None:
        netloc = f"{parts.username}:***@{netloc.rsplit('@', 1)[1]}"
    return urlunsplit(parts._replace(netloc=netloc, query="&".join(hidden)))


class SlackSettings(BaseModel, extra="forbid"):
    """Slack incoming webhook: the variable that holds its URL."""

    webhook_env: str = Field("HYPOTHEX_SLACK_WEBHOOK", pattern=ENV_NAME)


class EmailSettings(BaseModel, extra="forbid"):
    """SMTP delivery; the password comes from ``password_env``."""

    host: str = Field(min_length=1)
    port: int = Field(587, ge=1, le=65535)
    security: Literal["starttls", "ssl", "none"] = "starttls"
    username: str | None = None
    password_env: str | None = Field("HYPOTHEX_SMTP_PASSWORD", pattern=ENV_NAME)
    sender: str = Field(min_length=3)
    to: list[str] = Field(min_length=1)
    timeout: float = Field(20, gt=0, le=120)

    @model_validator(mode="after")
    def _no_clear_text_login(self) -> EmailSettings:
        """Refuse a login over plain SMTP to another machine."""
        if self.security == "none" and self.username and not is_loopback_host(self.host):
            raise ValueError(
                "security none with a username sends the password in clear text; "
                "use starttls or ssl"
            )
        return self


class ProjectRule(BaseModel, extra="forbid"):
    """Which run endings of one project notify, and where."""

    events: list[NotifyEvent] = Field(default_factory=lambda: ["finished", "failed", "lost"])
    channels: list[Channel] = Field(default_factory=lambda: ["slack"], min_length=1)
    min_seconds: float = Field(0, ge=0)
    fold_sweeps: bool = True


class NotifySettings(BaseModel, extra="forbid"):
    """Channels and per-project rules; unlisted projects get nothing unless ``default``."""

    slack: SlackSettings | None = None
    email: EmailSettings | None = None
    projects: dict[str, ProjectRule] = Field(default_factory=dict)
    default: ProjectRule | None = None
    max_age_hours: float = Field(24, gt=0)


class DigestSettings(BaseModel, extra="forbid"):
    """When and where the weekly digest goes."""

    enabled: bool = False
    weekday: Weekday = "mon"
    hour: int = Field(9, ge=0, le=23)
    timezone: str | None = None
    channels: list[Channel] = Field(default_factory=lambda: ["slack"])
    projects: list[str] | Literal["all"] = "all"
    save_to_notebook: bool = True
    top_notes: int = Field(5, ge=0, le=20)

    @field_validator("timezone")
    @classmethod
    def _known_zone(cls, value: str | None) -> str | None:
        """Accept only IANA zone names this machine knows."""
        if value is None:
            return None
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"unknown timezone {value!r} (use an IANA name)") from None
        return value


class ServerSettings(BaseModel, extra="forbid"):
    """Auth, public URL, sessions, and where the index lives."""

    auth: Literal["off", "on"] = "off"
    public_url: str | None = Field(None, pattern=r"^https?://[^/\s]+$")
    session_days: int = Field(90, ge=1, le=365)
    index_url: str | None = None
    index_password_env: str = Field("HYPOTHEX_INDEX_PASSWORD", pattern=ENV_NAME)

    @field_validator("auth", mode="before")
    @classmethod
    def _yaml_bool(cls, value: object) -> object:
        """YAML reads a bare ``off``/``on`` as a boolean."""
        if value is False:
            return "off"
        if value is True:
            return "on"
        return value

    @field_validator("index_url")
    @classmethod
    def _postgres_without_password(cls, value: str | None) -> str | None:
        """Only Postgres URLs, and never with a password in them."""
        if value is None:
            return None
        if not value.startswith(("postgresql://", "postgresql+psycopg://")):
            raise ValueError("index_url must start with postgresql+psycopg://")
        if url_holds_password(value):
            raise ValueError("index_url must not hold a password; set index_password_env")
        return value


class StorageSettings(BaseModel, extra="forbid"):
    """Defaults of ``hx storage clean``."""

    older_than_days: int = Field(30, ge=0)
    kinds: list[str] = Field(default_factory=lambda: ["checkpoint"])
    plan_ttl_minutes: int = Field(60, ge=1, le=1440)


class Settings(BaseModel, extra="forbid"):
    """The whole ``config.yaml``."""

    server: ServerSettings = Field(default_factory=ServerSettings)
    notify: NotifySettings = Field(default_factory=NotifySettings)
    digest: DigestSettings = Field(default_factory=DigestSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)


def settings_path(layout: Layout) -> Path:
    """
    Return the path of the settings file.

    Parameters
    ----------
    layout : Layout
        Home layout.

    Returns
    -------
    Path
        ``<home>/config.yaml``.
    """
    return layout.home / SETTINGS_FILENAME


def _key_line(text: str, keys: tuple[str, ...]) -> int | None:
    """The 1-based line of a nested mapping key, found on the composed YAML nodes."""
    try:
        node: Any = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError:
        return None
    line = None
    for key in keys:
        if not isinstance(node, yaml.MappingNode):
            return None
        match = next((pair for pair in node.value if pair[0].value == key), None)
        if match is None:
            return None
        line = match[0].start_mark.line + 1
        node = match[1]
    return line


def _refuse_literal_secrets(path: Path, text: str, data: dict[str, Any]) -> None:
    notify = data.get("notify")
    if not isinstance(notify, dict):
        return
    for section, field in _SECRET_FIELD.items():
        block = notify.get(section)
        if not isinstance(block, dict):
            continue
        for key in block:
            if key in LITERAL_SECRET_KEYS:
                line = _key_line(text, ("notify", section, key))
                where = "" if line is None else f" (line {line})"
                raise ConfigError(
                    f"{path}: notify.{section}.{key} holds a secret{where}; "
                    f"use {field}: NAME (the variable holding it)"
                )


def _refuse_index_password(path: Path, data: dict[str, Any]) -> None:
    server = data.get("server")
    url = server.get("index_url") if isinstance(server, dict) else None
    if isinstance(url, str) and url_holds_password(url):
        raise ConfigError(
            f"{path}: server.index_url {redact_url(url)} holds a password; "
            "remove it and set index_password_env"
        )


def _settings_errors(exc: ValidationError) -> str:
    """``path: message`` for each error, never the input value."""
    parts = []
    for error in exc.errors(include_input=False, include_url=False):
        where = ".".join(str(p) for p in error["loc"])
        parts.append(f"{where}: {error['msg']}")
    return "; ".join(parts)


def load_settings(layout: Layout) -> Settings:
    """
    Load and validate ``<home>/config.yaml``.

    A missing file gives the defaults (auth off, no notices, no digest). The
    text is pre-scanned like ``hypothex.yaml`` (depth, size, alias cycles).

    Parameters
    ----------
    layout : Layout
        Home layout.

    Returns
    -------
    Settings
        The settings.

    Raises
    ------
    ConfigError
        Invalid YAML, a literal secret (with its line and the ``*_env`` hint), a
        password in ``index_url``, or a value that does not match the schema.
        No message holds a value from the file.
    """
    path = settings_path(layout)
    if not path.is_file():
        return Settings()
    text = path.read_text(encoding="utf-8")
    try:
        scan = scan_yaml(text)
        data = None if scan.problem is not None else yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = "" if mark is None else f" (line {mark.line + 1})"
        problem = getattr(exc, "problem", None) or "invalid YAML"
        raise ConfigError(f"{path}: {problem}{where}") from None
    if scan.problem is not None:
        message, line = scan.problem
        raise ConfigError(f"{path}: {message} (line {line})")
    if has_cycle(data):
        raise ConfigError(f"{path}: {YAML_CYCLE}")
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a mapping at the top level")
    _refuse_literal_secrets(path, text, data)
    _refuse_index_password(path, data)
    try:
        return Settings.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"{path}: {_settings_errors(exc)}") from None


def write_private(path: Path, text: str) -> None:
    """
    Atomically write ``path`` as mode 0600 inside a 0700 folder.

    The parent folder is set to 0700 on every call: the first ``config.yaml``
    write makes the Hypothex home 0700 (``docs/team.rst`` says so).

    Parameters
    ----------
    path : Path
        Destination file.
    text : str
        Full content (UTF-8).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.unlink(missing_ok=True)  # a stale tmp keeps its old mode, which os.replace carries
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def save_settings(layout: Layout, settings: Settings) -> None:
    """
    Atomically write ``config.yaml`` (mode 0600), leaving defaults out.

    Parameters
    ----------
    layout : Layout
        Home layout.
    settings : Settings
        Settings to write.
    """
    data = settings.model_dump(mode="json", exclude_defaults=True)
    write_private(settings_path(layout), yaml.safe_dump(data, sort_keys=False))
```

Note: `write_private` chmods the parent to 0700; the parent of `config.yaml` is the Hypothex home, which phase 1 already creates for the user alone. Task 46 documents it in `docs/team.rst` (a lab-server home other users must read is not supported).

In `src/hypothex/cli/main.py`, delete the whole `def _write_private(path: Path, text: str) -> None:` function (main's hardened copy, the one with `tmp.unlink(missing_ok=True)` and `os.O_EXCL`) and add to the imports:

```python
from hypothex.core.settings import write_private as _write_private
```

Every existing `_write_private(...)` call in the CLI keeps working and now shares the one implementation. Check that no copy is left:

Run: `grep -c "def _write_private" src/hypothex/cli/main.py`
Expected: `0`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_settings.py tests/cli -v`
Expected: `tests/core/test_settings.py` `21 passed`; `tests/cli` still passes.

Run: `uv run python -m doctest src/hypothex/core/settings.py && uv run ruff check src/hypothex/core/settings.py src/hypothex/cli/main.py tests/core/test_settings.py && uv run ruff format --check src/hypothex/core/settings.py src/hypothex/cli/main.py tests/core/test_settings.py && uv run ty check src`
Expected: no doctest output, `All checks passed!`, `3 files already formatted`, `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/settings.py src/hypothex/cli/main.py tests/core/test_settings.py
git commit -m "feat(settings): hub config.yaml with secrets named by variable, never by value"
```

---

### Task 3: `secrets.env`, `resolve_secret`, and secret-free run environments

**Files:**
- Modify: `src/hypothex/core/settings.py`
- Modify: `src/hypothex/core/execution.py` (`_execute` builds the child environment through `scrub_env`)
- Test: `tests/core/test_settings.py` (append), `tests/core/test_execution.py` (append)

**Interfaces:**
- Produces (contract 1.1, exact): `SECRETS_FILENAME = "secrets.env"`, `resolve_secret(layout, name) -> SecretStr | None`, `class SecretsFileError(ConfigError)`.
- Produces (public helpers): `secrets_path(layout) -> Path`; `check_secrets_file(layout) -> None` (raises `SecretsFileError` when the file exists with group/other bits or another owner; `hx serve` calls it at start, Task 39); `DEFAULT_SECRET_VARS: tuple[str, ...]`; `secret_env_names(settings: Settings) -> set[str]`; `scrub_env(env: Mapping[str, str], names: Iterable[str]) -> dict[str, str]`.
- `_execute` (phase 1) removes `secret_env_names(load_settings(...))` from the environment it passes to the run's command (a bad `config.yaml` falls back to the default names). The defaults include the bearer secrets `HYPOTHEX_SERVE_TOKEN` and `HYPOTHEX_HUB_TOKEN`; Task 38 adds every configured host's `token_env`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/core/test_settings.py` (and add `from pydantic import SecretStr` and `from hypothex.core.envcapture import ENV_ALLOWLIST` plus `SecretsFileError, check_secrets_file, resolve_secret, scrub_env, secret_env_names, secrets_path` from `hypothex.core.settings` to the imports):

```python
def secrets_file(home: Path, text: str, mode: int = 0o600) -> Layout:
    layout = Layout(home)
    home.mkdir(parents=True, exist_ok=True)
    path = secrets_path(layout)
    path.write_text(text)
    path.chmod(mode)
    return layout


def test_environment_wins_over_the_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    layout = secrets_file(tmp_path, "LAB_HOOK=https://from-file\n")
    monkeypatch.setenv("LAB_HOOK", "https://from-env")
    value = resolve_secret(layout, "LAB_HOOK")
    assert isinstance(value, SecretStr) and value.get_secret_value() == "https://from-env"
    assert "from-env" not in repr(value)


def test_file_is_the_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LAB_HOOK", raising=False)
    layout = secrets_file(
        tmp_path, "# lab secrets\nexport LAB_HOOK='https://from-file'\n\nEMPTY=\n"
    )
    hook = resolve_secret(layout, "LAB_HOOK")
    assert hook is not None and hook.get_secret_value() == "https://from-file"
    assert resolve_secret(layout, "EMPTY") is None
    assert resolve_secret(layout, "MISSING") is None


def test_empty_environment_value_counts_as_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LAB_HOOK", "")
    assert resolve_secret(Layout(tmp_path), "LAB_HOOK") is None


@pytest.mark.parametrize("mode", [0o640, 0o604, 0o644])
def test_readable_secrets_file_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: int
) -> None:
    monkeypatch.delenv("LAB_HOOK", raising=False)
    layout = secrets_file(tmp_path, "LAB_HOOK=SECRETXYZ\n", mode)
    with pytest.raises(SecretsFileError, match="chmod 600") as info:
        resolve_secret(layout, "LAB_HOOK")
    assert "SECRETXYZ" not in str(info.value)
    with pytest.raises(SecretsFileError):
        check_secrets_file(layout)


def test_malformed_line_names_the_line_not_the_value(tmp_path: Path) -> None:
    layout = secrets_file(tmp_path, "GOOD=1\nnot a pair SECRETXYZ\n")
    with pytest.raises(SecretsFileError, match="line 2") as info:
        check_secrets_file(layout)
    assert "SECRETXYZ" not in str(info.value)


def test_no_secrets_file_is_fine(tmp_path: Path) -> None:
    check_secrets_file(Layout(tmp_path))


def test_secret_env_names_cover_configured_and_default_names() -> None:
    settings = Settings(
        notify=NotifySettings(
            slack=SlackSettings(webhook_env="LAB_HOOK"),
            email=EmailSettings(
                host="127.0.0.1", sender="a@b.c", to=["a@b.c"], password_env="LAB_SMTP"
            ),
        )
    )
    names = secret_env_names(settings)
    assert {
        "LAB_HOOK", "LAB_SMTP", "HYPOTHEX_INDEX_PASSWORD", "HYPOTHEX_SLACK_WEBHOOK",
        "HYPOTHEX_SERVE_TOKEN", "HYPOTHEX_HUB_TOKEN",
    } <= names  # fmt: skip
    assert scrub_env({"LAB_HOOK": "x", "PATH": "/bin"}, names) == {"PATH": "/bin"}


def test_env_allowlist_never_holds_a_secret_name() -> None:
    for name in ENV_ALLOWLIST:
        assert not name.endswith(("_WEBHOOK", "_PASSWORD", "_TOKEN", "_SECRET")), name
```

Append to `tests/core/test_execution.py` (it already imports `sys`, `Path`, `pytest`, `Context`, `RunRequest`, `prepare_run`, `execute_run`; add `from hypothex.core.layout import Layout` and `from hypothex.core.settings import NotifySettings, Settings, SlackSettings, save_settings`):

```python
def test_run_environment_never_holds_secret_variables(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_settings(
        Layout(ctx.layout.home),
        Settings(notify=NotifySettings(slack=SlackSettings(webhook_env="LAB_HOOK"))),
    )
    monkeypatch.setenv("LAB_HOOK", "https://hooks.example/SECRETXYZ")
    monkeypatch.setenv("HYPOTHEX_SMTP_PASSWORD", "hunter2")
    monkeypatch.setenv("HYPOTHEX_HUB_TOKEN", "hxs_s_000000000000_bearer")
    monkeypatch.setenv("KEEP_ME", "visible")
    code = (
        "import os; print(os.environ.get('LAB_HOOK', '-'), "
        "os.environ.get('HYPOTHEX_SMTP_PASSWORD', '-'), "
        "os.environ.get('HYPOTHEX_HUB_TOKEN', '-'), os.environ.get('KEEP_ME', '-'))"
    )
    record = prepare_run(ctx, RunRequest(repo=toy_repo, command=[sys.executable, "-c", code]))
    execute_run(ctx, record.run_id)
    stdout = (ctx.run_dir(record) / "logs" / "stdout.log").read_text()
    assert stdout.strip() == "- - - visible"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_settings.py tests/core/test_execution.py::test_run_environment_never_holds_secret_variables -v`
Expected: FAIL at collection with `ImportError: cannot import name 'SecretsFileError' from 'hypothex.core.settings'`.

- [ ] **Step 3: Write the implementation**

In `src/hypothex/core/settings.py`, add `import re` and `from collections.abc import Iterable, Mapping` to the imports, change the pydantic import to `from pydantic import BaseModel, Field, SecretStr, ValidationError, field_validator, model_validator`, and append:

```python
SECRETS_FILENAME = "secrets.env"
DEFAULT_SECRET_VARS = (
    "HYPOTHEX_SLACK_WEBHOOK",
    "HYPOTHEX_SMTP_PASSWORD",
    "HYPOTHEX_INDEX_PASSWORD",
    "HYPOTHEX_SERVE_TOKEN",
    "HYPOTHEX_HUB_TOKEN",
)
"""Variable names that always count as secrets, whatever ``config.yaml`` says."""


class SecretsFileError(ConfigError):
    """``secrets.env`` is readable by others, not the user's, or malformed."""


def secrets_path(layout: Layout) -> Path:
    """
    Return the path of the optional secrets file.

    Parameters
    ----------
    layout : Layout
        Home layout.

    Returns
    -------
    Path
        ``<home>/secrets.env``.
    """
    return layout.home / SECRETS_FILENAME


def _read_secrets(layout: Layout) -> dict[str, str]:
    """Parse ``secrets.env`` after checking its owner and mode; ``{}`` when absent."""
    path = secrets_path(layout)
    try:
        info = path.stat()
    except FileNotFoundError:
        return {}
    if info.st_mode & 0o077 or info.st_uid != os.getuid():
        raise SecretsFileError(f"{path} is readable by others or not yours; run: chmod 600 {path}")
    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ").strip()
        name, sep, value = line.partition("=")
        name = name.strip()
        if not sep or not re.fullmatch(ENV_NAME, name):
            raise SecretsFileError(f"{path}: line {number}: expected NAME=value")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[name] = value
    return values


def check_secrets_file(layout: Layout) -> None:
    """
    Refuse a ``secrets.env`` that others can read or that is malformed.

    Parameters
    ----------
    layout : Layout
        Home layout.

    Raises
    ------
    SecretsFileError
        The file has group/other permission bits, another owner, or a bad line
        (the message names the line, never a value). No file is fine.
    """
    _read_secrets(layout)


def resolve_secret(layout: Layout, name: str) -> SecretStr | None:
    """
    Read a secret by variable name: the environment first, then ``secrets.env``.

    Parameters
    ----------
    layout : Layout
        Home layout (for ``secrets.env``).
    name : str
        Variable name, e.g. ``HYPOTHEX_SLACK_WEBHOOK``.

    Returns
    -------
    SecretStr or None
        The value, wrapped; None when unset or empty in both places.

    Raises
    ------
    SecretsFileError
        ``secrets.env`` is consulted and is unsafe or malformed.
    """
    value = os.environ.get(name)
    if not value:
        value = _read_secrets(layout).get(name)
    return SecretStr(value) if value else None


def secret_env_names(settings: Settings) -> set[str]:
    """
    Return every variable name that holds a secret for these settings.

    Parameters
    ----------
    settings : Settings
        The hub's settings.

    Returns
    -------
    set of str
        ``DEFAULT_SECRET_VARS`` plus the configured ``webhook_env``,
        ``password_env``, and ``index_password_env``.
    """
    names = set(DEFAULT_SECRET_VARS)
    names.add(settings.server.index_password_env)
    if settings.notify.slack is not None:
        names.add(settings.notify.slack.webhook_env)
    if settings.notify.email is not None and settings.notify.email.password_env:
        names.add(settings.notify.email.password_env)
    return names


def scrub_env(env: Mapping[str, str], names: Iterable[str]) -> dict[str, str]:
    """
    Copy an environment without the given variables.

    Parameters
    ----------
    env : mapping of str to str
        An environment, e.g. ``os.environ``.
    names : iterable of str
        Variables to drop.

    Returns
    -------
    dict of str to str
        The copy.

    Examples
    --------
    >>> scrub_env({"A": "1", "B": "2"}, ["B"])
    {'A': '1'}
    """
    drop = set(names)
    return {k: v for k, v in env.items() if k not in drop}
```

In `src/hypothex/core/execution.py`, add to the imports:

```python
from hypothex.core.errors import ConfigError
from hypothex.core.settings import Settings, load_settings, scrub_env, secret_env_names
```

(merge `ConfigError` into the existing `hypothex.core.errors` import), add this helper above `_execute`:

```python
def _secret_names(ctx: Context) -> set[str]:
    """Secret variable names to keep out of a run (defaults when config.yaml is bad)."""
    try:
        settings = load_settings(ctx.layout)
    except ConfigError:
        settings = Settings()
    return secret_env_names(settings)
```

and in `_execute` replace

```python
    env = {
        **os.environ,
        "HYPOTHEX_RUN_DIR": str(run_dir),
```

with

```python
    env = {
        **scrub_env(os.environ, _secret_names(ctx)),
        "HYPOTHEX_RUN_DIR": str(run_dir),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_settings.py tests/core/test_execution.py -v`
Expected: `tests/core/test_settings.py` `30 passed`; every test in `tests/core/test_execution.py` passes, including `test_run_environment_never_holds_secret_variables`.

Run: `uv run python -m doctest src/hypothex/core/settings.py && uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check src`
Expected: no doctest output, `All checks passed!`, all files formatted, `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/settings.py src/hypothex/core/execution.py tests/core/test_settings.py tests/core/test_execution.py
git commit -m "feat(settings): resolve secrets from env or a 0600 secrets.env and keep them out of runs"
```

---

## Part 2: Ownership and the auth core

Contract 1.2, 1.3, 1.10 (store, scopes, pairing). Nothing here touches HTTP; Part 7 wires it in.

### Task 4: `owner` on runs, sweeps, and launch requests; index schema 4

**Files:**
- Modify: `src/hypothex/core/records.py` (`RunRecord.owner`)
- Modify: `src/hypothex/core/execution.py` (`RunRequest.owner`, copied in `_prepare_in`)
- Modify: `src/hypothex/core/control.py` (`rerun`, `reinfer` take `owner`)
- Modify: `src/hypothex/core/sweeps.py` (`SweepSpec.owner`, `launch_sweep(owner=)`, `_requests` copies it)
- Modify: `src/hypothex/core/index.py` (`SCHEMA_VERSION = 4`, `RunRow.owner`, `list_runs(owner=)`)
- Test: `tests/core/test_records_phase3.py`

**Interfaces:**
- Produces (contract 1.2, exact): `RunRecord.owner: str | None = None`; `SweepSpec.owner: str | None = None`; `RunRequest.owner: str | None = None` (copied to `RunRecord.owner`); `SCHEMA_VERSION = 4`; `Index.list_runs(..., owner: str | None = None)`.
- Produces (additive keywords): `control.rerun(..., owner: str | None = None)`, `control.reinfer(..., owner: str | None = None)` (the child run is owned by the caller); `launch_sweep(..., owner: str | None = None)` (stored on the spec; every run of the sweep, and of later `extend_sweep` calls, gets `spec.owner`).
- An index with `schema_version` 3 is rebuilt from files on the next `Context.open` (phase 1 rule).

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_records_phase3.py`:

```python
import sys
from pathlib import Path

import yaml

from hypothex.core import control
from hypothex.core.context import Context
from hypothex.core.execution import RunRequest, prepare_run
from hypothex.core.index import SCHEMA_VERSION, Index, MetaRow
from hypothex.core.records import RunRecord
from hypothex.core.sweeps import SweepParam, SweepSpec, launch_sweep, load_sweep
from tests.factories import make_record, seed_finished_run

PY = sys.executable


def test_old_run_yaml_loads_without_owner(ctx: Context, toy_repo: Path) -> None:
    record = seed_finished_run(ctx, toy_repo, "r1")
    path = ctx.run_dir(record) / "run.yaml"
    data = yaml.safe_load(path.read_text())
    data.pop("owner", None)
    path.write_text(yaml.safe_dump(data))
    assert ctx.store.read_record("toy", "r1").owner is None


def test_owner_round_trips() -> None:
    record = make_record(owner="alice")
    assert RunRecord.model_validate(record.model_dump(mode="json")).owner == "alice"


def test_request_owner_reaches_the_record(ctx: Context, toy_repo: Path) -> None:
    req = RunRequest(repo=toy_repo, command=[PY, "-c", "pass"], owner="alice")
    assert prepare_run(ctx, req).owner == "alice"


def test_rerun_child_is_owned_by_the_caller(ctx: Context, toy_repo: Path) -> None:
    parent = prepare_run(ctx, RunRequest(repo=toy_repo, command=[PY, "-c", "pass"], owner="sv"))
    child = control.rerun(ctx, parent.run_id, created_by="human:alice", owner="alice")
    control.wait_for_run(ctx, child.run_id, timeout=30)
    assert child.owner == "alice" and child.created_by == "human:alice"
    assert ctx.find_record(parent.run_id).owner == "sv"


def test_sweep_spec_without_owner_loads() -> None:
    spec = SweepSpec.model_validate(
        {
            "id": "s-0001",
            "project": "toy",
            "task": None,
            "host": None,
            "grid": [{"name": "x", "values": ["1"]}],
            "seeds": [1],
            "command_template": ["echo", "{x}"],
            "created_by": "human",
            "created_at": "2026-10-04T09:00:00+00:00",
        }
    )
    assert spec.owner is None


def test_sweep_owner_is_stored_and_given_to_every_run(ctx: Context, toy_repo: Path) -> None:
    ctx.register_project(toy_repo)
    summary = launch_sweep(
        ctx,
        project="toy",
        grid=[SweepParam(name="x", values=["1", "2"])],
        seeds=[1],
        command=[PY, "-c", "import sys", "{x}"],
        created_by="human:alice",
        owner="alice",
    )
    assert load_sweep(ctx.layout, "toy", summary.spec.id).owner == "alice"
    owners = {ctx.find_record(r).owner for r in summary.run_ids}
    assert owners == {"alice"}


def test_list_runs_filters_by_owner(ctx: Context) -> None:
    eid = ctx.descriptor.environment_id
    for run_id, owner in (("a", "alice"), ("b", "sv"), ("c", None)):
        ctx.create_run(make_record(run_id, environment_id=eid, owner=owner))
    assert [r.run_id for r in ctx.index.list_runs(owner="alice")] == ["a"]
    assert {r.run_id for r in ctx.index.list_runs()} == {"a", "b", "c"}


def test_schema_3_index_is_rebuilt(tmp_path: Path) -> None:
    from sqlalchemy.orm import Session

    index = Index(tmp_path / "index.db")
    with Session(index.engine) as session, session.begin():
        session.merge(MetaRow(key="schema_version", value="3"))
    assert SCHEMA_VERSION == 4
    assert Index(tmp_path / "index.db").rebuilt_schema is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_records_phase3.py -v`
Expected: FAIL; `test_owner_round_trips` with `AttributeError: 'RunRecord' object has no attribute 'owner'`, `test_request_owner_reaches_the_record` with `TypeError: RunRequest.__init__() got an unexpected keyword argument 'owner'`, `test_schema_3_index_is_rebuilt` with `assert 3 == 4`.

- [ ] **Step 3: Write the implementation**

In `src/hypothex/core/records.py`, in `RunRecord`, after `created_by: str = "human"` add:

```python
    owner: str | None = None
    """User name of the principal that created the run; None with auth off or before phase 3."""
```

In `src/hypothex/core/execution.py`, in `RunRequest`, after `diff: str | bytes | None = None` add:

```python
    owner: str | None = None
```

and extend its docstring with: "``owner`` is the user who asked for the run (``RunRecord.owner``)." In `_prepare_in`, in the `RunRecord(...)` call, after `created_by=req.created_by,` add `owner=req.owner,`.

In `src/hypothex/core/control.py`, add `owner: str | None = None,` after `created_by: str = "human",` in the signatures of `rerun` and `reinfer`, document it in both docstrings ("owner : str, optional — user name of the caller; the child run is theirs."), and add `owner=owner,` after `created_by=created_by,` in both `RunRequest(...)` calls.

In `src/hypothex/core/sweeps.py`:
- in `SweepSpec`, after `created_at: datetime` add `owner: str | None = None`;
- in `launch_sweep`, add `owner: str | None = None,` after `created_by: str = "human",`, document it ("owner : str, optional — user name stored on the sweep and given to each of its runs."), and add `owner=owner,` after `created_at=utcnow(),` in the `SweepSpec(...)` draft;
- in `_requests`, in the `RunRequest(...)` call, after `created_by=spec.created_by,` add `owner=spec.owner,`.

In `src/hypothex/core/index.py`:
- `SCHEMA_VERSION = 4`;
- in `RunRow`, after `starred` add `owner: Mapped[str | None] = mapped_column(String, nullable=True, index=True)`;
- in the shared `_run_values(record)` dictionary, after `"starred": record.starred,` add `"owner": record.owner,`; retain `"parent": record.parent`. Both `upsert_run` and staged `_add_run` use this helper, so live writes and rebuilds retain owner and parent;
- add `owner: str | None = None,` to `list_runs` and `count_runs`, document it alongside their existing filters, and add an `owner: str | None = None` keyword to `_filter_runs`. Pass `owner=owner` at both calls to `_filter_runs`, retaining all existing filters and keyset pagination. In `_filter_runs`, before its return, add:

```python
    if owner is not None:
        stmt = stmt.where(RunRow.owner == owner)
```

The existing parent index, `_touch` generation/change markers, and all staging/recovery helpers stay. Extend `test_list_runs_filters_by_owner` to assert `count_runs(owner="alice") == 1` and owner-filtered keyset pagination. Add a file-backed child with `owner="alice", parent="a"`, rebuild through `rebuild_index`, then assert both the returned record and SQL `RunRow.owner`/`RunRow.parent` retain those values. Reopen a home whose schema marker was set to 3 and assert `Context.open` rebuilds it to 4 while retaining that child and its scores. Keep the original schema-marker probe as a narrow constructor test, not evidence of a completed rebuild.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_records_phase3.py -v`
Expected: all record/schema/owner regression cases pass.

Run: `uv run pytest -q && uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check src`
Expected: every test passes; lint, format, and types clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/records.py src/hypothex/core/execution.py src/hypothex/core/control.py src/hypothex/core/sweeps.py src/hypothex/core/index.py tests/core/test_records_phase3.py
git commit -m "feat(records): run and sweep owner, owner filter, index schema 4"
```

---
### Task 5: Scopes, principals, and ownership rules (`hypothex.auth`)

**Files:**
- Create: `src/hypothex/auth/__init__.py`, `src/hypothex/auth/scopes.py`, `src/hypothex/auth/store.py` (models, errors, constants; `AuthStore` comes in Task 6), `src/hypothex/auth/ownership.py`
- Test: `tests/auth/__init__.py`, `tests/auth/test_scopes.py`

**Interfaces:**
- Produces (contract 1.10, 1.3, exact): `Scope`, `ScopeOrPublic`, `covers(held, wanted)`, `scopes_of(held)`; `USER_NAME`, `Client`, `User`, `Session`, `PairingOffer`, `Principal`, `LOCAL_OWNER`, `PAIRING_TTL_SECONDS`, `PAIRING_MAX_FAILURES`, `TICKET_TTL_SECONDS`, `AuthError`, `ScopeError`, `PairingError`; `RunAction`, `OWNER_ACTIONS`, `may_act`, `require_act`, `LOCAL_EXEC_REFUSED`, `require_local_exec`.
- Produces (public helpers): `SCOPE_ORDER`, `SCOPE_GLYPH = {"read": "r", "launch": "l", "admin": "a"}`; `HOST_PRINCIPAL = Principal(user="hub", scope="admin", session_id=None, client="host")` (a hub forwarding to a host, contract 7); `Principal.identity() -> str` (`human:<user>`, or `agent:<agent>@<user>` when `agent` is set); `PAIRING_INVALID` (the one `PairingError` message).

- [ ] **Step 1: Write the failing test**

Create `tests/auth/__init__.py` (empty) and `tests/auth/test_scopes.py`:

```python
import pytest

from hypothex.auth.ownership import OWNER_ACTIONS, may_act, require_act, require_local_exec
from hypothex.auth.scopes import covers, scopes_of
from hypothex.auth.store import HOST_PRINCIPAL, LOCAL_OWNER, PAIRING_INVALID, Principal, ScopeError


def who(user: str, scope: str, agent: str | None = None) -> Principal:
    return Principal(user=user, scope=scope, session_id="s_000000000001", client="cli", agent=agent)


@pytest.mark.parametrize(
    ("held", "wanted", "ok"),
    [
        ("read", "read", True),
        ("read", "launch", False),
        ("read", "admin", False),
        ("launch", "read", True),
        ("launch", "launch", True),
        ("launch", "admin", False),
        ("admin", "read", True),
        ("admin", "admin", True),
    ],
)
def test_covers(held: str, wanted: str, ok: bool) -> None:
    assert covers(held, wanted) is ok  # type: ignore[arg-type]


def test_scopes_of() -> None:
    assert scopes_of("read") == ["read"]
    assert scopes_of("launch") == ["read", "launch"]
    assert scopes_of("admin") == ["read", "launch", "admin"]


def test_identity() -> None:
    assert who("alice", "launch").identity() == "human:alice"
    assert who("alice", "launch", agent="claude").identity() == "agent:claude@alice"
    assert LOCAL_OWNER.scope == "admin" and LOCAL_OWNER.client == "local"


@pytest.mark.parametrize(
    ("user", "scope", "owner", "action", "ok"),
    [
        ("alice", "launch", "alice", "stop", True),
        ("alice", "launch", "sv", "stop", False),
        ("alice", "launch", "sv", "archive", False),
        ("alice", "launch", "sv", "cancel_queued", False),
        ("alice", "launch", "sv", "tag", True),
        ("alice", "launch", "sv", "rerun", True),
        ("alice", "launch", None, "stop", False),
        ("sv", "admin", "alice", "stop", True),
        ("sv", "admin", None, "archive", True),
        ("bob", "read", "bob", "stop", False),
        ("bob", "read", "bob", "note", False),
    ],
)
def test_may_act(user: str, scope: str, owner: str | None, action: str, ok: bool) -> None:
    assert may_act(who(user, scope), owner, action) is ok  # type: ignore[arg-type]


def test_only_admin_starts_runs_on_this_machine() -> None:
    require_local_exec(LOCAL_OWNER)  # auth off
    require_local_exec(HOST_PRINCIPAL)  # a hub forwarding to its host
    require_local_exec(who("sv", "admin"))
    with pytest.raises(ScopeError, match=r"^runs on this machine need admin; launch on a host$"):
        require_local_exec(who("alice", "launch"))


def test_require_act_message_names_the_owner() -> None:
    with pytest.raises(ScopeError, match="run owned by sv; stop needs owner or admin"):
        require_act(who("alice", "launch"), "sv", "stop")
    with pytest.raises(ScopeError, match="run owned by the hub owner"):
        require_act(who("alice", "launch"), None, "archive")
    with pytest.raises(ScopeError, match="launch scope"):
        require_act(who("bob", "read"), "bob", "tag")


def test_owner_actions() -> None:
    assert frozenset({"stop", "archive", "cancel_queued"}) == OWNER_ACTIONS
    assert "expired" in PAIRING_INVALID
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/auth/test_scopes.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'hypothex.auth'`.

- [ ] **Step 3: Write the implementation**

Create `src/hypothex/auth/__init__.py`:

```python
"""Users, pairing, sessions, scopes, and run ownership (phase 3 auth)."""
```

Create `src/hypothex/auth/scopes.py`:

```python
"""Scopes: ``read`` ⊂ ``launch`` ⊂ ``admin``."""

from __future__ import annotations

from typing import Literal

Scope = Literal["read", "launch", "admin"]
ScopeOrPublic = Literal["read", "launch", "admin", "public"]
SCOPE_ORDER: tuple[Scope, ...] = ("read", "launch", "admin")
SCOPE_GLYPH: dict[Scope, str] = {"read": "r", "launch": "l", "admin": "a"}


def covers(held: Scope, wanted: Scope) -> bool:
    """
    Tell whether a held scope allows an action that needs ``wanted``.

    Parameters
    ----------
    held : Scope
        The principal's scope.
    wanted : Scope
        The scope the route, socket, or tool declares.

    Returns
    -------
    bool
        True when ``held`` is ``wanted`` or wider.

    Examples
    --------
    >>> covers("admin", "launch"), covers("read", "launch")
    (True, False)
    """
    return SCOPE_ORDER.index(held) >= SCOPE_ORDER.index(wanted)


def scopes_of(held: Scope) -> list[Scope]:
    """
    List every scope a held scope includes.

    Parameters
    ----------
    held : Scope
        The principal's scope.

    Returns
    -------
    list of Scope
        From ``read`` up to ``held``.

    Examples
    --------
    >>> scopes_of("launch")
    ['read', 'launch']
    """
    return list(SCOPE_ORDER[: SCOPE_ORDER.index(held) + 1])
```

Create `src/hypothex/auth/store.py`:

```python
"""Users, pairing offers, sessions, and principals (state in ``<home>/auth/auth.db``)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from hypothex.auth.scopes import Scope
from hypothex.core.errors import HypothexError

USER_NAME = r"^[a-z][a-z0-9_-]{0,31}$"
Client = Literal["browser", "cli", "agent", "host", "local"]
PAIRING_TTL_SECONDS = 300
PAIRING_MAX_FAILURES = 5
TICKET_TTL_SECONDS = 30
PAIRING_INVALID = "pairing link invalid or expired; run hx pair again"


class AuthError(HypothexError):
    """No valid session (HTTP 401)."""


class ScopeError(HypothexError):
    """The principal's scope or ownership does not allow the action (HTTP 403)."""


class PairingError(HypothexError):
    """A pairing link is unknown, expired, used, or has a wrong secret (HTTP 400)."""


class User(BaseModel):
    """A person (or the hub owner) who may hold sessions."""

    name: str
    role: Scope
    created_at: datetime
    created_by: str
    disabled_at: datetime | None = None


class Session(BaseModel):
    """A revocable session of one device; its secret is stored as a sha256."""

    id: str
    user: str
    scope: Scope
    client: Client
    device: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None


class PairingOffer(BaseModel):
    """A one-time pairing link (``hx pair``)."""

    id: str
    user: str
    new_user: bool
    scope: Scope
    issued_by: str
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None = None
    failures: int = 0


class Principal(BaseModel):
    """Who is calling: a user's session, the local owner, or a hub forwarding."""

    user: str
    scope: Scope
    session_id: str | None
    client: Client
    agent: str | None = None

    def identity(self) -> str:
        """
        Return the ``created_by`` value for runs this principal starts.

        Returns
        -------
        str
            ``agent:<agent>@<user>`` when an agent acts for the user, else
            ``human:<user>``.

        Examples
        --------
        >>> Principal(user="al", scope="read", session_id=None, client="cli").identity()
        'human:al'
        """
        if self.agent:
            return f"agent:{self.agent}@{self.user}"
        return f"human:{self.user}"


LOCAL_OWNER = Principal(user="local", scope="admin", session_id=None, client="local")
"""Every request when auth is off (phase 1-2 behaviour)."""
HOST_PRINCIPAL = Principal(user="hub", scope="admin", session_id=None, client="host")
"""A hub forwarding to a host (``TokenGuard`` token or ``host_token``)."""
```

Create `src/hypothex/auth/ownership.py`:

```python
"""Who may act on a run: everyone with ``launch``; stop/archive/cancel only the owner or admin."""

from __future__ import annotations

from typing import Literal

from hypothex.auth.scopes import covers
from hypothex.auth.store import Principal, ScopeError

RunAction = Literal[
    "stop", "archive", "tag", "star", "note", "rerun", "reinfer", "reeval", "cancel_queued",
    "extend", "pull",
]  # fmt: skip
OWNER_ACTIONS = frozenset({"stop", "archive", "cancel_queued"})


def may_act(principal: Principal, owner: str | None, action: RunAction) -> bool:
    """
    Tell whether a principal may take an action on a run.

    Parameters
    ----------
    principal : Principal
        The caller.
    owner : str or None
        ``RunRecord.owner`` (or ``SweepSpec.owner``); None means the hub owner's.
    action : RunAction
        The action.

    Returns
    -------
    bool
        Every action needs ``launch``; ``OWNER_ACTIONS`` also need the caller
        to be the owner, or ``admin``. A run without an owner is the hub
        owner's, so only ``admin`` may stop or archive it.

    Examples
    --------
    >>> p = Principal(user="al", scope="launch", session_id=None, client="cli")
    >>> may_act(p, "al", "stop"), may_act(p, "sv", "stop"), may_act(p, "sv", "tag")
    (True, False, True)
    """
    if not covers(principal.scope, "launch"):
        return False
    if action not in OWNER_ACTIONS or principal.scope == "admin":
        return True
    return owner is not None and principal.user == owner


def require_act(principal: Principal, owner: str | None, action: RunAction) -> None:
    """
    Raise unless ``may_act`` allows the action.

    Parameters
    ----------
    principal : Principal
        The caller.
    owner : str or None
        The run's owner.
    action : RunAction
        The action.

    Raises
    ------
    ScopeError
        ``run owned by <owner>; <action> needs owner or admin``, or a missing
        ``launch`` scope.
    """
    if may_act(principal, owner, action):
        return
    if not covers(principal.scope, "launch"):
        raise ScopeError(f"{action} needs the launch scope; you hold {principal.scope}")
    who = owner if owner is not None else "the hub owner"
    raise ScopeError(f"run owned by {who}; {action} needs owner or admin")


LOCAL_EXEC_REFUSED = "runs on this machine need admin; launch on a host"


def require_local_exec(principal: Principal) -> None:
    """
    Raise unless a principal may start a run on this machine.

    A run executes as this server's Unix user, so its command can read every
    file that user can (``serve/server.json`` with the owner's admin token,
    ``secrets.env``, ``auth.db``, SSH keys). Starting one is trusting the
    caller with all of that, which is ``admin``: the hub owner, every caller
    with auth off (``LOCAL_OWNER``), and a hub forwarding to its host
    (``HOST_PRINCIPAL``). A ``launch`` principal launches on hosts, which run
    jobs under their own account.

    Parameters
    ----------
    principal : Principal
        The caller.

    Raises
    ------
    ScopeError
        ``runs on this machine need admin; launch on a host``.

    Examples
    --------
    >>> from hypothex.auth.store import LOCAL_OWNER
    >>> require_local_exec(LOCAL_OWNER)
    """
    if principal.scope != "admin":
        raise ScopeError(LOCAL_EXEC_REFUSED)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/auth/test_scopes.py -v`
Expected: `24 passed`.

Run: `uv run python -m doctest src/hypothex/auth/scopes.py src/hypothex/auth/store.py src/hypothex/auth/ownership.py && uv run ruff check src/hypothex/auth tests/auth && uv run ruff format --check src/hypothex/auth tests/auth && uv run ty check src`
Expected: no doctest output, `All checks passed!`, all files formatted, `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/auth tests/auth
git commit -m "feat(auth): scopes, principals, and run ownership rules"
```

---

### Task 6: `AuthStore` — users, pairing offers, sessions

**Files:**
- Modify: `src/hypothex/auth/store.py` (append `AuthStore`)
- Test: `tests/auth/test_store.py`

**Interfaces:**
- Consumes: Task 5 models and errors; `utcnow`; `Layout`.
- Produces (contract 1.10, exact): `AuthStore(layout, *, now=utcnow)` with `ensure_owner`, `users`, `get_user`, `disable_user`, `create_offer`, `redeem`, `authenticate`, `sessions`, `revoke`, `mint_local`. Tickets are Task 7.
- Produces (additive): `AuthStore(..., session_days: int = 90)` (`hx serve` passes `server.session_days`); `AuthStore.path` (`<home>/auth/auth.db`); `parse_token(token) -> tuple[str, str] | None`.
- Rules (contract 1.10, 7): `<home>/auth` is 0700, `auth.db` 0600; secrets are stored as `sha256` hex and compared with `hmac.compare_digest`. Token format `hxs_<session id>_<43-char secret>` with session id `s_<12 hex>`; offer id `p_<12 hex>`. A pairing offer is one use, at most 300 s, burned after 5 wrong secrets, and every failure raises `PairingError(PAIRING_INVALID)`. `create_offer` derives `new_user` from whether `user` exists; a new user or another user needs `admin`; the offer's scope never exceeds the issuer's scope or the target user's role. `redeem(client="host")` needs an `admin` offer (a host session forwards other users' identities, contract 1.2), else `PairingError` without using the offer. Sessions slide: `authenticate` moves `last_seen_at` and `expires_at = last_seen_at + session_days` at most once per 60 s. `sessions()` lists active sessions (not revoked, not expired), newest first.

- [ ] **Step 1: Write the failing test**

Create `tests/auth/test_store.py`:

```python
import re
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hypothex.auth.store import (
    PAIRING_INVALID,
    AuthStore,
    PairingError,
    Principal,
    ScopeError,
    parse_token,
)
from hypothex.core.layout import Layout

T0 = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)
TOKEN = re.compile(r"^hxs_s_[0-9a-f]{12}_[A-Za-z0-9_-]{43}$")


class Clock:
    def __init__(self) -> None:
        self.t = T0

    def __call__(self) -> datetime:
        return self.t

    def tick(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(tmp_path: Path, clock: Clock) -> AuthStore:
    return AuthStore(Layout(tmp_path), now=clock, session_days=90)


def owner(store: AuthStore) -> Principal:
    store.ensure_owner("sv")
    session, token = store.mint_local("sv")
    principal = store.authenticate(token)
    assert principal is not None
    return principal


def pair(store: AuthStore, issuer: Principal, user: str, scope: str, client: str = "cli") -> str:
    offer, secret = store.create_offer(issuer=issuer, user=user, scope=scope)  # type: ignore[arg-type]
    _, token = store.redeem(offer.id, secret, client=client, device="laptop")  # type: ignore[arg-type]
    return token


def test_files_are_private(store: AuthStore, tmp_path: Path) -> None:
    store.ensure_owner("sv")
    assert stat.S_IMODE((tmp_path / "auth").stat().st_mode) == 0o700
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600


def test_ensure_owner_is_idempotent(store: AuthStore) -> None:
    first = store.ensure_owner("sv")
    again = store.ensure_owner("sv")
    assert first == again and first.role == "admin"
    assert [u.name for u in store.users()] == ["sv"]


def test_pair_a_new_collaborator(store: AuthStore) -> None:
    admin = owner(store)
    offer, secret = store.create_offer(issuer=admin, user="alice", scope="launch")
    assert offer.new_user and offer.id.startswith("p_") and len(secret) == 43
    assert offer.expires_at == T0 + timedelta(seconds=300)
    session, token = store.redeem(offer.id, secret, client="cli", device="MacBook")
    assert TOKEN.match(token) and session.user == "alice" and session.scope == "launch"
    alice = store.authenticate(token)
    assert alice == Principal(user="alice", scope="launch", session_id=session.id, client="cli")
    assert store.get_user("alice") is not None and store.get_user("alice").role == "launch"


def test_pairing_never_widens_scope(store: AuthStore) -> None:
    admin = owner(store)
    alice = store.authenticate(pair(store, admin, "alice", "launch"))
    assert alice is not None
    with pytest.raises(ScopeError):
        store.create_offer(issuer=alice, user="alice", scope="admin")
    with pytest.raises(ScopeError, match="needs admin"):
        store.create_offer(issuer=alice, user="bob", scope="read")  # a new user
    with pytest.raises(ScopeError, match="needs admin"):
        store.create_offer(issuer=alice, user="sv", scope="read")  # another user
    offer, _ = store.create_offer(issuer=alice, user="alice", scope="read")  # own device, narrower
    assert offer.scope == "read" and not offer.new_user
    with pytest.raises(ScopeError, match="role"):
        store.create_offer(issuer=admin, user="alice", scope="admin")  # wider than her role


def test_host_sessions_need_an_admin_offer(store: AuthStore) -> None:
    admin = owner(store)
    alice = store.authenticate(pair(store, admin, "alice", "launch"))
    assert alice is not None
    offer, secret = store.create_offer(issuer=alice, user="alice", scope="launch")
    with pytest.raises(PairingError) as info:
        store.redeem(offer.id, secret, client="host", device="forged-hub")
    assert str(info.value) == PAIRING_INVALID
    session, _ = store.redeem(offer.id, secret, client="cli", device="laptop")  # not used up
    assert session.client == "cli"
    offer, secret = store.create_offer(issuer=admin, user="sv", scope="admin")
    session, _ = store.redeem(offer.id, secret, client="host", device="hub:lab")
    assert session.client == "host" and session.scope == "admin"


def test_ttl_is_at_most_five_minutes(store: AuthStore) -> None:
    with pytest.raises(PairingError):
        store.create_offer(issuer=owner(store), user="alice", scope="read", ttl_seconds=301)


def test_offer_is_one_use(store: AuthStore) -> None:
    offer, secret = store.create_offer(issuer=owner(store), user="alice", scope="read")
    store.redeem(offer.id, secret, client="browser", device="phone")
    with pytest.raises(PairingError) as info:
        store.redeem(offer.id, secret, client="browser", device="phone")
    assert str(info.value) == PAIRING_INVALID


def test_expired_offer_is_refused(store: AuthStore, clock: Clock) -> None:
    offer, secret = store.create_offer(issuer=owner(store), user="alice", scope="read")
    clock.tick(301)
    with pytest.raises(PairingError, match="invalid or expired"):
        store.redeem(offer.id, secret, client="cli", device="x")


def test_five_wrong_secrets_burn_the_offer(store: AuthStore) -> None:
    offer, secret = store.create_offer(issuer=owner(store), user="alice", scope="read")
    for _ in range(5):
        with pytest.raises(PairingError):
            store.redeem(offer.id, "x" * 43, client="cli", device="x")
    with pytest.raises(PairingError):
        store.redeem(offer.id, secret, client="cli", device="x")


def test_unknown_offer_has_the_same_message(store: AuthStore) -> None:
    with pytest.raises(PairingError) as info:
        store.redeem("p_000000000000", "y" * 43, client="cli", device="x")
    assert str(info.value) == PAIRING_INVALID


def test_sessions_slide_and_expire(store: AuthStore, clock: Clock) -> None:
    token = pair(store, owner(store), "alice", "read")
    clock.tick(89 * 86400)
    assert store.authenticate(token) is not None  # slides: expires 90 days from now
    clock.tick(89 * 86400)
    assert store.authenticate(token) is not None
    clock.tick(91 * 86400)
    assert store.authenticate(token) is None


def test_tampered_token_is_refused(store: AuthStore) -> None:
    token = pair(store, owner(store), "alice", "read")
    assert store.authenticate(token[:-1] + ("A" if token[-1] != "A" else "B")) is None
    assert store.authenticate("hxs_garbage") is None
    assert parse_token(token) is not None and parse_token("Bearer x") is None


def test_revoke_own_other_and_admin(store: AuthStore) -> None:
    admin = owner(store)
    alice_token = pair(store, admin, "alice", "launch")
    pair(store, admin, "bob", "read")
    alice = store.authenticate(alice_token)
    assert alice is not None
    bob_session = next(s for s in store.sessions("bob"))
    with pytest.raises(ScopeError):
        store.revoke(bob_session.id, by=alice)
    store.revoke(bob_session.id, by=admin)
    assert store.sessions("bob") == []
    store.revoke(str(alice.session_id), by=alice)
    assert store.authenticate(alice_token) is None


def test_disable_user_revokes_sessions(store: AuthStore) -> None:
    admin = owner(store)
    token = pair(store, admin, "alice", "launch")
    user = store.disable_user("alice", by=admin)
    assert user.disabled_at == T0
    assert store.authenticate(token) is None
    with pytest.raises(ScopeError):
        store.disable_user("sv", by=admin)  # never yourself


def test_secrets_are_stored_hashed(store: AuthStore) -> None:
    offer, secret = store.create_offer(issuer=owner(store), user="alice", scope="read")
    _, token = store.redeem(offer.id, secret, client="cli", device="x")
    data = store.path.read_bytes()
    parts = parse_token(token)
    assert parts is not None
    assert secret.encode() not in data and parts[1].encode() not in data


def test_mint_local_is_an_admin_local_session(store: AuthStore) -> None:
    store.ensure_owner("sv")
    session, token = store.mint_local("sv")
    assert session.client == "local" and session.scope == "admin"
    principal = store.authenticate(token)
    assert principal is not None and principal.user == "sv" and principal.scope == "admin"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/auth/test_store.py -v`
Expected: FAIL at collection with `ImportError: cannot import name 'AuthStore' from 'hypothex.auth.store'`.

- [ ] **Step 3: Write the implementation**

In `src/hypothex/auth/store.py`, replace the import block with:

```python
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from hypothex.auth.scopes import Scope, covers
from hypothex.core.errors import ConfigError, HypothexError, StoreError
from hypothex.core.ids import utcnow
from hypothex.core.layout import Layout
```

and append to the end of the file:

```python
AUTH_DIR = "auth"
AUTH_DB = "auth.db"
LAST_SEEN_EVERY = timedelta(seconds=60)
TOKEN_PREFIX = "hxs_"
_TOKEN = re.compile(r"^hxs_(s_[0-9a-f]{12})_([A-Za-z0-9_-]{43})$")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  name TEXT PRIMARY KEY, role TEXT NOT NULL, created_at TEXT NOT NULL,
  created_by TEXT NOT NULL, disabled_at TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, user TEXT NOT NULL, scope TEXT NOT NULL, client TEXT NOT NULL,
  device TEXT NOT NULL, secret_hash TEXT NOT NULL, created_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL, expires_at TEXT NOT NULL, revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS offers (
  id TEXT PRIMARY KEY, user TEXT NOT NULL, new_user INTEGER NOT NULL, scope TEXT NOT NULL,
  issued_by TEXT NOT NULL, secret_hash TEXT NOT NULL, created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL, used_at TEXT, failures INTEGER NOT NULL DEFAULT 0
);
"""


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _same(secret: str, stored: str) -> bool:
    return hmac.compare_digest(_hash(secret), stored)


def _at(text: str | None) -> datetime | None:
    return None if text is None else datetime.fromisoformat(text)


def parse_token(token: str) -> tuple[str, str] | None:
    """
    Split a session token into its session id and secret.

    Parameters
    ----------
    token : str
        ``hxs_<session id>_<secret>``.

    Returns
    -------
    tuple of (str, str) or None
        ``(session_id, secret)``; None when the text is not a token.

    Examples
    --------
    >>> parse_token("hxs_s_0123456789ab_" + "a" * 43)[0]
    's_0123456789ab'
    >>> parse_token("nope") is None
    True
    """
    match = _TOKEN.match(token)
    return (match.group(1), match.group(2)) if match else None


class AuthStore:
    """
    Users, pairing offers, sessions, and WebSocket tickets of one hub.

    State lives in ``<home>/auth/auth.db`` (SQLite; folder 0700, file 0600),
    never in the index: ``hx reindex`` does not touch it. Secrets are stored
    as sha256 and compared in constant time. Tickets live in memory only.

    Parameters
    ----------
    layout : Layout
        The hub's home.
    now : callable, optional
        Clock (tests pass a fake one).
    session_days : int
        Session lifetime; it slides with use.
    """

    def __init__(
        self,
        layout: Layout,
        *,
        now: Callable[[], datetime] = utcnow,
        session_days: int = 90,
    ) -> None:
        self.now = now
        self.session_days = session_days
        folder = layout.home / AUTH_DIR
        folder.mkdir(parents=True, exist_ok=True)
        folder.chmod(0o700)
        self.path: Path = folder / AUTH_DB
        if not self.path.exists():
            os.close(os.open(self.path, os.O_WRONLY | os.O_CREAT, 0o600))
        self.path.chmod(0o600)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)
        self._tickets: dict[str, tuple[Principal, datetime]] = {}
        self._ticket_lock = threading.Lock()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            conn.execute("PRAGMA busy_timeout=10000")
            conn.row_factory = sqlite3.Row
            yield conn
        finally:
            conn.close()

    # users ---------------------------------------------------------------------------
    @staticmethod
    def _user(row: sqlite3.Row) -> User:
        return User(
            name=row["name"],
            role=row["role"],
            created_at=datetime.fromisoformat(row["created_at"]),
            created_by=row["created_by"],
            disabled_at=_at(row["disabled_at"]),
        )

    def ensure_owner(self, name: str) -> User:
        """
        Create the first admin, or return it when it exists.

        Parameters
        ----------
        name : str
            User name (``USER_NAME``).

        Returns
        -------
        User
            The owner.

        Raises
        ------
        ConfigError
            The name does not match ``USER_NAME``.
        """
        if not re.fullmatch(USER_NAME, name):
            raise ConfigError(f"user name {name!r} must match {USER_NAME}")
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users(name, role, created_at, created_by) VALUES (?,?,?,?)",
                (name, "admin", self.now().isoformat(), "hx serve"),
            )
        user = self.get_user(name)
        assert user is not None
        return user

    def users(self) -> list[User]:
        """
        List every user, by name.

        Returns
        -------
        list of User
        """
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY name").fetchall()
        return [self._user(r) for r in rows]

    def get_user(self, name: str) -> User | None:
        """
        Return one user, or None.

        Parameters
        ----------
        name : str

        Returns
        -------
        User or None
        """
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchone()
        return None if row is None else self._user(row)

    def disable_user(self, name: str, *, by: Principal) -> User:
        """
        Disable a user and revoke every session they hold (admin only).

        Parameters
        ----------
        name : str
            User to disable.
        by : Principal
            The caller; must be ``admin`` and not ``name``.

        Returns
        -------
        User
            The disabled user.

        Raises
        ------
        ScopeError
            The caller is not admin, or names themselves.
        StoreError
            No such user (404).
        """
        if by.scope != "admin":
            raise ScopeError("disabling users needs admin")
        if by.user == name:
            raise ScopeError("you cannot disable yourself")
        now = self.now().isoformat()
        with self._conn() as conn:
            done = conn.execute(
                "UPDATE users SET disabled_at = COALESCE(disabled_at, ?) WHERE name = ?",
                (now, name),
            ).rowcount
            conn.execute(
                "UPDATE sessions SET revoked_at = ? WHERE user = ? AND revoked_at IS NULL",
                (now, name),
            )
        if not done:
            raise StoreError(f"no user {name!r}")
        user = self.get_user(name)
        assert user is not None
        return user

    # pairing -------------------------------------------------------------------------
    def create_offer(
        self,
        *,
        issuer: Principal,
        user: str,
        scope: Scope,
        ttl_seconds: int = PAIRING_TTL_SECONDS,
    ) -> tuple[PairingOffer, str]:
        """
        Issue a one-time pairing offer; never wider than the issuer or the user's role.

        Parameters
        ----------
        issuer : Principal
            Who asks for the link.
        user : str
            The user the new session belongs to; a name that does not exist yet
            makes a new user with role ``scope`` (admin only).
        scope : Scope
            Scope of the session the link creates.
        ttl_seconds : int
            Lifetime, 1 to 300 seconds.

        Returns
        -------
        tuple of (PairingOffer, str)
            The offer and its secret (shown once, in the link's fragment).

        Raises
        ------
        PairingError
            ``ttl_seconds`` outside 1..300.
        ConfigError
            A user name that does not match ``USER_NAME``.
        ScopeError
            ``scope`` is wider than the issuer's scope or the user's role; a new
            user or another user's device without ``admin``; a disabled user.
        """
        if not 1 <= ttl_seconds <= PAIRING_TTL_SECONDS:
            raise PairingError(f"ttl must be 1..{PAIRING_TTL_SECONDS} seconds")
        if not re.fullmatch(USER_NAME, user):
            raise ConfigError(f"user name {user!r} must match {USER_NAME}")
        if not covers(issuer.scope, scope):
            raise ScopeError(f"cannot pair with scope {scope}: you hold {issuer.scope}")
        target = self.get_user(user)
        if target is None and issuer.scope != "admin":
            raise ScopeError("adding a user needs admin")
        if target is not None:
            if target.name != issuer.user and issuer.scope != "admin":
                raise ScopeError("pairing another user's device needs admin")
            if target.disabled_at is not None:
                raise ScopeError(f"user {user} is disabled")
            if not covers(target.role, scope):
                raise ScopeError(f"user {user} has role {target.role}; cannot pair {scope}")
        now = self.now()
        offer = PairingOffer(
            id=f"p_{secrets.token_hex(6)}",
            user=user,
            new_user=target is None,
            scope=scope,
            issued_by=issuer.user,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        secret = secrets.token_urlsafe(32)
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO offers(id, user, new_user, scope, issued_by, secret_hash, "
                "created_at, expires_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    offer.id, offer.user, int(offer.new_user), offer.scope, offer.issued_by,
                    _hash(secret), now.isoformat(), offer.expires_at.isoformat(),
                ),
            )  # fmt: skip
        return offer, secret

    def redeem(
        self, offer_id: str, secret: str, *, client: Client, device: str
    ) -> tuple[Session, str]:
        """
        Exchange a pairing offer for a session (once).

        Parameters
        ----------
        offer_id : str
            ``p_<12 hex>`` from the link.
        secret : str
            The link's secret.
        client : Client
            ``browser``, ``cli``, ``agent``, or ``host``. A ``host`` session is
            trusted to forward ``created_by``/``owner`` for other users, so only
            an ``admin`` offer (issued by an admin) may be redeemed as ``host``.
        device : str
            A label shown in the sessions list (cut to 64 characters).

        Returns
        -------
        tuple of (Session, str)
            The session and its token ``hxs_<session id>_<secret>`` (shown once).

        Raises
        ------
        PairingError
            Unknown, expired, used, burned, or wrong secret, or ``client="host"``
            on an offer below ``admin``: always the same message.
        """
        if client not in ("browser", "cli", "agent", "host"):
            raise PairingError(PAIRING_INVALID)
        now = self.now()
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                session, token = self._redeem_in(conn, offer_id, secret, client, device, now)
            except BaseException:
                conn.execute("COMMIT")  # keeps a failure count written by _redeem_in
                raise
            conn.execute("COMMIT")
        return session, token

    def _redeem_in(
        self,
        conn: sqlite3.Connection,
        offer_id: str,
        secret: str,
        client: Client,
        device: str,
        now: datetime,
    ) -> tuple[Session, str]:
        row = conn.execute("SELECT * FROM offers WHERE id = ?", (offer_id,)).fetchone()
        if (
            row is None
            or row["used_at"] is not None
            or row["failures"] >= PAIRING_MAX_FAILURES
            or datetime.fromisoformat(row["expires_at"]) <= now
        ):
            raise PairingError(PAIRING_INVALID)
        if not _same(secret, row["secret_hash"]):
            conn.execute("UPDATE offers SET failures = failures + 1 WHERE id = ?", (offer_id,))
            raise PairingError(PAIRING_INVALID)
        if client == "host" and row["scope"] != "admin":
            raise PairingError(PAIRING_INVALID)  # only an admin may mint a forwarding credential
        user = conn.execute("SELECT * FROM users WHERE name = ?", (row["user"],)).fetchone()
        if row["new_user"]:
            if user is not None:
                raise PairingError(PAIRING_INVALID)
            conn.execute(
                "INSERT INTO users(name, role, created_at, created_by) VALUES (?,?,?,?)",
                (row["user"], row["scope"], now.isoformat(), row["issued_by"]),
            )
        elif user is None or user["disabled_at"] is not None:
            raise PairingError(PAIRING_INVALID)
        conn.execute("UPDATE offers SET used_at = ? WHERE id = ?", (now.isoformat(), offer_id))
        return self._new_session(conn, row["user"], row["scope"], client, device, now)

    def _new_session(
        self,
        conn: sqlite3.Connection,
        user: str,
        scope: str,
        client: str,
        device: str,
        now: datetime,
    ) -> tuple[Session, str]:
        session_id = f"s_{secrets.token_hex(6)}"
        secret = secrets.token_urlsafe(32)
        expires = now + timedelta(days=self.session_days)
        conn.execute(
            "INSERT INTO sessions(id, user, scope, client, device, secret_hash, created_at, "
            "last_seen_at, expires_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                session_id, user, scope, client, device[:64], _hash(secret), now.isoformat(),
                now.isoformat(), expires.isoformat(),
            ),
        )  # fmt: skip
        session = Session.model_validate(
            {
                "id": session_id,
                "user": user,
                "scope": scope,
                "client": client,
                "device": device[:64],
                "created_at": now,
                "last_seen_at": now,
                "expires_at": expires,
            }
        )
        return session, f"{TOKEN_PREFIX}{session_id}_{secret}"

    # sessions ------------------------------------------------------------------------
    @staticmethod
    def _session(row: sqlite3.Row) -> Session:
        data: dict[str, Any] = {k: row[k] for k in row.keys() if k != "secret_hash"}  # noqa: SIM118
        return Session.model_validate(data)

    def authenticate(self, token: str) -> Principal | None:
        """
        Turn a session token into a principal.

        Parameters
        ----------
        token : str
            ``hxs_...`` token (cookie or bearer).

        Returns
        -------
        Principal or None
            None for a malformed, unknown, revoked, or expired token, a wrong
            secret, or a disabled user. A valid use slides the session at most
            once per 60 s.
        """
        parts = parse_token(token)
        if parts is None:
            return None
        session_id, secret = parts
        now = self.now()
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row is None or not _same(secret, row["secret_hash"]):
                return None
            if row["revoked_at"] is not None or datetime.fromisoformat(row["expires_at"]) <= now:
                return None
            user = conn.execute(
                "SELECT disabled_at FROM users WHERE name = ?", (row["user"],)
            ).fetchone()
            if user is None or user["disabled_at"] is not None:
                return None
            if now - datetime.fromisoformat(row["last_seen_at"]) >= LAST_SEEN_EVERY:
                conn.execute(
                    "UPDATE sessions SET last_seen_at = ?, expires_at = ? WHERE id = ?",
                    (
                        now.isoformat(),
                        (now + timedelta(days=self.session_days)).isoformat(),
                        session_id,
                    ),
                )
        return Principal(
            user=row["user"], scope=row["scope"], session_id=session_id, client=row["client"]
        )

    def sessions(self, user: str | None = None) -> list[Session]:
        """
        List active sessions (not revoked, not expired), newest first.

        Parameters
        ----------
        user : str, optional
            Only this user's sessions.

        Returns
        -------
        list of Session
        """
        sql = "SELECT * FROM sessions WHERE revoked_at IS NULL AND expires_at > ?"
        args: list[str] = [self.now().isoformat()]
        if user is not None:
            sql += " AND user = ?"
            args.append(user)
        with self._conn() as conn:
            rows = conn.execute(sql + " ORDER BY created_at DESC, id", args).fetchall()
        return [self._session(r) for r in rows]

    def revoke(self, session_id: str, *, by: Principal) -> Session:
        """
        Revoke a session: the caller's own, or anyone's for an admin.

        Parameters
        ----------
        session_id : str
        by : Principal

        Returns
        -------
        Session
            The revoked session.

        Raises
        ------
        StoreError
            No such session (404).
        ScopeError
            Another user's session without ``admin``.
        """
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row is None:
                raise StoreError(f"no session {session_id!r}")
            if row["user"] != by.user and by.scope != "admin":
                raise ScopeError("revoking another user's session needs admin")
            conn.execute(
                "UPDATE sessions SET revoked_at = COALESCE(revoked_at, ?) WHERE id = ?",
                (self.now().isoformat(), session_id),
            )
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return self._session(row)

    def mint_local(self, user: str) -> tuple[Session, str]:
        """
        Create the admin session ``hx serve`` writes into its own ``server.json``.

        Parameters
        ----------
        user : str
            An existing admin (normally the owner).

        Returns
        -------
        tuple of (Session, str)
            Client ``local``, scope ``admin``; ``hx serve`` revokes it at stop.

        Raises
        ------
        ScopeError
            The user is missing, disabled, or not an admin.
        """
        target = self.get_user(user)
        if target is None or target.disabled_at is not None or target.role != "admin":
            raise ScopeError(f"{user} is not an active admin")
        with self._conn() as conn:
            return self._new_session(conn, user, "admin", "local", "hx serve", self.now())
```

Note the `Literal` import is already used by `Client`; `threading` is used for the ticket lock (Task 7 adds the ticket methods).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/auth -v`
Expected: `tests/auth/test_scopes.py` `24 passed`, `tests/auth/test_store.py` `16 passed`.

Run: `uv run python -m doctest src/hypothex/auth/store.py && uv run ruff check src/hypothex/auth tests/auth && uv run ruff format --check src/hypothex/auth tests/auth && uv run ty check src`
Expected: no doctest output, clean lint, format, and types.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/auth/store.py tests/auth/test_store.py
git commit -m "feat(auth): user, pairing, and session store with hashed secrets"
```

---

### Task 7: WebSocket tickets, pairing links, QR text, and the CLI's hub tokens

**Files:**
- Modify: `src/hypothex/auth/store.py` (`issue_ticket`, `redeem_ticket`)
- Create: `src/hypothex/auth/pairing.py`, `src/hypothex/auth/client.py`
- Test: `tests/auth/test_pairing.py`

**Interfaces:**
- Produces (contract 1.10, exact): `AuthStore.issue_ticket(principal) -> str`, `AuthStore.redeem_ticket(ticket) -> Principal | None` (in memory, single use, `TICKET_TTL_SECONDS`); `pairing_url(base_url, offer_id, secret)`, `parse_pairing_url(url)`, `qr_text(url)`.
- Produces (contract 2, `hub-tokens.json`): `hypothex.auth.client.HUB_TOKENS_FILE = "auth/hub-tokens.json"`, `class HubLogin(BaseModel)` (`token`, `user`, `scope`, `session_id`), `hub_key(url) -> str`, `load_hub_logins(layout) -> dict[str, HubLogin]`, `hub_login(layout, url) -> HubLogin | None`, `save_hub_login(layout, url, login) -> None` (0600), `forget_hub_login(layout, url) -> HubLogin | None`.

- [ ] **Step 1: Write the failing test**

Create `tests/auth/test_pairing.py`:

```python
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hypothex.auth.client import (
    HubLogin,
    forget_hub_login,
    hub_login,
    load_hub_logins,
    save_hub_login,
)
from hypothex.auth.pairing import pairing_url, parse_pairing_url, qr_text
from hypothex.auth.store import AuthStore, Principal
from hypothex.core.errors import ConfigError
from hypothex.core.layout import Layout

SECRET = "A" * 21 + "-_" + "b" * 20
ALICE = Principal(user="alice", scope="launch", session_id="s_00000000000a", client="browser")


def test_ticket_is_single_use_and_short_lived(tmp_path: Path) -> None:
    now = [datetime(2026, 10, 4, tzinfo=UTC)]
    store = AuthStore(Layout(tmp_path), now=lambda: now[0])
    ticket = store.issue_ticket(ALICE)
    assert store.redeem_ticket(ticket) == ALICE
    assert store.redeem_ticket(ticket) is None
    late = store.issue_ticket(ALICE)
    now[0] += timedelta(seconds=31)
    assert store.redeem_ticket(late) is None
    assert store.redeem_ticket("never-issued") is None


def test_pairing_url_round_trips() -> None:
    url = pairing_url("https://hub.tail1234.ts.net/", "p_0123456789ab", SECRET)
    assert url == f"https://hub.tail1234.ts.net/pair#p_0123456789ab.{SECRET}"
    assert parse_pairing_url(url) == ("https://hub.tail1234.ts.net", "p_0123456789ab", SECRET)
    local = pairing_url("http://127.0.0.1:7777", "p_0123456789ab", SECRET)
    assert parse_pairing_url(local)[0] == "http://127.0.0.1:7777"


@pytest.mark.parametrize(
    "url",
    [
        "https://hub/pair",
        "https://hub/pair#p_0123456789ab",
        "https://hub/pair#x_0123456789ab." + SECRET,
        "https://hub/login#p_0123456789ab." + SECRET,
        "ftp://hub/pair#p_0123456789ab." + SECRET,
        "https://hub/pair#p_0123456789ab.short",
    ],
)
def test_malformed_links_are_refused(url: str) -> None:
    with pytest.raises(ConfigError, match="pairing link"):
        parse_pairing_url(url)


def test_qr_text_is_plain_half_blocks() -> None:
    text = qr_text(pairing_url("http://127.0.0.1:7777", "p_0123456789ab", SECRET))
    assert "\x1b" not in text
    assert set(text) <= {"█", "▀", "▄", " ", "\n"}
    lines = text.splitlines()
    assert len(lines) > 10 and len({len(line) for line in lines}) == 1


def test_hub_logins_are_private_and_round_trip(tmp_path: Path) -> None:
    layout = Layout(tmp_path)
    login = HubLogin(token="hxs_t", user="alice", scope="launch", session_id="s_00000000000a")
    save_hub_login(layout, "https://hub.tail1234.ts.net/", login)
    path = tmp_path / "auth" / "hub-tokens.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert load_hub_logins(layout) == {"https://hub.tail1234.ts.net": login}
    assert hub_login(layout, "https://hub.tail1234.ts.net") == login
    assert forget_hub_login(layout, "https://hub.tail1234.ts.net") == login
    assert load_hub_logins(layout) == {}
    assert hub_login(Layout(tmp_path / "none"), "https://x") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/auth/test_pairing.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'hypothex.auth.client'`.

- [ ] **Step 3: Write the implementation**

Append to the `AuthStore` class in `src/hypothex/auth/store.py`:

```python
    # tickets -------------------------------------------------------------------------
    def issue_ticket(self, principal: Principal) -> str:
        """
        Issue a single-use WebSocket ticket for a principal (in memory, 30 s).

        Parameters
        ----------
        principal : Principal
            The caller of ``POST /api/v1/auth/ws-ticket``.

        Returns
        -------
        str
            The ticket, sent as ``/api/v1/ws?ticket=<t>``.
        """
        ticket = secrets.token_urlsafe(24)
        expires = self.now() + timedelta(seconds=TICKET_TTL_SECONDS)
        with self._ticket_lock:
            now = self.now()
            for key in [k for k, (_, at) in self._tickets.items() if at <= now]:
                del self._tickets[key]
            self._tickets[ticket] = (principal, expires)
        return ticket

    def redeem_ticket(self, ticket: str) -> Principal | None:
        """
        Use a WebSocket ticket once.

        Parameters
        ----------
        ticket : str

        Returns
        -------
        Principal or None
            The principal it was issued for; None when unknown, used, or expired.
        """
        with self._ticket_lock:
            found = self._tickets.pop(ticket, None)
        if found is None or found[1] <= self.now():
            return None
        return found[0]
```

Create `src/hypothex/auth/pairing.py`:

```python
"""Pairing links (secret in the ``#fragment``) and their QR code as plain text."""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

import segno

from hypothex.core.errors import ConfigError

_FRAGMENT = re.compile(r"^(p_[0-9a-f]{12})\.([A-Za-z0-9_-]{43})$")
_HALF = {(True, True): "█", (True, False): "▀", (False, True): "▄", (False, False): " "}


def pairing_url(base_url: str, offer_id: str, secret: str) -> str:
    """
    Build a pairing link; the secret stays in the fragment, which browsers never send.

    Parameters
    ----------
    base_url : str
        The hub's public URL (or its local URL).
    offer_id : str
        ``p_<12 hex>``.
    secret : str
        The offer's secret.

    Returns
    -------
    str
        ``<base_url>/pair#<offer_id>.<secret>``.

    Examples
    --------
    >>> pairing_url("http://127.0.0.1:7777/", "p_0123456789ab", "s")
    'http://127.0.0.1:7777/pair#p_0123456789ab.s'
    """
    return f"{base_url.rstrip('/')}/pair#{offer_id}.{secret}"


def parse_pairing_url(url: str) -> tuple[str, str, str]:
    """
    Split a pairing link into the hub URL, the offer id, and the secret.

    Parameters
    ----------
    url : str
        A link from ``hx pair``.

    Returns
    -------
    tuple of (str, str, str)
        ``(base_url, offer_id, secret)``.

    Raises
    ------
    ConfigError
        Not an ``http(s)://.../pair#p_<12 hex>.<43 chars>`` link.
    """
    bad = ConfigError("not a pairing link; copy the whole URL that hx pair printed")
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        raise bad from None
    match = _FRAGMENT.match(parts.fragment)
    if parts.scheme not in ("http", "https") or not parts.netloc or match is None:
        raise bad
    path = parts.path.rstrip("/")
    if not path.endswith("/pair"):
        raise bad
    base = urlunsplit((parts.scheme, parts.netloc, path[: -len("/pair")], "", ""))
    return base.rstrip("/"), match.group(1), match.group(2)


def qr_text(url: str) -> str:
    """
    Render a QR code of ``url`` with Unicode half blocks (no ANSI codes).

    Two module rows make one text line; a two-module quiet zone surrounds it.
    Dark modules are drawn, so it scans best on a light terminal background.

    Parameters
    ----------
    url : str
        Text to encode.

    Returns
    -------
    str
        Lines of equal width, joined with ``\\n``.
    """
    matrix = [[bool(cell) for cell in row] for row in segno.make_qr(url, error="m").matrix]
    size = len(matrix)
    border = 2
    width = size + 2 * border
    padded = [[False] * width for _ in range(border)]
    padded += [[False] * border + row + [False] * border for row in matrix]
    padded += [[False] * width for _ in range(border)]
    if len(padded) % 2:
        padded.append([False] * width)
    lines = []
    for top, bottom in zip(padded[0::2], padded[1::2], strict=True):
        lines.append("".join(_HALF[(a, b)] for a, b in zip(top, bottom, strict=True)))
    return "\n".join(lines)
```

Create `src/hypothex/auth/client.py`:

```python
"""The CLI's logins: ``<home>/auth/hub-tokens.json`` (0600), one entry per hub URL."""

from __future__ import annotations

import json

from pydantic import BaseModel, ValidationError

from hypothex.auth.scopes import Scope
from hypothex.core.layout import Layout
from hypothex.core.settings import write_private

HUB_TOKENS_FILE = "auth/hub-tokens.json"


class HubLogin(BaseModel):
    """A session this CLI holds on one hub (from ``hx login``)."""

    token: str
    user: str
    scope: Scope
    session_id: str


def hub_key(url: str) -> str:
    """
    Normalize a hub URL into the key of ``hub-tokens.json``.

    Parameters
    ----------
    url : str
        Hub base URL.

    Returns
    -------
    str
        The URL without trailing slashes.

    Examples
    --------
    >>> hub_key("https://hub.ts.net/")
    'https://hub.ts.net'
    """
    return url.strip().rstrip("/")


def load_hub_logins(layout: Layout) -> dict[str, HubLogin]:
    """
    Read every stored login.

    Parameters
    ----------
    layout : Layout
        The CLI's home.

    Returns
    -------
    dict of str to HubLogin
        Hub URL to login; ``{}`` when the file is missing or unreadable.
    """
    path = layout.home / HUB_TOKENS_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): HubLogin.model_validate(v) for k, v in raw.items()}
    except (OSError, ValueError, AttributeError, ValidationError):
        return {}


def hub_login(layout: Layout, url: str) -> HubLogin | None:
    """
    Return the login stored for one hub, or None.

    Parameters
    ----------
    layout : Layout
    url : str

    Returns
    -------
    HubLogin or None
    """
    return load_hub_logins(layout).get(hub_key(url))


def _write(layout: Layout, logins: dict[str, HubLogin]) -> None:
    data = {k: v.model_dump(mode="json") for k, v in sorted(logins.items())}
    write_private(layout.home / HUB_TOKENS_FILE, json.dumps(data, indent=2))


def save_hub_login(layout: Layout, url: str, login: HubLogin) -> None:
    """
    Store (or replace) the login for one hub.

    Parameters
    ----------
    layout : Layout
    url : str
    login : HubLogin
    """
    logins = load_hub_logins(layout)
    logins[hub_key(url)] = login
    _write(layout, logins)


def forget_hub_login(layout: Layout, url: str) -> HubLogin | None:
    """
    Remove the login of one hub.

    Parameters
    ----------
    layout : Layout
    url : str

    Returns
    -------
    HubLogin or None
        The removed login, or None when there was none.
    """
    logins = load_hub_logins(layout)
    gone = logins.pop(hub_key(url), None)
    if gone is not None:
        _write(layout, logins)
    return gone
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/auth -v`
Expected: `tests/auth/test_pairing.py` `10 passed`; the other auth files still pass.

Run: `uv run python -m doctest src/hypothex/auth/pairing.py src/hypothex/auth/client.py && uv run ruff check src/hypothex/auth tests/auth && uv run ruff format --check src/hypothex/auth tests/auth && uv run ty check src`
Expected: no doctest output, clean lint, format, and types.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/auth tests/auth/test_pairing.py
git commit -m "feat(auth): websocket tickets, pairing links with QR text, and CLI hub logins"
```

---
## Part 3: Notebook, paper baselines, and export

Contract 1.4, 1.5, 1.6. All three are hub-local reads and files; the routes come in Task 29, the CLI in Task 43, the MCP tools in Task 33.

### Task 8: Lab notebook (`hypothex.core.notebook`)

**Files:**
- Create: `src/hypothex/core/notebook.py`
- Test: `tests/core/test_notebook.py`

**Interfaces:**
- Consumes: `Context`, `group_label` (leaderboard), `parse_metric_key`, `atomic_write_bytes`, `RunStore.project_lock`, `EventLog.append`.
- Produces (contract 1.4, exact): `NOTEBOOK_DIR`, `DAY_PATTERN`, `RUN_LINK`, `NOTEBOOK_MAX_BYTES`, `RunChip`, `NotebookDay`, `NotebookConflictError` (with `.current`), `NotebookTooLargeError`, `notebook_dir`, `today`, `list_days`, `read_day`, `append_entry`, `write_day`, `run_links`.
- Produces (public helpers): `ENTRY_STAMP` (regex of `## <iso> — <author>`); `run_primary(ctx, record) -> float | None` (used by notices, Task 14); `day_path(layout, project, day) -> Path`; `hub_today(ctx, now=None) -> date` (`today(now, DigestSettings.timezone)` read from the hub's `config.yaml`, the machine's zone when unset or unreadable: the one "today" of contract 1.4 for `append_entry`, the routes' `today` day, MCP, and the CLI); `parse_day(text) -> date` (`ConfigError` for anything but `YYYY-MM-DD`); `parse_entries(text) -> list[tuple[datetime, str, str]]` (stamp, author, body; used by the digest, Task 18).
- Rules: unknown project → `StoreError`; both writes hold the project lock and emit `notebook.updated` `{project, day, author}` with `project=` set; an empty `write_day` text deletes the day file; `write_day` with a stale `base_hash` raises `NotebookConflictError` carrying the current day; a day file never grows past `NOTEBOOK_MAX_BYTES`. A chip of an unknown run id has `status=None` and `label=run_id`; a known run's label is its hypothesis clause (`group_label`), else its id; `primary` is its newest score of the task's primary metric at the current version.

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_notebook.py`:

```python
import os
import time
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from hypothex.core.context import Context
from hypothex.core.errors import ConfigError, StoreError
from hypothex.core.evaluation import evaluate_run
from hypothex.core.index import rebuild_index
from hypothex.core.notebook import (
    NOTEBOOK_MAX_BYTES,
    NotebookConflictError,
    NotebookTooLargeError,
    append_entry,
    day_path,
    hub_today,
    list_days,
    parse_day,
    parse_entries,
    read_day,
    run_links,
    today,
    write_day,
)
from hypothex.core.records import RunStatus
from hypothex.core.settings import settings_path
from tests.factories import PREDS_075, seed_finished_run

T = datetime(2026, 10, 4, 9, 14, tzinfo=UTC)
DAY = date(2026, 10, 4)


@pytest.fixture(autouse=True)
def utc_machine() -> Iterator[None]:
    """The default day is this machine's date: pin the machine to UTC."""
    old = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    time.tzset()
    yield
    if old is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = old
    time.tzset()


@pytest.fixture
def toy(ctx: Context, toy_repo: Path) -> Context:
    ctx.register_project(toy_repo)
    return ctx


def test_append_writes_a_stamped_entry(toy: Context) -> None:
    day = append_entry(toy, "toy", "  first [[run:r1]]  ", "human:alice", now=T)
    path = day_path(toy.layout, "toy", DAY)
    assert path.read_text() == "\n## 2026-10-04T09:14:00+00:00 — human:alice\n\nfirst [[run:r1]]\n"
    assert day.day == DAY and day.text == path.read_text()
    assert day.hash.startswith("sha256:") and len(day.hash) == 7 + 64
    assert day.updated_at is not None


def test_list_days_is_newest_first_with_counts(toy: Context) -> None:
    append_entry(toy, "toy", "a", "human:sv", day=date(2026, 10, 3), now=T)
    append_entry(toy, "toy", "b", "human:sv", now=T)
    append_entry(toy, "toy", "c", "human:alice", now=T)
    days = list_days(toy, "toy")
    assert [d["day"] for d in days] == ["2026-10-04", "2026-10-03"]
    assert [d["entries"] for d in days] == [2, 1] and days[0]["bytes"] > 0


def test_missing_day_is_empty(toy: Context) -> None:
    day = read_day(toy, "toy", DAY)
    assert (day.text, day.hash, day.runs, day.updated_at) == ("", "", [], None)


def test_a_day_cleared_while_it_is_read_reads_as_empty(
    toy: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    append_entry(toy, "toy", "soon gone", "human:sv", now=T)
    real_open = Path.open

    def unlinked(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self.suffix == ".md":  # an empty save removed the day after it was listed
            raise FileNotFoundError(str(self))
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", unlinked)
    day = read_day(toy, "toy", DAY)
    assert (day.text, day.hash, day.updated_at) == ("", "", None)
    assert list_days(toy, "toy") == []


def test_run_chips_show_status_and_primary(toy: Context, toy_repo: Path) -> None:
    seed_finished_run(toy, toy_repo, "r1", predictions=PREDS_075)
    evaluate_run(toy, "r1")
    day = append_entry(toy, "toy", "see [[run:r1]] and [[run:nope]] and [[run:r1]]", "x", now=T)
    known, unknown = day.runs
    assert (known.run_id, known.status, known.task, known.primary) == (
        "r1",
        RunStatus.FINISHED,
        "toy-acc",
        0.75,
    )
    assert known.label == "r1"
    assert (unknown.status, unknown.label, unknown.primary) == (None, "nope", None)


def test_run_links_are_unique_in_order() -> None:
    text = "[[run:b]] [[run:a]] [[run:b]] [[run:-bad]] [[run:c.1_x-2]]"
    assert run_links(text) == ["b", "a", "c.1_x-2"]


def test_write_day_needs_the_current_hash(toy: Context) -> None:
    first = append_entry(toy, "toy", "one", "human:sv", now=T)
    edited = write_day(toy, "toy", DAY, "# edited\n", base_hash=first.hash, author="human:sv")
    assert edited.text == "# edited\n" and edited.hash != first.hash
    append_entry(toy, "toy", "two", "human:alice", now=T)  # appends never conflict
    with pytest.raises(NotebookConflictError) as info:
        write_day(toy, "toy", DAY, "mine", base_hash=edited.hash, author="human:sv")
    assert "two" in info.value.current.text
    cleared = write_day(toy, "toy", DAY, "", base_hash=info.value.current.hash, author="human:sv")
    assert cleared.text == "" and not day_path(toy.layout, "toy", DAY).exists()


def test_day_files_have_a_size_limit(toy: Context) -> None:
    with pytest.raises(NotebookTooLargeError):
        append_entry(toy, "toy", "x" * NOTEBOOK_MAX_BYTES, "human:sv", now=T)
    with pytest.raises(NotebookTooLargeError):
        write_day(toy, "toy", DAY, "y" * (NOTEBOOK_MAX_BYTES + 1), base_hash="", author="a")


def test_unknown_project_and_empty_entry(toy: Context) -> None:
    with pytest.raises(StoreError):
        append_entry(toy, "nope", "x", "human:sv")
    with pytest.raises(StoreError):
        list_days(toy, "nope")
    with pytest.raises(ConfigError):
        append_entry(toy, "toy", "   ", "human:sv")


def test_writes_emit_notebook_updated(toy: Context) -> None:
    before = toy.events.last_sequence()
    append_entry(toy, "toy", "x", "human:alice", now=T)
    (event,) = toy.events.since(before)
    assert event.type == "notebook.updated" and event.project == "toy"
    assert event.payload == {"project": "toy", "day": "2026-10-04", "author": "human:alice"}


def test_today_follows_the_timezone() -> None:
    late = datetime(2026, 10, 4, 23, 30, tzinfo=UTC)
    assert today(late, "Asia/Tokyo") == date(2026, 10, 5)
    assert today(late, "UTC") == date(2026, 10, 4)


def test_hub_today_uses_the_configured_zone_for_appends(toy: Context) -> None:
    late = datetime(2026, 10, 4, 23, 30, tzinfo=UTC)
    settings_path(toy.layout).write_text("digest: {timezone: Asia/Tokyo}\n")
    assert hub_today(toy, late) == date(2026, 10, 5)
    assert append_entry(toy, "toy", "late", "human:sv", now=late).day == date(2026, 10, 5)
    settings_path(toy.layout).write_text("digest: [broken\n")
    assert hub_today(toy, late) == today(late)  # a bad config.yaml falls back to this machine


def test_parse_day_and_entries() -> None:
    assert parse_day("2026-10-04") == DAY
    for bad in ("2026-13-01", "04-10-2026", "../x"):
        with pytest.raises(ConfigError):
            parse_day(bad)
    text = "\n## 2026-10-04T09:14:00+00:00 — human:alice\n\nbody one\n\n## bad — x\n\nlost\n"
    ((stamp, author, body),) = parse_entries(text)
    assert (stamp, author, body) == (T, "human:alice", "body one")


def test_reindex_never_touches_the_notebook(toy: Context) -> None:
    append_entry(toy, "toy", "keep", "human:sv", now=T)
    rebuild_index(toy.index, toy.store)
    assert "keep" in read_day(toy, "toy", DAY).text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_notebook.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'hypothex.core.notebook'`.

- [ ] **Step 3: Write the implementation**

Create `src/hypothex/core/notebook.py`:

```python
"""Lab notebook: one Markdown file per project and day, with ``[[run:<id>]]`` chips.

Files live in ``<store>/<project>/notebook/YYYY-MM-DD.md`` on the hub. They are
files of record (``hx reindex`` never touches them) and are never mirrored to
hosts. Entries are ``## <iso time> — <author>`` sections, the format of run
``notes.md``.
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from hypothex.core.config import parse_metric_key
from hypothex.core.context import Context
from hypothex.core.errors import ConfigError, HypothexError, StoreError
from hypothex.core.fsutil import atomic_write_bytes
from hypothex.core.ids import utcnow
from hypothex.core.layout import Layout
from hypothex.core.leaderboard import group_label
from hypothex.core.records import RunRecord, RunStatus
from hypothex.core.settings import load_settings

NOTEBOOK_DIR = "notebook"
DAY_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
RUN_LINK = re.compile(r"\[\[run:([A-Za-z0-9][A-Za-z0-9_.-]{0,79})\]\]")
NOTEBOOK_MAX_BYTES = 1024 * 1024
ENTRY_STAMP = re.compile(r"^## (\S+) — (.+)$", re.MULTILINE)


class RunChip(BaseModel):
    """A ``[[run:<id>]]`` link resolved for display; ``status`` None = unknown run."""

    run_id: str
    status: RunStatus | None
    task: str | None
    label: str
    primary: float | None


class NotebookDay(BaseModel):
    """One day's notebook file; ``hash`` is ``sha256:<hex>`` of its bytes ("" when missing)."""

    project: str
    day: date
    text: str
    hash: str
    runs: list[RunChip]
    updated_at: datetime | None


class NotebookConflictError(HypothexError):
    """A whole-day save whose base hash is not the file's (someone else saved first)."""

    def __init__(self, message: str, current: NotebookDay) -> None:
        super().__init__(message)
        self.current = current


class NotebookTooLargeError(HypothexError):
    """A day file would grow past ``NOTEBOOK_MAX_BYTES``."""


def notebook_dir(layout: Layout, project: str) -> Path:
    """
    Return a project's notebook folder.

    Parameters
    ----------
    layout : Layout
    project : str

    Returns
    -------
    Path
        ``<store>/<project>/notebook``.
    """
    return layout.project_dir(project) / NOTEBOOK_DIR


def day_path(layout: Layout, project: str, day: date) -> Path:
    """
    Return the file of one notebook day.

    Parameters
    ----------
    layout : Layout
    project : str
    day : date

    Returns
    -------
    Path
        ``<store>/<project>/notebook/YYYY-MM-DD.md``.
    """
    return notebook_dir(layout, project) / f"{day.isoformat()}.md"


def parse_day(text: str) -> date:
    """
    Parse a ``YYYY-MM-DD`` day.

    Parameters
    ----------
    text : str

    Returns
    -------
    date

    Raises
    ------
    ConfigError
        Anything else (so a day can never name a path outside the folder).

    Examples
    --------
    >>> parse_day("2026-10-04")
    datetime.date(2026, 10, 4)
    """
    if not re.fullmatch(DAY_PATTERN, text):
        raise ConfigError(f"day must be YYYY-MM-DD, got {text!r}")
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ConfigError(f"day must be YYYY-MM-DD, got {text!r}") from None


def today(now: datetime | None = None, tz: str | None = None) -> date:
    """
    Return the hub-local date.

    Parameters
    ----------
    now : datetime, optional
        The moment (default now).
    tz : str, optional
        IANA zone (``DigestSettings.timezone``); None uses this machine's zone.

    Returns
    -------
    date
    """
    moment = now or utcnow()
    return (moment.astimezone(ZoneInfo(tz)) if tz else moment.astimezone()).date()


def hub_today(ctx: Context, now: datetime | None = None) -> date:
    """
    Return the hub's "today" for the notebook (contract 1.4).

    The UI, ``hx note``, MCP, and the digest all use this one date, so an entry
    written near midnight lands on the same day file whoever writes it.

    Parameters
    ----------
    ctx : Context
    now : datetime, optional
        The moment (default now).

    Returns
    -------
    date
        ``today(now, DigestSettings.timezone)``; this machine's zone when the
        timezone is unset or ``config.yaml`` cannot be read.
    """
    try:
        tz = load_settings(ctx.layout).digest.timezone
    except ConfigError:
        tz = None
    return today(now, tz)


def _hash(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest() if data else ""


def _require_project(ctx: Context, project: str) -> None:
    ctx.store.load_project(project)  # StoreError (404) for an unknown project


def run_links(text: str) -> list[str]:
    """
    Return the run ids linked as ``[[run:<id>]]``, unique, in order of first use.

    Parameters
    ----------
    text : str

    Returns
    -------
    list of str

    Examples
    --------
    >>> run_links("[[run:a]] [[run:b]] [[run:a]]")
    ['a', 'b']
    """
    return list(dict.fromkeys(RUN_LINK.findall(text)))


def parse_entries(text: str) -> list[tuple[datetime, str, str]]:
    """
    Split a notebook or ``notes.md`` text into its stamped entries.

    Parameters
    ----------
    text : str

    Returns
    -------
    list of (datetime, str, str)
        ``(stamp, author, body)`` in file order; sections whose stamp is not
        an ISO time with a zone are skipped.
    """
    matches = list(ENTRY_STAMP.finditer(text))
    out: list[tuple[datetime, str, str]] = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        try:
            stamp = datetime.fromisoformat(match.group(1))
        except ValueError:
            continue
        if stamp.tzinfo is None:
            continue
        out.append((stamp, match.group(2).strip(), text[match.end() : end].strip()))
    return out


def run_primary(ctx: Context, record: RunRecord) -> float | None:
    """
    Return a run's newest valid score of its task's primary metric at the current version.

    Parameters
    ----------
    ctx : Context
    record : RunRecord

    Returns
    -------
    float or None
        None for a run without a task, an unknown project or task, or no such score.
    """
    if record.task is None:
        return None
    try:
        config = ctx.store.load_project(record.project).config
    except StoreError:
        return None
    spec = config.tasks.get(record.task)
    if spec is None:
        return None
    metric, key = parse_metric_key(spec.primary)
    current = config.metrics.get(metric)
    if current is None:
        return None
    value: float | None = None
    scores = ctx.index.scores_for([record.run_id]).get(record.run_id, [])
    for score in sorted(scores, key=lambda s: s.created_at):
        if (
            score.metric == metric
            and score.key == key
            and score.version == current.version
            and score.error is None
            and score.value is not None
        ):
            value = score.value
    return value


def _chips(ctx: Context, run_ids: list[str]) -> list[RunChip]:
    chips: list[RunChip] = []
    for run_id in run_ids:
        record = ctx.index.get_run(run_id)
        if record is None:
            chips.append(RunChip(run_id=run_id, status=None, task=None, label=run_id, primary=None))
            continue
        label = group_label(record.hypothesis, record.tags, run_id).removeprefix("group ")
        chips.append(
            RunChip(
                run_id=run_id,
                status=record.status,
                task=record.task,
                label=label,
                primary=run_primary(ctx, record),
            )
        )
    return chips


def list_days(ctx: Context, project: str) -> list[dict[str, Any]]:
    """
    List a project's notebook days, newest first.

    Parameters
    ----------
    ctx : Context
    project : str

    Returns
    -------
    list of dict
        ``{day, bytes, entries}`` per day file.

    Raises
    ------
    StoreError
        Unknown project.
    """
    _require_project(ctx, project)
    folder = notebook_dir(ctx.layout, project)
    if not folder.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.md"), reverse=True):
        if not re.fullmatch(DAY_PATTERN, path.stem):
            continue
        try:
            with path.open("rb") as fh:
                data = fh.read()  # one read: bytes and entries of the same text
        except FileNotFoundError:
            continue  # an empty save removed the day after the listing
        text = data.decode("utf-8", errors="replace")
        out.append(
            {"day": path.stem, "bytes": len(data), "entries": len(ENTRY_STAMP.findall(text))}
        )
    return out


def read_day(ctx: Context, project: str, day: date) -> NotebookDay:
    """
    Read one notebook day with its run chips.

    Parameters
    ----------
    ctx : Context
    project : str
    day : date

    Returns
    -------
    NotebookDay
        Empty text and hash when the day has no file.

    Raises
    ------
    StoreError
        Unknown project.
    """
    _require_project(ctx, project)
    path = day_path(ctx.layout, project, day)
    # one open: the text, its hash, and its time come from the same file, and a day that
    # an empty save removes meanwhile reads as missing instead of failing
    updated: datetime | None = None
    try:
        with path.open("rb") as fh:
            data = fh.read()
            updated = datetime.fromtimestamp(os.fstat(fh.fileno()).st_mtime, UTC)
    except FileNotFoundError:
        data = b""
    text = data.decode("utf-8", errors="replace")
    return NotebookDay(
        project=project,
        day=day,
        text=text,
        hash=_hash(data),
        runs=_chips(ctx, run_links(text)),
        updated_at=updated,
    )


def _emit(ctx: Context, project: str, day: date, author: str) -> None:
    payload = {"project": project, "day": day.isoformat(), "author": author}
    ctx.events.append("notebook.updated", project=project, payload=payload)


def append_entry(
    ctx: Context,
    project: str,
    text: str,
    author: str,
    *,
    day: date | None = None,
    now: datetime | None = None,
) -> NotebookDay:
    """
    Append a stamped entry to a notebook day (never conflicts).

    Parameters
    ----------
    ctx : Context
    project : str
    text : str
        Markdown body; leading and trailing blank space is dropped.
    author : str
        ``human:<user>``, ``agent:<agent>@<user>``, ``digest``, ...
    day : date, optional
        Default: ``hub_today(ctx, now)``.
    now : datetime, optional
        Entry time (default now).

    Returns
    -------
    NotebookDay
        The day after the append.

    Raises
    ------
    StoreError
        Unknown project.
    ConfigError
        Empty text.
    NotebookTooLargeError
        The day would exceed ``NOTEBOOK_MAX_BYTES``.
    """
    _require_project(ctx, project)
    body = text.strip()
    if not body:
        raise ConfigError("empty notebook entry")
    moment = now or utcnow()
    when = day or hub_today(ctx, moment)
    entry = f"\n## {moment.isoformat()} — {author}\n\n{body}\n".encode()
    path = day_path(ctx.layout, project, when)
    with ctx.store.project_lock(project):
        size = path.stat().st_size if path.is_file() else 0
        if size + len(entry) > NOTEBOOK_MAX_BYTES:
            raise NotebookTooLargeError(
                f"notebook day {when} would exceed {NOTEBOOK_MAX_BYTES} bytes"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("ab") as fh:
            fh.write(entry)
    _emit(ctx, project, when, author)
    return read_day(ctx, project, when)


def write_day(
    ctx: Context, project: str, day: date, text: str, *, base_hash: str, author: str
) -> NotebookDay:
    """
    Replace a whole notebook day, if nobody saved it since ``base_hash``.

    Parameters
    ----------
    ctx : Context
    project : str
    day : date
    text : str
        New content; an empty text deletes the day file.
    base_hash : str
        ``NotebookDay.hash`` the editor started from ("" for a new day).
    author : str
        Who saved (for the event).

    Returns
    -------
    NotebookDay
        The saved day.

    Raises
    ------
    StoreError
        Unknown project.
    NotebookConflictError
        The file's hash is not ``base_hash``; ``.current`` holds the day as it is.
    NotebookTooLargeError
        ``text`` is larger than ``NOTEBOOK_MAX_BYTES``.
    """
    _require_project(ctx, project)
    data = text.encode("utf-8")
    if data and not data.endswith(b"\n"):
        data += b"\n"
    if len(data) > NOTEBOOK_MAX_BYTES:
        raise NotebookTooLargeError(f"notebook day {day} is over {NOTEBOOK_MAX_BYTES} bytes")
    path = day_path(ctx.layout, project, day)
    with ctx.store.project_lock(project):
        current = path.read_bytes() if path.is_file() else b""
        if _hash(current) != base_hash:
            raise NotebookConflictError(
                f"notebook day {day} changed since you opened it",
                current=read_day(ctx, project, day),
            )
        if data.strip():
            atomic_write_bytes(path, data)
        else:
            path.unlink(missing_ok=True)
    _emit(ctx, project, day, author)
    return read_day(ctx, project, day)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_notebook.py -v`
Expected: `14 passed`.

Run: `uv run python -m doctest src/hypothex/core/notebook.py && uv run ruff check src/hypothex/core/notebook.py tests/core/test_notebook.py && uv run ruff format --check src/hypothex/core/notebook.py tests/core/test_notebook.py && uv run ty check src`
Expected: no doctest output, `All checks passed!`, `2 files already formatted`, `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/notebook.py tests/core/test_notebook.py
git commit -m "feat(notebook): per-day project notebook with run chips and conflict-safe saves"
```

---

### Task 9: Paper baselines on tasks and leaderboards

**Files:**
- Modify: `src/hypothex/core/config.py` (`BASELINE_SOURCE`, `BaselineSpec`, `TaskSpec.baselines`, checks in `_check_references`)
- Modify: `src/hypothex/core/leaderboard.py` (`BaselineRow`, `Leaderboard.baselines`, `baseline_url`, `baseline_rows`; `build_leaderboard` fills them)
- Test: `tests/core/test_baselines.py`

**Interfaces:**
- Produces (contract 1.5, exact): `BASELINE_SOURCE`, `BaselineSpec` (`name`, `values`, `std`, `source`, `metric_version_equivalent: dict[str, str] | str`, `note`), `TaskSpec.baselines`, `BaselineRow`, `Leaderboard.baselines`, `baseline_url`.
- Produces (public helpers): `metric_ref(ref) -> str` (`acc` → `acc/value`, in `hypothex.core.config`); `BaselineSpec.equivalent_version(metric) -> str | None`; `baseline_rows(spec: TaskSpec, board: Leaderboard) -> list[BaselineRow]` (keys normalized to `metric/key`; `version_match` for every metric of the task; `delta_vs_best = best − value` when higher is better, `value − best` otherwise, so positive means the best group beats the paper).
- Baselines never count as seed groups, never become best, and never enter `vs_best`.

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_baselines.py`:

```python
import math
from datetime import timedelta
from typing import Any

import pytest

from hypothex.core.config import BaselineSpec, ProjectConfig
from hypothex.core.ids import utcnow
from hypothex.core.leaderboard import baseline_url, build_leaderboard
from hypothex.core.records import GitInfo, RunRecord, RunStatus, ScoreRecord
from tests.factories import make_record

T0 = utcnow()


def config(baselines: list[dict[str, Any]], primary: str = "acc") -> ProjectConfig:
    return ProjectConfig.model_validate(
        {
            "project": "toy",
            "datasets": {"d": {"version": "v1", "path": "x"}},
            "metrics": {
                "acc": {"version": "v2", "fn": "m:acc"},
                "loss": {"version": "v1", "fn": "m:loss", "higher_is_better": False},
            },
            "tasks": {
                "t": {
                    "dataset": "d",
                    "metrics": ["acc", "loss"],
                    "primary": primary,
                    "baselines": baselines,
                }
            },
        }
    )


HE = {
    "name": "He 2016",
    "values": {"acc": 0.9, "loss/value": 1.2},
    "std": {"acc": 0.01},
    "source": "arXiv:1512.03385",
    "metric_version_equivalent": {"acc": "v2"},
}
LEE = {
    "name": "Lee",
    "values": {"acc": 0.95},
    "source": "doi:10.1000/xyz",
    "metric_version_equivalent": "v1",
}


def runs_and_scores(
    metric: str, groups: dict[str, list[float]]
) -> tuple[list[RunRecord], dict[str, list[ScoreRecord]]]:
    runs: list[RunRecord] = []
    scores: dict[str, list[ScoreRecord]] = {}
    for group, values in groups.items():
        for i, value in enumerate(values):
            rid = f"{group}{i}"
            runs.append(
                make_record(
                    rid,
                    status=RunStatus.FINISHED,
                    config_hash=f"sha256:{group}",
                    git=GitInfo(commit="c1"),
                    created_at=T0 + timedelta(minutes=i),
                )
            )
            version = "v2" if metric == "acc" else "v1"
            score = ScoreRecord(
                metric=metric, version=version, key="value", value=value, created_at=T0
            )
            scores[rid] = [score]
    return runs, scores


def test_valid_baselines_parse() -> None:
    task = config([HE, LEE]).tasks["t"]
    assert [b.name for b in task.baselines] == ["He 2016", "Lee"]
    assert task.baselines[0].equivalent_version("acc") == "v2"
    assert task.baselines[0].equivalent_version("loss") is None
    assert task.baselines[1].equivalent_version("loss") == "v1"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"values": {"f1": 0.5}}, "unknown metric 'f1'"),
        ({"std": {"loss/p90": 0.1}}, "std without a value: loss/p90"),
        ({"metric_version_equivalent": {"f1": "v1"}}, "metric_version_equivalent names 'f1'"),
        ({"values": {"acc": math.nan}}, "finite number"),
        ({"source": "my paper"}, "should match pattern"),
    ],
)
def test_bad_baselines_are_refused(change: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        config([{**HE, **change}])


def test_duplicate_names_are_refused() -> None:
    with pytest.raises(ValueError, match="baseline name 'He 2016' is repeated"):
        config([HE, HE])


def test_baseline_url() -> None:
    assert baseline_url("arXiv:1512.03385") == "https://arxiv.org/abs/1512.03385"
    assert baseline_url("doi:10.1000/xyz") == "https://doi.org/10.1000/xyz"
    assert baseline_url("https://example.org/p") == "https://example.org/p"
    assert BaselineSpec.model_validate(HE).source == "arXiv:1512.03385"


def test_leaderboard_lists_baselines_after_the_groups() -> None:
    runs, scores = runs_and_scores("acc", {"a": [0.92, 0.93], "b": [0.85]})
    board = build_leaderboard("toy", "t", config([HE, LEE]), runs, scores)
    assert [r.group_id[:1] for r in board.rows] == ["a", "b"]
    he, lee = board.baselines
    assert he.values == {"acc/value": 0.9, "loss/value": 1.2} and he.std == {"acc/value": 0.01}
    assert he.source_url == "https://arxiv.org/abs/1512.03385"
    assert he.version_match == {"acc": True, "loss": False}
    assert lee.version_match == {"acc": False, "loss": True}
    assert he.primary == 0.9 and he.delta_vs_best == pytest.approx(0.025)
    assert lee.delta_vs_best == pytest.approx(-0.025)
    assert all(r.vs_best is None or r.vs_best.delta <= 0 for r in board.rows)


def test_lower_is_better_delta_is_positive_when_we_win() -> None:
    runs, scores = runs_and_scores("loss", {"a": [1.0]})
    board = build_leaderboard("toy", "t", config([HE], primary="loss"), runs, scores)
    assert board.baselines[0].delta_vs_best == pytest.approx(0.2)


def test_empty_board_has_baselines_without_delta() -> None:
    board = build_leaderboard("toy", "t", config([HE]), [], {})
    assert board.rows == [] and board.baselines[0].delta_vs_best is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_baselines.py -v`
Expected: FAIL at collection with `ImportError: cannot import name 'BaselineSpec' from 'hypothex.core.config'`.

- [ ] **Step 3: Write the implementation**

In `src/hypothex/core/config.py`, change `from typing import Any, Literal, NamedTuple` to `from typing import Annotated, Any, Literal, NamedTuple`, add after `_FIELD = ...`:

```python
BASELINE_SOURCE = r"^(arXiv:\d{4}\.\d{4,5}(v\d+)?|doi:10\.\d{4,9}/\S+|https://\S+)$"
FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
```

add after `parse_metric_key`:

```python
def metric_ref(ref: str) -> str:
    """
    Normalize a metric reference to ``metric/key``.

    Parameters
    ----------
    ref : str
        ``metric`` or ``metric/key``.

    Returns
    -------
    str

    Examples
    --------
    >>> metric_ref("acc"), metric_ref("topk/k=1")
    ('acc/value', 'topk/k=1')
    """
    name, key = parse_metric_key(ref)
    return f"{name}/{key}"
```

add above `class TaskSpec`:

```python
class BaselineSpec(_Strict):
    """
    A published result shown next to a task's leaderboard; never ranked.

    ``values`` and ``std`` are keyed by metric reference (``metric`` or
    ``metric/key``). ``metric_version_equivalent`` says which of our metric
    versions the paper's number matches: per metric, or one string for every
    metric of the task.

    Examples
    --------
    >>> spec = BaselineSpec(name="He 2016", values={"acc": 0.9}, source="arXiv:1512.03385")
    >>> spec.equivalent_version("acc") is None
    True
    """

    name: str = Field(min_length=1, max_length=64)
    values: dict[str, FiniteFloat] = Field(min_length=1)
    std: dict[str, FiniteFloat] = Field(default_factory=dict)
    source: str = Field(pattern=BASELINE_SOURCE)
    metric_version_equivalent: dict[str, str] | str = Field(default_factory=dict)
    note: str = Field("", max_length=200)

    def equivalent_version(self, metric: str) -> str | None:
        """
        Return our version of ``metric`` that the paper's number matches.

        Parameters
        ----------
        metric : str
            Metric name.

        Returns
        -------
        str or None
            The version, or None when the baseline does not say.
        """
        mve = self.metric_version_equivalent
        return mve if isinstance(mve, str) else mve.get(metric)
```

in `TaskSpec`, after `version_param: ...` add:

```python
    baselines: list[BaselineSpec] = Field(default_factory=list)
```

and extend the `TaskSpec` docstring with "``baselines`` lists published results (``BaselineSpec``) shown under the leaderboard." In `ProjectConfig._check_references`, inside the `for name, task in self.tasks.items():` loop, after the view checks, add:

```python
            seen: set[str] = set()
            for base in task.baselines:
                if base.name in seen:
                    errors.append(f"task {name!r}: baseline name {base.name!r} is repeated")
                seen.add(base.name)
                for key in sorted({*base.values, *base.std}):
                    if parse_metric_key(key)[0] not in task.metrics:
                        errors.append(
                            f"task {name!r}: baseline {base.name!r}: unknown metric {key!r}"
                        )
                std_refs = {metric_ref(k) for k in base.std}
                extra = sorted(std_refs - {metric_ref(k) for k in base.values})
                if extra:
                    errors.append(
                        f"task {name!r}: baseline {base.name!r}: std without a value: "
                        f"{', '.join(extra)}"
                    )
                if isinstance(base.metric_version_equivalent, dict):
                    errors.extend(
                        f"task {name!r}: baseline {base.name!r}: metric_version_equivalent "
                        f"names {m!r}, not a metric of the task"
                        for m in base.metric_version_equivalent
                        if m not in task.metrics
                    )
```

In `src/hypothex/core/leaderboard.py`, change `from pydantic import BaseModel` to `from pydantic import BaseModel, Field`, add `metric_ref` to the `hypothex.core.config` import, and add after `class LeaderboardRow`:

```python
class BaselineRow(BaseModel):
    """A paper's result as shown under a leaderboard (never a seed group, never best)."""

    name: str
    values: dict[str, float]
    std: dict[str, float]
    source: str
    source_url: str
    version_match: dict[str, bool]
    """Metric name -> the paper's version equals the leaderboard's (missing -> False)."""
    primary: float | None
    delta_vs_best: float | None
    """Best group's primary mean minus this value (higher is better), or the reverse."""
```

in `class Leaderboard`, after `value_format: ...` and its docstring, add:

```python
    baselines: list[BaselineRow] = Field(default_factory=list)
    """Published results from ``hypothex.yaml`` (``TaskSpec.baselines``)."""
```

add above `def build_leaderboard`:

```python
def baseline_url(source: str) -> str:
    """
    Turn a baseline source into a link.

    Parameters
    ----------
    source : str
        ``arXiv:<id>``, ``doi:<doi>``, or an ``https://`` URL.

    Returns
    -------
    str
        ``https://arxiv.org/abs/<id>``, ``https://doi.org/<doi>``, or the URL.

    Examples
    --------
    >>> baseline_url("arXiv:1512.03385")
    'https://arxiv.org/abs/1512.03385'
    """
    if source.startswith("arXiv:"):
        return "https://arxiv.org/abs/" + source.removeprefix("arXiv:")
    if source.startswith("doi:"):
        return "https://doi.org/" + source.removeprefix("doi:")
    return source


def baseline_rows(spec: TaskSpec, board: Leaderboard) -> list[BaselineRow]:
    """
    Build the baseline rows of a leaderboard.

    Parameters
    ----------
    spec : TaskSpec
        The task (its ``baselines`` and ``metrics``).
    board : Leaderboard
        The built leaderboard (ranked rows and metric versions).

    Returns
    -------
    list of BaselineRow
        One per baseline, in file order, keys as ``metric/key``.
    """
    top = board.rows[0].primary if board.rows else None
    best = top.mean if top is not None else None
    out: list[BaselineRow] = []
    for base in spec.baselines:
        values = {metric_ref(k): v for k, v in base.values.items()}
        primary = values.get(board.primary)
        delta = None
        if primary is not None and best is not None:
            delta = best - primary if board.higher_is_better else primary - best
        out.append(
            BaselineRow(
                name=base.name,
                values=values,
                std={metric_ref(k): v for k, v in base.std.items()},
                source=base.source,
                source_url=baseline_url(base.source),
                version_match={
                    m: base.equivalent_version(m) == board.metric_versions.get(m)
                    for m in spec.metrics
                },
                primary=primary,
                delta_vs_best=delta,
            )
        )
    return out
```

and at the end of `build_leaderboard`, before `return board`, add:

```python
    board.baselines = baseline_rows(spec, board)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_baselines.py tests/core/test_leaderboard.py tests/core/test_config.py -v`
Expected: `tests/core/test_baselines.py` `11 passed`; the phase 1 leaderboard and config tests still pass.

Run: `uv run python -m doctest src/hypothex/core/config.py src/hypothex/core/leaderboard.py && uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check src`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/config.py src/hypothex/core/leaderboard.py tests/core/test_baselines.py
git commit -m "feat(leaderboard): paper baselines per task with version match and delta to best"
```

---
### Task 10: Export tables from a leaderboard (`hypothex.core.export`, part 1)

**Files:**
- Create: `src/hypothex/core/export.py`
- Test: `tests/core/test_export.py`

**Interfaces:**
- Consumes: `Leaderboard`, `LeaderboardRow`, `BaselineRow`, `NoiseInterval` (Task 9 / phase 1b), `metric_ref`, `parse_metric_key`, `Stats`.
- Produces (contract 1.6, exact): `ExportFormat`, `NoiseMode`, `ExportOptions`, `ExportCell`, `ExportRow`, `ExportTable`, `leaderboard_table(board, opts)`.
- Produces (additive keyword): `leaderboard_table(board, opts, *, directions: dict[str, bool] | None = None, value_formats: dict[str, str] | None = None)` — metric name → higher is better for columns other than the primary (a `Leaderboard` knows only the primary's direction; `export_task` passes the project's metrics, Task 12). Default `True`.
- Produces (public helpers): `EXTENSIONS = {"latex": "tex", "markdown": "md", "csv": "csv"}`, `MARK_SINGLE = "¹"`, `MARK_NOISE = "†"`, `MARK_VERSION = "‡"`, `IDENTICAL = "◇"`; `mark_best(rows, higher_is_better) -> None`; `footnotes(versions, rows, opts, *, scaled, extra=None) -> list[str]` (shared by `compare_table`, Task 12).
- Rules: columns are `opts.metrics` (normalized `metric/key`) or the primary, then every other key a group has, sorted. Group cells take `Stats` of the row; `std` only when `noise` is `both`/`seed` and `n > 1`; `identical` when `noise` is `both`/`seed` and every seed value of that column is equal (`n > 1`); `lo`/`hi`/`method`/`n_examples` only on the primary column, from `row.test_interval`, when `noise` is `both`/`test`. `best` marks the best group mean per column (ties all). `percent=True` scales each column independently where its format is `fraction`, including mean, std, interval, and baseline cells; Task 12 derives formats from each metric unit and values. Unspecified secondary formats default to `number`. The footnote names the scaled columns (`values ×100: acc/value`). Baseline rows (`kind="baseline"`, `n=0`) come after the groups, never best; `version_mismatch` when a shown metric's `version_match` is false. Footnotes, in order: `metric versions: m@v, ...` (shown metrics), the legend of the marks present (`¹ single seed`, `◇×n identical seeds`, `† within noise of best` when `mark_noise`, `‡ metric version differs from the paper`) joined with ` · `, `[lo, hi] 95% test-set interval (<methods>)`, `values ×100: <columns>`, `baselines: <name> — <source>; ...`.

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_export.py`:

```python
import pytest

from hypothex.core.export import ExportOptions, leaderboard_table
from hypothex.core.leaderboard import BaselineRow, Leaderboard, LeaderboardRow, NoiseInterval
from hypothex.core.seeds import Stats


def group(
    gid: str,
    label: str,
    acc: list[float],
    acc_stats: Stats,
    f1: list[float],
    f1_stats: Stats,
    lo: float,
    hi: float,
    within: bool | None,
) -> LeaderboardRow:
    return LeaderboardRow(
        group_id=gid,
        run_ids=[f"{label}-{i}" for i in range(len(acc))],
        latest_run_id=f"{label}-0",
        hypothesis=label,
        commit="c1",
        config_hash=f"sha256:{gid}",
        n=len(acc),
        scores={"acc/value": acc_stats, "f1/value": f1_stats},
        primary=acc_stats,
        single_seed=len(acc) == 1,
        within_noise_of_best=within,
        label=label,
        seed_values={"acc/value": acc, "f1/value": f1},
        identical_seeds=len(acc) > 1 and len(set(acc)) == 1,
        test_interval=NoiseInterval(lo=lo, hi=hi, method="wilson", n=200),
        vs_best=None,
        created_by=["human"],
        usage=None,
    )


def make_board(*, baselines: bool = True) -> Leaderboard:
    rows = [
        group(
            "aaaa0001@c1", "svm", [0.91, 0.92, 0.93], Stats(mean=0.92, std=0.01, n=3),
            [0.88, 0.89, 0.90], Stats(mean=0.89, std=0.01, n=3), 0.871, 0.954, None,
        ),
        group(
            "aaaa0002@c1", "rf", [0.905, 0.91, 0.915], Stats(mean=0.91, std=0.005, n=3),
            [0.9, 0.91, 0.92], Stats(mean=0.91, std=0.01, n=3), 0.862, 0.947, True,
        ),
        group(
            "aaaa0003@c1", "logreg", [0.88, 0.88, 0.88], Stats(mean=0.88, std=0.0, n=3),
            [0.85, 0.86, 0.87], Stats(mean=0.86, std=0.01, n=3), 0.826, 0.925, False,
        ),
        group(
            "aaaa0004@c1", "knn", [0.85], Stats(mean=0.85, std=0.0, n=1),
            [0.8], Stats(mean=0.8, std=0.0, n=1), 0.794, 0.894, None,
        ),
    ]  # fmt: skip
    board = Leaderboard(
        project="toy",
        task="t",
        primary="acc/value",
        higher_is_better=True,
        metric_versions={"acc": "v2", "f1": "v1"},
        rows=rows,
        needs_reeval=[],
        unscored=[],
        headline="",
        kind="generic",
        stat_strip=[],
        value_format="fraction",
    )
    if baselines:
        board.baselines = [
            BaselineRow(
                name="Smith_2024 & co",
                values={"acc/value": 0.9, "f1/value": 0.87},
                std={"acc/value": 0.004},
                source="arXiv:2401.01234",
                source_url="https://arxiv.org/abs/2401.01234",
                version_match={"acc": True, "f1": True},
                primary=0.9,
                delta_vs_best=0.02,
            ),
            BaselineRow(
                name="Lee 2023",
                values={"acc/value": 0.93},
                std={},
                source="doi:10.1000/xyz123",
                source_url="https://doi.org/10.1000/xyz123",
                version_match={"acc": False, "f1": False},
                primary=0.93,
                delta_vs_best=-0.01,
            ),
        ]
    return board


def test_columns_rows_and_marks() -> None:
    table = leaderboard_table(make_board(), ExportOptions())
    assert table.title == "toy/t" and table.columns == ["acc/value", "f1/value"]
    assert table.higher_is_better == {"acc/value": True, "f1/value": True}
    assert [(r.kind, r.label) for r in table.rows] == [
        ("group", "svm"),
        ("group", "rf"),
        ("group", "logreg"),
        ("group", "knn"),
        ("baseline", "Smith_2024 & co"),
        ("baseline", "Lee 2023"),
    ]
    svm, rf, logreg, knn, smith, lee = table.rows
    assert svm.cells["acc/value"].best and not svm.cells["f1/value"].best
    assert rf.cells["f1/value"].best and rf.within_noise and not svm.within_noise
    assert logreg.cells["acc/value"].identical and not logreg.cells["f1/value"].identical
    assert knn.cells["acc/value"].std is None and knn.n == 1
    cell = svm.cells["acc/value"]
    assert (cell.lo, cell.hi, cell.method, cell.n_examples) == (0.871, 0.954, "wilson", 200)
    assert svm.cells["f1/value"].lo is None  # test-set CI only on the primary
    assert not smith.version_mismatch and lee.version_mismatch
    assert lee.cells["f1/value"].mean is None and not lee.cells["acc/value"].best
    assert smith.cells["acc/value"].std == 0.004 and smith.source == "arXiv:2401.01234"


def test_footnotes() -> None:
    assert leaderboard_table(make_board(), ExportOptions()).footnotes == [
        "metric versions: acc@v2, f1@v1",
        "¹ single seed · ◇×n identical seeds · † within noise of best · "
        "‡ metric version differs from the paper",
        "[lo, hi] 95% test-set interval (wilson)",
        "baselines: Smith_2024 & co — arXiv:2401.01234; Lee 2023 — doi:10.1000/xyz123",
    ]


@pytest.mark.parametrize(
    ("noise", "std", "ci", "identical"),
    [("both", True, True, True), ("seed", True, False, True), ("test", False, True, False),
     ("none", False, False, False)],
)  # fmt: skip
def test_noise_modes(noise: str, std: bool, ci: bool, identical: bool) -> None:
    table = leaderboard_table(make_board(), ExportOptions(noise=noise))  # type: ignore[arg-type]
    svm, _, logreg = table.rows[:3]
    assert (svm.cells["acc/value"].std is not None) is std
    assert (svm.cells["acc/value"].lo is not None) is ci
    assert logreg.cells["acc/value"].identical is identical


def test_metrics_top_groups_and_directions() -> None:
    board = make_board(baselines=False)
    table = leaderboard_table(board, ExportOptions(metrics=["f1"], top=2), directions={"f1": False})
    assert table.columns == ["f1/value"] and [r.label for r in table.rows] == ["svm", "rf"]
    assert table.higher_is_better == {"f1/value": False}
    assert table.rows[0].cells["f1/value"].best  # lower f1 wins when told so
    picked = leaderboard_table(board, ExportOptions(groups=["knn", "aaaa0003@c1"]))
    assert [r.label for r in picked.rows] == ["logreg", "knn"]


def test_percent_scales_fraction_boards() -> None:
    table = leaderboard_table(make_board(), ExportOptions(percent=True))
    cell = table.rows[0].cells["acc/value"]
    assert cell.mean == pytest.approx(92.0) and cell.std == pytest.approx(1.0)
    assert cell.lo == pytest.approx(87.1) and "values ×100: acc/value" in table.footnotes
    board = make_board()
    board.value_format = "number"
    plain = leaderboard_table(board, ExportOptions(percent=True))
    assert plain.rows[0].cells["acc/value"].mean == 0.92


@pytest.mark.parametrize("primary", ["acc/value", "latency/p95"])
def test_percent_scales_only_fraction_columns_in_groups_and_baselines(primary: str) -> None:
    board = make_board()
    for row in board.rows:
        row.scores["latency/p95"] = Stats(n=2, mean=440.0, std=10.0)
        row.seed_values["latency/p95"] = [430.0, 450.0]
    board.baselines[0].values["latency/p95"] = 400.0
    board.baselines[0].std["latency/p95"] = 5.0
    board.primary = primary
    board.value_format = "fraction" if primary == "acc/value" else "number"
    board.higher_is_better = primary == "acc/value"
    table = leaderboard_table(
        board,
        ExportOptions(percent=True, metrics=["acc/value", "latency/p95"]),
        directions={"acc/value": True, "latency/p95": False},
        value_formats={"acc/value": "fraction", "latency/p95": "number"},
    )
    assert table.rows[0].cells["acc/value"].mean == pytest.approx(92.0)
    assert table.rows[0].cells["acc/value"].std == pytest.approx(1.0)
    assert table.rows[0].cells["latency/p95"].mean == 440.0
    assert table.rows[0].cells["latency/p95"].std == 10.0
    baseline = next(row for row in table.rows if row.kind == "baseline")
    assert baseline.cells["acc/value"].mean == pytest.approx(90.0)
    assert baseline.cells["acc/value"].std == pytest.approx(0.4)
    assert baseline.cells["latency/p95"].mean == 400.0
    assert baseline.cells["latency/p95"].std == 5.0
    assert "values ×100: acc/value" in table.footnotes


def test_no_baselines_option_and_empty_board() -> None:
    groups_only = leaderboard_table(make_board(), ExportOptions(baselines=False))
    assert all(r.kind == "group" for r in groups_only.rows)
    empty = make_board(baselines=False)
    empty.rows = []
    table = leaderboard_table(empty, ExportOptions())
    assert table.columns == ["acc/value"] and table.rows == []
    assert table.footnotes == ["metric versions: acc@v2"]


def test_options_are_strict() -> None:
    with pytest.raises(ValueError):
        ExportOptions(format="html")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ExportOptions(digits=9)
    assert ExportOptions().model_dump()["noise"] == "both"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_export.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'hypothex.core.export'`.

- [ ] **Step 3: Write the implementation**

Create `src/hypothex/core/export.py`:

```python
"""Paper tables from leaderboards and comparisons: LaTeX (booktabs), Markdown, CSV.

``leaderboard_table`` and ``compare_table`` build an ``ExportTable`` (numbers,
marks, footnotes); ``render`` turns it into text. Output is deterministic: the
same table and options give byte-identical text (golden files in
``tests/core/golden/export``).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from hypothex.core.config import metric_ref, parse_metric_key
from hypothex.core.leaderboard import BaselineRow, Leaderboard, LeaderboardRow

ExportFormat = Literal["latex", "markdown", "csv"]
NoiseMode = Literal["both", "seed", "test", "none"]
EXTENSIONS: dict[str, str] = {"latex": "tex", "markdown": "md", "csv": "csv"}
MARK_SINGLE = "¹"
MARK_NOISE = "†"
MARK_VERSION = "‡"
IDENTICAL = "◇"


class ExportOptions(BaseModel, extra="forbid"):
    """What to export and how to show noise."""

    format: ExportFormat = "markdown"
    metrics: list[str] | None = None
    noise: NoiseMode = "both"
    digits: int = Field(3, ge=0, le=6)
    percent: bool = False
    top: int | None = Field(None, ge=1)
    groups: list[str] | None = None
    baselines: bool = True
    caption: str | None = None
    label: str | None = None
    standalone: bool = False
    mark_noise: bool = True


class ExportCell(BaseModel):
    """One metric of one row."""

    mean: float | None
    std: float | None
    n: int
    identical: bool
    lo: float | None
    hi: float | None
    method: Literal["wilson", "bootstrap"] | None
    n_examples: int | None
    best: bool


class ExportRow(BaseModel):
    """A seed group, a run (compare), or a paper baseline."""

    kind: Literal["group", "run", "baseline"]
    label: str
    key: str
    n: int
    cells: dict[str, ExportCell]
    within_noise: bool
    version_mismatch: bool
    source: str | None


class ExportTable(BaseModel):
    """Columns (metric refs), their directions, rows, and footnotes."""

    title: str
    columns: list[str]
    higher_is_better: dict[str, bool]
    rows: list[ExportRow]
    footnotes: list[str]


def _empty_cell() -> ExportCell:
    return ExportCell(
        mean=None, std=None, n=0, identical=False, lo=None, hi=None, method=None,
        n_examples=None, best=False,
    )  # fmt: skip


def _columns(board: Leaderboard, opts: ExportOptions) -> list[str]:
    if opts.metrics:
        return list(dict.fromkeys(metric_ref(m) for m in opts.metrics))
    present = {key for row in board.rows for key in row.scores}
    return [board.primary, *sorted(present - {board.primary})]


def _group_cell(
    row: LeaderboardRow, column: str, primary: str, opts: ExportOptions, scale: float
) -> ExportCell:
    stats = row.scores.get(column)
    if stats is None:
        return _empty_cell()
    seed = opts.noise in ("both", "seed")
    values = row.seed_values.get(column, [])
    identical = seed and len(values) > 1 and all(v == values[0] for v in values)
    interval = row.test_interval
    if column != primary or opts.noise not in ("both", "test"):
        interval = None
    return ExportCell(
        mean=stats.mean * scale,
        std=stats.std * scale if seed and stats.n > 1 else None,
        n=stats.n,
        identical=identical,
        lo=interval.lo * scale if interval is not None else None,
        hi=interval.hi * scale if interval is not None else None,
        method=interval.method if interval is not None else None,
        n_examples=interval.n if interval is not None else None,
        best=False,
    )


def _baseline_row(
    base: BaselineRow, columns: list[str], opts: ExportOptions, scales: dict[str, float]
) -> ExportRow:
    cells: dict[str, ExportCell] = {}
    shown: set[str] = set()
    for column in columns:
        scale = scales[column]
        value = base.values.get(column)
        if value is None:
            cells[column] = _empty_cell()
            continue
        shown.add(parse_metric_key(column)[0])
        std = base.std.get(column) if opts.noise in ("both", "seed") else None
        cell = _empty_cell().model_copy(
            update={"mean": value * scale, "std": None if std is None else std * scale}
        )
        cells[column] = cell
    mismatch = any(not base.version_match.get(metric, False) for metric in shown)
    return ExportRow(
        kind="baseline",
        label=base.name,
        key=base.name,
        n=0,
        cells=cells,
        within_noise=False,
        version_mismatch=mismatch,
        source=base.source,
    )


def mark_best(rows: list[ExportRow], higher_is_better: dict[str, bool]) -> None:
    """
    Flag the best non-baseline mean of each column (every tie is flagged).

    Parameters
    ----------
    rows : list of ExportRow
        Rows to update in place.
    higher_is_better : dict of str to bool
        Direction per column.
    """
    ranked = [r for r in rows if r.kind != "baseline"]
    for column, higher in higher_is_better.items():
        means: list[float] = []
        for row in ranked:
            cell = row.cells.get(column)
            if cell is not None and cell.mean is not None:
                means.append(cell.mean)
        if not means:
            continue
        best = max(means) if higher else min(means)
        for row in ranked:
            cell = row.cells.get(column)
            if cell is not None and cell.mean == best:
                row.cells[column] = cell.model_copy(update={"best": True})


def footnotes(
    versions: dict[str, str],
    rows: list[ExportRow],
    opts: ExportOptions,
    *,
    scaled: bool,
    extra: list[str] | None = None,
) -> list[str]:
    """
    Build a table's footnotes in their fixed order.

    Parameters
    ----------
    versions : dict of str to str
        Metric name -> version, for the metrics shown.
    rows : list of ExportRow
        The table's rows.
    opts : ExportOptions
        Export options (``mark_noise``).
    scaled : bool
        Whether values were multiplied by 100.
    extra : list of str, optional
        Notes added before the baselines line.

    Returns
    -------
    list of str
    """
    notes: list[str] = []
    if versions:
        notes.append(
            "metric versions: " + ", ".join(f"{m}@{v}" for m, v in sorted(versions.items()))
        )
    groups = [r for r in rows if r.kind == "group"]
    marks: list[str] = []
    if any(r.n == 1 for r in groups):
        marks.append(f"{MARK_SINGLE} single seed")
    if any(c.identical for r in groups for c in r.cells.values()):
        marks.append(f"{IDENTICAL}×n identical seeds")
    if opts.mark_noise and any(r.within_noise for r in rows):
        marks.append(f"{MARK_NOISE} within noise of best")
    if any(r.version_mismatch for r in rows):
        marks.append(f"{MARK_VERSION} metric version differs from the paper")
    if marks:
        notes.append(" · ".join(marks))
    methods = sorted({c.method for r in rows for c in r.cells.values() if c.method})
    if methods:
        notes.append(f"[lo, hi] 95% test-set interval ({', '.join(methods)})")
    if scaled:
        notes.append("values ×100")
    notes.extend(extra or [])
    base = [r for r in rows if r.kind == "baseline"]
    if base:
        notes.append("baselines: " + "; ".join(f"{r.label} — {r.source}" for r in base))
    return notes


def leaderboard_table(
    board: Leaderboard,
    opts: ExportOptions,
    *,
    directions: dict[str, bool] | None = None,
    value_formats: dict[str, str] | None = None,
) -> ExportTable:
    """
    Turn a leaderboard into an export table.

    Parameters
    ----------
    board : Leaderboard
        A built leaderboard (ranked rows, test-set intervals, baselines).
    opts : ExportOptions
        Columns, noise, rows, and marks.
    directions : dict of str to bool, optional
        Column ref (``latency/p95``), else metric name -> higher is better, for
        columns other than the primary.
    value_formats : dict of str to str, optional
        Column ref -> format. The primary defaults to ``board.value_format``;
        unspecified secondary columns default to ``number`` (never guess a unit).

    Returns
    -------
    ExportTable
        Ranked groups, then baselines; best cells flagged; footnotes.
    """
    columns = _columns(board, opts)
    given = directions or {}
    higher = {
        c: board.higher_is_better
        if c == board.primary
        else given.get(c, given.get(parse_metric_key(c)[0], True))
        for c in columns
    }
    formats = {board.primary: board.value_format, **(value_formats or {})}
    scales = {c: 100.0 if opts.percent and formats.get(c) == "fraction" else 1.0 for c in columns}
    scaled = [c for c in columns if scales[c] == 100.0]
    chosen = board.rows
    if opts.groups:
        wanted = set(opts.groups)
        chosen = [r for r in chosen if r.group_id in wanted or r.label in wanted]
    if opts.top is not None:
        chosen = chosen[: opts.top]
    rows = [
        ExportRow(
            kind="group",
            label=row.label,
            key=row.group_id,
            n=row.n,
            cells={c: _group_cell(row, c, board.primary, opts, scales[c]) for c in columns},
            within_noise=row.within_noise_of_best is True,
            version_mismatch=False,
            source=None,
        )
        for row in chosen
    ]
    mark_best(rows, higher)
    if opts.baselines:
        rows += [_baseline_row(b, columns, opts, scales) for b in board.baselines]
    shown = {parse_metric_key(c)[0] for c in columns}
    versions = {m: v for m, v in board.metric_versions.items() if m in shown}
    return ExportTable(
        title=f"{board.project}/{board.task}",
        columns=columns,
        higher_is_better=higher,
        rows=rows,
        footnotes=footnotes(
            versions,
            rows,
            opts,
            scaled=False,
            extra=["values ×100: " + ", ".join(scaled)] if scaled else [],
        ),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_export.py -v`
Expected: all cases pass, including the round-4 regressions.

Run: `uv run ruff check src/hypothex/core/export.py tests/core/test_export.py && uv run ruff format --check src/hypothex/core/export.py tests/core/test_export.py && uv run ty check src`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/export.py tests/core/test_export.py
git commit -m "feat(export): export tables from leaderboards with seed and test-set noise"
```

---

### Task 11: Render LaTeX, Markdown, and CSV; golden files

**Files:**
- Modify: `src/hypothex/core/export.py` (`latex_escape`, `render`)
- Create: `tests/core/golden/export/board.md`, `board.tex`, `board.csv`
- Test: `tests/core/test_export.py` (append)

**Interfaces:**
- Produces (contract 1.6, exact): `render(table, opts) -> str`, `latex_escape(text) -> str`.
- Produces (public helper): `CSV_HEADER` (contract column order); `fmt_number(x, digits) -> str` (fixed digits, never `-0.000`).
- Formats (contract 1.6): a cell is `mean`, `mean ± std` (seed noise), `mean (◇×n)` for identical seeds, then ` [lo, hi]` on the primary; the best is bold (`**…**`, `\textbf{…}`) around the mean part; a row label gets `¹` (single seed group), `†` (within noise, when `mark_noise`), `‡` (version mismatch). Markdown: a `| *baselines* |` separator row before baselines, `—` for missing, `- ` footnote lines after a blank line. LaTeX: first line `% requires \usepackage{booktabs}`, `tabular` with `\toprule`/`\midrule`/`\bottomrule`, `--` for missing, `\midrule` before baselines, footnotes as `% ` lines, or below the tabular inside `table` with `\caption`/`\label` when `standalone`. CSV: long format with `CSV_HEADER`, numbers as `repr(float)`, empty for missing, booleans `true`/`false`. Every output ends with one newline.

- [ ] **Step 1: Create the golden files**

Create `tests/core/golden/export/board.md`:

```markdown
| group | n | acc/value ↑ | f1/value ↑ |
|:--|--:|--:|--:|
| svm | 3 | **0.920 ± 0.010** [0.871, 0.954] | 0.890 ± 0.010 |
| rf† | 3 | 0.910 ± 0.005 [0.862, 0.947] | **0.910 ± 0.010** |
| logreg | 3 | 0.880 (◇×3) [0.826, 0.925] | 0.860 ± 0.010 |
| knn¹ | 1 | 0.850 [0.794, 0.894] | 0.800 |
| *baselines* |  |  |  |
| Smith_2024 & co | — | 0.900 ± 0.004 | 0.870 |
| Lee 2023‡ | — | 0.930 | — |

- metric versions: acc@v2, f1@v1
- ¹ single seed · ◇×n identical seeds · † within noise of best · ‡ metric version differs from the paper
- [lo, hi] 95% test-set interval (wilson)
- baselines: Smith_2024 & co — arXiv:2401.01234; Lee 2023 — doi:10.1000/xyz123
```

Create `tests/core/golden/export/board.tex`:

```latex
% requires \usepackage{booktabs}
\begin{tabular}{lrrr}
\toprule
group & $n$ & acc/value $\uparrow$ & f1/value $\uparrow$ \\
\midrule
svm & 3 & \textbf{0.920 $\pm$ 0.010} [0.871, 0.954] & 0.890 $\pm$ 0.010 \\
rf$^{\dagger}$ & 3 & 0.910 $\pm$ 0.005 [0.862, 0.947] & \textbf{0.910 $\pm$ 0.010} \\
logreg & 3 & 0.880 ($\diamond{\times}3$) [0.826, 0.925] & 0.860 $\pm$ 0.010 \\
knn$^{1}$ & 1 & 0.850 [0.794, 0.894] & 0.800 \\
\midrule
Smith\_2024 \& co & -- & 0.900 $\pm$ 0.004 & 0.870 \\
Lee 2023$^{\ddagger}$ & -- & 0.930 & -- \\
\bottomrule
\end{tabular}
% metric versions: acc@v2, f1@v1
% $^{1}$ single seed $\cdot$ $\diamond$$\times$n identical seeds $\cdot$ $^{\dagger}$ within noise of best $\cdot$ $^{\ddagger}$ metric version differs from the paper
% [lo, hi] 95\% test-set interval (wilson)
% baselines: Smith\_2024 \& co --- arXiv:2401.01234; Lee 2023 --- doi:10.1000/xyz123
```

Create `tests/core/golden/export/board.csv`:

```text
kind,label,key,n,metric,mean,std,identical,ci_lo,ci_hi,ci_method,n_examples,best,within_noise,version_mismatch,source
group,svm,aaaa0001@c1,3,acc/value,0.92,0.01,false,0.871,0.954,wilson,200,true,false,false,
group,svm,aaaa0001@c1,3,f1/value,0.89,0.01,false,,,,,false,false,false,
group,rf,aaaa0002@c1,3,acc/value,0.91,0.005,false,0.862,0.947,wilson,200,false,true,false,
group,rf,aaaa0002@c1,3,f1/value,0.91,0.01,false,,,,,true,true,false,
group,logreg,aaaa0003@c1,3,acc/value,0.88,0.0,true,0.826,0.925,wilson,200,false,false,false,
group,logreg,aaaa0003@c1,3,f1/value,0.86,0.01,false,,,,,false,false,false,
group,knn,aaaa0004@c1,1,acc/value,0.85,,false,0.794,0.894,wilson,200,false,false,false,
group,knn,aaaa0004@c1,1,f1/value,0.8,,false,,,,,false,false,false,
baseline,Smith_2024 & co,Smith_2024 & co,0,acc/value,0.9,0.004,false,,,,,false,false,false,arXiv:2401.01234
baseline,Smith_2024 & co,Smith_2024 & co,0,f1/value,0.87,,false,,,,,false,false,false,arXiv:2401.01234
baseline,Lee 2023,Lee 2023,0,acc/value,0.93,,false,,,,,false,false,true,doi:10.1000/xyz123
baseline,Lee 2023,Lee 2023,0,f1/value,,,false,,,,,false,false,true,doi:10.1000/xyz123
```

Each file's content is exactly the lines inside the fence, ending with one newline (the fence lines are not part of the file).

- [ ] **Step 2: Write the failing test**

Append to `tests/core/test_export.py` (and add `import os`, `from pathlib import Path`, and `latex_escape, render` to the `hypothex.core.export` import):

```python
GOLDEN = Path(__file__).parent / "golden" / "export"


def check_golden(name: str, text: str) -> None:
    """Compare with a golden file; ``HX_UPDATE_GOLDEN=1`` rewrites it instead."""
    path = GOLDEN / name
    if os.environ.get("HX_UPDATE_GOLDEN") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert text == path.read_text(encoding="utf-8")


@pytest.mark.parametrize(("fmt", "ext"), [("markdown", "md"), ("latex", "tex"), ("csv", "csv")])
def test_board_matches_the_golden_file(fmt: str, ext: str) -> None:
    opts = ExportOptions(format=fmt)  # type: ignore[arg-type]
    text = render(leaderboard_table(make_board(), opts), opts)
    check_golden(f"board.{ext}", text)
    assert text == render(leaderboard_table(make_board(), opts), opts)  # deterministic


def test_latex_is_ascii() -> None:
    opts = ExportOptions(format="latex")
    assert render(leaderboard_table(make_board(), opts), opts).isascii()


def test_latex_escape() -> None:
    text = latex_escape("a_b & 50% $x #1 {y} ~ ^ \\ é ± †")
    assert text == (
        r"a\_b \& 50\% \$x \#1 \{y\} \textasciitilde{} \textasciicircum{} "
        r"\textbackslash{} e $\pm$ $^{\dagger}$"
    )
    assert text.isascii()


def test_standalone_latex_wraps_a_table() -> None:
    opts = ExportOptions(format="latex", standalone=True, caption="Toy results", label="tab:toy")
    text = render(leaderboard_table(make_board(), opts), opts)
    lines = text.splitlines()
    assert lines[:5] == [
        r"% requires \usepackage{booktabs}",
        r"\begin{table}[t]",
        r"\centering",
        r"\caption{Toy results}",
        r"\label{tab:toy}",
    ]
    assert r"\par\smallskip\footnotesize" in lines
    assert lines[-2] == (
        r"baselines: Smith\_2024 \& co --- arXiv:2401.01234; Lee 2023 --- doi:10.1000/xyz123"
    )
    assert lines[-1] == r"\end{table}" and not any(line.startswith("% metric") for line in lines)


def test_noise_and_digits_in_markdown() -> None:
    opts = ExportOptions(noise="none", digits=1, mark_noise=False, baselines=False)
    lines = render(leaderboard_table(make_board(), opts), opts).splitlines()
    assert lines[2] == "| svm | 3 | **0.9** | 0.9 |"
    assert lines[3] == "| rf | 3 | 0.9 | **0.9** |"  # no † when mark_noise is off


def test_missing_values_never_print_nan() -> None:
    board = make_board()
    board.rows[0].scores.pop("f1/value")
    for fmt, missing in (("markdown", "—"), ("latex", "--")):
        opts = ExportOptions(format=fmt)  # type: ignore[arg-type]
        text = render(leaderboard_table(board, opts), opts)
        svm_line = text.splitlines()[2 if fmt == "markdown" else 5]
        assert "nan" not in text.lower() and missing in svm_line


def test_empty_board_renders_a_header_only_table() -> None:
    board = make_board(baselines=False)
    board.rows = []
    opts = ExportOptions()
    assert render(leaderboard_table(board, opts), opts) == (
        "| group | n | acc/value ↑ |\n|:--|--:|--:|\n\n- metric versions: acc@v2\n"
    )
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/core/test_export.py -v`
Expected: FAIL at collection with `ImportError: cannot import name 'latex_escape' from 'hypothex.core.export'`.

- [ ] **Step 4: Write the implementation**

In `src/hypothex/core/export.py`, add to the imports:

```python
import csv
import io
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
```

and append:

```python
CSV_HEADER = (
    "kind", "label", "key", "n", "metric", "mean", "std", "identical", "ci_lo", "ci_hi",
    "ci_method", "n_examples", "best", "within_noise", "version_mismatch", "source",
)  # fmt: skip
_LATEX_SPECIAL = {
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    "\\": r"\textbackslash{}",
}
_LATEX_UNICODE = {
    "±": r"$\pm$",
    "×": r"$\times$",
    "◇": r"$\diamond$",
    "¹": r"$^{1}$",
    "†": r"$^{\dagger}$",
    "‡": r"$^{\ddagger}$",
    "↑": r"$\uparrow$",
    "↓": r"$\downarrow$",
    "—": "---",
    "–": "--",
    "…": r"\ldots{}",
    "·": r"$\cdot$",
    "→": r"$\rightarrow$",
    "≠": r"$\neq$",
    "▲": r"$\blacktriangle$",
}


def latex_escape(text: str) -> str:
    """
    Escape text for LaTeX; the result is ASCII plus LaTeX commands.

    The ten special characters are escaped, the table glyphs become math
    commands, accented letters lose their accent, and any other non-ASCII
    character becomes ``?``.

    Parameters
    ----------
    text : str

    Returns
    -------
    str

    Examples
    --------
    >>> latex_escape("lr_1e-4 & 95%")
    'lr\\\\_1e-4 \\\\& 95\\\\%'
    """
    out: list[str] = []
    for ch in text:
        if ch in _LATEX_SPECIAL:
            out.append(_LATEX_SPECIAL[ch])
        elif ch in _LATEX_UNICODE:
            out.append(_LATEX_UNICODE[ch])
        elif ch.isascii():
            out.append(ch)
        else:
            plain = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode()
            out.append(plain or "?")
    return "".join(out)


def fmt_number(x: float, digits: int) -> str:
    """
    Format a number with fixed digits, never as ``-0.000``.

    Parameters
    ----------
    x : float
    digits : int

    Returns
    -------
    str

    Examples
    --------
    >>> fmt_number(0.9126, 3), fmt_number(-0.0001, 3)
    ('0.913', '0.000')
    """
    text = f"{x:.{digits}f}"
    return f"{0.0:.{digits}f}" if float(text) == 0.0 else text


@dataclass(frozen=True)
class _Style:
    missing: str
    pm: str
    identical: Callable[[int], str]
    bold: Callable[[str], str]
    up: str
    down: str


_MARKDOWN = _Style(
    missing="—",
    pm="±",
    identical=lambda n: f"{IDENTICAL}×{n}",
    bold=lambda t: f"**{t}**",
    up="↑",
    down="↓",
)
_LATEX = _Style(
    missing="--",
    pm=r"$\pm$",
    identical=lambda n: rf"$\diamond{{\times}}{n}$",
    bold=lambda t: rf"\textbf{{{t}}}",
    up=r"$\uparrow$",
    down=r"$\downarrow$",
)


def _cell_text(cell: ExportCell | None, digits: int, style: _Style) -> str:
    if cell is None or cell.mean is None:
        return style.missing
    text = fmt_number(cell.mean, digits)
    if cell.identical:
        text += f" ({style.identical(cell.n)})"
    elif cell.std is not None:
        text += f" {style.pm} {fmt_number(cell.std, digits)}"
    if cell.best:
        text = style.bold(text)
    if cell.lo is not None and cell.hi is not None:
        text += f" [{fmt_number(cell.lo, digits)}, {fmt_number(cell.hi, digits)}]"
    return text


def _marked(row: ExportRow, opts: ExportOptions) -> str:
    marks = ""
    if row.kind == "group" and row.n == 1:
        marks += MARK_SINGLE
    if opts.mark_noise and row.within_noise:
        marks += MARK_NOISE
    if row.version_mismatch:
        marks += MARK_VERSION
    return row.label + marks


def _first_header(table: ExportTable) -> str:
    return "run" if any(r.kind == "run" for r in table.rows) else "group"


def _markdown(table: ExportTable, opts: ExportOptions) -> str:
    def line(cells: list[str]) -> str:
        return "| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |"

    arrows = [
        f"{c} {_MARKDOWN.up if table.higher_is_better[c] else _MARKDOWN.down}"
        for c in table.columns
    ]
    lines = [
        line([_first_header(table), "n", *arrows]),
        "|" + "|".join([":--", "--:", *("--:" for _ in table.columns)]) + "|",
    ]
    baselines_started = False
    for row in table.rows:
        if row.kind == "baseline" and not baselines_started:
            lines.append(line(["*baselines*", "", *("" for _ in table.columns)]))
            baselines_started = True
        n = _MARKDOWN.missing if row.kind == "baseline" else str(row.n)
        cells = [_cell_text(row.cells.get(c), opts.digits, _MARKDOWN) for c in table.columns]
        lines.append(line([_marked(row, opts), n, *cells]))
    if table.footnotes:
        lines.append("")
        lines += [f"- {note}" for note in table.footnotes]
    return "\n".join(lines) + "\n"


def _latex(table: ExportTable, opts: ExportOptions) -> str:
    def line(cells: list[str]) -> str:
        return " & ".join(cells) + r" \\"

    arrows = [
        f"{latex_escape(c)} {_LATEX.up if table.higher_is_better[c] else _LATEX.down}"
        for c in table.columns
    ]
    lines = [r"% requires \usepackage{booktabs}"]
    if opts.standalone:
        lines += [
            r"\begin{table}[t]",
            r"\centering",
            rf"\caption{{{latex_escape(opts.caption or table.title)}}}",
        ]
        if opts.label:
            lines.append(rf"\label{{{opts.label}}}")
    lines += [
        rf"\begin{{tabular}}{{l{'r' * (len(table.columns) + 1)}}}",
        r"\toprule",
        line([_first_header(table), "$n$", *arrows]),
        r"\midrule",
    ]
    baselines_started = False
    for row in table.rows:
        if row.kind == "baseline" and not baselines_started:
            lines.append(r"\midrule")
            baselines_started = True
        n = _LATEX.missing if row.kind == "baseline" else str(row.n)
        cells = [_cell_text(row.cells.get(c), opts.digits, _LATEX) for c in table.columns]
        lines.append(line([latex_escape(_marked(row, opts)), n, *cells]))
    lines += [r"\bottomrule", r"\end{tabular}"]
    notes = [latex_escape(note) for note in table.footnotes]
    if opts.standalone:
        if notes:
            lines.append(r"\par\smallskip\footnotesize")
            lines += [note + r" \\" for note in notes[:-1]]
            lines.append(notes[-1])
        lines.append(r"\end{table}")
    else:
        lines += [f"% {note}" for note in notes]
    return "\n".join(lines) + "\n"


def _csv_number(x: float | None) -> str:
    return "" if x is None else repr(float(x))


def _csv_bool(x: bool) -> str:
    return "true" if x else "false"


def _csv(table: ExportTable) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    for row in table.rows:
        for column in table.columns:
            cell = row.cells.get(column) or _empty_cell()
            writer.writerow(
                [
                    row.kind, row.label, row.key, row.n, column, _csv_number(cell.mean),
                    _csv_number(cell.std), _csv_bool(cell.identical), _csv_number(cell.lo),
                    _csv_number(cell.hi), cell.method or "",
                    "" if cell.n_examples is None else cell.n_examples, _csv_bool(cell.best),
                    _csv_bool(row.within_noise), _csv_bool(row.version_mismatch),
                    row.source or "",
                ]
            )  # fmt: skip
    return buffer.getvalue()


def render(table: ExportTable, opts: ExportOptions) -> str:
    """
    Render an export table as LaTeX, Markdown, or CSV.

    Parameters
    ----------
    table : ExportTable
    opts : ExportOptions
        ``format``, ``digits``, ``mark_noise``, ``standalone``, ``caption``, ``label``.

    Returns
    -------
    str
        The text, ending with one newline; identical input gives identical bytes.
    """
    if opts.format == "latex":
        return _latex(table, opts)
    if opts.format == "csv":
        return _csv(table)
    return _markdown(table, opts)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_export.py -v`
Expected: all cases pass, including the earlier round-4 regressions.

Run: `uv run python -m doctest src/hypothex/core/export.py && uv run ruff check src/hypothex/core/export.py tests/core/test_export.py && uv run ruff format --check src/hypothex/core/export.py tests/core/test_export.py && uv run ty check src`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/hypothex/core/export.py tests/core/test_export.py tests/core/golden/export
git commit -m "feat(export): render booktabs LaTeX, Markdown, and CSV with golden files"
```

---

### Task 12: Compare tables and the `export_task` / `export_compare` entry points

**Files:**
- Modify: `src/hypothex/core/export.py` (`compare_table`, `export_task`, `export_compare`)
- Modify: `src/hypothex/core/leaderboard.py` (`metric_higher_is_better`; `_higher_is_better` calls it)
- Create: `tests/core/golden/export/compare.md`, `compare.csv`
- Test: `tests/core/test_export.py` (append)

**Interfaces:**
- Consumes: `get_leaderboard`, `resolve_task` (`hypothex.core.queries`), `Context`, `group_label`.
- Produces (contract 1.6, exact): `compare_table(ctx, run_ids, opts)`, `export_task(ctx, task, project, opts)`, `export_compare(ctx, run_ids, opts)`.
- Produces (public helper): `task_table(ctx, task, project, opts) -> ExportTable` (the table `export_task` renders; `hx export --json` returns it, Task 43); `COMPARE_MAX_RUNS = 20`; `leaderboard.metric_higher_is_better(config, kind, ref) -> bool` (the leaderboard's one direction rule, now shared: a percentile key of a `system_bench` task, e.g. `latency/p95`, ranks lower-first whatever the metric says; else the metric's `higher_is_better`).
- Rules: `compare_table` takes 2 to 20 runs (else `RunError`); one row per run (`kind="run"`, `n=1`, label = hypothesis clause or run id, key = run id); scores are each run's newest valid score at its project's current metric versions; columns are `opts.metrics` or the first run's task primary, then every other key, sorted; each column's direction is `metric_higher_is_better` for the run's task kind, so a benchmark's latency 300 is best over 440, as on the leaderboard; a shown metric whose version or direction differs between the compared runs' projects is refused (`RunError` "accuracy is accuracy@v1 in toy and accuracy@v2 in toy2; compare runs at one metric version"), and so is a column that ranks lower-first for some runs and higher-first for others; never merged into one column; no seed or test-set noise; `percent` multiplies a column by 100 only when it is a fraction (`headlines.value_format` of its unit and values is `fraction`, the leaderboard's rule; a latency of 440 ms stays 440) and the footnote `values ×100` appears only when a column was scaled; footnotes `metric versions: ...` and `one run per row`. `export_task` passes every column's `metric_higher_is_better` and independently computed `value_format(metric_unit(...), values, direction)` to `leaderboard_table` (a `system_bench` task's other percentile keys rank lower-first too).

- [ ] **Step 1: Create the golden files**

Create `tests/core/golden/export/compare.md`:

```markdown
| run | n | accuracy/value ↑ |
|:--|--:|--:|
| r1 | 1 | **0.750** |
| r2 | 1 | 0.250 |

- metric versions: accuracy@v1
- one run per row
```

Create `tests/core/golden/export/compare.csv`:

```text
kind,label,key,n,metric,mean,std,identical,ci_lo,ci_hi,ci_method,n_examples,best,within_noise,version_mismatch,source
run,r1,r1,1,accuracy/value,0.75,,false,,,,,true,false,false,
run,r2,r2,1,accuracy/value,0.25,,false,,,,,false,false,false,
```

- [ ] **Step 2: Write the failing test**

Append to `tests/core/test_export.py` (and add `import yaml`, `from hypothex.core.context import Context`, `from hypothex.core.errors import RunError`, `from hypothex.core.evaluation import evaluate_run`, `from hypothex.core.ids import utcnow`, `from hypothex.core.records import RunStatus, ScoreRecord`, `from tests.factories import PREDS_075, make_record, seed_finished_run, write_toy_project`, plus `compare_table, export_compare, export_task` to the `hypothex.core.export` import):

```python
PREDS_025 = [{"id": f"ex-{i}", "prediction": 1} for i in range(4)]  # 1 of 4 correct


@pytest.fixture
def scored(ctx: Context, toy_repo: Path) -> Context:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    seed_finished_run(ctx, toy_repo, "r2", predictions=PREDS_025)
    evaluate_run(ctx, "r1")
    evaluate_run(ctx, "r2")
    return ctx


@pytest.mark.parametrize(("fmt", "ext"), [("markdown", "md"), ("csv", "csv")])
def test_compare_matches_the_golden_file(scored: Context, fmt: str, ext: str) -> None:
    opts = ExportOptions(format=fmt)  # type: ignore[arg-type]
    check_golden(f"compare.{ext}", export_compare(scored, ["r1", "r2"], opts))


def test_compare_table_rows(scored: Context) -> None:
    table = compare_table(scored, ["r2", "r1"], ExportOptions())
    assert [(r.kind, r.key, r.n) for r in table.rows] == [("run", "r2", 1), ("run", "r1", 1)]
    assert table.rows[1].cells["accuracy/value"].best
    assert table.title == "compare"


def test_compare_refuses_two_versions_of_one_metric(scored: Context, tmp_path: Path) -> None:
    other = write_toy_project(tmp_path / "toy2", accuracy_version="v2", use_git=False)
    config = yaml.safe_load((other / "hypothex.yaml").read_text())
    config["project"] = "toy2"
    (other / "hypothex.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    seed_finished_run(scored, other, "r3", predictions=PREDS_075)
    evaluate_run(scored, "r3")
    with pytest.raises(RunError, match="accuracy is accuracy@v1 in toy and accuracy@v2 in toy2"):
        compare_table(scored, ["r1", "r3"], ExportOptions())


def test_compare_needs_two_to_twenty_runs(scored: Context) -> None:
    with pytest.raises(RunError):
        compare_table(scored, ["r1"], ExportOptions())
    with pytest.raises(RunError):
        compare_table(scored, ["r1"] * 21, ExportOptions())


def test_export_task_uses_the_live_leaderboard(scored: Context) -> None:
    text = export_task(scored, "toy-acc", "toy", ExportOptions())
    header, _, row = text.splitlines()[:3]
    assert header == "| group | n | accuracy/value ↑ |"
    assert row.startswith("| group aaaa@c1 | 2 |")  # r1 and r2 are one seed group
    assert "0.500 ± 0.354" in row and "[" in row  # test-set CI from per-example scores


@pytest.fixture
def bench(ctx: Context, toy_repo: Path) -> Context:
    """A system_bench task: p95 latency 440 ms (base) and 300 ms (fast)."""
    config = yaml.safe_load((toy_repo / "hypothex.yaml").read_text())
    config["metrics"]["lat"] = {"version": "v1", "fn": "toymetrics:accuracy"}
    config["tasks"]["sb"] = {
        "dataset": "toyset", "split": "test", "metrics": ["lat"],
        "primary": "lat/p95", "kind": "system_bench",
    }  # fmt: skip
    (toy_repo / "hypothex.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    ctx.register_project(toy_repo)
    for run_id, ms in (("base", 440.0), ("fast", 300.0)):
        record = ctx.create_run(
            make_record(
                run_id,
                project="toy",
                task="sb",
                status=RunStatus.FINISHED,
                environment_id=ctx.descriptor.environment_id,
            )
        )
        score = ScoreRecord(metric="lat", version="v1", key="p95", value=ms, created_at=utcnow())
        ctx.add_score(record, score)
    return ctx


def test_compare_ranks_benchmark_percentiles_like_the_leaderboard(bench: Context) -> None:
    table = compare_table(bench, ["base", "fast"], ExportOptions())
    assert table.columns == ["lat/p95"] and table.higher_is_better == {"lat/p95": False}
    assert [r.cells["lat/p95"].best for r in table.rows] == [False, True]  # 300 beats 440
    text = export_compare(bench, ["base", "fast"], ExportOptions())
    assert text.startswith("| run | n | lat/p95 ↓ |")


def test_compare_percent_scales_fractions(scored: Context) -> None:
    table = compare_table(scored, ["r1", "r2"], ExportOptions(percent=True))
    assert [r.cells["accuracy/value"].mean for r in table.rows] == [75.0, 25.0]
    assert "values ×100" in table.footnotes


def test_task_percent_derives_each_columns_unit(scored: Context, toy_repo: Path) -> None:
    config = yaml.safe_load((toy_repo / "hypothex.yaml").read_text())
    config["metrics"]["latency"] = {
        "version": "v1",
        "fn": "toymetrics:accuracy",
        "unit": "ms",
        "higher_is_better": False,
    }
    config["tasks"]["toy-acc"]["metrics"].append("latency")
    (toy_repo / "hypothex.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    scored.register_project(toy_repo)
    for run_id in ("r1", "r2"):
        scored.add_score(
            scored.find_record(run_id),
            ScoreRecord(
                metric="latency",
                version="v1",
                key="value",
                value=440.0,
                created_at=utcnow(),
            ),
        )
    from hypothex.core.export import task_table

    table = task_table(scored, "toy-acc", "toy", ExportOptions(percent=True))
    assert table.rows[0].cells["accuracy/value"].mean == pytest.approx(50.0)
    assert table.rows[0].cells["latency/value"].mean == 440.0


def test_compare_percent_leaves_latency_alone(bench: Context) -> None:
    table = compare_table(bench, ["base", "fast"], ExportOptions(percent=True))
    assert [r.cells["lat/p95"].mean for r in table.rows] == [440.0, 300.0]
    assert "values ×100" not in table.footnotes
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/core/test_export.py -v`
Expected: FAIL at collection with `ImportError: cannot import name 'compare_table' from 'hypothex.core.export'`.

- [ ] **Step 4: Write the implementation**

In `src/hypothex/core/leaderboard.py`, replace `_higher_is_better` with the shared rule and a caller of it:

```python
def metric_higher_is_better(config: ProjectConfig, kind: TaskKind | None, ref: str) -> bool:
    """
    Tell which way one score key ranks on a task of ``kind``.

    The leaderboard and the exports share this rule: a percentile key of a
    ``system_bench`` task (``latency/p95``) ranks lower-first whatever the
    metric says; any other key follows the metric's ``higher_is_better``.

    Parameters
    ----------
    config : ProjectConfig
        The project config (its ``metrics``).
    kind : TaskKind or None
        The task's kind; None for a run without a task.
    ref : str
        A metric reference, ``metric`` or ``metric/key``.

    Returns
    -------
    bool
        True when a larger value is better; True for an unknown metric.

    Examples
    --------
    >>> metric_higher_is_better(config, "system_bench", "lat/p95")  # doctest: +SKIP
    False
    """
    metric, key = parse_metric_key(ref)
    if kind == "system_bench" and percentile_of(f"{metric}/{key}"):
        return False
    spec = config.metrics.get(metric)
    return spec.higher_is_better if spec is not None else True


def _higher_is_better(config: ProjectConfig, spec: TaskSpec) -> bool:
    return metric_higher_is_better(config, spec.kind, spec.primary)
```

In `src/hypothex/core/export.py`, add to the imports:

```python
import math
from collections import defaultdict

from hypothex.core.config import ProjectConfig
from hypothex.core.context import Context
from hypothex.core.errors import RunError
from hypothex.core.headlines import metric_unit, value_format
from hypothex.core.leaderboard import group_label, metric_higher_is_better
from hypothex.core.queries import get_leaderboard, resolve_task
```

(merge `group_label` and `metric_higher_is_better` into the existing `hypothex.core.leaderboard` import), and append:

```python
COMPARE_MAX_RUNS = 20


def compare_table(ctx: Context, run_ids: list[str], opts: ExportOptions) -> ExportTable:
    """
    Build a table with one row per run (scores at each project's current versions).

    Parameters
    ----------
    ctx : Context
    run_ids : list of str
        2 to 20 runs, shown in this order.
    opts : ExportOptions
        Columns (``metrics``), ``percent``, ``digits``.

    Returns
    -------
    ExportTable
        ``kind="run"`` rows, ``n=1``, no noise columns.

    Raises
    ------
    RunError
        Fewer than 2 or more than 20 runs, or a shown metric with different
        versions or directions in the runs' projects.
    RunNotFoundError
        An unknown run id.
    """
    if not 2 <= len(run_ids) <= COMPARE_MAX_RUNS:
        raise RunError(f"compare export takes 2 to {COMPARE_MAX_RUNS} runs")
    records = [ctx.find_record(r) for r in run_ids]
    configs: dict[str, ProjectConfig] = {}
    for record in records:
        if record.project not in configs:
            configs[record.project] = ctx.store.load_project(record.project).config
    scores = ctx.index.scores_for(run_ids)
    values: dict[str, dict[str, float]] = {}
    versions: dict[str, str] = {}
    units: dict[str, str] = {}
    # metric -> (version, higher_is_better) -> the first project that scores it so
    seen: dict[str, dict[tuple[str, bool], str]] = defaultdict(dict)
    # column -> effective direction (the leaderboard's rule, per run's task kind) -> a run
    ranks: dict[str, dict[bool, str]] = defaultdict(dict)
    for record in records:
        config = configs[record.project]
        task_spec = config.tasks.get(record.task) if record.task is not None else None
        kind = task_spec.kind if task_spec is not None else None
        current: dict[str, float] = {}
        for score in sorted(scores.get(record.run_id, []), key=lambda s: s.created_at):
            metric = config.metrics.get(score.metric)
            if (
                metric is None
                or score.version != metric.version
                or score.error is not None
                or score.value is None
                or not math.isfinite(score.value)
            ):
                continue
            ref = f"{score.metric}/{score.key}"
            current[ref] = score.value
            units[ref] = metric_unit(ref, metric.unit)
            versions[score.metric] = metric.version
            seen[score.metric].setdefault((metric.version, metric.higher_is_better), record.project)
            ranks[ref].setdefault(metric_higher_is_better(config, kind, ref), record.run_id)
        values[record.run_id] = current
    primary = next(
        (
            metric_ref(configs[r.project].tasks[r.task].primary)
            for r in records
            if r.task is not None and r.task in configs[r.project].tasks
        ),
        None,
    )
    if opts.metrics:
        columns = list(dict.fromkeys(metric_ref(m) for m in opts.metrics))
    else:
        present = {key for v in values.values() for key in v}
        first = [primary] if primary is not None and primary in present else []
        columns = [*first, *sorted(present - set(first))]
    for name in dict.fromkeys(parse_metric_key(c)[0] for c in columns):
        if len(seen.get(name, {})) > 1:  # one column must mean one metric definition
            forms = " and ".join(f"{name}@{v} in {p}" for (v, _), p in seen[name].items())
            raise RunError(f"{name} is {forms}; compare runs at one metric version")
    for column in columns:
        if len(ranks.get(column, {})) > 1:  # a system_bench percentile ranks lower-first
            raise RunError(
                f"{column} ranks lower-first for {ranks[column][False]} and higher-first for "
                f"{ranks[column][True]}; compare runs of one task kind"
            )
    higher = {c: next(iter(ranks[c])) if ranks.get(c) else True for c in columns}
    # contract 1.6: x100 only for fractions (no unit, every value in [0, 1]), column by
    # column, with the leaderboard's own value_format rule; a latency of 440 ms stays 440
    scaled = {
        c
        for c in columns
        if opts.percent
        and value_format(units.get(c, ""), (v[c] for v in values.values() if c in v), higher[c])
        == "fraction"
    }
    rows: list[ExportRow] = []
    for record in records:
        cells: dict[str, ExportCell] = {}
        for column in columns:
            value = values[record.run_id].get(column)
            cell = _empty_cell()
            if value is not None:
                mean = value * 100.0 if column in scaled else value
                cell = cell.model_copy(update={"mean": mean, "n": 1})
            cells[column] = cell
        label = group_label(record.hypothesis, record.tags, record.run_id).removeprefix("group ")
        rows.append(
            ExportRow(
                kind="run",
                label=label,
                key=record.run_id,
                n=1,
                cells=cells,
                within_noise=False,
                version_mismatch=False,
                source=None,
            )
        )
    mark_best(rows, higher)
    shown = {parse_metric_key(c)[0] for c in columns}
    return ExportTable(
        title="compare",
        columns=columns,
        higher_is_better=higher,
        rows=rows,
        footnotes=footnotes(
            {m: v for m, v in versions.items() if m in shown},
            rows,
            opts,
            scaled=bool(scaled),
            extra=["one run per row"],
        ),
    )


def task_table(ctx: Context, task: str, project: str | None, opts: ExportOptions) -> ExportTable:
    """
    Build the export table of a task's live leaderboard.

    Parameters
    ----------
    ctx : Context
    task : str
        Task name or ``project/task``.
    project : str or None
    opts : ExportOptions

    Returns
    -------
    ExportTable
        With each column's direction by ``metric_higher_is_better`` (the
        leaderboard's rule for the task's kind).
    """
    entry, name = resolve_task(ctx, task, project)
    board = get_leaderboard(ctx, name, entry.project)
    kind = entry.config.tasks[name].kind
    directions = {c: metric_higher_is_better(entry.config, kind, c) for c in _columns(board, opts)}
    formats: dict[str, str] = {}
    for column in _columns(board, opts):
        metric = entry.config.metrics.get(parse_metric_key(column)[0])
        unit = metric_unit(column, metric.unit) if metric is not None else ""
        values = [r.scores[column].mean for r in board.rows if column in r.scores]
        values += [b.values[column] for b in board.baselines if column in b.values]
        formats[column] = value_format(unit, values, directions[column])
    return leaderboard_table(board, opts, directions=directions, value_formats=formats)


def export_task(ctx: Context, task: str, project: str | None, opts: ExportOptions) -> str:
    """
    Export a task's leaderboard as text.

    Parameters
    ----------
    ctx : Context
    task : str
        Task name or ``project/task``.
    project : str or None
    opts : ExportOptions

    Returns
    -------
    str
        LaTeX, Markdown, or CSV.
    """
    return render(task_table(ctx, task, project, opts), opts)


def export_compare(ctx: Context, run_ids: list[str], opts: ExportOptions) -> str:
    """
    Export a comparison of runs as text.

    Parameters
    ----------
    ctx : Context
    run_ids : list of str
    opts : ExportOptions

    Returns
    -------
    str
    """
    return render(compare_table(ctx, run_ids, opts), opts)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_export.py tests/core/test_leaderboard.py -v`
Expected: `tests/core/test_export.py` `28 passed` (19 from Tasks 10–11, then 9 here); the leaderboard tests still pass (`test_system_bench_percentile_is_lower_is_better` now goes through `metric_higher_is_better`).

Run: `uv run ruff check src/hypothex/core tests/core/test_export.py && uv run ruff format --check src/hypothex/core tests/core/test_export.py && uv run ty check src`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/hypothex/core/export.py src/hypothex/core/leaderboard.py tests/core/test_export.py tests/core/golden/export
git commit -m "feat(export): compare tables and task/compare export entry points"
```

---
## Part 4: Notifications

Contract 1.7, 8 (failure modes 1–7), 9 (fakes). Only the hub notifies: a host never runs the notifier, and a mirrored run notifies from its `mirror.run_updated` event. Delivery is at least once through an outbox of one file per notice and channel.

### Task 13: Fake Slack webhook and fake SMTP server

**Files:**
- Create: `tests/fakes/webhook.py`, `tests/fakes/smtp.py`
- Test: `tests/notify/__init__.py`, `tests/notify/test_fakes.py`

**Interfaces:**
- Produces (tests only, contract 9):
  - `tests.fakes.webhook.Reply(status=200, retry_after=None, stall=0.0, body="ok")`; `FakeWebhook(script=None)` — a `ThreadingHTTPServer` on `127.0.0.1:0`; `url` = `http://127.0.0.1:<port>/services/T000/B000/<secret>` (`secret` starts with `SECRETHOOK`); `requests: list[dict]` (`path`, `body`, `headers`); `queue(*replies)`; context manager (`start`/`stop`).
  - `tests.fakes.smtp.FakeSmtp(mode="plain"|"starttls"|"ssl", user=None, password=None, fail=None)` — `aiosmtpd` on `127.0.0.1:<port>`; `received: list[Received]` (`mail_from`, `rcpt_tos`, `message`); `client_context` (an `ssl.SSLContext` trusting the fake's `trustme` CA); `fail` one of `"auth"` (every login 535), `"data_451"`, `"data_550"`, `"connect_421"` (greets with 421 and hangs up), `"stall"` (accepts and never answers); context manager.

- [ ] **Step 1: Write the failing test**

Create `tests/notify/__init__.py` (empty) and `tests/notify/test_fakes.py`:

```python
import smtplib
from email.message import EmailMessage

import httpx
import pytest

from tests.fakes.smtp import FakeSmtp
from tests.fakes.webhook import FakeWebhook, Reply


def message(subject: str = "hi") -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, "hx@lab.org", "sv@lab.org"
    msg.set_content("body\n")
    return msg


def test_webhook_records_and_plays_its_script() -> None:
    with FakeWebhook([Reply(429, retry_after=7), Reply(500)]) as hook:
        assert hook.url.startswith("http://127.0.0.1:")
        assert "/services/T000/B000/SECRETHOOK" in hook.url
        first = httpx.post(hook.url, json={"text": "a"})
        assert first.status_code == 429 and first.headers["Retry-After"] == "7"
        assert httpx.post(hook.url, json={"text": "b"}).status_code == 500
        assert httpx.post(hook.url, json={"text": "c"}).status_code == 200
        assert [r["body"]["text"] for r in hook.requests] == ["a", "b", "c"]


def test_webhook_stall_times_the_client_out() -> None:
    with FakeWebhook([Reply(stall=2.0)]) as hook, pytest.raises(httpx.TimeoutException):
        httpx.post(hook.url, json={}, timeout=0.3)


def test_plain_smtp_receives() -> None:
    with FakeSmtp() as smtp, smtplib.SMTP("127.0.0.1", smtp.port, timeout=5) as client:
        client.send_message(message("plain"))
    assert smtp.received[0].message["Subject"] == "plain"
    assert smtp.received[0].rcpt_tos == ["sv@lab.org"]


def test_starttls_with_login() -> None:
    with FakeSmtp(mode="starttls", user="sv", password="pw") as smtp:
        with smtplib.SMTP("127.0.0.1", smtp.port, timeout=5) as client:
            client.starttls(context=smtp.client_context)
            client.login("sv", "pw")
            client.send_message(message("tls"))
        assert smtp.received[0].message["Subject"] == "tls"


def test_implicit_ssl() -> None:
    with FakeSmtp(mode="ssl") as smtp:
        with smtplib.SMTP_SSL(
            "127.0.0.1", smtp.port, timeout=5, context=smtp.client_context
        ) as client:
            client.send_message(message("ssl"))
        assert smtp.received[0].message["Subject"] == "ssl"


def test_wrong_password_is_535() -> None:
    with FakeSmtp(user="sv", password="pw") as smtp, smtplib.SMTP("127.0.0.1", smtp.port) as c:
        with pytest.raises(smtplib.SMTPAuthenticationError) as info:
            c.login("sv", "nope")
        assert info.value.smtp_code == 535


@pytest.mark.parametrize(("fail", "code"), [("data_451", 451), ("data_550", 550)])
def test_scripted_data_failures(fail: str, code: int) -> None:
    with FakeSmtp(fail=fail) as smtp:  # type: ignore[arg-type]
        with smtplib.SMTP("127.0.0.1", smtp.port, timeout=5) as client:
            with pytest.raises(smtplib.SMTPDataError) as info:
                client.send_message(message())
            assert info.value.smtp_code == code
        assert smtp.received == []


def test_connect_421_and_stall() -> None:
    with FakeSmtp(fail="connect_421") as smtp, pytest.raises(smtplib.SMTPConnectError) as info:
        smtplib.SMTP("127.0.0.1", smtp.port, timeout=5)
    assert info.value.smtp_code == 421
    # smtplib turns a read timeout during the greeting into SMTPServerDisconnected
    with (
        FakeSmtp(fail="stall") as smtp,
        pytest.raises(smtplib.SMTPServerDisconnected, match="timed out"),
    ):
        smtplib.SMTP("127.0.0.1", smtp.port, timeout=0.5)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/notify/test_fakes.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'tests.fakes.smtp'`.

- [ ] **Step 3: Write the fakes**

Create `tests/fakes/webhook.py`:

```python
"""
A fake Slack incoming webhook on 127.0.0.1: records requests and plays scripted replies.

Examples
--------
>>> with FakeWebhook([Reply(429, retry_after=7)]) as hook:  # doctest: +SKIP
...     httpx.post(hook.url, json={"text": "hi"}).status_code
429
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


@dataclass
class Reply:
    """One scripted answer: status, optional ``Retry-After``, and a stall before it."""

    status: int = 200
    retry_after: float | None = None
    stall: float = 0.0
    body: str = "ok"


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        """Stay quiet when a client gave up (a timeout test)."""


class FakeWebhook:
    """
    A webhook receiver; replies follow ``script``, then 200.

    Parameters
    ----------
    script : list of Reply, optional
        Replies for the first requests, in order.
    """

    def __init__(self, script: list[Reply] | None = None) -> None:
        self.script: list[Reply] = list(script or [])
        self.requests: list[dict[str, Any]] = []
        self.secret = "SECRETHOOK" + secrets.token_hex(6)
        self._lock = threading.Lock()
        self.server = _Server(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        """The webhook URL; its path holds the secret, as Slack's does."""
        port = self.server.server_address[1]
        return f"http://127.0.0.1:{port}/services/T000/B000/{self.secret}"

    def queue(self, *replies: Reply) -> None:
        """Add replies to the end of the script."""
        with self._lock:
            self.script.extend(replies)

    def _next(self) -> Reply:
        with self._lock:
            return self.script.pop(0) if self.script else Reply()

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                reply = fake._next()
                with fake._lock:
                    fake.requests.append(
                        {
                            "path": self.path,
                            "body": json.loads(raw or b"null"),
                            "headers": dict(self.headers),
                        }
                    )
                if reply.stall:
                    time.sleep(reply.stall)
                body = reply.body.encode()
                self.send_response(reply.status)
                if reply.retry_after is not None:
                    self.send_header("Retry-After", str(int(reply.retry_after)))
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:
                return

        return Handler

    def start(self) -> FakeWebhook:
        """Start serving; returns self."""
        self.thread.start()
        return self

    def stop(self) -> None:
        """Stop serving and close the socket."""
        self.server.shutdown()
        self.server.server_close()

    def __enter__(self) -> FakeWebhook:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()
```

Create `tests/fakes/smtp.py`:

```python
"""
A fake SMTP server on 127.0.0.1 built on aiosmtpd, with a trustme CA for TLS.

``mode`` picks plain SMTP, STARTTLS, or implicit TLS; ``user``/``password`` turn
on AUTH PLAIN/LOGIN; ``fail`` scripts a failure. ``connect_421`` and ``stall``
use a raw socket server instead of aiosmtpd.
"""

from __future__ import annotations

import contextlib
import socket
import ssl
import threading
from dataclasses import dataclass
from email import message_from_bytes, policy
from email.message import Message
from typing import Any, Literal

import trustme
from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult, LoginPassword

Mode = Literal["plain", "starttls", "ssl"]
Failure = Literal["auth", "data_451", "data_550", "connect_421", "stall"]


@dataclass
class Received:
    """One accepted message."""

    mail_from: str
    rcpt_tos: list[str]
    message: Message


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _Handler:
    def __init__(self, fake: FakeSmtp) -> None:
        self.fake = fake

    async def handle_DATA(self, server: Any, session: Any, envelope: Any) -> str:
        if self.fake.fail == "data_451":
            return "451 4.3.0 try again later"
        if self.fake.fail == "data_550":
            return "550 5.7.1 message rejected"
        raw = envelope.original_content or envelope.content
        parsed = message_from_bytes(raw, policy=policy.default)  # decoded headers
        self.fake.received.append(Received(envelope.mail_from, list(envelope.rcpt_tos), parsed))
        return "250 OK"


class _RawServer:
    """Greets with 421 and hangs up, or accepts and never says a word."""

    def __init__(self, port: int, fail: Failure) -> None:
        self.fail = fail
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", port))
        self.sock.listen(8)
        self.sock.settimeout(0.1)
        self.stopping = threading.Event()
        self.held: list[socket.socket] = []
        self.thread = threading.Thread(target=self._serve, daemon=True)

    def _serve(self) -> None:
        while not self.stopping.is_set():
            try:
                conn, _ = self.sock.accept()
            except (TimeoutError, OSError):
                continue
            if self.fail == "connect_421":
                with contextlib.suppress(OSError):
                    conn.sendall(b"421 4.3.2 busy, try again later\r\n")
                conn.close()
            else:
                self.held.append(conn)

    def start(self) -> _RawServer:
        self.thread.start()
        return self

    def stop(self) -> None:
        self.stopping.set()
        self.thread.join(2)
        for conn in self.held:
            conn.close()
        self.sock.close()


class FakeSmtp:
    """
    A fake SMTP server on a free 127.0.0.1 port.

    Parameters
    ----------
    mode : {"plain", "starttls", "ssl"}
        Plain SMTP, STARTTLS offered and required, or TLS from the first byte.
    user, password : str, optional
        Turn on AUTH with this login.
    fail : str, optional
        ``auth``, ``data_451``, ``data_550``, ``connect_421``, or ``stall``.
    """

    def __init__(
        self,
        *,
        mode: Mode = "plain",
        user: str | None = None,
        password: str | None = None,
        fail: Failure | None = None,
    ) -> None:
        self.mode = mode
        self.user = user
        self.password = password
        self.fail = fail
        self.received: list[Received] = []
        self.port = _free_port()
        ca = trustme.CA()
        cert = ca.issue_cert("127.0.0.1", "localhost")
        self.server_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        cert.configure_cert(self.server_context)
        self.client_context = ssl.create_default_context()
        ca.configure_trust(self.client_context)
        self._controller: Controller | None = None
        self._raw: _RawServer | None = None

    def _authenticate(
        self, server: Any, session: Any, envelope: Any, mechanism: str, auth_data: Any
    ) -> AuthResult:
        ok = (
            self.fail != "auth"
            and isinstance(auth_data, LoginPassword)
            and auth_data.login.decode() == self.user
            and auth_data.password.decode() == self.password
        )
        return AuthResult(success=ok, handled=False)

    def start(self) -> FakeSmtp:
        """Start serving; returns self."""
        if self.fail in ("connect_421", "stall"):
            self._raw = _RawServer(self.port, self.fail).start()
            return self
        options: dict[str, Any] = {}
        if self.user is not None:
            options["authenticator"] = self._authenticate
            options["auth_require_tls"] = self.mode == "starttls"
        if self.mode == "starttls":
            options["tls_context"] = self.server_context
            options["require_starttls"] = True
        self._controller = Controller(
            _Handler(self),
            hostname="127.0.0.1",
            port=self.port,
            ssl_context=self.server_context if self.mode == "ssl" else None,
            **options,
        )
        self._controller.start()
        return self

    def stop(self) -> None:
        """Stop serving."""
        if self._controller is not None:
            self._controller.stop()
        if self._raw is not None:
            self._raw.stop()

    def __enter__(self) -> FakeSmtp:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/notify/test_fakes.py -v`
Expected: `9 passed`.

Run: `uv run ruff check tests/fakes tests/notify && uv run ruff format --check tests/fakes tests/notify`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add tests/fakes/webhook.py tests/fakes/smtp.py tests/notify
git commit -m "test: fake slack webhook and fake smtp server with tls"
```

---

### Task 14: Notices and how each channel shows them (`hypothex.notify.messages`)

**Files:**
- Create: `src/hypothex/notify/__init__.py`, `src/hypothex/notify/messages.py`
- Test: `tests/notify/test_messages.py`

**Interfaces:**
- Consumes: `run_primary` (Task 8), `compute_cost`, `SweepSummary`, `EmailSettings`, `Channel`.
- Produces (contract 1.7, exact): `NoticeKind`, `Notice`, `run_notice`, `sweep_notice`, `test_notice`, `render_slack`, `render_email`.
- Produces (public helpers): `STATUS_GLYPH = {"finished": "✓", "failed": "✗", "lost": "?", "killed": "⊘"}`; `notice_id(kind, project, ref, status, n=0) -> str` (16 hex of sha256 of the joined fields); `fmt_duration(seconds) -> str` (`45s`, `12m`, `1h05m`, `2d03h`).
- Formats: a run title is `<glyph> <project>/<task> <run_id>` plus `<metric> <value>` (3 decimals) for a finished run with a primary score; its first line is `<created_by> · <gpu_h> GPU-h · $<usd> · <duration>`; a failed run adds `exit <code> · <last stderr line, 200 chars>`, a lost run `lost · no exit record`, a killed run `killed`. A sweep title is `<✓|✗> <project> sweep <id> <done>/<total>` (✗ when any run failed or was lost), its lines `✓<n> ✗<n> ?<n> ⊘<n> · $<usd>` and `best <k=v ...> <mean>`. URLs are `<base>/r/<run_id>` and `<base>/s/<project>/<id>` (no URL without a base). Slack: `{"text": title\nlines…\nurl}`. Email: `Subject` = title, `text/plain` body of the lines and the URL.

- [ ] **Step 1: Write the failing test**

Create `tests/notify/test_messages.py`:

```python
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hypothex.core.context import Context
from hypothex.core.evaluation import evaluate_run
from hypothex.core.records import CostTotals, RunRecord, RunStatus
from hypothex.core.settings import EmailSettings
from hypothex.core.sweeps import SweepParam, SweepSpec, SweepSummary
from hypothex.notify.messages import (
    fmt_duration,
    notice_id,
    render_email,
    render_slack,
    run_notice,
    sweep_notice,
)
from hypothex.notify.messages import test_notice as make_test_notice  # not a test
from tests.factories import PREDS_075, seed_finished_run

T0 = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)
EMAIL = EmailSettings(host="127.0.0.1", sender="hx@lab.org", to=["sv@lab.org", "al@lab.org"])


def ended(ctx: Context, run_id: str, status: RunStatus, *, minutes: float = 12) -> RunRecord:
    def mutate(r: RunRecord) -> RunRecord:
        return r.model_copy(
            update={
                "status": status,
                "started_at": T0,
                "ended_at": T0 + timedelta(minutes=minutes),
                "exit_code": 0 if status == RunStatus.FINISHED else 1,
                "created_by": "human:alice",
                "cost": CostTotals(gpu_hours=0.4, gpu_usd=0.84, total_usd=0.84),
            }
        )

    return ctx.update_run(run_id, f"run.{status.value}", mutate)


@pytest.mark.parametrize(
    ("seconds", "text"), [(45, "45s"), (720, "12m"), (3900, "1h05m"), (183600, "2d03h")]
)
def test_fmt_duration(seconds: float, text: str) -> None:
    assert fmt_duration(seconds) == text


def test_finished_run_notice(ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    evaluate_run(ctx, "r1")
    notice = run_notice(ctx, ended(ctx, "r1", RunStatus.FINISHED), base_url="https://hub.ts.net")
    assert notice.title == "✓ toy/toy-acc r1 accuracy 0.750"
    assert notice.lines == ["human:alice · 0.4 GPU-h · $0.84 · 12m"]
    assert notice.url == "https://hub.ts.net/r/r1"
    assert (notice.kind, notice.project, notice.run_id) == ("run", "toy", "r1")
    assert notice.status == "finished"
    assert notice.id == notice_id("run", "toy", "r1", "finished") and len(notice.id) == 16


def test_failed_run_quotes_the_last_stderr_line(ctx: Context, toy_repo: Path) -> None:
    record = seed_finished_run(ctx, toy_repo, "r2")
    stderr = ctx.run_dir(record) / "logs" / "stderr.log"
    stderr.write_text("warming up\nTraceback ...\nValueError: " + "x" * 300 + "\n\n")
    notice = run_notice(ctx, ended(ctx, "r2", RunStatus.FAILED), base_url=None)
    assert notice.title == "✗ toy/toy-acc r2" and notice.url is None
    assert notice.lines[1].startswith("exit 1 · ValueError: x")
    assert len(notice.lines[1]) == len("exit 1 · ") + 200


@pytest.mark.parametrize(
    ("status", "glyph", "line"),
    [(RunStatus.LOST, "?", "lost · no exit record"), (RunStatus.KILLED, "⊘", "killed")],
)
def test_lost_and_killed(
    ctx: Context, toy_repo: Path, status: RunStatus, glyph: str, line: str
) -> None:
    seed_finished_run(ctx, toy_repo, "r3")
    notice = run_notice(ctx, ended(ctx, "r3", status), base_url=None)
    assert notice.title.startswith(glyph + " ") and notice.lines[-1] == line
    assert notice.id != notice_id("run", "toy", "r3", "finished")


def test_sweep_notice(ctx: Context) -> None:
    spec = SweepSpec(
        id="s-7f3a",
        project="toy",
        task="toy-acc",
        host="gpu1",
        grid=[SweepParam(name="lr", values=["1e-4", "3e-4"])],
        seeds=[1, 2, 3],
        command_template=["python", "train.py", "{lr}"],
        created_by="agent:tuner@sv",
        created_at=T0,
    )
    counts = {"queued": 0, "running": 0, "finished": 4, "failed": 1, "killed": 0, "lost": 1}
    summary = SweepSummary(
        spec=spec,
        counts={**counts, "total": 6},
        cells=[],
        best={"params": {"lr": "3e-4"}, "mean": 0.6131},
        headline="",
        total_usd=12.5,
    )
    notice = sweep_notice(ctx, summary, base_url="https://hub.ts.net")
    assert notice.title == "✗ toy sweep s-7f3a 6/6"
    assert notice.lines == ["✓4 ✗1 ?1 ⊘0 · $12.50", "best lr=3e-4 0.613"]
    assert notice.url == "https://hub.ts.net/s/toy/s-7f3a"
    assert notice.id == notice_id("sweep", "toy", "s-7f3a", "done", 6)


def test_test_notice_and_renderers() -> None:
    notice = make_test_notice("slack")
    assert notice.kind == "test" and notice.title == "✓ hypothex test · slack"
    full = notice.model_copy(update={"lines": ["a · b"], "url": "https://hub/r/x"})
    assert render_slack(full) == {"text": "✓ hypothex test · slack\na · b\nhttps://hub/r/x"}
    email = render_email(full, EMAIL)
    assert email["Subject"] == "✓ hypothex test · slack"
    assert email["From"] == "hx@lab.org" and email["To"] == "sv@lab.org, al@lab.org"
    assert email.get_content_type() == "text/plain"
    assert email.get_content() == "a · b\nhttps://hub/r/x\n"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/notify/test_messages.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'hypothex.notify'`.

- [ ] **Step 3: Write the implementation**

Create `src/hypothex/notify/__init__.py`:

```python
"""Slack and email notices from the hub (phase 3)."""
```

Create `src/hypothex/notify/messages.py`:

```python
"""Notices: what a run, sweep, digest, or test notification says, and how channels show it."""

from __future__ import annotations

import hashlib
from datetime import datetime
from email.message import EmailMessage
from typing import Any, Literal

from pydantic import BaseModel

from hypothex.core.config import parse_metric_key
from hypothex.core.context import Context
from hypothex.core.cost import compute_cost
from hypothex.core.errors import StoreError
from hypothex.core.ids import utcnow
from hypothex.core.notebook import run_primary
from hypothex.core.records import RunRecord, RunStatus
from hypothex.core.settings import Channel, EmailSettings
from hypothex.core.sweeps import SweepSummary

NoticeKind = Literal["run", "sweep", "digest", "test"]
STATUS_GLYPH = {"finished": "✓", "failed": "✗", "lost": "?", "killed": "⊘"}
STDERR_CHARS = 200
STDERR_TAIL_BYTES = 8192


class Notice(BaseModel):
    """One notification, before it is shown on a channel."""

    id: str
    kind: NoticeKind
    project: str | None
    run_id: str | None = None
    sweep_id: str | None = None
    status: str | None = None
    title: str
    lines: list[str]
    url: str | None
    created_at: datetime


def notice_id(
    kind: str, project: str | None, ref: str | None, status: str | None, n: int = 0
) -> str:
    """
    Return the stable id of a notice: one per (kind, project, run/sweep/week, status, n).

    Parameters
    ----------
    kind : str
    project : str or None
    ref : str or None
        Run id, sweep id, or ISO week.
    status : str or None
    n : int
        Run count for a sweep notice.

    Returns
    -------
    str
        16 hex digits.

    Examples
    --------
    >>> notice_id("run", "toy", "r1", "finished") == notice_id("run", "toy", "r1", "finished")
    True
    """
    joined = "\x1f".join([kind, project or "", ref or "", status or "", str(n)])
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def fmt_duration(seconds: float) -> str:
    """
    Format a duration tersely.

    Parameters
    ----------
    seconds : float

    Returns
    -------
    str
        ``45s``, ``12m``, ``1h05m``, or ``2d03h``.

    Examples
    --------
    >>> fmt_duration(3900)
    '1h05m'
    """
    total = max(int(seconds), 0)
    if total < 60:
        return f"{total}s"
    minutes = total // 60
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h{minutes:02d}m"
    days, hours = divmod(hours, 24)
    return f"{days}d{hours:02d}h"


def _primary_text(ctx: Context, record: RunRecord) -> str | None:
    value = run_primary(ctx, record)
    if value is None or record.task is None:
        return None
    try:
        spec = ctx.store.load_project(record.project).config.tasks[record.task]
    except (StoreError, KeyError):
        return None
    metric, key = parse_metric_key(spec.primary)
    name = metric if key == "value" else f"{metric}/{key}"
    return f"{name} {value:.3f}"


def _stderr_tail(ctx: Context, record: RunRecord) -> str | None:
    path = ctx.run_dir(record) / "logs" / "stderr.log"
    try:
        with path.open("rb") as fh:
            size = fh.seek(0, 2)
            fh.seek(max(size - STDERR_TAIL_BYTES, 0))
            text = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1][:STDERR_CHARS] if lines else None


def _url(base_url: str | None, path: str) -> str | None:
    return f"{base_url.rstrip('/')}{path}" if base_url else None


def run_notice(ctx: Context, record: RunRecord, *, base_url: str | None) -> Notice:
    """
    Build the notice of a run that ended.

    Parameters
    ----------
    ctx : Context
    record : RunRecord
        A run in a terminal status.
    base_url : str or None
        ``server.public_url`` (no link when None).

    Returns
    -------
    Notice
        Not yet redacted: the notifier redacts secrets before it stores it.
    """
    status = record.status.value
    primary = _primary_text(ctx, record) if record.status == RunStatus.FINISHED else None
    head = [STATUS_GLYPH.get(status, "·"), f"{record.project}/{record.task or 'exploratory'}"]
    title = " ".join([*head, record.run_id, *([primary] if primary else [])])
    cost = record.cost or compute_cost(record, None)
    wall = None
    if record.started_at is not None and record.ended_at is not None:
        wall = (record.ended_at - record.started_at).total_seconds()
    facts = [
        record.created_by,
        f"{cost.gpu_hours:.1f} GPU-h",
        f"${cost.total_usd:.2f}",
        fmt_duration(wall) if wall is not None else None,
    ]
    lines = [" · ".join(f for f in facts if f)]
    if record.status == RunStatus.FAILED:
        tail = _stderr_tail(ctx, record)
        lines.append(f"exit {record.exit_code}" + (f" · {tail}" if tail else ""))
    elif record.status == RunStatus.LOST:
        lines.append("lost · no exit record")
    elif record.status == RunStatus.KILLED:
        lines.append("killed")
    return Notice(
        id=notice_id("run", record.project, record.run_id, status),
        kind="run",
        project=record.project,
        run_id=record.run_id,
        status=status,
        title=title,
        lines=lines,
        url=_url(base_url, f"/r/{record.run_id}"),
        created_at=utcnow(),
    )


def sweep_notice(ctx: Context, summary: SweepSummary, *, base_url: str | None) -> Notice:
    """
    Build the one notice of a sweep whose runs have all ended.

    Parameters
    ----------
    ctx : Context
    summary : SweepSummary
    base_url : str or None

    Returns
    -------
    Notice
    """
    counts, spec = summary.counts, summary.spec
    done = sum(counts.get(k, 0) for k in ("finished", "failed", "lost", "killed"))
    total = counts.get("total", done)
    bad = counts.get("failed", 0) + counts.get("lost", 0)
    lines = [
        f"✓{counts.get('finished', 0)} ✗{counts.get('failed', 0)} ?{counts.get('lost', 0)} "
        f"⊘{counts.get('killed', 0)} · ${summary.total_usd:.2f}"
    ]
    best: dict[str, Any] | None = summary.best
    if best:
        params = " ".join(f"{k}={v}" for k, v in best.get("params", {}).items())
        mean = best.get("mean")
        lines.append(f"best {params} {mean:.3f}" if mean is not None else f"best {params}")
    return Notice(
        id=notice_id("sweep", spec.project, spec.id, "done", total),
        kind="sweep",
        project=spec.project,
        sweep_id=spec.id,
        status="done",
        title=f"{'✗' if bad else '✓'} {spec.project} sweep {spec.id} {done}/{total}",
        lines=lines,
        url=_url(base_url, f"/s/{spec.project}/{spec.id}"),
        created_at=utcnow(),
    )


def test_notice(channel: Channel) -> Notice:
    """
    Build a test notice for one channel (``hx notify test``).

    Parameters
    ----------
    channel : Channel

    Returns
    -------
    Notice
    """
    now = utcnow()
    return Notice(
        id=notice_id("test", None, channel, now.isoformat()),
        kind="test",
        project=None,
        title=f"✓ hypothex test · {channel}",
        lines=[],
        url=None,
        created_at=now,
    )


def render_slack(notice: Notice) -> dict[str, Any]:
    """
    Show a notice as a Slack incoming-webhook payload.

    Parameters
    ----------
    notice : Notice

    Returns
    -------
    dict
        ``{"text": "<title>\\n<lines...>\\n<url>"}``.
    """
    parts = [notice.title, *notice.lines, *([notice.url] if notice.url else [])]
    return {"text": "\n".join(parts)}


def render_email(notice: Notice, settings: EmailSettings) -> EmailMessage:
    """
    Show a notice as a plain-text email.

    Parameters
    ----------
    notice : Notice
    settings : EmailSettings
        Sender and recipients.

    Returns
    -------
    EmailMessage
        ``Subject`` = the title; body = the lines and the URL.
    """
    message = EmailMessage()
    message["Subject"] = notice.title
    message["From"] = settings.sender
    message["To"] = ", ".join(settings.to)
    body = "\n".join([*notice.lines, *([notice.url] if notice.url else [])])
    message.set_content((body or notice.title) + "\n")
    return message
```

The test module imports `test_notice` under another name (`make_test_notice`): pytest collects every module-level function whose name starts with `test`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/notify/test_messages.py -v`
Expected: `10 passed`.

Run: `uv run python -m doctest src/hypothex/notify/messages.py && uv run ruff check src/hypothex/notify tests/notify && uv run ruff format --check src/hypothex/notify tests/notify && uv run ty check src`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/notify tests/notify/test_messages.py
git commit -m "feat(notify): run, sweep, and test notices with slack and email renderings"
```

---

### Task 15: Channels — Slack and SMTP delivery with redacted errors

**Files:**
- Create: `src/hypothex/notify/channels.py`
- Test: `tests/notify/test_channels.py`

**Interfaces:**
- Produces (contract 1.7, exact): `ChannelError` (`permanent`, `retry_after`, `error_class`; `str(exc) == error_class`), `send_slack(webhook, payload, *, timeout=10)`, `send_email(settings, password, message)`, `redact(text, secrets)`.
- Produces (additive keywords): `send_slack(..., transport: httpx.BaseTransport | None = None)`; `send_email(..., ssl_context: ssl.SSLContext | None = None)` (tests trust the fake's CA).
- Rules: webhooks must be `https://` unless the host is loopback (`insecure_webhook`, permanent, no request sent). Slack 2xx ok; 429 (with `Retry-After`) and 5xx retryable (`http_<code>`); other 4xx permanent; timeouts `timeout` and transport errors `transport` retryable. SMTP auth failures and 5xx permanent (`smtp_<code>`); 4xx (including a 421 greeting) retryable; a server without STARTTLS `smtp_no_starttls` and TLS errors `tls` permanent; timeouts `timeout`, connection errors `connection` retryable. Every `ChannelError` is raised `from None` so no library message (with a URL or a login) rides along, and while a webhook call runs, log records of `httpx`/`httpcore` that quote the webhook path are dropped (httpx logs each request URL at INFO).

- [ ] **Step 1: Write the failing test**

Create `tests/notify/test_channels.py`:

```python
import logging
from email.message import EmailMessage

import pytest
from pydantic import SecretStr

from hypothex.core.settings import EmailSettings
from hypothex.notify.channels import ChannelError, redact, send_email, send_slack
from tests.fakes.smtp import FakeSmtp
from tests.fakes.webhook import FakeWebhook, Reply


def message() -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = "✓ toy r1", "hx@lab.org", "sv@lab.org"
    msg.set_content("line\n")
    return msg


def email(smtp: FakeSmtp, **over: object) -> EmailSettings:
    base: dict[str, object] = {
        "host": "127.0.0.1",
        "port": smtp.port,
        "security": "none",
        "password_env": None,
        "sender": "hx@lab.org",
        "to": ["sv@lab.org"],
        "timeout": 5,
    }
    return EmailSettings.model_validate({**base, **over})


def test_slack_ok() -> None:
    with FakeWebhook() as hook:
        send_slack(SecretStr(hook.url), {"text": "✓ toy"})
        assert hook.requests[0]["body"] == {"text": "✓ toy"}


@pytest.mark.parametrize(
    ("reply", "error_class", "permanent", "retry_after"),
    [
        (Reply(429, retry_after=7), "http_429", False, 7.0),
        (Reply(500), "http_500", False, None),
        (Reply(503), "http_503", False, None),
        (Reply(404), "http_404", True, None),
        (Reply(410), "http_410", True, None),
    ],
)
def test_slack_errors(
    reply: Reply, error_class: str, permanent: bool, retry_after: float | None
) -> None:
    with FakeWebhook([reply]) as hook:
        with pytest.raises(ChannelError) as info:
            send_slack(SecretStr(hook.url), {"text": "x"})
        exc = info.value
        assert (exc.error_class, exc.permanent, exc.retry_after) == (
            error_class,
            permanent,
            retry_after,
        )
        assert str(exc) == error_class and hook.secret not in str(exc)
        assert exc.__cause__ is None and exc.__suppress_context__


def test_slack_url_never_reaches_the_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    with FakeWebhook() as hook:
        send_slack(SecretStr(hook.url), {"text": "x"})
    assert hook.secret not in caplog.text


def test_slack_timeout_is_retryable() -> None:
    with FakeWebhook([Reply(stall=2.0)]) as hook, pytest.raises(ChannelError) as info:
        send_slack(SecretStr(hook.url), {"text": "x"}, timeout=0.3)
    assert info.value.error_class == "timeout" and not info.value.permanent


def test_plain_http_off_loopback_is_refused_without_a_request() -> None:
    with pytest.raises(ChannelError) as info:
        send_slack(SecretStr("http://hooks.example.com/services/T/B/SECRET"), {"text": "x"})
    assert info.value.error_class == "insecure_webhook" and info.value.permanent


@pytest.mark.parametrize("mode", ["plain", "starttls", "ssl"])
def test_email_ok_in_every_mode(mode: str) -> None:
    security = {"plain": "none", "starttls": "starttls", "ssl": "ssl"}[mode]
    with FakeSmtp(mode=mode, user="sv", password="pw") as smtp:  # type: ignore[arg-type]
        settings = email(smtp, security=security, username="sv")
        send_email(settings, SecretStr("pw"), message(), ssl_context=smtp.client_context)
        assert smtp.received[0].message["Subject"] == "✓ toy r1"


@pytest.mark.parametrize(
    ("fail", "error_class", "permanent"),
    [
        ("auth", "smtp_535", True),
        ("data_451", "smtp_451", False),
        ("data_550", "smtp_550", True),
        ("connect_421", "smtp_421", False),
    ],
)
def test_email_errors(fail: str, error_class: str, permanent: bool) -> None:
    with FakeSmtp(user="sv", password="pw", fail=fail) as smtp:  # type: ignore[arg-type]
        with pytest.raises(ChannelError) as info:
            send_email(email(smtp, username="sv"), SecretStr("pw"), message())
        assert (info.value.error_class, info.value.permanent) == (error_class, permanent)
        assert "pw" not in str(info.value)


def test_email_stall_times_out() -> None:
    with FakeSmtp(fail="stall") as smtp, pytest.raises(ChannelError) as info:
        send_email(email(smtp, timeout=0.5), None, message())
    assert (info.value.error_class, info.value.permanent) == ("timeout", False)


def test_starttls_missing_is_permanent() -> None:
    with FakeSmtp() as smtp, pytest.raises(ChannelError) as info:
        send_email(email(smtp, security="starttls"), None, message())
    assert (info.value.error_class, info.value.permanent) == ("smtp_no_starttls", True)


def test_redact_values_and_webhook_paths() -> None:
    hook = "https://hooks.slack.com/services/T0/B0/SECRETXYZ"
    text = f"POST {hook} failed; path /services/T0/B0/SECRETXYZ; pw hunter2"
    assert redact(text, [SecretStr(hook), "hunter2", None]) == "POST *** failed; path ***; pw ***"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/notify/test_channels.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'hypothex.notify.channels'`.

- [ ] **Step 3: Write the implementation**

Create `src/hypothex/notify/channels.py`:

```python
"""Slack and SMTP delivery; every failure leaves as an error class, never a secret."""

from __future__ import annotations

import logging
import smtplib
import ssl
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from email.message import EmailMessage
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from hypothex.core.errors import HypothexError
from hypothex.core.settings import EmailSettings, is_loopback_host


class ChannelError(HypothexError):
    """
    A delivery failed; the message is only the error class (no URL, no login).

    Parameters
    ----------
    error_class : str
        ``http_429``, ``smtp_535``, ``timeout``, ``unset:<VAR>``, ...
    permanent : bool
        True when retrying cannot help.
    retry_after : float, optional
        Seconds the server asked to wait (Slack ``Retry-After``).
    """

    def __init__(
        self, error_class: str, *, permanent: bool, retry_after: float | None = None
    ) -> None:
        super().__init__(error_class)
        self.error_class = error_class
        self.permanent = permanent
        self.retry_after = retry_after


def redact(text: str, secrets: Iterable[SecretStr | str | None]) -> str:
    """
    Replace every secret value, and the path of a webhook URL, with ``***``.

    Parameters
    ----------
    text : str
        Any text that may quote a secret.
    secrets : iterable of SecretStr, str, or None
        Values to hide; None and empty values are skipped.

    Returns
    -------
    str

    Examples
    --------
    >>> redact("pw=hunter2", ["hunter2"])
    'pw=***'
    """
    out = text
    for secret in secrets:
        if secret is None:
            continue
        value = secret.get_secret_value() if isinstance(secret, SecretStr) else secret
        if not value:
            continue
        out = out.replace(value, "***")
        try:
            path = urlsplit(value).path
        except ValueError:
            path = ""
        if len(path) > 1:
            out = out.replace(path, "***")
    return out


class _DropSecret(logging.Filter):
    """Drop log records that quote a secret (httpx logs every request URL at INFO)."""

    def __init__(self, secret: str) -> None:
        super().__init__()
        self.secret = secret

    def filter(self, record: logging.LogRecord) -> bool:
        """Keep a record unless its message holds the secret."""
        return self.secret not in record.getMessage()


@contextmanager
def _quiet(secret: str) -> Iterator[None]:
    """Keep ``secret`` out of the ``httpx`` and ``httpcore`` logs for one call."""
    drop = _DropSecret(secret)
    loggers = [logging.getLogger(name) for name in ("httpx", "httpcore")]
    for logger in loggers:
        logger.addFilter(drop)
    try:
        yield
    finally:
        for logger in loggers:
            logger.removeFilter(drop)


def _retry_after(header: str | None) -> float | None:
    try:
        return float(header) if header is not None else None
    except ValueError:
        return None


def send_slack(
    webhook: SecretStr,
    payload: dict[str, Any],
    *,
    timeout: float = 10,
    transport: httpx.BaseTransport | None = None,
) -> None:
    """
    POST a payload to a Slack incoming webhook.

    Parameters
    ----------
    webhook : SecretStr
        The webhook URL; ``https://`` unless the host is loopback.
    payload : dict
        JSON body (``render_slack``).
    timeout : float
        Seconds.
    transport : httpx.BaseTransport, optional
        For tests.

    Raises
    ------
    ChannelError
        ``insecure_webhook``/``bad_webhook`` (permanent, nothing sent),
        ``http_429``/``http_5xx``/``timeout``/``transport`` (retryable), other
        ``http_4xx`` (permanent).
    """
    url = webhook.get_secret_value()
    try:
        parts = urlsplit(url)
    except ValueError:
        raise ChannelError("bad_webhook", permanent=True) from None
    local = parts.scheme == "http" and is_loopback_host(parts.hostname or "")
    if parts.scheme != "https" and not local:
        raise ChannelError("insecure_webhook", permanent=True) from None
    try:
        with (
            _quiet(parts.path or url),
            httpx.Client(timeout=timeout, transport=transport, follow_redirects=False) as client,
        ):
            resp = client.post(url, json=payload)
    except httpx.TimeoutException:
        raise ChannelError("timeout", permanent=False) from None
    except httpx.HTTPError:
        raise ChannelError("transport", permanent=False) from None
    if 200 <= resp.status_code < 300:
        return
    error = f"http_{resp.status_code}"
    if resp.status_code == 429 or resp.status_code >= 500:
        retry = _retry_after(resp.headers.get("Retry-After"))
        raise ChannelError(error, permanent=False, retry_after=retry) from None
    raise ChannelError(error, permanent=True) from None


def send_email(
    settings: EmailSettings,
    password: SecretStr | None,
    message: EmailMessage,
    *,
    ssl_context: ssl.SSLContext | None = None,
) -> None:
    """
    Send one email over SMTP (STARTTLS, implicit TLS, or plain on loopback).

    Parameters
    ----------
    settings : EmailSettings
        Server, security, login name.
    password : SecretStr or None
        The SMTP password (needed when ``settings.username`` is set).
    message : EmailMessage
        The message (``render_email``).
    ssl_context : ssl.SSLContext, optional
        Default: the system trust store.

    Raises
    ------
    ChannelError
        ``smtp_<code>`` (5xx and auth permanent, 4xx retryable),
        ``smtp_no_starttls`` and ``tls`` (permanent), ``timeout`` and
        ``connection`` (retryable).
    """
    context = ssl_context or ssl.create_default_context()
    try:
        if settings.security == "ssl":
            client: smtplib.SMTP = smtplib.SMTP_SSL(
                settings.host, settings.port, timeout=settings.timeout, context=context
            )
        else:
            client = smtplib.SMTP(settings.host, settings.port, timeout=settings.timeout)
        with client:
            if settings.security == "starttls":
                client.starttls(context=context)
            if settings.username:
                secret = password.get_secret_value() if password is not None else ""
                client.login(settings.username, secret)
            client.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        raise ChannelError(f"smtp_{exc.smtp_code}", permanent=True) from None
    except smtplib.SMTPRecipientsRefused as exc:
        codes = sorted({code for code, _ in exc.recipients.values()})
        code = codes[0] if codes else 550
        raise ChannelError(f"smtp_{code}", permanent=code >= 500) from None
    except smtplib.SMTPResponseException as exc:
        raise ChannelError(f"smtp_{exc.smtp_code}", permanent=exc.smtp_code >= 500) from None
    except smtplib.SMTPNotSupportedError:
        raise ChannelError("smtp_no_starttls", permanent=True) from None
    except smtplib.SMTPServerDisconnected as exc:
        # smtplib reports a read timeout as "Connection unexpectedly closed: timed out"
        error = "timeout" if "timed out" in str(exc) else "connection"
        raise ChannelError(error, permanent=False) from None
    except TimeoutError:
        raise ChannelError("timeout", permanent=False) from None
    except ssl.SSLError:
        raise ChannelError("tls", permanent=True) from None
    except (smtplib.SMTPException, OSError):
        raise ChannelError("connection", permanent=False) from None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/notify/test_channels.py -v`
Expected: `19 passed`.

Run: `uv run python -m doctest src/hypothex/notify/channels.py && uv run ruff check src/hypothex/notify tests/notify && uv run ruff format --check src/hypothex/notify tests/notify && uv run ty check src`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/notify/channels.py tests/notify/test_channels.py
git commit -m "feat(notify): slack and smtp delivery with retryable and permanent error classes"
```

---
### Task 16: Notifier outbox and event scan

**Files:**
- Create: `src/hypothex/notify/notifier.py`
- Modify: `src/hypothex/core/sweeps.py` (`sweep_issuing`)
- Test: `tests/notify/test_notifier.py`

**Interfaces:**
- Consumes: `EventLog.since/last_sequence`, `Context.find_record`, `summarize_sweep`, `sweep_combos`, `sweep_tag`, `run_notice`, `sweep_notice`, `redact`, `resolve_secret`, `write_private`, `Settings`.
- Produces (contract 1.7, exact): `NOTIFY_DIR`, `RETRY_DELAYS`, `TERMINAL_EVENTS`, `OutboxEntry`, `Notifier(ctx, settings, *, now=utcnow, transport=None)` with `scan()`.
- Produces (additive): `Notifier(..., ssl_context=None)`; `Notifier.enqueue(notice, channels) -> list[OutboxEntry]` (redacts the notice itself, so no caller can skip it; idempotent per `(notice.id, channel)`; only configured channels; used by the digest, Task 19); `hypothex.core.sweeps.sweep_issuing(layout, project, sweep_id) -> bool` (True while `launch_sweep` or `extend_sweep` holds the sweep's lock to issue runs); `Notifier.secret_values() -> list[SecretStr]`; `SENDING_RETRY_SECONDS = 60.0`.
- Files (contract 2): `<home>/notify/pending-sweeps.json` (sweep key → terminal `Event`, persisted before cursor advancement; retried each scan and after restart until settled or excluded by current notification policy), `<home>/notify/cursor.json` `{last_sequence}`, `outbox/<id>.<channel>.json` (one `OutboxEntry`, rewritten atomically), `sent.jsonl` (final entries) — all 0600.
- Rules: the first scan sets the cursor to the log's last sequence and enqueues nothing (no backlog flood). A run notifies on `run.finished|failed|killed|lost`, or on `mirror.run_updated` whose `original_type` is one of them. Its project's rule is `notify.projects[project]`, else `notify.default`, else nothing. A run that ended more than `max_age_hours` before now gets nothing. With `fold_sweeps` and a `sweep_id` whose sweep file is on this hub and whose run carries this hub's member tag `sweep:<owner8>:<id>` (a mirrored run of another hub's sweep with the same id is not a member and is notified as a run), nothing is sent while the sweep has a queued or running run, nor while it has fewer members than `len(sweep_combos(spec)) * len(spec.seeds)` and `sweep_issuing` says its launch is still issuing runs (a short first run ending before the last launch must not read `1/1`); when none of that holds, one sweep notice (the same id for every final event, so one entry) if at least one of its runs ended with a status in `rule.events` (a failure-only rule hears only about sweeps with a failure; `events: []` hears nothing); the sweep's summary is read once per event batch, after the batch is fetched, never kept across batches (a sweep whose last run ends between two batches still notifies). Otherwise the run's status must be in `rule.events`, and a finished run shorter than `min_seconds` is skipped. Notices are redacted (every configured secret value) by `enqueue` before they are written, whatever enqueues them (run, sweep, digest).

- [ ] **Step 1: Write the failing test**

Create `tests/notify/test_notifier.py`:

```python
import fcntl
import json
import stat
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hypothex.core.context import Context
from hypothex.core.events import Event
from hypothex.core.records import RunRecord, RunStatus
from hypothex.core.settings import (
    EmailSettings,
    NotifySettings,
    ProjectRule,
    Settings,
    SlackSettings,
)
from hypothex.core.sweeps import (
    SweepParam,
    SweepSpec,
    save_sweep,
    sweep_issuing,
    sweep_path,
    sweep_tag,
)
from hypothex.notify.notifier import Notifier, OutboxEntry
from tests.factories import make_record
from tests.fakes.smtp import FakeSmtp
from tests.fakes.webhook import FakeWebhook

T0 = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.t = T0 + timedelta(hours=1)

    def __call__(self) -> datetime:
        return self.t

    def tick(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def hook(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeWebhook]:
    with FakeWebhook() as fake:
        monkeypatch.setenv("HX_TEST_HOOK", fake.url)
        yield fake


@pytest.fixture
def smtp() -> Iterator[FakeSmtp]:
    with FakeSmtp() as fake:
        yield fake


@pytest.fixture
def toy(ctx: Context, toy_repo: Path) -> Context:
    ctx.register_project(toy_repo)
    return ctx


def settings_for(
    smtp: FakeSmtp | None = None,
    *,
    project: str = "toy",
    default: ProjectRule | None = None,
    **rule: object,
) -> Settings:
    email = None
    if smtp is not None:
        email = EmailSettings(
            host="127.0.0.1",
            port=smtp.port,
            security="none",
            password_env=None,
            sender="hx@lab.org",
            to=["sv@lab.org"],
            timeout=5,
        )
    channels = ["slack", "email"] if smtp is not None else ["slack"]
    return Settings(
        notify=NotifySettings(
            slack=SlackSettings(webhook_env="HX_TEST_HOOK"),
            email=email,
            projects={project: ProjectRule.model_validate({"channels": channels, **rule})},
            default=default,
        )
    )


def end_run(
    ctx: Context,
    run_id: str,
    status: str,
    *,
    minutes: float = 10,
    ended: datetime = T0,
    project: str = "toy",
    tags: list[str] | None = None,
    sweep_id: str | None = None,
) -> RunRecord:
    ctx.create_run(
        make_record(
            run_id,
            project=project,
            task="toy-acc",
            status=RunStatus.RUNNING,
            started_at=ended - timedelta(minutes=minutes),
            environment_id=ctx.descriptor.environment_id,
            tags=tags or [],
            sweep_id=sweep_id,
        )
    )
    return ctx.update_run(
        run_id,
        f"run.{status}",
        lambda r: r.model_copy(
            update={"status": RunStatus(status), "ended_at": ended, "exit_code": 0}
        ),
    )


def primed(ctx: Context, settings: Settings, clock: Clock) -> Notifier:
    notifier = Notifier(ctx, settings, now=clock)
    assert notifier.scan() == []  # first start: cursor at the end of the log
    return notifier


def test_first_start_skips_the_backlog(toy: Context, hook: FakeWebhook, clock: Clock) -> None:
    end_run(toy, "old", "finished")
    notifier = primed(toy, settings_for(), clock)
    assert json.loads((toy.layout.home / "notify" / "cursor.json").read_text()) == {
        "last_sequence": toy.events.last_sequence()
    }
    end_run(toy, "new", "finished")
    (entry,) = notifier.scan()
    assert entry.notice.run_id == "new" and entry.channel == "slack" and entry.status == "pending"


def test_each_ending_enqueues_once_per_channel(
    toy: Context, hook: FakeWebhook, smtp: FakeSmtp, clock: Clock
) -> None:
    notifier = primed(toy, settings_for(smtp), clock)
    for run_id, status in (("a", "finished"), ("b", "failed"), ("c", "lost")):
        end_run(toy, run_id, status)
    made = notifier.scan()
    assert sorted((e.notice.run_id, e.channel) for e in made) == [
        ("a", "email"), ("a", "slack"), ("b", "email"), ("b", "slack"), ("c", "email"),
        ("c", "slack"),
    ]  # fmt: skip
    assert notifier.scan() == []
    toy.events.append("run.lost", project="toy", run_id="c", payload={})  # a repeated event
    assert notifier.scan() == []


def test_unlisted_projects_get_nothing_unless_a_default(
    toy: Context, hook: FakeWebhook, clock: Clock
) -> None:
    notifier = primed(toy, settings_for(project="other"), clock)
    end_run(toy, "a", "failed")
    assert notifier.scan() == []
    notifier.settings = settings_for(project="other", default=ProjectRule())
    end_run(toy, "b", "failed")
    assert [e.notice.run_id for e in notifier.scan()] == ["b"]


def test_events_and_min_seconds(toy: Context, hook: FakeWebhook, clock: Clock) -> None:
    notifier = primed(toy, settings_for(events=["finished", "failed"], min_seconds=600), clock)
    end_run(toy, "short", "finished", minutes=5)
    end_run(toy, "long", "finished", minutes=10)
    end_run(toy, "crash", "failed", minutes=1)
    end_run(toy, "gone", "lost")
    assert sorted(e.notice.run_id for e in notifier.scan()) == ["crash", "long"]


def test_mirrored_runs_notify_from_the_mirror_event(
    toy: Context, hook: FakeWebhook, clock: Clock
) -> None:
    notifier = primed(toy, settings_for(), clock)
    toy.create_run(
        make_record(
            "remote1",
            task="toy-acc",
            status=RunStatus.FAILED,
            environment_id="env-gpu1",
            started_at=T0 - timedelta(minutes=3),
            ended_at=T0,
        )
    )
    toy.events.append(
        "mirror.run_updated",
        project="toy",
        run_id="remote1",
        payload={"host": "gpu1", "original_type": "run.started", "status": "running"},
    )
    assert notifier.scan() == []
    toy.events.append(
        "mirror.run_updated",
        project="toy",
        run_id="remote1",
        payload={"host": "gpu1", "original_type": "run.failed", "status": "failed"},
    )
    (entry,) = notifier.scan()
    assert entry.notice.run_id == "remote1" and entry.notice.status == "failed"


def test_runs_that_ended_long_ago_are_skipped(
    toy: Context, hook: FakeWebhook, clock: Clock
) -> None:
    notifier = primed(toy, settings_for(), clock)
    end_run(toy, "late", "finished", ended=clock() - timedelta(hours=25))
    assert notifier.scan() == []


def test_sweep_gives_one_notice_when_its_last_run_ends(
    toy: Context, hook: FakeWebhook, clock: Clock
) -> None:
    spec = SweepSpec(
        id="s-0001",
        project="toy",
        task="toy-acc",
        host=None,
        grid=[SweepParam(name="x", values=[str(i) for i in range(200)])],
        seeds=[1],
        command_template=["echo", "{x}"],
        created_by="human:sv",
        created_at=T0,
    )
    save_sweep(toy.layout, spec)
    tag = sweep_tag(toy.descriptor.environment_id, spec.id)
    notifier = primed(toy, settings_for(), clock)
    for i in range(200):
        toy.create_run(
            make_record(
                f"sw{i:03d}",
                task="toy-acc",
                status=RunStatus.QUEUED,
                environment_id=toy.descriptor.environment_id,
                tags=[tag],
                sweep_id=spec.id,
            )
        )
    for i in range(199):
        status = RunStatus.FAILED if i % 50 == 0 else RunStatus.FINISHED
        toy.update_run(
            f"sw{i:03d}",
            f"run.{status.value}",
            lambda r, s=status: r.model_copy(update={"status": s, "ended_at": T0}),
        )
    assert notifier.scan() == []  # one run still queued
    toy.update_run(
        "sw199",
        "run.finished",
        lambda r: r.model_copy(update={"status": RunStatus.FINISHED, "ended_at": T0}),
    )
    (entry,) = notifier.scan()
    assert entry.notice.kind == "sweep" and entry.notice.title == "✗ toy sweep s-0001 200/200"
    assert entry.notice.lines[0].startswith("✓196 ✗4 ?0 ⊘0")


def test_a_sweep_that_ends_between_scan_batches_still_notifies(
    toy: Context, hook: FakeWebhook, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("hypothex.notify.notifier.SCAN_BATCH", 1)
    spec = SweepSpec(
        id="s-0009", project="toy", task="toy-acc", host=None,
        grid=[SweepParam(name="x", values=["1", "2"])], seeds=[1],
        command_template=["echo", "{x}"], created_by="human:sv", created_at=T0,
    )  # fmt: skip
    save_sweep(toy.layout, spec)
    tag = sweep_tag(toy.descriptor.environment_id, spec.id)
    for run_id in ("y0", "y1"):
        toy.create_run(
            make_record(
                run_id, task="toy-acc", status=RunStatus.QUEUED, tags=[tag],
                environment_id=toy.descriptor.environment_id, sweep_id=spec.id,
            )
        )  # fmt: skip
    notifier = primed(toy, settings_for(), clock)

    def finish(run_id: str) -> None:
        toy.update_run(
            run_id,
            "run.finished",
            lambda r: r.model_copy(update={"status": RunStatus.FINISHED, "ended_at": T0}),
        )

    finish("y0")  # batch 1: y0 ended, y1 still queued
    real_since = toy.events.since
    calls = {"n": 0}

    def since(after: int, limit: int) -> list[Event]:
        calls["n"] += 1
        if calls["n"] == 2:
            finish("y1")  # the last run ends while batch 1 is being read
        return real_since(after, limit)

    monkeypatch.setattr(toy.events, "since", since)
    (entry,) = notifier.scan()
    assert entry.notice.kind == "sweep" and entry.notice.sweep_id == "s-0009"


def test_folded_sweeps_follow_the_rule_events(
    toy: Context, hook: FakeWebhook, clock: Clock
) -> None:
    def sweep(sweep_id: str, statuses: list[RunStatus]) -> None:
        values = [str(i) for i in range(len(statuses))]
        spec = SweepSpec(
            id=sweep_id, project="toy", task="toy-acc", host=None,
            grid=[SweepParam(name="x", values=values)], seeds=[1],
            command_template=["echo", "{x}"], created_by="human:sv", created_at=T0,
        )  # fmt: skip
        save_sweep(toy.layout, spec)
        tag = sweep_tag(toy.descriptor.environment_id, sweep_id)
        for i, status in enumerate(statuses):
            run_id = f"x{sweep_id[-1]}{i}"
            toy.create_run(
                make_record(
                    run_id, task="toy-acc", status=RunStatus.QUEUED, tags=[tag],
                    environment_id=toy.descriptor.environment_id, sweep_id=sweep_id,
                )
            )  # fmt: skip
            toy.update_run(
                run_id,
                f"run.{status.value}",
                lambda r, s=status: r.model_copy(update={"status": s, "ended_at": T0}),
            )

    notifier = primed(toy, settings_for(events=["failed", "lost"]), clock)
    sweep("s-0002", [RunStatus.FINISHED, RunStatus.FINISHED])
    assert notifier.scan() == []  # all finished: a failure-only rule hears nothing
    sweep("s-0003", [RunStatus.FINISHED, RunStatus.FAILED])
    (entry,) = notifier.scan()
    assert entry.notice.kind == "sweep" and entry.notice.sweep_id == "s-0003"
    notifier.settings = settings_for(events=[])
    sweep("s-0004", [RunStatus.FAILED])
    assert notifier.scan() == []


def small_sweep(ctx: Context, sweep_id: str, n: int) -> str:
    spec = SweepSpec(
        id=sweep_id, project="toy", task="toy-acc", host=None,
        grid=[SweepParam(name="x", values=[str(i) for i in range(n)])], seeds=[1],
        command_template=["echo", "{x}"], created_by="human:sv", created_at=T0,
    )  # fmt: skip
    save_sweep(ctx.layout, spec)
    return sweep_tag(ctx.descriptor.environment_id, sweep_id)


def test_a_foreign_sweep_with_the_same_id_is_not_folded(
    toy: Context, hook: FakeWebhook, clock: Clock
) -> None:
    mine = small_sweep(toy, "s-0005", 2)
    toy.create_run(
        make_record(
            "own0", task="toy-acc", status=RunStatus.QUEUED, tags=[mine],
            environment_id=toy.descriptor.environment_id, sweep_id="s-0005",
        )
    )  # fmt: skip
    notifier = primed(toy, settings_for(), clock)
    # another hub's sweep s-0005, mirrored here from a host both hubs use
    foreign = sweep_tag("ffffffff00000000", "s-0005")
    end_run(toy, "far0", "failed", tags=[foreign], sweep_id="s-0005")
    (entry,) = notifier.scan()
    assert entry.notice.kind == "run" and entry.notice.run_id == "far0"


def test_a_sweep_still_launching_waits_for_its_last_run(
    toy: Context, hook: FakeWebhook, clock: Clock
) -> None:
    tag = small_sweep(toy, "s-0006", 2)
    notifier = primed(toy, settings_for(), clock)
    lock = sweep_path(toy.layout, "toy", "s-0006").with_suffix(".lock")
    with lock.open("a") as fh:  # launch_sweep holds the sweep's lock while it issues runs
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        assert sweep_issuing(toy.layout, "toy", "s-0006")
        end_run(toy, "q0", "finished", tags=[tag], sweep_id="s-0006")  # a short first run
        assert notifier.scan() == []  # 1 of 2 runs exists: never "1/1"
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    assert not sweep_issuing(toy.layout, "toy", "s-0006")
    end_run(toy, "q1", "finished", tags=[tag], sweep_id="s-0006")
    (entry,) = notifier.scan()
    assert entry.notice.title == "✓ toy sweep s-0006 2/2"
    # a launch that failed after one run: nothing is issuing, so what exists is final
    part = small_sweep(toy, "s-0007", 3)
    end_run(toy, "p0", "failed", tags=[part], sweep_id="s-0007")
    (partial,) = notifier.scan()
    assert partial.notice.title == "✗ toy sweep s-0007 1/1"


def test_partial_sweep_notifies_after_issuance_failure_without_new_events(
    toy: Context, hook: FakeWebhook, clock: Clock
) -> None:
    tag = small_sweep(toy, "s-0008", 3)
    settings = settings_for()
    notifier = primed(toy, settings, clock)
    lock = sweep_path(toy.layout, "toy", "s-0008").with_suffix(".lock")
    with lock.open("a") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        end_run(toy, "partial0", "failed", tags=[tag], sweep_id="s-0008")
        assert notifier.scan() == []
        cursor = toy.events.last_sequence()
        pending = toy.layout.home / "notify" / "pending-sweeps.json"
        assert json.loads(pending.read_text())
        assert stat.S_IMODE(pending.stat().st_mode) == 0o600
        toy.events.append("run.created", project="toy", run_id="partial0", payload={})
        assert notifier.scan() == []
        assert json.loads(pending.read_text())  # unrelated nonterminal event cannot erase it
        cursor = toy.events.last_sequence()
        # Restart while still issuing. It must neither lose the trigger nor emit early.
        notifier = Notifier(toy, settings, now=clock)
        assert notifier.scan() == []
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)  # later launch failed, no further run exists
    assert toy.events.last_sequence() == cursor
    (entry,) = notifier.scan()
    assert entry.notice.title == "✗ toy sweep s-0008 1/1"
    assert json.loads(pending.read_text()) == {}
    assert notifier.scan() == []
    assert Notifier(toy, settings, now=clock).scan() == []


def test_unconfigured_channels_are_not_enqueued(
    toy: Context, hook: FakeWebhook, clock: Clock
) -> None:
    settings = settings_for()
    settings.notify.projects["toy"] = ProjectRule(channels=["slack", "email"])
    notifier = primed(toy, settings, clock)
    end_run(toy, "a", "failed")
    assert [e.channel for e in notifier.scan()] == ["slack"]


def test_stored_notices_are_redacted(toy: Context, hook: FakeWebhook, clock: Clock) -> None:
    notifier = primed(toy, settings_for(), clock)
    record = end_run(toy, "leaky", "failed")
    (toy.run_dir(record) / "logs" / "stderr.log").write_text(f"POST {hook.url} -> 500\n")
    toy.events.append("run.failed", project="toy", run_id="leaky", payload={})
    (entry,) = notifier.scan()
    path = toy.layout.home / "notify" / "outbox" / f"{entry.id}.slack.json"
    text = path.read_text()
    assert hook.secret not in text and "***" in text
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert OutboxEntry.model_validate_json(text).status == "pending"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/notify/test_notifier.py -v`
Expected: FAIL at collection with `ImportError: cannot import name 'sweep_issuing' from 'hypothex.core.sweeps'`.

- [ ] **Step 3: Write the implementation**

In `src/hypothex/core/sweeps.py`, insert after `_sweep_lock` (it uses the same lock file; `fcntl` is already imported):

```python
def sweep_issuing(layout: Layout, project: str, sweep_id: str) -> bool:
    """
    Tell whether a launch or extend of a sweep is issuing its runs right now.

    ``launch_sweep`` and ``extend_sweep`` hold the sweep's lock while they
    issue runs one by one; this tries the lock without waiting. The notifier
    uses it so a short first run that ends before the last launch does not
    read as a finished sweep.

    Parameters
    ----------
    layout : Layout
    project : str
    sweep_id : str

    Returns
    -------
    bool
        True while another open file holds the lock (this process included:
        ``flock`` locks belong to the open file, not the process).

    Examples
    --------
    >>> sweep_issuing(ctx.layout, "toy", "s-0001")  # doctest: +SKIP
    False
    """
    path = sweep_path(layout, project, sweep_id).with_suffix(".lock")
    if not path.is_file():
        return False
    with path.open("a") as fh:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    return False
```

Create `src/hypothex/notify/notifier.py`:

```python
"""The hub's notifier: event log -> outbox -> Slack and email, at least once.

Only the hub's ``hx serve`` runs it (a thread in the lifespan, Task 30). Each
notice and channel is one file in ``<home>/notify/outbox``; a final state moves
it to ``sent.jsonl``. A crash after a send but before its record leaves the
entry ``sending``; it is sent again after ``SENDING_RETRY_SECONDS``.
"""

from __future__ import annotations

import json
import logging
import os
import ssl
import threading
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, SecretStr, ValidationError

from hypothex.core.context import Context
from hypothex.core.errors import ConfigError, StoreError
from hypothex.core.events import Event
from hypothex.core.fsutil import read_jsonl
from hypothex.core.ids import utcnow
from hypothex.core.records import RunRecord
from hypothex.core.settings import (
    Channel,
    ProjectRule,
    Settings,
    load_settings,
    resolve_secret,
    write_private,
)
from hypothex.core.sweeps import (
    SweepSummary,
    summarize_sweep,
    sweep_combos,
    sweep_issuing,
    sweep_tag,
)
from hypothex.notify.channels import ChannelError, redact, send_email, send_slack
from hypothex.notify.messages import Notice, render_email, render_slack, run_notice, sweep_notice

log = logging.getLogger(__name__)

NOTIFY_DIR = "notify"
RETRY_DELAYS = (30.0, 120.0, 600.0)
"""Seconds to wait after failed attempts 1, 2, and 3; a fourth failure is final."""
TERMINAL_EVENTS = ("run.finished", "run.failed", "run.killed", "run.lost")
SENDING_RETRY_SECONDS = 60.0
SCAN_BATCH = 500


class OutboxEntry(BaseModel):
    """One notice on one channel, from enqueue to its final state."""

    id: str
    channel: Channel
    notice: Notice
    status: Literal["pending", "sending", "sent", "failed", "skipped"]
    attempts: int = 0
    next_at: datetime
    last_error: str | None = None
    created_at: datetime
    sent_at: datetime | None = None


class _Skip(Exception):
    """The entry cannot be sent with the current settings (``unset:<VAR>``, ...)."""

    def __init__(self, error_class: str) -> None:
        super().__init__(error_class)
        self.error_class = error_class


def _status_of(event: Event) -> str | None:
    """The terminal status an event reports, or None."""
    if event.type in TERMINAL_EVENTS:
        return event.type.removeprefix("run.")
    if event.type == "mirror.run_updated":
        original = event.payload.get("original_type")
        if original in TERMINAL_EVENTS:
            return str(original).removeprefix("run.")
    return None


def _append_private(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


class Notifier:
    """
    Turns run endings into outbox entries and delivers them.

    Parameters
    ----------
    ctx : Context
        The hub's context.
    settings : Settings
        Current settings (``run_notifier_loop`` refreshes them every tick).
    now : callable
        Clock (tests pass a fake one; no test sleeps).
    transport : httpx.BaseTransport, optional
        For Slack calls in tests.
    ssl_context : ssl.SSLContext, optional
        For SMTP in tests (trust a fake CA).
    """

    def __init__(
        self,
        ctx: Context,
        settings: Settings,
        *,
        now: Callable[[], datetime] = utcnow,
        transport: httpx.BaseTransport | None = None,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self.ctx = ctx
        self.settings = settings
        self.now = now
        self.transport = transport
        self.ssl_context = ssl_context
        self.root = ctx.layout.home / NOTIFY_DIR
        self.outbox = self.root / "outbox"
        self._sent: set[str] | None = None
        self._sweeps: dict[tuple[str, str], SweepSummary | None] = {}
        self._pending = self._read_pending()

    # files ---------------------------------------------------------------------------
    def _path(self, entry_id: str, channel: str) -> Path:
        return self.outbox / f"{entry_id}.{channel}.json"

    def _write(self, entry: OutboxEntry) -> None:
        write_private(self._path(entry.id, entry.channel), entry.model_dump_json(indent=2))

    def _read_cursor(self) -> int | None:
        try:
            return int(json.loads((self.root / "cursor.json").read_text())["last_sequence"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _save_cursor(self, sequence: int) -> None:
        write_private(self.root / "cursor.json", json.dumps({"last_sequence": sequence}))

    def _read_pending(self) -> dict[str, Event]:
        try:
            raw = json.loads((self.root / "pending-sweeps.json").read_text())
            return {key: Event.model_validate(value) for key, value in raw.items()}
        except (OSError, ValueError, TypeError, AttributeError):
            return {}

    def _save_pending(self) -> None:
        write_private(
            self.root / "pending-sweeps.json",
            json.dumps(
                {key: event.model_dump(mode="json") for key, event in self._pending.items()}
            ),
        )

    def _sent_keys(self) -> set[str]:
        if self._sent is None:
            rows = read_jsonl(self.root / "sent.jsonl")
            self._sent = {f"{r.get('id')}.{r.get('channel')}" for r in rows}
        return self._sent

    def _finish(self, entry: OutboxEntry) -> OutboxEntry:
        _append_private(self.root / "sent.jsonl", entry.model_dump_json())
        self._path(entry.id, entry.channel).unlink(missing_ok=True)
        self._sent_keys().add(f"{entry.id}.{entry.channel}")
        kind = "notify.sent" if entry.status == "sent" else "notify.failed"
        self.ctx.events.append(
            kind,
            project=entry.notice.project,
            run_id=entry.notice.run_id,
            payload={
                "entry_id": entry.id,
                "channel": entry.channel,
                "kind": entry.notice.kind,
                "run_id": entry.notice.run_id,
                "attempts": entry.attempts,
                "error_class": entry.last_error,
            },
        )
        return entry

    # rules ---------------------------------------------------------------------------
    def _configured(self, channel: Channel) -> bool:
        if channel == "slack":
            return self.settings.notify.slack is not None
        return self.settings.notify.email is not None

    def _rule(self, project: str) -> ProjectRule | None:
        return self.settings.notify.projects.get(project) or self.settings.notify.default

    def secret_values(self) -> list[SecretStr]:
        """
        Return every configured secret value (to redact from notices and errors).

        Returns
        -------
        list of SecretStr
            Values of the webhook, SMTP password, and index password variables
            that are set; an unsafe ``secrets.env`` contributes nothing.
        """
        names = [self.settings.server.index_password_env]
        if self.settings.notify.slack is not None:
            names.append(self.settings.notify.slack.webhook_env)
        email = self.settings.notify.email
        if email is not None and email.password_env:
            names.append(email.password_env)
        values: list[SecretStr] = []
        for name in names:
            try:
                value = resolve_secret(self.ctx.layout, name)
            except ConfigError:
                value = None
            if value is not None:
                values.append(value)
        return values

    def _redact(self, notice: Notice) -> Notice:
        secrets = self.secret_values()
        return notice.model_copy(
            update={
                "title": redact(notice.title, secrets),
                "lines": [redact(line, secrets) for line in notice.lines],
            }
        )

    # enqueue -------------------------------------------------------------------------
    def enqueue(self, notice: Notice, channels: Iterable[Channel]) -> list[OutboxEntry]:
        """
        Write one pending entry per configured channel, unless one exists already.

        Every configured secret value is redacted here, before anything is
        written: run, sweep, and digest notices (a note quoting a webhook URL)
        all pass through this one place.

        Parameters
        ----------
        notice : Notice
            The notice as built.
        channels : iterable of Channel
            Wanted channels; unconfigured ones are dropped.

        Returns
        -------
        list of OutboxEntry
            The new entries (empty when every one was queued or sent before).
        """
        notice = self._redact(notice)
        made: list[OutboxEntry] = []
        now = self.now()
        for channel in dict.fromkeys(channels):
            if not self._configured(channel):
                continue
            if f"{notice.id}.{channel}" in self._sent_keys():
                continue
            if self._path(notice.id, channel).exists():
                continue
            entry = OutboxEntry(
                id=notice.id,
                channel=channel,
                notice=notice,
                status="pending",
                next_at=now,
                created_at=now,
            )
            self._write(entry)
            made.append(entry)
        return made

    def scan(self) -> list[OutboxEntry]:
        """
        Read the event log after the cursor and enqueue the notices it calls for.

        Returns
        -------
        list of OutboxEntry
            New entries. The first scan of a home only sets the cursor.
        """
        last = self._read_cursor()
        if last is None:
            self._save_cursor(self.ctx.events.last_sequence())
            return []
        self._sweeps = {}
        made: list[OutboxEntry] = []
        # Retry before fetching events, even with an empty log or after restart. If a
        # later launch failed there may never be another member-ending event.
        for event in list(self._pending.values()):
            made += self._consider(event)
        while True:
            batch = self.ctx.events.since(last, SCAN_BATCH)
            # one summary per sweep per batch, read after the batch was fetched, so it holds
            # every ending in it; a summary kept across batches would miss a sweep whose last
            # run ends while an earlier batch is read (its notice would never be sent)
            self._sweeps = {}
            for event in batch:
                made += self._consider(event)
                last = event.sequence
            self._save_cursor(last)
            if len(batch) < SCAN_BATCH:
                return made

    def _sweep(self, record: RunRecord) -> SweepSummary | None:
        # a member carries this hub's tag (sweep_runs matches it exactly): a mirrored run of
        # another hub's sweep with the same id is not one, and is notified as a run
        if sweep_tag(self.ctx.descriptor.environment_id, str(record.sweep_id)) not in record.tags:
            return None
        key = (record.project, str(record.sweep_id))
        if key not in self._sweeps:
            try:
                self._sweeps[key] = summarize_sweep(self.ctx, *key)
            except (StoreError, ConfigError):
                self._sweeps[key] = None  # the sweep file is not on this hub: notify the run
        return self._sweeps[key]

    def _consider(self, event: Event) -> list[OutboxEntry]:
        if _status_of(event) is None or event.run_id is None:
            return []
        made, deferred = self._consider_now(event)
        # One trigger per sweep is sufficient; it is only used to find the live summary.
        try:
            record = self.ctx.find_record(event.run_id) if event.run_id else None
        except StoreError:
            record = None
        owns_sweep = (
            record is not None
            and record.sweep_id is not None
            and (sweep_tag(self.ctx.descriptor.environment_id, str(record.sweep_id)) in record.tags)
        )
        key = (
            f"{record.project}/{record.sweep_id}"
            if owns_sweep
            else next((k for k, saved in self._pending.items() if saved.run_id == event.run_id), "")
        )
        if deferred:
            self._pending[key] = event
            self._save_pending()  # durable before scan can advance its event cursor
        elif key in self._pending:
            del self._pending[key]
            self._save_pending()  # after enqueue: deterministic IDs make replay safe
        return made

    def _consider_now(self, event: Event) -> tuple[list[OutboxEntry], bool]:
        status = _status_of(event)
        if status is None or event.run_id is None:
            return [], False
        try:
            record = self.ctx.find_record(event.run_id)
        except StoreError:
            return [], False
        rule = self._rule(record.project)
        if rule is None:
            return [], False
        max_age = timedelta(hours=self.settings.notify.max_age_hours)
        if record.ended_at is not None and self.now() - record.ended_at > max_age:
            return [], False
        base = self.settings.server.public_url
        summary = self._sweep(record) if rule.fold_sweeps and record.sweep_id else None
        if summary is not None:
            counts = summary.counts
            if counts.get("queued", 0) + counts.get("running", 0) > 0:
                return [], True
            spec = summary.spec
            planned = len(sweep_combos(spec)) * len(spec.seeds)
            if counts.get("total", 0) < planned and sweep_issuing(
                self.ctx.layout, spec.project, spec.id
            ):
                return [], True  # durable retry after issuance ends, even without another event
            if not any(counts.get(wanted, 0) for wanted in rule.events):
                return [], False  # the sweep's outcome holds no status this rule asks for
            notice = sweep_notice(self.ctx, summary, base_url=base)
        else:
            if status not in rule.events:
                return [], False
            if status == "finished" and rule.min_seconds > 0:
                wall = 0.0
                if record.started_at is not None and record.ended_at is not None:
                    wall = (record.ended_at - record.started_at).total_seconds()
                if wall < rule.min_seconds:
                    return [], False
            notice = run_notice(self.ctx, record, base_url=base)
        return self.enqueue(notice, rule.channels), False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/notify/test_notifier.py -v`
Expected: all cases pass, including the round-4 regressions.

Run: `uv run ruff check src/hypothex/notify src/hypothex/core/sweeps.py tests/notify && uv run ruff format --check src/hypothex/notify src/hypothex/core/sweeps.py tests/notify && uv run ty check src`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/notify/notifier.py src/hypothex/core/sweeps.py tests/notify/test_notifier.py
git commit -m "feat(notify): notifier scans the event log into a per-channel outbox"
```

---

### Task 17: Delivery, retries, crash recovery, and the notifier loop

**Files:**
- Modify: `src/hypothex/notify/notifier.py` (`deliver`, `recent`, `tick`, `run_notifier_loop`)
- Test: `tests/notify/test_notifier.py` (append)

**Interfaces:**
- Produces (contract 1.7, exact): `Notifier.deliver()`, `Notifier.recent(limit=50)`, `Notifier.tick()`, `run_notifier_loop(ctx, stop, *, interval=5.0)`.
- Rules (contract 8, failure modes 1–4): `deliver` takes every entry that is `pending` or `sending` with `next_at <= now`, marks it `sending` with `next_at = now + 60 s` (written before the send), then sends. Success → `sent` (final). A permanent `ChannelError` → `failed` (final). A retryable one → `pending` again with `next_at = now + max(RETRY_DELAYS[attempts - 1], retry_after)`; the fourth failed attempt is final `failed`. An unset secret variable → `skipped` with `error_class` `unset:<VAR>` (final); a removed channel `unconfigured`; an unsafe `secrets.env` `secrets_file`. Final entries go to `sent.jsonl`, then leave the outbox (an outbox file whose `(id, channel)` is already in `sent.jsonl`, left by a crash between the two, is removed and never sent again), and emit `notify.sent` or `notify.failed` `{entry_id, channel, kind, run_id, attempts, error_class}`. `last_error` is the redacted error class only. `tick()` is `scan()` then `deliver()` (Task 19 adds the digests). `run_notifier_loop` re-reads `config.yaml` every tick and never dies on an error (it logs the error's type name only).

- [ ] **Step 1: Write the failing test**

Append to `tests/notify/test_notifier.py` (and add `import threading`, `from hypothex.core.fsutil import read_jsonl`, `from tests.fakes.webhook import Reply`, and `run_notifier_loop` to the `hypothex.notify.notifier` import):

```python
def outbox(ctx: Context) -> list[OutboxEntry]:
    folder = ctx.layout.home / "notify" / "outbox"
    return [OutboxEntry.model_validate_json(p.read_text()) for p in sorted(folder.glob("*.json"))]


def finals(ctx: Context) -> list[dict]:
    return read_jsonl(ctx.layout.home / "notify" / "sent.jsonl")


def test_deliver_sends_once_per_channel(
    toy: Context, hook: FakeWebhook, smtp: FakeSmtp, clock: Clock
) -> None:
    notifier = primed(toy, settings_for(smtp), clock)
    end_run(toy, "a", "failed")
    notifier.scan()
    before = toy.events.last_sequence()
    done = notifier.deliver()
    assert sorted((e.channel, e.status, e.attempts) for e in done) == [
        ("email", "sent", 1),
        ("slack", "sent", 1),
    ]
    assert hook.requests[0]["body"]["text"].startswith("✗ toy/toy-acc a")
    assert smtp.received[0].message["Subject"].startswith("✗ toy/toy-acc a")
    assert outbox(toy) == [] and len(finals(toy)) == 2
    events = toy.events.since(before)
    assert [e.type for e in events] == ["notify.sent", "notify.sent"]
    keys = {"entry_id", "channel", "kind", "run_id", "attempts", "error_class"}
    assert set(events[0].payload) == keys
    assert notifier.deliver() == []


def test_slack_429_waits_for_retry_after_or_the_schedule(
    toy: Context, hook: FakeWebhook, clock: Clock
) -> None:
    hook.queue(Reply(429, retry_after=7), Reply(429, retry_after=500))
    notifier = primed(toy, settings_for(), clock)
    end_run(toy, "a", "failed")
    notifier.scan()
    (first,) = notifier.deliver()
    assert (first.status, first.attempts, first.last_error) == ("pending", 1, "http_429")
    assert first.next_at == clock() + timedelta(seconds=30)  # max(7, 30)
    clock.tick(29)
    assert notifier.deliver() == []
    clock.tick(1)
    (second,) = notifier.deliver()
    assert second.next_at == clock() + timedelta(seconds=500)  # max(500, 120)
    clock.tick(500)
    (third,) = notifier.deliver()
    assert third.status == "sent" and third.attempts == 3 and len(hook.requests) == 3


def test_three_retries_then_failed(toy: Context, hook: FakeWebhook, clock: Clock) -> None:
    hook.queue(*[Reply(500)] * 4)
    notifier = primed(toy, settings_for(), clock)
    end_run(toy, "a", "failed")
    notifier.scan()
    for delay in (30, 120, 600):
        (entry,) = notifier.deliver()
        assert entry.status == "pending" and entry.next_at == clock() + timedelta(seconds=delay)
        clock.tick(delay)
    before = toy.events.last_sequence()
    (last,) = notifier.deliver()
    assert (last.status, last.attempts, last.last_error) == ("failed", 4, "http_500")
    (event,) = toy.events.since(before)
    assert event.type == "notify.failed" and event.payload["error_class"] == "http_500"


def test_permanent_errors_fail_at_once(
    toy: Context, hook: FakeWebhook, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook.queue(Reply(404))
    with FakeSmtp(user="sv", password="right") as smtp:
        settings = settings_for(smtp)
        assert settings.notify.email is not None
        settings.notify.email = settings.notify.email.model_copy(
            update={"username": "sv", "password_env": "HX_TEST_SMTP"}
        )
        monkeypatch.setenv("HX_TEST_SMTP", "wrong")
        notifier = primed(toy, settings, clock)
        end_run(toy, "a", "failed")
        notifier.scan()
        done = {e.channel: e for e in notifier.deliver()}
    assert (done["slack"].status, done["slack"].last_error) == ("failed", "http_404")
    assert (done["email"].status, done["email"].last_error) == ("failed", "smtp_535")
    assert "wrong" not in (toy.layout.home / "notify" / "sent.jsonl").read_text()


def test_unset_secret_skips(
    toy: Context, hook: FakeWebhook, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    notifier = primed(toy, settings_for(), clock)
    end_run(toy, "a", "failed")
    notifier.scan()
    monkeypatch.delenv("HX_TEST_HOOK")
    (entry,) = notifier.deliver()
    assert (entry.status, entry.last_error) == ("skipped", "unset:HX_TEST_HOOK")
    assert hook.requests == []


def test_entry_left_sending_by_a_crash_is_retried_once(
    toy: Context, hook: FakeWebhook, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    notifier = primed(toy, settings_for(), clock)
    end_run(toy, "a", "failed")
    notifier.scan()
    real_finish = Notifier._finish
    calls = {"n": 0}

    def crash_once(self: Notifier, entry: OutboxEntry) -> OutboxEntry:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("hub died after the send, before the record")
        return real_finish(self, entry)

    monkeypatch.setattr(Notifier, "_finish", crash_once)
    with pytest.raises(RuntimeError):
        notifier.deliver()
    (left,) = outbox(toy)
    assert left.status == "sending" and left.next_at == clock() + timedelta(seconds=60)
    assert notifier.deliver() == []  # not yet due
    clock.tick(60)
    (again,) = notifier.deliver()
    assert again.status == "sent" and len(hook.requests) == 2  # at least once
    clock.tick(3600)
    assert notifier.deliver() == [] and len(hook.requests) == 2


def test_an_entry_recorded_before_a_crash_is_not_sent_again(
    toy: Context, hook: FakeWebhook, clock: Clock
) -> None:
    notifier = primed(toy, settings_for(), clock)
    end_run(toy, "a", "failed")
    notifier.scan()
    (sent,) = notifier.deliver()
    assert sent.status == "sent" and len(hook.requests) == 1
    # a crash between the sent.jsonl append and the outbox unlink leaves both behind
    notifier._write(sent.model_copy(update={"status": "sending", "next_at": clock()}))
    restarted = Notifier(toy, settings_for(), now=clock)
    clock.tick(60)
    assert restarted.deliver() == [] and len(hook.requests) == 1
    assert outbox(toy) == []


def test_recent_lists_final_and_pending_newest_first(
    toy: Context, hook: FakeWebhook, clock: Clock
) -> None:
    notifier = primed(toy, settings_for(), clock)
    end_run(toy, "a", "failed")
    notifier.scan()
    notifier.deliver()
    clock.tick(10)
    end_run(toy, "b", "failed")
    notifier.scan()
    recent = notifier.recent()
    assert [(e.notice.run_id, e.status) for e in recent] == [("b", "pending"), ("a", "sent")]
    assert len(notifier.recent(limit=1)) == 1


def test_tick_scans_and_delivers(toy: Context, hook: FakeWebhook, clock: Clock) -> None:
    notifier = primed(toy, settings_for(), clock)
    end_run(toy, "a", "lost")
    notifier.tick()
    assert [r["status"] for r in finals(toy)] == ["sent"]


def test_loop_rereads_settings_and_stops(toy: Context, hook: FakeWebhook) -> None:
    from hypothex.core.settings import save_settings

    save_settings(toy.layout, settings_for())
    stop = threading.Event()
    thread = threading.Thread(target=run_notifier_loop, args=(toy, stop), kwargs={"interval": 0.05})
    thread.start()
    try:
        cursor = toy.layout.home / "notify" / "cursor.json"
        for _ in range(100):
            if cursor.exists():
                break
            stop.wait(0.05)
        end_run(toy, "a", "failed", ended=datetime.now(UTC))
        for _ in range(100):
            if hook.requests:
                break
            stop.wait(0.05)
    finally:
        stop.set()
        thread.join(5)
    assert not thread.is_alive() and len(hook.requests) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/notify/test_notifier.py -v`
Expected: FAIL at collection with `ImportError: cannot import name 'run_notifier_loop' from 'hypothex.notify.notifier'`.

- [ ] **Step 3: Write the implementation**

Append to the `Notifier` class in `src/hypothex/notify/notifier.py`:

```python
    # delivery ------------------------------------------------------------------------
    def _send(self, entry: OutboxEntry) -> None:
        notice = entry.notice
        layout = self.ctx.layout
        if entry.channel == "slack":
            slack = self.settings.notify.slack
            if slack is None:
                raise _Skip("unconfigured")
            hook = resolve_secret(layout, slack.webhook_env)
            if hook is None:
                raise _Skip(f"unset:{slack.webhook_env}")
            send_slack(hook, render_slack(notice), transport=self.transport)
            return
        email = self.settings.notify.email
        if email is None:
            raise _Skip("unconfigured")
        password = resolve_secret(layout, email.password_env) if email.password_env else None
        if email.username and password is None:
            raise _Skip(f"unset:{email.password_env}")
        message = render_email(notice, email)
        send_email(email, password, message, ssl_context=self.ssl_context)

    def _attempt(self, entry: OutboxEntry, now: datetime) -> OutboxEntry:
        sending = entry.model_copy(
            update={"status": "sending", "next_at": now + timedelta(seconds=SENDING_RETRY_SECONDS)}
        )
        self._write(sending)  # recorded before the send: a crash leaves it "sending"
        attempts = entry.attempts + 1
        try:
            self._send(sending)
        except _Skip as exc:
            final = {"status": "skipped", "attempts": attempts, "last_error": exc.error_class}
            return self._finish(sending.model_copy(update=final))
        except ConfigError:
            final = {"status": "skipped", "attempts": attempts, "last_error": "secrets_file"}
            return self._finish(sending.model_copy(update=final))
        except ChannelError as exc:
            error = redact(exc.error_class, self.secret_values())
            if exc.permanent or attempts > len(RETRY_DELAYS):
                final = {"status": "failed", "attempts": attempts, "last_error": error}
                return self._finish(sending.model_copy(update=final))
            delay = max(RETRY_DELAYS[attempts - 1], exc.retry_after or 0.0)
            retry = sending.model_copy(
                update={
                    "status": "pending",
                    "attempts": attempts,
                    "last_error": error,
                    "next_at": now + timedelta(seconds=delay),
                }
            )
            self._write(retry)
            return retry
        sent = {"status": "sent", "attempts": attempts, "sent_at": now, "last_error": None}
        return self._finish(sending.model_copy(update=sent))

    def deliver(self) -> list[OutboxEntry]:
        """
        Send every due entry once.

        Returns
        -------
        list of OutboxEntry
            The entries after this attempt (final or rescheduled).
        """
        now = self.now()
        out: list[OutboxEntry] = []
        for path in sorted(self.outbox.glob("*.json")) if self.outbox.is_dir() else []:
            try:
                entry = OutboxEntry.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValidationError):
                continue
            if f"{entry.id}.{entry.channel}" in self._sent_keys():
                # `_finish` records the final entry, then unlinks this file: a crash between
                # the two leaves both, and the record wins (never sent twice)
                path.unlink(missing_ok=True)
                continue
            if entry.status not in ("pending", "sending") or entry.next_at > now:
                continue
            out.append(self._attempt(entry, now))
        return out

    def recent(self, limit: int = 50) -> list[OutboxEntry]:
        """
        Return the newest entries, final and pending, newest first.

        Parameters
        ----------
        limit : int

        Returns
        -------
        list of OutboxEntry
        """
        entries: list[OutboxEntry] = []
        for row in read_jsonl(self.root / "sent.jsonl")[-limit:]:
            try:
                entries.append(OutboxEntry.model_validate(row))
            except ValidationError:
                continue
        for path in self.outbox.glob("*.json") if self.outbox.is_dir() else []:
            try:
                entries.append(OutboxEntry.model_validate_json(path.read_text(encoding="utf-8")))
            except (OSError, ValidationError):
                continue
        entries.sort(key=lambda e: (e.created_at, e.id, e.channel), reverse=True)
        return entries[:limit]

    def tick(self) -> None:
        """Scan the event log, then deliver what is due."""
        self.scan()
        self.deliver()
```

and append at module level:

```python
def run_notifier_loop(ctx: Context, stop: threading.Event, *, interval: float = 5.0) -> None:
    """
    Run the notifier until ``stop`` is set (a thread in the hub's ``hx serve``).

    ``config.yaml`` is read again every tick, so edits apply without a restart.
    An error in one tick is logged by its type name only (it may quote a URL)
    and the loop goes on.

    Parameters
    ----------
    ctx : Context
        The hub's context.
    stop : threading.Event
    interval : float
        Seconds between ticks.
    """
    notifier: Notifier | None = None
    while not stop.is_set():
        try:
            settings = load_settings(ctx.layout)
            if notifier is None:
                notifier = Notifier(ctx, settings)
            else:
                notifier.settings = settings
            notifier.tick()
        except Exception as exc:  # noqa: BLE001 - the loop must outlive any one tick
            log.warning("notifier tick failed: %s", type(exc).__name__)
        stop.wait(interval)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/notify -v`
Expected: `tests/notify/test_notifier.py` `23 passed`; the other notify files still pass.

Run: `uv run ruff check src/hypothex/notify tests/notify && uv run ruff format --check src/hypothex/notify tests/notify && uv run ty check src`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/notify/notifier.py tests/notify/test_notifier.py
git commit -m "feat(notify): deliver with retries, crash-safe resend, and the notifier loop"
```

---
## Part 5: Weekly digest

Contract 1.8, 8 (failure mode 15). The digest reuses the leaderboard builder on filtered inputs and the notifier's outbox.

### Task 18: Build and render the weekly digest (`hypothex.core.digest`)

**Files:**
- Create: `src/hypothex/core/digest.py`
- Test: `tests/core/test_digest.py`

**Interfaces:**
- Consumes: `build_leaderboard`, `add_costs`, `parse_entries`, `day_path`, `list_sweeps`, `Notice`, `notice_id`.
- Produces (contract 1.8, exact): `TaskChange`, `NoteItem`, `SweepLine`, `Digest`, `build_digest(ctx, project, *, since, until=None, top_notes=5)`, `render_digest_markdown(digest)`, `digest_notice(digest, *, base_url)`, `week_key(moment)`. (`digest_due`, `send_digest` are Task 19.)
- Rules: the window is `[since, until]`. `counts`: `started` = runs created in the window, `finished`/`failed`/`lost`/`killed` = runs that ended in it by status, `queued` = runs created in it that still wait. `by_owner` counts created runs per `created_by`. `cost` sums the `cost` of runs that ended in the window (`CostTotals()` when none). For each task: `before` from runs created and ended before `since` with scores made before `since`, `after` from everything up to `until`; a task is listed when it gained a finished run or a new best group. Notes: run `notes.md` sections and notebook entries stamped in the window (notebook entries by `digest` are skipped), newest first, `top_notes` of them, each cut to 200 characters. Sweeps: those created in the window. `headline` = `▲<started> ✓<finished> ✗<failed> ?<lost>` (`⊘<killed>` when any) `· <gpu_h> GPU-h $<usd>` and, for the first task with a new best, `· <task> <before>→<after> ▲`.

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_digest.py`:

```python
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hypothex.core.context import Context
from hypothex.core.digest import (
    build_digest,
    digest_notice,
    render_digest_markdown,
    week_key,
)
from hypothex.core.errors import StoreError
from hypothex.core.notebook import append_entry
from hypothex.core.records import CostTotals, GitInfo, RunStatus, ScoreRecord
from hypothex.core.sweeps import SweepParam, SweepSpec, save_sweep
from tests.factories import make_record

T0 = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)  # a Monday
SINCE = T0 - timedelta(days=7)


def run(
    ctx: Context,
    run_id: str,
    *,
    created: datetime,
    status: RunStatus,
    ended: datetime | None = None,
    chash: str = "sha256:aaaa",
    by: str = "human",
    cost: CostTotals | None = None,
    hypothesis: str = "",
) -> None:
    ctx.create_run(
        make_record(
            run_id,
            task="toy-acc",
            status=status,
            created_at=created,
            started_at=created,
            ended_at=ended,
            config_hash=chash,
            git=GitInfo(commit="c1"),
            created_by=by,
            cost=cost,
            hypothesis=hypothesis,
            environment_id=ctx.descriptor.environment_id,
        )
    )


def score(ctx: Context, run_id: str, value: float, at: datetime) -> None:
    ctx.add_score(
        ctx.find_record(run_id),
        ScoreRecord(metric="accuracy", version="v1", key="value", value=value, created_at=at),
    )


@pytest.fixture
def week(ctx: Context, toy_repo: Path) -> Context:
    ctx.register_project(toy_repo)
    day = timedelta(days=1)
    run(
        ctx,
        "old1",
        created=T0 - 10 * day,
        status=RunStatus.FINISHED,
        ended=T0 - 10 * day + timedelta(hours=1),
    )
    score(ctx, "old1", 0.6, T0 - 10 * day + timedelta(hours=2))
    run(
        ctx,
        "new1",
        created=T0 - 2 * day,
        status=RunStatus.FINISHED,
        ended=T0 - 2 * day + timedelta(hours=1),
        chash="sha256:bbbb",
        by="human:alice",
        cost=CostTotals(gpu_hours=1.0, gpu_usd=1.5, total_usd=1.5),
        hypothesis="bigger model",
    )
    score(ctx, "new1", 0.7, T0 - 2 * day + timedelta(hours=2))
    run(
        ctx,
        "new2",
        created=T0 - day,
        status=RunStatus.FAILED,
        ended=T0 - day + timedelta(minutes=10),
        by="agent:claude@sv",
        cost=CostTotals(gpu_hours=0.5, api_usd=0.5, total_usd=0.5),
    )
    run(ctx, "new3", created=T0 - day, status=RunStatus.QUEUED)
    run(
        ctx,
        "lost1",
        created=T0 - 3 * day,
        status=RunStatus.LOST,
        ended=T0 - 3 * day + timedelta(hours=5),
        by="human:alice",
    )
    notes = ctx.run_dir(ctx.find_record("new1")) / "notes.md"
    notes.write_text(
        f"\n## {(T0 - timedelta(days=1)).isoformat()} — human:alice\n\nfound the bug\n"
        f"\n## {(T0 - timedelta(days=9)).isoformat()} — human:alice\n\ntoo old\n"
    )
    late = T0 - timedelta(hours=12)
    append_entry(ctx, "toy", "plan [[run:new1]]", "human:sv", day=late.date(), now=late)
    append_entry(ctx, "toy", "last week's digest", "digest", day=late.date(), now=late)
    save_sweep(
        ctx.layout,
        SweepSpec(
            id="s-0002",
            project="toy",
            task="toy-acc",
            host=None,
            grid=[SweepParam(name="x", values=["1"])],
            seeds=[1],
            command_template=["echo", "{x}"],
            created_by="human:sv",
            created_at=T0 - timedelta(days=1),
        ),
    )
    return ctx


def test_week_key() -> None:
    assert week_key(T0) == "2026-W41"
    assert week_key(datetime(2027, 1, 1, tzinfo=UTC)) == "2026-W53"


def test_counts_owners_and_cost(week: Context) -> None:
    digest = build_digest(week, "toy", since=SINCE, until=T0)
    assert digest.week == "2026-W41"
    assert digest.counts == {
        "started": 4, "finished": 1, "failed": 1, "lost": 1, "killed": 0, "queued": 1,
    }  # fmt: skip
    assert digest.by_owner == {"agent:claude@sv": 1, "human": 1, "human:alice": 2}
    assert digest.cost == CostTotals(gpu_hours=1.5, gpu_usd=1.5, api_usd=0.5, total_usd=2.0)


def test_leaderboard_change(week: Context) -> None:
    (change,) = build_digest(week, "toy", since=SINCE, until=T0).tasks
    assert change.task == "toy-acc" and change.primary == "accuracy/value"
    assert (change.before, change.after, change.new_best, change.n_new_runs) == (0.6, 0.7, True, 1)
    assert change.best_label == "bigger model" and change.best_group_id == "bbbb@c1"


def test_notes_and_sweeps(week: Context) -> None:
    digest = build_digest(week, "toy", since=SINCE, until=T0, top_notes=5)
    assert [(n.source, n.author, n.text) for n in digest.notes] == [
        ("notebook", "human:sv", "plan [[run:new1]]"),
        ("run", "human:alice", "found the bug"),
    ]
    assert digest.notes[1].run_id == "new1" and digest.notes[0].day is not None
    assert [(s.id, s.n_runs) for s in digest.sweeps] == [("s-0002", 0)]
    assert len(build_digest(week, "toy", since=SINCE, until=T0, top_notes=1).notes) == 1


def test_markdown_and_notice(week: Context) -> None:
    digest = build_digest(week, "toy", since=SINCE, until=T0)
    assert digest.headline == "▲4 ✓1 ✗1 ?1 · 1.5 GPU-h $2.00 · toy-acc 0.600→0.700 ▲"
    assert render_digest_markdown(digest) == (
        "**2026-W41** · ▲4 ✓1 ✗1 ?1 · 1.5 GPU-h $2.00 · toy-acc 0.600→0.700 ▲\n"
        "\n"
        "- toy-acc 0.600→0.700 ▲ · 1 runs\n"
        "\n"
        "notes\n"
        "- 10-04 21:00 @sv plan [[run:new1]]\n"
        "- 10-04 09:00 @alice [[run:new1]] found the bug\n"
        "\n"
        "sweeps\n"
        "- s-0002 · 0 runs\n"
    )
    notice = digest_notice(digest, base_url="https://hub.ts.net")
    assert notice.kind == "digest" and notice.project == "toy"
    assert notice.title == "Σ toy 2026-W41 · " + digest.headline
    assert notice.lines == [
        "toy-acc 0.600→0.700 ▲ · 1 runs",
        "✎ 10-04 21:00 @sv plan [[run:new1]]",
        "✎ 10-04 09:00 @alice [[run:new1]] found the bug",
    ]  # the top notes travel with the Slack/email summary (spec 9), not only the notebook
    assert notice.url == "https://hub.ts.net/n/toy"


def test_empty_week_and_unknown_project(ctx: Context, toy_repo: Path) -> None:
    ctx.register_project(toy_repo)
    digest = build_digest(ctx, "toy", since=SINCE, until=T0)
    assert digest.tasks == [] and digest.notes == [] and digest.cost == CostTotals()
    assert digest.headline == "▲0 ✓0 ✗0 ?0 · 0.0 GPU-h $0.00"
    assert render_digest_markdown(digest) == "**2026-W41** · ▲0 ✓0 ✗0 ?0 · 0.0 GPU-h $0.00\n"
    with pytest.raises(StoreError):
        build_digest(ctx, "nope", since=SINCE, until=T0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_digest.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'hypothex.core.digest'`.

- [ ] **Step 3: Write the implementation**

Create `src/hypothex/core/digest.py`:

```python
"""Weekly digest per project: counts, cost, leaderboard changes, notes, and sweeps.

``build_digest`` reads the index, run notes, the notebook, and sweep files;
``send_digest`` (Task 19) enqueues it on the notifier's outbox and saves it to
the notebook. The notifier calls ``digest_due`` every tick.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel

from hypothex.core.context import Context
from hypothex.core.cost import add_costs
from hypothex.core.ids import utcnow
from hypothex.core.leaderboard import build_leaderboard
from hypothex.core.notebook import day_path, parse_entries
from hypothex.core.records import CostTotals, RunRecord, RunStatus, ScoreRecord
from hypothex.core.sweeps import list_sweeps
from hypothex.notify.messages import Notice, notice_id

NOTE_CHARS = 200
DIGEST_AUTHOR = "digest"


class TaskChange(BaseModel):
    """How one task's best result moved during the window."""

    task: str
    primary: str
    before: float | None
    after: float | None
    best_label: str
    best_group_id: str | None
    new_best: bool
    n_new_runs: int


class NoteItem(BaseModel):
    """A run note or notebook entry written during the window."""

    source: Literal["run", "notebook"]
    run_id: str | None
    day: date | None
    author: str
    at: datetime
    text: str


class SweepLine(BaseModel):
    """A sweep created during the window."""

    id: str
    n_runs: int
    best: dict[str, Any] | None


class Digest(BaseModel):
    """One project's week."""

    project: str
    since: datetime
    until: datetime
    week: str
    counts: dict[str, int]
    by_owner: dict[str, int]
    cost: CostTotals
    tasks: list[TaskChange]
    notes: list[NoteItem]
    sweeps: list[SweepLine]
    headline: str


def week_key(moment: datetime) -> str:
    """
    Return the ISO week of a moment.

    Parameters
    ----------
    moment : datetime

    Returns
    -------
    str
        ``YYYY-Www``.

    Examples
    --------
    >>> from datetime import UTC
    >>> week_key(datetime(2026, 10, 5, tzinfo=UTC))
    '2026-W41'
    """
    year, week, _ = moment.isocalendar()
    return f"{year}-W{week:02d}"


def _in(moment: datetime | None, since: datetime, until: datetime) -> bool:
    return moment is not None and since <= moment <= until


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.3f}"


def _task_changes(
    ctx: Context,
    project: str,
    runs: list[RunRecord],
    scores: dict[str, list[ScoreRecord]],
    since: datetime,
    until: datetime,
) -> list[TaskChange]:
    config = ctx.store.load_project(project).config
    changes: list[TaskChange] = []
    for name in sorted(config.tasks):
        task_runs = [r for r in runs if r.task == name]
        if not task_runs:
            continue
        before_runs = [
            r
            for r in task_runs
            if r.created_at < since and (r.ended_at is None or r.ended_at < since)
        ]
        before_scores = {k: [s for s in v if s.created_at < since] for k, v in scores.items()}
        after_runs = [r for r in task_runs if r.created_at <= until]
        after_scores = {k: [s for s in v if s.created_at <= until] for k, v in scores.items()}
        before = build_leaderboard(project, name, config, before_runs, before_scores)
        after = build_leaderboard(project, name, config, after_runs, after_scores)
        top_before = before.rows[0] if before.rows and before.rows[0].primary else None
        top_after = after.rows[0] if after.rows and after.rows[0].primary else None
        new_best = top_after is not None and (
            top_before is None or top_after.group_id != top_before.group_id
        )
        n_new = sum(
            1 for r in task_runs if r.status == RunStatus.FINISHED and _in(r.ended_at, since, until)
        )
        if not n_new and not new_best:
            continue
        changes.append(
            TaskChange(
                task=name,
                primary=after.primary,
                before=top_before.primary.mean if top_before and top_before.primary else None,
                after=top_after.primary.mean if top_after and top_after.primary else None,
                best_label=top_after.label if top_after else "",
                best_group_id=top_after.group_id if top_after else None,
                new_best=new_best,
                n_new_runs=n_new,
            )
        )
    return changes


def _notes(
    ctx: Context, project: str, runs: list[RunRecord], since: datetime, until: datetime
) -> list[NoteItem]:
    items: list[NoteItem] = []
    for record in runs:
        for stamp, author, body in parse_entries(ctx.store.read_notes(project, record.run_id)):
            if _in(stamp, since, until):
                items.append(
                    NoteItem(
                        source="run",
                        run_id=record.run_id,
                        day=None,
                        author=author,
                        at=stamp,
                        text=body[:NOTE_CHARS],
                    )
                )
    day = since.date() - timedelta(days=1)
    while day <= until.date() + timedelta(days=1):
        path = day_path(ctx.layout, project, day)
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            for stamp, author, body in parse_entries(text):
                if author != DIGEST_AUTHOR and _in(stamp, since, until):
                    items.append(
                        NoteItem(
                            source="notebook",
                            run_id=None,
                            day=day,
                            author=author,
                            at=stamp,
                            text=body[:NOTE_CHARS],
                        )
                    )
        day += timedelta(days=1)
    items.sort(key=lambda n: n.at, reverse=True)
    return items


def build_digest(
    ctx: Context,
    project: str,
    *,
    since: datetime,
    until: datetime | None = None,
    top_notes: int = 5,
) -> Digest:
    """
    Build one project's digest for a window.

    Parameters
    ----------
    ctx : Context
    project : str
    since : datetime
        Window start (aware).
    until : datetime, optional
        Window end; default now.
    top_notes : int
        Notes to keep, newest first.

    Returns
    -------
    Digest

    Raises
    ------
    StoreError
        Unknown project.
    """
    end = until or utcnow()
    ctx.store.load_project(project)
    runs = ctx.index.list_runs(project=project, include_archived=True, limit=None)
    created = [r for r in runs if _in(r.created_at, since, end)]
    ended = [r for r in runs if _in(r.ended_at, since, end)]
    counts = {"started": len(created)}
    for status in (RunStatus.FINISHED, RunStatus.FAILED, RunStatus.LOST, RunStatus.KILLED):
        counts[status.value] = sum(1 for r in ended if r.status == status)
    counts["queued"] = sum(1 for r in created if r.status == RunStatus.QUEUED)
    by_owner = dict(sorted(Counter(r.created_by for r in created).items()))
    cost = add_costs(r.cost for r in ended) or CostTotals()
    scores = ctx.index.scores_for(r.run_id for r in runs)
    tasks = _task_changes(ctx, project, runs, scores, since, end)
    notes = _notes(ctx, project, runs, since, end)[:top_notes]
    sweeps = [
        SweepLine(id=s["id"], n_runs=s["n_runs"], best=s["best"])
        for s in list_sweeps(ctx, project)
        if _in(s["created_at"], since, end)
    ]
    head = f"▲{counts['started']} ✓{counts['finished']} ✗{counts['failed']} ?{counts['lost']}" + (
        f" ⊘{counts['killed']}" if counts["killed"] else ""
    )
    parts = [head, f"{cost.gpu_hours:.1f} GPU-h ${cost.total_usd:.2f}"]
    best = next((t for t in tasks if t.new_best and t.after is not None), None)
    if best is not None:
        parts.append(f"{best.task} {_fmt(best.before)}→{_fmt(best.after)} ▲")
    return Digest(
        project=project,
        since=since,
        until=end,
        week=week_key(end),
        counts=counts,
        by_owner=by_owner,
        cost=cost,
        tasks=tasks,
        notes=notes,
        sweeps=sweeps,
        headline=" · ".join(parts),
    )


def _who(author: str) -> str:
    return "@" + author.removeprefix("human:") if author.startswith("human:") else author


def _task_line(change: TaskChange) -> str:
    """One task change as ``toy-acc 0.600→0.700 ▲ · 1 runs`` (notebook and notices alike)."""
    best = " ▲" if change.new_best else ""
    moved = f"{_fmt(change.before)}→{_fmt(change.after)}{best}"
    return f"{change.task} {moved} · {change.n_new_runs} runs"


def _note_line(note: NoteItem) -> str:
    """One note as ``10-04 09:00 @alice [[run:<id>]] <text on one line>``."""
    text = " ".join(note.text.split())
    link = f" [[run:{note.run_id}]]" if note.run_id else ""
    return f"{note.at:%m-%d %H:%M} {_who(note.author)}{link} {text}"


def render_digest_markdown(digest: Digest) -> str:
    """
    Render a digest as the Markdown block saved to the notebook.

    Parameters
    ----------
    digest : Digest

    Returns
    -------
    str
        ``**<week>** · <headline>``, then a list of task changes, notes, and
        sweeps (each only when present).
    """
    blocks = [f"**{digest.week}** · {digest.headline}"]
    if digest.tasks:
        # a list, not a table: the UI's Markdown (and contract 10.1's summary block) has no tables
        blocks.append("\n".join(f"- {_task_line(t)}" for t in digest.tasks))
    if digest.notes:
        blocks.append("\n".join(["notes", *(f"- {_note_line(n)}" for n in digest.notes)]))
    if digest.sweeps:
        lines = ["sweeps"]
        for sweep in digest.sweeps:
            best = ""
            if sweep.best:
                params = " ".join(f"{k}={v}" for k, v in sweep.best.get("params", {}).items())
                mean = sweep.best.get("mean")
                best = f" · best {params}" + (f" {mean:.3f}" if mean is not None else "")
            lines.append(f"- {sweep.id} · {sweep.n_runs} runs{best}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def digest_notice(digest: Digest, *, base_url: str | None) -> Notice:
    """
    Build the notice of a digest (one per send).

    Parameters
    ----------
    digest : Digest
    base_url : str or None

    Returns
    -------
    Notice
        ``lines``: one per task change, then one ``✎`` line per top note
        (``top_notes`` of the build, newest first).
    """
    lines = [_task_line(t) for t in digest.tasks]
    lines += [f"✎ {_note_line(note)}" for note in digest.notes]
    return Notice(
        id=notice_id("digest", digest.project, digest.week, digest.until.isoformat()),
        kind="digest",
        project=digest.project,
        title=f"Σ {digest.project} {digest.week} · {digest.headline}",
        lines=lines,
        url=f"{base_url.rstrip('/')}/n/{digest.project}" if base_url else None,
        created_at=utcnow(),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_digest.py -v`
Expected: `6 passed`.

Run: `uv run python -m doctest src/hypothex/core/digest.py && uv run ruff check src/hypothex/core/digest.py tests/core/test_digest.py && uv run ruff format --check src/hypothex/core/digest.py tests/core/test_digest.py && uv run ty check src`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/digest.py tests/core/test_digest.py
git commit -m "feat(digest): weekly project digest with counts, cost, best changes, and notes"
```

---

### Task 19: When the digest is due, sending it, and the notifier's digest tick

**Files:**
- Modify: `src/hypothex/core/digest.py` (`digest_due`, `send_digest`)
- Modify: `src/hypothex/notify/notifier.py` (`Notifier.digests`; `tick` calls it)
- Test: `tests/core/test_digest.py` (append), `tests/notify/test_notifier.py` (append)

**Interfaces:**
- Produces (contract 1.8, exact): `digest_due(settings, last_sent, now) -> str | None`, `send_digest(ctx, settings, project, *, now, channels=None) -> list[str]`, `Notifier.digests() -> list[str]`.
- Produces (additive): `send_digest(..., since: datetime | None = None)` (the API's `since?`; default `now − 7 days`); `digest_due_at(settings, now) -> datetime` (this week's send time in the digest's zone).
- Rules: `digest_due` returns this week's key when `now`, in `DigestSettings.timezone` (or the hub's zone), is at or after this ISO week's `weekday` at `hour:00` and `last_sent` is not that key; missed earlier weeks are never returned. `send_digest` builds the digest, enqueues one notice per wanted and configured channel (`channels` or `digest.channels`), appends `render_digest_markdown` to the notebook day of `now` (author `digest`) when `save_to_notebook`, emits `digest.sent` `{project, week, channels}`, and returns the channels it enqueued. `send_digest` skips the notebook append when the day already holds that entry's stamp (`## <now iso> — digest`). `Notifier.digests()` sends each due project (`digest.projects`, `all` = every project) with `now` = `digest_due_at` (the week's send time, so a resend after a crash before the checkpoint has the same notice id and stamp: queued and saved once) and records `{project: week}` in `<home>/notify/digest.json` (0600). `tick()` is now scan, digests, deliver (a digest goes out on the tick it was made); an error in `digests()` is logged by type name and never stops `deliver()`. A full notebook day (`NotebookTooLargeError`) skips the notebook copy with a warning; the digest is still queued and checkpointed, so no tick retries the week. The digest notice is redacted like every notice (`enqueue` redacts, Task 16): a top note that quotes a secret reaches no outbox, history, or channel.

- [ ] **Step 1: Write the failing tests**

Append to `tests/core/test_digest.py` (and add `from hypothex.core.digest import digest_due, send_digest`, `from hypothex.core.notebook import read_day`, `from hypothex.core.settings import DigestSettings, NotifySettings, Settings, SlackSettings`):

```python
LONDON = DigestSettings(enabled=True, weekday="mon", hour=9, timezone="Europe/London")


@pytest.mark.parametrize(
    ("now", "last", "due"),
    [
        (datetime(2026, 10, 5, 7, 59, tzinfo=UTC), None, None),  # 08:59 in London (BST)
        (datetime(2026, 10, 5, 8, 0, tzinfo=UTC), None, "2026-W41"),
        (datetime(2026, 10, 5, 8, 0, tzinfo=UTC), "2026-W41", None),
        (datetime(2026, 10, 7, 12, 0, tzinfo=UTC), "2026-W40", "2026-W41"),  # hub was off
        (datetime(2026, 10, 12, 7, 0, tzinfo=UTC), "2026-W40", None),  # W41 missed: never sent
        (datetime(2026, 10, 12, 8, 0, tzinfo=UTC), "2026-W40", "2026-W42"),
    ],
)
def test_digest_due(now: datetime, last: str | None, due: str | None) -> None:
    assert digest_due(LONDON, last, now) == due


def test_send_digest_enqueues_and_saves_to_the_notebook(
    week: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HX_TEST_HOOK", "http://127.0.0.1:9/services/T/B/x")
    settings = Settings(
        notify=NotifySettings(slack=SlackSettings(webhook_env="HX_TEST_HOOK")),
        digest=DigestSettings(enabled=True, channels=["slack", "email"], timezone="UTC"),
    )
    before = week.events.last_sequence()
    assert send_digest(week, settings, "toy", now=T0) == ["slack"]  # email is not configured
    outbox = list((week.layout.home / "notify" / "outbox").glob("*.slack.json"))
    assert len(outbox) == 1 and "Σ toy 2026-W41" in outbox[0].read_text()
    day = read_day(week, "toy", T0.date())
    assert "— digest" in day.text and "**2026-W41**" in day.text
    sent = [e for e in week.events.since(before) if e.type == "digest.sent"]
    assert sent[0].payload == {"project": "toy", "week": "2026-W41", "channels": ["slack"]}
```

Append to `tests/notify/test_notifier.py` (and add `date` to the `datetime` import, `import hypothex.core.notebook as notebook_module`, `from hypothex.core.notebook import append_entry, read_day`, and `DigestSettings` to the `hypothex.core.settings` import):

```python
def test_digest_goes_out_once_per_week(
    toy: Context, hook: FakeWebhook, smtp: FakeSmtp, clock: Clock
) -> None:
    settings = settings_for(smtp)
    settings.digest = DigestSettings(
        enabled=True, weekday="sun", hour=0, timezone="UTC", channels=["slack", "email"]
    )
    notifier = primed(toy, settings, clock)  # 2026-10-04 is a Sunday
    notifier.tick()
    assert [r["body"]["text"].split(" · ")[0] for r in hook.requests] == ["Σ toy 2026-W40"]
    assert smtp.received[0].message["Subject"].startswith("Σ toy 2026-W40")
    state = json.loads((toy.layout.home / "notify" / "digest.json").read_text())
    assert state == {"toy": "2026-W40"}
    clock.tick(3600)
    assert notifier.digests() == []
    notifier.settings = settings.model_copy(update={"digest": DigestSettings(enabled=False)})
    clock.tick(7 * 86400)
    assert notifier.digests() == []


def test_a_digest_sent_again_after_a_crash_is_queued_and_saved_once(
    toy: Context, hook: FakeWebhook, clock: Clock
) -> None:
    settings = settings_for()
    settings.digest = DigestSettings(
        enabled=True, weekday="sun", hour=0, timezone="UTC", channels=["slack"]
    )
    assert primed(toy, settings, clock).digests() == ["toy"]
    (toy.layout.home / "notify" / "digest.json").unlink()  # crashed before the checkpoint
    clock.tick(3600)
    assert Notifier(toy, settings, now=clock).digests() == ["toy"]
    assert len(list((toy.layout.home / "notify" / "outbox").glob("*.slack.json"))) == 1
    assert read_day(toy, "toy", date(2026, 10, 4)).text.count("— digest") == 1


def test_a_digest_note_never_carries_a_secret(
    toy: Context, hook: FakeWebhook, clock: Clock
) -> None:
    settings = settings_for()
    settings.digest = DigestSettings(
        enabled=True, weekday="sun", hour=0, timezone="UTC", channels=["slack"]
    )
    when = clock() - timedelta(days=1)
    append_entry(toy, "toy", f"hook is {hook.url}", "human:sv", day=when.date(), now=when)
    assert primed(toy, settings, clock).digests() == ["toy"]
    (path,) = (toy.layout.home / "notify" / "outbox").glob("*.slack.json")
    assert hook.secret not in path.read_text() and "***" in path.read_text()


def test_a_full_notebook_day_never_stops_digests_or_delivery(
    toy: Context, hook: FakeWebhook, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = settings_for()
    settings.digest = DigestSettings(
        enabled=True, weekday="sun", hour=0, timezone="UTC", channels=["slack"]
    )
    notifier = primed(toy, settings, clock)
    monkeypatch.setattr(notebook_module, "NOTEBOOK_MAX_BYTES", 10)  # today's page is full
    end_run(toy, "r1", "failed")
    notifier.tick()
    assert sorted(r["body"]["text"][:1] for r in hook.requests) == ["Σ", "✗"]
    state = json.loads((toy.layout.home / "notify" / "digest.json").read_text())
    assert state == {"toy": "2026-W40"}  # sent once: the next tick does not retry the week
    assert "— digest" not in read_day(toy, "toy", date(2026, 10, 4)).text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_digest.py tests/notify/test_notifier.py -v`
Expected: FAIL at collection with `ImportError: cannot import name 'digest_due' from 'hypothex.core.digest'`.

- [ ] **Step 3: Write the implementation**

In `src/hypothex/core/digest.py`, add to the imports:

```python
import logging
from zoneinfo import ZoneInfo

from hypothex.core.notebook import NotebookTooLargeError, append_entry, read_day, today
from hypothex.core.settings import Channel, DigestSettings, Settings
```

(merge `NotebookTooLargeError`, `append_entry`, `read_day`, `today` into the existing `hypothex.core.notebook` import), add `log = logging.getLogger(__name__)` below the imports, and append:

```python
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def digest_due(settings: DigestSettings, last_sent: str | None, now: datetime) -> str | None:
    """
    Tell whether this week's digest is due.

    Parameters
    ----------
    settings : DigestSettings
        Weekday, hour, and timezone.
    last_sent : str or None
        The week key sent last (``digest.json``).
    now : datetime
        Aware current time.

    Returns
    -------
    str or None
        This week's key when ``now`` (local) is at or after this week's
        ``weekday`` ``hour:00`` and that week was not sent; else None. Earlier
        missed weeks are never sent.
    """
    zone = ZoneInfo(settings.timezone) if settings.timezone else None
    local = now.astimezone(zone) if zone is not None else now.astimezone()
    key = week_key(local)
    if last_sent == key:
        return None
    return key if local >= digest_due_at(settings, now) else None


def digest_due_at(settings: DigestSettings, now: datetime) -> datetime:
    """
    Return this week's send time: ``weekday`` at ``hour:00`` in the digest's zone.

    A scheduled digest ends its window here (not at the tick that sends it), so
    a resend after a crash builds the same window, notice id, and notebook stamp.

    Parameters
    ----------
    settings : DigestSettings
        Weekday, hour, and timezone (the machine's zone when unset).
    now : datetime
        Aware time in the week.

    Returns
    -------
    datetime
        Aware, in the digest's zone.

    Examples
    --------
    >>> from datetime import UTC
    >>> s = DigestSettings(enabled=True, weekday="mon", hour=9, timezone="UTC")
    >>> digest_due_at(s, datetime(2026, 10, 7, 12, tzinfo=UTC)).isoformat()
    '2026-10-05T09:00:00+00:00'
    """
    zone = ZoneInfo(settings.timezone) if settings.timezone else None
    local = now.astimezone(zone) if zone is not None else now.astimezone()
    monday = local.date() - timedelta(days=local.weekday())
    day = monday + timedelta(days=WEEKDAYS.index(settings.weekday))
    return datetime(day.year, day.month, day.day, settings.hour, tzinfo=zone or local.tzinfo)


def send_digest(
    ctx: Context,
    settings: Settings,
    project: str,
    *,
    now: datetime,
    channels: list[Channel] | None = None,
    since: datetime | None = None,
) -> list[str]:
    """
    Build a project's digest, enqueue it, and save it to the notebook.

    Parameters
    ----------
    ctx : Context
    settings : Settings
    project : str
    now : datetime
        The window's end and the notebook entry's time.
    channels : list of Channel, optional
        Default ``settings.digest.channels``; unconfigured channels are dropped.
    since : datetime, optional
        Window start; default ``now - 7 days``.

    Returns
    -------
    list of str
        Channels a notice was enqueued on. A notebook day that is full
        (``NotebookTooLargeError``) loses the copy, never the digest: it is
        logged and the digest still counts as sent.

    Raises
    ------
    StoreError
        Unknown project.
    """
    from hypothex.notify.notifier import Notifier  # the notifier imports this module

    digest = build_digest(
        ctx,
        project,
        since=since or now - timedelta(days=7),
        until=now,
        top_notes=settings.digest.top_notes,
    )
    notifier = Notifier(ctx, settings, now=lambda: now)
    wanted = channels if channels is not None else settings.digest.channels
    made = notifier.enqueue(digest_notice(digest, base_url=settings.server.public_url), wanted)
    sent = [e.channel for e in made]
    if settings.digest.save_to_notebook:
        day = today(now, settings.digest.timezone)
        stamp = f"## {now.isoformat()} — {DIGEST_AUTHOR}\n"  # append_entry's entry header
        if stamp not in read_day(ctx, project, day).text:  # a resend after a crash: saved once
            body = render_digest_markdown(digest)
            try:
                append_entry(ctx, project, body, DIGEST_AUTHOR, day=day, now=now)
            except NotebookTooLargeError:
                # the notice is queued already; a retry would hit the same full day each tick
                log.warning("digest of %s not saved: notebook day %s is full", project, day)
    ctx.events.append(
        "digest.sent",
        project=project,
        payload={"project": project, "week": digest.week, "channels": sent},
    )
    return list(sent)
```

In `src/hypothex/notify/notifier.py`, add `from hypothex.core.digest import digest_due, digest_due_at, send_digest` to the imports, add to the `Notifier` class:

```python
    def digests(self) -> list[str]:
        """
        Send this week's digest for every project whose time has come.

        Returns
        -------
        list of str
            Projects sent on this call; ``<home>/notify/digest.json`` records them.
        """
        cfg = self.settings.digest
        if not cfg.enabled:
            return []
        path = self.root / "digest.json"
        try:
            state: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
        if cfg.projects == "all":
            projects = [e.project for e in self.ctx.store.list_projects()]
        else:
            projects = list(cfg.projects)
        now = self.now()
        # the week's send time, not this tick's: a resend after a crash (before digest.json
        # below) has the same window, notice id, and notebook stamp, so it is queued once
        at = digest_due_at(cfg, now)
        sent: list[str] = []
        for project in projects:
            key = digest_due(cfg, state.get(project), now)
            if key is None:
                continue
            try:
                send_digest(self.ctx, self.settings, project, now=at)
            except StoreError:
                continue
            state[project] = key
            sent.append(project)
        if sent:
            write_private(path, json.dumps(state, indent=2, sort_keys=True))
        return sent
```

and replace `tick` with:

```python
    def tick(self) -> None:
        """
        Scan the event log, send due digests, then deliver what is due.

        A digest that fails (an unreadable project file, a full disk) is logged
        by its type name and tried again next tick; it never stops delivery of
        the notices already queued.
        """
        self.scan()
        try:
            self.digests()
        except Exception as exc:  # noqa: BLE001 - delivery must not wait on a digest
            log.warning("digest failed: %s", type(exc).__name__)
        self.deliver()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_digest.py tests/notify/test_notifier.py -v`
Expected: `tests/core/test_digest.py` `13 passed`, `tests/notify/test_notifier.py` `27 passed`.

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check src`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/digest.py src/hypothex/notify/notifier.py tests/core/test_digest.py tests/notify/test_notifier.py
git commit -m "feat(digest): weekly schedule per timezone, send once, and save to the notebook"
```

---
## Part 6: Storage report and cleanup

Contract 1.9, 7 (destructive actions), 8 (failure mode 9). Every byte count comes from `measure_path` (an `lstat` walk). Cleanup is always plan, then apply with the exact byte total; every item is checked again where its file lives, so a hub's plan can never delete what the host would refuse. The HTTP routes are Task 31, the CLI Task 44.

### Task 20: Measuring, protected paths, and the storage report

**Files:**
- Create: `src/hypothex/core/storage.py`
- Test: `tests/core/test_storage.py`

**Interfaces:**
- Consumes: `Context`, `RunRecord.artifacts`, `EnvClient.get_json` (through `HostClients`), `HX_DIR`.
- Produces (contract 1.9, exact): `StorageKind`, `StorageItem`, `StorageReport`, `CleanPolicy`, `CleanItem`, `CleanPlan`, `CleanResult`, `CleanedArtifact`, `CleanRefusedError`, `HostClients`, `measure_path`, `local_usage`, `storage_report`. (`plan_clean` is Task 21; `apply_clean`, `delete_artifacts`, `cleaned_artifacts` Task 22.)
- Produces (public helpers): `LOCAL_HOST = "local"`; `CLEANABLE_SUBDIRS = ("artifacts", "pulled")`; `protected_reason(ctx, path) -> str | None` (`"protected"` for `/`, the user's home, the Hypothex home, a registered repo (current or previous) or any of their ancestors, and every path inside the Hypothex home that is not inside a run's `artifacts/` or `pulled/`, and every path in the Hypothex home below a symlinked folder; checked on the literal path and on its parent folder resolved, never following the target).
- Items (contract 1.9): one `run` item per run folder on this machine (its bytes without `artifacts/` and `pulled/`), one `artifact` item per recorded artifact path of this environment's runs whose `host` is `local` or this machine's label (missing files: `exists=False`, 0 bytes), and one `pulled` item per entry in a run's `pulled/` folder (a `pulled/` that is a symlink is not entered: its target is not the run's). Remote rows come from each host's `GET /api/v1/storage/usage`, with `host` set to the host's name; an unreachable host lands in `errors` as `{host, error}`.

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_storage.py`:

```python
import os
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from hypothex.core.context import Context
from hypothex.core.ids import utcnow
from hypothex.core.records import Artifact, RunRecord, RunStatus
from hypothex.core.storage import (
    LOCAL_HOST,
    StorageItem,
    local_usage,
    measure_path,
    protected_reason,
    storage_report,
)
from hypothex.remote.client import EnvUnreachableError
from tests.factories import make_record


def blocks(path: Path) -> int:
    info = os.lstat(path)
    return info.st_blocks * 512 if hasattr(info, "st_blocks") else info.st_size


def ended_run(
    ctx: Context,
    run_id: str,
    *,
    days_ago: float = 40,
    artifacts: list[tuple[str, Path]] | None = None,
    archived: bool = True,
    starred: bool = False,
    status: RunStatus = RunStatus.FINISHED,
    parent: str | None = None,
    environment_id: str | None = None,
    vars: dict[str, Any] | None = None,
    cwd: str | None = None,
) -> RunRecord:
    ended = utcnow() - timedelta(days=days_ago)
    record = make_record(
        run_id,
        status=status,
        archived=archived,
        starred=starred,
        parent=parent,
        vars=vars or {},
        **({"cwd": cwd} if cwd is not None else {}),
        started_at=ended - timedelta(hours=1),
        ended_at=None if status == RunStatus.RUNNING else ended,
        artifacts=[Artifact(kind=k, path=str(p)) for k, p in artifacts or []],
        environment_id=environment_id or ctx.descriptor.environment_id,
    )
    ctx.create_run(record)
    return record


def write(path: Path, size: int = 10_000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


class FakeHost:
    """A connected host's env client: answers the usage route with fixed rows."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.posted: list[dict[str, Any]] = []

    def get_json(self, path: str, **params: Any) -> Any:
        assert path == "/api/v1/storage/usage"
        return [
            r for r in self.rows if "project" not in params or r["project"] == params["project"]
        ]

    def post_json(self, path: str, body: dict[str, Any]) -> Any:
        if path == "/api/v1/storage/check":
            return []  # read-only preflight; dedicated tests inject alias refusals
        assert path == "/api/v1/storage/delete"
        self.posted.append(body)
        return {"plan_id": body["plan_id"], "deleted": body["items"], "skipped": [],
                "freed_bytes": sum(i["bytes"] for i in body["items"]), "errors": []}  # fmt: skip


class FakeHosts:
    """``HostClients`` with one live host (``gpu1``) and one that does not answer."""

    def __init__(self, gpu1: FakeHost) -> None:
        self.gpu1 = gpu1

    def names(self) -> list[str]:
        return ["gpu1", "dead"]

    def client(self, name: str) -> Any:
        if name == "dead":
            raise EnvUnreachableError("dead did not answer")
        return self.gpu1

    def host_for_environment(self, environment_id: str) -> str | None:
        return "gpu1" if environment_id == "env-gpu1" else None


def remote_row(run_id: str, path: str, *, kind: str = "artifact", **over: Any) -> dict[str, Any]:
    ended = (utcnow() - timedelta(days=40)).isoformat()
    row: dict[str, Any] = {
        "project": "toy", "run_id": run_id, "host": "local", "environment_id": "env-gpu1",
        "kind": kind, "artifact_kind": "checkpoint" if kind == "artifact" else None,
        "path": path, "bytes": 4096, "files": 1, "mtime": 1.0, "exists": True,
        "archived": True, "starred": False, "status": "finished", "ended_at": ended,
    }  # fmt: skip
    row.update(over)
    return row


@pytest.fixture
def toy(ctx: Context, toy_repo: Path) -> Context:
    ctx.register_project(toy_repo)
    return ctx


def test_measure_path(tmp_path: Path) -> None:
    a = write(tmp_path / "d" / "a.bin", 5000)
    b = write(tmp_path / "d" / "sub" / "b.bin", 9000)
    size, files, mtime = measure_path(tmp_path / "d")
    assert (size, files) == (blocks(a) + blocks(b), 2) and mtime is not None
    assert measure_path(a)[:2] == (blocks(a), 1)
    link = tmp_path / "link.bin"
    link.symlink_to(b)
    assert measure_path(link)[0] == blocks(link)  # the link, never its target
    assert measure_path(tmp_path / "missing") == (0, 0, None)


def test_protected_paths(toy: Context, toy_repo: Path, tmp_path: Path) -> None:
    record = ended_run(toy, "r1")
    run_dir = toy.run_dir(record)
    never = [
        Path("/"),
        Path.home(),
        toy.layout.home,
        toy_repo,
        toy_repo.parent,
        run_dir / "run.yaml",
        run_dir / "artifacts",
        toy.layout.store,
    ]
    for path in never:
        assert protected_reason(toy, str(path)) == "protected", path
    assert protected_reason(toy, str(run_dir / "artifacts" / "step_1.pt")) is None
    assert protected_reason(toy, str(run_dir / "pulled" / "x" / "y.pt")) is None
    assert protected_reason(toy, str(tmp_path / "scratch" / "ckpt.pt")) is None


def test_a_symlinked_pulled_folder_is_never_entered(toy: Context, tmp_path: Path) -> None:
    keep = write(tmp_path / "unrelated" / "keep.bin")
    run_dir = toy.run_dir(ended_run(toy, "r1"))
    (run_dir / "pulled").symlink_to(keep.parent, target_is_directory=True)
    assert [i for i in local_usage(toy) if i.kind == "pulled"] == []
    # the path reads as inside pulled/, but the folder links elsewhere: never ours to delete
    assert protected_reason(toy, str(run_dir / "pulled" / "keep.bin")) == "protected"
    assert keep.exists()


def test_local_usage_lists_runs_artifacts_and_pulled(toy: Context, tmp_path: Path) -> None:
    ckpt = write(tmp_path / "scratch" / "r1.pt")
    record = ended_run(toy, "r1", artifacts=[("checkpoint", ckpt), ("log", tmp_path / "nope")])
    inside = write(toy.run_dir(record) / "artifacts" / "best.pt", 20_000)
    pulled = write(toy.run_dir(record) / "pulled" / "remote.pt", 30_000)
    items = {(i.kind, Path(i.path).name): i for i in local_usage(toy)}
    run = items[("run", "r1")]
    assert run.host == LOCAL_HOST and run.archived and run.status == RunStatus.FINISHED
    assert run.bytes > 0 and run.bytes < blocks(inside)  # artifacts/ and pulled/ left out
    art = items[("artifact", "r1.pt")]
    assert (art.artifact_kind, art.bytes, art.exists) == ("checkpoint", blocks(ckpt), True)
    assert items[("artifact", "nope")].exists is False and items[("artifact", "nope")].bytes == 0
    assert items[("pulled", "remote.pt")].bytes == blocks(pulled)


def test_mirrored_runs_list_only_their_local_copies(toy: Context, tmp_path: Path) -> None:
    record = ended_run(toy, "m1", environment_id="env-gpu1",
                       artifacts=[("checkpoint", Path("/scratch/m1.pt"))])  # fmt: skip
    write(toy.run_dir(record) / "pulled" / "m1.pt")
    kinds = sorted(i.kind for i in local_usage(toy))
    assert kinds == ["pulled", "run"]


def test_report_sums_local_and_remote(toy: Context, tmp_path: Path) -> None:
    ended_run(toy, "r1", artifacts=[("checkpoint", write(tmp_path / "s" / "r1.pt"))])
    hosts = FakeHosts(FakeHost([remote_row("g1", "/scratch/g1.pt", bytes=1_000_000)]))
    report = storage_report(toy, hosts)
    assert report.errors == [{"host": "dead", "error": "dead did not answer"}]
    remote = [i for i in report.items if i.host == "gpu1"]
    assert [(i.run_id, i.bytes) for i in remote] == [("g1", 1_000_000)]
    assert report.by_host["gpu1"] == 1_000_000
    assert report.total_bytes == sum(i.bytes for i in report.items)
    assert sum(report.by_kind.values()) == sum(report.by_project.values()) == report.total_bytes
    assert all(isinstance(i, StorageItem) for i in report.items)
    local_only = storage_report(toy, hosts, remote=False)
    assert {i.host for i in local_only.items} == {LOCAL_HOST} and local_only.errors == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_storage.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'hypothex.core.storage'`.

- [ ] **Step 3: Write the implementation**

Create `src/hypothex/core/storage.py`:

```python
"""Bytes per project, host, and kind; plan-then-apply cleanup of archived runs' artifacts.

Sizes are allocated bytes (``st_blocks * 512``) from an ``lstat`` walk that
never follows a symlink. Cleanup never deletes a run's records: only recorded
artifact paths of archived, unstarred, ended runs, and files in a run's
``pulled/`` folder, and never a protected path.
"""

from __future__ import annotations

import contextlib
import os
import stat
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pydantic import BaseModel, Field, ValidationError

from hypothex.core.context import Context
from hypothex.core.errors import HypothexError
from hypothex.core.ids import utcnow
from hypothex.core.records import RunRecord, RunStatus

if TYPE_CHECKING:
    from hypothex.remote.client import EnvClient

StorageKind = Literal["run", "artifact", "pulled"]
LOCAL_HOST = "local"
CLEANABLE_SUBDIRS = ("artifacts", "pulled")


class StorageItem(BaseModel):
    """Bytes of one run folder, artifact, or pulled file, with its run's flags."""

    project: str
    run_id: str
    host: str
    environment_id: str
    kind: StorageKind
    artifact_kind: str | None
    path: str
    bytes: int
    files: int
    mtime: float | None
    exists: bool
    archived: bool
    starred: bool
    status: RunStatus
    ended_at: datetime | None


class StorageReport(BaseModel):
    """Every item, sums by project, host, and kind, and hosts that did not answer."""

    items: list[StorageItem]
    by_project: dict[str, int]
    by_host: dict[str, int]
    by_kind: dict[str, int]
    total_bytes: int
    errors: list[dict[str, str]]
    generated_at: datetime


class CleanPolicy(BaseModel, extra="forbid"):
    """What a cleanup may take: always archived runs only (spec 9)."""

    archived: Literal[True] = True
    older_than_days: int = Field(30, ge=0)
    kinds: list[str] = Field(default_factory=lambda: ["checkpoint"])
    projects: list[str] | None = None
    hosts: list[str] | None = None
    include_pulled: bool = True


class CleanItem(BaseModel):
    """One path a plan would delete."""

    project: str
    run_id: str
    host: str
    environment_id: str
    kind: Literal["artifact", "pulled"]
    artifact_kind: str | None
    path: str
    bytes: int
    mtime: float | None
    reason: str


class CleanPlan(BaseModel):
    """A dry run, stored in ``<home>/storage/plans/<plan_id>.json`` until applied or expired."""

    plan_id: str
    policy: CleanPolicy
    items: list[CleanItem]
    refused: list[dict[str, str]]
    total_bytes: int
    created_at: datetime
    expires_at: datetime
    created_by: str


class CleanResult(BaseModel):
    """What an apply deleted, skipped, and could not reach."""

    plan_id: str
    deleted: list[CleanItem]
    skipped: list[dict[str, Any]]
    freed_bytes: int
    errors: list[dict[str, str]]


class CleanedArtifact(BaseModel):
    """A deleted artifact, as recorded in ``<run_dir>/.hx/cleaned.json``."""

    path: str
    bytes: int
    at: datetime
    actor: str
    plan_id: str


class CleanRefusedError(HypothexError):
    """An apply with an unknown or expired plan, or a wrong byte confirmation (HTTP 400)."""


class HostClients(Protocol):
    """The hub's connected hosts (``api.app.HubManager`` satisfies it)."""

    def names(self) -> list[str]:
        """Remote host names."""
        ...

    def client(self, name: str) -> EnvClient:
        """A connected host's client; ``HostUnavailableError`` when not connected."""
        ...

    def host_for_environment(self, environment_id: str) -> str | None:
        """The host that serves an environment, or None."""
        ...


def _allocated(info: os.stat_result) -> int:
    blocks = getattr(info, "st_blocks", None)
    return int(blocks) * 512 if blocks is not None else int(info.st_size)


def measure_path(path: Path) -> tuple[int, int, float | None]:
    """
    Measure a file or folder without following symlinks.

    Parameters
    ----------
    path : Path

    Returns
    -------
    tuple of (int, int, float or None)
        ``(bytes, files, newest mtime)``; ``(0, 0, None)`` when the path is
        missing. A symlink counts as one small file (the link itself).
    """
    try:
        info = os.lstat(path)
    except OSError:
        return 0, 0, None
    if not stat.S_ISDIR(info.st_mode):
        return _allocated(info), 1, info.st_mtime
    total, files, newest = 0, 0, info.st_mtime
    stack = [path]
    while stack:
        folder = stack.pop()
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for entry in entries:
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            newest = max(newest, st.st_mtime)
            if stat.S_ISDIR(st.st_mode):
                stack.append(Path(entry.path))
            else:
                total += _allocated(st)
                files += 1
    return total, files, newest


def _forms(path: str) -> set[Path]:
    """The literal absolute path, and the same name under its resolved parent folder."""
    literal = Path(os.path.abspath(path))
    forms = {literal}
    with contextlib.suppress(OSError):
        forms.add(literal.parent.resolve() / literal.name)
    return forms


def _roots(ctx: Context) -> set[Path]:
    roots = {Path("/"), Path.home(), ctx.layout.home}
    for entry in ctx.store.list_projects():
        roots.update(Path(p) for p in [entry.repo, *entry.previous_repos])
    resolved = set()
    for root in roots:
        resolved.add(Path(os.path.abspath(root)))
        with contextlib.suppress(OSError):
            resolved.add(root.resolve())
    return resolved


def _linked_below(home: Path, path: Path) -> bool:
    """True when a folder between ``home`` and ``path`` is a symlink (its target is not ours)."""
    folder = home
    for part in path.relative_to(home).parts[:-1]:
        folder = folder / part
        if folder.is_symlink():
            return True
    return False


def protected_reason(ctx: Context, path: str) -> str | None:
    """
    Tell whether cleanup must never delete a path.

    Parameters
    ----------
    ctx : Context
    path : str
        Absolute path on this machine.

    Returns
    -------
    str or None
        ``"protected"`` for ``/``, the user's home, the Hypothex home, a
        registered repo or any of their ancestors, any path in the Hypothex
        home outside a run's ``artifacts/`` or ``pulled/``, and any path in
        the Hypothex home below a symlinked folder (a ``pulled/`` that links
        elsewhere reads as ours but is not); else None.
    """
    roots = _roots(ctx)
    home = ctx.layout.home
    for form in _forms(path):
        if any(root == form or root.is_relative_to(form) for root in roots):
            return "protected"
        if form.is_relative_to(home):
            parts = form.relative_to(home).parts
            in_run = len(parts) >= 6 and parts[0] == "store" and parts[2] == "runs"
            if not (in_run and parts[4] in CLEANABLE_SUBDIRS) or _linked_below(home, form):
                return "protected"
    return None


def _run_folder_bytes(run_dir: Path) -> tuple[int, int, float | None]:
    total, files, newest = 0, 0, None
    try:
        entries = list(os.scandir(run_dir))
    except OSError:
        return 0, 0, None
    for entry in entries:
        if entry.name in CLEANABLE_SUBDIRS:
            continue
        size, count, mtime = measure_path(Path(entry.path))
        total, files = total + size, files + count
        if mtime is not None:
            newest = mtime if newest is None else max(newest, mtime)
    return total, files, newest


def _item(record: RunRecord, kind: StorageKind, path: Path | str, **extra: Any) -> StorageItem:
    size, files, mtime = measure_path(Path(path))
    return StorageItem(
        project=record.project,
        run_id=record.run_id,
        host=LOCAL_HOST,
        environment_id=record.environment_id,
        kind=kind,
        artifact_kind=extra.get("artifact_kind"),
        path=str(path),
        bytes=extra.get("bytes", size),
        files=extra.get("files", files),
        mtime=extra.get("mtime", mtime),
        exists=os.path.lexists(path),
        archived=record.archived,
        starred=record.starred,
        status=record.status,
        ended_at=record.ended_at,
    )


def local_usage(ctx: Context, *, project: str | None = None) -> list[StorageItem]:
    """
    List the bytes of this machine's run folders, artifacts, and pulled files.

    Parameters
    ----------
    ctx : Context
    project : str, optional

    Returns
    -------
    list of StorageItem
        ``host`` is ``local`` (the hub renames rows it gets from hosts).
    """
    own = ctx.descriptor.environment_id
    labels = {"local", ctx.descriptor.label}
    items: list[StorageItem] = []
    for record in ctx.index.list_runs(project=project, include_archived=True, limit=None):
        run_dir = ctx.run_dir(record)
        size, files, mtime = _run_folder_bytes(run_dir)
        items.append(_item(record, "run", run_dir, bytes=size, files=files, mtime=mtime))
        if record.environment_id == own:
            kinds = {a.path: a.kind for a in record.artifacts if a.host in labels}
            for path, kind in kinds.items():
                items.append(_item(record, "artifact", path, artifact_kind=kind))
        pulled = run_dir / "pulled"
        if pulled.is_dir() and not pulled.is_symlink():  # a linked pulled/ is not ours
            for entry in sorted(pulled.iterdir()):
                items.append(_item(record, "pulled", entry))
    return items


def _brief(exc: BaseException) -> str:
    return (str(exc).strip() or type(exc).__name__)[:300]


def _remote_usage(
    hosts: HostClients, project: str | None
) -> tuple[list[StorageItem], list[dict[str, str]]]:
    items: list[StorageItem] = []
    errors: list[dict[str, str]] = []
    params = {"project": project} if project else {}
    for name in hosts.names():
        try:
            rows = hosts.client(name).get_json("/api/v1/storage/usage", **params)
            items += [StorageItem.model_validate(r).model_copy(update={"host": name}) for r in rows]
        except (HypothexError, ValueError, ValidationError, TypeError) as exc:
            errors.append({"host": name, "error": _brief(exc)})
    return items, errors


def _sums(items: list[StorageItem], key: str) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for item in items:
        out[getattr(item, key)] += item.bytes
    return dict(sorted(out.items()))


def storage_report(
    ctx: Context,
    hosts: HostClients | None,
    *,
    project: str | None = None,
    remote: bool = True,
) -> StorageReport:
    """
    Report bytes here and, through the hub's host clients, on every host.

    Parameters
    ----------
    ctx : Context
    hosts : HostClients or None
        None on an env server or with no hub.
    project : str, optional
    remote : bool
        Ask the hosts too.

    Returns
    -------
    StorageReport
    """
    items = local_usage(ctx, project=project)
    errors: list[dict[str, str]] = []
    if remote and hosts is not None:
        more, errors = _remote_usage(hosts, project)
        items += more
    return StorageReport(
        items=items,
        by_project=_sums(items, "project"),
        by_host=_sums(items, "host"),
        by_kind=_sums(items, "kind"),
        total_bytes=sum(i.bytes for i in items),
        errors=errors,
        generated_at=utcnow(),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_storage.py -v`
Expected: `6 passed`.

Run: `uv run ruff check src/hypothex/core/storage.py tests/core/test_storage.py && uv run ruff format --check src/hypothex/core/storage.py tests/core/test_storage.py && uv run ty check src`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/storage.py tests/core/test_storage.py
git commit -m "feat(storage): measure runs, artifacts, and pulled files here and on hosts"
```

---

### Task 21: Cleanup plans (`plan_clean`)

The remote preflight call introduced here is served by Task 31 using Task 22's `check_artifacts`. Task 21 unit tests use `FakeHost`; assembled remote tests run after Task 31. A host without the check route is refused during planning, never assumed safe.

**Files:**
- Modify: `src/hypothex/core/storage.py`
- Test: `tests/core/test_storage.py` (append)

**Interfaces:**
- Produces (contract 1.9, exact): `plan_clean(ctx, hosts, policy, *, created_by, settings, now=None) -> CleanPlan`.
- Produces (public helpers): `PLAN_ID` (regex `^cp-[0-9a-f]{8}$`); `plans_dir(layout) -> Path` (`<home>/storage/plans`); `eligible(item, cutoff) -> bool`; `input_paths(record, *, local=False) -> list[str]` (checkpoint paths relative to recorded cwd; locally also resolved reader targets); `overlaps(a, b, *, local=False) -> bool` (equal/ancestor paths; locally parent-resolved aliases, preserving deletion-leaf symlinks). Remote candidates require the read-only owning-environment preflight from Tasks 22 and 31; a failed/unavailable check refuses those candidates.
- Rules: an item is planned when its run is archived, unstarred, ended, `ended_at <= now − older_than_days`, it exists, its kind is in `kinds` (`["*"]` = every kind) or it is a `pulled` item (with `include_pulled`), and it matches `projects`/`hosts`. It is **refused** (listed in `refused` as `{path, run_id, reason}`) when another run that is not eligible records, on the same host, the same path as an artifact or a path inside or above it (`overlaps`: an archived run that owns the folder `/scratch/models` must not take a starred run's `/scratch/models/best.pt` with it), or reads it (or a path inside or above it) as an input (`input_paths`: `vars["checkpoint"]`, which `control.reinfer` sets and never records as an artifact) — `used by <run_id>`, e.g. an unarchived or queued `reinfer` child; a reader whose host the hub cannot tell blocks the path on every host — or the path is protected: here by `protected_reason`; for a host by what the hub knows (`/`, inside that host's run folder outside `artifacts/`/`pulled/`, a mapped checkout or the host's absolute Hypothex home, or an ancestor of one) — the owning host also preflights every remaining candidate through `/storage/check`, resolving its own aliases; it checks again at delete. A path two eligible runs share is planned once. The plan expires after `settings.plan_ttl_minutes`, is written 0600, older expired plans are pruned, and `storage.plan_created` `{plan_id, total_bytes, n_items}` is emitted.

- [ ] **Step 1: Write the failing test**

Append to `tests/core/test_storage.py` (and add `import stat`, `from hypothex.core.settings import StorageSettings`, `from hypothex.remote.config import EnvironmentsFile, HostSpec, save_hosts`, and `CleanPlan, CleanPolicy, plan_clean, plans_dir` to the `hypothex.core.storage` import):

```python
SETTINGS = StorageSettings(plan_ttl_minutes=60)


def plan(ctx: Context, hosts: Any = None, **policy: Any) -> CleanPlan:
    return plan_clean(ctx, hosts, CleanPolicy(**policy), created_by="human:sv", settings=SETTINGS)


@pytest.fixture
def lab(toy: Context, tmp_path: Path) -> Context:
    scratch = tmp_path / "scratch"
    ended_run(toy, "old", artifacts=[("checkpoint", write(scratch / "old.pt"))])
    ended_run(toy, "recent", days_ago=10, artifacts=[("checkpoint", write(scratch / "recent.pt"))])
    ended_run(toy, "starred", starred=True, artifacts=[("checkpoint", write(scratch / "s.pt"))])
    ended_run(toy, "visible", archived=False, artifacts=[("checkpoint", write(scratch / "v.pt"))])
    ended_run(toy, "logs", artifacts=[("log", write(scratch / "train.log"))])
    shared = write(scratch / "shared.pt")
    ended_run(toy, "parent", artifacts=[("checkpoint", shared)])
    # what control.reinfer really writes: the input in vars, no child artifact
    ended_run(toy, "child", archived=False, parent="parent", vars={"checkpoint": str(shared)})
    return toy


def test_plan_lists_only_eligible_artifacts(lab: Context) -> None:
    result = plan(lab)
    assert [i.run_id for i in result.items] == ["old"]
    assert result.items[0].reason == "archived 40d"
    assert result.refused == [
        {"path": result.refused[0]["path"], "run_id": "parent", "reason": "used by child"}
    ]
    assert result.total_bytes == result.items[0].bytes
    assert sorted(i.run_id for i in plan(lab, kinds=["*"]).items) == ["logs", "old"]
    assert sorted(i.run_id for i in plan(lab, older_than_days=7).items) == ["old", "recent"]


def test_a_folder_artifact_holding_a_kept_file_is_refused(toy: Context, tmp_path: Path) -> None:
    models = tmp_path / "scratch" / "models"
    best = write(models / "best.pt")
    ended_run(toy, "old", artifacts=[("checkpoint", models)])
    ended_run(toy, "kept", starred=True, artifacts=[("checkpoint", best)])
    result = plan(toy)
    assert result.items == []
    assert result.refused == [{"path": str(models), "run_id": "old", "reason": "used by kept"}]


@pytest.mark.parametrize("alias", ["relative", "parent-symlink", "leaf-symlink"])
def test_plan_protects_checkpoint_input_aliases(toy: Context, tmp_path: Path, alias: str) -> None:
    checkpoint = write(tmp_path / "data" / "p.pt")
    parent = tmp_path / "alias"
    parent.symlink_to(checkpoint.parent, target_is_directory=True)
    leaf = tmp_path / "input.pt"
    leaf.symlink_to(checkpoint)
    value = {
        "relative": "data/p.pt",
        "parent-symlink": str(parent / "p.pt"),
        "leaf-symlink": str(leaf),
    }[alias]
    ended_run(toy, "parent", artifacts=[("checkpoint", checkpoint)])
    ended_run(toy, "reader", archived=False, vars={"checkpoint": value}, cwd=str(tmp_path))
    result = plan(toy)
    assert result.items == [] and checkpoint.exists()
    assert [row["reason"] for row in result.refused] == ["used by reader"]


def test_protected_artifacts_are_refused(toy: Context, toy_repo: Path) -> None:
    ended_run(toy, "bad", artifacts=[("checkpoint", toy_repo)])
    result = plan(toy)
    assert result.items == []
    assert result.refused == [{"path": str(toy_repo), "run_id": "bad", "reason": "protected"}]


def test_pulled_files_follow_include_pulled(toy: Context) -> None:
    record = ended_run(toy, "m1", environment_id="env-gpu1")
    write(toy.run_dir(record) / "pulled" / "m1.pt")
    assert [i.kind for i in plan(toy).items] == ["pulled"]
    assert plan(toy, include_pulled=False).items == []


def test_plan_file_event_and_expiry(lab: Context) -> None:
    before = lab.events.last_sequence()
    result = plan(lab)
    assert result.plan_id.startswith("cp-") and len(result.plan_id) == 11
    assert result.expires_at - result.created_at == timedelta(minutes=60)
    path = plans_dir(lab.layout) / f"{result.plan_id}.json"
    assert CleanPlan.model_validate_json(path.read_text()) == result
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    (event,) = [e for e in lab.events.since(before) if e.type == "storage.plan_created"]
    assert event.payload == {
        "plan_id": result.plan_id,
        "total_bytes": result.total_bytes,
        "n_items": 1,
    }
    later = plan_clean(
        lab, None, CleanPolicy(), created_by="human:sv", settings=SETTINGS,
        now=result.expires_at + timedelta(seconds=1),
    )  # fmt: skip
    assert not path.exists() and (plans_dir(lab.layout) / f"{later.plan_id}.json").exists()


def test_project_and_host_filters(lab: Context) -> None:
    assert plan(lab, projects=["other"]).items == []
    assert plan(lab, hosts=["gpu1"]).items == []


def test_unavailable_remote_preflight_refuses_candidates(toy: Context) -> None:
    class NoCheck(FakeHost):
        def post_json(self, path: str, body: dict[str, Any]) -> Any:
            if path == "/api/v1/storage/check":
                raise EnvUnreachableError("check unavailable")
            return super().post_json(path, body)

    result = plan(toy, FakeHosts(NoCheck([remote_row("g1", "/scratch/g1.pt")])))
    assert result.items == [] and result.total_bytes == 0
    assert result.refused[0]["reason"].startswith("host check failed:")


def test_remote_items_and_remote_protection(toy: Context) -> None:
    save_hosts(
        toy.layout,
        EnvironmentsFile(
            environments={
                "gpu1": HostSpec(route="url", url="http://127.0.0.1:9", home="/home/hx/.hypothex",
                                 projects={"toy": "/home/hx/toy"}),
            }
        ),
    )  # fmt: skip
    run_dir = "/home/hx/.hypothex/store/toy/runs/g1"
    rows = [
        remote_row("g1", run_dir, kind="run"),
        remote_row("g1", "/scratch/g1.pt"),
        remote_row("g1", f"{run_dir}/predictions/p.jsonl"),
        remote_row("g2", "/home/hx/toy"),
        remote_row("g3", "/scratch/live.pt", archived=False),
        remote_row("g4", "/scratch/live.pt"),
    ]
    result = plan(toy, FakeHosts(FakeHost(rows)))
    assert [(i.host, i.path) for i in result.items] == [("gpu1", "/scratch/g1.pt")]
    reasons = {(r["run_id"], r["reason"]) for r in result.refused}
    assert reasons == {("g1", "protected"), ("g2", "protected"), ("g4", "used by g3")}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_storage.py -v`
Expected: FAIL at collection with `ImportError: cannot import name 'CleanPolicy'`... (or `plan_clean`) `from 'hypothex.core.storage'`.

- [ ] **Step 3: Write the implementation**

In `src/hypothex/core/storage.py`, add to the imports:

```python
import re
import secrets
from datetime import timedelta

from hypothex.core.layout import Layout
from hypothex.core.records import TERMINAL_STATUSES
from hypothex.core.settings import StorageSettings, write_private
```

(merge `TERMINAL_STATUSES` into the existing `hypothex.core.records` import, and `timedelta` into the `datetime` import), and append:

```python
STORAGE_DIR = "storage"
PLANS_DIR = "plans"
PLAN_ID = re.compile(r"^cp-[0-9a-f]{8}$")


def plans_dir(layout: Layout) -> Path:
    """
    Return the folder of stored cleanup plans.

    Parameters
    ----------
    layout : Layout

    Returns
    -------
    Path
        ``<home>/storage/plans``.
    """
    return layout.home / STORAGE_DIR / PLANS_DIR


def eligible(item: StorageItem, cutoff: datetime) -> bool:
    """
    Tell whether an item's run may lose its artifacts.

    Parameters
    ----------
    item : StorageItem
    cutoff : datetime
        ``now - older_than_days``.

    Returns
    -------
    bool
        Archived, unstarred, ended, and ended at or before ``cutoff``.
    """
    return (
        item.archived
        and not item.starred
        and item.status in TERMINAL_STATUSES
        and item.ended_at is not None
        and item.ended_at <= cutoff
    )


def input_paths(record: RunRecord, *, local: bool = False) -> list[str]:
    """List checkpoint inputs, relative to the run's recorded working directory.

    Parameters
    ----------
    record : RunRecord
    local : bool
        Resolve filesystem aliases only on the environment that owns the run.
        Readers follow a final symlink; artifact deletion only unlinks that leaf.

    Returns
    -------
    list of str
        Absolute lexical path and, locally, its resolved input target.
    """
    value = record.vars.get("checkpoint")
    if not isinstance(value, str) or not value:
        return []
    path = Path(value)
    if not path.is_absolute():
        path = Path(record.cwd) / path
    paths = {os.path.normpath(str(path))}
    if local:
        with contextlib.suppress(OSError, RuntimeError):
            paths.add(str(path.resolve()))
    return sorted(paths)


def overlaps(a: str, b: str, *, local: bool = False) -> bool:
    """Compare equal/ancestor paths, resolving parent aliases only on their owner.

    Parameters
    ----------
    a, b : str
        Absolute POSIX paths; reader targets have already passed ``input_paths``.
    local : bool
        Include parent-resolved forms without following the deletion leaf.

    Returns
    -------
    bool
        Whether deleting either path touches the other.
    """
    left = _forms(a) if local else {Path(os.path.normpath(a))}
    right = _forms(b) if local else {Path(os.path.normpath(b))}
    return any(x == y or x in y.parents or y in x.parents for x in left for y in right)


def _settled_by(record: RunRecord, cutoff: datetime) -> bool:
    return (
        record.archived
        and not record.starred
        and record.status in TERMINAL_STATUSES
        and record.ended_at is not None
        and record.ended_at <= cutoff
    )


def _input_readers(
    ctx: Context, hosts: HostClients | None
) -> dict[str, list[tuple[str, RunRecord]]]:
    """Host name (``"*"`` when unknown) -> ``[(input path, run)]`` for runs that read inputs."""
    own = ctx.descriptor.environment_id
    out: dict[str, list[tuple[str, RunRecord]]] = defaultdict(list)
    for record in ctx.index.list_runs(include_archived=True, limit=None):
        paths = input_paths(record, local=record.environment_id == own)
        if not paths:
            continue
        if record.environment_id == own:
            host: str | None = LOCAL_HOST
        else:
            host = hosts.host_for_environment(record.environment_id) if hosts else None
        out[host or "*"] += [(path, record) for path in paths]
    return out


def _wanted(item: StorageItem, policy: CleanPolicy) -> bool:
    if item.kind == "run" or not item.exists:
        return False
    if policy.projects is not None and item.project not in policy.projects:
        return False
    if policy.hosts is not None and item.host not in policy.hosts:
        return False
    if item.kind == "pulled":
        return policy.include_pulled
    return "*" in policy.kinds or item.artifact_kind in policy.kinds


def _covers(root: str, path: str) -> bool:
    """True when ``path`` is ``root`` or one of its ancestors (POSIX paths)."""
    root_parts = Path(root).parts
    path_parts = Path(path).parts
    return root_parts[: len(path_parts)] == path_parts


def _remote_protected(ctx: Context, item: StorageItem, items: list[StorageItem]) -> str | None:
    """What the hub can tell about a host path; the host checks everything again."""
    from hypothex.core.errors import ConfigError
    from hypothex.remote.config import load_hosts

    if item.path in ("/", ""):
        return "protected"
    for run in items:
        if run.kind == "run" and run.host == item.host and run.run_id == item.run_id:
            parts = Path(item.path).parts
            base = Path(run.path).parts
            if parts[: len(base)] == base:
                inside = parts[len(base) :]
                if len(inside) < 2 or inside[0] not in CLEANABLE_SUBDIRS:
                    return "protected"
    try:
        spec = load_hosts(ctx.layout).environments.get(item.host)
    except ConfigError:
        spec = None
    roots = [] if spec is None else [*spec.projects.values(), spec.home]
    if any(r.startswith("/") and _covers(r, item.path) for r in roots):
        return "protected"
    return None


def _prune_plans(layout: Layout, now: datetime) -> None:
    folder = plans_dir(layout)
    for path in folder.glob("cp-*.json") if folder.is_dir() else []:
        try:
            if CleanPlan.model_validate_json(path.read_text(encoding="utf-8")).expires_at <= now:
                path.unlink(missing_ok=True)
        except (OSError, ValidationError):
            path.unlink(missing_ok=True)


def plan_clean(
    ctx: Context,
    hosts: HostClients | None,
    policy: CleanPolicy,
    *,
    created_by: str,
    settings: StorageSettings,
    now: datetime | None = None,
) -> CleanPlan:
    """
    Make a dry-run cleanup plan and store it until it is applied or expires.

    Parameters
    ----------
    ctx : Context
    hosts : HostClients or None
        The hub's hosts (their artifacts are planned too).
    policy : CleanPolicy
    created_by : str
        Who asked (``human:<user>``).
    settings : StorageSettings
        ``plan_ttl_minutes``.
    now : datetime, optional

    Returns
    -------
    CleanPlan
        Planned items, refused paths with reasons, and the byte total to confirm.
    """
    moment = now or utcnow()
    _prune_plans(ctx.layout, moment)
    report = storage_report(ctx, hosts)
    cutoff = moment - timedelta(days=policy.older_than_days)
    # host -> every recorded artifact or pulled file there; a folder artifact that holds
    # another run's file (or sits inside one) is "used" as much as the same path is
    users: dict[str, list[StorageItem]] = defaultdict(list)
    for item in report.items:
        if item.kind != "run":
            users[item.host].append(item)
    readers = _input_readers(ctx, hosts)
    items: list[CleanItem] = []
    refused: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in report.items:
        if not _wanted(item, policy) or not eligible(item, cutoff):
            continue
        key = (item.host, item.path)
        blockers = [
            o.run_id
            for o in users[item.host]
            if o.run_id != item.run_id
            and overlaps(o.path, item.path, local=item.host == LOCAL_HOST)
            and not eligible(o, cutoff)
        ]
        blockers += [
            r.run_id
            for path, r in [*readers.get(item.host, []), *readers.get("*", [])]
            if r.run_id != item.run_id
            and overlaps(
                path,
                item.path,
                local=item.host == LOCAL_HOST and r.environment_id == ctx.descriptor.environment_id,
            )
            and not _settled_by(r, cutoff)
        ]
        if blockers:
            reason = f"used by {blockers[0]}"
            refused.append({"path": item.path, "run_id": item.run_id, "reason": reason})
            continue
        if item.host == LOCAL_HOST:
            why = protected_reason(ctx, item.path)
        else:
            why = _remote_protected(ctx, item, report.items)
        if why is not None:
            refused.append({"path": item.path, "run_id": item.run_id, "reason": why})
            continue
        if key in seen:
            continue
        seen.add(key)
        assert item.ended_at is not None
        items.append(
            CleanItem(
                project=item.project,
                run_id=item.run_id,
                host=item.host,
                environment_id=item.environment_id,
                kind="pulled" if item.kind == "pulled" else "artifact",
                artifact_kind=item.artifact_kind,
                path=item.path,
                bytes=item.bytes,
                mtime=item.mtime,
                reason=f"archived {(moment - item.ended_at).days}d",
            )
        )
    # The hub cannot resolve aliases in a host filesystem. Ask each owner to
    # perform the same read-only checks it will repeat under the delete lock.
    remote: dict[str, list[CleanItem]] = defaultdict(list)
    for candidate in items:
        if candidate.host != LOCAL_HOST:
            remote[candidate.host].append(candidate)
    for host, candidates in remote.items():
        try:
            if hosts is None:
                raise HypothexError(f"host {host} is not connected")
            answer = hosts.client(host).post_json(
                "/api/v1/storage/check",
                {
                    "items": [i.model_dump(mode="json") for i in candidates],
                    "older_than_days": policy.older_than_days,
                },
            )
            if not isinstance(answer, list) or any(
                not isinstance(row, dict)
                or not all(isinstance(row.get(k), str) for k in ("path", "run_id", "reason"))
                for row in answer
            ):
                raise ValueError("invalid storage check response")
            blocked = {(row["run_id"], row["path"]): row["reason"] for row in answer}
        except (HypothexError, ValueError, TypeError) as exc:
            blocked = {(i.run_id, i.path): f"host check failed: {_brief(exc)}" for i in candidates}
        for candidate in candidates:
            reason = blocked.get((candidate.run_id, candidate.path))
            if reason is not None:
                items.remove(candidate)
                refused.append(
                    {"path": candidate.path, "run_id": candidate.run_id, "reason": reason}
                )
    result = CleanPlan(
        plan_id=f"cp-{secrets.token_hex(4)}",
        policy=policy,
        items=items,
        refused=refused,
        total_bytes=sum(i.bytes for i in items),
        created_at=moment,
        expires_at=moment + timedelta(minutes=settings.plan_ttl_minutes),
        created_by=created_by,
    )
    path = plans_dir(ctx.layout) / f"{result.plan_id}.json"
    write_private(path, result.model_dump_json(indent=2))
    payload = {"plan_id": result.plan_id, "total_bytes": result.total_bytes, "n_items": len(items)}
    ctx.events.append("storage.plan_created", payload=payload)
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_storage.py -v`
Expected: all cases pass, including the round-4 regressions.

Run: `uv run ruff check src/hypothex/core/storage.py tests/core/test_storage.py && uv run ruff format --check src/hypothex/core/storage.py tests/core/test_storage.py && uv run ty check src`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/storage.py tests/core/test_storage.py
git commit -m "feat(storage): dry-run cleanup plans with shared-checkpoint and protected-path refusals"
```

---
### Task 22: Apply a plan, delete with re-checks, and record cleaned artifacts

**Files:**
- Modify: `src/hypothex/core/storage.py` (`cleanup_lock`, `check_artifacts`, `delete_artifacts`, `apply_clean`, `cleaned_artifacts`)
- Modify: `src/hypothex/core/queries.py` (`RunDetail.cleaned`, filled by `show_run`; `star_run`/`archive_run` under `cleanup_lock`)
- Modify: `src/hypothex/core/execution.py` (`_prepare_in` creates a run that reads an input under `cleanup_lock`)
- Test: `tests/core/test_storage.py` (append)

**Interfaces:**
- Produces (contract 1.9, exact): `apply_clean(ctx, hosts, plan_id, *, confirm_bytes, actor, now=None) -> CleanResult`, `delete_artifacts(ctx, items, *, actor, plan_id, older_than_days) -> CleanResult`, `cleaned_artifacts(ctx, record) -> list[CleanedArtifact]`, `cleanup_lock(layout)`, `RunDetail.cleaned: list[CleanedArtifact] = []`.
- Produces (public helper): `CLEANED_FILE = "cleaned.json"`; `record_cleaned(ctx, run_id, items, *, actor, plan_id) -> None` (appends to `<run_dir>/.hx/cleaned.json` under the run lock and emits `run.artifacts_cleaned` `{paths, freed_bytes, plan_id}`; the hub calls it for mirrored runs after a host deleted).
- Rules: `apply_clean` refuses (`CleanRefusedError`, nothing deleted) an id that is not `cp-<8 hex>` or has no plan file, an expired plan (the file is removed), and a `confirm_bytes` that is not the plan's `total_bytes` (the plan stays). Otherwise it removes the plan file first (one use), deletes local items with `delete_artifacts`, sends each host's items to that host's `POST /api/v1/storage/delete` (command id `<plan_id>:<host>`) and records the deleted ones on the hub's mirrored runs, puts an unreachable host in `errors` while other hosts go on, and emits `storage.cleaned` `{plan_id, freed_bytes, n_deleted, n_skipped}`. `delete_artifacts` re-checks every item where the file lives, with the plan's own `older_than_days` (apply passes `plan.policy.older_than_days` to it and to each host's delete route): run known, archived, unstarred, ended, and ended at or before `now − older_than_days` (`too recent`); the path still a recorded artifact of that run with that kind (or inside its `pulled/`); no other run that is not archived-unstarred-ended-by-that-cutoff records it, or a path inside or above it (`overlaps`), as an artifact (`used by <id>`); not protected; still there; bytes and mtime unchanged (`changed since plan`). The `used by` check also covers runs that read the path as an input (`input_paths`, `overlaps`), so a `reinfer` child queued after the plan keeps its checkpoint, and so does an archived child that ended yesterday under a 30-day policy. The whole check-and-delete runs under `cleanup_lock` (`<home>/storage/.lock`, cross-process) with the index read inside it; creating a run that reads an input (`execution._prepare_in`), `star_run`, and `archive_run` take the same lock, so a reader or owner made or changed during an apply waits for it to end instead of slipping between a check and its deletion (deleting files takes seconds; these are rare user actions). A failing check puts `{path, run_id, host, reason}` in `skipped`. A symlink is unlinked, never its target; a folder is removed with `shutil.rmtree` (which unlinks symlinks inside it). `run.yaml` is never written.

- [ ] **Step 1: Write the failing test**

Append to `tests/core/test_storage.py` (and add `import fcntl`, `import json`, `import sys`, `import threading`, `import pytest`, `import hypothex.core.storage as storage_module`, `from hypothex.core.execution import RunRequest, prepare_run`, `from hypothex.core.queries import show_run`, and `CleanRefusedError, CleanItem, apply_clean, cleaned_artifacts, cleanup_lock, delete_artifacts, input_paths` to the `hypothex.core.storage` import):

```python
def test_apply_frees_exactly_the_planned_bytes(lab: Context) -> None:
    result = plan(lab)
    (item,) = result.items
    record = lab.find_record("old")
    run_yaml = (lab.run_dir(record) / "run.yaml").read_bytes()
    before = lab.events.last_sequence()
    total = result.total_bytes
    done = apply_clean(lab, None, result.plan_id, confirm_bytes=total, actor="human:sv")
    assert done.freed_bytes == total and done.deleted == [item] and done.skipped == []
    assert not Path(item.path).exists()
    assert (lab.run_dir(record) / "run.yaml").read_bytes() == run_yaml
    (cleaned,) = cleaned_artifacts(lab, record)
    assert (cleaned.path, cleaned.bytes, cleaned.actor, cleaned.plan_id) == (
        item.path,
        item.bytes,
        "human:sv",
        result.plan_id,
    )
    assert show_run(lab, "old").cleaned == [cleaned]
    events = {e.type: e for e in lab.events.since(before)}
    assert events["run.artifacts_cleaned"].payload == {
        "paths": [item.path],
        "freed_bytes": item.bytes,
        "plan_id": result.plan_id,
    }
    assert events["storage.cleaned"].payload == {
        "plan_id": result.plan_id,
        "freed_bytes": item.bytes,
        "n_deleted": 1,
        "n_skipped": 0,
    }
    with pytest.raises(CleanRefusedError, match="unknown plan"):
        apply_clean(lab, None, result.plan_id, confirm_bytes=result.total_bytes, actor="x")


def test_wrong_confirmation_or_expired_plan_deletes_nothing(lab: Context) -> None:
    result = plan(lab)
    path = Path(result.items[0].path)
    with pytest.raises(CleanRefusedError, match="confirm"):
        apply_clean(lab, None, result.plan_id, confirm_bytes=result.total_bytes - 1, actor="x")
    assert path.exists() and (plans_dir(lab.layout) / f"{result.plan_id}.json").exists()
    with pytest.raises(CleanRefusedError, match="expired"):
        apply_clean(
            lab, None, result.plan_id, confirm_bytes=result.total_bytes, actor="x",
            now=result.expires_at,
        )  # fmt: skip
    assert path.exists()
    with pytest.raises(CleanRefusedError, match="unknown plan"):
        apply_clean(lab, None, "../../etc/passwd", confirm_bytes=0, actor="x")


def test_changed_or_unarchived_items_are_skipped_at_apply(toy: Context, tmp_path: Path) -> None:
    scratch = tmp_path / "scratch"
    for run_id in ("a", "b", "c", "d"):
        ended_run(toy, run_id, artifacts=[("checkpoint", write(scratch / f"{run_id}.pt"))])
    result = plan(toy)
    assert len(result.items) == 4
    write(scratch / "a.pt", 50_000)  # rewritten by a job after the plan
    toy.update_run("b", "run.archived", lambda r: r.model_copy(update={"archived": False}))
    toy.update_run("c", "run.starred", lambda r: r.model_copy(update={"starred": True}))
    done = apply_clean(toy, None, result.plan_id, confirm_bytes=result.total_bytes, actor="x")
    reasons = {s["run_id"]: s["reason"] for s in done.skipped}
    assert reasons == {"a": "changed since plan", "b": "not archived", "c": "starred"}
    assert [i.run_id for i in done.deleted] == ["d"] and not (scratch / "d.pt").exists()
    assert all((scratch / f"{r}.pt").exists() for r in "abc")
    assert done.freed_bytes == done.deleted[0].bytes


def test_a_reinfer_child_queued_after_the_plan_keeps_its_input(
    toy: Context, tmp_path: Path
) -> None:
    checkpoint = write(tmp_path / "scratch" / "p.pt")
    ended_run(toy, "parent", artifacts=[("checkpoint", checkpoint)])
    result = plan(toy)
    assert [i.run_id for i in result.items] == ["parent"]
    ended_run(
        toy, "child", archived=False, status=RunStatus.RUNNING, parent="parent",
        vars={"checkpoint": str(checkpoint)},
    )  # fmt: skip
    done = apply_clean(toy, None, result.plan_id, confirm_bytes=result.total_bytes, actor="x")
    assert done.deleted == [] and checkpoint.exists()
    assert done.skipped == [
        {"path": str(checkpoint), "run_id": "parent", "host": "local", "reason": "used by child"}
    ]


@pytest.mark.parametrize("alias", ["relative", "parent-symlink", "leaf-symlink"])
def test_apply_rechecks_new_readers_through_aliases(
    toy: Context, tmp_path: Path, alias: str
) -> None:
    checkpoint = write(tmp_path / "data" / "p.pt")
    ended_run(toy, "parent", artifacts=[("checkpoint", checkpoint)])
    planned = plan(toy)
    parent = tmp_path / "alias"
    parent.symlink_to(checkpoint.parent, target_is_directory=True)
    leaf = tmp_path / "input.pt"
    leaf.symlink_to(checkpoint)
    value = {
        "relative": "data/p.pt",
        "parent-symlink": str(parent / "p.pt"),
        "leaf-symlink": str(leaf),
    }[alias]
    ended_run(
        toy,
        "reader",
        archived=False,
        status=RunStatus.RUNNING,
        vars={"checkpoint": value},
        cwd=str(tmp_path),
    )
    done = apply_clean(toy, None, planned.plan_id, confirm_bytes=planned.total_bytes, actor="x")
    assert done.deleted == [] and checkpoint.exists()
    assert [row["reason"] for row in done.skipped] == ["used by reader"]


def test_apply_skips_a_folder_that_holds_a_kept_file(toy: Context, tmp_path: Path) -> None:
    models = tmp_path / "scratch" / "models"
    best = write(models / "best.pt")
    ended_run(toy, "old", artifacts=[("checkpoint", models)])
    result = plan(toy)
    assert [i.path for i in result.items] == [str(models)]
    # starred after the plan: a run that records a file inside the planned folder
    ended_run(toy, "kept", starred=True, artifacts=[("checkpoint", best)])
    done = apply_clean(toy, None, result.plan_id, confirm_bytes=result.total_bytes, actor="x")
    assert done.deleted == [] and best.exists()
    assert [s["reason"] for s in done.skipped] == ["used by kept"]


def test_symlink_artifact_removes_the_link_only(toy: Context, tmp_path: Path) -> None:
    target = write(tmp_path / "keep" / "real.pt")
    link = tmp_path / "scratch" / "link.pt"
    link.parent.mkdir(parents=True)
    link.symlink_to(target)
    ended_run(toy, "sym", artifacts=[("checkpoint", link)])
    result = plan(toy)
    apply_clean(toy, None, result.plan_id, confirm_bytes=result.total_bytes, actor="x")
    assert not os.path.lexists(link) and target.exists()


def test_forged_items_are_rechecked(toy: Context, toy_repo: Path) -> None:
    record = ended_run(toy, "r1", artifacts=[("checkpoint", toy_repo)])
    size, _, mtime = measure_path(toy_repo)
    forged = CleanItem(
        project="toy", run_id="r1", host="local", environment_id=record.environment_id,
        kind="artifact", artifact_kind="checkpoint", path=str(toy_repo), bytes=size,
        mtime=mtime, reason="archived 40d",
    )  # fmt: skip
    not_ours = forged.model_copy(update={"path": "/etc/hosts"})
    done = delete_artifacts(
        toy, [forged, not_ours], actor="x", plan_id="cp-00000000", older_than_days=30
    )
    assert done.deleted == [] and toy_repo.is_dir()
    assert {s["reason"] for s in done.skipped} == {"protected", "not an artifact of the run"}


def test_apply_keeps_the_plan_age_for_runs_made_after_it(toy: Context, tmp_path: Path) -> None:
    checkpoint = write(tmp_path / "scratch" / "p.pt")
    ended_run(toy, "parent", artifacts=[("checkpoint", checkpoint)])
    result = plan(toy)  # older_than_days=30
    # an archived child that ended today reads the checkpoint: settled, but not 30 days old
    ended_run(toy, "child", days_ago=0, parent="parent", vars={"checkpoint": str(checkpoint)})
    done = apply_clean(toy, None, result.plan_id, confirm_bytes=result.total_bytes, actor="x")
    assert done.deleted == [] and checkpoint.exists()
    assert [s["reason"] for s in done.skipped] == ["used by child"]
    young = CleanItem.model_validate({**result.items[0].model_dump(), "run_id": "child"})
    again = delete_artifacts(toy, [young], actor="x", plan_id="cp-00000001", older_than_days=30)
    assert [s["reason"] for s in again.skipped] == ["too recent"]


def test_apply_checks_and_deletes_under_the_cleanup_lock(
    toy: Context, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ended_run(toy, "a", artifacts=[("checkpoint", write(tmp_path / "scratch" / "a.pt"))])
    result = plan(toy)
    real_remove = storage_module._remove
    held: list[bool] = []

    def remove(path: str) -> str | None:
        with (toy.layout.home / "storage" / ".lock").open("a") as fh:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                held.append(True)
            else:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                held.append(False)
        return real_remove(path)

    monkeypatch.setattr(storage_module, "_remove", remove)
    apply_clean(toy, None, result.plan_id, confirm_bytes=result.total_bytes, actor="x")
    assert held == [True]


def test_a_run_that_reads_an_input_waits_for_a_cleanup_in_progress(
    toy: Context, toy_repo: Path, tmp_path: Path
) -> None:
    checkpoint = write(tmp_path / "scratch" / "p.pt")
    request = RunRequest(
        repo=toy_repo,
        command=[sys.executable, "-c", "pass"],
        hypothesis="reads p.pt",
        vars={"checkpoint": str(checkpoint)},
    )
    made: list[RunRecord] = []
    worker = threading.Thread(target=lambda: made.append(prepare_run(toy, request)))
    with cleanup_lock(toy.layout):  # an apply is checking and deleting
        worker.start()
        worker.join(2)  # git info and dataset fingerprints take well under a second here
        assert worker.is_alive() and made == []
        assert [r for r in toy.index.list_runs(limit=None) if input_paths(r)] == []
    worker.join(30)
    assert len(made) == 1 and input_paths(made[0]) == [str(checkpoint)]


def test_remote_hosts_delete_their_items(toy: Context, tmp_path: Path) -> None:
    ended_run(toy, "g1", environment_id="env-gpu1")  # the hub's mirror of gpu1's run
    ended_run(toy, "local1", artifacts=[("checkpoint", write(tmp_path / "s" / "l.pt"))])
    gpu1 = FakeHost([remote_row("g1", "/scratch/g1.pt")])
    result = plan(toy, FakeHosts(gpu1))
    assert sorted(i.host for i in result.items) == ["gpu1", "local"]
    done = apply_clean(
        toy, FakeHosts(gpu1), result.plan_id, confirm_bytes=result.total_bytes, actor="human:sv"
    )
    assert sorted(i.run_id for i in done.deleted) == ["g1", "local1"]
    assert gpu1.posted[0]["plan_id"] == result.plan_id and gpu1.posted[0]["actor"] == "human:sv"
    assert gpu1.posted[0]["command_id"] == f"{result.plan_id}:gpu1"
    hub_file = toy.run_dir(toy.find_record("g1")) / ".hx" / "cleaned.json"
    assert [c["path"] for c in json.loads(hub_file.read_text())] == ["/scratch/g1.pt"]


def test_unreachable_host_lands_in_errors(toy: Context, tmp_path: Path) -> None:
    ended_run(toy, "local1", artifacts=[("checkpoint", write(tmp_path / "s" / "l.pt"))])
    rows = [remote_row("g9", "/scratch/g9.pt", host="local")]
    hosts = FakeHosts(FakeHost(rows))
    result = plan(toy, hosts)
    stuck = [i.model_copy(update={"host": "dead"}) for i in result.items if i.host == "gpu1"]
    stored = result.model_copy(update={"items": [*result.items, *stuck]})
    stored = stored.model_copy(update={"total_bytes": sum(i.bytes for i in stored.items)})
    path = plans_dir(toy.layout) / f"{result.plan_id}.json"
    path.write_text(stored.model_dump_json())
    done = apply_clean(toy, hosts, result.plan_id, confirm_bytes=stored.total_bytes, actor="x")
    assert {e["host"] for e in done.errors} == {"dead"}
    assert {i.run_id for i in done.deleted} == {"local1", "g9"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_storage.py -v`
Expected: FAIL at collection with `ImportError: cannot import name 'CleanItem'`... (or `apply_clean`) `from 'hypothex.core.storage'`.

- [ ] **Step 3: Write the implementation**

In `src/hypothex/core/storage.py`, add to the imports:

```python
import json
import shutil

from contextlib import AbstractContextManager

from hypothex.core.errors import StoreError
from hypothex.core.fsutil import atomic_write_text
from hypothex.core.layout import HX_DIR
from hypothex.core.store import dir_lock, run_lock
```

(merge `StoreError` into the existing `hypothex.core.errors` import and `HX_DIR` into the `hypothex.core.layout` import), and append:

```python
CLEANED_FILE = "cleaned.json"


def cleanup_lock(layout: Layout) -> AbstractContextManager[None]:
    """
    Hold the cleanup lock, ``<home>/storage/.lock`` (exclusive, across processes).

    ``delete_artifacts`` holds it while it checks and deletes. Creating a run
    that reads an input path, starring a run, and archiving or unarchiving one
    take it too, so none of them lands between a check and its deletion.

    Parameters
    ----------
    layout : Layout

    Returns
    -------
    contextlib.AbstractContextManager
        Enter to hold the lock.
    """
    return dir_lock(layout.home / STORAGE_DIR)


def _cleaned_path(ctx: Context, record: RunRecord) -> Path:
    return ctx.run_dir(record) / HX_DIR / CLEANED_FILE


def cleaned_artifacts(ctx: Context, record: RunRecord) -> list[CleanedArtifact]:
    """
    List a run's deleted artifacts (``<run_dir>/.hx/cleaned.json``).

    Parameters
    ----------
    ctx : Context
    record : RunRecord

    Returns
    -------
    list of CleanedArtifact
        Oldest first; ``[]`` when nothing was cleaned or the file is unreadable.
    """
    try:
        raw = json.loads(_cleaned_path(ctx, record).read_text(encoding="utf-8"))
        return [CleanedArtifact.model_validate(r) for r in raw]
    except (OSError, ValueError, TypeError, ValidationError):
        return []


def record_cleaned(
    ctx: Context, run_id: str, items: list[CleanItem], *, actor: str, plan_id: str
) -> None:
    """
    Append deleted items to a run's ``cleaned.json`` and emit ``run.artifacts_cleaned``.

    Parameters
    ----------
    ctx : Context
    run_id : str
    items : list of CleanItem
        Items of this run that were deleted.
    actor : str
    plan_id : str
    """
    record = ctx.find_record(run_id)
    now = utcnow()
    with run_lock(ctx.run_dir(record)):
        done = cleaned_artifacts(ctx, record)
        done += [
            CleanedArtifact(path=i.path, bytes=i.bytes, at=now, actor=actor, plan_id=plan_id)
            for i in items
        ]
        text = json.dumps([d.model_dump(mode="json") for d in done], indent=2)
        atomic_write_text(_cleaned_path(ctx, record), text)
    payload = {
        "paths": [i.path for i in items],
        "freed_bytes": sum(i.bytes for i in items),
        "plan_id": plan_id,
    }
    ctx.emit("run.artifacts_cleaned", record, payload)


def _recheck(
    ctx: Context,
    item: CleanItem,
    users: list[tuple[str, RunRecord]],
    cutoff: datetime,
) -> str | None:
    try:
        record = ctx.find_record(item.run_id)
    except StoreError:
        return "run not found"
    if not record.archived:
        return "not archived"
    if record.starred:
        return "starred"
    if record.status not in TERMINAL_STATUSES:
        return "not ended"
    if record.ended_at is None or record.ended_at > cutoff:
        return "too recent"
    if item.kind == "artifact":
        kinds = {a.kind for a in record.artifacts if a.path == item.path}
        if not kinds:
            return "not an artifact of the run"
        if item.artifact_kind is not None and item.artifact_kind not in kinds:
            return "not an artifact of the run"
    else:
        pulled = ctx.run_dir(record) / "pulled"
        if not Path(os.path.abspath(item.path)).is_relative_to(pulled):
            return "not in pulled/"
    for path, other in users:  # owners and readers; a folder holding the path counts too
        if (
            other.run_id != record.run_id
            and overlaps(path, item.path, local=True)
            and not _settled_by(other, cutoff)
        ):
            return f"used by {other.run_id}"
    why = protected_reason(ctx, item.path)
    if why is not None:
        return why
    if not os.path.lexists(item.path):
        return "gone"
    size, _, mtime = measure_path(Path(item.path))
    if size != item.bytes or mtime != item.mtime:
        return "changed since plan"
    return None


def check_artifacts(
    ctx: Context, items: list[CleanItem], *, older_than_days: int
) -> list[dict[str, str]]:
    """Check candidate artifacts on their owning environment without deleting.

    Parameters
    ----------
    ctx : Context
    items : list of CleanItem
    older_than_days : int
        Cleanup policy age cutoff.

    Returns
    -------
    list of dict
        Refused items with path, run_id, host, and reason.
    """
    cutoff = utcnow() - timedelta(days=older_than_days)
    refused: list[dict[str, str]] = []
    with cleanup_lock(ctx.layout):
        users: list[tuple[str, RunRecord]] = []
        own = ctx.descriptor.environment_id
        for record in ctx.index.list_runs(include_archived=True, limit=None):
            if record.environment_id != own:
                continue
            users += [(a.path, record) for a in record.artifacts]
            users += [(path, record) for path in input_paths(record, local=True)]
        for item in items:
            why = _recheck(ctx, item, users, cutoff)
            if why is not None:
                refused.append(
                    {"path": item.path, "run_id": item.run_id, "host": item.host, "reason": why}
                )
    return refused


def _remove(path: str) -> str | None:
    try:
        if os.path.islink(path) or not os.path.isdir(path):
            os.unlink(path)
        else:
            shutil.rmtree(path)
    except OSError as exc:
        return exc.strerror or type(exc).__name__
    return None


def delete_artifacts(
    ctx: Context, items: list[CleanItem], *, actor: str, plan_id: str, older_than_days: int
) -> CleanResult:
    """
    Delete planned items on this machine, checking each one again first.

    Parameters
    ----------
    ctx : Context
    items : list of CleanItem
        Items whose files live here.
    actor : str
        Who applied the plan.
    plan_id : str
    older_than_days : int
        The plan's policy: the item's run, and every other run that records
        or reads its path, counts as settled only when it ended at or before
        ``now - older_than_days``.

    Returns
    -------
    CleanResult
        Deleted items, ``skipped`` entries ``{path, run_id, host, reason}``,
        and the freed bytes.
    """
    cutoff = utcnow() - timedelta(days=older_than_days)
    deleted: list[CleanItem] = []
    skipped: list[dict[str, Any]] = []
    with cleanup_lock(ctx.layout):
        # read under the lock: a run created, starred, or unarchived later waits for us
        # (path, run) for every artifact a run records and every input it reads
        users: list[tuple[str, RunRecord]] = []
        for record in ctx.index.list_runs(include_archived=True, limit=None):
            if record.environment_id != ctx.descriptor.environment_id:
                continue
            users += [(path, record) for path in {a.path for a in record.artifacts}]
            users += [(path, record) for path in input_paths(record, local=True)]
        for item in items:
            why = _recheck(ctx, item, users, cutoff) or _remove(item.path)
            if why is not None:
                skipped.append(
                    {"path": item.path, "run_id": item.run_id, "host": item.host, "reason": why}
                )
            else:
                deleted.append(item)
        by_run: dict[str, list[CleanItem]] = defaultdict(list)
        for item in deleted:
            by_run[item.run_id].append(item)
        for run_id, done in by_run.items():
            record_cleaned(ctx, run_id, done, actor=actor, plan_id=plan_id)
    return CleanResult(
        plan_id=plan_id,
        deleted=deleted,
        skipped=skipped,
        freed_bytes=sum(i.bytes for i in deleted),
        errors=[],
    )


def apply_clean(
    ctx: Context,
    hosts: HostClients | None,
    plan_id: str,
    *,
    confirm_bytes: int,
    actor: str,
    now: datetime | None = None,
) -> CleanResult:
    """
    Apply a stored plan: delete here and on each host, once.

    Parameters
    ----------
    ctx : Context
    hosts : HostClients or None
    plan_id : str
    confirm_bytes : int
        Must equal the plan's ``total_bytes`` (the number the user typed back).
    actor : str
    now : datetime, optional

    Returns
    -------
    CleanResult

    Raises
    ------
    CleanRefusedError
        Unknown or expired plan, or a wrong ``confirm_bytes``; nothing is deleted.
    """
    unknown = CleanRefusedError(
        f"unknown plan {plan_id!r}; make one with hx storage clean --archived"
    )
    if not PLAN_ID.match(plan_id):
        raise unknown
    path = plans_dir(ctx.layout) / f"{plan_id}.json"
    try:
        plan = CleanPlan.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError):
        raise unknown from None
    if plan.expires_at <= (now or utcnow()):
        path.unlink(missing_ok=True)
        raise CleanRefusedError(f"plan {plan_id} expired; make a new one")
    if confirm_bytes != plan.total_bytes:
        raise CleanRefusedError(
            f"confirm_bytes {confirm_bytes} does not match the plan's {plan.total_bytes}"
        )
    try:
        path.unlink()  # one use, before anything is deleted
    except FileNotFoundError:
        raise unknown from None  # a concurrent apply of the same plan won the race
    local = [i for i in plan.items if i.host == LOCAL_HOST]
    days = plan.policy.older_than_days  # the plan's age rule holds at delete, here and on hosts
    result = delete_artifacts(ctx, local, actor=actor, plan_id=plan_id, older_than_days=days)
    deleted, skipped, errors = list(result.deleted), list(result.skipped), list(result.errors)
    remote: dict[str, list[CleanItem]] = defaultdict(list)
    for item in plan.items:
        if item.host != LOCAL_HOST:
            remote[item.host].append(item)
    for host, items in remote.items():
        try:
            if hosts is None:
                raise HypothexError(f"host {host} is not connected")
            body = {
                "items": [i.model_dump(mode="json") for i in items],
                "plan_id": plan_id,
                "actor": actor,
                "older_than_days": days,
                "command_id": f"{plan_id}:{host}",
            }
            answer = CleanResult.model_validate(
                hosts.client(host).post_json("/api/v1/storage/delete", body)
            )
        except (HypothexError, ValueError, ValidationError, TypeError) as exc:
            errors.append({"host": host, "error": _brief(exc)})
            continue
        done = [i.model_copy(update={"host": host}) for i in answer.deleted]
        mirrored: dict[str, list[CleanItem]] = defaultdict(list)
        for item in done:
            mirrored[item.run_id].append(item)
        for run_id, run_items in mirrored.items():
            try:
                record_cleaned(ctx, run_id, run_items, actor=actor, plan_id=plan_id)
            except StoreError:
                continue  # the hub has no copy of that run
        deleted += done
        skipped += answer.skipped
        errors += answer.errors
    freed = sum(i.bytes for i in deleted)
    ctx.events.append(
        "storage.cleaned",
        payload={
            "plan_id": plan_id,
            "freed_bytes": freed,
            "n_deleted": len(deleted),
            "n_skipped": len(skipped),
        },
    )
    return CleanResult(
        plan_id=plan_id, deleted=deleted, skipped=skipped, freed_bytes=freed, errors=errors
    )
```

In `src/hypothex/core/queries.py`, add `from hypothex.core.storage import CleanedArtifact, cleaned_artifacts` to the imports, add to `RunDetail` after `children: list[str]`:

```python
    cleaned: list[CleanedArtifact] = Field(default_factory=list)
    """Artifacts deleted by ``hx storage clean`` (``<run_dir>/.hx/cleaned.json``)."""
```

and in `show_run`, add `cleaned=cleaned_artifacts(ctx, record),` after `children=sorted(children),` in the `RunDetail(...)` call.

Still in `src/hypothex/core/queries.py`, add `cleanup_lock` to that `hypothex.core.storage` import and make starring and archiving wait for a cleanup in progress (either can turn a settled run back into one that keeps its files). Replace the body of `star_run` (after its docstring) with:

```python
    with cleanup_lock(ctx.layout):  # starring protects the run's files from a running apply
        return ctx.update_run(
            run_id, "run.starred", lambda r: r.model_copy(update={"starred": on}), {"on": on}
        )
```

and the body of `archive_run` (after its docstring) with:

```python
    with cleanup_lock(ctx.layout):  # unarchiving protects the run's files from a running apply
        return ctx.update_run(
            run_id, "run.archived", lambda r: r.model_copy(update={"archived": on}), {"on": on}
        )
```

In `src/hypothex/core/execution.py`, add `from hypothex.core.storage import cleanup_lock, input_paths` to the imports and in `_prepare_in` replace

```python
    try:
        ctx.create_run(record)
    except StoreError as exc:
        if isinstance(exc.__cause__, FileExistsError):  # the run folder exists: id clash
            raise _RunIdTakenError(run_id) from exc
        raise
    if user_config is not None:
```

with

```python
    try:
        # An input reader and cleanup serialize, while id collisions still retry.
        with cleanup_lock(ctx.layout) if input_paths(record) else contextlib.nullcontext():
            ctx.create_run(record)
    except StoreError as exc:
        if isinstance(exc.__cause__, FileExistsError):  # preserve exclusive folder ownership
            raise _RunIdTakenError(run_id) from exc
        raise
    if user_config is not None:
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_storage.py tests/core/test_queries.py tests/core/test_execution.py -v`
Expected: all storage regression cases pass; `tests/core/test_queries.py` and `tests/core/test_execution.py` still pass.

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check src`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/storage.py src/hypothex/core/queries.py src/hypothex/core/execution.py tests/core/test_storage.py
git commit -m "feat(storage): apply plans with exact confirmation and per-item re-checks"
```

---
## Part 7: Auth on the HTTP API

Contract 1.2 (identity), 1.3, 1.10 (guard, scopes, tickets), 3 (auth routes), 7 (authorization), 8 (failure modes 10–12). With auth off nothing here changes phase 1–2 behaviour: every request is `LOCAL_OWNER`, and `create_app` keeps `OriginGuard`, `TrustedHostMiddleware`, and the optional `TokenGuard`.

### Task 23: `hypothex.api.auth` — the guard, scope dependencies, identities

**Files:**
- Create: `src/hypothex/api/auth.py`
- Modify: `src/hypothex/api/security.py` (`TokenGuard` marks the request with `HOST_PRINCIPAL`)
- Modify: `src/hypothex/api/app.py` (`create_app(auth=, public_url=)`, `AuthStore` on `app.state`, `AuthGuard` when auth is on, 401/403 mapping, `annotate_scopes`)
- Create: `tests/api/authkit.py`
- Test: `tests/api/test_auth_guard.py`

**Interfaces:**
- Consumes: `AuthStore`, `Principal`, `LOCAL_OWNER`, `HOST_PRINCIPAL`, `covers`, `load_settings`.
- Produces (contract 1.10, exact): `SESSION_COOKIE = "hx_session"`, `AGENT_HEADER = "X-Hypothex-Agent"`, `SCOPE_KEY = "x-hx-scope"`, `requires(scope)`, `principal_of(request | websocket)`, `AuthGuard(app, store, *, host_token=None)`, `route_scopes(app)`.
- Produces (public helpers): `PRINCIPAL_KEY = "hx.principal"` (ASGI scope key); `PUBLIC`, `READ`, `LAUNCH`, `ADMIN` (`[requires(...)]` lists for `dependencies=`); `annotate_scopes(app)` (copies each route's scope into `openapi_extra[SCOPE_KEY]`); `auth_on(conn) -> bool`; `identity(conn, *, created_by, owner) -> tuple[str, str | None]`; `command_key(conn, command_id) -> str | None` (the receipt key of a client command id: `<user>|<scope>|<METHOD> <path>|<command_id>`; every route passes it to `EventLog.run_once` instead of the raw id, because `run_once` hands a stored result to anyone who repeats an id without running the route's checks again).
- Produces (additive, `create_app`): `auth: bool | None = None` (None = `server.auth` of `config.yaml`), `public_url: str | None = None` (None = `server.public_url`); `app.state.auth` (`AuthStore`), `app.state.auth_on`, `app.state.public_url`.
- Rules: with auth on, `AuthGuard` (outermost) turns a `Bearer` token (or the env server's `host_token`, which becomes `HOST_PRINCIPAL`), the `hx_session` cookie, or for a WebSocket a `?ticket=` into `scope["hx.principal"]`, and adds `agent` from `X-Hypothex-Agent` (a name matching `^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$`). Paths under `/api/` and `/mcp` without a principal get 401 `{error, type: "AuthError"}` with `WWW-Authenticate: Bearer realm="hypothex"` (a WebSocket is closed with 4401 before accept), except the public ones: `/.well-known/hypothex/...` and `POST /api/v1/auth/pair`. Every other path (the UI, `/pair`) is public. `identity` returns `(created_by, owner)`: the body's values from the host principal (a hub forwarding), `(created_by, None)` with auth off, else `(principal.identity(), principal.user)`. `AuthError` → 401, `ScopeError` → 403, `PairingError` → 400.

- [ ] **Step 1: Write the test helpers and the failing test**

Create `tests/api/authkit.py`:

```python
"""Test helpers: a hub app with auth on, and session tokens for each scope."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI

from hypothex.auth.scopes import Scope
from hypothex.auth.store import AuthStore, Principal

BASE = "http://127.0.0.1:7777"
WS_URL = "ws://127.0.0.1:7777/api/v1/ws"
OWNER = Principal(user="sv", scope="admin", session_id=None, client="local")


def auth_app(home: Path, **kwargs: Any) -> FastAPI:
    """A hub app with auth on, no host connections, no background loops, no UI."""
    from hypothex.api.app import create_app

    options: dict[str, Any] = {"background_repair": False, "hub": False, "auth": True}
    options.update(kwargs)
    return create_app(home, ui_dir=home / "no-ui", **options)


def token_for(store: AuthStore, user: str, scope: Scope, *, client: str = "cli") -> str:
    """A fresh session token for ``user`` (created with role ``scope`` when new)."""
    store.ensure_owner("sv")
    offer, secret = store.create_offer(issuer=OWNER, user=user, scope=scope)
    _, token = store.redeem(offer.id, secret, client=client, device="test")  # type: ignore[arg-type]
    return token


def bearer(token: str) -> dict[str, str]:
    """The ``Authorization`` header of a token."""
    return {"Authorization": f"Bearer {token}"}
```

Create `tests/api/test_auth_guard.py`:

```python
from pathlib import Path

import pytest
from fastapi import FastAPI, Request, WebSocket
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send
from starlette.websockets import WebSocketDisconnect

from hypothex.api.app import create_app
from hypothex.api.auth import (
    PRINCIPAL_KEY,
    READ,
    SCOPE_KEY,
    SESSION_COOKIE,
    AuthGuard,
    annotate_scopes,
    command_key,
    identity,
    principal_of,
    requires,
    route_scopes,
)
from hypothex.api.security import TokenGuard
from hypothex.auth.store import HOST_PRINCIPAL, LOCAL_OWNER, AuthStore, Principal, ScopeError
from hypothex.core.layout import Layout
from tests.api.authkit import BASE, WS_URL, auth_app, bearer, token_for

ALICE = Principal(user="alice", scope="launch", session_id="s_00000000000a", client="cli")


async def echo(scope: Scope, receive: Receive, send: Send) -> None:
    principal = scope.get(PRINCIPAL_KEY)
    body = None if principal is None else principal.model_dump()
    await JSONResponse({"principal": body})(scope, receive, send)


def request_as(principal: Principal | None, *, on: bool) -> Request:
    app = FastAPI()
    app.state.auth_on = on
    scope: dict = {"type": "http", "app": app, "headers": []}
    if principal is not None:
        scope[PRINCIPAL_KEY] = principal
    return Request(scope)


def test_auth_on_needs_a_session(home: Path) -> None:
    app = auth_app(home)
    with TestClient(app, base_url=BASE) as client:
        refused = client.get("/api/v1/projects")
        assert refused.status_code == 401 and refused.json()["type"] == "AuthError"
        assert refused.headers["WWW-Authenticate"] == 'Bearer realm="hypothex"'
        assert client.get("/.well-known/hypothex/environment").status_code == 200
        token = token_for(app.state.auth, "alice", "read")
        assert client.get("/api/v1/projects", headers=bearer(token)).status_code == 200
        cookie = {"Cookie": f"{SESSION_COOKIE}={token}"}
        assert client.get("/api/v1/projects", headers=cookie).status_code == 200
        assert client.get("/api/v1/projects", headers=bearer("hxs_nope")).status_code == 401


def test_revoked_session_is_401(home: Path) -> None:
    app = auth_app(home)
    store: AuthStore = app.state.auth
    token = token_for(store, "alice", "read")
    alice = store.authenticate(token)
    assert alice is not None
    store.revoke(str(alice.session_id), by=alice)
    with TestClient(app, base_url=BASE) as client:
        assert client.get("/api/v1/projects", headers=bearer(token)).status_code == 401


def test_websocket_without_a_session_is_closed_4401(home: Path) -> None:
    with TestClient(auth_app(home), base_url=BASE) as client:
        with pytest.raises(WebSocketDisconnect) as info, client.websocket_connect(WS_URL):
            pass
        assert info.value.code == 4401


def test_auth_off_is_the_local_owner(home: Path) -> None:
    app = create_app(home, background_repair=False, hub=False, ui_dir=home / "no-ui")
    assert app.state.auth_on is False
    with TestClient(app, base_url=BASE) as client:
        assert client.get("/api/v1/projects").status_code == 200
    assert principal_of(request_as(None, on=False)) == LOCAL_OWNER


def test_guards_set_the_principal(tmp_path: Path) -> None:
    store = AuthStore(Layout(tmp_path))
    token = token_for(store, "alice", "launch")
    guarded = TestClient(AuthGuard(echo, store, host_token="hubtoken"), base_url=BASE)
    me = guarded.get("/api/v1/x", headers={**bearer(token), "X-Hypothex-Agent": "claude"})
    assert me.json()["principal"]["user"] == "alice"
    assert me.json()["principal"]["agent"] == "claude"
    bad_agent = guarded.get("/api/v1/x", headers={**bearer(token), "X-Hypothex-Agent": "-x y"})
    assert bad_agent.json()["principal"]["agent"] is None
    hub = guarded.get("/api/v1/x", headers=bearer("hubtoken")).json()["principal"]
    assert hub == HOST_PRINCIPAL.model_dump()
    assert guarded.get("/pair").json() == {"principal": None}  # UI paths are public
    token_guard = TestClient(TokenGuard(echo, token="hubtoken"), base_url=BASE)
    assert token_guard.get("/x", headers=bearer("hubtoken")).json()["principal"]["client"] == "host"


def test_identity_rules() -> None:
    assert identity(request_as(ALICE, on=True), created_by="human:sv", owner="sv") == (
        "human:alice",
        "alice",
    )
    agent = ALICE.model_copy(update={"agent": "claude"})
    assert identity(request_as(agent, on=True), created_by="x", owner=None) == (
        "agent:claude@alice",
        "alice",
    )
    hub = request_as(HOST_PRINCIPAL, on=True)
    assert identity(hub, created_by="human:alice", owner="alice") == ("human:alice", "alice")
    off = request_as(None, on=False)
    assert identity(off, created_by="agent:claude", owner="sv") == ("agent:claude", None)
    assert identity(request_as(HOST_PRINCIPAL, on=False), created_by="h", owner="o") == ("h", "o")


def test_command_key_binds_the_caller_and_the_route() -> None:
    def key(principal: Principal, path: str, command_id: str | None = "c1") -> str | None:
        app = FastAPI()
        app.state.auth_on = True
        scope: dict = {"type": "http", "app": app, "headers": [], "method": "POST", "path": path}
        scope[PRINCIPAL_KEY] = principal
        return command_key(Request(scope), command_id)

    mine = key(ALICE, "/api/v1/runs/r1/tags")
    assert mine == "alice|launch|POST /api/v1/runs/r1/tags|c1"
    assert key(ALICE, "/api/v1/runs/r1/tags") == mine  # a retry finds its receipt
    admin = ALICE.model_copy(update={"scope": "admin"})
    others = {
        key(ALICE, "/api/v1/runs/r2/tags"),  # another target
        key(ALICE, "/api/v1/auth/logout"),  # another operation
        key(admin, "/api/v1/runs/r1/tags"),  # the same user's admin session
        key(HOST_PRINCIPAL, "/api/v1/runs/r1/tags"),  # a hub forwarding
    }
    assert len(others) == 4 and mine not in others
    assert key(ALICE, "/api/v1/runs/r1/tags", None) is None


def test_route_scopes_and_openapi() -> None:
    app = FastAPI()

    @app.get("/a", dependencies=READ)
    def a() -> dict[str, str]:
        return {}

    @app.post("/b", dependencies=[requires("admin")])
    def b() -> dict[str, str]:
        return {}

    @app.get("/c")
    def c() -> dict[str, str]:
        return {}

    @app.websocket("/ws", dependencies=READ)
    async def ws(socket: WebSocket) -> None:
        await socket.close()

    assert route_scopes(app) == {"GET /a": "read", "POST /b": "admin", "WS /ws": "read"}
    annotate_scopes(app)
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert paths["/a"]["get"][SCOPE_KEY] == "read" and SCOPE_KEY not in paths["/c"]["get"]


def test_scope_check_raises_scope_error() -> None:
    check = requires("admin").dependency
    with pytest.raises(ScopeError, match="admin scope needed; you hold launch"):
        check(request_as(ALICE, on=True))
    assert check(request_as(None, on=False)) == LOCAL_OWNER
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_auth_guard.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'hypothex.api.auth'`.

- [ ] **Step 3: Write `hypothex.api.auth`**

Create `src/hypothex/api/auth.py`:

```python
"""FastAPI glue for phase 3 auth: the ASGI guard, scope dependencies, and identities.

Every route declares a scope with ``dependencies=READ`` (or ``LAUNCH``,
``ADMIN``, ``PUBLIC``); ``route_scopes`` lists them, and a unit test fails on
any route without one. ``AuthGuard`` runs only with auth on; with auth off every
request is ``LOCAL_OWNER`` (phase 1-2 behaviour).
"""

from __future__ import annotations

import asyncio
import hmac
import re
from http.cookies import CookieError, SimpleCookie
from typing import Any
from urllib.parse import parse_qs

from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute, APIWebSocketRoute
from starlette.datastructures import Headers
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Send
from starlette.types import Scope as AsgiScope

from hypothex.auth.scopes import ScopeOrPublic, covers
from hypothex.auth.store import (
    HOST_PRINCIPAL,
    LOCAL_OWNER,
    AuthError,
    AuthStore,
    Principal,
    ScopeError,
)

SESSION_COOKIE = "hx_session"
AGENT_HEADER = "X-Hypothex-Agent"
SCOPE_KEY = "x-hx-scope"
PRINCIPAL_KEY = "hx.principal"
CREDENTIAL_KEY = "hx.credential"  # private ASGI scope state, never a response field
AGENT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
PUBLIC_PREFIX = "/.well-known/hypothex/"
PUBLIC_ROUTES = frozenset({("POST", "/api/v1/auth/pair")})
GUARDED_PREFIXES = ("/api/", "/mcp")
UNAUTHORIZED = {"WWW-Authenticate": 'Bearer realm="hypothex"'}
SIGN_IN = "401 · pair this device: hx pair"


def auth_on(conn: HTTPConnection) -> bool:
    """
    Tell whether the app serving a request has auth on.

    Parameters
    ----------
    conn : HTTPConnection
        A request or WebSocket.

    Returns
    -------
    bool
    """
    return bool(getattr(conn.app.state, "auth_on", False))


def principal_of(conn: HTTPConnection) -> Principal:
    """
    Return who is calling.

    Parameters
    ----------
    conn : HTTPConnection
        A request or WebSocket.

    Returns
    -------
    Principal
        The principal ``AuthGuard`` or ``TokenGuard`` resolved; ``LOCAL_OWNER``
        when auth is off and no guard named one.

    Raises
    ------
    AuthError
        Auth is on and the request has no principal (a public route).
    """
    principal = conn.scope.get(PRINCIPAL_KEY)
    if isinstance(principal, Principal):
        return principal
    if auth_on(conn):
        raise AuthError(SIGN_IN)
    return LOCAL_OWNER


class _ScopeCheck:
    """The dependency behind ``requires``; ``route_scopes`` reads ``scope`` back."""

    def __init__(self, scope: ScopeOrPublic) -> None:
        self.scope: ScopeOrPublic = scope

    def __call__(self, conn: HTTPConnection) -> Principal | None:
        if self.scope == "public":
            return None
        principal = principal_of(conn)
        if not covers(principal.scope, self.scope):
            raise ScopeError(f"{self.scope} scope needed; you hold {principal.scope}")
        return principal


def requires(scope: ScopeOrPublic) -> Any:
    """
    Declare the scope a route or WebSocket needs.

    Parameters
    ----------
    scope : {"read", "launch", "admin", "public"}

    Returns
    -------
    Any
        A FastAPI ``Depends``; put it in the route's ``dependencies``.
        ``annotate_scopes`` copies it into ``openapi_extra[SCOPE_KEY]``.
    """
    return Depends(_ScopeCheck(scope))


PUBLIC = [requires("public")]
READ = [requires("read")]
LAUNCH = [requires("launch")]
ADMIN = [requires("admin")]


def _declared(dependant: Any) -> ScopeOrPublic | None:
    for dep in getattr(dependant, "dependencies", []):
        if isinstance(dep.call, _ScopeCheck):
            return dep.call.scope
        found = _declared(dep)
        if found is not None:
            return found
    return None


def route_scopes(app: FastAPI) -> dict[str, ScopeOrPublic]:
    """
    List the declared scope of every route and WebSocket.

    Parameters
    ----------
    app : FastAPI

    Returns
    -------
    dict of str to str
        ``"METHOD path"`` (``"WS path"`` for WebSockets; paths without
        converters, as in OpenAPI: ``{path}``, not ``{path:path}``) to its scope;
        routes without a declaration are absent.
    """
    out: dict[str, ScopeOrPublic] = {}
    for route in app.routes:
        if isinstance(route, APIRoute):
            scope = _declared(route.dependant)
            if scope is not None:
                for method in sorted(route.methods):
                    out[f"{method} {route.path_format}"] = scope
        elif isinstance(route, APIWebSocketRoute):
            scope = _declared(route.dependant)
            if scope is not None:
                out[f"WS {route.path_format}"] = scope
    return out


def annotate_scopes(app: FastAPI) -> None:
    """
    Show each route's scope in the OpenAPI document (``x-hx-scope``).

    Parameters
    ----------
    app : FastAPI
        Call after every route is registered.
    """
    for route in app.routes:
        if isinstance(route, APIRoute):
            scope = _declared(route.dependant)
            if scope is not None:
                route.openapi_extra = {**(route.openapi_extra or {}), SCOPE_KEY: scope}


def identity(conn: HTTPConnection, *, created_by: str, owner: str | None) -> tuple[str, str | None]:
    """
    Decide ``created_by`` and ``owner`` for something a request creates.

    Parameters
    ----------
    conn : HTTPConnection
    created_by : str
        The body's value.
    owner : str or None
        The body's value.

    Returns
    -------
    tuple of (str, str or None)
        The body's values from a hub forwarding (``client == "host"`` with
        ``admin`` scope: ``HOST_PRINCIPAL`` or a host session redeemed from an
        admin offer); with auth off ``(created_by, None)``; else the principal's
        identity and user.
    """
    principal = principal_of(conn)
    if principal.client == "host" and principal.scope == "admin":
        return created_by, owner
    if not auth_on(conn):
        return created_by, None
    return principal.identity(), principal.user


def command_key(conn: HTTPConnection, command_id: str | None) -> str | None:
    """
    Bind a client's command id to the caller and the route it was sent to.

    ``EventLog.run_once`` hands a stored result to anyone who repeats a
    command id, without running the route's scope or ownership checks again.
    A raw id would let a reader send an admin's id to a read route and get the
    admin's result back. Every route therefore stores its receipt under this
    key: the caller's user and scope, the method, and the path (operation and
    target). Only the same caller retrying the same call finds it. The body is
    left out on purpose: a retry with an edited body still gets the first
    result (phase 1 rule, ``test_put_view_is_idempotent_by_command_id``).

    Parameters
    ----------
    conn : HTTPConnection
        The request.
    command_id : str or None
        The body's ``command_id``.

    Returns
    -------
    str or None
        ``<user>|<scope>|<METHOD> <path>|<command_id>``; None when
        ``command_id`` is None (no idempotency).

    Examples
    --------
    >>> command_key(request, "c1")  # doctest: +SKIP
    'alice|launch|POST /api/v1/runs/r1/tags|c1'
    """
    if command_id is None:
        return None
    principal = principal_of(conn)
    method = str(conn.scope.get("method", ""))
    path = str(conn.scope.get("path", ""))
    return f"{principal.user}|{principal.scope}|{method} {path}|{command_id}"


def _cookie(header: str | None, name: str) -> str | None:
    if not header:
        return None
    jar = SimpleCookie()
    try:
        jar.load(header)
    except CookieError:
        return None
    morsel = jar.get(name)
    return morsel.value if morsel is not None else None


def _public(scope: AsgiScope) -> bool:
    path: str = scope.get("path", "")
    if path.startswith(PUBLIC_PREFIX):
        return True
    if (scope.get("method"), path) in PUBLIC_ROUTES:
        return True
    return not path.startswith(GUARDED_PREFIXES)


class AuthGuard:
    """
    ASGI middleware: resolve the caller, and refuse guarded paths without one.

    Parameters
    ----------
    app : ASGIApp
        The wrapped application.
    store : AuthStore
        Sessions and tickets.
    host_token : str, optional
        ``HYPOTHEX_SERVE_TOKEN`` of an env server: the hub's ``Bearer`` token,
        accepted as ``HOST_PRINCIPAL``.
    """

    def __init__(self, app: ASGIApp, store: AuthStore, *, host_token: str | None = None) -> None:
        self.app = app
        self.store = store
        self._host = f"Bearer {host_token}".encode() if host_token else None

    def _resolve(self, scope: AsgiScope) -> Principal | None:
        scope.pop(CREDENTIAL_KEY, None)
        headers = Headers(scope=scope)
        given = headers.get("authorization", "")
        credential: str | None = None
        principal: Principal | None = None
        if given:
            if self._host is not None and hmac.compare_digest(given.encode(), self._host):
                principal = HOST_PRINCIPAL
                credential = given.removeprefix("Bearer ")
            elif given.startswith("Bearer "):
                token = given.removeprefix("Bearer ").strip()
                principal = self.store.authenticate(token)
                if principal is not None:
                    credential = token
        if principal is None:
            token = _cookie(headers.get("cookie"), SESSION_COOKIE)
            if token:
                principal = self.store.authenticate(token)
                if principal is not None:
                    credential = token
        if principal is not None and credential is not None:
            scope[CREDENTIAL_KEY] = credential
        if principal is None and scope["type"] == "websocket":
            query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
            ticket = query.get("ticket", [""])[0]
            if ticket:
                principal = self.store.redeem_ticket(ticket)
        agent = headers.get(AGENT_HEADER) or ""
        if principal is not None and principal.client != "host" and AGENT_NAME.match(agent):
            principal = principal.model_copy(update={"agent": agent})
        return principal

    async def __call__(self, scope: AsgiScope, receive: Receive, send: Send) -> None:
        """
        Resolve the principal; answer 401 (or close 4401) on a guarded path without one.

        Parameters
        ----------
        scope : Scope
        receive : Receive
        send : Send
        """
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        if not str(scope.get("path", "")).startswith(GUARDED_PREFIXES):
            # static UI files, /pair, /.well-known: public and never read a principal,
            # so skip the auth.db lookup (a thread hop and a SQLite read per asset)
            await self.app(scope, receive, send)
            return
        principal = await asyncio.to_thread(self._resolve, scope)
        if principal is not None:
            scope[PRINCIPAL_KEY] = principal
        elif not _public(scope):
            if scope["type"] == "websocket":
                await receive()  # websocket.connect
                await send({"type": "websocket.close", "code": 4401})
                return
            body = {"error": SIGN_IN, "type": "AuthError"}
            await JSONResponse(body, status_code=401, headers=UNAUTHORIZED)(scope, receive, send)
            return
        await self.app(scope, receive, send)
```

- [ ] **Step 4: Mark `TokenGuard` requests and wire the guard into `create_app`**

In `src/hypothex/api/security.py`, add to the imports:

```python
from hypothex.auth.store import HOST_PRINCIPAL
```

and in `TokenGuard.__call__`, replace

```python
        if bearer_matches(Headers(scope=scope).get("authorization"), self._token):
            await self.app(scope, receive, send)
            return
```

with

```python
        if bearer_matches(Headers(scope=scope).get("authorization"), self._token):
            scope["hx.principal"] = HOST_PRINCIPAL  # api.auth.PRINCIPAL_KEY: a hub forwarding
            scope["hx.credential"] = self._token  # the exact token authenticated above
            await self.app(scope, receive, send)
            return
```

Keep the current `bearer_matches` helper, minimal unauthenticated descriptor, `same_origin` check and JSON-or-client-header POST requirement. Add principal/credential state only after successful authentication; do not restore the old loopback-host-only origin rule. Run the existing `tests/api/test_security.py` with these auth tests.

In `src/hypothex/api/app.py`:

1. Add to the imports:

```python
from urllib.parse import urlsplit

from hypothex.api.auth import UNAUTHORIZED, AuthGuard, annotate_scopes
from hypothex.auth.store import AuthError, AuthStore, ScopeError
from hypothex.core.settings import load_settings
```

2. In the signature of `create_app`, after `hub_url: str | None = None,` add:

```python
    auth: bool | None = None,
    public_url: str | None = None,
```

and document both in the docstring's Parameters:

```
    auth : bool, optional
        Require a session (``AuthGuard``) on every route except the public ones.
        Default: ``server.auth`` in ``<home>/config.yaml``.
    public_url : str, optional
        The URL people reach this hub at (pairing links, ``Host``/``Origin``
        allow-list, ``Secure`` cookies). Default: ``server.public_url``.
```

3. Right after

```python
    ctx = Context.open(home)
    if kind is not None:
        ctx.descriptor.kind = kind
```

add:

```python
    settings = load_settings(ctx.layout)
    auth_enabled = settings.server.auth == "on" if auth is None else auth
    public = public_url or settings.server.public_url
    store = AuthStore(ctx.layout, session_days=settings.server.session_days)
```

4. Replace

```python
    app.state.ctx = ctx
    app.state.hub = manager
    app.state.mcp = mcp_server
    hosts = allowed_hosts(host)
    app.add_middleware(OriginGuard, hosts=hosts)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)
    if auth_token:
        app.add_middleware(TokenGuard, token=auth_token)  # outermost: checked first
```

with

```python
    app.state.ctx = ctx
    app.state.hub = manager
    app.state.mcp = mcp_server
    app.state.auth = store
    app.state.auth_on = auth_enabled
    app.state.public_url = public
    hosts = allowed_hosts(host)
    public_host = urlsplit(public).hostname if public else None
    if public_host and public_host not in hosts:
        hosts.append(public_host)
    app.add_middleware(OriginGuard, hosts=hosts)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)
    if auth_enabled:
        app.add_middleware(AuthGuard, store=store, host_token=auth_token)  # outermost
    elif auth_token:
        app.add_middleware(TokenGuard, token=auth_token)  # outermost: checked first
```

5. Replace the body of `hypothex_error` with:

```python
    @app.exception_handler(HypothexError)
    async def hypothex_error(_: Request, exc: HypothexError) -> JSONResponse:
        headers: dict[str, str] = {}
        if isinstance(exc, StoreError):
            status = 404
        elif isinstance(exc, HostUnavailableError):
            status = 503
        elif isinstance(exc, AuthError):
            status, headers = 401, UNAUTHORIZED
        elif isinstance(exc, ScopeError):
            status = 403
        else:
            status = 400
        if isinstance(exc, CommandInterruptedError):
            status = 409  # the command's outcome is unknown: never replayed
        content: dict[str, Any] = {"error": str(exc), "type": type(exc).__name__}
        if isinstance(exc, ViewValidationError):
            content["issues"] = to_jsonable(exc.issues)
        return JSONResponse(status_code=status, content=content, headers=headers)
```

6. Replace

```python
    register_env_routes(app, ctx)
    app.mount("/mcp", mcp_http)
```

with

```python
    register_env_routes(app, ctx)
    annotate_scopes(app)
    app.mount("/mcp", mcp_http)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_auth_guard.py tests/api/test_security.py tests/api/test_app.py -v`
Expected: `tests/api/test_auth_guard.py` `9 passed`; the phase 1–2 API tests still pass.

Run: `uv run python -m doctest src/hypothex/api/auth.py && uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check src`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/hypothex/api/auth.py src/hypothex/api/security.py src/hypothex/api/app.py tests/api/authkit.py tests/api/test_auth_guard.py
git commit -m "feat(api): auth guard with cookie, bearer, and ticket principals"
```

---

### Task 24: A scope on every existing route, and the test that enforces it

**Files:**
- Modify: `src/hypothex/api/app.py` (every route decorator in `create_app` and `register_env_routes`)
- Test: `tests/api/test_route_scopes.py`

**Interfaces:**
- Consumes: `PUBLIC`, `READ`, `LAUNCH`, `ADMIN`, `route_scopes` (Task 23).
- Produces: the scope of every phase 1–2 route (contract 3): `GET` → `read`; the descriptor → `public`; launch, rerun, reinfer, reeval, stop, tags, star, archive, notes, views PUT/DELETE, sweeps POST/cancel/extend, pull, hosts reload/connect/disconnect, `POST /api/v1/hosts/{host}/runs`, task reeval → `launch`; views validate/query (POST but read-only) → `read`; env routes (`files`, `entry`, `gpus`, `queue`, `slurm`) → `read`; `/api/v1/ws` → `read`.

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_route_scopes.py`:

```python
from pathlib import Path

from fastapi import FastAPI
from fastapi.routing import APIRoute, APIWebSocketRoute
from fastapi.testclient import TestClient

from hypothex.api.app import create_app
from hypothex.api.auth import route_scopes

PHASE_1_2 = {
    "GET /.well-known/hypothex/environment": "public",
    "GET /api/v1/hosts": "read",
    "POST /api/v1/hosts/reload": "launch",
    "POST /api/v1/hosts/{host}/connect": "launch",
    "POST /api/v1/hosts/{host}/disconnect": "launch",
    "POST /api/v1/hosts/{host}/runs": "launch",
    "GET /api/v1/overview": "read",
    "GET /api/v1/projects": "read",
    "GET /api/v1/tasks": "read",
    "GET /api/v1/tasks/{project}/{task}": "read",
    "GET /api/v1/tasks/{project}/{task}/leaderboard": "read",
    "POST /api/v1/tasks/{project}/{task}/reeval": "launch",
    "GET /api/v1/tasks/{project}/{task}/kind": "read",
    "GET /api/v1/tasks/{project}/{task}/views": "read",
    "POST /api/v1/tasks/{project}/{task}/views/validate": "read",
    "POST /api/v1/tasks/{project}/{task}/views/query": "read",
    "GET /api/v1/tasks/{project}/{task}/views/{name}": "read",
    "PUT /api/v1/tasks/{project}/{task}/views/{name}": "launch",
    "DELETE /api/v1/tasks/{project}/{task}/views/{name}": "launch",
    "GET /api/v1/runs": "read",
    "POST /api/v1/runs": "launch",
    "GET /api/v1/runs/{run_id}": "read",
    "GET /api/v1/runs/{run_id}/metrics": "read",
    "GET /api/v1/runs/{run_id}/traces": "read",
    "GET /api/v1/runs/{run_id}/traces/{example_id}": "read",
    "GET /api/v1/runs/{run_id}/logs": "read",
    "GET /api/v1/runs/{run_id}/predictions": "read",
    "POST /api/v1/runs/{run_id}/rerun": "launch",
    "POST /api/v1/runs/{run_id}/reinfer": "launch",
    "POST /api/v1/runs/{run_id}/reeval": "launch",
    "POST /api/v1/runs/{run_id}/stop": "launch",
    "POST /api/v1/runs/{run_id}/tags": "launch",
    "POST /api/v1/runs/{run_id}/star": "launch",
    "POST /api/v1/runs/{run_id}/archive": "launch",
    "POST /api/v1/runs/{run_id}/notes": "launch",
    "POST /api/v1/sweeps": "launch",
    "GET /api/v1/sweeps/{sweep_id}": "read",
    "GET /api/v1/sweeps/{project}/{sweep_id}": "read",
    "GET /api/v1/projects/{project}/sweeps": "read",
    "POST /api/v1/sweeps/{project}/{sweep_id}/cancel_queued": "launch",
    "POST /api/v1/sweeps/{project}/{sweep_id}/extend": "launch",
    "POST /api/v1/runs/{run_id}/pull": "launch",
    "GET /api/v1/compare": "read",
    "GET /api/v1/compare/examples": "read",
    "GET /api/v1/datasets/check": "read",
    "WS /api/v1/ws": "read",
    "GET /api/v1/runs/{run_id}/files/{path}": "read",
    "GET /api/v1/projects/{project}/entry": "read",
    "GET /api/v1/gpus": "read",
    "GET /api/v1/queue": "read",
    "GET /api/v1/slurm": "read",
}


def undeclared(app: FastAPI) -> list[str]:
    """Every route or WebSocket that declares no scope."""
    declared = route_scopes(app)
    missing: list[str] = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            keys = [f"{m} {route.path_format}" for m in sorted(route.methods)]
            missing += [k for k in keys if k not in declared]
        elif isinstance(route, APIWebSocketRoute) and f"WS {route.path_format}" not in declared:
            missing.append(f"WS {route.path_format}")
    return missing


def app_for(home: Path) -> FastAPI:
    return create_app(home, background_repair=False, hub=False, ui_dir=home / "no-ui")


def test_every_route_and_the_websocket_declare_a_scope(home: Path) -> None:
    assert undeclared(app_for(home)) == []


def test_phase_1_2_routes_have_the_contract_scopes(home: Path) -> None:
    declared = route_scopes(app_for(home))
    assert {k: declared.get(k) for k in PHASE_1_2} == PHASE_1_2


def test_a_route_without_a_scope_is_caught() -> None:
    app = FastAPI()

    @app.get("/api/v1/forgotten")
    def forgotten() -> dict[str, str]:
        return {}

    assert undeclared(app) == ["GET /api/v1/forgotten"]


def test_openapi_shows_each_scope(home: Path) -> None:
    with TestClient(app_for(home), base_url="http://127.0.0.1:7777") as client:
        paths = client.get("/api/openapi.json").json()["paths"]
    assert paths["/api/v1/runs"]["get"]["x-hx-scope"] == "read"
    assert paths["/api/v1/runs/{run_id}/stop"]["post"]["x-hx-scope"] == "launch"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_route_scopes.py -v`
Expected: FAIL: `test_every_route_and_the_websocket_declare_a_scope` lists all 51 routes, `test_phase_1_2_routes_have_the_contract_scopes` shows every value `None`, `test_openapi_shows_each_scope` with `KeyError: 'x-hx-scope'`.

- [ ] **Step 3: Declare the scopes**

In `src/hypothex/api/app.py`, add `ADMIN, LAUNCH, PUBLIC, READ` to the `hypothex.api.auth` import (`ADMIN` is used from Task 25 on). Then give every decorator a `dependencies=` argument. Each line below is the exact new decorator; only `, dependencies=...` is added to the existing line.

In `register_env_routes`:

```python
    @app.get("/api/v1/runs/{run_id}/files/{path:path}", dependencies=READ)
    @app.get("/api/v1/projects/{project}/entry", dependencies=READ)
    @app.get("/api/v1/gpus", dependencies=READ)
    @app.get("/api/v1/queue", dependencies=READ)
    @app.get("/api/v1/slurm", dependencies=READ)
```

In `create_app`, in file order:

```python
    @app.get("/.well-known/hypothex/environment", dependencies=PUBLIC)
    @app.get("/api/v1/hosts", dependencies=READ)
    @app.post("/api/v1/hosts/reload", dependencies=LAUNCH)
    @app.post("/api/v1/hosts/{host}/connect", dependencies=LAUNCH)
    @app.post("/api/v1/hosts/{host}/disconnect", dependencies=LAUNCH)
    @app.post("/api/v1/hosts/{host}/runs", dependencies=LAUNCH)
    @app.get("/api/v1/overview", dependencies=READ)
    @app.get("/api/v1/projects", dependencies=READ)
    @app.get("/api/v1/tasks", dependencies=READ)
    @app.get("/api/v1/tasks/{project}/{task}", dependencies=READ)
    @app.get("/api/v1/tasks/{project}/{task}/leaderboard", dependencies=READ)
    @app.post("/api/v1/tasks/{project}/{task}/reeval", dependencies=LAUNCH)
    @app.get("/api/v1/tasks/{project}/{task}/kind", dependencies=READ)
    @app.get("/api/v1/tasks/{project}/{task}/views", dependencies=READ)
    @app.post("/api/v1/tasks/{project}/{task}/views/validate", dependencies=READ)
    @app.post("/api/v1/tasks/{project}/{task}/views/query", dependencies=READ)
    @app.get("/api/v1/tasks/{project}/{task}/views/{name}", dependencies=READ)
    @app.put("/api/v1/tasks/{project}/{task}/views/{name}", dependencies=LAUNCH)
    @app.delete("/api/v1/tasks/{project}/{task}/views/{name}", dependencies=LAUNCH)
    @app.get("/api/v1/runs", dependencies=READ)
    @app.post("/api/v1/runs", dependencies=LAUNCH)
    @app.get("/api/v1/runs/{run_id}", dependencies=READ)
    @app.get("/api/v1/runs/{run_id}/metrics", dependencies=READ)
    @app.get("/api/v1/runs/{run_id}/traces", dependencies=READ)
    @app.get("/api/v1/runs/{run_id}/traces/{example_id:path}", dependencies=READ)
    @app.get("/api/v1/runs/{run_id}/logs", dependencies=READ)
    @app.get("/api/v1/runs/{run_id}/predictions", dependencies=READ)
    @app.post("/api/v1/runs/{run_id}/rerun", dependencies=LAUNCH)
    @app.post("/api/v1/runs/{run_id}/reinfer", dependencies=LAUNCH)
    @app.post("/api/v1/runs/{run_id}/reeval", dependencies=LAUNCH)
    @app.post("/api/v1/runs/{run_id}/stop", dependencies=LAUNCH)
    @app.post("/api/v1/runs/{run_id}/tags", dependencies=LAUNCH)
    @app.post("/api/v1/runs/{run_id}/star", dependencies=LAUNCH)
    @app.post("/api/v1/runs/{run_id}/archive", dependencies=LAUNCH)
    @app.post("/api/v1/runs/{run_id}/notes", dependencies=LAUNCH)
    @app.post("/api/v1/sweeps", dependencies=LAUNCH)
    @app.get("/api/v1/sweeps/{sweep_id}", dependencies=READ)
    @app.get("/api/v1/sweeps/{project}/{sweep_id}", dependencies=READ)
    @app.get("/api/v1/projects/{project}/sweeps", dependencies=READ)
    @app.post("/api/v1/sweeps/{project}/{sweep_id}/cancel_queued", dependencies=LAUNCH)
    @app.post("/api/v1/sweeps/{project}/{sweep_id}/extend", dependencies=LAUNCH)
    @app.post("/api/v1/runs/{run_id}/pull", dependencies=LAUNCH)
    @app.get("/api/v1/compare", dependencies=READ)
    @app.get("/api/v1/compare/examples", dependencies=READ)
    @app.get("/api/v1/datasets/check", dependencies=READ)
    @app.websocket("/api/v1/ws", dependencies=READ)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api -v`
Expected: `tests/api/test_route_scopes.py` `4 passed`; every other API test still passes (auth is off in them, so every route runs as `LOCAL_OWNER`, which holds `admin`).

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check src`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/api/app.py tests/api/test_route_scopes.py
git commit -m "feat(api): declare a scope on every route and the websocket"
```

---
### Task 25: Auth routes — pair, me, logout, tickets, pairings, sessions, users

**Files:**
- Create: `src/hypothex/api/routes_auth.py`
- Modify: `src/hypothex/api/app.py` (register the routes)
- Test: `tests/api/test_auth_routes.py`

**Interfaces:**
- Consumes: `AuthStore` (Tasks 6–7), `pairing_url`, `qr_text`, `principal_of`, `PUBLIC`/`READ`/`ADMIN`.
- Produces (contract 3, exact): `POST /api/v1/auth/pair` (public), `GET /api/v1/auth/me` (read), `POST /api/v1/auth/logout` (read), `POST /api/v1/auth/ws-ticket` (read), `POST /api/v1/auth/pairings` (read + scope rule), `GET /api/v1/auth/sessions` (read; `?user=` needs admin for others), `POST /api/v1/auth/sessions/{session_id}/revoke` (read; own, or admin), `GET /api/v1/auth/users` (admin), `POST /api/v1/auth/users/{name}/disable` (admin).
- Produces (public helpers): `register_auth_routes(app, ctx, store)`; `PairLimiter(now)` with `blocked(address) -> bool` and `fail(address) -> None` (10 failed attempts per 60 s per client address; a successful pairing is not counted); `PAIR_ATTEMPTS_PER_MINUTE = 10`; `pair_client_key(peer, headers, *, behind_proxy) -> str` (the address the limit counts: behind a loopback proxy such as `tailscale serve`, i.e. `public_url` set and the peer loopback, the `Tailscale-User-Login` header, else the last `X-Forwarded-For` hop the proxy appended, else the peer; so one person's bad attempts never lock pairing for the whole lab, and a header sent from a non-loopback peer is ignored).
- Rules: a browser pair sets `hx_session` (`HttpOnly; SameSite=Strict; Path=/`, `Secure` when `public_url` is https, lifetime `session_days`) and returns `{user, scope, scopes, session_id}`; other clients get `{token, ...}` too. Pairing and `pairings` answer 400 when auth is off. `pairings` defaults `user` to the caller; `new_user` must match whether the user exists; the link uses `public_url`, else the request's base URL; its result is never stored in a command receipt (it holds the secret). Session changes emit `auth.session_created` / `auth.session_revoked` `{session_id, user, client}`.

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_auth_routes.py`:

```python
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hypothex.api.app import create_app
from hypothex.api.routes_auth import PAIR_ATTEMPTS_PER_MINUTE, pair_client_key
from hypothex.auth.pairing import parse_pairing_url
from hypothex.auth.store import PAIRING_INVALID, AuthStore
from tests.api.authkit import BASE, auth_app, bearer, token_for


@pytest.fixture
def app(home: Path) -> FastAPI:
    return auth_app(home)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, base_url=BASE) as test_client:
        yield test_client


def owner_token(app: FastAPI) -> str:
    return token_for(app.state.auth, "sv", "admin")


def pair_link(client: TestClient, token: str, **body: object) -> str:
    resp = client.post("/api/v1/auth/pairings", json=body, headers=bearer(token))
    assert resp.status_code == 200, resp.text
    return resp.json()["url"]


def test_owner_pairs_a_new_collaborator(app: FastAPI, client: TestClient) -> None:
    resp = client.post(
        "/api/v1/auth/pairings",
        json={"user": "alice", "new_user": True, "scope": "launch"},
        headers=bearer(owner_token(app)),
    )
    offer = resp.json()
    assert offer["url"].startswith(f"{BASE}/pair#p_") and "█" in offer["qr"]
    _, offer_id, secret = parse_pairing_url(offer["url"])
    paired = client.post(
        "/api/v1/auth/pair",
        json={"offer_id": offer_id, "secret": secret, "device": "MacBook", "client": "cli"},
    ).json()
    assert paired["user"] == "alice" and paired["scopes"] == ["read", "launch"]
    me = client.get("/api/v1/auth/me", headers=bearer(paired["token"])).json()
    assert (me["user"], me["scope"], me["client"], me["auth"]) == ("alice", "launch", "cli", "on")


@pytest.mark.parametrize(("public", "secure"), [(None, False), ("https://hub.ts.net", True)])
def test_browser_pairing_sets_a_strict_cookie(home: Path, public: str | None, secure: bool) -> None:
    app = auth_app(home, public_url=public)
    with TestClient(app, base_url=BASE) as client:
        link = pair_link(client, owner_token(app), user="sv", scope="read")
        _, offer_id, secret = parse_pairing_url(link)
        resp = client.post(
            "/api/v1/auth/pair", json={"offer_id": offer_id, "secret": secret, "device": "phone"}
        )
    cookie = resp.headers["set-cookie"].lower()
    assert "hx_session=hxs_" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    assert "path=/" in cookie and ("secure" in cookie) is secure
    assert "token" not in resp.json()
    if public:
        assert link.startswith("https://hub.ts.net/pair#")


def test_pairing_never_widens_scope_over_http(app: FastAPI, client: TestClient) -> None:
    alice = token_for(app.state.auth, "alice", "launch")
    resp = client.post("/api/v1/auth/pairings", json={"scope": "admin"}, headers=bearer(alice))
    assert resp.status_code == 403
    resp = client.post(
        "/api/v1/auth/pairings", json={"user": "bob", "new_user": True}, headers=bearer(alice)
    )
    assert resp.status_code == 403
    assert (
        client.post(
            "/api/v1/auth/pairings", json={"user": "zed"}, headers=bearer(alice)
        ).status_code
        == 400
    )


def test_bad_links_get_one_message_and_reuse_fails(app: FastAPI, client: TestClient) -> None:
    link = pair_link(client, owner_token(app), user="sv", scope="read")
    _, offer_id, secret = parse_pairing_url(link)
    body = {"offer_id": offer_id, "secret": secret, "client": "cli"}
    assert client.post("/api/v1/auth/pair", json=body).status_code == 200
    again = client.post("/api/v1/auth/pair", json=body)
    wrong = client.post("/api/v1/auth/pair", json={**body, "secret": "x" * 43})
    for resp in (again, wrong):
        assert resp.status_code == 400 and resp.json() == {
            "error": PAIRING_INVALID,
            "type": "PairingError",
        }


def test_pairing_attempts_are_rate_limited(client: TestClient) -> None:
    body = {"offer_id": "p_000000000000", "secret": "y" * 43}
    codes = [client.post("/api/v1/auth/pair", json=body).status_code for _ in range(11)]
    assert codes == [400] * 10 + [429]


def test_successful_pairings_do_not_count(app: FastAPI, client: TestClient) -> None:
    token = owner_token(app)
    for i in range(PAIR_ATTEMPTS_PER_MINUTE + 2):  # a lab pairing a dozen devices in a minute
        _, offer_id, secret = parse_pairing_url(pair_link(client, token, scope="read"))
        body = {"offer_id": offer_id, "secret": secret, "device": f"d{i}", "client": "cli"}
        assert client.post("/api/v1/auth/pair", json=body).status_code == 200


def test_the_pairing_limit_counts_people_behind_a_proxy() -> None:
    ts = {"tailscale-user-login": "alice@lab.org", "x-forwarded-for": "100.64.0.7"}
    assert pair_client_key("127.0.0.1", ts, behind_proxy=True) == "ts:alice@lab.org"
    xff = {"x-forwarded-for": "203.0.113.9, 100.64.0.7"}
    assert pair_client_key("127.0.0.1", xff, behind_proxy=True) == "100.64.0.7"
    assert pair_client_key("127.0.0.1", {}, behind_proxy=True) == "127.0.0.1"
    assert pair_client_key("10.0.0.5", ts, behind_proxy=True) == "10.0.0.5"  # not from the proxy
    assert pair_client_key("127.0.0.1", ts, behind_proxy=False) == "127.0.0.1"


def test_logout_revokes_and_clears_the_cookie(app: FastAPI, client: TestClient) -> None:
    token = token_for(app.state.auth, "alice", "read")
    before = app.state.ctx.events.last_sequence()
    resp = client.post("/api/v1/auth/logout", headers=bearer(token), json={})
    assert resp.json() == {"ok": True} and 'hx_session=""' in resp.headers["set-cookie"]
    assert client.get("/api/v1/auth/me", headers=bearer(token)).status_code == 401
    (event,) = [e for e in app.state.ctx.events.since(before) if e.type == "auth.session_revoked"]
    assert event.payload["user"] == "alice" and "token" not in event.payload


def test_sessions_are_own_unless_admin(app: FastAPI, client: TestClient) -> None:
    store: AuthStore = app.state.auth
    admin, alice = owner_token(app), token_for(store, "alice", "launch")
    token_for(store, "bob", "read")
    mine = client.get("/api/v1/auth/sessions", headers=bearer(alice)).json()
    assert {s["user"] for s in mine} == {"alice"} and all("secret" not in s for s in mine)
    assert client.get("/api/v1/auth/sessions?user=bob", headers=bearer(alice)).status_code == 403
    every = client.get("/api/v1/auth/sessions", headers=bearer(admin)).json()
    assert {s["user"] for s in every} == {"sv", "alice", "bob"}
    bob_session = next(s["id"] for s in every if s["user"] == "bob")
    url = f"/api/v1/auth/sessions/{bob_session}/revoke"
    assert client.post(url, json={}, headers=bearer(alice)).status_code == 403
    assert client.post(url, json={}, headers=bearer(admin)).json()["revoked_at"] is not None


def test_users_are_admin_only_and_disable_locks_out(app: FastAPI, client: TestClient) -> None:
    admin, alice = owner_token(app), token_for(app.state.auth, "alice", "launch")
    assert client.get("/api/v1/auth/users", headers=bearer(alice)).status_code == 403
    users = client.get("/api/v1/auth/users", headers=bearer(admin)).json()
    assert {u["name"]: u["role"] for u in users} == {"sv": "admin", "alice": "launch"}
    resp = client.post("/api/v1/auth/users/alice/disable", json={}, headers=bearer(admin))
    assert resp.json()["disabled_at"] is not None
    assert client.get("/api/v1/auth/me", headers=bearer(alice)).status_code == 401


def test_ws_ticket(app: FastAPI, client: TestClient) -> None:
    resp = client.post("/api/v1/auth/ws-ticket", headers=bearer(owner_token(app)), json={})
    assert resp.json()["expires_in"] == 30 and len(resp.json()["ticket"]) > 20


def test_auth_off_answers_as_local_owner(home: Path) -> None:
    app = create_app(home, background_repair=False, hub=False, ui_dir=home / "no-ui")
    with TestClient(app, base_url=BASE) as client:
        me = client.get("/api/v1/auth/me").json()
        assert (me["user"], me["scope"], me["auth"], me["session_id"]) == (
            "local",
            "admin",
            "off",
            None,
        )
        assert client.post("/api/v1/auth/pairings", json={}).status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_auth_routes.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'hypothex.api.routes_auth'` (the module and its routes come in Step 3).

- [ ] **Step 3: Write the routes**

Create `src/hypothex/api/routes_auth.py`:

```python
"""``/api/v1/auth/*``: pairing, the caller, logout, WebSocket tickets, sessions, users."""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

from hypothex.api.auth import ADMIN, PUBLIC, READ, SESSION_COOKIE, command_key, principal_of
from hypothex.auth.pairing import pairing_url, qr_text
from hypothex.auth.scopes import Scope, scopes_of
from hypothex.auth.store import (
    TICKET_TTL_SECONDS,
    AuthStore,
    PairingError,
    ScopeError,
    Session,
)
from hypothex.core.context import Context
from hypothex.core.errors import ConfigError
from hypothex.core.jsonutil import to_jsonable
from hypothex.core.settings import is_loopback_host

PAIR_ATTEMPTS_PER_MINUTE = 10


class PairBody(BaseModel):
    """Body of ``POST /api/v1/auth/pair`` (the link's fragment, sent by the client)."""

    offer_id: str = Field(max_length=32)
    secret: str = Field(max_length=128)
    device: str = Field("device", min_length=1, max_length=64)
    client: Literal["browser", "cli", "agent", "host"] = "browser"


class PairingBody(BaseModel):
    """Body of ``POST /api/v1/auth/pairings``."""

    user: str | None = None
    new_user: bool = False
    scope: Scope = "read"
    ttl_seconds: int = Field(300, ge=1, le=300)
    client_hint: str | None = Field(None, max_length=16)
    command_id: str | None = None


class CommandBody(BaseModel):
    """An optional body with a ``command_id``."""

    command_id: str | None = None


def pair_client_key(peer: str, headers: Mapping[str, str], *, behind_proxy: bool) -> str:
    """
    Choose the address the pairing rate limit counts.

    Behind ``tailscale serve`` (``public_url`` set) every request reaches the hub
    from ``127.0.0.1``; counting the peer would let one person's typos lock
    pairing for the whole lab. Headers count only when the peer is loopback (the
    proxy), so a remote caller cannot pick its own key.

    Parameters
    ----------
    peer : str
        The TCP peer address.
    headers : mapping of str to str
        Request headers (lower-case keys, as Starlette gives them).
    behind_proxy : bool
        The hub has a ``public_url``.

    Returns
    -------
    str
        ``ts:<login>`` from ``Tailscale-User-Login``, else the last
        ``X-Forwarded-For`` hop (the one the proxy appended), else ``peer``.

    Examples
    --------
    >>> pair_client_key("127.0.0.1", {"x-forwarded-for": "a, 100.64.0.7"}, behind_proxy=True)
    '100.64.0.7'
    """
    if behind_proxy and is_loopback_host(peer):
        login = headers.get("tailscale-user-login", "").strip()
        if login:
            return f"ts:{login}"
        hops = [h.strip() for h in headers.get("x-forwarded-for", "").split(",") if h.strip()]
        if hops:
            return hops[-1]
    return peer


class PairLimiter:
    """
    At most ``PAIR_ATTEMPTS_PER_MINUTE`` failed pairing attempts per client address and minute.

    Only failures count: a success used up a fresh one-use secret that only the
    offer's issuer could hand out, so it is no guessing. A lab pairing several
    devices in a minute (or a test suite) is never locked out; a guesser is.

    Parameters
    ----------
    now : callable
        The auth store's clock.
    """

    def __init__(self, now: Callable[[], datetime]) -> None:
        self.now = now
        self._fails: dict[str, deque[datetime]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _recent(self, address: str) -> deque[datetime]:
        now = self.now()
        fails = self._fails[address]
        while fails and now - fails[0] >= timedelta(minutes=1):
            fails.popleft()
        return fails

    def blocked(self, address: str) -> bool:
        """
        Tell whether ``address`` has used up its failed attempts for this minute.

        Parameters
        ----------
        address : str

        Returns
        -------
        bool
        """
        with self._lock:
            return len(self._recent(address)) >= PAIR_ATTEMPTS_PER_MINUTE

    def fail(self, address: str) -> None:
        """
        Count one failed attempt of ``address``.

        Parameters
        ----------
        address : str
        """
        with self._lock:
            self._recent(address).append(self.now())


def register_auth_routes(app: FastAPI, ctx: Context, store: AuthStore) -> None:
    """
    Add the ``/api/v1/auth/*`` routes.

    Parameters
    ----------
    app : FastAPI
    ctx : Context
        For ``auth.*`` events and command receipts.
    store : AuthStore
    """
    limiter = PairLimiter(store.now)

    def session_event(kind: str, session: Session) -> None:
        payload = {"session_id": session.id, "user": session.user, "client": session.client}
        ctx.events.append(kind, payload=payload)

    @app.post("/api/v1/auth/pair", dependencies=PUBLIC)
    def pair(body: PairBody, request: Request) -> JSONResponse:
        if not request.app.state.auth_on:
            raise ConfigError("auth is off on this hub; there is nothing to pair")
        peer = request.client.host if request.client else "unknown"
        behind_proxy = request.app.state.public_url is not None
        address = pair_client_key(peer, request.headers, behind_proxy=behind_proxy)
        if limiter.blocked(address):
            return JSONResponse(
                {"error": "too many pairing attempts; wait a minute", "type": "RateLimitError"},
                status_code=429,
            )
        try:
            session, token = store.redeem(
                body.offer_id, body.secret, client=body.client, device=body.device
            )
        except PairingError:
            limiter.fail(address)
            raise
        session_event("auth.session_created", session)
        out = {
            "user": session.user,
            "scope": session.scope,
            "scopes": scopes_of(session.scope),
            "session_id": session.id,
        }
        if body.client != "browser":
            return JSONResponse({"token": token, **out})
        response = JSONResponse(out)
        public = request.app.state.public_url
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=store.session_days * 86400,
            path="/",
            httponly=True,
            samesite="strict",
            secure=bool(public and public.startswith("https://")),
        )
        return response

    @app.get("/api/v1/auth/me", dependencies=READ)
    def me(request: Request) -> dict[str, Any]:
        principal = principal_of(request)
        return {
            "user": principal.user,
            "scope": principal.scope,
            "scopes": scopes_of(principal.scope),
            "session_id": principal.session_id,
            "client": principal.client,
            "auth": "on" if request.app.state.auth_on else "off",
            "public_url": request.app.state.public_url,
        }

    @app.post("/api/v1/auth/logout", dependencies=READ)
    def logout(request: Request) -> JSONResponse:
        principal = principal_of(request)
        if principal.session_id is not None:
            session_event("auth.session_revoked", store.revoke(principal.session_id, by=principal))
        response = JSONResponse({"ok": True})
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    @app.post("/api/v1/auth/ws-ticket", dependencies=READ)
    def ws_ticket(request: Request) -> dict[str, Any]:
        ticket = store.issue_ticket(principal_of(request))
        return {"ticket": ticket, "expires_in": TICKET_TTL_SECONDS}

    @app.post("/api/v1/auth/pairings", dependencies=READ)
    def pairings(body: PairingBody, request: Request) -> dict[str, Any]:
        if not request.app.state.auth_on:
            raise ConfigError("auth is off; set server.auth: on (or hx serve --auth) to pair")
        principal = principal_of(request)
        user = body.user or principal.user
        exists = store.get_user(user) is not None
        if body.new_user and exists:
            raise ConfigError(f"user {user} exists; drop --new-user")
        if not body.new_user and not exists:
            raise ConfigError(f"no user {user}; add --new-user")
        offer, secret = store.create_offer(
            issuer=principal, user=user, scope=body.scope, ttl_seconds=body.ttl_seconds
        )
        base = request.app.state.public_url or str(request.base_url).rstrip("/")
        url = pairing_url(base, offer.id, secret)
        # never stored as a command receipt: the link holds the secret
        return {
            "offer_id": offer.id,
            "url": url,
            "expires_at": offer.expires_at.isoformat(),
            "qr": qr_text(url),
        }

    @app.get("/api/v1/auth/sessions", dependencies=READ)
    def sessions(request: Request, user: str | None = None) -> list[dict[str, Any]]:
        principal = principal_of(request)
        if principal.scope != "admin":
            if user not in (None, principal.user):
                raise ScopeError("listing another user's sessions needs admin")
            user = principal.user
        return to_jsonable(store.sessions(user))

    @app.post("/api/v1/auth/sessions/{session_id}/revoke", dependencies=READ)
    def revoke(
        session_id: str, request: Request, body: CommandBody | None = None
    ) -> dict[str, Any]:
        principal = principal_of(request)

        def act() -> dict[str, Any]:
            session = store.revoke(session_id, by=principal)
            session_event("auth.session_revoked", session)
            return to_jsonable(session)

        key = command_key(request, (body or CommandBody()).command_id)
        return ctx.events.run_once(key, act)

    @app.get("/api/v1/auth/users", dependencies=ADMIN)
    def users() -> list[dict[str, Any]]:
        return to_jsonable(store.users())

    @app.post("/api/v1/auth/users/{name}/disable", dependencies=ADMIN)
    def disable(name: str, request: Request, body: CommandBody | None = None) -> dict[str, Any]:
        principal = principal_of(request)

        def act() -> dict[str, Any]:
            active = store.sessions(name)
            user = store.disable_user(name, by=principal)
            for session in active:
                session_event("auth.session_revoked", session)
            return to_jsonable(user)

        key = command_key(request, (body or CommandBody()).command_id)
        return ctx.events.run_once(key, act)
```

In `src/hypothex/api/app.py`, add `from hypothex.api.routes_auth import register_auth_routes` to the imports and replace

```python
    register_env_routes(app, ctx)
    annotate_scopes(app)
```

with

```python
    register_auth_routes(app, ctx, store)
    register_env_routes(app, ctx)
    annotate_scopes(app)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_auth_routes.py tests/api/test_route_scopes.py -v`
Expected: `tests/api/test_auth_routes.py` `13 passed`; `tests/api/test_route_scopes.py` still `4 passed` (the new routes declare their scopes).

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check src`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/api/routes_auth.py src/hypothex/api/app.py tests/api/test_auth_routes.py
git commit -m "feat(api): pairing, sessions, users, and websocket ticket routes"
```

---

### Task 26: WebSocket tickets, revocation within 30 s, and admin-only event types

**Files:**
- Modify: `src/hypothex/auth/store.py` (`AuthStore.session_active`)
- Modify: `src/hypothex/api/app.py` (`events_ws`, `WS_RECHECK_SECONDS`, `ADMIN_EVENT_PREFIXES`)
- Test: `tests/api/test_ws_auth.py`

**Interfaces:**
- Produces (contract 1.10, 2): the WebSocket accepts a principal from a ticket (`?ticket=`, single use), a cookie, or a bearer header (hubs and the CLI); with auth on it re-checks the session every `WS_RECHECK_SECONDS = 30.0` and closes with code `4401` when it is revoked, expired, or its user disabled; `auth.*` and `notify.*` events go to `admin` principals only (the cursor still moves past them).
- Produces (additive): `AuthStore.session_active(session_id) -> bool` (no sliding).

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_ws_auth.py`:

```python
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from hypothex.api import app as app_module
from hypothex.auth.store import AuthStore
from tests.api.authkit import BASE, WS_URL, auth_app, bearer, token_for


def drain(ws: object) -> list[str]:
    """Event types up to ``ready``."""
    types: list[str] = []
    while True:
        message = ws.receive_json()  # type: ignore[attr-defined]
        if message["type"] == "ready":
            return types
        types.append(message["event"]["type"])


def test_a_ticket_opens_the_socket_once(home: Path) -> None:
    app = auth_app(home)
    token = token_for(app.state.auth, "alice", "read", client="browser")
    with TestClient(app, base_url=BASE) as client:
        ticket = client.post("/api/v1/auth/ws-ticket", headers=bearer(token), json={}).json()["ticket"]
        with client.websocket_connect(f"{WS_URL}?ticket={ticket}") as ws:
            ws.send_json({"type": "subscribe", "after_sequence": 0})
            drain(ws)
        with (
            pytest.raises(WebSocketDisconnect) as info,
            client.websocket_connect(f"{WS_URL}?ticket={ticket}"),
        ):
            pass
        assert info.value.code == 4401


def test_revoked_session_closes_the_socket_with_4401(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "WS_RECHECK_SECONDS", 0.0)
    app = auth_app(home)
    store: AuthStore = app.state.auth
    token = token_for(store, "alice", "read")
    alice = store.authenticate(token)
    assert alice is not None and store.session_active(str(alice.session_id))
    with (
        TestClient(app, base_url=BASE) as client,
        client.websocket_connect(WS_URL, headers=bearer(token)) as ws,
    ):
        ws.send_json({"type": "subscribe", "after_sequence": 0})
        drain(ws)
        store.revoke(str(alice.session_id), by=alice)
        with pytest.raises(WebSocketDisconnect) as info:
            ws.receive_json()
        assert info.value.code == 4401
    assert not store.session_active(str(alice.session_id))


def test_auth_and_notify_events_go_to_admins_only(home: Path) -> None:
    app = auth_app(home)
    events = app.state.ctx.events
    events.append(
        "auth.session_created", payload={"session_id": "s_x", "user": "u", "client": "cli"}
    )
    events.append("notify.sent", payload={"entry_id": "e"})
    events.append("notebook.updated", project="toy", payload={"project": "toy"})
    with TestClient(app, base_url=BASE) as client:
        seen = {}
        for user, scope in (("alice", "launch"), ("sv", "admin")):
            token = token_for(app.state.auth, user, scope)
            with client.websocket_connect(WS_URL, headers=bearer(token)) as ws:
                ws.send_json({"type": "subscribe", "after_sequence": 0})
                seen[scope] = drain(ws)
    assert "notebook.updated" in seen["launch"]
    assert not any(t.startswith(("auth.", "notify.")) for t in seen["launch"])
    assert {"auth.session_created", "notify.sent"} <= set(seen["admin"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_ws_auth.py -v`
Expected: FAIL: `test_revoked_session_closes_the_socket_with_4401` with `AttributeError: 'AuthStore' object has no attribute 'session_active'`, and `test_auth_and_notify_events_go_to_admins_only` because the `launch` socket sees `auth.session_created`.

- [ ] **Step 3: Write the implementation**

In `src/hypothex/auth/store.py`, add to `AuthStore` (after `authenticate`):

```python
    def session_active(self, session_id: str) -> bool:
        """
        Tell whether a session is still usable (checked by open WebSockets).

        Parameters
        ----------
        session_id : str

        Returns
        -------
        bool
            False when it is unknown, revoked, expired, or its user is disabled.
            Unlike ``authenticate`` it never slides the session.
        """
        with self._conn() as conn:
            row = conn.execute(
                'SELECT s.revoked_at, s.expires_at, u.disabled_at FROM sessions s '
                'JOIN users u ON u.name = s."user" WHERE s.id = ?',
                (session_id,),
            ).fetchone()
        return (
            row is not None
            and row["revoked_at"] is None
            and row["disabled_at"] is None
            and datetime.fromisoformat(row["expires_at"]) > self.now()
        )
```

In `src/hypothex/api/app.py`:

1. Add after `WS_BATCH = 500`:

```python
WS_RECHECK_SECONDS = 30.0
"""An open WebSocket re-checks its session this often (contract 1.10)."""
ADMIN_EVENT_PREFIXES = ("auth.", "notify.")
"""Event types only ``admin`` principals receive on the WebSocket."""
```

2. Add `principal_of` to the `hypothex.api.auth` import.

3. Replace the whole `events_ws` function with:

```python
    @app.websocket("/api/v1/ws", dependencies=READ)
    async def events_ws(ws: WebSocket) -> None:
        principal = principal_of(ws)
        admin = principal.scope == "admin"
        watch = auth_enabled and principal.session_id is not None
        await ws.accept()
        checked = time.monotonic()
        try:
            first = await ws.receive()
            if first["type"] == "websocket.disconnect":
                return
            try:
                sub = SubscribeMessage.model_validate_json(
                    first.get("text") or first.get("bytes") or ""
                )
            except ValidationError:
                await ws.send_json(
                    {
                        "type": "error",
                        "error": "first message must be {type: subscribe, after_sequence: N}"
                        " with N an integer >= 0",
                    }
                )
                await ws.close()
                return
            last = sub.after_sequence
            ready = False
            while True:
                if watch and time.monotonic() - checked >= WS_RECHECK_SECONDS:
                    checked = time.monotonic()
                    if not await asyncio.to_thread(store.session_active, str(principal.session_id)):
                        await ws.close(code=4401)
                        return
                batch = await asyncio.to_thread(ctx.events.since, last, WS_BATCH)
                for event in batch:
                    last = event.sequence
                    if not admin and event.type.startswith(ADMIN_EVENT_PREFIXES):
                        continue
                    await ws.send_json({"type": "event", "event": event.model_dump(mode="json")})
                if len(batch) < WS_BATCH:
                    if not ready:
                        await ws.send_json({"type": "ready", "last_sequence": last})
                        ready = True
                    if await client_left(ws, WS_POLL_SECONDS):
                        return
        except WebSocketDisconnect:
            return
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_ws_auth.py tests/api/test_app.py -v`
Expected: `tests/api/test_ws_auth.py` `3 passed`; the phase 1 WebSocket tests in `tests/api/test_app.py` still pass.

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check src`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/auth/store.py src/hypothex/api/app.py tests/api/test_ws_auth.py
git commit -m "feat(api): websocket tickets, 4401 on revoked sessions, admin-only event types"
```

---

### Task 27: Identity from the principal, run ownership, and `owner=me`

**Files:**
- Modify: `src/hypothex/api/app.py` (`ActionBody.owner`, `run_request`, `stamp`, `launcher_for`, `once` and `forward` keyed by `command_key`, routes `POST /api/v1/runs`, `POST /api/v1/hosts/{host}/runs`, rerun, reinfer, reeval, stop, tags, star, archive, notes, pull, task reeval, view PUT, sweeps POST, extend and cancel, `GET /api/v1/runs`)
- Modify: `src/hypothex/core/overview.py` (`owner` on `TimelineItem`, `IdeaRow`, `FailureRow`)
- Test: `tests/api/test_ownership_api.py`

**Interfaces:**
- Consumes: `identity`, `principal_of`, `command_key` (Task 23), `require_act` (Task 5), `RunRequest.owner`, `control.rerun/reinfer(owner=)`, `launch_sweep(owner=)` (Task 4).
- Produces (contract 1.2, exact): `ActionBody.owner: str | None = None`; `GET /api/v1/runs?owner=` (`me` = the caller; with auth off `me` filters nothing, since runs then have no owner).
- Produces (public helper): `stamp(conn, body) -> body` (a copy with `created_by`/`owner` from `identity`).
- Produces (additive, contract 1.12 "the Overview shows `owner`" on running and recent rows): `TimelineItem.owner`, `IdeaRow.owner` (the group's first run's, like its `created_by`), `FailureRow.owner`, each `str | None = None`.
- Rules: a run that would execute on this machine (`POST /api/v1/runs`, a host launch to `local`, a rerun or reinfer of a local run, a sweep or sweep extension placed here) needs `require_local_exec` (admin; contract 1.3, 7): its command runs as the server's Unix user and could read the owner's token in `server.json`, so a `launch` collaborator launches on hosts only, and gets 403 `runs on this machine need admin; launch on a host` here; launches, host launches, reruns, reinfers, and sweeps get `created_by`/`owner` from `identity` (a collaborator's body values are ignored; a hub's are kept); a note's `author` becomes the caller's identity; stop and archive need `require_act(..., record.owner, ...)` and sweep cancel `require_act(..., spec.owner, "cancel_queued")`; forwarded bodies carry `created_by` and `owner` to the host. Every receipt is stored under `command_key(request, command_id)` (Task 23): `once(conn, body, fn)` and `forward(conn, ...)` take the request; a forwarded body, a host launch, a sweep's own claim, and a cancel's per-run stops carry the hub's key instead of the raw id, so the host's receipts are per hub caller too. The same caller retrying gets the stored result even with an edited body (phase 1); another caller, or another route, with the same id runs its own command.

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_ownership_api.py`:

```python
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hypothex.api.app import create_app
from hypothex.core import control
from hypothex.core.context import Context
from hypothex.core.records import RunStatus
from hypothex.core.sweeps import SweepParam, SweepSpec, save_sweep
from tests.api.authkit import BASE, auth_app, bearer, token_for
from tests.factories import make_record

PY = sys.executable


@pytest.fixture
def hub(home: Path, toy_repo: Path) -> Iterator[tuple[FastAPI, TestClient, Context]]:
    ctx = Context.open(home)
    ctx.register_project(toy_repo)
    app = auth_app(home)
    with TestClient(app, base_url=BASE) as client:
        yield app, client, ctx


def queued(ctx: Context, run_id: str, owner: str | None) -> None:
    ctx.create_run(make_record(run_id, owner=owner, environment_id=ctx.descriptor.environment_id))


def launch_body(repo: Path, **over: object) -> dict[str, object]:
    body: dict[str, object] = {
        "repo": str(repo),
        "command": [PY, "-c", "pass"],
        "hypothesis": "ownership",
        "created_by": "human:sv",
        "owner": "sv",
    }
    body.update(over)
    return body


def test_body_identity_is_ignored_with_auth_on(
    hub: tuple[FastAPI, TestClient, Context], toy_repo: Path
) -> None:
    app, client, ctx = hub
    carol = token_for(app.state.auth, "carol", "admin")  # a second admin, not the owner sv
    record = client.post("/api/v1/runs", json=launch_body(toy_repo), headers=bearer(carol)).json()
    assert (record["created_by"], record["owner"]) == ("human:carol", "carol")
    headers = {**bearer(carol), "X-Hypothex-Agent": "claude"}
    agent = client.post("/api/v1/runs", json=launch_body(toy_repo), headers=headers).json()
    assert (agent["created_by"], agent["owner"]) == ("agent:claude@carol", "carol")
    for run in (record, agent):
        control.wait_for_run(ctx, str(run["run_id"]), timeout=30)


def test_launch_scope_never_runs_code_on_the_hub(
    hub: tuple[FastAPI, TestClient, Context], toy_repo: Path
) -> None:
    # a run here executes as the hub's user and could read the owner's token in server.json
    app, client, ctx = hub
    alice = bearer(token_for(app.state.auth, "alice", "launch"))
    queued(ctx, "hers", "alice")
    refused = [
        client.post("/api/v1/runs", json=launch_body(toy_repo), headers=alice),
        client.post("/api/v1/hosts/local/runs", json={"project": "toy"}, headers=alice),
        client.post("/api/v1/runs/hers/rerun", json={}, headers=alice),
        client.post("/api/v1/runs/hers/reinfer", json={}, headers=alice),
        client.post(
            "/api/v1/sweeps",
            json={
                "project": "toy", "grid": [], "seeds": [1], "command": [PY, "-c", "pass"],
                "hypothesis": "x",
            },  # fmt: skip
            headers=alice,
        ),
    ]
    assert [r.status_code for r in refused] == [403] * 5
    assert {r.json()["error"] for r in refused} == {
        "runs on this machine need admin; launch on a host"
    }
    assert [r.run_id for r in ctx.index.list_runs(limit=None)] == ["hers"]


def test_auth_off_keeps_phase_2_identity(home: Path, toy_repo: Path) -> None:
    ctx = Context.open(home)
    ctx.register_project(toy_repo)
    app = create_app(home, background_repair=False, hub=False, ui_dir=home / "no-ui")
    with TestClient(app, base_url=BASE) as client:
        record = client.post("/api/v1/runs", json=launch_body(toy_repo)).json()
    assert (record["created_by"], record["owner"]) == ("human:sv", None)
    control.wait_for_run(ctx, str(record["run_id"]), timeout=30)


def test_only_owner_or_admin_may_stop(hub: tuple[FastAPI, TestClient, Context]) -> None:
    app, client, ctx = hub
    alice = token_for(app.state.auth, "alice", "launch")
    admin = token_for(app.state.auth, "sv", "admin")
    for run_id, owner in (("svs", "sv"), ("hers", "alice"), ("legacy", None)):
        queued(ctx, run_id, owner)
    refused = client.post("/api/v1/runs/svs/stop", json={}, headers=bearer(alice))
    assert refused.status_code == 403
    assert refused.json()["error"] == "run owned by sv; stop needs owner or admin"
    assert (
        client.post("/api/v1/runs/legacy/stop", json={}, headers=bearer(alice)).status_code == 403
    )
    own = client.post("/api/v1/runs/hers/stop", json={}, headers=bearer(alice))
    assert own.json()["status"] == RunStatus.KILLED.value
    assert client.post("/api/v1/runs/svs/stop", json={}, headers=bearer(admin)).status_code == 200


def test_archive_needs_the_owner_but_tags_do_not(hub: tuple[FastAPI, TestClient, Context]) -> None:
    app, client, ctx = hub
    alice = token_for(app.state.auth, "alice", "launch")
    queued(ctx, "svs", "sv")
    assert (
        client.post("/api/v1/runs/svs/archive", json={}, headers=bearer(alice)).status_code == 403
    )
    tagged = client.post("/api/v1/runs/svs/tags", json={"add": ["seen"]}, headers=bearer(alice))
    assert tagged.json()["tags"] == ["seen"]


def test_sweep_cancel_needs_the_sweep_owner(hub: tuple[FastAPI, TestClient, Context]) -> None:
    app, client, ctx = hub
    alice = token_for(app.state.auth, "alice", "launch")
    save_sweep(
        ctx.layout,
        SweepSpec(
            id="s-0003",
            project="toy",
            task=None,
            host=None,
            grid=[SweepParam(name="x", values=["1"])],
            seeds=[1],
            command_template=["echo", "{x}"],
            created_by="human:sv",
            created_at=make_record().created_at,
            owner="sv",
        ),
    )
    resp = client.post("/api/v1/sweeps/toy/s-0003/cancel_queued", json={}, headers=bearer(alice))
    assert resp.status_code == 403 and "cancel_queued needs owner or admin" in resp.json()["error"]


def test_owner_me_filters_runs(hub: tuple[FastAPI, TestClient, Context]) -> None:
    app, client, ctx = hub
    alice = token_for(app.state.auth, "alice", "read")
    queued(ctx, "a1", "alice")
    queued(ctx, "s1", "sv")
    mine = client.get("/api/v1/runs?owner=me", headers=bearer(alice)).json()
    assert [r["run_id"] for r in mine] == ["a1"]
    theirs = client.get("/api/v1/runs?owner=sv", headers=bearer(alice)).json()
    assert [r["run_id"] for r in theirs] == ["s1"]


def test_owner_me_with_auth_off_lists_every_run(home: Path) -> None:
    app = create_app(home, background_repair=False, hub=False, ui_dir=home / "no-ui")
    ctx: Context = app.state.ctx
    queued(ctx, "a1", "alice")
    queued(ctx, "n1", None)  # what an auth-off launch records
    with TestClient(app, base_url=BASE) as client:
        mine = client.get("/api/v1/runs?owner=me").json()
    assert {r["run_id"] for r in mine} == {"a1", "n1"}


def test_overview_rows_name_their_owner(hub: tuple[FastAPI, TestClient, Context]) -> None:
    app, client, ctx = hub
    reader = token_for(app.state.auth, "bo", "read")
    queued(ctx, "al-fail", "alice")
    ctx.update_run(
        "al-fail",
        "run.failed",
        lambda r: r.model_copy(update={"status": RunStatus.FAILED, "ended_at": r.created_at}),
    )
    queued(ctx, "sv-q", "sv")
    body = client.get("/api/v1/overview", headers=bearer(reader)).json()
    assert {t["run_id"]: t["owner"] for t in body["timeline"]} == {"al-fail": "alice", "sv-q": "sv"}
    assert [(f["run_id"], f["owner"]) for f in body["failures"]] == [("al-fail", "alice")]
    assert body["ideas"] and all(i["owner"] in ("alice", "sv") for i in body["ideas"])
    assert [r["owner"] for r in body["running"]] == ["sv"]


def test_note_author_is_the_caller(hub: tuple[FastAPI, TestClient, Context]) -> None:
    app, client, ctx = hub
    alice = token_for(app.state.auth, "alice", "launch")
    queued(ctx, "svs", "sv")
    body = {"text": "looks good", "author": "human:sv"}
    assert client.post("/api/v1/runs/svs/notes", json=body, headers=bearer(alice)).json() == {
        "ok": True
    }
    assert "— human:alice" in ctx.store.read_notes("toy", "svs")


def test_a_command_id_is_bound_to_its_caller_and_route(
    hub: tuple[FastAPI, TestClient, Context],
) -> None:
    app, client, ctx = hub
    admin = bearer(token_for(app.state.auth, "sv", "admin"))
    alice = bearer(token_for(app.state.auth, "alice", "launch"))
    reader = token_for(app.state.auth, "bo", "read")
    queued(ctx, "r1", "sv")
    tags = "/api/v1/runs/r1/tags"
    first = client.post(tags, json={"add": ["a"], "command_id": "c1"}, headers=admin).json()
    assert first["tags"] == ["a"]
    # the same caller retrying gets the stored result, even with an edited body (phase 1)
    again = client.post(tags, json={"add": ["z"], "command_id": "c1"}, headers=admin).json()
    assert again["tags"] == ["a"]
    # another caller with the same id runs their own command
    hers = client.post(tags, json={"add": ["b"], "command_id": "c1"}, headers=alice).json()
    assert hers["tags"] == ["a", "b"]
    # a reader replaying the id on a read route gets that route's answer, not the admin's
    session = app.state.auth.authenticate(reader)
    assert session is not None
    out = client.post(
        f"/api/v1/auth/sessions/{session.session_id}/revoke",
        json={"command_id": "c1"},
        headers=bearer(reader),
    ).json()
    assert "tags" not in out and out["user"] == "bo"


def test_rerun_belongs_to_the_caller(
    hub: tuple[FastAPI, TestClient, Context], toy_repo: Path
) -> None:
    app, client, ctx = hub
    admin = token_for(app.state.auth, "sv", "admin")
    carol = token_for(app.state.auth, "carol", "admin")
    parent = client.post("/api/v1/runs", json=launch_body(toy_repo), headers=bearer(admin)).json()
    control.wait_for_run(ctx, str(parent["run_id"]), timeout=30)
    child = client.post(
        f"/api/v1/runs/{parent['run_id']}/rerun", json={}, headers=bearer(carol)
    ).json()
    assert (child["owner"], child["created_by"], child["parent"]) == (
        "carol",
        "human:carol",
        parent["run_id"],
    )
    control.wait_for_run(ctx, str(child["run_id"]), timeout=30)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_ownership_api.py -v`
Expected: FAIL: `test_body_identity_is_ignored_with_auth_on` with `('human:sv', None) != ('human:carol', 'carol')`, `test_launch_scope_never_runs_code_on_the_hub` and the stop/archive/cancel tests with `200 != 403`, and `test_owner_me_filters_runs` returning every run.

- [ ] **Step 3: Write the implementation**

In `src/hypothex/api/app.py`:

1. Add `from typing import TypeVar` (merge into the `typing` import), `from starlette.requests import HTTPConnection`, `auth_on`, `command_key` and `identity` to the `hypothex.api.auth` import, and `from hypothex.auth.ownership import require_act, require_local_exec`.

2. Replace `ActionBody` with:

```python
class ActionBody(BaseModel):
    """
    Common fields of every POST body.

    With auth on, ``created_by`` and ``owner`` are taken from the caller's
    session; the body's values count only when a hub forwards (contract 1.2).
    """

    command_id: str | None = None
    created_by: str = "api"
    owner: str | None = None
```

3. Add below `ActionBody` (before `class RunFields`):

```python
_Body = TypeVar("_Body", bound=ActionBody)


def stamp(conn: HTTPConnection, body: _Body) -> _Body:
    """
    Return a copy of a body with ``created_by`` and ``owner`` decided by the server.

    Parameters
    ----------
    conn : HTTPConnection
        The request.
    body : ActionBody
        The parsed body.

    Returns
    -------
    ActionBody
        Same type; see ``hypothex.api.auth.identity``.
    """
    created_by, owner = identity(conn, created_by=body.created_by, owner=body.owner)
    return body.model_copy(update={"created_by": created_by, "owner": owner})
```

4. In `run_request`, add `owner=body.owner,` after `created_by=body.created_by,`.

5. In `launcher_for`, in the `HostLaunchBody(...)` call, add `owner=req.owner,` after `created_by=req.created_by,`.

6. Key every receipt by `command_key` (Task 23). Replace `once` and `forward` with:

```python
    def once(conn: HTTPConnection, body: ActionBody, fn: Callable[[], Any]) -> dict[str, Any]:
        # keyed by caller and route: another caller's id, or this id on another route, is new
        return ctx.events.run_once(command_key(conn, body.command_id), lambda: to_jsonable(fn()))

    def forward(
        conn: HTTPConnection,
        run_id: str,
        action: str,
        body: ActionBody,
        local: Callable[[], Any],
        *,
        remote_only: bool = False,
    ) -> dict[str, Any]:
        # A run mirrored from a host is acted on by that host; same body, and the hub's
        # receipt key as its command_id, so the host's receipt is per hub caller too.
        # The run is looked up inside the receipt, so a replayed command_id gets its
        # receipt first (as in phase 1); an error releases the claim, so a retry runs again.
        key = command_key(conn, body.command_id)

        def act() -> Any:
            record = ctx.find_record(run_id)
            host = manager.host_for_environment(record.environment_id)
            if host is None:
                foreign = record.environment_id != ctx.descriptor.environment_id
                if remote_only and foreign:
                    # its pids and paths belong to another machine: never act on them here
                    raise HostUnavailableError(
                        f"run {run_id} belongs to environment {record.environment_id}, which "
                        f"no configured host serves; {action} must run on that host "
                        "(`hx hosts add` / `hx hosts connect`)"
                    )
                return local()
            payload = {**body.model_dump(mode="json"), "command_id": key}
            return manager.client(host).post_json(f"/api/v1/runs/{run_id}/{action}", payload)

        return ctx.events.run_once(key, lambda: to_jsonable(act()))
```

and replace these routes, which item 7 does not replace, so that they pass the request:

```python
    @app.post("/api/v1/tasks/{project}/{task}/reeval", dependencies=LAUNCH)
    def task_reeval(project: str, task: str, body: ReevalBody, request: Request) -> dict[str, Any]:
        return once(
            request,
            body,
            lambda: reeval(ctx, project=project, task=task, metric=body.metric, force=body.force),
        )
```

```python
    @app.put("/api/v1/tasks/{project}/{task}/views/{name}", dependencies=LAUNCH)
    def view_put(
        project: str, task: str, name: str, body: ViewPutBody, request: Request
    ) -> dict[str, Any]:
        return once(request, body, lambda: put_view(ctx, task, name, body.text, project))
```

```python
    @app.post("/api/v1/runs/{run_id}/reeval", dependencies=LAUNCH)
    def run_reeval(run_id: str, body: ReevalBody, request: Request) -> dict[str, Any]:
        return forward(
            request,
            run_id,
            "reeval",
            body,
            lambda: reeval(ctx, run_id=run_id, metric=body.metric, force=body.force),
            remote_only=True,
        )
```

```python
    @app.post("/api/v1/runs/{run_id}/tags", dependencies=LAUNCH)
    def run_tags(run_id: str, body: TagBody, request: Request) -> dict[str, Any]:
        def act() -> RunRecord:
            return q.tag_run(ctx, run_id, body.add, body.remove)

        return forward(request, run_id, "tags", body, act)

    @app.post("/api/v1/runs/{run_id}/star", dependencies=LAUNCH)
    def run_star(run_id: str, body: FlagBody, request: Request) -> dict[str, Any]:
        return forward(request, run_id, "star", body, lambda: q.star_run(ctx, run_id, body.on))
```

```python
    @app.post("/api/v1/runs/{run_id}/pull", dependencies=LAUNCH)
    def run_pull(run_id: str, body: PullBody, request: Request) -> dict[str, Any]:
        def act() -> dict[str, str]:
            return {"local_path": str(pull_artifact(ctx, manager, run_id, body.artifact))}

        return once(request, body, act)
```

7. Replace these route functions (decorators from Task 24 unchanged):

```python
    @app.post("/api/v1/hosts/{host}/runs", dependencies=LAUNCH)
    def host_launch(host: str, body: HostLaunchBody, request: Request) -> dict[str, Any]:
        if not is_remote(host):
            require_local_exec(principal_of(request))  # `local`: the run executes here
        body = stamp(request, body)
        # the host keeps its receipt under the hub's key: one per hub caller
        sent = body.model_copy(update={"command_id": command_key(request, body.command_id)})
        return once(request, body, lambda: launch_on_host(ctx, manager, host, sent))
```

```python
    @app.get("/api/v1/runs", dependencies=READ)
    def runs(
        request: Request,
        project: str | None = None,
        task: str | None = None,
        status: RunStatus | None = None,
        tag: str | None = None,
        environment_id: str | None = None,
        owner: str | None = None,
        archived: bool = False,
        limit: Annotated[int, Query(ge=1)] = 200,
    ) -> list[dict[str, Any]]:
        # no cap below `limit`: the UI pages through a host's queue or a sweep with a
        # growing limit, starting at 1000
        who = owner
        if owner == "me":  # with auth off runs have no owner: every run is the caller's
            who = principal_of(request).user if auth_on(request) else None
        return to_jsonable(
            ctx.index.list_runs(
                project=project,
                task=task,
                status=status,
                tag=tag,
                environment_id=environment_id,
                owner=who,
                include_archived=archived,
                limit=limit,
            )
        )

    @app.post("/api/v1/runs", dependencies=LAUNCH)
    def launch(body: LaunchBody, request: Request) -> dict[str, Any]:
        require_local_exec(principal_of(request))  # the command runs as this server's user
        body = stamp(request, body)
        return once(request, body, lambda: launch_here(ctx, body, body.repo))
```

```python
    @app.post("/api/v1/runs/{run_id}/rerun", dependencies=LAUNCH)
    def run_rerun(run_id: str, body: ActionBody, request: Request) -> dict[str, Any]:
        principal = principal_of(request)
        body = stamp(request, body)

        def here() -> RunRecord:  # a local run's child executes here; a host's is forwarded
            require_local_exec(principal)
            return control.rerun(ctx, run_id, created_by=body.created_by, owner=body.owner)

        return forward(request, run_id, "rerun", body, here, remote_only=True)

    @app.post("/api/v1/runs/{run_id}/reinfer", dependencies=LAUNCH)
    def run_reinfer(run_id: str, body: ReinferBody, request: Request) -> dict[str, Any]:
        principal = principal_of(request)
        body = stamp(request, body)

        def here() -> RunRecord:
            require_local_exec(principal)
            return control.reinfer(
                ctx,
                run_id,
                checkpoint=body.checkpoint,
                created_by=body.created_by,
                owner=body.owner,
            )

        return forward(request, run_id, "reinfer", body, here, remote_only=True)
```

```python
    @app.post("/api/v1/runs/{run_id}/stop", dependencies=LAUNCH)
    def run_stop(run_id: str, body: StopBody, request: Request) -> dict[str, Any]:
        require_act(principal_of(request), ctx.find_record(run_id).owner, "stop")

        def act() -> RunRecord:
            if body.only_queued:
                return stop_if_queued(ctx, run_id)
            return control.stop_run(ctx, run_id)

        return forward(request, run_id, "stop", body, act, remote_only=True)
```

```python
    @app.post("/api/v1/runs/{run_id}/archive", dependencies=LAUNCH)
    def run_archive(run_id: str, body: FlagBody, request: Request) -> dict[str, Any]:
        require_act(principal_of(request), ctx.find_record(run_id).owner, "archive")
        return forward(
            request, run_id, "archive", body, lambda: q.archive_run(ctx, run_id, body.on)
        )

    @app.post("/api/v1/runs/{run_id}/notes", dependencies=LAUNCH)
    def run_note(run_id: str, body: NoteBody, request: Request) -> dict[str, Any]:
        author, _ = identity(request, created_by=body.author, owner=None)
        body = body.model_copy(update={"author": author})

        def act() -> dict[str, bool]:
            q.add_note(ctx, run_id, body.text, body.author)
            return {"ok": True}

        return forward(request, run_id, "notes", body, act)
```

In `sweep_create`, change the signature to `def sweep_create(body: SweepBody, request: Request) -> dict[str, Any]:`, add as its first lines

```python
        if not is_remote(body.host):
            require_local_exec(principal_of(request))  # its runs execute on this machine
        body = stamp(request, body)
```

in the `launch_sweep(...)` call add `owner=body.owner,` after `created_by=body.created_by,` and replace `command_id=body.command_id,  # a retry resumes this sweep (Task 40)` with `command_id=command_key(request, body.command_id),  # a retry by this caller resumes it`, and replace its last line `return once(body, act)` with `return once(request, body, act)`.

Replace `sweep_extend` with:

```python
    @app.post("/api/v1/sweeps/{project}/{sweep_id}/extend", dependencies=LAUNCH)
    def sweep_extend(
        project: str, sweep_id: str, body: SeedsBody, request: Request
    ) -> dict[str, Any]:
        principal = principal_of(request)

        def act() -> SweepSummary:
            spec = find_sweep(ctx, sweep_id, project)
            if not is_remote(spec.host):
                require_local_exec(principal)  # the new seeds run on this machine
            launched: list[str] = []
            launch = launcher_for(spec.host, launched, project=spec.project)
            more = extend_sweep(ctx, spec.project, spec.id, body.seeds, launch=launch)
            return settled(more.spec, launched)

        return once(request, body, act)
```

Replace `sweep_cancel` with:

```python
    @app.post("/api/v1/sweeps/{project}/{sweep_id}/cancel_queued", dependencies=LAUNCH)
    def sweep_cancel(
        project: str, sweep_id: str, request: Request, body: ActionBody | None = None
    ) -> dict[str, Any]:
        action = body or ActionBody()
        principal = principal_of(request)

        def act() -> SweepSummary:
            spec = find_sweep(ctx, sweep_id, project)
            require_act(principal, spec.owner, "cancel_queued")
            stop = stopper_for(spec.host, command_key(request, action.command_id))
            return cancel_queued(ctx, spec.project, spec.id, stop=stop)

        return once(request, action, act)
```

In `src/hypothex/core/overview.py`, add this field as the last field of `TimelineItem` (after `label: str`), of `IdeaRow` (after its `unit` docstring), and of `FailureRow` (after `retried_ok: bool`):

```python
    owner: str | None = None
    """The run's owner (``RunRecord.owner``); None with auth off or before phase 3."""
```

then pass it where `build_overview` builds them: `owner=run.owner,` after `label=label(run),` in `TimelineItem(...)`; `owner=members[0].owner,` after `created_by=members[0].created_by,` in `IdeaRow(...)`; `owner=run.owner,` after `retried_ok=_retried_ok(run, everything),` in `FailureRow(...)`. (`running` is a list of `RunRecord`, which carries `owner` since Task 4.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api -v`
Expected: `tests/api/test_ownership_api.py` `12 passed`; every phase 1–2 API test (forwarding, sweeps, hosts, `test_put_view_is_idempotent_by_command_id`) still passes: with auth off `identity` keeps the body's `created_by` and every caller is `LOCAL_OWNER` (admin, so local runs are allowed), and the hub's forwarded bodies now also carry `owner`.

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check src`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/api/app.py src/hypothex/core/overview.py tests/api/test_ownership_api.py
git commit -m "feat(api): server-set run identity, owner-only stop and archive, owner filter"
```

---

### Task 28: The scope matrix test

**Files:**
- Test: `tests/api/test_route_scopes.py` (append)

**Interfaces:**
- Consumes: every route of `create_app` with auth on (this task's test also covers routes added by Tasks 29–31, because it walks `route_scopes`).
- Produces: contract 9's table-driven test: each declared route is called as a `read`, a `launch`, and an `admin` principal, with path parameters set to `x` and an empty JSON body for `POST`/`PUT`; the answer is 403 exactly when the principal's scope does not cover the declared one. Fresh tokens per call (so `logout` cannot spoil later calls).

- [ ] **Step 1: Write the test**

Append to `tests/api/test_route_scopes.py` (and add `import re`, `import pytest`, `from hypothex.auth.scopes import covers`, `from tests.api.authkit import BASE, WS_URL, auth_app, bearer, token_for`):

```python
USERS = {"read": "reader", "launch": "launcher", "admin": "sv"}


@pytest.mark.parametrize("held", ["read", "launch", "admin"])
def test_scope_matrix(home: Path, held: str) -> None:
    app = auth_app(home)
    wrong: list[str] = []
    with TestClient(app, base_url=BASE) as client:
        for key, declared in sorted(route_scopes(app).items()):
            method, path = key.split(" ", 1)
            if method == "WS" or declared == "public":
                continue
            token = token_for(app.state.auth, USERS[held], held)  # type: ignore[arg-type]
            url = re.sub(r"\{[^}]+\}", "x", path)
            body = {} if method in ("POST", "PUT") else None
            status = client.request(method, url, json=body, headers=bearer(token)).status_code
            if (status == 403) != (not covers(held, declared)):  # type: ignore[arg-type]
                wrong.append(f"{key}: {status} as {held}")
    assert wrong == []


def test_websocket_needs_only_read(home: Path) -> None:
    app = auth_app(home)
    token = token_for(app.state.auth, "reader", "read")
    with (
        TestClient(app, base_url=BASE) as client,
        client.websocket_connect(WS_URL, headers=bearer(token)) as ws,
    ):
        ws.send_json({"type": "subscribe", "after_sequence": 0})
        assert ws.receive_json()["type"] in ("event", "ready")
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/api/test_route_scopes.py -v`
Expected: `8 passed` (4 earlier + 3 matrix cases + the WebSocket test). A route whose handler raises `ScopeError` for another reason, or that declares the wrong scope, shows up in the `wrong` list with its status.

Run: `uv run ruff check tests && uv run ruff format --check tests`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add tests/api/test_route_scopes.py
git commit -m "test(api): scope matrix over every route for read, launch, and admin"
```

---
## Part 8: Team routes — notebook, export, digest, notifications, storage

Contract 3 (new routes), 1.12 (what a collaborator sees). The route groups live in their own modules; `create_app` registers them. With auth off they behave as in a single-user hub.

### Task 29: Notebook, export, and digest routes

**Files:**
- Create: `src/hypothex/api/routes_team.py`
- Modify: `src/hypothex/api/app.py` (register the routes; 409 and 413 mapping)
- Test: `tests/api/test_team_routes.py`

**Interfaces:**
- Consumes: `hypothex.core.notebook` (Task 8), `hypothex.core.export` (Tasks 10–12), `hypothex.core.digest` (Tasks 18–19), `principal_of`, `auth_on`.
- Produces (contract 3, exact): `GET /api/v1/projects/{project}/notebook` (read), `GET|POST|PUT /api/v1/projects/{project}/notebook/{day}` (read | launch | launch), `GET /api/v1/tasks/{project}/{task}/export` (read), `GET /api/v1/compare/export` (read), `GET /api/v1/projects/{project}/digest` (read), `POST /api/v1/projects/{project}/digest/send` (admin). `GET .../leaderboard` already carries `baselines` (Task 9) and `GET /api/v1/runs/{id}` carries `cleaned` and `record.owner` (Tasks 4, 22).
- Produces (public helper): `register_team_routes(app, ctx)`; `notebook_author(conn) -> str` (`human:<user>` / `agent:<agent>@<user>` with auth on, `human` with auth off).
- Rules: `{day}` is `YYYY-MM-DD` or `today` (the hub's date, `hub_today`: the UI and `hx note` in client mode never compute it themselves); `NotebookConflictError` → 409 `{error, type, current}`; `NotebookTooLargeError` → 413. Export options are query parameters (`metrics` and `groups` comma-separated); the answer is `text/plain; charset=utf-8` (LaTeX, Markdown) or `text/csv; charset=utf-8` with `Content-Disposition: attachment; filename="<task>.<ext>"` (`compare.<ext>`); `run_ids` takes 2 to 20 ids. The digest window defaults to the last 7 days; naive datetimes are UTC.

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_team_routes.py`:

```python
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hypothex.core.context import Context
from hypothex.core.evaluation import evaluate_run
from hypothex.core.notebook import NOTEBOOK_MAX_BYTES, hub_today
from tests.api.authkit import BASE, auth_app, bearer, token_for
from tests.factories import PREDS_075, seed_finished_run

PREDS_025 = [{"id": f"ex-{i}", "prediction": 1} for i in range(4)]
NOTEBOOK = "/api/v1/projects/toy/notebook"


@pytest.fixture
def team(home: Path, toy_repo: Path) -> Iterator[tuple[FastAPI, TestClient, Context]]:
    ctx = Context.open(home)
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    seed_finished_run(ctx, toy_repo, "r2", predictions=PREDS_025)
    evaluate_run(ctx, "r1")
    evaluate_run(ctx, "r2")
    app = auth_app(home)
    with TestClient(app, base_url=BASE) as client:
        yield app, client, ctx


def test_notebook_round_trip(team: tuple[FastAPI, TestClient, Context]) -> None:
    app, client, ctx = team
    alice = bearer(token_for(app.state.auth, "alice", "launch"))
    day = client.post(f"{NOTEBOOK}/2026-10-04", json={"text": "see [[run:r1]]"}, headers=alice)
    assert day.status_code == 200 and "— human:alice" in day.json()["text"]
    assert day.json()["runs"][0]["primary"] == 0.75
    assert client.get(NOTEBOOK, headers=alice).json() == [
        {"day": "2026-10-04", "bytes": len(day.json()["text"].encode()), "entries": 1}
    ]
    saved = client.put(
        f"{NOTEBOOK}/2026-10-04",
        json={"text": "# rewritten\n", "base_hash": day.json()["hash"]},
        headers=alice,
    )
    assert saved.json()["text"] == "# rewritten\n"
    stale = client.put(
        f"{NOTEBOOK}/2026-10-04",
        json={"text": "mine", "base_hash": day.json()["hash"]},
        headers=alice,
    )
    assert stale.status_code == 409 and stale.json()["type"] == "NotebookConflictError"
    assert stale.json()["current"]["text"] == "# rewritten\n"
    big = client.put(
        f"{NOTEBOOK}/2026-10-05",
        json={"text": "x" * (NOTEBOOK_MAX_BYTES + 1), "base_hash": ""},
        headers=alice,
    )
    assert big.status_code == 413
    assert client.get(f"{NOTEBOOK}/04-10-2026", headers=alice).status_code == 400
    now_day = client.get(f"{NOTEBOOK}/today", headers=alice).json()["day"]
    assert now_day == hub_today(ctx).isoformat()  # the hub names "today", not the caller


def test_task_export_downloads(team: tuple[FastAPI, TestClient, Context]) -> None:
    app, client, _ = team
    reader = bearer(token_for(app.state.auth, "reader", "read"))
    md = client.get("/api/v1/tasks/toy/toy-acc/export", headers=reader)
    assert md.headers["content-type"] == "text/plain; charset=utf-8"
    assert md.headers["content-disposition"] == 'attachment; filename="toy-acc.md"'
    assert md.text.startswith("| group | n | accuracy/value ↑ |")
    tex = client.get("/api/v1/tasks/toy/toy-acc/export?format=latex&digits=2", headers=reader)
    assert tex.text.startswith("% requires \\usepackage{booktabs}")
    assert tex.headers["content-disposition"].endswith('filename="toy-acc.tex"')
    csv = client.get("/api/v1/tasks/toy/toy-acc/export?format=csv&noise=seed", headers=reader)
    assert csv.headers["content-type"] == "text/csv; charset=utf-8"
    assert csv.text.splitlines()[0].startswith("kind,label,key,n,metric,mean")


def test_compare_export(team: tuple[FastAPI, TestClient, Context]) -> None:
    app, client, _ = team
    reader = bearer(token_for(app.state.auth, "reader", "read"))
    resp = client.get("/api/v1/compare/export?run_ids=r1,r2&format=csv", headers=reader)
    assert resp.headers["content-disposition"] == 'attachment; filename="compare.csv"'
    assert resp.text.splitlines()[1].startswith("run,r1,r1,1,accuracy/value,0.75")
    assert client.get("/api/v1/compare/export?run_ids=r1", headers=reader).status_code == 400


def test_leaderboard_and_run_detail_carry_phase_3_fields(
    team: tuple[FastAPI, TestClient, Context],
) -> None:
    app, client, _ = team
    reader = bearer(token_for(app.state.auth, "reader", "read"))
    board = client.get("/api/v1/tasks/toy/toy-acc/leaderboard", headers=reader).json()
    assert board["baselines"] == []
    detail = client.get("/api/v1/runs/r1", headers=reader).json()
    assert detail["cleaned"] == [] and detail["record"]["owner"] is None


def test_digest_routes(team: tuple[FastAPI, TestClient, Context]) -> None:
    app, client, ctx = team
    admin = bearer(token_for(app.state.auth, "sv", "admin"))
    digest = client.get("/api/v1/projects/toy/digest", headers=admin).json()
    assert digest["project"] == "toy" and digest["counts"]["started"] == 2
    sent = client.post("/api/v1/projects/toy/digest/send", json={}, headers=admin).json()
    assert sent["channels"] == [] and sent["notebook_day"] is not None  # no channel configured
    day = client.get(f"{NOTEBOOK}/{sent['notebook_day']}", headers=admin).json()
    assert "— digest" in day["text"]
    launcher = bearer(token_for(app.state.auth, "alice", "launch"))
    assert (
        client.post("/api/v1/projects/toy/digest/send", json={}, headers=launcher).status_code
        == 403
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_team_routes.py -v`
Expected: FAIL: the notebook, export, compare-export, and digest tests get `404`; `test_leaderboard_and_run_detail_carry_phase_3_fields` passes already (Tasks 9 and 22).

- [ ] **Step 3: Write the routes**

Create `src/hypothex/api/routes_team.py`:

```python
"""Notebook, export, and digest routes (phase 3)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from fastapi import FastAPI, Query, Request
from pydantic import BaseModel, Field
from starlette.requests import HTTPConnection
from starlette.responses import Response

from hypothex.api.auth import ADMIN, LAUNCH, READ, auth_on, command_key, principal_of
from hypothex.core.context import Context
from hypothex.core.digest import build_digest, send_digest
from hypothex.core.errors import RunError
from hypothex.core.export import (
    EXTENSIONS,
    ExportFormat,
    ExportOptions,
    NoiseMode,
    export_compare,
    export_task,
)
from hypothex.core.ids import utcnow
from hypothex.core.jsonutil import to_jsonable
from hypothex.core.notebook import (
    append_entry,
    hub_today,
    list_days,
    parse_day,
    read_day,
    today,
    write_day,
)
from hypothex.core.settings import Channel, load_settings


class NotebookAppendBody(BaseModel):
    """Body of ``POST .../notebook/{day}``; the author is the caller."""

    text: str
    command_id: str | None = None


class NotebookWriteBody(BaseModel):
    """Body of ``PUT .../notebook/{day}``."""

    text: str
    base_hash: str
    command_id: str | None = None


class DigestSendBody(BaseModel):
    """Body of ``POST .../digest/send``."""

    since: datetime | None = None
    channels: list[Channel] | None = None
    command_id: str | None = None


def notebook_author(conn: HTTPConnection) -> str:
    """
    Return who writes a notebook entry.

    Parameters
    ----------
    conn : HTTPConnection

    Returns
    -------
    str
        The caller's identity with auth on; ``human`` with auth off.
    """
    return principal_of(conn).identity() if auth_on(conn) else "human"


def _aware(moment: datetime | None) -> datetime | None:
    if moment is not None and moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment


def _split(value: str | None) -> list[str] | None:
    items = [v.strip() for v in (value or "").split(",") if v.strip()]
    return items or None


def _download(text: str, fmt: str, stem: str) -> Response:
    media = "text/csv; charset=utf-8" if fmt == "csv" else "text/plain; charset=utf-8"
    disposition = f'attachment; filename="{stem}.{EXTENSIONS[fmt]}"'
    return Response(text, media_type=media, headers={"Content-Disposition": disposition})


def register_team_routes(app: FastAPI, ctx: Context) -> None:
    """
    Add the notebook, export, and digest routes.

    Parameters
    ----------
    app : FastAPI
    ctx : Context
    """

    def the_day(day: str) -> date:
        # `today` is the hub's date (contract 1.4), so a browser or a client in another
        # zone never picks the day file; anything else must be YYYY-MM-DD
        return hub_today(ctx) if day == "today" else parse_day(day)

    @app.get("/api/v1/projects/{project}/notebook", dependencies=READ)
    def notebook_days(project: str) -> list[dict[str, Any]]:
        return list_days(ctx, project)

    @app.get("/api/v1/projects/{project}/notebook/{day}", dependencies=READ)
    def notebook_day(project: str, day: str) -> dict[str, Any]:
        return to_jsonable(read_day(ctx, project, the_day(day)))

    @app.post("/api/v1/projects/{project}/notebook/{day}", dependencies=LAUNCH)
    def notebook_append(
        project: str, day: str, body: NotebookAppendBody, request: Request
    ) -> dict[str, Any]:
        when = the_day(day)
        author = notebook_author(request)
        return ctx.events.run_once(
            command_key(request, body.command_id),
            lambda: to_jsonable(append_entry(ctx, project, body.text, author, day=when)),
        )

    @app.put("/api/v1/projects/{project}/notebook/{day}", dependencies=LAUNCH)
    def notebook_write(
        project: str, day: str, body: NotebookWriteBody, request: Request
    ) -> dict[str, Any]:
        when = the_day(day)
        author = notebook_author(request)
        return ctx.events.run_once(
            command_key(request, body.command_id),
            lambda: to_jsonable(
                write_day(ctx, project, when, body.text, base_hash=body.base_hash, author=author)
            ),
        )

    def options(
        fmt: ExportFormat,
        metrics: str | None,
        noise: NoiseMode,
        digits: int,
        percent: bool,
        top: int | None,
        groups: str | None,
        baselines: bool,
        caption: str | None,
        label: str | None,
        standalone: bool,
    ) -> ExportOptions:
        return ExportOptions(
            format=fmt,
            metrics=_split(metrics),
            noise=noise,
            digits=digits,
            percent=percent,
            top=top,
            groups=_split(groups),
            baselines=baselines,
            caption=caption,
            label=label,
            standalone=standalone,
        )

    @app.get("/api/v1/tasks/{project}/{task}/export", dependencies=READ)
    def task_export(
        project: str,
        task: str,
        format: ExportFormat = "markdown",
        metrics: str | None = None,
        noise: NoiseMode = "both",
        digits: Annotated[int, Query(ge=0, le=6)] = 3,
        percent: bool = False,
        top: Annotated[int | None, Query(ge=1)] = None,
        groups: str | None = None,
        baselines: bool = True,
        caption: str | None = None,
        label: str | None = None,
        standalone: bool = False,
    ) -> Response:
        opts = options(
            format, metrics, noise, digits, percent, top, groups, baselines, caption, label,
            standalone,
        )  # fmt: skip
        return _download(export_task(ctx, task, project, opts), opts.format, task)

    @app.get("/api/v1/compare/export", dependencies=READ)
    def compare_export(
        run_ids: str,
        format: ExportFormat = "markdown",
        metrics: str | None = None,
        noise: NoiseMode = "both",
        digits: Annotated[int, Query(ge=0, le=6)] = 3,
        percent: bool = False,
        top: Annotated[int | None, Query(ge=1)] = None,
        groups: str | None = None,
        baselines: bool = True,
        caption: str | None = None,
        label: str | None = None,
        standalone: bool = False,
    ) -> Response:
        ids = _split(run_ids) or []
        if not 2 <= len(ids) <= 20:
            raise RunError("run_ids takes 2 to 20 comma-separated run ids")
        opts = options(
            format, metrics, noise, digits, percent, top, groups, baselines, caption, label,
            standalone,
        )  # fmt: skip
        return _download(export_compare(ctx, ids, opts), opts.format, "compare")

    @app.get("/api/v1/projects/{project}/digest", dependencies=READ)
    def digest(
        project: str, since: datetime | None = None, until: datetime | None = None
    ) -> dict[str, Any]:
        end = _aware(until) or utcnow()
        start = _aware(since) or end - timedelta(days=7)
        top_notes = load_settings(ctx.layout).digest.top_notes
        return to_jsonable(build_digest(ctx, project, since=start, until=end, top_notes=top_notes))

    @app.post("/api/v1/projects/{project}/digest/send", dependencies=ADMIN)
    def digest_send(project: str, body: DigestSendBody, request: Request) -> dict[str, Any]:
        settings = load_settings(ctx.layout)

        def act() -> dict[str, Any]:
            now = utcnow()
            channels = send_digest(
                ctx, settings, project, now=now, channels=body.channels, since=_aware(body.since)
            )
            day = today(now, settings.digest.timezone) if settings.digest.save_to_notebook else None
            return {"channels": channels, "notebook_day": None if day is None else day.isoformat()}

        return ctx.events.run_once(command_key(request, body.command_id), act)
```

In `src/hypothex/api/app.py`:

1. Add `from hypothex.api.routes_team import register_team_routes` and `from hypothex.core.notebook import NotebookConflictError, NotebookTooLargeError` to the imports.
2. In `hypothex_error`, after `elif isinstance(exc, ScopeError): status = 403` add:

```python
        elif isinstance(exc, NotebookConflictError):
            status = 409
        elif isinstance(exc, NotebookTooLargeError):
            status = 413
```

   and after `content["issues"] = ...` add:

```python
        if isinstance(exc, NotebookConflictError):
            content["current"] = to_jsonable(exc.current)
```

3. Replace

```python
    register_auth_routes(app, ctx, store)
    register_env_routes(app, ctx)
```

with

```python
    register_auth_routes(app, ctx, store)
    register_team_routes(app, ctx)
    register_env_routes(app, ctx)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_team_routes.py tests/api/test_route_scopes.py -v`
Expected: `tests/api/test_team_routes.py` `5 passed`; `tests/api/test_route_scopes.py` `8 passed` (the matrix now covers the new routes).

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check src`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/api/routes_team.py src/hypothex/api/app.py tests/api/test_team_routes.py
git commit -m "feat(api): notebook, export, and digest routes"
```

---

### Task 30: Notification routes and the notifier thread in the hub

**Files:**
- Modify: `src/hypothex/notify/notifier.py` (`Notifier.send_test`)
- Modify: `src/hypothex/api/routes_team.py` (`GET /api/v1/notify`, `POST /api/v1/notify/test`)
- Modify: `src/hypothex/api/app.py` (`create_app(notifier=)`, the notifier thread, `NOTIFY_INTERVAL_SECONDS`)
- Test: `tests/api/test_team_routes.py` (append)

**Interfaces:**
- Produces (contract 3, exact): `GET /api/v1/notify` (admin) → `{channels: {slack: {configured, env, set}, email: {configured, env, set, host, to}}, projects, default, digest, recent}`; `POST /api/v1/notify/test` (admin) `{channel, command_id?}` → `{ok, error_class}`.
- Produces (additive): `Notifier.send_test(channel) -> dict[str, Any]` (sends a test notice now, not through the outbox); `notify_status(ctx, settings) -> dict[str, Any]` (the body of `GET /api/v1/notify`, shared with `hx notify status`, Task 44); `create_app(..., notifier: bool | None = None)` (default: `background_repair and hub and` the environment kind is `local`); `NOTIFY_INTERVAL_SECONDS = 5.0`.
- Rules: `set` says whether the variable has a value; the value never appears in an answer. The notifier thread runs only in the hub (`kind == "local"`), stops with the lifespan, and is joined like the scheduler thread.

- [ ] **Step 1: Write the failing test**

Append to `tests/api/test_team_routes.py` (and add `import os`, `from hypothex.api import app as app_module`, `from hypothex.api.app import create_app`, `from hypothex.core.records import RunStatus`, `from hypothex.core.settings import NotifySettings, ProjectRule, Settings, SlackSettings, save_settings`, `from tests.api.envserver import wait_until`, `from tests.factories import make_record`, `from tests.fakes.webhook import FakeWebhook`):

```python
@pytest.fixture
def hook(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeWebhook]:
    with FakeWebhook() as fake:
        monkeypatch.setenv("HX_TEST_HOOK", fake.url)
        yield fake


def slack_settings() -> Settings:
    return Settings(
        notify=NotifySettings(
            slack=SlackSettings(webhook_env="HX_TEST_HOOK"),
            projects={"toy": ProjectRule(channels=["slack"])},
        )
    )


def test_notify_status_never_returns_a_secret(home: Path, hook: FakeWebhook) -> None:
    save_settings(Context.open(home).layout, slack_settings())
    app = auth_app(home)
    with TestClient(app, base_url=BASE) as client:
        admin = bearer(token_for(app.state.auth, "sv", "admin"))
        status = client.get("/api/v1/notify", headers=admin)
        launcher = bearer(token_for(app.state.auth, "alice", "launch"))
        assert client.get("/api/v1/notify", headers=launcher).status_code == 403
    body = status.json()
    assert body["channels"]["slack"] == {"configured": True, "env": "HX_TEST_HOOK", "set": True}
    assert body["channels"]["email"]["configured"] is False
    assert body["projects"]["toy"]["channels"] == ["slack"] and body["recent"] == []
    assert hook.secret not in status.text and os.environ["HX_TEST_HOOK"] not in status.text


def test_notify_test_sends_now(
    home: Path, hook: FakeWebhook, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_settings(Context.open(home).layout, slack_settings())
    app = auth_app(home)
    with TestClient(app, base_url=BASE) as client:
        admin = bearer(token_for(app.state.auth, "sv", "admin"))
        ok = client.post("/api/v1/notify/test", json={"channel": "slack"}, headers=admin).json()
        assert ok == {"ok": True, "error_class": None}
        assert hook.requests[0]["body"]["text"] == "✓ hypothex test · slack"
        monkeypatch.delenv("HX_TEST_HOOK")
        unset = client.post("/api/v1/notify/test", json={"channel": "slack"}, headers=admin).json()
        assert unset == {"ok": False, "error_class": "unset:HX_TEST_HOOK"}
        email = client.post("/api/v1/notify/test", json={"channel": "email"}, headers=admin).json()
        assert email == {"ok": False, "error_class": "unconfigured"}


def test_hub_runs_the_notifier_thread(
    home: Path, hook: FakeWebhook, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "NOTIFY_INTERVAL_SECONDS", 0.05)
    ctx = Context.open(home)
    save_settings(ctx.layout, slack_settings())
    app = create_app(home, background_repair=False, hub=False, notifier=True, ui_dir=home / "no-ui")
    with TestClient(app, base_url=BASE):
        wait_until(lambda: (ctx.layout.home / "notify" / "cursor.json").exists(), timeout=10)
        ctx.create_run(make_record("n1", environment_id=ctx.descriptor.environment_id))
        ctx.update_run(
            "n1",
            "run.failed",
            lambda r: r.model_copy(update={"status": RunStatus.FAILED, "ended_at": r.created_at}),
        )
        wait_until(lambda: hook.requests, timeout=10)
    assert hook.requests[0]["body"]["text"].startswith("✗ toy/t n1")


def test_notifier_is_off_without_background_loops(home: Path) -> None:
    app = create_app(home, background_repair=False, hub=False, ui_dir=home / "no-ui")
    with TestClient(app, base_url=BASE):
        pass
    assert not (home / "notify" / "cursor.json").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_team_routes.py -v`
Expected: FAIL: the two notify route tests get `404`, `test_hub_runs_the_notifier_thread` with `TypeError: create_app() got an unexpected keyword argument 'notifier'`.

- [ ] **Step 3: Write the implementation**

Append to the `Notifier` class in `src/hypothex/notify/notifier.py` (and add `from typing import Any` and `test_notice` to the `hypothex.notify.messages` import):

```python
    def send_test(self, channel: Channel) -> dict[str, Any]:
        """
        Send a test notice on one channel now (not through the outbox).

        Parameters
        ----------
        channel : Channel

        Returns
        -------
        dict
            ``{"ok": bool, "error_class": str | None}``; the error class is
            redacted (``unset:<VAR>``, ``unconfigured``, ``http_404``, ...).
        """
        now = self.now()
        notice = test_notice(channel)
        entry = OutboxEntry(
            id=notice.id,
            channel=channel,
            notice=notice,
            status="sending",
            next_at=now,
            created_at=now,
        )
        try:
            self._send(entry)
        except _Skip as exc:
            return {"ok": False, "error_class": exc.error_class}
        except ConfigError:
            return {"ok": False, "error_class": "secrets_file"}
        except ChannelError as exc:
            return {"ok": False, "error_class": redact(exc.error_class, self.secret_values())}
        return {"ok": True, "error_class": None}
```

and append at module level:

```python
def notify_status(ctx: Context, settings: Settings) -> dict[str, Any]:
    """
    Describe the notification setup without any secret value.

    Parameters
    ----------
    ctx : Context
    settings : Settings

    Returns
    -------
    dict
        ``{channels: {slack: {configured, env, set}, email: {configured, env, set,
        host, to}}, projects, default, digest, recent}``; ``set`` says whether the
        variable has a value.
    """

    def has_value(name: str | None) -> bool:
        if name is None:
            return False
        try:
            return resolve_secret(ctx.layout, name) is not None
        except ConfigError:
            return False

    slack, email = settings.notify.slack, settings.notify.email
    email_set = email is not None and (not email.username or has_value(email.password_env))
    channels: dict[str, Any] = {
        "slack": {
            "configured": slack is not None,
            "env": slack.webhook_env if slack else None,
            "set": has_value(slack.webhook_env) if slack else False,
        },
        "email": {
            "configured": email is not None,
            "env": email.password_env if email else None,
            "set": email_set,
            "host": email.host if email else None,
            "to": email.to if email else [],
        },
    }
    return {
        "channels": channels,
        "projects": {k: v.model_dump(mode="json") for k, v in settings.notify.projects.items()},
        "default": settings.notify.default.model_dump(mode="json")
        if settings.notify.default
        else None,
        "digest": settings.digest.model_dump(mode="json"),
        "recent": [e.model_dump(mode="json") for e in Notifier(ctx, settings).recent()],
    }
```

In `src/hypothex/api/routes_team.py`, add `from hypothex.notify.notifier import Notifier, notify_status` to its imports and this body model at module scope, after `DigestSendBody`:

```python
class NotifyTestBody(BaseModel):
    """Body of ``POST /api/v1/notify/test``."""

    channel: Channel
    command_id: str | None = None
```

Then append to `register_team_routes`:

```python
    @app.get("/api/v1/notify", dependencies=ADMIN)
    def notify_route() -> dict[str, Any]:
        return notify_status(ctx, load_settings(ctx.layout))

    @app.post("/api/v1/notify/test", dependencies=ADMIN)
    def notify_test(body: NotifyTestBody, request: Request) -> dict[str, Any]:
        notifier = Notifier(ctx, load_settings(ctx.layout))
        key = command_key(request, body.command_id)
        return ctx.events.run_once(key, lambda: notifier.send_test(body.channel))
```

(`NotifyTestBody` must live at module scope: the module uses `from __future__ import annotations`, so FastAPI resolves the annotation `NotifyTestBody` from the module's globals; a class local to `register_team_routes` is not found there and FastAPI reads `body` as a required query parameter, answering the documented JSON body with 422. Every other body model of the plan is module-level for the same reason.)

In `src/hypothex/api/app.py`:

1. Add `from hypothex.notify.notifier import run_notifier_loop` to the imports and, after `SCHEDULER_INTERVAL_SECONDS = 5.0`, add:

```python
NOTIFY_INTERVAL_SECONDS = 5.0
"""The hub's notifier ticks this often (Slack/email outbox, digests)."""
```

2. In the signature of `create_app`, after `public_url: str | None = None,` add `notifier: bool | None = None,` and document it:

```
    notifier : bool, optional
        Run the notifier thread (Slack/email, digests). Default: on for the hub
        (``kind`` ``local``) when ``background_repair`` and ``hub`` are on.
```

3. After `store = AuthStore(...)` add:

```python
    run_notifier = (
        notifier
        if notifier is not None
        else background_repair and hub and ctx.descriptor.kind == "local"
    )
```

(Task 23 put `store = ...` after the `kind` override, so `ctx.descriptor.kind` is final here.)

4. In `lifespan`, right before the first `for loop in loops:` (the one that calls `loop.start()`, above the `SlurmPoller`; not the join loop inside the nested `finally`) add:

```python
        if run_notifier:
            loops.append(
                threading.Thread(
                    target=run_notifier_loop,
                    args=(ctx, stop),
                    kwargs={"interval": NOTIFY_INTERVAL_SECONDS},
                    name="hx-notifier",
                    daemon=True,
                )
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_team_routes.py tests/api/test_route_scopes.py tests/notify -v`
Expected: `tests/api/test_team_routes.py` `9 passed`; the matrix and notify tests still pass.

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check src`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/notify/notifier.py src/hypothex/api/routes_team.py src/hypothex/api/app.py tests/api/test_team_routes.py
git commit -m "feat(api): notification status and test routes; notifier thread in the hub"
```

---

### Task 31: Storage routes on the hub and on env servers

**Files:**
- Create: `src/hypothex/api/routes_storage.py`
- Modify: `src/hypothex/api/app.py` (register the routes with the `HubManager` as `HostClients`)
- Test: `tests/api/test_storage_routes.py`

**Interfaces:**
- Consumes: `storage_report`, `plan_clean`, `apply_clean`, `local_usage`, `check_artifacts`, `delete_artifacts` (Tasks 20–22); `HubManager` (phase 2; it has `names`, `client`, `host_for_environment`, so it satisfies `HostClients`).
- Produces (contract 3, exact): `GET /api/v1/storage` (admin, `project?`, `remote?=true`) → `StorageReport`; `POST /api/v1/storage/plan` (admin, `CleanPolicy` + `command_id?`) → `CleanPlan`; `POST /api/v1/storage/plans/{plan_id}/apply` (admin, `{confirm_bytes, command_id?}`) → `CleanResult` (400 `CleanRefusedError`); env routes `GET /api/v1/storage/usage` (admin, `project?`) → `list[StorageItem]` and `POST /api/v1/storage/check` (admin, `{items, older_than_days}`) → `list[{path, run_id, host, reason}]` (read-only refusals), and `POST /api/v1/storage/delete` (admin, `{items, plan_id, actor, older_than_days, command_id?}`) → `CleanResult`.
- Produces (public helper): `register_storage_routes(app, ctx, hosts)`.
- Rules: `created_by`/`actor` are the caller's identity (`human` with auth off). There is no MCP path to apply or delete (Task 33).

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_storage_routes.py`:

```python
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hypothex.api.app import create_app
from hypothex.core.context import Context
from hypothex.core.ids import utcnow
from hypothex.core.records import Artifact, RunStatus
from tests.api.envserver import remote_hub, wait_until
from tests.factories import make_record

BASE = "http://127.0.0.1:7777"


def archived(ctx: Context, run_id: str, artifact: Path) -> None:
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"x" * 20_000)
    ended = utcnow() - timedelta(days=40)
    ctx.create_run(
        make_record(
            run_id,
            status=RunStatus.FINISHED,
            archived=True,
            started_at=ended - timedelta(hours=1),
            ended_at=ended,
            artifacts=[Artifact(kind="checkpoint", path=str(artifact))],
            environment_id=ctx.descriptor.environment_id,
        )
    )


def test_hub_plans_and_applies_local_cleanup(home: Path, tmp_path: Path) -> None:
    ctx = Context.open(home)
    archived(ctx, "old", tmp_path / "scratch" / "old.pt")
    app = create_app(home, background_repair=False, hub=False, ui_dir=home / "no-ui")
    with TestClient(app, base_url=BASE) as client:
        report = client.get("/api/v1/storage").json()
        assert report["by_kind"]["artifact"] > 0 and report["errors"] == []
        plan = client.post("/api/v1/storage/plan", json={"older_than_days": 30}).json()
        assert [i["run_id"] for i in plan["items"]] == ["old"] and plan["created_by"] == "human"
        url = f"/api/v1/storage/plans/{plan['plan_id']}/apply"
        wrong = client.post(url, json={"confirm_bytes": plan["total_bytes"] + 1})
        assert wrong.status_code == 400 and wrong.json()["type"] == "CleanRefusedError"
        done = client.post(url, json={"confirm_bytes": plan["total_bytes"]}).json()
    assert (
        done["freed_bytes"] == plan["total_bytes"]
        and not (tmp_path / "scratch" / "old.pt").exists()
    )


def test_policy_must_stay_archived_only(home: Path) -> None:
    app = create_app(home, background_repair=False, hub=False, ui_dir=home / "no-ui")
    with TestClient(app, base_url=BASE) as client:
        resp = client.post("/api/v1/storage/plan", json={"archived": False})
    assert resp.status_code == 422


def test_env_routes_list_and_delete(home: Path, tmp_path: Path) -> None:
    ctx = Context.open(home)
    archived(ctx, "old", tmp_path / "scratch" / "old.pt")
    app = create_app(home, background_repair=False, hub=False, ui_dir=home / "no-ui", kind="ssh")
    with TestClient(app, base_url=BASE) as client:
        usage = client.get("/api/v1/storage/usage").json()
        item = next(u for u in usage if u["kind"] == "artifact")
        body = {
            "items": [
                {
                    **{k: item[k] for k in ("project", "run_id", "host", "environment_id")},
                    "kind": "artifact",
                    "artifact_kind": "checkpoint",
                    "path": item["path"],
                    "bytes": item["bytes"],
                    "mtime": item["mtime"],
                    "reason": "archived 40d",
                }
            ],
            "plan_id": "cp-0000000a",
            "actor": "human:sv",
            "older_than_days": 30,
        }
        checked = client.post(
            "/api/v1/storage/check",
            json={
                "items": body["items"],
                "older_than_days": 30,
            },
        )
        assert checked.status_code == 200 and checked.json() == []
        assert Path(item["path"]).exists()  # preflight is read-only
        done = client.post("/api/v1/storage/delete", json=body).json()
    assert [d["run_id"] for d in done["deleted"]] == ["old"] and done["skipped"] == []


@pytest.mark.parametrize("after_plan", [False, True])
def test_host_checks_checkpoint_alias_on_its_own_filesystem(
    tmp_path: Path, after_plan: bool
) -> None:
    with remote_hub(tmp_path) as r:
        checkpoint = tmp_path / "host-data" / "parent.pt"
        archived(r.env, "parent", checkpoint)
        wait_until(lambda: "parent" in r.hub.index.run_ids(), timeout=30)
        alias = tmp_path / "host-alias"
        alias.symlink_to(checkpoint.parent, target_is_directory=True)

        def reader() -> None:
            r.env.create_run(
                make_record(
                    "reader",
                    archived=False,
                    status=RunStatus.QUEUED,
                    environment_id=r.env.descriptor.environment_id,
                    cwd=str(tmp_path),
                    vars={"checkpoint": "host-alias/parent.pt"},
                )
            )

        if not after_plan:
            reader()  # host check must see this without waiting for a mirrored reader
        result = r.client.post("/api/v1/storage/plan", json={}).json()
        if after_plan:
            assert len(result["items"]) == 1
            reader()
            response = r.client.post(
                f"/api/v1/storage/plans/{result['plan_id']}/apply",
                json={
                    "confirm_bytes": result["total_bytes"],
                },
            ).json()
            assert response["deleted"] == []
            assert any(row["reason"] == "used by reader" for row in response["skipped"])
        else:
            assert result["items"] == []
            assert any(row["reason"] == "used by reader" for row in result["refused"])
        assert checkpoint.exists()


def test_hub_cleans_a_hosts_artifacts(tmp_path: Path) -> None:
    with remote_hub(tmp_path) as r:
        archived(r.env, "g1", tmp_path / "gpu1-scratch" / "g1.pt")
        wait_until(lambda: "g1" in r.hub.index.run_ids(), timeout=30)
        report = r.client.get("/api/v1/storage").json()
        assert any(i["host"] == "gpu1" and i["run_id"] == "g1" for i in report["items"])
        plan = r.client.post("/api/v1/storage/plan", json={}).json()
        assert [(i["host"], i["run_id"]) for i in plan["items"]] == [("gpu1", "g1")]
        url = f"/api/v1/storage/plans/{plan['plan_id']}/apply"
        done = r.client.post(url, json={"confirm_bytes": plan["total_bytes"]}).json()
        assert [d["host"] for d in done["deleted"]] == ["gpu1"] and done["errors"] == []
        assert not (tmp_path / "gpu1-scratch" / "g1.pt").exists()
        env_record = r.env.find_record("g1")
        assert (r.env.run_dir(env_record) / ".hx" / "cleaned.json").is_file()
        hub_record = r.hub.find_record("g1")
        assert (r.hub.run_dir(hub_record) / ".hx" / "cleaned.json").is_file()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_storage_routes.py -v`
Expected: FAIL: every test gets `404` from `/api/v1/storage...`, except `test_policy_must_stay_archived_only` (`404 != 422`).

- [ ] **Step 3: Write the routes**

Create `src/hypothex/api/routes_storage.py`:

```python
"""Storage routes: the hub's report, plan, and apply; each env server's usage and delete."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field

from hypothex.api.auth import ADMIN, command_key, identity
from hypothex.core.context import Context
from hypothex.core.jsonutil import to_jsonable
from hypothex.core.settings import load_settings
from hypothex.core.storage import (
    CleanItem,
    CleanPolicy,
    HostClients,
    apply_clean,
    check_artifacts,
    delete_artifacts,
    local_usage,
    plan_clean,
    storage_report,
)


class PlanBody(CleanPolicy):
    """Body of ``POST /api/v1/storage/plan``: a policy plus a command id."""

    command_id: str | None = None


class ApplyBody(BaseModel):
    """Body of ``POST /api/v1/storage/plans/{plan_id}/apply``."""

    confirm_bytes: int = Field(ge=0)
    command_id: str | None = None


class CheckBody(BaseModel):
    """Read-only owning-environment cleanup preflight."""

    items: list[CleanItem]
    older_than_days: int = Field(ge=0)


class DeleteBody(BaseModel):
    """Body of the env route ``POST /api/v1/storage/delete`` (sent by the hub)."""

    items: list[CleanItem]
    plan_id: str = Field(pattern=r"^cp-[0-9a-f]{8}$")
    actor: str = Field(min_length=1, max_length=100)
    older_than_days: int = Field(ge=0)  # the plan's policy: the host rechecks the age too
    command_id: str | None = None


def register_storage_routes(app: FastAPI, ctx: Context, hosts: HostClients | None) -> None:
    """
    Add the storage routes.

    Parameters
    ----------
    app : FastAPI
    ctx : Context
    hosts : HostClients or None
        The hub's host connections (``HubManager``).
    """

    def who(request: Request) -> str:
        return identity(request, created_by="human", owner=None)[0]

    @app.get("/api/v1/storage", dependencies=ADMIN)
    def storage(project: str | None = None, remote: bool = True) -> dict[str, Any]:
        return to_jsonable(storage_report(ctx, hosts, project=project, remote=remote))

    @app.post("/api/v1/storage/plan", dependencies=ADMIN)
    def make_plan(body: PlanBody, request: Request) -> dict[str, Any]:
        policy = CleanPolicy.model_validate(body.model_dump(exclude={"command_id"}))
        settings = load_settings(ctx.layout).storage
        created_by = who(request)
        return ctx.events.run_once(
            command_key(request, body.command_id),
            lambda: to_jsonable(
                plan_clean(ctx, hosts, policy, created_by=created_by, settings=settings)
            ),
        )

    @app.post("/api/v1/storage/plans/{plan_id}/apply", dependencies=ADMIN)
    def apply(plan_id: str, body: ApplyBody, request: Request) -> dict[str, Any]:
        actor = who(request)
        return ctx.events.run_once(
            command_key(request, body.command_id),
            lambda: to_jsonable(
                apply_clean(ctx, hosts, plan_id, confirm_bytes=body.confirm_bytes, actor=actor)
            ),
        )

    @app.get("/api/v1/storage/usage", dependencies=ADMIN)
    def usage(project: str | None = None) -> list[dict[str, Any]]:
        return to_jsonable(local_usage(ctx, project=project))

    @app.post("/api/v1/storage/check", dependencies=ADMIN)
    def check(body: CheckBody) -> list[dict[str, str]]:
        return check_artifacts(ctx, body.items, older_than_days=body.older_than_days)

    @app.post("/api/v1/storage/delete", dependencies=ADMIN)
    def delete(body: DeleteBody, request: Request) -> dict[str, Any]:
        return ctx.events.run_once(
            command_key(request, body.command_id),
            lambda: to_jsonable(
                delete_artifacts(
                    ctx,
                    body.items,
                    actor=body.actor,
                    plan_id=body.plan_id,
                    older_than_days=body.older_than_days,
                )
            ),
        )
```

In `src/hypothex/api/app.py`, add `from hypothex.api.routes_storage import register_storage_routes` to the imports and replace

```python
    register_team_routes(app, ctx)
    register_env_routes(app, ctx)
```

with

```python
    register_team_routes(app, ctx)
    register_storage_routes(app, ctx, manager)
    register_env_routes(app, ctx)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_storage_routes.py tests/api/test_route_scopes.py -v`
Expected: all storage-route regression cases pass; `tests/api/test_route_scopes.py` `8 passed`.

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check src`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/api/routes_storage.py src/hypothex/api/app.py tests/api/test_storage_routes.py
git commit -m "feat(api): storage report, plan, and apply on the hub; usage and delete on env servers"
```

---
## Part 9: MCP

Contract 1.10 (`scoped`), 5 (tools and scopes), 7. Over `/mcp` with auth on, the caller's principal (from the guard) applies to every tool; stdio `hx mcp` runs as `LOCAL_OWNER`, and its hub calls use the CLI's login (Task 41).

### Task 32: `@scoped` on every MCP tool, the caller's identity, and `/mcp` behind auth

**Files:**
- Modify: `src/hypothex/mcp/server.py` (`scoped`, `tool_scopes`, `acting_as`, `caller`, `caller_token`, identity in launching tools, every tool decorated)
- Test: `tests/mcp/test_scoped_tools.py`

**Interfaces:**
- Produces (contract 1.10, exact): `scoped(scope) -> Callable[[F], F]` (tool decorator), `tool_scopes(server) -> dict[str, Scope]`.
- Produces (public helpers): `acting_as(principal)` (context manager: the principal of in-process tool calls, e.g. tests and stdio); `caller() -> Principal` (inside a tool); `caller_token() -> str | None` (the exact credential selected by the guard in private ASGI state, so the tool's own hub calls act as the caller); `tool_hub_token(fallback) -> str | None` (over HTTP `caller_token()` and never the fallback; in-process/stdio `fallback()`); `TOOL_SCOPE_ATTR = "__hx_scope__"`.
- Rules: the wrapper finds the principal in `ctx.request_context.request.scope["hx.principal"]` (an HTTP call through `AuthGuard`/`TokenGuard`), else the `acting_as` principal, else `LOCAL_OWNER`; a tool whose scope the caller does not hold raises a tool error `403 · <scope> scope needed; you hold <scope>`. List/get tools are `read`; `launch_run`, `rerun`, `reinfer`, `reevaluate`, `stop_run`, `add_note`, `tag_run`, `add_view`, `launch_sweep`, `cancel_sweep`, `extend_sweep`, `pull_artifact`, `connect_host` are `launch`; `list_sweeps` is `read`. A session principal launches as `agent:<agent>@<user>` with `owner=<user>`; `LOCAL_OWNER` keeps `agent:<agent>` and no owner. Over HTTP a tool's hub calls carry only the caller's credential: a cookie caller forwards its cookie's session token, and a caller without one gets no token, never `hub_token` or the local admin token (that fallback would let any caller act with the server's own rights). Tools apply the same ownership rules as HTTP (contract 1.3): `stop_run` on a local run calls `require_act(caller(), record.owner, "stop")` and `cancel_sweep` on a local sweep `require_act(caller(), spec.owner, "cancel_queued")` before acting, and `launch_run`, `rerun`, `reinfer`, `launch_sweep`, `extend_sweep` call `require_local_exec(caller())` before a run that executes on this machine (a `launch` caller launches on hosts only); forwarded calls are checked by the hub, which sees the caller's own token. Tool errors reach the client as `Error executing tool <name>: <message>` (the SDK's prefix), so tests match the message's end.

- [ ] **Step 1: Write the failing test**

Create `tests/mcp/test_scoped_tools.py`:

```python
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from hypothex.auth.store import Principal
from tests.api.authkit import BASE, auth_app

from hypothex.core import control
from hypothex.core.context import Context
from hypothex.core.sweeps import SweepParam, SweepSpec, save_sweep
from hypothex.mcp.server import (
    acting_as,
    build_server,
    caller,
    caller_token,
    scoped,
    tool_hub_token,
    tool_scopes,
)
from tests.factories import make_record
from tests.mcp.test_server import call

PY = sys.executable
READER = Principal(user="bob", scope="read", session_id="s_00000000000b", client="cli")
ALICE = Principal(user="alice", scope="launch", session_id="s_00000000000a", client="cli")
CAROL = Principal(user="carol", scope="admin", session_id="s_00000000000c", client="cli")
LAUNCH_TOOLS = {
    "launch_run", "rerun", "reinfer", "reevaluate", "stop_run", "add_note", "tag_run",
    "add_view", "launch_sweep", "cancel_sweep", "extend_sweep", "pull_artifact", "connect_host",
}  # fmt: skip


def test_every_tool_declares_a_scope(home: Path) -> None:
    server = build_server(home)
    names = {t.name for t in asyncio.run(server.list_tools())}
    scopes = tool_scopes(server)
    assert set(scopes) == names
    assert {n for n, s in scopes.items() if s == "launch"} == LAUNCH_TOOLS
    assert all(s == "read" for n, s in scopes.items() if n.startswith(("list_", "get_")))


def test_read_principal_cannot_launch(home: Path, toy_repo: Path) -> None:
    with acting_as(READER):
        err, message = call(
            home,
            "launch_run",
            {"repo": str(toy_repo), "hypothesis": "x", "command": [PY, "-c", "pass"]},
        )
        # the SDK prefixes "Error executing tool launch_run: "; the message is ours
        assert err and message.endswith("403 · launch scope needed; you hold read")
        err, _ = call(home, "list_projects")
        assert not err


def test_session_principal_launches_as_agent_at_user(home: Path, toy_repo: Path) -> None:
    args = {"repo": str(toy_repo), "hypothesis": "x", "command": [PY, "-c", "pass"]}
    with acting_as(CAROL):
        err, out = call(home, "launch_run", {**args, "agent": "claude"})
    assert not err, out
    assert (out["run"]["created_by"], out["run"]["owner"]) == ("agent:claude@carol", "carol")
    control.wait_for_run(Context.open(home), out["run"]["run_id"], timeout=30)
    with acting_as(ALICE):  # launch scope: hosts only, never this machine
        err, message = call(home, "launch_run", {**args, "agent": "claude"})
    assert err and message.endswith("runs on this machine need admin; launch on a host")


def test_local_owner_keeps_phase_2_identity(home: Path, toy_repo: Path) -> None:
    err, out = call(
        home,
        "launch_run",
        {"repo": str(toy_repo), "hypothesis": "x", "command": [PY, "-c", "pass"]},
    )
    assert not err and (out["run"]["created_by"], out["run"]["owner"]) == ("agent:mcp", None)
    control.wait_for_run(Context.open(home), out["run"]["run_id"], timeout=30)


def fake_http(credential: str | None) -> SimpleNamespace:
    request = SimpleNamespace(scope={"hx.principal": ALICE, "hx.credential": credential})
    return SimpleNamespace(request_context=SimpleNamespace(request=request))


def test_http_principal_and_token_reach_the_tool() -> None:
    def who() -> dict[str, str | None]:
        return {
            "user": caller().user,
            "token": caller_token(),
            "hub": tool_hub_token(lambda: "SERVER-ADMIN"),
        }

    wrapped = scoped("read")(who)
    bearer_call = fake_http("hxs_abc")
    expected = {"user": "alice", "token": "hxs_abc", "hub": "hxs_abc"}
    assert wrapped(hx_mcp_ctx=bearer_call) == expected
    cookie_call = fake_http("hxs_cookie")
    assert wrapped(hx_mcp_ctx=cookie_call)["hub"] == "hxs_cookie"  # never the server's token
    bare_call = fake_http(None)
    assert wrapped(hx_mcp_ctx=bare_call)["hub"] is None
    local = wrapped(hx_mcp_ctx=None)
    assert local == {"user": "local", "token": None, "hub": "SERVER-ADMIN"}  # stdio
    with pytest.raises(Exception, match="admin scope needed"):
        scoped("admin")(who)(hx_mcp_ctx=bearer_call)


@pytest.mark.parametrize("authorization", [None, b"Bearer rejected", b"Bearer ", b"Bearer \xa0"])
@pytest.mark.parametrize("tool_name", ["stop_run", "get_sweep", "cancel_sweep", "extend_sweep"])
def test_registered_http_tool_forwards_only_authenticated_cookie(
    home: Path, monkeypatch: pytest.MonkeyPatch, authorization: bytes | None, tool_name: str
) -> None:
    import httpx
    from hypothex.api.auth import AuthGuard
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from tests.api.authkit import token_for

    app = auth_app(home)
    token = token_for(app.state.auth, "alice", "launch")
    server = build_server(home, hub_url=BASE, hub_token="SERVER-ADMIN")
    tool = next(t for t in server._tool_manager.list_tools() if t.name == tool_name)
    args = (
        {"run_id": "remote-run"}
        if tool_name == "stop_run"
        else {
            "project": "toy",
            "sweep_id": "s-0001",
        }
    )
    if tool_name == "extend_sweep":
        args["seeds"] = [2]
    spec = SweepSpec(
        id="s-0001",
        project="toy",
        task=None,
        host=None,
        grid=[SweepParam(name="x", values=["1"])],
        seeds=[1],
        command_template=["echo", "{x}"],
        created_by="human:alice",
        created_at=make_record().created_at,
        owner="alice",
    )
    sent: list[dict[str, str]] = []

    def request(method: str, url: str, **kwargs: object) -> httpx.Response:
        assert url.startswith(BASE + "/api/v1/")
        sent.append(dict(kwargs["headers"]))
        return httpx.Response(200, json={"spec": spec.model_dump(mode="json")})

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("HTTP caller must never discover the server credential")

    monkeypatch.setattr("hypothex.mcp.server.httpx.request", request)
    monkeypatch.setattr("hypothex.mcp.server.resolve_hub_token", forbidden)

    async def invoke(request: Request) -> JSONResponse:
        mcp_ctx = SimpleNamespace(request_context=SimpleNamespace(request=request))
        return JSONResponse(tool.fn(**args, hx_mcp_ctx=mcp_ctx))

    endpoint = Starlette(routes=[Route("/mcp/", invoke, methods=["POST"])])
    with TestClient(AuthGuard(endpoint, app.state.auth), base_url=BASE) as client:
        headers = [(b"cookie", f"hx_session={token}".encode())]
        if authorization is not None:
            headers.append((b"authorization", authorization))
        assert client.post("/mcp/", headers=headers, json={}).status_code == 200
    assert sent and all(headers["Authorization"] == f"Bearer {token}" for headers in sent)
    # Even a principal-only HTTP context cannot activate either discovery layer.
    sent.clear()
    tool.fn(**args, hx_mcp_ctx=fake_http(None))
    assert sent and all("Authorization" not in headers for headers in sent)


@pytest.mark.parametrize("tool_name", ["list_runs", "get_run"])
@pytest.mark.parametrize("credential", ["hxs_selected", None])
def test_host_state_reads_never_discover_a_server_token_over_http(
    home: Path,
    toy_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    credential: str | None,
) -> None:
    import httpx

    ctx = Context.open(home)
    ctx.register_project(toy_repo)
    ctx.create_run(make_record("remote-read", environment_id="env-remote"))
    sent: list[dict[str, str]] = []

    def request(method: str, url: str, **kwargs: object) -> httpx.Response:
        assert method == "GET" and "/api/v1/runs?" in url
        sent.append(dict(kwargs["headers"]))
        return httpx.Response(200, json=[{"host_state": "connected"}])

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("HTTP host-state reads cannot discover a server credential")

    monkeypatch.setattr("hypothex.mcp.server.httpx.request", request)
    monkeypatch.setattr("hypothex.mcp.server.resolve_hub_token", forbidden)
    server = build_server(home, hub_url=BASE, hub_token="SERVER-ADMIN")
    tool = next(t for t in server._tool_manager.list_tools() if t.name == tool_name)
    args = {"run_id": "remote-read"} if tool_name == "get_run" else {}
    tool.fn(**args, hx_mcp_ctx=fake_http(credential))
    assert len(sent) == 1
    if credential is None:
        assert "Authorization" not in sent[0]
    else:
        assert sent[0]["Authorization"] == f"Bearer {credential}"


def test_read_principal_cannot_reconnect_a_host(home: Path) -> None:
    with acting_as(READER):
        err, message = call(home, "connect_host", {"name": "gpu1"})
    assert err and message.endswith("403 · launch scope needed; you hold read")


def test_tools_keep_the_ownership_rules(home: Path, toy_repo: Path) -> None:
    ctx = Context.open(home)
    ctx.register_project(toy_repo)
    ctx.create_run(make_record("svs", owner="sv", environment_id=ctx.descriptor.environment_id))
    save_sweep(
        ctx.layout,
        SweepSpec(
            id="sw-sv",
            project="toy",
            task=None,
            host=None,
            grid=[SweepParam(name="x", values=["1"])],
            seeds=[1],
            command_template=["echo", "{x}"],
            created_by="human:sv",
            created_at=make_record().created_at,
            owner="sv",
        ),
    )
    with acting_as(ALICE):
        err, message = call(home, "stop_run", {"run_id": "svs"})
        assert err and message.endswith("run owned by sv; stop needs owner or admin")
        err, message = call(home, "cancel_sweep", {"project": "toy", "sweep_id": "sw-sv"})
        assert err and message.endswith("run owned by sv; cancel_queued needs owner or admin")
    assert ctx.find_record("svs").status.value == "queued"


def test_mcp_over_http_needs_a_session(home: Path) -> None:
    with TestClient(auth_app(home), base_url=BASE) as client:
        resp = client.post("/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert resp.status_code == 401 and resp.json()["type"] == "AuthError"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/mcp/test_scoped_tools.py -v`
Expected: FAIL at collection with `ImportError: cannot import name 'acting_as' from 'hypothex.mcp.server'`.

- [ ] **Step 3: Write `scoped` and its helpers**

In `src/hypothex/mcp/server.py`, add to the imports:

```python
import inspect
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TypeVar, cast

from mcp.server.mcpserver import Context as McpContext

from hypothex.auth.ownership import require_act, require_local_exec
from hypothex.auth.scopes import Scope, covers
from hypothex.auth.store import LOCAL_OWNER, Principal
```

(merge with the existing `collections.abc`, `contextlib`, and `typing` imports; `hypothex.api.auth` imports only FastAPI, Starlette, and `hypothex.auth`, so there is no cycle with `hypothex.api.app`), and add after `_expose_errors`:

```python
F = TypeVar("F", bound=Callable[..., Any])
TOOL_SCOPE_ATTR = "__hx_scope__"
_CTX_PARAM = "hx_mcp_ctx"
_ACTING: ContextVar[Principal | None] = ContextVar("hx_mcp_acting", default=None)
_CALLER: ContextVar[Principal] = ContextVar("hx_mcp_caller", default=LOCAL_OWNER)
_CALLER_TOKEN: ContextVar[str | None] = ContextVar("hx_mcp_caller_token", default=None)
_OVER_HTTP: ContextVar[bool] = ContextVar("hx_mcp_over_http", default=False)


@contextmanager
def acting_as(principal: Principal) -> Iterator[None]:
    """
    Run in-process tool calls (tests, stdio) as ``principal``.

    Parameters
    ----------
    principal : Principal

    Yields
    ------
    None
    """
    token = _ACTING.set(principal)
    try:
        yield
    finally:
        _ACTING.reset(token)


def caller() -> Principal:
    """
    Return the principal of the tool call being served.

    Returns
    -------
    Principal
    """
    return _CALLER.get()


def caller_token() -> str | None:
    """
    Return the caller's credential over HTTP, so a tool's hub calls act as the caller.

    Returns
    -------
    str or None
        The exact bearer or cookie credential the guard authenticated; None
        in-process, over stdio, or for an HTTP caller with no selected credential.
    """
    return _CALLER_TOKEN.get()


def _request_of(mcp_ctx: Any) -> Any:
    if mcp_ctx is None:
        return None
    try:
        return mcp_ctx.request_context.request
    except (ValueError, AttributeError, LookupError):
        return None


def _principal_from(request: Any) -> Principal:
    scope = getattr(request, "scope", None)
    if isinstance(scope, dict):
        found = scope.get("hx.principal")
        if isinstance(found, Principal):
            return found
    acting = _ACTING.get()
    return acting if acting is not None else LOCAL_OWNER


def _credential_from(request: Any) -> str | None:
    # Forward exactly the credential AuthGuard/TokenGuard authenticated, not a second
    # interpretation of the headers. A rejected bearer can coexist with a valid cookie.
    scope = getattr(request, "scope", None)
    found = scope.get("hx.credential") if isinstance(scope, dict) else None
    return found if isinstance(found, str) and found else None


def tool_hub_token(fallback: Callable[[], str | None]) -> str | None:
    """
    Choose the bearer token a tool's own hub calls send.

    Parameters
    ----------
    fallback : callable
        The server's token (``hub_token`` or ``resolve_hub_token``); used only
        for in-process and stdio calls.

    Returns
    -------
    str or None
        Over HTTP the caller's credential (``caller_token()``), even when it is
        None: a caller never borrows the server's own rights.
    """
    if _OVER_HTTP.get():
        return caller_token()
    return fallback()


def scoped(scope: Scope) -> Callable[[F], F]:
    """
    Declare the scope an MCP tool needs, and check it on every call.

    The wrapper adds a hidden ``hx_mcp_ctx`` parameter (an MCP ``Context``,
    left out of the tool's schema by the SDK) to reach the HTTP request.

    Parameters
    ----------
    scope : {"read", "launch", "admin"}

    Returns
    -------
    callable
        The decorator; ``tool_scopes`` reads the scope back.
    """

    def wrap(fn: F) -> F:
        signature = inspect.signature(fn, eval_str=True)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            request = _request_of(kwargs.pop(_CTX_PARAM, None))
            principal = _principal_from(request)
            if not covers(principal.scope, scope):
                raise ToolError(f"403 · {scope} scope needed; you hold {principal.scope}")
            who = _CALLER.set(principal)
            token = _CALLER_TOKEN.set(_credential_from(request))
            over_http = _OVER_HTTP.set(request is not None)
            try:
                return fn(*args, **kwargs)
            finally:
                _OVER_HTTP.reset(over_http)
                _CALLER_TOKEN.reset(token)
                _CALLER.reset(who)

        params = list(signature.parameters.values())
        hidden = inspect.Parameter(
            _CTX_PARAM, inspect.Parameter.KEYWORD_ONLY, default=None, annotation=McpContext
        )
        wrapper.__signature__ = signature.replace(parameters=[*params, hidden])  # type: ignore[attr-defined]
        wrapper.__annotations__ = {
            **{p.name: p.annotation for p in params if p.annotation is not p.empty},
            _CTX_PARAM: McpContext,
            "return": signature.return_annotation,
        }
        setattr(wrapper, TOOL_SCOPE_ATTR, scope)
        return cast(F, wrapper)

    return wrap


def tool_scopes(server: MCPServer) -> dict[str, Scope]:
    """
    List the declared scope of every tool of a server.

    Parameters
    ----------
    server : MCPServer

    Returns
    -------
    dict of str to Scope
        Tool name to scope; tools without ``@scoped`` are absent (a test fails on them).
    """
    manager = getattr(server, "_tool_manager", None)
    tools = manager.list_tools() if manager is not None else []
    return {
        t.name: getattr(t.fn, TOOL_SCOPE_ATTR)
        for t in tools
        if getattr(t.fn, TOOL_SCOPE_ATTR, None) is not None
    }
```

- [ ] **Step 4: Decorate every tool and use the caller's identity**

In `build_server`:

1. Replace `def auth()` with:

```python
    def auth() -> str | None:
        # over HTTP only the caller's own credential (the hub sees who acts and
        # applies their scope and ownership); the server's token only in-process/stdio
        return tool_hub_token(lambda: hub_token or resolve_hub_token(hub_url, ctx().layout.home))
```

Before adding tool helpers, add `discover_token: bool = True` to `hub_call`'s keyword arguments and document it: local/stdio callers may discover a saved token, while authenticated HTTP forwarding disables discovery. Replace `auth = token or resolve_hub_token(base)` with:

```python
    auth = (token or resolve_hub_token(base)) if discover_token else token
```

In `build_server`'s existing `hub` helper, pass `discover_token=not _OVER_HTTP.get()` along with `token=auth()`. Keep this argument when Task 41 replaces the helper. This explicit transport flag must reach the actual `hub_call`; returning `None` from `tool_hub_token` alone does not disable the client's token discovery.

Carry the same flag through the other existing forwarding path: add keyword-only `discover_token: bool = True` to both `sweep_summary` and `locate_sweep`, and document it with the same meaning as `hub_call`. In `sweep_summary`'s missing-local-sweep branch, replace credential resolution and forwarding with:

```python
        auth = (token or resolve_hub_token(url, ctx.layout.home)) if discover_token else token
        return hub_call("GET", path, url=url, token=auth, discover_token=discover_token)
```

In `locate_sweep`, pass `discover_token=discover_token` to `sweep_summary`. In the registered `get_sweep`, `cancel_sweep`, and `extend_sweep` tools, pass `discover_token=not _OVER_HTTP.get()` to their `sweep_summary` / `locate_sweep` calls. Thus both the sweep pre-read and its subsequent mutation use the caller credential only. Stdio and ordinary CLI helper calls keep the default discovery behavior. During the final baseline refresh, apply this same propagation to any new forwarding helpers added on main (including host-state lookups); audit every `token=auth()` call and every `resolve_hub_token` call reached by an HTTP tool.

2. Add after `def dump(...)`:

```python
    def agent_identity(agent: str) -> tuple[str, str | None]:
        # a session acts as agent:<agent>@<user>; the local owner keeps phase 2 values
        principal = caller()
        if principal.session_id is None:
            return f"agent:{agent}", None
        return f"agent:{agent}@{principal.user}", principal.user
```

The merged `host_states(ctx, environment_ids, *, url=None, token=None)` is another forwarding path used by `list_runs` and `get_run`. Add keyword-only `discover_token: bool = True`, documenting the same rule as `hub_call`. Replace its credential selection with:

```python
        auth = (auth or token or resolve_hub_token(url, ctx.layout.home)) if discover_token else token
```

Pass `discover_token=discover_token` to its real `hub_call`, retaining `timeout=HOST_STATE_SECONDS`. In both `list_runs` and `get_run`, pass `discover_token=not _OVER_HTTP.get()` at their `host_states` calls alongside `token=auth()`. Keep the merged host-state and untrusted-source metadata on these responses, and the task-wide remote reeval and pinned local sweep behavior.

3. Put `@scoped("read")` or `@scoped("launch")` between `@mcp.tool()` and `@_expose_errors` on every tool: `read` on `list_projects`, `list_tasks`, `get_task`, `get_leaderboard`, `list_runs`, `get_run`, `compare_runs`, `get_predictions`, `list_views`, `get_view`, `query_view`, `list_hosts`, `list_sweeps`, `get_sweep`; `launch` on `launch_run`, `rerun`, `reinfer`, `reevaluate`, `stop_run`, `add_note`, `tag_run`, `add_view`, `launch_sweep`, `cancel_sweep`, `extend_sweep`, `pull_artifact`, `connect_host`. For example:

```python
    @mcp.tool()
    @scoped("read")
    @_expose_errors
    def list_projects() -> dict[str, Any]:
```

4. In `launch_run`, replace `created_by = f"agent:{agent}"` with `created_by, owner = agent_identity(agent)`, add `"owner": owner,` to the remote `body` after `"created_by": created_by,`, add `require_local_exec(caller())  # the run executes on this machine` as the first line after the remote branch (before `record = control.launch_run(`), and add `owner=owner,` after `created_by=created_by,` in the local `RunRequest(...)`.

5. In `rerun` and `reinfer`, compute `created_by, owner = agent_identity(agent)` at the top, add `require_local_exec(caller())` after the `if out is not None: return {"run": out}` early return (a local run's child executes here), and pass `created_by=created_by, owner=owner` to `control.rerun(...)` / `control.reinfer(...)` instead of `created_by=f"agent:{agent}"`.

6. In `launch_sweep`, compute `created_by, owner = agent_identity(agent)` at the top, use `created_by` in `require_agent_hypothesis` and in the remote body (`"created_by": created_by,` plus `"owner": owner,`), add `require_local_exec(caller())` just before `summary = core_sweeps.launch_sweep(`, and pass `created_by=created_by, owner=owner` to `core_sweeps.launch_sweep(...)`. In `extend_sweep`, add `require_local_exec(caller())` just before its last line (`return dump(core_sweeps.extend_sweep(c, spec.project, spec.id, seeds))`).

7. In `add_note`, replace its body with:

```python
        writer = agent_identity(author)[0] if caller().session_id else author
        if via_hub(run_id, "notes", {"text": text, "author": writer}) is None:
            q.add_note(ctx(), run_id, text, writer)
        return {"ok": True}
```

8. In `stop_run`, check ownership before stopping a local run (a forwarded stop is checked by the hub, which sees the caller's token):

```python
        out = via_hub(run_id, "stop", {})
        if out is not None:
            return {"run": out}
        c = ctx()
        require_act(caller(), c.find_record(run_id).owner, "stop")
        return {"run": dump(control.stop_run(c, run_id))}
```

9. In `cancel_sweep`, replace the last line (`return dump(core_sweeps.cancel_queued(c, spec.project, spec.id))`) with:

```python
        require_act(caller(), spec.owner, "cancel_queued")
        return dump(core_sweeps.cancel_queued(c, spec.project, spec.id))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/mcp -v`
Expected: all scoped-tool regression cases pass; `tests/mcp/test_server.py`, `test_remote_tools.py`, and `test_remote_helpers.py` still pass (stdio and in-memory calls run as `LOCAL_OWNER`).

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check src`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/hypothex/mcp/server.py tests/mcp/test_scoped_tools.py
git commit -m "feat(mcp): per-tool scopes, caller identity over /mcp, and acting_as"
```

---

### Task 33: Nine new MCP tools

**Files:**
- Modify: `src/hypothex/mcp/server.py` (tools and `INSTRUCTIONS`)
- Modify: `tests/mcp/test_server.py` (`EXPECTED_TOOLS`), `tests/mcp/test_scoped_tools.py` (`LAUNCH_TOOLS` gains `add_notebook_entry`)
- Test: `tests/mcp/test_team_tools.py`

**Interfaces:**
- Consumes: `export_task`/`export_compare` (Task 12), `get_leaderboard`, `read_day`/`append_entry`/`today` (Task 8), `build_digest` (Task 18), `storage_report`/`plan_clean` (Tasks 20–21), the hub's storage routes (Task 31).
- Produces (contract 5, exact): `export_table(task, format="markdown", project=None, metrics=None, noise="both", digits=3) -> {text}` (read); `export_compare(run_ids, format="markdown") -> {text}` (read); `get_baselines(task, project=None) -> {baselines}` (read); `get_notebook(project, day=None) -> NotebookDay` (read); `add_notebook_entry(project, text, agent="mcp") -> NotebookDay` (launch); `get_digest(project, days=7) -> Digest` (read); `storage_report(project=None) -> StorageReport` (admin); `plan_storage_clean(older_than_days=30, kinds=None, project=None) -> CleanPlan` (admin, dry run only); `whoami() -> {user, scope}` (read).
- Rules: `storage_report` and `plan_storage_clean` ask the hub (with the caller's token) and fall back to this machine when no hub answers. No tool applies a cleanup, sends a notification, or manages users or sessions (agents never delete; skill rule 6).

- [ ] **Step 1: Write the failing test**

Create `tests/mcp/test_team_tools.py`:

```python
import asyncio
from pathlib import Path

from hypothex.auth.store import Principal
from hypothex.core.context import Context
from hypothex.core.evaluation import evaluate_run
from hypothex.mcp.server import acting_as, build_server, tool_scopes
from tests.factories import PREDS_075, seed_finished_run
from tests.mcp.test_server import call

ALICE = Principal(user="alice", scope="launch", session_id="s_00000000000a", client="cli")
NEW = {
    "export_table": "read",
    "export_compare": "read",
    "get_baselines": "read",
    "get_notebook": "read",
    "add_notebook_entry": "launch",
    "get_digest": "read",
    "storage_report": "admin",
    "plan_storage_clean": "admin",
    "whoami": "read",
}


def scored(home: Path, toy_repo: Path) -> Context:
    ctx = Context.open(home)
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    seed_finished_run(ctx, toy_repo, "r2", predictions=PREDS_075, config_hash="sha256:bbbb")
    evaluate_run(ctx, "r1")
    evaluate_run(ctx, "r2")
    return ctx


def test_new_tools_and_their_scopes(home: Path) -> None:
    scopes = tool_scopes(build_server(home))
    assert {name: scopes[name] for name in NEW} == NEW


def test_no_tool_deletes_sends_or_manages_people(home: Path) -> None:
    names = {t.name for t in asyncio.run(build_server(home).list_tools())}
    for word in ("apply", "delete", "clean_apply", "send", "notify", "user", "session"):
        assert not any(word in name for name in names), word


def test_export_tools(home: Path, toy_repo: Path) -> None:
    scored(home, toy_repo)
    err, out = call(home, "export_table", {"task": "toy-acc", "format": "latex"})
    assert not err and out["text"].startswith("% requires \\usepackage{booktabs}")
    err, out = call(home, "export_compare", {"run_ids": ["r1", "r2"]})
    assert not err and out["text"].startswith("| run | n | accuracy/value ↑ |")
    err, out = call(home, "get_baselines", {"task": "toy-acc"})
    assert not err and out == {"baselines": []}


def test_notebook_tools(home: Path, toy_repo: Path) -> None:
    scored(home, toy_repo)
    with acting_as(ALICE):
        err, day = call(
            home,
            "add_notebook_entry",
            {"project": "toy", "text": "r1 wins [[run:r1]]", "agent": "claude"},
        )
    assert not err and "— agent:claude@alice" in day["text"]
    err, again = call(home, "get_notebook", {"project": "toy", "day": day["day"]})
    assert not err and again["runs"][0]["run_id"] == "r1"
    reader = ALICE.model_copy(update={"scope": "read"})
    with acting_as(reader):
        err, message = call(home, "add_notebook_entry", {"project": "toy", "text": "x"})
    assert err and "launch scope needed" in message


def test_digest_and_whoami(home: Path, toy_repo: Path) -> None:
    scored(home, toy_repo)
    err, digest = call(home, "get_digest", {"project": "toy", "days": 7})
    assert not err and digest["counts"]["started"] == 2
    with acting_as(ALICE):
        err, me = call(home, "whoami")
    assert not err and me == {"user": "alice", "scope": "launch"}


def test_storage_tools_need_admin_and_never_apply(home: Path, toy_repo: Path) -> None:
    scored(home, toy_repo)
    with acting_as(ALICE):
        err, message = call(home, "storage_report")
    assert err and "admin scope needed" in message
    err, report = call(home, "storage_report")  # no hub answers: this machine only
    assert not err and report["errors"] == [] and report["total_bytes"] > 0
    err, plan = call(home, "plan_storage_clean", {"older_than_days": 30})
    assert not err and plan["plan_id"].startswith("cp-") and plan["items"] == []
```

In `tests/mcp/test_server.py`, add the nine names to `EXPECTED_TOOLS`:

```python
    "export_table",
    "export_compare",
    "get_baselines",
    "get_notebook",
    "add_notebook_entry",
    "get_digest",
    "storage_report",
    "plan_storage_clean",
    "whoami",
```

In `tests/mcp/test_scoped_tools.py` (Task 32), `add_notebook_entry` is a new `launch` tool, so the exact set gains it; replace `LAUNCH_TOOLS` with:

```python
LAUNCH_TOOLS = {
    "launch_run", "rerun", "reinfer", "reevaluate", "stop_run", "add_note", "tag_run",
    "add_view", "launch_sweep", "cancel_sweep", "extend_sweep", "pull_artifact",
    "add_notebook_entry", "connect_host",
}  # fmt: skip
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/mcp/test_team_tools.py tests/mcp/test_server.py -v`
Expected: FAIL: `test_new_tools_and_their_scopes` with `KeyError: 'export_table'`, the tool calls with `Unknown tool`, and `tests/mcp/test_server.py`'s tool-list test with the nine missing names.

- [ ] **Step 3: Write the tools**

In `src/hypothex/mcp/server.py`, add to the imports:

```python
from datetime import timedelta

from hypothex.core import digest as core_digest
from hypothex.core import export as core_export
from hypothex.core import notebook as core_notebook
from hypothex.core import storage as core_storage
from hypothex.core.ids import utcnow
from hypothex.core.settings import load_settings
```

append to `INSTRUCTIONS` (before the closing `"""`):

```
Team: export_table / export_compare give LaTeX, Markdown, or CSV for a paper;
get_notebook and add_notebook_entry read and write the project's lab notebook
([[run:<id>]] links show as run chips); get_digest summarizes a week; whoami.
Storage: storage_report and plan_storage_clean only show and plan; never delete.
```

and add these tools at the end of `build_server`, before `return mcp`:

```python
    @mcp.tool()
    @scoped("read")
    @_expose_errors
    def export_table(
        task: str,
        format: str = "markdown",
        project: str | None = None,
        metrics: list[str] | None = None,
        noise: str = "both",
        digits: int = 3,
    ) -> dict[str, Any]:
        """Export a task's leaderboard as LaTeX (booktabs), Markdown, or CSV for a paper."""
        opts = core_export.ExportOptions.model_validate(
            {"format": format, "metrics": metrics, "noise": noise, "digits": digits}
        )
        return {"text": core_export.export_task(ctx(), task, project, opts)}

    @mcp.tool()
    @scoped("read")
    @_expose_errors
    def export_compare(run_ids: list[str], format: str = "markdown") -> dict[str, Any]:
        """Export 2-20 runs side by side (scores at current metric versions)."""
        opts = core_export.ExportOptions.model_validate({"format": format})
        return {"text": core_export.export_compare(ctx(), run_ids, opts)}

    @mcp.tool()
    @scoped("read")
    @_expose_errors
    def get_baselines(task: str, project: str | None = None) -> dict[str, Any]:
        """Paper baselines of a task, with version match and delta to the best group."""
        board = q.get_leaderboard(ctx(), task, project, examples=False)
        return {"baselines": [dump(b) for b in board.baselines]}

    @mcp.tool()
    @scoped("read")
    @_expose_errors
    def get_notebook(project: str, day: str | None = None) -> dict[str, Any]:
        """Read one day of the project's lab notebook (default today) with run chips."""
        c = ctx()
        when = core_notebook.parse_day(day) if day else core_notebook.hub_today(c)
        return dump(core_notebook.read_day(c, project, when))

    @mcp.tool()
    @scoped("launch")
    @_expose_errors
    def add_notebook_entry(project: str, text: str, agent: str = "mcp") -> dict[str, Any]:
        """Write a finding to today's lab notebook; link runs as [[run:<id>]]."""
        author, _ = agent_identity(agent)
        return dump(core_notebook.append_entry(ctx(), project, text, author))

    @mcp.tool()
    @scoped("read")
    @_expose_errors
    def get_digest(project: str, days: int = 7) -> dict[str, Any]:
        """Summarize the last N days: runs, cost, best changes per task, notes, sweeps."""
        end = utcnow()
        top = load_settings(ctx().layout).digest.top_notes
        found = core_digest.build_digest(
            ctx(), project, since=end - timedelta(days=days), until=end, top_notes=top
        )
        return dump(found)

    @mcp.tool()
    @scoped("admin")
    @_expose_errors
    def storage_report(project: str | None = None) -> dict[str, Any]:
        """Bytes by project, host, and kind (local and on hosts). Read only."""
        path = "/api/v1/storage" + (f"?project={project}" if project else "")
        try:
            return hub("GET", path)
        except HubUnavailableError:
            return dump(core_storage.storage_report(ctx(), None, project=project))

    @mcp.tool()
    @scoped("admin")
    @_expose_errors
    def plan_storage_clean(
        older_than_days: int = 30, kinds: list[str] | None = None, project: str | None = None
    ) -> dict[str, Any]:
        """
        Dry-run a cleanup of archived, unstarred runs' artifacts. Never deletes: a human
        applies the plan with `hx storage clean --apply <plan_id>`.
        """
        policy = core_storage.CleanPolicy(
            older_than_days=older_than_days,
            kinds=kinds or ["checkpoint"],
            projects=[project] if project else None,
        )
        try:
            return hub("POST", "/api/v1/storage/plan", policy.model_dump(mode="json"))
        except HubUnavailableError:
            settings = load_settings(ctx().layout).storage
            found = core_storage.plan_clean(
                ctx(), None, policy, created_by=agent_identity("mcp")[0], settings=settings
            )
            return dump(found)

    @mcp.tool()
    @scoped("read")
    @_expose_errors
    def whoami() -> dict[str, Any]:
        """Who this agent acts as on the hub, and its scope."""
        principal = caller()
        return {"user": principal.user, "scope": principal.scope}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/mcp -v`
Expected: `tests/mcp/test_team_tools.py` `6 passed`; every other MCP test passes with the longer tool list.

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check src`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/mcp/server.py tests/mcp/test_server.py tests/mcp/test_scoped_tools.py tests/mcp/test_team_tools.py
git commit -m "feat(mcp): export, baselines, notebook, digest, storage report and plan, whoami tools"
```

---
## Part 10: Postgres server mode

Contract 1.11, 8 (failure mode 13), 9 (Docker test). The index is the only thing that moves: the event log, command receipts, `auth.db`, and every file stay under the server's home. SQLite keeps its disposable schema-version rebuild; Postgres gets Alembic.

### Task 34: Index dialects, `upsert`, `open_index`, and a 503 when the index is down

**Files:**
- Modify: `src/hypothex/core/index.py` (`Index(target, store=None, *, password=)`, `dialect`, `upsert`, `upsert_statement`, `json_text`, `open_index`, `IndexUnavailableError`, `IndexSchemaError`, `HEAD_REVISION`; every `session.merge` and `sqlite_insert` goes through `upsert`; `Index.pending`, `INDEX_PENDING_FILE`, `repair_pending`)
- Modify: `src/hypothex/core/context.py` (`Context.open` uses `open_index`, then `repair_pending`)
- Modify: `src/hypothex/api/app.py` (`environment_runs` uses `json_text`; 503 for `IndexUnavailableError` and SQLAlchemy `OperationalError`; `_repair_loop` runs `repair_pending`)
- Test: `tests/core/test_index_dialects.py`

**Interfaces:**
- Produces (contract 1.11, exact): `Index.__init__(target: Path | str, store: RunStore | None = None, *, password: SecretStr | None = None)`, `Index.dialect`, `upsert(session, model, values, keys)`, `open_index(layout, settings)`, `IndexUnavailableError` (API 503), `IndexSchemaError` (a `ConfigError`: "run hx db upgrade").
- Produces (additive): `upsert(..., *, keep_max: str | None = None)` (keeps the larger value of one column, for `set_cursor`); `upsert_statement(dialect, model, values, keys, *, keep_max=None)`; `Index.json_text(column, key)` (`json_extract` on SQLite, `json_extract_path_text` on Postgres); `HEAD_REVISION = "0001_phase3"`; `INDEX_PENDING_FILE = "index-pending.txt"`; `Index.pending: Path | None` (set by `open_index` to `<home>/index-pending.txt`); `repair_pending(index, store) -> list[str]`.
- Rebuild/recovery: preserve main `1b769f4ce9210096640a7054f5d757f09f4bb4df` generation/change markers, schema-3 parent/deferred-point/stale-score state and atomic concurrent SQLite rebuild. `Index.store` is retained on both dialects; PostgreSQL gets the explicit staged transaction below and never accesses a SQLite path. PostgreSQL mutation transactions take one exclusive advisory guard before any live DML; final swap takes the same guard, while staging and ordinary reads remain available.
- Rules: a `Path` target is SQLite exactly as before; a `postgresql+psycopg://` URL opens a pooled engine (`pool_pre_ping=True`) with the password from `server.index_password_env`, never from the URL, and checks that the Alembic revision is `HEAD_REVISION` (`IndexSchemaError` otherwise). A server that does not answer raises `IndexUnavailableError` naming the URL with `***` for any password. A Postgres URL without `psycopg` installed raises `ConfigError` "a Postgres index needs psycopg: uv tool install 'hypothex[server]'" (never a bare `ModuleNotFoundError` from SQLAlchemy). Mid-request index failures answer 503 `{error, type: "IndexUnavailableError"}`. Run files are written before the index, so a failed write leaves the index row missing (a new run: `repair_index_gaps` adds it) or stale (an archive, star, status change, or score append on an indexed run, which `repair_index_gaps` never looks at): every run write of `Index` (`upsert_run`, `add_score`, `replace_scores`, `_replace_metric_points` (public replacement and deferred hydration), `delete_run`) that fails with `OperationalError`/`InterfaceError` appends its run id to `Index.pending` (under the file's `flock`, re-opening when a repair moved the file) before re-raising, and `repair_pending` re-indexes those runs from their files (drops the ones whose folder is gone) on the next `Context.open` and every 30 s in the server's repair loop, so the index catches up once Postgres answers. The claim is recoverable: the journal is moved to `index-pending.txt.<8 hex>.claim`, every claim file (a crashed process's too) is read, and each is removed only after all its runs are indexed. Each run is re-read and indexed under its `run_lock` (the lock `Context.update_run` holds), so a repair racing an archive never writes the old value back.

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_index_dialects.py`:

```python
import sys
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

import hypothex.core.index as index_module
from hypothex.api.app import create_app
from hypothex.core.context import Context
from hypothex.core.errors import ConfigError
from hypothex.core.index import (
    HostCursorRow,
    Index,
    IndexUnavailableError,
    MetaRow,
    RunRow,
    open_index,
    repair_pending,
    upsert,
    upsert_statement,
)
from hypothex.core.layout import Layout
from hypothex.core.queries import archive_run
from hypothex.core.settings import ServerSettings, Settings, save_settings
from hypothex.core.store import run_lock
from tests.factories import make_record

DEAD_PG = "postgresql+psycopg://hx@127.0.0.1:1/hypothex"


def test_sqlite_index_is_unchanged(tmp_path: Path) -> None:
    index = Index(tmp_path / "index.db")
    assert index.dialect == "sqlite" and index.rebuilt_schema is True
    assert Index(tmp_path / "index.db").rebuilt_schema is True  # no rebuild finished yet
    index.set_meta("schema_version", str(index_module.SCHEMA_VERSION))
    assert Index(tmp_path / "index.db").rebuilt_schema is False


def test_upsert_inserts_then_updates(tmp_path: Path) -> None:
    index = Index(tmp_path / "index.db")
    with Session(index.engine) as session, session.begin():
        upsert(session, MetaRow, {"key": "k", "value": "1"}, ["key"])
        upsert(session, MetaRow, {"key": "k", "value": "2"}, ["key"])
    assert index.get_meta("k") == "2"
    index.set_cursor("gpu1", "env-a", 9)
    index.set_cursor("gpu1", "env-a", 4)  # never moves back
    assert index.get_cursor("gpu1", "env-a") == 9


def test_postgres_statements_compile(tmp_path: Path) -> None:
    stmt = upsert_statement(
        "postgresql",
        HostCursorRow,
        {"host": "gpu1", "environment_id": "e", "last_sequence": 3},
        ["host", "environment_id"],
        keep_max="last_sequence",
    )
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (host, environment_id) DO UPDATE SET last_sequence = greatest(" in sql
    lite = str(
        upsert_statement("sqlite", MetaRow, {"key": "k", "value": "v"}, ["key"]).compile(
            dialect=sqlite.dialect()
        )
    )
    assert "ON CONFLICT (key) DO UPDATE SET value = excluded.value" in lite


def test_json_text_reads_record_fields(ctx: Context) -> None:
    ctx.create_run(make_record("r1", environment_id=ctx.descriptor.environment_id))
    ended = ctx.index.json_text(RunRow.record_json, "run_id")
    with Session(ctx.index.engine) as session:
        assert session.scalars(select(ended)).all() == ["r1"]


def test_open_index_defaults_to_sqlite(tmp_path: Path) -> None:
    layout = Layout(tmp_path)
    assert open_index(layout, ServerSettings()).dialect == "sqlite"


def test_unreachable_postgres_names_the_url_without_the_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HYPOTHEX_INDEX_PASSWORD", "pw-SECRETXYZ")
    with pytest.raises(IndexUnavailableError) as info:
        open_index(Layout(tmp_path), ServerSettings(index_url=DEAD_PG))
    message = str(info.value)
    assert "127.0.0.1:1" in message and "hx@" in message and "SECRETXYZ" not in message


def test_postgres_without_psycopg_says_what_to_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "psycopg", None)  # as on an install without the extra
    with pytest.raises(ConfigError, match=r"needs psycopg: uv tool install 'hypothex\[server\]'"):
        Index(DEAD_PG)


def test_context_open_uses_config_yaml(home: Path) -> None:
    save_settings(Layout(home), Settings(server=ServerSettings(index_url=DEAD_PG)))
    with pytest.raises(IndexUnavailableError):
        Context.open(home)


def test_index_failure_mid_request_is_503(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(home, background_repair=False, hub=False, ui_dir=home / "no-ui")

    def down(*args: object, **kwargs: object) -> None:
        raise OperationalError("SELECT 1", {}, Exception("server closed the connection"))

    monkeypatch.setattr(app.state.ctx.index, "list_runs", down)
    with TestClient(app, base_url="http://127.0.0.1:7777") as client:
        resp = client.get("/api/v1/runs")
    assert resp.status_code == 503 and resp.json()["type"] == "IndexUnavailableError"


def test_a_write_that_fails_at_the_index_is_repaired_from_files(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = Context.open(home)
    ctx.create_run(make_record("r1", environment_id=ctx.descriptor.environment_id))
    real = index_module.upsert

    def down(*args: object, **kwargs: object) -> None:
        raise OperationalError("INSERT", {}, Exception("server closed the connection"))

    monkeypatch.setattr(index_module, "upsert", down)
    with pytest.raises(OperationalError):
        archive_run(ctx, "r1")  # run.yaml is archived; the indexed row is not
    monkeypatch.setattr(index_module, "upsert", real)
    stale = ctx.index.get_run("r1")
    assert ctx.find_record("r1").archived and stale is not None and not stale.archived
    reopened = Context.open(home)  # the next open, or the server's repair loop
    fresh = reopened.index.get_run("r1")
    assert fresh is not None and fresh.archived
    assert repair_pending(reopened.index, reopened.store) == []


def test_a_claim_left_by_a_crashed_repair_is_picked_up(home: Path) -> None:
    ctx = Context.open(home)
    ctx.create_run(make_record("r1", environment_id=ctx.descriptor.environment_id))
    ctx.store.write_record(ctx.find_record("r1").model_copy(update={"archived": True}))
    assert ctx.index.pending is not None
    left = ctx.index.pending.with_name(f"{ctx.index.pending.name}.deadbeef.claim")
    left.write_text("r1\n")  # moved out of the journal, then that process died
    assert repair_pending(ctx.index, ctx.store) == ["r1"]
    fresh = ctx.index.get_run("r1")
    assert fresh is not None and fresh.archived and not left.exists()


def test_repair_reads_and_indexes_under_the_run_lock(home: Path) -> None:
    ctx = Context.open(home)
    ctx.create_run(make_record("r1", environment_id=ctx.descriptor.environment_id))
    assert ctx.index.pending is not None
    ctx.index.pending.write_text("r1\n")  # an earlier write that failed at the index
    done: list[list[str]] = []
    worker = threading.Thread(target=lambda: done.append(repair_pending(ctx.index, ctx.store)))
    record = ctx.find_record("r1")
    with run_lock(ctx.run_dir(record)):  # Context.update_run archiving it, mid-write
        worker.start()
        worker.join(1)
        assert worker.is_alive() and done == []
        archived = record.model_copy(update={"archived": True})
        ctx.store.write_record(archived)
        ctx.index.upsert_run(archived)
    worker.join(30)
    fresh = ctx.index.get_run("r1")
    assert done == [["r1"]] and fresh is not None and fresh.archived  # never the old value
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_index_dialects.py -v`
Expected: FAIL at collection with `ImportError: cannot import name 'IndexUnavailableError' from 'hypothex.core.index'`.

- [ ] **Step 3: Write the implementation**

In `src/hypothex/core/index.py`:

1. Keep the merged-main imports (including `errno`, `sqlite3`, `datetime`, `TemporaryDirectory`, `TYPE_CHECKING`, `Select`, `insert`, `tuple_`, `SqlIndex`, `RunNotFoundError`, and `lttb`). Merge these additions into their existing groups:

```python
import os
import secrets
from contextlib import contextmanager
from typing import Literal, Protocol

from pydantic import SecretStr
from sqlalchemy import JSON, BigInteger, MetaData, Table, cast
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import InterfaceError, ProgrammingError

from hypothex.core.errors import ConfigError, HypothexError
from hypothex.core.layout import Layout
from hypothex.core.settings import ServerSettings, redact_url, resolve_secret
```

`sqlite_insert`, `OperationalError`, `Session`, `RunStore` and the other existing imports stay. Do not replace this module's import block with a pre-audit version.

2. After `MAX_POINTS_PER_METRIC = 1000` add:

```python
HEAD_REVISION = "0001_phase3"
"""The Alembic revision a Postgres index must be at (``hypothex.core.migrations``)."""

INDEX_PENDING_FILE = "index-pending.txt"
"""Run ids whose index write failed after their files were written (``repair_pending``)."""


class IndexUnavailableError(HypothexError):
    """The Postgres index does not answer (HTTP 503)."""


class IndexSchemaError(ConfigError):
    """The Postgres index is not at ``HEAD_REVISION``: run ``hx db upgrade``."""
```

3. Add before `class Index`:

```python
def upsert_statement(
    dialect: str,
    model: type[Base],
    values: dict[str, Any],
    keys: list[str],
    *,
    keep_max: str | None = None,
) -> Any:
    """
    Build ``INSERT ... ON CONFLICT DO UPDATE`` for SQLite or Postgres.

    Parameters
    ----------
    dialect : str
        ``sqlite`` or ``postgresql``.
    model : type
        An index table.
    values : dict
        Column values, keys included.
    keys : list of str
        The conflict target (primary key columns).
    keep_max : str, optional
        A column that keeps the larger of the stored and the new value.

    Returns
    -------
    sqlalchemy.sql.dml.Insert
        The statement.
    """
    insert = pg_insert if dialect == "postgresql" else sqlite_insert
    stmt = insert(model).values(**values)
    update: dict[str, Any] = {k: stmt.excluded[k] for k in values if k not in keys}
    if keep_max is not None:
        larger = func.greatest if dialect == "postgresql" else func.max
        update[keep_max] = larger(getattr(model, keep_max), stmt.excluded[keep_max])
    if not update:
        return stmt.on_conflict_do_nothing(index_elements=keys)
    return stmt.on_conflict_do_update(index_elements=keys, set_=update)


def upsert(
    session: Session,
    model: type[Base],
    values: dict[str, Any],
    keys: list[str],
    *,
    keep_max: str | None = None,
) -> None:
    """
    Insert a row or update it in place, atomically, on either dialect.

    Parameters
    ----------
    session : Session
        An open session (inside a transaction).
    model : type
        An index table.
    values : dict
        Column values, keys included.
    keys : list of str
        The conflict target.
    keep_max : str, optional
        A column that keeps the larger value.
    """
    _index_write_guard(session)
    dialect = session.get_bind().dialect.name
    session.execute(upsert_statement(dialect, model, values, keys, keep_max=keep_max))
```

4. Replace `Index.__init__` with:

```python
    def __init__(
        self, target: Path | str, store: RunStore | None = None, *, password: SecretStr | None = None
    ) -> None:
        self.store = store
        self.dialect: Literal["sqlite", "postgresql"]
        if isinstance(target, Path):
            self.path = target  # SQLite staging/rebuild owns a local database path
            target.parent.mkdir(parents=True, exist_ok=True)
            self.engine = create_engine(
                f"sqlite:///{target}", connect_args={"check_same_thread": False, "timeout": 10}
            )
            event.listen(self.engine, "connect", _sqlite_pragmas)
            self.dialect = "sqlite"
            self.rebuilt_schema = self._ensure_schema()
            return
        url = make_url(target)
        if password is not None:
            url = url.set(password=password.get_secret_value())
        try:
            self.engine = create_engine(url, pool_pre_ping=True, isolation_level="READ COMMITTED")
        except ImportError:
            raise ConfigError(
                "a Postgres index needs psycopg: uv tool install 'hypothex[server]'"
            ) from None
        self.dialect = "postgresql"
        self.rebuilt_schema = False  # Alembic owns the schema; never dropped here
        self._check_revision(redact_url(target))
```

   and update its docstring's Parameters to:

```
    target : Path or str
        A SQLite file, or a ``postgresql+psycopg://user@host:port/db`` URL.
    store : RunStore, optional
        Store used to fill deferred metric points after a rebuild (both dialects).
    password : SecretStr, optional
        The Postgres password (``server.index_password_env``).
```

5. Add to `Index`, after `_ensure_schema`:

```python
    def _check_revision(self, shown: str) -> None:
        try:
            with self.engine.connect() as conn:
                row = conn.execute(text("SELECT version_num FROM alembic_version")).first()
        except ProgrammingError:
            row = None  # no alembic_version table: never upgraded
        except OperationalError as exc:
            reason = type(exc.orig).__name__ if exc.orig is not None else "no answer"
            message = f"the index at {shown} does not answer ({reason})"
            raise IndexUnavailableError(message) from None
        found = row[0] if row is not None else "none"
        if found != HEAD_REVISION:
            raise IndexSchemaError(
                f"the index at {shown} is at revision {found}, not {HEAD_REVISION}; "
                "run hx db upgrade"
            )

    def json_text(self, column: Any, key: str) -> Any:
        """
        Read one top-level field of a JSON text column, as text.

        Parameters
        ----------
        column : column expression
            E.g. ``RunRow.record_json``.
        key : str
            Field name, e.g. ``ended_at``.

        Returns
        -------
        SQL expression
        """
        if self.dialect == "postgresql":
            return func.json_extract_path_text(cast(column, JSON), key)
        return func.json_extract(column, f"$.{key}")
```

6. Replace the `session.merge(ProjectRow(...))` call in `upsert_project` with:

```python
            upsert(
                session,
                ProjectRow,
                {"name": entry.project, "repo": entry.repo, "entry_json": entry.model_dump_json()},
                ["name"],
            )
```

   the current `session.merge(RunRow(**_run_values(record)))` call in `upsert_run` with:

```python
            upsert(session, RunRow, _run_values(record), ["run_id"])
```

   Keep `_touch(session, record.run_id)` before it. Task 4 adds owner to `_run_values`; the shared dictionary also retains parent and is used by staging rebuilds.

   the body of `set_meta` with:

```python
        with Session(self.engine) as session, session.begin():
            upsert(session, MetaRow, {"key": key, "value": value}, ["key"])
```

   the body of `set_cursor` (after its docstring) with:

```python
        values = {"host": host, "environment_id": environment_id, "last_sequence": last_sequence}
        keys = ["host", "environment_id"]
        with Session(self.engine) as session, session.begin():
            upsert(session, HostCursorRow, values, keys, keep_max="last_sequence")
```

   the body of `reset_cursor` (after its docstring) with:

```python
        values = {"host": host, "environment_id": environment_id, "last_sequence": 0}
        with _index_write_session(self.engine) as session:
            upsert(session, HostCursorRow, values, ["host", "environment_id"])
```

   This deliberately omits `keep_max`: a restarted event log resets its sequence to zero while retaining the identity reservation. Keep `cursor_hosts` unchanged, including zero-sequence and historical aliases. Neither cursor setter nor reset bumps generation. `_CARRIED_TABLES` retains every cursor through both rebuilds, including a reservation with no run yet.

   and the transaction line in `upsert_run`, `add_score`, `replace_scores`, `_replace_metric_points`, and `delete_run` (`with Session(self.engine) as session, session.begin():`) with

```python
        with self._journal(run_id), _index_write_session(self.engine) as session:
```

   (`record.run_id` instead of `run_id` in `upsert_run`), and add to `Index`, after `json_text`:

```python
    pending: Path | None = None
    """Where failed run writes are noted (``open_index`` sets it; None: not noted)."""

    @contextmanager
    def _journal(self, run_id: str) -> Iterator[None]:
        """Note ``run_id`` in ``pending`` when its write fails; the files hold the truth."""
        try:
            yield
        except (OperationalError, InterfaceError):
            if self.pending is not None:
                with contextlib.suppress(OSError):
                    _append_pending(self.pending, run_id)
            raise
```

7. Preserve the merged generation, change-marker and recovery code, and add a dialect-specific staged rebuild.

Every data mutation keeps its existing `_touch` at the same logical point in the transaction. After applying the explicit snippets, replace **every mutation transaction inside `Index`** from `with Session(self.engine) as session, session.begin():` to `with _index_write_session(self.engine) as session:`. For the five journalled run writes use `with self._journal(run_id), _index_write_session(self.engine) as session:` (`record.run_id` for `upsert_run`). This includes `clear`, project/run upserts, run deletion, metadata/cursor writes and reset, score marking/replacement, and metric-point replacement. Read-only sessions stay unchanged. Add `_index_write_guard(session)` as the first statement of `_touch`, before its SQL; `upsert` also invokes it above for direct callers. Reacquisition within the same transaction is allowed and never increments generation by itself. Do not wrap `_rebuild_postgres` in `_index_write_session`: its staging must remain outside the mutation guard. Convert `mark_scores_stale` to:

```python
        with _index_write_session(self.engine) as session:
            upsert(session, ScoresStaleRow, {"run_id": run_id}, ["run_id"])
```

This mark still does not bump generation. `replace_scores` still atomically deletes the stale mark and replaces scores; `Context.add_score` keeps mark → file append → full score replacement under its run lock. Keep `_DATA_TABLES`, `_CARRIED_TABLES`, `_run_values`, `_score_values`, `RunChangeRow`, `PointsPendingRow`, `ScoresStaleRow`, `_fill_pending_points`, and their current call paths.

The merged metric mutator is `_replace_metric_points(self, run_id, points, *, pending_status) -> bool`; public `replace_metric_points` only delegates with `pending_status=None`. Journal and guard the private transaction, before its pending-marker DELETE/EXISTS claim. Preserve its captured `RunRow.status`, `rowcount` check and `_touch` only after a successful claim. `_fill_pending_points` retries by re-reading pending/status outside the transaction through `points_to_index`. A lost claim changes neither data nor generation; a later successful retry is a separate write. The exclusive guard prevents pending-row/generation-row inversion against `delete_run` and final publication. Never replace either method with a pre-CAS body.

Keep `points_to_index`, `INDEXED_POINT_STATUSES`, `index_run_points`, the imported `MAX_POINTS_PER_METRIC`, and two-dimensional `_IN_CHUNK` query chunking. Live histories use bounded store reads; indexed terminal histories use full reads then downsampling. Local `_execute` publishes its terminal record before replacing metrics, retains warnings if indexing fails, and continues terminal/evaluation cleanup. `stop_run`, SLURM end/settlement, mirror installation and pending repair retain their current status-first, `points_to_index`/`index_run` paths. Rebuild staging continues to defer metrics; hydration chooses live/full from the captured indexed status and rechecks that status atomically. Keep bounded parsing specific to metrics: exact events, receipts, claims, scores and other state reads must not silently skip oversized or invalid UTF-8 records.

Host identity is also a storage invariant: retain `Hub._reserve_environment` under the claims-directory lock before any session await, cursor-zero reservation, configured/disabled/draining ownership checks, and normalization of legacy hostless claims from exactly one preexisting cursor owner before alias reservation and relabelling. Do not infer ownership from a newly connecting descriptor. Removal releases an alias only after outstanding mirrors drain. Existing claim labels and configured aliases determine routing; resetting/rebuilding the index must never let another configured host acquire the same identity. Storage Tasks 20–22 and forwarding Tasks 27–32 use the preserved `host_for_environment`/claim routing; unknown input-reader ownership remains a wildcard blocker, never a guess from project paths. Preserve `Context.local_repo` and the merged repository gate in all edited call paths; host-reported checkout paths are not local repositories.

PostgreSQL details follow the official [transaction advisory-lock documentation](https://www.postgresql.org/docs/16/explicit-locking.html#ADVISORY-LOCKS) and [temporary-table/LIKE semantics](https://www.postgresql.org/docs/16/sql-createtable.html). Those references establish primitives; the Docker regressions below must establish the assembled implementation.

Use `BigInteger` for `MetricPointRow.step`, `HostCursorRow.last_sequence`, and `RunChangeRow.generation`, and the corresponding three migration columns. These are signed-int64 values already accepted by SQLite/records/event sequences; PostgreSQL `Integer` is int32. Preserve the same 64-bit capacity for `ScoreRow.id` and `MetricPointRow.id` with `BigInteger().with_variant(Integer(), "sqlite")`, retaining `primary_key=True, autoincrement=True`. Use the equivalent `sa.BigInteger().with_variant(sa.Integer(), "sqlite")` in Alembic: PostgreSQL gets BIGSERIAL while SQLite still gets the exact INTEGER primary-key type required for rowid autoincrement. Qualify the generation target and use BIGINT casts in both constants (plain `value` in PostgreSQL's conflict-update expression is ambiguous with `excluded.value`):

```python
_BUMP_GENERATION = text(
    "INSERT INTO meta(key, value) VALUES (:key, '1') ON CONFLICT(key) "
    "DO UPDATE SET value = CAST(CAST(meta.value AS BIGINT) + 1 AS TEXT)"
).bindparams(key=GENERATION_KEY)
_MARK_RUN = text(
    "INSERT INTO run_changes(run_id, generation) "
    "SELECT :run_id, CAST(meta.value AS BIGINT) FROM meta WHERE key = :key "
    "ON CONFLICT(run_id) DO UPDATE SET generation = excluded.generation"
).bindparams(key=GENERATION_KEY)
```

Add the following helpers. The two advisory keys are fixed application-wide constants, scoped by the PostgreSQL database: one serializes rebuilds; one serializes ordinary index mutation transactions with each other and with final catch-up/swap. The latter matches SQLite's single-writer behavior; generation updates already contend on one metadata row. Readers take neither lock. Acquire the writer guard **before any live-table DML or row lock**; never acquire the rebuild-serialization key from an ordinary write transaction. Rebuild staging does not call `upsert` or `_touch` until it already holds the exclusive lock. The default engine isolation is explicitly READ COMMITTED, so the final catch-up sees every preceding writer commit.

```python
PG_REBUILD_LOCK = 0x48595801
PG_WRITE_LOCK = 0x48595802


def _index_write_guard(session: Session) -> None:
    """Serialize PostgreSQL index mutations and the final swap; SQLite is unchanged."""
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": PG_WRITE_LOCK})


@contextlib.contextmanager
def _index_write_session(engine: Engine) -> Iterator[Session]:
    """Acquire the PostgreSQL write guard before any live-table DML or row lock."""
    with Session(engine) as session, session.begin():
        _index_write_guard(session)
        yield session


class _Rows(Protocol):
    """The two staging backends share the existing row-building functions."""

    def add(self, table: str, row: dict[str, Any]) -> None: ...
    def flush(self) -> None: ...


class _PgBatch:
    """Batch writes into this transaction's temporary PostgreSQL tables."""

    def __init__(self, session: Session, tables: dict[str, Table]) -> None:
        self.session = session
        self.tables = tables
        self.rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.size = 0

    def add(self, table: str, row: dict[str, Any]) -> None:
        self.rows[table].append(row)
        self.size += 1
        if self.size >= REBUILD_BATCH:
            self.flush()

    def flush(self) -> None:
        for name, rows in self.rows.items():
            if rows:
                self.session.execute(insert(self.tables[name]), rows)
        self.rows.clear()
        self.size = 0


def _rebuild_postgres(index: Index, store: RunStore) -> int:
    """
    Stage a rebuild, then catch up changed runs and replace live data in one transaction.

    Parameters
    ----------
    index : Index
        An upgraded PostgreSQL index.
    store : RunStore
        Authoritative file store.

    Returns
    -------
    int
        Number of run rows published.

    Notes
    -----
    Concurrent readers keep seeing committed live data. Writers proceed during
    staging, then wait only for the final swap; their later commits land on the
    rebuilt index. Rebuild never takes run locks while excluding index writes:
    an ordinary writer can already hold one while waiting to index its file.
    """
    with Session(index.engine) as session, session.begin():
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": PG_REBUILD_LOCK})
        since = int(session.scalar(select(MetaRow.value).where(MetaRow.key == GENERATION_KEY)) or 0)
        tables: dict[str, Table] = {}
        metadata = MetaData()
        for model in _DATA_TABLES:
            original = Base.metadata.tables[model.__tablename__]
            name = f"hx_rebuild_{original.name}"
            # Names come only from our metadata. LIKE retains serial defaults,
            # so stage score/point ids use the live sequences (gaps are harmless).
            session.execute(
                text(
                    f'CREATE TEMPORARY TABLE "{name}" (LIKE "{original.name}" INCLUDING DEFAULTS) '
                    "ON COMMIT DROP"
                )
            )
            tables[original.name] = original.to_metadata(metadata, name=name)
        batch = _PgBatch(session, tables)
        for record in store.iter_records():
            _add_run(batch, store, record)
        batch.flush()
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": PG_WRITE_LOCK})
        changed = list(
            session.execute(
                select(RunChangeRow.run_id, RunRow.project)
                .outerjoin(RunRow, RunRow.run_id == RunChangeRow.run_id)
                .where(RunChangeRow.generation > since)
            )
        )
        for run_id, project in changed:
            for name in ("runs", "run_tags", "scores", "metric_points_pending"):
                table = tables[name]
                session.execute(delete(table).where(table.c.run_id == run_id))
            try:
                record = store.read_record(project or store.find_project_of(run_id), run_id)
            except RunNotFoundError:
                continue
            except Exception:  # noqa: BLE001 - matches SQLite's unreadable-run policy
                continue
            _add_run(batch, store, record)
        for entry in store.list_projects():
            _add_project(batch, entry)
        batch.flush()
        count = int(session.scalar(select(func.count()).select_from(tables["runs"])) or 0)
        for model in _DATA_TABLES:
            live = Base.metadata.tables[model.__tablename__]
            staged = tables[live.name]
            session.execute(delete(live))
            session.execute(insert(live).from_select(list(live.columns.keys()), select(staged)))
        # Bookkeeping tables are not rebuilt: cursors, stale-score marks and
        # run-change generations survive, including writes made during staging.
        _touch(session)
        upsert(session, MetaRow, {"key": "schema_version", "value": str(SCHEMA_VERSION)}, ["key"])
        session.execute(delete(MetaRow).where(MetaRow.key == STORE_SCAN_KEY))
        return count  # transaction commits before return; any exception rolls it all back
```

Change only the type annotation of `batch` in `_add_run` and `_add_project` from `_Batch` to `_Rows`; both implementations share the complete current row builders. Add at the top of `rebuild_index`'s body, after its docstring:

```python
    if index.dialect == "postgresql":
        return _rebuild_postgres(index, store)
```

The existing SQLite `_rebuild_lock`/`_rebuild_locked`/`_build_fresh`/`_catch_up`/`_swap_in` sequence remains verbatim. Do not route PostgreSQL through those SQLite file helpers or through `clear()` followed by a series of separately committed inserts. `rebuild_index_if_stale` is SQLite-only; its entry must reject a PostgreSQL index with `IndexSchemaError("Postgres schemas require hx db upgrade")`, avoiding any `index.path` access. Document both dialects' atomic publication and retained concurrent writes; PostgreSQL failure rolls back live changes and transaction-created staging tables, and transaction locks release on disconnect.

8. Add at the end of the module:

```python
def _append_pending(path: Path, run_id: str) -> None:
    """Add one id to the journal under its lock; follow the journal if a repair moved it."""
    for _ in range(5):
        with path.open("a") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)  # released when the file closes
            try:
                current = os.stat(path).st_ino == os.fstat(fh.fileno()).st_ino
            except FileNotFoundError:
                current = False
            if current:
                fh.write(f"{run_id}\n")
                return
        # a repair claimed the file between our open and our lock: write to the new one


def _claim_ids(path: Path) -> set[str]:
    """Read a claim file under its lock (a journal write still going in finishes first)."""
    try:
        with path.open("r") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_SH)
            text = fh.read()
    except FileNotFoundError:
        return set()
    return {s for s in (x.strip() for x in text.splitlines()) if s}


def repair_pending(index: Index, store: RunStore) -> list[str]:
    """
    Re-index the runs whose index write failed after their files were written.

    A write that reaches the run folder and then fails at the index (Postgres
    went away mid-request) leaves the row stale, not missing, so
    ``repair_index_gaps`` never sees it. ``Index`` notes those run ids in
    ``index.pending``; this re-reads each one from its files (drops it when its
    folder is gone).

    The journal is first moved to a claim file of its own,
    ``index-pending.txt.<8 hex>.claim`` (a write failing meanwhile starts a new
    journal). Then every claim file is read, those a crashed process left
    included, and each is removed only after all of its runs are indexed. A
    crash or an error at any step leaves a file the next call reads; two
    repairs at once index some runs twice, which is harmless. Each run is
    re-read and indexed under its run lock, the one ``Context.update_run``
    holds, so a repair never writes back a value older than an update that
    finished meanwhile.

    Parameters
    ----------
    index : Index
    store : RunStore
        File store, the source of truth.

    Returns
    -------
    list of str
        Run ids re-indexed or dropped, sorted.
    """
    if index.pending is None:
        return []
    journal = index.pending
    with contextlib.suppress(FileNotFoundError):
        os.replace(journal, journal.with_name(f"{journal.name}.{secrets.token_hex(4)}.claim"))
    claims = sorted(journal.parent.glob(f"{journal.name}.*.claim"))
    wanted: set[str] = set()
    for claim in claims:
        wanted |= _claim_ids(claim)
    ids = sorted(wanted)
    on_disk = store.list_run_ids() if ids else {}
    for run_id in ids:
        if run_id in on_disk:
            project = on_disk[run_id]
            with run_lock(store.layout.run_dir(project, run_id)):
                index_run(index, store, store.read_record(project, run_id))
        else:
            index.delete_run(run_id)
    for claim in claims:
        claim.unlink(missing_ok=True)
    return ids


def open_index(layout: Layout, settings: ServerSettings, store: RunStore | None = None) -> Index:
    """
    Open the index ``config.yaml`` asks for.

    Parameters
    ----------
    layout : Layout
    settings : ServerSettings
        ``index_url`` (None = SQLite ``<home>/index.db``) and ``index_password_env``.
    store : RunStore, optional
        Existing store; defaults to a store over ``layout``.

    Returns
    -------
    Index

    Raises
    ------
    IndexUnavailableError
        Postgres does not answer.
    IndexSchemaError
        Postgres is not at ``HEAD_REVISION``.
    """
    source = store if store is not None else RunStore(layout)
    if settings.index_url is None:
        index = Index(layout.index_db, store=source)
    else:
        password = resolve_secret(layout, settings.index_password_env)
        index = Index(settings.index_url, store=source, password=password)
    index.pending = layout.home / INDEX_PENDING_FILE
    return index
```

In `src/hypothex/core/context.py`, keep `Index`, `rebuild_index_if_stale`, `repair_index_if_changed`, and `repair_stale_scores` in the current grouped import; add `open_index` and `repair_pending`, plus `from hypothex.core.settings import load_settings`. Replace `index = Index(layout.index_db, store=store)` with:

```python
        index = open_index(layout, load_settings(layout).server, store=store)
```

Retain the current end of `Context.open`, adding only the pending-journal repair after stale-score repair:

```python
        if index.rebuilt_schema:
            rebuild_index_if_stale(index, store)  # SQLite: concurrent opens rebuild once
        else:
            repair_index_if_changed(index, store)
        repair_stale_scores(index, store)
        repair_pending(index, store)
        return ctx
```

Postgres never enters the automatic schema rebuild branch: an old Alembic revision is a clear `IndexSchemaError`. Explicit `rebuild_index` uses the dialect dispatch below.

and add to its docstring: "The index is SQLite unless ``server.index_url`` in ``<home>/config.yaml`` names Postgres (``IndexUnavailableError`` when it does not answer, ``IndexSchemaError`` before ``hx db upgrade``). ``config.yaml`` is read on every open, so an invalid file (``ConfigError`` naming the line) stops every ``hx`` command on this home, not only ``hx serve``: on purpose, so a typo never silently falls back to the SQLite index or to auth off."

In `src/hypothex/api/app.py`:

1. In `environment_runs`, replace `ended = func.json_extract(RunRow.record_json, "$.ended_at")` with `ended = ctx.index.json_text(RunRow.record_json, "ended_at")`.
2. Add `from hypothex.core.index import IndexUnavailableError, RunRow, repair_pending` (replacing the `RunRow` import); in `_repair_loop`, replace `await asyncio.to_thread(control.repair_runs, ctx)` with

```python
            await asyncio.to_thread(repair_pending, ctx.index, ctx.store)  # once the index is back
            await asyncio.to_thread(control.repair_runs, ctx)
```

   and after the `host_error` handler add:

```python
    @app.exception_handler(OperationalError)
    async def index_down(_: Request, exc: OperationalError) -> JSONResponse:
        # file first, index second: the run folders are written; repair indexes them later
        return JSONResponse(
            status_code=503,
            content={"error": "the index does not answer; retry", "type": "IndexUnavailableError"},
        )
```

3. In `hypothex_error`, after `elif isinstance(exc, HostUnavailableError): status = 503` add `elif isinstance(exc, IndexUnavailableError): status = 503`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_index_dialects.py tests/core/test_index.py tests/core/test_context.py -v`
Expected: `tests/core/test_index_dialects.py` `12 passed`; the phase 1–2 index and context tests still pass.

Run: `uv run pytest -q && uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check src`
Expected: every test passes; clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/index.py src/hypothex/core/context.py src/hypothex/api/app.py tests/core/test_index_dialects.py
git commit -m "feat(index): postgres dialect with portable upserts, open_index, and 503 when down"
```

---

### Task 35: Alembic migrations and `hx db upgrade|current`

**Files:**
- Create: `src/hypothex/core/migrations/__init__.py`, `env.py`, `script.py.mako`, `versions/0001_phase3.py`
- Modify: `src/hypothex/cli/main.py` (`hx db upgrade`, `hx db current`)
- Test: `tests/core/test_migrations.py`, `tests/cli/test_db_cli.py`

**Interfaces:**
- Produces (contract 1.11, exact): `alembic_config(index_url, password) -> alembic.config.Config`, `upgrade(layout, settings) -> str`, `current(layout, settings) -> str | None`; revision `0001_phase3` creates exactly `Base.metadata` at `SCHEMA_VERSION = 4` (and its `meta` row); `hx db upgrade` / `hx db current` (`ConfigError` on SQLite: "the SQLite index needs no migrations").
- Rules: the URL (with the password) is handed to `env.py` as `config.attributes["url"]`, never written into an Alembic option (no `%` interpolation, no password in text). The Alembic files ship in the wheel (they are inside `src/hypothex`). `hx db` never calls `Context.open` (that would refuse an index that is not upgraded yet).

- [ ] **Step 1: Write the failing tests**

Create `tests/core/test_migrations.py`:

```python
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from hypothex.core.errors import ConfigError
from hypothex.core.index import HEAD_REVISION, SCHEMA_VERSION, Base
from hypothex.core.layout import Layout
from hypothex.core.migrations import alembic_config, current, upgrade
from hypothex.core.settings import ServerSettings


def test_head_creates_exactly_the_models(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'migrated.db'}"
    config = alembic_config(url, None)
    assert ScriptDirectory.from_config(config).get_current_head() == HEAD_REVISION
    command.upgrade(config, "head")
    engine = create_engine(url)
    with engine.connect() as conn:
        context = MigrationContext.configure(conn, opts={"compare_type": True})
        assert compare_metadata(context, Base.metadata) == []
        version = conn.execute(text("SELECT value FROM meta WHERE key = 'schema_version'"))
        assert version.scalar() == str(SCHEMA_VERSION)
        assert (
            conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == HEAD_REVISION
        )


def test_password_never_lands_in_alembic_options() -> None:
    from pydantic import SecretStr

    config = alembic_config("postgresql+psycopg://hx@db:5432/hx", SecretStr("p%w-SECRET"))
    assert "SECRET" not in str(config.get_main_option("sqlalchemy.url"))
    assert config.attributes["url"].password == "p%w-SECRET"


def test_sqlite_needs_no_migrations(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="the SQLite index needs no migrations"):
        upgrade(Layout(tmp_path), ServerSettings())
    with pytest.raises(ConfigError, match="the SQLite index needs no migrations"):
        current(Layout(tmp_path), ServerSettings())
```

Create `tests/cli/test_db_cli.py`:

```python
from pathlib import Path

from typer.testing import CliRunner

from hypothex.cli.main import app

runner = CliRunner()


def test_db_upgrade_refuses_sqlite(home: Path) -> None:
    result = runner.invoke(app, ["db", "upgrade", "--json"])
    assert result.exit_code == 1
    assert "the SQLite index needs no migrations" in str(result.exception)


def test_db_current_refuses_sqlite(home: Path) -> None:
    result = runner.invoke(app, ["db", "current", "--json"])
    assert result.exit_code == 1 and "needs no migrations" in str(result.exception)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_migrations.py tests/cli/test_db_cli.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'hypothex.core.migrations'`.

- [ ] **Step 3: Write the migrations package**

Create `src/hypothex/core/migrations/__init__.py`:

```python
"""Alembic migrations of the Postgres index (server mode). SQLite never migrates."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import NullPool

from hypothex.core.errors import ConfigError
from hypothex.core.index import IndexUnavailableError
from hypothex.core.layout import Layout
from hypothex.core.settings import ServerSettings, redact_url, resolve_secret

SCRIPT_DIR = Path(__file__).resolve().parent
NO_MIGRATIONS = "the SQLite index needs no migrations (it rebuilds itself from files)"


def alembic_config(index_url: str, password: SecretStr | None) -> Config:
    """
    Build an Alembic config for an index URL.

    Parameters
    ----------
    index_url : str
        ``postgresql+psycopg://user@host:port/db`` (tests also pass ``sqlite:///``).
    password : SecretStr or None

    Returns
    -------
    alembic.config.Config
        ``script_location`` is this package; the URL with its password is in
        ``config.attributes["url"]`` only, never in an option.
    """
    config = Config()
    config.set_main_option("script_location", str(SCRIPT_DIR))
    url = make_url(index_url)
    if password is not None:
        url = url.set(password=password.get_secret_value())
    config.attributes["url"] = url
    return config


def _postgres(layout: Layout, settings: ServerSettings) -> Config:
    if settings.index_url is None:
        raise ConfigError(NO_MIGRATIONS)
    return alembic_config(settings.index_url, resolve_secret(layout, settings.index_password_env))


def current(layout: Layout, settings: ServerSettings) -> str | None:
    """
    Return the Postgres index's Alembic revision.

    Parameters
    ----------
    layout : Layout
    settings : ServerSettings

    Returns
    -------
    str or None
        None when the database was never upgraded.

    Raises
    ------
    ConfigError
        The index is SQLite.
    IndexUnavailableError
        Postgres does not answer.
    """
    config = _postgres(layout, settings)
    engine = create_engine(config.attributes["url"], poolclass=NullPool)
    try:
        with engine.connect() as conn:
            return MigrationContext.configure(conn).get_current_revision()
    except OperationalError:
        shown = redact_url(str(settings.index_url))
        raise IndexUnavailableError(f"the index at {shown} does not answer") from None
    finally:
        engine.dispose()


def upgrade(layout: Layout, settings: ServerSettings) -> str:
    """
    Upgrade the Postgres index to the newest revision.

    Parameters
    ----------
    layout : Layout
    settings : ServerSettings

    Returns
    -------
    str
        The revision after the upgrade.

    Raises
    ------
    ConfigError
        The index is SQLite.
    IndexUnavailableError
        Postgres does not answer.
    """
    config = _postgres(layout, settings)
    try:
        command.upgrade(config, "head")
    except OperationalError:
        shown = redact_url(str(settings.index_url))
        raise IndexUnavailableError(f"the index at {shown} does not answer") from None
    found = current(layout, settings)
    assert found is not None
    return found
```

Create `src/hypothex/core/migrations/env.py`:

```python
"""Alembic environment: one online connection; the URL comes from ``config.attributes``."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from hypothex.core.index import Base

config = context.config


def run_migrations_online() -> None:
    """Run the migrations over a connection to ``config.attributes["url"]``."""
    engine = create_engine(config.attributes["url"], poolclass=NullPool)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection, target_metadata=Base.metadata, compare_type=True
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("offline migrations are not supported; run hx db upgrade")
run_migrations_online()
```

Create `src/hypothex/core/migrations/script.py.mako`:

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

${imports if imports else ""}
revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

Create `src/hypothex/core/migrations/versions/0001_phase3.py`:

```python
"""phase 3: the whole index at SCHEMA_VERSION 4

Revision ID: 0001_phase3
Revises:
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_phase3"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create every index table, with the indexes the models declare."""
    meta = op.create_table(
        "meta",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("value", sa.String(), nullable=False),
    )
    op.create_table(
        "projects",
        sa.Column("name", sa.String(), primary_key=True),
        sa.Column("repo", sa.String(), nullable=False),
        sa.Column("entry_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "datasets",
        sa.Column("project", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), primary_key=True),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("host", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
    )
    op.create_table(
        "metrics",
        sa.Column("project", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), primary_key=True),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("fn", sa.String(), nullable=False),
        sa.Column("higher_is_better", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "tasks",
        sa.Column("project", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), primary_key=True),
        sa.Column("dataset", sa.String(), nullable=False),
        sa.Column("split", sa.String(), nullable=True),
        sa.Column("primary", sa.String(), nullable=False),
        sa.Column("metrics_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "runs",
        sa.Column("run_id", sa.String(), primary_key=True),
        sa.Column("project", sa.String(), nullable=False),
        sa.Column("task", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("config_hash", sa.String(), nullable=False),
        sa.Column("commit", sa.String(), nullable=True),
        sa.Column("environment_id", sa.String(), nullable=False),
        sa.Column("parent", sa.String(), nullable=True),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("starred", sa.Boolean(), nullable=False),
        sa.Column("owner", sa.String(), nullable=True),
        sa.Column("record_json", sa.Text(), nullable=False),
    )
    for column in ("project", "task", "status", "created_at", "parent", "owner"):
        op.create_index(f"ix_runs_{column}", "runs", [column])
    op.create_table(
        "run_tags",
        sa.Column("run_id", sa.String(), primary_key=True),
        sa.Column("tag", sa.String(), primary_key=True),
    )
    op.create_index("ix_run_tags_tag", "run_tags", ["tag"])
    op.create_table(
        "scores",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("record_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("ix_scores_run_id", "scores", ["run_id"])
    op.create_table(
        "metric_points",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("step", sa.BigInteger(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("t", sa.Float(), nullable=True),
    )
    op.create_index("ix_metric_points_run_name_step", "metric_points", ["run_id", "name", "step"])
    op.create_table(
        "host_cursors",
        sa.Column("host", sa.String(), primary_key=True),
        sa.Column("environment_id", sa.String(), primary_key=True),
        sa.Column("last_sequence", sa.BigInteger(), nullable=False),
    )
    op.create_table(
        "run_changes",
        sa.Column("run_id", sa.String(), primary_key=True),
        sa.Column("generation", sa.BigInteger(), nullable=False),
    )
    for name in ("metric_points_pending", "scores_stale"):
        op.create_table(name, sa.Column("run_id", sa.String(), primary_key=True))
    op.bulk_insert(meta, [{"key": "schema_version", "value": "4"}])


def downgrade() -> None:
    """Drop every index table."""
    for table in (
        "scores_stale", "metric_points_pending", "run_changes", "host_cursors",
        "metric_points", "scores", "run_tags", "runs", "tasks", "metrics",
        "datasets", "projects", "meta",
    ):  # fmt: skip
        op.drop_table(table)
```

- [ ] **Step 4: Add `hx db`**

In `src/hypothex/cli/main.py`, after the `hosts_app` block add:

```python
db_app = typer.Typer(no_args_is_help=True, help="The Postgres index (server mode).")
app.add_typer(db_app, name="db")
```

and add the commands (next to `reindex`):

```python
@db_app.command("upgrade")
def db_upgrade(as_json: JsonFlag = False) -> None:
    """Upgrade the Postgres index to the newest schema (never needed for SQLite)."""
    from hypothex.core.migrations import upgrade
    from hypothex.core.settings import load_settings

    layout = Layout(_home_path())
    revision = upgrade(layout, load_settings(layout).server)
    _emit({"revision": revision}, as_json, f"index at {revision}")


@db_app.command("current")
def db_current(as_json: JsonFlag = False) -> None:
    """Show the Postgres index's schema revision."""
    from hypothex.core.migrations import current
    from hypothex.core.settings import load_settings

    layout = Layout(_home_path())
    revision = current(layout, load_settings(layout).server)
    _emit({"revision": revision}, as_json, revision or "none")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_migrations.py tests/cli/test_db_cli.py -v`
Expected: `tests/core/test_migrations.py` `3 passed`, `tests/cli/test_db_cli.py` `2 passed`.

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check src && uv build --wheel && unzip -l dist/hypothex-*.whl | grep -c "hypothex/core/migrations/"`
Expected: clean; the wheel builds into `dist/` (git-ignored); the last command prints `4` (`__init__.py`, `env.py`, `script.py.mako`, and `versions/0001_phase3.py` ship in the wheel).

- [ ] **Step 6: Commit**

```bash
git add src/hypothex/core/migrations src/hypothex/cli/main.py tests/core/test_migrations.py tests/cli/test_db_cli.py
git commit -m "feat(index): alembic migrations for the postgres index and hx db upgrade|current"
```

---

### Task 36: Postgres in Docker — upgrade, live vs rebuilt index, concurrent upserts

**Files:**
- Test: `tests/docker/test_postgres_index.py`

**Interfaces:**
- Consumes: `run_cmd`, `free_port`, `wait_until` (`tests/docker/conftest.py`, phase 2), `upgrade`/`current` (Task 35), `open_index` (Task 34), `rebuild_index`.
- Produces: contract 9's Docker test (marker `docker`): a throwaway `postgres:16-alpine` on a random 127.0.0.1 port with a random password; `hx db upgrade`, then `Context.open` works; the index built live equals the index rebuilt from files, and equals SQLite's answers for the same store; concurrent `upsert_run`/`set_cursor` from 8 threads never fail and the cursor ends at the maximum; `Context.open` before the upgrade raises `IndexSchemaError`.

- [ ] **Step 1: Write the test**

Create `tests/docker/test_postgres_index.py`:

```python
import secrets
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from hypothex.core.settings import ServerSettings, Settings, save_settings
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from typer.testing import CliRunner

import hypothex.core.index as index_module
from hypothex.cli.main import app
from hypothex.core.context import Context
from hypothex.core.fsutil import append_jsonl
from hypothex.core.ids import utcnow
from hypothex.core.index import Index, IndexSchemaError, rebuild_index
from hypothex.core.layout import Layout
from hypothex.core.records import MetricPoint, RunRecord, RunStatus, ScoreRecord
from hypothex.core.store import RunStore
from tests.docker.conftest import free_port, run_cmd, wait_until
from tests.factories import make_record, write_toy_project

pytestmark = pytest.mark.docker
IMAGE = "postgres:16-alpine"


def connect(port: int, password: str, dbname: str = "hypothex") -> object:
    import psycopg

    return psycopg.connect(
        host="127.0.0.1", port=port, user="hx", password=password, dbname=dbname, autocommit=True
    )


@pytest.fixture(scope="module")
def postgres() -> Iterator[tuple[int, str]]:
    """A throwaway Postgres on a random loopback port with a random password."""
    port = free_port()
    password = secrets.token_hex(12)
    name = f"hx-test-pg-{secrets.token_hex(4)}"
    run_cmd(
        [
            "docker", "run", "-d", "--rm", "--name", name, "-e", f"POSTGRES_PASSWORD={password}",
            "-e", "POSTGRES_USER=hx", "-e", "POSTGRES_DB=hypothex", "-p", f"127.0.0.1:{port}:5432",
            IMAGE,
        ]
    )  # fmt: skip
    try:
        wait_until(
            lambda: connect(port, password).close() or True,  # type: ignore[attr-defined]
            timeout=120,
            what="postgres to accept connections",
        )
        yield port, password
    finally:
        run_cmd(["docker", "rm", "-f", name], check=False)


@pytest.fixture
def pg_home(tmp_path: Path, postgres: tuple[int, str], monkeypatch: pytest.MonkeyPatch) -> Path:
    """A home whose config.yaml points at a fresh database of the container."""
    port, password = postgres
    dbname = f"hx_{secrets.token_hex(4)}"
    with connect(port, password) as conn:  # type: ignore[attr-defined]
        conn.execute(f"CREATE DATABASE {dbname}")
    home = tmp_path / "hxhome"
    home.mkdir()
    monkeypatch.setenv("HYPOTHEX_HOME", str(home))
    monkeypatch.setenv("HYPOTHEX_INDEX_PASSWORD", password)
    url = f"postgresql+psycopg://hx@127.0.0.1:{port}/{dbname}"
    save_settings(Layout(home), Settings(server=ServerSettings(index_url=url)))
    return home


def snapshot(index: Index) -> dict[str, object]:
    runs = index.list_runs(include_archived=True, limit=None)
    ids = sorted(r.run_id for r in runs)
    scores = index.scores_for(ids)
    return {
        "projects": [p.project for p in index.list_projects()],
        "runs": sorted(r.model_dump_json() for r in runs),
        "scores": {k: [s.model_dump_json() for s in v] for k, v in sorted(scores.items())},
        "owners": sorted(r.run_id for r in index.list_runs(owner="alice", limit=None)),
    }


def test_upgrade_then_live_index_equals_rebuilt_and_sqlite(pg_home: Path, tmp_path: Path) -> None:
    with pytest.raises(IndexSchemaError, match="run hx db upgrade"):
        Context.open(pg_home)
    result = CliRunner().invoke(app, ["db", "upgrade", "--json"], catch_exceptions=False)
    assert result.exit_code == 0 and '"revision": "0001_phase3"' in result.stdout
    ctx = Context.open(pg_home)
    assert ctx.index.dialect == "postgresql"
    ctx.register_project(write_toy_project(tmp_path / "toy"))
    for i in range(12):
        record = make_record(
            f"r{i:02d}",
            status=RunStatus.FINISHED,
            owner="alice" if i % 3 == 0 else "sv",
            environment_id=ctx.descriptor.environment_id,
        )
        ctx.create_run(record)
        value = i / 12
        score = ScoreRecord(
            metric="accuracy", version="v1", key="value", value=value, created_at=utcnow()
        )
        ctx.add_score(record, score)
    live = snapshot(ctx.index)
    rebuild_index(ctx.index, ctx.store)
    assert snapshot(ctx.index) == live
    lite = Index(tmp_path / "sqlite.db", store=ctx.store)
    rebuild_index(lite, ctx.store)
    assert snapshot(lite) == live


def test_concurrent_upserts_never_fail(pg_home: Path) -> None:
    CliRunner().invoke(app, ["db", "upgrade"], catch_exceptions=False)
    ctx = Context.open(pg_home)
    record = make_record("same", environment_id=ctx.descriptor.environment_id)
    errors: list[BaseException] = []

    def work(n: int) -> None:
        try:
            for step in range(20):
                ctx.index.upsert_run(record.model_copy(update={"hypothesis": f"{n}-{step}"}))
                ctx.index.set_cursor("gpu1", "env-a", n * 100 + step)
        except BaseException as exc:  # noqa: BLE001 - collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert ctx.index.get_cursor("gpu1", "env-a") == 7 * 100 + 19
    assert [r.run_id for r in ctx.index.list_runs(include_archived=True)] == ["same"]


class PausedStore(RunStore):
    """Pause once after the first staged row; no lock is held by the hook."""

    def __init__(self, layout: Layout, hook: Callable[[], None]) -> None:
        super().__init__(layout)
        self.hook = hook
        self.points_read = 0

    def iter_records(self, project: str | None = None) -> Iterator[RunRecord]:
        for i, record in enumerate(super().iter_records(project)):
            yield record
            if i == 0:
                self.hook()

    def read_metric_points(self, project: str, run_id: str) -> list[MetricPoint]:
        self.points_read += 1
        return super().read_metric_points(project, run_id)


def ready_context(pg_home: Path) -> Context:
    result = CliRunner().invoke(app, ["db", "upgrade"], catch_exceptions=False)
    assert result.exit_code == 0
    ctx = Context.open(pg_home)
    for rid in ("r0", "r1", "r2"):
        ctx.create_run(make_record(rid, status=RunStatus.FINISHED, owner="alice"))
        append_jsonl(
            ctx.layout.run_dir("toy", rid) / "metrics.jsonl",
            {"name": "loss", "step": 0, "value": 1.0},
        )
    return ctx


def test_int64_steps_cursors_and_generation_round_trip(pg_home: Path) -> None:
    ctx = ready_context(pg_home)
    step = 2**63 - 1
    ctx.index.replace_metric_points("r0", [MetricPoint(name="loss", step=step, value=0.5)])
    assert ctx.index.metric_points("r0")[0].step == step
    append_jsonl(
        ctx.layout.run_dir("toy", "r0") / "metrics.jsonl",
        {"name": "loss", "step": step, "value": 0.5},
    )
    ctx.index.set_cursor("gpu1", "env-a", step)
    assert ctx.index.get_cursor("gpu1", "env-a") == step
    ctx.index.set_meta(index_module.GENERATION_KEY, str(2**31 - 1))
    ctx.index.upsert_run(ctx.find_record("r0"))  # exercises existing-key conflict RHS
    assert ctx.index.generation() == 2**31
    with Session(ctx.index.engine) as session:
        assert (
            session.scalar(
                select(index_module.RunChangeRow.generation).where(
                    index_module.RunChangeRow.run_id == "r0"
                )
            )
            == 2**31
        )
    rebuild_index(ctx.index, ctx.store)
    assert ctx.index.get_cursor("gpu1", "env-a") == step
    assert max(p.step for p in ctx.index.metric_points("r0")) == step  # lazy hydration too

    # The index's generated row ids also retain SQLite's int64 capacity.
    with Session(ctx.index.engine) as session, session.begin():
        for table in ("scores", "metric_points"):
            session.execute(
                index_module.text(
                    "SELECT setval(pg_get_serial_sequence(:table, 'id')::regclass, :value, true)"
                ),
                {"table": table, "value": 2**31},
            )
    score = ScoreRecord(metric="acc", version="v1", key="value", value=0.7, created_at=utcnow())
    ctx.add_score(ctx.find_record("r0"), score)
    ctx.index.replace_metric_points("r0", [MetricPoint(name="loss", step=step, value=0.5)])
    with Session(ctx.index.engine) as session:
        assert (
            session.scalar(
                select(index_module.ScoreRow.id).where(index_module.ScoreRow.run_id == "r0")
            )
            > 2**31
        )
        assert (
            session.scalar(
                select(index_module.MetricPointRow.id).where(
                    index_module.MetricPointRow.run_id == "r0"
                )
            )
            > 2**31
        )


def test_rebuild_keeps_readers_writes_markers_and_deferred_points(pg_home: Path) -> None:
    ctx = ready_context(pg_home)
    before = snapshot(ctx.index)
    generation = ctx.index.generation()
    ctx.index.set_cursor("gpu1", "env-a", 9)
    score = ScoreRecord(metric="acc", version="v1", key="value", value=0.8, created_at=utcnow())
    writer_errors: list[BaseException] = []

    def changed_during_scan() -> None:
        # A separate session sees the complete old index, not staging rows.
        assert snapshot(ctx.index) == before

        def write() -> None:
            try:
                ctx.update_run(
                    "r0",
                    "run.tagged",
                    lambda r: r.model_copy(
                        update={"tags": ["late"], "parent": "r2", "owner": "sv"}
                    ),
                )
                ctx.add_score(ctx.find_record("r0"), score)
                ctx.create_run(make_record("late", owner="alice", parent="r0"))
                ctx.index.set_cursor("gpu1", "env-a", 12)
                ctx.index.mark_scores_stale("r2")
                ctx.store.append_score("toy", "r2", score)  # simulate a cut-short add
            except BaseException as exc:  # noqa: BLE001 - asserted in test thread
                writer_errors.append(exc)

        worker = threading.Thread(target=write, daemon=True)
        worker.start()
        worker.join(10)
        assert not worker.is_alive(), "staging must not exclude ordinary writers"
        assert writer_errors == []

    staged = PausedStore(ctx.layout, changed_during_scan)
    ctx.index.store = staged
    assert rebuild_index(ctx.index, staged) == 4
    assert staged.points_read == 0  # neither dialect reads metric files while rebuilding
    assert ctx.index.get_cursor("gpu1", "env-a") == 12
    assert ctx.index.generation() > generation
    assert ctx.index.stale_score_runs() == ["r2"]
    with Session(ctx.index.engine) as session:
        assert session.execute(
            select(index_module.RunRow.owner, index_module.RunRow.parent).where(
                index_module.RunRow.run_id == "r0"
            )
        ).one() == ("sv", "r2")
        assert (
            session.scalar(
                select(index_module.RunChangeRow.generation).where(
                    index_module.RunChangeRow.run_id == "r0"
                )
            )
            is not None
        )
    current = ctx.index.get_run("r0")
    assert current is not None and current.tags == ["late"]
    assert ctx.index.scores_for(["r0"])["r0"] == [score]
    assert [(p.name, p.step) for p in ctx.index.metric_points("r0")] == [("loss", 0)]
    assert staged.points_read == 1
    ctx.index.metric_points("r0")
    assert staged.points_read == 1
    reopened = Context.open(pg_home)
    assert reopened.index.store is reopened.store
    assert reopened.index.stale_score_runs() == []
    assert reopened.index.scores_for(["r2"])["r2"] == [score]  # repaired exactly once


def test_failure_after_live_replacement_rolls_back_everything(
    pg_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = ready_context(pg_home)
    before = snapshot(ctx.index)
    generation = ctx.index.generation()
    real = index_module._touch

    def fail_publish(session: Session, *run_ids: str) -> None:
        if not run_ids:
            # Rebuild invokes _touch after DELETE/INSERT, before commit. Other
            # sessions still see the old index even at this final boundary.
            assert snapshot(ctx.index) == before
            raise RuntimeError("publication interrupted")
        real(session, *run_ids)

    monkeypatch.setattr(index_module, "_touch", fail_publish)
    with pytest.raises(RuntimeError, match="publication interrupted"):
        rebuild_index(ctx.index, ctx.store)
    assert snapshot(ctx.index) == before and ctx.index.generation() == generation
    monkeypatch.setattr(index_module, "_touch", real)
    assert rebuild_index(ctx.index, ctx.store) == 3  # locks/staging released after failure


def test_a_writer_waits_for_final_swap_then_commits_after_it(pg_home: Path) -> None:
    ctx = ready_context(pg_home)
    entered = threading.Event()
    done = threading.Event()
    errors: list[BaseException] = []

    def writer() -> None:
        entered.set()
        try:
            ctx.update_run("r0", "run.tagged", lambda r: r.model_copy(update={"tags": ["after"]}))
        except BaseException as exc:  # noqa: BLE001 - asserted below
            errors.append(exc)
        finally:
            done.set()

    with Session(ctx.index.engine) as session, session.begin():
        session.execute(
            index_module.text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": index_module.PG_WRITE_LOCK},
        )
        worker = threading.Thread(target=writer, daemon=True)
        worker.start()
        assert entered.wait(5)
        wait_until(
            lambda: ctx.store.read_record("toy", "r0").tags == ["after"],
            timeout=5,
            what="writer to reach its index update",
        )
        assert not done.is_set()
        # Ordinary reads do not acquire the write guard.
        assert ctx.index.count_runs(include_archived=True) == 3
    worker.join(10)
    assert done.is_set() and not worker.is_alive() and errors == []
    current = ctx.index.get_run("r0")
    assert current is not None and current.tags == ["after"]


def test_concurrent_rebuilds_keep_writes_and_use_separate_staging(pg_home: Path) -> None:
    ctx = ready_context(pg_home)
    first_paused, release, second_scanned = threading.Event(), threading.Event(), threading.Event()
    errors: list[BaseException] = []

    def pause() -> None:
        first_paused.set()
        assert release.wait(10)

    def rebuild(store: RunStore) -> None:
        try:
            rebuild_index(ctx.index, store)
        except BaseException as exc:  # noqa: BLE001 - asserted after both joins
            errors.append(exc)

    first = threading.Thread(target=rebuild, args=(PausedStore(ctx.layout, pause),), daemon=True)
    second = threading.Thread(
        target=rebuild, args=(PausedStore(ctx.layout, second_scanned.set),), daemon=True
    )
    first.start()
    try:
        assert first_paused.wait(5)
        second.start()
        assert not second_scanned.wait(0.1)  # waits on rebuild lock, not the write guard
        ctx.update_run("r0", "run.tagged", lambda r: r.model_copy(update={"tags": ["kept"]}))
    finally:
        release.set()
        first.join(10)
        if second.ident is not None:
            second.join(10)
    assert not first.is_alive() and not second.is_alive() and errors == []
    assert second_scanned.is_set()
    current = ctx.index.get_run("r0")
    assert current is not None and current.tags == ["kept"]


def test_cursor_reset_keeps_empty_identity_across_rebuild(pg_home: Path) -> None:
    ctx = ready_context(pg_home)
    generation = ctx.index.generation()
    ctx.index.set_cursor("reserved-only", "env-empty", 0)
    ctx.index.set_cursor("gpu1", "env-a", 9)
    ctx.index.reset_cursor("gpu1", "env-a")
    assert ctx.index.get_cursor("gpu1", "env-a") == 0
    assert ctx.index.cursor_hosts("env-a") == ["gpu1"]
    assert ctx.index.generation() == generation
    rebuild_index(ctx.index, ctx.store)
    reopened = Context.open(pg_home)
    assert reopened.index.cursor_hosts("env-empty") == ["reserved-only"]
    assert reopened.index.cursor_hosts("env-a") == ["gpu1"]
    assert reopened.index.get_cursor("gpu1", "env-a") == 0


def test_pending_hydration_cannot_resurrect_deleted_run(
    pg_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = ready_context(pg_home)
    rebuild_index(ctx.index, ctx.store)
    captured, resume = threading.Event(), threading.Event()
    errors: list[BaseException] = []
    result: list[list[MetricPoint]] = []
    real_read = index_module.points_to_index

    def paused_read(
        store: RunStore, project: str, run_id: str, status: RunStatus | str
    ) -> list[MetricPoint]:
        points = real_read(store, project, run_id, status)
        captured.set()
        assert resume.wait(10)
        return points

    def hydrate() -> None:
        try:
            result.append(ctx.index.metric_points("r0"))
        except BaseException as exc:  # noqa: BLE001 - asserted after join
            errors.append(exc)

    monkeypatch.setattr(index_module, "points_to_index", paused_read)
    worker = threading.Thread(target=hydrate, daemon=True)
    worker.start()
    try:
        assert captured.wait(5)
        ctx.index.delete_run("r0")
        published_generation = ctx.index.generation()
    finally:
        resume.set()
        worker.join(10)
    assert not worker.is_alive() and errors == []
    assert result == [[]] and ctx.index.get_run("r0") is None
    assert ctx.index.generation() == published_generation
    with Session(ctx.index.engine) as session:
        assert (
            session.scalar(
                select(index_module.PointsPendingRow.run_id).where(
                    index_module.PointsPendingRow.run_id == "r0"
                )
            )
            is None
        )


def test_pending_hydration_waits_for_swap_and_retries_terminal_status(
    pg_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = ready_context(pg_home)
    ctx.update_run(
        "r0", "run.running", lambda r: r.model_copy(update={"status": RunStatus.RUNNING})
    )
    rebuild_index(ctx.index, ctx.store)
    captured, resume_read = threading.Event(), threading.Event()
    swap_holds_guard, release_swap = threading.Event(), threading.Event()
    hydration_at_guard, hydrated = threading.Event(), threading.Event()
    errors: list[BaseException] = []
    claims: list[tuple[bool, int, int]] = []
    claim_before: list[int] = []
    result: list[list[MetricPoint]] = []
    real_read, real_touch = index_module.points_to_index, index_module._touch
    real_guard, real_replace = index_module._index_write_guard, ctx.index._replace_metric_points
    expected = [
        MetricPoint(name="loss", step=0, value=1.0),
        MetricPoint(name="loss", step=1, value=0.25),
    ]

    def paused_read(
        store: RunStore, project: str, run_id: str, status: RunStatus | str
    ) -> list[MetricPoint]:
        points = real_read(store, project, run_id, status)
        if threading.current_thread().name == "hydration" and not captured.is_set():
            captured.set()
            assert resume_read.wait(10)
        return points

    def guarded(session: Session) -> None:
        if threading.current_thread().name == "hydration":
            hydration_at_guard.set()
        real_guard(session)
        if threading.current_thread().name == "hydration" and not claim_before:
            claim_before.append(ctx.index.generation())

    def publish(session: Session, *run_ids: str) -> None:
        if threading.current_thread().name == "publication" and not run_ids:
            swap_holds_guard.set()  # DELETE/INSERT already ran under PG_WRITE_LOCK
            assert release_swap.wait(10)
        real_touch(session, *run_ids)

    def replace(run_id: str, points: list[MetricPoint], *, pending_status: str | None) -> bool:
        if threading.current_thread().name == "hydration":
            claim_before.clear()
            accepted = real_replace(run_id, points, pending_status=pending_status)
            # captured by the actual transaction guard, after publication commits
            assert len(claim_before) == 1
            claims.append((accepted, claim_before[0], ctx.index.generation()))
            return accepted
        return real_replace(run_id, points, pending_status=pending_status)

    def hydrate() -> None:
        try:
            result.append(ctx.index.metric_points("r0"))
        except BaseException as exc:  # noqa: BLE001 - asserted after join
            errors.append(exc)
        finally:
            hydrated.set()

    def rebuild() -> None:
        try:
            rebuild_index(ctx.index, ctx.store)
        except BaseException as exc:  # noqa: BLE001 - asserted after join
            errors.append(exc)

    monkeypatch.setattr(index_module, "points_to_index", paused_read)
    monkeypatch.setattr(index_module, "_index_write_guard", guarded)
    monkeypatch.setattr(index_module, "_touch", publish)
    monkeypatch.setattr(ctx.index, "_replace_metric_points", replace)
    worker = threading.Thread(target=hydrate, name="hydration", daemon=True)
    publisher = threading.Thread(target=rebuild, name="publication", daemon=True)
    worker.start()
    try:
        assert captured.wait(5)
        append_jsonl(ctx.layout.run_dir("toy", "r0") / "metrics.jsonl", expected[-1].model_dump())
        ctx.update_run(
            "r0", "run.finished", lambda r: r.model_copy(update={"status": RunStatus.FINISHED})
        )
        ctx.index.replace_metric_points("r0", expected)
        publisher.start()
        assert swap_holds_guard.wait(5)
        resume_read.set()
        assert hydration_at_guard.wait(5)
        assert not hydrated.is_set()
    finally:
        release_swap.set()
        resume_read.set()
        worker.join(10)
        if publisher.ident is not None:
            publisher.join(10)
    assert not worker.is_alive() and not publisher.is_alive() and errors == []
    assert result == [expected]
    assert len(claims) == 2 and [accepted for accepted, _, _ in claims] == [False, True]
    assert claims[0][1] == claims[0][2]  # failed status CAS did not bump generation
    assert claims[1][2] == claims[1][1] + 1


def test_failed_deferred_hydration_is_journalled_and_repaired(
    pg_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = ready_context(pg_home)
    rebuild_index(ctx.index, ctx.store)
    real_guard = index_module._index_write_guard

    def unavailable(session: Session) -> None:
        raise OperationalError("SELECT pg_advisory_xact_lock", {}, RuntimeError("offline"))

    monkeypatch.setattr(index_module, "_index_write_guard", unavailable)
    with pytest.raises(OperationalError):
        ctx.index.metric_points("r0")
    assert ctx.index.pending is not None
    assert ctx.index.pending.read_text().splitlines() == ["r0"]
    monkeypatch.setattr(index_module, "_index_write_guard", real_guard)
    assert index_module.repair_pending(ctx.index, ctx.store) == ["r0"]
    assert ctx.index.metric_points("r0") == [MetricPoint(name="loss", step=0, value=1.0)]
    assert not ctx.index.pending.exists()
    assert list(ctx.layout.home.glob("index-pending.txt.*.claim")) == []
```

- [ ] **Step 2: Run the test**

The concrete hydration tests above require real PostgreSQL: a pending reader cannot resurrect a deleted row, waits before live DML while final publication holds the writer guard, rejects a recreated pending marker when its captured status is old, retries terminal history, and journals failed hydration for repair. All worker joins are bounded and errors propagated. A lost claim cannot bump generation; a successful retry increments it once. The cursor test covers zero reservations without any run, explicit reset and rebuild/reopen preservation.

Retain and run the existing SQLite `tests/core/test_index_rebuild.py` regressions and `tests/core/test_index.py::test_pending_live_metric_read_keeps_a_newer_terminal_index` as part of Task 34. Keep the terminal-ordering and failure-warning tests in `tests/core/test_execution.py`, fallback-stop tests in `tests/core/test_control.py`, and SLURM terminal-metric tests. Retain `tests/remote/test_identity.py` and cursor/rebuild tests to verify concurrent reservations, disabled and draining owners, crash-restart alias normalization, and hostless-claim failures. `tests/core/test_index_rebuild_overlap.py` is currently a step-6 integration artifact, not part of this pinned merged baseline; add it to required checks if that final merge retains it. The Docker cases below are required in addition; SQL compilation or an extracted fake-session probe cannot establish PostgreSQL lock, sequence or MVCC behavior.

Run: `uv run pytest -m docker tests/docker/test_postgres_index.py -v`
Expected: all PostgreSQL upgrade/rebuild/concurrency tests pass with Docker running (the tests are skipped without Docker, and an error with `HYPOTHEX_REQUIRE_DOCKER=1`). The network guard allows the test: Postgres listens on `127.0.0.1`.

Run: `uv run pytest -q` (without `-m docker`)
Expected: the Docker tests are deselected; everything else passes.

- [ ] **Step 3: Commit**

```bash
git add tests/docker/test_postgres_index.py
git commit -m "test(docker): postgres index upgrade, rebuild equivalence, and concurrent upserts"
```

---
## Part 11: Tailscale, paired `route: url` hosts, and `hx serve` with auth

Contract 1.13, 1.10 (`hx serve` with auth), 7 (network), 8 (failure modes 14, 17). Tailscale only terminates HTTPS (`tailscale serve`); there is no relay. A lab server is an env server with auth on; the hub holds a paired `host` session for it (or a token from `token_env`).

### Task 37: Fake `tailscale` and `hypothex.remote.tailscale`

**Files:**
- Create: `tests/fakes/fake_tailscale.py`
- Modify: `tests/fakes/__init__.py` (`install_fake_tailscale`, `FakeTailscale`)
- Create: `src/hypothex/remote/tailscale.py`
- Test: `tests/remote/test_tailscale.py`

**Interfaces:**
- Produces (contract 1.13, exact): `TailscaleError`, `tailscale_bin()`, `tailscale_dns_name(*, timeout=10)`, `serve_https(port, *, https_port=443)`, `unserve(https_port=443)`.
- Produces (tests only, contract 9): `tests/fakes/fake_tailscale.py` (state in `HYPOTHEX_FAKE_TAILSCALE_STATE`: `{logged_in, dns_name, serve: {https_port: target}, calls: [argv]}`; `status --json`, `serve --bg --https=N http://127.0.0.1:P`, `serve --https=N off`); `install_fake_tailscale(base, monkeypatch, *, logged_in=True, dns_name="hub.tail1234.ts.net.") -> FakeTailscale` (writes a `sh` wrapper `<base>/tailscale`, sets `HYPOTHEX_TAILSCALE`); `FakeTailscale.state() -> dict`.
- Rules: a missing binary, a non-zero exit, a timeout, or a logged-out node (`BackendState != "Running"`) raise `TailscaleError` that names `tailscale up` where it helps; the DNS name loses its trailing dot; the URL is `https://<dns>` (`:<port>` when not 443).

- [ ] **Step 1: Write the fake**

Create `tests/fakes/fake_tailscale.py`:

```python
"""
Fake ``tailscale`` CLI for tests (never a real tailnet).

State lives in the JSON file named by ``HYPOTHEX_FAKE_TAILSCALE_STATE``:
``{"logged_in": bool, "dns_name": str, "serve": {"443": "http://..."}, "calls": [[...]]}``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    """Answer ``status --json`` and ``serve`` like tailscale does; record every call."""
    path = Path(os.environ["HYPOTHEX_FAKE_TAILSCALE_STATE"])
    state = json.loads(path.read_text())
    state.setdefault("calls", []).append(argv)
    code = 0
    if argv[:2] == ["status", "--json"]:
        backend = "Running" if state.get("logged_in") else "NeedsLogin"
        name = state.get("dns_name", "") if state.get("logged_in") else ""
        print(json.dumps({"BackendState": backend, "Self": {"DNSName": name}}))
    elif argv[:1] == ["serve"] and not state.get("logged_in"):
        print("Logged out.", file=sys.stderr)
        code = 1
    elif argv[:2] == ["serve", "--bg"] and len(argv) == 4 and argv[2].startswith("--https="):
        state.setdefault("serve", {})[argv[2].removeprefix("--https=")] = argv[3]
    elif argv[:1] == ["serve"] and len(argv) == 3 and argv[2] == "off":
        state.setdefault("serve", {}).pop(argv[1].removeprefix("--https="), None)
    else:
        print(f"fake tailscale: unsupported {argv}", file=sys.stderr)
        code = 2
    path.write_text(json.dumps(state))
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

Append to `tests/fakes/__init__.py`:

```python
@dataclass(frozen=True)
class FakeTailscale:
    """Handle on a fake ``tailscale`` (``HYPOTHEX_TAILSCALE``)."""

    bin: str
    state_path: Path

    def state(self) -> dict:
        """The fake's current state (serve mappings and recorded calls)."""
        return json.loads(self.state_path.read_text())


def install_fake_tailscale(
    base: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    logged_in: bool = True,
    dns_name: str = "hub.tail1234.ts.net.",
) -> FakeTailscale:
    """
    Install the fake ``tailscale`` and point ``HYPOTHEX_TAILSCALE`` at it.

    Parameters
    ----------
    base : Path
        Directory for the wrapper and the state file.
    monkeypatch : pytest.MonkeyPatch
    logged_in : bool
        Whether ``tailscale status`` reports a running node.
    dns_name : str
        The node's MagicDNS name (with the trailing dot tailscale prints).

    Returns
    -------
    FakeTailscale
    """
    base.mkdir(parents=True, exist_ok=True)
    state = base / "tailscale-state.json"
    state.write_text(json.dumps({"logged_in": logged_in, "dns_name": dns_name, "serve": {}}))
    wrapper = _wrapper(base / "tailscale", FAKES_DIR / "fake_tailscale.py")
    monkeypatch.setenv("HYPOTHEX_TAILSCALE", wrapper)
    monkeypatch.setenv("HYPOTHEX_FAKE_TAILSCALE_STATE", str(state))
    return FakeTailscale(bin=wrapper, state_path=state)
```

- [ ] **Step 2: Write the failing test**

Create `tests/remote/test_tailscale.py`:

```python
from pathlib import Path

import pytest

from hypothex.remote.tailscale import (
    TailscaleError,
    serve_https,
    tailscale_bin,
    tailscale_dns_name,
    unserve,
)
from tests.fakes import install_fake_tailscale


def test_dns_name_without_the_trailing_dot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = install_fake_tailscale(tmp_path, monkeypatch)
    assert tailscale_bin() == fake.bin
    assert tailscale_dns_name() == "hub.tail1234.ts.net"


def test_logged_out_names_tailscale_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_tailscale(tmp_path, monkeypatch, logged_in=False)
    with pytest.raises(TailscaleError, match="tailscale up"):
        tailscale_dns_name()
    with pytest.raises(TailscaleError, match="tailscale up"):
        serve_https(7777)


def test_serve_and_unserve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = install_fake_tailscale(tmp_path, monkeypatch)
    assert serve_https(51234) == "https://hub.tail1234.ts.net"
    assert fake.state()["serve"] == {"443": "http://127.0.0.1:51234"}
    assert serve_https(51235, https_port=8443) == "https://hub.tail1234.ts.net:8443"
    unserve()
    assert fake.state()["serve"] == {"8443": "http://127.0.0.1:51235"}
    assert ["serve", "--https=443", "off"] in fake.state()["calls"]


def test_missing_or_refusing_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(TailscaleError):
        tailscale_dns_name()  # the session's refusing stub
    monkeypatch.setenv("HYPOTHEX_TAILSCALE", str(tmp_path / "not-there"))
    with pytest.raises(TailscaleError, match="not installed"):
        tailscale_dns_name()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/remote/test_tailscale.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'hypothex.remote.tailscale'`.

- [ ] **Step 4: Write the implementation**

Create `src/hypothex/remote/tailscale.py`:

```python
"""Tailscale HTTPS for the hub: ``tailscale serve`` in front of 127.0.0.1 (no relay)."""

from __future__ import annotations

import json
import os
import subprocess

from hypothex.core.errors import HypothexError

SERVE_TIMEOUT_SECONDS = 30.0


class TailscaleError(HypothexError):
    """``tailscale`` is missing, logged out, or failed."""


def tailscale_bin() -> str:
    """
    Return the ``tailscale`` program to run.

    Returns
    -------
    str
        ``$HYPOTHEX_TAILSCALE`` (tests point it at a fake), else ``tailscale``.
    """
    return os.environ.get("HYPOTHEX_TAILSCALE") or "tailscale"


def _run(args: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [tailscale_bin(), *args], capture_output=True, text=True, timeout=timeout
        )
    except FileNotFoundError:
        raise TailscaleError(
            "tailscale is not installed; install it, then run tailscale up"
        ) from None
    except subprocess.TimeoutExpired:
        raise TailscaleError(f"tailscale {args[0]} gave no answer in {timeout:g}s") from None


def _why(proc: subprocess.CompletedProcess[str]) -> str:
    lines = [line.strip() for line in proc.stderr.splitlines() if line.strip()]
    return lines[-1][:200] if lines else f"exit {proc.returncode}"


def tailscale_dns_name(*, timeout: float = 10) -> str:
    """
    Return this node's MagicDNS name.

    Parameters
    ----------
    timeout : float
        Seconds.

    Returns
    -------
    str
        E.g. ``hub.tail1234.ts.net`` (no trailing dot).

    Raises
    ------
    TailscaleError
        Not installed, failed, or logged out (names ``tailscale up``).
    """
    proc = _run(["status", "--json"], timeout)
    if proc.returncode != 0:
        raise TailscaleError(f"tailscale status failed ({_why(proc)}); run tailscale up")
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        raise TailscaleError("tailscale status --json gave no JSON; run tailscale up") from None
    name = str((data.get("Self") or {}).get("DNSName") or "").rstrip(".")
    if data.get("BackendState") != "Running" or not name:
        raise TailscaleError("tailscale is logged out; run tailscale up")
    return name


def serve_https(port: int, *, https_port: int = 443) -> str:
    """
    Publish ``http://127.0.0.1:<port>`` on the tailnet over HTTPS.

    Parameters
    ----------
    port : int
        The hub's local port.
    https_port : int
        The tailnet port.

    Returns
    -------
    str
        ``https://<dns name>`` (``:<https_port>`` when not 443): the hub's public URL.

    Raises
    ------
    TailscaleError
    """
    name = tailscale_dns_name()
    target = f"http://127.0.0.1:{port}"
    proc = _run(["serve", "--bg", f"--https={https_port}", target], SERVE_TIMEOUT_SECONDS)
    if proc.returncode != 0:
        raise TailscaleError(f"tailscale serve failed ({_why(proc)}); run tailscale up")
    return f"https://{name}" if https_port == 443 else f"https://{name}:{https_port}"


def unserve(https_port: int = 443) -> None:
    """
    Remove the HTTPS mapping ``serve_https`` set.

    Parameters
    ----------
    https_port : int

    Raises
    ------
    TailscaleError
    """
    proc = _run(["serve", f"--https={https_port}", "off"], SERVE_TIMEOUT_SECONDS)
    if proc.returncode != 0:
        raise TailscaleError(f"tailscale serve off failed ({_why(proc)})")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/remote/test_tailscale.py -v`
Expected: `4 passed`.

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check src`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/hypothex/remote/tailscale.py tests/fakes/fake_tailscale.py tests/fakes/__init__.py tests/remote/test_tailscale.py
git commit -m "feat(remote): tailscale serve for hub https, with a fake tailscale for tests"
```

---

### Task 38: Paired `route: url` hosts — `token_env`, `host-tokens.json`, and the re-pair message

**Files:**
- Modify: `src/hypothex/remote/config.py` (`HostSpec.token_env`, `HOST_TOKENS_FILE`, `host_token`, `save_host_token`, `forget_host_token`, `load_host_tokens`, `same_origin`, `host_token_env_names`)
- Modify: `src/hypothex/remote/hub.py` (a `route: url` session sends `host_token(...)`; an auth failure says how to re-pair)
- Modify: `src/hypothex/core/execution.py` (`_secret_names` also drops every host's `token_env`)
- Modify: `tests/remote/test_hub.py` (the message of `test_an_auth_failure_stops_retrying_until_connect`)
- Modify: `tests/core/test_execution.py` (append)
- Test: `tests/remote/test_host_pairing.py`

**Interfaces:**
- Produces (contract 1.13, exact): `HostSpec.token_env: str | None` (pattern `ENV_NAME`, `route: url` only), `HOST_TOKENS_FILE = "auth/host-tokens.json"`, `host_token(layout, name, spec) -> SecretStr | None` (the file first, then `resolve_secret(token_env)`).
- Produces (public helpers): `load_host_tokens(layout) -> dict[str, dict[str, str]]` (`{host: {"url", "token"}}`), `save_host_token(layout, name, url, token) -> None` (0600), `forget_host_token(layout, name) -> None`, `same_origin(a, b) -> bool`, `host_token_env_names(layout) -> set[str]` (the `token_env` of every configured host; `set()` when `hosts.yaml` is missing or bad).
- Rules: runs never see a host's bearer token: `_execute` scrubs `host_token_env_names(...)` next to Task 3's names. A paired token is bound to the URL it was redeemed at: `host_token` returns it only while `spec.url` is that same origin (scheme, host, port), so editing `hosts.yaml` to point the name at another server never sends it there; it then falls back to `token_env`. Each session of a `route: url` host reads its token again (so `hx hosts pair` + reconnect uses the new one). A 401/403 from a `route: url` host stops retrying with state `error` and message `auth failed: hx hosts pair <name> <pairing-url>` (spec 5.3, contract failure mode 17); `route: ssh` keeps the phase 2 message (its token is re-read from `server.json` on `connect`).

- [ ] **Step 1: Write the failing test**

Create `tests/remote/test_host_pairing.py`:

```python
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from hypothex.api.app import create_app
from hypothex.core.layout import Layout
from hypothex.remote.config import (
    HostSpec,
    forget_host_token,
    host_token,
    load_host_tokens,
    same_origin,
    save_host_token,
)
from tests.api.authkit import token_for
from tests.api.envserver import host_state, serve_app, wait_until, write_hosts

BASE = "http://127.0.0.1:7777"
EXPECTED = "auth failed: hx hosts pair gpu1 <pairing-url>"


def test_token_env_is_for_url_hosts_only() -> None:
    assert HostSpec(route="url", url="http://h:1", token_env="LAB_TOKEN").token_env == "LAB_TOKEN"
    with pytest.raises(ValidationError, match="token_env"):
        HostSpec(route="ssh", ssh_alias="gpu1", token_env="LAB_TOKEN")
    with pytest.raises(ValidationError):
        HostSpec(route="url", url="http://h:1", token_env="lower")


def test_host_token_prefers_the_paired_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = Layout(tmp_path)
    spec = HostSpec(route="url", url="http://h:1", token_env="LAB_TOKEN")
    assert host_token(layout, "lab", spec) is None
    monkeypatch.setenv("LAB_TOKEN", "from-env")
    token = host_token(layout, "lab", spec)
    assert token is not None and token.get_secret_value() == "from-env"
    save_host_token(layout, "lab", "http://h:1/", "hxs_paired")
    path = tmp_path / "auth" / "host-tokens.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert load_host_tokens(layout) == {"lab": {"url": "http://h:1", "token": "hxs_paired"}}
    paired = host_token(layout, "lab", spec)
    assert paired is not None and paired.get_secret_value() == "hxs_paired"
    forget_host_token(layout, "lab")
    assert load_host_tokens(layout) == {}


def test_a_paired_token_never_goes_to_another_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = Layout(tmp_path)
    save_host_token(layout, "lab", "http://lab-a:8000", "hxs_for_a")
    moved = HostSpec(route="url", url="http://lab-b:8000")
    assert host_token(layout, "lab", moved) is None
    monkeypatch.setenv("LAB_TOKEN", "from-env")
    moved_env = HostSpec(route="url", url="http://lab-b:8000", token_env="LAB_TOKEN")
    token = host_token(layout, "lab", moved_env)
    assert token is not None and token.get_secret_value() == "from-env"
    assert same_origin("http://lab-a:8000/", "HTTP://LAB-A:8000")
    assert not same_origin("http://lab-a:8000", "https://lab-a:8000")


def test_hub_sends_the_token_of_a_url_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = create_app(tmp_path / "gpu1", background_repair=False, kind="ssh", auth_token="T" * 32)
    with serve_app(env) as url:
        hub_home = tmp_path / "hub"
        spec = HostSpec(route="url", url=url, token_env="HX_GPU1_TOKEN")
        write_hosts(hub_home, {"gpu1": spec})
        monkeypatch.setenv("HX_GPU1_TOKEN", "T" * 32)
        with TestClient(create_app(hub_home, background_repair=False), base_url=BASE) as hub:
            wait_until(lambda: host_state(hub, "gpu1") == "connected", timeout=30)


def test_a_rejected_token_asks_to_re_pair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = create_app(tmp_path / "gpu1", background_repair=False, kind="ssh", auth_token="T" * 32)
    with serve_app(env) as url:
        hub_home = tmp_path / "hub"
        write_hosts(hub_home, {"gpu1": HostSpec(route="url", url=url, token_env="HX_GPU1_TOKEN")})
        monkeypatch.setenv("HX_GPU1_TOKEN", "wrong")
        with TestClient(create_app(hub_home, background_repair=False), base_url=BASE) as hub:
            wait_until(lambda: host_state(hub, "gpu1") == "error", timeout=30)
            row = next(r for r in hub.get("/api/v1/hosts").json() if r["name"] == "gpu1")
    assert row["state"]["message"] == EXPECTED


def test_a_paired_host_session_on_a_lab_server(tmp_path: Path) -> None:
    lab = create_app(tmp_path / "lab", background_repair=False, kind="ssh", auth=True)
    token = token_for(lab.state.auth, "sv", "admin", client="host")
    with serve_app(lab) as url:
        hub_home = tmp_path / "hub"
        write_hosts(hub_home, {"lab": HostSpec(route="url", url=url)})
        save_host_token(Layout(hub_home), "lab", url, token)
        with TestClient(create_app(hub_home, background_repair=False), base_url=BASE) as hub:
            wait_until(lambda: host_state(hub, "lab") == "connected", timeout=30)
```

Append to `tests/core/test_execution.py` (add `from hypothex.remote.config import HostSpec` and `from tests.api.envserver import write_hosts`):

```python
def test_run_environment_never_holds_a_host_token(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab = HostSpec(route="url", url="http://127.0.0.1:9", token_env="LAB_TOKEN")
    write_hosts(ctx.layout.home, {"lab": lab})
    monkeypatch.setenv("LAB_TOKEN", "hxs_s_000000000000_hosttoken")
    code = "import os; print(os.environ.get('LAB_TOKEN', '-'))"
    record = prepare_run(ctx, RunRequest(repo=toy_repo, command=[sys.executable, "-c", code]))
    execute_run(ctx, record.run_id)
    assert (ctx.run_dir(record) / "logs" / "stdout.log").read_text().strip() == "-"
```

In `tests/remote/test_hub.py`, in `test_an_auth_failure_stops_retrying_until_connect`, replace

```python
                assert state.message.startswith("authentication failed (HTTP 403)")
                assert "hx hosts connect a" in state.message
```

with

```python
                assert state.message == "auth failed: hx hosts pair a <pairing-url>"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/remote/test_host_pairing.py tests/remote/test_hub.py::test_an_auth_failure_stops_retrying_until_connect -v`
Expected: FAIL at collection with `ImportError: cannot import name 'forget_host_token' from 'hypothex.remote.config'`.

- [ ] **Step 3: Write the implementation**

In `src/hypothex/remote/config.py`:

1. Add to the imports:

```python
import json
from urllib.parse import urlsplit

from pydantic import SecretStr

from hypothex.core.settings import ENV_NAME, resolve_secret, write_private
```

2. In `HostSpec`, after `projects: ...` add:

```python
    token_env: str | None = Field(default=None, pattern=ENV_NAME)
    """``route: url``: the variable holding the env server's bearer token."""
```

   and in `_check_route_and_kind`, before `bad = ...`, add:

```python
        if self.token_env is not None and self.route != "url":
            raise ValueError("token_env is only for route url hosts")
```

3. Append:

```python
HOST_TOKENS_FILE = "auth/host-tokens.json"
"""``<hub home>/auth/host-tokens.json`` (0600): ``{host: {url, token}}`` from ``hx hosts pair``."""


def _origin(url: str) -> tuple[str, str, int | None]:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    port = parts.port or {"http": 80, "https": 443}.get(scheme)
    return scheme, (parts.hostname or "").lower(), port


def same_origin(a: str, b: str) -> bool:
    """
    Tell whether two URLs name the same server (scheme, host, port).

    Parameters
    ----------
    a, b : str

    Returns
    -------
    bool

    Examples
    --------
    >>> same_origin("http://lab:8000/", "HTTP://LAB:8000")
    True
    >>> same_origin("http://lab:8000", "https://lab:8000")
    False
    """
    return _origin(a) == _origin(b)


def load_host_tokens(layout: Layout) -> dict[str, dict[str, str]]:
    """
    Read the paired host tokens.

    Parameters
    ----------
    layout : Layout
        The hub's home.

    Returns
    -------
    dict of str to dict
        Host name to ``{"url": <url it was paired at>, "token": ...}``; ``{}``
        when the file is missing or unreadable. Entries without both keys are dropped.
    """
    try:
        raw = json.loads((layout.home / HOST_TOKENS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        str(k): {"url": str(v["url"]), "token": str(v["token"])}
        for k, v in raw.items()
        if isinstance(v, dict) and v.get("url") and v.get("token")
    }


def save_host_token(layout: Layout, name: str, url: str, token: str) -> None:
    """
    Store the token a host pairing returned, bound to the URL it came from (mode 0600).

    Parameters
    ----------
    layout : Layout
    name : str
        Host name.
    url : str
        The base URL of the pairing link (the server that issued the token).
    token : str
    """
    tokens = load_host_tokens(layout)
    tokens[name] = {"url": url.rstrip("/"), "token": token}
    write_private(layout.home / HOST_TOKENS_FILE, json.dumps(tokens, indent=2, sort_keys=True))


def forget_host_token(layout: Layout, name: str) -> None:
    """
    Remove a host's paired token.

    Parameters
    ----------
    layout : Layout
    name : str
    """
    tokens = load_host_tokens(layout)
    if tokens.pop(name, None) is not None:
        write_private(layout.home / HOST_TOKENS_FILE, json.dumps(tokens, indent=2, sort_keys=True))


def host_token_env_names(layout: Layout) -> set[str]:
    """
    Return the ``token_env`` names of every configured host (kept out of runs).

    Parameters
    ----------
    layout : Layout

    Returns
    -------
    set of str
        Empty when ``hosts.yaml`` is missing or invalid.
    """
    try:
        hosts = load_hosts(layout)
    except ConfigError:
        return set()
    return {spec.token_env for spec in hosts.environments.values() if spec.token_env}


def host_token(layout: Layout, name: str, spec: HostSpec) -> SecretStr | None:
    """
    Return the bearer token the hub sends to a ``route: url`` host.

    Parameters
    ----------
    layout : Layout
        The hub's home.
    name : str
        Host name.
    spec : HostSpec

    Returns
    -------
    SecretStr or None
        ``host-tokens.json`` first (only while ``spec.url`` is the origin it was
        paired at), then the ``token_env`` variable; None without either.
    """
    paired = load_host_tokens(layout).get(name)
    if paired and spec.url is not None and same_origin(paired["url"], spec.url):
        return SecretStr(paired["token"])
    return resolve_secret(layout, spec.token_env) if spec.token_env else None
```

In `src/hypothex/core/execution.py`, replace the last line of `_secret_names` (`return secret_env_names(settings)`) with:

```python
    from hypothex.remote.config import host_token_env_names  # lazy: remote imports core

    return secret_env_names(settings) | host_token_env_names(ctx.layout)
```

In `src/hypothex/remote/hub.py`:

1. Add `host_token` to the `hypothex.remote.config` import.

2. In `_session`, replace

```python
            sup.token = None  # route url: no token; route ssh: _open_route sets it
            base_url = await self._open_route(sup)
```

with

```python
            sup.token = None  # route ssh: _open_route sets it from server.json
            if sup.spec.route == "url":
                # read again every session: `hx hosts pair` then connect uses the new one
                secret = host_token(self.ctx.layout, sup.name, sup.spec)
                sup.token = secret.get_secret_value() if secret is not None else None
            base_url = await self._open_route(sup)
```

3. In `_supervise`, replace

```python
                if status is not None:  # retrying with the same token cannot help
                    self._set(
                        sup,
                        "error",
                        f"authentication failed (HTTP {status}); reconnect or re-pair: "
                        f"hx hosts connect {sup.name}",
                    )
                    return
```

with

```python
                if status is not None:  # retrying with the same token cannot help (spec 5.3)
                    if sup.spec.route == "url":
                        message = f"auth failed: hx hosts pair {sup.name} <pairing-url>"
                    else:
                        message = (
                            f"authentication failed (HTTP {status}); reconnect or re-pair: "
                            f"hx hosts connect {sup.name}"
                        )
                    self._set(sup, "error", message)
                    return
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/remote/test_host_pairing.py tests/remote/test_hub.py tests/remote/test_config.py tests/core/test_execution.py -v`
Expected: `tests/remote/test_host_pairing.py` `6 passed`; `test_run_environment_never_holds_a_host_token` passes; the hub, config, and execution tests still pass.

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check src`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/remote/config.py src/hypothex/remote/hub.py src/hypothex/core/execution.py tests/remote/test_host_pairing.py tests/remote/test_hub.py tests/core/test_execution.py
git commit -m "feat(remote): paired or env-held tokens for url hosts and a re-pair message"
```

---

### Task 39: `hx serve --auth --tailscale --public-url`

**Files:**
- Modify: `src/hypothex/cli/main.py` (`serve`, `_serve_token`, `_server_file`, `owner_name`)
- Test: `tests/cli/test_serve_auth.py`

**Interfaces:**
- Consumes: `load_settings`, `check_secrets_file` (Tasks 2–3), `AuthStore.ensure_owner/mint_local/sessions/revoke` (Task 6), `serve_https`/`unserve` (Task 37), `create_app(auth=, public_url=)` (Task 23).
- Produces (contract 1.10, 1.13, 4): `hx serve [--auth] [--tailscale] [--public-url URL]`; `owner_name() -> str` (`$USER` lowercased with characters outside `[a-z0-9_-]` dropped, else `owner`).
- Rules: `secrets.env` with group/other bits stops the start (`chmod 600 <path>`). `--auth` or `server.auth: on` turns auth on: `ensure_owner(owner_name())`, earlier `local` sessions of the owner are revoked, `mint_local` writes the new token into `server.json` (an env server's `HYPOTHEX_SERVE_TOKEN` wins when both exist; both pass `AuthGuard`), and the session is revoked when the server stops. A non-loopback `--host` needs auth on or a serve token (the refusal names both). `--tailscale` needs auth on ("tailscale needs server.auth: on"), binds `127.0.0.1`, uses `serve_https(port)` as `public_url`, and calls `unserve()` at stop. The start claims the home (`server.json`, refused while a live server owns it) before any side effect, so a second `hx serve` on the same home exits without touching the running server's tailnet mapping or local session; the minted token is written into the claimed `server.json` after. Cleanup (revoke the local session, `unserve()`) runs once: in the app's lifespan (inside uvicorn's signal handling), or at once when the start fails before the app serves (e.g. `create_app` raises `IndexUnavailableError`).

- [ ] **Step 1: Write the failing test**

Create `tests/cli/test_serve_auth.py`:

```python
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from hypothex.auth.store import AuthStore
from hypothex.cli.main import _serve_token, owner_name
from hypothex.core.errors import ConfigError
from hypothex.core.layout import Layout
from hypothex.core.settings import ServerSettings, Settings, save_settings
from tests.api.envserver import wait_until
from tests.fakes import install_fake_tailscale

HX = [sys.executable, "-m", "hypothex.cli.main"]


def start(home: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.Popen[bytes]:
    full = {k: v for k, v in os.environ.items() if k != "HYPOTHEX_SERVE_TOKEN"}
    full.update(env or {})
    return subprocess.Popen(
        [*HX, "--home", str(home), "serve", "--port", "0", *args],
        env=full,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def info_of(home: Path) -> dict:
    # the home is claimed first and the minted token written right after: wait for the token
    def ready() -> dict | None:
        info = json.loads((home / "serve" / "server.json").read_text())
        return info if info.get("token") else None

    return wait_until(ready, timeout=30)


def stop(proc: subprocess.Popen[bytes]) -> None:
    proc.terminate()
    proc.wait(timeout=30)


def test_owner_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USER", "Alice.Smith")
    assert owner_name() == "alicesmith"
    monkeypatch.setenv("USER", "9bad")
    assert owner_name() == "owner"


def test_serve_with_auth_mints_a_local_owner_session(tmp_path: Path) -> None:
    home = tmp_path / "h"
    proc = start(home, "--auth", env={"USER": "sv"})
    try:
        info = info_of(home)
        assert info["token"].startswith("hxs_")
        base = f"http://127.0.0.1:{info['port']}"
        wait_until(
            lambda: httpx.get(f"{base}/.well-known/hypothex/environment", timeout=2), timeout=30
        )
        assert httpx.get(f"{base}/api/v1/projects", timeout=5).status_code == 401
        auth = {"Authorization": f"Bearer {info['token']}"}
        me = httpx.get(f"{base}/api/v1/auth/me", headers=auth, timeout=5).json()
        assert (me["user"], me["scope"], me["client"], me["auth"]) == ("sv", "admin", "local", "on")
    finally:
        stop(proc)
    sessions = AuthStore(Layout(home)).sessions("sv")
    assert [s for s in sessions if s.client == "local"] == []  # revoked at stop


def test_tailscale_needs_auth(tmp_path: Path) -> None:
    done = subprocess.run(
        [*HX, "--home", str(tmp_path / "h"), "serve", "--tailscale"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 1 and "tailscale needs server.auth: on" in done.stderr


def test_tailscale_publishes_and_unpublishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = install_fake_tailscale(tmp_path / "ts", monkeypatch)
    home = tmp_path / "h"
    proc = start(home, "--auth", "--tailscale", env={"USER": "sv"})
    try:
        info = info_of(home)
        port = info["port"]
        wait_until(lambda: fake.state()["serve"].get("443"), timeout=30)
        assert fake.state()["serve"] == {"443": f"http://127.0.0.1:{port}"}
        auth = {"Authorization": f"Bearer {info['token']}"}
        me = wait_until(
            lambda: httpx.get(
                f"http://127.0.0.1:{port}/api/v1/auth/me", headers=auth, timeout=2
            ).json(),
            timeout=30,
        )
        assert me["public_url"] == "https://hub.tail1234.ts.net"
    finally:
        stop(proc)
    assert fake.state()["serve"] == {}


def test_a_second_start_leaves_the_running_server_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = install_fake_tailscale(tmp_path / "ts", monkeypatch)
    home = tmp_path / "h"
    proc = start(home, "--auth", "--tailscale", env={"USER": "sv"})
    try:
        info = info_of(home)
        wait_until(lambda: fake.state()["serve"].get("443"), timeout=30)
        mapping = fake.state()["serve"]
        auth = {"Authorization": f"Bearer {info['token']}"}
        base = f"http://127.0.0.1:{info['port']}"
        wait_until(lambda: httpx.get(f"{base}/api/v1/auth/me", headers=auth, timeout=2), timeout=30)
        second = subprocess.run(
            [*HX, "--home", str(home), "serve", "--auth", "--tailscale", "--port", "0"],
            env={**os.environ, "USER": "sv"},
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert second.returncode == 1 and "already serves this home" in second.stderr
        assert fake.state()["serve"] == mapping  # the first server's mapping is untouched
        me = httpx.get(f"{base}/api/v1/auth/me", headers=auth, timeout=5)
        assert me.status_code == 200 and me.json()["user"] == "sv"  # its session still works
    finally:
        stop(proc)


def test_a_start_that_fails_before_serving_undoes_its_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = install_fake_tailscale(tmp_path / "ts", monkeypatch)
    home = tmp_path / "h"
    dead = "postgresql+psycopg://hx@127.0.0.1:1/hypothex"  # create_app cannot open the index
    save_settings(Layout(home), Settings(server=ServerSettings(index_url=dead)))
    done = subprocess.run(
        [*HX, "--home", str(home), "serve", "--auth", "--tailscale", "--port", "0"],
        env={**os.environ, "USER": "sv"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 1 and "does not answer" in done.stderr
    assert fake.state()["serve"] == {}  # unpublished
    assert [s for s in AuthStore(Layout(home)).sessions("sv") if s.client == "local"] == []
    assert not (home / "serve" / "server.json").exists()


def test_open_bind_needs_auth_or_a_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # the refusal comes before any socket is opened, so nothing listens on 0.0.0.0
    done = subprocess.run(
        [*HX, "--home", str(tmp_path / "h"), "serve", "--host", "0.0.0.0", "--port", "0"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 1
    assert "server.auth: on" in done.stderr and "HYPOTHEX_SERVE_TOKEN" in done.stderr
    # with auth on the open bind is allowed; checked on the decision itself, never by
    # listening on every interface of the developer's machine
    monkeypatch.delenv("HYPOTHEX_SERVE_TOKEN", raising=False)
    assert _serve_token("0.0.0.0", "local", False, auth_on=True) is None
    with pytest.raises(ConfigError, match="server.auth: on"):
        _serve_token("0.0.0.0", "local", False, auth_on=False)


def test_readable_secrets_file_stops_the_start(tmp_path: Path) -> None:
    home = tmp_path / "h"
    home.mkdir()
    secrets = home / "secrets.env"
    secrets.write_text("HYPOTHEX_SLACK_WEBHOOK=https://hooks.example/SECRET\n")
    secrets.chmod(0o640)
    done = subprocess.run(
        [*HX, "--home", str(home), "serve", "--port", "0"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 1 and f"chmod 600 {secrets}" in done.stderr
    assert "SECRET" not in done.stderr.replace(str(secrets), "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/cli/test_serve_auth.py -v`
Expected: FAIL at collection with `ImportError: cannot import name 'owner_name' from 'hypothex.cli.main'`.

- [ ] **Step 3: Write the implementation**

In `src/hypothex/cli/main.py`:

1. Add after `resolve_serve_kind`:

```python
def owner_name() -> str:
    """
    Return the hub owner's user name for a first ``hx serve --auth``.

    Returns
    -------
    str
        ``$USER`` lowercased with characters outside ``[a-z0-9_-]`` dropped,
        when that is a valid user name; else ``owner``.

    Examples
    --------
    >>> import os
    >>> os.environ["USER"] = "Sv"
    >>> owner_name()
    'sv'
    """
    from hypothex.auth.store import USER_NAME

    name = re.sub(r"[^a-z0-9_-]", "", os.environ.get("USER", "").lower())[:32]
    return name if re.fullmatch(USER_NAME, name) else "owner"
```

2. Change `_serve_token` to take `*, auth_on: bool = False`, and replace its refusal block with:

```python
    if token is None and not auth_on and not is_loopback_bind(host):
        raise ConfigError(
            f"refusing to serve on {host!r} without authentication: anyone who can reach "
            "this address could start arbitrary commands and read run files through the "
            "API. Turn on auth (server.auth: on in config.yaml, or hx serve --auth), or set "
            "HYPOTHEX_SERVE_TOKEN to require 'Authorization: Bearer <token>', or keep "
            "--host 127.0.0.1 and reach it through an SSH tunnel "
            "(ssh -L 7777:127.0.0.1:7777 HOST)"
        )
```

   and add to its docstring: "auth_on : bool — with auth on, sessions protect every route, so an open bind is allowed."

3. Replace the `serve` command with:

```python
@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Bind address.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port; 0 picks a free one.")] = 7777,
    kind: Annotated[
        str | None,
        typer.Option(
            "--kind",
            help="Run as a host's env server: ssh (GPU queue) or slurm. Default: the saved kind.",
        ),
    ] = None,
    no_auth: Annotated[
        bool,
        typer.Option(
            "--no-auth", help="Env server without a bearer token (demo and test hosts only)."
        ),
    ] = False,
    auth: Annotated[
        bool, typer.Option("--auth", help="Require paired sessions (server.auth: on).")
    ] = False,
    tailscale: Annotated[
        bool, typer.Option("--tailscale", help="Publish over HTTPS with tailscale serve.")
    ] = False,
    public_url: Annotated[
        str | None, typer.Option("--public-url", help="URL people reach this hub at.")
    ] = None,
) -> None:
    """
    Serve the HTTP/WebSocket API, the UI when built, and (on the hub) the hosts.

    With auth on (``--auth`` or ``server.auth: on``) every route needs a paired
    session; this machine's CLI uses the owner session written to
    ``<home>/serve/server.json``. ``--tailscale`` (auth on) publishes the hub
    on the tailnet with ``tailscale serve``. An env server (``--kind ssh|slurm``)
    keeps its per-start bearer token. A non-loopback --host needs auth on or a token.
    """
    import uvicorn

    from hypothex.api.app import create_app
    from hypothex.auth.store import AuthStore, Principal
    from hypothex.core.environment import PROTOCOL_VERSION
    from hypothex.core.settings import check_secrets_file, load_settings
    from hypothex.demo import demo_hosts_running
    from hypothex.remote.bootstrap import ServerInfo
    from hypothex.remote.tailscale import serve_https, unserve

    home = _home_path()
    layout = Layout(home)
    layout.ensure()
    settings = load_settings(layout)
    check_secrets_file(layout)
    auth_on = auth or settings.server.auth == "on"
    if tailscale and not auth_on:
        raise ConfigError("tailscale needs server.auth: on (or hx serve --auth)")
    if tailscale:
        host = "127.0.0.1"
    resolved = resolve_serve_kind(home, kind)
    token = _serve_token(host, resolved, no_auth, auth_on=auth_on)
    sock = _listen(host, port)
    bound = sock.getsockname()[1]
    public = public_url or settings.server.public_url
    owner = owner_name()
    me = Principal(user=owner, scope="admin", session_id=None, client="local")
    store: AuthStore | None = None
    local_session_id: str | None = None
    published = False
    info = ServerInfo(
        pid=os.getpid(),
        port=bound,
        managed=False,
        hx_version=__version__,
        protocol_version=PROTOCOL_VERSION,
        token=token,
    )

    def release() -> None:
        # undo this start's side effects, each at most once: at stop (the lifespan), or at
        # once when the start fails before the app serves (e.g. the index does not answer)
        nonlocal local_session_id, published
        if store is not None and local_session_id is not None:
            with contextlib.suppress(HypothexError):
                store.revoke(local_session_id, by=me)
            local_session_id = None
        if published:
            with contextlib.suppress(HypothexError):
                unserve()
            published = False

    class _Server(uvicorn.Server):
        # uvicorn re-raises SIGTERM/SIGINT once it has shut down, which ends the
        # process before `with _server_file` cleans up: drop server.json first
        @contextmanager
        def capture_signals(self) -> Iterator[None]:
            with super().capture_signals():
                try:
                    yield
                finally:
                    _drop_server_file(home, info.pid)

    @contextmanager
    def served() -> Iterator[None]:
        # entered and left by the app's lifespan, so SIGTERM runs this cleanup too
        try:
            with demo_hosts_running(home) as live:
                if live:
                    typer.secho(f"demo hosts up; {len(live)} sweep runs launched on gpu1", err=True)
                yield
        finally:
            release()

    # claim the home first: a second `hx serve` stops here, before it touches the tailnet
    # mapping or the owner's local session that the running server holds
    with _server_file(home, info) as set_token:
        try:
            if auth_on:
                store = AuthStore(layout, session_days=settings.server.session_days)
                store.ensure_owner(owner)
                for old in store.sessions(owner):
                    if old.client == "local":
                        store.revoke(old.id, by=me)
                session, local_token = store.mint_local(owner)
                local_session_id = session.id
                if token is None:  # an env server's HYPOTHEX_SERVE_TOKEN wins
                    set_token(local_token)
            if tailscale:
                public = serve_https(bound)
                published = True
            application = create_app(
                home,
                host=host,
                kind=resolved,
                auth_token=token,
                hub_url=_url(host, bound),
                lifespan_context=served,
                auth=auth_on,
                public_url=public,
            )
            shown = f"{_url(host, bound)}" + (f" · {public}" if public else "")
            typer.secho(f"hx serve on {shown}" + (" · auth on" if auth_on else ""), err=True)
            # the socket is bound already: uvicorn logs no "running on" line for it, so
            # the start script finds the port in server.json (written above, Task 11)
            config = uvicorn.Config(application, host=host, port=bound, log_level="info")
            _Server(config).run(sockets=[sock])
        finally:
            release()  # a no-op when the lifespan already ran it
```

4. Make `_server_file` yield a way to add the token once it is minted (the home is claimed before any side effect, and the claim is not given up to write the token). Replace its signature line and the tail of its body:

```python
@contextmanager
def _server_file(home: Path, info: ServerInfo) -> Iterator[None]:
```

with

```python
@contextmanager
def _server_file(home: Path, info: ServerInfo) -> Iterator[Callable[[str | None], None]]:
```

and

```python
    try:
        yield
    finally:
        _drop_server_file(home, info.pid)
```

with

```python
    def set_token(token: str | None) -> None:
        # the same record with the token minted after the claim; this process owns the
        # home, so an atomic rewrite needs no lock (a rival start reads a live owner)
        _write_private(path, json.dumps({**record, "token": token}, indent=2))

    try:
        yield set_token
    finally:
        _drop_server_file(home, info.pid)
```

   and add `Callable` to the `collections.abc` import.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/cli/test_serve_auth.py tests/cli/test_serve.py -v`
Expected: `tests/cli/test_serve_auth.py` `8 passed`; the phase 2 serve tests still pass.

Run: `uv run python -m doctest src/hypothex/cli/main.py && uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check src`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/cli/main.py tests/cli/test_serve_auth.py
git commit -m "feat(cli): hx serve --auth with a local owner session, --tailscale, --public-url"
```

---
## Part 12: SDK and CLI

Contract 1.14, 4. Every new command supports `--json`; text output is one line or a table. A CLI that logged in to a hub (`hx login`) reads projects, tasks, runs, notebooks, digests, and exports through it ("client mode"); otherwise commands work on this machine's home, and commands that belong to the hub (notify, storage, digest send) try the running hub first.

### Task 40: `run.log_cost`

**Files:**
- Modify: `src/hypothex/sdk.py` (`Run.log_cost`, `NoopRun.log_cost`)
- Test: `tests/test_sdk_cost.py`

**Interfaces:**
- Produces (contract 1.14, exact): `Run.log_cost(usd, tokens_in=0, tokens_out=0, example_id=None) -> None` (= `log_usage(usd=, tokens_in=, tokens_out=, example_id=)`, so it lands in `usage.jsonl` and in `cost.api_usd` when the run ends); `NoopRun.log_cost` does nothing.

- [ ] **Step 1: Write the failing test**

Create `tests/test_sdk_cost.py`:

```python
import json
from pathlib import Path

import pytest

import hypothex as hx
from hypothex import sdk


@pytest.fixture
def run_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    run_dir = tmp_path / "run"
    (run_dir / "predictions").mkdir(parents=True)
    monkeypatch.setenv("HYPOTHEX_RUN_DIR", str(run_dir))
    monkeypatch.setenv("HYPOTHEX_RUN_ID", "r1")
    monkeypatch.setenv("HYPOTHEX_PROJECT", "toy")
    monkeypatch.setattr(sdk, "_current", None)
    return run_dir


def test_log_cost_writes_a_usage_row(run_env: Path) -> None:
    hx.current().log_cost(0.0131, tokens_in=4410, tokens_out=512, example_id="ex-1")
    hx.current().log_cost(0.5)
    rows = [json.loads(line) for line in (run_env / "usage.jsonl").read_text().splitlines()]
    assert rows == [
        {"example_id": "ex-1", "tokens_in": 4410, "tokens_out": 512, "usd": 0.0131, "seconds": 0.0},
        {"example_id": None, "tokens_in": 0, "tokens_out": 0, "usd": 0.5, "seconds": 0.0},
    ]


def test_log_cost_refuses_bad_values(run_env: Path) -> None:
    with pytest.raises(ValueError):
        hx.current().log_cost(-1.0)
    assert not (run_env / "usage.jsonl").exists()


def test_noop_log_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HYPOTHEX_RUN_DIR", raising=False)
    monkeypatch.setattr(sdk, "_current", None)
    assert hx.current().log_cost(1.0, tokens_in=3) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sdk_cost.py -v`
Expected: FAIL with `AttributeError: 'Run' object has no attribute 'log_cost'`.

- [ ] **Step 3: Write the implementation**

In `src/hypothex/sdk.py`, add to `Run` after `log_usage`:

```python
    def log_cost(
        self,
        usd: float,
        tokens_in: int = 0,
        tokens_out: int = 0,
        example_id: str | None = None,
    ) -> None:
        """
        Record API spend (spec 9's ``run.log_cost``); same row as ``log_usage``.

        Parameters
        ----------
        usd : float
            Cost in US dollars.
        tokens_in, tokens_out : int
            Tokens, split like ``usage.jsonl``.
        example_id : str, optional
            The example the call was made for.

        Raises
        ------
        ValueError
            If a value is negative or not finite; nothing is written then.

        Examples
        --------
        >>> hx.current().log_cost(0.0131, tokens_in=4410, tokens_out=512)  # doctest: +SKIP
        """
        self.log_usage(tokens_in=tokens_in, tokens_out=tokens_out, usd=usd, example_id=example_id)
```

and to `NoopRun` after its `log_usage`:

```python
    def log_cost(
        self,
        usd: float,
        tokens_in: int = 0,
        tokens_out: int = 0,
        example_id: str | None = None,
    ) -> None:
        """Do nothing."""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_sdk_cost.py tests/test_sdk.py -v`
Expected: `tests/test_sdk_cost.py` `3 passed`; `tests/test_sdk.py` still passes.

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check src`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/sdk.py tests/test_sdk_cost.py
git commit -m "feat(sdk): run.log_cost for api spend"
```

---

### Task 41: `hx login|logout|whoami|pair`, `hx sessions`, `hx users`, and hub tokens for the CLI

**Files:**
- Modify: `src/hypothex/mcp/server.py` (`resolve_hub_token` reads `hub-tokens.json`; `hub_call` sends `X-Hypothex-Agent` and takes `text=` and `agent=`; the MCP tools' hub calls send their own `agent`)
- Modify: `src/hypothex/cli/main.py` (commands and the `sessions`, `users` groups)
- Test: `tests/cli/test_auth_cli.py`

**Interfaces:**
- Consumes: `parse_pairing_url` (Task 7), `HubLogin`/`save_hub_login`/`hub_login`/`forget_hub_login` (Task 7), the auth routes (Task 25).
- Produces (contract 4, exact): `hx pair [--user NAME] [--new-user] [--scope read|launch|admin] [--client browser|cli|host] [--ttl 300] [--url HUB]` (prints the QR code and the URL; `--json` the offer); `hx login <pairing-url> [--device NAME]` (as `cli`, or `agent` when `HYPOTHEX_AGENT` is set; stores the token in `hub-tokens.json`; never prints it); `hx logout [--hub URL]`; `hx whoami`; `hx sessions list [--all]` / `hx sessions revoke <id>`; `hx users list` / `hx users disable <name>`.
- Produces (contract 2): `resolve_hub_token(url, home)` order: `$HYPOTHEX_HUB_TOKEN`, then the `hub-tokens.json` login for that URL, then (loopback only) `serve/server.json`.
- Produces (additive): `hub_call(..., text: bool = False, agent: str | None = None, discover_token: bool = True)` (`text`: return the body as text, for exports; `agent`: the `X-Hypothex-Agent` header, default `$HYPOTHEX_AGENT`); the CLI sends `X-Hypothex-Agent: $HYPOTHEX_AGENT`; an MCP tool's hub call sends the tool's own `agent` argument (default `mcp`), because an authenticated hub takes the agent from that header and overwrites the body's `created_by` (contract 1.2), so `launch_run(agent="claude", host=...)` by alice is `agent:claude@alice`, not `human:alice`.

- [ ] **Step 1: Write the failing test**

Create `tests/cli/test_auth_cli.py`:

```python
import json
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from hypothex.auth.store import AuthStore
from hypothex.cli.main import app
from hypothex.core.context import Context
from hypothex.mcp.server import hub_call
from tests.api.authkit import auth_app, token_for
from tests.api.envserver import serve_app
from tests.factories import write_toy_project

runner = CliRunner()


@pytest.fixture
def hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[str, AuthStore]]:
    home = tmp_path / "hub-home"
    Context.open(home).register_project(write_toy_project(tmp_path / "toy"))
    app_ = auth_app(home)
    with serve_app(app_) as url:
        monkeypatch.setenv("HYPOTHEX_HUB_URL", url)
        yield url, app_.state.auth


def hx(home: Path, *args: str, env: dict[str, str] | None = None) -> Any:
    result = runner.invoke(
        app, ["--home", str(home), *args, "--json"], env=env, catch_exceptions=False
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def fails(home: Path, *args: str, env: dict[str, str] | None = None) -> str:
    result = runner.invoke(app, ["--home", str(home), *args], env=env)
    assert result.exit_code == 1
    return str(result.exception)


def owner_env(store: AuthStore) -> dict[str, str]:
    return {"HYPOTHEX_HUB_TOKEN": token_for(store, "sv", "admin")}


def login_alice(tmp_path: Path, url: str, store: AuthStore, **env: str) -> Path:
    new = ["--new-user"] if store.get_user("alice") is None else []
    args = ["pair", *new, "--user", "alice", "--scope", "launch"]
    offer = hx(tmp_path / "owner", *args, env=owner_env(store))
    laptop = tmp_path / "alice-laptop"
    out = hx(laptop, "login", offer["url"], "--device", "MacBook", env=env or None)
    assert (out["hub"], out["user"], out["scope"]) == (url, "alice", "launch")
    return laptop


def test_pair_then_login_from_another_home(tmp_path: Path, hub: tuple[str, AuthStore]) -> None:
    url, store = hub
    laptop = login_alice(tmp_path, url, store)
    path = laptop / "auth" / "hub-tokens.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    token = json.loads(path.read_text())[url]["token"]
    me = hx(laptop, "whoami")
    assert (me["user"], me["scope"], me["client"]) == ("alice", "launch", "cli")
    raw = runner.invoke(app, ["--home", str(laptop), "whoami", "--json"])
    assert token not in raw.stdout


def test_pair_prints_a_qr_code_and_the_link(tmp_path: Path, hub: tuple[str, AuthStore]) -> None:
    _, store = hub
    result = runner.invoke(
        app, ["--home", str(tmp_path / "o"), "pair", "--user", "sv", "--scope", "read"],
        env=owner_env(store),
    )  # fmt: skip
    assert result.exit_code == 0 and "█" in result.stdout and "/pair#p_" in result.stdout
    # a host link must be admin: the hub would refuse to redeem anything less as host
    message = fails(tmp_path / "o", "pair", "--client", "host", "--scope", "launch")
    assert message == "--client host needs --scope admin"


def test_agent_login_is_an_agent_session(tmp_path: Path, hub: tuple[str, AuthStore]) -> None:
    url, store = hub
    laptop = login_alice(tmp_path, url, store, HYPOTHEX_AGENT="claude")
    assert hx(laptop, "whoami")["client"] == "agent"


def test_sessions_users_and_disable(tmp_path: Path, hub: tuple[str, AuthStore]) -> None:
    url, store = hub
    laptop = login_alice(tmp_path, url, store)
    mine = hx(laptop, "sessions", "list")
    assert [s["user"] for s in mine] == ["alice"]
    owner = owner_env(store)
    every = hx(tmp_path / "owner", "sessions", "list", "--all", env=owner)
    assert {"sv", "alice"} <= {s["user"] for s in every}
    users = hx(tmp_path / "owner", "users", "list", env=owner)
    assert {u["name"]: u["role"] for u in users}["alice"] == "launch"
    assert "admin" in fails(laptop, "users", "list")
    hx(tmp_path / "owner", "users", "disable", "alice", env=owner)
    assert "401" in fails(laptop, "whoami")


def test_revoke_and_logout(tmp_path: Path, hub: tuple[str, AuthStore]) -> None:
    url, store = hub
    laptop = login_alice(tmp_path, url, store)
    session = hx(laptop, "whoami")["session_id"]
    hx(tmp_path / "owner", "sessions", "revoke", session, env=owner_env(store))
    assert "401" in fails(laptop, "whoami")
    other = login_alice(tmp_path / "again", url, store)
    assert hx(other, "logout") == {"hub": url, "logged_out": True}
    assert json.loads((other / "auth" / "hub-tokens.json").read_text()) == {}


def test_hub_calls_carry_the_callers_agent(hub: tuple[str, AuthStore]) -> None:
    url, store = hub
    alice = token_for(store, "alice", "launch")
    path = "/api/v1/projects/toy/notebook/today"
    day = hub_call("POST", path, {"text": "from an agent"}, url=url, token=alice, agent="claude")
    assert "— agent:claude@alice" in day["text"]  # not human:alice: the header names the agent
    plain = hub_call("POST", path, {"text": "by hand"}, url=url, token=alice)
    assert "— human:alice" in plain["text"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/cli/test_auth_cli.py -v`
Expected: FAIL: `No such command 'pair'` (exit code 2) in the five CLI tests, and `test_hub_calls_carry_the_callers_agent` with `TypeError: hub_call() got an unexpected keyword argument 'agent'`.

- [ ] **Step 3: Teach the hub client about logins and agents**

In `src/hypothex/mcp/server.py`:

1. Add `from hypothex.auth.client import hub_login` and `from hypothex.core.layout import Layout, default_home` (merge with the existing `default_home` import).

2. Replace the body of `resolve_hub_token` (after its docstring, which gains "then the ``hub-tokens.json`` login of ``hx login`` for that URL" in its first paragraph) with:

```python
    given = os.environ.get("HYPOTHEX_HUB_TOKEN")
    if given:
        return given
    base = (url or hub_url()).rstrip("/")
    login = hub_login(Layout(home or default_home()), base)
    if login is not None:
        return login.token
    parts = urlsplit(base)
    try:
        port = parts.port
    except ValueError:
        return None
    if parts.hostname is None or not is_loopback_bind(parts.hostname):
        return None
    path = (home or default_home()) / "serve" / "server.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or record.get("port") != port:
        return None
    token = record.get("token")
    return token if isinstance(token, str) and token else None
```

3. In `hub_call`, preserve Task 32's `discover_token` argument and conditional credential selection; add `text: bool = False,` and `agent: str | None = None,` after `token: str | None = None,`, document them ("text : bool — return the body as text (exports) instead of JSON." and "agent : str, optional — the agent this call acts for (``X-Hypothex-Agent``); default ``$HYPOTHEX_AGENT``."), replace

```python
    headers = {"Authorization": f"Bearer {auth}"} if auth else {}
```

with

```python
    headers = {"Authorization": f"Bearer {auth}"} if auth else {}
    acting = agent or os.environ.get("HYPOTHEX_AGENT")
    if acting:
        # an authenticated hub takes the agent from this header, never from the body
        headers["X-Hypothex-Agent"] = acting
```

and replace

```python
    if resp.status_code < 400:
        return resp.json()
```

with

```python
    if resp.status_code < 400:
        return resp.text if text else resp.json()
```

4. In `build_server`, let every tool's hub call carry the tool's agent. Replace `hub` and `via_hub` with:

```python
    def hub(
        method: str, path: str, body: dict[str, Any] | None = None,
        agent: str = "mcp", timeout: float = 120.0,
    ) -> Any:
        # a tool always acts for an agent: the hub stamps agent:<agent>@<user> from the header
        return hub_call(
            method,
            path,
            body,
            url=hub_url,
            token=auth(),
            agent=agent,
            timeout=timeout,
            discover_token=not _OVER_HTTP.get(),
        )


    def via_hub(run_id: str, action: str, body: dict[str, Any], agent: str = "mcp") -> Any:
        # a mirrored run is acted on by its host: the hub forwards it (Task 45)
        if not acts_through_hub(ctx(), run_id):
            return None
        full = {**body, "command_id": new_command_id(), "created_by": f"agent:{agent}"}
        return hub("POST", f"/api/v1/runs/{run_id}/{action}", full, agent=agent)
```

   and pass the tool's agent in the three launching calls: in `launch_run`, `hub("POST", f"/api/v1/hosts/{host}/runs", body, agent=agent)`; in `launch_sweep`, `hub("POST", "/api/v1/sweeps", body, agent=agent)`; in `extend_sweep`, `hub("POST", f"/api/v1/sweeps/{spec.project}/{spec.id}/extend", body, agent=agent)`.

- [ ] **Step 4: Add the commands**

In `src/hypothex/cli/main.py`, after the `db_app` block add:

```python
sessions_app = typer.Typer(no_args_is_help=True, help="Your sessions on the hub.")
app.add_typer(sessions_app, name="sessions")
users_app = typer.Typer(no_args_is_help=True, help="People on the hub (admin).")
app.add_typer(users_app, name="users")
SCOPES = ("read", "launch", "admin")
```

and add these helpers and commands (after the `hosts` commands):

```python
def _redeem(pairing: str, client: str, device: str) -> tuple[str, dict[str, Any]]:
    """Redeem a pairing link with the hub it names; the secret travels in the body only."""
    import httpx

    from hypothex.auth.pairing import parse_pairing_url

    base, offer_id, secret = parse_pairing_url(pairing)
    body = {"offer_id": offer_id, "secret": secret, "client": client, "device": device}
    try:
        resp = httpx.post(f"{base}/api/v1/auth/pair", json=body, timeout=30)
    except httpx.HTTPError as exc:
        raise HypothexError(f"the hub at {base} did not answer ({type(exc).__name__})") from None
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code >= 400:
        error = data.get("error") if isinstance(data, dict) else None
        raise HypothexError(error or f"hub answered {resp.status_code}")
    return base, data


def _device() -> str:
    return (socket.gethostname() or "device")[:64]


@app.command()
def login(
    pairing_url: Annotated[str, typer.Argument(help="The link from `hx pair`.")],
    device: Annotated[
        str | None, typer.Option("--device", help="Name in the sessions list.")
    ] = None,
    as_json: JsonFlag = False,
) -> None:
    """Pair this CLI with a hub; the token is kept in <home>/auth/hub-tokens.json."""
    from hypothex.auth.client import HubLogin, save_hub_login
    from hypothex.mcp.server import hub_url

    client = "agent" if os.environ.get("HYPOTHEX_AGENT") else "cli"
    base, data = _redeem(pairing_url, client, device or _device())
    entry = HubLogin(
        token=data["token"], user=data["user"], scope=data["scope"], session_id=data["session_id"]
    )
    save_hub_login(Layout(_home_path()), base, entry)
    out = {"hub": base, "user": entry.user, "scope": entry.scope, "session_id": entry.session_id}
    text = f"✓ {entry.user} · {entry.scope} · {base}"
    if hub_url() != base:
        text += f"\nset HYPOTHEX_HUB_URL={base}"
    _emit(out, as_json, text)


@app.command()
def logout(
    hub: Annotated[
        str | None, typer.Option("--hub", help="Hub URL (default: HYPOTHEX_HUB_URL).")
    ] = None,
    as_json: JsonFlag = False,
) -> None:
    """Revoke this CLI's session on a hub and forget its token."""
    from hypothex.auth.client import forget_hub_login, hub_login
    from hypothex.mcp.server import hub_call, hub_url

    url = (hub or hub_url()).rstrip("/")
    layout = Layout(_home_path())
    entry = hub_login(layout, url)
    if entry is not None:
        with contextlib.suppress(HypothexError):
            hub_call("POST", "/api/v1/auth/logout", {}, url=url, token=entry.token)
        forget_hub_login(layout, url)
    text = f"logged out of {url}" if entry is not None else f"no login for {url}"
    _emit({"hub": url, "logged_out": entry is not None}, as_json, text)


@app.command()
def whoami(as_json: JsonFlag = False) -> None:
    """Who this CLI is on the hub, and with what scope."""
    me = _hub("GET", "/api/v1/auth/me")
    _emit(me, as_json, f"{me['user']} · {me['scope']} · auth {me['auth']}")


@app.command()
def pair(
    user: Annotated[str | None, typer.Option("--user", help="User (default: you).")] = None,
    new_user: Annotated[bool, typer.Option("--new-user", help="Create the user.")] = False,
    scope: Annotated[str, typer.Option("--scope", help="read, launch, or admin.")] = "launch",
    client: Annotated[str, typer.Option("--client", help="browser, cli, or host.")] = "browser",
    ttl: Annotated[int, typer.Option("--ttl", min=1, max=300, help="Seconds (at most 300).")] = 300,
    url: Annotated[str | None, typer.Option("--url", help="Hub URL.")] = None,
    as_json: JsonFlag = False,
) -> None:
    """Make a one-time pairing link (5 min) and its QR code."""
    from hypothex.mcp.server import hub_call, hub_url, resolve_hub_token

    if scope not in SCOPES:
        raise ConfigError(f"--scope must be one of {', '.join(SCOPES)}")
    if client not in ("browser", "cli", "host"):
        raise ConfigError("--client must be browser, cli, or host")
    if client == "host" and scope != "admin":
        raise ConfigError("--client host needs --scope admin")  # AuthStore.redeem refuses less
    base = (url or hub_url()).rstrip("/")
    body = {
        "user": user,
        "new_user": new_user,
        "scope": scope,
        "ttl_seconds": ttl,
        "client_hint": client,
    }
    token = resolve_hub_token(base, _home_path())
    offer = hub_call("POST", "/api/v1/auth/pairings", body, url=base, token=token)
    if as_json:
        _print_json(offer)
        return
    typer.echo(offer["qr"])
    typer.echo(offer["url"])
    typer.echo(f"{user or 'you'} · {scope} · {ttl // 60}:{ttl % 60:02d}")


def _age(when: str) -> str:
    from datetime import datetime

    from hypothex.core.ids import utcnow
    from hypothex.notify.messages import fmt_duration

    return fmt_duration((utcnow() - datetime.fromisoformat(when)).total_seconds())


@sessions_app.command("list")
def sessions_list(
    all_users: Annotated[bool, typer.Option("--all", help="Everyone's (admin).")] = False,
    as_json: JsonFlag = False,
) -> None:
    """List active sessions (yours, or everyone's with --all)."""
    if all_users:
        rows = _hub("GET", "/api/v1/auth/sessions")
    else:
        me = _hub("GET", "/api/v1/auth/me")
        rows = _hub("GET", f"/api/v1/auth/sessions?user={me['user']}")
    if as_json:
        _print_json(rows)
        return
    _table(
        ["session", "user", "client", "device", "scope", "seen"],
        [
            [s["id"], s["user"], s["client"], s["device"], s["scope"], _age(s["last_seen_at"])]
            for s in rows
        ],
    )


@sessions_app.command("revoke")
def sessions_revoke(session_id: str, as_json: JsonFlag = False) -> None:
    """Revoke a session (yours, or anyone's as admin)."""
    path = f"/api/v1/auth/sessions/{session_id}/revoke"
    out = _hub("POST", path, {"command_id": new_command_id()})
    _emit(out, as_json, f"revoked {session_id}")


@users_app.command("list")
def users_list(as_json: JsonFlag = False) -> None:
    """List users and their roles (admin)."""
    rows = _hub("GET", "/api/v1/auth/users")
    if as_json:
        _print_json(rows)
        return
    _table(
        ["user", "role", "disabled"],
        [[u["name"], u["role"], "×" if u["disabled_at"] else None] for u in rows],
    )


@users_app.command("disable")
def users_disable(name: str, as_json: JsonFlag = False) -> None:
    """Disable a user and revoke their sessions (admin)."""
    out = _hub("POST", f"/api/v1/auth/users/{name}/disable", {"command_id": new_command_id()})
    _emit(out, as_json, f"disabled {name}")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/cli/test_auth_cli.py tests/mcp/test_remote_helpers.py -v`
Expected: `tests/cli/test_auth_cli.py` `6 passed`; the hub-client helper tests still pass (a login for another URL is never used).

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check src`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/hypothex/mcp/server.py src/hypothex/cli/main.py tests/cli/test_auth_cli.py
git commit -m "feat(cli): pair, login, logout, whoami, sessions, and users"
```

---

### Task 42: Client mode for reads, `hx runs --owner`, and `hx hosts pair`

**Files:**
- Modify: `src/hypothex/cli/main.py` (`_client_hub`; `projects`, `tasks`, `runs --owner` read through a logged-in hub; `hx hosts pair`; `hx hosts add --token-env/--pair`)
- Test: `tests/cli/test_auth_cli.py` (append)

**Interfaces:**
- Consumes: `hub_login` (Task 7), `save_host_token` (Task 38), `_redeem` (Task 41).
- Produces (contract 4, exact): `hx runs --owner me|NAME`; `hx hosts add <name> --url URL [--token-env VAR | --pair PAIRING_URL]`; `hx hosts pair <name> <pairing-url>` (redeems as `host`, writes `host-tokens.json`, reconnects the host through a running hub).
- Produces (public helper): `_client_hub() -> str | None` (the hub URL when this home holds a login for it).
- Rules: in client mode `projects`, `tasks`, and `runs` print the hub's data in the same shape as phase 1; `--owner me` asks the hub who "me" is (client mode, or a hub running on this machine), else it is an error; a hub with auth off answers `auth: "off"`, and `me` then filters nothing (runs have no owner; every run is the caller's), like the API.

- [ ] **Step 1: Write the failing test**

Append to `tests/cli/test_auth_cli.py` (and add `from hypothex.api.app import create_app`, `from hypothex.auth.pairing import pairing_url`, `from hypothex.remote.config import HostSpec, load_host_tokens, load_hosts`, `from tests.api.authkit import OWNER`, `from tests.api.envserver import write_hosts`, `from tests.factories import make_record`):

```python
def test_a_logged_in_cli_reads_the_hub(tmp_path: Path, hub: tuple[str, AuthStore]) -> None:
    url, store = hub
    laptop = login_alice(tmp_path, url, store)
    assert [p["project"] for p in hx(laptop, "projects")] == ["toy"]
    assert {t["name"] for t in hx(laptop, "tasks")} == {"toy-acc", "toy-broken"}
    hub_ctx = Context.open(tmp_path / "hub-home")
    for run_id, owner in (("a1", "alice"), ("s1", "sv")):
        hub_ctx.create_run(
            make_record(run_id, owner=owner, environment_id=hub_ctx.descriptor.environment_id)
        )
    assert [r["run_id"] for r in hx(laptop, "runs", "--owner", "me")] == ["a1"]
    assert {r["run_id"] for r in hx(laptop, "runs")} == {"a1", "s1"}


def test_owner_me_needs_a_hub(tmp_path: Path) -> None:
    assert "hub" in fails(tmp_path / "solo", "runs", "--owner", "me")


def test_hosts_pair_and_add_with_a_token_env(tmp_path: Path) -> None:
    lab = create_app(tmp_path / "lab", background_repair=False, kind="ssh", auth=True)
    lab_store: AuthStore = lab.state.auth
    lab_store.ensure_owner("sv")
    with serve_app(lab) as lab_url:
        hub_home = tmp_path / "hub-home"
        other = HostSpec(route="url", url="http://127.0.0.1:9")
        write_hosts(hub_home, {"lab": HostSpec(route="url", url=lab_url), "other": other})
        offer, secret = lab_store.create_offer(issuer=OWNER, user="sv", scope="admin")
        link = pairing_url(lab_url, offer.id, secret)
        assert "the link is for" in fails(hub_home, "hosts", "pair", "other", link)
        out = hx(hub_home, "hosts", "pair", "lab", link)  # the refused try did not use it
        assert (out["name"], out["user"], out["scope"]) == ("lab", "sv", "admin")
        paired = load_host_tokens(Context.open(hub_home).layout)["lab"]
        assert paired["url"] == lab_url.rstrip("/")
        assert lab_store.authenticate(paired["token"]) is not None
        added = hx(hub_home, "hosts", "add", "lab2", "--url", lab_url, "--token-env", "LAB_TOKEN")
        assert added["host"]["token_env"] == "LAB_TOKEN"
        offer2, secret2 = lab_store.create_offer(issuer=OWNER, user="sv", scope="admin")
        hx(
            hub_home,
            "hosts",
            "add",
            "lab3",
            "--url",
            lab_url,
            "--pair",
            pairing_url(lab_url, offer2.id, secret2),
        )
    layout = Context.open(hub_home).layout
    assert set(load_host_tokens(layout)) == {"lab", "lab3"}
    assert load_hosts(layout).environments["lab2"].token_env == "LAB_TOKEN"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/cli/test_auth_cli.py -v`
Expected: FAIL: `test_a_logged_in_cli_reads_the_hub` lists no projects (the laptop's home is empty), `test_owner_me_needs_a_hub` with `No such option: --owner`, and `test_hosts_pair_and_add_with_a_token_env` with `No such command 'pair'`.

- [ ] **Step 3: Write the implementation**

In `src/hypothex/cli/main.py`:

1. Add after `_hub_try`:

```python
def _client_hub() -> str | None:
    """The hub URL when this home logged in to it (`hx login`): reads go through it."""
    from hypothex.auth.client import hub_login
    from hypothex.mcp.server import hub_url

    url = hub_url()
    return url if hub_login(Layout(_home_path()), url) is not None else None


def _me() -> str | None:
    """
    The caller's user name on the hub (client mode, or a hub on this machine).

    None when the hub has auth off: runs then have no owner and every run is
    the caller's, so ``--owner me`` filters nothing (the API does the same).
    """
    me = _hub_try("GET", "/api/v1/auth/me")
    if me is None:
        raise ConfigError("--owner me needs a hub: run hx serve, or hx login <pairing-url>")
    return None if me.get("auth") == "off" else str(me["user"])
```

2. Replace the bodies of `projects` and `tasks` with:

```python
@app.command()
def projects(as_json: JsonFlag = False) -> None:
    """List projects."""
    if _client_hub() is not None:
        rows = [
            {"project": p["project"], "repo": p["repo"], "tasks": p["tasks"]}
            for p in _hub("GET", "/api/v1/projects")
        ]
    else:
        rows = [
            {"project": e.project, "repo": e.repo, "tasks": sorted(e.config.tasks)}
            for e in q.list_projects(_ctx())
        ]
    if as_json:
        _print_json(rows)
        return
    _table(
        ["project", "repo", "tasks"],
        [[r["project"], r["repo"], ", ".join(r["tasks"])] for r in rows],
    )


@app.command()
def tasks(project: ProjectOpt = None, as_json: JsonFlag = False) -> None:
    """List tasks with their dataset, metric versions, and best score."""
    if _client_hub() is not None:
        path = "/api/v1/tasks" + (f"?project={project}" if project else "")
        items = [q.TaskSummary.model_validate(t) for t in _hub("GET", path)]
    else:
        items = q.list_tasks(_ctx(), project)
    if as_json:
        _print_json(items)
        return
    _table(
        ["task", "dataset", "metrics", "primary", "runs", "best"],
        [
            [
                f"{t.project}/{t.name}",
                f"{t.dataset}@{t.dataset_version}",
                ", ".join(f"{m}@{v}" for m, v in t.metrics.items()),
                t.primary,
                t.n_runs,
                None if t.best is None else f"{t.best:.4f}",
            ]
            for t in items
        ],
    )
```

3. Replace `list_runs_cmd` with:

```python
@app.command("runs")
def list_runs_cmd(
    project: ProjectOpt = None,
    task: TaskOpt = None,
    status: Annotated[RunStatus | None, typer.Option(help="Filter by status.")] = None,
    tag: Annotated[str | None, typer.Option(help="Filter by tag.")] = None,
    owner: Annotated[
        str | None, typer.Option("--owner", help="Runs of this user; `me` for yours.")
    ] = None,
    archived: Annotated[bool, typer.Option(help="Include archived runs.")] = False,
    limit: Annotated[int, typer.Option(help="Maximum rows.")] = 50,
    as_json: JsonFlag = False,
) -> None:
    """List runs, newest first."""
    if _client_hub() is not None:
        from urllib.parse import urlencode

        params = {
            "project": project,
            "task": task,
            "status": status.value if status else None,
            "tag": tag,
            "owner": owner,
            "archived": "true" if archived else None,
            "limit": limit,
        }
        query = urlencode({k: v for k, v in params.items() if v is not None})
        records = [RunRecord.model_validate(r) for r in _hub("GET", f"/api/v1/runs?{query}")]
    else:
        who = _me() if owner == "me" else owner
        records = _ctx().index.list_runs(
            project=project,
            task=task,
            status=status,
            tag=tag,
            owner=who,
            include_archived=archived,
            limit=limit,
        )
    if as_json:
        _print_json(records)
        return
    _table(
        ["run", "task", "status", "owner", "created", "hypothesis"],
        [
            [
                r.run_id,
                r.task,
                r.status.value,
                f"@{r.owner}" if r.owner else None,
                r.created_at.strftime("%Y-%m-%d %H:%M"),
                r.hypothesis[:50],
            ]
            for r in records
        ],
    )
```

4. Add to `hosts_add` two options after `usd`:

```python
    token_env: Annotated[
        str | None, typer.Option("--token-env", help="Variable holding a --url host's token.")
    ] = None,
    pair_link: Annotated[
        str | None, typer.Option("--pair", help="Pairing link from the --url host's hx pair.")
    ] = None,
```

   refuse them without `--url` (add after the `--partition` check):

```python
    if (token_env or pair_link) and url is None:
        raise ConfigError("--token-env and --pair are for --url hosts")
    if token_env and pair_link:
        raise ConfigError("give --token-env or --pair, not both")
```

   pass `token_env=token_env,` to `HostSpec(...)`, and right after `save_hosts(...)` add:

```python
    paired = _pair_host(c, name, url, pair_link) if pair_link and url else None
```

   and add `"paired": paired,` to the JSON output dict.

5. Add the helper and the command:

```python
def _pair_host(c: Context, name: str, host_url: str, link: str) -> dict[str, Any]:
    """Redeem a host's pairing link as `host`; keep the token bound to that host's URL."""
    from hypothex.auth.pairing import parse_pairing_url
    from hypothex.remote.config import same_origin, save_host_token

    base, _, _ = parse_pairing_url(link)
    if not same_origin(base, host_url):
        # never redeem (or later send) one server's token for another host name
        raise ConfigError(f"the link is for {base}, but {name} is {host_url}")
    _, data = _redeem(link, "host", f"hub:{_device()}")
    save_host_token(c.layout, name, base, data["token"])
    return {"user": data["user"], "scope": data["scope"], "session_id": data["session_id"]}


@hosts_app.command("pair")
def hosts_pair(
    name: Annotated[str, typer.Argument(help="A --url host from `hx hosts list`.")],
    pairing: Annotated[str, typer.Argument(help="The link its owner made with hx pair.")],
    as_json: JsonFlag = False,
) -> None:
    """Pair the hub with a --url host (a lab server with auth on); then reconnect it."""
    c, hosts = _hosts()
    spec = _known_host(hosts, name)
    if spec.route != "url":
        raise ConfigError(f"{name} is reached over ssh; it needs no pairing")
    paired = _pair_host(c, name, str(spec.url), pairing)
    state = _hub_try("POST", f"/api/v1/hosts/{name}/connect", {})
    out = {"name": name, **paired, "state": state}
    text = f"✓ {name} paired · {paired['user']} · {paired['scope']}"
    _emit(out, as_json, text + (f" · {state['state']}" if state else ""))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/cli -v`
Expected: `tests/cli/test_auth_cli.py` `9 passed`; the phase 1–2 CLI tests (`projects`, `tasks`, `runs`, `hosts add`) still pass.

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check src`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/cli/main.py tests/cli/test_auth_cli.py
git commit -m "feat(cli): read through a logged-in hub, runs --owner, and hosts pair"
```

---
### Task 43: `hx export`, `hx note --project`, `hx notebook`, `hx digest`

**Files:**
- Modify: `src/hypothex/cli/main.py` (commands, the `notebook` group, `parse_duration`)
- Test: `tests/cli/test_team_cli.py`

**Interfaces:**
- Consumes: `task_table`, `compare_table`, `render`, `ExportOptions` (Tasks 10–12), `append_entry`/`list_days`/`read_day`/`parse_day`/`today` (Task 8), `build_digest`/`render_digest_markdown`/`send_digest` (Tasks 18–19), the team routes (Task 29) in client mode, `hub_call(text=True)` (Task 41).
- Produces (contract 4, exact): `hx export <task> [-p P] [--format latex|markdown|csv] [--metrics a,b] [--noise both|seed|test|none] [--digits 3] [--percent] [--top N] [--groups g1,g2] [--no-baselines] [--caption C] [--label L] [--standalone] [-o FILE]` and `hx export --runs a,b[,c…] [same options]` (`--json`: `{format, text, table}`; `table` is null in client mode); `hx note --project P <text> [--day YYYY-MM-DD]` (and `hx note <run_id> <text>` unchanged); `hx notebook list -p P`, `hx notebook show -p P [--day D]`; `hx digest [-p P] [--since 7d] [--send] [--channels slack,email]` (all projects without `-p`; `--send` through the running hub, else locally into this home's outbox and notebook).
- Produces (public helper): `parse_duration(text) -> timedelta` (`Nh`, `Nd`, `Nw`).

- [ ] **Step 1: Write the failing test**

Create `tests/cli/test_team_cli.py`:

```python
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from hypothex.cli.main import app, parse_duration
from hypothex.core.context import Context
from hypothex.core.evaluation import evaluate_run
from hypothex.core.settings import NotifySettings, Settings, SlackSettings, save_settings
from tests.factories import PREDS_075, seed_finished_run

runner = CliRunner()
PREDS_025 = [{"id": f"ex-{i}", "prediction": 1} for i in range(4)]


def hx(*args: str, input: str | None = None) -> Any:
    result = runner.invoke(app, [*args, "--json"], input=input, catch_exceptions=False)
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def text(*args: str) -> str:
    result = runner.invoke(app, list(args), catch_exceptions=False)
    assert result.exit_code == 0, result.output
    return result.stdout


@pytest.fixture
def scored(ctx: Context, toy_repo: Path) -> Context:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    seed_finished_run(ctx, toy_repo, "r2", predictions=PREDS_025, config_hash="sha256:bbbb")
    evaluate_run(ctx, "r1")
    evaluate_run(ctx, "r2")
    return ctx


def test_parse_duration() -> None:
    assert parse_duration("30d") == timedelta(days=30)
    assert parse_duration("12h") == timedelta(hours=12)
    assert parse_duration("2w") == timedelta(days=14)
    with pytest.raises(Exception, match="30d"):
        parse_duration("soon")


def test_export_a_task(scored: Context, tmp_path: Path) -> None:
    md = text("export", "toy-acc")
    assert md.startswith("| group | n | accuracy/value ↑ |")
    out = hx("export", "toy-acc", "--format", "latex", "--digits", "2")
    assert out["format"] == "latex" and out["text"].startswith("% requires")
    assert [r["kind"] for r in out["table"]["rows"]] == ["group", "group"]
    target = tmp_path / "table.csv"
    assert (
        text("export", "toy/toy-acc", "--format", "csv", "-o", str(target)).strip()
        == f"wrote {target}"
    )
    assert target.read_text().startswith("kind,label,key,n,metric")


def test_export_runs(scored: Context) -> None:
    out = hx("export", "--runs", "r1,r2")
    assert out["text"].splitlines()[2] == "| r1 | 1 | **0.750** |"
    result = runner.invoke(app, ["export"])
    assert result.exit_code == 1 and "give a task, or --runs" in str(result.exception)


def test_note_to_the_project_notebook(scored: Context) -> None:
    day = hx("note", "--project", "toy", "r1 beats r2 [[run:r1]]", "--day", "2026-10-04")
    assert day["day"] == "2026-10-04" and "— human" in day["text"]
    hx("note", "r1", "a run note")  # phase 1 form still works
    assert "a run note" in scored.store.read_notes("toy", "r1")


def test_notebook_list_and_show(scored: Context) -> None:
    hx("note", "--project", "toy", "see [[run:r1]]", "--day", "2026-10-04")
    assert hx("notebook", "list", "-p", "toy")[0]["day"] == "2026-10-04"
    shown = hx("notebook", "show", "-p", "toy", "--day", "2026-10-04")
    assert shown["runs"][0]["run_id"] == "r1"
    rendered = text("notebook", "show", "-p", "toy", "--day", "2026-10-04")
    assert "see [[run:r1]]" in rendered and "r1" in rendered.splitlines()[-1]


def test_digest_prints_and_sends_locally(scored: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HX_TEST_HOOK", "http://127.0.0.1:9/services/T/B/x")
    save_settings(
        scored.layout,
        Settings(notify=NotifySettings(slack=SlackSettings(webhook_env="HX_TEST_HOOK"))),
    )
    (digest,) = hx("digest", "-p", "toy", "--since", "7d")
    assert digest["digest"]["counts"]["started"] == 2 and digest["sent"] is None
    assert text("digest", "-p", "toy").startswith("**")
    (sent,) = hx("digest", "-p", "toy", "--send")
    assert sent["sent"]["channels"] == ["slack"]
    assert list((scored.layout.home / "notify" / "outbox").glob("*.slack.json"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/cli/test_team_cli.py -v`
Expected: FAIL at collection with `ImportError: cannot import name 'parse_duration' from 'hypothex.cli.main'`.

- [ ] **Step 3: Write the commands**

In `src/hypothex/cli/main.py`:

1. Add after the `users_app` block:

```python
notebook_app = typer.Typer(no_args_is_help=True, help="The project lab notebook.")
app.add_typer(notebook_app, name="notebook")
ProjectReq = Annotated[str, typer.Option("--project", "-p", help="Project name.")]
DURATION = re.compile(r"^(\d+)([hdw])$")
```

2. Add helpers (after `_client_hub`):

```python
def parse_duration(text: str) -> timedelta:
    """
    Parse ``Nh``, ``Nd``, or ``Nw``.

    Parameters
    ----------
    text : str

    Returns
    -------
    timedelta

    Raises
    ------
    ConfigError
        Anything else.

    Examples
    --------
    >>> parse_duration("30d").days
    30
    """
    match = DURATION.match(text.strip())
    if match is None:
        raise ConfigError(f"duration must look like 30d, 12h, or 2w; got {text!r}")
    n, unit = int(match.group(1)), match.group(2)
    if unit == "h":
        return timedelta(hours=n)
    return timedelta(days=n * (7 if unit == "w" else 1))


def _split(value: str | None) -> list[str] | None:
    items = [v.strip() for v in (value or "").split(",") if v.strip()]
    return items or None


def _hub_text(path: str, params: dict[str, Any]) -> str:
    from urllib.parse import urlencode

    from hypothex.mcp.server import hub_call

    query = urlencode({k: v for k, v in params.items() if v is not None})
    return hub_call("GET", f"{path}?{query}", token=_hub_token(), text=True)
```

   and add `from datetime import timedelta` to the module imports.

3. Add the commands:

```python
@app.command()
def export(
    task: Annotated[str | None, typer.Argument(help="Task, or project/task.")] = None,
    project: ProjectOpt = None,
    runs: Annotated[str | None, typer.Option("--runs", help="Compare runs: a,b[,c...].")] = None,
    fmt: Annotated[str, typer.Option("--format", help="latex, markdown, or csv.")] = "markdown",
    metrics: Annotated[str | None, typer.Option("--metrics", help="a,b (metric/key).")] = None,
    noise: Annotated[str, typer.Option("--noise", help="both, seed, test, or none.")] = "both",
    digits: Annotated[int, typer.Option("--digits", min=0, max=6)] = 3,
    percent: Annotated[bool, typer.Option("--percent", help="x100 for fractions.")] = False,
    top: Annotated[int | None, typer.Option("--top", min=1)] = None,
    groups: Annotated[str | None, typer.Option("--groups", help="g1,g2 (id or label).")] = None,
    no_baselines: Annotated[bool, typer.Option("--no-baselines")] = False,
    caption: Annotated[str | None, typer.Option("--caption")] = None,
    label: Annotated[str | None, typer.Option("--label")] = None,
    standalone: Annotated[bool, typer.Option("--standalone", help="LaTeX table env.")] = False,
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Write to FILE.")] = None,
    as_json: JsonFlag = False,
) -> None:
    """Export a leaderboard (or runs) as a paper table: LaTeX booktabs, Markdown, or CSV."""
    from hypothex.core import export as ex

    if (task is None) == (runs is None):
        raise ConfigError("give a task, or --runs a,b")
    try:
        opts = ex.ExportOptions.model_validate(
            {
                "format": fmt,
                "metrics": _split(metrics),
                "noise": noise,
                "digits": digits,
                "percent": percent,
                "top": top,
                "groups": _split(groups),
                "baselines": not no_baselines,
                "caption": caption,
                "label": label,
                "standalone": standalone,
            }
        )
    except ValidationError as exc:
        raise ConfigError(f"invalid export options: {exc.errors()[0]['msg']}") from None
    table: ex.ExportTable | None = None
    if _client_hub() is not None:
        params = opts.model_dump(mode="json")
        for key in ("metrics", "groups"):
            params[key] = ",".join(params[key]) if params[key] else None
        if runs is not None:
            body = _hub_text("/api/v1/compare/export", {**params, "run_ids": runs})
        else:
            assert task is not None
            proj, sep, name = task.partition("/")
            if not sep:
                proj, name = project or "", task
            if not proj:
                raise ConfigError("give -p PROJECT (or project/task): the hub needs it")
            body = _hub_text(f"/api/v1/tasks/{proj}/{name}/export", params)
    else:
        c = _ctx()
        if runs is not None:
            table = ex.compare_table(c, _split(runs) or [], opts)
        else:
            assert task is not None
            table = ex.task_table(c, task, project, opts)
        body = ex.render(table, opts)
    if output is not None:
        output.write_text(body, encoding="utf-8")
    if as_json:
        _print_json({"format": opts.format, "text": body, "table": table})
        return
    if output is not None:
        typer.echo(f"wrote {output}")
    else:
        typer.echo(body, nl=False)
```

4. Replace the `note` command with:

```python
@app.command()
def note(
    args: Annotated[list[str], typer.Argument(help="RUN_ID TEXT, or TEXT with --project.")],
    project: ProjectOpt = None,
    day: Annotated[str | None, typer.Option("--day", help="YYYY-MM-DD (default today).")] = None,
    author: Annotated[str | None, typer.Option(help="Author (default: human/agent).")] = None,
    as_json: JsonFlag = False,
) -> None:
    """Add a note to a run, or with --project an entry to the project's lab notebook."""
    from hypothex.core import notebook

    if project is None:
        if len(args) != 2:
            raise ConfigError("usage: hx note RUN_ID TEXT (or hx note --project P TEXT)")
        run_id, body = args
        sent = _through_hub(run_id, "notes", {"text": body, "author": author or _created_by()})
        if sent is None:
            q.add_note(_ctx(), run_id, body, author or _created_by())
        _emit({"ok": True}, as_json, "noted")
        return
    if len(args) != 1:
        raise ConfigError("usage: hx note --project P TEXT")
    when = notebook.parse_day(day) if day else None
    if _client_hub() is not None:
        target = when.isoformat() if when else "today"  # the hub picks its own today
        path = f"/api/v1/projects/{project}/notebook/{target}"
        out = _hub("POST", path, {"text": args[0], "command_id": new_command_id()})
    else:
        entry = notebook.append_entry(_ctx(), project, args[0], author or _created_by(), day=when)
        out = to_jsonable(entry)
    _emit(out, as_json, f"noted · {project} {out['day']}")
```

5. Add the notebook commands:

```python
@notebook_app.command("list")
def notebook_list(project: ProjectReq, as_json: JsonFlag = False) -> None:
    """List a project's notebook days, newest first."""
    from hypothex.core import notebook

    if _client_hub() is not None:
        days = _hub("GET", f"/api/v1/projects/{project}/notebook")
    else:
        days = notebook.list_days(_ctx(), project)
    if as_json:
        _print_json(days)
        return
    _table(["day", "entries", "bytes"], [[d["day"], d["entries"], d["bytes"]] for d in days])


@notebook_app.command("show")
def notebook_show(
    project: ProjectReq,
    day: Annotated[str | None, typer.Option("--day", help="YYYY-MM-DD (default today).")] = None,
    as_json: JsonFlag = False,
) -> None:
    """Show one notebook day, then its run chips as `run status primary`."""
    from hypothex.core import notebook

    when = notebook.parse_day(day) if day else None
    if _client_hub() is not None:
        target = when.isoformat() if when else "today"  # the hub picks its own today
        data = _hub("GET", f"/api/v1/projects/{project}/notebook/{target}")
    else:
        c = _ctx()
        data = to_jsonable(notebook.read_day(c, project, when or notebook.hub_today(c)))
    if as_json:
        _print_json(data)
        return
    typer.echo(data["text"].rstrip() or "—")
    if data["runs"]:
        _table(
            ["run", "status", "primary"],
            [
                [
                    r["run_id"],
                    r["status"] or "?",
                    None if r["primary"] is None else f"{r['primary']:.3f}",
                ]
                for r in data["runs"]
            ],
        )
```

6. Add the digest command:

```python
@app.command()
def digest(
    project: ProjectOpt = None,
    since: Annotated[str, typer.Option("--since", help="Window: 7d, 12h, 2w.")] = "7d",
    send: Annotated[
        bool, typer.Option("--send", help="Send it and save it to the notebook.")
    ] = False,
    channels: Annotated[str | None, typer.Option("--channels", help="slack,email.")] = None,
    as_json: JsonFlag = False,
) -> None:
    """Print the weekly digest (all projects without -p); --send enqueues it."""
    from hypothex.core import digest as dg
    from hypothex.core.ids import utcnow
    from hypothex.core.settings import load_settings

    now = utcnow()
    start = now - parse_duration(since)
    client = _client_hub() is not None
    c = None if client else _ctx()
    if project is not None:
        projects = [project]
    elif c is None:
        projects = [p["project"] for p in _hub("GET", "/api/v1/projects")]
    else:
        projects = [e.project for e in c.store.list_projects()]
    out: list[dict[str, Any]] = []
    for name in projects:
        if c is None:
            from urllib.parse import quote

            found = _hub("GET", f"/api/v1/projects/{name}/digest?since={quote(start.isoformat())}")
        else:
            top = load_settings(c.layout).digest.top_notes
            found = to_jsonable(dg.build_digest(c, name, since=start, until=now, top_notes=top))
        sent = None
        if send:
            body = {
                "since": start.isoformat(),
                "channels": _split(channels),
                "command_id": new_command_id(),
            }
            sent = _hub_try("POST", f"/api/v1/projects/{name}/digest/send", body)
            if sent is None:
                local = c or _ctx()
                settings = load_settings(local.layout)
                wanted = cast("list[Any] | None", _split(channels))
                done = dg.send_digest(local, settings, name, now=now, channels=wanted, since=start)
                day = None
                if settings.digest.save_to_notebook:
                    from hypothex.core.notebook import today

                    day = today(now, settings.digest.timezone).isoformat()
                sent = {"channels": done, "notebook_day": day}
        out.append({"project": name, "digest": found, "sent": sent})
    if as_json:
        _print_json(out)
        return
    for item in out:
        typer.echo(dg.render_digest_markdown(dg.Digest.model_validate(item["digest"])), nl=False)
        if item["sent"] is not None:
            typer.echo(f"sent · {', '.join(item['sent']['channels']) or 'no channel'}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/cli/test_team_cli.py tests/cli/test_cli.py -v`
Expected: `tests/cli/test_team_cli.py` `6 passed`; the phase 1 `hx note RUN TEXT` tests in `tests/cli/test_cli.py` still pass.

Run: `uv run python -m doctest src/hypothex/cli/main.py && uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check src`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/cli/main.py tests/cli/test_team_cli.py
git commit -m "feat(cli): export tables, project notes, notebook, and digest commands"
```

---

### Task 44: `hx notify status|test` and `hx storage report|clean`

**Files:**
- Modify: `src/hypothex/core/storage.py` (`fmt_bytes`)
- Modify: `src/hypothex/cli/main.py` (the `notify` and `storage` groups)
- Test: `tests/cli/test_team_cli.py` (append)

**Interfaces:**
- Consumes: `notify_status`, `Notifier.send_test` (Task 30), `storage_report`, `plan_clean`, `apply_clean`, `plans_dir`, `PLAN_ID` (Tasks 20–22), the hub routes (Tasks 30–31) when a hub answers.
- Produces (contract 4, exact): `hx notify status` (channels `●`/`○` with the variable name, recent sends), `hx notify test slack|email` (exit 1 when it fails); `hx storage report [-p P] [--local-only]` (bytes by project, host, kind, and the 20 largest items); `hx storage clean --archived [--older-than 30d] [--kind checkpoint …|--all-kinds] [-p P] [--host H] [--no-pulled] [--dry-run]` (always a dry run: prints the plan id, items, refusals, and the total; refuses without `--archived`); `hx storage clean --apply <plan_id> [--yes]` (asks to type the total unless `--yes`; prints freed bytes).
- Produces (additive): `hx storage clean --apply <id> --confirm-bytes N` (for a plan made on another machine: the total to confirm); `fmt_bytes(n) -> str` (`1.8 TB`, `412.3 GB`; base 1000) in `hypothex.core.storage`.
- Rules: both groups try the running hub first and fall back to this home; `hx storage clean` never deletes without an applied plan and the exact total.

- [ ] **Step 1: Write the failing test**

Append to `tests/cli/test_team_cli.py` (and add `from hypothex.core.ids import utcnow`, `from hypothex.core.records import Artifact, RunStatus`, `from hypothex.core.storage import fmt_bytes`, `from tests.factories import make_record`, `from tests.fakes.webhook import FakeWebhook`):

```python
def archived(ctx: Context, run_id: str, artifact: Path) -> None:
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"x" * 30_000)
    ended = utcnow() - timedelta(days=40)
    ctx.create_run(
        make_record(
            run_id,
            status=RunStatus.FINISHED,
            archived=True,
            started_at=ended,
            ended_at=ended,
            artifacts=[Artifact(kind="checkpoint", path=str(artifact))],
            environment_id=ctx.descriptor.environment_id,
        )
    )


def test_fmt_bytes() -> None:
    assert [fmt_bytes(n) for n in (512, 4096, 412_300_000_000, 1_840_000_000_000)] == [
        "512 B",
        "4.1 KB",
        "412.3 GB",
        "1.8 TB",
    ]


def test_notify_status_and_test(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    with FakeWebhook() as hook:
        monkeypatch.setenv("HX_TEST_HOOK", hook.url)
        save_settings(
            ctx.layout,
            Settings(notify=NotifySettings(slack=SlackSettings(webhook_env="HX_TEST_HOOK"))),
        )
        status = hx("notify", "status")
        assert status["channels"]["slack"] == {
            "configured": True,
            "env": "HX_TEST_HOOK",
            "set": True,
        }
        shown = text("notify", "status")
        assert "slack ● set HX_TEST_HOOK" in shown and hook.secret not in shown
        assert hx("notify", "test", "slack") == {"ok": True, "error_class": None}
        assert hook.requests[0]["body"]["text"] == "✓ hypothex test · slack"
        monkeypatch.delenv("HX_TEST_HOOK")
        result = runner.invoke(app, ["notify", "test", "slack"])
        assert result.exit_code == 1 and "✗ slack unset:HX_TEST_HOOK" in result.stdout


def test_storage_report(ctx: Context, tmp_path: Path) -> None:
    archived(ctx, "old", tmp_path / "scratch" / "old.pt")
    report = hx("storage", "report", "--local-only")
    assert report["total_bytes"] > 0 and report["errors"] == []
    shown = text("storage", "report")
    assert shown.splitlines()[0].endswith("items") and "old.pt" in shown


def test_storage_clean_plans_then_applies(ctx: Context, tmp_path: Path) -> None:
    artifact = tmp_path / "scratch" / "old.pt"
    archived(ctx, "old", artifact)
    refused = runner.invoke(app, ["storage", "clean"])
    assert refused.exit_code == 1 and "--archived" in str(refused.exception)
    plan = hx("storage", "clean", "--archived", "--older-than", "30d", "--dry-run")
    assert [i["run_id"] for i in plan["items"]] == ["old"] and artifact.exists()
    shown = text("storage", "clean", "--archived")
    assert "hx storage clean --apply cp-" in shown
    wrong = runner.invoke(app, ["storage", "clean", "--apply", plan["plan_id"]], input="1\n")
    assert wrong.exit_code == 1 and "not confirmed" in str(wrong.exception) and artifact.exists()
    typed = f"{plan['total_bytes']}\n"
    done = runner.invoke(
        app, ["storage", "clean", "--apply", plan["plan_id"], "--json"], input=typed
    )
    assert done.exit_code == 0, done.output
    payload = done.stdout[done.stdout.index("{") :]  # the prompt line comes first
    assert json.loads(payload)["freed_bytes"] == plan["total_bytes"]
    assert not artifact.exists()


def test_apply_needs_a_known_total(ctx: Context) -> None:
    result = runner.invoke(app, ["storage", "clean", "--apply", "cp-0000000a", "--yes"])
    assert result.exit_code == 1 and "--confirm-bytes" in str(result.exception)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/cli/test_team_cli.py -v`
Expected: FAIL at collection with `ImportError: cannot import name 'fmt_bytes' from 'hypothex.core.storage'`.

- [ ] **Step 3: Write the implementation**

Append to `src/hypothex/core/storage.py`:

```python
def fmt_bytes(n: int | float) -> str:
    """
    Format a byte count tersely (base 1000).

    Parameters
    ----------
    n : int or float

    Returns
    -------
    str

    Examples
    --------
    >>> fmt_bytes(412_300_000_000)
    '412.3 GB'
    """
    value = float(n)
    if abs(value) < 1000:
        return f"{int(value)} B"
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1000
        if abs(value) < 1000 or unit == "TB":
            return f"{value:.1f} {unit}"
    return f"{value:.1f} TB"
```

In `src/hypothex/cli/main.py`, add after the `notebook_app` block:

```python
notify_app = typer.Typer(no_args_is_help=True, help="Slack and email notices (hub).")
app.add_typer(notify_app, name="notify")
storage_app = typer.Typer(no_args_is_help=True, help="Bytes on disk and cleanup of old artifacts.")
app.add_typer(storage_app, name="storage")
SENT_GLYPH = {"sent": "✓", "failed": "✗", "pending": "…", "sending": "…", "skipped": "○"}
```

and the commands:

```python
@notify_app.command("status")
def notify_status_cmd(as_json: JsonFlag = False) -> None:
    """Channel status (never a secret) and recent sends."""
    from hypothex.core.settings import load_settings
    from hypothex.notify.notifier import notify_status

    data = _hub_try("GET", "/api/v1/notify")
    if data is None:
        c = _ctx()
        data = notify_status(c, load_settings(c.layout))
    if as_json:
        _print_json(data)
        return
    for name in ("slack", "email"):
        channel = data["channels"][name]
        state = "set" if channel["set"] else ("unset" if channel["configured"] else "off")
        mark = "●" if channel["configured"] and channel["set"] else "○"
        typer.echo(f"{name} {mark} {state}" + (f" {channel['env']}" if channel["env"] else ""))
    if data["recent"]:
        _table(
            ["time", "kind", "run", "channel", "", "tries", "error"],
            [
                [
                    str(e["created_at"])[11:16],
                    e["notice"]["kind"],
                    e["notice"]["run_id"] or e["notice"]["project"],
                    e["channel"],
                    SENT_GLYPH.get(e["status"], "?"),
                    e["attempts"],
                    e["last_error"],
                ]
                for e in data["recent"]
            ],
        )


@notify_app.command("test")
def notify_test_cmd(
    channel: Annotated[str, typer.Argument(help="slack or email.")], as_json: JsonFlag = False
) -> None:
    """Send a test notice now (through the hub when it runs)."""
    from hypothex.core.settings import load_settings
    from hypothex.notify.notifier import Notifier

    if channel not in ("slack", "email"):
        raise ConfigError("channel must be slack or email")
    data = _hub_try(
        "POST", "/api/v1/notify/test", {"channel": channel, "command_id": new_command_id()}
    )
    if data is None:
        c = _ctx()
        data = Notifier(c, load_settings(c.layout)).send_test(channel)  # type: ignore[arg-type]
    shown = f"✓ {channel}" if data["ok"] else f"✗ {channel} {data['error_class']}"
    _emit(data, as_json, shown)
    if not data["ok"]:
        raise typer.Exit(1)


@storage_app.command("report")
def storage_report_cmd(
    project: ProjectOpt = None,
    local_only: Annotated[bool, typer.Option("--local-only", help="Skip hosts.")] = False,
    as_json: JsonFlag = False,
) -> None:
    """Bytes by project, host, and kind, and the 20 largest items."""
    from urllib.parse import urlencode

    from hypothex.core import storage as st

    query = urlencode(
        {
            k: v
            for k, v in {"project": project, "remote": "false" if local_only else None}.items()
            if v
        }
    )
    data = _hub_try("GET", f"/api/v1/storage?{query}")
    if data is None:
        data = to_jsonable(st.storage_report(_ctx(), None, project=project, remote=False))
    if as_json:
        _print_json(data)
        return
    typer.echo(f"{st.fmt_bytes(data['total_bytes'])} · {len(data['items'])} items")
    for title in ("by_project", "by_host", "by_kind"):
        _table(
            [title.removeprefix("by_"), "bytes"],
            [[k, st.fmt_bytes(v)] for k, v in data[title].items()],
        )
    largest = sorted(data["items"], key=lambda i: i["bytes"], reverse=True)[:20]
    _table(
        ["run", "host", "kind", "path", "bytes", ""],
        [
            [
                i["run_id"],
                i["host"],
                i["artifact_kind"] or i["kind"],
                i["path"],
                st.fmt_bytes(i["bytes"]),
                ("★" if i["starred"] else "") + ("archived" if i["archived"] else ""),
            ]
            for i in largest
        ],
    )
    for error in data["errors"]:
        typer.secho(f"{error['host']}: {error['error']}", fg="yellow", err=True)


def _apply_plan(plan_id: str, yes: bool, confirm_bytes: int | None, as_json: bool) -> None:
    from hypothex.core import storage as st

    total = confirm_bytes
    path = st.plans_dir(Layout(_home_path())) / f"{plan_id}.json"
    if total is None and st.PLAN_ID.match(plan_id) and path.is_file():
        total = st.CleanPlan.model_validate_json(path.read_text(encoding="utf-8")).total_bytes
    if total is None:
        raise ConfigError(
            f"plan {plan_id} is not in this home; pass --confirm-bytes N (the total it printed)"
        )
    if not yes:
        typed = typer.prompt(
            f"delete {st.fmt_bytes(total)}: type {total} to confirm", default="", show_default=False
        )
        if typed.strip() != str(total):
            raise ConfigError("not confirmed; nothing deleted")
    body = {"confirm_bytes": total, "command_id": new_command_id()}
    result = _hub_try("POST", f"/api/v1/storage/plans/{plan_id}/apply", body)
    if result is None:
        result = to_jsonable(
            st.apply_clean(_ctx(), None, plan_id, confirm_bytes=total, actor=_created_by())
        )
    shown = f"freed {st.fmt_bytes(result['freed_bytes'])} · {len(result['skipped'])} skipped"
    if result["errors"]:
        shown += f" · {len(result['errors'])} hosts unreachable"
    _emit(result, as_json, shown)


@storage_app.command("clean")
def storage_clean(
    archived: Annotated[
        bool, typer.Option("--archived", help="Required: archived runs only.")
    ] = False,
    older_than: Annotated[str | None, typer.Option("--older-than", help="E.g. 30d.")] = None,
    kind: Annotated[
        list[str] | None, typer.Option("--kind", help="Artifact kind (repeat).")
    ] = None,
    all_kinds: Annotated[bool, typer.Option("--all-kinds", help="Every artifact kind.")] = False,
    project: ProjectOpt = None,
    host: Annotated[list[str] | None, typer.Option("--host", help="Host (repeat).")] = None,
    no_pulled: Annotated[bool, typer.Option("--no-pulled", help="Keep pulled copies.")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Plans are always dry runs.")] = False,
    apply: Annotated[str | None, typer.Option("--apply", help="Delete what a plan lists.")] = None,
    yes: Annotated[bool, typer.Option("--yes", help="Do not ask to type the total.")] = False,
    confirm_bytes: Annotated[
        int | None, typer.Option("--confirm-bytes", help="The plan's total (remote plans).")
    ] = None,
    as_json: JsonFlag = False,
) -> None:
    """Plan a cleanup of archived runs' artifacts (a dry run); --apply PLAN deletes it."""
    from hypothex.core import storage as st
    from hypothex.core.settings import load_settings

    if apply is not None:
        _apply_plan(apply, yes, confirm_bytes, as_json)
        return
    if not archived:
        raise ConfigError("add --archived: only artifacts of archived, unstarred runs are cleaned")
    layout = Layout(_home_path())
    defaults = load_settings(layout).storage
    days = parse_duration(older_than).days if older_than else defaults.older_than_days
    policy = st.CleanPolicy(
        older_than_days=days,
        kinds=["*"] if all_kinds else (kind or defaults.kinds),
        projects=[project] if project else None,
        hosts=host or None,
        include_pulled=not no_pulled,
    )
    body = {**policy.model_dump(mode="json"), "command_id": new_command_id()}
    plan = _hub_try("POST", "/api/v1/storage/plan", body)
    if plan is None:
        made = st.plan_clean(_ctx(), None, policy, created_by=_created_by(), settings=defaults)
        plan = to_jsonable(made)
    if as_json:
        _print_json(plan)
        return
    _table(
        ["run", "host", "kind", "path", "bytes", "reason"],
        [
            [i["run_id"], i["host"], i["artifact_kind"] or i["kind"], i["path"],
             st.fmt_bytes(i["bytes"]), i["reason"]]
            for i in plan["items"]
        ],
    )  # fmt: skip
    if plan["refused"]:
        _table(
            ["refused", "path", "reason"],
            [[r["run_id"], r["path"], r["reason"]] for r in plan["refused"]],
        )
    hosts = len({i["host"] for i in plan["items"]})
    typer.echo(
        f"plan {plan['plan_id']} · {st.fmt_bytes(plan['total_bytes'])} · {len(plan['items'])} "
        f"paths · {hosts} hosts · hx storage clean --apply {plan['plan_id']}"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/cli/test_team_cli.py -v`
Expected: `11 passed`.

Run: `uv run python -m doctest src/hypothex/core/storage.py && uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check src`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/storage.py src/hypothex/cli/main.py tests/cli/test_team_cli.py
git commit -m "feat(cli): notify status and test; storage report and plan-then-apply cleanup"
```

---
## Part 13: Demo, docs, the secret-leak scan, and acceptance

Contract 11 (demo fixtures and done criteria), 5 (skill), 7 and 9 (secret-leak scan).

### Task 45: `hx demo --with-team`

**Files:**
- Create: `src/hypothex/demo_team.py`
- Modify: `src/hypothex/demo.py` (`demo_hosts_running` launches the sweep's live runs only when a fake GPU host exists)
- Modify: `src/hypothex/cli/main.py` (`hx demo --with-team`; `hx serve` runs `demo_team_running` and prints the pairing links)
- Test: `tests/test_demo_team.py`

**Interfaces:**
- Consumes: `seed_demo` and the demo host machinery (`_demo_host_home`, `_DemoHost`, `DEMO_HOSTS_DIR`, `DEMO_HOSTS_FILE`, `_PLACEHOLDER_URL`, `demo_hosts_running`), `AuthStore`, `append_entry`, `build_digest`, `record_cleaned`, `OutboxEntry`, `save_settings`.
- Produces (contract 11): `hx demo --with-team` (hidden; needs the `generic` and `training` demos) → auth on with owner `sv` (admin) and `alice` (launch); notebook days in both projects plus one weekly summary entry; two baselines on `toy-classifier/toy-test` (one with a version mismatch); six archived runs with artifacts (`st-a`, `st-b` cleanable, `st-prot` protected, `st-parent` shared with the unarchived child `st-child`, `st-star` starred, `st-done` already cleaned with a `cleaned.json` record of 4.2 GB); outbox entries in every state; one fake host `shared` (`route: url` with `token_env: HX_DEMO_SHARED_TOKEN`, the token in the hub's `secrets.env`; started by `hx serve` with the other demo hosts and that token, so the hub forwards as the host principal and runs launched there keep their owner). At `hx serve`, `demo_team_running` starts a loopback webhook and a loopback SMTP sink (stdlib, so the installed package needs no test dependency), points `HX_DEMO_SLACK_WEBHOOK` and `notify.email.port` at them, and writes fresh pairing links for `sv` and `alice` to `<home>/demo-team/pairing.json` (0600) and stderr.
- Produces (public helpers): `seed_demo_team(home) -> dict[str, Any]`; `demo_team_running(home, base_url) -> ContextManager[dict[str, str]]`; `TEAM_DIR = "demo-team"`, `PAIRING_FILE = "pairing.json"`, `SLACK_ENV = "HX_DEMO_SLACK_WEBHOOK"`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_demo_team.py`:

```python
import json
import os
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

import httpx

from hypothex.auth.pairing import parse_pairing_url
from hypothex.auth.store import AuthStore
from hypothex.cli.main import app
from hypothex.core.context import Context
from hypothex.core.notebook import list_days
from hypothex.core.queries import get_leaderboard, show_run
from hypothex.core.settings import StorageSettings, load_settings
from hypothex.core.storage import CleanPolicy, plan_clean
from hypothex.demo import seed_demo
from hypothex.demo_team import (
    PAIRING_FILE,
    SLACK_ENV,
    TEAM_DIR,
    demo_team_running,
    seed_demo_team,
)
from hypothex.notify.notifier import Notifier
from hypothex.remote.config import load_hosts


@pytest.fixture(scope="module")
def team_home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    home = tmp_path_factory.mktemp("team") / "home"
    seed_demo(home, kinds=["generic", "training"])
    seed_demo_team(home)
    return home


def test_auth_users_and_settings(team_home: Path) -> None:
    ctx = Context.open(team_home)
    settings = load_settings(ctx.layout)
    assert settings.server.auth == "on" and settings.digest.enabled
    assert settings.notify.projects["toy-classifier"].channels == ["slack", "email"]
    users = {u.name: u.role for u in AuthStore(ctx.layout).users()}
    assert users == {"sv": "admin", "alice": "launch"}


def test_baselines_on_the_toy_task(team_home: Path) -> None:
    board = get_leaderboard(Context.open(team_home), "toy-test", "toy-classifier")
    assert [b.name for b in board.baselines] == ["SVC (Hsu 2003)", "Smith 2024"]
    assert [b.version_match["accuracy"] for b in board.baselines] == [True, False]


def test_storage_fixtures_plan_two_items_and_refuse_two(team_home: Path) -> None:
    ctx = Context.open(team_home)
    plan = plan_clean(ctx, None, CleanPolicy(), created_by="human:sv", settings=StorageSettings())
    assert sorted(i.run_id for i in plan.items) == ["st-a", "st-b"]
    assert {r["run_id"]: r["reason"] for r in plan.refused} == {
        "st-parent": "used by st-child",
        "st-prot": "protected",
    }
    (cleaned,) = show_run(ctx, "st-done").cleaned
    assert cleaned.bytes == 4_200_000_000


def test_notebook_and_weekly_summary(team_home: Path) -> None:
    ctx = Context.open(team_home)
    assert list_days(ctx, "toy-classifier") and list_days(ctx, "rxn-forward")
    texts = "".join(
        (ctx.layout.project_dir("toy-classifier") / "notebook" / f"{d['day']}.md").read_text()
        for d in list_days(ctx, "toy-classifier")
    )
    assert "— digest" in texts and "[[run:st-parent]]" in texts and "— human:alice" in texts


def test_outbox_has_every_state(team_home: Path) -> None:
    ctx = Context.open(team_home)
    statuses = {e.status for e in Notifier(ctx, load_settings(ctx.layout)).recent()}
    assert statuses == {"pending", "sending", "sent", "failed", "skipped"}


def test_shared_fake_host(team_home: Path) -> None:
    marker = json.loads((team_home / "demo-hosts" / "hosts.json").read_text())
    assert "shared" in [h["name"] for h in marker]
    spec = load_hosts(Context.open(team_home).layout).environments["shared"]
    assert (spec.route, spec.token_env) == ("url", "HX_DEMO_SHARED_TOKEN")
    secrets_file = team_home / "secrets.env"
    assert stat.S_IMODE(secrets_file.stat().st_mode) == 0o600
    value = secrets_file.read_text().split("HX_DEMO_SHARED_TOKEN=", 1)[1].splitlines()[0]
    assert value and value not in (team_home / "demo-hosts" / "hosts.json").read_text()


def test_running_team_gives_links_and_working_channels(team_home: Path) -> None:
    ctx = Context.open(team_home)
    with demo_team_running(team_home, "http://127.0.0.1:7777") as links:
        assert set(links) == {"sv", "alice"}
        assert parse_pairing_url(links["alice"])[0] == "http://127.0.0.1:7777"
        path = team_home / TEAM_DIR / PAIRING_FILE
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        notifier = Notifier(ctx, load_settings(ctx.layout))
        assert notifier.send_test("slack") == {"ok": True, "error_class": None}
        assert notifier.send_test("email") == {"ok": True, "error_class": None}
    assert SLACK_ENV not in os.environ


def test_demo_hosts_start_the_shared_host(team_home: Path) -> None:
    from hypothex.demo import demo_hosts_running

    with demo_hosts_running(team_home, ready_timeout=60) as started:
        assert started == []  # no fake GPU host: no live sweep runs
        url = load_hosts(Context.open(team_home).layout).environments["shared"].url
        assert url is not None and url.startswith("http://127.0.0.1:")
        # a token, not --no-auth: the hub's forwards keep each run's owner on the host
        assert httpx.get(f"{url}/api/v1/projects", timeout=5).status_code == 401


def test_cli_seeds_the_team(tmp_path: Path) -> None:
    home = tmp_path / "cli-home"
    result = CliRunner().invoke(
        app, ["--home", str(home), "demo", "--kinds", "generic,training", "--with-team", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["team"]["users"] == {"sv": "admin", "alice": "launch"}
    refused = CliRunner().invoke(
        app, ["--home", str(tmp_path / "x"), "demo", "--kinds", "generic", "--with-team"]
    )
    assert refused.exit_code == 1 and "--with-team needs" in str(refused.exception)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_demo_team.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'hypothex.demo_team'`.

- [ ] **Step 3: Write `hypothex.demo_team`**

Create `src/hypothex/demo_team.py`:

```python
"""``hx demo --with-team``: a team hub for the phase 3 UI and its Playwright tests.

Seeds auth (owner ``sv``, collaborator ``alice``), notebook days with a weekly
summary, paper baselines, storage fixtures, outbox entries in every state, and a
shared fake host. ``demo_team_running`` (entered by ``hx serve``) starts a
loopback webhook and SMTP sink and writes fresh pairing links. Nothing here
reaches the network.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import socketserver
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import yaml

from hypothex.auth.pairing import pairing_url
from hypothex.auth.store import AuthStore, Principal
from hypothex.core.context import Context
from hypothex.core.digest import build_digest, render_digest_markdown
from hypothex.core.errors import ConfigError, StoreError
from hypothex.core.fsutil import atomic_write_text
from hypothex.core.ids import utcnow
from hypothex.core.layout import Layout
from hypothex.core.notebook import append_entry
from hypothex.core.records import Artifact, RunKind, RunRecord, RunStatus
from hypothex.core.settings import (
    DigestSettings,
    EmailSettings,
    NotifySettings,
    ProjectRule,
    ServerSettings,
    Settings,
    SlackSettings,
    load_settings,
    save_settings,
    secrets_path,
    write_private,
)
from hypothex.core.storage import CleanItem, record_cleaned
from hypothex.demo import (
    _PLACEHOLDER_URL,
    DEMO_HOSTS_DIR,
    DEMO_HOSTS_FILE,
    DEMO_TASKS,
    _demo_host_home,
    _DemoHost,
)
from hypothex.notify.messages import STATUS_GLYPH, Notice, notice_id
from hypothex.notify.notifier import NOTIFY_DIR, OutboxEntry
from hypothex.remote.config import HostSpec, load_hosts, save_hosts

TEAM_DIR = "demo-team"
TEAM_FILE = "team.json"
PAIRING_FILE = "pairing.json"
SLACK_ENV = "HX_DEMO_SLACK_WEBHOOK"
SHARED_TOKEN_ENV = "HX_DEMO_SHARED_TOKEN"
OWNER = "sv"
COLLABORATOR = "alice"
SHARED_HOST = "shared"
OWNER_PRINCIPAL = Principal(user=OWNER, scope="admin", session_id=None, client="local")


def _settings(ctx: Context, generic: str, training: str) -> None:
    email = EmailSettings(
        host="127.0.0.1",
        port=9,  # demo_team_running points it at the loopback sink
        security="none",
        password_env=None,
        sender="hx-demo@lab.org",
        to=["sv@lab.org", "alice@lab.org"],
    )
    rules = {
        generic: ProjectRule(channels=["slack", "email"], min_seconds=60),
        training: ProjectRule(channels=["slack"]),
    }
    save_settings(
        ctx.layout,
        Settings(
            server=ServerSettings(auth="on"),
            notify=NotifySettings(
                slack=SlackSettings(webhook_env=SLACK_ENV), email=email, projects=rules
            ),
            digest=DigestSettings(enabled=True, weekday="mon", hour=9, channels=["slack"]),
        ),
    )


def _users(ctx: Context) -> None:
    store = AuthStore(ctx.layout)
    store.ensure_owner(OWNER)
    if store.get_user(COLLABORATOR) is None:
        offer, secret = store.create_offer(
            issuer=OWNER_PRINCIPAL, user=COLLABORATOR, scope="launch"
        )
        session, _ = store.redeem(offer.id, secret, client="browser", device="demo")
        store.revoke(session.id, by=OWNER_PRINCIPAL)


def _baselines(ctx: Context, project: str, task: str) -> None:
    entry = ctx.store.load_project(project)
    path = Path(entry.repo) / "hypothex.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["tasks"][task]["baselines"] = [
        {
            "name": "SVC (Hsu 2003)",
            "values": {"accuracy": 0.9},
            "std": {"accuracy": 0.012},
            "source": "https://www.csie.ntu.edu.tw/~cjlin/papers/guide/guide.pdf",
            "metric_version_equivalent": {"accuracy": "v1"},
        },
        {
            "name": "Smith 2024",
            "values": {"accuracy": 0.93},
            "source": "arXiv:2401.01234",
            "metric_version_equivalent": {"accuracy": "v0"},
            "note": "reported on the v0 split",
        },
    ]
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    ctx.register_project(Path(entry.repo))


def _blob(path: Path, megabytes: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        fh.write(b"\x00" * (megabytes * 1_000_000))
    return path


def _storage_runs(ctx: Context, project: str, task: str) -> list[str]:
    now = utcnow()
    eid = ctx.descriptor.environment_id
    repo = ctx.store.load_project(project).repo

    def own(run_id: str) -> str:
        # the run's artifacts/: the only part of the Hypothex home cleanup may delete
        # (protected_reason), so <home>/demo-team/... would never be cleanable
        return str(ctx.layout.run_dir(project, run_id) / "artifacts" / "model.pt")

    def ended(
        run_id: str, days: int, owner: str, by: str, artifact: str | None, **extra: Any
    ) -> None:
        at = now - timedelta(days=days)
        digest = hashlib.sha256(run_id.encode()).hexdigest()[:16]
        ctx.create_run(
            RunRecord(
                run_id=run_id,
                project=project,
                task=task,
                command=["python", "train.py"],
                command_template=["python", "train.py"],
                cwd=repo,
                environment_id=eid,
                host=ctx.descriptor.label,
                config_hash=f"sha256:{digest}",
                status=RunStatus.FINISHED,
                created_at=at - timedelta(hours=2),
                started_at=at - timedelta(hours=2),
                ended_at=at,
                artifacts=[Artifact(kind="checkpoint", path=artifact)] if artifact else [],
                archived=extra.pop("archived", True),
                created_by=by,
                owner=owner,
                **extra,
            )
        )

    ended("st-a", 45, "sv", "human:sv", own("st-a"), hypothesis="wider MLP")
    ended("st-b", 60, "alice", "human:alice", own("st-b"), hypothesis="dropout 0.3")
    ended("st-prot", 50, "sv", "agent:claude@sv", repo, hypothesis="checkpoint saved into the repo")
    shared = own("st-parent")
    ended("st-parent", 70, "sv", "human:sv", shared, hypothesis="rbf kernel, C=10")
    ended(  # as control.reinfer writes it: the parent's checkpoint in vars, no artifact
        "st-child", 3, "alice", "human:alice", None, archived=False, parent="st-parent",
        kind=RunKind.INFER, vars={"checkpoint": shared}, hypothesis="Re-infer of st-parent",
    )  # fmt: skip
    ended("st-star", 80, "alice", "human:alice", own("st-star"), starred=True)
    for run_id, megabytes in (("st-a", 6), ("st-b", 4), ("st-parent", 5), ("st-star", 2)):
        _blob(Path(own(run_id)), megabytes)  # after create_run, which makes the run folder
    gone = own("st-done")  # cleaned: the file is not there
    ended("st-done", 90, "sv", "human:sv", gone, hypothesis="first baseline")
    item = CleanItem(
        project=project, run_id="st-done", host="local", environment_id=eid, kind="artifact",
        artifact_kind="checkpoint", path=gone, bytes=4_200_000_000, mtime=None,
        reason="archived 90d",
    )  # fmt: skip
    record_cleaned(ctx, "st-done", [item], actor="human:sv", plan_id="cp-0000d3e0")
    return ["st-a", "st-b", "st-prot", "st-parent", "st-star", "st-done"]


def _at(day: datetime, hour: int, minute: int) -> datetime:
    return day.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _notebook(ctx: Context, generic: str, training: str) -> list[str]:
    now = utcnow()
    yesterday = now - timedelta(days=1)
    runs = [
        r.run_id for r in ctx.index.list_runs(project=generic, status=RunStatus.FINISHED, limit=2)
    ]
    first, second = (runs + runs)[:2]
    append_entry(
        ctx, generic, f"svm still leads: [[run:{first}]] beats [[run:{second}]] on 9 items",
        "human:alice", now=_at(yesterday, 9, 14),
    )  # fmt: skip
    append_entry(ctx, generic, "next: sweep C for the rbf kernel, 3 seeds", "human:sv",
                 now=_at(yesterday, 16, 2))  # fmt: skip
    append_entry(
        ctx, generic, "[[run:st-parent]] checkpoint is still used by [[run:st-child]]; keep it",
        "agent:claude@sv", now=now,
    )  # fmt: skip
    digest = build_digest(ctx, generic, since=now - timedelta(days=7), until=now)
    append_entry(ctx, generic, render_digest_markdown(digest), "digest", now=now)
    trained = [r.run_id for r in ctx.index.list_runs(project=training, limit=1)]
    link = f" ([[run:{trained[0]}]])" if trained else ""
    append_entry(ctx, training, f"lr 3e-4 diverged at step 9000{link}; try warmup", "human:sv",
                 now=_at(yesterday, 11, 40))  # fmt: skip
    return sorted({now.astimezone().date().isoformat(), yesterday.astimezone().date().isoformat()})


def _outbox(ctx: Context, project: str, task: str) -> list[str]:
    root = ctx.layout.home / NOTIFY_DIR
    now = utcnow()
    later = now + timedelta(days=1)
    runs = ctx.index.list_runs(project=project, status=RunStatus.FINISHED, limit=5)
    plan = [
        ("slack", "sent", 1, None),
        ("email", "failed", 4, "smtp_451"),
        ("slack", "skipped", 1, f"unset:{SLACK_ENV}"),
        ("slack", "pending", 1, "http_429"),
        ("email", "sending", 0, None),
    ]
    finals: list[str] = []
    made: list[str] = []
    for i, (channel, status, attempts, error) in enumerate(plan):
        record = runs[i % len(runs)]
        state = "failed" if status == "failed" else "finished"
        when = now - timedelta(minutes=10 * (len(plan) - i))
        notice = Notice(
            id=notice_id("run", project, record.run_id, f"{state}:{i}"),
            kind="run",
            project=project,
            run_id=record.run_id,
            status=state,
            title=f"{STATUS_GLYPH[state]} {project}/{task} {record.run_id}",
            lines=[f"{record.created_by} · 0.4 GPU-h · $0.84 · 12m"],
            url=None,
            created_at=when,
        )
        entry = OutboxEntry(
            id=notice.id,
            channel=channel,  # type: ignore[arg-type]
            notice=notice,
            status=status,  # type: ignore[arg-type]
            attempts=attempts,
            next_at=later if status in ("pending", "sending") else when,
            last_error=error,
            created_at=when,
            sent_at=when if status == "sent" else None,
        )
        if status in ("pending", "sending"):
            write_private(
                root / "outbox" / f"{entry.id}.{channel}.json", entry.model_dump_json(indent=2)
            )
        else:
            finals.append(entry.model_dump_json())
        made.append(status)
    write_private(root / "sent.jsonl", "\n".join(finals) + "\n")
    write_private(root / "cursor.json", json.dumps({"last_sequence": ctx.events.last_sequence()}))
    return made


def _set_secret(layout: Layout, name: str, value: str) -> None:
    """Add or replace ``NAME=value`` in the hub's ``secrets.env`` (0600)."""
    path = secrets_path(layout)
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    kept = [ln for ln in lines if ln.strip().removeprefix("export ").split("=", 1)[0] != name]
    write_private(path, "\n".join([*kept, f"{name}={value}"]) + "\n")


def _shared_host(ctx: Context, project: str) -> str:
    # a bearer token, as on a real lab server: the hub forwards as the host principal, so
    # the host keeps each run's owner (alice may stop the runs she launched there)
    _set_secret(ctx.layout, SHARED_TOKEN_ENV, secrets.token_urlsafe(32))
    root = ctx.layout.home / DEMO_HOSTS_DIR
    root.mkdir(parents=True, exist_ok=True)
    host_ctx, repo = _demo_host_home(root, SHARED_HOST, Path(ctx.store.load_project(project).repo))
    marker = root / DEMO_HOSTS_FILE
    hosts = json.loads(marker.read_text(encoding="utf-8")) if marker.is_file() else []
    hosts.append(
        _DemoHost(
            name=SHARED_HOST,
            kind="ssh",
            home=str(host_ctx.layout.home),
            repo=str(repo),
            token_env=SHARED_TOKEN_ENV,
        ).model_dump()
    )
    atomic_write_text(marker, json.dumps(hosts, indent=2))
    current = load_hosts(ctx.layout)
    spec = HostSpec(
        route="url",
        url=_PLACEHOLDER_URL,
        kind="ssh",
        usd_per_gpu_hour=0.9,
        projects={project: str(repo)},
        token_env=SHARED_TOKEN_ENV,
    )
    save_hosts(
        ctx.layout,
        current.model_copy(update={"environments": {**current.environments, SHARED_HOST: spec}}),
    )
    return SHARED_HOST


def seed_demo_team(home: Path) -> dict[str, Any]:
    """
    Seed the team fixtures next to the generic and training demos.

    Parameters
    ----------
    home : Path
        A home that already holds ``toy-classifier`` and ``rxn-forward``.

    Returns
    -------
    dict
        ``{users, storage_runs, notebook_days, outbox, host}``.

    Raises
    ------
    ConfigError
        The generic or training demo is missing.
    StoreError
        The team fixtures exist already.
    """
    ctx = Context.open(home.expanduser().resolve())
    generic, generic_task = DEMO_TASKS["generic"]
    training, _ = DEMO_TASKS["training"]
    for project in (generic, training):
        try:
            ctx.store.load_project(project)
        except StoreError as exc:
            raise ConfigError(
                "--with-team needs the generic and training demos; add --kinds generic,training"
            ) from exc
    root = ctx.layout.home / TEAM_DIR
    if root.exists():
        raise StoreError(f"demo team already exists in {root}; seed into an empty HYPOTHEX_HOME")
    root.mkdir(parents=True)
    _settings(ctx, generic, training)
    _users(ctx)
    _baselines(ctx, generic, generic_task)
    made = {
        "users": {OWNER: "admin", COLLABORATOR: "launch"},
        "storage_runs": _storage_runs(ctx, generic, generic_task),
        "notebook_days": _notebook(ctx, generic, training),
        "outbox": _outbox(ctx, generic, generic_task),
        "host": _shared_host(ctx, generic),
    }
    atomic_write_text(root / TEAM_FILE, json.dumps(made, indent=2))
    return made


class _Webhook:
    """A loopback Slack-like webhook that answers 200."""

    def __init__(self) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - http.server's name
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/services/DEMO/DEMO/demo"

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class _SmtpHandler(socketserver.StreamRequestHandler):
    """Just enough SMTP to accept a message (EHLO, MAIL, RCPT, DATA, QUIT)."""

    def handle(self) -> None:
        self.wfile.write(b"220 hx-demo ESMTP\r\n")
        data = False
        while line := self.rfile.readline():
            if data:
                if line in (b".\r\n", b".\n"):
                    data = False
                    self.wfile.write(b"250 OK\r\n")
                continue
            verb = line.strip().split(b" ", 1)[0].upper()
            if verb in (b"EHLO", b"HELO"):
                self.wfile.write(b"250 hx-demo\r\n")
            elif verb in (b"MAIL", b"RCPT", b"RSET", b"NOOP"):
                self.wfile.write(b"250 OK\r\n")
            elif verb == b"DATA":
                data = True
                self.wfile.write(b"354 end with .\r\n")
            elif verb == b"QUIT":
                self.wfile.write(b"221 bye\r\n")
                return
            else:
                self.wfile.write(b"502 not implemented\r\n")


class _Smtp:
    """A loopback SMTP sink for the demo's email channel."""

    def __init__(self) -> None:
        socketserver.ThreadingTCPServer.allow_reuse_address = True
        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _SmtpHandler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def _links(layout: Layout, base_url: str) -> dict[str, str]:
    store = AuthStore(layout)
    out: dict[str, str] = {}
    for user, scope in ((OWNER, "admin"), (COLLABORATOR, "launch")):
        offer, secret = store.create_offer(issuer=OWNER_PRINCIPAL, user=user, scope=scope)  # type: ignore[arg-type]
        out[user] = pairing_url(base_url, offer.id, secret)
    return out


@contextmanager
def demo_team_running(home: Path, base_url: str) -> Iterator[dict[str, str]]:
    """
    Run the team demo's loopback channels and hand out fresh pairing links.

    Without ``<home>/demo-team/team.json`` this does nothing and yields ``{}``.

    Parameters
    ----------
    home : Path
        The hub's home.
    base_url : str
        Where browsers reach the hub (pairing links point there).

    Yields
    ------
    dict of str to str
        ``{"sv": link, "alice": link}``, also written to ``<home>/demo-team/pairing.json``.
    """
    if not (home / TEAM_DIR / TEAM_FILE).is_file():
        yield {}
        return
    layout = Layout(home.expanduser().resolve())
    webhook, smtp = _Webhook(), _Smtp()
    os.environ[SLACK_ENV] = webhook.url
    try:
        settings = load_settings(layout)
        if settings.notify.email is not None:
            settings.notify.email = settings.notify.email.model_copy(update={"port": smtp.port})
            save_settings(layout, settings)
        links = _links(layout, base_url)
        write_private(layout.home / TEAM_DIR / PAIRING_FILE, json.dumps(links, indent=2))
        yield links
    finally:
        os.environ.pop(SLACK_ENV, None)
        webhook.stop()
        smtp.stop()
```

- [ ] **Step 4: Wire it into `hx demo` and `hx serve`**

In `src/hypothex/demo.py`:

1. In `_DemoHost`, after `bin: str | None = None` add:

```python
    token_env: str | None = None
    """The hub's variable (``secrets.env``) with this host's bearer token; None: ``--no-auth``."""
```

2. Change `_start_demo_host(host: _DemoHost)` to `_start_demo_host(host: _DemoHost, hub: Layout | None = None)` (document `hub : Layout, optional — the hub's home, whose secrets.env holds token_env`; the phase 2 test that calls it with one argument is unchanged), and replace

```python
    # --no-auth: the hub reaches these fake hosts by `route: url`, which carries no token
    argv = [
        sys.executable, "-m", "hypothex.cli.main", "--home", host.home,
        "serve", "--host", "127.0.0.1", "--port", "0", "--kind", host.kind, "--no-auth",
    ]  # fmt: skip
```

with

```python
    argv = [
        sys.executable, "-m", "hypothex.cli.main", "--home", host.home,
        "serve", "--host", "127.0.0.1", "--port", "0", "--kind", host.kind,
    ]  # fmt: skip
    token = resolve_secret(hub, host.token_env) if hub is not None and host.token_env else None
    if token is not None:
        # the hub sends it (`token_env`) and is the host principal there: owners are kept
        env["HYPOTHEX_SERVE_TOKEN"] = token.get_secret_value()
    else:
        # --no-auth: the hub reaches these fake hosts by `route: url` without a token
        argv.append("--no-auth")
```

   add `from hypothex.core.settings import resolve_secret` to the imports, and in `demo_hosts_running` replace `procs.append(_start_demo_host(host))` with `procs.append(_start_demo_host(host, Layout(home)))`.

3. In `demo_hosts_running`, replace

```python
        _launch_live_runs(home, hosts, urls, started)
```

with

```python
        if gpu is not None:  # the team demo's shared host has no fake GPUs
            _launch_live_runs(home, hosts, urls, started)
```

In `src/hypothex/cli/main.py`, in `demo`:

1. Add the option after `with_hosts`:

```python
    with_team: Annotated[
        bool,
        typer.Option(
            "--with-team",
            help="Also seed a team hub (auth on: sv admin, alice launch; notebook, baselines, "
            "storage, notices, a shared host); `hx serve` prints pairing links.",
        ),
    ] = False,
```

2. After `selected = cast(...)` add:

```python
    if with_team and not {"generic", "training"} <= set(selected):
        raise ConfigError(
            "--with-team needs the generic and training demos; add --kinds generic,training"
        )
```

3. Change the import to `from hypothex.demo import DEMO_TASKS, seed_demo, seed_demo_hosts` plus `from hypothex.demo_team import seed_demo_team`, and before `_emit(made, as_json, text)` add:

```python
    if with_team:
        made["team"] = seed_demo_team(home)
        text += "\nteam: sv (admin), alice (launch); `hx serve` prints pairing links"
```

In `serve` (Task 39), import `from hypothex.demo_team import demo_team_running` and replace the first two lines of `served()`'s `try:` block

```python
            with demo_hosts_running(home) as live:
                if live:
```

with

```python
            base = public or _url(host, bound)
            with demo_hosts_running(home) as live, demo_team_running(home, base) as links:
                for user, link in links.items():
                    typer.secho(f"pair {user}: {link}", err=True)
                if live:
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_demo_team.py tests/test_demo.py -v`
Expected: `tests/test_demo_team.py` `9 passed`; `tests/test_demo.py` still passes.

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check src`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/hypothex/demo_team.py src/hypothex/demo.py src/hypothex/cli/main.py tests/test_demo_team.py
git commit -m "feat(demo): hx demo --with-team seeds a team hub for the phase 3 UI"
```

---
### Task 46: Docs pages and the agent skill

**Files:**
- Create: `docs/team.rst`, `docs/notifications.rst`, `docs/export.rst`, `docs/storage.rst`
- Modify: `docs/index.rst` (toctree), `docs/cli.rst` (a "Team and output" section), `skills/hypothex/SKILL.md` (a "Team and output" section)
- Test: `tests/test_docs_phase3.py`

**Interfaces:**
- Produces (contract 11, 5): the four pages, in the toctree after `remote`; `docs/cli.rst` lists every new command; `SKILL.md` teaches: export a table for a paper (`hx export ... --json`, MCP `export_table`), write findings to the notebook (`hx note --project`, MCP `add_notebook_entry`), read the week (`hx digest`), and never apply a storage cleanup (agents may only plan it).

- [ ] **Step 1: Write the failing test**

Create `tests/test_docs_phase3.py`:

```python
"""The phase 3 docs pages exist, are in the toctree, and name what a user needs."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
PAGES = {
    "team": ("hx pair", "hx login", "hx sessions", "auth: on", "hx serve --auth --tailscale",
             "hx hosts pair", "hx db upgrade", "index_url", "owner", "need admin"),
    "notifications": ("webhook_env", "password_env", "secrets.env", "chmod 600", "hx notify test",
                      "fold_sweeps", "min_seconds", "digest", "max_age_hours"),
    "export": ("hx export", "--format latex", "booktabs", "--noise", "baselines",
               "metric_version_equivalent", "mean ± std"),
    "storage": ("hx storage report", "hx storage clean --archived", "--apply", "protected",
                "used by", "changed since plan", "never through MCP"),
}  # fmt: skip


def test_pages_are_in_the_toctree_after_remote() -> None:
    index = (DOCS / "index.rst").read_text()
    assert "   remote\n   team\n   notifications\n   export\n   storage\n" in index


def test_pages_name_what_a_user_needs() -> None:
    for page, needles in PAGES.items():
        text = (DOCS / f"{page}.rst").read_text()
        for needle in needles:
            assert needle in text, (page, needle)


def test_cli_page_lists_the_new_commands() -> None:
    text = (DOCS / "cli.rst").read_text()
    for command in ("hx export", "hx note --project", "hx notebook show", "hx digest",
                    "hx notify status", "hx storage clean", "hx pair", "hx login", "hx whoami",
                    "hx users", "hx db upgrade", "hx hosts pair"):  # fmt: skip
        assert command in text, command


def test_skill_teaches_team_and_output() -> None:
    text = (ROOT / "skills" / "hypothex" / "SKILL.md").read_text()
    for needle in ("## Team and output", "hx export", "hx note --project", "hx digest",
                   "`export_table`", "`add_notebook_entry`", "`plan_storage_clean`",
                   "Never apply a storage cleanup"):  # fmt: skip
        assert needle in text, needle
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_docs_phase3.py -v`
Expected: FAIL: `FileNotFoundError` for `docs/team.rst` and a missing toctree line.

- [ ] **Step 3: Write the pages**

Create `docs/team.rst`:

```rst
A hub for a small lab
=====================

One hub serves a few people. Turn auth on, pair each device once, and everyone sees
the same projects, tasks, runs, sweeps, hosts, and notebooks. There are no passwords:
a device is paired with a one-time link.

Turn auth on
------------

.. code-block:: yaml

   # ~/.hypothex/config.yaml
   server:
     auth: on                       # or: hx serve --auth
     public_url: https://hub.tail1234.ts.net

``hx serve`` then makes you the owner (``admin``) and writes a session for this
machine's CLI into ``~/.hypothex/serve/server.json`` (readable only by you).

``config.yaml`` and every token file are written with mode 0600, and their folder, the
Hypothex home, is set to 0700 on each write. A home that other accounts must read (one
shared lab account) is not supported: give each person their own account and pair them.

Every ``hx`` command reads ``config.yaml``. If it is invalid, every command on that home
stops with the line and the problem (never a silent fallback to auth off or to SQLite);
fix the file, and the next command runs.

Pair a device
-------------

.. code-block:: bash

   hx pair --new-user --user alice --scope launch    # prints a QR code and a link (5 min)
   hx login 'https://hub.tail1234.ts.net/pair#p_...' # on alice's laptop
   hx whoami

A browser opens the link and gets a cookie; the CLI keeps its token in
``~/.hypothex/auth/hub-tokens.json``. The secret is after ``#``, so it is never sent
in a request line or logged. A link works once, for 5 minutes, and dies after 5 wrong
tries. Pairing never gives more than the person who made the link holds.

Scopes and ownership
--------------------

``read`` sees everything. ``launch`` also launches, reruns, tags, notes, edits the
notebook, and exports. ``admin`` also manages users, sessions, notifications, and
storage. Every run has an ``owner``: only the owner or an admin may stop, archive, or
cancel it. With auth on, the hub records who made each run (``human:alice``,
``agent:claude@alice``); a request cannot claim to be someone else.

A run executes as the Unix user of the machine that runs it, and can read everything
that user can, the hub owner's token in ``serve/server.json`` included. So runs on the
hub's own machine need admin; ``launch`` collaborators launch on hosts. Run each shared
host under its own account, never the hub owner's: everyone who launches there shares
that account.

.. code-block:: bash

   hx runs --owner me --json
   hx sessions list            # yours; --all for everyone (admin)
   hx sessions revoke s_0123456789ab
   hx users list && hx users disable bob

Reach the hub from anywhere
---------------------------

.. code-block:: bash

   hx serve --auth --tailscale

``tailscale serve`` publishes the hub over HTTPS on your tailnet; there is no other
relay. ``--tailscale`` needs auth on and binds ``127.0.0.1``.

A lab server as a host
----------------------

Run ``hx serve --auth`` on the lab server, then pair the hub with it:

.. code-block:: bash

   hx pair --client host --scope admin                 # on the lab server
   hx hosts add lab --url https://lab.tail1234.ts.net
   hx hosts pair lab 'https://lab.tail1234.ts.net/pair#p_...'   # on the hub

Only an ``admin`` link can be redeemed as a host (a host session vouches for who launched
each run). ``hx hosts pair`` refuses a link whose URL is not the host's, and the token is
only ever sent to the URL it was paired at: point ``lab`` somewhere else and the hub stops
sending it. ``token_env: LAB_TOKEN`` in ``environments.yaml`` is the other way to give the
hub a token. When the lab server stops accepting the hub, the host shows
``auth failed: hx hosts pair lab <pairing-url>`` and the hub stops retrying.

Postgres
--------

.. code-block:: yaml

   server:
     index_url: postgresql+psycopg://hx@db.lab:5432/hypothex   # never a password, not even ?password=
     index_password_env: HYPOTHEX_INDEX_PASSWORD

.. code-block:: bash

   uv tool install 'hypothex[server]'
   hx db upgrade && hx db current

Only the index moves to Postgres; run folders, the event log, and ``auth.db`` stay in
the hub's home.
```

Create `docs/notifications.rst`:

```rst
Notifications and the weekly digest
===================================

The hub tells you when a run ends: Slack (an incoming webhook) and email (SMTP).
Projects opt in one by one. Secrets are never written in ``config.yaml``: it names
the environment variables that hold them.

.. code-block:: yaml

   notify:
     slack: {webhook_env: HYPOTHEX_SLACK_WEBHOOK}
     email: {host: smtp.lab.org, port: 587, security: starttls, username: sv,
             password_env: HYPOTHEX_SMTP_PASSWORD, sender: hx@lab.org, to: [sv@lab.org]}
     projects:
       deepretro: {events: [finished, failed, lost], channels: [slack, email],
                   min_seconds: 300, fold_sweeps: true}
     max_age_hours: 24

A secret may also live in ``~/.hypothex/secrets.env`` (``NAME=value`` lines). That
file must be yours and private: ``chmod 600 ~/.hypothex/secrets.env``, or
``hx serve`` refuses to start. A literal ``webhook:`` or ``password:`` key in
``config.yaml`` is refused with the line, and the value is never printed.

``min_seconds`` skips short finished runs; failures always notify.
``fold_sweeps`` sends one notice per sweep when its last run ends. A run that ended
more than ``max_age_hours`` before the hub saw it (the hub was off) gets no notice.

Delivery
--------

Each notice is a file in ``~/.hypothex/notify/outbox`` until it is sent. Slack
``429`` and ``5xx``, SMTP ``4xx``, and timeouts are retried after 30 s, 2 min, and
10 min; a revoked webhook or a wrong password fails at once. A crash between a send
and its record sends it again (at least once).

.. code-block:: bash

   hx notify status        # slack ● set / email ○ unset, recent sends
   hx notify test slack

Weekly digest
-------------

.. code-block:: yaml

   digest: {enabled: true, weekday: mon, hour: 9, timezone: Europe/London,
            channels: [slack], projects: all, save_to_notebook: true}

The digest counts runs started and ended, cost, new best results per task, new notes,
and sweeps. It is sent once per ISO week (a hub that was off sends it at its next
start that week) and saved to the project notebook.

.. code-block:: bash

   hx digest -p deepretro --since 7d
   hx digest -p deepretro --send
```

Create `docs/export.rst`:

```rst
Paper tables
============

``hx export`` turns a leaderboard (or a few runs) into a table for a paper: LaTeX with
``booktabs``, Markdown, or CSV.

.. code-block:: bash

   hx export uspto50k-topk --format latex --digits 3 -o table.tex
   hx export uspto50k-topk --format markdown --noise seed
   hx export --runs r1,r2,r3 --format csv

Each cell is ``mean ± std`` over seeds, and the primary metric adds a 95% test-set
interval ``[lo, hi]`` (``--noise both|seed|test|none``). The best value of each column
is bold; ``†`` marks rows within noise of the best, ``¹`` a single seed, and
``(◇×n)`` seeds with identical results. Output is the same bytes for the same data.

Paper baselines
---------------

.. code-block:: yaml

   tasks:
     uspto50k-topk:
       baselines:
         - name: Chemformer
           values: {topk/k=1: 0.548}
           source: arXiv:2108.12345
           metric_version_equivalent: {topk: v2}

Baselines are listed under the groups, never bold. ``‡`` marks a baseline whose
``metric_version_equivalent`` is not the leaderboard's metric version.
```

Create `docs/storage.rst`:

```rst
Storage
=======

.. code-block:: bash

   hx storage report               # bytes by project, host, and kind; the 20 largest
   hx storage clean --archived --older-than 30d          # always a dry run: a plan
   hx storage clean --apply cp-1a2b3c4d                  # type the total to confirm

Cleanup deletes only recorded artifacts (and pulled copies) of runs that are
archived, not starred, ended, and older than the limit. It never deletes run records
or a protected path (``/``, your home, the Hypothex home, a project repo, or any
parent of them). A path still used by another run is refused (``used by <run>``). At
apply, every item is checked again where it lives; an item that was rewritten is
skipped (``changed since plan``). A symlink is removed, never its target. Cleanup is
admin-only and never through MCP: agents may plan it, a person applies it.
```

In `docs/index.rst` (on `main` the User guide toctree reads `... ui`, `remote`, `gpus`, `slurm`, `sweeps`, `cost`), replace

```
   remote
   gpus
```

with

```
   remote
   team
   notifications
   export
   storage
   gpus
```

Append to `docs/cli.rst`:

```rst
Team and output
---------------

.. code-block:: bash

   hx export uspto50k-topk --format latex -o table.tex
   hx export --runs r1,r2 --format csv
   hx note --project deepretro "beam 10 wins [[run:20261004-0914-topk-a1b2]]"
   hx notebook list -p deepretro && hx notebook show -p deepretro --day 2026-10-04
   hx digest -p deepretro --since 7d [--send]
   hx notify status && hx notify test slack
   hx storage report && hx storage clean --archived --older-than 30d
   hx storage clean --apply cp-1a2b3c4d
   hx pair --new-user --user alice --scope launch && hx login <link> && hx whoami
   hx sessions list [--all] && hx users list
   hx hosts pair lab <link>
   hx db upgrade && hx db current
   hx serve --auth --tailscale

See :doc:`team`, :doc:`notifications`, :doc:`export`, and :doc:`storage`.
```

Append to `skills/hypothex/SKILL.md`:

```markdown
## Team and output

- Paper table: `hx export <task> --format latex --json` (also `markdown`, `csv`;
  `--noise seed|test|both`). Compare runs: `hx export --runs a,b --json`.
  MCP: `export_table`, `export_compare`, `get_baselines`.
- Write what you learned to the project notebook, linking runs as `[[run:<id>]]`:
  `hx note --project <project> "<finding> [[run:<id>]]" --json`. Read it with
  `hx notebook show -p <project> --json`. MCP: `get_notebook`, `add_notebook_entry`.
- The week: `hx digest -p <project> --json`. MCP: `get_digest`. `whoami` tells who you act as.
- Never apply a storage cleanup. You may look (`hx storage report --json`, MCP
  `storage_report`) and plan (`hx storage clean --archived --json`, MCP
  `plan_storage_clean`); a person applies the plan.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_docs_phase3.py tests/test_skill.py tests/test_docs_ui.py -v`
Expected: `tests/test_docs_phase3.py` `4 passed`; `tests/test_skill.py` passes (every `hx <command>` in the skill exists); `tests/test_docs_ui.py` passes.

Run: `uv run sphinx-build -W -b html docs docs/_build/html`
Expected: `build succeeded.` with no warnings.

- [ ] **Step 5: Commit**

```bash
git add docs/team.rst docs/notifications.rst docs/export.rst docs/storage.rst docs/index.rst docs/cli.rst skills/hypothex/SKILL.md tests/test_docs_phase3.py
git commit -m "docs: team hub, notifications, paper tables, and storage; skill section"
```

---

### Task 47: The secret-leak scan

**Files:**
- Test: `tests/test_secret_leaks.py`

**Interfaces:**
- Consumes: every secret path of the plan: settings (Tasks 2–3), channels and notifier (Tasks 15–17), run environments (Task 3), the API (Tasks 25, 30), the CLI (Task 44), `hx serve` (Task 39), the auth store (Task 6).
- Produces: contract 9's scan: after successful sends, each failure class (Slack 404, 429, 500; SMTP 535; the timeout class is covered by Task 15), a run that prints its environment, `GET /api/v1/notify`, `POST /api/v1/notify/test`, `hx notify status --json`, `hx notify test --json`, pairing and session use, and a failing `hx serve` start, no secret (webhook URL and path, SMTP password, index password, `HYPOTHEX_HUB_TOKEN`, a host's `token_env` value, `secrets.env` value, session token secret, pairing secret) appears in any file under the home (except the four places meant to hold them: `secrets.env`, `serve/server.json`, `auth/hub-tokens.json`, `auth/host-tokens.json`), any event payload, any log line captured at DEBUG, any CLI output, or any API answer other than the pairing link and token answers to their owner.

- [ ] **Step 1: Write the test**

Create `tests/test_secret_leaks.py`:

```python
"""Secret-leak scan (contract 9): no secret reaches a file, event, log line, answer, or output."""

import logging
import secrets
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from hypothex.auth.pairing import parse_pairing_url
from hypothex.auth.store import parse_token
from hypothex.cli.main import app as cli
from hypothex.core.context import Context
from hypothex.core.execution import RunRequest, execute_run, prepare_run
from hypothex.core.records import RunStatus
from hypothex.core.settings import (
    EmailSettings,
    NotifySettings,
    ProjectRule,
    Settings,
    SlackSettings,
    save_settings,
)
from hypothex.notify.notifier import Notifier
from hypothex.remote.config import HostSpec
from tests.api.authkit import BASE, auth_app, bearer, token_for
from tests.api.envserver import write_hosts
from tests.factories import make_record
from tests.fakes.smtp import FakeSmtp
from tests.fakes.webhook import FakeWebhook, Reply

ALLOWED = {"secrets.env", "serve/server.json", "auth/hub-tokens.json", "auth/host-tokens.json"}
T0 = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)


def leaks(text: str, needles: list[str]) -> list[str]:
    return [n for n in needles if n and n in text]


def file_hits(home: Path, needles: list[str]) -> list[str]:
    hits: list[str] = []
    for path in home.rglob("*"):
        if not path.is_file() or path.relative_to(home).as_posix() in ALLOWED:
            continue
        data = path.read_bytes()
        hits += [f"{path.relative_to(home)}: {n[:12]}" for n in needles if n and n.encode() in data]
    return hits


def end(ctx: Context, run_id: str, status: RunStatus) -> None:
    ctx.create_run(
        make_record(run_id, status=RunStatus.RUNNING, started_at=T0 - timedelta(minutes=10),
                    environment_id=ctx.descriptor.environment_id)
    )  # fmt: skip
    ctx.update_run(
        run_id,
        f"run.{status.value}",
        lambda r: r.model_copy(update={"status": status, "ended_at": T0, "exit_code": 1}),
    )


def test_no_secret_reaches_any_file_event_log_or_output(
    home: Path, toy_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:  # fmt: skip
    caplog.set_level(logging.DEBUG)
    password = "SECRETSMTP-" + secrets.token_hex(6)
    index_password = "SECRETPG-" + secrets.token_hex(6)
    hub_token = "SECRETHUB-" + secrets.token_hex(6)
    host_token = "SECRETHOST-" + secrets.token_hex(6)
    monkeypatch.setenv("HX_LEAK_SMTP", password)
    monkeypatch.setenv("HYPOTHEX_INDEX_PASSWORD", index_password)
    monkeypatch.setenv("HYPOTHEX_HUB_TOKEN", hub_token)
    monkeypatch.setenv("HX_LEAK_HOST", host_token)
    ctx = Context.open(home)
    ctx.register_project(toy_repo)
    outputs: list[str] = []
    replies = [Reply(200), Reply(404), Reply(429, retry_after=1), Reply(500)]
    with FakeWebhook(replies) as hook, FakeSmtp(user="sv", password=password) as smtp:
        monkeypatch.setenv("HX_LEAK_HOOK", hook.url)
        email = EmailSettings(
            host="127.0.0.1", port=smtp.port, security="none", username="sv",
            password_env="HX_LEAK_SMTP", sender="hx@lab.org", to=["sv@lab.org"], timeout=1,
        )  # fmt: skip
        settings = Settings(
            notify=NotifySettings(
                slack=SlackSettings(webhook_env="HX_LEAK_HOOK"),
                email=email,
                projects={"toy": ProjectRule(channels=["slack", "email"])},
            )
        )
        save_settings(ctx.layout, settings)
        now = [T0 + timedelta(minutes=5)]
        notifier = Notifier(ctx, settings, now=lambda: now[0])
        notifier.scan()
        for run_id, status in (("a", RunStatus.FINISHED), ("b", RunStatus.FAILED),
                               ("c", RunStatus.LOST), ("d", RunStatus.KILLED)):  # fmt: skip
            end(ctx, run_id, status)
        notifier.scan()
        for _ in range(6):
            notifier.deliver()
            now[0] += timedelta(minutes=11)
        with FakeSmtp(user="sv", password="another-password") as wrong:  # SMTP 535
            settings.notify.email = email.model_copy(update={"port": wrong.port})
            end(ctx, "e", RunStatus.FAILED)
            notifier.scan()
            notifier.deliver()
        settings.notify.email = email
        lab = HostSpec(route="url", url="http://127.0.0.1:9", token_env="HX_LEAK_HOST")
        write_hosts(home, {"lab": lab})
        record = prepare_run(
            ctx,
            RunRequest(
                repo=toy_repo,
                command=[sys.executable, "-c", "import os; print(dict(os.environ))"],
            ),
        )
        execute_run(ctx, record.run_id)
        write_hosts(home, {})  # the hub below has no host to dial
        app = auth_app(home)
        with TestClient(app, base_url=BASE) as client:
            admin = token_for(app.state.auth, "sv", "admin")
            offer = client.post(
                "/api/v1/auth/pairings", json={"user": "sv", "scope": "read"}, headers=bearer(admin)
            ).json()
            _, offer_id, pairing_secret = parse_pairing_url(offer["url"])
            paired = client.post(
                "/api/v1/auth/pair",
                json={"offer_id": offer_id, "secret": pairing_secret, "client": "cli"},
            ).json()
            parts = parse_token(paired["token"])
            assert parts is not None
            session_secret = parts[1]
            for resp in (
                client.get("/api/v1/notify", headers=bearer(admin)),
                client.post(
                    "/api/v1/notify/test", json={"channel": "slack"}, headers=bearer(admin)
                ),
                client.post(
                    "/api/v1/notify/test", json={"channel": "email"}, headers=bearer(admin)
                ),
                client.get("/api/v1/auth/me", headers=bearer(paired["token"])),
                client.get("/api/v1/auth/sessions", headers=bearer(admin)),
            ):
                outputs.append(resp.text)
        runner = CliRunner()
        for args in (["notify", "status", "--json"], ["notify", "test", "slack", "--json"]):
            outputs.append(runner.invoke(cli, args).output)
    file_secret = "SECRETFILE-" + secrets.token_hex(6)
    bad_home = tmp_path / "bad-home"
    bad_home.mkdir()
    (bad_home / "secrets.env").write_text(f"HYPOTHEX_SLACK_WEBHOOK={file_secret}\n")
    (bad_home / "secrets.env").chmod(0o640)
    start = subprocess.run(
        [
            sys.executable,
            "-m",
            "hypothex.cli.main",
            "--home",
            str(bad_home),
            "serve",
            "--port",
            "0",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert start.returncode == 1
    outputs += [start.stdout, start.stderr]
    needles = [
        hook.secret, hook.url, password, index_password, file_secret, pairing_secret,
        session_secret, hub_token, host_token,
    ]  # fmt: skip
    events = "\n".join(e.model_dump_json() for e in ctx.events.since(0, limit=100_000))
    assert file_hits(home, needles) == []
    assert leaks(events, needles) == []
    assert leaks(caplog.text, needles) == []
    assert leaks("\n".join(outputs), needles) == []
    statuses = {e.status for e in notifier.recent(limit=100)}
    assert {"sent", "failed"} <= statuses  # the scenario really went through both paths
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/test_secret_leaks.py -v`
Expected: `1 passed`. A failure lists the file, the event log, the log text, or the output that quoted a secret (the first 12 characters of the secret only).

Run: `uv run ruff check tests && uv run ruff format --check tests`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add tests/test_secret_leaks.py
git commit -m "test: secret-leak scan over files, events, logs, answers, and cli output"
```

---

### Task 48: Acceptance — a collaborator on a shared host, and notices end to end

**Files:**
- Modify: `tests/api/envserver.py` (`serve_app(app, port=0)`)
- Test: `tests/test_acceptance_phase3.py`

**Interfaces:**
- Consumes: everything above.
- Produces: contract 11's done criteria 1 and 2 as tests. (Criteria 3–7 are the golden-file tests of Task 11–12, the storage tests of Tasks 21–22 and 31, the digest tests of Tasks 18–19 and the notebook round trips of Tasks 8, 29, 43, the scope tests of Tasks 24, 28, 32, and the Docker test of Task 36; criterion 8 is the frontend plan; criterion 9 is CI.)
- Produces (additive): `serve_app(app, port=0)` (a fixed port, so a hub's `public_url` can name it before it starts).

- [ ] **Step 1: Let `serve_app` take a port**

In `tests/api/envserver.py`, change `def serve_app(app: FastAPI) -> Iterator[str]:` to `def serve_app(app: FastAPI, port: int = 0) -> Iterator[str]:`, document the parameter ("port : int — 0 picks a free one."), and change `sock.bind(("127.0.0.1", 0))` to `sock.bind(("127.0.0.1", port))`.

- [ ] **Step 2: Write the acceptance tests**

Create `tests/test_acceptance_phase3.py`:

```python
"""Phase 3 done criteria (contract 11): a collaborator on a shared host; notices end to end."""

import json
import socket
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from hypothex.api.app import create_app
from hypothex.auth.store import AuthStore
from hypothex.cli import main as cli_main
from hypothex.cli.main import app
from hypothex.core.context import Context
from hypothex.core.records import RunStatus
from hypothex.core.settings import (
    EmailSettings,
    NotifySettings,
    ProjectRule,
    ServerSettings,
    Settings,
    SlackSettings,
    save_settings,
)
from hypothex.core.sweeps import SweepParam, SweepSpec, save_sweep, sweep_tag
from hypothex.notify.notifier import Notifier
from hypothex.remote.config import HostSpec
from tests.api.envserver import serve_app, wait_until, write_fake_gpus, write_hosts
from tests.factories import git, make_record, write_toy_project
from tests.fakes.smtp import FakeSmtp
from tests.fakes.webhook import FakeWebhook

PY = sys.executable
runner = CliRunner()
HOST_TOKEN = "h" * 48


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def hx(home: Path, *args: str, env: dict[str, str] | None = None) -> Any:
    argv = ["--home", str(home), *args]
    argv.insert(argv.index("--") if "--" in argv else len(argv), "--json")
    result = runner.invoke(app, argv, env=env, catch_exceptions=False)
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def refused(home: Path, *args: str) -> str:
    result = runner.invoke(app, ["--home", str(home), *args])
    assert result.exit_code == 1, result.output
    return str(result.exception)


@pytest.fixture
def lab(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    """A hub with auth on and a public URL, and a shared route-url host with 4 fake GPUs."""
    hub_repo = write_toy_project(tmp_path / "hub-repo")
    origin = tmp_path / "origin.git"
    git(tmp_path, "clone", "-q", "--bare", str(hub_repo), str(origin))
    git(hub_repo, "remote", "add", "origin", str(origin))
    shared_repo = tmp_path / "shared-repo"
    git(tmp_path, "clone", "-q", str(origin), str(shared_repo))
    monkeypatch.setenv("HYPOTHEX_FAKE_GPUS", str(write_fake_gpus(tmp_path / "gpus.json", count=4)))
    monkeypatch.setenv("SHARED_TOKEN", HOST_TOKEN)
    monkeypatch.setattr(cli_main, "REMOTE_POLL_SECONDS", 0.2)
    shared = create_app(tmp_path / "shared-home", kind="ssh", auth_token=HOST_TOKEN)
    hub_home = tmp_path / "hub-home"
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    with serve_app(shared) as shared_url:
        spec = HostSpec(
            route="url", url=shared_url, token_env="SHARED_TOKEN",
            projects={"toy": str(shared_repo.resolve())},
        )  # fmt: skip
        write_hosts(hub_home, {"shared": spec})
        hub_ctx = Context.open(hub_home)
        hub_ctx.register_project(hub_repo)
        save_settings(hub_ctx.layout, Settings(server=ServerSettings(auth="on", public_url=url)))
        store = AuthStore(hub_ctx.layout)
        store.ensure_owner("sv")
        _, owner_token = store.mint_local("sv")
        hub_app = create_app(hub_home, background_repair=False)
        with serve_app(hub_app, port=port):
            monkeypatch.setenv("HYPOTHEX_HUB_URL", url)
            owner = {"HYPOTHEX_HUB_TOKEN": owner_token}
            wait_until(
                lambda: (
                    next(
                        h
                        for h in hx(hub_home, "hosts", "status", env=owner)
                        if h["name"] == "shared"
                    )["state"]["state"]
                    == "connected"
                ),
                timeout=30,
            )
            yield {"hub": hub_ctx, "home": hub_home, "url": url, "owner": owner,
                   "origin": origin, "store": store}  # fmt: skip


def test_a_collaborator_pairs_sees_the_same_projects_and_launches_on_a_shared_host(
    tmp_path: Path, lab: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    hub_home, owner, hub_ctx = lab["home"], lab["owner"], lab["hub"]
    offer = hx(hub_home, "pair", "--new-user", "--user", "alice", "--scope", "launch", env=owner)
    assert offer["url"].startswith(lab["url"] + "/pair#p_")
    laptop_home = tmp_path / "alice-home"
    login = hx(laptop_home, "login", offer["url"], "--device", "alice-laptop")
    assert (login["user"], login["scope"]) == ("alice", "launch")
    assert hx(laptop_home, "projects") == hx(hub_home, "projects", env=owner)
    assert hx(laptop_home, "tasks") == hx(hub_home, "tasks", env=owner)
    laptop = tmp_path / "alice-checkout"
    git(tmp_path, "clone", "-q", str(lab["origin"]), str(laptop))
    monkeypatch.chdir(laptop)
    record = hx(
        laptop_home, "launch", "--host", "shared", "-t", "toy-acc", "-H", "alice on the shared box",
        "--wait", "--", PY, "-c", "print('hi')",
    )  # fmt: skip
    assert record["status"] == "finished"
    mirrored = wait_until(lambda: hub_ctx.index.get_run(record["run_id"]), timeout=30)
    assert (mirrored.owner, mirrored.created_by) == ("alice", "human:alice")
    assert record["run_id"] in {r["run_id"] for r in hx(hub_home, "runs", env=owner)}
    eid = hub_ctx.descriptor.environment_id
    hub_ctx.create_run(make_record("svs-run", owner="sv", environment_id=eid))
    hub_ctx.create_run(make_record("alices-run", owner="alice", environment_id=eid))
    assert "run owned by sv" in refused(laptop_home, "stop", "svs-run")
    assert hx(laptop_home, "stop", "alices-run")["status"] == RunStatus.KILLED.value
    session = hx(laptop_home, "whoami")["session_id"]
    hx(hub_home, "sessions", "revoke", session, env=owner)
    assert "401" in refused(laptop_home, "whoami")


def test_notices_end_to_end(home: Path, toy_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = Context.open(home)
    ctx.register_project(toy_repo)
    eid = ctx.descriptor.environment_id
    t0 = datetime.now(UTC)
    with FakeWebhook() as hook, FakeSmtp() as smtp:
        monkeypatch.setenv("HX_ACC_HOOK", hook.url)
        email = EmailSettings(
            host="127.0.0.1", port=smtp.port, security="none", password_env=None,
            sender="hx@lab.org", to=["sv@lab.org"],
        )  # fmt: skip
        settings = Settings(
            notify=NotifySettings(
                slack=SlackSettings(webhook_env="HX_ACC_HOOK"),
                email=email,
                projects={"toy": ProjectRule(channels=["slack", "email"])},
            )
        )
        notifier = Notifier(ctx, settings)
        notifier.tick()  # the first tick only sets the cursor
        endings = [
            ("f", "finished", "toy"),
            ("x", "failed", "toy"),
            ("l", "lost", "toy"),
            ("o", "failed", "other"),
        ]
        for run_id, status, project in endings:
            ctx.create_run(make_record(run_id, project=project, environment_id=eid))
            ctx.update_run(
                run_id,
                f"run.{status}",
                lambda r, s=status: r.model_copy(update={"status": RunStatus(s), "ended_at": t0}),
            )
        spec = SweepSpec(
            id="s-0200", project="toy", task="t", host=None,
            grid=[SweepParam(name="x", values=[str(i) for i in range(200)])], seeds=[1],
            command_template=["echo", "{x}"], created_by="human:sv", created_at=t0,
        )  # fmt: skip
        save_sweep(ctx.layout, spec)
        tag = sweep_tag(eid, spec.id)
        for i in range(200):
            run_id = f"sw{i:03d}"
            ctx.create_run(make_record(run_id, environment_id=eid, tags=[tag], sweep_id=spec.id))
            ctx.update_run(
                run_id,
                "run.finished",
                lambda r: r.model_copy(update={"status": RunStatus.FINISHED, "ended_at": t0}),
            )
        notifier.tick()
        titles = sorted(r["body"]["text"].splitlines()[0] for r in hook.requests)
        subjects = sorted(m.message["Subject"] for m in smtp.received)
    assert len(titles) == 4 and titles == subjects
    assert [t.split()[0] for t in titles] == ["?", "✓", "✓", "✗"]
    assert any("sweep s-0200 200/200" in t for t in titles)
    assert not any(" other/" in t for t in titles)
```

- [ ] **Step 3: Run the tests**

Run: `uv run pytest tests/test_acceptance_phase3.py -v`
Expected: `2 passed`.

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check src`
Expected: every test passes (Docker tests deselected); clean.

- [ ] **Step 4: Commit**

```bash
git add tests/api/envserver.py tests/test_acceptance_phase3.py
git commit -m "test: phase 3 acceptance for a paired collaborator and end-to-end notices"
```

---
## Done criteria map (contract 11)

| # | Criterion | Where it is proven |
|---|---|---|
| 1 | A collaborator pairs a laptop with a server hub, sees the same projects, launches on a shared host; ownership and revocation hold | Task 48 `test_a_collaborator_pairs_sees_the_same_projects_and_launches_on_a_shared_host` |
| 2 | Finished, failed, lost runs give one Slack notice and one email each for an opted-in project, none otherwise; a 200-run sweep gives one; no secret leaks | Task 48 `test_notices_end_to_end`, Task 16 `test_sweep_gives_one_notice_when_its_last_run_ends`, Task 47 |
| 3 | `hx export` golden files (LaTeX, Markdown, CSV; seed noise, test-set CI, best, `†`, baselines, `‡`) | Tasks 11–12 (`board.{md,tex,csv}`, `compare.{md,csv}`) |
| 4 | Storage dry run lists exactly the eligible artifacts (local and on a host), apply frees exactly the planned bytes, every refusal of failure mode 9 holds | Tasks 21–22, Task 31 `test_hub_cleans_a_hosts_artifacts`, Task 44 |
| 5 | Weekly digest built, sent once per week through both fakes, saved to the notebook; `hx note --project` and the notebook API round-trip with run chips | Tasks 18–19 (`test_digest_goes_out_once_per_week`), Tasks 8, 29, 43 |
| 6 | Every route, the WebSocket, and every MCP tool declares a scope; the scope matrix passes | Tasks 24, 28, 32, 33 |
| 7 | Postgres: `hx db upgrade`, reindex equivalence with SQLite | Task 36 (marker `docker`), Task 35 (Alembic head vs models) |
| 8 | Playwright smoke of every new screen | Frontend plan (fixtures from Task 45) |
| 9 | `uv run pytest`, `ruff check`, `ruff format --check`, `ty check` clean | Every task's last steps; Task 48 Step 3 |

The user's manual steps after this plan: a first send to the real Slack workspace and SMTP server (`hx notify test slack|email`), and a first `hx serve --auth --tailscale` on the real tailnet.

## Assembly notes

Inputs: the phase 3 contract, spec sections 3.4, 5.3, 5.4, 7.2–7.4, 9, 12, 13, 14, and the code on `main` at `e27a3a2` (first written against `738c711`; see the Prerequisite for the drift). Where the contract was ambiguous or silent, this plan decided as follows.

**Contract readings.**

- **Retries.** Contract 1.7 says `RETRY_DELAYS = (30, 120, 600)` "after attempts 1, 2, 3; then failed", and failure mode 1 says "after 3 failed attempts the entry is failed". The task summary says "retries at 30 s, 2 min and 10 min". This plan makes four attempts: the first, then retries after 30 s, 2 min, and 10 min; the fourth failure is final (Task 17 `test_three_retries_then_failed`). A server's `Retry-After` can only lengthen a wait.
- **Literal-secret hint.** Contract 1.1 says the hint is "use <key>_env: NAME". For `webhook`/`password` that is exactly the real field; for `url`, `token`, `secret`, and `webhook_url` the plan names the real field (`webhook_env` under Slack, `password_env` under email), since `url_env` does not exist.
- **Remote storage sizes** come from each host's env route `GET /api/v1/storage/usage` (contract 1.9), not `du` over SSH (spec 9), so they also work for `route: url` hosts. The hub can only partly check a host path for protection (`/`, the host's run folders, mapped checkouts, an absolute host home); the hub also calls the owner's read-only `POST /api/v1/storage/check` before including remote candidates. The owner resolves input aliases, then repeats all checks under the deletion lock at apply; failures there return `skipped` (Tasks 21–22, 31).
- **CSV export and test-set intervals** are kept from the contract (the spec names only LaTeX and Markdown). `noise` drops data from the table itself (not only from the rendering), so CSV follows the same choice. `percent` scales the table's numbers (CSV too) per column, only when that column's `value_format` is `fraction`, for both leaderboard and comparison tables. Leaderboard footnotes name the scaled columns (`values ×100: <columns>`); comparisons retain `values ×100` (contract 1.6). Baseline rows show `—`/`--` in the `n` column and `n = 0` in CSV.
- **Metric directions in export.** A `Leaderboard` knows only the primary's direction, so `leaderboard_table` takes `directions=` (column ref, else metric name → higher is better); `task_table`/`export_task` and `compare_table` use `leaderboard.metric_higher_is_better`, the leaderboard's own rule (a `system_bench` percentile key ranks lower-first), so an export never ranks against its leaderboard (Tasks 10, 12).
- **Route scope keys** use FastAPI's `path_format` (`/api/v1/runs/{run_id}/files/{path}`), as OpenAPI does, so the matrix test can fill parameters with one regex (Tasks 23, 24, 28).
- **`/mcp` principal.** Tools read the principal from the MCP SDK's request context (`ctx.request_context.request.scope["hx.principal"]`) through a hidden `hx_mcp_ctx` parameter that `@scoped` adds; in-process calls use `acting_as`, else `LOCAL_OWNER`. Over HTTP a tool's own hub calls carry the caller's credential (`caller_token`: the bearer token, else the `hx_session` cookie) and never the server's `hub_token` or local admin token (`tool_hub_token`), so the hub sees who acts and applies their scope and ownership; `stop_run` and `cancel_sweep` check `require_act` on local runs and sweeps (Task 32). `tool_scopes` reads the SDK's tool registry (`_tool_manager`), the only place the decorated functions are kept (Task 32).
- **Auth failure message** `auth failed: hx hosts pair <name> <pairing-url>` is used for `route: url` hosts; `route: ssh` hosts keep phase 2's `hx hosts connect` message, because their token is re-read from `server.json` on connect (Task 38). The phase 2 test of that message is updated.
- **`owner` with auth off** stays `None` even when a body sends one, except from a hub forwarding to a host (the host principal), where both `owner` and `created_by` are kept (Task 23 `identity`).
- **`hx pair` default scope** is `launch` (the contract gives none); a caller with less gets 403.
- **`hx export --json` in client mode** returns `table: null`: the hub's route answers text; the table is built only when the CLI has the store (Task 43).
- **`hx storage clean --apply` on another machine** needs `--confirm-bytes N` (an addition): the plan file lives on the hub, and the CLI must know the total to confirm (Task 44).
- **The fake `tailscale`** is `tests/fakes/fake_tailscale.py`; `install_fake_tailscale` writes the `sh` wrapper the contract names (`<base>/tailscale`) that runs it with this Python, like phase 2's fake `ssh` (Task 37).
- **Notifier tick order** is scan, digests, deliver, so a digest goes out on the tick that made it (contract 1.7 says so since review round 2).
- **Local runs need admin with auth on.** A run executes as the serving machine's Unix user and can read `serve/server.json`; `require_local_exec` (Tasks 5, 27, 32) keeps `launch` collaborators on hosts. Separating execution by Unix account (a `run_as` user) would let collaborators run on the hub's own machine, but needs privileged setup that tests cannot fake; a lab runs its shared GPU box as a host under its own account instead (`docs/team.rst`).
- **Failed index writes** are journaled per run (`Index.pending`) and re-indexed from files by `repair_pending` on open and every 30 s; `repair_index_gaps` alone only finds missing rows, not stale ones. A claim is a file of its own (`index-pending.txt.<8 hex>.claim`) that stays until its runs are indexed, so a crash never strands it, and each run is re-indexed under its `run_lock` (Task 34).
- **Sweep folding** needs the sweep file on the hub; a run whose sweep file is elsewhere (a sweep made directly on a host) is notified on its own (Task 16).
- **Demo team counts.** The six archived runs with artifacts are `st-a`, `st-b` (cleanable), `st-prot` (protected), `st-parent` (shared with the unarchived child `st-child`), `st-star` (starred), and `st-done` (already cleaned; its `cleaned.json` records a 4.2 GB checkpoint). Each checkpoint is `<run_dir>/artifacts/model.pt`, the only place in the Hypothex home that cleanup may delete. The cleanable files are a few MB, so the demo stays small (Task 45).

**Safety additions beyond the contract text.**

- httpx logs every request URL at INFO; while a webhook call runs, records of `httpx`/`httpcore` that quote the webhook path are dropped (Task 15), and the leak scan captures logs at DEBUG (Task 47).
- `POST /api/v1/auth/pairings` never stores its answer as a command receipt (`events.db` would then hold a pairing secret) (Task 25).
- Command receipts are keyed by `command_key` (caller, method, path), on phase 1–2 routes too, so a command id replayed by another caller or on another route never returns a stored result it could not have produced (Tasks 23, 25, 27, 29–31).
- `hx serve --auth` revokes earlier `local` sessions of the owner before it mints a new one, so a crashed start leaves no live extra admin session behind (Task 39).
- A demo with the team but without `--with-hosts` has no fake GPU host; `demo_hosts_running` now skips the live sweep runs in that case instead of failing (Task 45).
- The network guard wraps `psycopg.connect` because libpq connects in C, below Python's `socket` (Task 1).

**Changes after review round 1** (contract section "Changes after review round 1" has the rulings).

- Host forwarding is trusted only from an `admin` host principal; `redeem(client="host")` needs an `admin` offer and `hx pair --client host` needs `--scope admin` (Tasks 6, 23, 41).
- Paired host tokens are bound to the origin they came from (`same_origin`, `{host: {url, token}}`), and runs never see `HYPOTHEX_HUB_TOKEN` or a host's `token_env` (Tasks 3, 38, 42, 47).
- Cleanup counts `vars["checkpoint"]` as a use (`input_paths`, `overlaps`) at plan and at delete; a concurrent second apply of one plan is refused, not a 500 (Tasks 21, 22, 45).
- Export refuses a comparison that would merge two versions of one metric (Task 12). Folded sweeps follow `rule.events` (Task 16). Digest notices carry the top notes, and the notebook block lists task changes as lines (Task 18).
- `hub_today` and the API's `today` day make one "today" for the UI, the CLI, MCP, and the digest (Tasks 8, 29, 33, 43).
- The pairing limit counts failures only, keyed per person behind `tailscale serve` (Task 25). `AuthGuard` skips the session lookup for paths outside `/api/` and `/mcp` (Task 23). `NotifyTestBody` is module-level (Task 30). Overview rows carry `owner` (Task 27). A Postgres URL without `psycopg` is a `ConfigError` (Task 34). The open-bind test checks the decision instead of listening on `0.0.0.0` (Task 39). `write_private` is main's hardened version and the CLI shares it (Task 2).

**Order.** Parts 3 (notebook, baselines, export), 4–5 (notify, digest), 6 (storage), and 10 (Postgres) depend only on Parts 1–2 and may run in parallel. Part 7 needs Part 2; Part 8 needs Parts 3–7; Part 9 needs Parts 3–7; Part 11 needs Parts 1, 2, and 7; Part 12 needs Parts 7–9 and 11; Part 13 needs everything.
