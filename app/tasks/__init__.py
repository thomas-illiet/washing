"""Celery task package.

Each task lives in its own module. Importing this package registers every task
with the shared Celery application.
"""

from app.tasks.run_provider import run_provider_task
from app.tasks.run_provisioner import run_provisioner_task
from app.tasks.sync_application import sync_application_task
from app.tasks.dispatch_due_jobs import dispatch_due_jobs_task
from app.tasks.dispatch_due_application_syncs import dispatch_due_application_syncs_task

__all__ = [
    "dispatch_due_application_syncs_task",
    "dispatch_due_jobs_task",
    "run_provider_task",
    "run_provisioner_task",
    "sync_application_task",
]
