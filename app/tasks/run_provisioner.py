from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.services.inventory import run_provisioner_inventory


@celery_app.task(name="provisioners.run")
def run_provisioner_task(provisioner_id: int) -> dict[str, int]:
    db = SessionLocal()
    try:
        return run_provisioner_inventory(db, provisioner_id)
    finally:
        db.close()
