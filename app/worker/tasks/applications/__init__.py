"""Worker tasks for application jobs."""

from app.worker.tasks.applications.sync_application import sync_application_task

__all__ = ["sync_application_task"]
