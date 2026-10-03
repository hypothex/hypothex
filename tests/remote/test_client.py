"""EnvClient against in-process env servers (uvicorn on a random port) and fake WS servers."""

import contextlib
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

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
