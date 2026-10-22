"""Disk-backed snapshots and verified, non-overwriting installation."""

from __future__ import annotations

import ctypes
import fnmatch
import hashlib
import os
import stat
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from hypothex.sharing.models import MAX_FILES, ArtifactKind, FileEntry, Manifest, SharingError

_CHUNK = 1024 * 1024
_EXCLUDED = {".git", ".hg", ".svn", ".venv", "__pycache__", ".env"}


def _walk_error(error: OSError) -> None:
    raise error


def _selected(path: str, include: Sequence[str], exclude: Sequence[str]) -> bool:
    parts = path.split("/")
    if any(p in _EXCLUDED or p.startswith(".env.") for p in parts):
        return False
    return (not include or any(fnmatch.fnmatchcase(path, p) for p in include)) and not any(
        fnmatch.fnmatchcase(path, p) for p in exclude
    )


def _copy_file(parent_fd: int, name: str, relative: str, destination: Path) -> FileEntry:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
    with os.fdopen(fd, "rb") as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise SharingError("publications can contain regular files only")
        # Validate before making a path in the snapshot.
        FileEntry(path=relative, size=0, sha256="0" * 64)
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        with destination.open("xb") as output:
            while chunk := source.read(_CHUNK):
                output.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        after = os.fstat(source.fileno())
        if (
            size != before.st_size
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
        ):
            raise SharingError(
                "source changed while taking publication snapshot; retry when stable"
            )
        return FileEntry(path=relative, size=size, sha256=digest.hexdigest())


@contextmanager
def snapshot(
    source: Path,
    kind: ArtifactKind,
    *,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
    metadata: dict[str, str] | None = None,
) -> Iterator[tuple[Path, Manifest]]:
    """Stage selected regular files and hash the exact bytes sent to providers."""
    with TemporaryDirectory(prefix="hx-publish-") as temporary:
        root = Path(temporary)
        entries: list[FileEntry] = []
        try:
            source_stat = source.lstat()
            if stat.S_ISREG(source_stat.st_mode):
                parent_fd = os.open(source.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    if _selected(source.name, include, exclude):
                        entries.append(
                            _copy_file(parent_fd, source.name, source.name, root / source.name)
                        )
                finally:
                    os.close(parent_fd)
            elif stat.S_ISDIR(source_stat.st_mode):
                source_fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    for current, dirs, files, directory_fd in os.fwalk(
                        ".", dir_fd=source_fd, onerror=_walk_error
                    ):
                        relative_root = Path(current)
                        dirs[:] = sorted(
                            d
                            for d in dirs
                            if d not in _EXCLUDED
                            and not d.startswith(".env.")
                            and not any(
                                fnmatch.fnmatchcase((relative_root / d).as_posix(), p)
                                for p in exclude
                            )
                        )
                        for d in dirs:
                            if stat.S_ISLNK(
                                os.stat(d, dir_fd=directory_fd, follow_symlinks=False).st_mode
                            ):
                                raise SharingError("symlink directories cannot be published")
                        for name in sorted(files):
                            relative = (relative_root / name).as_posix()
                            if not _selected(relative, include, exclude):
                                continue
                            if len(entries) >= MAX_FILES:
                                raise SharingError("publication exceeds the file count limit")
                            entries.append(
                                _copy_file(directory_fd, name, relative, root / relative)
                            )
                finally:
                    os.close(source_fd)
            else:
                raise SharingError("source must be a regular file or directory, not a symlink")
            if not entries:
                raise SharingError("no publishable files selected")
            entries.sort(key=lambda entry: entry.path)
            manifest = Manifest(
                kind=kind,
                files=tuple(entries),
                metadata=metadata or {},
            )
        except (OSError, ValueError):
            raise SharingError(
                "cannot snapshot source: check paths, file types and read permissions"
            ) from None
        yield root, manifest


def verify_file(path: Path, entry: FileEntry) -> None:
    """Refuse a transfer whose complete byte stream differs from the manifest."""
    digest = hashlib.sha256()
    size = 0
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise SharingError("download did not produce a regular file")
        while chunk := source.read(_CHUNK):
            size += len(chunk)
            if size > entry.size:
                raise SharingError("download size exceeds its manifest")
            digest.update(chunk)
    if size != entry.size or digest.hexdigest() != entry.sha256:
        raise SharingError("download failed SHA-256 verification")


def install_directory(staged: Path, destination: Path) -> None:
    """Atomically install on Linux/macOS without replacing a concurrent destination."""
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin" and hasattr(libc, "renamex_np"):
        rename = libc.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(os.fsencode(staged), os.fsencode(destination), 4)  # RENAME_EXCL
    elif sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        rename = libc.renameat2
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        result = rename(-100, os.fsencode(staged), -100, os.fsencode(destination), 1)
    else:
        raise SharingError("atomic non-overwriting downloads require Linux or macOS")
    if result:
        raise SharingError(
            "cannot install download: destination exists or filesystem refused rename"
        )
