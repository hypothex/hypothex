"""Env-server routes: run files (path safety, max_bytes), GPUs, and the queue."""

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hypothex.api.app import create_app, read_span
from hypothex.core.context import Context
from tests.factories import seed_finished_run

FILES = "/api/v1/runs/r1/files"


@pytest.fixture
def app(home: Path) -> FastAPI:
    return create_app(home, background_repair=False)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, base_url="http://127.0.0.1:7777") as c:
        yield c


@pytest.fixture
def run_dir(client: TestClient, ctx: Context, toy_repo: Path) -> Path:
    record = seed_finished_run(ctx, toy_repo, "r1")
    return ctx.run_dir(record)


# files -------------------------------------------------------------------------------
def test_file_bytes_size_header_and_nested_names(client: TestClient, run_dir: Path) -> None:
    (run_dir / "notes.md").write_bytes(b"# r1\nlooks good\n")
    (run_dir / "traces").mkdir()
    (run_dir / "traces" / "a b#1.jsonl").write_bytes(b'{"step": 1}\n')
    resp = client.get(f"{FILES}/notes.md")
    assert resp.status_code == 200 and resp.content == b"# r1\nlooks good\n"
    assert resp.headers["content-length"] == "16" and resp.headers["x-hypothex-size"] == "16"
    nested = client.get(f"{FILES}/traces/a%20b%231.jsonl")
    assert nested.status_code == 200 and nested.content == b'{"step": 1}\n'


def test_max_bytes_gives_413_or_the_tail(client: TestClient, run_dir: Path) -> None:
    (run_dir / "logs" / "stdout.log").write_bytes(b"0123456789")
    exact = client.get(f"{FILES}/logs/stdout.log", params={"max_bytes": 10})
    assert exact.status_code == 200 and exact.content == b"0123456789"
    big = client.get(f"{FILES}/logs/stdout.log", params={"max_bytes": 9})
    assert big.status_code == 413
    assert big.json() == {
        "error": "logs/stdout.log is 10 bytes, over max_bytes=9",
        "type": "FileTooLargeError",
        "size": 10,
    }
    tail = client.get(f"{FILES}/logs/stdout.log", params={"max_bytes": 4, "tail": True})
    assert tail.status_code == 200 and tail.content == b"6789"
    assert tail.headers["x-hypothex-size"] == "10"
    assert client.get(f"{FILES}/logs/stdout.log", params={"max_bytes": -1}).status_code == 422


def test_missing_file_and_missing_run_are_404(client: TestClient, run_dir: Path) -> None:
    missing = client.get(f"{FILES}/nope.txt")
    assert missing.status_code == 404 and missing.json()["type"] == "StoreError"
    assert "'nope.txt'" in missing.json()["error"]
    no_run = client.get("/api/v1/runs/ghost/files/run.yaml")
    assert no_run.status_code == 404 and no_run.json()["type"] == "RunNotFoundError"


def test_folder_listing_is_recursive_sorted_and_skips_hidden(
    client: TestClient, run_dir: Path
) -> None:
    preds = run_dir / "predictions"
    (preds / "sub").mkdir(parents=True)
    (preds / "b.jsonl").write_bytes(b"bb")
    (preds / "a.jsonl").write_bytes(b"a")
    (preds / "sub" / "c.jsonl").write_bytes(b"ccc")
    (preds / ".a.jsonl.tmp").write_bytes(b"partial")
    resp = client.get(f"{FILES}/predictions")
    assert resp.status_code == 200 and resp.headers["x-hypothex-dir"] == "1"
    listing = resp.json()
    assert [(item["path"], item["size"]) for item in listing] == [
        ("predictions/a.jsonl", 1),
        ("predictions/b.jsonl", 2),
        ("predictions/sub/c.jsonl", 3),
    ]
    assert all(isinstance(item["mtime_ns"], int) for item in listing)
    whole = [item["path"] for item in client.get(f"{FILES}/").json()]
    assert "run.yaml" in whole and "predictions/sub/c.jsonl" in whole
    assert ".lock" not in whole


@pytest.mark.parametrize(
    "path",
    [
        "%2E%2E/%2E%2E/%2E%2E/secret.txt",
        "logs/..%2F..%2F..%2F..%2Fsecret.txt",
        "%2Fetc%2Fpasswd",
        "run.yaml%00.txt",
    ],
)
def test_paths_outside_the_run_folder_are_404(
    client: TestClient, run_dir: Path, home: Path, path: str
) -> None:
    (home / "store" / "secret.txt").write_text("TOPSECRET")
    resp = client.get(f"{FILES}/{path}")
    assert resp.status_code == 404
    assert "outside the run folder" in resp.json()["error"]
    assert "TOPSECRET" not in resp.text and "root:" not in resp.text


