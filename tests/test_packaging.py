"""Build the sdist and wheel the way a release does (``uv build``) and check their contents."""

import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[list[str], list[str]]:
    """
    Build a copy of the project with a fake UI build and some internal docs.

    The copy holds the packaging inputs only, so the build is fast and never writes into
    the checkout. ``uv build`` with no flags builds the sdist first, then the wheel from
    the sdist, as a release does.

    Returns
    -------
    tuple[list[str], list[str]]
        The sdist member names (without the top folder) and the wheel member names.
    """
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not on PATH")
    src = tmp_path_factory.mktemp("pkg") / "hypothex"
    src.mkdir()
    for name in ("pyproject.toml", "README.md", ".gitignore"):
        shutil.copy2(ROOT / name, src / name)
    shutil.copytree(
        ROOT / "src",
        src / "src",
        ignore=shutil.ignore_patterns("__pycache__", "ui_dist"),
    )
    shutil.copytree(ROOT / "skills", src / "skills")
    # Git-ignored UI build (bun run build writes it) and internal docs that stay out.
    ui = src / "src" / "hypothex" / "ui_dist"
    (ui / "assets").mkdir(parents=True)
    (ui / "index.html").write_text("<!doctype html>")
    (ui / "assets" / "app.js").write_text("")
    for internal in ("docs/superpowers/plans/p.md", "docs/mockups/m.html", ".superpowers/n.md"):
        (src / internal).parent.mkdir(parents=True, exist_ok=True)
        (src / internal).write_text("internal")
    (src / "docs" / "index.rst").write_text("Hypothex\n========\n")
    out = src / "dist"
    subprocess.run([uv, "build", "--out-dir", str(out)], cwd=src, check=True, capture_output=True)
    with tarfile.open(next(out.glob("*.tar.gz"))) as sdist:
        sdist_names = [n.split("/", 1)[1] for n in sdist.getnames() if "/" in n]
    with zipfile.ZipFile(next(out.glob("*.whl"))) as wheel:
        wheel_names = wheel.namelist()
    return sdist_names, wheel_names


def test_wheel_built_from_the_sdist_has_the_ui(built: tuple[list[str], list[str]]) -> None:
    sdist, wheel = built
    assert "src/hypothex/ui_dist/index.html" in sdist
    assert "hypothex/ui_dist/index.html" in wheel
    assert "hypothex/ui_dist/assets/app.js" in wheel
