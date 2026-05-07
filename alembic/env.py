"""Alembic environment configuration."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

from internal.infra.config.settings import get_settings
from internal.infra.db import models  # noqa: F401
from internal.infra.db.base import Base
from internal.infra.db.config import build_connect_args, uses_postgresql

config = context.config
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(object_, name: str, type_: str, reflected: bool, compare_to) -> bool:
    """Keep Alembic's own version table out of autogenerate diffs."""
    if type_ == "table" and name == "alembic_version":
        return False
    return True


def run_migrations_offline() -> None:
    """Run migrations in offline mode without opening a DB connection."""
    url = config.get_main_option("sqlalchemy.url")
    version_table_schema = settings.database_schema if uses_postgresql(url) else None
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        version_table_schema=version_table_schema,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations with a live SQLAlchemy connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=build_connect_args(settings.database_url, settings.database_schema),
    )

    with connectable.connect() as connection:
        version_table_schema = None
        if uses_postgresql(settings.database_url):
            schema = connection.dialect.identifier_preparer.quote(settings.database_schema)
            connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
            connection.commit()
            version_table_schema = settings.database_schema

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            version_table_schema=version_table_schema,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
