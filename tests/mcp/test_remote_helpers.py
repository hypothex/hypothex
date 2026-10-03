import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from hypothex.api.app import create_app
from hypothex.core.context import Context
from hypothex.core.errors import ConfigError, HypothexError, RunError, StoreError
from hypothex.core.ids import utcnow
from hypothex.core.sweeps import SweepParam, SweepSpec, save_sweep, sweep_path
from hypothex.mcp.server import (
    DEFAULT_HUB_URL,
    HubUnavailableError,
    find_sweep,
    hub_call,
    hub_url,
    is_remote,
    parse_grid,
    parse_ranges,
    parse_seeds,
    ssh_target,
)
from hypothex.remote.config import HostSpec
from hypothex.remote.ssh import SshTarget, copy_from, copy_to
from tests.api.envserver import serve_app, write_fake_scp
from tests.factories import write_toy_project


@pytest.fixture
def toy(ctx: Context, toy_repo: Path) -> Context:
    ctx.register_project(toy_repo)
    return ctx


def _saved_sweep(ctx: Context, sweep_id: str = "s-ab12") -> SweepSpec:
    spec = SweepSpec(
        id=sweep_id,
        project="toy",
        task="toy-acc",
        host=None,
        grid=parse_grid(["x=1,2"]),
        seeds=[1, 2],
        command_template=["python", "train.py", "{x}"],
        created_by="human",
        created_at=utcnow(),
    )
    save_sweep(ctx.layout, spec)
    return spec


def test_is_remote() -> None:
    assert not is_remote(None) and not is_remote("") and not is_remote("local")
    assert is_remote("gpu1")


def test_ssh_target_uses_the_env_binaries() -> None:
    target = ssh_target(HostSpec(route="ssh", ssh_alias="gpu1-alias"))
    assert target.alias == "gpu1-alias"
    with pytest.raises(ConfigError, match="route: ssh"):
        ssh_target(HostSpec(route="url", url="http://127.0.0.1:9"))


def test_parse_grid_ranges_and_seeds() -> None:
    assert parse_grid(["lr=1e-4,3e-4", "beam=5"]) == [
        SweepParam(name="lr", values=["1e-4", "3e-4"]),
        SweepParam(name="beam", values=["5"]),
    ]
    assert parse_ranges(["lr=1e-5:1e-3:log"]) == [
        SweepParam(name="lr", low=1e-5, high=1e-3, log=True)
    ]
    assert parse_seeds("3") == [1, 2, 3]
    assert parse_seeds("4,5") == [4, 5]
    assert parse_seeds("7", count_ok=False) == [7]
    for bad in (["lr"], ["lr="], ["=1,2"], ["lr=1", "lr=2"]):
        with pytest.raises(RunError):
            parse_grid(bad)
    for bad_range in ("lr=1:0", "lr=0:1:log", "lr=a:b", "lr=1:2:lin", "lr"):
        with pytest.raises(RunError):
            parse_ranges([bad_range])
    for bad_seeds in ("0", "x", "1,1", ""):
        with pytest.raises(RunError):
            parse_seeds(bad_seeds)


def test_find_sweep(toy: Context, tmp_path: Path) -> None:
    spec = _saved_sweep(toy)
    assert find_sweep(toy, spec.id).id == spec.id
    assert find_sweep(toy, spec.id, "toy").project == "toy"
    with pytest.raises(StoreError, match="no sweep s-0000"):
        find_sweep(toy, "s-0000")
    with pytest.raises(StoreError, match="no sweep"):
        find_sweep(toy, "../../etc")
    other = write_toy_project(tmp_path / "other")
    config = yaml.safe_load((other / "hypothex.yaml").read_text())
    config["project"] = "other"
    (other / "hypothex.yaml").write_text(yaml.safe_dump(config))
    toy.register_project(other)
    copy = sweep_path(toy.layout, "other", spec.id)
    copy.parent.mkdir(parents=True)
    shutil.copy(sweep_path(toy.layout, "toy", spec.id), copy)
    with pytest.raises(ConfigError, match="pass --project"):
        find_sweep(toy, spec.id)


