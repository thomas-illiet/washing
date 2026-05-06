"""High-level smoke tests for startup and migrations."""

import os
import subprocess
import sys
import time
from pathlib import Path

from tests.constants import TEST_ENCRYPTION_KEY


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _clean_env(**overrides: str) -> dict[str, str]:
    """Build a subprocess environment with only the settings this project needs."""
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env["APP_NAME"] = "Metrics Collector"
    env["INTEGRATION_CONFIG_ENCRYPTION_KEY"] = TEST_ENCRYPTION_KEY
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
