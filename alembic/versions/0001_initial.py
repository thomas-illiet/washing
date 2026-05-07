"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-03 16:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_type() -> sa.types.TypeEngine:
    """Return a JSON type compatible with both PostgreSQL and SQLite."""
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _timestamp_default():
    """Return the backend-specific default used for timestamp columns."""
    if op.get_context().dialect.name == "sqlite":
        return sa.text("CURRENT_TIMESTAMP")
    return sa.text("now()")


def _timestamps() -> list[sa.Column]:
    """Return shared timestamp columns for created and updated times."""
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_timestamp_default(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_timestamp_default(), nullable=False),
    ]


def _create_metric_table(table_name: str) -> None:
    """Create one simplified daily machine metric table."""
    op.create_table(
        table_name,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("machine_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["machines.id"],
            name=f"fk_{table_name}_machine_id_machines",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["machine_providers.id"],
            name=f"fk_{table_name}_provider_id_machine_providers",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=f"pk_{table_name}"),
        sa.UniqueConstraint("provider_id", "machine_id", "date", name=f"uq_{table_name}_day"),
    )
    op.create_index(f"ix_{table_name}_machine_id", table_name, ["machine_id"])
    op.create_index(f"ix_{table_name}_date", table_name, ["date"])
    op.create_index(f"ix_{table_name}_provider_date", table_name, ["provider_id", "date"])


