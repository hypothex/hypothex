from pathlib import Path

import pytest

from hypothex.core.errors import GitError
from hypothex.core.gitinfo import capture_diff, create_worktree, git_info, head_commit
from tests.factories import git, init_git_repo


def test_git_info_clean_and_dirty(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.txt").write_text("one\n")
    sha = init_git_repo(repo)
    info = git_info(repo)
    assert info.commit == sha and info.branch == "main" and not info.dirty
    (repo / "a.txt").write_text("two\n")
    assert git_info(repo).dirty
    assert head_commit(repo) == sha


def test_non_git_directory_gives_empty_info(tmp_path: Path) -> None:
    info = git_info(tmp_path)
    assert info.commit is None and info.branch is None and not info.dirty
    assert capture_diff(tmp_path).diff is None


def test_capture_diff_and_size_limit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.txt").write_text("one\n")
    init_git_repo(repo)
    assert capture_diff(repo).diff is None
    (repo / "a.txt").write_text("two\n")
    cap = capture_diff(repo)
    assert cap.diff is not None and b"+two" in cap.diff and "a.txt" in cap.stat
    big = capture_diff(repo, limit=10)
    assert big.diff is None and big.too_large


def test_create_worktree_applies_diff(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.txt").write_text("one\n")
    sha = init_git_repo(repo)
    (repo / "a.txt").write_text("patched\n")
    diff = capture_diff(repo).diff
    git(repo, "checkout", "--", "a.txt")
    (repo / "a.txt").write_text("later\n")
    git(repo, "commit", "-qam", "later")
    wt = create_worktree(repo, sha, tmp_path / "wt", diff)
    assert (wt / "a.txt").read_text() == "patched\n"
    assert head_commit(wt) == sha


def test_create_worktree_missing_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)
    with pytest.raises(GitError, match="not found"):
        create_worktree(repo, "0" * 40, tmp_path / "wt", None)


def test_git_info_strips_credentials_from_remote(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_git_repo(repo)
    git(repo, "remote", "add", "origin", "https://user:s3cret-token@example.com:8443/org/r.git")
    assert git_info(repo).repo == "https://example.com:8443/org/r.git"
    git(repo, "remote", "set-url", "origin", "https://ghp_tokenonly@github.com/org/r.git")
    assert git_info(repo).repo == "https://github.com/org/r.git"


def test_git_info_keeps_credential_free_remotes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_git_repo(repo)
    git(repo, "remote", "add", "origin", "git@github.com:org/r.git")
    assert git_info(repo).repo == "git@github.com:org/r.git"
    git(repo, "remote", "set-url", "origin", "https://github.com/org/r.git")
    assert git_info(repo).repo == "https://github.com/org/r.git"


def test_capture_diff_of_non_utf8_file_round_trips(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "latin.txt").write_bytes("caf\xe9 old\n".encode("latin-1"))
    sha = init_git_repo(repo)
    (repo / "latin.txt").write_bytes("caf\xe9 new \xff\n".encode("latin-1"))
    cap = capture_diff(repo)
    assert isinstance(cap.diff, bytes) and b"caf\xe9 new \xff" in cap.diff
    assert "latin.txt" in cap.stat
    git(repo, "checkout", "--", "latin.txt")
    wt = create_worktree(repo, sha, tmp_path / "wt", cap.diff)
    assert (wt / "latin.txt").read_bytes() == "caf\xe9 new \xff\n".encode("latin-1")
