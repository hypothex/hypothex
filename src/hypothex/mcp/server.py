"""MCP server: Hypothex actions as tools for coding agents."""

from __future__ import annotations

import functools
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from hypothex.core import control
from hypothex.core import panels as core_panels
from hypothex.core import queries as q
from hypothex.core import views as core_views
from hypothex.core.config import load_project_config
from hypothex.core.context import Context
from hypothex.core.errors import ConfigError, HypothexError, StoreError
from hypothex.core.evaluation import reeval
from hypothex.core.execution import RunRequest
from hypothex.core.jsonutil import to_jsonable
from hypothex.core.records import RunStatus
from hypothex.core.store import ProjectEntry
from hypothex.core.views import PanelSpec, ValidationIssue, ViewInfo, ViewSpec

INSTRUCTIONS = """\
Hypothex tracks ML/AI experiments across projects. Each run belongs to a task
(dataset + versioned metrics) and records its hypothesis, exact command, git commit,
dataset fingerprints, config, environment, logs, predictions, and scores.

Loop for a new iteration:
1. list_tasks -> pick the task. 2. get_leaderboard -> see what is best and what was tried.
3. get_run on the top rows -> read hypotheses and notes; do not repeat work.
4. launch_run with a one-sentence hypothesis; use seeds (>= 3) before claiming a win.
5. compare_runs against the best; add_note with what you learned.
Never delete runs. Never change a metric's code without bumping its version in
hypothex.yaml; then call reevaluate for the task.

Dashboards: list_views, get_view, add_view (YAML; validated, never saved while invalid;
fix the returned issues and call again), query_view (panel data as rows).
"""

PRESET_VIEW = core_views.RESERVED_VIEW


class ViewValidationError(ConfigError):
    """
    A view's YAML failed validation; nothing was saved.

    Parameters
    ----------
    message : str
        One-line summary (the first issue).
    issues : list of ValidationIssue
        Every problem found, with line, path, message, and suggested fix.
    """

    def __init__(self, message: str, issues: list[ValidationIssue]) -> None:
        super().__init__(message)
        self.issues = issues


def dump_view(view: ViewSpec) -> dict[str, Any]:
    """
    Convert a view to JSON with the YAML key names (``from``, not ``from_``).

    Parameters
    ----------
    view : ViewSpec
        The view.

    Returns
    -------
    dict
        JSON-ready view.
    """
    return view.model_dump(mode="json", by_alias=True)


def list_task_views(ctx: Context, task: str, project: str | None = None) -> list[ViewInfo]:
    """
    List a task's views: ``overview`` first, then inline views, then view files.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    task : str
        Task name, or ``project/task``.
    project : str, optional
        Project to restrict the search to.

    Returns
    -------
    list of ViewInfo
    """
    entry, name = q.resolve_task(ctx, task, project)
    return core_views.list_views(Path(entry.repo), entry.config, name)


def _find_view(
    ctx: Context, task: str, name: str, project: str | None
) -> tuple[ProjectEntry, str, ViewInfo]:
    entry, task_name = q.resolve_task(ctx, task, project)
    for info in core_views.list_views(Path(entry.repo), entry.config, task_name):
        if info.name == name:
            return entry, task_name, info
    # refresh_project keeps the last good config when hypothex.yaml is invalid, so
    # a view that exists only in the broken file would be "unknown": report why
    load_project_config(Path(entry.repo))  # raises ConfigError if the file is invalid
    raise StoreError(f"unknown view {name!r} for task {entry.project}/{task_name}")


def _yaml(data: Any) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def view_document(ctx: Context, task: str, name: str, project: str | None = None) -> dict[str, Any]:
    """
    Read one view: its info, its YAML text as stored, and the resolved view.

    File views return the file's text unchanged; inline views and the preset are
    serialised to YAML.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    task : str
        Task name, or ``project/task``.
    name : str
        View name (``overview`` is the kind's preset).
    project : str, optional
        Project to restrict the search to.

    Returns
    -------
    dict
        ``{"info": ViewInfo, "text": str, "view": ViewSpec}`` as JSON.

    Raises
    ------
    StoreError
        The task has no view with this name.
    ConfigError
        The view is not in the last good config and ``hypothex.yaml`` is invalid
        now (for example an inline view with YAML anchors).
    """
    entry, task_name, info = _find_view(ctx, task, name, project)
    spec = entry.config.tasks[task_name]
    if info.origin == "file" and info.path is not None:
        text = Path(info.path).read_text(encoding="utf-8")
    elif info.origin == "inline":
        text = _yaml(spec.views[name])
    else:
        preset = core_views.load_preset(spec.kind)
        text = _yaml(preset.model_dump(mode="json", by_alias=True, exclude_defaults=True))
    view = core_views.get_view(Path(entry.repo), entry.config, task_name, name)
    return {"info": to_jsonable(info), "text": text, "view": dump_view(view)}


