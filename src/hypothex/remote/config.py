"""The hub's environments file, ``<home>/environments.yaml``: one entry per host."""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from hypothex.core.config import NAME_PATTERN, YAML_CYCLE, has_cycle, scan_yaml
from hypothex.core.errors import ConfigError
from hypothex.core.fsutil import read_yaml, write_yaml
from hypothex.core.layout import Layout

HostKind = Literal["ssh", "slurm"]
Route = Literal["ssh", "url", "local"]

HOST_NAME = r"^[a-z0-9][a-z0-9_-]{0,31}$"
"""Pattern for host names; ``local`` is reserved for the hub itself."""
RESERVED_HOST_NAMES = frozenset({"local"})
ENVIRONMENTS_FILENAME = "environments.yaml"
SSH_ALIAS = r"^[A-Za-z0-9_.@][A-Za-z0-9_.@:-]{0,254}$"
"""An ``ssh`` destination: a ``Host`` from ``~/.ssh/config`` or ``user@host``; never ``-...``."""
REMOTE_PATH = r"^(~|~/[A-Za-z0-9_.+@/-]*|/[A-Za-z0-9_.+@/-]*)$"
"""A path on a host: absolute or under ``~``, shell-safe characters only."""
SLURM_NAME = r"^[A-Za-z0-9_][A-Za-z0-9_.,-]*$"
SLURM_TIME = r"^(\d+-)?\d+(:\d{2}){0,2}$"
SBATCH_VALUE = r"[A-Za-z0-9_.:+@/,=-]+"
"""Characters an ``extra`` option value may hold (nothing a shell or sbatch would split)."""
SBATCH_LONG = re.compile(rf"--([a-z][a-z0-9-]*)(?:={SBATCH_VALUE})?")
SBATCH_SHORT = re.compile(rf"-([A-Za-z])({SBATCH_VALUE})?")
RESERVED_SBATCH_OPTIONS = ("job-name", "comment", "output", "error", "chdir", "wrap")
"""``sbatch`` options Hypothex owns: the job's identity, its log files, and its command."""
RESERVED_SBATCH_SHORT = {"J": "job-name", "o": "output", "e": "error", "D": "chdir"}
SBATCH_SHORT_FLAGS = frozenset("hHIkOQsuvVW")
"""Short options that take no value (or only an optional one): text after them could be
read as more bundled options (``-HJx`` is ``-H -J x``)."""


def sbatch_option_problem(item: str) -> str | None:
    """
    Say why ``item`` cannot be an ``extra`` sbatch option, or return None.

    An item is exactly one option token (``shlex.split(item) == [item]``):
    ``--name``, ``--name=value``, ``-X``, or ``-Xvalue``, values in
    ``SBATCH_VALUE`` only. It never sets an option Hypothex owns, in any form:
    a long name, any prefix of it (sbatch accepts unique abbreviations, so
    ``--job=x`` is ``--job-name=x``), or its short letter.

    Parameters
    ----------
    item : str
        One ``extra`` item.

    Returns
    -------
    str or None
        The reason it is refused, or None when it is one safe option.

    Examples
    --------
    >>> sbatch_option_problem("--qos=high") is None
    True
    >>> sbatch_option_problem("-Jx")
    "'-Jx' sets --job-name, which Hypothex sets itself (it identifies the job)"
    >>> sbatch_option_problem("--qos=normal --job-name=c")
    "'--qos=normal --job-name=c' must be exactly one option token (one option per item)"
    """
    try:
        tokens = shlex.split(item)
    except ValueError:
        tokens = []
    if tokens != [item]:
        return f"{item!r} must be exactly one option token (one option per item)"
    taken: str | None = None
    long = SBATCH_LONG.fullmatch(item)
    if long is not None:
        name = long.group(1)
        taken = next((r for r in RESERVED_SBATCH_OPTIONS if r.startswith(name)), None)
    else:
        short = SBATCH_SHORT.fullmatch(item)
        if short is None:
            return (
                f"{item!r} is not an sbatch option: use --name, --name=value, -X, or -Xvalue "
                "with letters, digits, and _ . : + @ / , = - only"
            )
        letter, value = short.group(1), short.group(2)
        taken = RESERVED_SBATCH_SHORT.get(letter)
        if taken is None and value and letter in SBATCH_SHORT_FLAGS:
            return f"{item!r} bundles short options; give each option as its own item"
    if taken is not None:
        return f"{item!r} sets --{taken}, which Hypothex sets itself (it identifies the job)"
    return None


