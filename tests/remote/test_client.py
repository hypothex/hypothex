"""EnvClient against in-process env servers (uvicorn on a random port) and fake WS servers."""

import contextlib
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import uvicorn

from hypothex.api.app import create_app
from hypothex.core.context import Context
from hypothex.remote.client import EnvClient, EnvRequestError, EnvUnreachableError
from tests.factories import seed_finished_run


@contextlib.contextmanager
def live_server(home: Path) -> Iterator[str]:
    """Serve ``create_app(home)`` with uvicorn on a free loopback port in a thread."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    app = create_app(home, background_repair=False)
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="on"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError("env server did not start")
        time.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(10)
        if thread.is_alive():
            server.force_exit = True
            thread.join(5)
        sock.close()


def free_port() -> int:
    """Return a loopback port with nothing listening on it."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def env(home: Path, ctx: Context) -> Iterator[EnvClient]:
    with live_server(home) as url, EnvClient(url, timeout=5) as client:
        yield client


# HTTP --------------------------------------------------------------------------------
def test_descriptor_matches_the_server(env: EnvClient, ctx: Context) -> None:
    desc = env.descriptor()
    assert desc.environment_id == ctx.descriptor.environment_id
    assert desc.protocol_version == 1


def test_get_json_drops_none_params_and_post_json(
    env: EnvClient, ctx: Context, toy_repo: Path
) -> None:
    seed_finished_run(ctx, toy_repo, "r1")
    runs = env.get_json("/api/v1/runs", project="toy", task=None)
    assert [r["run_id"] for r in runs] == ["r1"]
    assert env.get_json("/api/v1/runs", project="other") == []
    tagged = env.post_json("/api/v1/runs/r1/tags", {"add": ["sweep:s1"], "command_id": "c-1"})
    assert tagged["tags"] == ["sweep:s1"]
    again = env.post_json("/api/v1/runs/r1/tags", {"add": ["sweep:s1"], "command_id": "c-1"})
    assert again == tagged


def test_server_errors_keep_status_and_type(env: EnvClient) -> None:
    with pytest.raises(EnvRequestError) as missing:
        env.get_json("/api/v1/runs/ghost")
    assert missing.value.status_code == 404
    assert missing.value.error_type == "RunNotFoundError"
    assert "no run 'ghost'" in str(missing.value)
    with pytest.raises(EnvRequestError) as invalid:
        env.post_json("/api/v1/runs/ghost/notes", {})
    assert invalid.value.status_code == 422 and "text" in str(invalid.value)


def test_unreachable_server_raises_unreachable() -> None:
    client = EnvClient(f"http://127.0.0.1:{free_port()}", timeout=2)
    with client, pytest.raises(EnvUnreachableError) as err:
        client.descriptor()
    assert err.value.status_code is None and "cannot reach" in str(err.value)


# files -------------------------------------------------------------------------------
def test_fetch_file_writes_whole_file_or_nothing(
    env: EnvClient, ctx: Context, toy_repo: Path, tmp_path: Path
) -> None:
    run_dir = ctx.run_dir(seed_finished_run(ctx, toy_repo, "r1"))
    (run_dir / "logs" / "stdout.log").write_bytes(b"0123456789")
    (run_dir / "traces").mkdir()
    (run_dir / "traces" / "a b#1.jsonl").write_bytes(b"{}\n")
    out = tmp_path / "mirror"
    assert env.fetch_file("r1", "run.yaml", out / "run.yaml", max_bytes=10_000) is True
    assert (out / "run.yaml").read_bytes() == (run_dir / "run.yaml").read_bytes()
    assert env.fetch_file("r1", "traces/a b#1.jsonl", out / "t.jsonl", max_bytes=100)
    assert (out / "t.jsonl").read_bytes() == b"{}\n"
    assert env.fetch_file("r1", "nope.txt", out / "nope.txt", max_bytes=100) is False
    assert not (out / "nope.txt").exists()
    (out / "stdout.log").write_bytes(b"old")
    assert env.fetch_file("r1", "logs/stdout.log", out / "stdout.log", max_bytes=9) is False
    assert (out / "stdout.log").read_bytes() == b"old"
    tail = env.fetch_file("r1", "logs/stdout.log", out / "stdout.log", max_bytes=4, tail=True)
    assert tail is True and (out / "stdout.log").read_bytes() == b"6789"
    assert sorted(p.name for p in out.iterdir()) == ["run.yaml", "stdout.log", "t.jsonl"]


