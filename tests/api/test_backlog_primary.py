"""HTTP primary selection recomputes a board instead of changing its label."""

from pathlib import Path

from fastapi.testclient import TestClient

from hypothex.api.app import create_app
from hypothex.core.context import Context
from tests.core.test_backlog_backend import indexed


def test_http_selected_primary_recomputes_rank_and_rejects_unknown_key(
    ctx: Context, toy_repo: Path
) -> None:
    indexed(ctx, toy_repo)
    with TestClient(
        create_app(ctx.layout.home, background_repair=False, hub=False), base_url="http://localhost"
    ) as client:
        path = "/api/v1/tasks/toy/t/leaderboard"
        default = client.get(path)
        selected = client.get(path, params={"primary": "latency/p95"})
        assert default.status_code == selected.status_code == 200
        assert default.json()["rows"][0]["run_ids"] == ["a"]
        assert selected.json()["rows"][0]["run_ids"] == ["b"]
        assert selected.json()["primary"] == "latency/p95"
        invalid = client.get(path, params={"primary": "latency/typo"})
        assert invalid.status_code in {400, 422}
        assert invalid.json()["type"] == "ConfigError"
