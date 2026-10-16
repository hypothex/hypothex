import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute, APIWebSocketRoute
from fastapi.testclient import TestClient

from hypothex.api.app import create_app
from hypothex.api.auth import route_scopes
from hypothex.auth.scopes import covers
from tests.api.authkit import BASE, auth_app, bearer, token_for

PHASE_1_2 = {
    "GET /.well-known/hypothex/environment": "public",
    "HEAD /.well-known/hypothex/environment": "public",
    "POST /api/v1/auth/ws-ticket": "read",
    "GET /api/v1/hosts": "read",
    "POST /api/v1/hosts/reload": "launch",
    "POST /api/v1/hosts/{host}/connect": "launch",
    "POST /api/v1/hosts/{host}/disconnect": "launch",
    "POST /api/v1/hosts/{host}/runs": "launch",
    "GET /api/v1/overview": "read",
    "GET /api/v1/projects": "read",
    "GET /api/v1/tasks": "read",
    "GET /api/v1/tasks/{project}/{task}": "read",
    "GET /api/v1/tasks/{project}/{task}/leaderboard": "read",
    "GET /api/v1/tasks/{project}/{task}/runs": "read",
    "POST /api/v1/tasks/{project}/{task}/reeval": "launch",
    "GET /api/v1/tasks/{project}/{task}/kind": "read",
    "GET /api/v1/tasks/{project}/{task}/views": "read",
    "POST /api/v1/tasks/{project}/{task}/views/validate": "read",
    "POST /api/v1/tasks/{project}/{task}/views/query": "read",
    "GET /api/v1/tasks/{project}/{task}/views/{name}": "read",
    "PUT /api/v1/tasks/{project}/{task}/views/{name}": "launch",
    "DELETE /api/v1/tasks/{project}/{task}/views/{name}": "launch",
    "GET /api/v1/runs": "read",
    "POST /api/v1/runs": "launch",
    "POST /api/v1/runs/stop_queued": "launch",
    "GET /api/v1/runs/{run_id}": "read",
    "GET /api/v1/runs/{run_id}/metrics": "read",
    "GET /api/v1/runs/{run_id}/traces": "read",
    "GET /api/v1/runs/{run_id}/traces/{example_id}": "read",
    "GET /api/v1/runs/{run_id}/logs": "read",
    "GET /api/v1/runs/{run_id}/predictions": "read",
    "POST /api/v1/runs/{run_id}/rerun": "launch",
    "POST /api/v1/runs/{run_id}/reinfer": "launch",
    "POST /api/v1/runs/{run_id}/reeval": "launch",
    "POST /api/v1/runs/{run_id}/stop": "launch",
    "POST /api/v1/runs/{run_id}/tags": "launch",
    "POST /api/v1/runs/{run_id}/name": "launch",
    "POST /api/v1/runs/{run_id}/star": "launch",
    "POST /api/v1/runs/{run_id}/archive": "launch",
    "POST /api/v1/runs/{run_id}/notes": "launch",
    "POST /api/v1/sweeps": "launch",
    "GET /api/v1/sweeps/{sweep_id}": "read",
    "GET /api/v1/sweeps/{project}/{sweep_id}": "read",
    "GET /api/v1/projects/{project}/sweeps": "read",
    "POST /api/v1/sweeps/{project}/{sweep_id}/cancel_queued": "launch",
    "POST /api/v1/sweeps/{project}/{sweep_id}/extend": "launch",
    "POST /api/v1/runs/{run_id}/pull": "launch",
    "GET /api/v1/compare": "read",
    "GET /api/v1/compare/examples": "read",
    "GET /api/v1/datasets/check": "read",
    "WS /api/v1/ws": "read",
    "GET /api/v1/runs/{run_id}/files/{path}": "read",
    "GET /api/v1/projects/{project}/entry": "read",
    "GET /api/v1/gpus": "read",
    "GET /api/v1/queue": "read",
    "GET /api/v1/slurm": "read",
}


def undeclared(app: FastAPI) -> list[str]:
    """Every route or WebSocket that declares no scope."""
    declared = route_scopes(app)
    missing: list[str] = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            keys = [f"{m} {route.path_format}" for m in sorted(route.methods)]
            missing += [k for k in keys if k not in declared]
        elif isinstance(route, APIWebSocketRoute) and f"WS {route.path_format}" not in declared:
            missing.append(f"WS {route.path_format}")
    return missing


def app_for(home: Path) -> FastAPI:
    return create_app(home, background_repair=False, hub=False, ui_dir=home / "no-ui")


def test_every_route_and_the_websocket_declare_a_scope(home: Path) -> None:
    assert undeclared(app_for(home)) == []


def test_phase_1_2_routes_have_the_contract_scopes(home: Path) -> None:
    declared = route_scopes(app_for(home))
    assert {k: declared.get(k) for k in PHASE_1_2} == PHASE_1_2


def test_a_route_without_a_scope_is_caught() -> None:
    app = FastAPI()

    @app.get("/api/v1/forgotten")
    def forgotten() -> dict[str, str]:
        return {}

    assert undeclared(app) == ["GET /api/v1/forgotten"]


def test_openapi_shows_each_scope(home: Path) -> None:
    with TestClient(app_for(home), base_url="http://127.0.0.1:7777") as client:
        paths = client.get("/api/openapi.json").json()["paths"]
    assert paths["/api/v1/runs"]["get"]["x-hx-scope"] == "read"
    assert paths["/api/v1/runs/{run_id}/stop"]["post"]["x-hx-scope"] == "launch"


USERS = {"read": "reader", "launch": "launcher", "admin": "sv"}


@pytest.mark.parametrize("held", ["read", "launch", "admin"])
def test_scope_matrix(home: Path, held: str) -> None:
    app = auth_app(home)
    wrong: list[str] = []
    with TestClient(app, base_url=BASE) as client:
        for key, declared in sorted(route_scopes(app).items()):
            method, path = key.split(" ", 1)
            if method == "WS" or declared == "public":
                continue
            token = token_for(app.state.auth, USERS[held], held)  # type: ignore[arg-type]
            url = re.sub(r"\{[^}]+\}", "x", path)
            body = {} if method in ("POST", "PUT") else None
            status = client.request(method, url, json=body, headers=bearer(token)).status_code
            if (status == 403) != (not covers(held, declared)):  # type: ignore[arg-type]
                wrong.append(f"{key}: {status} as {held}")
    assert wrong == []
