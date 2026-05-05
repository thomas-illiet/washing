"""Machine metric routes."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import PaginationParams, get_db
from app.api.routes.common import get_or_404, paginate_query
from internal.contracts.http.resources import MachineMetricRead, PaginatedResponse, Scope
from internal.infra.db.models import (
    Machine,
    MachineCPUMetric,
    MachineDiskMetric,
    MachineProvider,
    MachineProviderProvisioner,
    MachineRAMMetric,
)


router = APIRouter(prefix="/machines", tags=["machine-metrics"])

METRIC_MODELS = {
    "cpu": MachineCPUMetric,
    "ram": MachineRAMMetric,
    "disk": MachineDiskMetric,
}


def _metric_query(
    scope: Scope,
    db: Session,
    platform_id: int | None = None,
    provider_id: int | None = None,
    provisioner_id: int | None = None,
    machine_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
):
    """Build the shared machine metric query for one scope."""
    model = METRIC_MODELS[scope]
    query = db.query(model).join(MachineProvider, model.provider_id == MachineProvider.id)

    if platform_id is not None:
        query = query.filter(MachineProvider.platform_id == platform_id)
    if provider_id is not None:
        query = query.filter(model.provider_id == provider_id)
    if provisioner_id is not None:
        query = query.join(MachineProviderProvisioner, MachineProviderProvisioner.provider_id == model.provider_id)
        query = query.filter(MachineProviderProvisioner.provisioner_id == provisioner_id)
    if machine_id is not None:
        query = query.filter(model.machine_id == machine_id)
    if start is not None:
        query = query.filter(model.date >= start)
    if end is not None:
        query = query.filter(model.date <= end)

    return model, query


@router.get("/metrics", response_model=PaginatedResponse[MachineMetricRead])
def list_machine_metrics(
    metric_type: Scope = Query(alias="type"),
    platform_id: int | None = None,
    provider_id: int | None = None,
    provisioner_id: int | None = None,
    machine_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_db),
) -> PaginatedResponse[MachineMetricRead]:
    """List paginated metrics for one metric type across machines."""
    model, query = _metric_query(metric_type, db, platform_id, provider_id, provisioner_id, machine_id, start, end)
    return paginate_query(query, MachineMetricRead, pagination, model.date.desc(), model.id.desc())


@router.get("/{machine_id:int}/metrics", response_model=PaginatedResponse[MachineMetricRead])
def list_machine_metric_history(
    machine_id: int,
    metric_type: Scope = Query(alias="type"),
    provider_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_db),
) -> PaginatedResponse[MachineMetricRead]:
    """List paginated metrics for one machine and metric type."""
    get_or_404(db, Machine, machine_id, "machine not found")
    model, query = _metric_query(metric_type, db, provider_id=provider_id, machine_id=machine_id, start=start, end=end)
    return paginate_query(query, MachineMetricRead, pagination, model.date.desc(), model.id.desc())
