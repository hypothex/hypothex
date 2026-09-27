"""Read git state and build worktrees for exact reruns."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from hypothex.core.errors import GitError
from hypothex.core.records import GitInfo

DIFF_LIMIT_BYTES = 5 * 1024 * 1024
UNTRACKED_LIST_LIMIT = 20


@dataclass(frozen=True)
class DiffCapture:
    """
    Uncommitted changes at launch time.

    Parameters
    ----------
    diff : bytes or None
        Raw ``git diff HEAD --binary`` output (bytes, since tracked files need
        not be UTF-8), or None when clean, not a repo, or too large.
    stat : str
        ``git diff HEAD --stat`` output (undecodable bytes replaced).
    too_large : bool
        True when the diff exceeded the size limit and was dropped.
    """

    diff: bytes | None
    stat: str
    too_large: bool


def _git_bytes(
    path: Path, *args: str, input_bytes: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", "-C", str(path), *args],
            capture_output=True,
            input=input_bytes,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitError("git is not installed") from exc


def _git(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    raw = _git_bytes(path, *args)
    return subprocess.CompletedProcess(
        raw.args,
        raw.returncode,
        raw.stdout.decode("utf-8", errors="replace"),
        raw.stderr.decode("utf-8", errors="replace"),
    )


def strip_credentials(url: str) -> str:
    """
    Remove userinfo (user name, password, or token) from a remote URL.

    scp-style remotes such as ``git@github.com:org/repo.git`` carry no
    secret and are returned unchanged.

    Parameters
    ----------
    url : str
        A git remote URL.

    Returns
    -------
    str
        The URL without any ``user[:password]@`` part.

    Examples
    --------
    >>> strip_credentials("https://user:token@example.com/org/repo.git")
    'https://example.com/org/repo.git'
    >>> strip_credentials("git@github.com:org/repo.git")
    'git@github.com:org/repo.git'
    """
    parts = urlsplit(url)
    if "@" not in parts.netloc:
        return url
    return urlunsplit(parts._replace(netloc=parts.netloc.rpartition("@")[2]))


def head_commit(path: Path) -> str | None:
    """
    Return the HEAD commit sha of the repo containing ``path``.

    Parameters
    ----------
    path : Path
        Directory inside (or outside) a git repo.

    Returns
    -------
    str or None
        The commit sha, or None when ``path`` is not inside a git repo.
    """
    out = _git(path, "rev-parse", "HEAD")
    return out.stdout.strip() if out.returncode == 0 else None


def untracked_files(path: Path) -> list[str]:
    """
    List untracked, non-ignored files of the whole repo containing ``path``.

    Parameters
    ----------
    path : Path
        Directory inside a git repo (any subdirectory works).

    Returns
    -------
    list of str
        Paths relative to the repo root, in git's (sorted) order; empty when
        ``path`` is not inside a git repo.
    """
    top = _git(path, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        return []
    out = _git(Path(top.stdout.strip()), "ls-files", "--others", "--exclude-standard", "-z")
    if out.returncode != 0:
        return []
    return [name for name in out.stdout.split("\0") if name]


def git_info(path: Path) -> GitInfo:
    """
    Describe the git state of ``path``.

    ``dirty`` counts tracked changes only (staged or unstaged), matching what
    ``capture_diff`` saves. Untracked files are reported separately.

    Parameters
    ----------
    path : Path
        Directory inside (or outside) a git repo.

    Returns
    -------
    GitInfo
        Empty (all None) when ``path`` is not inside a git repo.
    """
    commit = head_commit(path)
    if commit is None:
        return GitInfo()
    branch = _git(path, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or None
    remote = _git(path, "remote", "get-url", "origin")
    status = _git(path, "status", "--porcelain", "--untracked-files=no")
    untracked = untracked_files(path)
    return GitInfo(
        repo=strip_credentials(remote.stdout.strip()) if remote.returncode == 0 else None,
        commit=commit,
        branch=branch,
        dirty=bool(status.stdout.strip()),
        untracked_count=len(untracked),
        untracked=untracked[:UNTRACKED_LIST_LIMIT],
    )


def git_state_label(info: GitInfo) -> str:
    """
    One-line wording of a run's git state for run pages and ``hx show``.

    Parameters
    ----------
    info : GitInfo
        The run's recorded git state.

    Returns
    -------
    str
        ``"no git"``, ``"dirty"``, ``"dirty, N untracked"``,
        ``"untracked files only (N)"``, or ``"clean"``.

    Examples
    --------
    >>> git_state_label(GitInfo(commit="abc", untracked_count=2))
    'untracked files only (2)'
    >>> git_state_label(GitInfo(commit="abc", dirty=True))
    'dirty'
    """
    if info.commit is None:
        return "no git"
    if info.dirty:
        return f"dirty, {info.untracked_count} untracked" if info.untracked_count else "dirty"
    if info.untracked_count:
        return f"untracked files only ({info.untracked_count})"
    return "clean"


def capture_diff(path: Path, limit: int = DIFF_LIMIT_BYTES) -> DiffCapture:
    """
    Capture ``git diff HEAD`` (tracked files only).

    Parameters
    ----------
    path : Path
        Directory inside the repo.
    limit : int
        Maximum diff size in bytes; larger diffs are not stored.

    Returns
    -------
    DiffCapture
        ``diff`` is None when clean, not a repo, or too large.
    """
    out = _git_bytes(path, "diff", "HEAD", "--binary")
    if out.returncode != 0:
        return DiffCapture(diff=None, stat="", too_large=False)
    stat = _git(path, "diff", "HEAD", "--stat").stdout
    if len(out.stdout) > limit:
        return DiffCapture(diff=None, stat=stat, too_large=True)
    return DiffCapture(diff=out.stdout or None, stat=stat, too_large=False)


def commit_exists(repo: Path, commit: str) -> bool:
    """
    Check whether ``commit`` exists in ``repo``.

    Parameters
    ----------
    repo : Path
        A git repository.
    commit : str
        A commit sha.

    Returns
    -------
    bool
        True if the commit object exists in ``repo``.
    """
    return _git(repo, "cat-file", "-e", f"{commit}^{{commit}}").returncode == 0


def create_worktree(repo: Path, commit: str, dest: Path, diff: bytes | None) -> Path:
    """
    Check out ``commit`` into a new detached worktree and apply ``diff``.

    Parameters
    ----------
    repo : Path
        The source git repository.
    commit : str
        The commit sha to check out.
    dest : Path
        Destination directory for the new worktree.
    diff : bytes or None
        A raw diff (as captured by ``capture_diff``) to apply on top of the
        checkout, or None.

    Returns
    -------
    Path
        ``dest``, once the worktree is ready.

    Raises
    ------
    GitError
        If the commit is missing or the diff does not apply.
    """
    if not commit_exists(repo, commit):
        raise GitError(f"commit {commit} not found in {repo}; it may have been rebased away")
    dest.parent.mkdir(parents=True, exist_ok=True)
    added = _git(repo, "worktree", "add", "--detach", str(dest), commit)
    if added.returncode != 0:
        raise GitError(f"git worktree add failed: {added.stderr.strip()}")
    if diff:
        applied = _git_bytes(dest, "apply", "--whitespace=nowarn", "-", input_bytes=diff)
        if applied.returncode != 0:
            stderr = applied.stderr.decode("utf-8", errors="replace").strip()
            raise GitError(f"could not apply the saved diff: {stderr}")
    return dest
