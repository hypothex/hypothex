# Phase 3 installed-package acceptance — backend Task 49

**Status: plan only.** Implementation remains gated on the complete Claude and adversarial reviews. This task owns contract §11 done criterion **9**; it follows backend Task 48 and the assembled frontend through Task 26. Its green result is required before claiming the package is ready for the user's later-week testing. It does not replace criterion 8's full browser suite or criterion 10's source checks.

**References:** [contract](2026-10-04-hypothex-phase3-contract.md), [backend](2026-10-04-hypothex-phase3-backend.md), [frontend](2026-10-04-hypothex-phase3-frontend.md). Reviewed baseline: `a4441256f39d014d9ad43dea976af1b448f163e3`, whose SQLite schema is 3. Backend Tasks 34–35 advance the disposable SQLite index to 4 and package Alembic revision `0001_phase3` for PostgreSQL. Do not label SQLite rebuilding as an Alembic upgrade or call `hx db upgrade` on a SQLite home expecting success.

## Files and ownership

Create during implementation:

- `tests/packaging/__init__.py`, `tests/packaging/test_installed.py`, `tests/packaging/test_runner.py`: pytest orchestration and harness unit tests; only the installed test module has the `package` marker.
- `tests/packaging/runner.py`: build/install and subprocess ownership; stdlib-only control code, executable by the source checkout's Python without importing `hypothex`.
- `tests/packaging/installed_checks.py`: assertions executed with the wheel interpreter using `-I`, copied outside the checkout; only stdlib and declared runtime dependencies.
- `tests/packaging/make_schema3_fixture.py`: maintainer-only generator against the pinned old source, never imported by the new wheel tests.
- `tests/fixtures/package-schema3/`: immutable SQL dumps, file tree, `manifest.json`, `expected.json`, and generation README. Generated synthetic data only; no user's home or credentials.
- `ui/playwright.package.config.ts`, `ui/package-e2e/installed.spec.ts`, `ui/package-e2e/tsconfig.json`: smoke of the installed application's static UI, separate from development-server fixtures.
- `docs/package-testing.rst`: exact automated and manual test path, expected results, restart behavior, artifact locations.

Modify `pyproject.toml` (marker/default marker expression and, only if a regression demonstrates it, package-data rules), `.github/workflows/ci.yml` (seventh check), `docs/index.rst` (toctree), README (short testing link). Production fixes exposed by these tests belong to their existing task owners; rerun this task after fixing them. Every new Python function/method has annotations and a numpydoc docstring; every public harness operation has a unit test covering a meaningful failure or success condition.

The existing packaging mechanism is Hatchling, **not a custom build hook**. `ui/package.json`'s `bun run build` invokes TypeScript then Vite and emits `src/hypothex/ui_dist`; `pyproject.toml` includes this ignored directory in both the wheel and sdist `artifacts` rules. Plain `uv build` builds an sdist and then a wheel from that sdist. Exercise exactly that path, not only `uv build --wheel`. Tracked Python migration files are included with the package; verify that `script.py.mako` is also present, adding an explicit Hatchling rule if necessary. Do not solve missing resources by reading the checkout from installed code.

## Step 1 — write the failing acceptance tests first

Add `package: installed-wheel acceptance, run explicitly with -m package` to pytest markers and change default `addopts` to `-m 'not docker and not package'`; explicit `-m package` overrides it. Preserve the Docker marker and all existing checks. A selected package test must fail if its wheel/fixture/browser prerequisite is absent; it must never skip because `CI`, Bun, a migration, or a fixture is missing.

The pytest driver obtains one session-scoped `PackageRun` from `runner.py`. Its root is `tempfile.mkdtemp(prefix="hx-package-")`, resolved and asserted not under the checkout. It uses separate `venv`, `cwd`, `bin`, `private`, and `artifacts` directories. A caller-supplied `HX_PACKAGE_ARTIFACTS` is the destination for sanitized results, not the installation or home directory. The driver itself may run in the source dev environment; no product assertions run there.

Implement these concrete tests, in this order, with independent homes so pytest order is irrelevant:

