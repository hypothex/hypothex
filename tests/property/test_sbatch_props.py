"""Property tests: ``extra`` sbatch options never inject an option or a reserved key."""

import re
import shlex
import string
import subprocess
from pathlib import Path

import pytest
from hypothesis import HealthCheck, assume, example, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from hypothex.core.slurm import SlurmError, render_sbatch, validate_defaults
from hypothex.remote.config import SlurmDefaults, sbatch_option_problem
from tests.factories import make_record

FAST = settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])

# What sbatch itself owns, written out independently of hypothex.remote.config.
OWNED_LONG = ("job-name", "comment", "output", "error", "chdir", "wrap")
REQUEUE_LONG = ("requeue", "no-requeue")
OWNED_SHORT = {"J": "job-name", "o": "output", "e": "error", "D": "chdir"}
NO_ARG_SHORT = set("hHIkOQsuvVW")  # sbatch short options without a required argument
VALUE_CHARS = set(string.ascii_letters + string.digits + "_.:+@/,=-")

nasty = "-=Jjoe DdwW#;&|$`'\"\\\t\n\r\x00*?~!(){}[]<>%^é　 "
prefixes = st.sampled_from(OWNED_LONG + REQUEUE_LONG).flatmap(
    lambda name: st.integers(1, len(name)).map(lambda n: name[:n])
)
items = st.one_of(
    st.text(alphabet=nasty + "abcqos0123", max_size=14),
    st.builds(
        lambda p, v: f"--{p}{v}", prefixes, st.sampled_from(["", "=x", "=a b", "=$(id)", "\n"])
    ),
    st.builds(
        lambda c, v: f"-{c}{v}", st.sampled_from(string.ascii_letters), st.text(nasty, max_size=5)
    ),
    st.builds(
        lambda n, v: f"--{n}={v}",
        st.from_regex(r"[a-z][a-z0-9-]{0,10}", fullmatch=True),
        st.text(nasty + "ab9", max_size=6),
    ),
    st.sampled_from(["--qos=high", "--exclusive", "-pgpu", "--mem=32G", "-HJx", "-Jx", "--job=x"]),
)


def sbatch_sees(item: str) -> list[str]:
    """
    The long option names sbatch would set from one ``#SBATCH`` token.

    A model of getopt_long: a long name may be any unique-or-not prefix (all
    matches are returned), and short options bundle until one takes an argument.
    """
    if item.startswith("--"):
        name = item[2:].split("=", 1)[0]
        known = (*OWNED_LONG, *REQUEUE_LONG, "qos", "exclusive", "mem", "partition")
        return [k for k in known if name and k.startswith(name)] or [f"?{name}"]
    seen = []
    rest = item[1:]
    while rest:
        letter, rest = rest[0], rest[1:]
        seen.append(OWNED_SHORT.get(letter, f"-{letter}"))
        if letter not in NO_ARG_SHORT:
            break  # the rest is this option's argument
    return seen


@FAST
@given(items)
@example("--job-name=x")
@example("-HJx")
@example("--qos=a\n#SBATCH --job-name=y")
@example("--output")
@example("--c")
def test_accepted_items_are_one_harmless_token(item: str) -> None:
    problem = sbatch_option_problem(item)
    if problem is not None:
        assert isinstance(problem, str) and problem
        return
    # one token: the shell, sbatch's line split, and shlex all see the item itself
    assert shlex.split(item) == [item]
    assert item.split() == [item]
    assert item.isascii() and item.isprintable()
    assert set(item) <= VALUE_CHARS
    assert item.startswith("-")
    assert not set(sbatch_sees(item)) & set(OWNED_LONG)


@FAST
@given(prefixes, st.sampled_from(["", "=x", "=1"]))
def test_every_owned_option_and_abbreviation_is_refused(prefix: str, value: str) -> None:
    item = f"--{prefix}{value}"
    owned_hit = any(name.startswith(prefix) for name in OWNED_LONG)
    assert (sbatch_option_problem(item) is not None) == owned_hit
    if not owned_hit:  # a requeue option: the model allows it, render_sbatch refuses it
        with pytest.raises(SlurmError, match="requeue"):
            validate_defaults(SlurmDefaults(extra=[item]))


@FAST
@given(st.sampled_from(sorted(OWNED_SHORT)), st.text(alphabet="abcxyz019=", max_size=4))
def test_owned_short_letters_are_refused_with_any_value(letter: str, value: str) -> None:
    assert sbatch_option_problem(f"-{letter}{value}") is not None


