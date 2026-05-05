"""Read-only metric browsing routes."""

from datetime import date
from typing import Type

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from internal.contracts.http.resources import MetricRead
from internal.infra.db.models import (
    MachineCPUMetric,
    MachineDiskMetric,
    MachineProvider,
    MachineProviderProvisioner,
    MachineRAMMetric,
)


router = APIRouter(prefix="/metrics", tags=["metrics"])


METRIC_ROUTE_MODELS = {
    "cpu": MachineCPUMetric,
    "ram": MachineRAMMetric,
    "disk": MachineDiskMetric,
}


def _list_metrics(
    metric_name: str,
    platform_id: int | None,
    provider_id: int | None,
    provisioner_id: int | None,
    machine_id: int | None,
    start: date | None,
    end: date | None,
    offset: int,
    limit: int,
    db: Session,
) -> list:
    """Run a metric query for one metric family with shared filters."""
    model: Type = METRIC_ROUTE_MODELS[metric_name]
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
        query = query.filter(model.metric_date >= start)
    if end is not None:
        query = query.filter(model.metric_date <= end)

    return query.order_by(model.metric_date.desc(), model.collected_at.desc()).offset(offset).limit(limit).all()


@router.get("/{metric_name}", response_model=list[MetricRead])
def list_metrics(
    metric_name: str,
    platform_id: int | None = None,
    provider_id: int | None = None,
    provisioner_id: int | None = None,
    machine_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
    offset: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list:
    """List stored metric samples for one metric family."""
    if metric_name not in METRIC_ROUTE_MODELS:
        raise HTTPException(status_code=404, detail="metric route not found")
    return _list_metrics(metric_name, platform_id, provider_id, provisioner_id, machine_id, start, end, offset, limit, db)
