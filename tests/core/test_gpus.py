import json
import os
from pathlib import Path

import pytest

from hypothex.core.context import Context
from hypothex.core.environment import count_gpus
from hypothex.core.errors import ConfigError
from hypothex.core.gpus import (
    APPS_QUERY,
    FAKE_GPUS_ENV,
    GPU_QUERY,
    GpuInfo,
    free_gpus,
    gpu_status,
    parse_nvidia_smi,
    query_gpus,
)
from hypothex.core.records import ExecutorInfo, RunStatus
from tests.factories import make_record

GPU_CSV = (
    "0, GPU-aaa, NVIDIA A100-SXM4-80GB, 37, 1024, 81920\n"
    "1, GPU-bbb, NVIDIA A100-SXM4-80GB, [N/A], 0, 81920\n"
)
APPS_CSV = "GPU-aaa, 4242\nGPU-aaa, 4343\n"
A100 = "NVIDIA A100-SXM4-80GB"


def _fake_smi(bin_dir: Path, *, gpu_exit: int = 0, apps_exit: int = 0) -> Path:
    """Write a fake nvidia-smi that logs its args and prints canned CSV."""
    bin_dir.mkdir()
    (bin_dir / "gpus.csv").write_text(GPU_CSV)
    (bin_dir / "apps.csv").write_text(APPS_CSV)
    script = bin_dir / "nvidia-smi"
    script.write_text(
        "#!/bin/sh\n"
        'here="$(dirname "$0")"\n'
        'echo "$@" >> "$here/calls.log"\n'
        'case "$1" in\n'
        f'  --query-gpu=*) cat "$here/gpus.csv"; exit {gpu_exit} ;;\n'
        f'  --query-compute-apps=*) cat "$here/apps.csv"; exit {apps_exit} ;;\n'
        "esac\n"
        "exit 2\n"
    )
    script.chmod(0o755)
    return bin_dir


def _use_fake_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entries: object) -> Path:
    path = tmp_path / "fake-gpus.json"
    path.write_text(json.dumps(entries))
    monkeypatch.setenv(FAKE_GPUS_ENV, str(path))
    return path


def test_parse_nvidia_smi_reads_gpus_and_compute_apps() -> None:
    assert parse_nvidia_smi(GPU_CSV, APPS_CSV) == [
        GpuInfo(index=0, name=A100, util=37.0, mem_used_mb=1024, mem_total_mb=81920, external=True),
        GpuInfo(index=1, name=A100, util=0.0, mem_used_mb=0, mem_total_mb=81920, external=False),
    ]


def test_parse_nvidia_smi_skips_junk_lines() -> None:
    text = "No devices were found\n\n" + GPU_CSV.splitlines()[1] + "\n"
    gpus = parse_nvidia_smi(text, "No running processes found\n")
    assert [(g.index, g.external) for g in gpus] == [(1, False)]


def test_parse_without_apps_marks_every_gpu_external() -> None:
    assert [g.external for g in parse_nvidia_smi(GPU_CSV, None)] == [True, True]


