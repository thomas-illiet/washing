"""rename metrics to machine daily metrics

Revision ID: 0003_machine_daily_metrics
Revises: 0002_applications
Create Date: 2026-05-03 17:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0003_machine_daily_metrics"
down_revision: str | None = "0002_applications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


METRIC_RENAMES = (
    ("cpu_metrics", "machine_cpu_metrics", "cpu"),
    ("ram_metrics", "machine_ram_metrics", "ram"),
    ("disk_metrics", "machine_disk_metrics", "disk"),
)


def _is_sqlite() -> bool:
    """Return whether the migration is running against SQLite."""
    return op.get_context().dialect.name == "sqlite"


def _timestamp_default():
    """Return the backend-specific default used for timestamp columns."""
    if _is_sqlite():
        return sa.text("CURRENT_TIMESTAMP")
    return sa.text("now()")


def _json_type() -> sa.types.TypeEngine:
    """Return a JSON type compatible with both PostgreSQL and SQLite."""
    return sa.JSON()


def _create_sqlite_daily_metric_table(table_name: str, metric_code: str) -> None:
    """Create the target daily metric table directly for SQLite smoke migrations."""
    variant_column = (
        sa.Column("percentile", sa.Float(), nullable=False, server_default="95")
        if metric_code in {"cpu", "ram"}
        else sa.Column("usage_type", sa.String(length=64), nullable=False, server_default="used")
    )
    unique_columns = (
        ["provider_id", "machine_id", "metric_date", "percentile"]
        if metric_code in {"cpu", "ram"}
        else ["provider_id", "machine_id", "metric_date", "usage_type"]
    )

    op.create_table(
        table_name,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("machine_id", sa.Integer(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("labels", _json_type(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), server_default=_timestamp_default(), nullable=False),
        sa.Column("metric_date", sa.Date(), nullable=False),
        variant_column,
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_timestamp_default(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_timestamp_default(), nullable=False),
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
        sa.UniqueConstraint(*unique_columns, name=f"uq_machine_{metric_code}_metrics_day"),
    )
    _create_new_indexes(table_name)


def _drop_old_indexes(table_name: str) -> None:
    """Drop the indexes attached to the pre-rename metric table."""
    op.drop_index(f"ix_{table_name}_provider_collected_at", table_name=table_name)
    op.drop_index(f"ix_{table_name}_collected_at", table_name=table_name)
    op.drop_index(f"ix_{table_name}_machine_id", table_name=table_name)


def _create_new_indexes(table_name: str) -> None:
    """Create the indexes expected by the daily metric schema."""
    op.create_index(f"ix_{table_name}_machine_id", table_name, ["machine_id"])
    op.create_index(f"ix_{table_name}_metric_date", table_name, ["metric_date"])
    op.create_index(f"ix_{table_name}_collected_at", table_name, ["collected_at"])
    op.create_index(f"ix_{table_name}_provider_date", table_name, ["provider_id", "metric_date"])


def upgrade() -> None:
    """Rename metric tables and convert them to daily storage."""
    if _is_sqlite():
        for old_table, new_table, metric_code in METRIC_RENAMES:
            op.drop_table(old_table)
            _create_sqlite_daily_metric_table(new_table, metric_code)
        return

    for old_table, new_table, metric_code in METRIC_RENAMES:
        _drop_old_indexes(old_table)
        op.drop_constraint(f"fk_{old_table}_machine_id_machines", old_table, type_="foreignkey")
        op.drop_constraint(f"fk_{old_table}_provider_id_machine_providers", old_table, type_="foreignkey")
        op.rename_table(old_table, new_table)
        op.execute(f"ALTER TABLE {new_table} RENAME CONSTRAINT pk_{old_table} TO pk_{new_table}")

        op.add_column(new_table, sa.Column("metric_date", sa.Date(), nullable=True))
        op.execute(f"DELETE FROM {new_table} WHERE machine_id IS NULL")
        op.execute(f"UPDATE {new_table} SET metric_date = collected_at::date WHERE metric_date IS NULL")
        op.alter_column(new_table, "metric_date", existing_type=sa.Date(), nullable=False)
        op.alter_column(new_table, "machine_id", existing_type=sa.Integer(), nullable=False)

        if metric_code in {"cpu", "ram"}:
            op.add_column(new_table, sa.Column("percentile", sa.Float(), server_default="95", nullable=False))
            op.alter_column(new_table, "percentile", server_default=None)
            op.create_unique_constraint(
                f"uq_machine_{metric_code}_metrics_day",
                new_table,
                ["provider_id", "machine_id", "metric_date", "percentile"],
            )
        else:
            op.add_column(new_table, sa.Column("usage_type", sa.String(length=64), server_default="used", nullable=False))
            op.alter_column(new_table, "usage_type", server_default=None)
            op.create_unique_constraint(
                "uq_machine_disk_metrics_day",
                new_table,
                ["provider_id", "machine_id", "metric_date", "usage_type"],
            )

        op.create_foreign_key(
            f"fk_{new_table}_machine_id_machines",
            new_table,
            "machines",
            ["machine_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_foreign_key(
            f"fk_{new_table}_provider_id_machine_providers",
            new_table,
            "machine_providers",
            ["provider_id"],
            ["id"],
            ondelete="CASCADE",
        )
        _create_new_indexes(new_table)


def downgrade() -> None:
    """Restore the pre-daily metric table layout."""
    for old_table, new_table, metric_code in reversed(METRIC_RENAMES):
        op.drop_index(f"ix_{new_table}_provider_date", table_name=new_table)
        op.drop_index(f"ix_{new_table}_collected_at", table_name=new_table)
        op.drop_index(f"ix_{new_table}_metric_date", table_name=new_table)
        op.drop_index(f"ix_{new_table}_machine_id", table_name=new_table)
        op.drop_constraint(f"fk_{new_table}_provider_id_machine_providers", new_table, type_="foreignkey")
        op.drop_constraint(f"fk_{new_table}_machine_id_machines", new_table, type_="foreignkey")

        if metric_code in {"cpu", "ram"}:
            op.drop_constraint(f"uq_machine_{metric_code}_metrics_day", new_table, type_="unique")
            op.drop_column(new_table, "percentile")
        else:
            op.drop_constraint("uq_machine_disk_metrics_day", new_table, type_="unique")
            op.drop_column(new_table, "usage_type")

        op.drop_column(new_table, "metric_date")
        op.alter_column(new_table, "machine_id", existing_type=sa.Integer(), nullable=True)
        op.execute(f"ALTER TABLE {new_table} RENAME CONSTRAINT pk_{new_table} TO pk_{old_table}")
        op.rename_table(new_table, old_table)
        op.create_foreign_key(
            f"fk_{old_table}_machine_id_machines",
            old_table,
            "machines",
            ["machine_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_foreign_key(
            f"fk_{old_table}_provider_id_machine_providers",
            old_table,
            "machine_providers",
            ["provider_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_index(f"ix_{old_table}_machine_id", old_table, ["machine_id"])
        op.create_index(f"ix_{old_table}_collected_at", old_table, ["collected_at"])
        op.create_index(f"ix_{old_table}_provider_collected_at", old_table, ["provider_id", "collected_at"])
