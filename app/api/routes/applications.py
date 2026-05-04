from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.routes.common import apply_patch, commit_or_409, get_or_404
from app.core.config import get_settings
from app.db.models import Application
from app.schemas.resources import ApplicationCreate, ApplicationRead, ApplicationUpdate, TaskEnqueueResponse
from app.services.applications import dispatch_due_application_syncs
from app.tasks.sync_application import sync_application_task


router = APIRouter(prefix="/applications", tags=["applications"])


@router.post("", response_model=ApplicationRead, status_code=status.HTTP_201_CREATED)
def create_application(payload: ApplicationCreate, db: Session = Depends(get_db)) -> Application:
    application = Application(**payload.model_dump())
    db.add(application)
    commit_or_409(db, "application already exists for this environment and region")
    db.refresh(application)
    return application


@router.get("", response_model=list[ApplicationRead])
def list_applications(
    name: str | None = None,
    environment: str | None = None,
    region: str | None = None,
    offset: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[Application]:
    query = db.query(Application)
    if name is not None:
        query = query.filter(Application.name == name)
    if environment is not None:
        query = query.filter(Application.environment == environment)
    if region is not None:
        query = query.filter(Application.region == region)
    return query.order_by(Application.name, Application.environment, Application.region).offset(offset).limit(limit).all()


@router.post("/sync-due")
def enqueue_due_application_syncs(db: Session = Depends(get_db)) -> dict[str, list[int] | int]:
    settings = get_settings()
    return dispatch_due_application_syncs(
        db,
        enqueue_application=lambda application_id: sync_application_task.delay(application_id).id,
        window_days=settings.application_sync_window_days,
        tick_seconds=settings.application_sync_tick_seconds,
        configured_batch_size=settings.application_sync_batch_size,
        retry_after_seconds=settings.application_sync_retry_after_seconds,
    )


@router.get("/{application_id}", response_model=ApplicationRead)
def get_application(application_id: int, db: Session = Depends(get_db)) -> Application:
    return get_or_404(db, Application, application_id, "application not found")


@router.patch("/{application_id}", response_model=ApplicationRead)
def update_application(
    application_id: int,
    payload: ApplicationUpdate,
    db: Session = Depends(get_db),
) -> Application:
    application = get_or_404(db, Application, application_id, "application not found")
    apply_patch(application, payload.model_dump(exclude_unset=True))
    commit_or_409(db, "application already exists for this environment and region")
    db.refresh(application)
    return application


@router.delete("/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_application(application_id: int, db: Session = Depends(get_db)) -> Response:
    application = get_or_404(db, Application, application_id, "application not found")
    db.delete(application)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{application_id}/sync", response_model=TaskEnqueueResponse, status_code=status.HTTP_202_ACCEPTED)
def enqueue_application_sync(application_id: int, db: Session = Depends(get_db)) -> TaskEnqueueResponse:
    get_or_404(db, Application, application_id, "application not found")
    task = sync_application_task.delay(application_id)
    return TaskEnqueueResponse(task_id=task.id)
