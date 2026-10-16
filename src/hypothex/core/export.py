"""Paper tables from leaderboards and comparisons: LaTeX (booktabs), Markdown, CSV.

``leaderboard_table`` and ``compare_table`` build an ``ExportTable`` (numbers,
marks, footnotes); ``render`` turns it into text. Output is deterministic: the
same table and options give byte-identical text (golden files in
``tests/core/golden/export``).
"""

from __future__ import annotations

import csv
import io
import math
import unicodedata
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from hypothex.core.config import ProjectConfig, metric_ref, parse_metric_key
from hypothex.core.context import Context
from hypothex.core.errors import RunError
from hypothex.core.headlines import metric_unit, value_format
from hypothex.core.leaderboard import (
    BaselineRow,
    Leaderboard,
    LeaderboardRow,
    group_label,
    key_higher_is_better,
)
from hypothex.core.queries import get_leaderboard, resolve_task

ExportFormat = Literal["latex", "markdown", "csv"]
NoiseMode = Literal["both", "seed", "test", "none"]
EXTENSIONS: dict[str, str] = {"latex": "tex", "markdown": "md", "csv": "csv"}
MARK_SINGLE = "¹"
MARK_NOISE = "†"
MARK_VERSION = "‡"
IDENTICAL = "◇"


class ExportOptions(BaseModel, extra="forbid"):
    """What to export and how to show noise."""

    format: ExportFormat = "markdown"
    metrics: list[str] | None = None
    primary: str | None = None
    """Task ranking metric/key; None retains configured primary. Refused for run comparisons."""
    noise: NoiseMode = "both"
    digits: int = Field(3, ge=0, le=6)
    percent: bool = False
    top: int | None = Field(None, ge=1)
    groups: list[str] | None = None
    baselines: bool = True
    caption: str | None = None
    label: str | None = None
    standalone: bool = False
    mark_noise: bool = True


class ExportCell(BaseModel):
    """One metric of one row."""

    mean: float | None
    std: float | None
    n: int
    identical: bool
    lo: float | None
    hi: float | None
    method: Literal["wilson", "bootstrap"] | None
    n_examples: int | None
    best: bool


class ExportRow(BaseModel):
    """A seed group, a run (compare), or a paper baseline."""

    kind: Literal["group", "run", "baseline"]
    label: str
    key: str
    n: int
    cells: dict[str, ExportCell]
    within_noise: bool
    version_mismatch: bool
    source: str | None


class ExportTable(BaseModel):
    """Columns (metric refs), their directions, rows, and footnotes."""

    title: str
    columns: list[str]
    higher_is_better: dict[str, bool]
    rows: list[ExportRow]
    footnotes: list[str]


def _empty_cell() -> ExportCell:
    return ExportCell(
        mean=None, std=None, n=0, identical=False, lo=None, hi=None, method=None,
        n_examples=None, best=False,
    )  # fmt: skip


def _columns(board: Leaderboard, opts: ExportOptions) -> list[str]:
    if opts.metrics:
        return list(dict.fromkeys(metric_ref(m) for m in opts.metrics))
    present = {key for row in board.rows for key in row.scores}
    return [board.primary, *sorted(present - {board.primary})]


def _group_cell(
    row: LeaderboardRow, column: str, primary: str, opts: ExportOptions, scale: float
) -> ExportCell:
    stats = row.scores.get(column)
    if stats is None:
        return _empty_cell()
    seed = opts.noise in ("both", "seed")
    values = row.seed_values.get(column, [])
    identical = seed and len(values) > 1 and all(v == values[0] for v in values)
    interval = row.test_interval
    if column != primary or opts.noise not in ("both", "test"):
        interval = None
    return ExportCell(
        mean=stats.mean * scale,
        std=stats.std * scale if seed and stats.n > 1 else None,
        n=stats.n,
        identical=identical,
        lo=interval.lo * scale if interval is not None else None,
        hi=interval.hi * scale if interval is not None else None,
        method=interval.method if interval is not None else None,
        n_examples=interval.n if interval is not None else None,
        best=False,
    )