| Test | Mandatory assertion / expected first failure |
|---|---|
| `test_wheel_import_resources_and_migration` | Execute the resource/migration checker below with the installed interpreter; before Phase 3 it fails because the migration package/head is absent. |
| `test_packaged_default_token_start_restart` | Fresh non-team demo, packaged static assets, real token gate/HTTP behavior, rotating local root credential on restart. |
| `test_packaged_team_pair_login_restart` | Packaged `--with-team`, default dependency closure, local owner credential discovery, paired CLI persists across restart, browser smoke. Before Task 45 it fails on unsupported `--with-team`. |
| `test_schema3_home_upgrade_restart_and_reindex` | Frozen schema-3 fixture, preserved files/scores/bound population, schema 4, scoped sessions/settings/notebook survive restart and explicit reindex, browser smoke. Before Task 34 it fails on actual schema version 3, not an invented missing SQL column. |
| `test_missing_packaged_asset_is_reported` | Unit-test resource manifest validation against a synthetic directory missing `index.html` or a referenced JS asset; fails clearly, never falls back to source UI. |
| `test_runner_rejects_checkout_interpreter_and_cleans_up` | Unit-test path guard and controlled failing child: installed module under source is rejected, owned subprocesses receive bounded termination, unrelated PID is untouched. |
| `test_fixture_restoration_preserves_bound_bytes` | Restore frozen fixture twice outside repo; validate manifest, schema 3 before any new `Context.open`, identical per-example raw bytes/hashes, distinct correctly relocated project paths. |

Implement unit-only harness tests in a separate unmarked `tests/packaging/test_runner.py` so the normal test suite covers their control logic without building a wheel. The table's last three tests live there. All behavioral package assertions must be hard assertions of observed state, not only CLI exit code or a worker's own success flag. Write tests and fixture first; record genuine red results against the pinned baseline or pre-fix implementation, then implement fixes. An initial collection failure from a missing harness is not the final regression evidence.

The concrete pytest entrypoint is:

```python
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.packaging.runner import PackageRun

pytestmark = pytest.mark.package


@pytest.fixture(scope="session")
def installed() -> Iterator[PackageRun]:
    """
    Build one wheel and install it in an external disposable environment.

    Yields
    ------
    PackageRun
        Owner of all installed subprocesses and sanitized evidence.
    """
    run = PackageRun.create(checkout=Path(__file__).resolve().parents[2])
    try:
        run.prepare()
        yield run
    finally:
        run.close()


def test_wheel_import_resources_and_migration(installed: PackageRun) -> None:
    """
    Require imports and resources from the built wheel and execute its revision.

    Parameters
    ----------
    installed : PackageRun
        Isolated installed-wheel harness.
    """
    installed.check_resources()


def test_packaged_default_token_start_restart(installed: PackageRun) -> None:
    """
    Exercise a packaged token server, its browser UI and restart credentials.

    Parameters
    ----------
    installed : PackageRun
        Isolated installed-wheel harness.
    """
    installed.check_token_start_restart()


def test_packaged_team_pair_login_restart(installed: PackageRun) -> None:
    """
    Exercise packaged team seeding, real pairing, saved login and browser reload.

    Parameters
    ----------
    installed : PackageRun
        Isolated installed-wheel harness.
    """
    installed.check_team_pair_login_restart()


def test_schema3_home_upgrade_restart_and_reindex(installed: PackageRun) -> None:
    """
    Preserve old evaluation evidence and new auth across upgrade and rebuild.

    Parameters
    ----------
    installed : PackageRun
        Isolated installed-wheel harness.
    """
    installed.check_schema3_upgrade_restart_reindex()
```

`PackageRun.create(*, checkout: Path) -> PackageRun` allocates the external root and artifact directory; `prepare() -> None` builds and installs once. Each `check_*() -> None` creates its own scenario home, copies the external checker, and executes Steps 3–6 with mandatory assertions in `installed_checks.py`; a failed assertion/nonzero child propagates as a pytest failure with a sanitized traceback. These methods may not merely return a success flag. `close() -> None` is idempotent, always terminates owned children before removing private data, copies release artifacts/reports, and raises on leaked children or artifact secrets; cleanup failure must not hide the original test error. Implement private helpers `run_checked(argv: list[str], *, cwd: Path, env: dict[str, str], timeout: float) -> subprocess.CompletedProcess[str]`, `restore_schema3(destination: Path, interpreter: Path) -> dict[str, object]`, and `browser(descriptor: Path) -> None` using the exact boundaries below. Unit tests cover timeout/failed-assertion propagation, redaction and restoration, not a mock that always returns success.

