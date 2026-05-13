"""Machine optimization routes."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import PaginationParams, get_db
from app.api.routes.common import get_or_404, paginate_query
from internal.contracts.http.resources import (
    MachineOptimizationAction,
    MachineOptimizationRead,
    MachineOptimizationStatus,
    PaginatedResponse,
    TaskEnqueueResponse,
)
from internal.domain import normalize_application_code, normalize_dimension
from internal.infra.db.base import utcnow
from internal.infra.db.models import Machine, MachineOptimization
from internal.infra.queue.enqueue import enqueue_celery_task
from internal.infra.queue.task_names import RECALCULATE_MACHINE_OPTIMIZATIONS_TASK


router = APIRouter(prefix="/machines", tags=["Machine Optimizations"])


def _authenticated_principal_name(request: Request) -> str | None:
    """Return the authenticated user name recorded by the OIDC middleware."""
    principal = getattr(request.state, "authenticated_principal", None)
    if principal is None:
        return None
    return principal.username or principal.subject


@router.get("/optimizations", response_model=PaginatedResponse[MachineOptimizationRead])
def list_machine_optimizations(
    current_only: bool = True,
    platform_id: int | None = None,
    machine_id: int | None = None,
    application: str | None = None,
    environment: str | None = None,
    region: str | None = None,
    status: MachineOptimizationStatus | None = None,
    action: MachineOptimizationAction | None = None,
    acknowledged: bool | None = None,
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_db),
) -> PaginatedResponse[MachineOptimizationRead]:
    """List machine optimizations with pagination and optional filters."""
    query = db.query(MachineOptimization)
    needs_machine_join = any(
        value is not None
        for value in (
            platform_id,
            application,
            environment,
            region,
        )
    )
    if needs_machine_join:
        query = query.join(Machine, MachineOptimization.machine_id == Machine.id)

    normalized_application = normalize_application_code(application)
    normalized_environment = normalize_dimension(environment)
    normalized_region = normalize_dimension(region)

    if current_only:
        query = query.filter(MachineOptimization.is_current.is_(True))
    if platform_id is not None:
        query = query.filter(Machine.platform_id == platform_id)
    if machine_id is not None:
        query = query.filter(MachineOptimization.machine_id == machine_id)
    if normalized_application is not None:
        query = query.filter(Machine.application == normalized_application)
    if normalized_environment is not None:
        query = query.filter(Machine.environment == normalized_environment)
    if normalized_region is not None:
        query = query.filter(Machine.region == normalized_region)
    if status is not None:
        query = query.filter(MachineOptimization.status == status)
    if action is not None:
        query = query.filter(MachineOptimization.action == action)
    if acknowledged is not None:
        if acknowledged:
            query = query.filter(MachineOptimization.acknowledged_at.is_not(None))
        else:
            query = query.filter(MachineOptimization.acknowledged_at.is_(None))

    return paginate_query(
        query,
        MachineOptimizationRead,
        pagination,
        MachineOptimization.computed_at.desc(),
        MachineOptimization.id.desc(),
    )


@router.post("/optimizations/{optimization_id:int}/acknowledge", response_model=MachineOptimizationRead)
def acknowledge_machine_optimization(
    optimization_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> MachineOptimizationRead:
    """Mark one optimization revision as acknowledged."""
    optimization = get_or_404(db, MachineOptimization, optimization_id, "optimization not found")
    if optimization.acknowledged_at is None:
        optimization.acknowledged_at = utcnow()
        optimization.acknowledged_by = _authenticated_principal_name(request)
        db.commit()
        db.refresh(optimization)
    return MachineOptimizationRead.model_validate(optimization)


@router.get("/{machine_id:int}/optimizations", response_model=MachineOptimizationRead)
def get_machine_optimization(
    machine_id: int,
    db: Session = Depends(get_db),
) -> MachineOptimizationRead:
    """Return the current optimization for one machine."""
    get_or_404(db, Machine, machine_id, "machine not found")
    optimization = (
        db.query(MachineOptimization)
        .filter(MachineOptimization.machine_id == machine_id)
        .filter(MachineOptimization.is_current.is_(True))
        .one_or_none()
    )
    if optimization is None:
        raise HTTPException(status_code=404, detail="optimization not computed yet")
    return MachineOptimizationRead.model_validate(optimization)


@router.get("/{machine_id:int}/optimizations/history", response_model=PaginatedResponse[MachineOptimizationRead])
def list_machine_optimization_history(
    machine_id: int,
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_db),
) -> PaginatedResponse[MachineOptimizationRead]:
    """List all optimization revisions for one machine."""
    get_or_404(db, Machine, machine_id, "machine not found")
    query = db.query(MachineOptimization).filter(MachineOptimization.machine_id == machine_id)
    return paginate_query(
        query,
        MachineOptimizationRead,
        pagination,
        MachineOptimization.revision.desc(),
        MachineOptimization.id.desc(),
    )


@router.post(
    "/{machine_id:int}/optimizations/recalculate",
    response_model=TaskEnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def recalculate_machine_optimization(
    machine_id: int,
    db: Session = Depends(get_db),
) -> TaskEnqueueResponse:
    """Enqueue a manual optimization recalculation for one machine."""
    get_or_404(db, Machine, machine_id, "machine not found")
    task = enqueue_celery_task(RECALCULATE_MACHINE_OPTIMIZATIONS_TASK, args=[machine_id])
    return TaskEnqueueResponse(task_id=task.id)
