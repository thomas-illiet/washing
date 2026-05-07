"""Helpers for backend-specific database connection settings."""

from sqlalchemy.engine import make_url


def uses_postgresql(database_url: str) -> bool:
    """Return whether the configured database URL targets PostgreSQL."""
    return make_url(database_url).get_backend_name() == "postgresql"


def build_connect_args(database_url: str, schema: str) -> dict[str, str]:
    """Return SQLAlchemy connect args for the configured backend."""
    if not uses_postgresql(database_url):
        return {}
    return {"options": f"-csearch_path={schema}"}