def _baseline_row(
    base: BaselineRow, columns: list[str], opts: ExportOptions, scales: dict[str, float]
) -> ExportRow:
    cells: dict[str, ExportCell] = {}
    shown: set[str] = set()
    for column in columns:
        scale = scales[column]
        value = base.values.get(column)
        if value is None:
            cells[column] = _empty_cell()
            continue
        shown.add(parse_metric_key(column)[0])
        std = base.std.get(column) if opts.noise in ("both", "seed") else None
        cell = _empty_cell().model_copy(
            update={"mean": value * scale, "std": None if std is None else std * scale}
        )
        cells[column] = cell
    mismatch = any(not base.version_match.get(metric, False) for metric in shown)
    return ExportRow(
        kind="baseline",
        label=base.name,
        key=base.name,
        n=0,
        cells=cells,
        within_noise=False,
        version_mismatch=mismatch,
        source=base.source,
    )


def mark_best(rows: list[ExportRow], higher_is_better: dict[str, bool]) -> None:
    """
    Flag the best non-baseline mean of each column (every tie is flagged).

    Parameters
    ----------
    rows : list of ExportRow
        Rows to update in place.
    higher_is_better : dict of str to bool
        Direction per column.
    """
    for row in rows:
        for cell in row.cells.values():
            cell.best = False
    ranked = [r for r in rows if r.kind != "baseline"]
    for column, higher in higher_is_better.items():
        means: list[float] = []
        for row in ranked:
            cell = row.cells.get(column)
            if cell is not None and cell.mean is not None:
                means.append(cell.mean)
        if not means:
            continue
        best = max(means) if higher else min(means)
        for row in ranked:
            cell = row.cells.get(column)
            if cell is not None and cell.mean == best:
                row.cells[column] = cell.model_copy(update={"best": True})


def footnotes(
    versions: dict[str, str],
    rows: list[ExportRow],
    opts: ExportOptions,
    *,
    scaled: bool,
    extra: list[str] | None = None,
) -> list[str]:
    """
    Build a table's footnotes in their fixed order.

    Parameters
    ----------
    versions : dict of str to str
        Metric name -> version, for the metrics shown.
    rows : list of ExportRow
        The table's rows.
    opts : ExportOptions
        Export options (``mark_noise``).
    scaled : bool
        Whether values were multiplied by 100.
    extra : list of str, optional
        Notes added before the baselines line.

    Returns
    -------
    list of str
    """
    notes: list[str] = []
    if versions:
        notes.append(
            "metric versions: " + ", ".join(f"{m}@{v}" for m, v in sorted(versions.items()))
        )
    groups = [r for r in rows if r.kind == "group"]
    marks: list[str] = []
    if any(r.n == 1 for r in groups):
        marks.append(f"{MARK_SINGLE} single seed")
    if any(c.identical for r in groups for c in r.cells.values()):
        marks.append(f"{IDENTICAL}×n identical seeds")
    if opts.mark_noise and any(r.within_noise for r in rows):
        marks.append(f"{MARK_NOISE} within noise of best")
    if any(r.version_mismatch for r in rows):
        marks.append(f"{MARK_VERSION} metric version differs from the paper")
    if marks:
        notes.append(" · ".join(marks))
    methods = sorted({c.method for r in rows for c in r.cells.values() if c.method})
    if methods:
        notes.append(f"[lo, hi] 95% test-set interval ({', '.join(methods)})")
    if scaled:
        notes.append("values ×100")
    notes.extend(extra or [])
    base = [r for r in rows if r.kind == "baseline"]
    if base:
        notes.append("baselines: " + "; ".join(f"{r.label} — {r.source}" for r in base))
    return notes


