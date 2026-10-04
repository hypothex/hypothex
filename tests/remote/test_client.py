"""EnvClient against in-process env servers (uvicorn on a random port) and fake WS servers."""

import asyncio
import contextlib
import json
import socket
import threading
import time
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Iterator
from http import HTTPStatus
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from websockets.asyncio.server import ServerConnection, serve
from websockets.http11 import Request, Response

from hypothex.api.app import create_app
from hypothex.core.context import Context
from hypothex.core.events import Event
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


def _event(sequence: int, type_: str = "run.started") -> dict[str, Any]:
    return {
        "sequence": sequence,
        "type": type_,
        "project": "toy",
        "run_id": "r1",
        "payload": {},
        "created_at": "2026-10-03T00:00:00+00:00",
    }


async def _take(agen: AsyncGenerator[Event, None], n: int, timeout: float = 10) -> list[Event]:
    out: list[Event] = []

    async def pull() -> None:
        async for event in agen:
            out.append(event)
            if len(out) == n:
                return

    async with contextlib.aclosing(agen):
        await asyncio.wait_for(pull(), timeout)
    return out


@contextlib.asynccontextmanager
async def fake_ws(
    handler: Callable[[ServerConnection], Awaitable[None]], **options: Any
) -> AsyncIterator[str]:
    """A bare WebSocket server on a free port that runs ``handler`` per connection."""
    async with serve(handler, "127.0.0.1", 0, **options) as server:
        port = next(iter(server.sockets)).getsockname()[1]
        yield f"http://127.0.0.1:{port}"


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


