"""
Snapshot tests of the ``--json`` key sets (spec 11: "CLI ``--json`` snapshot tests").

Agents read ``hx ... --json`` as a stable schema, so a renamed, dropped, or added
key must be a deliberate change. Each test runs real commands on the toy project
and compares the set of key paths of the output (``rows[].primary.mean``; ``[]``
marks list items) with ``tests/cli/snapshots/json_keys.json``. Values are not
compared; other tests check them.

After an intended schema change, rewrite the snapshot and review its diff::

    HYPOTHEX_UPDATE_SNAPSHOTS=1 uv run pytest tests/cli/test_json_snapshots.py
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from hypothex.cli.main import app
from hypothex.core import control
from hypothex.core.context import Context
from tests.api.envserver import remote_hub

runner = CliRunner()
PY = sys.executable
SNAPSHOT = Path(__file__).parent / "snapshots" / "json_keys.json"
UPDATE_ENV = "HYPOTHEX_UPDATE_SNAPSHOTS"
WRITE_PREDS = (
    "import json, os; d = os.environ['HYPOTHEX_RUN_DIR']; "
    "open(d + '/predictions/predictions.jsonl', 'w').write(''.join("
    "json.dumps(dict(id='ex-' + str(i), prediction=i % 2)) + chr(10) for i in range(4)))"
)


def key_paths(value: Any, prefix: str = "") -> set[str]:
    """
    Return every key path in a JSON value; list items share the ``[]`` segment.

    Parameters
    ----------
    value : Any
        Parsed JSON.
    prefix : str
        Path of ``value`` itself.

    Returns
    -------
    set of str
        One path per key at any depth.

    Examples
    --------
    >>> sorted(key_paths({"rows": [{"a": 1}, {"b": {"c": None}}], "n": 2}))
    ['n', 'rows', 'rows[].a', 'rows[].b', 'rows[].b.c']
    """
    paths: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            paths |= {path} | key_paths(item, path)
    elif isinstance(value, list):
        for item in value:
            paths |= key_paths(item, f"{prefix}[]")
    return paths


def hx(*args: str) -> Any:
    argv = list(args)
    argv.insert(argv.index("--") if "--" in argv else len(argv), "--json")
    result = runner.invoke(app, argv, catch_exceptions=False)
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def check_snapshots(outputs: dict[str, Any]) -> None:
    """
    Compare each command's key paths with the snapshot (rewrite it when ``UPDATE_ENV=1``).

    Parameters
    ----------
    outputs : dict of str to Any
        Command name -> its parsed ``--json`` output.
    """
    stored = json.loads(SNAPSHOT.read_text(encoding="utf-8")) if SNAPSHOT.exists() else {}
    got = {name: sorted(key_paths(out)) for name, out in outputs.items()}
    if os.environ.get(UPDATE_ENV) == "1":
        SNAPSHOT.parent.mkdir(exist_ok=True)
        merged = dict(sorted({**stored, **got}.items()))
        SNAPSHOT.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
        return
    problems = []
    for name, paths in got.items():
        want = set(stored.get(name, []))
        added, removed = sorted(set(paths) - want), sorted(want - set(paths))
        if added or removed:
            problems.append(f"hx {name} --json: added {added}, removed {removed}")
    assert not problems, (
        "the --json schema changed; if on purpose, run with HYPOTHEX_UPDATE_SNAPSHOTS=1 "
        "and review the snapshot diff:\n" + "\n".join(problems)
    )


def test_key_paths_merge_list_items_and_stop_at_scalars() -> None:
    value = {"rows": [{"a": 1}, {"a": None, "b": [{"c": 2}]}], "empty": [], "none": None}
    assert key_paths(value) == {"rows", "rows[].a", "rows[].b", "rows[].b[].c", "empty", "none"}
    assert key_paths([1, "x"]) == set() and key_paths(3) == set()


def test_check_snapshots_names_added_and_removed_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(UPDATE_ENV, raising=False)
    path = tmp_path / "keys.json"
    path.write_text(json.dumps({"runs": ["run_id", "status"]}))
    monkeypatch.setattr(sys.modules[__name__], "SNAPSHOT", path)
    check_snapshots({"runs": {"run_id": "r1", "status": "finished"}})
    with pytest.raises(AssertionError, match=r"added \['state'\], removed \['status'\]"):
        check_snapshots({"runs": {"run_id": "r1", "state": "finished"}})


def test_local_commands_keep_their_json_keys(
    toy_repo: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(toy_repo)
    # two seed groups: one with two seeds (stats, the best), one single seed
    run = ["run", "-t", "toy-acc", "--seed"]
    first = hx(*run, "1", "-H", "baseline", "--", PY, "-c", WRITE_PREDS)
    hx(*run, "2", "-H", "baseline", "--", PY, "-c", WRITE_PREDS)
    hx(*run, "1", "-H", "other", "--", PY, "-c", WRITE_PREDS + "  # other")
    sweep = hx(
        "sweep", "create", "-t", "toy-acc", "-H", "x helps", "--grid", "x=1,2", "--seeds", "1",
        "--", PY, "-c", WRITE_PREDS, "{x}", "{seed}",
    )  # fmt: skip
    ctx = Context.open(home)
    for run_id in sweep["run_ids"]:
        control.wait_for_run(ctx, run_id, timeout=60)
    sweep_id = sweep["spec"]["id"]
    check_snapshots(
        {
            "projects": hx("projects"),
            "tasks": hx("tasks"),
            "task show": hx("task", "show", "toy-acc"),
            "leaderboard": hx("leaderboard", "toy-acc"),
            "runs": hx("runs"),
            "show": hx("show", first["run_id"]),
            "sweep show": hx("sweep", "show", sweep_id),
            "sweeps": hx("sweeps"),
        }
    )


def test_host_commands_keep_their_json_keys(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with remote_hub(tmp_path, threaded=True, hub_home=home) as r:
        monkeypatch.setenv("HYPOTHEX_HUB_URL", r.hub_url)
        check_snapshots({"hosts list": hx("hosts", "list"), "hosts status": hx("hosts", "status")})
