"""Machine optimization routes."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import PaginationParams, get_db
from app.api.routes.common import get_or_404, paginate_query
from internal.contracts.http.resources import (
    MachineOptimizationAction,
    MachineOptimizationRead,
    MachineOptimizationResourceRead,
    MachineOptimizationStatus,
    PaginatedResponse,
    Scope,
    TaskEnqueueResponse,
)
from internal.domain import normalize_application_code, normalize_dimension
from internal.infra.db.models import Machine, MachineOptimization
from internal.infra.queue.enqueue import enqueue_celery_task
from internal.infra.queue.task_names import RECALCULATE_MACHINE_OPTIMIZATIONS_TASK


router = APIRouter(prefix="/machines", tags=["Machine Optimizations"])

RESOURCE_UNITS: dict[Scope, str] = {
    "cpu": "cores",
    "ram": "mb",
    "disk": "mb",
}

RESOURCE_CURRENT_FIELDS: dict[Scope, str] = {
    "cpu": "current_cpu",
    "ram": "current_ram_mb",
    "disk": "current_disk_mb",
}

RESOURCE_TARGET_FIELDS: dict[Scope, str] = {
    "cpu": "target_cpu",
    "ram": "target_ram_mb",
    "disk": "target_disk_mb",
}


def _optimization_resource_summary(optimization: MachineOptimization, scope: Scope) -> MachineOptimizationResourceRead:
    """Build the public summary for one optimized resource."""
    details = optimization.details.get(scope, {})
    return MachineOptimizationResourceRead(
        status=details.get("status", "insufficient_data"),
        action=details.get("action", "insufficient_data"),
        current=getattr(optimization, RESOURCE_CURRENT_FIELDS[scope]),
        recommended=getattr(optimization, RESOURCE_TARGET_FIELDS[scope]),
        unit=RESOURCE_UNITS[scope],
        utilization_percent=details.get("utilization_percent"),
        reason=details.get("reason_code", "unavailable"),
    )


def serialize_machine_optimization(optimization: MachineOptimization) -> MachineOptimizationRead:
    """Build the simplified public optimization response."""
    return MachineOptimizationRead(
        id=optimization.id,
        machine_id=optimization.machine_id,
        status=optimization.status,
        action=optimization.action,
        computed_at=optimization.computed_at,
        resources={
            "cpu": _optimization_resource_summary(optimization, "cpu"),
            "ram": _optimization_resource_summary(optimization, "ram"),
            "disk": _optimization_resource_summary(optimization, "disk"),
        },
        created_at=optimization.created_at,
        updated_at=optimization.updated_at,
    )


@router.get("/optimizations", response_model=PaginatedResponse[MachineOptimizationRead])
def list_machine_optimizations(
    platform_id: int | None = None,
    machine_id: int | None = None,
    application: str | None = None,
    environment: str | None = None,
    region: str | None = None,
    status: MachineOptimizationStatus | None = None,
    action: MachineOptimizationAction | None = None,
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

    return paginate_query(
        query,
        MachineOptimizationRead,
        pagination,
        MachineOptimization.computed_at.desc(),
        MachineOptimization.id.desc(),
        transform=serialize_machine_optimization,
    )


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
        .one_or_none()
    )
    if optimization is None:
        raise HTTPException(status_code=404, detail="optimization not computed yet")
    return serialize_machine_optimization(optimization)


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
