"""encrypt integration configs and remove provider scheduling

Revision ID: 0004_typed_integrations
Revises: 0003_machine_daily_metrics
Create Date: 2026-05-05 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from internal.infra.security import decrypt_json_value, encrypt_json_value


revision: str = "0004_typed_integrations"
down_revision: str | None = "0003_machine_daily_metrics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _provisioners_table(config_type: sa.types.TypeEngine) -> sa.Table:
    return sa.table(
        "machine_provisioners",
        sa.column("id", sa.Integer()),
        sa.column("config", config_type),
    )


def _providers_table(config_type: sa.types.TypeEngine) -> sa.Table:
    return sa.table(
        "machine_providers",
        sa.column("id", sa.Integer()),
        sa.column("config", config_type),
    )


def _migrate_config_column(table_name: str, target_column: str, rows: list[dict], serializer) -> None:
    connection = op.get_bind()
    for row in rows:
        connection.execute(
            sa.text(f"UPDATE {table_name} SET {target_column} = :config WHERE id = :id"),
            {"id": row["id"], "config": serializer(row["config"] or {})},
        )


def upgrade() -> None:
    connection = op.get_bind()
    provisioners = _provisioners_table(postgresql.JSONB())
    providers = _providers_table(postgresql.JSONB())
    provisioner_rows = connection.execute(
        sa.select(provisioners.c.id, provisioners.c.config)
    ).mappings().all()
    provider_rows = connection.execute(
        sa.select(providers.c.id, providers.c.config)
    ).mappings().all()

    op.add_column("machine_provisioners", sa.Column("config_encrypted", sa.Text(), nullable=True))
    op.add_column("machine_providers", sa.Column("config_encrypted", sa.Text(), nullable=True))

    _migrate_config_column("machine_provisioners", "config_encrypted", provisioner_rows, encrypt_json_value)
    _migrate_config_column("machine_providers", "config_encrypted", provider_rows, encrypt_json_value)

    op.alter_column("machine_provisioners", "config_encrypted", nullable=False)
    op.alter_column("machine_providers", "config_encrypted", nullable=False)

    op.drop_column("machine_provisioners", "config")
    op.alter_column("machine_provisioners", "config_encrypted", new_column_name="config")

    op.drop_column("machine_providers", "config")
    op.alter_column("machine_providers", "config_encrypted", new_column_name="config")
    op.drop_column("machine_providers", "cron")
    op.drop_column("machine_providers", "last_scheduled_at")


def downgrade() -> None:
    connection = op.get_bind()
    provisioners = _provisioners_table(sa.Text())
    providers = _providers_table(sa.Text())
    provisioner_rows = connection.execute(
        sa.select(provisioners.c.id, provisioners.c.config)
    ).mappings().all()
    provider_rows = connection.execute(
        sa.select(providers.c.id, providers.c.config)
    ).mappings().all()

    op.add_column("machine_provisioners", sa.Column("config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("machine_providers", sa.Column("config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("machine_providers", sa.Column("cron", sa.String(length=64), server_default="*/5 * * * *", nullable=False))
    op.add_column("machine_providers", sa.Column("last_scheduled_at", sa.DateTime(timezone=True), nullable=True))

    _migrate_config_column("machine_provisioners", "config_json", provisioner_rows, decrypt_json_value)
    _migrate_config_column("machine_providers", "config_json", provider_rows, decrypt_json_value)

    op.alter_column("machine_provisioners", "config_json", nullable=False)
    op.alter_column("machine_providers", "config_json", nullable=False)
    op.alter_column("machine_providers", "cron", server_default=None)

    op.drop_column("machine_provisioners", "config")
    op.alter_column("machine_provisioners", "config_json", new_column_name="config")

    op.drop_column("machine_providers", "config")
    op.alter_column("machine_providers", "config_json", new_column_name="config")
