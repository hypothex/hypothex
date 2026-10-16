import sys
from pathlib import Path

import pytest
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


@pytest.mark.parametrize("old_version", ["3", "4"])
def test_old_index_marker_requests_rebuild(tmp_path: Path, old_version: str) -> None:
    from sqlalchemy.orm import Session

    index = Index(tmp_path / "index.db")
    with Session(index.engine) as session, session.begin():
        session.merge(MetaRow(key="schema_version", value=old_version))
    assert SCHEMA_VERSION == 5
    assert Index(tmp_path / "index.db").rebuilt_schema is True


def test_reinfer_child_is_owned_by_the_caller(ctx: Context, toy_repo: Path) -> None:
    parent = prepare_run(ctx, RunRequest(repo=toy_repo, command=[PY, "-c", "pass"], owner="sv"))
    checkpoint = toy_repo / "synthetic-checkpoint"
    checkpoint.write_text("synthetic")
    child = control.reinfer(
        ctx,
        parent.run_id,
        checkpoint=str(checkpoint),
        background=False,
        created_by="human:alice",
        owner="alice",
    )
    assert child.owner == "alice" and child.created_by == "human:alice"
    assert child.parent == parent.run_id
    assert ctx.find_record(parent.run_id).owner == "sv"


def test_sweep_extension_and_retry_keep_original_owner(ctx: Context, toy_repo: Path) -> None:
    from hypothex.core.sweeps import extend_sweep

    ctx.register_project(toy_repo)
    requests: list[RunRequest] = []

    def fake_launch(req: RunRequest, command_id: str) -> RunRecord:
        requests.append(req)
        record = make_record(
            f"owned-{len(requests)}",
            owner=req.owner,
            created_by=req.created_by,
            seed=req.seed,
            params=req.params,
            tags=req.tags,
            environment_id=ctx.descriptor.environment_id,
        )
        ctx.create_run(record)
        return record

    kwargs = dict(
        project="toy",
        grid=[SweepParam(name="x", values=["1", "2"])],
        seeds=[1],
        command=["echo", "{x}"],
        launch=fake_launch,
        command_id="owned-sweep",
    )
    summary = launch_sweep(ctx, **kwargs, created_by="human:alice", owner="alice")
    replay = launch_sweep(ctx, **kwargs, created_by="human:sv", owner="sv")
    assert replay.spec.id == summary.spec.id and replay.spec.owner == "alice"
    assert len(requests) == 2
    extended = extend_sweep(ctx, "toy", summary.spec.id, [2], launch=fake_launch)
    assert len(requests) == 4 and extended.spec.owner == "alice"
    assert {req.owner for req in requests} == {"alice"}
    assert {req.created_by for req in requests} == {"human:alice"}


def test_owner_filter_combines_with_literal_search_count_and_keyset(ctx: Context) -> None:
    from datetime import UTC, datetime

    stamp = datetime(2026, 10, 17, tzinfo=UTC)
    for rid, owner, name, archived in [
        ("a", "alice", "wide %_ beam", False),
        ("b", "alice", "wide %_ beam", False),
        ("c", "sv", "wide %_ beam", False),
        ("d", "alice", "wide X beam", False),
        ("e", "alice", "wide %_ beam", True),
    ]:
        ctx.create_run(
            make_record(rid, owner=owner, name=name, archived=archived, created_at=stamp)
        )
    page = ctx.index.list_runs(owner="alice", search="%_", limit=1)
    assert [r.run_id for r in page] == ["b"]
    rest = ctx.index.list_runs(owner="alice", search="%_", before=(stamp, "b"))
    assert [r.run_id for r in rest] == ["a"]
    assert ctx.index.count_runs(owner="alice", search="%_") == 2
    assert ctx.index.count_runs(owner="alice", search="%_", include_archived=True) == 3


@pytest.mark.parametrize("old_version", [None, "3", "4"])
def test_rebuild_retains_owner_parent_name_scores_and_deferred_points(
    ctx: Context,
    toy_repo: Path,
    old_version: str | None,
) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from hypothex.core.fsutil import append_jsonl
    from hypothex.core.index import RunRow, rebuild_index
    from hypothex.core.records import ScoreRecord

    ctx.register_project(toy_repo)
    parent = make_record("a", environment_id=ctx.descriptor.environment_id)
    child = make_record(
        "child",
        owner="alice",
        parent="a",
        name="wide %_ beam",
        environment_id=ctx.descriptor.environment_id,
    )
    ctx.create_run(parent)
    ctx.create_run(child)
    score = ScoreRecord(
        metric="accuracy",
        version="v1",
        key="value",
        value=0.75,
        created_at=child.created_at,
        per_example_hash="sha256:bound",
        evaluation_examples=4,
        evaluation_ids_hash="sha256:ids",
    )
    ctx.add_score(child, score)
    run_dir = ctx.run_dir(child)
    append_jsonl(run_dir / "metrics.jsonl", {"name": "loss", "step": 1, "value": 0.3})
    scores_before = (run_dir / "scores.jsonl").read_bytes()
    if old_version is None:
        rebuild_index(ctx.index, ctx.store)
    else:
        # This checks the reopen path, not the independent Task49 legacy fixtures.
        ctx.index.set_meta("schema_version", old_version)
        ctx.index.engine.dispose()
        ctx = Context.open(ctx.layout.home)
    assert ctx.index.schema_version() == "5"
    record = ctx.index.get_run("child")
    assert record is not None and (record.owner, record.parent, record.name) == (
        "alice",
        "a",
        "wide %_ beam",
    )
    with Session(ctx.index.engine) as session:
        row = session.execute(
            select(RunRow.owner, RunRow.parent, RunRow.name).where(RunRow.run_id == "child")
        ).one()
    assert tuple(row) == ("alice", "a", "wide %_ beam")
    assert ctx.index.child_run_ids("a") == ["child"]
    assert ctx.index.count_runs(owner="alice", search="%_") == 1
    assert ctx.index.scores_for(["child"])["child"] == [score]
    assert (run_dir / "scores.jsonl").read_bytes() == scores_before
    assert ctx.index.metric_names_for(["child"]) == ["loss"]
    assert ctx.index.metric_points("child")[0].value == 0.3
