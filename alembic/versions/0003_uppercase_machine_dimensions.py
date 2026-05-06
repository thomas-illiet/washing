"""normalize environment and region values to uppercase

Revision ID: 0003_uppercase_machine_dimensions
Revises: 0002_machine_storage_mb
Create Date: 2026-05-06 19:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0003_uppercase_machine_dimensions"
down_revision: str | None = "0002_machine_storage_mb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Normalize persisted machine and application dimensions to uppercase."""
    connection = op.get_bind()
    for table_name in ("machines", "applications"):
        connection.execute(
            sa.text(
                f"""
                UPDATE {table_name}
                SET environment = UPPER(TRIM(environment))
                WHERE environment IS NOT NULL AND TRIM(environment) <> ''
                """
            )
        )
        connection.execute(
            sa.text(
                f"""
                UPDATE {table_name}
                SET region = UPPER(TRIM(region))
                WHERE region IS NOT NULL AND TRIM(region) <> ''
                """
            )
        )


def downgrade() -> None:
    """Restore persisted machine and application dimensions to lowercase."""
    connection = op.get_bind()
    for table_name in ("machines", "applications"):
        connection.execute(
            sa.text(
                f"""
                UPDATE {table_name}
                SET environment = LOWER(TRIM(environment))
                WHERE environment IS NOT NULL AND TRIM(environment) <> ''
                """
            )
        )
        connection.execute(
            sa.text(
                f"""
                UPDATE {table_name}
                SET region = LOWER(TRIM(region))
                WHERE region IS NOT NULL AND TRIM(region) <> ''
                """
            )
        )
