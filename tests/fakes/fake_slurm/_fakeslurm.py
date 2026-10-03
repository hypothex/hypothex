"""
State and behaviour shared by the fake SLURM commands (tests only).

Never talks to a real cluster. State lives in the JSON file named by
``HYPOTHEX_FAKE_SLURM_STATE``::

    {"next_id": 1000, "mode": "hold", "user": null, "fail": {"squeue": "message"},
     "accounting_flags": "job_comment", "sbatch_signal": null,
     "jobs": {"1000": {"state": "PENDING", "node": null, "exit": "0:0",
                       "in_queue": true, "in_sacct": true, "name": "hx-...",
                       "output": "/abs/slurm-%j.out", "gpus": 1, "directives": {},
                       "script": "...", "cwd": "/abs", "pgid": null}},
     "calls": [["sbatch", "--parsable"]]}

``mode: hold`` keeps submitted jobs PENDING until a test edits the state.
``mode: run`` starts each job at once on ``fake-node1`` in a detached process
and marks it COMPLETED or FAILED when its script exits. ``fail`` maps a
command name to a stderr message; that command then exits 1.
``accounting_flags`` is what ``scontrol show config`` reports as
``AccountingStoreFlags`` (SLURM stores job comments only with
``job_comment``). ``sbatch_signal`` makes ``sbatch`` kill itself with that
signal right after it queued the job, before it prints the id. Runs on any
``python3`` >= 3.9 (stdlib only).
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

FAKE_NODE = "fake-node1"
SQUEUE_FORMAT = "%i|%T|%N"
SACCT_FORMAT = "JobID,State,ExitCode,NodeList"
_DIRECTIVE = re.compile(r"^#SBATCH\s+--([A-Za-z-]+)=(.*)$")


def _state_path() -> Path:
    raw = os.environ.get("HYPOTHEX_FAKE_SLURM_STATE")
    if not raw:
        sys.stderr.write("fake slurm: HYPOTHEX_FAKE_SLURM_STATE is not set\n")
        raise SystemExit(2)
    return Path(raw)


@contextlib.contextmanager
def locked_state() -> Iterator[dict[str, Any]]:
    """Yield the state under an exclusive lock; write it back on normal exit."""
    path = _state_path()
    with open(path.with_name(path.name + ".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.loads(path.read_text()) if path.is_file() else {}
        state.setdefault("next_id", 1000)
        state.setdefault("mode", "hold")
        state.setdefault("user", None)
        state.setdefault("fail", {})
        state.setdefault("accounting_flags", "job_comment")
        state.setdefault("sbatch_signal", None)
        state.setdefault("jobs", {})
        state.setdefault("calls", [])
        yield state
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        os.replace(tmp, path)


def _begin(name: str, argv: list[str]) -> None:
    """Record the call; exit 1 with the configured message if ``name`` must fail."""
    with locked_state() as state:
        state["calls"].append([name, *argv])
        message = state["fail"].get(name)
    if message:
        sys.stderr.write(message + "\n")
        raise SystemExit(1)


def _option(argv: list[str], name: str) -> str | None:
    for i, arg in enumerate(argv):
        if arg.startswith(name + "="):
            return arg.split("=", 1)[1]
        if arg == name and i + 1 < len(argv):
            return argv[i + 1]
    return None


# sbatch options that take a value, as (long name, short name). Both ``--name=value``
# and ``--name value`` work for these. Any other ``--name=value`` is kept as given.
_SBATCH_VALUE_OPTIONS = {
    "--job-name": "-J",
    "--output": "-o",
    "--comment": "",
    "--time": "-t",
    "--gpus": "-G",
    "--partition": "-p",
    "--account": "-A",
}


def _parse_sbatch(argv: list[str]) -> tuple[dict[str, str], bool, list[str]] | None:
    """Split sbatch argv into (options, parsable, files); None when an argument is unsupported."""
    shorts = {short: long for long, short in _SBATCH_VALUE_OPTIONS.items() if short}
    options: dict[str, str] = {}
    files: list[str] = []
    parsable = False
    i = 0
    while i < len(argv):
        arg = argv[i]
        i += 1
        if arg == "--parsable":
            parsable = True
        elif arg.startswith("--") and "=" in arg:
            key, value = arg[2:].split("=", 1)
            options[key] = value
        elif arg in _SBATCH_VALUE_OPTIONS or arg in shorts:
            if i >= len(argv):
                return None
            options[(arg if arg.startswith("--") else shorts[arg])[2:]] = argv[i]
            i += 1
        elif arg.startswith("-"):
            return None
        else:
            files.append(arg)
    if len(files) > 1:
        return None
    return options, parsable, files


def sbatch(argv: list[str]) -> int:
    """
    Fake ``sbatch``: queue a job. Exit 2 on any argument it does not support.

    Supported: ``--parsable``; ``--job-name``, ``--output``, ``--comment``, ``--time``,
    ``--gpus``, ``--partition``, ``--account`` (``--opt=v`` or ``--opt v``, short forms
    ``-J -o -t -G -p -A``); any other ``--opt=v``; at most one script file (stdin when none).
    Command-line options override ``#SBATCH`` lines, as in SLURM.
    """
    _begin("sbatch", argv)
    parsed = _parse_sbatch(argv)
    if parsed is None:
        sys.stderr.write(f"fake sbatch: unsupported arguments {argv}\n")
        return 2
    options, parsable, files = parsed
    script = Path(files[0]).read_text() if files else sys.stdin.read()
    directives: dict[str, str] = {}
    for line in script.splitlines():
        match = _DIRECTIVE.match(line.strip())
        if match:
            directives[match.group(1)] = match.group(2)
    directives.update(options)
    with locked_state() as state:
        job_id = str(state["next_id"])
        state["next_id"] += 1
        state["jobs"][job_id] = {
            "state": "PENDING",
            "node": None,
            "exit": "0:0",
            "in_queue": True,
            "in_sacct": True,
            "name": directives.get("job-name", "sbatch"),
            "comment": directives.get("comment", ""),
            "output": directives.get("output", os.path.join(os.getcwd(), "slurm-%j.out")),
            "gpus": int(directives.get("gpus", "0").split(":")[-1]),
            "directives": directives,
            "script": script,
            "cwd": os.getcwd(),
            "pgid": None,
        }
        mode = state["mode"]
        die_by = state["sbatch_signal"]
    if mode == "run":
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "runjob", job_id],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    if die_by:  # accepted, but the caller never hears the job id
        sys.stdout.flush()
        os.kill(os.getpid(), getattr(signal, f"SIG{die_by}"))
    print(job_id if parsable else f"Submitted batch job {job_id}")
    return 0


def runjob(job_id: str) -> int:
    """Run a submitted job's script on the fake node and record how it ended."""
    path = _state_path()
    with locked_state() as state:
        job = state["jobs"][job_id]
        if job["state"] != "PENDING":
            return 0
        script_file = path.with_name(f"job-{job_id}.sh")
        script_file.write_text(job["script"])
        env = dict(os.environ, SLURM_JOB_ID=job_id, SLURMD_NODENAME=FAKE_NODE)
        env.pop("CUDA_VISIBLE_DEVICES", None)
        if job["gpus"] > 0:
            env["CUDA_VISIBLE_DEVICES"] = ",".join(str(i) for i in range(job["gpus"]))
        out = open(job["output"].replace("%j", job_id), "ab")  # noqa: SIM115 - closed below
        proc = subprocess.Popen(
            ["bash", str(script_file)],
            cwd=job["cwd"],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        job.update(state="RUNNING", node=FAKE_NODE, pgid=proc.pid)
    rc = proc.wait()
    out.close()
    with locked_state() as state:
        job = state["jobs"][job_id]
        if job["state"] == "RUNNING":
            job["state"] = "COMPLETED" if rc == 0 else "FAILED"
            job["exit"] = f"{rc}:0" if rc >= 0 else f"0:{-rc}"
            job["in_queue"] = False
    return 0


def _parse_scancel(argv: list[str]) -> tuple[dict[str, str], list[str]] | None:
    """Split scancel argv into (filters, job ids); None when an argument is unsupported."""
    filters: dict[str, str] = {}
    ids: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        i += 1
        if arg.startswith("--"):
            key, sep, value = arg[2:].partition("=")
            if key not in ("state", "user", "name"):
                return None
            if not sep:
                if i >= len(argv):
                    return None
                value = argv[i]
                i += 1
            filters[key] = value
        elif arg.startswith("-"):
            return None
        else:
            ids.append(arg)
    if not ids and not filters:
        return None
    return filters, ids


def scancel(argv: list[str]) -> int:
    """
    Fake ``scancel``: cancel queued jobs, SIGTERM running ones. Exit 2 on unsupported arguments.

    Supported: ``<id>...`` and the filters ``--state=S[,S]``, ``--user=U``, ``--name=N``
    (``--opt=v`` or ``--opt v``). With filters and no ids, every queued job that matches is
    cancelled (none matching is not an error). With ids, an unknown or finished id fails.
    At least one id or filter is required.
    """
    _begin("scancel", argv)
    parsed = _parse_scancel(argv)
    if parsed is None:
        sys.stderr.write(f"fake scancel: unsupported arguments {argv}\n")
        return 2
    filters, ids = parsed
    states = {s.upper() for s in filters["state"].split(",")} if "state" in filters else None
    with locked_state() as state:
        strict = bool(ids)
        if not ids:
            ids = [job_id for job_id, job in state["jobs"].items() if job["in_queue"]]
        for job_id in ids:
            job = state["jobs"].get(job_id)
            if job is None or not job["in_queue"]:
                if strict:
                    sys.stderr.write(
                        f"scancel: error: Kill job error on job id {job_id}: "
                        "Invalid job id specified\n"
                    )
                    return 1
                continue
            if (
                (states is not None and job["state"] not in states)
                or ("name" in filters and job["name"] != filters["name"])
                or (
                    "user" in filters
                    and state["user"] is not None
                    and filters["user"] != state["user"]
                )
            ):
                continue
            job.update(state="CANCELLED", exit="0:15", in_queue=False)
            if job.get("pgid"):
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(job["pgid"], signal.SIGTERM)
    return 0


def squeue(argv: list[str]) -> int:
    """Fake ``squeue --noheader [--user=U] [--name=N] --format=%i|%T|%N[|%k]``: queued jobs."""
    _begin("squeue", argv)
    fmt = _option(argv, "--format")
    if "--noheader" not in argv or fmt not in (SQUEUE_FORMAT, SQUEUE_FORMAT + "|%k"):
        sys.stderr.write(f"fake squeue: unsupported arguments {argv}\n")
        return 2
    user = _option(argv, "--user")
    name = _option(argv, "--name")
    with locked_state() as state:
        jobs = state["jobs"]
        owner = state["user"]
    for job_id, job in sorted(jobs.items(), key=lambda kv: int(kv[0])):
        if not job["in_queue"] or (name is not None and job["name"] != name):
            continue
        if user is None or owner is None or user == owner:
            row = f"{job_id}|{job['state']}|{job['node'] or ''}"
            print(row + f"|{job.get('comment', '')}" if fmt.endswith("|%k") else row)
    return 0


def sacct(argv: list[str]) -> int:
    """Fake ``sacct -X --noheader --parsable2 --format=...[,Comment] [--jobs=a,b | --name=N]``."""
    _begin("sacct", argv)
    fmt = _option(argv, "--format")
    if not {"-X", "--noheader", "--parsable2"} <= set(argv) or (
        fmt not in (SACCT_FORMAT, SACCT_FORMAT + ",Comment")
    ):
        sys.stderr.write(f"fake sacct: unsupported arguments {argv}\n")
        return 2
    with locked_state() as state:
        jobs = state["jobs"]
    ordered = [job_id for job_id, _ in sorted(jobs.items(), key=lambda kv: int(kv[0]))]
    name = _option(argv, "--name")
    listed = _option(argv, "--jobs")
    if name is not None:
        wanted = [job_id for job_id in ordered if jobs[job_id]["name"] == name]
    elif listed is not None:
        wanted = listed.split(",")
    else:
        wanted = ordered  # no filter: every job (of the --starttime window)
    for job_id in wanted:
        job = jobs.get(job_id)
        if job is None or not job["in_sacct"]:
            continue
        row = f"{job_id}|{job['state']}|{job['exit']}|{job['node'] or 'None assigned'}"
        print(row + f"|{job.get('comment', '')}" if fmt.endswith(",Comment") else row)
    return 0


def scontrol(argv: list[str]) -> int:
    """Fake ``scontrol show config``: the accounting flags (other keys are fixed)."""
    _begin("scontrol", argv)
    if argv != ["show", "config"]:
        sys.stderr.write(f"fake scontrol: unsupported arguments {argv}\n")
        return 2
    with locked_state() as state:
        flags = state["accounting_flags"] or "(null)"
    print("Configuration data as of 2026-10-03T09:00:00")
    print("AccountingStorageType   = accounting_storage/slurmdbd")
    print(f"AccountingStoreFlags    = {flags}")
    print("ClusterName             = fake")
    return 0


if __name__ == "__main__":
    raise SystemExit(runjob(sys.argv[2]))
