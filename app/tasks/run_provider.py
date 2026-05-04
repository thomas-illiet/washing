from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.services.metrics import run_provider_collection


@celery_app.task(name="providers.run")
def run_provider_task(provider_id: int) -> dict[str, int]:
    db = SessionLocal()
    try:
        return run_provider_collection(db, provider_id)
    finally:
        db.close()
