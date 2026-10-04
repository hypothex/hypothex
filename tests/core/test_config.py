from pathlib import Path

import pytest
from pydantic import ValidationError

from hypothex.core.config import (
    CONFIG_FILENAME,
    MetricSpec,
    find_repo_root,
    load_project_config,
    parse_metric_key,
    parse_metric_version,
    render_template,
    starter_config,
    template_fields,
    template_var_hint,
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
    with pytest.raises(ConfigError, match="bogus: Extra inputs are not permitted"):
        load_project_config(_write(tmp_path, VALID + "\nbogus: 1\n"))


def test_validation_errors_are_one_brief_line_per_problem(tmp_path: Path) -> None:
    text = VALID.replace("project: deepretro", "project: Ünicode") + "\nbogus: 1\n"
    with pytest.raises(ConfigError) as caught:
        load_project_config(_write(tmp_path, text))
    message = str(caught.value)
    assert message.endswith(
        "hypothex.yaml: project: String should match pattern '^[a-z0-9][a-z0-9_.-]*$'; "
        "bogus: Extra inputs are not permitted"
    )
    assert "pydantic.dev" not in message and "\n" not in message


def test_a_model_check_error_has_no_location_prefix(tmp_path: Path) -> None:
    text = VALID.replace("dataset: uspto50k", "dataset: missing")
    with pytest.raises(ConfigError) as caught:
        load_project_config(_write(tmp_path, text))
    assert str(caught.value).endswith("hypothex.yaml: task 'uspto-topk': unknown dataset 'missing'")


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


@pytest.mark.parametrize(
    ("name", "hint"),
    [
        ("seed", "seed (--seed N; API/MCP: seed)"),
        ("config", "config (--config PATH)"),
        ("checkpoint", "checkpoint (set by hx reinfer, or --var checkpoint=VALUE;"),
        ("dataset.path", "dataset.path (--task NAME; API/MCP: task)"),
        ("beam", "beam (--var beam=VALUE; API: vars, MCP: template_vars)"),
    ],
)
def test_a_missing_template_variable_names_the_way_to_set_it(name: str, hint: str) -> None:
    with pytest.raises(TemplateError) as caught:
        render_template(f"run {{{name}}}", {})
    assert hint in str(caught.value)
    assert template_var_hint(name) in str(caught.value)


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
    assert cfg.tasks["example-test"].kind == "generic"


def test_task_kind_and_view_fields_default(tmp_path: Path) -> None:
    task = load_project_config(_write(tmp_path, VALID)).tasks["uspto-topk"]
    assert task.kind == "generic"
    assert task.views == {}
    assert task.baseline is None
    assert task.version_param == "version"


def test_task_kind_and_views_load(tmp_path: Path) -> None:
    text = VALID.replace(
        "    primary: topk/k=1\n",
        "    primary: topk/k=1\n"
        "    kind: system_bench\n"
        "    baseline: tag:baseline\n"
        "    version_param: prompt_version\n"
        "    views:\n"
        "      route-quality:\n"
        "        title: route quality\n"
        "        panels: [{type: leaderboard}]\n",
    )
    task = load_project_config(_write(tmp_path, text)).tasks["uspto-topk"]
    assert task.kind == "system_bench"
    assert task.baseline == "tag:baseline"
    assert task.version_param == "prompt_version"
    assert task.views == {
        "route-quality": {"title": "route quality", "panels": [{"type": "leaderboard"}]}
    }


@pytest.mark.parametrize(
    ("addition", "message"),
    [
        ("    kind: benchmark\n", "kind"),
        ("    version_param: ''\n", "version_param"),
        ("    views: {Route: {title: x}}\n", "view name 'Route' must match"),
        ("    views: {overview: {title: x}}\n", "reserved"),
        ("    views: {a.b: {title: x}}\n", "view name 'a.b' must match"),
    ],
)
def test_invalid_task_kind_and_view_names(tmp_path: Path, addition: str, message: str) -> None:
    text = VALID.replace("    primary: topk/k=1\n", "    primary: topk/k=1\n" + addition)
    with pytest.raises(ConfigError, match=message):
        load_project_config(_write(tmp_path, text))


LOOP_LINE = "            spec: &s {mark: point, layer: [*s]}"


def _line_of(text: str, needle: str) -> int:
    return next(i for i, row in enumerate(text.splitlines(), 1) if needle in row)


def test_inline_view_anchors_and_aliases_are_rejected_with_their_line(tmp_path: Path) -> None:
    # regression: this inline view contains itself; it loaded, then views recursed forever
    loop = (
        "    views:\n      loop:\n        title: loop\n        panels:\n"
        f"          - type: vega_lite\n{LOOP_LINE}\n"
    )
    text = VALID.replace("    primary: topk/k=1\n", "    primary: topk/k=1\n" + loop)
    line = _line_of(text, LOOP_LINE)
    with pytest.raises(
        ConfigError, match=rf"YAML anchors and aliases are not allowed in views \(line {line}\)"
    ):
        load_project_config(_write(tmp_path, text))
    # an alias inside views to an anchor outside them is rejected as well
    text = VALID.replace("    split: test\n", "    split: &sp test\n").replace(
        "    primary: topk/k=1\n", "    primary: topk/k=1\n    views: {v: {title: *sp}}\n"
    )
    line = _line_of(text, "views: {v: {title: *sp}}")
    with pytest.raises(ConfigError, match=rf"not allowed in views \(line {line}\)"):
        load_project_config(_write(tmp_path, text))


@pytest.mark.parametrize(
    "views",
    [
        "{loop: {title: loop, panels: [{type: vega_lite, spec: &s {mark: point, layer: [*s]}}]}}",
        "{v: {title: x}}",
    ],
)
def test_views_key_written_as_an_alias_is_resolved(tmp_path: Path, views: str) -> None:
    # regression: `*vk:` names `views` through an anchor defined elsewhere, which hid
    # the self-referencing view below it from a check that only read plain keys
    text = VALID.replace("    split: test\n", "    split: test\n    description: &vk views\n")
    text = text.replace("    primary: topk/k=1\n", f"    primary: topk/k=1\n    *vk: {views}\n")
    line = _line_of(text, "*vk:")
    with pytest.raises(
        ConfigError, match=rf"YAML anchors and aliases are not allowed in views \(line {line}\)"
    ):
        load_project_config(_write(tmp_path, text))


def test_deep_or_cyclic_yaml_is_a_config_error(tmp_path: Path) -> None:
    # regression: 600 nested lists raised RecursionError inside the YAML loader
    deep = "[" * 600 + "]" * 600
    text = VALID.replace("    split: test\n", f"    split: test\n    description: {deep}\n")
    line = _line_of(text, "description:")
    with pytest.raises(
        ConfigError, match=rf"YAML nested too deeply \(over 64 levels\) \(line {line}\)"
    ):
        load_project_config(_write(tmp_path, text))
    # a cycle outside views: metric params that contain themselves
    text = VALID.replace("    params: {k: [1, 5]}\n", "    params: &p {k: [1, 5], again: *p}\n")
    line = _line_of(text, "again: *p")
    with pytest.raises(ConfigError, match=rf"YAML aliases must not form a cycle \(line {line}\)"):
        load_project_config(_write(tmp_path, text))


def test_anchors_outside_views_stay_allowed(tmp_path: Path) -> None:
    text = VALID.replace(
        "    path: data/test.jsonl\n", "    path: &test data/test.jsonl\n"
    ).replace("test: data/test.jsonl}", "test: *test}")
    assert "*test" in text
    cfg = load_project_config(_write(tmp_path, text))
    assert cfg.datasets["uspto50k"].splits["test"] == "data/test.jsonl"
    shared = VALID.replace("    params: {k: [1, 5]}\n", "    params: &p {k: [1, 5]}\n")
    shared = shared.replace("    split: test\n", "    split: test\n    description: *p\n")
    assert "*p" in shared  # a shared (not cyclic) mapping: passes the guards
    with pytest.raises(ConfigError, match="description"):  # then fails the model: not a str
        load_project_config(_write(tmp_path, shared))


def test_metric_unit_is_optional_and_short() -> None:
    assert MetricSpec(version="v1", fn="m:f").unit == ""
    assert MetricSpec(version="v1", fn="m:f", unit="ms").unit == "ms"
    with pytest.raises(ValidationError):
        MetricSpec(version="v1", fn="m:f", unit="milliseconds")
