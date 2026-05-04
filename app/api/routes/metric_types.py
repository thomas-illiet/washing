from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.routes.common import apply_patch, commit_or_409, get_or_404
from internal.contracts.http.resources import MetricTypeCreate, MetricTypeRead, MetricTypeUpdate
from internal.infra.db.models import MetricType


router = APIRouter(prefix="/metric-types", tags=["metric-types"])


@router.post("", response_model=MetricTypeRead, status_code=status.HTTP_201_CREATED)
def create_metric_type(payload: MetricTypeCreate, db: Session = Depends(get_db)) -> MetricType:
    metric_type = MetricType(**payload.model_dump())
    db.add(metric_type)
    commit_or_409(db, "metric type code already exists")
    db.refresh(metric_type)
    return metric_type


@router.get("", response_model=list[MetricTypeRead])
def list_metric_types(offset: int = 0, limit: int = 100, db: Session = Depends(get_db)) -> list[MetricType]:
    return db.query(MetricType).offset(offset).limit(limit).all()


@router.get("/{metric_type_id}", response_model=MetricTypeRead)
def get_metric_type(metric_type_id: int, db: Session = Depends(get_db)) -> MetricType:
    return get_or_404(db, MetricType, metric_type_id, "metric type not found")


@router.patch("/{metric_type_id}", response_model=MetricTypeRead)
def update_metric_type(metric_type_id: int, payload: MetricTypeUpdate, db: Session = Depends(get_db)) -> MetricType:
    metric_type = get_or_404(db, MetricType, metric_type_id, "metric type not found")
    apply_patch(metric_type, payload.model_dump(exclude_unset=True))
    commit_or_409(db, "metric type code already exists")
    db.refresh(metric_type)
    return metric_type


@router.delete("/{metric_type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_metric_type(metric_type_id: int, db: Session = Depends(get_db)) -> Response:
    metric_type = get_or_404(db, MetricType, metric_type_id, "metric type not found")
    db.delete(metric_type)
    commit_or_409(db, "metric type is still used by providers")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