def _check(
    ctx: Context, entry: ProjectEntry, task: str, text: str
) -> tuple[ViewSpec | None, list[ValidationIssue]]:
    metrics, fields = core_views.view_context(ctx, entry.project, task)
    return core_views.validate_view_text(text, metrics, fields)


def validate_view(ctx: Context, task: str, text: str, project: str | None = None) -> dict[str, Any]:
    """
    Validate view YAML against the task's known metrics and fields; save nothing.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    task : str
        Task name, or ``project/task``.
    text : str
        View YAML.
    project : str, optional
        Project to restrict the search to.

    Returns
    -------
    dict
        ``{"ok": bool, "issues": [ValidationIssue], "view": ViewSpec}``; ``view`` is
        present only when the YAML parsed into a view. It is the resolved view: a
        ``from:`` view comes back with the preset's panels (and their layouts) first,
        so the editor can preview and count every panel. The preset is the one
        ``from`` names, even when it is not the task's own kind.
    """
    entry, task_name = q.resolve_task(ctx, task, project)
    view, issues = _check(ctx, entry, task_name, text)
    out: dict[str, Any] = {"ok": view is not None and not issues, "issues": to_jsonable(issues)}
    if view is not None:
        out["view"] = dump_view(core_views.resolve_view(view))
    return out


def put_view(
    ctx: Context, task: str, name: str, text: str, project: str | None = None
) -> dict[str, Any]:
    """
    Validate view YAML and save it to ``<repo>/.hypothex/views/<task>/<name>.yaml``.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    task : str
        Task name, or ``project/task``.
    name : str
        View name.
    text : str
        View YAML; saved byte for byte when valid.
    project : str, optional
        Project to restrict the search to.

    Returns
    -------
    dict
        ``{"info": ViewInfo, "view": ViewSpec}`` (resolved) as JSON.

    Raises
    ------
    ConfigError
        Bad or reserved name.
    ViewValidationError
        The YAML is invalid; nothing was written.
    """
    core_views.check_view_name(name)
    entry, task_name = q.resolve_task(ctx, task, project)
    view, issues = _check(ctx, entry, task_name, text)
    if view is None or issues:
        first = issues[0].message if issues else "not a view"
        raise ViewValidationError(f"invalid view {name!r}: {first}", issues)
    core_views.save_view(Path(entry.repo), task_name, name, text)
    entry, task_name, info = _find_view(ctx, task_name, name, entry.project)
    resolved = core_views.get_view(Path(entry.repo), entry.config, task_name, name)
    return {"info": to_jsonable(info), "view": dump_view(resolved)}


def remove_view(ctx: Context, task: str, name: str, project: str | None = None) -> dict[str, bool]:
    """
    Delete a view file.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    task : str
        Task name, or ``project/task``.
    name : str
        View name.

    Returns
    -------
    dict
        ``{"ok": True}``.

    Raises
    ------
    ConfigError
        ``overview`` or an inline view (edit ``hypothex.yaml`` instead).
    StoreError
        No such view.
    """
    if name == PRESET_VIEW:
        raise ConfigError(f"{PRESET_VIEW!r} is the task's preset view and cannot be deleted")
    entry, task_name, info = _find_view(ctx, task, name, project)
    if info.origin != "file":
        raise ConfigError(f"view {name!r} is declared in hypothex.yaml; remove it there")
    core_views.delete_view(Path(entry.repo), task_name, name)
    return {"ok": True}


def query_task_view(
    ctx: Context,
    task: str,
    *,
    project: str | None = None,
    name: str | None = None,
    view: ViewSpec | None = None,
    panel: PanelSpec | None = None,
) -> dict[str, Any]:
    """
    Compute panel data server-side.

    Priority: ``panel`` (one panel, filtered by ``view.runs`` when a view is also
    given), then ``view`` (resolved first), then the saved view ``name``
    (default ``overview``).

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    task : str
        Task name, or ``project/task``.
    project : str, optional
        Project to restrict the search to.
    name : str, optional
        Saved view name.
    view : ViewSpec, optional
        An unsaved view (e.g. the editor's preview).
    panel : PanelSpec, optional
        A single panel.

    Returns
    -------
    dict
        ``{"panels": [PanelResult]}`` as JSON.
    """
    entry, task_name = q.resolve_task(ctx, task, project)
    if panel is not None:
        runs = view.runs if view is not None else None
        results = [core_panels.query_panel(ctx, entry.project, task_name, panel, runs)]
    else:
        if view is not None:
            chosen = core_views.resolve_view(view)
        else:
            entry, task_name, info = _find_view(ctx, task_name, name or PRESET_VIEW, entry.project)
            chosen = core_views.get_view(Path(entry.repo), entry.config, task_name, info.name)
        results = core_panels.query_view(ctx, entry.project, task_name, chosen)
    return {"panels": to_jsonable(results)}