def leaderboard_table(
    board: Leaderboard,
    opts: ExportOptions,
    *,
    directions: dict[str, bool] | None = None,
    value_formats: dict[str, str] | None = None,
) -> ExportTable:
    """
    Turn a leaderboard into an export table.

    Parameters
    ----------
    board : Leaderboard
        A built leaderboard (ranked rows, test-set intervals, baselines).
    opts : ExportOptions
        Columns, noise, rows, and marks.
    directions : dict of str to bool, optional
        Column ref (``latency/p95``), else metric name -> higher is better, for
        columns other than the primary.
    value_formats : dict of str to str, optional
        Column ref -> format. The primary defaults to ``board.value_format``;
        unspecified secondary columns default to ``number`` (never guess a unit).

    Returns
    -------
    ExportTable
        Ranked groups, then baselines; best cells flagged; footnotes.
    """
    columns = _columns(board, opts)
    given = directions or {}
    higher = {
        c: board.higher_is_better
        if c == board.primary
        else given.get(c, given.get(parse_metric_key(c)[0], True))
        for c in columns
    }
    formats = {board.primary: board.value_format, **(value_formats or {})}
    scales = {c: 100.0 if opts.percent and formats.get(c) == "fraction" else 1.0 for c in columns}
    scaled = [c for c in columns if scales[c] == 100.0]
    chosen = board.rows
    if opts.groups:
        wanted = set(opts.groups)
        chosen = [r for r in chosen if r.group_id in wanted or r.label in wanted]
    if opts.top is not None:
        chosen = chosen[: opts.top]
    rows = [
        ExportRow(
            kind="group",
            label=row.label,
            key=row.group_id,
            n=row.n,
            cells={c: _group_cell(row, c, board.primary, opts, scales[c]) for c in columns},
            within_noise=row.within_noise_of_best is True,
            version_mismatch=False,
            source=None,
        )
        for row in chosen
    ]
    mark_best(rows, higher)
    if opts.baselines:
        rows += [_baseline_row(b, columns, opts, scales) for b in board.baselines]
    shown = {parse_metric_key(c)[0] for c in columns}
    versions = {m: v for m, v in board.metric_versions.items() if m in shown}
    return ExportTable(
        title=f"{board.project}/{board.task}",
        columns=columns,
        higher_is_better=higher,
        rows=rows,
        footnotes=footnotes(
            versions,
            rows,
            opts,
            scaled=False,
            extra=["values ×100: " + ", ".join(scaled)] if scaled else [],
        ),
    )


CSV_HEADER = (
    "kind", "label", "key", "n", "metric", "mean", "std", "identical", "ci_lo", "ci_hi",
    "ci_method", "n_examples", "best", "within_noise", "version_mismatch", "source",
)  # fmt: skip
_LATEX_SPECIAL = {
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    "\\": r"\textbackslash{}",
}
_LATEX_UNICODE = {
    "±": r"$\pm$",
    "×": r"$\times$",
    "◇": r"$\diamond$",
    "¹": r"$^{1}$",
    "†": r"$^{\dagger}$",
    "‡": r"$^{\ddagger}$",
    "↑": r"$\uparrow$",
    "↓": r"$\downarrow$",
    "—": "---",
    "–": "--",
    "…": r"\ldots{}",
    "·": r"$\cdot$",
    "→": r"$\rightarrow$",
    "≠": r"$\neq$",
    "▲": r"$\blacktriangle$",
}


def latex_escape(text: str) -> str:
    """
    Escape text for LaTeX; the result is ASCII plus LaTeX commands.

    The ten special characters are escaped, the table glyphs become math
    commands, accented letters lose their accent, and any other non-ASCII
    character becomes ``?``.

    Parameters
    ----------
    text : str

    Returns
    -------
    str

    Examples
    --------
    >>> latex_escape("lr_1e-4 & 95%")
    'lr\\\\_1e-4 \\\\& 95\\\\%'
    """
    out: list[str] = []
    for ch in text:
        if ch in _LATEX_SPECIAL:
            out.append(_LATEX_SPECIAL[ch])
        elif ch in _LATEX_UNICODE:
            out.append(_LATEX_UNICODE[ch])
        elif ch in "\r\n\t":
            out.append(" ")
        elif ch.isascii():
            out.append(ch)
        else:
            plain = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode()
            out.append("".join(_LATEX_SPECIAL.get(c, c) for c in plain) or "?")
    return "".join(out)


def fmt_number(x: float, digits: int) -> str:
    """
    Format a number with fixed digits, never as ``-0.000``.

    Parameters
    ----------
    x : float
    digits : int

    Returns
    -------
    str

    Examples
    --------
    >>> fmt_number(0.9126, 3), fmt_number(-0.0001, 3)
    ('0.913', '0.000')
    """
    text = f"{x:.{digits}f}"
    return f"{0.0:.{digits}f}" if float(text) == 0.0 else text


@dataclass(frozen=True)
class _Style:
    missing: str
    pm: str
    identical: Callable[[int], str]
    bold: Callable[[str], str]
    up: str
    down: str


_MARKDOWN = _Style(
    missing="—",
    pm="±",
    identical=lambda n: f"{IDENTICAL}×{n}",
    bold=lambda t: f"**{t}**",
    up="↑",
    down="↓",
)
_LATEX = _Style(
    missing="--",
    pm=r"$\pm$",
    identical=lambda n: rf"$\diamond{{\times}}{n}$",
    bold=lambda t: rf"\textbf{{{t}}}",
    up=r"$\uparrow$",
    down=r"$\downarrow$",
)


