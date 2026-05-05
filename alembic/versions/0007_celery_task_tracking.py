"""add celery task tracking

Revision ID: 0007_celery_task_tracking
Revises: 0006_simplify_flavor_history
Create Date: 2026-05-05 17:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0007_celery_task_tracking"
down_revision: str | None = "0006_simplify_flavor_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the persistent Celery task execution history table."""
    op.create_table(
        "celery_task_executions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.String(length=255), nullable=False),
        sa.Column("task_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=True),
        sa.Column("resource_id", sa.Integer(), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column(
            "result",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_celery_task_executions")),
    )
    op.create_index(op.f("ix_celery_task_executions_queued_at"), "celery_task_executions", ["queued_at"], unique=False)
    op.create_index(
        op.f("ix_celery_task_executions_resource"),
        "celery_task_executions",
        ["resource_type", "resource_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_celery_task_executions_resource_id"),
        "celery_task_executions",
        ["resource_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_celery_task_executions_resource_type"),
        "celery_task_executions",
        ["resource_type"],
        unique=False,
    )
    op.create_index(op.f("ix_celery_task_executions_status"), "celery_task_executions", ["status"], unique=False)
    op.create_index(op.f("ix_celery_task_executions_task_id"), "celery_task_executions", ["task_id"], unique=True)
    op.create_index(
        op.f("ix_celery_task_executions_task_name"),
        "celery_task_executions",
        ["task_name"],
        unique=False,
    )


def downgrade() -> None:
    """Drop the persistent Celery task execution history table."""
    op.drop_index(op.f("ix_celery_task_executions_task_name"), table_name="celery_task_executions")
    op.drop_index(op.f("ix_celery_task_executions_task_id"), table_name="celery_task_executions")
    op.drop_index(op.f("ix_celery_task_executions_status"), table_name="celery_task_executions")
    op.drop_index(op.f("ix_celery_task_executions_resource_type"), table_name="celery_task_executions")
    op.drop_index(op.f("ix_celery_task_executions_resource_id"), table_name="celery_task_executions")
    op.drop_index(op.f("ix_celery_task_executions_resource"), table_name="celery_task_executions")
    op.drop_index(op.f("ix_celery_task_executions_queued_at"), table_name="celery_task_executions")
    op.drop_table("celery_task_executions")
