"""Application read and sync routes."""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import PaginationParams, get_db
from app.api.routes.common import get_or_404, paginate_query
from app.api.routes.machines.optimizations import serialize_machine_optimization
from internal.domain import normalize_application_code, normalize_dimension
from internal.contracts.http.resources import (
    ApplicationRead,
    ApplicationSyncType,
    MachineOptimizationRead,
    MachineRead,
    PaginatedResponse,
    TaskEnqueueResponse,
)
from internal.infra.db.models import Application, Machine, MachineOptimization
from internal.infra.queue.enqueue import enqueue_celery_task
from internal.infra.queue.task_names import (
    DISPATCH_DUE_APPLICATION_METRICS_SYNCS_TASK,
    SYNC_APPLICATION_INVENTORY_DISCOVERY_TASK,
    SYNC_APPLICATION_METRICS_TASK,
)


router = APIRouter(prefix="/applications", tags=["Applications"])


def _application_machine_query(db: Session, application: Application):
    """Build the current machine query matching one application projection row."""
    return (
        db.query(Machine)
        .filter(Machine.application == application.name)
        .filter(func.coalesce(Machine.environment, "UNKNOWN") == application.environment)
        .filter(func.coalesce(Machine.region, "UNKNOWN") == application.region)
    )


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


@router.get("/{application_id}/machines", response_model=PaginatedResponse[MachineRead])
def list_application_machines(
    application_id: int,
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_db),
) -> PaginatedResponse[MachineRead]:
    """List machines represented by one application projection row."""
    application = get_or_404(db, Application, application_id, "application not found")
    query = _application_machine_query(db, application)
    return paginate_query(query, MachineRead, pagination, Machine.hostname.asc(), Machine.id.asc())


@router.post("/{application_id}/metrics/sync", response_model=TaskEnqueueResponse, status_code=status.HTTP_202_ACCEPTED)
def enqueue_single_application_metrics_sync(
    application_id: int,
    db: Session = Depends(get_db),
) -> TaskEnqueueResponse:
    """Enqueue a metrics sync for one application projection row."""
    get_or_404(db, Application, application_id, "application not found")
    task = enqueue_celery_task(SYNC_APPLICATION_METRICS_TASK, args=[application_id])
    return TaskEnqueueResponse(task_id=task.id)


@router.get("/{application_id}/optimizations", response_model=PaginatedResponse[MachineOptimizationRead])
def list_application_optimizations(
    application_id: int,
    current_only: bool = True,
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_db),
) -> PaginatedResponse[MachineOptimizationRead]:
    """List optimization revisions for machines represented by one application row."""
    application = get_or_404(db, Application, application_id, "application not found")
    machine_query = _application_machine_query(db, application).with_entities(Machine.id)
    query = db.query(MachineOptimization).filter(MachineOptimization.machine_id.in_(machine_query))
    if current_only:
        query = query.filter(MachineOptimization.is_current.is_(True))
    return paginate_query(
        query,
        MachineOptimizationRead,
        pagination,
        MachineOptimization.computed_at.desc(),
        MachineOptimization.id.desc(),
        transform=serialize_machine_optimization,
    )
