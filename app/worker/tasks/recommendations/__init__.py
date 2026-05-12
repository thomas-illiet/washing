"""Worker tasks for machine recommendations."""

from app.worker.tasks.recommendations.recalculate import recalculate_machine_recommendations_task

__all__ = ["recalculate_machine_recommendations_task"]
