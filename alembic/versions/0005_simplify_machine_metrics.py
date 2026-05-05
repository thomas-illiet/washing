"""simplify machine metrics and remove metric types

Revision ID: 0005_simplify_machine_metrics
Revises: 0004_typed_integrations
Create Date: 2026-05-05 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0005_simplify_machine_metrics"
down_revision: str | None = "0004_typed_integrations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


METRIC_TABLES = (
    "machine_cpu_metrics",
    "machine_ram_metrics",
    "machine_disk_metrics",
)


def _is_sqlite() -> bool:
    """Return whether the migration is running against SQLite."""
    return op.get_context().dialect.name == "sqlite"


def _timestamps() -> list[sa.Column]:
    """Return timestamp columns consistent with the existing schema."""
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def _create_simplified_metric_table(table_name: str) -> None:
    """Create the simplified daily metric table shape."""
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


def _create_legacy_metric_table(table_name: str, scope: str) -> None:
    """Restore the pre-simplification daily metric table shape."""
    variant_column = (
        sa.Column("percentile", sa.Float(), nullable=False, server_default="95")
        if scope in {"cpu", "ram"}
        else sa.Column("usage_type", sa.String(length=64), nullable=False, server_default="used")
    )
    unique_columns = ["provider_id", "machine_id", "metric_date", "percentile" if scope in {"cpu", "ram"} else "usage_type"]

    op.create_table(
        table_name,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("machine_id", sa.Integer(), nullable=False),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column(
            "labels",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("collected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        variant_column,
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
        sa.UniqueConstraint(*unique_columns, name=f"uq_{table_name}_day"),
    )
    op.alter_column(table_name, "labels", server_default=None)
    if scope in {"cpu", "ram"}:
        op.alter_column(table_name, "percentile", server_default=None)
    else:
        op.alter_column(table_name, "usage_type", server_default=None)
    op.create_index(f"ix_{table_name}_machine_id", table_name, ["machine_id"])
    op.create_index(f"ix_{table_name}_metric_date", table_name, ["metric_date"])
    op.create_index(f"ix_{table_name}_collected_at", table_name, ["collected_at"])
    op.create_index(f"ix_{table_name}_provider_date", table_name, ["provider_id", "metric_date"])


def upgrade() -> None:
    """Remove metric types and simplify stored machine metrics."""
    for table_name in METRIC_TABLES:
        op.drop_table(table_name)

    if _is_sqlite():
        connection = op.get_bind()
        with op.batch_alter_table("machine_providers") as batch_op:
            batch_op.add_column(sa.Column("scope", sa.String(length=16), nullable=True))

        for metric_type_id, scope in ((1, "cpu"), (2, "ram"), (3, "disk")):
            connection.execute(
                sa.text(
                    "UPDATE machine_providers SET scope = :scope WHERE metric_type_id = :metric_type_id"
                ),
                {"scope": scope, "metric_type_id": metric_type_id},
            )

        with op.batch_alter_table("machine_providers") as batch_op:
            batch_op.alter_column("scope", existing_type=sa.String(length=16), nullable=False)
            batch_op.create_index("ix_machine_providers_scope", ["scope"], unique=False)
            batch_op.drop_column("metric_type_id")
    else:
        op.add_column("machine_providers", sa.Column("scope", sa.String(length=16), nullable=True))
        op.execute(
            sa.text(
                """
                UPDATE machine_providers AS mp
                SET scope = mt.code
                FROM metric_types AS mt
                WHERE mp.metric_type_id = mt.id
                """
            )
        )
        op.alter_column("machine_providers", "scope", nullable=False)
        op.create_index("ix_machine_providers_scope", "machine_providers", ["scope"])
        op.drop_constraint(
            "fk_machine_providers_metric_type_id_metric_types",
            "machine_providers",
            type_="foreignkey",
        )
        op.drop_column("machine_providers", "metric_type_id")

    op.drop_table("metric_types")

    for table_name in METRIC_TABLES:
        _create_simplified_metric_table(table_name)


def downgrade() -> None:
    """Restore metric types and the legacy machine metric table shape."""
    for table_name in METRIC_TABLES:
        op.drop_table(table_name)

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
        sa.column("id", sa.Integer()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("unit", sa.String()),
        sa.column("description", sa.String()),
    )
    op.bulk_insert(
        metric_types,
        [
            {"id": 1, "code": "cpu", "name": "CPU", "unit": "percent", "description": "CPU utilization or capacity metric."},
            {"id": 2, "code": "ram", "name": "RAM", "unit": "gb", "description": "Memory utilization or capacity metric."},
            {"id": 3, "code": "disk", "name": "Disk", "unit": "gb", "description": "Disk utilization or capacity metric."},
        ],
    )

    op.add_column("machine_providers", sa.Column("metric_type_id", sa.Integer(), nullable=True))
    op.execute(
        sa.text(
            """
            UPDATE machine_providers AS mp
            SET metric_type_id = mt.id
            FROM metric_types AS mt
            WHERE mp.scope = mt.code
            """
        )
    )
    op.create_foreign_key(
        "fk_machine_providers_metric_type_id_metric_types",
        "machine_providers",
        "metric_types",
        ["metric_type_id"],
        ["id"],
    )
    op.alter_column("machine_providers", "metric_type_id", nullable=False)
    op.drop_index("ix_machine_providers_scope", table_name="machine_providers")
    op.drop_column("machine_providers", "scope")

    for table_name, scope in (
        ("machine_cpu_metrics", "cpu"),
        ("machine_ram_metrics", "ram"),
        ("machine_disk_metrics", "disk"),
    ):
        _create_legacy_metric_table(table_name, scope)
