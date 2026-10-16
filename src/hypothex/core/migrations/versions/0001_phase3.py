"""phase 3: the whole index at SCHEMA_VERSION 5

Revision ID: 0001_phase3
Revises:
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_phase3"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create every index table, with the indexes the models declare."""
    meta = op.create_table(
        "meta",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("value", sa.String(), nullable=False),
    )
    op.create_table(
        "projects",
        sa.Column("name", sa.String(), primary_key=True),
        sa.Column("repo", sa.String(), nullable=False),
        sa.Column("entry_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "datasets",
        sa.Column("project", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), primary_key=True),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("host", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
    )
    op.create_table(
        "metrics",
        sa.Column("project", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), primary_key=True),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("fn", sa.String(), nullable=False),
        sa.Column("higher_is_better", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "tasks",
        sa.Column("project", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), primary_key=True),
        sa.Column("dataset", sa.String(), nullable=False),
        sa.Column("split", sa.String(), nullable=True),
        sa.Column("primary", sa.String(), nullable=False),
        sa.Column("metrics_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "runs",
        sa.Column("run_id", sa.String(), primary_key=True),
        sa.Column("project", sa.String(), nullable=False),
        sa.Column("task", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("config_hash", sa.String(), nullable=False),
        sa.Column("commit", sa.String(), nullable=True),
        sa.Column("environment_id", sa.String(), nullable=False),
        sa.Column("parent", sa.String(), nullable=True),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("starred", sa.Boolean(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("owner", sa.String(), nullable=True),
        sa.Column("record_json", sa.Text(), nullable=False),
    )
    for column in ("project", "task", "status", "created_at", "parent", "name", "owner"):
        op.create_index(f"ix_runs_{column}", "runs", [column])
    op.create_table(
        "run_tags",
        sa.Column("run_id", sa.String(), primary_key=True),
        sa.Column("tag", sa.String(), primary_key=True),
    )
    op.create_index("ix_run_tags_tag", "run_tags", ["tag"])
    op.create_table(
        "scores",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("record_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("ix_scores_run_id", "scores", ["run_id"])
    op.create_table(
        "metric_points",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("step", sa.BigInteger(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("t", sa.Float(), nullable=True),
    )
    op.create_index("ix_metric_points_run_name_step", "metric_points", ["run_id", "name", "step"])
    op.create_table(
        "host_cursors",
        sa.Column("host", sa.String(), primary_key=True),
        sa.Column("environment_id", sa.String(), primary_key=True),
        sa.Column("last_sequence", sa.BigInteger(), nullable=False),
    )
    op.create_table(
        "run_changes",
        sa.Column("run_id", sa.String(), primary_key=True),
        sa.Column("generation", sa.BigInteger(), nullable=False),
    )
    for name in ("metric_points_pending", "scores_stale"):
        op.create_table(name, sa.Column("run_id", sa.String(), primary_key=True))
    op.bulk_insert(meta, [{"key": "schema_version", "value": "5"}])


def downgrade() -> None:
    """Drop every index table."""
    for table in (
        "scores_stale", "metric_points_pending", "run_changes", "host_cursors",
        "metric_points", "scores", "run_tags", "runs", "tasks", "metrics",
        "datasets", "projects", "meta",
    ):  # fmt: skip
        op.drop_table(table)
