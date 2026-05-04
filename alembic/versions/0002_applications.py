"""add applications

Revision ID: 0002_applications
Revises: 0001_initial
Create Date: 2026-05-03 17:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0002_applications"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "applications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("environment", sa.String(length=128), nullable=False),
        sa.Column("region", sa.String(length=128), nullable=False),
        sa.Column("sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_error", sa.Text(), nullable=True),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_applications"),
        sa.UniqueConstraint("name", "environment", "region", name="uq_applications_name_environment_region"),
    )
    op.create_index("ix_applications_name", "applications", ["name"])
    op.create_index("ix_applications_environment", "applications", ["environment"])
    op.create_index("ix_applications_region", "applications", ["region"])
    op.create_index("ix_applications_sync_at", "applications", ["sync_at"])
    op.create_index("ix_applications_sync_scheduled_at", "applications", ["sync_scheduled_at"])

    op.add_column("machines", sa.Column("application_id", sa.Integer(), nullable=True))
    op.create_index("ix_machines_application_id", "machines", ["application_id"])
    op.create_foreign_key(
        "fk_machines_application_id_applications",
        "machines",
        "applications",
        ["application_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_machines_application_id_applications", "machines", type_="foreignkey")
    op.drop_index("ix_machines_application_id", table_name="machines")
    op.drop_column("machines", "application_id")

    op.drop_index("ix_applications_sync_scheduled_at", table_name="applications")
    op.drop_index("ix_applications_sync_at", table_name="applications")
    op.drop_index("ix_applications_region", table_name="applications")
    op.drop_index("ix_applications_environment", table_name="applications")
    op.drop_index("ix_applications_name", table_name="applications")
    op.drop_table("applications")
