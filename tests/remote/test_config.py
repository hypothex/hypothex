from pathlib import Path

import pytest
from pydantic import ValidationError

from hypothex.core.errors import ConfigError
from hypothex.core.layout import Layout
from hypothex.remote.config import (
    EnvironmentsFile,
    HostSpec,
    SlurmDefaults,
    environments_path,
    load_hosts,
    save_hosts,
)

SPEC_EXAMPLE = """\
environments:
  gpu1:
    route: ssh
    ssh_alias: SV-a100-retrollm2
    kind: ssh
    home: ~/.hypothex
    usd_per_gpu_hour: 2.10
    projects: {deepretro: /home/sv/code/DeepRetro}
  cluster:
    route: ssh
    ssh_alias: login-node
    kind: slurm
    home: /scratch/sv/hx
    slurm: {partition: gpu, account: null, time: "02:00:00", gpus: 1}
  fake:
    route: url
    url: http://127.0.0.1:7801
"""


def write(layout: Layout, text: str) -> None:
    layout.home.mkdir(parents=True, exist_ok=True)
    environments_path(layout).write_text(text)


def test_environments_path_is_in_home(tmp_path: Path) -> None:
    assert environments_path(Layout(tmp_path)) == tmp_path / "environments.yaml"


def test_missing_file_means_no_hosts(tmp_path: Path) -> None:
    assert load_hosts(Layout(tmp_path)) == EnvironmentsFile()


@pytest.mark.parametrize("text", ["", "environments:\n", "environments: {}\n"])
def test_empty_file_or_key_means_no_hosts(tmp_path: Path, text: str) -> None:
    layout = Layout(tmp_path)
    write(layout, text)
    assert load_hosts(layout).environments == {}


def test_spec_example_loads(tmp_path: Path) -> None:
    layout = Layout(tmp_path)
    write(layout, SPEC_EXAMPLE)
    hosts = load_hosts(layout).environments
    assert list(hosts) == ["gpu1", "cluster", "fake"]
    gpu1 = hosts["gpu1"]
    assert (gpu1.route, gpu1.kind, gpu1.ssh_alias) == ("ssh", "ssh", "SV-a100-retrollm2")
    assert gpu1.usd_per_gpu_hour == 2.10 and gpu1.slurm is None
    assert gpu1.projects == {"deepretro": "/home/sv/code/DeepRetro"}
    cluster = hosts["cluster"]
    assert cluster.kind == "slurm" and cluster.home == "/scratch/sv/hx"
    assert cluster.slurm == SlurmDefaults(partition="gpu", time="02:00:00", gpus=1)
    assert cluster.usd_per_gpu_hour is None
    assert hosts["fake"].url == "http://127.0.0.1:7801" and hosts["fake"].home == "~/.hypothex"


def test_save_then_load_round_trips(tmp_path: Path) -> None:
    layout = Layout(tmp_path / "hub")
    hosts = EnvironmentsFile(
        environments={
            "gpu1": HostSpec(
                route="ssh", ssh_alias="gpu1", usd_per_gpu_hour=1.25, projects={"toy": "~/toy"}
            ),
            "cluster": HostSpec(
                route="ssh",
                ssh_alias="login",
                kind="slurm",
                slurm=SlurmDefaults(),
            ),
        }
    )
    save_hosts(layout, hosts)
    assert load_hosts(layout) == hosts


def test_save_omits_defaults(tmp_path: Path) -> None:
    layout = Layout(tmp_path)
    save_hosts(
        layout, EnvironmentsFile(environments={"gpu1": HostSpec(route="ssh", ssh_alias="g1")})
    )
    assert environments_path(layout).read_text() == (
        "environments:\n  gpu1:\n    route: ssh\n    ssh_alias: g1\n"
    )


def test_save_replaces_the_file_atomically(tmp_path: Path) -> None:
    layout = Layout(tmp_path)
    write(layout, SPEC_EXAMPLE)
    save_hosts(layout, EnvironmentsFile())
    assert load_hosts(layout).environments == {}
    assert [p.name for p in tmp_path.iterdir()] == ["environments.yaml"]