@FAST
@given(st.sampled_from(sorted(NO_ARG_SHORT)), st.text(alphabet="Jabcoe1", min_size=1, max_size=4))
def test_flags_never_bundle_more_options(flag: str, rest: str) -> None:
    assert sbatch_option_problem(f"-{flag}{rest}") is not None


# render_sbatch ----------------------------------------------------------------------------
safe_extra = items.filter(lambda i: sbatch_option_problem(i) is None)
slurm_name = st.one_of(
    st.none(),
    st.from_regex(r"[A-Za-z0-9_][A-Za-z0-9_.,-]{0,8}", fullmatch=True),
    st.text(alphabet="ab_-.,9 $\n", min_size=1, max_size=6),
)
slurm_time = st.one_of(
    st.sampled_from(["02:00:00", "30", "1-00:00:00", "10:00"]),
    st.text(alphabet="0123456789:- \n", max_size=10),
)
run_ids = st.from_regex(r"[a-z0-9][a-z0-9_.-]{0,20}", fullmatch=True)


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    st.lists(safe_extra, max_size=4),
    slurm_name,
    slurm_name,
    slurm_time,
    st.integers(0, 8),
    run_ids,
)
def test_rendered_script_owns_job_identity_exactly_once(
    extra: list[str],
    partition: str | None,
    account: str | None,
    time: str,
    gpus: int,
    run_id: str,
) -> None:
    try:
        defaults = SlurmDefaults(partition=partition, account=account, time=time, extra=extra)
    except ValidationError:
        return
    record = make_record(run_id, gpus_requested=gpus)
    try:
        script = render_sbatch(record, defaults, Path("/h"))
    except SlurmError as exc:
        assert "requeue" in str(exc) or "characters" in str(exc)
        return
    lines = script.split("\n")
    directives = [line.removeprefix("#SBATCH ") for line in lines if line.startswith("#SBATCH")]
    assert lines[0] == "#!/bin/bash" and script.endswith("\n")
    assert all(len(line.split()) == 2 for line in lines if line.startswith("#SBATCH"))
    assert directives[: len(directives) - len(extra)][:3] == [
        f"--job-name=hx-{run_id}",
        f"--output=/h/store/toy/runs/{run_id}/logs/slurm-%j.out",
        "--no-requeue",
    ]
    assert directives[len(directives) - len(extra) :] == extra
    seen = [name for d in directives for name in sbatch_sees(d)]
    for owned in ("job-name", "output", "no-requeue"):
        assert seen.count(owned) == 1
    for owned in ("comment", "error", "chdir", "wrap", "requeue"):
        assert owned not in seen
    for value in (partition, account, time):
        if value is not None:
            assert re.fullmatch(r"[A-Za-z0-9_.:+@/,-]+", value)


home_paths = st.text(
    alphabet=string.ascii_letters + string.digits + "/._-$'\"`\\;&|*?~!()<>{}[]#%^=:,@+é",
    min_size=1,
    max_size=24,
).map(lambda s: "/" + s)


@settings(max_examples=25, deadline=None)
@given(home_paths, run_ids)
@example("/h'; rm -rf ~; '", "r1")
@example("/$(id)`id`", "r.1")
def test_exec_line_survives_the_shell_unchanged(home: str, run_id: str) -> None:
    assume(not any(ch.isspace() for ch in home))
    script = render_sbatch(make_record(run_id), SlurmDefaults(), Path(home))
    exec_line = next(line for line in script.splitlines() if line.startswith("exec "))
    args = shlex.split(exec_line.removeprefix("exec "))
    assert args[1:] == [
        "-m",
        "hypothex.cli.main",
        "--home",
        str(Path(home)),
        "run",
        "--child",
        run_id,
    ]
    # the real shell tokenizes it the same way, and runs nothing else
    probe = "printf '%s\\0' " + exec_line.removeprefix("exec ")
    out = subprocess.run(["sh", "-c", probe], capture_output=True, check=True).stdout
    assert out.decode().split("\0")[:-1] == args


@settings(max_examples=40, deadline=None)
@given(st.text(alphabet=" \t\n/ab", min_size=1, max_size=8))
def test_home_with_whitespace_is_refused(home: str) -> None:
    assume(any(ch.isspace() for ch in home))
    with pytest.raises(SlurmError, match="whitespace"):
        render_sbatch(make_record("r1"), SlurmDefaults(), Path("/") / home)
