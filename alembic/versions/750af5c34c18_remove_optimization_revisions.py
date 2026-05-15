"""remove optimization revisions

Revision ID: 750af5c34c18
Revises: dde2830db606
Create Date: 2026-05-15 20:00:51.984900

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '750af5c34c18'
down_revision: Union[str, Sequence[str], None] = 'dde2830db606'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index("ix_machine_optimizations_machine_current", table_name="machine_optimizations")
    op.drop_index("ix_machine_optimizations_superseded_at", table_name="machine_optimizations")
    op.drop_index("uq_machine_optimizations_current_machine", table_name="machine_optimizations")

    with op.batch_alter_table("machine_optimizations") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_machine_optimizations_ck_machine_optimizations_current_state"),
            type_="check",
        )
        batch_op.drop_constraint("uq_machine_optimizations_machine_revision", type_="unique")
        batch_op.create_unique_constraint("uq_machine_optimizations_machine_id", ["machine_id"])
        batch_op.drop_column("acknowledged_by")
        batch_op.drop_column("acknowledged_at")
        batch_op.drop_column("is_current")
        batch_op.drop_column("revision")
        batch_op.drop_column("superseded_at")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("machine_optimizations") as batch_op:
        batch_op.drop_constraint("uq_machine_optimizations_machine_id", type_="unique")
        batch_op.add_column(sa.Column("revision", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("is_current", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("acknowledged_by", sa.String(length=255), nullable=True))

    op.execute("UPDATE machine_optimizations SET revision = 1, is_current = 1")

    with op.batch_alter_table("machine_optimizations") as batch_op:
        batch_op.alter_column("revision", existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column("is_current", existing_type=sa.Boolean(), nullable=False)
        batch_op.create_unique_constraint("uq_machine_optimizations_machine_revision", ["machine_id", "revision"])
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
    op.create_index("ix_machine_optimizations_superseded_at", "machine_optimizations", ["superseded_at"])
    op.create_index("ix_machine_optimizations_machine_current", "machine_optimizations", ["machine_id", "is_current"])