@pytest.mark.parametrize(
    "update",
    [{"projects": {"toy": "relative/path"}}, {"projects": {"bad name": "/srv/x"}}],
)
def test_save_refuses_hosts_that_would_not_load(tmp_path: Path, update: dict) -> None:
    # model_copy(update=...) skips validation; save_hosts must not write what
    # load_hosts rejects, or every later host command breaks
    layout = Layout(tmp_path)
    good = HostSpec(route="ssh", ssh_alias="g1", projects={"toy": "/srv/toy"})
    save_hosts(layout, EnvironmentsFile(environments={"gpu1": good}))
    bad = EnvironmentsFile().model_copy(
        update={"environments": {"gpu1": good.model_copy(update=update)}}
    )
    with pytest.raises(ConfigError, match="gpu1"):
        save_hosts(layout, bad)
    assert load_hosts(layout).environments["gpu1"].projects == {"toy": "/srv/toy"}


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ({"route": "ssh"}, "route ssh needs ssh_alias"),
        ({"route": "url"}, "route url needs url"),
        ({"route": "ssh", "ssh_alias": "a", "kind": "slurm"}, "kind slurm needs a slurm block"),
        (
            {"route": "ssh", "ssh_alias": "a", "slurm": {"partition": "gpu"}},
            "only allowed with kind: slurm",
        ),
        ({"route": "ssh", "ssh_alias": "a", "projects": {"Bad Name": "~/x"}}, "project names"),
        ({"route": "ssh", "ssh_alias": "a", "workdir": "/x"}, "Extra inputs are not permitted"),
    ],
)
def test_host_spec_rules(spec: dict, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        HostSpec.model_validate(spec)


@pytest.mark.parametrize(
    "alias", ["-oProxyCommand=touch /tmp/pwned", "gpu 1", "gpu1;id", "", "a\nb"]
)
def test_ssh_alias_cannot_inject_options_or_shell(alias: str) -> None:
    with pytest.raises(ValidationError):
        HostSpec(route="ssh", ssh_alias=alias)


@pytest.mark.parametrize("alias", ["gpu1", "SV-a100-retrollm2", "sv@10.0.0.5", "login.hpc.edu"])
def test_ssh_alias_accepts_hosts_and_user_at_host(alias: str) -> None:
    assert HostSpec(route="ssh", ssh_alias=alias).ssh_alias == alias


@pytest.mark.parametrize("home", ["~", "~/.hypothex", "/scratch/sv/hx", "/home/sv/hx/"])
def test_home_accepts_absolute_and_tilde_paths(home: str) -> None:
    assert HostSpec(route="ssh", ssh_alias="a", home=home).home == home


@pytest.mark.parametrize("home", ["rel/path", "~/a b", "/x;rm -rf ~", "$HOME/hx", "~other/hx"])
def test_home_rejects_relative_and_shell_unsafe_paths(home: str) -> None:
    with pytest.raises(ValidationError):
        HostSpec(route="ssh", ssh_alias="a", home=home)


def test_project_paths_use_the_same_rule() -> None:
    with pytest.raises(ValidationError):
        HostSpec(route="ssh", ssh_alias="a", projects={"toy": "code/toy"})


@pytest.mark.parametrize("rate", [-0.5, float("inf"), float("nan")])
def test_rate_must_be_finite_and_not_negative(rate: float) -> None:
    with pytest.raises(ValidationError):
        HostSpec(route="ssh", ssh_alias="a", usd_per_gpu_hour=rate)


def test_url_must_be_http() -> None:
    assert HostSpec(route="url", url="https://lab.ts.net:7777").url == "https://lab.ts.net:7777"
    with pytest.raises(ValidationError):
        HostSpec(route="url", url="ftp://x")


@pytest.mark.parametrize("time", ["30", "02:00:00", "1-12:00:00", "2-06", "90:00"])
def test_slurm_time_formats(time: str) -> None:
    assert SlurmDefaults(time=time).time == time


@pytest.mark.parametrize("time", ["2h", "", "1-", "02:00:00\n"])
def test_slurm_time_rejects_garbage(time: str) -> None:
    with pytest.raises(ValidationError):
        SlurmDefaults(time=time)


def test_slurm_extra_is_one_option_per_line() -> None:
    assert SlurmDefaults(extra=["--qos=high", "--exclusive"]).extra == ["--qos=high", "--exclusive"]
    for bad in ["qos=high", "--qos=high\n#SBATCH --mem=1T", "--qos=high\n", "-q high"]:
        with pytest.raises(ValidationError):
            SlurmDefaults(extra=[bad])


@pytest.mark.parametrize(
    "item",
    [
        "--job-name=custom",
        "--job=custom",
        "--comment=x",
        "--output=/tmp/o",
        "--out=/tmp/o",
        "--error=/tmp/e",
        "--chdir=/tmp",
        "--ch=/tmp",
        "--wrap=id",
        "-Jcustom",
        "-J",
        "-o/tmp/o",
        "-e/tmp/e",
        "-D/tmp",
    ],
)
def test_slurm_extra_cannot_set_the_job_identity(item: str) -> None:
    with pytest.raises(ValidationError, match="Hypothex sets itself"):
        SlurmDefaults(extra=[item])


@pytest.mark.parametrize(
    ("item", "message"),
    [
        ("--qos=normal --output=/tmp/x --job-name=c", "exactly one option token"),
        ("--qos='a b'", "exactly one option token"),
        ("--qos=normal\t--output=/tmp/x", "exactly one option token"),
        ("--mem=1G;id", "not an sbatch option"),
        ("--export=$HOME", "not an sbatch option"),
        ("--QOS=high", "not an sbatch option"),
        ("-HJx", "bundles short options"),
        ("-kofile", "bundles short options"),
    ],
)
def test_slurm_extra_is_exactly_one_safe_option(item: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        SlurmDefaults(extra=[item])


def test_slurm_extra_keeps_ordinary_options() -> None:
    items = ["--qos=high", "--exclusive", "--gres=gpu:a100:2", "--export=ALL,SEED=1", "-pgpu-long"]
    assert SlurmDefaults(extra=[*items, "-H", "-q"]).extra == [*items, "-H", "-q"]


def test_slurm_partition_and_gpus_rules() -> None:
    assert SlurmDefaults(partition="gpu,gpu-long", gpus=0).gpus == 0
    with pytest.raises(ValidationError):
        SlurmDefaults(partition="--gpu")
    with pytest.raises(ValidationError):
        SlurmDefaults(gpus=-1)


@pytest.mark.parametrize("name", ["local", "GPU1", "-gpu", "a" * 33, "gpu.1"])
def test_bad_host_names_are_rejected(tmp_path: Path, name: str) -> None:
    layout = Layout(tmp_path)
    write(layout, f"environments:\n  {name}:\n    route: url\n    url: http://127.0.0.1:1\n")
    with pytest.raises(ConfigError, match="host name"):
        load_hosts(layout)


def test_host_name_with_a_trailing_newline_is_rejected(tmp_path: Path) -> None:
    # Python's `$` also matches before a final newline; fullmatch does not.
    layout = Layout(tmp_path)
    write(layout, 'environments:\n  "gpu1\\n": {route: url, url: "http://127.0.0.1:1"}\n')
    with pytest.raises(ConfigError, match="host name"):
        load_hosts(layout)


def test_project_name_with_a_trailing_newline_is_rejected() -> None:
    with pytest.raises(ValidationError, match="project names"):
        HostSpec(route="ssh", ssh_alias="a", projects={"toy\n": "~/toy"})


def test_validation_error_names_the_file(tmp_path: Path) -> None:
    layout = Layout(tmp_path)
    write(layout, "environments:\n  gpu1: {route: ssh}\n")
    with pytest.raises(ConfigError) as info:
        load_hosts(layout)
    assert str(info.value).startswith(str(environments_path(layout)))
    assert "route ssh needs ssh_alias" in str(info.value)


def test_top_level_list_is_an_error(tmp_path: Path) -> None:
    layout = Layout(tmp_path)
    write(layout, "- gpu1\n")
    with pytest.raises(ConfigError, match="expected a mapping"):
        load_hosts(layout)


def test_invalid_yaml_is_an_error(tmp_path: Path) -> None:
    layout = Layout(tmp_path)
    write(layout, "environments: {gpu1: [\n")
    with pytest.raises(ConfigError, match="environments.yaml"):
        load_hosts(layout)


def test_deep_nesting_is_an_error_not_a_crash(tmp_path: Path) -> None:
    layout = Layout(tmp_path)
    write(layout, "environments: " + "[" * 500 + "]" * 500 + "\n")
    with pytest.raises(ConfigError, match=r"nested too deeply \(over 64 levels\) \(line 1\)"):
        load_hosts(layout)


def test_alias_cycle_is_an_error(tmp_path: Path) -> None:
    layout = Layout(tmp_path)
    write(layout, "environments: &e\n  gpu1: {route: ssh, ssh_alias: a, projects: *e}\n")
    with pytest.raises(ConfigError, match=r"must not form a cycle \(line 2\)"):
        load_hosts(layout)


def test_shared_anchors_are_allowed(tmp_path: Path) -> None:
    layout = Layout(tmp_path)
    write(
        layout,
        "environments:\n"
        "  a: {route: ssh, ssh_alias: a, kind: slurm,\n"
        "      slurm: &s {partition: gpu, time: '04:00:00'}}\n"
        "  b: {route: ssh, ssh_alias: b, kind: slurm, slurm: *s}\n",
    )
    hosts = load_hosts(layout).environments
    assert hosts["a"].slurm == hosts["b"].slurm == SlurmDefaults(partition="gpu", time="04:00:00")


def test_unknown_top_level_key_is_an_error(tmp_path: Path) -> None:
    layout = Layout(tmp_path)
    write(layout, "hosts: {}\n")
    with pytest.raises(ConfigError, match="hosts"):
        load_hosts(layout)


def test_stale_banner_hours_defaults_to_a_day_and_is_configurable(tmp_path: Path) -> None:
    layout = Layout(tmp_path)
    assert load_hosts(layout).stale_banner_hours == 24
    write(layout, "stale_banner_hours: 6\nenvironments: {}\n")
    assert load_hosts(layout).stale_banner_hours == 6
    save_hosts(layout, load_hosts(layout))
    assert load_hosts(layout).stale_banner_hours == 6
    for bad in ("0", "-1", ".nan", "x"):
        write(layout, f"stale_banner_hours: {bad}\n")
        with pytest.raises(ConfigError, match="stale_banner_hours"):
            load_hosts(layout)
