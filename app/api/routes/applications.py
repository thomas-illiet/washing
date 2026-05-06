"""Application CRUD and sync routes."""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import PaginationParams, get_db
from app.api.routes.common import commit_or_409, get_or_404, paginate_query
from internal.contracts.http.resources import (
    ApplicationCreate,
    ApplicationRead,
    PaginatedResponse,
    TaskEnqueueResponse,
)
from internal.infra.db.models import Application
from internal.infra.queue.enqueue import enqueue_celery_task
from internal.infra.queue.task_names import DISPATCH_DUE_APPLICATION_SYNCS_TASK, SYNC_APPLICATION_TASK


router = APIRouter(prefix="/applications", tags=["Applications"])


@router.post("", response_model=ApplicationRead, status_code=status.HTTP_201_CREATED)
def create_application(payload: ApplicationCreate, db: Session = Depends(get_db)) -> Application:
    """Create an application row."""
    application = Application(**payload.model_dump())
    db.add(application)
    commit_or_409(db, "application already exists for this environment and region")
    db.refresh(application)
    return application


@router.get("", response_model=PaginatedResponse[ApplicationRead])
def list_applications(
    name: str | None = None,
    environment: str | None = None,
    region: str | None = None,
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_db),
) -> PaginatedResponse[ApplicationRead]:
    """List applications with optional identity filters."""
    query = db.query(Application)
    if name is not None:
        query = query.filter(Application.name == name)
    if environment is not None:
        query = query.filter(Application.environment == environment)
    if region is not None:
        query = query.filter(Application.region == region)
    return paginate_query(
        query,
        ApplicationRead,
        pagination,
        Application.name.asc(),
        Application.environment.asc(),
        Application.region.asc(),
        Application.id.asc(),
    )


@router.post("/sync-due", response_model=TaskEnqueueResponse, status_code=status.HTTP_202_ACCEPTED)
def enqueue_due_application_syncs() -> TaskEnqueueResponse:
    """Enqueue the dispatcher that schedules the next due application sync batch."""
    task = enqueue_celery_task(DISPATCH_DUE_APPLICATION_SYNCS_TASK)
    return TaskEnqueueResponse(task_id=task.id)


@router.get("/{application_id}", response_model=ApplicationRead)
def get_application(application_id: int, db: Session = Depends(get_db)) -> Application:
    """Return one application by id."""
    return get_or_404(db, Application, application_id, "application not found")


@router.delete("/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_application(application_id: int, db: Session = Depends(get_db)) -> Response:
    """Delete an application."""
    application = get_or_404(db, Application, application_id, "application not found")
    db.delete(application)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{application_id}/sync", response_model=TaskEnqueueResponse, status_code=status.HTTP_202_ACCEPTED)
def enqueue_application_sync(application_id: int, db: Session = Depends(get_db)) -> TaskEnqueueResponse:
    """Enqueue a manual sync for one application."""
    get_or_404(db, Application, application_id, "application not found")
    task = enqueue_celery_task(SYNC_APPLICATION_TASK, args=[application_id])
    return TaskEnqueueResponse(task_id=task.id)
