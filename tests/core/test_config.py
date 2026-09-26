from pathlib import Path

import pytest

from hypothex.core.config import (
    CONFIG_FILENAME,
    find_repo_root,
    load_project_config,
    parse_metric_key,
    parse_metric_version,
    render_template,
    starter_config,
    template_fields,
)
from hypothex.core.errors import ConfigError, TemplateError

VALID = """
project: deepretro
datasets:
  uspto50k:
    version: v1
    path: data/test.jsonl
    splits: {train: data/train.jsonl, test: data/test.jsonl}
metrics:
  topk:
    version: v2
    fn: deepretro.eval:topk
    params: {k: [1, 5]}
tasks:
  uspto-topk:
    dataset: uspto50k
    split: test
    metrics: [topk]
    primary: topk/k=1
stages:
  infer: python infer.py --ckpt {checkpoint} --out {run_dir}/predictions --beam {beam}
"""


def _write(tmp_path: Path, text: str) -> Path:
    (tmp_path / CONFIG_FILENAME).write_text(text)
    return tmp_path


def test_valid_config_loads(tmp_path: Path) -> None:
    cfg = load_project_config(_write(tmp_path, VALID))
    assert cfg.project == "deepretro"
    assert cfg.metrics["topk"].version == "v2"
    assert cfg.datasets["uspto50k"].path_for("test") == "data/test.jsonl"
    assert cfg.datasets["uspto50k"].path_for(None) == "data/test.jsonl"
    with pytest.raises(ConfigError, match="no split"):
        cfg.datasets["uspto50k"].path_for("valid")


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("dataset: uspto50k", "dataset: missing", "unknown dataset"),
        ("metrics: [topk]", "metrics: [nope]", "unknown metric"),
        ("primary: topk/k=1", "primary: other/k=1", "primary"),
        ("split: test", "split: valid", "no split"),
        ("project: deepretro", "project: Deep Retro", "project"),
    ],
)
def test_invalid_configs_raise(tmp_path: Path, old: str, new: str, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        load_project_config(_write(tmp_path, VALID.replace(old, new)))


def test_unknown_top_level_key_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="extra"):
        load_project_config(_write(tmp_path, VALID + "\nbogus: 1\n"))


def test_missing_file_mentions_init(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="hx init"):
        load_project_config(tmp_path)


def test_templates() -> None:
    tpl = "python x.py --out {run_dir}/p --data {dataset.path} --beam {beam}"
    assert template_fields(tpl) == {"run_dir", "dataset.path", "beam"}
    out = render_template(tpl, {"run_dir": "/r", "dataset.path": "/d", "beam": "5"})
    assert out == "python x.py --out /r/p --data /d --beam 5"
    with pytest.raises(TemplateError, match="beam"):
        render_template(tpl, {"run_dir": "/r", "dataset.path": "/d"})


def test_metric_ref_parsing() -> None:
    assert parse_metric_key("topk/k=1") == ("topk", "k=1")
    assert parse_metric_key("acc") == ("acc", "value")
    assert parse_metric_version("topk@v2") == ("topk", "v2")
    assert parse_metric_version("topk") == ("topk", None)


def test_find_repo_root_walks_up(tmp_path: Path) -> None:
    _write(tmp_path, VALID)
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    assert find_repo_root(deep) == tmp_path.resolve()
    with pytest.raises(ConfigError):
        find_repo_root(Path("/"))


def test_starter_config_is_valid(tmp_path: Path) -> None:
    cfg = load_project_config(_write(tmp_path, starter_config("my-proj")))
    assert cfg.project == "my-proj"
