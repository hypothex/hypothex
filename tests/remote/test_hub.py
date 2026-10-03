"""Hub supervisors and the run mirror (spec 5.3, 5.5, 5.6, 8A.2-8A.3).

Every host here is an in-process env server (``create_app`` under uvicorn on a
random loopback port, in a thread) or a fake; nothing connects to a real host.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

import pytest

import hypothex.remote.hub as hub_mod
from hypothex.core.context import Context
from hypothex.core.errors import StoreError
from hypothex.core.events import Event, EventLog
from hypothex.core.fsutil import append_jsonl
from hypothex.core.ids import utcnow
from hypothex.core.index import SCHEMA_VERSION, Index
from hypothex.core.records import Artifact, RunRecord, RunStatus, ScoreRecord
from hypothex.remote.client import EnvUnreachableError, RemoteFile
from hypothex.remote.hub import Backoff, mirror_event, wanted_path
from tests.factories import make_record

# index cursors -----------------------------------------------------------------------


def test_cursor_roundtrip_per_host_and_environment(tmp_path: Path) -> None:
    idx = Index(tmp_path / "i.db")
    assert idx.get_cursor("a", "env-1") == 0
    idx.set_cursor("a", "env-1", 5)
    idx.set_cursor("a", "env-2", 9)
    idx.set_cursor("b", "env-1", 1)
    idx.set_cursor("a", "env-1", 7)
    assert (idx.get_cursor("a", "env-1"), idx.get_cursor("a", "env-2")) == (7, 9)
    assert idx.get_cursor("b", "env-1") == 1


def test_cursor_never_moves_back(tmp_path: Path) -> None:
    idx = Index(tmp_path / "i.db")
    idx.set_cursor("a", "env-1", 7)
    idx.set_cursor("a", "env-1", 3)  # a late, older apply
    assert idx.get_cursor("a", "env-1") == 7


def test_clear_keeps_cursors(tmp_path: Path) -> None:
    idx = Index(tmp_path / "i.db")
    idx.set_cursor("a", "env-1", 5)
    idx.clear()
    assert idx.get_cursor("a", "env-1") == 5


def test_old_schema_version_is_rebuilt_with_cursor_table(tmp_path: Path) -> None:
    assert SCHEMA_VERSION == 2
    path = tmp_path / "i.db"
    Index(path).set_cursor("a", "env-1", 5)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(SCHEMA_VERSION - 1),)
        )
    again = Index(path)
    assert again.rebuilt_schema is True
    assert again.get_cursor("a", "env-1") == 0


def test_append_once_writes_one_event_per_key(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "e.db")
    first = log.append_once("mirror:gpu1:env-1:7", "mirror.run_updated", run_id="r1")
    assert first is not None and first.sequence == 1
    assert log.append_once("mirror:gpu1:env-1:7", "mirror.run_updated", run_id="r1") is None
    again = EventLog(tmp_path / "e.db")  # another process, same file
    assert again.append_once("mirror:gpu1:env-1:7", "mirror.run_updated", run_id="r1") is None
    assert again.append_once("mirror:gpu1:env-1:8", "mirror.run_updated", run_id="r1") is not None
    assert [e.sequence for e in log.since(0)] == [1, 2]


# pure helpers ------------------------------------------------------------------------


def test_backoff_sequence_caps_and_resets_after_stable_connection() -> None:
    b = Backoff()
    assert [b.next_delay(0.0) for _ in range(6)] == [3.0, 4.0, 8.0, 16.0, 16.0, 16.0]
    b.connected(100.0)
    assert b.next_delay(129.0) == 16.0  # 29 s is not stable yet
    b.connected(200.0)
    assert b.next_delay(230.0) == 3.0
    assert b.next_delay(231.0) == 4.0


def test_backoff_rejects_empty_delays() -> None:
    with pytest.raises(ValueError, match="delays"):
        Backoff(())


@pytest.mark.parametrize(
    ("rel", "ok"),
    [
        ("run.yaml", True),
        ("scores.jsonl", True),
        ("git.diff", True),
        ("predictions/predictions.jsonl", True),
        ("traces/e1.jsonl", True),
        ("logs/stdout.log", True),
        ("artifacts/model.pt", False),
        ("predictions", False),
        ("random.txt", False),
        ("../run.yaml", False),
        ("logs/../../etc/passwd", False),
        ("/etc/passwd", False),
        ("logs//x", False),
        ("logs\\x", False),
        ("", False),
    ],
)
def test_wanted_path(rel: str, ok: bool) -> None:
    assert wanted_path(rel) is ok


# mirror_event helpers ---------------------------------------------------------------


def seed_run(
    ctx: Context, run_id: str, value: float = 0.5, status: RunStatus = RunStatus.FINISHED
) -> RunRecord:
    """Create a run with one prediction file and one score: emits 2 run.* events."""
    record = ctx.create_run(
        make_record(run_id, environment_id=ctx.descriptor.environment_id, status=status)
    )
    (ctx.run_dir(record) / "predictions" / "predictions.jsonl").write_text(
        '{"id": "e1", "prediction": "x"}\n'
    )
    ctx.add_score(
        record,
        ScoreRecord(metric="acc", version="1", key="value", value=value, created_at=utcnow()),
    )
    return record


class FakeClient:
    """Serves run files straight from a 'remote' home, the way the env server does."""

    def __init__(self, remote: Context) -> None:
        self.remote = remote
        self.fetched: list[str] = []

    def _dir(self, run_id: str) -> Path:
        return self.remote.run_dir(self.remote.find_record(run_id))

    def list_files(self, run_id: str, rel_dir: str = "") -> list[RemoteFile]:
        run_dir = self._dir(run_id)
        return [
            RemoteFile(
                path=f.relative_to(run_dir).as_posix(),
                size=f.stat().st_size,
                mtime_ns=f.stat().st_mtime_ns,
            )
            for f in sorted(run_dir.rglob("*"))
            if f.is_file() and f.name != ".lock"
        ]

    def fetch_file(
        self,
        run_id: str,
        rel_path: str,
        dest: Path,
        *,
        max_bytes: int,
        tail: bool = False,
    ) -> bool:
        try:
            src = self._dir(run_id) / rel_path
        except StoreError:
            return False
        if not src.is_file():
            return False
        data = src.read_bytes()
        if len(data) > max_bytes:
            if not tail:
                return False
            data = data[len(data) - max_bytes :]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        self.fetched.append(rel_path)
        return True

    def get_json(self, path: str, **params: Any) -> Any:
        prefix, _, rest = path.removeprefix("/api/v1/projects/").partition("/")
        if rest != "entry":
            raise AssertionError(f"unexpected GET {path}")
        return self.remote.store.load_project(prefix).model_dump(mode="json")


@pytest.fixture
def pair(tmp_path: Path) -> tuple[Context, Context]:
    return Context.open(tmp_path / "hub"), Context.open(tmp_path / "remote")


def run_event(remote: Context, run_id: str) -> Event:
    return [e for e in remote.events.since(0) if e.run_id == run_id][-1]


# mirror_event ------------------------------------------------------------------------


def test_mirror_event_copies_small_files_and_indexes(pair: tuple[Context, Context]) -> None:
    hub, remote = pair
    record = seed_run(remote, "r1", value=0.75)
    run_dir = remote.run_dir(record)
    append_jsonl(run_dir / "metrics.jsonl", {"name": "loss", "step": 1, "value": 0.5})
    (run_dir / "artifacts").mkdir()
    (run_dir / "artifacts" / "model.pt").write_bytes(b"\0" * 10)
    client = FakeClient(remote)

    mirror_event(hub, client, "gpu1", "env-remote", run_event(remote, "r1"))  # type: ignore[arg-type]

    local = hub.layout.run_dir("toy", "r1")
    assert (local / "predictions" / "predictions.jsonl").read_bytes() == (
        run_dir / "predictions" / "predictions.jsonl"
    ).read_bytes()
    assert (local / "scores.jsonl").read_bytes() == (run_dir / "scores.jsonl").read_bytes()
    assert not (local / "artifacts").exists()
    indexed = hub.index.get_run("r1")
    assert indexed is not None
    assert indexed.environment_id == "env-remote"
    assert indexed.status == RunStatus.FINISHED
    assert [s.value for s in hub.index.scores_for(["r1"])["r1"]] == [0.75]
    assert [(p.name, p.step, p.value) for p in hub.index.metric_points("r1")] == [("loss", 1, 0.5)]
    [emitted] = [e for e in hub.events.since(0) if e.type == "mirror.run_updated"]
    assert (emitted.project, emitted.run_id) == ("toy", "r1")
    assert emitted.payload == {
        "host": "gpu1",
        "environment_id": "env-remote",
        "original_type": "run.score_added",
        "remote_sequence": 2,
        "status": "finished",
    }


def test_mirror_carries_the_reason_a_run_ended(pair: tuple[Context, Context]) -> None:
    hub, remote = pair
    seed_run(remote, "r1", status=RunStatus.RUNNING)
    reason = "SLURM ended job 1000 with NODE_FAIL on n2; no exit record"
    remote.update_run(
        "r1",
        "run.lost",
        lambda r: r.model_copy(update={"status": RunStatus.LOST}),
        {"reason": reason, "slurm_state": "NODE_FAIL"},
    )
    mirror_event(hub, FakeClient(remote), "gpu1", "env-remote", run_event(remote, "r1"))  # type: ignore[arg-type]
    [emitted] = [e for e in hub.events.since(0) if e.type == "mirror.run_updated"]
    assert (emitted.payload["original_type"], emitted.payload["status"]) == ("run.lost", "lost")
    assert emitted.payload["reason"] == reason


def test_mirror_event_skips_unchanged_files(pair: tuple[Context, Context]) -> None:
    hub, remote = pair
    seed_run(remote, "r1")
    client = FakeClient(remote)
    event = run_event(remote, "r1")
    mirror_event(hub, client, "gpu1", "env-remote", event)  # type: ignore[arg-type]
    assert sorted(client.fetched) == ["predictions/predictions.jsonl", "run.yaml", "scores.jsonl"]
    client.fetched.clear()
    mirror_event(hub, client, "gpu1", "env-remote", event)  # type: ignore[arg-type]
    assert client.fetched == ["run.yaml"]
    # one remote event is re-emitted once, however often it is mirrored
    assert len([e for e in hub.events.since(0) if e.type == "mirror.run_updated"]) == 1


def test_mirror_records_too_big_files_as_remote_artifacts(
    pair: tuple[Context, Context], monkeypatch: pytest.MonkeyPatch
) -> None:
    hub, remote = pair
    record = seed_run(remote, "r1")
    big = remote.run_dir(record) / "predictions" / "big.jsonl"
    big.write_bytes(b"x" * 1_048_576)
    monkeypatch.setattr(hub_mod, "MIRROR_MAX_BYTES", 524_288)

    mirror_event(hub, FakeClient(remote), "gpu1", "env-remote", run_event(remote, "r1"))  # type: ignore[arg-type]

    local = hub.layout.run_dir("toy", "r1")
    assert not (local / "predictions" / "big.jsonl").exists()
    assert (local / "predictions" / "predictions.jsonl").is_file()
    mirrored = hub.find_record("r1")
    assert mirrored.artifacts == [
        Artifact(kind="remote_file", path="predictions/big.jsonl", host="gpu1", size=1_048_576)
    ]


def test_mirror_ignores_events_that_are_not_about_runs(pair: tuple[Context, Context]) -> None:
    hub, remote = pair
    seed_run(remote, "r1")
    event = Event(
        sequence=9, type="host.state", project="toy", run_id="r1", payload={}, created_at=utcnow()
    )
    mirror_event(hub, FakeClient(remote), "gpu1", "env-remote", event)  # type: ignore[arg-type]
    assert hub.index.get_run("r1") is None
    assert hub.events.since(0) == []


def test_mirror_never_overwrites_a_run_of_another_environment(
    pair: tuple[Context, Context],
) -> None:
    hub, remote = pair
    hub.create_run(
        make_record("r1", environment_id=hub.descriptor.environment_id, command=["mine"])
    )
    seed_run(remote, "r1")
    mirror_event(hub, FakeClient(remote), "gpu1", "env-remote", run_event(remote, "r1"))  # type: ignore[arg-type]
    kept = hub.find_record("r1")
    assert kept.environment_id == hub.descriptor.environment_id
    assert kept.command == ["mine"]
    assert [e.type for e in hub.events.since(0)] == ["run.created"]


@pytest.mark.parametrize(("project", "run_id"), [("../evil", "r1"), ("toy", "../../r1")])
def test_mirror_rejects_unsafe_names(
    pair: tuple[Context, Context], project: str, run_id: str
) -> None:
    hub, remote = pair
    event = Event(
        sequence=1,
        type="run.created",
        project=project,
        run_id=run_id,
        payload={},
        created_at=utcnow(),
    )
    mirror_event(hub, FakeClient(remote), "gpu1", "env-remote", event)  # type: ignore[arg-type]
    assert not (hub.layout.home / "evil").exists()
    assert hub.index.run_ids() == set()
    assert hub.events.since(0) == []


def test_mirror_skips_run_deleted_on_host(pair: tuple[Context, Context]) -> None:
    hub, remote = pair
    event = Event(
        sequence=1,
        type="run.created",
        project="toy",
        run_id="gone",
        payload={},
        created_at=utcnow(),
    )
    mirror_event(hub, FakeClient(remote), "gpu1", "env-remote", event)  # type: ignore[arg-type]
    assert not hub.layout.run_dir("toy", "gone").exists()
    assert hub.events.since(0) == []


def test_mirror_fetches_changed_files_whole(pair: tuple[Context, Context]) -> None:
    hub, remote = pair
    record = seed_run(remote, "r1", status=RunStatus.RUNNING)
    run_dir = remote.run_dir(record)
    for step in range(200):
        append_jsonl(run_dir / "metrics.jsonl", {"name": "loss", "step": step, "value": 1.0})
    (run_dir / "logs" / "stdout.log").write_bytes(b"line\n" * 20_000)
    client = FakeClient(remote)
    hub_mod.mirror_run(hub, client, "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    append_jsonl(run_dir / "metrics.jsonl", {"name": "loss", "step": 200, "value": 0.5})
    with (run_dir / "logs" / "stdout.log").open("ab") as fh:
        fh.write(b"new line\n")
    client.fetched.clear()
    hub_mod.mirror_run(hub, client, "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    assert sorted(client.fetched) == ["logs/stdout.log", "metrics.jsonl", "run.yaml"]
    local = hub.layout.run_dir("toy", "r1")
    for rel in ("metrics.jsonl", "logs/stdout.log"):
        assert (local / rel).read_bytes() == (run_dir / rel).read_bytes(), rel
    assert hub.index.metric_points("r1")[-1].value == 0.5


def test_mirror_keeps_only_a_tail_of_big_logs(
    pair: tuple[Context, Context], monkeypatch: pytest.MonkeyPatch
) -> None:
    hub, remote = pair
    monkeypatch.setattr(hub_mod, "LOG_TAIL_BYTES", 1000)
    monkeypatch.setattr(hub_mod, "MIRROR_MAX_BYTES", 2000)
    record = seed_run(remote, "r1", status=RunStatus.RUNNING)
    log = remote.run_dir(record) / "logs" / "stdout.log"
    log.write_bytes(bytes(range(256)) * 20)  # 5120 bytes: over both limits
    mirror_event(hub, FakeClient(remote), "gpu1", "env-remote", run_event(remote, "r1"))  # type: ignore[arg-type]
    local = hub.layout.run_dir("toy", "r1") / "logs" / "stdout.log"
    assert local.read_bytes() == log.read_bytes()[-1000:]
    assert all(a.kind != "remote_file" for a in hub.find_record("r1").artifacts)


def test_mirror_refetches_a_rewritten_jsonl_whole(pair: tuple[Context, Context]) -> None:
    hub, remote = pair
    record = seed_run(remote, "r1", status=RunStatus.RUNNING)
    preds = remote.run_dir(record) / "predictions" / "predictions.jsonl"
    preds.write_text("".join(f'{{"id": "e{i}", "prediction": "a"}}\n' for i in range(50)))
    client = FakeClient(remote)
    hub_mod.mirror_run(hub, client, "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    preds.write_text("".join(f'{{"id": "e{i}", "prediction": "b"}}\n' for i in range(60)))
    hub_mod.mirror_run(hub, client, "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    hub_mod.mirror_run(hub, client, "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    local = hub.layout.run_dir("toy", "r1") / "predictions" / "predictions.jsonl"
    assert local.read_bytes() == preds.read_bytes()


def test_mirror_names_the_host_on_its_artifacts(pair: tuple[Context, Context]) -> None:
    hub, remote = pair
    record = seed_run(remote, "r1")
    remote.update_run(
        "r1",
        "run.artifact",
        lambda r: r.model_copy(
            update={"artifacts": [Artifact(kind="checkpoint", path="/scratch/ckpt/best.pt")]}
        ),
    )
    assert remote.find_record(record.run_id).artifacts[0].host == "local"
    mirror_event(hub, FakeClient(remote), "gpu1", "env-remote", run_event(remote, "r1"))  # type: ignore[arg-type]
    [artifact] = hub.find_record("r1").artifacts
    assert (artifact.kind, artifact.host) == ("checkpoint", "gpu1")


def test_mirror_copies_a_project_only_the_host_knows(
    pair: tuple[Context, Context], toy_repo: Path
) -> None:
    hub, remote = pair
    remote.register_project(toy_repo)
    seed_run(remote, "r1")
    mirror_event(hub, FakeClient(remote), "gpu1", "env-remote", run_event(remote, "r1"))  # type: ignore[arg-type]
    entry = hub.store.load_project("toy")
    assert entry.remote_host == "gpu1" and "toy-acc" in entry.config.tasks
    assert [p.project for p in hub.index.list_projects()] == ["toy"]


def test_a_log_tail_never_grows_past_its_limit(
    pair: tuple[Context, Context], monkeypatch: pytest.MonkeyPatch
) -> None:
    hub, remote = pair
    monkeypatch.setattr(hub_mod, "LOG_TAIL_BYTES", 1000)
    record = seed_run(remote, "r1", status=RunStatus.RUNNING)
    log = remote.run_dir(record) / "logs" / "stdout.log"
    log.write_bytes(b"a" * 900)
    hub_mod.mirror_run(hub, FakeClient(remote), "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    with log.open("ab") as fh:
        fh.write(bytes(range(256)) * 2)  # 512 new bytes: 1412 on the host
    hub_mod.mirror_run(hub, FakeClient(remote), "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    local = hub.layout.run_dir("toy", "r1") / "logs" / "stdout.log"
    assert local.read_bytes() == log.read_bytes()[-1000:]


def test_a_rewritten_file_of_an_ended_run_is_fixed_in_the_same_mirror(
    pair: tuple[Context, Context],
) -> None:
    # no refresh comes for an ended run: one mirror must leave the right bytes
    hub, remote = pair
    record = seed_run(remote, "r1")
    preds = remote.run_dir(record) / "predictions" / "predictions.jsonl"
    preds.write_text("".join(f'{{"id": "e{i}", "prediction": "a"}}\n' for i in range(50)))
    client = FakeClient(remote)
    hub_mod.mirror_run(hub, client, "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    preds.write_text("".join(f'{{"id": "e{i}", "prediction": "b"}}\n' for i in range(60)))
    hub_mod.mirror_run(hub, client, "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    local = hub.layout.run_dir("toy", "r1") / "predictions" / "predictions.jsonl"
    assert local.read_bytes() == preds.read_bytes()


def test_a_failed_index_is_retried_on_the_next_mirror(
    pair: tuple[Context, Context], monkeypatch: pytest.MonkeyPatch
) -> None:
    hub, remote = pair
    seed_run(remote, "r1", value=0.75)
    real = hub_mod.index_run

    def row_then_crash(index: Index, store: Any, record: RunRecord) -> None:
        index.upsert_run(record)  # the run row lands, its scores do not
        raise RuntimeError("disk I/O error")

    monkeypatch.setattr(hub_mod, "index_run", row_then_crash)
    with pytest.raises(RuntimeError):
        hub_mod.mirror_run(hub, FakeClient(remote), "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    assert hub.index.scores_for(["r1"]).get("r1", []) == []
    monkeypatch.setattr(hub_mod, "index_run", real)
    hub_mod.mirror_run(hub, FakeClient(remote), "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    assert [s.value for s in hub.index.scores_for(["r1"])["r1"]] == [0.75]
    assert not (hub.layout.run_dir("toy", "r1") / ".mirror-index-pending").exists()


def test_an_index_failure_after_growth_never_duplicates_bytes(
    pair: tuple[Context, Context], monkeypatch: pytest.MonkeyPatch
) -> None:
    # 100 identical bytes, then 10 more: a retried install must never add them twice
    hub, remote = pair
    record = seed_run(remote, "r1", status=RunStatus.RUNNING)
    log = remote.run_dir(record) / "logs" / "stdout.log"
    log.write_bytes(b"a" * 100)
    hub_mod.mirror_run(hub, FakeClient(remote), "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    with log.open("ab") as fh:
        fh.write(b"a" * 10)
    real = hub_mod.index_run

    def crash(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("disk I/O error")

    monkeypatch.setattr(hub_mod, "index_run", crash)
    with pytest.raises(RuntimeError):
        hub_mod.mirror_run(hub, FakeClient(remote), "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    monkeypatch.setattr(hub_mod, "index_run", real)
    hub_mod.mirror_run(hub, FakeClient(remote), "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    local = hub.layout.run_dir("toy", "r1")
    assert (local / "logs" / "stdout.log").read_bytes() == b"a" * 110
    manifest = json.loads((local / hub_mod.MANIFEST_NAME).read_text())
    assert manifest["logs/stdout.log"][0] == 110
    assert not (local / hub_mod.INDEX_PENDING).exists()


class FailingClient(FakeClient):
    """The tunnel drops when the mirror asks for one file."""

    def __init__(self, remote: Context, fail_on: str) -> None:
        super().__init__(remote)
        self.fail_on = fail_on

    def fetch_file(
        self, run_id: str, rel_path: str, dest: Path, *, max_bytes: int, tail: bool = False
    ) -> bool:
        if rel_path == self.fail_on:
            raise EnvUnreachableError("cannot reach http://127.0.0.1:1: connection reset")
        return super().fetch_file(run_id, rel_path, dest, max_bytes=max_bytes, tail=tail)


def test_a_failed_fetch_installs_nothing(pair: tuple[Context, Context]) -> None:
    # the host rewrote its predictions and ended the run; the tunnel drops mid-mirror
    hub, remote = pair
    record = seed_run(remote, "r1", status=RunStatus.RUNNING)
    preds = remote.run_dir(record) / "predictions" / "predictions.jsonl"
    hub_mod.mirror_run(hub, FakeClient(remote), "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    old = preds.read_bytes()
    preds.write_text('{"id": "e1", "prediction": "rewritten"}\n')
    remote.update_run(
        "r1", "run.finished", lambda r: r.model_copy(update={"status": RunStatus.FINISHED})
    )
    dropping = FailingClient(remote, "predictions/predictions.jsonl")
    with pytest.raises(EnvUnreachableError):
        hub_mod.mirror_run(hub, dropping, "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    local = hub.layout.run_dir("toy", "r1")
    assert hub.find_record("r1").status == RunStatus.RUNNING  # no terminal run.yaml yet
    indexed = hub.index.get_run("r1")
    assert indexed is not None and indexed.status == RunStatus.RUNNING
    assert (local / "predictions" / "predictions.jsonl").read_bytes() == old
    hub_mod.mirror_run(hub, FakeClient(remote), "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    assert hub.find_record("r1").status == RunStatus.FINISHED
    assert (local / "predictions" / "predictions.jsonl").read_bytes() == preds.read_bytes()


def test_a_claimed_run_id_stays_owned_after_a_failed_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # host A writes project toy's run folder and fails to index; host B has project other
    hub = Context.open(tmp_path / "hub")
    remote_a = Context.open(tmp_path / "remote-a")
    remote_b = Context.open(tmp_path / "remote-b")
    seed_run(remote_a, "r1")
    remote_b.create_run(
        make_record("r1", project="other", environment_id=remote_b.descriptor.environment_id)
    )
    real = hub_mod.index_run

    def crash(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("disk I/O error")

    monkeypatch.setattr(hub_mod, "index_run", crash)
    with pytest.raises(RuntimeError):
        hub_mod.mirror_run(hub, FakeClient(remote_a), "a", "env-a", "toy", "r1")  # type: ignore[arg-type]
    monkeypatch.setattr(hub_mod, "index_run", real)
    assert hub.index.get_run("r1") is None  # no index entry: only the claim says who owns it
    assert hub_mod.mirror_run(hub, FakeClient(remote_b), "b", "env-b", "other", "r1") is None  # type: ignore[arg-type]
    assert not hub.layout.run_dir("other", "r1").exists()
    mirrored = hub_mod.mirror_run(hub, FakeClient(remote_a), "a", "env-a", "toy", "r1")  # type: ignore[arg-type]
    assert mirrored is not None and mirrored[0].environment_id == "env-a"
    indexed = hub.index.get_run("r1")
    assert indexed is not None and indexed.project == "toy"


def test_two_hosts_never_both_install_one_run_id(tmp_path: Path) -> None:
    hub = Context.open(tmp_path / "hub")
    remotes = [Context.open(tmp_path / f"remote-{i}") for i in (1, 2)]
    for remote in remotes:
        seed_run(remote, "r1")
    both_checked = threading.Barrier(2, timeout=5)

    class RacingClient(FakeClient):
        def list_files(self, run_id: str, rel_dir: str = "") -> list[RemoteFile]:
            both_checked.wait()  # both mirrors passed the first conflict check
            return super().list_files(run_id, rel_dir)

    results: list[Any] = [None, None]

    def mirror(i: int) -> None:
        client = RacingClient(remotes[i])
        results[i] = hub_mod.mirror_run(hub, client, f"h{i}", f"env-{i}", "toy", "r1")  # type: ignore[arg-type]

    threads = [threading.Thread(target=mirror, args=(i,)) for i in (0, 1)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    winners = [i for i in (0, 1) if results[i] is not None]
    assert len(winners) == 1
    owner = f"env-{winners[0]}"
    assert hub.find_record("r1").environment_id == owner
    indexed = hub.index.get_run("r1")
    assert indexed is not None and indexed.environment_id == owner


class StaleListing(FakeClient):
    """Lists the files as they were when it was made, then the truth (a listing gone stale)."""

    def __init__(self, remote: Context, listing: list[RemoteFile]) -> None:
        super().__init__(remote)
        self.listing = listing
        self.listed = 0

    def list_files(self, run_id: str, rel_dir: str = "") -> list[RemoteFile]:
        self.listed += 1
        return self.listing if self.listed == 1 else super().list_files(run_id, rel_dir)


def test_a_file_deleted_after_the_listing_is_deleted_here(pair: tuple[Context, Context]) -> None:
    hub, remote = pair
    record = seed_run(remote, "r1", status=RunStatus.RUNNING)
    notes = remote.run_dir(record) / "notes.md"
    notes.write_text("old notes\n")
    hub_mod.mirror_run(hub, FakeClient(remote), "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    local = hub.layout.run_dir("toy", "r1")
    assert (local / "notes.md").read_text() == "old notes\n"
    notes.write_text("new notes, deleted before the hub fetches them\n")
    listing = FakeClient(remote).list_files("r1")
    notes.unlink()  # 404 for the listed file, and absent from the second listing
    client = StaleListing(remote, listing)
    assert hub_mod.mirror_run(hub, client, "gpu1", "env-remote", "toy", "r1") is not None  # type: ignore[arg-type]
    assert client.listed == 2  # listed again, once
    assert not (local / "notes.md").exists()  # no stale copy next to newer files
    assert "notes.md" not in json.loads((local / hub_mod.MANIFEST_NAME).read_text())


def test_a_file_deleted_on_the_host_between_mirrors_is_deleted_here(
    pair: tuple[Context, Context],
) -> None:
    hub, remote = pair
    record = seed_run(remote, "r1", status=RunStatus.RUNNING)
    run_dir = remote.run_dir(record)
    old = run_dir / "predictions" / "old.jsonl"
    old.write_text('{"id": "e0", "prediction": "old"}\n')
    log_file = run_dir / "logs" / "stdout.log"
    log_file.parent.mkdir(exist_ok=True)
    log_file.write_text("step 1\n")
    hub_mod.mirror_run(hub, FakeClient(remote), "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    local = hub.layout.run_dir("toy", "r1")
    assert (local / "predictions" / "old.jsonl").is_file() and (
        local / "logs" / "stdout.log"
    ).is_file()
    old.unlink()  # the user deletes them on the host: never listed again
    log_file.unlink()
    client = FakeClient(remote)
    result = hub_mod.mirror_run(hub, client, "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    assert result is not None and result[1]  # a change
    assert client.fetched == ["run.yaml"]  # nothing to fetch: only deletes
    assert not (local / "predictions" / "old.jsonl").exists()
    assert not (local / "logs" / "stdout.log").exists()
    manifest = json.loads((local / hub_mod.MANIFEST_NAME).read_text())
    assert "predictions/old.jsonl" not in manifest and "logs/stdout.log" not in manifest
    assert (local / "predictions" / "predictions.jsonl").is_file()  # still listed: kept
    assert "predictions/predictions.jsonl" in manifest
    again = hub_mod.mirror_run(hub, FakeClient(remote), "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    assert again is not None and not again[1]  # settled: the next mirror changes nothing


def test_an_unsafe_manifest_entry_is_never_deleted(pair: tuple[Context, Context]) -> None:
    hub, remote = pair
    seed_run(remote, "r1")
    hub_mod.mirror_run(hub, FakeClient(remote), "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    local = hub.layout.run_dir("toy", "r1")
    outside = local.parent / "keep.txt"
    outside.write_text("not the mirror's file\n")
    (local / ".hx").mkdir(exist_ok=True)
    (local / ".hx" / "state").write_text("hub state\n")
    manifest = json.loads((local / hub_mod.MANIFEST_NAME).read_text())
    manifest |= {"../keep.txt": [1, 1], ".hx/state": [1, 1], "run.yaml": [1, 1]}
    (local / hub_mod.MANIFEST_NAME).write_text(json.dumps(manifest))
    hub_mod.mirror_run(hub, FakeClient(remote), "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    assert (
        outside.is_file() and (local / ".hx" / "state").is_file() and (local / "run.yaml").is_file()
    )
    cleaned = json.loads((local / hub_mod.MANIFEST_NAME).read_text())
    assert not {"../keep.txt", ".hx/state", "run.yaml"} & set(cleaned)


def test_a_file_that_grew_too_big_is_recorded_as_skipped(
    pair: tuple[Context, Context], monkeypatch: pytest.MonkeyPatch
) -> None:
    hub, remote = pair
    monkeypatch.setattr(hub_mod, "MIRROR_MAX_BYTES", 2000)
    record = seed_run(remote, "r1", status=RunStatus.RUNNING)
    preds = remote.run_dir(record) / "predictions" / "predictions.jsonl"
    hub_mod.mirror_run(hub, FakeClient(remote), "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    run = hub.layout.run_dir("toy", "r1")
    local = run / "predictions" / "predictions.jsonl"
    skips = run / hub_mod.SKIPS_FILE
    assert local.is_file() and not skips.exists()
    preds.write_text("x" * 500 + "\n")  # small when listed ...
    listing = FakeClient(remote).list_files("r1")
    preds.write_bytes(b"y" * 5000)  # ... too big when fetched: 413
    client = StaleListing(remote, listing)
    hub_mod.mirror_run(hub, client, "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    assert not local.exists()
    assert not local.with_name("predictions.jsonl.skipped").exists()  # nothing next to it
    assert json.loads(skips.read_text()) == {
        "predictions/predictions.jsonl": {"reason": "too big", "size": 5000, "max_bytes": 2000}
    }
    assert hub.find_record("r1").artifacts == [
        Artifact(kind="remote_file", path="predictions/predictions.jsonl", host="gpu1", size=5000)
    ]
    hub_mod.mirror_run(hub, FakeClient(remote), "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    assert not local.exists()  # a fresh listing agrees
    assert list(json.loads(skips.read_text())) == ["predictions/predictions.jsonl"]
    preds.write_text('{"id": "e1", "prediction": "small again"}\n')
    hub_mod.mirror_run(hub, FakeClient(remote), "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    assert local.read_bytes() == preds.read_bytes() and not skips.exists()


def test_a_host_file_named_like_a_marker_is_an_ordinary_file(
    pair: tuple[Context, Context], monkeypatch: pytest.MonkeyPatch
) -> None:
    # the host has predictions/x (it grows too big) and its own predictions/x.skipped
    hub, remote = pair
    monkeypatch.setattr(hub_mod, "MIRROR_MAX_BYTES", 2000)
    record = seed_run(remote, "r1", status=RunStatus.RUNNING)
    preds = remote.run_dir(record) / "predictions"
    (preds / "x").write_text("small\n")
    (preds / "x.skipped").write_text('{"note": "the user\'s own file"}\n')
    hub_mod.mirror_run(hub, FakeClient(remote), "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    run = hub.layout.run_dir("toy", "r1")
    assert (run / "predictions" / "x").read_text() == "small\n"
    (preds / "x").write_bytes(b"y" * 5000)  # too big now: the stale copy here must go
    for _ in range(2):  # two repeated mirrors
        hub_mod.mirror_run(hub, FakeClient(remote), "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
        assert not (run / "predictions" / "x").exists()
        mirrored = (run / "predictions" / "x.skipped").read_bytes()
        assert mirrored == (preds / "x.skipped").read_bytes()  # intact, never a marker
        skips = json.loads((run / hub_mod.SKIPS_FILE).read_text())
        assert skips == {"predictions/x": {"reason": "too big", "size": 5000, "max_bytes": 2000}}
        manifest = json.loads((run / hub_mod.MANIFEST_NAME).read_text())
        assert "predictions/x" not in manifest and "predictions/x.skipped" in manifest


def test_the_mirror_never_fetches_the_reserved_folder(
    pair: tuple[Context, Context], monkeypatch: pytest.MonkeyPatch
) -> None:
    # refused even if the allow-list took it: the hub never takes its own state from a host
    hub, remote = pair
    monkeypatch.setattr(hub_mod, "MIRROR_DIRS", (*hub_mod.MIRROR_DIRS, ".hx"))
    record = seed_run(remote, "r1")
    planted = remote.run_dir(record) / ".hx" / "mirror-skips.json"
    planted.parent.mkdir()
    planted.write_text('{"scores.jsonl": {"reason": "planted"}}')
    client = FakeClient(remote)
    hub_mod.mirror_run(hub, client, "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    run = hub.layout.run_dir("toy", "r1")
    assert ".hx/mirror-skips.json" in [f.path for f in client.list_files("r1")]
    assert not any(p.startswith(".hx") for p in client.fetched)
    assert not (run / ".hx").exists() and (run / "scores.jsonl").is_file()
    assert ".hx/mirror-skips.json" not in json.loads((run / hub_mod.MANIFEST_NAME).read_text())


def test_a_listed_file_never_served_leaves_no_stale_copy(pair: tuple[Context, Context]) -> None:
    hub, remote = pair
    record = seed_run(remote, "r1", status=RunStatus.RUNNING)
    notes = remote.run_dir(record) / "notes.md"
    notes.write_text("v1\n")
    hub_mod.mirror_run(hub, FakeClient(remote), "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    notes.write_text("v2, which the host refuses to serve\n")

    class Refusing(FakeClient):
        def fetch_file(
            self, run_id: str, rel_path: str, dest: Path, *, max_bytes: int, tail: bool = False
        ) -> bool:
            if rel_path == "notes.md":
                return False
            return super().fetch_file(run_id, rel_path, dest, max_bytes=max_bytes, tail=tail)

    hub_mod.mirror_run(hub, Refusing(remote), "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    run = hub.layout.run_dir("toy", "r1")
    assert not (run / "notes.md").exists()
    note = json.loads((run / hub_mod.SKIPS_FILE).read_text())["notes.md"]
    assert note["reason"] == "not served" and note["size"] == notes.stat().st_size


class Crash(BaseException):
    """The hub dies right here (a BaseException: nothing on the way catches it)."""


def crash_at(step: str, hub: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the next mirror die at one step of its install."""
    if step == "marker":  # the marker is durable, nothing else changed yet
        real_touch = hub_mod._durable_touch

        def touch_then_crash(path: Path) -> None:
            real_touch(path)
            raise Crash

        monkeypatch.setattr(hub_mod, "_durable_touch", touch_then_crash)
    elif step == "file":  # the first live file is replaced
        real_replace = os.replace

        def replace_then_crash(src: Any, dst: Any) -> None:
            real_replace(src, dst)
            if Path(dst).name == "scores.jsonl":
                raise Crash

        monkeypatch.setattr(os, "replace", replace_then_crash)
    elif step == "record":  # run.yaml is written
        real_write = hub.store.write_record

        def write_then_crash(record: RunRecord) -> None:
            real_write(record)
            raise Crash

        monkeypatch.setattr(hub.store, "write_record", write_then_crash)
    elif step == "index":  # index_run got half-way

        def half_index(index: Index, store: Any, record: RunRecord) -> None:
            index.upsert_run(record)
            raise Crash

        monkeypatch.setattr(hub_mod, "index_run", half_index)
    else:  # "manifest": .mirror.json is written, the marker is still there
        real_atomic = hub_mod.atomic_write_text

        def write_then_crash_on_manifest(path: Path, text: str) -> None:
            real_atomic(path, text)
            if path.name == hub_mod.MANIFEST_NAME:
                raise Crash

        monkeypatch.setattr(hub_mod, "atomic_write_text", write_then_crash_on_manifest)