def _cell_text(cell: ExportCell | None, digits: int, style: _Style) -> str:
    if cell is None or cell.mean is None:
        return style.missing
    text = fmt_number(cell.mean, digits)
    if cell.identical:
        text += f" ({style.identical(cell.n)})"
    elif cell.std is not None:
        text += f" {style.pm} {fmt_number(cell.std, digits)}"
    if cell.best:
        text = style.bold(text)
    if cell.lo is not None and cell.hi is not None:
        text += f" [{fmt_number(cell.lo, digits)}, {fmt_number(cell.hi, digits)}]"
    return text


def _marked(row: ExportRow, opts: ExportOptions) -> str:
    marks = ""
    if row.kind == "group" and row.n == 1:
        marks += MARK_SINGLE
    if opts.mark_noise and row.within_noise:
        marks += MARK_NOISE
    if row.version_mismatch:
        marks += MARK_VERSION
    return row.label + marks


def _first_header(table: ExportTable) -> str:
    return "run" if any(r.kind == "run" for r in table.rows) else "group"


def _markdown(table: ExportTable, opts: ExportOptions) -> str:
    def escape_cell(text: str) -> str:
        return (
            text.replace("\\", "\\\\")
            .replace("|", "\\|")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
            .replace("\n", "<br>")
        )

    def line(cells: list[str]) -> str:
        return "| " + " | ".join(escape_cell(c) for c in cells) + " |"

    arrows = [
        f"{c} {_MARKDOWN.up if table.higher_is_better[c] else _MARKDOWN.down}"
        for c in table.columns
    ]
    lines = [
        line([_first_header(table), "n", *arrows]),
        "|" + "|".join([":--", "--:", *("--:" for _ in table.columns)]) + "|",
    ]
    baselines_started = False
    for row in table.rows:
        if row.kind == "baseline" and not baselines_started:
            lines.append(line(["*baselines*", "", *("" for _ in table.columns)]))
            baselines_started = True
        n = _MARKDOWN.missing if row.kind == "baseline" else str(row.n)
        cells = [_cell_text(row.cells.get(c), opts.digits, _MARKDOWN) for c in table.columns]
        lines.append(line([_marked(row, opts), n, *cells]))
    if table.footnotes:
        lines.append("")
        lines += ["- " + " ".join(note.splitlines()) for note in table.footnotes]
    return "\n".join(lines) + "\n"


def _latex(table: ExportTable, opts: ExportOptions) -> str:
    def line(cells: list[str]) -> str:
        return " & ".join(cells) + r" \\"

    arrows = [
        f"{latex_escape(c)} {_LATEX.up if table.higher_is_better[c] else _LATEX.down}"
        for c in table.columns
    ]
    lines = [r"% requires \usepackage{booktabs}"]
    if opts.standalone:
        lines += [
            r"\begin{table}[t]",
            r"\centering",
            rf"\caption{{{latex_escape(opts.caption or table.title)}}}",
        ]
        if opts.label:
            lines.append(rf"\label{{{latex_escape(opts.label)}}}")
    lines += [
        rf"\begin{{tabular}}{{l{'r' * (len(table.columns) + 1)}}}",
        r"\toprule",
        line([_first_header(table), "$n$", *arrows]),
        r"\midrule",
    ]
    baselines_started = False
    for row in table.rows:
        if row.kind == "baseline" and not baselines_started:
            lines.append(r"\midrule")
            baselines_started = True
        n = _LATEX.missing if row.kind == "baseline" else str(row.n)
        cells = [_cell_text(row.cells.get(c), opts.digits, _LATEX) for c in table.columns]
        lines.append(line([latex_escape(_marked(row, opts)), n, *cells]))
    lines += [r"\bottomrule", r"\end{tabular}"]
    notes = [latex_escape(note) for note in table.footnotes]
    if opts.standalone:
        if notes:
            lines.append(r"\par\smallskip\footnotesize")
            lines += [note + r" \\" for note in notes[:-1]]
            lines.append(notes[-1])
        lines.append(r"\end{table}")
    else:
        lines += [f"% {note}" for note in notes]
    return "\n".join(lines) + "\n"


def _csv_number(x: float | None) -> str:
    return "" if x is None else repr(float(x))


def _csv_bool(x: bool) -> str:
    return "true" if x else "false"


