"""drop application extra column

Revision ID: 0005_drop_application_extra
Revises: 0004_normalize_machine_identifiers
Create Date: 2026-05-07 13:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0005_drop_application_extra"
down_revision: str | None = "0004_normalize_machine_identifiers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_type() -> sa.types.TypeEngine:
    """Return a JSON type compatible with both PostgreSQL and SQLite."""
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    """Remove the unused application metadata payload column."""
    with op.batch_alter_table("applications") as batch_op:
        batch_op.drop_column("extra")


def downgrade() -> None:
    """Restore the application metadata payload column."""
    with op.batch_alter_table("applications") as batch_op:
        batch_op.add_column(sa.Column("extra", _json_type(), nullable=True))

    connection = op.get_bind()
    connection.execute(sa.text("UPDATE applications SET extra = '{}' WHERE extra IS NULL"))

    with op.batch_alter_table("applications") as batch_op:
        batch_op.alter_column("extra", nullable=False)
