"""Tests covering the Flower-specific Celery entrypoint."""

import json
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_flower_entrypoint_imports_without_application_settings(tmp_path: Path) -> None:
    """Flower should start from broker settings without loading worker-only modules."""
    script = """
import json
import sys

from app.flower.celery import celery_app

print(json.dumps({
    "broker_url": celery_app.conf.broker_url,
    "result_backend": celery_app.conf.result_backend,
    "loaded_application_settings": "internal.infra.config.settings" in sys.modules,
    "loaded_celery_prometheus": "internal.infra.observability.prometheus" in sys.modules,
    "loaded_task_tracking": "internal.infra.queue.task_tracking" in sys.modules,
    "loaded_worker_tasks": any(
        module_name == "app.worker.tasks" or module_name.startswith("app.worker.tasks.")
        for module_name in sys.modules
    ),
}))
"""
    env = os.environ.copy()
    env.pop("DATABASE_ENCRYPTION_KEY", None)
    env.update(
        {
            "CELERY_BROKER_URL": "memory://",
            "CELERY_RESULT_BACKEND": "cache+memory://",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(PROJECT_ROOT),
        }
    )

    process = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(process.stdout.strip().splitlines()[-1])

    assert data == {
        "broker_url": "memory://",
        "result_backend": "cache+memory://",
        "loaded_application_settings": False,
        "loaded_celery_prometheus": False,
        "loaded_task_tracking": False,
        "loaded_worker_tasks": False,
    }
