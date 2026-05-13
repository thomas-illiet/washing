"""rename machine recommendations to optimizations

Revision ID: b7e1d2f3a4c5
Revises: 126a0810958b
Create Date: 2026-05-13 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b7e1d2f3a4c5'
down_revision: Union[str, Sequence[str], None] = '126a0810958b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _rename_postgresql_objects(prefix_from: str, prefix_to: str, table_name: str) -> None:
    """Rename PostgreSQL objects that keep their old names after table renames."""
    op.execute(f'ALTER INDEX ix_{prefix_from}_machine_current RENAME TO ix_{prefix_to}_machine_current')
    op.execute(f'ALTER INDEX ix_{prefix_from}_machine_id RENAME TO ix_{prefix_to}_machine_id')
    op.execute(f'ALTER INDEX ix_{prefix_from}_superseded_at RENAME TO ix_{prefix_to}_superseded_at')
    op.execute(
        f'ALTER TABLE {table_name} RENAME CONSTRAINT uq_{prefix_from}_machine_revision '
        f'TO uq_{prefix_to}_machine_revision'
    )
    op.execute(
        f'ALTER TABLE {table_name} RENAME CONSTRAINT uq_{prefix_from}_current_machine_id '
        f'TO uq_{prefix_to}_current_machine_id'
    )
    op.execute(f'ALTER TABLE {table_name} RENAME CONSTRAINT pk_{prefix_from} TO pk_{prefix_to}')
    op.execute(
        f'ALTER TABLE {table_name} RENAME CONSTRAINT fk_{prefix_from}_machine_id_machines '
        f'TO fk_{prefix_to}_machine_id_machines'
    )
    op.execute(
        f'ALTER TABLE {table_name} RENAME CONSTRAINT ck_{prefix_from}_ck_{prefix_from}_current_machine_matches_machine '
        f'TO ck_{prefix_to}_ck_{prefix_to}_current_machine_matches_machine'
    )
    op.execute(
        f'ALTER TABLE {table_name} RENAME CONSTRAINT ck_{prefix_from}_ck_{prefix_from}_current_state '
        f'TO ck_{prefix_to}_ck_{prefix_to}_current_state'
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.rename_table('machine_recommendations', 'machine_optimizations')
    if op.get_bind().dialect.name == 'postgresql':
        _rename_postgresql_objects('machine_recommendations', 'machine_optimizations', 'machine_optimizations')


def downgrade() -> None:
    """Downgrade schema."""
    op.rename_table('machine_optimizations', 'machine_recommendations')
    if op.get_bind().dialect.name == 'postgresql':
        _rename_postgresql_objects('machine_optimizations', 'machine_recommendations', 'machine_recommendations')