## Step 2 — freeze a real schema-3 home

Do not synthesize an old home by changing `meta.schema_version` in a database created by the new models. Generate once from a clean `git archive a4441256f39d014d9ad43dea976af1b448f163e3` extracted under a fresh temporary directory. Run `uv sync --locked --all-groups` there and execute the generator under that checkout's interpreter. Check `hypothex.__file__` resolves inside that old archive and `SCHEMA_VERSION == 3` before writing anything. This generation is a maintainer step; ordinary CI restores the committed fixture and does not fetch Git history or resolve the old lockfile.

The generator reuses the pinned source's `tests.factories.write_toy_project`, `seed_finished_run`, and `tests.core.test_bound_comparison.bound_pair`, with the old archive as working directory/import root. Call `write_toy_project(root / "toy", use_git=False)`; no Git process is required for this fixture. Resolve both archive and fixture root before path comparisons (macOS `/tmp` and `/var` have physical aliases). The latter uses real evaluator workers, writes two finished runs `a` and `b` for project `toy`, task `toy-acc`, dataset `toyset@v1/test`, and produces complete evaluator-issued binding fields. Invoke it once and capture `compare_examples(ctx, "a", "b", "accuracy", require_bound=True).model_dump(mode="json")` as the oracle: `fixed == ["ex-3"]`, `broken == []`, `both_pass == 3`, `both_fail == 0`. Retain whole score records, including `source_hash`, `per_example_hash`, `evaluation_examples`, and `evaluation_ids_hash`; do not reconstruct reduced score dictionaries.

Also add one separate legacy finished run `legacy` with a valid older/unbound `ScoreRecord` (binding fields None); it must remain unbound after upgrade. Store one metric history through old `Context`/store APIs and assert its known points through the old query path. This exercises both raw records and the disposable index. Record full expected score JSON for each run and project/task/run identities. The fixture is small: four examples per bound run, a handful of points, no model downloads or training.

After all evaluator workers finish, close/dispose old SQLAlchemy engines and checkpoint SQLite WAL. Export `index.db` and `events.db` with stdlib `sqlite3.Connection.iterdump()` and omit binary DB/WAL/SHM files from the committed fixture. Validate `PRAGMA integrity_check == 'ok'` and `SELECT value FROM meta WHERE key='schema_version' == '3'`. Preserve the old `environment.json` and project/run files. The fixture manifest records generator source SHA, old import path relative to the archive, generator hash, file hashes, expected run IDs and score bindings, and permitted path substitutions.

Make it portable **without changing bound bytes**: replace the temporary fixture root with literal `__HX_FIXTURE_ROOT__` only in explicitly enumerated path-bearing text files and SQL dumps; record this allowlist in the manifest. These include project registry/config, run cwd/provenance paths, and their indexed copies. Preserve `predictions/scores.accuracy@v1.jsonl`, predictions inputs, dataset contents, `scores.jsonl`, all recorded hashes, and evaluator source bytes byte-for-byte. Reject the placeholder in a bound file. The source fixture root is a plain path without quote/backslash characters; at restore, use structured parsing for JSON/YAML and correctly SQL-quote paths in dump text (or restore SQL then update enumerated path columns). Do not blindly replace arbitrary file bytes. The old helper also embeds its Python executable in the toy config: enumerate those config/registry fields separately, replace it with `__HX_FIXTURE_PYTHON__`, and restore that marker to the installed venv interpreter before validation. Preserve evaluator source bytes and recorded score provenance. Reject unresolved placeholders and references to the generator directory/interpreter. Record hashes both before relocation and immediately after relocation, so later upgrade comparisons use the latter.

Restore `index.sql`/`events.sql` to a new root with stdlib sqlite3 **before importing Phase 3**. Include representative saved `serve/server.json` in the template with token `schema3-synthetic-root`, port, hostname, environment_id, home, PID/create-time fields matching old `ServerInfo` shape. On each restoration, replace hostname/home/environment_id with this fixture's values and PID with a just-spawned, waited-for harmless child PID; assert it is dead immediately before `serve`. Use a port reserved for this harness and released immediately before launch, never a real endpoint. Set file mode 0600 and directory 0700. This verifies reclaiming real stale server state rather than failing on a foreign hostname/live process or deleting the file to avoid the behavior.

