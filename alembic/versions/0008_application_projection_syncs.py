"""convert applications to a machine-derived projection

Revision ID: 0008_application_projection_syncs
Revises: 0007_celery_task_tracking
Create Date: 2026-05-06 15:30:00.000000
"""

from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0008_application_projection_syncs"
down_revision: str | None = "0007_celery_task_tracking"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_type() -> sa.types.TypeEngine:
    """Return a JSON type compatible with both PostgreSQL and SQLite."""
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _is_sqlite() -> bool:
    """Return whether the migration is running against SQLite."""
    return op.get_context().dialect.name == "sqlite"


def _normalize_optional(value: str | None, transform) -> str | None:
    """Normalize optional string values while preserving nullability."""
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return transform(normalized)


def _normalize_application(value: str | None) -> str | None:
    """Return the canonical application code."""
    return _normalize_optional(value, str.upper)


def _normalize_dimension(value: str | None) -> str | None:
    """Return the canonical lowercase dimension value."""
    return _normalize_optional(value, str.lower)


def _coalesce_dimension(value: str | None) -> str:
    """Return a non-empty dimension value compatible with the applications table."""
    return _normalize_dimension(value) or "unknown"


def _machines_table() -> sa.Table:
    """Return a lightweight SQLAlchemy table for machine migration updates."""
    return sa.table(
        "machines",
        sa.column("id", sa.Integer()),
        sa.column("application", sa.String(length=255)),
        sa.column("environment", sa.String(length=128)),
        sa.column("region", sa.String(length=128)),
    )