def _expose_errors(fn: Callable[..., Any]) -> Callable[..., Any]:
    """
    Let expected errors reach the calling agent as readable text.

    ``MCPServer`` only forwards a ``ToolError``'s message to the client; every
    other exception is treated as a crash and its text stays server-side. Our
    tools raise ``HypothexError`` (domain errors, as the CLI and HTTP API do)
    and ``ValueError`` (argument validation) deliberately, so re-raise both as
    ``ToolError`` to keep that message visible.

    Parameters
    ----------
    fn : callable
        The tool function to wrap.

    Returns
    -------
    callable
        The wrapped function.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except (HypothexError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    return wrapper


def build_server(home: Path | None = None) -> MCPServer:
    """
    Build the Hypothex MCP server.

    Parameters
    ----------
    home : Path, optional
        Hypothex home directory.

    Returns
    -------
    MCPServer
        Run with ``.run()`` for stdio, or mount ``.streamable_http_app()``.
    """
    mcp = MCPServer("hypothex", instructions=INSTRUCTIONS)
    holder: dict[str, Context] = {}

    def ctx() -> Context:
        if "ctx" not in holder:
            holder["ctx"] = Context.open(home)
        return holder["ctx"]

    def dump(obj: Any) -> Any:
        return obj.model_dump(mode="json") if hasattr(obj, "model_dump") else obj

    @mcp.tool()
    @_expose_errors
    def list_projects() -> dict[str, Any]:
        """List projects with their repo paths and task names."""
        return {
            "projects": [
                {"project": e.project, "repo": e.repo, "tasks": sorted(e.config.tasks)}
                for e in q.list_projects(ctx())
            ]
        }

    @mcp.tool()
    @_expose_errors
    def list_tasks(project: str | None = None) -> dict[str, Any]:
        """List tasks: dataset@version, metric versions, primary metric, run count, best."""
        return {"tasks": [dump(t) for t in q.list_tasks(ctx(), project)]}

    @mcp.tool()
    @_expose_errors
    def get_task(task: str, project: str | None = None) -> dict[str, Any]:
        """Show a task's dataset (path, version), metrics (fn, version), stages, and repo."""
        return q.get_task(ctx(), task, project)

    @mcp.tool()
    @_expose_errors
    def get_leaderboard(task: str, project: str | None = None) -> dict[str, Any]:
        """Rank seed groups of a task (mean ± std, n); lists runs needing re-evaluation."""
        return dump(q.get_leaderboard(ctx(), task, project))

    @mcp.tool()
    @_expose_errors
    def list_runs(
        project: str | None = None,
        task: str | None = None,
        status: str | None = None,
        tag: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """List runs, newest first. status: queued|running|finished|failed|killed|lost."""
        records = ctx().index.list_runs(
            project=project,
            task=task,
            status=RunStatus(status) if status else None,
            tag=tag,
            limit=limit,
        )
        return {"runs": [dump(r) for r in records]}

    @mcp.tool()
    @_expose_errors
    def get_run(run_id: str) -> dict[str, Any]:
        """Everything about a run: record, scores, notes, children, and all file paths."""
        return dump(q.show_run(ctx(), run_id))

    @mcp.tool()
    @_expose_errors
    def compare_runs(run_ids: list[str]) -> dict[str, Any]:
        """Show config fields and scores that differ between runs."""
        return dump(q.compare_runs(ctx(), run_ids))

    @mcp.tool()
    @_expose_errors
    def launch_run(
        repo: str,
        hypothesis: str,
        task: str | None = None,
        stage: str | None = None,
        command: list[str] | None = None,
        seed: int | None = None,
        params: dict[str, str] | None = None,
        template_vars: dict[str, str] | None = None,
        tags: list[str] | None = None,
        agent: str = "mcp",
    ) -> dict[str, Any]:
        """
        Start a run in the background. Give a command (argv list; may use {seed},
        {run_dir}, {dataset.path}, ...) or a stage name from hypothex.yaml. A
        hypothesis is required.
        """
        if not hypothesis.strip():
            raise ValueError("a hypothesis is required: why does this run exist?")
        record = control.launch_run(
            ctx(),
            RunRequest(
                repo=Path(repo),
                command=command,
                stage=stage,
                task=task,
                hypothesis=hypothesis,
                seed=seed,
                tags=tags or [],
                params=params or {},
                vars=template_vars or {},
                created_by=f"agent:{agent}",
            ),
        )
        return {"run": dump(record), "run_dir": str(ctx().run_dir(record))}

    @mcp.tool()
    @_expose_errors
    def rerun(run_id: str, agent: str = "mcp") -> dict[str, Any]:
        """Rerun with the same command, commit (via worktree if needed), config, and seed."""
        return {"run": dump(control.rerun(ctx(), run_id, created_by=f"agent:{agent}"))}

    @mcp.tool()
    @_expose_errors
    def reinfer(run_id: str, checkpoint: str | None = None, agent: str = "mcp") -> dict[str, Any]:
        """Run the project's `infer` stage with this run's (or the given) checkpoint."""
        return {
            "run": dump(
                control.reinfer(ctx(), run_id, checkpoint=checkpoint, created_by=f"agent:{agent}")
            )
        }

    @mcp.tool()
    @_expose_errors
    def reevaluate(
        run_id: str | None = None,
        task: str | None = None,
        project: str | None = None,
        metric: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Re-score saved predictions with current metric versions (one run or a whole task)."""
        c = ctx()
        if run_id is not None:
            return dump(reeval(c, run_id=run_id, metric=metric, force=force))
        if task is None:
            raise ValueError("give run_id or task")
        entry, name = q.resolve_task(c, task, project)
        return dump(reeval(c, project=entry.project, task=name, metric=metric, force=force))

    @mcp.tool()
    @_expose_errors
    def stop_run(run_id: str) -> dict[str, Any]:
        """Stop a queued or running run."""
        return {"run": dump(control.stop_run(ctx(), run_id))}

    @mcp.tool()
    @_expose_errors
    def add_note(run_id: str, text: str, author: str = "agent") -> dict[str, Any]:
        """Append a Markdown note to a run (findings, next steps)."""
        q.add_note(ctx(), run_id, text, author)
        return {"ok": True}

    @mcp.tool()
    @_expose_errors
    def tag_run(
        run_id: str, add: list[str] | None = None, remove: list[str] | None = None
    ) -> dict[str, Any]:
        """Add or remove tags on a run."""
        return {"run": dump(q.tag_run(ctx(), run_id, add or [], remove or []))}

    @mcp.tool()
    @_expose_errors
    def get_predictions(
        run_id: str,
        metric: str | None = None,
        failures_only: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Page through predictions with references and per-example scores."""
        return dump(
            q.get_predictions(
                ctx(),
                run_id,
                offset=offset,
                limit=limit,
                metric=metric,
                failures_only=failures_only,
            )
        )

    @mcp.tool()
    @_expose_errors
    def list_views(task: str, project: str | None = None) -> dict[str, Any]:
        """List a task's views (dashboards): preset `overview`, inline views, view files."""
        return {"views": [dump(v) for v in list_task_views(ctx(), task, project)]}

    @mcp.tool()
    @_expose_errors
    def get_view(task: str, name: str, project: str | None = None) -> dict[str, Any]:
        """Read one view: info (origin, path), its YAML text, and the resolved view."""
        return view_document(ctx(), task, name, project)

    @mcp.tool()
    @_expose_errors
    def add_view(
        task: str, name: str, yaml_text: str, project: str | None = None
    ) -> dict[str, Any]:
        """
        Validate a view's YAML and save it as .hypothex/views/<task>/<name>.yaml in the
        repo. If invalid, nothing is saved and ok=false comes back with issues (line,
        path, message, suggestion); fix them and call again.
        """
        try:
            return {"ok": True, **put_view(ctx(), task, name, yaml_text, project)}
        except ViewValidationError as exc:
            return {"ok": False, "error": str(exc), "issues": to_jsonable(exc.issues)}

    @mcp.tool()
    @_expose_errors
    def query_view(task: str, name: str, project: str | None = None) -> dict[str, Any]:
        """Compute a saved view's panels as rows (the same data the UI draws)."""
        return query_task_view(ctx(), task, project=project, name=name)

    return mcp
