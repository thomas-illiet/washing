"""simplify_machine_optimizations

Revision ID: dde2830db606
Revises: 1365251cef3b
Create Date: 2026-05-13 19:02:48.333781

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dde2830db606'
down_revision: Union[str, Sequence[str], None] = '1365251cef3b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("machine_optimizations") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_machine_optimizations_ck_machine_optimizations_current_machine_matches_machine"),
            type_="check",
        )
        batch_op.drop_constraint(
            op.f("ck_machine_optimizations_ck_machine_optimizations_current_state"),
            type_="check",
        )
        batch_op.drop_constraint("uq_machine_optimizations_current_machine_id", type_="unique")
        batch_op.drop_column("current_machine_id")
        batch_op.create_check_constraint(
            op.f("ck_machine_optimizations_ck_machine_optimizations_current_state"),
            "(is_current AND superseded_at IS NULL) OR ((NOT is_current) AND superseded_at IS NOT NULL)",
        )

    op.create_index(
        "uq_machine_optimizations_current_machine",
        "machine_optimizations",
        ["machine_id"],
        unique=True,
        postgresql_where=sa.text("is_current = TRUE"),
        sqlite_where=sa.text("is_current = 1"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("uq_machine_optimizations_current_machine", table_name="machine_optimizations")

    with op.batch_alter_table("machine_optimizations") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_machine_optimizations_ck_machine_optimizations_current_state"),
            type_="check",
        )
        batch_op.add_column(sa.Column("current_machine_id", sa.Integer(), nullable=True))

    op.execute("UPDATE machine_optimizations SET current_machine_id = machine_id WHERE is_current")

    with op.batch_alter_table("machine_optimizations") as batch_op:
        batch_op.create_unique_constraint(
            "uq_machine_optimizations_current_machine_id",
            ["current_machine_id"],
        )
        batch_op.create_check_constraint(
            op.f("ck_machine_optimizations_ck_machine_optimizations_current_machine_matches_machine"),
            "current_machine_id IS NULL OR current_machine_id = machine_id",
        )
        batch_op.create_check_constraint(
            op.f("ck_machine_optimizations_ck_machine_optimizations_current_state"),
            "(is_current AND current_machine_id IS NOT NULL AND superseded_at IS NULL) "
            "OR ((NOT is_current) AND current_machine_id IS NULL AND superseded_at IS NOT NULL)",
        )