def scores_of(records: list[ScoreRecord]) -> list[float]:
    return sorted(s.value for s in records if s.value is not None)


def indexed_scores(hub: Context) -> list[float]:
    return scores_of(hub.index.scores_for(["r1"]).get("r1", []))


@pytest.mark.parametrize("repair", ["replay", "startup"])
@pytest.mark.parametrize("step", ["marker", "file", "record", "index", "manifest"])
def test_a_crash_at_any_install_step_is_reindexed(
    pair: tuple[Context, Context], monkeypatch: pytest.MonkeyPatch, step: str, repair: str
) -> None:
    hub, remote = pair
    record = seed_run(remote, "r1", value=0.5)
    hub_mod.mirror_run(hub, FakeClient(remote), "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    remote.add_score(
        record, ScoreRecord(metric="f1", version="1", key="value", value=0.9, created_at=utcnow())
    )
    remote.update_run("r1", "run.tagged", lambda r: r.model_copy(update={"tags": ["x"]}))
    crash_at(step, hub, monkeypatch)
    with pytest.raises(Crash):
        hub_mod.mirror_run(hub, FakeClient(remote), "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    monkeypatch.undo()
    local = hub.layout.run_dir("toy", "r1")
    assert (local / hub_mod.INDEX_PENDING).exists()  # written before the first change
    if repair == "startup":  # the hub restarts; no event ever comes for this run again
        assert hub_mod.reindex_pending(hub) == ["r1"]
        on_disk = scores_of(hub.store.read_scores("toy", "r1"))
        assert indexed_scores(hub) == on_disk  # the index matches whatever was installed
    hub_mod.mirror_run(hub, FakeClient(remote), "gpu1", "env-remote", "toy", "r1")  # type: ignore[arg-type]
    assert indexed_scores(hub) == [0.5, 0.9]
    indexed = hub.index.get_run("r1")
    assert indexed is not None and indexed.tags == ["x"]
    assert not (local / hub_mod.INDEX_PENDING).exists()
