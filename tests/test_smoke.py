"""High-level smoke tests for startup and migrations."""

import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from internal.infra.config.settings import get_settings
from tests.constants import TEST_ENCRYPTION_KEY


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _clean_env(**overrides: str) -> dict[str, str]:
    """Build a subprocess environment with only the settings this project needs."""
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env["APP_NAME"] = "Metrics Collector"
    env["APP_ENV"] = "prod"
    env["OIDC_ENABLED"] = "false"
    env["DATABASE_ENCRYPTION_KEY"] = TEST_ENCRYPTION_KEY
    env.update(overrides)
    return env


def test_api_import_smoke_in_clean_subprocess() -> None:
    """A clean Python subprocess should be able to import the API entrypoint."""
    result = subprocess.run(
        [sys.executable, "-c", "from app.api.main import app; print(app.title)"],
        cwd=PROJECT_ROOT,
        env=_clean_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "Metrics Collector"


def test_mcp_import_smoke_in_clean_subprocess() -> None:
    """A clean Python subprocess should be able to import the MCP entrypoint."""

    result = subprocess.run(
        [sys.executable, "-c", "from app.mcp.main import app; print(app.title)"],
        cwd=PROJECT_ROOT,
        env=_clean_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "Metrics Collector MCP"


def test_alembic_upgrade_head_smoke_on_sqlite(tmp_path: Path) -> None:
    """Alembic should upgrade a fresh SQLite database all the way to head."""
    database_path = tmp_path / "smoke.db"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT,
        env=_clean_env(DATABASE_URL=f"sqlite:///{database_path}"),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert database_path.exists()


def test_clean_initial_migration_creates_current_schema_on_sqlite(tmp_path: Path) -> None:
    """The clean initial migration should create the current machine/application schema directly."""
    database_path = tmp_path / "reset-initial.db"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT,
        env=_clean_env(DATABASE_URL=f"sqlite:///{database_path}"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    connection = sqlite3.connect(database_path)
    try:
        machine_columns = [row[1] for row in connection.execute("PRAGMA table_info(machines)")]
        provider_columns = [row[1] for row in connection.execute("PRAGMA table_info(machine_providers)")]
        flavor_columns = [row[1] for row in connection.execute("PRAGMA table_info(machine_flavor_history)")]
        optimization_columns = [row[1] for row in connection.execute("PRAGMA table_info(machine_optimizations)")]

        assert "application" in machine_columns
        assert "application_id" not in machine_columns
        assert {"ram_mb", "disk_mb"} <= set(machine_columns)
        assert {column for column in machine_columns if column.startswith(("ram_", "disk_"))} == {"ram_mb", "disk_mb"}
        assert "scope" in provider_columns
        assert "metric_type_id" not in provider_columns
        assert {"cpu", "ram_mb", "disk_mb"} <= set(flavor_columns)
        assert not any(column.startswith(("previous_", "new_")) for column in flavor_columns)
        assert {
            "machine_id",
            "revision",
            "is_current",
            "acknowledged_at",
            "acknowledged_by",
            "window_size",
            "min_cpu",
            "max_cpu",
            "min_ram_mb",
            "max_ram_mb",
            "details",
        } <= set(optimization_columns)
        assert "current_machine_id" not in optimization_columns
        optimization_indexes = list(connection.execute("PRAGMA index_list(machine_optimizations)"))
        assert any(row[1] == "uq_machine_optimizations_current_machine" and row[2] and row[4] for row in optimization_indexes)
    finally:
        connection.close()


def test_api_startup_fails_fast_when_database_is_not_migrated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The API should fail at startup with an actionable migration error."""
    database_path = tmp_path / "startup-unmigrated.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("OIDC_ENABLED", "false")
    monkeypatch.setenv("DATABASE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    get_settings.cache_clear()

    try:
        with pytest.raises(RuntimeError, match=r"run `alembic upgrade head` before starting the API"):
            with TestClient(create_app()):
                pass
    finally:
        get_settings.cache_clear()


def test_beat_smoke_starts_without_local_schedule_persistence(tmp_path: Path) -> None:
    """Beat should start in a read-only working directory without writing schedule state."""
    readonly_dir = tmp_path / "readonly"
    readonly_dir.mkdir()
    readonly_dir.chmod(0o555)

    process = subprocess.Popen(
        [sys.executable, "-m", "celery", "-A", "app.beat.celery.celery_app", "beat", "--loglevel=INFO"],
        cwd=readonly_dir,
        env=_clean_env(
            DATABASE_URL="sqlite://",
            CELERY_BROKER_URL="memory://",
            CELERY_RESULT_BACKEND="cache+memory://",
            CELERY_PROMETHEUS_ENABLED="false",
            PYTHONDONTWRITEBYTECODE="1",
            PYTHONPATH=str(PROJECT_ROOT),
            HOME=str(readonly_dir),
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        time.sleep(3)
        if process.poll() is None:
            process.terminate()
        output, _ = process.communicate(timeout=10)
    finally:
        readonly_dir.chmod(0o755)

    assert "beat: Starting..." in output
    assert "Read-only file system" not in output
    assert "Traceback" not in output
