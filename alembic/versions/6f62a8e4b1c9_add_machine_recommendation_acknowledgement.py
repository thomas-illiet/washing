"""add machine recommendation acknowledgement

Revision ID: 6f62a8e4b1c9
Revises: db0aaeafbd5c
Create Date: 2026-05-13 14:48:13.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6f62a8e4b1c9'
down_revision: Union[str, Sequence[str], None] = 'db0aaeafbd5c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'machine_recommendations',
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'machine_recommendations',
        sa.Column('acknowledged_by', sa.String(length=255), nullable=True),
    )
    op.create_index(
        op.f('ix_machine_recommendations_acknowledged_at'),
        'machine_recommendations',
        ['acknowledged_at'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_machine_recommendations_acknowledged_at'), table_name='machine_recommendations')
    op.drop_column('machine_recommendations', 'acknowledged_by')
    op.drop_column('machine_recommendations', 'acknowledged_at')
