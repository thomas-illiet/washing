"""simplify flavor history state

Revision ID: 0006_simplify_flavor_history
Revises: 0005_simplify_machine_metrics
Create Date: 2026-05-05 16:15:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0006_simplify_flavor_history"
down_revision: str | None = "0005_simplify_machine_metrics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Keep only the changed state in flavor history rows."""
    op.add_column("machine_flavor_history", sa.Column("cpu", sa.Float(), nullable=True))
    op.add_column("machine_flavor_history", sa.Column("ram_mb", sa.Float(), nullable=True))
    op.add_column("machine_flavor_history", sa.Column("disk_mb", sa.Float(), nullable=True))

    op.execute(
        sa.text(
            """
            UPDATE machine_flavor_history
            SET cpu = new_cpu,
                ram_mb = CASE WHEN new_ram_gb IS NULL THEN NULL ELSE new_ram_gb * 1024 END,
                disk_mb = CASE WHEN new_disk_gb IS NULL THEN NULL ELSE new_disk_gb * 1024 END
            """
        )
    )

    op.drop_column("machine_flavor_history", "previous_cpu")
    op.drop_column("machine_flavor_history", "previous_ram_gb")
    op.drop_column("machine_flavor_history", "previous_disk_gb")
    op.drop_column("machine_flavor_history", "new_cpu")
    op.drop_column("machine_flavor_history", "new_ram_gb")
    op.drop_column("machine_flavor_history", "new_disk_gb")


def downgrade() -> None:
    """Restore the previous/new flavor history layout."""
    op.add_column("machine_flavor_history", sa.Column("previous_cpu", sa.Float(), nullable=True))
    op.add_column("machine_flavor_history", sa.Column("previous_ram_gb", sa.Float(), nullable=True))
    op.add_column("machine_flavor_history", sa.Column("previous_disk_gb", sa.Float(), nullable=True))
    op.add_column("machine_flavor_history", sa.Column("new_cpu", sa.Float(), nullable=True))
    op.add_column("machine_flavor_history", sa.Column("new_ram_gb", sa.Float(), nullable=True))
    op.add_column("machine_flavor_history", sa.Column("new_disk_gb", sa.Float(), nullable=True))

    op.execute(
        sa.text(
            """
            UPDATE machine_flavor_history
            SET previous_cpu = NULL,
                previous_ram_gb = NULL,
                previous_disk_gb = NULL,
                new_cpu = cpu,
                new_ram_gb = CASE WHEN ram_mb IS NULL THEN NULL ELSE ram_mb / 1024 END,
                new_disk_gb = CASE WHEN disk_mb IS NULL THEN NULL ELSE disk_mb / 1024 END
            """
        )
    )

    op.drop_column("machine_flavor_history", "cpu")
    op.drop_column("machine_flavor_history", "ram_mb")
    op.drop_column("machine_flavor_history", "disk_mb")
