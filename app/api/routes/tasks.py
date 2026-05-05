"""Task execution history routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import PaginationParams, get_db
from app.api.routes.common import paginate_query
from internal.contracts.http.resources import PaginatedResponse, TaskExecutionRead, TaskExecutionStatus
from internal.infra.db.models import CeleryTaskExecution


router = APIRouter(prefix="/worker/tasks", tags=["tasks"])


@router.get("", response_model=PaginatedResponse[TaskExecutionRead])
def list_task_executions(
    task_name: str | None = None,
    status: TaskExecutionStatus | None = None,
    resource_type: str | None = None,
    resource_id: int | None = None,
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_db),
) -> PaginatedResponse[TaskExecutionRead]:
    """List tracked Celery task executions with pagination and filters."""
    query = db.query(CeleryTaskExecution)
    if task_name is not None:
        query = query.filter(CeleryTaskExecution.task_name == task_name)
    if status is not None:
        query = query.filter(CeleryTaskExecution.status == status)
    if resource_type is not None:
        query = query.filter(CeleryTaskExecution.resource_type == resource_type)
    if resource_id is not None:
        query = query.filter(CeleryTaskExecution.resource_id == resource_id)

    return paginate_query(
        query,
        TaskExecutionRead,
        pagination,
        CeleryTaskExecution.queued_at.desc(),
        CeleryTaskExecution.id.desc(),
    )