def _csv(table: ExportTable) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    for row in table.rows:
        for column in table.columns:
            cell = row.cells.get(column) or _empty_cell()
            writer.writerow(
                [
                    row.kind, row.label, row.key, row.n, column, _csv_number(cell.mean),
                    _csv_number(cell.std), _csv_bool(cell.identical), _csv_number(cell.lo),
                    _csv_number(cell.hi), cell.method or "",
                    "" if cell.n_examples is None else cell.n_examples, _csv_bool(cell.best),
                    _csv_bool(row.within_noise), _csv_bool(row.version_mismatch),
                    row.source or "",
                ]
            )  # fmt: skip
    return buffer.getvalue()


def render(table: ExportTable, opts: ExportOptions) -> str:
    """
    Render an export table as LaTeX, Markdown, or CSV.

    Parameters
    ----------
    table : ExportTable
    opts : ExportOptions
        ``format``, ``digits``, ``mark_noise``, ``standalone``, ``caption``, ``label``.

    Returns
    -------
    str
        The text, ending with one newline; identical input gives identical bytes.
    """
    if opts.format == "latex":
        return _latex(table, opts)
    if opts.format == "csv":
        return _csv(table)
    return _markdown(table, opts)


COMPARE_MAX_RUNS = 20


def compare_table(ctx: Context, run_ids: list[str], opts: ExportOptions) -> ExportTable:
    """
    Build a table with one row per run (scores at each project's current versions).

    Parameters
    ----------
    ctx : Context
    run_ids : list of str
        2 to 20 runs, shown in this order.
    opts : ExportOptions
        Columns (``metrics``), ``percent``, ``digits``.

    Returns
    -------
    ExportTable
        ``kind="run"`` rows, ``n=1``, no noise columns.

    Raises
    ------
    RunError
        Fewer than 2 or more than 20 runs, or a shown metric with different
        versions or directions in the runs' projects.
    RunNotFoundError
        An unknown run id.
    """
    if opts.primary is not None:
        raise RunError("primary applies to task export, not run comparison")
    if not 2 <= len(run_ids) <= COMPARE_MAX_RUNS:
        raise RunError(f"compare export takes 2 to {COMPARE_MAX_RUNS} runs")
    records = [ctx.find_record(r) for r in run_ids]
    configs: dict[str, ProjectConfig] = {}
    for record in records:
        if record.project not in configs:
            configs[record.project] = ctx.store.load_project(record.project).config
    scores = ctx.index.scores_for(run_ids)
    values: dict[str, dict[str, float]] = {}
    versions: dict[str, str] = {}
    units: dict[str, set[str]] = defaultdict(set)
    # metric -> version -> first project; effective direction is checked per key below
    seen: dict[str, dict[str, str]] = defaultdict(dict)
    # column -> effective direction (the leaderboard's rule, per run's task kind) -> a run
    ranks: dict[str, dict[bool, str]] = defaultdict(dict)
    for record in records:
        config = configs[record.project]
        current: dict[str, float] = {}
        for score in sorted(scores.get(record.run_id, []), key=lambda s: s.created_at):
            metric = config.metrics.get(score.metric)
            if (
                metric is None
                or score.version != metric.version
                or score.error is not None
                or score.value is None
                or not math.isfinite(score.value)
            ):
                continue
            ref = f"{score.metric}/{score.key}"
            current[ref] = score.value
        values[record.run_id] = current
    primary = next(
        (
            metric_ref(configs[r.project].tasks[r.task].primary)
            for r in records
            if r.task is not None and r.task in configs[r.project].tasks
        ),
        None,
    )
    if opts.metrics:
        columns = list(dict.fromkeys(metric_ref(m) for m in opts.metrics))
    else:
        present = {key for v in values.values() for key in v}
        first = [primary] if primary is not None and primary in present else []
        columns = [*first, *sorted(present - set(first))]
    # Missing scores do not erase a project's metric definition. Otherwise an
    # explicitly selected missing key would silently change its arrow, and a
    # missing result could hide an incompatible version in another project.
    for record in records:
        config = configs[record.project]
        task_spec = config.tasks.get(record.task) if record.task is not None else None
        for column in columns:
            name = parse_metric_key(column)[0]
            metric = config.metrics.get(name)
            if metric is None:
                continue
            units[column].add(metric_unit(column, metric.unit))
            versions[name] = metric.version
            seen[name].setdefault(metric.version, record.project)
            direction = (
                key_higher_is_better(config, task_spec, column)
                if task_spec is not None
                else metric.higher_is_better is not False
            )
            ranks[column].setdefault(direction, record.run_id)
    for name in dict.fromkeys(parse_metric_key(c)[0] for c in columns):
        if len(seen.get(name, {})) > 1:  # one column must mean one metric definition
            forms = " and ".join(f"{name}@{v} in {p}" for v, p in seen[name].items())
            raise RunError(f"{name} is {forms}; compare runs at one metric version")
    for column in columns:
        if len(ranks.get(column, {})) > 1:  # a system_bench percentile ranks lower-first
            raise RunError(
                f"{column} ranks lower-first for {ranks[column][False]} and higher-first for "
                f"{ranks[column][True]}; compare runs of one task kind"
            )
    higher = {c: next(iter(ranks[c])) if ranks.get(c) else True for c in columns}
    # contract 1.6: x100 only for fractions (no unit, every value in [0, 1]), column by
    # column, with the leaderboard's own value_format rule; a latency of 440 ms stays 440
    scaled = {
        c
        for c in columns
        if opts.percent
        and not any(units.get(c, set()))
        and value_format("", (v[c] for v in values.values() if c in v), higher[c]) == "fraction"
    }
    rows: list[ExportRow] = []
    for record in records:
        cells: dict[str, ExportCell] = {}
        for column in columns:
            value = values[record.run_id].get(column)
            cell = _empty_cell()
            if value is not None:
                mean = value * 100.0 if column in scaled else value
                cell = cell.model_copy(update={"mean": mean, "n": 1})
            cells[column] = cell
        label = group_label(record.hypothesis, record.tags, record.run_id).removeprefix("group ")
        rows.append(
            ExportRow(
                kind="run",
                label=label,
                key=record.run_id,
                n=1,
                cells=cells,
                within_noise=False,
                version_mismatch=False,
                source=None,
            )
        )
    mark_best(rows, higher)
    shown = {parse_metric_key(c)[0] for c in columns}
    return ExportTable(
        title="compare",
        columns=columns,
        higher_is_better=higher,
        rows=rows,
        footnotes=footnotes(
            {m: v for m, v in versions.items() if m in shown},
            rows,
            opts,
            scaled=bool(scaled),
            extra=["one run per row"],
        ),
    )