Generation README retains exact archive/generation commands and expected comparison JSON. Commit the fixture as data only; package tests must not import baseline helpers or Phase 3 helpers to recreate schema 3. Assert the archived fixture files remain unchanged after every test.

## Step 3 — build and install outside the checkout

`PackageRun.prepare()` runs the following sequence once, with bounded subprocess timeouts and captured sanitized logs:

```sh
# At the implementation worktree root; do not run in the main checkout.
uv sync --locked --all-groups
bun --cwd ui install --frozen-lockfile
bun --cwd ui run build
uv build --out-dir "$package_build_dir"
uv venv --python 3.13 "$package_root/venv"
uv pip install --python "$package_root/venv/bin/python" "$package_wheel"
```

Here the runner supplies absolute task-specific paths using argument arrays, checks exactly one newly built wheel and one sdist exist, and hashes both. `uv pip install` is uv's supported wheel-install command; there is no direct pip/poetry/conda invocation. Build output uses a newly created directory, preventing selection of an old wheel. Do not install `.[dev]`, test extras, `-e`, or `--system` into this venv. No source code is copied into site-packages manually. Copy only `installed_checks.py` and fixture input to the external harness directory. Run product probes with `[venv_python, "-I", external_checker, operation, ...]`, `cwd=package_root/cwd`, and product CLI with the absolute `venv/bin/hx` path and explicit `--home`.

Child environment construction removes `PYTHONPATH`, `PYTHONHOME`, `VIRTUAL_ENV`, inherited `HYPOTHEX_*`, `HX_DEMO_*`, and proxy settings, then adds only this test's explicit values. Do not mutate the user's shell/home environment. Retain ordinary OS runtime variables and the baseline refusal wrappers for SSH/SCP, SLURM, `nvidia-smi`, and Tailscale; the wrappers must fail if accidentally invoked. Demo fake hosts use their own documented fake machinery. Check all server/public/notification URLs are loopback; no real SSH, credentials, GPUs, SMTP, Slack, Tailscale, or providers are used. Ordinary package/dependency installation is the only network provisioning step.

The installed resource checker implements these executable assertions (no pytest import):

```python
from importlib import resources, util
from pathlib import Path
import sysconfig

import hypothex
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from hypothex.core.index import HEAD_REVISION, SCHEMA_VERSION
from hypothex.core.migrations import alembic_config

package = Path(hypothex.__file__).resolve()
assert package.is_relative_to(Path(sysconfig.get_paths()["purelib"]).resolve())
assert not package.is_relative_to(checkout.resolve())  # checkout is an input Path
assert "PYTHONPATH" not in child_env  # runner also records sanitized sys.path
root = resources.files("hypothex")
assert root.joinpath("ui_dist/index.html").is_file()
for name in ("__init__.py", "env.py", "script.py.mako", "versions/0001_phase3.py"):
    assert root.joinpath("core/migrations", name).is_file(), name
for name in ("pytest", "aiosmtpd", "trustme", "sklearn", "sphinx"):
    assert util.find_spec(name) is None, name
config = alembic_config(f"sqlite:///{scratch / 'migration-check.db'}", None)
assert ScriptDirectory.from_config(config).get_current_head() == HEAD_REVISION == "0001_phase3"
command.upgrade(config, "head")
engine = create_engine(config.attributes["url"])
with engine.connect() as connection:
    assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == HEAD_REVISION
    assert connection.execute(text("SELECT value FROM meta WHERE key='schema_version'")).scalar() == str(SCHEMA_VERSION) == "4"
engine.dispose()
```

Wrap this block in annotated functions with numpydoc docstrings; `checkout`, `child_env`, and `scratch` are explicit checker/runner inputs, not ambient globals. This disposable SQLite database exercises packaged Alembic files using the same direct `alembic_config` route as backend Task 35's test; it is **not a supported SQLite home migration command**. No offline migration mode exists. Real PostgreSQL migration/equivalence remains Task 36's Docker gate. Also parse installed `index.html` asset URLs, require at least one JS and CSS file, reject source/dev-server URLs, and verify every local referenced asset exists under the installed UI directory. Check wheel metadata has no unconditional pytest/aiosmtpd/trustme/Sphinx requirement, and retain `uv pip list --python <venv-python> --format json` as dependency evidence.

