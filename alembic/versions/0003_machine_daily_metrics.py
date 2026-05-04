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


def _drop_old_indexes(table_name: str) -> None:
    op.drop_index(f"ix_{table_name}_provider_collected_at", table_name=table_name)
    op.drop_index(f"ix_{table_name}_collected_at", table_name=table_name)
    op.drop_index(f"ix_{table_name}_machine_id", table_name=table_name)


def _create_new_indexes(table_name: str) -> None:
    op.create_index(f"ix_{table_name}_machine_id", table_name, ["machine_id"])
    op.create_index(f"ix_{table_name}_metric_date", table_name, ["metric_date"])
    op.create_index(f"ix_{table_name}_collected_at", table_name, ["collected_at"])
    op.create_index(f"ix_{table_name}_provider_date", table_name, ["provider_id", "metric_date"])


def upgrade() -> None:
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