class SlurmDefaults(BaseModel):
    """
    Default ``sbatch`` resources for a SLURM host.

    ``time`` uses SLURM's formats (``MM``, ``HH:MM:SS``, ``D-HH:MM:SS``).
    ``extra`` holds further ``sbatch`` options, exactly one option token per
    item (``--qos=high``, ``--exclusive``, ``-pgpu``); options Hypothex sets
    itself are refused (``sbatch_option_problem``).

    Examples
    --------
    >>> SlurmDefaults(partition="gpu", time="1-00:00:00", extra=["--qos=high"]).gpus
    1
    """

    model_config = ConfigDict(extra="forbid")

    partition: str | None = Field(default=None, pattern=SLURM_NAME)
    account: str | None = Field(default=None, pattern=SLURM_NAME)
    time: str = Field(default="02:00:00", pattern=SLURM_TIME)
    gpus: int = Field(default=1, ge=0)
    extra: list[str] = Field(default_factory=list)

    @field_validator("extra")
    @classmethod
    def _one_safe_option_each(cls, extra: list[str]) -> list[str]:
        for item in extra:
            problem = sbatch_option_problem(item)
            if problem is not None:
                raise ValueError(problem)
        return extra


class HostSpec(BaseModel):
    """
    One host in ``environments.yaml``.

    ``route`` is how the hub reaches the host's env server: ``ssh`` (bootstrap
    and tunnel over ``ssh_alias``), ``url`` (an env server already listening
    at ``url``; tests and phase 3), or ``local`` (this machine). ``kind`` says
    how the env server executes runs. ``projects`` maps a project name to its
    repo path on the host.

    Examples
    --------
    >>> spec = HostSpec(route="ssh", ssh_alias="gpu1", projects={"toy": "~/code/toy"})
    >>> spec.kind, spec.home
    ('ssh', '~/.hypothex')
    """

    model_config = ConfigDict(extra="forbid")

    route: Route
    kind: HostKind = "ssh"
    ssh_alias: str | None = Field(default=None, pattern=SSH_ALIAS)
    url: str | None = Field(default=None, pattern=r"^https?://\S+$")
    home: str = Field(default="~/.hypothex", pattern=REMOTE_PATH)
    usd_per_gpu_hour: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    slurm: SlurmDefaults | None = None
    projects: dict[str, Annotated[str, Field(pattern=REMOTE_PATH)]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_route_and_kind(self) -> HostSpec:
        """Require the fields each route and kind needs; check project names."""
        if self.route == "ssh" and self.ssh_alias is None:
            raise ValueError("route ssh needs ssh_alias (a Host from ~/.ssh/config)")
        if self.route == "url" and self.url is None:
            raise ValueError("route url needs url")
        if self.kind == "slurm" and self.slurm is None:
            raise ValueError("kind slurm needs a slurm block (partition, time, gpus)")
        if self.kind != "slurm" and self.slurm is not None:
            raise ValueError("a slurm block is only allowed with kind: slurm")
        bad = sorted(p for p in self.projects if not re.fullmatch(NAME_PATTERN, p))
        if bad:
            raise ValueError(f"project names must match {NAME_PATTERN}: {', '.join(bad)}")
        return self


class EnvironmentsFile(BaseModel):
    """
    Parsed ``environments.yaml``: host name to host spec.

    Examples
    --------
    >>> EnvironmentsFile.model_validate({"environments": None}).environments
    {}
    """

    model_config = ConfigDict(extra="forbid")

    stale_banner_hours: float = Field(24.0, gt=0, allow_inf_nan=False)
    """Hours a host may be unreachable before the UI shows a banner (spec 5.6)."""
    environments: dict[str, HostSpec] = Field(default_factory=dict)

    @field_validator("environments", mode="before")
    @classmethod
    def _none_is_empty(cls, value: object) -> object:
        """Read an empty ``environments:`` key as no hosts."""
        return {} if value is None else value

    @field_validator("environments")
    @classmethod
    def _check_names(cls, value: dict[str, HostSpec]) -> dict[str, HostSpec]:
        """Host names match ``HOST_NAME`` and are not reserved."""
        for name in value:
            if name in RESERVED_HOST_NAMES:
                raise ValueError(f"host name {name!r} is reserved for the hub")
            if not re.fullmatch(HOST_NAME, name):
                raise ValueError(f"host name {name!r} must match {HOST_NAME}")
        return value


def environments_path(layout: Layout) -> Path:
    """
    Return the path of the hub's environments file.

    Parameters
    ----------
    layout : Layout
        Hub home layout.

    Returns
    -------
    Path
        ``<home>/environments.yaml``.

    Examples
    --------
    >>> environments_path(Layout(Path("/h"))).as_posix()
    '/h/environments.yaml'
    """
    return layout.home / ENVIRONMENTS_FILENAME


def load_hosts(layout: Layout) -> EnvironmentsFile:
    """
    Load and validate ``<home>/environments.yaml``.

    A missing or empty file means no hosts. The text is pre-scanned like
    ``hypothex.yaml`` (``scan_yaml``): nesting deeper than ``YAML_MAX_DEPTH``,
    more than ``YAML_MAX_EVENTS`` events, and aliases that form a cycle are
    errors with their line. Other anchors and aliases are allowed (for
    example shared ``slurm`` defaults).

    Parameters
    ----------
    layout : Layout
        Hub home layout.

    Returns
    -------
    EnvironmentsFile
        The hosts.

    Raises
    ------
    ConfigError
        If the file is not valid YAML, too deep or too large, has an alias
        cycle, or does not match the schema. The message starts with the path.

    Examples
    --------
    >>> load_hosts(Layout(Path("/nonexistent"))).environments
    {}
    """
    path = environments_path(layout)
    if not path.is_file():
        return EnvironmentsFile()
    try:
        scan = scan_yaml(path.read_text(encoding="utf-8"))
        data = None if scan.problem is not None else read_yaml(path)
    except (ValueError, yaml.YAMLError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    if scan.problem is not None:
        message, line = scan.problem
        raise ConfigError(f"{path}: {message} (line {line})")
    if has_cycle(data):
        where = "" if scan.cycle is None else f" (line {scan.cycle})"
        raise ConfigError(f"{path}: {YAML_CYCLE}{where}")
    try:
        return EnvironmentsFile.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def save_hosts(layout: Layout, hosts: EnvironmentsFile) -> None:
    """
    Atomically write ``<home>/environments.yaml``.

    Fields left at their defaults are omitted, so the file stays short.
    Comments in a hand-edited file are not kept. The text is validated again
    first (``model_copy(update=...)`` skips validation), so a file that
    ``load_hosts`` would reject is never written.

    Parameters
    ----------
    layout : Layout
        Hub home layout; the home directory is created if missing.
    hosts : EnvironmentsFile
        Hosts to write.

    Raises
    ------
    ConfigError
        The hosts do not match the schema; the file is left unchanged.

    Examples
    --------
    >>> import tempfile
    >>> lay = Layout(Path(tempfile.mkdtemp()))
    >>> gpu1 = HostSpec(route="ssh", ssh_alias="g1")
    >>> save_hosts(lay, EnvironmentsFile(environments={"gpu1": gpu1}))
    >>> load_hosts(lay).environments["gpu1"].ssh_alias
    'g1'
    """
    data = hosts.model_dump(mode="json", exclude_defaults=True)
    try:
        EnvironmentsFile.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"invalid hosts, not saved: {exc}") from exc
    write_yaml(environments_path(layout), data)