def _applications_table() -> sa.Table:
    """Return a lightweight SQLAlchemy table for application migration updates."""
    return sa.table(
        "applications",
        sa.column("id", sa.Integer()),
        sa.column("name", sa.String(length=255)),
        sa.column("environment", sa.String(length=128)),
        sa.column("region", sa.String(length=128)),
        sa.column("sync_at", sa.DateTime(timezone=True)),
        sa.column("sync_scheduled_at", sa.DateTime(timezone=True)),
        sa.column("sync_error", sa.Text()),
        sa.column("extra", _json_type()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )


def _snapshot_from_machines(connection) -> set[tuple[str, str, str]]:
    """Return the normalized distinct application keys derived from machines."""
    rows = connection.execute(
        sa.text(
            """
            SELECT DISTINCT application, environment, region
            FROM machines
            WHERE application IS NOT NULL AND TRIM(application) <> ''
            """
        )
    ).mappings()
    return {
        (
            _normalize_application(row["application"]),
            _coalesce_dimension(row["environment"]),
            _coalesce_dimension(row["region"]),
        )
        for row in rows
        if _normalize_application(row["application"]) is not None
    }


def upgrade() -> None:
    """Convert applications into a machine-derived projection."""
    machines = _machines_table()
    applications = _applications_table()
    connection = op.get_bind()

    if _is_sqlite():
        with op.batch_alter_table("machines") as batch_op:
            batch_op.add_column(sa.Column("application", sa.String(length=255), nullable=True))
    else:
        op.add_column("machines", sa.Column("application", sa.String(length=255), nullable=True))

    if _is_sqlite():
        connection.execute(
            sa.text(
                """
                UPDATE machines
                SET application = (
                    SELECT applications.name
                    FROM applications
                    WHERE applications.id = machines.application_id
                )
                WHERE application_id IS NOT NULL
                """
            )
        )
    else:
        connection.execute(
            sa.text(
                """
                UPDATE machines
                SET application = applications.name
                FROM applications
                WHERE machines.application_id = applications.id
                """
            )
        )

    for row in connection.execute(sa.select(machines.c.id, machines.c.application, machines.c.environment, machines.c.region)).mappings():
        connection.execute(
            sa.update(machines)
            .where(machines.c.id == row["id"])
            .values(
                application=_normalize_application(row["application"]),
                environment=_normalize_dimension(row["environment"]),
                region=_normalize_dimension(row["region"]),
            )
        )

    if _is_sqlite():
        with op.batch_alter_table("machines") as batch_op:
            batch_op.drop_constraint("fk_machines_application_id_applications", type_="foreignkey")
            batch_op.drop_index("ix_machines_application_id")
            batch_op.drop_column("application_id")
            batch_op.create_index("ix_machines_application", ["application"], unique=False)
    else:
        op.drop_constraint("fk_machines_application_id_applications", "machines", type_="foreignkey")
        op.drop_index("ix_machines_application_id", table_name="machines")
        op.drop_column("machines", "application_id")
        op.create_index("ix_machines_application", "machines", ["application"], unique=False)

    existing_rows = list(
        connection.execute(
            sa.select(
                applications.c.id,
                applications.c.name,
                applications.c.environment,
                applications.c.region,
            )
        ).mappings()
    )

    keepers: dict[tuple[str, str, str], int] = {}
    duplicates: list[int] = []
    normalized_updates: list[dict[str, object]] = []
    for row in existing_rows:
        key = (
            _normalize_application(row["name"]),
            _coalesce_dimension(row["environment"]),
            _coalesce_dimension(row["region"]),
        )
        if key in keepers:
            duplicates.append(row["id"])
            continue
        keepers[key] = row["id"]
        normalized_updates.append(
            {
                "id": row["id"],
                "name": key[0],
                "environment": key[1],
                "region": key[2],
            }
        )

    if duplicates:
        connection.execute(sa.delete(applications).where(applications.c.id.in_(duplicates)))

    for update in normalized_updates:
        connection.execute(
            sa.update(applications)
            .where(applications.c.id == update["id"])
            .values(
                name=update["name"],
                environment=update["environment"],
                region=update["region"],
            )
        )

    snapshot = _snapshot_from_machines(connection)
    current_rows = list(
        connection.execute(
            sa.select(
                applications.c.id,
                applications.c.name,
                applications.c.environment,
                applications.c.region,
            )
        ).mappings()
    )
    current_by_key = {
        (row["name"], row["environment"], row["region"]): row["id"]
        for row in current_rows
    }

    orphan_ids = [row_id for key, row_id in current_by_key.items() if key not in snapshot]
    if orphan_ids:
        connection.execute(sa.delete(applications).where(applications.c.id.in_(orphan_ids)))

    missing_rows = [key for key in sorted(snapshot) if key not in current_by_key]
    if missing_rows:
        now = datetime.now(timezone.utc)
        connection.execute(
            sa.insert(applications),
            [
                {
                    "name": name,
                    "environment": environment,
                    "region": region,
                    "sync_at": None,
                    "sync_scheduled_at": None,
                    "sync_error": None,
                    "extra": {},
                    "created_at": now,
                    "updated_at": now,
                }
                for name, environment, region in missing_rows
            ],
        )


def downgrade() -> None:
    """Recreate the machine/application foreign key shape."""
    machines = sa.table(
        "machines",
        sa.column("id", sa.Integer()),
        sa.column("application", sa.String(length=255)),
        sa.column("environment", sa.String(length=128)),
        sa.column("region", sa.String(length=128)),
        sa.column("application_id", sa.Integer()),
    )
    applications = _applications_table()
    connection = op.get_bind()

    if _is_sqlite():
        with op.batch_alter_table("machines") as batch_op:
            batch_op.add_column(sa.Column("application_id", sa.Integer(), nullable=True))
    else:
        op.add_column("machines", sa.Column("application_id", sa.Integer(), nullable=True))

    application_rows = list(
        connection.execute(
            sa.select(applications.c.id, applications.c.name, applications.c.environment, applications.c.region)
        ).mappings()
    )
    application_ids = {
        (row["name"], row["environment"], row["region"]): row["id"]
        for row in application_rows
    }

    for row in connection.execute(
        sa.select(machines.c.id, machines.c.application, machines.c.environment, machines.c.region)
    ).mappings():
        key = (
            _normalize_application(row["application"]),
            _coalesce_dimension(row["environment"]),
            _coalesce_dimension(row["region"]),
        )
        connection.execute(
            sa.update(machines)
            .where(machines.c.id == row["id"])
            .values(application_id=application_ids.get(key))
        )

    if _is_sqlite():
        with op.batch_alter_table("machines") as batch_op:
            batch_op.drop_index("ix_machines_application")
            batch_op.create_index("ix_machines_application_id", ["application_id"], unique=False)
            batch_op.create_foreign_key(
                "fk_machines_application_id_applications",
                "applications",
                ["application_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch_op.drop_column("application")
    else:
        op.drop_index("ix_machines_application", table_name="machines")
        op.create_index("ix_machines_application_id", "machines", ["application_id"], unique=False)
        op.create_foreign_key(
            "fk_machines_application_id_applications",
            "machines",
            "applications",
            ["application_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.drop_column("machines", "application")
