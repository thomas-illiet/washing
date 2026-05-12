"""Worker task that recalculates one machine recommendation."""

from app.worker.tasks._db import run_with_db_session
from internal.infra.queue.celery import celery_app
from internal.infra.queue.task_names import RECALCULATE_MACHINE_RECOMMENDATIONS_TASK
from internal.usecases.recommendations import refresh_machine_recommendation


@celery_app.task(name=RECALCULATE_MACHINE_RECOMMENDATIONS_TASK)
def recalculate_machine_recommendations_task(machine_id: int) -> dict[str, int | str]:
    """Recalculate the stored recommendation for one machine."""
    def operation(db):
        result = refresh_machine_recommendation(db, machine_id)
        db.commit()
        return result

    return run_with_db_session(operation)
