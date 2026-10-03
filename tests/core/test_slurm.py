import getpass
import json
import os
import shlex
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from hypothex.core.slurm import (
    SlurmError,
    SlurmJob,
    SlurmTimeout,
    SubmitUnknownError,
    cancel,
    comment_accounting,
    find_submitted,
    is_finished,
    lost_reason,
    poll,
    render_sbatch,
    submit,
)
from hypothex.remote.config import SlurmDefaults
from tests.factories import make_record

FAKE_SLURM = Path(__file__).resolve().parents[1] / "fakes" / "fake_slurm"
PY = sys.executable


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
