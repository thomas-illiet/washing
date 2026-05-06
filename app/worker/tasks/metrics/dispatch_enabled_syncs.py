"""Worker task that dispatches enabled metric provider syncs."""

from internal.infra.queue.celery import celery_app
from internal.infra.queue.enqueue import enqueue_celery_task
from internal.infra.queue.task_names import DISPATCH_ENABLED_PROVIDER_SYNCS_TASK, RUN_PROVIDER_TASK
from internal.usecases.metrics import dispatch_enabled_provider_syncs

from app.worker.tasks._db import run_with_db_session


@celery_app.task(name=DISPATCH_ENABLED_PROVIDER_SYNCS_TASK)
def dispatch_enabled_provider_syncs_task() -> dict[str, list[int]]:
    """Enqueue one provider dispatcher task per enabled provider."""
    return run_with_db_session(
        lambda db: dispatch_enabled_provider_syncs(
            db,
            enqueue_provider=lambda provider_id: enqueue_celery_task(
                RUN_PROVIDER_TASK,
                args=[provider_id],
            ).id,
        )
    )
