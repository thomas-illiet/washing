"""Application read and sync routes."""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import PaginationParams, get_db
from app.api.routes.common import get_or_404, paginate_query
from internal.domain import normalize_application_code, normalize_dimension
from internal.contracts.http.resources import (
    ApplicationRead,
    ApplicationSyncType,
    PaginatedResponse,
    TaskEnqueueResponse,
)
from internal.infra.db.models import Application
from internal.infra.queue.enqueue import enqueue_celery_task
from internal.infra.queue.task_names import (
    DISPATCH_DUE_APPLICATION_METRICS_SYNCS_TASK,
    SYNC_APPLICATION_INVENTORY_DISCOVERY_TASK,
)


router = APIRouter(prefix="/applications", tags=["Applications"])


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
    normalized_name = normalize_application_code(name)
    normalized_environment = normalize_dimension(environment)
    normalized_region = normalize_dimension(region)
    if normalized_name is not None:
        query = query.filter(Application.name == normalized_name)
    if normalized_environment is not None:
        query = query.filter(Application.environment == normalized_environment)
    if normalized_region is not None:
        query = query.filter(Application.region == normalized_region)
    return paginate_query(
        query,
        ApplicationRead,
        pagination,
        Application.name.asc(),
        Application.environment.asc(),
        Application.region.asc(),
        Application.id.asc(),
    )


@router.post(
    "/sync",
    response_model=TaskEnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_application_sync(
    sync_type: ApplicationSyncType = Query(alias="type"),
) -> TaskEnqueueResponse:
    """Enqueue one application sync pipeline."""
    task_name = (
        SYNC_APPLICATION_INVENTORY_DISCOVERY_TASK
        if sync_type == "inventory_discovery"
        else DISPATCH_DUE_APPLICATION_METRICS_SYNCS_TASK
    )
    task = enqueue_celery_task(task_name)
    return TaskEnqueueResponse(task_id=task.id)


@router.get("/{application_id}", response_model=ApplicationRead)
def get_application(application_id: int, db: Session = Depends(get_db)) -> Application:
    """Return one application by id."""
    return get_or_404(db, Application, application_id, "application not found")