def test_hub_url_default_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HYPOTHEX_HUB_URL")
    assert hub_url() == DEFAULT_HUB_URL
    monkeypatch.setenv("HYPOTHEX_HUB_URL", "http://127.0.0.1:8000/")
    assert hub_url() == "http://127.0.0.1:8000"


def test_hub_call_maps_answers_and_errors(home: Path, toy: Context) -> None:
    with serve_app(create_app(home, background_repair=False)) as url:
        assert hub_call("GET", "/api/v1/projects", url=url)[0]["project"] == "toy"
        with pytest.raises(StoreError, match="nope"):
            hub_call("GET", "/api/v1/runs/nope", url=url)
        with pytest.raises(HypothexError, match="unknown task") as plain:
            hub_call("GET", "/api/v1/tasks/toy/nope", url=url)
        assert type(plain.value) is HypothexError  # a 400 is neither StoreError nor 503
    with pytest.raises(HubUnavailableError, match="hx serve"):
        hub_call("GET", "/api/v1/projects")  # the autouse fixture points at a dead port


def _status_app() -> FastAPI:
    app = FastAPI()

    @app.get("/status/{code}")
    def status(code: int) -> JSONResponse:
        return JSONResponse({"error": f"answer {code}", "type": "X"}, status_code=code)

    @app.get("/bare/{code}")
    def bare(code: int) -> JSONResponse:
        return JSONResponse(["not", "a", "dict"], status_code=code)

    return app


@pytest.mark.parametrize(
    ("code", "error"),
    [(404, StoreError), (503, HubUnavailableError), (400, HypothexError), (500, HypothexError)],
)
def test_hub_call_maps_each_status_to_one_exact_type(code: int, error: type[Exception]) -> None:
    with serve_app(_status_app()) as url:
        with pytest.raises(HypothexError, match=f"^answer {code}$") as raised:
            hub_call("GET", f"/status/{code}", url=url)
        assert type(raised.value) is error
        with pytest.raises(HypothexError, match=f"hub answered {code} to GET /bare/{code}") as bare:
            hub_call("GET", f"/bare/{code}", url=url)  # no `error` text: a generic message
        assert type(bare.value) is error


def _scp(scp: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(scp), *args], capture_output=True, text=True, check=False)


def test_write_fake_scp_copies_inside_its_folder(tmp_path: Path) -> None:
    remote = tmp_path / "remote" / "ckpt" / "step_1.pt"
    remote.parent.mkdir(parents=True)
    remote.write_bytes(b"weights")
    target = SshTarget(alias="box", ssh_bin="false", scp_bin=str(write_fake_scp(tmp_path)))
    dest = tmp_path / "local" / "step_1.pt"
    copy_from(target, str(remote), dest, work=tmp_path / "pulls")  # any alias: box
    assert dest.read_bytes() == b"weights"
    copy_to(target, dest, "~/up.pt")  # the alias's home is <folder>/<alias>
    assert (tmp_path / "box" / "up.pt").read_bytes() == b"weights"


def test_write_fake_scp_refuses_paths_outside_its_folder(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    scp = write_fake_scp(root)
    src = tmp_path / "f.txt"
    src.write_text("x")
    outside = tmp_path / "outside.txt"  # a real path on this machine, next to the root
    batch = ("-o", "BatchMode=yes")
    for remote in (f"box:{outside}", "box:../../outside.txt", f"box:{root}/../outside.txt"):
        res = _scp(scp, *batch, str(src), remote)
        assert res.returncode == 1 and "outside the fake remote root" in res.stderr, remote
    assert not outside.exists()
    outside.write_text("secret")
    res = _scp(scp, *batch, f"box:{outside}", str(tmp_path / "got.txt"))
    assert res.returncode == 1 and not (tmp_path / "got.txt").exists()
    res = _scp(scp, *batch, str(src), "..:x.txt")  # the alias cannot climb out either
    assert res.returncode == 255 and "Could not resolve hostname" in res.stderr
    assert not (tmp_path / "x.txt").exists()
    res = _scp(scp, str(src), "box:f.txt")  # BatchMode is required, as for every fake
    assert res.returncode == 255 and "BatchMode" in res.stderr
    assert not (root / "box" / "f.txt").exists()