def test_query_gpus_runs_nvidia_smi(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = _fake_smi(tmp_path / "bin")
    monkeypatch.delenv(FAKE_GPUS_ENV, raising=False)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    gpus = query_gpus()
    assert [(g.index, g.util, g.mem_used_mb, g.external) for g in gpus] == [
        (0, 37.0, 1024, True),
        (1, 0.0, 0, False),
    ]
    calls = (bin_dir / "calls.log").read_text().splitlines()
    assert calls == [" ".join(GPU_QUERY[1:]), " ".join(APPS_QUERY[1:])]


def test_query_gpus_without_nvidia_smi_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.delenv(FAKE_GPUS_ENV, raising=False)
    monkeypatch.setenv("PATH", str(empty))
    assert query_gpus() == []


def test_query_gpus_when_nvidia_smi_fails_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = _fake_smi(tmp_path / "bin", gpu_exit=9)
    monkeypatch.delenv(FAKE_GPUS_ENV, raising=False)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    assert query_gpus() == []
    assert (bin_dir / "calls.log").read_text().splitlines() == [" ".join(GPU_QUERY[1:])]


def test_query_gpus_when_apps_query_fails_marks_gpus_external(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = _fake_smi(tmp_path / "bin", apps_exit=6)
    monkeypatch.delenv(FAKE_GPUS_ENV, raising=False)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    assert [(g.index, g.external) for g in query_gpus()] == [(0, True), (1, True)]


def test_fake_gpus_file_fills_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    entries = [{"index": 1, "external": True}, {"index": 0, "name": "H100", "util": 50}]
    _use_fake_file(tmp_path, monkeypatch, entries)
    assert query_gpus() == [
        GpuInfo(index=0, name="H100", util=50.0, mem_used_mb=0, mem_total_mb=81920, external=False),
        GpuInfo(
            index=1, name="Fake GPU", util=0.0, mem_used_mb=0, mem_total_mb=81920, external=True
        ),
    ]


def test_fake_gpus_missing_file_is_empty_and_bad_file_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "fake-gpus.json"
    monkeypatch.setenv(FAKE_GPUS_ENV, str(path))
    assert query_gpus() == []
    path.write_text('{"index": 0}')
    with pytest.raises(ConfigError, match="not a JSON list of GPUs"):
        query_gpus()
    path.write_text('[{"index": "zero"}]')
    with pytest.raises(ConfigError, match="not a JSON list of GPUs"):
        query_gpus()


def test_gpu_status_marks_gpus_held_by_active_runs(
    ctx: Context, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    busy = {"external": True}
    entries = [{"index": 0}, {"index": 1, **busy}, {"index": 2, **busy}, {"index": 3}]
    _use_fake_file(tmp_path, monkeypatch, entries)
    me = ctx.descriptor.environment_id
    ctx.create_run(
        make_record(
            "train",
            status=RunStatus.RUNNING,
            environment_id=me,
            executor=ExecutorInfo(pid=os.getpid(), gpus=[1]),
        )
    )
    ctx.create_run(
        make_record(
            "starting", status=RunStatus.QUEUED, environment_id=me, executor=ExecutorInfo(gpus=[3])
        )
    )
    status = gpu_status(ctx)
    assert [(g.index, g.run_id, g.external) for g in status] == [
        (0, None, False),
        (1, "train", False),  # its own process is on the GPU: held, not external
        (2, None, True),  # someone else's process
        (3, "starting", False),  # assigned, supervisor still starting
    ]
    assert free_gpus(status) == [0]


def test_gpu_status_ignores_finished_and_foreign_runs(
    ctx: Context, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_fake_file(tmp_path, monkeypatch, [{"index": 0}, {"index": 1}])
    me = ctx.descriptor.environment_id
    ctx.create_run(
        make_record(
            "done", status=RunStatus.FINISHED, environment_id=me, executor=ExecutorInfo(gpus=[0])
        )
    )
    ctx.create_run(
        make_record(
            "elsewhere",
            status=RunStatus.RUNNING,
            environment_id="other-env",
            executor=ExecutorInfo(gpus=[1]),
        )
    )
    assert free_gpus(gpu_status(ctx)) == [0, 1]


def test_count_gpus_reads_the_same_source_as_query_gpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert count_gpus() == 0  # the refusing nvidia-smi stub of Task 1 Step 0
    _use_fake_file(tmp_path, monkeypatch, [{"index": 0}, {"index": 1}, {"index": 2}])
    assert count_gpus() == 3
    (tmp_path / "fake-gpus.json").write_text("not json")
    assert count_gpus() == 0
    bin_dir = _fake_smi(tmp_path / "bin")
    monkeypatch.delenv(FAKE_GPUS_ENV)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    assert count_gpus() == 2
    assert (bin_dir / "calls.log").read_text().splitlines()[0] == " ".join(GPU_QUERY[1:])
