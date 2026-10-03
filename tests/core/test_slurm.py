import errno
import getpass
import json
import os
import shlex
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from hypothex.cli.main import app
from hypothex.core import control
from hypothex.core import slurm as slurm_module
from hypothex.core.context import Context
from hypothex.core.errors import ConfigError, RunError
from hypothex.core.execution import RunRequest, prepare_run
from hypothex.core.ids import utcnow
from hypothex.core.records import ExecutorInfo, RunRecord, RunStatus
from hypothex.core.slurm import (
    EXIT_FILE,
    SBATCH_FILE,
    SlurmError,
    SlurmJob,
    SlurmTimeout,
    SubmitUnknownError,
    cancel,
    comment_accounting,
    find_submitted,
    flock_supported,
    is_finished,
    lost_reason,
    poll,
    reconcile,
    render_sbatch,
    require_flock,
    run_child,
    run_slurm_settings,
    submit,
    submit_run,
    track_slurm_run,
)
from hypothex.remote.config import SlurmDefaults
from tests.factories import make_record

FAKE_SLURM = Path(__file__).resolve().parents[1] / "fakes" / "fake_slurm"
PY = sys.executable
runner = CliRunner()


class FakeSlurm:
    """Read and edit the fake SLURM state file (see tests/fakes/fake_slurm/_fakeslurm.py)."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def state(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {
                "next_id": 1000,
                "mode": "hold",
                "user": None,
                "fail": {},
                "accounting_flags": "job_comment",
                "sbatch_signal": None,
                "jobs": {},
                "calls": [],
            }
        return json.loads(self.path.read_text())

    def save(self, state: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(state))

    def set(self, **fields: Any) -> None:
        state = self.state()
        state.update(fields)
        self.save(state)

    def add_job(
        self,
        job_id: str,
        state: str = "PENDING",
        *,
        node: str | None = None,
        exit: str = "0:0",
        in_queue: bool = True,
        in_sacct: bool = True,
        name: str | None = None,
        comment: str = "",
    ) -> None:
        current = self.state()
        current["jobs"][job_id] = {
            "state": state,
            "node": node,
            "exit": exit,
            "in_queue": in_queue,
            "in_sacct": in_sacct,
            "name": name or f"job-{job_id}",
            "comment": comment,
            "output": "/dev/null",
            "gpus": 0,
            "directives": {},
            "script": "",
            "cwd": "/",
            "pgid": None,
        }
        self.save(current)

    def job(self, job_id: str) -> dict[str, Any]:
        return self.state()["jobs"][job_id]

    def calls(self, name: str) -> list[list[str]]:
        return [call[1:] for call in self.state()["calls"] if call[0] == name]


@pytest.fixture
def slurm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeSlurm:
    monkeypatch.setenv("PATH", f"{FAKE_SLURM}{os.pathsep}{os.environ['PATH']}")
    path = tmp_path / "slurm-state.json"
    monkeypatch.setenv("HYPOTHEX_FAKE_SLURM_STATE", str(path))
    fake = FakeSlurm(path)
    fake.save(fake.state())
    return fake


def wait_until(predicate: Callable[[], bool], timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError(f"condition not met within {timeout}s")


def sh(*argv: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(argv), input=stdin, capture_output=True, text=True, check=False)


def slurm_run(
    ctx: Context,
    run_id: str,
    *,
    job_id: str = "1000",
    status: RunStatus = RunStatus.RUNNING,
    environment_id: str | None = None,
    **executor: Any,
) -> RunRecord:
    """A submitted SLURM run, tracked in the outbox as submit_run leaves it."""
    record = ctx.create_run(
        make_record(
            run_id,
            status=status,
            environment_id=environment_id or ctx.descriptor.environment_id,
            executor=ExecutorInfo(type="slurm", slurm_job_id=job_id, **executor),
        )
    )
    track_slurm_run(ctx.layout, record, comment=f"hx-{run_id}-0000")
    return record


class Crash(BaseException):
    """The env server dies right here (a BaseException: nothing on the way catches it)."""


def dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


# fake SLURM commands -----------------------------------------------------------------
def test_fake_slurm_submit_queue_cancel_account(slurm: FakeSlurm) -> None:
    script = "#!/bin/bash\n#SBATCH --job-name=hx-x\n#SBATCH --gpus=2\necho hi\n"
    assert sh("sbatch", "--parsable", stdin=script).stdout == "1000\n"
    assert sh("squeue", "--noheader", "--user=me", "--format=%i|%T|%N").stdout == (
        "1000|PENDING|\n"
    )
    assert sh("scancel", "1000").returncode == 0
    assert sh("squeue", "--noheader", "--format=%i|%T|%N").stdout == ""
    acct = sh(
        "sacct",
        "-X",
        "--noheader",
        "--parsable2",
        "--format=JobID,State,ExitCode,NodeList",
        "--jobs=1000",
    )
    assert acct.stdout == "1000|CANCELLED|0:15|None assigned\n"
    again = sh("scancel", "1000")
    assert again.returncode == 1
    assert "Invalid job id specified" in again.stderr
    assert slurm.job("1000")["directives"] == {"job-name": "hx-x", "gpus": "2"}
    assert [c[0] for c in slurm.state()["calls"]] == [
        "sbatch",
        "squeue",
        "scancel",
        "squeue",
        "sacct",
        "scancel",
    ]


def test_fake_slurm_injected_failure(slurm: FakeSlurm) -> None:
    slurm.set(fail={"squeue": "slurm_load_jobs error: Unable to contact slurm controller"})
    out = sh("squeue", "--noheader", "--format=%i|%T|%N")
    assert out.returncode == 1
    assert out.stderr == "slurm_load_jobs error: Unable to contact slurm controller\n"


def test_fake_slurm_run_mode_executes_script_on_fake_node(slurm: FakeSlurm, tmp_path: Path) -> None:
    slurm.set(mode="run")
    ok = (
        f"#!/bin/bash\n#SBATCH --output={tmp_path}/out-%j.txt\n#SBATCH --gpus=2\n"
        'echo "job $SLURM_JOB_ID on $SLURMD_NODENAME gpus $CUDA_VISIBLE_DEVICES"\n'
    )
    bad = f"#!/bin/bash\n#SBATCH --output={tmp_path}/out-%j.txt\nexit 3\n"
    assert sh("sbatch", "--parsable", stdin=ok).stdout == "1000\n"
    assert sh("sbatch", "--parsable", stdin=bad).stdout == "1001\n"
    wait_until(lambda: not slurm.job("1000")["in_queue"] and not slurm.job("1001")["in_queue"])
    assert (tmp_path / "out-1000.txt").read_text() == "job 1000 on fake-node1 gpus 0,1\n"
    assert (slurm.job("1000")["state"], slurm.job("1000")["exit"]) == ("COMPLETED", "0:0")
    assert (slurm.job("1001")["state"], slurm.job("1001")["exit"]) == ("FAILED", "3:0")


def test_fake_slurm_finds_jobs_by_name_and_comment(slurm: FakeSlurm) -> None:
    script = "#!/bin/bash\n#SBATCH --job-name=hx-r1\ntrue\n"
    assert sh("sbatch", "--parsable", "--comment=hx-r1-ab12", stdin=script).stdout == "1000\n"
    assert sh("sbatch", "--parsable", stdin="#!/bin/bash\ntrue\n").stdout == "1001\n"
    assert slurm.job("1000")["comment"] == "hx-r1-ab12"
    found = sh("squeue", "--noheader", "--name=hx-r1", "--format=%i|%T|%N|%k")
    assert found.stdout == "1000|PENDING||hx-r1-ab12\n"
    sh("scancel", "1000")
    acct = sh(
        "sacct",
        "-X",
        "--noheader",
        "--parsable2",
        "--format=JobID,State,ExitCode,NodeList,Comment",
        "--starttime=now-7days",
    )
    assert acct.stdout == (
        "1000|CANCELLED|0:15|None assigned|hx-r1-ab12\n1001|PENDING|0:0|None assigned|\n"
    )


def test_fake_scontrol_reports_the_accounting_flags(slurm: FakeSlurm) -> None:
    config = sh("scontrol", "show", "config")
    assert config.returncode == 0
    assert "AccountingStoreFlags    = job_comment\n" in config.stdout
    slurm.set(accounting_flags="")
    assert "AccountingStoreFlags    = (null)\n" in sh("scontrol", "show", "config").stdout
    assert sh("scontrol", "show", "jobs").returncode == 2


def test_fake_sbatch_can_die_by_a_signal_after_accepting(slurm: FakeSlurm) -> None:
    slurm.set(sbatch_signal="KILL")
    out = sh("sbatch", "--parsable", "--comment=hx-r1-sig", stdin="#!/bin/bash\ntrue\n")
    assert (out.returncode, out.stdout) == (-9, "")
    assert slurm.job("1000")["comment"] == "hx-r1-sig"  # SLURM had taken it


def test_fake_sbatch_reads_options_from_the_command_line(slurm: FakeSlurm, tmp_path: Path) -> None:
    out = sh(
        "sbatch",
        "--parsable",
        "--comment",
        "hx-r1-ab12",
        "--job-name=hx-r1",
        f"--output={tmp_path}/slurm-%j.out",
        "--time=00:10:00",
        "--gpus=2",
        "--partition=gpu",
        "--account=lab",
        "--qos=high",
        stdin="#!/bin/bash\n#SBATCH --job-name=ignored\ntrue\n",
    )
    assert out.stdout == "1000\n"
    job = slurm.job("1000")
    assert (job["name"], job["comment"], job["gpus"]) == ("hx-r1", "hx-r1-ab12", 2)
    assert job["output"] == f"{tmp_path}/slurm-%j.out"
    assert job["directives"]["qos"] == "high"
    assert job["directives"]["partition"] == "gpu"
    assert slurm.job("1000")["script"].endswith("true\n")


def test_fake_sbatch_takes_a_script_file_and_refuses_unknown_arguments(
    slurm: FakeSlurm, tmp_path: Path
) -> None:
    script = tmp_path / "job.sh"
    script.write_text("#!/bin/bash\n#SBATCH --job-name=from-file\ntrue\n")
    assert sh("sbatch", "--parsable", str(script)).stdout == "1000\n"
    assert slurm.job("1000")["name"] == "from-file"
    for bad in (["--wrap", "true"], ["-Z"], [str(script), str(script)], ["--comment"]):
        result = sh("sbatch", *bad)
        assert result.returncode == 2, bad
        assert "unsupported arguments" in result.stderr
    assert list(slurm.state()["jobs"]) == ["1000"]


def test_fake_scancel_by_state_cancels_every_pending_job(slurm: FakeSlurm) -> None:
    slurm.add_job("1", "PENDING")
    slurm.add_job("2", "PENDING", name="other")
    slurm.add_job("3", "RUNNING", node="fake-node1")
    assert sh("scancel", "--state=PENDING", "--name=job-1").returncode == 0
    assert (slurm.job("1")["state"], slurm.job("2")["state"]) == ("CANCELLED", "PENDING")
    assert sh("scancel", "--state", "PENDING").returncode == 0
    assert (slurm.job("2")["state"], slurm.job("2")["exit"]) == ("CANCELLED", "0:15")
    assert (slurm.job("3")["state"], slurm.job("3")["in_queue"]) == ("RUNNING", True)
    assert sh("scancel", "--state=PENDING").returncode == 0  # nothing left: not an error


def test_fake_scancel_refuses_unknown_arguments(slurm: FakeSlurm) -> None:
    slurm.add_job("1", "PENDING")
    for bad in ([], ["--signal=KILL", "1"], ["-Q", "1"], ["--state"]):
        result = sh("scancel", *bad)
        assert result.returncode == 2, bad
        assert "unsupported arguments" in result.stderr
    assert slurm.job("1")["state"] == "PENDING"


# render_sbatch ---------------------------------------------------------------------
def test_render_sbatch_exact_directives(tmp_path: Path) -> None:
    home = tmp_path / "hx"
    record = make_record("r1", project="toy", gpus_requested=2)
    defaults = SlurmDefaults(
        partition="gpu",
        account="lab",
        time="08:00:00",
        gpus=1,
        extra=["--mem=32G", "--constraint=a100"],
    )
    child = shlex.join([PY, "-m", "hypothex.cli.main", "--home", str(home), "run", "--child", "r1"])
    assert render_sbatch(record, defaults, home) == (
        "#!/bin/bash\n"
        "#SBATCH --job-name=hx-r1\n"
        f"#SBATCH --output={home}/store/toy/runs/r1/logs/slurm-%j.out\n"
        "#SBATCH --time=08:00:00\n"
        "#SBATCH --gpus=2\n"
        "#SBATCH --partition=gpu\n"
        "#SBATCH --account=lab\n"
        "#SBATCH --mem=32G\n"
        "#SBATCH --constraint=a100\n"
        "\n"
        f"exec {child}\n"
    )


def test_render_sbatch_defaults_and_zero_gpus(tmp_path: Path) -> None:
    home = tmp_path / "hx"
    lines = render_sbatch(make_record("r1"), SlurmDefaults(), home).splitlines()
    assert lines[1:5] == [
        "#SBATCH --job-name=hx-r1",
        f"#SBATCH --output={home}/store/toy/runs/r1/logs/slurm-%j.out",
        "#SBATCH --time=02:00:00",
        "#SBATCH --gpus=1",
    ]
    assert lines[5] == ""
    cpu = render_sbatch(make_record("r1"), SlurmDefaults(gpus=0), home)
    assert "--gpus" not in cpu


# SlurmDefaults already refuses these (Task 2). model_construct skips that check, so
# these cases test render_sbatch's own guard (settings can also arrive merged from dicts).
@pytest.mark.parametrize(
    ("defaults", "message"),
    [
        (SlurmDefaults.model_construct(extra=["--mem=32G\nrm -rf ~"]), "exactly one option"),
        (SlurmDefaults.model_construct(extra=["mem=32G"]), "not an sbatch option"),
        (SlurmDefaults.model_construct(extra=["--job-name=x"]), "sets --job-name"),
        (SlurmDefaults.model_construct(extra=["--comm=x"]), "sets --comment"),
        (SlurmDefaults.model_construct(extra=["-Jx"]), "sets --job-name"),
        (
            SlurmDefaults.model_construct(extra=["--qos=normal --output=/tmp/x --job-name=c"]),
            "exactly one option",
        ),
        (SlurmDefaults.model_construct(partition="gpu; rm"), "partition 'gpu; rm'"),
        (SlurmDefaults.model_construct(account="lab\n#SBATCH --qos=high"), "account"),
        (SlurmDefaults.model_construct(time="2 hours"), "time '2 hours'"),
    ],
)
def test_render_sbatch_rejects_unsafe_settings(
    tmp_path: Path, defaults: SlurmDefaults, message: str
) -> None:
    with pytest.raises(SlurmError, match=message):
        render_sbatch(make_record("r1"), defaults, tmp_path / "hx")


def test_render_sbatch_rejects_home_with_spaces(tmp_path: Path) -> None:
    with pytest.raises(SlurmError, match="whitespace"):
        render_sbatch(make_record("r1"), SlurmDefaults(), tmp_path / "my home")


# submit / poll / cancel ------------------------------------------------------------------
def test_submit_returns_job_id_and_sends_script_on_stdin(slurm: FakeSlurm, tmp_path: Path) -> None:
    script = "#!/bin/bash\n#SBATCH --job-name=hx-a\ntrue\n"
    assert submit(script, tmp_path) == "1000"
    assert submit(script, tmp_path) == "1001"
    assert slurm.calls("sbatch") == [["--parsable"], ["--parsable"]]
    job = slurm.job("1000")
    assert job["script"] == script
    assert job["cwd"] == str(tmp_path.resolve())


def test_submit_passes_the_comment_and_find_submitted_matches_it(
    slurm: FakeSlurm, tmp_path: Path
) -> None:
    script = "#!/bin/bash\n#SBATCH --job-name=hx-r1\ntrue\n"
    assert submit(script, tmp_path, comment="hx-r1-aaaa") == "1000"
    assert submit(script, tmp_path, comment="hx-r1-bbbb") == "1001"
    assert slurm.calls("sbatch")[0] == ["--parsable", "--comment=hx-r1-aaaa"]
    found, complete = find_submitted("hx-r1-bbbb")
    assert found is not None and (found.job_id, found.state, complete) == ("1001", "PENDING", True)
    assert find_submitted("hx-r2-cccc") == (None, True)
    cancel("1001")  # left the queue: sacct finds it by its comment
    found, _ = find_submitted("hx-r1-bbbb")
    assert found is not None and (found.job_id, found.state) == ("1001", "CANCELLED")


def test_find_submitted_never_matches_by_name_alone(slurm: FakeSlurm) -> None:
    # a job named hx-r1 (extra --job-name, or another submission) with another comment
    slurm.add_job("1000", "PENDING", name="hx-r1", comment="hx-r1-other")
    slurm.add_job("1001", "COMPLETED", name="hx-r1", in_queue=False)
    assert find_submitted("hx-r1-mine") == (None, True)


def test_find_submitted_is_incomplete_while_sacct_fails(slurm: FakeSlurm) -> None:
    slurm.add_job("1000", "COMPLETED", name="hx-r1", comment="hx-r1-mine", in_queue=False)
    slurm.set(fail={"sacct": "sacct: error: Slurm accounting storage is disabled"})
    assert find_submitted("hx-r1-mine") == (None, False)  # unknown, never "absent"


def test_submit_tells_rejection_from_an_unknown_outcome(
    slurm: FakeSlurm, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = "#!/bin/bash\ntrue\n"
    slurm.set(fail={"sbatch": "sbatch: error: invalid partition specified: nope"})
    with pytest.raises(SlurmError) as rejected:
        submit(script, tmp_path)
    assert not isinstance(rejected.value, SubmitUnknownError)
    timeout = "sbatch: error: Batch job submission failed: Socket timed out on send/recv operation"
    slurm.set(fail={"sbatch": timeout})
    with pytest.raises(SubmitUnknownError, match="Socket timed out"):
        submit(script, tmp_path)
    monkeypatch.setattr(
        "hypothex.core.slurm._exec",
        lambda argv, **k: subprocess.CompletedProcess(argv, 0, "Submitted?\n", ""),
    )
    with pytest.raises(SubmitUnknownError, match="not a job id"):
        submit(script, tmp_path)


def test_sbatch_killed_by_a_signal_after_accepting_is_unknown(
    slurm: FakeSlurm, tmp_path: Path
) -> None:
    slurm.set(sbatch_signal="KILL")
    with pytest.raises(SubmitUnknownError, match="signal 9"):
        submit("#!/bin/bash\ntrue\n", tmp_path, comment="hx-r1-kill")
    found, complete = find_submitted("hx-r1-kill")  # SLURM had taken it
    assert found is not None and (found.job_id, complete) == ("1000", True)


@pytest.mark.parametrize(
    ("rc", "stdout", "stderr"),
    [
        (1, "", "sbatch: error: Something nobody has seen before\n"),
        (1, "1000\n", "sbatch: error: invalid partition specified: gpu\n"),  # an id after all
        (-15, "", "sbatch: error: invalid partition specified: gpu\n"),  # a signal
        (1, "", ""),
        (0, "", ""),
        (0, "\x00\x01garbled\n", ""),
    ],
)
def test_only_positive_evidence_is_a_rejection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, rc: int, stdout: str, stderr: str
) -> None:
    monkeypatch.setattr(
        "hypothex.core.slurm._exec",
        lambda argv, **k: subprocess.CompletedProcess(argv, rc, stdout, stderr),
    )
    with pytest.raises(SubmitUnknownError):
        submit("#!/bin/bash\ntrue\n", tmp_path)


@pytest.mark.parametrize(
    "stderr",
    [
        "sbatch: error: invalid partition specified: nope",
        "sbatch: error: Batch job submission failed: Invalid account or account/partition "
        "combination specified",
        "sbatch: error: Batch job submission failed: Requested node configuration is not available",
        "sbatch: error: Batch job submission failed: Job violates accounting/QOS policy "
        "(job submit limit, user's size and/or time limits)",
        "sbatch: unrecognized option '--bogus'",
    ],
)
def test_a_recognised_rejection_is_definitive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stderr: str
) -> None:
    monkeypatch.setattr(
        "hypothex.core.slurm._exec",
        lambda argv, **k: subprocess.CompletedProcess(argv, 1, "", stderr + "\n"),
    )
    with pytest.raises(SlurmError) as rejected:
        submit("#!/bin/bash\ntrue\n", tmp_path)
    assert not isinstance(rejected.value, SubmitUnknownError)


def _time_out(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    raise subprocess.TimeoutExpired(args[0], 60.0)


def test_sbatch_timeout_is_unknown_never_a_rejection(
    slurm: FakeSlurm, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("hypothex.core.slurm.subprocess.run", _time_out)
    with pytest.raises(SubmitUnknownError, match="timed out.*the job may exist"):
        submit("#!/bin/bash\ntrue\n", tmp_path, comment="hx-r1-timeout")


def test_poll_timeout_raises_slurm_timeout(
    slurm: FakeSlurm, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("hypothex.core.slurm.subprocess.run", _time_out)
    with pytest.raises(SlurmTimeout, match="squeue timed out") as timed_out:
        poll(["1000"])
    assert not isinstance(timed_out.value, SubmitUnknownError)


def test_sbatch_that_cannot_start_is_a_definitive_error(slurm: FakeSlurm, tmp_path: Path) -> None:
    with pytest.raises(SlurmError, match="could not run sbatch") as refused:
        submit("#!/bin/bash\ntrue\n", tmp_path / "no-such-dir")
    assert not isinstance(refused.value, SubmitUnknownError | SlurmTimeout)
    assert slurm.calls("sbatch") == []  # it never ran, so no job can exist


def test_without_comment_accounting_sacct_never_proves_absence(slurm: FakeSlurm) -> None:
    slurm.set(accounting_flags="")
    slurm.add_job("1000", "COMPLETED", comment="hx-r1-done", in_queue=False)
    slurm.add_job("1001", "PENDING", comment="hx-r2-queued")
    assert find_submitted("hx-r1-done") == (None, False)  # unknown, never "absent"
    found, complete = find_submitted("hx-r2-queued")  # squeue's %k still works
    assert found is not None and (found.job_id, complete) == ("1001", True)
    assert slurm.calls("sacct") == []


def test_comment_accounting_is_probed_once_per_server_start(slurm: FakeSlurm) -> None:
    assert comment_accounting() is True
    slurm.set(accounting_flags="job_env")
    assert comment_accounting() is True  # cached for this server's life
    assert comment_accounting(refresh=True) is False  # the next server start asks again
    assert len(slurm.calls("scontrol")) == 2
    slurm.set(fail={"scontrol": "scontrol: error: slurm_load_ctl_conf: Unable to contact"})
    assert comment_accounting(refresh=True) is False  # a failing probe: no comment lookup
    slurm.set(fail={}, accounting_flags="job_comment,job_env")
    assert comment_accounting() is True  # ... and it is asked again, not cached


def test_submit_failure_raises_with_stderr(slurm: FakeSlurm, tmp_path: Path) -> None:
    slurm.set(fail={"sbatch": "sbatch: error: invalid partition specified: nope"})
    with pytest.raises(SlurmError, match="invalid partition specified: nope"):
        submit("#!/bin/bash\ntrue\n", tmp_path)


def test_submit_without_sbatch_on_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(SlurmError, match="sbatch not found on PATH"):
        submit("#!/bin/bash\ntrue\n", tmp_path)


def test_poll_reads_squeue_then_sacct(slurm: FakeSlurm) -> None:
    slurm.add_job("1000", "RUNNING", node="n1")
    slurm.add_job("1001", "PENDING")
    slurm.add_job("1002", "COMPLETED", node="n2", exit="0:0", in_queue=False)
    slurm.add_job("1003", "FAILED", node="n3", exit="2:0", in_queue=False)
    slurm.add_job("1004", "CANCELLED by 1000", exit="0:15", in_queue=False)
    slurm.add_job("1005", "COMPLETED", in_queue=False, in_sacct=False)
    slurm.add_job("1007", "RUNNING", node="n9")
    jobs = poll(["1000", "1001", "1002", "1003", "1004", "1005", "1006"])
    assert jobs == {
        "1000": SlurmJob(job_id="1000", state="RUNNING", node="n1"),
        "1001": SlurmJob(job_id="1001", state="PENDING"),
        "1002": SlurmJob(job_id="1002", state="COMPLETED", node="n2", exit_code=0),
        "1003": SlurmJob(job_id="1003", state="FAILED", node="n3", exit_code=2),
        "1004": SlurmJob(job_id="1004", state="CANCELLED", exit_code=143),
    }
    assert slurm.calls("squeue") == [
        ["--noheader", f"--user={getpass.getuser()}", "--format=%i|%T|%N"]
    ]
    assert slurm.calls("sacct") == [
        [
            "-X",
            "--noheader",
            "--parsable2",
            "--format=JobID,State,ExitCode,NodeList",
            "--jobs=1002,1003,1004,1005,1006",
        ]
    ]


def test_poll_skips_sacct_when_all_queued_and_nothing_for_empty(slurm: FakeSlurm) -> None:
    assert poll([]) == {}
    assert slurm.state()["calls"] == []
    slurm.add_job("1000", "PENDING")
    assert poll(["1000"]) == {"1000": SlurmJob(job_id="1000", state="PENDING")}
    assert slurm.calls("sacct") == []


def test_poll_raises_when_squeue_fails(slurm: FakeSlurm) -> None:
    slurm.set(fail={"squeue": "slurm_load_jobs error: Unable to contact slurm controller"})
    with pytest.raises(SlurmError, match="Unable to contact slurm controller"):
        poll(["1000"])


def test_poll_tolerates_sacct_failure(slurm: FakeSlurm) -> None:
    slurm.add_job("1000", "RUNNING", node="n1")
    slurm.set(fail={"sacct": "sacct: error: Slurm accounting storage is disabled"})
    assert poll(["1000", "1001"]) == {"1000": SlurmJob(job_id="1000", state="RUNNING", node="n1")}


def test_is_finished_and_lost_reason() -> None:
    assert not is_finished(SlurmJob(job_id="1", state="COMPLETING"))
    assert is_finished(SlurmJob(job_id="1", state="TIMEOUT"))
    node_fail = SlurmJob(job_id="7", state="NODE_FAIL", node="r208u06n02")
    assert lost_reason("7", node_fail) == (
        "SLURM ended job 7 with NODE_FAIL on r208u06n02; no exit record"
    )
    failed = SlurmJob(job_id="7", state="FAILED", node="n3", exit_code=2)
    assert (
        lost_reason("7", failed) == "SLURM ended job 7 with FAILED on n3 (exit 2); no exit record"
    )
    assert lost_reason("7", None) == (
        "slurm job 7 left the queue; SLURM reports no end state for it; no exit record"
    )


def test_cancel_calls_scancel_and_raises_on_unknown_job(slurm: FakeSlurm) -> None:
    slurm.add_job("1000", "PENDING")
    cancel("1000")
    assert slurm.job("1000")["state"] == "CANCELLED"
    with pytest.raises(SlurmError, match="Invalid job id specified"):
        cancel("1000")
    assert slurm.calls("scancel") == [["1000"], ["1000"]]


# hx run --child ----------------------------------------------------------------------------
def submitted(ctx: Context, toy_repo: Path, code: str, job_id: str = "4242") -> RunRecord:
    req = RunRequest(repo=toy_repo, command=[PY, "-c", code], gpus=2, slurm=SlurmDefaults())
    record = prepare_run(ctx, req)
    return ctx.update_run(
        record.run_id,
        "run.submitted",
        lambda r: r.model_copy(
            update={"executor": ExecutorInfo(type="slurm", slurm_job_id=job_id, host="cluster")}
        ),
    )


READ_OWN_RECORD = (
    "import os, yaml; "
    "r = yaml.safe_load(open(os.environ['HYPOTHEX_RUN_DIR'] + '/run.yaml')); "
    "print(r['status'], r['executor']['type'], r['executor']['slurm_job_id'], "
    "r['executor']['node'])"
)


def test_run_child_keeps_slurm_executor_fields(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SLURM_JOB_ID", "4242")
    monkeypatch.setenv("SLURMD_NODENAME", "n7")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "2,3")
    record = submitted(ctx, toy_repo, READ_OWN_RECORD)
    final = run_child(ctx.layout.home, record.run_id)
    assert final.status == RunStatus.FINISHED
    run_dir = ctx.run_dir(final)
    # while running, run.yaml already said slurm + node (not a plain local executor)
    assert (run_dir / "logs" / "stdout.log").read_text().strip() == "running slurm 4242 n7"
    ex = final.executor
    assert (ex.type, ex.slurm_job_id, ex.node, ex.gpus, ex.host) == (
        "slurm",
        "4242",
        "n7",
        [2, 3],
        "cluster",
    )
    assert ex.pid == os.getpid()


def test_run_child_gpus_fall_back_to_requested_count(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    monkeypatch.delenv("SLURMD_NODENAME", raising=False)
    record = submitted(ctx, toy_repo, "pass")
    final = run_child(ctx.layout.home, record.run_id)
    assert final.executor.gpus == [0, 1]
    assert final.executor.node is not None and final.executor.node != ""


def test_cli_run_child(ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLURM_JOB_ID", "4242")
    monkeypatch.setenv("SLURMD_NODENAME", "n7")
    record = submitted(ctx, toy_repo, "import sys; print('on node'); sys.exit(3)")
    result = runner.invoke(app, ["run", "--child", record.run_id, "--json"])
    assert result.exit_code == 3
    final = ctx.find_record(record.run_id)
    assert (final.status, final.exit_code, final.executor.node) == (RunStatus.FAILED, 3, "n7")
    assert (ctx.run_dir(final) / "logs" / "stdout.log").read_text() == "on node\n"


def test_cli_run_child_refuses_a_run_that_is_not_queued(ctx: Context, toy_repo: Path) -> None:
    record = submitted(ctx, toy_repo, "pass")
    run_child(ctx.layout.home, record.run_id)
    result = runner.invoke(app, ["run", "--child", record.run_id])
    assert result.exit_code != 0
    assert isinstance(result.exception, RunError)
    assert "not queued" in str(result.exception)


def test_run_child_never_opens_the_index_or_event_log(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = submitted(ctx, toy_repo, "print('on node')")
    before = len(ctx.events.since(0, limit=10_000))

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("the compute node opened a SQLite file")

    monkeypatch.setattr("hypothex.core.index.Index.__init__", refuse)
    monkeypatch.setattr("hypothex.core.events.EventLog.__init__", refuse)
    final = run_child(ctx.layout.home, record.run_id)
    assert final.status == RunStatus.FINISHED
    # no node-side events and no index writes: the login node publishes them later
    assert len(ctx.events.since(0, limit=10_000)) == before
    indexed = ctx.index.get_run(record.run_id)
    assert indexed is not None and indexed.status == RunStatus.QUEUED
    exit_record = json.loads((ctx.run_dir(final) / EXIT_FILE).read_text())
    assert (exit_record["status"], exit_record["exit_code"]) == ("finished", 0)


def test_a_home_without_flock_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert flock_supported(tmp_path)
    require_flock(tmp_path)

    def no_flock(fd: int, operation: int) -> None:
        raise OSError(errno.ENOSYS, "Function not implemented")  # Lustre without -o flock

    monkeypatch.setattr("hypothex.core.slurm.fcntl.flock", no_flock)
    assert not flock_supported(tmp_path)
    with pytest.raises(ConfigError, match=r"does not support flock.*mount it with flock"):
        require_flock(tmp_path)


# submit_run and launch_run ------------------------------------------------------------------
def test_launch_run_submits_to_slurm(ctx: Context, toy_repo: Path, slurm: FakeSlurm) -> None:
    req = RunRequest(
        repo=toy_repo,
        command=[PY, "-c", "pass"],
        hypothesis="slurm",
        gpus=2,
        slurm=SlurmDefaults(partition="gpu", time="00:10:00"),
    )
    record = control.launch_run(ctx, req)
    assert record.status == RunStatus.QUEUED
    ex = record.executor
    assert (ex.type, ex.slurm_job_id, ex.pid, ex.child_pid) == ("slurm", "1000", None, None)
    assert ex.host == ctx.descriptor.label
    run_dir = ctx.run_dir(record)
    assert not (run_dir / "supervisor.pid").exists()
    job = slurm.job("1000")
    assert job["script"] == (run_dir / SBATCH_FILE).read_text()
    assert (
        job["comment"].startswith(f"hx-{record.run_id}-")
        and len(job["comment"]) == len(f"hx-{record.run_id}-") + 8
    )
    assert job["directives"] == {
        "comment": job["comment"],  # the fake keeps every flag, --comment included
        "job-name": f"hx-{record.run_id}",
        "output": f"{run_dir}/logs/slurm-%j.out",
        "time": "00:10:00",
        "gpus": "2",
        "partition": "gpu",
    }
    assert job["cwd"] == record.cwd
    types = [e.type for e in ctx.events.since(0, limit=10_000) if e.run_id == record.run_id]
    assert types[-2:] == ["run.submitting", "run.submitted"]  # the intent comes before sbatch


def test_launch_run_on_slurm_env_uses_default_settings(
    ctx: Context, toy_repo: Path, slurm: FakeSlurm
) -> None:
    ctx.descriptor = ctx.descriptor.model_copy(update={"kind": "slurm"})
    record = control.launch_run(ctx, RunRequest(repo=toy_repo, command=[PY, "-c", "pass"]))
    assert record.executor.slurm_job_id == "1000"
    assert slurm.job("1000")["directives"]["time"] == "02:00:00"
    assert slurm.job("1000")["directives"]["gpus"] == "1"


def test_launch_run_rejects_unsafe_settings_before_creating_a_run(
    ctx: Context, toy_repo: Path, slurm: FakeSlurm
) -> None:
    unsafe = SlurmDefaults.model_construct(partition="gpu;id")  # skips Task 2's check
    req = RunRequest(repo=toy_repo, command=[PY, "-c", "pass"], slurm=unsafe)
    with pytest.raises(SlurmError, match="partition"):
        control.launch_run(ctx, req)
    assert ctx.index.list_runs(include_archived=True, limit=None) == []
    assert slurm.calls("sbatch") == []


def test_queued_slurm_launch_never_waits_in_the_host_queue(
    ctx: Context, toy_repo: Path, slurm: FakeSlurm
) -> None:
    req = RunRequest(
        repo=toy_repo, command=[PY, "-c", "pass"], gpus=2, queue=True, slurm=SlurmDefaults()
    )
    record = control.launch_run(ctx, req)
    assert record.executor.slurm_job_id == "1000"
    assert not (ctx.run_dir(record) / "queue.json").exists()


def test_an_unknown_sbatch_outcome_keeps_the_run_and_its_intent(
    ctx: Context, toy_repo: Path, slurm: FakeSlurm, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hypothex.core import slurm as slurm_module

    real = slurm_module.submit

    def accepted_then_timed_out(script: str, cwd: Path, *, comment: str | None = None) -> str:
        real(script, cwd, comment=comment)  # the controller took the job ...
        raise slurm_module.SubmitUnknownError("sbatch timed out after 60s; the job may exist")

    monkeypatch.setattr(slurm_module, "submit", accepted_then_timed_out)
    req = RunRequest(repo=toy_repo, command=[PY, "-c", "pass"], slurm=SlurmDefaults())
    record = control.launch_run(ctx, req)  # ... and no error: it may well run
    assert record.status == RunStatus.QUEUED and record.executor.slurm_job_id is None
    entry = json.loads((ctx.layout.home / "slurm" / "outbox" / f"{record.run_id}.json").read_text())
    assert entry["state"] == "unknown" and entry["comment"] == slurm.job("1000")["comment"]
    types = [e.type for e in ctx.events.since(0, limit=10_000) if e.run_id == record.run_id]
    assert types[-1] == "run.submit_unknown" and "run.failed" not in types


def test_submit_run_records_sbatch_failure(ctx: Context, toy_repo: Path, slurm: FakeSlurm) -> None:
    slurm.set(fail={"sbatch": "sbatch: error: invalid partition specified: nope"})
    record = prepare_run(ctx, RunRequest(repo=toy_repo, command=[PY, "-c", "pass"]))
    with pytest.raises(RunError, match="invalid partition specified: nope"):
        submit_run(ctx, record, SlurmDefaults(partition="nope"))
    failed = ctx.find_record(record.run_id)
    assert failed.status == RunStatus.FAILED
    assert failed.ended_at is not None
    last = [e for e in ctx.events.since(0, limit=10_000) if e.run_id == record.run_id][-1]
    assert last.type == "run.failed"
    assert "invalid partition specified: nope" in last.payload["reason"]


def test_end_to_end_job_runs_hx_run_child(ctx: Context, toy_repo: Path, slurm: FakeSlurm) -> None:
    slurm.set(mode="run")
    req = RunRequest(
        repo=toy_repo,
        command=[PY, "-c", "print('on node')"],
        hypothesis="e2e",
        gpus=1,
        slurm=SlurmDefaults(partition="gpu"),
    )
    record = control.launch_run(ctx, req)
    done = control.wait_for_run(ctx, record.run_id, timeout=60)
    assert done.status == RunStatus.FINISHED
    ex = done.executor
    assert (ex.type, ex.slurm_job_id, ex.node, ex.gpus) == ("slurm", "1000", "fake-node1", [0])
    run_dir = ctx.run_dir(done)
    assert (run_dir / "logs" / "stdout.log").read_text() == "on node\n"
    wait_until(lambda: not slurm.job("1000")["in_queue"])
    assert slurm.job("1000")["state"] == "COMPLETED"
    slurm_out = (run_dir / "logs" / "slurm-1000.out").read_text()
    assert f"finished (exit 0) {done.run_id}" in slurm_out
    assert json.loads((run_dir / EXIT_FILE).read_text())["status"] == "finished"


def test_submit_run_saves_the_settings_with_the_run(
    ctx: Context, toy_repo: Path, slurm: FakeSlurm
) -> None:
    settings = SlurmDefaults(partition="gpu", account="lab", time="00:10:00", gpus=2)
    req = RunRequest(repo=toy_repo, command=[PY, "-c", "pass"], gpus=2, slurm=settings)
    record = control.launch_run(ctx, req)
    saved = json.loads((ctx.run_dir(record) / "slurm.json").read_text())
    assert SlurmDefaults.model_validate(saved) == settings


def test_slurm_env_remembers_the_last_settings_it_was_sent(
    ctx: Context, toy_repo: Path, slurm: FakeSlurm
) -> None:
    ctx.descriptor = ctx.descriptor.model_copy(update={"kind": "slurm"})
    hub_block = SlurmDefaults(partition="gpu", account="lab")
    control.launch_run(ctx, RunRequest(repo=toy_repo, command=[PY, "-c", "pass"], slurm=hub_block))
    # a later launch without settings (hx launch on the login node) keeps partition and account
    control.launch_run(ctx, RunRequest(repo=toy_repo, command=[PY, "-c", "pass"]))
    directives = slurm.job("1001")["directives"]
    assert (directives["partition"], directives["account"]) == ("gpu", "lab")


def test_rerun_keeps_the_slurm_settings_and_gpus(
    ctx: Context, toy_repo: Path, slurm: FakeSlurm
) -> None:
    settings = SlurmDefaults(partition="gpu", account="lab", time="00:10:00")
    req = RunRequest(repo=toy_repo, command=[PY, "-c", "pass"], gpus=2, slurm=settings)
    parent = control.launch_run(ctx, req)
    (ctx.layout.home / "slurm_defaults.json").unlink()  # only the run's own copy is left
    child = control.rerun(ctx, parent.run_id)
    assert child.gpus_requested == 2 and child.executor.slurm_job_id == "1001"
    directives = slurm.job("1001")["directives"]
    assert (directives["partition"], directives["account"], directives["gpus"]) == (
        "gpu",
        "lab",
        "2",
    )


def test_corrupt_last_defaults_refuse_a_slurm_launch(
    ctx: Context, toy_repo: Path, slurm: FakeSlurm, caplog: pytest.LogCaptureFixture
) -> None:
    ctx.descriptor = ctx.descriptor.model_copy(update={"kind": "slurm"})
    (ctx.layout.home / "slurm_defaults.json").write_text("{not json")
    with caplog.at_level("WARNING"), pytest.raises(RunError, match="invalid SLURM settings"):
        control.launch_run(ctx, RunRequest(repo=toy_repo, command=[PY, "-c", "pass"]))
    assert "slurm_defaults.json" in caplog.text
    assert slurm.calls("sbatch") == []
    assert ctx.index.list_runs(include_archived=True, limit=None) == []


def test_corrupt_run_settings_refuse_a_rerun(
    ctx: Context, toy_repo: Path, slurm: FakeSlurm
) -> None:
    req = RunRequest(repo=toy_repo, command=[PY, "-c", "pass"], slurm=SlurmDefaults())
    parent = control.launch_run(ctx, req)
    (ctx.run_dir(parent) / "slurm.json").write_text("{not json")
    with pytest.raises(RunError, match="invalid SLURM settings"):
        control.rerun(ctx, parent.run_id)
    assert len(slurm.calls("sbatch")) == 1  # no local run, no second job


def test_missing_slurm_settings_are_not_an_error(tmp_path: Path) -> None:
    assert run_slurm_settings(tmp_path) is None


def test_foreground_rerun_on_slurm_is_refused(
    ctx: Context, toy_repo: Path, slurm: FakeSlurm
) -> None:
    req = RunRequest(repo=toy_repo, command=[PY, "-c", "pass"], slurm=SlurmDefaults())
    parent = control.launch_run(ctx, req)
    # reinfer reaches the same check: both go through control._start
    with pytest.raises(RunError, match="SLURM runs are always submitted; drop --foreground"):
        control.rerun(ctx, parent.run_id, background=False)
    assert [r.run_id for r in ctx.index.list_runs(include_archived=True, limit=None)] == [
        parent.run_id
    ]
    assert len(slurm.calls("sbatch")) == 1  # nothing ran on the login node either


def test_rerun_of_a_gpu_run_waits_for_gpus(
    ctx: Context, toy_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = tmp_path / "gpus.json"
    fake.write_text(json.dumps([{"index": 0}, {"index": 1}]))
    monkeypatch.setenv("HYPOTHEX_FAKE_GPUS", str(fake))
    parent = prepare_run(ctx, RunRequest(repo=toy_repo, command=[PY, "-c", "pass"], gpus=2))
    child = control.rerun(ctx, parent.run_id)
    assert child.gpus_requested == 2
    assert child.status == RunStatus.QUEUED and child.executor.queue_position == 1
    assert not (ctx.run_dir(child) / "supervisor.pid").exists()


# reconcile (lost detection) ------------------------------------------------------------------
def test_reconcile_records_node_of_running_job(ctx: Context, slurm: FakeSlurm) -> None:
    slurm.add_job("1000", "RUNNING", node="n1")
    slurm_run(ctx, "r1", status=RunStatus.QUEUED)
    changed = reconcile(ctx)
    assert [(r.run_id, r.status, r.executor.node) for r in changed] == [
        ("r1", RunStatus.QUEUED, "n1")
    ]
    last = ctx.events.since(0, limit=10_000)[-1]
    assert (last.type, last.payload["slurm_state"], last.payload["node"]) == (
        "run.slurm_state",
        "RUNNING",
        "n1",
    )
    assert reconcile(ctx) == []


def test_reconcile_marks_vanished_job_lost(ctx: Context, slurm: FakeSlurm) -> None:
    slurm_run(ctx, "r1", job_id="1000")
    changed = reconcile(ctx)
    assert [(r.run_id, r.status) for r in changed] == [("r1", RunStatus.LOST)]
    assert changed[0].ended_at is not None
    last = ctx.events.since(0, limit=10_000)[-1]
    assert last.type == "run.lost"
    assert last.payload["reason"] == (
        "slurm job 1000 left the queue; SLURM reports no end state for it; no exit record"
    )
    assert last.payload["slurm_state"] is None


def test_reconcile_marks_node_fail_lost_with_slurm_state(ctx: Context, slurm: FakeSlurm) -> None:
    slurm.add_job("1000", "NODE_FAIL", node="r208u06n02", exit="0:0", in_queue=False)
    slurm_run(ctx, "r1", job_id="1000")
    [lost] = reconcile(ctx)
    assert lost.status == RunStatus.LOST
    last = ctx.events.since(0, limit=10_000)[-1]
    assert last.payload["slurm_state"] == "NODE_FAIL"
    assert last.payload["reason"] == (
        "SLURM ended job 1000 with NODE_FAIL on r208u06n02 (exit 0); no exit record"
    )


def test_reconcile_keeps_runs_with_an_exit_record(ctx: Context, slurm: FakeSlurm) -> None:
    slurm.add_job("1000", "COMPLETED", node="n1", in_queue=False)
    record = slurm_run(ctx, "r1", job_id="1000")
    # the node wrote run.yaml (no event, no index: it never opens the SQLite files)
    ctx.store.write_record(record.model_copy(update={"status": RunStatus.FINISHED, "exit_code": 0}))
    assert [(r.run_id, r.status) for r in reconcile(ctx)] == [("r1", RunStatus.FINISHED)]
    assert ctx.find_record("r1").status == RunStatus.FINISHED
    indexed = ctx.index.get_run("r1")
    assert indexed is not None and indexed.status == RunStatus.FINISHED
    # (task "t" is not in a registered project, so scoring adds run.eval_skipped after it)
    published = [e for e in ctx.events.since(0, limit=10_000) if e.type == "run.finished"]
    assert [(e.run_id, e.payload["exit_code"]) for e in published] == [("r1", 0)]
    assert reconcile(ctx) == []  # published once


def test_reconcile_publishes_the_node_s_start(ctx: Context, slurm: FakeSlurm) -> None:
    slurm.add_job("1000", "RUNNING", node="n1")
    record = slurm_run(ctx, "r1", job_id="1000", status=RunStatus.QUEUED, node="n1")
    ctx.store.write_record(record.model_copy(update={"status": RunStatus.RUNNING}))
    [started] = reconcile(ctx)
    assert started.status == RunStatus.RUNNING
    assert ctx.events.since(0, limit=10_000)[-1].type == "run.started"
    indexed = ctx.index.get_run("r1")
    assert indexed is not None and indexed.status == RunStatus.RUNNING


def test_reconcile_restores_the_exit_record(ctx: Context, slurm: FakeSlurm) -> None:
    # the node's exit record is newer than run.yaml (a write that replaced its last one)
    slurm.add_job("1000", "COMPLETED", node="n1", in_queue=False)
    record = slurm_run(ctx, "r1", job_id="1000")
    exit_record = {"run_id": "r1", "status": "failed", "exit_code": 3}
    exit_record["ended_at"] = "2026-10-03T10:00:00+00:00"
    (ctx.run_dir(record) / EXIT_FILE).write_text(json.dumps(exit_record))
    [ended] = reconcile(ctx)
    assert (ended.status, ended.exit_code) == (RunStatus.FAILED, 3)
    assert ctx.events.since(0, limit=10_000)[-1].type == "run.failed"
    assert reconcile(ctx) == []


def test_end_to_end_events_come_from_the_login_node(
    ctx: Context, toy_repo: Path, slurm: FakeSlurm
) -> None:
    slurm.set(mode="run")
    req = RunRequest(repo=toy_repo, command=[PY, "-c", "pass"], slurm=SlurmDefaults(gpus=0))
    record = control.launch_run(ctx, req)
    control.wait_for_run(ctx, record.run_id, timeout=60)
    types = [e.type for e in ctx.events.since(0, limit=10_000) if e.run_id == record.run_id]
    assert "run.finished" not in types  # the node wrote run.yaml only
    reconcile(ctx)
    types = [e.type for e in ctx.events.since(0, limit=10_000) if e.run_id == record.run_id]
    assert types[-1] == "run.finished"
    indexed = ctx.index.get_run(record.run_id)
    assert indexed is not None and indexed.status == RunStatus.FINISHED


def test_reconcile_changes_nothing_when_squeue_fails(ctx: Context, slurm: FakeSlurm) -> None:
    slurm_run(ctx, "r1", job_id="1000")
    slurm.set(fail={"squeue": "slurm_load_jobs error: Unable to contact slurm controller"})
    with pytest.raises(SlurmError):
        reconcile(ctx)
    assert ctx.find_record("r1").status == RunStatus.RUNNING


def test_reconcile_ignores_local_and_foreign_runs(ctx: Context, slurm: FakeSlurm) -> None:
    ctx.create_run(
        make_record("local", status=RunStatus.RUNNING, environment_id=ctx.descriptor.environment_id)
    )
    slurm_run(ctx, "foreign", environment_id="another-env")
    assert reconcile(ctx) == []
    assert slurm.state()["calls"] == []


def test_reconcile_confirm_gone_needs_two_polls(ctx: Context, slurm: FakeSlurm) -> None:
    slurm_run(ctx, "r1", job_id="1000")
    gone: dict[str, SlurmJob | None] = {}
    assert reconcile(ctx, confirm_gone=gone) == []
    assert gone == {"1000": None}
    assert ctx.find_record("r1").status == RunStatus.RUNNING
    [lost] = reconcile(ctx, confirm_gone=gone)
    assert lost.status == RunStatus.LOST
    assert gone == {}


def test_reconcile_confirm_gone_resets_when_job_reappears(ctx: Context, slurm: FakeSlurm) -> None:
    slurm_run(ctx, "r1", job_id="1000")
    gone: dict[str, SlurmJob | None] = {}
    reconcile(ctx, confirm_gone=gone)
    slurm.add_job("1000", "RUNNING", node="n1")  # requeued / visible again
    reconcile(ctx, confirm_gone=gone)
    assert gone == {}
    assert ctx.find_record("r1").status == RunStatus.RUNNING


def test_the_lost_reason_keeps_slurm_s_end_state(ctx: Context, slurm: FakeSlurm) -> None:
    # NODE_FAIL in sacct at the first poll; sacct is down at the second
    slurm.add_job("1000", "NODE_FAIL", node="r208u06n02", exit="0:0", in_queue=False)
    slurm_run(ctx, "r1", job_id="1000")
    gone: dict[str, SlurmJob | None] = {}
    assert reconcile(ctx, confirm_gone=gone) == []
    slurm.set(fail={"sacct": "sacct: error: Slurm accounting storage is disabled"})
    [lost] = reconcile(ctx, confirm_gone=gone)
    assert lost.status == RunStatus.LOST
    last = ctx.events.since(0, limit=10_000)[-1]
    assert (last.type, last.payload["slurm_state"]) == ("run.lost", "NODE_FAIL")
    assert last.payload["reason"].startswith("SLURM ended job 1000 with NODE_FAIL on r208u06n02")


def test_a_node_that_ends_during_reconcile_is_published_not_lost(
    ctx: Context, slurm: FakeSlurm, monkeypatch: pytest.MonkeyPatch
) -> None:
    slurm_run(ctx, "r1", job_id="1000")
    real = slurm_module.poll

    def poll_then_the_node_finishes(job_ids: list[str]) -> dict[str, SlurmJob]:
        jobs = real(job_ids)  # gone: the run is about to be marked lost ...
        done = ctx.find_record("r1").model_copy(update={"status": RunStatus.FINISHED})
        ctx.store.write_record(done.model_copy(update={"exit_code": 0}))  # ... the node ends
        return jobs

    monkeypatch.setattr(slurm_module, "poll", poll_then_the_node_finishes)
    [done] = reconcile(ctx)
    assert done.status == RunStatus.FINISHED
    types = [e.type for e in ctx.events.since(0, limit=10_000) if e.run_id == "r1"]
    assert "run.lost" not in types and types.count("run.finished") == 1
    assert ctx.events.since(0, limit=10_000)[-1].payload.get("status") != "lost"
    assert not outbox(ctx, "r1").exists()  # acknowledged after run.finished, not before


def test_an_unknown_outcome_is_resolved_by_the_job_s_comment(
    ctx: Context, toy_repo: Path, slurm: FakeSlurm, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = slurm_module.submit

    def accepted_then_timed_out(script: str, cwd: Path, *, comment: str | None = None) -> str:
        real(script, cwd, comment=comment)
        raise SubmitUnknownError("sbatch timed out after 60s; the job may exist")

    monkeypatch.setattr(slurm_module, "submit", accepted_then_timed_out)
    req = RunRequest(repo=toy_repo, command=[PY, "-c", "pass"], slurm=SlurmDefaults())
    record = control.launch_run(ctx, req)
    monkeypatch.setattr(slurm_module, "submit", real)
    [found] = reconcile(ctx)
    assert (found.status, found.executor.slurm_job_id) == (RunStatus.QUEUED, "1000")
    assert json.loads(outbox(ctx, record.run_id).read_text())["state"] == "submitted"
    assert len(slurm.calls("sbatch")) == 1  # never submitted twice


def test_an_unknown_outcome_fails_only_when_slurm_provably_never_took_the_job(
    ctx: Context, toy_repo: Path, slurm: FakeSlurm, monkeypatch: pytest.MonkeyPatch
) -> None:
    def timed_out(script: str, cwd: Path, *, comment: str | None = None) -> str:
        raise SubmitUnknownError("sbatch timed out after 60s; the job may exist")

    monkeypatch.setattr(slurm_module, "submit", timed_out)
    req = RunRequest(repo=toy_repo, command=[PY, "-c", "pass"], slurm=SlurmDefaults())
    run_id = control.launch_run(ctx, req).run_id
    assert reconcile(ctx) == []  # too early: the controller may still create it
    entry = json.loads(outbox(ctx, run_id).read_text())
    entry["intent_at"] = "2000-01-01T00:00:00+00:00"
    outbox(ctx, run_id).write_text(json.dumps(entry))
    slurm.set(fail={"sacct": "sacct: error: Slurm accounting storage is disabled"})
    assert reconcile(ctx) == []  # sacct did not answer: unknown, never absent
    assert ctx.find_record(run_id).status == RunStatus.QUEUED
    slurm.set(fail={})
    [failed] = reconcile(ctx)
    assert failed.status == RunStatus.FAILED
    last = ctx.events.since(0, limit=10_000)[-1]
    assert last.type == "run.failed" and "sbatch never accepted" in last.payload["reason"]
    assert not outbox(ctx, run_id).exists()


def test_without_comment_accounting_an_unknown_submission_stays_unknown(
    ctx: Context, toy_repo: Path, slurm: FakeSlurm, monkeypatch: pytest.MonkeyPatch
) -> None:
    slurm.set(accounting_flags="")  # the cluster's sacct keeps no job comments

    def timed_out(script: str, cwd: Path, *, comment: str | None = None) -> str:
        raise SubmitUnknownError("sbatch timed out after 60s; the job may exist")

    monkeypatch.setattr(slurm_module, "submit", timed_out)
    req = RunRequest(repo=toy_repo, command=[PY, "-c", "pass"], slurm=SlurmDefaults())
    run_id = control.launch_run(ctx, req).run_id
    entry = json.loads(outbox(ctx, run_id).read_text())
    entry["intent_at"] = "2000-01-01T00:00:00+00:00"
    outbox(ctx, run_id).write_text(json.dumps(entry))
    assert reconcile(ctx) == [] and reconcile(ctx) == []  # never "absent", however long
    assert ctx.find_record(run_id).status == RunStatus.QUEUED
    assert json.loads(outbox(ctx, run_id).read_text())["state"] == "unknown"
    notices = [
        e.payload
        for e in ctx.events.since(0, limit=10_000)
        if e.run_id == run_id and e.payload.get("reason") == slurm_module.UNRESOLVED_SUBMISSION
    ]
    assert notices == [
        {
            "reason": "submission outcome unknown; check squeue/sacct",
            "comment": entry["comment"],
            "comment_accounting": False,
        }
    ]
    assert slurm.calls("sacct") == []


def test_sbatch_killed_after_accepting_is_found_by_its_comment(
    ctx: Context, toy_repo: Path, slurm: FakeSlurm
) -> None:
    slurm.set(sbatch_signal="KILL")  # the controller took the job; sbatch died before the id
    req = RunRequest(repo=toy_repo, command=[PY, "-c", "pass"], slurm=SlurmDefaults())
    record = control.launch_run(ctx, req)
    assert record.status == RunStatus.QUEUED and record.executor.slurm_job_id is None
    assert json.loads(outbox(ctx, record.run_id).read_text())["state"] == "unknown"
    types = [e.type for e in ctx.events.since(0, limit=10_000) if e.run_id == record.run_id]
    assert types[-1] == "run.submit_unknown" and "run.failed" not in types
    slurm.set(sbatch_signal=None)
    [found] = reconcile(ctx)
    assert (found.status, found.executor.slurm_job_id) == (RunStatus.QUEUED, "1000")
    assert len(slurm.calls("sbatch")) == 1  # never submitted twice


def test_a_node_that_ends_while_its_intent_is_resolved_is_published(
    ctx: Context, toy_repo: Path, slurm: FakeSlurm, monkeypatch: pytest.MonkeyPatch
) -> None:
    def timed_out(script: str, cwd: Path, *, comment: str | None = None) -> str:
        raise SubmitUnknownError("sbatch timed out after 60s; the job may exist")

    monkeypatch.setattr(slurm_module, "submit", timed_out)
    req = RunRequest(repo=toy_repo, command=[PY, "-c", "pass"], slurm=SlurmDefaults())
    run_id = control.launch_run(ctx, req).run_id
    entry = json.loads(outbox(ctx, run_id).read_text())
    entry["intent_at"] = "2000-01-01T00:00:00+00:00"
    outbox(ctx, run_id).write_text(json.dumps(entry))
    real = slurm_module.find_submitted

    def nothing_found_then_the_node_finishes(comment: str) -> tuple[SlurmJob | None, bool]:
        answer = real(comment)  # (None, True): no job carries the comment ...
        node_end = {"status": RunStatus.FINISHED, "exit_code": 0, "ended_at": utcnow()}
        ctx.store.write_record(ctx.find_record(run_id).model_copy(update=node_end))
        return answer  # ... yet the node ran it and ended (a late accounting record)

    monkeypatch.setattr(slurm_module, "find_submitted", nothing_found_then_the_node_finishes)
    [done] = reconcile(ctx)
    assert done.status == RunStatus.FINISHED
    types = [e.type for e in ctx.events.since(0, limit=10_000) if e.run_id == run_id]
    assert "run.failed" not in types and types.count("run.finished") == 1
    indexed = ctx.index.get_run(run_id)
    assert indexed is not None and indexed.status == RunStatus.FINISHED
    assert not outbox(ctx, run_id).exists()  # dropped only after the node's end was published


def test_repair_runs_leaves_slurm_runs_to_reconcile(ctx: Context) -> None:
    old = utcnow() - timedelta(minutes=2)
    ctx.create_run(
        make_record(
            "slurmq",
            status=RunStatus.QUEUED,
            created_at=old,
            environment_id=ctx.descriptor.environment_id,
            executor=ExecutorInfo(type="slurm", slurm_job_id="1000"),
        )
    )
    ctx.create_run(
        make_record(
            "localq",
            status=RunStatus.QUEUED,
            created_at=old,
            environment_id=ctx.descriptor.environment_id,
        )
    )
    assert [r.run_id for r in control.repair_runs(ctx)] == ["localq"]
    assert ctx.find_record("slurmq").status == RunStatus.QUEUED


def outbox(ctx: Context, run_id: str) -> Path:
    return ctx.layout.home / "slurm" / "outbox" / f"{run_id}.json"


def test_crash_after_sbatch_is_matched_to_its_job(
    ctx: Context, toy_repo: Path, slurm: FakeSlurm, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = slurm_module.submit

    def submit_then_crash(script: str, cwd: Path, *, comment: str | None = None) -> str:
        real(script, cwd, comment=comment)  # SLURM accepted the job ...
        raise Crash  # ... and the env server died before it recorded the id

    monkeypatch.setattr(slurm_module, "submit", submit_then_crash)
    req = RunRequest(repo=toy_repo, command=[PY, "-c", "pass"], slurm=SlurmDefaults())
    with pytest.raises(Crash):
        control.launch_run(ctx, req)
    monkeypatch.setattr(slurm_module, "submit", real)
    [run_id] = list(ctx.index.run_ids())
    stuck = ctx.find_record(run_id)
    assert (stuck.executor.type, stuck.executor.slurm_job_id) == ("slurm", None)
    assert [r.run_id for r in control.repair_runs(ctx)] == []  # not a local orphan
    [found] = reconcile(ctx)
    assert (found.status, found.executor.slurm_job_id) == (RunStatus.QUEUED, "1000")
    assert len(slurm.calls("sbatch")) == 1  # never submitted twice
    assert reconcile(ctx) == []


def test_crash_before_sbatch_fails_the_run_once_the_submitter_is_gone(
    ctx: Context, toy_repo: Path, slurm: FakeSlurm, monkeypatch: pytest.MonkeyPatch
) -> None:
    def crash(script: str, cwd: Path, *, comment: str | None = None) -> str:
        raise Crash

    monkeypatch.setattr(slurm_module, "submit", crash)
    req = RunRequest(repo=toy_repo, command=[PY, "-c", "pass"], slurm=SlurmDefaults())
    with pytest.raises(Crash):
        control.launch_run(ctx, req)
    [run_id] = list(ctx.index.run_ids())
    assert reconcile(ctx) == []  # its submitter (this process) lives: sbatch may still answer
    entry = json.loads(outbox(ctx, run_id).read_text())
    entry["submitter"] = {"pid": dead_pid(), "create_time": None}  # the env server restarted
    outbox(ctx, run_id).write_text(json.dumps(entry))
    assert reconcile(ctx) == []  # still inside the settle window: no conclusion yet
    assert json.loads(outbox(ctx, run_id).read_text())["state"] == "unknown"
    entry = json.loads(outbox(ctx, run_id).read_text())
    entry["intent_at"] = "2000-01-01T00:00:00+00:00"
    outbox(ctx, run_id).write_text(json.dumps(entry))
    [failed] = reconcile(ctx)
    assert failed.status == RunStatus.FAILED
    last = ctx.events.since(0, limit=10_000)[-1]
    assert last.type == "run.failed" and "sbatch never accepted" in last.payload["reason"]
    assert not outbox(ctx, run_id).exists()
    assert slurm.calls("sbatch") == []


def test_a_job_that_ended_before_its_submission_was_recorded_is_published(
    ctx: Context, toy_repo: Path, slurm: FakeSlurm, monkeypatch: pytest.MonkeyPatch
) -> None:
    slurm.set(mode="run")
    real = slurm_module.submit

    def submit_and_let_it_finish(script: str, cwd: Path, *, comment: str | None = None) -> str:
        job_id = real(script, cwd, comment=comment)
        wait_until(lambda: not slurm.job(job_id)["in_queue"])  # a fast child is done first
        return job_id

    monkeypatch.setattr(slurm_module, "submit", submit_and_let_it_finish)
    req = RunRequest(repo=toy_repo, command=[PY, "-c", "pass"], slurm=SlurmDefaults(gpus=0))
    record = control.launch_run(ctx, req)
    indexed = ctx.index.get_run(record.run_id)
    assert indexed is not None and indexed.status == RunStatus.FINISHED  # before any poll
    reconcile(ctx)
    reconcile(ctx)
    types = [e.type for e in ctx.events.since(0, limit=10_000) if e.run_id == record.run_id]
    assert types.count("run.finished") == 1
    assert not outbox(ctx, record.run_id).exists()


def test_a_terminal_run_yaml_indexed_by_another_write_is_still_published(
    ctx: Context, slurm: FakeSlurm
) -> None:
    slurm.add_job("1000", "COMPLETED", node="n1", in_queue=False)
    record = slurm_run(ctx, "r1", job_id="1000")
    ctx.store.write_record(record.model_copy(update={"status": RunStatus.FINISHED, "exit_code": 0}))
    # a tag on the login node reads the node's final run.yaml and indexes it first
    ctx.update_run("r1", "run.tagged", lambda r: r.model_copy(update={"tags": ["x"]}))
    indexed = ctx.index.get_run("r1")
    assert indexed is not None and indexed.status == RunStatus.FINISHED
    [done] = reconcile(ctx)
    assert done.status == RunStatus.FINISHED
    types = [e.type for e in ctx.events.since(0, limit=10_000) if e.run_id == "r1"]
    assert types.count("run.finished") == 1
    assert reconcile(ctx) == [] and not outbox(ctx, "r1").exists()
