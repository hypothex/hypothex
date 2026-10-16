"""Maintainer-only historical generation; never imported by installed acceptance."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT_MARKER = "__HX_FIXTURE_ROOT__"
PYTHON_MARKER = "__HX_FIXTURE_PYTHON__"
REVISIONS = {
    3: "a4441256f39d014d9ad43dea976af1b448f163e3",
    4: "e73b8105df32a1d2488477c48e680cb5de922771",
}
STAMP = datetime(2026, 10, 6, 12, tzinfo=UTC)


def _digest(path: Path) -> str:
    """Return the SHA256 of a file without altering its bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _replace_fields(
    value: Any, source: str, python: str, fields: list[list[Any]], at: tuple[Any, ...] = ()
) -> Any:
    """Relocate only explicitly recorded string leaves in structured documents."""
    if isinstance(value, dict):
        return {
            key: _replace_fields(child, source, python, fields, (*at, key))
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [
            _replace_fields(child, source, python, fields, (*at, i))
            for i, child in enumerate(value)
        ]
    if isinstance(value, str) and (source in value or python in value):
        fields.append(list(at))
        return value.replace(python, PYTHON_MARKER).replace(source, ROOT_MARKER)
    return value


def _extras(ctx: Any, repo: Path) -> None:
    """Seed schema-4 direction, score-key, obsolete-version and naming cases through old APIs."""
    import yaml

    from hypothex.core import queries
    from hypothex.core.fsutil import append_jsonl
    from hypothex.core.records import ScoreRecord
    from hypothex.core.views import save_view
    from tests.factories import seed_finished_run

    config = yaml.safe_load((repo / "hypothex.yaml").read_text())
    for name, direction in (("up", True), ("down", False), ("latency", None)):
        config["metrics"][name] = {"version": "v1", "fn": "toymetrics:accuracy"}
        if direction is not None:
            config["metrics"][name]["higher_is_better"] = direction
    config["tasks"].update(
        {
            "direction": {
                "dataset": "toyset",
                "split": "test",
                "metrics": ["up", "down"],
                "primary": "up",
            },
            "bench": {
                "kind": "system_bench",
                "dataset": "toyset",
                "split": "test",
                "metrics": ["latency"],
                "primary": "latency/p95",
            },
            "matrix": {
                "dataset": "toyset",
                "split": "test",
                "metrics": ["accuracy"],
                "primary": "accuracy/set-0.m-a.top1",
                "score_keys": "{dataset}.{model}.{metric}",
            },
        }
    )
    (repo / "hypothex.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    ctx.register_project(repo)
    queries.rename_run(ctx, "a", "wide %_ beam")
    parented = seed_finished_run(ctx, repo, "parent-child", config_hash="parented")
    parented.parent = "a"
    ctx.store.write_record(parented)
    ctx.index.upsert_run(parented)
    for task in ("direction", "bench", "matrix"):
        for i, value in enumerate((0.25, 0.75)):
            record = seed_finished_run(
                ctx, repo, f"{task}-{i}", task=task, config_hash=f"{task}-{i}", seed=i
            )
            metrics = (
                [("up", "value", value), ("down", "value", value)]
                if task == "direction"
                else (
                    [("latency", "p95", value * 100)]
                    if task == "bench"
                    else [
                        ("accuracy", "set-0.m-a.top1", value),
                        ("accuracy", "set-1.m-a.top1", value / 2),
                    ]
                )
            )
            for metric, key, val in metrics:
                ctx.add_score(
                    record,
                    ScoreRecord(
                        metric=metric,
                        version="v1",
                        key=key,
                        value=val,
                        source_hash="sha256:synthetic",
                        created_at=STAMP,
                    ),
                )
            ctx.add_score(
                record,
                ScoreRecord(
                    metric=metrics[0][0],
                    version="v0",
                    key=metrics[0][1],
                    value=99,
                    source_hash="sha256:obsolete",
                    created_at=STAMP + timedelta(seconds=1),
                ),
            )
            # Numeric quantity controls system_bench despite the deliberately opposite ok flag.
            if task == "bench":
                path = ctx.run_dir(record) / "predictions/scores.latency@v1.jsonl"
                append_jsonl(path, {"id": "sample", "p95": value * 100, "ok": i == 0})
    text = (
        "title: Package comparison\npanels:\n  - type: compare\n"
        "    title: Across datasets\n"
        "    data: {datasets: [set-1, set-0], model: m-a, metrics: [top1]}\n"
        "    render: bars\n"
    )
    save_view(repo, "matrix", "package", text)


def generate(schema: int) -> None:
    """Generate a frozen portable home exclusively with the specified historical source.

    Parameters
    ----------
    schema : int
        Exact old schema, either 3 or 4; the revision is fixed in this module.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--guard", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()
    archive, output = args.archive.resolve(), args.output.resolve()
    assert Path.cwd().resolve() == archive
    assert not output.exists(), "fixture is immutable; use a new output directory"
    sys.path.insert(0, str(archive))
    import pytest
    import yaml

    import hypothex
    from hypothex.core import evaluation
    from hypothex.core.context import Context
    from hypothex.core.index import SCHEMA_VERSION, index_run_points
    from hypothex.core.records import ScoreRecord
    from tests import factories
    from tests.core.test_bound_comparison import bound_pair
    from tests.fakes import DEAD_HUB, refuse_host_tools, refuse_remote

    imported = Path(hypothex.__file__).resolve()
    assert imported.is_relative_to(archive / "src")
    assert schema == SCHEMA_VERSION
    # Verify exact archive files against the pinned repository objects, without editing the archive.
    for relative in (
        "src/hypothex/core/index.py",
        "src/hypothex/core/records.py",
        "tests/factories.py",
        "tests/core/test_bound_comparison.py",
    ):
        original = subprocess.check_output(
            [
                "git",
                "-C",
                str(Path(__file__).resolve().parents[2]),
                "show",
                f"{REVISIONS[schema]}:{relative}",
            ]
        )
        assert (archive / relative).read_bytes() == original, relative
    generation_root = Path(tempfile.mkdtemp(prefix=f"hx-schema{schema}-generation-")).resolve()
    root = generation_root / "fixture"
    root.mkdir()
    guard_spec = importlib.util.spec_from_file_location("historical_network_guard", args.guard)
    assert guard_spec and guard_spec.loader
    guard = importlib.util.module_from_spec(guard_spec)
    guard_spec.loader.exec_module(guard)
    isolation = pytest.MonkeyPatch()
    guard.scrub_pg_environment(isolation)
    guard.guard_network(isolation)
    for name in guard.SECRET_VARS:
        isolation.delenv(name, raising=False)
    isolation.setenv("HYPOTHEX_HUB_URL", DEAD_HUB)
    isolation.setenv("HOME", str(generation_root / "os-home"))
    isolation.setenv("USER", "fixture")
    refuse_remote(generation_root / "no-ssh", isolation)
    refuse_host_tools(generation_root, isolation)
    guard.refuse_tailscale(generation_root / "no-tailscale", isolation)
    os_home = generation_root / "os-home"
    os_home.mkdir()
    try:
        with (
            patch.object(factories, "utcnow", return_value=STAMP),
            patch.object(evaluation, "utcnow", return_value=STAMP),
        ):
            ctx = Context.open(root / "home")
            repo = factories.write_toy_project(root / "toy", use_git=False)
            bound_pair(ctx, repo)
            legacy = factories.seed_finished_run(ctx, repo, "legacy", config_hash="legacy")
            ctx.add_score(
                legacy,
                ScoreRecord(
                    metric="accuracy", version="v1", key="value", value=0.5, created_at=STAMP
                ),
            )
            from hypothex.sdk import Run

            with patch("hypothex.sdk.time.time", return_value=STAMP.timestamp()):
                handle = Run(ctx.run_dir(ctx.find_record("a")), "a", "toy")
                for step, value in enumerate((1.0, 0.5, 0.25)):
                    handle.log({"loss": value}, step=step)
            index_run_points(ctx.index, ctx.store, ctx.find_record("a"))
            if schema == 4:
                _extras(ctx, repo)
            from installed_checks import snapshot

            expected = snapshot(ctx, schema)
            comparison = expected["comparison"]
            assert comparison["fixed"] == ["ex-3"] and comparison["broken"] == []
            assert comparison["both_pass"] == 3 and comparison["both_fail"] == 0
            assert [point["value"] for point in expected["history"]] == [1.0, 0.5, 0.25]
            assert all(s["per_example_hash"] is None for s in expected["scores"]["legacy"])
            if schema == 4:
                assert expected["projects"][0]["config_format"] == 2
                assert expected["search"]["%"]["first"] == ["a"]
                assert expected["search"]["_"]["first"] == ["a"]
                assert expected["boards"]["bench:latency/p95"]["higher_is_better"] is False
                assert expected["boards"]["direction:up"]["higher_is_better"] is True
                assert expected["boards"]["direction:down"]["higher_is_better"] is False
                ctx.index.set_cursor("fixture-host", "fixture-remote", 17)
                ctx.index.set_cursor("reserved-host", "reserved-remote", 0)
                ctx.index.mark_scores_stale("legacy")
            ctx.index.engine.dispose()
        index = root / "home/index.db"
        with sqlite3.connect(index) as db:
            assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone() == (
                str(schema),
            )
            columns = [row[1] for row in db.execute("PRAGMA table_info(runs)")]
            assert "owner" not in columns
            if schema == 4:
                assert "name" in columns
                assert "ix_runs_name" in [row[1] for row in db.execute("PRAGMA index_list(runs)")]
                db.execute("DELETE FROM metric_points WHERE run_id='a'")
                db.execute("INSERT OR REPLACE INTO metric_points_pending(run_id) VALUES ('a')")
                db.commit()
            carried = {
                table: [list(row) for row in db.execute(f'SELECT * FROM "{table}" ORDER BY 1')]
                for table in ("host_cursors", "run_changes", "scores_stale")
            }
            pending = [
                row[0]
                for row in db.execute("SELECT run_id FROM metric_points_pending ORDER BY run_id")
            ]
            tables = {
                row[0]: [list(column) for column in db.execute(f'PRAGMA table_info("{row[0]}")')]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
            }
            expected["index_state"] = {
                "carried": carried,
                "pending": pending,
                "schema": tables,
                "generation": int(
                    db.execute("SELECT value FROM meta WHERE key='generation'").fetchone()[0]
                ),
            }
        # Validate deferred hydration independently, leaving frozen input deferred.
        if schema == 4:
            copy = generation_root / "hydration-copy"
            shutil.copytree(root, copy)
            hydrated = Context.open(copy / "home")
            from hypothex.core.queries import metric_history

            assert [
                point.model_dump(mode="json") for point in metric_history(hydrated, "a")
            ] == expected["history"]
            assert hydrated.index.metric_names("a") == ["loss"]
            hydrated.index.engine.dispose()
        identity = json.loads((root / "home/environment.json").read_text())
        server = {
            "pid": 1,
            "port": 0,
            "managed": False,
            "hx_version": "0.1.0.dev0",
            "protocol_version": 1,
            "token": f"schema{schema}-synthetic-root",
            "environment_id": identity["environment_id"],
            "hostname": socket.gethostname(),
            "home": str(root / "home"),
            "pid_create_time": 0.0,
        }
        (root / "home/serve").mkdir(exist_ok=True)
        (root / "home/serve/server.json").write_text(json.dumps(server, indent=2) + "\n")
        output.mkdir(parents=True)
        tree = output / "tree"
        tree.mkdir()
        fields: dict[str, list[list[Any]]] = {}
        protected: dict[str, str] = {}
        original_hashes: dict[str, str] = {}
        sql_columns: dict[str, list[str]] = {}
        for path in sorted(root.rglob("*")):
            if (
                not path.is_file()
                or "__pycache__" in path.parts
                or path.name.startswith(".")
                or path.suffix in (".db", ".pyc")
                or path.name.endswith(("-wal", "-shm"))
            ):
                continue
            relative = path.relative_to(root).as_posix()
            target = tree / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            raw = path.read_bytes()
            original_hashes[relative] = _digest(path)
            is_bound = path.suffix == ".jsonl" or path.suffix == ".py"
            if is_bound:
                assert (
                    str(root).encode() not in raw and str(Path(sys.executable)).encode() not in raw
                ), relative
                target.write_bytes(raw)
                protected[relative] = _digest(path)
            elif str(root).encode() in raw or str(Path(sys.executable)).encode() in raw:
                assert path.suffix in (".json", ".yaml", ".yml"), relative
                value = yaml.safe_load(raw)
                pointers: list[list[Any]] = []
                value = _replace_fields(value, str(root), str(Path(sys.executable)), pointers)
                fields[relative] = pointers
                target.write_text(json.dumps(value, indent=2, default=str) + "\n")
            else:
                target.write_bytes(raw)
        for filename in ("index", "events"):
            database = root / f"home/{filename}.db"
            with sqlite3.connect(database) as db:
                db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
                sql = "\n".join(db.iterdump()) + "\n"
                touched = []
                for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                    table = row[0]
                    names = [column[1] for column in db.execute(f'PRAGMA table_info("{table}")')]
                    for record in db.execute(f'SELECT * FROM "{table}"'):
                        for name, value in zip(names, record, strict=True):
                            if isinstance(value, str) and (
                                str(root) in value or str(Path(sys.executable)) in value
                            ):
                                touched.append(f"{table}.{name}")
                sql_columns[f"{filename}.sql"] = sorted(set(touched))
                assert "'" not in str(root) and "\\" not in str(root)
                sql = sql.replace(str(Path(sys.executable)), PYTHON_MARKER).replace(
                    str(root), ROOT_MARKER
                )
                (output / f"{filename}.sql").write_text(sql)
        expected_fields: list[list[Any]] = []
        expected = _replace_fields(expected, str(root), str(Path(sys.executable)), expected_fields)
        (output / "expected.json").write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n")
        files = {
            p.relative_to(output).as_posix(): _digest(p)
            for p in sorted(output.rglob("*"))
            if p.is_file()
        }
        manifest = {
            "schema": schema,
            "source_revision": REVISIONS[schema],
            "old_import_path": imported.relative_to(archive).as_posix(),
            "generator_sha256": _digest(Path(__file__)),
            "generator_entry_sha256": _digest(Path(sys.argv[0])),
            "source_hashes": {
                relative: _digest(archive / relative)
                for relative in (
                    "src/hypothex/core/index.py",
                    "src/hypothex/core/records.py",
                    "tests/factories.py",
                    "tests/core/test_bound_comparison.py",
                )
            },
            "files": files,
            "protected_bytes": protected,
            "pre_relocation_hashes": original_hashes,
            "path_fields": fields,
            "sql_path_columns": sql_columns,
            "expected_path_fields": expected_fields,
            "run_ids": sorted(expected["records"]),
            "score_bindings": {rid: expected["scores"][rid] for rid in ("a", "b", "legacy")},
        }
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        readme = f"""# Genuine schema-{schema} fixture

Generated from git archive `{REVISIONS[schema]}`.
Old import: `{manifest["old_import_path"]}`; actual SQLite schema: {schema}.

```sh
git archive {REVISIONS[schema]} | tar -x -C ARCHIVE
(cd ARCHIVE && uv sync --locked --all-groups)
cd ARCHIVE
uv run --no-sync python /absolute/checkout/tests/packaging/make_schema{schema}_fixture.py \
  --archive ARCHIVE --output OUTPUT \
  --guard /absolute/checkout/tests/fakes/network.py --receipt RECEIPT
```

The generator checks pinned source bytes, old imported module path, schema, and
evaluator-issued complete scores. Manifest hashes bind frozen files, the generator,
and protected dataset/prediction/evaluator/score bytes. Relocation is restricted to
recorded structured document leaves and SQL columns; no protected byte stream may
contain a placeholder.

Strict comparison oracle:

```json
{json.dumps(comparison, indent=2)}
```

Normal CI restores this data; it never fetches history or regenerates the oracle.
"""
        (output / "README.md").write_text(readme)
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(
            json.dumps(
                {
                    "schema": schema,
                    "revision": REVISIONS[schema],
                    "archive": str(archive),
                    "import": str(imported),
                    "output": str(output),
                    "files": len(files),
                    "comparison": comparison,
                    "guard_sha256": _digest(args.guard),
                    "real_connections": 0,
                },
                indent=2,
            )
            + "\n"
        )
        print(json.dumps({"schema": schema, "files": len(files), "bound_files": len(protected)}))
    finally:
        isolation.undo()
