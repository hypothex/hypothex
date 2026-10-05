from pathlib import Path

import pytest

from hypothex.remote import ssh


def test_staged_pull_installs_only_after_success(tmp_path: Path) -> None:
    destination = tmp_path / "nested" / "output"
    work = tmp_path / "trusted"
    with ssh.staged_pull(destination, work=work) as part:
        part.write_bytes(b"complete")
        assert part.is_relative_to(work / "stage")
        assert not destination.parent.exists()
    assert destination.read_bytes() == b"complete"
    assert list((work / "stage").iterdir()) == []


@pytest.mark.parametrize("existing", [False, True])
def test_staged_pull_failure_preserves_destinations(tmp_path: Path, existing: bool) -> None:
    destination = tmp_path / "nested" / "output"
    if existing:
        destination.mkdir(parents=True)
        (destination / "old").write_bytes(b"keep")
    work = tmp_path / "trusted"
    with (
        pytest.raises(RuntimeError, match="failed stream"),
        ssh.staged_pull(destination, work=work) as part,
    ):
        part.mkdir()
        (part / "partial").write_bytes(b"incomplete")
        raise RuntimeError("failed stream")
    if existing:
        assert list(destination.iterdir()) == [destination / "old"]
        assert (destination / "old").read_bytes() == b"keep"
    else:
        assert not destination.parent.exists()
    assert list((work / "stage").iterdir()) == []
