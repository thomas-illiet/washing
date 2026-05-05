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
    """Return the shared timestamp columns used by the initial schema."""
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_timestamp_default(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_timestamp_default(), nullable=False),
    ]


def _metric_columns(table_name: str) -> list[sa.Column]:
    """Build the shared columns for the original metric tables."""
    return [
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("machine_id", sa.Integer(), nullable=True),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("labels", _json_type(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), server_default=_timestamp_default(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], name=f"fk_{table_name}_machine_id_machines", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["machine_providers.id"],
            name=f"fk_{table_name}_provider_id_machine_providers",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=f"pk_{table_name}"),
    ]


def upgrade() -> None:
    """Create the initial application schema."""
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
        "metric_types",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_metric_types"),
        sa.UniqueConstraint("code", name="uq_metric_types_code"),
    )
    op.create_index("ix_metric_types_code", "metric_types", ["code"])

    metric_types = sa.table(
        "metric_types",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("unit", sa.String),
        sa.column("description", sa.String),
    )
    op.bulk_insert(
        metric_types,
        [
            {"code": "cpu", "name": "CPU", "unit": "percent", "description": "CPU utilization or capacity metric."},
            {"code": "ram", "name": "RAM", "unit": "gb", "description": "Memory utilization or capacity metric."},
            {"code": "disk", "name": "Disk", "unit": "gb", "description": "Disk utilization or capacity metric."},
        ],
    )

    op.create_table(
        "machine_provisioners",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("platform_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("config", _json_type(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("cron", sa.String(length=64), nullable=False),
        sa.Column("last_scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["platform_id"], ["platforms.id"], name="fk_machine_provisioners_platform_id_platforms", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_machine_provisioners"),
        sa.UniqueConstraint("platform_id", "name", name="uq_machine_provisioners_platform_name"),
    )

    op.create_table(
        "machine_providers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("platform_id", sa.Integer(), nullable=False),
        sa.Column("metric_type_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("config", _json_type(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("cron", sa.String(length=64), nullable=False),
        sa.Column("last_scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["metric_type_id"], ["metric_types.id"], name="fk_machine_providers_metric_type_id_metric_types"),
        sa.ForeignKeyConstraint(["platform_id"], ["platforms.id"], name="fk_machine_providers_platform_id_platforms", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_machine_providers"),
        sa.UniqueConstraint("platform_id", "name", name="uq_machine_providers_platform_name"),
    )

    op.create_table(
        "machine_provider_provisioners",
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("provisioner_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_timestamp_default(), nullable=False),
        sa.ForeignKeyConstraint(["provider_id"], ["machine_providers.id"], name="fk_mpp_provider", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["provisioner_id"], ["machine_provisioners.id"], name="fk_mpp_provisioner", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("provider_id", "provisioner_id", name="pk_machine_provider_provisioners"),
        sa.UniqueConstraint("provider_id", "provisioner_id", name="uq_machine_provider_provisioners_pair"),
    )

    op.create_table(
        "machines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("platform_id", sa.Integer(), nullable=False),
        sa.Column("source_provisioner_id", sa.Integer(), nullable=True),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("region", sa.String(length=128), nullable=True),
        sa.Column("environment", sa.String(length=128), nullable=True),
        sa.Column("cpu", sa.Float(), nullable=True),
        sa.Column("ram_gb", sa.Float(), nullable=True),
        sa.Column("disk_gb", sa.Float(), nullable=True),
        sa.Column("extra", _json_type(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["platform_id"], ["platforms.id"], name="fk_machines_platform_id_platforms", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_provisioner_id"], ["machine_provisioners.id"], name="fk_machines_source_prov", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_machines"),
        sa.UniqueConstraint("platform_id", "hostname", name="uq_machines_platform_hostname"),
        sa.UniqueConstraint("source_provisioner_id", "external_id", name="uq_machines_provisioner_external_id"),
    )
    op.create_index("ix_machines_external_id", "machines", ["external_id"])
    op.create_index("ix_machines_hostname", "machines", ["hostname"])
    op.create_index("ix_machines_region", "machines", ["region"])
    op.create_index("ix_machines_environment", "machines", ["environment"])

    op.create_table(
        "machine_flavor_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("machine_id", sa.Integer(), nullable=False),
        sa.Column("source_provisioner_id", sa.Integer(), nullable=True),
        sa.Column("previous_cpu", sa.Float(), nullable=True),
        sa.Column("previous_ram_gb", sa.Float(), nullable=True),
        sa.Column("previous_disk_gb", sa.Float(), nullable=True),
        sa.Column("new_cpu", sa.Float(), nullable=True),
        sa.Column("new_ram_gb", sa.Float(), nullable=True),
        sa.Column("new_disk_gb", sa.Float(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=_timestamp_default(), nullable=False),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], name="fk_machine_flavor_history_machine_id_machines", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_provisioner_id"], ["machine_provisioners.id"], name="fk_mfh_source_prov", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_machine_flavor_history"),
    )
    op.create_index("ix_machine_flavor_history_machine_id", "machine_flavor_history", ["machine_id"])
    op.create_index("ix_machine_flavor_history_changed_at", "machine_flavor_history", ["changed_at"])

    for table_name in ("cpu_metrics", "ram_metrics", "disk_metrics"):
        op.create_table(table_name, *_metric_columns(table_name))
        op.create_index(f"ix_{table_name}_machine_id", table_name, ["machine_id"])
        op.create_index(f"ix_{table_name}_collected_at", table_name, ["collected_at"])
        op.create_index(f"ix_{table_name}_provider_collected_at", table_name, ["provider_id", "collected_at"])


def downgrade() -> None:
    """Drop the initial application schema."""
    for table_name in ("disk_metrics", "ram_metrics", "cpu_metrics"):
        op.drop_index(f"ix_{table_name}_provider_collected_at", table_name=table_name)
        op.drop_index(f"ix_{table_name}_collected_at", table_name=table_name)
        op.drop_index(f"ix_{table_name}_machine_id", table_name=table_name)
        op.drop_table(table_name)

    op.drop_index("ix_machine_flavor_history_changed_at", table_name="machine_flavor_history")
    op.drop_index("ix_machine_flavor_history_machine_id", table_name="machine_flavor_history")
    op.drop_table("machine_flavor_history")

    op.drop_index("ix_machines_environment", table_name="machines")
    op.drop_index("ix_machines_region", table_name="machines")
    op.drop_index("ix_machines_hostname", table_name="machines")
    op.drop_index("ix_machines_external_id", table_name="machines")
    op.drop_table("machines")

    op.drop_table("machine_provider_provisioners")
    op.drop_table("machine_providers")
    op.drop_table("machine_provisioners")
    op.drop_index("ix_metric_types_code", table_name="metric_types")
    op.drop_table("metric_types")
    op.drop_index("ix_platforms_name", table_name="platforms")
    op.drop_table("platforms")