def test_symlinks_cannot_escape_the_run_folder(
    client: TestClient, run_dir: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("TOPSECRET")
    (run_dir / "leak.txt").symlink_to(outside / "secret.txt")
    (run_dir / "leakdir").symlink_to(outside, target_is_directory=True)
    (run_dir / "loop").symlink_to(run_dir / "loop")
    (run_dir / "alias.yaml").symlink_to(run_dir / "run.yaml")
    for path in ("leak.txt", "leakdir/secret.txt", "leakdir", "loop"):
        resp = client.get(f"{FILES}/{path}")
        assert resp.status_code == 404, path
        assert "TOPSECRET" not in resp.text
    # no symlink is followed, even one that stays inside the run folder
    alias = client.get(f"{FILES}/alias.yaml")
    assert alias.status_code == 404 and "outside the run folder" in alias.json()["error"]
    listed = [item["path"] for item in client.get(f"{FILES}/").json()]
    assert "run.yaml" in listed
    assert not any(p.startswith(("leak", "loop", "alias")) for p in listed)


def _outside_copy(run_dir: Path, outside: Path) -> None:
    """A look-alike run folder outside the store: the real run.yaml plus a secret."""
    (outside / "traces").mkdir(parents=True)
    (outside / "run.yaml").write_bytes((run_dir / "run.yaml").read_bytes())
    (outside / "secret.txt").write_text("TOPSECRET")
    (outside / "traces" / "x.txt").write_text("TOPSECRET")


def test_a_run_folder_replaced_by_a_symlink_is_refused(
    client: TestClient, run_dir: Path, tmp_path: Path
) -> None:
    # the run root itself is the link: the walk from the store root never follows it
    outside = tmp_path / "outside"
    _outside_copy(run_dir, outside)
    run_dir.rename(run_dir.with_name("r1.old"))
    run_dir.symlink_to(outside, target_is_directory=True)
    for path in ("secret.txt", "run.yaml", "traces/x.txt", ""):
        resp = client.get(f"{FILES}/{path}")
        assert resp.status_code == 404, path
        assert "TOPSECRET" not in resp.text


@pytest.mark.parametrize("swapped", ["traces", "run root"])
def test_a_folder_swapped_for_a_symlink_mid_request_cannot_escape(
    client: TestClient,
    run_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    swapped: str,
) -> None:
    # the folder becomes a link to outside after every earlier check, right before
    # the walk opens it
    outside = tmp_path / "outside"
    _outside_copy(run_dir, outside)
    traces = run_dir / "traces"
    traces.mkdir()
    (traces / "x.txt").write_text("inside")
    victim, target = (traces, outside / "traces") if swapped == "traces" else (run_dir, outside)
    real_open = os.open
    done: list[str] = []

    def open_then_swap(path: Any, flags: int, mode: int = 0o777, *, dir_fd: Any = None) -> int:
        if not done and dir_fd is not None and str(path) == victim.name:
            done.append(str(path))
            victim.rename(victim.with_name(victim.name + ".old"))
            victim.symlink_to(target, target_is_directory=True)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", open_then_swap)
    resp = client.get(f"{FILES}/traces/x.txt")
    monkeypatch.setattr(os, "open", real_open)  # not undo(): that would drop the isolation too
    assert done
    assert resp.status_code == 404 and "TOPSECRET" not in resp.text
    listing = client.get(f"{FILES}/")
    assert "TOPSECRET" not in listing.text
    if swapped == "traces":
        assert not any(item["path"].startswith("traces/") for item in listing.json())
    else:
        assert listing.status_code == 404


def test_fifo_is_404_and_does_not_hang(client: TestClient, run_dir: Path) -> None:
    os.mkfifo(run_dir / "pipe")
    resp = client.get(f"{FILES}/pipe")
    assert resp.status_code == 404 and "not a regular file" in resp.json()["error"]


def test_the_reserved_hx_folder_is_never_served(client: TestClient, run_dir: Path) -> None:
    hx = run_dir / ".hx"
    hx.mkdir()
    (hx / "mirror-skips.json").write_text('{"notes.md": {"reason": "too big"}}')
    for path in (".hx/mirror-skips.json", ".hx", ".hx/", "%2Ehx/mirror-skips.json"):
        resp = client.get(f"{FILES}/{path}")
        assert resp.status_code == 404, path
        assert "reserved" in resp.json()["error"] and "too big" not in resp.text
    listed = [item["path"] for item in client.get(f"{FILES}/").json()]
    assert not any(p.startswith(".hx") for p in listed)


def test_read_span_stops_at_the_length_fixed_at_start(tmp_path: Path) -> None:
    log = tmp_path / "grow.log"
    log.write_bytes(b"abcdef")
    fd = os.open(log, os.O_RDONLY)
    chunks = read_span(fd, 2, 4)
    with log.open("ab") as fh:
        fh.write(b"MORE")  # the file grows after the response started
    assert b"".join(chunks) == b"cdef"
    with pytest.raises(OSError):
        os.fstat(fd)  # closed when the iterator finished
