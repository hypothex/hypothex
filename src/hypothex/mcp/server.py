"""MCP server: Hypothex actions as tools for coding agents."""

from __future__ import annotations

import functools
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from hypothex.core import control
from hypothex.core import queries as q
from hypothex.core.context import Context
from hypothex.core.errors import HypothexError
from hypothex.core.evaluation import reeval
from hypothex.core.execution import RunRequest
from hypothex.core.records import RunStatus

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
"""


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

    return mcp
