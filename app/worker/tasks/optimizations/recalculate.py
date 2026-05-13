"""Worker task that recalculates one machine optimization."""

from app.worker.tasks._db import run_with_db_session
from internal.infra.queue.celery import celery_app
from internal.infra.queue.task_names import RECALCULATE_MACHINE_OPTIMIZATIONS_TASK
from internal.usecases.optimizations import refresh_machine_optimization


@celery_app.task(name=RECALCULATE_MACHINE_OPTIMIZATIONS_TASK)
def recalculate_machine_optimizations_task(machine_id: int) -> dict[str, int | str]:
    """Recalculate the stored optimization for one machine."""
    def operation(db):
        result = refresh_machine_optimization(db, machine_id)
        db.commit()
        return result

    return run_with_db_session(operation)
