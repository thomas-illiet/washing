"""normalize machine hostname and external id casing

Revision ID: 0004_normalize_machine_identifiers
Revises: 0003_uppercase_machine_dimensions
Create Date: 2026-05-06 20:15:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0004_normalize_machine_identifiers"
down_revision: str | None = "0003_uppercase_machine_dimensions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Normalize persisted machine identifiers to hostname=UPPER and external_id=lower."""
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE machines
            SET hostname = UPPER(TRIM(hostname))
            WHERE TRIM(hostname) <> ''
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE machines
            SET external_id = LOWER(TRIM(external_id))
            WHERE external_id IS NOT NULL AND TRIM(external_id) <> ''
            """
        )
    )


def downgrade() -> None:
    """Restore persisted machine identifiers to their previous lowercase convention."""
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE machines
            SET hostname = LOWER(TRIM(hostname))
            WHERE TRIM(hostname) <> ''
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE machines
            SET external_id = LOWER(TRIM(external_id))
            WHERE external_id IS NOT NULL AND TRIM(external_id) <> ''
            """
        )
    )
