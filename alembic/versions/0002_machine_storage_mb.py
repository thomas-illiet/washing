"""placeholder revision kept after folding machine storage units into the initial schema

Revision ID: 0002_machine_storage_mb
Revises: 0001_initial
Create Date: 2026-05-06 18:30:00.000000
"""

from collections.abc import Sequence

revision: str = "0002_machine_storage_mb"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Keep Alembic history stable after the initial schema reset."""
    return None


def downgrade() -> None:
    """Leave the folded schema unchanged when stepping back one revision."""
    return None
