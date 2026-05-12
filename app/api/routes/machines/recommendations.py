"""Machine recommendation routes."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import PaginationParams, get_db
from app.api.routes.common import get_or_404, paginate_query
from internal.contracts.http.resources import MachineRecommendationRead, PaginatedResponse, TaskEnqueueResponse
from internal.infra.db.models import Machine, MachineRecommendation
from internal.infra.queue.enqueue import enqueue_celery_task
from internal.infra.queue.task_names import RECALCULATE_MACHINE_RECOMMENDATIONS_TASK


router = APIRouter(prefix="/machines", tags=["Machines"])


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
