"""Shared pytest fixtures for API and database tests."""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from internal.infra.auth import clear_oidc_caches
from tests.constants import TEST_ENCRYPTION_KEY

os.environ.setdefault("DATABASE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
os.environ.setdefault("APP_ENV", "prod")
os.environ.setdefault("OIDC_ENABLED", "false")

from app.api.deps import get_db
from app.api.main import create_app
from internal.infra.config.settings import get_settings
from internal.infra.db.base import Base


@pytest.fixture()
def db_session() -> Session:
    """Provide an in-memory SQLite session."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        """Keep SQLite tests aligned with PostgreSQL foreign key behavior."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()

    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _build_client(db_session: Session) -> TestClient:
    """Build a TestClient wired to the fixture-backed in-memory database."""
    get_settings.cache_clear()
    clear_oidc_caches()
    app = create_app(validate_database_on_startup=False)

    def override_get_db():
        """Reuse the fixture-backed database session inside FastAPI dependencies."""
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


@pytest.fixture()
def client(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Provide a deterministic production-mode TestClient."""
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("OIDC_ENABLED", "false")
    test_client = _build_client(db_session)
    try:
        yield test_client
    finally:
        test_client.app.dependency_overrides.clear()
        get_settings.cache_clear()
        clear_oidc_caches()


@pytest.fixture()
def dev_client(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Provide a development-mode TestClient with dev-only routes enabled."""
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("OIDC_ENABLED", "false")
    test_client = _build_client(db_session)
    try:
        yield test_client
    finally:
        test_client.app.dependency_overrides.clear()
        get_settings.cache_clear()
        clear_oidc_caches()
