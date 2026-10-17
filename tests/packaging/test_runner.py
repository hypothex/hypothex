"""Fast harness regressions; no wheel build or real service is needed."""

from __future__ import annotations

import contextlib
import json
import os
import signal
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.packaging.installed_checks import validate_assets
from tests.packaging.runner import (
    CommandFailure,
    PackageRun,
    Server,
    assert_installed_path,
    child_environment,
    run_checked,
)


@pytest.fixture
def package_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[PackageRun]:
    """Yield one external control harness and publish only into a test-owned directory."""
    monkeypatch.setenv("HX_PACKAGE_ARTIFACTS", str(tmp_path / "artifacts"))
    run = PackageRun.create(checkout=Path(__file__).resolve().parents[2])
    try:
        yield run
    finally:
        run.close()


@pytest.mark.parametrize("missing", ["index", "javascript", "css"])
def test_missing_packaged_asset_is_reported(tmp_path: Path, missing: str) -> None:
    """Resource validation fails visibly without using source UI assets."""
    (tmp_path / "assets").mkdir()
    if missing != "index":
        (tmp_path / "index.html").write_text(
            '<html><script src="/assets/app.js"></script><link href="/assets/app.css"></html>'
        )
    if missing != "javascript":
        (tmp_path / "assets/app.js").write_text("export {}")
    if missing != "css":
        (tmp_path / "assets/app.css").write_text("body{}")
    with pytest.raises(AssertionError, match="missing"):
        validate_assets(tmp_path)


def test_packaged_asset_manifest_accepts_only_local_complete_resources(tmp_path: Path) -> None:
    """A complete synthetic production entrypoint passes; an external URL fails."""
    (tmp_path / "app.js").write_text("export {}")
    (tmp_path / "app.css").write_text("body{}")
    entry = tmp_path / "index.html"
    entry.write_text('<script src="/app.js"></script><link href="/app.css">')
    assert validate_assets(tmp_path) == ["/app.js", "/app.css"]
    entry.write_text('<script src="https://example.org/app.js"></script>')
    with pytest.raises(AssertionError, match="outside"):
        validate_assets(tmp_path)


def test_runner_rejects_checkout_interpreter_and_cleans_up(package_run: PackageRun) -> None:
    """Path proof rejects editable imports; cleanup kills only an owned process group."""
    checkout = package_run.checkout
    with pytest.raises(AssertionError):
        assert_installed_path(
            checkout / "src/hypothex/__init__.py",
            package_run.root / "venv/lib/site-packages",
            checkout,
        )
    external = package_run.root / "venv/lib/site-packages"
    assert_installed_path(external / "hypothex/__init__.py", external, checkout)
    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True
    )
    owned = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"], text=True, start_new_session=True
    )
    log = (package_run.root / "private/owned.log").open("w+")
    server = Server(
        owned,
        package_run.root / "private/dummy",
        "http://127.0.0.1:1",
        "synthetic",
        log,
        "",
        "unit",
    )
    package_run.processes.append(server)
    try:
        package_run.close()
        package_run.close()
        assert owned.poll() is not None and unrelated.poll() is None
        assert not package_run.root.exists()
        assert (package_run.destination / "process-cleanup.json").is_file()
    finally:
        os.killpg(unrelated.pid, signal.SIGTERM)
        unrelated.wait(timeout=5)