def upgrade() -> None:
    """Create the current application schema from scratch."""
    op.create_table(
        "platforms",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("extra", _json_type(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_platforms"),
        sa.UniqueConstraint("name", name="uq_platforms_name"),
    )
    op.create_index("ix_platforms_name", "platforms", ["name"])

    op.create_table(
        "applications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("environment", sa.String(length=128), nullable=False),
        sa.Column("region", sa.String(length=128), nullable=False),
        sa.Column("sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_error", sa.Text(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_applications"),
        sa.UniqueConstraint("name", "environment", "region", name="uq_applications_name_environment_region"),
    )
    op.create_index("ix_applications_name", "applications", ["name"])
    op.create_index("ix_applications_environment", "applications", ["environment"])
    op.create_index("ix_applications_region", "applications", ["region"])
    op.create_index("ix_applications_sync_at", "applications", ["sync_at"])
    op.create_index("ix_applications_sync_scheduled_at", "applications", ["sync_scheduled_at"])

    op.create_table(
        "celery_task_executions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.String(length=255), nullable=False),
        sa.Column("task_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=True),
        sa.Column("resource_id", sa.Integer(), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), server_default=_timestamp_default(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("result", _json_type(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_celery_task_executions"),
    )
    op.create_index("ix_celery_task_executions_task_id", "celery_task_executions", ["task_id"], unique=True)
    op.create_index("ix_celery_task_executions_task_name", "celery_task_executions", ["task_name"])
    op.create_index("ix_celery_task_executions_status", "celery_task_executions", ["status"])
    op.create_index("ix_celery_task_executions_resource_type", "celery_task_executions", ["resource_type"])
    op.create_index("ix_celery_task_executions_resource_id", "celery_task_executions", ["resource_id"])
    op.create_index("ix_celery_task_executions_queued_at", "celery_task_executions", ["queued_at"])
    op.create_index(
        "ix_celery_task_executions_resource",
        "celery_task_executions",
        ["resource_type", "resource_id"],
    )

    op.create_table(
        "machine_provisioners",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("platform_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("config", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("cron", sa.String(length=64), nullable=False),
        sa.Column("last_scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["platform_id"],
            ["platforms.id"],
            name="fk_machine_provisioners_platform_id_platforms",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_machine_provisioners"),
        sa.UniqueConstraint("platform_id", "name", name="uq_machine_provisioners_platform_name"),
    )

    op.create_table(
        "machine_providers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("platform_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("config", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["platform_id"],
            ["platforms.id"],
            name="fk_machine_providers_platform_id_platforms",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_machine_providers"),
        sa.UniqueConstraint("platform_id", "name", name="uq_machine_providers_platform_name"),
    )
    op.create_index("ix_machine_providers_scope", "machine_providers", ["scope"])

    op.create_table(
        "machine_provider_provisioners",
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("provisioner_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_timestamp_default(), nullable=False),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["machine_providers.id"],
            name="fk_machine_provider_provisioners_provider_id_machine_providers",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["provisioner_id"],
            ["machine_provisioners.id"],
            name="fk_mpp_provisioner",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("provider_id", "provisioner_id", name="pk_machine_provider_provisioners"),
        sa.UniqueConstraint("provider_id", "provisioner_id", name="uq_machine_provider_provisioners_pair"),
    )

    op.create_table(
        "machines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("platform_id", sa.Integer(), nullable=False),
        sa.Column("application", sa.String(length=255), nullable=True),
        sa.Column("source_provisioner_id", sa.Integer(), nullable=True),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("region", sa.String(length=128), nullable=True),
        sa.Column("environment", sa.String(length=128), nullable=True),
        sa.Column("cpu", sa.Float(), nullable=True),
        sa.Column("ram_mb", sa.Float(), nullable=True),
        sa.Column("disk_mb", sa.Float(), nullable=True),
        sa.Column("extra", _json_type(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["platform_id"],
            ["platforms.id"],
            name="fk_machines_platform_id_platforms",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_provisioner_id"],
            ["machine_provisioners.id"],
            name="fk_machines_source_provisioner_id_machine_provisioners",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_machines"),
        sa.UniqueConstraint("platform_id", "hostname", name="uq_machines_platform_hostname"),
        sa.UniqueConstraint("source_provisioner_id", "external_id", name="uq_machines_provisioner_external_id"),
    )
    op.create_index("ix_machines_application", "machines", ["application"])
    op.create_index("ix_machines_external_id", "machines", ["external_id"])
    op.create_index("ix_machines_hostname", "machines", ["hostname"])
    op.create_index("ix_machines_region", "machines", ["region"])
    op.create_index("ix_machines_environment", "machines", ["environment"])

    op.create_table(
        "machine_flavor_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("machine_id", sa.Integer(), nullable=False),
        sa.Column("source_provisioner_id", sa.Integer(), nullable=True),
        sa.Column("cpu", sa.Float(), nullable=True),
        sa.Column("ram_mb", sa.Float(), nullable=True),
        sa.Column("disk_mb", sa.Float(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=_timestamp_default(), nullable=False),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["machines.id"],
            name="fk_machine_flavor_history_machine_id_machines",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_provisioner_id"],
            ["machine_provisioners.id"],
            name="fk_mfh_source_prov",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_machine_flavor_history"),
    )
    op.create_index("ix_machine_flavor_history_machine_id", "machine_flavor_history", ["machine_id"])
    op.create_index("ix_machine_flavor_history_changed_at", "machine_flavor_history", ["changed_at"])

    for table_name in ("machine_cpu_metrics", "machine_ram_metrics", "machine_disk_metrics"):
        _create_metric_table(table_name)


def downgrade() -> None:
    """Drop the current application schema."""
    for table_name in ("machine_disk_metrics", "machine_ram_metrics", "machine_cpu_metrics"):
        op.drop_index(f"ix_{table_name}_provider_date", table_name=table_name)
        op.drop_index(f"ix_{table_name}_date", table_name=table_name)
        op.drop_index(f"ix_{table_name}_machine_id", table_name=table_name)
        op.drop_table(table_name)

    op.drop_index("ix_machine_flavor_history_changed_at", table_name="machine_flavor_history")
    op.drop_index("ix_machine_flavor_history_machine_id", table_name="machine_flavor_history")
    op.drop_table("machine_flavor_history")

    op.drop_index("ix_machines_environment", table_name="machines")
    op.drop_index("ix_machines_region", table_name="machines")
    op.drop_index("ix_machines_hostname", table_name="machines")
    op.drop_index("ix_machines_external_id", table_name="machines")
    op.drop_index("ix_machines_application", table_name="machines")
    op.drop_table("machines")

    op.drop_table("machine_provider_provisioners")

    op.drop_index("ix_machine_providers_scope", table_name="machine_providers")
    op.drop_table("machine_providers")
    op.drop_table("machine_provisioners")

    op.drop_index("ix_celery_task_executions_resource", table_name="celery_task_executions")
    op.drop_index("ix_celery_task_executions_queued_at", table_name="celery_task_executions")
    op.drop_index("ix_celery_task_executions_resource_id", table_name="celery_task_executions")
    op.drop_index("ix_celery_task_executions_resource_type", table_name="celery_task_executions")
    op.drop_index("ix_celery_task_executions_status", table_name="celery_task_executions")
    op.drop_index("ix_celery_task_executions_task_name", table_name="celery_task_executions")
    op.drop_index("ix_celery_task_executions_task_id", table_name="celery_task_executions")
    op.drop_table("celery_task_executions")

    op.drop_index("ix_applications_sync_scheduled_at", table_name="applications")
    op.drop_index("ix_applications_sync_at", table_name="applications")
    op.drop_index("ix_applications_region", table_name="applications")
    op.drop_index("ix_applications_environment", table_name="applications")
    op.drop_index("ix_applications_name", table_name="applications")
    op.drop_table("applications")

    op.drop_index("ix_platforms_name", table_name="platforms")
    op.drop_table("platforms")
