"""Worker tasks for inventory jobs."""

from app.worker.tasks.inventory.run_provisioner import run_provisioner_task

__all__ = ["run_provisioner_task"]
