"""Database startup readiness checks."""

from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from internal.infra.config.settings import get_settings
from internal.infra.db.config import build_connect_args, uses_postgresql


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI_PATH = PROJECT_ROOT / "alembic.ini"
ALEMBIC_SCRIPT_PATH = PROJECT_ROOT / "alembic"


def _expected_migration_heads() -> tuple[str, ...]:
    """Return the Alembic head revisions defined by the checked-in migrations."""
    config = Config(str(ALEMBIC_INI_PATH))
    config.set_main_option("script_location", str(ALEMBIC_SCRIPT_PATH))
    return tuple(sorted(ScriptDirectory.from_config(config).get_heads()))


def ensure_database_schema_is_current() -> None:
    """Fail fast when the configured database schema is missing required migrations."""
    settings = get_settings()
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args=build_connect_args(settings.database_url, settings.database_schema),
    )

    try:
        with engine.connect() as connection:
            context_options: dict[str, str] = {}
            if uses_postgresql(settings.database_url):
                context_options["version_table_schema"] = settings.database_schema
            current_heads = tuple(
                sorted(MigrationContext.configure(connection, opts=context_options).get_current_heads())
            )
    finally:
        engine.dispose()

    if current_heads != _expected_migration_heads():
        raise RuntimeError(
            f"database schema '{settings.database_schema}' is not initialized or not up to date; "
            "run `alembic upgrade head` before starting the API"
        )
