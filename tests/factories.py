"""Shared builders for tests."""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from hypothex.core.context import Context
from hypothex.core.ids import utcnow
from hypothex.core.records import GitInfo, RunRecord, RunStatus


def make_record(run_id: str = "r1", project: str = "toy", **overrides: Any) -> RunRecord:
    """Build a valid RunRecord with sensible defaults."""
    base: dict[str, Any] = {
        "run_id": run_id,
        "project": project,
        "task": "t",
        "command": ["echo", "hi"],
        "command_template": ["echo", "hi"],
        "cwd": "/tmp",
        "environment_id": "env1",
        "host": "mac",
        "config_hash": "sha256:abc",
        "status": RunStatus.QUEUED,
        "created_at": utcnow(),
    }
    base.update(overrides)
    return RunRecord.model_validate(base)


def git(repo: Path, *args: str) -> str:
    """Run git in ``repo`` with a fixed identity; return stdout."""
    out = subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def init_git_repo(repo: Path) -> str:
    """Init a repo, commit everything in it, and return the commit sha."""
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", "init")
    return git(repo, "rev-parse", "HEAD")


TOY_METRICS = """\
from hypothex.metrics import MetricResult


def accuracy(examples):
    per = {e.id: {"correct": e.prediction == e.reference} for e in examples}
    value = sum(v["correct"] for v in per.values()) / max(len(per), 1)
    return MetricResult(values={"value": value}, per_example=per)


def broken(examples):
    raise RuntimeError("boom")
"""

TOY_INFER = """\
import json
import os
import sys
from pathlib import Path

run_dir = Path(os.environ["HYPOTHEX_RUN_DIR"])
ckpt = sys.argv[sys.argv.index("--ckpt") + 1]
with (run_dir / "predictions" / "predictions.jsonl").open("w") as fh:
    for i in range(4):
        fh.write(json.dumps({"id": f"ex-{i}", "prediction": i % 2}) + "\\n")
print("inferred with", ckpt)
"""

# references are [0, 1, 0, 0]; these predictions are [0, 1, 0, 1] -> accuracy 0.75
PREDS_075 = [{"id": f"ex-{i}", "prediction": i % 2} for i in range(4)]


def write_toy_project(repo: Path, *, accuracy_version: str = "v1", use_git: bool = True) -> Path:
    """Write a tiny Hypothex project (data, metrics, infer stage) and optionally git-init it."""
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "data").mkdir(exist_ok=True)
    refs = [0, 1, 0, 0]
    (repo / "data" / "test.jsonl").write_text(
        "".join(json.dumps({"id": f"ex-{i}", "reference": r}) + "\n" for i, r in enumerate(refs))
    )
    config = {
        "project": "toy",
        "datasets": {
            "toyset": {
                "version": "v1",
                "path": "data/test.jsonl",
                "splits": {"test": "data/test.jsonl"},
            },
        },
        "metrics": {
            "accuracy": {"version": accuracy_version, "fn": "toymetrics:accuracy"},
            "broken": {"version": "v1", "fn": "toymetrics:broken"},
        },
        "tasks": {
            "toy-acc": {
                "dataset": "toyset",
                "split": "test",
                "metrics": ["accuracy"],
                "primary": "accuracy",
            },
            "toy-broken": {
                "dataset": "toyset",
                "split": "test",
                "metrics": ["accuracy", "broken"],
                "primary": "accuracy",
            },
        },
        "stages": {"infer": f"{shlex.quote(sys.executable)} infer.py --ckpt {{checkpoint}}"},
        "env": {"python": [sys.executable]},
    }
    (repo / "hypothex.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    (repo / "toymetrics.py").write_text(TOY_METRICS)
    (repo / "infer.py").write_text(TOY_INFER)
    if use_git and not (repo / ".git").exists():
        init_git_repo(repo)
    return repo


def seed_finished_run(
    ctx: Context,
    repo: Path,
    run_id: str,
    *,
    task: str = "toy-acc",
    predictions: list[dict] | None = None,
    config_hash: str = "sha256:aaaa",
    commit: str | None = "c1",
    seed: int | None = None,
) -> RunRecord:
    """Register the project and create a finished run, optionally with predictions."""
    entry = ctx.register_project(repo)
    record = make_record(
        run_id,
        project=entry.project,
        task=task,
        status=RunStatus.FINISHED,
        config_hash=config_hash,
        git=GitInfo(commit=commit),
        seed=seed,
        cwd=str(repo),
        environment_id=ctx.descriptor.environment_id,
    )
    ctx.create_run(record)
    if predictions is not None:
        path = ctx.run_dir(record) / "predictions" / "predictions.jsonl"
        path.write_text("".join(json.dumps(p) + "\n" for p in predictions))
    return record