def test_post_json_can_wait_longer_than_the_client_timeout(
    env: EnvClient, ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_finished_run(ctx, toy_repo, "r1")
    seen: list[Any] = []
    real = env._http.request

    def spy(method: str, url: str, **kw: Any) -> httpx.Response:
        seen.append(kw.get("timeout", "client default"))
        return real(method, url, **kw)

    monkeypatch.setattr(env._http, "request", spy)
    env.post_json("/api/v1/runs/r1/star", {"on": True})
    env.post_json("/api/v1/runs/r1/star", {"on": True}, timeout=600)
    assert seen == ["client default", 600]


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


def _mock_client(handler: Callable[[httpx.Request], httpx.Response]) -> EnvClient:
    client = EnvClient("http://fake-host")
    client._http = httpx.Client(base_url="http://fake-host", transport=httpx.MockTransport(handler))
    return client


def test_unparsable_content_length_is_treated_as_unknown(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"abc", headers={"content-length": "oops"})

    client = _mock_client(handler)
    assert client.fetch_file("r1", "a.txt", tmp_path / "a.txt", max_bytes=10) is True
    assert (tmp_path / "a.txt").read_bytes() == b"abc"
    assert client.fetch_file("r1", "a.txt", tmp_path / "b.txt", max_bytes=2) is False
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.txt"]


@pytest.mark.parametrize("url", ["127.0.0.1:1", "ftp://127.0.0.1:1", "http://", ""])
def test_base_url_needs_http_or_https(url: str) -> None:
    with pytest.raises(ValueError, match="http:// or https://"):
        EnvClient(url)


def test_https_base_url_gives_a_wss_url() -> None:
    with EnvClient("https://env.example.org/") as client:
        assert client.ws_url == "wss://env.example.org/api/v1/ws"


@pytest.mark.parametrize("listed", [True, False], ids=["files", "empty"])
def test_a_folder_never_lands_on_an_existing_file(tmp_path: Path, listed: bool) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        rel = request.url.path.split("/files/", 1)[1]
        if rel == "predictions":
            listing = [{"path": "predictions/a.jsonl", "size": 1}] if listed else []
            return httpx.Response(200, json=listing, headers={"X-Hypothex-Dir": "1"})
        return httpx.Response(200, content=b"a")

    dest = tmp_path / "predictions"
    dest.write_bytes(b"mine")
    with pytest.raises(NotADirectoryError, match="is a file"):
        _mock_client(handler).fetch_file("r1", "predictions", dest, max_bytes=10)
    assert dest.read_bytes() == b"mine"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["predictions"]


def test_a_file_never_lands_on_an_existing_folder(tmp_path: Path) -> None:
    dest = tmp_path / "scores.jsonl"
    dest.mkdir()
    (dest / "keep.txt").write_bytes(b"k")
    client = _mock_client(lambda request: httpx.Response(200, content=b"{}\n"))
    with pytest.raises(IsADirectoryError, match="is a folder"):
        client.fetch_file("r1", "scores.jsonl", dest, max_bytes=10)
    assert sorted(p.name for p in dest.iterdir()) == ["keep.txt"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["scores.jsonl"]


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


# events ------------------------------------------------------------------------------
def test_events_replay_then_stream_live(env: EnvClient, ctx: Context) -> None:
    for i in range(3):
        ctx.events.append("test.event", payload={"i": i})
    base = ctx.events.last_sequence()

    async def scenario() -> list[Event]:
        agen = env.events(base - 2)
        out: list[Event] = []
        async with contextlib.aclosing(agen):
            async for event in agen:
                out.append(event)
                if len(out) == 2:
                    await asyncio.to_thread(ctx.events.append, "test.live")
                if len(out) == 3:
                    break
        return out

    events = asyncio.run(asyncio.wait_for(scenario(), 10))
    assert [e.sequence for e in events] == [base - 1, base, base + 1]
    assert [e.type for e in events] == ["test.event", "test.event", "test.live"]
    assert events[0].payload == {"i": 1}


def test_events_drop_duplicates_and_end_on_close() -> None:
    received: list[dict[str, Any]] = []

    async def handler(ws: ServerConnection) -> None:
        received.append(json.loads(await ws.recv()))
        for seq in (4, 5, 5, 3, 6):
            await ws.send(json.dumps({"type": "event", "event": _event(seq)}))
        await ws.send(json.dumps({"type": "ready", "last_sequence": 6}))
        await ws.close()

    async def scenario() -> list[int]:
        async with fake_ws(handler) as url:
            client = EnvClient(url, timeout=5)
            return [e.sequence async for e in client.events(3)]

    assert asyncio.run(asyncio.wait_for(scenario(), 10)) == [4, 5, 6]
    assert received == [{"type": "subscribe", "after_sequence": 3}]


def test_events_error_message_raises() -> None:
    async def handler(ws: ServerConnection) -> None:
        await ws.recv()
        await ws.send(json.dumps({"type": "error", "error": "first message must be subscribe"}))
        await ws.close()

    async def scenario() -> None:
        async with fake_ws(handler) as url:
            async for _ in EnvClient(url, timeout=5).events(0):
                pass

    with pytest.raises(EnvRequestError, match="first message must be subscribe"):
        asyncio.run(asyncio.wait_for(scenario(), 10))


@pytest.mark.parametrize(
    "frame",
    [
        "<html>proxy page</html>",
        "[1, 2]",
        "null",
        json.dumps({"type": "event"}),
        json.dumps({"type": "event", "event": {"sequence": "x"}}),
        json.dumps({"type": "event", "event": "nope"}),
    ],
    ids=["not-json", "not-an-object", "null", "no-event-key", "bad-event-body", "event-not-object"],
)
def test_events_bad_frame_raises_env_request_error(frame: str) -> None:
    async def handler(ws: ServerConnection) -> None:
        await ws.recv()
        await ws.send(frame)
        await ws.close()

    async def scenario() -> None:
        async with fake_ws(handler) as url:
            async for _ in EnvClient(url, timeout=5).events(0):
                pass

    with pytest.raises(EnvRequestError, match="invalid message") as err:
        asyncio.run(asyncio.wait_for(scenario(), 10))
    assert not isinstance(err.value, EnvUnreachableError)


def test_events_refused_handshake_keeps_the_status() -> None:
    def refuse(conn: ServerConnection, request: Request) -> Response:
        return conn.respond(HTTPStatus.FORBIDDEN, "Cross-origin request rejected\n")

    async def never(ws: ServerConnection) -> None:
        await ws.close()

    async def scenario() -> None:
        async with fake_ws(never, process_request=refuse) as url:
            async for _ in EnvClient(url, timeout=5).events(0):
                pass

    with pytest.raises(EnvRequestError) as err:
        asyncio.run(asyncio.wait_for(scenario(), 10))
    assert err.value.status_code == 403
    assert not isinstance(err.value, EnvUnreachableError)


def test_events_unreachable_raises() -> None:
    async def scenario() -> None:
        async for _ in EnvClient(f"http://127.0.0.1:{free_port()}", timeout=2).events(0):
            pass

    with pytest.raises(EnvUnreachableError):
        asyncio.run(scenario())


def test_closed_subscription_does_not_hold_the_server(home: Path, ctx: Context) -> None:
    ctx.events.append("test.event")
    with live_server(home) as url:
        events = asyncio.run(_take(EnvClient(url, timeout=5).events(0), 1))
        assert [e.type for e in events] == ["test.event"]
        stopping = time.monotonic()
    assert time.monotonic() - stopping < 5  # uvicorn waits for open WebSocket handlers