## Step 4 — exercise actual installed processes

`PackageRun.start(home, *, port, auth)` uses absolute installed `hx --home HOME serve --host 127.0.0.1 --port PORT` and `--auth` only when enabling scoped mode. It owns the Popen object/process group, captures stdout/stderr privately, waits at most 60 seconds for matching `serve/server.json` PID/environment identity plus the public `/.well-known/hypothex/environment` response, and fails if the child exits early or another environment answers. Port allocation retries only on a positively identified bind collision; never reuse an existing server. All HTTP calls use explicit loopback URL and timeout. Stop uses SIGTERM, bounded wait (90 seconds for demo children), then owned process-group kill on failure; cleanup happens in `finally`, including browser failure. Verify the main PID and recorded demo descendants are gone, and owned server.json is removed. Never signal a PID from an untrusted preexisting record.

1. **Fresh default token case.** Seed `hx --home TOKEN_HOME demo --kinds generic,training --json`, start with no `--auth`/`--no-auth`, assert root UI returns HTML, protected API gives 401 without a token and 200 with the live server.json token, and all installed JS/CSS URLs return 200 with correct content types. Test deep-link HTML for `/settings`, `/storage`, `/n/toy-classifier`, `/n/toy-classifier/YYYY-MM-DD`, `/pair` and a known `/r/<id>` in both auth modes; API denial must stay JSON. Restart at the same port/home, assert environment_id/data preserved, a fresh generated root token differs, old token fails and new token works. The token is not a persistent scoped session.
2. **Fresh packaged team case.** Seed `hx --home TEAM_HOME demo --kinds generic,training --with-team --json` using only installed dependencies; no test SMTP library may appear in its environment. Start; validate fresh private demo pairing file has `sv` and `alice` links on this loopback origin and fakes started. With only `HYPOTHEX_HUB_URL=URL` (no explicit bearer), run owner CLI `whoami --json` using `--home TEAM_HOME`; local server.json discovery must report `sv/admin`. Create a fresh `hx pair --user alice --scope launch --client cli --json`, redeem its returned `url` with `hx --home ALICE_HOME login URL --json`, then use the same `HYPOTHEX_HUB_URL` for `whoami --json` and `projects --json` in ALICE_HOME. Assert alice/launch, same project IDs as owner, mode 0600 hub-tokens file, and no token in login output. Another empty client home must fail authentication. Test an explicit wrong `HYPOTHEX_HUB_TOKEN` overrides the saved login and fails. Browser gets its own newly issued browser offer, never reuses the one-use CLI offer.
3. Stop/restart team server at the **same origin** without reseeding. Local session token/session ID rotates and the old local bearer is rejected; Alice's paired session ID remains the same and works without re-login. Preserve users and demo notebook entries. For fake readiness inspect the live host state and loopback endpoints, and run `hx notify test slack --json` and `hx notify test email --json` through the running hub. Require each actual send result to equal `{"ok": true, "error_class": null}` (the same handshake assertion as Task 45), not just a configured-channel status. These demo sinks do not retain message bodies; Task 48's separate fakes own delivery-body/receipt assertions. Task 48 continues to own the full host-launch/notification scenarios.
4. Run packaged browser smoke while each server is alive, including after restart. Result collection never prints pairing URLs, session cookies or bearer tokens.

## Step 5 — upgrade, restart and rebuild the frozen home

Restore the frozen fixture into `UPGRADE_ROOT`, verify old schema by raw sqlite3 and all bound-file hashes, then run installed `hx --home UPGRADE_HOME projects --json`. This is the first Phase 3 open and must automatically rebuild to `meta.schema_version == '4'`; inspect with sqlite3 afterwards. Compare project/task/run IDs, statuses, known metric history and **whole score JSON** against frozen expected values (normalizing only the explicit path relocation). Strict comparison of a/b via installed `compare_examples(..., require_bound=True)` and HTTP `/api/v1/compare/examples?a=a&b=b&metric=accuracy&require_bound=true` must match the old oracle; legacy scores stay unbound. Raw `run.yaml`, `scores.jsonl`, prediction/per-example files and dataset bytes match post-relocation snapshots. Do not accept counts alone. Also require `PRAGMA integrity_check == 'ok'` and no corrupt-file fallback.