@pytest.mark.parametrize("schema", [3, 4])
def test_fixture_restoration_preserves_bound_bytes(package_run: PackageRun, schema: int) -> None:
    """Restore authentic old schemas twice with distinct paths and unchanged bound evidence."""
    method = package_run.restore_schema3 if schema == 3 else package_run.restore_schema4
    results = [
        method(package_run.root / "private" / label, Path(sys.executable))
        for label in ("first copy", "second'copy")
    ]
    for result in results:
        root = Path(result["fixture_root"])
        with sqlite3.connect(Path(result["home"]) / "index.db") as db:
            assert db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone() == (
                str(schema),
            )
            assert "owner" not in [row[1] for row in db.execute("PRAGMA table_info(runs)")]
            if schema == 4:
                assert "name" in [row[1] for row in db.execute("PRAGMA table_info(runs)")]
                assert db.execute("SELECT name FROM runs WHERE run_id='a'").fetchone() == (
                    "wide %_ beam",
                )
                assert db.execute("SELECT run_id FROM metric_points_pending").fetchall() == [("a",)]
        assert result["expected"]["comparison"]["fixed"] == ["ex-3"]
        assert result["expected"]["comparison"]["both_pass"] == 3
        assert result["expected"]["records"]["a"]["cwd"] == str(root / "toy")
        assert result["expected"]["projects"][0]["config"]["env"]["python"] == [sys.executable]
        server = Path(result["home"]) / "serve/server.json"
        assert server.stat().st_mode & 0o777 == 0o600
        assert server.parent.stat().st_mode & 0o777 == 0o700
        pid = json.loads(server.read_text())["pid"]
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    assert results[0]["protected_bytes"] == results[1]["protected_bytes"]
    assert results[0]["fixture_hashes"] == results[1]["fixture_hashes"]
    assert (
        results[0]["expected"]["records"]["a"]["cwd"]
        != results[1]["expected"]["records"]["a"]["cwd"]
    )
    for relative in results[0]["protected_bytes"]:
        assert (Path(results[0]["fixture_root"]) / relative).read_bytes() == (
            Path(results[1]["fixture_root"]) / relative
        ).read_bytes()


def test_fixture_manifest_refuses_tampered_bound_data(
    package_run: PackageRun, tmp_path: Path
) -> None:
    """A mutated copied fixture cannot pass its pinned manifest."""
    import shutil

    source = package_run.checkout / "tests/fixtures/package-schema3"
    alternate = tmp_path / "checkout"
    target = alternate / "tests/fixtures/package-schema3"
    shutil.copytree(source, target)
    (target / "tree/toy/data/test.jsonl").write_text("corrupted\n")
    package_run.checkout = alternate
    with pytest.raises(AssertionError):
        package_run.restore_schema3(package_run.root / "private/tampered", Path(sys.executable))


@pytest.mark.parametrize("parent_user", ["runner", "shreyasv"])
def test_child_environments_strip_defaults_after_overrides_and_pin_only_team(
    package_run: PackageRun, monkeypatch: pytest.MonkeyPatch, parent_user: str
) -> None:
    """Every final mapping is PG-free, nonmutating, and preserves explicit synthetic settings."""
    parent = {
        "USER": parent_user,
        "HOME": "/synthetic",
        "PATH": "/bin",
        "PYTHONPATH": "/checkout",
        "PGHOSTADDR": "203.0.113.5",
        "PGSERVICE": "",
        "HTTP_PROXY": "http://203.0.113.2",
        "HYPOTHEX_HUB_TOKEN": "inherited",
    }
    overrides = {
        "PGHOST": "db.example.org",
        "PGPASSWORD": "synthetic-pg",
        "PGSERVICEFILE": "/synthetic/service",
        "HYPOTHEX_INDEX_PASSWORD": "synthetic-explicit",
    }
    before = (dict(parent), dict(overrides))
    clean = child_environment(parent, overrides)
    assert clean == {
        "USER": parent_user,
        "HOME": "/synthetic",
        "PATH": "/bin",
        "HYPOTHEX_INDEX_PASSWORD": "synthetic-explicit",
    }
    assert before == (parent, overrides)
    monkeypatch.setenv("USER", parent_user)
    for label in ("seed", "start", "restart", "cli", "checker"):
        team = package_run.environment(overrides, scenario="team")
        assert team["USER"] == "sv", label
        assert team["HYPOTHEX_INDEX_PASSWORD"] == "synthetic-explicit"
        assert not any(key.startswith("PG") for key in team)
    assert package_run.environment()["USER"] == os.environ["USER"] == parent_user
    assert package_run.environment(scenario="schema4-upgraded")["USER"] == parent_user


