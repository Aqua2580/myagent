"""Create the initial Python-native persistence schema.

Revision ID: 20260716_01
Revises: None
Create Date: 2026-07-16 14:30:00 +08:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260716_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_threads",
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_checkpoint_version", sa.Integer(), nullable=False),
        sa.Column("total_step_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "current_checkpoint_version >= 0",
            name=op.f("ck_agent_threads_current_checkpoint_version_non_negative"),
        ),
        sa.CheckConstraint(
            "total_step_count >= 0",
            name=op.f("ck_agent_threads_total_step_count_non_negative"),
        ),
        sa.PrimaryKeyConstraint("thread_id", name=op.f("pk_agent_threads")),
    )
    op.create_index(
        "ix_agent_threads_user_updated",
        "agent_threads",
        ["user_id", "updated_at"],
        unique=False,
    )

    op.create_table(
        "agent_runs",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("engine", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "request_payload",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "result_payload",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "engine IN ('native', 'langgraph')",
            name=op.f("ck_agent_runs_known_engine"),
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"],
            ["agent_threads.thread_id"],
            name=op.f("fk_agent_runs_thread_id_agent_threads"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_id", name=op.f("pk_agent_runs")),
    )
    op.create_index(
        "ix_agent_runs_thread_started",
        "agent_runs",
        ["thread_id", "started_at"],
        unique=False,
    )

    op.create_table(
        "agent_checkpoints",
        sa.Column("checkpoint_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("state_schema_version", sa.Integer(), nullable=False),
        sa.Column(
            "state_payload",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state_schema_version > 0",
            name=op.f("ck_agent_checkpoints_schema_version_positive"),
        ),
        sa.CheckConstraint(
            "version > 0",
            name=op.f("ck_agent_checkpoints_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"],
            ["agent_threads.thread_id"],
            name=op.f("fk_agent_checkpoints_thread_id_agent_threads"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("checkpoint_id", name=op.f("pk_agent_checkpoints")),
        sa.UniqueConstraint("thread_id", "version", name="thread_version"),
    )
    op.create_index(
        "ix_agent_checkpoints_thread_created",
        "agent_checkpoints",
        ["thread_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_agent_checkpoints_thread_created", table_name="agent_checkpoints")
    op.drop_table("agent_checkpoints")
    op.drop_index("ix_agent_runs_thread_started", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index("ix_agent_threads_user_updated", table_name="agent_threads")
    op.drop_table("agent_threads")
