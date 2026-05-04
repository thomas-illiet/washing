from internal.infra.db.session import SessionLocal
from internal.infra.queue.celery import celery_app
from internal.infra.queue.task_names import RUN_PROVIDER_TASK
from internal.usecases.metrics import run_provider_collection


@celery_app.task(name=RUN_PROVIDER_TASK)
def run_provider_task(provider_id: int) -> dict[str, int]:
    db = SessionLocal()
    try:
        return run_provider_collection(db, provider_id)
    finally:
        db.close()