def test_actual_command_launch_scrubs_late_pg_overrides(package_run: PackageRun) -> None:
    """An actual child receives the final scrubbed mapping and explicit synthetic credential."""
    result = package_run.command(
        [sys.executable, "-I", "-c", "import json,os; print(json.dumps(dict(os.environ)))"],
        overrides={
            "PGSERVICE": "",
            "PGHOSTADDR": "203.0.113.1",
            "HYPOTHEX_INDEX_PASSWORD": "synthetic-explicit",
        },
        scenario="team",
    )
    received = json.loads(result.stdout)
    assert not any(name.startswith("PG") for name in received)
    assert received["USER"] == "sv"
    assert received["HYPOTHEX_INDEX_PASSWORD"] == "synthetic-explicit"
    assert "PYTHONPATH" not in received and "VIRTUAL_ENV" not in received
    assert Path(received["HOME"]).is_relative_to(package_run.root)


def test_run_checked_propagates_assertions_and_timeouts(tmp_path: Path) -> None:
    """Real failed assertions and timed-out children never become passing harness flags."""
    env = child_environment(dict(os.environ), {"PGHOST": "203.0.113.1"})
    with pytest.raises(CommandFailure) as failure:
        run_checked(
            [sys.executable, "-I", "-c", "assert False, 'deliberate-unit-red'"],
            cwd=tmp_path,
            env=env,
            timeout=5,
        )
    assert "AssertionError: deliberate-unit-red" in failure.value.result.stderr
    marker = tmp_path / "pid"
    script = f"import os,time; open({str(marker)!r},'w').write(str(os.getpid())); time.sleep(60)"
    with pytest.raises(subprocess.TimeoutExpired):
        run_checked([sys.executable, "-I", "-c", script], cwd=tmp_path, env=env, timeout=0.5)
    with pytest.raises(ProcessLookupError):
        os.kill(int(marker.read_text()), 0)


def test_redaction_and_publication_reject_secrets(package_run: PackageRun) -> None:
    """Sanitization covers raw and URL-encoded values; unsanitized artifacts fail closed."""
    from urllib.parse import quote

    secret = "synthetic/private token+value"
    package_run.secrets.add(secret)
    raw = f"{secret} {quote(secret, safe='')} http://127.0.0.1:1/pair#offer=synthetic Bearer abc123"
    redacted = package_run.redact(raw)
    assert secret not in redacted and quote(secret, safe="") not in redacted
    assert "offer=synthetic" not in redacted and "abc123" not in redacted
    package_run.write_report("safe.json", {"diagnostic": raw})
    assert secret not in (package_run.root / "artifacts/safe.json").read_text()
    (package_run.root / "artifacts/unsafe.txt").write_text(secret)
    with pytest.raises(AssertionError, match="secret"):
        package_run.close()
    assert not (package_run.destination / "unsafe.txt").exists()


def test_command_failure_diagnostics_are_sanitized(package_run: PackageRun) -> None:
    """A failing real child's traceback stays useful without leaking its synthetic secret."""
    secret = "synthetic-command-secret"
    package_run.secrets.add(secret)
    with pytest.raises(AssertionError, match="AssertionError") as error:
        package_run.command([sys.executable, "-I", "-c", f"assert False, {secret!r}"])
    assert secret not in str(error.value)
    evidence = list((package_run.root / "artifacts").glob("failure-*.json"))
    assert len(evidence) == 1 and secret not in evidence[0].read_text()


def test_checker_and_browser_refuse_missing_prerequisites(package_run: PackageRun) -> None:
    """Selected acceptance operations fail instead of skipping absent installation or input."""
    with pytest.raises(AssertionError):
        package_run.check_resources()
    with pytest.raises(AssertionError):
        package_run.browser(package_run.checkout / "descriptor.json")


def test_loopback_redirect_is_not_followed() -> None:
    """A loopback redirect to an external host returns without opening the target."""
    import http.server
    import threading

    from tests.packaging.runner import request

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            """Return a redirect whose target must never be contacted."""
            self.send_response(302)
            self.send_header("Location", "https://package-redirect.invalid/")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            """Suppress this synthetic server's routine access log."""

    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, _, headers = request(f"http://127.0.0.1:{server.server_port}/")
            assert status == 302 and headers["Location"] == "https://package-redirect.invalid/"
        finally:
            server.shutdown()
            thread.join(timeout=5)


