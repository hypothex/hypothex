"""Storage routes: the hub's report, plan, and apply; each env server's usage and delete."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field

from hypothex.api.auth import ADMIN, command_key, identity, principal_of
from hypothex.core.context import Context
from hypothex.core.jsonutil import to_jsonable
from hypothex.core.settings import load_settings
from hypothex.core.storage import (
    CleanItem,
    CleanPolicy,
    HostClients,
    apply_clean,
    check_artifacts,
    delete_artifacts,
    local_usage,
    plan_clean,
    storage_report,
)


class PlanBody(CleanPolicy):
    """Body of ``POST /api/v1/storage/plan``: a policy plus a command id."""

    command_id: str | None = None


class ApplyBody(BaseModel):
    """Body of ``POST /api/v1/storage/plans/{plan_id}/apply``."""

    confirm_bytes: int = Field(ge=0)
    command_id: str | None = None


class CheckBody(BaseModel):
    """Read-only owning-environment cleanup preflight."""

    items: list[CleanItem]
    older_than_days: int = Field(ge=0)


class DeleteBody(BaseModel):
    """Body of the env route ``POST /api/v1/storage/delete`` (sent by the hub)."""

    items: list[CleanItem]
    plan_id: str = Field(pattern=r"^cp-[0-9a-f]{8}$")
    actor: str = Field(min_length=1, max_length=100)
    older_than_days: int = Field(ge=0)  # the plan's policy: the host rechecks the age too
    command_id: str | None = None


def register_storage_routes(app: FastAPI, ctx: Context, hosts: HostClients | None) -> None:
    """
    Add the storage routes.

    Parameters
    ----------
    app : FastAPI
    ctx : Context
    hosts : HostClients or None
        The hub's host connections (``HubManager``).
    """

    def who(request: Request) -> str:
        """Resolve the cleanup actor from the authenticated caller."""
        return identity(request, created_by="human", owner=None)[0]

    @app.get("/api/v1/storage", dependencies=ADMIN)
    def storage(project: str | None = None, remote: bool = True) -> dict[str, Any]:
        """Report local and optionally remote storage usage."""
        return to_jsonable(storage_report(ctx, hosts, project=project, remote=remote))

    @app.post("/api/v1/storage/plan", dependencies=ADMIN)
    def make_plan(body: PlanBody, request: Request) -> dict[str, Any]:
        """Persist a cleanup plan using the caller identity and receipt key."""
        policy = CleanPolicy.model_validate(body.model_dump(exclude={"command_id"}))
        settings = load_settings(ctx.layout).storage
        created_by = who(request)
        return ctx.events.run_once(
            command_key(request, body.command_id),
            lambda: to_jsonable(
                plan_clean(ctx, hosts, policy, created_by=created_by, settings=settings)
            ),
        )

    @app.post("/api/v1/storage/plans/{plan_id}/apply", dependencies=ADMIN)
    def apply(plan_id: str, body: ApplyBody, request: Request) -> dict[str, Any]:
        """Apply an authorized cleanup plan with exact byte confirmation."""
        actor = who(request)
        return ctx.events.run_once(
            command_key(request, body.command_id),
            lambda: to_jsonable(
                apply_clean(ctx, hosts, plan_id, confirm_bytes=body.confirm_bytes, actor=actor)
            ),
        )

    @app.get("/api/v1/storage/usage", dependencies=ADMIN)
    def usage(project: str | None = None) -> list[dict[str, Any]]:
        """List storage items measured on this environment."""
        return to_jsonable(local_usage(ctx, project=project))

    @app.post("/api/v1/storage/check", dependencies=ADMIN)
    def check(body: CheckBody) -> list[dict[str, str]]:
        """Check cleanup candidates on their owning filesystem without deleting."""
        return check_artifacts(ctx, body.items, older_than_days=body.older_than_days)

    @app.post("/api/v1/storage/delete", dependencies=ADMIN)
    def delete(body: DeleteBody, request: Request) -> dict[str, Any]:
        """Delete authorized candidates after authoritative filesystem checks."""
        forwarded = principal_of(request).client == "host"
        actor, _ = identity(request, created_by=body.actor if forwarded else "human", owner=None)
        return ctx.events.run_once(
            command_key(request, body.command_id),
            lambda: to_jsonable(
                delete_artifacts(
                    ctx,
                    body.items,
                    actor=actor,
                    plan_id=body.plan_id,
                    older_than_days=body.older_than_days,
                )
            ),
        )
