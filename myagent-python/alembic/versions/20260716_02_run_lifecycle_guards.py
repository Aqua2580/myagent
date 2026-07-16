"""Add database guards for the runtime Run lifecycle.

Revision ID: 20260716_02
Revises: 20260716_01
Create Date: 2026-07-16 16:00:00 +08:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260716_02"
down_revision: str | None = "20260716_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KNOWN_STATUS_SQL = (
    "status IN ('running', 'waiting_confirmation', 'completed', "
    "'partial_completed', 'error', 'cancelled')"
)
ACTIVE_STATUS_SQL = "status IN ('running', 'waiting_confirmation')"


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("agent_runs") as batch_op:
            batch_op.create_check_constraint(
                op.f("ck_agent_runs_known_status"),
                KNOWN_STATUS_SQL,
            )
    else:
        op.create_check_constraint(
            op.f("ck_agent_runs_known_status"),
            "agent_runs",
            KNOWN_STATUS_SQL,
        )

    op.create_index(
        "uq_agent_runs_thread_active",
        "agent_runs",
        ["thread_id"],
        unique=True,
        postgresql_where=sa.text(ACTIVE_STATUS_SQL),
        sqlite_where=sa.text(ACTIVE_STATUS_SQL),
    )


def downgrade() -> None:
    op.drop_index("uq_agent_runs_thread_active", table_name="agent_runs")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("agent_runs") as batch_op:
            batch_op.drop_constraint(
                op.f("ck_agent_runs_known_status"),
                type_="check",
            )
    else:
        op.drop_constraint(
            op.f("ck_agent_runs_known_status"),
            "agent_runs",
            type_="check",
        )