def test_owned_descendant_cleanup_after_group_leader_exit(tmp_path: Path) -> None:
    """An owned descendant ignoring SIGTERM is removed after its parent exits."""
    from tests.packaging.runner import _group_alive, _terminate

    child = (
        "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);"
        "print('ready',flush=True);time.sleep(60)"
    )
    parent = (
        "import subprocess,sys;p=subprocess.Popen([sys.executable,'-c',sys.argv[1]],"
        "stdout=subprocess.PIPE,text=True);p.stdout.readline()"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", parent, child],
        cwd=tmp_path,
        env=child_environment(dict(os.environ)),
        text=True,
        start_new_session=True,
    )
    process.wait(timeout=10)
    assert _group_alive(process.pid)
    _terminate(process)
    assert not _group_alive(process.pid)


def test_dispatch_paths_scrub_environment_at_launch(
    package_run: PackageRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLI, checker, browser and server dispatch receive PG-free private environments."""
    from typing import Any

    from tests.packaging import runner

    for key in ("PGHOST", "PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGPASSFILE", "PGPASSWORD"):
        monkeypatch.setenv(key, "synthetic-external-default")
    original_parent = dict(os.environ)
    captured: list[tuple[list[str], dict[str, str]]] = []

    def capture(
        argv: list[str], *, cwd: Path, env: dict[str, str], timeout: float
    ) -> subprocess.CompletedProcess[str]:
        """Capture the real dispatch mapping without replacing its construction."""
        captured.append((argv, dict(env)))
        return subprocess.CompletedProcess(argv, 0, "{}", "")

    monkeypatch.setattr(runner, "run_checked", capture)
    package_run.prepared = True
    (package_run.root / "venv/bin").mkdir(parents=True)
    home = package_run.root / "private/dispatch-home"
    home.mkdir()
    package_run.cli_json(
        home,
        ["demo", "--with-team", "--json"],
        scenario="team",
        overrides={"PGHOST": "late", "HYPOTHEX_INDEX_PASSWORD": "explicit-synthetic"},
    )
    package_run.checker("resources", {}, scenario="team")
    descriptor = package_run.root / "private/descriptor.json"
    descriptor.write_text("{}")
    descriptor.chmod(0o600)
    package_run.browser(descriptor)
    assert len(captured) == 3
    assert captured[0][1]["HYPOTHEX_INDEX_PASSWORD"] == "explicit-synthetic"
    assert captured[0][1]["USER"] == captured[1][1]["USER"] == "sv"
    assert "HX_PACKAGE_DESCRIPTOR" in captured[2][1]
    for argv, env in captured:
        assert argv and not any(key.startswith("PG") for key in env)
        assert Path(env["HOME"]).is_relative_to(package_run.root)

    # Servers use Popen directly, so inspect that boundary independently on start/restart.
    (home / "environment.json").write_text('{"environment_id":"synthetic"}')
    original_popen = subprocess.Popen

    def server_child(argv: list[str], **kwargs: Any) -> subprocess.Popen[str]:
        """Launch a controlled failing child using the captured server environment."""
        captured.append((argv, dict(kwargs["env"])))
        return original_popen([sys.executable, "-c", "raise SystemExit(7)"], **kwargs)

    monkeypatch.setattr(runner.subprocess, "Popen", server_child)
    # _terminate reads process state using subprocess.run, which also dispatches Popen.
    monkeypatch.setattr(runner, "_group_alive", lambda group: False)
    monkeypatch.setattr(runner, "_descendant_identities", lambda pid: {})
    monkeypatch.setattr(runner, "_remaining_descendants", lambda identities: [])
    for _ in range(2):
        with pytest.raises(AssertionError, match="exited before readiness"):
            package_run.start(home, scenario="team")
    assert len(captured) == 5
    for _, env in captured[-2:]:
        assert env["USER"] == "sv" and not any(key.startswith("PG") for key in env)
    assert dict(os.environ) == original_parent


def test_source_provenance_distinguishes_dirty_input_from_head(tmp_path: Path) -> None:
    """An unchanged HEAD cannot hide changed or untracked packaged source bytes."""
    from tests.packaging.runner import source_provenance

    source = tmp_path / "src/example.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "synthetic"\n')
    cache = source.parent / "__pycache__"
    cache.mkdir()
    (cache / "example.pyc").write_bytes(b"private cache")
    clean = source_provenance(tmp_path, "")
    assert clean["source_dirty"] is False
    assert set(clean["source_files"]) == {"src/example.py", "pyproject.toml"}
    source.write_text("VALUE = 2\n")
    added = source.parent / "new.py"
    added.write_text("ADDED = True\n")
    dirty = source_provenance(tmp_path, " M src/example.py\n?? src/new.py\n")
    assert dirty["source_dirty"] is True
    assert dirty["source_status"] == [" M src/example.py", "?? src/new.py"]
    assert dirty["source_files"]["src/example.py"] != clean["source_files"]["src/example.py"]
    assert "src/new.py" in dirty["source_files"]


def test_start_reads_final_scoped_credential_after_readiness(
    package_run: PackageRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Provisional server.json credentials can rotate before HTTP readiness completes."""
    from typing import Any

    from tests.packaging import runner

    package_run.prepared = True
    (package_run.root / "venv/bin").mkdir(parents=True)
    home = package_run.root / "private/start-home"
    (home / "serve").mkdir(parents=True)
    (home / "environment.json").write_text('{"environment_id":"synthetic"}')
    record_path = home / "serve/server.json"
    original_popen = subprocess.Popen

    def spawn(argv: list[str], **kwargs: Any) -> subprocess.Popen[str]:
        """Start an owned inert child and publish a provisional identity record."""
        process = original_popen([sys.executable, "-c", "import time;time.sleep(60)"], **kwargs)
        record_path.write_text(
            json.dumps(
                {
                    "pid": process.pid,
                    "home": str(home),
                    "environment_id": "synthetic",
                    "token": "provisional-synthetic",
                }
            )
        )
        return process

    def ready(url: str, **kwargs: Any) -> tuple[int, dict[str, str], dict[str, str]]:
        """Complete scoped credential initialization as the public endpoint becomes ready."""
        record = json.loads(record_path.read_text())
        record["token"] = "final-synthetic"
        record_path.write_text(json.dumps(record))
        return 200, {"environment_id": "synthetic"}, {}

    def token(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        """Return the final credential discovered by the installed CLI boundary."""
        return subprocess.CompletedProcess(argv, 0, "final-synthetic\n", "")

    monkeypatch.setattr(runner.subprocess, "Popen", spawn)
    monkeypatch.setattr(runner, "request", ready)
    monkeypatch.setattr(runner, "_group_alive", lambda group: False)
    monkeypatch.setattr(runner, "_descendant_identities", lambda pid: {})
    monkeypatch.setattr(runner, "_remaining_descendants", lambda identities: [])
    monkeypatch.setattr(package_run, "command", token)
    try:
        server = package_run.start(home, auth=True)
        assert server.token == "final-synthetic"
    finally:
        record_path.unlink(missing_ok=True)
        for server in list(package_run.processes):
            package_run.stop(server)


def test_descendant_identity_proof_includes_detached_children(tmp_path: Path) -> None:
    """A detached owned child is tracked, while a different PID birth identity is ignored."""
    import time

    from tests.packaging.runner import _descendant_identities, _remaining_descendants

    marker = tmp_path / "child"
    script = (
        "import subprocess,sys,time;"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],"
        "start_new_session=True);"
        "open(sys.argv[1],'w').write(str(p.pid));time.sleep(60)"
    )
    parent = subprocess.Popen([sys.executable, "-c", script, str(marker)], start_new_session=True)
    child = None
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        child = int(marker.read_text())
        identities = _descendant_identities(parent.pid)
        assert child in identities and os.getpgid(child) != os.getpgid(parent.pid)
        assert _remaining_descendants(identities) == [child]
        assert _remaining_descendants({child: "different process start"}) == []
        os.kill(child, signal.SIGTERM)
        deadline = time.monotonic() + 5
        while _remaining_descendants(identities) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert _remaining_descendants(identities) == []
    finally:
        if child is not None:
            with contextlib.suppress(ProcessLookupError):
                os.kill(child, signal.SIGKILL)
        parent.terminate()
        parent.wait(timeout=5)