Start this restored home in token mode to verify stale server.json reclamation and token discovery; old synthetic root bearer must fail, new bearer succeeds. Stop. Enable scoped auth using installed `load_settings`/`save_settings` with `server.auth="on"` (preserve all existing fields), start with `--auth`, and discover the local owner via `whoami`. Create `alice` using `hx pair --new-user --user alice --scope launch --client cli --json`, log in from a new ALICE_HOME, and compare HTTP data through her saved credential. Add a notebook entry using `hx note --project toy "package upgrade [[run:a]]" --day 2026-10-06 --json` and snapshot settings plus notebook bytes. No pre-Phase-3 notebook/auth database is invented; these are created **after** upgrade and tested for later persistence.

Stop and restart at the same origin. Assert paired alice session/user persists, fresh local token is minted and old local token revoked, notebook/settings remain, run/score/bound comparisons still match, and browser can pair/reload `/n/toy/2026-10-06`, `/settings`, `/storage`, `/r/a`. Then stop, run installed `hx --home UPGRADE_HOME reindex --json` with hub routing unset, restart and repeat these assertions. Auth lives outside the disposable index: session IDs/users/revocation state must survive. Before reindex, create and revoke a second synthetic client session; it must remain revoked after rebuild. Compare auth semantics, not raw auth.db bytes (timestamps and new local-session rows legitimately change). Retain schema/data/hash/credential reports before upgrade, after upgrade, after restart and after reindex; none include secrets.

## Step 6 — installed browser smoke, no Vite or source server

`ui/playwright.package.config.ts` imports `defineConfig` directly, **not** `e2e/paths`, `fixtures` or the normal playwright config. Set `testDir: './package-e2e'`, `workers: 1`, `retries: 0`, no `webServer`, no trace/video/screenshot, and explicit light/dark Chromium projects. A harness-created private descriptor passed by `HX_PACKAGE_DESCRIPTOR` contains URL, expected environment_id, scenario (`token`, `team`, `upgraded`), home and interpreter paths; file mode 0600. Do not put credentials in env, command arguments, test titles or Playwright attachments. Read live server.json only after checking descriptor paths are under this run's temporary root and matching server identity. Run `bunx playwright test --config playwright.package.config.ts` from `ui` in the parent harness while the installed child serves from outside the repo. Typecheck with `bunx tsc -p package-e2e/tsconfig.json`.

Use direct `@playwright/test` fixtures, and abort non-loopback browser requests. For token scenario, visit a deep link, fill accessible `Token` input and click `Unlock`, confirm page data and authenticated API, reload, then visit a run. For scoped team/upgraded scenarios, request a fresh browser pairing offer as local owner, visit `/pair#...`, fill `device`, click `pair`, assert success heading and `/api/v1/auth/me` user/scope using browser cookie; verify fragment is cleared. Visit settings, storage, notebook and run deep links directly and reload each; assert expected screen heading/data and no failed static requests or unexpected page errors. On upgraded home assert `package upgrade` notebook text and run `a`; on team assert seeded notebook/baselines and `sv`/`alice` ownership. Browser tests receive no runtime import of repository Python or a dev server. Scenario/restart stage is recorded in a sanitized summary.

The complete frontend Task 25 suite still owns all editing, conflict, deletion and theme behavior. This small additional browser suite proves that the **installed wheel** actually serves the built pages in fresh/upgraded and restarted homes. Do not import normal fixtures to gain coverage at the expense of inadvertently launching source `uv run hx`.

## Step 7 — seventh CI check and exact local command

Keep all four `test` matrix combinations, the existing `ui` job and Docker job unchanged in purpose. Add the following sibling job; reuse repository-pinned action/runtime versions rather than inventing versions. Set no `continue-on-error`. Install browsers before the package pytest invocation; the harness owns the build, installation, server and browser lifecycles, so CI and local commands use one path.

