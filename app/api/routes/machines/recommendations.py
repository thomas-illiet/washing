"""Machine recommendation routes."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import PaginationParams, get_db
from app.api.routes.common import get_or_404, paginate_query
from internal.contracts.http.resources import (
    MachineRecommendationAction,
    MachineRecommendationRead,
    MachineRecommendationStatus,
    PaginatedResponse,
    TaskEnqueueResponse,
)
from internal.domain import normalize_application_code, normalize_dimension
from internal.infra.db.base import utcnow
from internal.infra.db.models import Machine, MachineRecommendation
from internal.infra.queue.enqueue import enqueue_celery_task
from internal.infra.queue.task_names import RECALCULATE_MACHINE_RECOMMENDATIONS_TASK


router = APIRouter(prefix="/machines", tags=["Machine Recommendations"])


def _authenticated_principal_name(request: Request) -> str | None:
    """Return the authenticated user name recorded by the OIDC middleware."""
    principal = getattr(request.state, "authenticated_principal", None)
    if principal is None:
        return None
    return principal.username or principal.subject


@router.get("/recommendations", response_model=PaginatedResponse[MachineRecommendationRead])
def list_machine_recommendations(
    current_only: bool = True,
    platform_id: int | None = None,
    machine_id: int | None = None,
    application: str | None = None,
    environment: str | None = None,
    region: str | None = None,
    status: MachineRecommendationStatus | None = None,
    action: MachineRecommendationAction | None = None,
    acknowledged: bool | None = None,
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_db),
) -> PaginatedResponse[MachineRecommendationRead]:
    """List machine recommendations with pagination and optional filters."""
    query = db.query(MachineRecommendation)
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
        query = query.join(Machine, MachineRecommendation.machine_id == Machine.id)

    normalized_application = normalize_application_code(application)
    normalized_environment = normalize_dimension(environment)
    normalized_region = normalize_dimension(region)

    if current_only:
        query = query.filter(MachineRecommendation.is_current.is_(True))
    if platform_id is not None:
        query = query.filter(Machine.platform_id == platform_id)
    if machine_id is not None:
        query = query.filter(MachineRecommendation.machine_id == machine_id)
    if normalized_application is not None:
        query = query.filter(Machine.application == normalized_application)
    if normalized_environment is not None:
        query = query.filter(Machine.environment == normalized_environment)
    if normalized_region is not None:
        query = query.filter(Machine.region == normalized_region)
    if status is not None:
        query = query.filter(MachineRecommendation.status == status)
    if action is not None:
        query = query.filter(MachineRecommendation.action == action)
    if acknowledged is not None:
        if acknowledged:
            query = query.filter(MachineRecommendation.acknowledged_at.is_not(None))
        else:
            query = query.filter(MachineRecommendation.acknowledged_at.is_(None))

    return paginate_query(
        query,
        MachineRecommendationRead,
        pagination,
        MachineRecommendation.computed_at.desc(),
        MachineRecommendation.id.desc(),
    )


@router.post("/recommendations/{recommendation_id:int}/acknowledge", response_model=MachineRecommendationRead)
def acknowledge_machine_recommendation(
    recommendation_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> MachineRecommendationRead:
    """Mark one recommendation revision as acknowledged."""
    recommendation = get_or_404(db, MachineRecommendation, recommendation_id, "recommendation not found")
    if recommendation.acknowledged_at is None:
        recommendation.acknowledged_at = utcnow()
        recommendation.acknowledged_by = _authenticated_principal_name(request)
        db.commit()
        db.refresh(recommendation)
    return MachineRecommendationRead.model_validate(recommendation)


@router.get("/{machine_id:int}/recommendations", response_model=MachineRecommendationRead)
def get_machine_recommendation(
    machine_id: int,
    db: Session = Depends(get_db),
) -> MachineRecommendationRead:
    """Return the current recommendation for one machine."""
    get_or_404(db, Machine, machine_id, "machine not found")
    recommendation = (
        db.query(MachineRecommendation)
        .filter(MachineRecommendation.machine_id == machine_id)
        .filter(MachineRecommendation.is_current.is_(True))
        .one_or_none()
    )
    if recommendation is None:
        raise HTTPException(status_code=404, detail="recommendation not computed yet")
    return MachineRecommendationRead.model_validate(recommendation)


@router.get("/{machine_id:int}/recommendations/history", response_model=PaginatedResponse[MachineRecommendationRead])
def list_machine_recommendation_history(
    machine_id: int,
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_db),
) -> PaginatedResponse[MachineRecommendationRead]:
    """List all recommendation revisions for one machine."""
    get_or_404(db, Machine, machine_id, "machine not found")
    query = db.query(MachineRecommendation).filter(MachineRecommendation.machine_id == machine_id)
    return paginate_query(
        query,
        MachineRecommendationRead,
        pagination,
        MachineRecommendation.revision.desc(),
        MachineRecommendation.id.desc(),
    )


@router.post(
    "/{machine_id:int}/recommendations/recalculate",
    response_model=TaskEnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def recalculate_machine_recommendation(
    machine_id: int,
    db: Session = Depends(get_db),
) -> TaskEnqueueResponse:
    """Enqueue a manual recommendation recalculation for one machine."""
    get_or_404(db, Machine, machine_id, "machine not found")
    task = enqueue_celery_task(RECALCULATE_MACHINE_RECOMMENDATIONS_TASK, args=[machine_id])
    return TaskEnqueueResponse(task_id=task.id)