def task_table(ctx: Context, task: str, project: str | None, opts: ExportOptions) -> ExportTable:
    """
    Build the export table of a task's live leaderboard.

    Parameters
    ----------
    ctx : Context
    task : str
        Task name or ``project/task``.
    project : str or None
    opts : ExportOptions

    Returns
    -------
    ExportTable
        With each column's direction by ``key_higher_is_better`` (the
        leaderboard's rule for the task's kind).
    """
    entry, name = resolve_task(ctx, task, project)
    board = get_leaderboard(ctx, name, entry.project, primary=opts.primary)
    spec = entry.config.tasks[name]
    columns = _columns(board, opts)
    directions = {
        c: key_higher_is_better(entry.config, spec, c)
        if parse_metric_key(c)[0] in entry.config.metrics
        else True
        for c in columns
    }
    directions[board.primary] = board.higher_is_better
    formats: dict[str, str] = {}
    for column in columns:
        metric = entry.config.metrics.get(parse_metric_key(column)[0])
        unit = metric_unit(column, metric.unit) if metric is not None else ""
        values = [r.scores[column].mean for r in board.rows if column in r.scores]
        values += [b.values[column] for b in board.baselines if column in b.values]
        formats[column] = value_format(unit, values, directions[column])
    return leaderboard_table(board, opts, directions=directions, value_formats=formats)


def export_task(ctx: Context, task: str, project: str | None, opts: ExportOptions) -> str:
    """
    Export a task's leaderboard as text.

    Parameters
    ----------
    ctx : Context
    task : str
        Task name or ``project/task``.
    project : str or None
    opts : ExportOptions

    Returns
    -------
    str
        LaTeX, Markdown, or CSV.
    """
    return render(task_table(ctx, task, project, opts), opts)


def export_compare(ctx: Context, run_ids: list[str], opts: ExportOptions) -> str:
    """
    Export a comparison of runs as text.

    Parameters
    ----------
    ctx : Context
    run_ids : list of str
    opts : ExportOptions

    Returns
    -------
    str
    """
    return render(compare_table(ctx, run_ids, opts), opts)