```yaml
  package:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    env:
      HX_PACKAGE_ARTIFACTS: ${{ runner.temp }}/hx-package-artifacts
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v10.2.0
        with:
          python-version: "3.13"
      - uses: oven-sh/setup-bun@v2
        with:
          bun-version: "1.3.10"
      - run: uv sync --locked --all-groups
      - run: bun --cwd ui install --frozen-lockfile
      - run: bunx playwright install --with-deps chromium
        working-directory: ui
      - run: bunx tsc -p package-e2e/tsconfig.json
        working-directory: ui
      - run: uv run pytest -m package tests/packaging/test_installed.py -v --junitxml="${HX_PACKAGE_ARTIFACTS}/junit.xml"
      - name: Installed package evidence
        if: always()
        uses: actions/upload-artifact@v7
        with:
          name: installed-package-acceptance
          path: ${{ runner.temp }}/hx-package-artifacts
          retention-days: 7
          if-no-files-found: error
```

Ensure the driver creates the artifact directory before tests/JUnit write (pytest creates missing JUnit parents, but harness results must exist on preparation failure too). Default tests remain free of package builds; Docker keeps its explicit `-m docker`. `package` must be included among required CI checks for release/merge acceptance; a cancelled/skipped package job is not a pass.

Local reproduction, from the isolated implementation worktree:

```sh
uv sync --locked --all-groups
bun --cwd ui install --frozen-lockfile
(cd ui && bunx playwright install chromium)
(cd ui && bunx tsc -p package-e2e/tsconfig.json)
HX_PACKAGE_ARTIFACTS="$(mktemp -d /tmp/hx-package-artifacts.XXXXXX)" uv run pytest -m package tests/packaging/test_installed.py -v
```

The runner prints only sanitized artifact-directory and scenario results. Expected: fresh token, fresh team pair/login/restart, schema3 upgrade/restart/reindex and both-theme browser smoke all pass; import/resource/migration/dependency checks pass; every owned child exits. Package checking complements `uv run pytest`, Ruff, ty, Sphinx and the existing frontend/Docker suites; run affected checks and all required repository checks on final assembled code.

## Step 8 — handoff and retained evidence

Write `docs/package-testing.rst` and link it from the docs toctree and README. Include the automated commands above plus these reviewable manual steps using the **same built wheel path** from `build.json`. The runner copies the wheel/sdist into the sanitized artifact directory before temporary-root cleanup, so that path remains usable:

```sh
package_demo_root=$(mktemp -d /tmp/hx-wheel-demo.XXXXXX)
uv venv --python 3.13 "$package_demo_root/venv"
uv pip install --python "$package_demo_root/venv/bin/python" /absolute/path/to/hypothex-WHEEL.whl
cd "$package_demo_root"
env -u PYTHONPATH -u HYPOTHEX_HUB_URL -u HYPOTHEX_HUB_TOKEN "$package_demo_root/venv/bin/hx" --home "$package_demo_root/home" demo --kinds generic,training --with-team --json
env -u PYTHONPATH -u HYPOTHEX_HUB_URL -u HYPOTHEX_HUB_TOKEN "$package_demo_root/venv/bin/hx" --home "$package_demo_root/home" serve --host 127.0.0.1 --port 0
```

`serve --port 0` selects an ephemeral port; read the displayed URL/server.json rather than guessing it. Explain browser pairing with a fresh owner link, CLI pairing from a second explicit temporary home with `HYPOTHEX_HUB_URL` set, expected `whoami`, then Ctrl-C and restart on the recorded **same port** for persisted paired-token verification. State that local owner sessions rotate at restart, paired sessions persist, and SQLite automatically rebuilds; `hx db upgrade` is PostgreSQL-only. All temporary paths/credentials remain private. The automated upgrade test restores a new synthetic fixture copy; the guide does not ask the user to experiment on a real home.

Retain sanitized `build.json` (source SHA, wheel/sdist SHA256, commands, versions), `installed.json` (import/resource paths, dependency list, migration head), `fixture.json` (pinned source/schema/hash oracle), per-stage preservation/assertion JSON, `browser-summary.json`, JUnit, and process-cleanup summary. Keep private homes/server logs/pairing files separate from uploaded artifacts and remove them in cleanup. Sanitize before upload; test the redactor against known generated secrets and their URL-encoded representations, and fail artifact publication if scanning finds one. Do not upload browser storage state, traces, cookies, raw home/config/secrets, or pairing-bearing stderr. Preserve enough nonsecret failure detail (operation, status, traceback without tokens) to diagnose failures.

Record genuine red/green results and artifact paths in `tasks/todo.md` during implementation. Review the final installed evidence before marking backend Task 49 / contract done9 complete. No tests or package implementation in this supplement have been executed merely by writing this plan.