def test_fetch_folder_copies_files_under_the_limit(
    env: EnvClient, ctx: Context, toy_repo: Path, tmp_path: Path
) -> None:
    run_dir = ctx.run_dir(seed_finished_run(ctx, toy_repo, "r1"))
    preds = run_dir / "predictions"
    (preds / "sub").mkdir(parents=True)
    (preds / "small.jsonl").write_bytes(b"s")
    (preds / "sub" / "deep.jsonl").write_bytes(b"dd")
    (preds / "huge.bin").write_bytes(b"x" * 50)
    dest = tmp_path / "mirror" / "predictions"
    assert env.fetch_file("r1", "predictions", dest, max_bytes=10) is True
    assert (dest / "small.jsonl").read_bytes() == b"s"
    assert (dest / "sub" / "deep.jsonl").read_bytes() == b"dd"
    assert not (dest / "huge.bin").exists()
    listed = env.list_files("r1", "predictions")
    assert [(f.path, f.size) for f in listed] == [
        ("predictions/huge.bin", 50),
        ("predictions/small.jsonl", 1),
        ("predictions/sub/deep.jsonl", 2),
    ]
    with pytest.raises(EnvRequestError) as not_dir:
        env.list_files("r1", "run.yaml")
    assert "is a file" in str(not_dir.value)


def test_fetch_ignores_listing_entries_outside_the_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = {"predictions/ok.jsonl": b"ok", "../../evil.sh": b"rm -rf ~", "/abs.txt": b"x"}

    def handler(request: httpx.Request) -> httpx.Response:
        rel = request.url.path.split("/files/", 1)[1]
        if rel == "predictions":
            listing = [{"path": p, "size": len(b)} for p, b in files.items()]
            listing.append({"path": "other/x.txt", "size": 1})
            return httpx.Response(200, json=listing, headers={"X-Hypothex-Dir": "1"})
        return httpx.Response(200, content=files.get(rel, b"?"))

    client = EnvClient("http://fake-host")
    client._http = httpx.Client(base_url="http://fake-host", transport=httpx.MockTransport(handler))
    dest = tmp_path / "mirror" / "predictions"
    assert client.fetch_file("r1", "predictions", dest, max_bytes=100) is True
    written = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if p.is_file())
    assert written == ["mirror/predictions/ok.jsonl"]


def test_dropped_transfer_leaves_no_partial_file(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        def body() -> Iterator[bytes]:
            yield b"first half"
            raise httpx.ReadError("connection reset")

        return httpx.Response(200, content=body())

    client = EnvClient("http://fake-host")
    client._http = httpx.Client(base_url="http://fake-host", transport=httpx.MockTransport(handler))
    dest = tmp_path / "scores.jsonl"
    with pytest.raises(EnvUnreachableError):
        client.fetch_file("r1", "scores.jsonl", dest, max_bytes=100)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "answer",
    [b"<html>proxy page</html>", b'{"path": "a", "size": 1}', b'[{"path": "a"}]', b"null"],
    ids=["not-json", "not-a-list", "wrong-shape", "null"],
)
def test_bad_listing_raises_env_request_error(tmp_path: Path, answer: bytes) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=answer, headers={"X-Hypothex-Dir": "1"})

    client = EnvClient("http://fake-host")
    client._http = httpx.Client(base_url="http://fake-host", transport=httpx.MockTransport(handler))
    with pytest.raises(EnvRequestError) as listed:
        client.list_files("r1", "predictions")
    assert listed.value.status_code == 200
    with pytest.raises(EnvRequestError) as fetched:
        client.fetch_file("r1", "predictions", tmp_path / "predictions", max_bytes=100)
    assert fetched.value.status_code == 200
    assert not (tmp_path / "predictions").exists()
